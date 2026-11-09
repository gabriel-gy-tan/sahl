"""Matches a browser page's DOM fields to a guide, then releases only the verified values it needs.

The extension extracts labels and element rectangles; it never sends values. This module ranks guides from the
page's title, URL path and field labels, optionally asks the local text model, and maps the guide's fields to the
page's elements by their visible text. Values come from the same vault as the screen reader.
"""
import calendar
import re
from collections import Counter


from . import ai, fieldtype, intent, match, taught, vault

THRESHOLD = 82
SHARED = 95  # a second box that reads exactly like a guide field's label gets the same value
UNSAFE_TYPES = {"password", "file", "hidden", "submit", "button", "reset", "image"}


def _safe(field: dict) -> bool:
    """Fields Sahl must never put a value in: passwords, PINs, one-time codes, a card's security code, uploads."""
    tag = str(field.get("tag", "")).lower()
    kind = str(field.get("type", "")).lower()
    if tag in ("button", "submit") or kind in UNSAFE_TYPES:
        return False
    said = [field.get(k) for k in ("label", "name", "placeholder", "autocomplete")] + list(field.get("labels", []))
    return taught.allowed(" ".join(str(x) for x in said if x))


def _kind(field: dict) -> str:
    tag = str(field.get("tag", "")).lower()
    kind = str(field.get("type", "")).lower()
    if tag == "date-parts":
        return "date-parts"
    if tag == "select":
        return "select"
    if tag == "radio":
        return "radio"
    if kind in ("date", "month", "week", "datetime-local"):
        return "date"
    if kind == "checkbox":
        return "checkbox"
    return "text"


def _texts(field: dict) -> list[str]:
    out = [field.get("label", ""), field.get("placeholder", ""), field.get("name", "")]
    out += field.get("labels", [])
    name = re.sub(r"([a-z])([A-Z])", r"\1 \2", str(field.get("name", "")))
    name = re.sub(r"[_\-\[\].]+", " ", name)
    out.append(name)
    return [x for x in dict.fromkeys(str(t).strip() for t in out) if x]


def _field_score(field: dict, spec: dict) -> float:
    """How well a box fits a guide field: its words against the aliases, or what the box asks for (fieldtype)."""
    fuzzy = max((match._score(t, spec["aliases"]) for t in _texts(field)), default=0.0)
    meant = fieldtype.score(field, spec)
    if meant < 0:  # about someone else: only a label the guide itself spells out can say otherwise
        return fuzzy if fuzzy >= SHARED else 0.0
    return max(fuzzy, meant)


def _page_text(page: dict) -> str:
    bits = [page.get("title", ""), page.get("headings", ""), page.get("url", "")]
    bits += [t for f in page.get("fields", []) for t in _texts(f)[:2]]
    return " ".join(str(x) for x in bits if x)[:6000]


def _guide_for(page: dict, guides: dict) -> tuple[dict | None, float]:
    chosen = page.get("guide")
    if chosen in guides:
        return guides[chosen], 1.0
    text = _page_text(page)
    ranked = intent.rank(text, intent.catalogue(guides))
    if ranked and ranked[0][0] >= 0.75:
        return guides[ranked[0][1]], ranked[0][0]
    if not ranked or ranked[0][0] < 0.3:
        return None, 0.0  # nothing on the page resembles a guide: use the generic fields, don't wake the model
    # in between: the closest guide now, and the local model's pick in the background for the next read of this page,
    # so a read never waits for the model to load (it took up to 8 s)
    where = str(page.get("url", "")).split("?")[0].split("#")[0]
    picked_id = _picked.get(where)
    if where not in _picked:
        _picked[where] = None
        taught._spawn(_pick_later, where, text, guides)
    if picked_id in guides:
        score = dict((i, s) for s, i in ranked).get(picked_id, 0.0)
        return guides[picked_id], score
    return guides[ranked[0][1]], ranked[0][0]


_picked: dict[str, str | None] = {}  # page address -> the guide the local model picked for it (None while it thinks)


def _pick_later(where: str, text: str, guides: dict):
    picked = intent.pick(text, guides, timeout=60)
    _picked[where] = picked.get("guide") if isinstance(picked, dict) else None


def _needs(key) -> str | None:
    first = (key if isinstance(key, str) else (key or [""])[0]).removeprefix("ar:").split(".")[0]
    return first if first in ("passport", "eid") else None


def _identity(field: dict) -> str:
    return str(field.get("id") or field.get("element_id") or f"field-{id(field)}")


def _match_fields(guide: dict, fields: list[dict]) -> list[dict]:
    safe = [f for f in fields if _safe(f)]
    # equal scores: the longer label wins the guide field; a box that reads exactly like one of its labels shares it,
    # so "Name" and "Name in English" both get the name
    pairs = sorted(
        ((_field_score(field, spec), len(match._norm(str(field.get("label", "")))), gi, fi)
         for fi, field in enumerate(safe) for gi, spec in enumerate(guide["fields"])),
        reverse=True)
    used_spec, used_field, hits = set(), set(), []
    for score, _, gi, fi in pairs:
        if score < THRESHOLD:
            break
        if fi in used_field or (gi in used_spec and score < SHARED):
            continue
        used_spec.add(gi)
        used_field.add(fi)
        hits.append((gi, fi, score))
    out = []
    for gi, fi, score in sorted(hits, key=lambda h: (h[0], h[1])):
        spec = guide["fields"][gi]
        field = safe[fi]
        kind = _kind(field)
        if kind == "checkbox":
            continue
        item = {
            "element_id": _identity(field),
            "field_id": spec["id"],
            "label": spec["aliases"][0],
            "seen": field.get("label", ""),
            "input": spec["input"],
            "kind": kind,
            "confidence": round(score),
            "help": spec.get("help", {}),
            "needs": _needs(spec.get("vault_key")),
        }
        if kind == "date-parts":
            item["parts"] = [{"element_id": p.get("element_id"), "part": p.get("part")} for p in field.get("parts", [])]
        out.append(item)
    return out


def _fallback(fields: list[dict], guides: dict) -> tuple[dict, list[dict]] | None:
    generic = guides.get(intent.GENERIC)
    if not generic:
        return None
    matched = _match_fields(generic, fields)
    return (generic, matched) if len(matched) >= 2 else None


def _unknown_fields(fields: list[dict], matched: list[dict], person) -> list[dict]:
    """Boxes no guide field matched, after the known ones: with what the person told Sahl before, a suggestion of which
    told detail it is, or nothing, so the popup asks. Text boxes, dropdowns and radio buttons; never a secret."""
    taken = {m["element_id"] for m in matched}
    boxes = [f for f in fields if _safe(f) and _identity(f) not in taken and _kind(f) in ("text", "select", "radio")
             and str(f.get("label", "")).strip(" :*")]
    labels = [str(f["label"]).strip(" :*") for f in boxes]
    shared = Counter(match._norm(x) for x in labels)
    seen: Counter = Counter()
    for i, label in enumerate(labels):  # boxes that share a label (a month and a year under "Expiry") are two details
        if shared[match._norm(label)] > 1:
            seen[match._norm(label)] += 1
            labels[i] = f"{label} {seen[match._norm(label)]}"
    told = {_identity(f): taught.get(label, person) for f, label in zip(boxes, labels)}
    ideas = taught.suggestions([label for f, label in zip(boxes, labels) if not told[_identity(f)]], person)
    out = []
    for f, label in zip(boxes, labels):
        item = {"element_id": _identity(f), "field_id": "taught:" + match._norm(label), "label": label, "seen": label,
                "input": _kind(f), "kind": _kind(f), "confidence": 100, "help": {}, "needs": None, "unknown": True,
                "told": bool(told[_identity(f)]), "rect": f.get("rect", [])}
        if (c := ideas.get(label)):
            item["suggest"] = c  # the told detail's name only: values leave the vault one box at a time, on a fill
        out.append(item)
    out.sort(key=lambda x: ((x["rect"] or [0, 0])[1], (x["rect"] or [0, 0])[0]))
    return out


def _person(people: list[dict], person: str | None) -> str | None:
    if person in {p["id"] for p in people}:
        return person
    return people[0]["id"] if len(people) == 1 else None


def plan(page: dict, guides: dict, person: str | None = None, lang: str = "en") -> dict:
    """Match a page to a guide and return fields, without values."""
    people = vault.people()
    person = _person(people, person)
    guide, confidence = _guide_for(page, guides)
    fields = page.get("fields", [])
    matched = _match_fields(guide, fields) if guide else []
    if not matched:
        fallback = _fallback(fields, guides)
        if fallback:
            guide, matched = fallback
            confidence = 0.5
    generic = guides.get(intent.GENERIC)
    if guide and generic and guide is not generic:  # a box this guide lacks may still be a plain one: a name, a date of birth
        taken = {m["element_id"] for m in matched}
        matched += _match_fields(generic, [f for f in fields if _identity(f) not in taken])
    specs = {f["id"]: f for g in (guide, generic) if g for f in g.get("fields", [])}
    for m in matched:  # whether a value is there to fill (never the value itself), and whether the AI wrote it
        key = specs.get(m["field_id"], {}).get("vault_key")
        m["ai"] = isinstance(key, str) and key.startswith("ar:")
        if not person:
            m["has_value"] = False
        elif m["ai"]:  # written from the English name when filled; needs that name and the text model
            got = vault.get(key[3:], person)
            m["has_value"] = bool(got and got.get("verified")) and ai.have(ai.text_model())
        else:
            got = vault.get(key, person) if key else None
            m["has_value"] = bool(got and got.get("verified"))
    unknown = _unknown_fields(fields, matched, person)
    for u in unknown:
        u["has_value"] = bool(u.get("told"))
    if not guide and not unknown:
        return {"guide": None, "confidence": 0, "fields": [], "person": person, "people": people,
                "reason": "no guide matched this page"}
    return {
        "guide": {"id": guide["id"], "name": guide["service"].get(lang) or guide["service"].get("en", guide["id"]),
                  "about": guide.get("about", "")}
        if guide else None,
        "confidence": round(confidence * 100) if guide else 0,
        "fields": matched + unknown,
        "person": person,
        "people": people,
        "reason": "" if matched or unknown else "the page has no fields this guide recognises",
        "_guide": guide,
        "_specs": specs,
        "_fields": fields,
    }


def teach(scan: dict, element_id: str, value: str, person: str | None = None) -> str | None:
    """The person typed what goes in a box no guide knows: remember it under the box's label. None when the box is
    not one the last scan asked about."""
    f = next((x for x in scan.get("fields", []) if x["element_id"] == element_id and x.get("unknown")), None)
    if not f or not taught.allowed(f["label"]):
        return None
    return taught.teach(f["label"], value, _person(scan.get("people", []), person) or scan.get("person"))


def alias(scan: dict, element_id: str, concept: str) -> bool:
    """The person agreed a box is a detail they told Sahl about under another name."""
    f = next((x for x in scan.get("fields", []) if x["element_id"] == element_id and x.get("unknown")), None)
    return bool(f and taught.allowed(f["label"]) and taught.alias(f["label"], concept))


def _forms(value: str) -> set[str]:
    forms = {value}
    for country, word in vault.NATIONS.values():
        if match._norm(value) in (match._norm(country), match._norm(word)):
            forms |= {country, word}
    return {match._norm(x) for x in forms if x}


def _option(options: list[dict], value: str) -> dict | None:
    want = _forms(value)
    scored = []
    for o in options:
        text = str(o.get("text") or o.get("label") or "")
        n = match._norm(text)
        if not n:
            continue
        if n in want:
            scored.append((0, len(n), o))
        elif any(w and (w in n or n in w) for w in want):
            scored.append((1, abs(len(n) - min(len(w) for w in want)), o))
    return min(scored, key=lambda x: (x[0], x[1]))[2] if scored else None


def _loose_part(label: str, value: str) -> list[str]:
    """A told value for a box that is only a month or only a year (a card's expiry): the ways a menu may write it.
    "March 2030", "03/30" and "3" all give month 3; "2030" and "30" give 2030."""
    if label.endswith("(month)"):
        word = next((i for i in range(1, 13) if re.search(rf"\b{calendar.month_abbr[i]}", value, re.I)), None)
        num = re.match(r"\s*(\d{1,2})\b", value)
        month = word or (int(num[1]) if num and 1 <= int(num[1]) <= 12 else None)
        if month:
            return [f"{month:02d}", str(month), calendar.month_abbr[month], calendar.month_name[month]]
    if label.endswith("(year)"):
        y = re.findall(r"\d{4}|\d{2}", value)
        if y:
            year = y[-1] if len(y[-1]) == 4 else f"20{y[-1]}"
            return [year, year[2:]]
    return [value]


def _part_values(value: str) -> list[dict]:
    d, m, y = value.split("/")
    month = int(m)
    return [
        {"part": "d", "value": d, "texts": [d, str(int(d))]},
        {"part": "m", "value": m, "texts": [m, str(month), calendar.month_abbr[month], calendar.month_name[month]]},
        {"part": "y", "value": y, "texts": [y]},
    ]


_arabic_names: dict[str, str] = {}
TRANSLATE = """Write this person's name in Arabic letters, the way it is sounded (a transliteration, not a meaning).
Keep every name part in order, add nothing. Name: {name}"""


def _arabic(key: str, person) -> dict | None:
    """The person's name from `key` in Arabic letters, written by the local text model from the English one. It is a
    transliteration, so the popup says so (help text) and the person checks it; the form is never submitted."""
    en = vault.get(key, person)
    if not en or not en.get("verified"):
        return None
    name = " ".join(re.sub(r"[^A-Za-z' .-]", " ", en["value"]).split())
    if name not in _arabic_names:
        out = ai.chat({
            "model": ai.text_model(),
            "format": {"type": "object", "properties": {"arabic": {"type": "string"}}, "required": ["arabic"]},
            "options": {"temperature": 0, "num_predict": 120},
            "messages": [{"role": "user", "content": TRANSLATE.format(name=name)}],
        }, timeout=60, tries=1)
        ar = " ".join(str(out.get("arabic", "")).split()) if isinstance(out, dict) else ""
        # only Arabic letters and spaces, and as many words as the English name
        if not re.fullmatch(r"[\u0621-\u064a ]+", ar) or len(ar.split()) != len(name.split()):
            return None
        _arabic_names[name] = ar
    return {"value": _arabic_names[name], "verified": True, "source": "written from your name in English"}


def values(scan: dict, element_ids: list[str], person: str | None = None) -> dict:
    """Verified values for the fields in a scan, by element id: from documents for guide fields, from what the person
    told Sahl for the rest. Whose values, when the vault holds more than one person, is the person's choice."""
    people = scan.get("people", [])
    pid = person if person in {p["id"] for p in people} else scan.get("person")
    if not pid and len(people) > 1:
        return {"values": [], "missing": [{"element_id": i, "reason": "choose a person"} for i in element_ids], "needs_person": True}
    by_id = {m["element_id"]: m for m in scan.get("fields", [])}
    specs = scan.get("_specs") or {f["id"]: f for f in (scan.get("_guide") or {}).get("fields", [])}
    out, missing = [], []
    for element_id in element_ids:
        m = by_id.get(element_id)
        if not m:
            missing.append({"element_id": element_id, "reason": "field not in the last scan"})
            continue
        if m.get("unknown"):
            told = taught.get(m["label"], pid) if taught.allowed(m["label"]) else None
            if not told:
                missing.append({"element_id": element_id, "reason": "not told yet"})
                continue
            got = {"value": told["value"], "verified": True}  # the person's own words
        else:
            spec = specs.get(m["field_id"])
            if not spec or spec["input"] == "checkbox":
                missing.append({"element_id": element_id, "reason": "Sahl never ticks this"})
                continue
            got = _arabic(spec["vault_key"][3:], pid) if str(spec["vault_key"]).startswith("ar:") else vault.get(spec["vault_key"], pid)
        if not got or not got.get("verified"):
            missing.append({"element_id": element_id, "reason": "no verified value", "needs": m.get("needs")})
            continue
        value = got["value"]
        if m["kind"] == "date-parts":
            if not re.fullmatch(r"\d\d/\d\d/\d{4}", value):
                missing.append({"element_id": element_id, "reason": "not a full date"})
                continue
            out.append({"element_id": element_id, "kind": "date-parts", "parts": [
                {**p, "element_id": next((x["element_id"] for x in m.get("parts", []) if x["part"] == p["part"]), None)}
                for p in _part_values(value)]})
            continue
        if m["kind"] in ("select", "radio"):
            opts = next((f.get("options", []) for f in scan.get("_fields", [])
                         if str(f.get("id") or f.get("element_id")) == element_id), [])
            forms = _loose_part(m["label"], value) if m.get("unknown") else [value]
            choice = next((c for c in (_option(opts, f) for f in forms) if c), None)
            if not choice:
                missing.append({"element_id": element_id, "reason": "no matching option", "options": [o.get("text") for o in opts]})
                continue
            out.append({"element_id": element_id, "kind": m["kind"], "option": choice.get("text") or choice.get("label")})
            continue
        if m["kind"] == "date" and re.fullmatch(r"\d\d/\d\d/\d{4}", value):
            d, mo, y = value.split("/")
            value = f"{y}-{mo}-{d}"
        out.append({"element_id": element_id, "kind": m["kind"], "value": value})
    return {"values": out, "missing": missing, "needs_person": False}
