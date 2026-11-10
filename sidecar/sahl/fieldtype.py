"""What a form box asks for, read from its words rather than matched to a list of spellings.

A label is split into what it asks for (a name, a date of birth, a passport number), which language it wants it in
("in Arabic") and whose it is ("Father's name", "Account owner"). The same reading serves any form, so "Name",
"Name in English" and "Applicant full name" are one detail, "Name in Arabic" is another, and a box about someone
else is never filled with the person's own detail. A browser's `autocomplete` hint counts most when the page gives one.
Guide aliases (match._score) still run first; this catches the spellings no alias list has.
"""
import re

from . import match

# whose it is: anyone but the person themselves, or a thing that is not a person's detail at all
OTHER = re.compile(r"\b(?:father|mother|spouse|wife|husband|sponsor|guardian|parent|child|children|son|daughter|employer|"
                   r"company|business|trade|bank|branch|beneficiary|owner|emergency|contact|reference|relative|friend|witness|"
                   r"representative|agent|school|user|file|domain|nick|street|city|account|holder|supplier|vendor|organi[sz]ation)s?\b"
                   r"|والد|الاب|الام|زوج|كفيل|ولي|صاحب|الشركة|بنك|مستفيد|قريب|المنشاه|المستخدم")
ENGLISH = re.compile(r"\b(?:english|latin)\b|انجليز|بالانجليزيه")
ARABIC = re.compile(r"\barabic\b|عرب")
NAME = re.compile(r"\bname\b|\bnames\b|الاسم|اسم")
GIVEN = re.compile(r"\b(?:first|given|fore)\b|الاول")
SURNAME = re.compile(r"\b(?:last|family|surname|sur)\b|العائله|اللقب")
OTHER_NAME_PARTS = re.compile(r"\b(?:middle|second|third|fourth|maiden|mother|alias|former|previous|short)\b")
AUTOCOMPLETE = {"name": "name", "given-name": "given", "family-name": "surname", "bday": "dob", "nationality": "nationality"}


def read(field: dict) -> dict:
    """{what, lang, other}: what = a concept like "name", "dob", "passport.number" or None; lang = "ar", "en" or None;
    other = the box is about someone or something else."""
    parts = [field.get("label", ""), field.get("placeholder", ""), *field.get("labels", [])[:3]]
    text = " ".join(match._norm(str(p)) for p in parts if p)
    ident = match._norm(re.sub(r"([a-z])([A-Z])", r"\1 \2", str(field.get("name", ""))))
    lang = "ar" if ARABIC.search(text) else "en" if ENGLISH.search(text) else None
    other = bool(OTHER.search(text))
    token = str(field.get("autocomplete", "")).split()[-1:] or [""]
    if (what := AUTOCOMPLETE.get(token[0])) and not other:
        return {"what": what, "lang": lang, "other": False}
    what = None
    if re.search(r"\bpassport\b|جواز", text):
        what = "passport.number" if re.search(r"\b(?:number|no|num)\b|رقم", text) else "passport.expiry" if re.search(r"expir|انتهاء", text) else None
    elif re.search(r"\b(?:emirates id|eid)\b|الهويه", text):
        what = "eid.number" if re.search(r"\b(?:number|no|num)\b|رقم", text) else None
    elif re.search(r"nationalit|citizenship|الجنسيه", text):
        what = "nationality"
    elif re.search(r"\bbirth\b|\bdob\b|\bborn\b|الميلاد", text) and not re.search(r"\b(?:place|country|city)\b|مكان", text):
        what = "dob"
    elif NAME.search(text) and not OTHER_NAME_PARTS.search(text):
        what = "given" if GIVEN.search(text) else "surname" if SURNAME.search(text) else "name"
        if what == "name" and not lang and re.search(r"[؀-ۿ]", text) and not re.search(r"[a-z]", text):
            what = None  # a bare Arabic "الاسم" could want either script: leave it to the guide's own aliases
    return {"what": what, "lang": lang, "other": other}


def wants(spec: dict) -> tuple[str, str | None] | None:
    """(what, lang) a guide field is for, from the vault key it fills."""
    key = spec.get("vault_key")
    key = key[0] if isinstance(key, list) and key else key
    if not isinstance(key, str):
        return None
    ar = key.startswith("ar:")
    key = key.removeprefix("ar:")
    doc, _, part = key.partition(".")
    what = key if part in ("number", "expiry") else part
    return what, ("ar" if ar else "en" if what in ("name", "given", "surname") else None)


def score(field: dict, spec: dict) -> float:
    """0 when the box is about someone else; 96 when it asks for what the guide field fills, in the right language."""
    seen, want = read(field), wants(spec)
    if not want:
        return 0.0
    if seen["other"]:
        return -1.0  # never the person's own detail
    what, lang = want
    if seen["what"] != what:
        return 0.0
    if lang and seen["lang"] and seen["lang"] != lang:
        return 0.0
    if lang == "ar" and not seen["lang"]:
        return 0.0  # a name that doesn't say Arabic is not the Arabic one
    return 96.0
