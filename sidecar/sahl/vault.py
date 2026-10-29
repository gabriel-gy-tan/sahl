"""The residents' own documents, read once and kept on this computer.

Every reading is kept per document file, with a PNG crop of the line it came from, in SQLite under
SAHL_HOME (default: %APPDATA%\\Sahl on Windows, ~/Library/Application Support/Sahl on macOS).
Documents are grouped into people by birth date and name, and a form asks for values in the order of
sources it prefers.
The public form guides never touch this store.

A value is "verified" only when something other than one reading backs it: a check digit in the
machine-readable zone, or the local AI and the printed text agreeing. Unverified values are shown,
never typed.
"""
import base64
import os
import re
import shutil
import sqlite3
import sys
import threading
import time
from io import BytesIO
from pathlib import Path

import numpy as np
from PIL import Image
from rapidfuzz import fuzz

from . import ai, ocr

MONTHS = "JAN FEB MAR APR MAY JUN JUL AUG SEP OCT NOV DEC".split()
# ICAO code → (country, nationality). ponytail: the common UAE resident nationalities; load the full ICAO list when one is missing
NATIONS = {
    "IND": ("India", "Indian"), "PAK": ("Pakistan", "Pakistani"), "BGD": ("Bangladesh", "Bangladeshi"),
    "PHL": ("Philippines", "Filipino"), "LKA": ("Sri Lanka", "Sri Lankan"), "NPL": ("Nepal", "Nepalese"),
    "ARE": ("United Arab Emirates", "Emirati"), "SAU": ("Saudi Arabia", "Saudi"), "OMN": ("Oman", "Omani"),
    "EGY": ("Egypt", "Egyptian"), "JOR": ("Jordan", "Jordanian"), "SYR": ("Syria", "Syrian"), "LBN": ("Lebanon", "Lebanese"),
    "IRQ": ("Iraq", "Iraqi"), "YEM": ("Yemen", "Yemeni"), "PSE": ("Palestine", "Palestinian"), "SDN": ("Sudan", "Sudanese"),
    "MAR": ("Morocco", "Moroccan"), "TUN": ("Tunisia", "Tunisian"), "DZA": ("Algeria", "Algerian"), "IRN": ("Iran", "Iranian"),
    "AFG": ("Afghanistan", "Afghan"), "TUR": ("Turkey", "Turkish"), "CHN": ("China", "Chinese"), "IDN": ("Indonesia", "Indonesian"),
    "MYS": ("Malaysia", "Malaysian"), "THA": ("Thailand", "Thai"), "VNM": ("Vietnam", "Vietnamese"),
    "NGA": ("Nigeria", "Nigerian"), "KEN": ("Kenya", "Kenyan"), "ETH": ("Ethiopia", "Ethiopian"), "UGA": ("Uganda", "Ugandan"),
    "ZAF": ("South Africa", "South African"), "GBR": ("United Kingdom", "British"), "USA": ("United States", "American"),
    "CAN": ("Canada", "Canadian"), "AUS": ("Australia", "Australian"), "FRA": ("France", "French"), "DEU": ("Germany", "German"),
    "RUS": ("Russia", "Russian"), "UKR": ("Ukraine", "Ukrainian"), "KAZ": ("Kazakhstan", "Kazakh"), "UZB": ("Uzbekistan", "Uzbek"),
}
EID = re.compile(r"784-?\d{4}-?\d{7}-?\d")
ID_WORDS = re.compile(r"passport|identity|emirates|resident|nationality|surname|given name|date of expiry|place of birth"
                      r"|place of issue|جواز|هوية|الجنسية", re.I)
FORCED_PAGES = 3  # when one page of a document is an ID, the AI also reads its first pages: OCR can miss the words
# ponytail: an ID copy buried past this page of a long scan is missed; raise it if real folders have those
SCAN_LIMIT = 5  # scanned pages OCR'd before giving up on a document with no ID signs
# OCR mixes letters and digits in the MRZ; each field is known to be one or the other
TO_ALPHA = str.maketrans("0125861", "OIZSBGI")
TO_DIGIT = str.maketrans("OQDILZSBG", "001112586")


def home() -> Path:
    """Where Sahl keeps its vault database and settings; SAHL_HOME overrides it (tests use a temp folder)."""
    if p := os.environ.get("SAHL_HOME"):
        p = Path(p)
    elif sys.platform == "win32":
        p = Path(os.environ.get("APPDATA", Path.home() / "AppData/Roaming")) / "Sahl"
    elif sys.platform == "darwin":
        p = Path.home() / "Library/Application Support/Sahl"
    else:
        p = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "Sahl"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _db():
    db = sqlite3.connect(home() / "vault.db")
    if db.execute("pragma user_version").fetchone()[0] < 2:  # older dev formats: rebuilt from the documents folder
        for t in ("vals", "files", "people", "readings"):
            db.execute(f"drop table if exists {t}")
        db.execute("pragma user_version = 3")
    if db.execute("pragma user_version").fetchone()[0] < 3:  # 3 adds given/surname: re-read only identity documents
        if db.execute("select 1 from sqlite_master where name = 'files'").fetchone():
            db.execute("update files set mtime = 0 where doc_type in ('passport', 'eid')")
        db.execute("pragma user_version = 3")
    db.execute("create table if not exists people (id integer primary key, name text, first text, last text, dob text)")
    db.execute("create table if not exists files (path text primary key, size int, mtime int, person int, doc_type text,"
               " ai_pending int default 0)")
    if "ai_pending" not in [r[1] for r in db.execute("pragma table_info(files)")]:
        db.execute("alter table files add column ai_pending int default 0")
    db.execute("create table if not exists readings (path text, key text, value text, verified int, crop blob,"
               " primary key (path, key))")
    return db


def check_digit(s: str) -> str:
    """ICAO 9303 check digit."""
    v = lambda c: int(c) if c.isdigit() else 0 if c == "<" else ord(c) - 55
    return str(sum(v(c) * (7, 3, 1)[i % 3] for i, c in enumerate(s)) % 10)


def _date(yymmdd: str, future: bool) -> str:
    yy, mm, dd = int(yymmdd[:2]), yymmdd[2:4], yymmdd[4:]
    year = 2000 + yy if future or yy <= time.gmtime().tm_year % 100 else 1900 + yy
    return f"{dd}/{mm}/{year}"


def _letters(s: str) -> str:
    return re.sub(r"[^A-Z]", "", s.upper())


def _nationality(code: str) -> str | None:
    n = NATIONS.get(code.translate(TO_ALPHA))
    return n[1] if n else None


def _mrz_name(field: str) -> str:
    surname, _, given = field.partition("<<")
    return " ".join(given.replace("<", " ").split() + surname.replace("<", " ").split())


def parse_mrz(l1: str, l2: str) -> dict:
    """TD3 passport MRZ → {key: (value, verified)}. The name isn't covered by any check digit, so it is never verified here."""
    l2 = l2[:13] + l2[13:20].translate(TO_DIGIT) + l2[20] + l2[21:28].translate(TO_DIGIT) + l2[28:]
    num, dob, exp, pers = l2[0:9], l2[13:19], l2[21:27], l2[28:42]
    composite = check_digit(l2[0:10] + l2[13:20] + l2[21:43]) == l2[43]
    out = {
        "name": (_mrz_name(l1[5:].translate(TO_ALPHA)), False),
        "passport.number": (num.rstrip("<"), check_digit(num) == l2[9] and composite),
        "dob": (_date(dob, future=False), check_digit(dob) == l2[19] and composite),
        "passport.expiry": (_date(exp, future=True), check_digit(exp) == l2[27] and composite),
    }
    nat = _nationality(l2[10:13])
    if nat:
        out["nationality"] = (nat, True)
    return out


def parse_td1(l1: str, l2: str, l3: str) -> dict:
    """TD1 MRZ on the back of an Emirates ID → {key: (value, verified)}."""
    l2 = l2[0:7].translate(TO_DIGIT) + l2[7] + l2[8:15].translate(TO_DIGIT) + l2[15:]
    composite = check_digit(l1[5:30] + l2[0:7] + l2[8:15] + l2[18:29]) == l2[29]
    out = {
        "name": (_mrz_name(l3.translate(TO_ALPHA)), False),
        "dob": (_date(l2[0:6], future=False), check_digit(l2[0:6]) == l2[6] and composite),
        "eid.expiry": (_date(l2[8:14], future=True), check_digit(l2[8:14]) == l2[14] and composite),
    }
    m = EID.search(l1[15:30].translate(TO_DIGIT))
    if m:
        out["eid.number"] = (_eid_format(m.group()), composite)
    nat = _nationality(l2[15:18])
    if nat:
        out["nationality"] = (nat, True)
    return out


def _eid_format(s: str) -> str:
    d = re.sub(r"\D", "", s)
    return f"{d[:3]}-{d[3:7]}-{d[7:14]}-{d[14]}"


def _printed(value: str, text: str) -> bool:
    """Every word of the value appears in the page's own OCR text: the AI didn't invent it."""
    words = [w for w in re.split(r"[\s,]+", value.upper()) if w]
    return bool(words) and all(fuzz.partial_ratio(w, text) >= 90 for w in words)


def _printed_name(lines, field: str) -> tuple[str, str] | None:
    """(given names, surname) from the printed lines, when they match the MRZ name field.

    The MRZ spells the name but OCR reads its "<" fillers as letters (KOMALKVIJAY); the printed
    lines have the real spacing. Label words ("Surname") are dropped because the MRZ doesn't contain them.
    """
    surname, _, given = field.partition("<<")
    parts = []
    for part in (given, surname):
        want = _letters(part)
        if not want:
            return None
        best = None
        for t, _ in lines:
            if "<" in t:
                continue  # the MRZ itself
            words = [w for w in t.upper().replace(",", " ").split()
                     if len(_letters(w)) >= 2 and fuzz.partial_ratio(_letters(w), want) >= 90]
            got = " ".join(words)
            score = fuzz.ratio(_letters(got), want)
            if words and score >= 88 and (not best or score > best[0]):
                best = (score, got)
        if not best:
            return None
        parts.append(best[1])
    return parts[0], parts[1]


def _shown_as(key, value):
    """How the value is printed in the document's visual zone, to find the line for its crop."""
    if key.endswith((".dob", ".expiry")):
        d, m, y = value.split("/")
        return f"{d} {MONTHS[int(m) - 1]} {y}"
    return value.upper()


def _mrz_lines(flat, width):
    return [i for i, (t, _) in enumerate(flat) if len(t) == width and re.fullmatch(r"[A-Z0-9<]+", t)]


def _read_page(gray: np.ndarray, lines=None, force: bool = False) -> tuple[str, dict, bool]:
    """(document type, {key: (value, verified, crop PNG bytes or None)}, AI needed but failed) for one page.

    Name, birth date and nationality are kept per document type (passport.name, eid.name, other.name)
    so a form can ask for the one it wants: "as in passport" means the passport's.
    """
    lines = ocr.lines(gray) if lines is None else lines
    flat = [(t.replace(" ", "").upper(), b) for t, b in lines]
    text = " ".join(t for t, _ in lines).upper()
    found, boxes = {}, {}

    td3 = _mrz_lines(flat, 44)
    if len(td3) >= 2 and flat[td3[0]][0].startswith("P"):
        found.update(parse_mrz(flat[td3[0]][0], flat[td3[1]][0]))
        boxes = {k: flat[td3[0 if k == "name" else 1]][1] for k in found}
    td1 = _mrz_lines(flat, 30)
    if len(td1) >= 3 and flat[td1[0]][0][2:5] == "ARE":
        for k, v in parse_td1(*(flat[i][0] for i in td1[:3])).items():
            found.setdefault(k, v)
            boxes.setdefault(k, flat[td1[0]][1])
    printed_eid = next(((_eid_format(m.group()), b) for t, b in flat if (m := EID.search(t))), None)

    if not (force or found or printed_eid or ID_WORDS.search(text)):
        return "other", {}, False  # not an identity document: don't spend an AI call on it

    mrz_name = next((flat[ls[i]][0] for ls, i in ((td3, 0), (td1, 2)) if len(ls) > i), None)
    if mrz_name:
        field = mrz_name[5:] if len(mrz_name) == 44 else mrz_name
        printed = _printed_name(lines, field.translate(TO_ALPHA))
        if printed:  # the MRZ's "<<" also says where the surname ends, for forms with separate boxes
            given, surname = printed
            found.update(name=(f"{given} {surname}", True), given=(given, True), surname=(surname, True))

    # the AI (seconds per page) only reads what the check digits and the printed text couldn't settle
    settled = found.get("name", ("", False))[1] and "nationality" in found and not (
        printed_eid and not found.get("eid.number", ("", False))[1])
    read = {} if settled else ai.read_page(gray)
    ai_failed = read is None
    read = read or {}
    if read.get("full_name") and not found.get("name", ("", False))[1]:
        name = _given_first(read["full_name"].upper())
        mrz = found.get("name", ("", False))[0]
        # the MRZ name has no check digit and OCR reads its "<" fillers as letters, so it only confirms
        backed = (mrz and fuzz.ratio(_letters(name), _letters(mrz)) >= 88) or _printed(name, text)
        found["name"] = (name, bool(backed))
    if "nationality" not in found and read.get("nationality"):
        n = read["nationality"].strip().title()
        known = next((d for c, d in NATIONS.values() if n in (c, d)), None)
        found["nationality"] = (known or n, bool(known) and _printed(n, text))
    if "dob" not in found and read.get("date_of_birth"):
        found["dob"] = (read["date_of_birth"], _printed_date(read["date_of_birth"], text))
    if "passport.number" not in found and read.get("passport_number"):
        pp = read["passport_number"].upper().replace(" ", "")
        found["passport.number"] = (pp, pp in text.replace(" ", ""))  # no MRZ: the AI and the page's own text must agree
    ai_eid = re.sub(r"\D", "", read.get("emirates_id_number", ""))
    if printed_eid:
        num, box = printed_eid
        prev = found.get("eid.number")  # from the card's MRZ, when the back is on this page
        found["eid.number"] = (num, bool(prev and prev[0] == num) or ai_eid == re.sub(r"\D", "", num))
        boxes["eid.number"] = box
    elif "eid.number" not in found and len(ai_eid) == 15 and ai_eid.startswith("784"):
        # OCR broke the number up (spaces, line wrap): the AI's reading counts only if the page's digits contain it
        found["eid.number"] = (_eid_format(ai_eid), ai_eid in re.sub(r"\D", "", text))
    if read.get("doc_type") == "passport" and read.get("expiry_date") and "passport.expiry" not in found:
        found["passport.expiry"] = (read["expiry_date"], _printed_date(read["expiry_date"], text))

    doc = ("passport" if td3 or read.get("doc_type") == "passport" else
           "eid" if td1 or printed_eid or read.get("doc_type") == "emirates_id" or "eid.number" in found else "other")
    img = Image.fromarray(gray)
    out = {}
    for k, (v, ok) in found.items():
        typed = f"{doc}.{k}" if k in ("name", "given", "surname", "dob", "nationality") else k
        box = boxes.get(k)
        try:
            best = max(lines, key=lambda l: fuzz.ratio(l[0].upper(), _shown_as(typed, v)))
            if fuzz.ratio(best[0].upper(), _shown_as(typed, v)) >= 85:
                box = best[1]
        except (ValueError, IndexError):
            pass
        png = None
        if box:
            x0, y0, x1, y1 = box
            pad = (y1 - y0) * 0.6
            buf = BytesIO()
            img.crop((max(0, x0 - pad), max(0, y0 - pad), x1 + pad, y1 + pad)).save(buf, "PNG")
            png = buf.getvalue()
        out[typed] = (v, ok, png)
    return doc, out, ai_failed


def _given_first(name: str) -> str:
    """'REBELLO, EDEN M' (surname first, as on US forms) → 'EDEN M REBELLO'."""
    last, comma, given = name.partition(",")
    return f"{given.strip()} {last.strip()}".strip() if comma else name.strip()


def _printed_date(dmy: str, text: str) -> bool:
    try:
        d, m, y = dmy.split("/")
        return any(s in text for s in (f"{d} {MONTHS[int(m) - 1]} {y}", f"{d}/{m}/{y}", f"{d}.{m}.{y}", f"{d}-{m}-{y}"))
    except (ValueError, IndexError):
        return False


def read_document(path) -> tuple[str, dict, bool]:
    """(document type, {key: (value, verified, crop)}, AI failed on a page) for one image or PDF.

    A verified reading beats an unverified one.
    """
    doc, found, ai_failed = "other", {}, False
    pdf = str(path).lower().endswith(".pdf")
    layers = ocr.pdf_text(path) if pdf else [None]  # digital pages come with their text: no rendering, no OCR
    pages, looks = [], []  # (gray or None until needed, lines) for each page looked at
    for i, layer in enumerate(layers):
        if layer is None and i >= SCAN_LIMIT and not looks:
            break  # a long scan with no ID in its first pages: the rest isn't read
        gray = None if layer is not None else ocr.pdf_page(path, i) if pdf else ocr.image(path)
        lines = layer if layer is not None else ocr.lines(gray)
        pages.append((gray, lines))
        if _looks_like_id(lines):
            looks.append(i)
    for i, (gray, lines) in enumerate(pages):
        if i not in looks and not (looks and i < FORCED_PAGES):
            continue
        if gray is None:
            gray = ocr.pdf_page(path, i)  # the AI and the source crops need the picture
        t, page, failed = _read_page(gray, lines, force=True)
        ai_failed |= failed
        if page and doc == "other":
            doc = t
        for k, v in page.items():
            if k not in found or (v[1] and not found[k][1]):
                found[k] = v
    return doc, found, ai_failed


def _looks_like_id(lines) -> bool:
    texts = [t for t, _ in lines]
    flat = [t.replace(" ", "").upper() for t in texts]
    return any(EID.search(t) or (len(t) in (30, 44) and "<" in t) for t in flat) or bool(ID_WORDS.search(" ".join(texts)))


def _holder(found: dict) -> tuple[str | None, str | None]:
    """The document holder's name and birth date, from whichever document type this was."""
    pick = lambda k: next((found[f"{d}.{k}"][0] for d in ("passport", "eid", "other") if f"{d}.{k}" in found), None)
    return pick("name"), pick("dob")


def _same_name_part(a: str, b: str) -> bool:
    return fuzz.ratio(a, b) >= 85  # Mohammed / Mohammad


def _person(db, name: str | None, dob: str | None, doc: str) -> int:
    """The person a document belongs to.

    Names alone mislead: an Emirates ID adds the father's name, a US form puts the surname first, and a
    father's name can sit inside his child's. So a birth date decides when both sides have one, with
    the first given name as a sanity check; otherwise first and last names must both match.
    """
    words = [_letters(w) for w in (name or "").split() if _letters(w)]
    first, last = (words[0], words[-1]) if words else ("", "")
    for pid, pname, pfirst, plast, pdob in db.execute("select id, name, first, last, dob from people").fetchall():
        if dob and pdob:
            same = dob == pdob and (not first or not pfirst or _same_name_part(first, pfirst))
        else:
            same = bool(first) and _same_name_part(first, pfirst or "") and _same_name_part(last, plast or "")
        if same:
            if dob and not pdob:
                db.execute("update people set dob=? where id=?", (dob, pid))
            if name and doc == "passport":  # the passport's spelling is the one shown
                db.execute("update people set name=?, first=?, last=? where id=?", (name.title(), first, last, pid))
            return pid
    return db.execute("insert into people (name, first, last, dob) values (?,?,?,?)",
                      ((name or "Unknown").title(), first, last, dob)).lastrowid


def import_document(path) -> int | None:
    """Reads one document into the vault, replacing what was read from it before. Returns the holder's person id."""
    path = Path(path)
    doc, found, ai_failed = read_document(path)
    st = path.stat()
    with _db() as db:
        db.execute("delete from readings where path=?", (str(path),))
        holder = _holder(found)
        pid = _person(db, *holder, doc) if any(holder) else None  # no name or birth date: belongs to no one yet
        db.execute("insert or replace into files values (?,?,?,?,?,?)",
                   (str(path), st.st_size, int(st.st_mtime), pid, doc, int(ai_failed)))
        for k, (v, ok, png) in found.items():
            db.execute("insert into readings values (?,?,?,?,?)", (str(path), k, v, int(ok), png))
    return pid


DOCUMENTS = {".png", ".jpg", ".jpeg", ".pdf"}
_IMPORT_LOCK = threading.Lock()
PROGRESS = {"done": 0, "total": 0}  # read by the panel while documents are read


def sync(folder) -> tuple[list[int], list[str]]:
    """Brings the vault in line with a folder: reads new and changed documents, forgets removed ones.

    Returns (people found, files that couldn't be opened). One sync at a time, so the background
    scan and a drop never race on the store or pdfium.
    """
    with _IMPORT_LOCK:
        return _sync(Path(folder))


def _sync(root: Path) -> tuple[list[int], list[str]]:
    files = sorted(f for f in root.rglob("*") if f.suffix.lower() in DOCUMENTS and not f.name.startswith("."))
    with _db() as db:
        known = {p: (s, m) for p, s, m in db.execute("select path, size, mtime from files")}
        pending = {p for (p,) in db.execute("select path from files where ai_pending")}
        for p in set(known) - {str(f) for f in files}:  # removed from the folder (or from an older location)
            db.execute("delete from readings where path=?", (p,))
            db.execute("delete from files where path=?", (p,))
        db.execute("delete from people where id not in (select person from files where person is not null)")
    retry = pending if pending and ai.available() else set()  # the AI failed on these before: try again now it answers
    todo = [f for f in files if known.get(str(f)) != (f.stat().st_size, int(f.stat().st_mtime)) or str(f) in retry]
    PROGRESS.update(done=0, total=len(todo))
    skipped = []
    for f in todo:
        try:
            import_document(f)
        except Exception:  # locked or damaged PDF, unreadable image: skip it, keep going
            skipped.append(f.name)
        PROGRESS["done"] += 1
    found = [r[0] for r in _db().execute("select distinct person from files where person is not null")]
    return found, skipped


def people() -> list[dict]:
    return [{"id": str(i), "name": n} for i, n in _db().execute("select id, name from people order by name")]


def get(keys, person):
    """{value, verified, source, crop (data URL)} for one person, from the first of `keys` that has a value.

    A verified value under an earlier key wins; then any verified value; then the first unverified one.
    """
    if not keys or person is None:
        return None
    keys = [keys] if isinstance(keys, str) else keys
    rows = []
    for k in keys:
        rows += _db().execute("select r.value, r.verified, r.path, r.crop from readings r join files f using (path)"
                              " where f.person=? and r.key=? order by r.verified desc, f.mtime desc",
                              (int(person), k)).fetchall()
    if not rows:
        return None
    v, ok, path, crop = next((r for r in rows if r[1]), rows[0])
    data = "data:image/png;base64," + base64.b64encode(crop).decode() if crop else None
    return {"value": v, "verified": bool(ok), "source": Path(path).name, "crop": data}


def forget_all():
    """Deletes every stored reading and person (not the documents themselves)."""
    with _db() as db:
        for t in ("readings", "files", "people"):
            db.execute(f"delete from {t}")
    shutil.rmtree(home() / "crops", ignore_errors=True)  # where older versions kept crop images
