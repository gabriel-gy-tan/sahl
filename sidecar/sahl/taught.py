"""What the person has told Sahl about boxes its guides don't know ("Company", "Fax"), remembered for next time.

A value belongs to a concept ("Company"), and any number of printed labels can mean that concept ("Workplace",
"Employer"). A label is the same concept when it reads alike (spelling, case, punctuation), or when the person agrees
to a suggestion from the local model; the model's guess is never used on its own. Values are the person's own words, so
they count as verified. Stored in the vault database, per person (0 = told before any document was added).
"""
import re
import threading

from rapidfuzz import fuzz

from . import ai, match, vault

SOURCE = "you told Sahl"
SIMILAR = 85  # as close as a guide's alias must be (match.THRESHOLD); numbers must still agree: "Address line 1" is not "2"
# Sahl never types passwords, PINs, one-time codes or a card's security code, so it never asks to remember them either.
# Other card details (number, expiry, name on card) are told like any other box. Letters only bound a word, so a field
# named "card_cvv" or "cc-csc" is caught too.
NEVER = re.compile(r"pass(?:word|code|phrase)|(?<![a-z])(?:pin|otp|cv[cv]\d?|csc)(?![a-z])|one.time"
                   r"|card\s*verification|security\s*code|verification\s*(?:code|number|value)", re.I)


def allowed(label: str) -> bool:
    return not NEVER.search(label)


def _who(person) -> int:
    return int(person) if str(person).isdigit() else 0


def _numbers(norm: str) -> list[str]:
    return re.findall(r"\d+", norm)


def concept_for(label: str) -> str | None:
    """The concept a printed label already means: the same words, or close enough to be one spelling of them."""
    n = match._norm(label)
    if not n:
        return None
    rows = vault._db().execute("select label, concept from taught_labels").fetchall()
    for known, concept in rows:
        if known == n:
            return concept
    best = max(((fuzz.ratio(n, known), concept) for known, concept in rows if _numbers(known) == _numbers(n)),
               default=(0, None))
    return best[1] if best[0] >= SIMILAR else None


def get(label: str, person) -> dict | None:
    """{value, concept} for a label Sahl was told about, for this person (or told before any person existed)."""
    concept = concept_for(label)
    if not concept:
        return None
    with vault._db() as db:
        row = db.execute("select value from taught_values where concept=? and person in (?, 0) order by person desc",
                         (concept, _who(person))).fetchone()
    return {"value": row[0], "concept": concept} if row else None


def concepts(person) -> dict[str, str]:
    """{concept: value} the person has told Sahl, to offer as meanings of a label it doesn't know."""
    rows = vault._db().execute("select concept, value from taught_values where person in (?, 0) order by person",
                               (_who(person),)).fetchall()
    return dict(rows)


def teach(label: str, value: str, person) -> str:
    """Remember `value` for what `label` means (a new concept if no told label reads like it); the concept."""
    label, value = label.strip(" :*"), value.strip()
    concept = concept_for(label) or label
    with vault._db() as db:
        db.execute("insert or replace into taught_labels values (?, ?)", (match._norm(label), concept))
        db.execute("insert or replace into taught_values values (?, ?, ?)", (_who(person), concept, value))
    return concept


def alias(label: str, concept: str) -> bool:
    """The person said `label` means an existing concept: from now on it reads as that."""
    with vault._db() as db:
        if not db.execute("select 1 from taught_values where concept=?", (concept,)).fetchone():
            return False
        db.execute("insert or replace into taught_labels values (?, ?)", (match._norm(label), concept))
    return True


def forget(concept: str):
    with vault._db() as db:
        db.execute("delete from taught_values where concept=?", (concept,))
        db.execute("delete from taught_labels where concept=?", (concept,))


def listing(person) -> list[dict]:
    """[{concept, value, labels}] for the settings page."""
    db = vault._db()
    out = []
    for concept, value in concepts(person).items():
        labels = [r[0] for r in db.execute("select label from taught_labels where concept=? order by label", (concept,))]
        out.append({"concept": concept, "value": value, "labels": labels})
    return out


ASK = """A person fills in forms. These are things they told you before, by the name the form gave them:
{known}

A new form has boxes labelled:
{labels}

For each new label say which told name it means, only when it is the same kind of detail in other words
(Company = Workplace = Employer; Cell phone = Mobile). Different details are not the same: Home phone is not Work
phone, Address line 1 is not Address line 2, Date of birth is not Birth place. When unsure, or when it is a different detail, answer "none". Most labels are "none".
"""


def similar(labels: list[str], person) -> dict[str, str]:
    """{label: told name} the local model thinks mean the same; a proposal for the person to confirm."""
    known = concepts(person)
    labels = [l for l in dict.fromkeys(labels) if l and not concept_for(l)][:16]
    if not known or not labels:
        return {}
    out = ai.chat({
        "model": ai.text_model(),
        "format": {
            "type": "object",
            "properties": {"matches": {"type": "array", "maxItems": len(labels), "items": {  # unbounded, the model repeats a match until it is cut off
                "type": "object",
                "properties": {"label": {"type": "string", "enum": labels}, "means": {"type": "string", "enum": ["none", *known]}},
                "required": ["label", "means"]}}},
            "required": ["matches"],
        },
        "options": {"temperature": 0, "num_predict": 50 * len(labels) + 30},
        "messages": [{"role": "user", "content": ASK.format(known="\n".join(f"- {c}" for c in known),
                                                            labels="\n".join(f"- {l}" for l in labels))}],
    }, timeout=8, tries=1)
    got = out.get("matches") if isinstance(out, dict) else None
    return {m["label"]: m["means"] for m in got or []
            if isinstance(m, dict) and m.get("label") in labels and m.get("means") in known}  # only what it was shown


_asked: dict[tuple, str] = {}  # (person, label, told names) -> the name the model proposed, "" for none; kept in memory
_spawn = lambda fn, *args: threading.Thread(target=fn, args=args, daemon=True).start()  # tests run it at once


def suggestions(labels: list[str], person) -> dict[str, str]:
    """What the model has proposed for these labels so far. It is asked about new ones in the background, once each, so a
    read never waits for it: the proposals show on the next read."""
    names = tuple(sorted(concepts(person)))
    key = lambda l: (_who(person), l, names)
    fresh = [l for l in dict.fromkeys(labels) if key(l) not in _asked and not concept_for(l)]
    if fresh and names:
        for l in fresh:
            _asked[key(l)] = ""
        _spawn(_ask, fresh, person, key)
    return {l: c for l in labels if (c := _asked.get(key(l)))}


def _ask(labels, person, key):
    for l, c in similar(labels, person).items():
        _asked[key(l)] = c
