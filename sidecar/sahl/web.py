"""Matches a browser page's DOM fields to a guide, then releases only the verified values it needs.

The extension extracts labels and element rectangles; it never sends values. This module ranks guides from the
page's title, URL path and field labels, optionally asks the local text model, and maps the guide's fields to the
page's elements by their visible text. Values come from the same vault as the screen reader.
"""
import calendar
import re


from . import intent, match, vault

THRESHOLD = 82
UNSAFE_TYPES = {"password", "file", "hidden", "submit", "button", "reset", "image"}
PAYMENT = re.compile(r"(?:cc-(?:name|number|exp|csc|type)|card\s*(?:number|no|holder)|cvv|cvc|security\s*code)", re.I)


def _safe(field: dict) -> bool:
    """Fields Sahl must never read values into: passwords, uploads and payment details."""
    tag = str(field.get("tag", "")).lower()
    kind = str(field.get("type", "")).lower()
    auto = str(field.get("autocomplete", "")).lower()
    if tag in ("button", "submit") or kind in UNSAFE_TYPES:
        return False
    if auto.startswith("cc-") or PAYMENT.search(" ".join(str(x) for x in (field.get("name"), field.get("label"), field.get("autocomplete")))):
        return False
    return True


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


def _field_score(field: dict, aliases: list[str]) -> float:
    texts = _texts(field)
    return max((match._score(t, aliases) for t in texts), default=0.0)


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
    picked = intent.pick(text, guides, timeout=8)
    picked_id = picked.get("guide") if isinstance(picked, dict) else None
    if picked_id in guides:
        score = dict((i, s) for s, i in ranked).get(picked_id, 0.0)
        return guides[picked_id], score
    return guides[ranked[0][1]], ranked[0][0]


def _needs(key) -> str | None:
    first = (key if isinstance(key, str) else (key or [""])[0]).split(".")[0]
    return first if first in ("passport", "eid") else None


def _identity(field: dict) -> str:
    return str(field.get("id") or field.get("element_id") or f"field-{id(field)}")


def _match_fields(guide: dict, fields: list[dict]) -> list[dict]:
    safe = [f for f in fields if _safe(f)]
    pairs = sorted(
        ((_field_score(field, spec["aliases"]), gi, fi)
         for fi, field in enumerate(safe) for gi, spec in enumerate(guide["fields"])),
        reverse=True)
    used_spec, used_field, hits = set(), set(), {}
    for score, gi, fi in pairs:
        if score < THRESHOLD:
            break
        if gi in used_spec or fi in used_field:
            continue
        used_spec.add(gi)
        used_field.add(fi)
        hits[gi] = (fi, score)
    out = []
    for gi, spec in enumerate(guide["fields"]):
        if gi not in hits:
            continue
        fi, score = hits[gi]
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


def plan(page: dict, guides: dict, person: str | None = None) -> dict:
    """Match a page to a guide and return fields, without values."""
    people = vault.people()
    if person not in {p["id"] for p in people}:
        person = people[0]["id"] if len(people) == 1 else None
    guide, confidence = _guide_for(page, guides)
    fields = page.get("fields", [])
    matched = _match_fields(guide, fields) if guide else []
    if not matched:
        fallback = _fallback(fields, guides)
        if fallback:
            guide, matched = fallback
            confidence = 0.5
    if not guide:
        return {"guide": None, "confidence": 0, "fields": [], "person": person, "people": people,
                "reason": "no guide matched this page"}
    return {
        "guide": {"id": guide["id"], "name": guide["service"].get("en", guide["id"]), "about": guide.get("about", "")},
        "confidence": round(confidence * 100),
        "fields": matched,
        "person": person,
        "people": people,
        "reason": "" if matched else "the page has no fields this guide recognises",
        "_guide": guide,
        "_fields": fields,
    }


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


def _part_values(value: str) -> list[dict]:
    d, m, y = value.split("/")
    month = int(m)
    return [
        {"part": "d", "value": d, "texts": [d, str(int(d))]},
        {"part": "m", "value": m, "texts": [m, str(month), calendar.month_abbr[month], calendar.month_name[month]]},
        {"part": "y", "value": y, "texts": [y]},
    ]


def values(scan: dict, element_ids: list[str], person: str | None = None) -> dict:
    """Verified values for the fields in a scan, by element id."""
    guide = scan.get("_guide")
    if not guide:
        return {"values": [], "missing": [{"element_id": i, "reason": "no guide"} for i in element_ids], "needs_person": False}
    pid = person if person in {p["id"] for p in scan.get("people", [])} else scan.get("person")
    if not pid:
        return {"values": [], "missing": [{"element_id": i, "reason": "choose a person"} for i in element_ids], "needs_person": True}
    by_id = {m["element_id"]: m for m in scan.get("fields", [])}
    specs = {f["id"]: f for f in guide["fields"]}
    out, missing = [], []
    for element_id in element_ids:
        m = by_id.get(element_id)
        if not m:
            missing.append({"element_id": element_id, "reason": "field not in the last scan"})
            continue
        spec = specs.get(m["field_id"])
        if not spec or spec["input"] == "checkbox":
            missing.append({"element_id": element_id, "reason": "Sahl never ticks this"})
            continue
        got = vault.get(spec["vault_key"], pid)
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
            choice = _option(opts, value)
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
