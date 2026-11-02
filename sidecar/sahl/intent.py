"""A short conversation that helps someone find the form they want, with a small local text model.

Which form they mean is decided first, without a model, by the rare words they share with a guide's names, aliases
and "about" line. A 1.7B model is asked only when those words don't settle it, and only to choose among the closest
guides. A second call writes Sahl's reply, told only about the guides that matched. The person still chooses the form.
"""
import math
import os
import re
from concurrent.futures import ThreadPoolExecutor

from rapidfuzz import fuzz

from . import ai

GENERIC = "any-form"  # used when Sahl has no guide for the form; never offered as a match

PICK = """You help a UAE resident find the government form they want to fill in.
These are the forms that might fit, one per line as id: names | what it is for.
{catalogue}

The person wrote: "{text}"

Answer JSON only.
- kind "match" and guide = its id, when they clearly want to fill in, book or start one of the forms above.
- kind "about" and guide = its id, when they ask a question about one of the forms above (what it is, cost, documents, how long, how to).
- kind "new" and name = the service in a few of their own words (same language), when they want a specific government service that is not above.
- kind "unsure" for anything else: a greeting, thanks, or vague words like "help" or "a form".
Never pick a form just because it shares a word; it must be the thing they mean."""

TALK = """You are Sahl, a calm helper on a UAE resident's own computer. You help them with government forms.
{catalogue}

Their last message is in {language}: reply in {language}, in one to three short, kind sentences. Plain words only: no lists,
no JSON, no web addresses.
- Fees, documents, deadlines and rules are only what is written above under "Needs". For anything not written there,
  say you aren't sure and that the official government website has it. Never make up a requirement.
- Never say Sahl has a guide for a form that is not named above. When they name another form, say Sahl doesn't know that
  one yet but can still go through it with them box by box. When they haven't named a form, ask which form they want.
- Questions about their own documents ("what documents do I have?") are answered from "Documents Sahl holds" below:
  say which kinds of document, and for whom if there is more than one person, but never read out numbers or other values.
  If it says none, tell them they can add documents with the + button.
- Never ask for their personal details: Sahl reads those from their own documents later.
You can't log in, pay or submit anything for them.

Documents Sahl holds (counts only):
{held}"""

# words that say how someone asks, not which form: they never decide the match
STOP = set("""a an the my me mine i im i'm id's to for of in on at and or but is are was be been do does did done can could
would should will shall may might how what whats what's which when where why who tell about please want wants need needs
needed like help helps helping hi hello hey thanks thank you your yours sahl form forms fill filling start starting book this
that it its with from much many long take takes cost costs fee fees price document documents paper papers required require
there any some just now page online apply applying get getting have has had know explain let lets is there one ok okay
أريد اريد كيف ما ماذا هل كم متى أين اين لماذا عن في من على الى إلى لي انا أنا رسوم نموذج اشرح ابغى أبغى ممكن""".split())
QUESTION = re.compile(r"^\s*(how|what|what's|whats|which|when|where|why|who|is|are|does|do i|do you|can i|could i|can you tell|"
                      r"could you tell|tell me|explain|كيف|ما|ماذا|هل|كم|متى|أين|لماذا|اشرح|کیسے|کیا|کتنا|کب)\b|[?؟]\s*$", re.I)
REQUEST = re.compile(r"\b(help me (fill|with|start|apply|renew|book)|fill (in|out)|start|i want to|i'd like to|let's|lets)\b", re.I)
STRONG = 0.75  # share of a message's weight that one guide covers for Sahl to name it without asking the model


def catalogue(guides: dict) -> dict:
    return {i: g for i, g in guides.items() if i != GENERIC}


def _needs(g: dict) -> str:
    """The guide's requirements as one line each, from the official page it was read from."""
    return "\n".join(f"  Needs, {k}: " + "; ".join(v) for k, v in g.get("requirements", {}).items())


def _names(g: dict) -> list[str]:
    return [s.split("·")[0].strip() for s in g["service"].values()]  # "Residency medical fitness · booking" -> head


def _words(text: str) -> list[str]:
    out = []
    for w in re.findall(r"\w+", text.casefold().replace("license", "licence")):
        if w.startswith(("ال", "وال")) and len(w) > 4:  # Arabic "the"
            w = w[w.index("ال") + 2:]
        if w not in STOP and (len(w) > 1 or not w.isascii()):
            out.append(w)
    return out


def _same(a: str, b: str) -> bool:
    """renew ~ renewal ~ renewing, register ~ registration, residence ~ residency; short words only exactly."""
    if a == b:
        return True
    if min(len(a), len(b)) < 4:
        return False
    return len(os.path.commonprefix([a, b])) >= max(4, 0.75 * min(len(a), len(b))) or fuzz.ratio(a, b) >= 88


def is_question(text: str) -> bool:
    return bool(QUESTION.search(text)) and not REQUEST.search(text)


def rank(text: str, guides: dict) -> list[tuple[float, str]]:
    """Guides by how much of the message's weight their words cover (0..1), best first. Rare words weigh more, so
    "car" beats "registration"; a word no guide has (a service Sahl doesn't know) still weighs, keeping scores low.

    # ponytail: word overlap with idf weights; swap for local embeddings if real questions keep missing.
    """
    q = list(dict.fromkeys(_words(text)))
    if not q:
        return []
    bags = {i: set(_words(" ".join([*_names(g), *g.get("aliases", []), g.get("about", "")]))) for i, g in guides.items()}
    has = {w: {i for i, b in bags.items() if any(_same(w, x) for x in b)} for w in q}
    idf = {w: math.log(1 + len(guides) / (1 + len(has[w]))) for w in q}
    total = sum(idf.values())
    t = " ".join(q)

    def tie(g: dict) -> float:  # equal cover: the guide whose own name is closest to the message, with fewest extra words
        return max(fuzz.token_sort_ratio(n.casefold(), t) for n in [*_names(g), *g.get("aliases", [])])
    scored = [(sum(idf[w] for w in q if i in has[w]) / total, tie(guides[i]), i) for i in guides]
    return [(s, i) for s, _, i in sorted(scored, reverse=True) if s > 0]


def _shortlist(text: str, guides: dict, n: int = 8) -> dict:
    """The n guides closest to the text, so the small model never reads the whole catalogue."""
    return {i: guides[i] for _, i in rank(text, guides)[:n]}


def _strong(ranked: list[tuple[float, str]]) -> list[str]:
    """Up to three guides that clearly cover the message, near the best one."""
    if not ranked or ranked[0][0] < STRONG:
        return []
    return [i for s, i in ranked if s >= max(STRONG, ranked[0][0] - 0.1)][:3]


def _answer(kind: str, options: list[str], name: str = "") -> dict:
    return {"kind": kind, "guide": options[0] if options else None, "options": options, "name": name}


def _quick(text: str, known: dict) -> dict | None:
    """The answer when no model is needed: nothing that could name a form, or a guide the words clearly name."""
    if not _words(text):  # "hi", "help", "thanks"
        return _answer("unsure", [])
    if strong := _strong(rank(text, known)):
        return _answer("about" if is_question(text) else "match", strong)
    return None


def pick(text: str, guides: dict) -> dict:
    """{kind: match|about|new|unsure, guide: best id or None, options: up to 3 ids, name: the service in their words
    for "new"}. "about" is a question about a form, so Sahl answers it and offers the form without choosing it."""
    known = catalogue(guides)
    text = text.strip()[:300]
    if quick := _quick(text, known):
        return quick
    asking = is_question(text)
    ranked = rank(text, known)
    near = {i: known[i] for _, i in ranked[:8]}
    lines = "\n".join(f"{i}: {' / '.join(dict.fromkeys(_names(g)))} | {g.get('about', '')}" for i, g in near.items())
    out = ai.chat({
        "model": ai.text_model(),
        "stream": False,
        "think": True,  # a short think is what tells "medical for my visa" apart from a new service
        "format": {
            "type": "object",
            "properties": {"kind": {"type": "string", "enum": ["match", "about", "new", "unsure"]},
                           "guide": {"type": "string", "enum": [*near, ""]},
                           "name": {"type": "string"}},
            "required": ["kind", "guide", "name"],
        },
        "keep_alive": "30m",
        "options": {"temperature": 0, "num_predict": 600},
        "messages": [{"role": "user", "content": PICK.format(catalogue=lines or "(none)", text=text.replace('"', "'"))}],
    }, timeout=20, tries=1)
    if not isinstance(out, dict):
        return _answer("unsure", [])
    kind, guide, name = out.get("kind"), out.get("guide"), str(out.get("name", "")).strip()[:60]
    if kind in ("match", "about") and guide in near:  # the model's id is only trusted if it is one it was shown
        return _answer("about" if asking or kind == "about" else "match", [guide])
    # small models sometimes call a vague message a new service, or name it after a known guide
    if (kind == "new" and not asking and _words(name) and fuzz.token_set_ratio(name.casefold(), text.casefold()) >= 60
            and not _strong(rank(name, known))):
        return _answer("new", [], name)
    return _answer("unsure", [])


def _language(text: str) -> str:
    """The small model often answers in English; naming the language keeps it in theirs."""
    if any("\u0d00" <= c <= "\u0d7f" for c in text):
        return "Malayalam"
    if any(c in "ٹڈڑںےۓہھ" for c in text):  # letters Urdu has and Arabic doesn't
        return "Urdu"
    if any("\u0600" <= c <= "\u06ff" for c in text):
        return "Arabic"
    return "English"


def _held(summary: dict | None) -> str:
    """What the vault holds as one line per person, from vault.summary(): types and counts, never values."""
    rows = [f"{p['name']}: " + (", ".join(f"{n} {doc.replace('_', ' ')}" for doc, n in p["docs"].items()) or "nothing")
            for p in (summary or {}).get("people", [])]
    if (summary or {}).get("unmatched"):
        rows.append(f"{summary['unmatched']} not matched to anyone")
    return "\n".join(rows) or "none yet"


def _focus(text: str, guides: dict) -> dict:
    """The guides Sahl's reply may talk about: the ones the message clearly covers, else the close ones."""
    ranked = rank(text, catalogue(guides))
    ids = _strong(ranked) or [i for s, i in ranked[:3] if s >= 0.5]
    return {i: guides[i] for i in ids}


def reply(turns: list[dict], guides: dict, held: dict | None = None) -> str:
    """Sahl's words back, or "" when the model isn't running."""
    focus = _focus(turns[-1]["content"], guides)
    if focus:
        lines = "Forms Sahl has a guide for that match their message, as names | what it is for, then what it needs:\n" + "\n".join(
            f"{' / '.join(dict.fromkeys(_names(g)))} | {g.get('about', '')}\n{_needs(g)}".rstrip() for g in focus.values())
    else:  # nothing named: say what Sahl does, without a list a small model would read out or blend together
        lines = (f"Sahl has guides for {len(catalogue(guides))} UAE government services (Abu Dhabi TAMM, ICP, MOHRE, MOHAP), "
                 "such as Emirates ID, visas and residence, passports, vehicles, work permits and family services. "
                 "No particular form matches their message, so don't describe one.")
    out = ai.chat({
        "model": ai.text_model(),
        "stream": False,
        "think": False,  # plain conversation; the offer is decided by pick()
        "format": {"type": "object", "properties": {"reply": {"type": "string"}}, "required": ["reply"]},
        "keep_alive": "30m",
        "options": {"temperature": 0.3, "num_predict": 200},
        "messages": [{"role": "system", "content": TALK.format(catalogue=lines, held=_held(held), language=_language(turns[-1]["content"]))}, *turns],
    }, timeout=30, tries=1)
    return str(out.get("reply", "")).strip()[:600] if isinstance(out, dict) else ""


def search(text: str, guides: dict, n: int = 8) -> list[str]:
    """The form search box: guide ids for what they've typed so far, best first."""
    text = text.strip()[:100]
    known = catalogue(guides)
    if not text:
        return sorted(known, key=lambda i: _names(known[i])[0].casefold())
    ranked = [i for s, i in sorted(rank(text, known), key=lambda x: (-x[0], len(_names(known[x[1]])[0]))) if s >= 0.3]
    t = text.casefold()  # a name typed partly ("emir") has no whole word yet
    typed = [i for i, g in known.items() if i not in ranked and any(t in n.casefold() for n in [*_names(g), *g.get("aliases", [])])]
    return (ranked + typed)[:n]


def talk(history: list[dict], guides: dict, held: dict | None = None) -> dict:
    """Sahl's next message. history is [{role: user|assistant, text}], oldest first, ending with the person's message.

    Returns {reply, kind, guide, options, name}: "match" offers options (guide is the first), "about" answers a question
    and offers them too, "new" means they want a form Sahl has no guide for (name, in their words), "unsure" is only a
    reply. reply is "" when the model isn't running.
    """
    turns = [{"role": "assistant" if h["role"] == "assistant" else "user", "content": h["text"].strip()[:500]} for h in history[-10:]]
    last = next((t["content"] for t in reversed(turns) if t["role"] == "user"), "")
    if not last:
        return {"reply": "", **_answer("unsure", [])}
    quick = _quick(last[:300], catalogue(guides))
    if quick and quick["kind"] == "match":  # the panel says "sounds like" over the forms; a model's words add only risk
        return {"reply": "", **quick}
    if quick:
        return {"reply": reply(turns, guides, held), **quick}
    with ThreadPoolExecutor(2) as pool:  # Ollama answers both at once when it can, so the wait is one call, not two
        offer, words = pool.submit(pick, last, guides), pool.submit(reply, turns, guides, held)
        return {"reply": words.result(), **offer.result()}
