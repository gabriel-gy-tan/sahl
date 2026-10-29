from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw, ImageFont

from sahl import server, vault

ROOT = Path(__file__).resolve().parents[2]
BLANK = np.full((1964, 3024), 255, np.uint8)  # a second, empty monitor to the left
PORTAL = np.array(Image.open(Path(__file__).parent / "fixtures/portal.png").convert("L"))
# input rectangles in fixtures/portal.png, measured from the rendered page
INPUTS = {
    "full_name": (263, 368, 1137, 428), "dob": (263, 490, 1137, 549), "nationality": (263, 611, 1137, 670),
    "passport_number": (263, 815, 1137, 874), "passport_expiry": (263, 936, 1137, 995),
    "emirates_id": (263, 1058, 1137, 1116), "centre": (263, 1261, 1137, 1291),
}


@pytest.fixture
def client(fake_ai):
    typed, page = [], PORTAL.copy()

    def typer(box, value):  # draws the value into the box, like a real page would show it
        typed.append((box, value))
        if value.startswith("MISS"):
            return  # simulates a click that landed in the wrong box
        img = Image.fromarray(page)
        ImageDraw.Draw(img).text((box[0] + 12, box[1] + 14), value, fill=0, font=ImageFont.load_default(26))
        page[:] = np.array(img)

    app = server.create_app("t0k", screen=lambda: [(BLANK, 2.0, (-1512, 0, 1512, 982)), (page, 1.0, (0, 0, 1400, 1400))], typer=typer)
    c = TestClient(app, headers={"x-sahl-token": "t0k"})
    c.typed = typed
    return c


def test_check_digit_icao_example():
    assert vault.check_digit("L898902C3") == "6"  # ICAO 9303 part 4 specimen
    assert vault.check_digit("740812") == "2"


# what the local vision model says about each invented document (tests don't need Ollama running)
def _answer(doc, name, nat, dob, pp="", eid="", exp=""):
    return {"doc_type": doc, "full_name": name, "nationality": nat, "date_of_birth": dob,
            "passport_number": pp, "emirates_id_number": eid, "expiry_date": exp}


AI_ANSWERS = [  # (text on the page, answer); the first match wins
    ("NONIMMIGRANT", _answer("other", "KUNNUMMAL, MOHAMMED RAFEEQ", "India", "14/03/1985", "X1234567")),
    ("784-1985", _answer("emirates_id", "MOHAMMAD RAFEEQ ABDULLA KUNNUMMAL", "Indian", "14/03/1985", eid="784-1985-0000001-0")),
    ("784-1962", _answer("emirates_id", "PRIYA ANIL MENON", "Indian", "05/08/1962", eid="784-1962-0000002-7")),
    ("Y1112223", _answer("passport", "ABDULLA KUNNUMMAL", "Indian", "10/02/1955", "Y1112223", exp="06/06/2030")),
    ("Z7654321", _answer("passport", "PRIYA ANIL MENON", "Indian", "05/08/1962", "Z7654321", exp="17/01/2029")),
    ("X1234567", _answer("passport", "MOHAMMED RAFEEQ KUNNUMMAL", "Indian", "14/03/1985", "X1234567", exp="02/09/2031")),
]


@pytest.fixture(autouse=True)
def fake_ai(monkeypatch, tmp_path):
    from sahl import ai, ocr
    monkeypatch.setenv("SAHL_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("SAHL_LIBRARY", str(tmp_path / "library"))  # never the real ~/Documents/Sahl
    def read_page(gray):
        text = " ".join(t for t, _ in ocr.lines(gray))
        return next((a for k, a in AI_ANSWERS if k in text), None)
    monkeypatch.setattr(ai, "read_page", read_page)


def test_mrz_flags_a_corrupted_digit():
    l1 = "P<INDKUNNUMMAL<<MOHAMMED<RAFEEQ<<<<<<<<<<<<<"
    l2 = "X1234567<7IND8503149M3109029<<<<<<<<<<<<<<04"
    good = vault.parse_mrz(l1, l2)
    assert good["passport.number"] == ("X1234567", True)
    assert good["dob"] == ("14/03/1985", True)
    assert good["passport.expiry"] == ("02/09/2031", True)
    assert good["name"] == ("MOHAMMED RAFEEQ KUNNUMMAL", False)  # no check digit covers the name
    bad = vault.parse_mrz(l1, l2.replace("X1234567", "X1234561"))
    assert bad["passport.number"][1] is False


def test_mrz_ocr_slips_are_repaired():
    # "1ND" for IND, and an O read in a date: both fields are known letters / digits
    l2 = "X1234567<71ND85O3149M3109029<<<<<<<<<<<<<<04"
    out = vault.parse_mrz("P<INDKUNNUMMAL<<MOHAMMED<RAFEEQ<<<<<<<<<<<<<", l2)
    assert out["nationality"] == ("Indian", True) and out["dob"] == ("14/03/1985", True)


def test_name_comes_from_the_printed_page_not_the_mrz(monkeypatch):
    # OCR reads the "<" between given names as K; the AI's printed reading is used, and the MRZ confirms it
    from sahl import ocr
    real = ocr.lines
    monkeypatch.setattr(ocr, "lines", lambda g: [(t.replace("MOHAMMED<RAFEEQ", "MOHAMMEDKRAFEEQ"), b) for t, b in real(g)])
    name, ok, _ = vault.read_document(ROOT / "demo/samples/passport.png")[1]["passport.name"]
    assert (name, ok) == ("MOHAMMED RAFEEQ KUNNUMMAL", True)


def test_passport_needs_no_ai_but_an_id_front_does(monkeypatch):
    from sahl import ai
    calls = []
    monkeypatch.setattr(ai, "read_page", lambda g: calls.append(1))
    got = vault.read_document(ROOT / "demo/samples/passport.png")[1]
    # check digits verify the numbers, and the printed name matching the MRZ verifies the name: no AI call
    assert got["passport.number"][:2] == ("X1234567", True)
    assert got["passport.name"][:2] == ("MOHAMMED RAFEEQ KUNNUMMAL", True) and calls == []
    assert got["passport.given"][:2] == ("MOHAMMED RAFEEQ", True) and got["passport.surname"][:2] == ("KUNNUMMAL", True)
    front = vault.read_document(ROOT / "demo/samples/emirates_id.png")[1]
    assert calls and front["eid.number"][1] is False and "eid.name" not in front  # nothing backs it without the AI


def test_split_name_boxes_are_found():
    # DS-160 style: separate Surnames / Given Names boxes, and a native-alphabet name that isn't ours to fill
    import json
    from sahl import match
    guide = json.loads((ROOT / "guides/any-form.json").read_text(encoding="utf-8"))
    lines = [("Surnames", (100, 100, 300, 130)), ("Given Names", (100, 400, 320, 430)),
             ("Full Name in Native Alphabet", (100, 600, 600, 630))]
    assert sorted(f["id"] for f in match.match(lines, guide)) == ["given_names", "surname"]


def test_token_required(client):
    assert client.get("/guides", headers={"x-sahl-token": "wrong"}).status_code == 403
    assert TestClient(client.app).get("/guides").status_code == 403


def test_vault_lives_in_appdata_on_windows(monkeypatch, tmp_path):
    import sys
    monkeypatch.delenv("SAHL_HOME", raising=False)
    monkeypatch.setenv("APPDATA", str(tmp_path / "roaming"))
    monkeypatch.setattr(sys, "platform", "win32")
    assert vault.home() == tmp_path / "roaming/Sahl"


def test_forget_uses_the_recycle_bin_off_macos(monkeypatch, tmp_path):
    import sys
    import types
    from sahl import library
    lib = tmp_path / "library"
    lib.mkdir()
    (lib / "passport.png").write_bytes(b"x")
    (lib / ".keep").write_bytes(b"")
    monkeypatch.setenv("SAHL_LIBRARY", str(lib))
    sent = []
    monkeypatch.setitem(sys.modules, "send2trash", types.SimpleNamespace(send2trash=sent.append))
    monkeypatch.setattr(sys, "platform", "win32")
    library.forget()
    assert sent == [str(lib / "passport.png")]  # dot files stay; a real Windows run puts it in the Recycle Bin


def test_fill_clicks_physical_pixels_on_windows(fake_ai, monkeypatch):
    import sys
    typed, page = [], PORTAL.copy()

    def typer(box, value):
        typed.append(box)
        img = Image.fromarray(page)
        ImageDraw.Draw(img).text((box[0] + 12, box[1] + 14), value, fill=0, font=ImageFont.load_default(26))
        page[:] = np.array(img)

    app = server.create_app("t0k", screen=lambda: [(page, 2.0, (0, 0, 700, 700))], typer=typer)
    c = TestClient(app, headers={"x-sahl-token": "t0k"})
    c.post("/vault/import", json={"path": str(ROOT / "demo/samples/passport.png")})
    field = next(f for f in c.post("/read", json={"guide": "medical-fitness"}).json()["fields"] if f["id"] == "full_name")
    monkeypatch.setattr(sys, "platform", "win32")  # pynput/SetCursorPos wants pixels on a DPI-aware Windows process
    assert c.post("/fill", json={"field_id": "full_name"}).json()["landed"] is True
    assert typed == [tuple(v * 2 for v in field["input_box"])]


def test_import_says_what_it_read_and_the_summary_has_no_values(client):
    passport = str(ROOT / "demo/samples/passport.png")
    r = client.post("/vault/import", json={"path": passport}).json()
    assert r["read"] == [{"person": r["people"][0], "type": "passport"}]
    assert client.post("/vault/import", json={"path": passport}).json()["read"] == []  # nothing new to read
    s = client.get("/vault/summary").json()
    assert s == {"people": [{"id": s["people"][0]["id"], "name": r["people"][0], "docs": {"passport": 1}}], "unmatched": 0}
    fields = {f["id"]: f for f in client.post("/read", json={"guide": "medical-fitness"}).json()["fields"]}
    assert fields["emirates_id"]["vault"] is None and fields["emirates_id"]["needs"] == "eid"  # the panel asks for it


def test_family_in_one_folder(client):
    r = client.post("/vault/import", json={"path": str(ROOT / "demo/samples")}).json()
    # one entry per person, though the son's name appears three ways (passport, ID with his father's
    # name added, visa form surname first) and the father's name sits inside the son's
    assert sorted(r["people"]) == ["Abdulla Kunnummal", "Mohammed Rafeeq Kunnummal", "Priya Anil Menon"]
    people = {p["name"]: p["id"] for p in client.get("/people").json()}
    unsure = client.post("/read", json={"guide": "medical-fitness"}).json()
    assert unsure["person"] is None and all(f["vault"] is None for f in unsure["fields"])  # three people: Sahl asks
    read = lambda who: {f["id"]: f["vault"] for f in client.post(
        "/read", json={"guide": "medical-fitness", "person": people[who]}).json()["fields"]}
    son = read("Mohammed Rafeeq Kunnummal")
    assert son["full_name"]["value"] == "MOHAMMED RAFEEQ KUNNUMMAL"  # "as in passport": the passport's, not the ID's or the visa form's
    assert son["full_name"]["source"] == "passport.png"
    assert son["emirates_id"]["value"] == "784-1985-0000001-0" and son["emirates_id"]["verified"]
    mum = read("Priya Anil Menon")
    assert mum["passport_number"]["value"] == "Z7654321" and mum["dob"]["value"] == "05/08/1962"
    dad = read("Abdulla Kunnummal")
    assert dad["passport_number"]["value"] == "Y1112223" and dad["emirates_id"] is None


def test_visa_form_name_is_turned_given_first():
    doc, got, _ = vault.read_document(ROOT / "demo/samples/visa_form.png")
    assert doc == "other" and got["other.name"][0] == "MOHAMMED RAFEEQ KUNNUMMAL"


def test_documents_folder_follows_adds_and_removals(client, tmp_path):
    import shutil
    lib = tmp_path / "library"
    lib.mkdir(exist_ok=True)
    shutil.copy(ROOT / "demo/samples/passport_2.png", lib)
    assert client.post("/vault/sync").json()["people"] == ["Priya Anil Menon"]
    (lib / "passport_2.png").unlink()  # removed from the folder: Sahl forgets it
    assert client.post("/vault/sync").json()["people"] == [] and client.get("/people").json() == []


def test_read_fill_flow(client):
    client.post("/vault/import", json={"path": str(ROOT / "demo/samples")})  # a whole folder
    me = {p["name"]: p["id"] for p in client.get("/people").json()}["Mohammed Rafeeq Kunnummal"]
    read = lambda **kw: client.post("/read", json={"guide": "medical-fitness", "person": me, **kw}).json()
    r = read()
    got = {f["id"]: f for f in r["fields"]}
    assert set(INPUTS) <= set(got) and "mobile" not in got  # mobile is below the fold
    for fid, (x0, y0, x1, y1) in INPUTS.items():
        bx0, by0, bx1, by1 = got[fid]["input_box"]
        cx, cy = (bx0 + bx1) / 2, (by0 + by1) / 2
        assert x0 < cx < x1 and y0 < cy < y1, fid
        assert by0 >= y0 - 4 and by1 <= y1 + 4, fid
    assert r["next"] == "full_name"
    assert r["monitor"] == [0, 0, 1400, 1400]  # picked the monitor that has the form
    assert got["passport_number"]["vault"]["value"] == "X1234567"
    assert got["emirates_id"]["vault"]["value"] == "784-1985-0000001-0"
    assert got["nationality"]["vault"]["value"] == "Indian"
    assert got["full_name"]["vault"]["crop"].startswith("data:image/png;base64,")

    r = client.post("/fill", json={"field_id": "full_name"})
    assert r.status_code == 200 and r.json()["landed"] is True
    assert client.typed[-1][1] == "MOHAMMED RAFEEQ KUNNUMMAL"
    assert client.post("/fill", json={"field_id": "centre"}).status_code == 422  # dropdowns stay show-only
    assert client.post("/fill", json={"field_id": "mobile"}).status_code == 404  # not on screen
    assert read()["next"] == "dob"
    hidden = read(exclude=[[0, 440, 1400, 480]])
    assert "dob" not in {f["id"] for f in hidden["fields"]}  # a blanked region is never read


def test_read_again_after_every_field_is_skipped_starts_over(client):
    client.post("/vault/import", json={"path": str(ROOT / "demo/samples")})
    read = lambda **kw: client.post("/read", json={"guide": "medical-fitness", **kw}).json()
    first = read()
    assert first["next"] == "full_name"
    for f in first["fields"]:
        assert client.post("/confirm", json={"field_id": f["id"]}).status_code == 200
    done = read()
    assert done["next"] is None and all(f["confirmed"] for f in done["fields"])
    again = read(restart=True)
    assert again["next"] == "full_name" and not any(f["confirmed"] for f in again["fields"])


@pytest.mark.parametrize("seen, want, expected", [
    ("Khan", "Khan", True),
    ("Khan|", "Khan", True),
    ("Last nameKhan", "Khan", True),
    ("Khaan", "Khan", True),
    ("KUNN", "KUNNUMMAL", True),  # a narrow box shows only the start of a long surname
    ("Khalid", "Khan", False),
    ("Last name", "Khan", False),
    ("", "Khan", False),
])
def test_landed_text_tolerates_ocr_noise(seen, want, expected):
    assert server._matches(seen, want) is expected


def test_fill_that_misses_does_not_advance(client, monkeypatch):
    client.post("/vault/import", json={"path": str(ROOT / "demo/samples/passport.png")})
    client.post("/read", json={"guide": "medical-fitness"})
    real = vault.get
    monkeypatch.setattr(vault, "get", lambda k, p: {**real(k, p), "value": "MISS" + real(k, p)["value"]} if real(k, p) else None)
    client.post("/read", json={"guide": "medical-fitness"})
    assert client.post("/fill", json={"field_id": "full_name"}).json()["landed"] is False
    assert client.post("/read", json={"guide": "medical-fitness"}).json()["next"] == "full_name"


def test_improvement_reports_are_off_by_default_and_hold_no_values(client, monkeypatch):
    import json
    client.post("/vault/import", json={"path": str(ROOT / "demo/samples/passport.png")})
    client.post("/read", json={"guide": "medical-fitness"})
    assert client.get("/improve").json() == {"on": False, "folder": client.get("/improve").json()["folder"], "reports": []}
    assert client.post("/improve", json={"on": True}).json()["on"] is True
    fields = client.post("/read", json={"guide": "medical-fitness"}).json()["fields"]
    real = vault.get
    monkeypatch.setattr(vault, "get", lambda k, p: {**real(k, p), "value": "MISS" + real(k, p)["value"]} if real(k, p) else None)
    client.post("/read", json={"guide": "medical-fitness"})
    client.post("/fill", json={"field_id": "full_name"})
    [r] = client.get("/improve").json()["reports"]
    assert (r["guide"], r["found"], r["missed"]) == ("medical-fitness", len(fields), 1)
    report = json.loads(r["text"])
    assert report["found"]["full_name"]["label"] == next(f["seen"] for f in fields if f["id"] == "full_name")
    values = [f["vault"]["value"] for f in fields if f["vault"]]
    assert values and not any(v in r["text"] for v in values)  # labels and positions only, never the person's details


def test_pdfs(tmp_path):
    fx = Path(__file__).parent / "fixtures"
    assert vault.read_document(fx / "passport_scan.pdf")[1]["passport.number"][:2] == ("X1234567", True)
    assert vault.read_document(fx / "eid_2pages.pdf")[1]["eid.number"][0] == "784-1985-0000001-0"  # found on page 2
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs/locked.pdf").write_bytes(b"%PDF-1.7 not really")
    found, skipped = vault.sync(tmp_path / "docs")
    assert found == [] and skipped == ["locked.pdf"]  # a bad file is reported, not fatal


def _crash(path):  # stands in for pdfium dying on a malformed PDF (quietly: no macOS crash dialog)
    import os
    os._exit(70)


def test_pdf_crash_stays_in_child(tmp_path):
    from concurrent.futures.process import BrokenProcessPool
    from sahl import ocr
    with pytest.raises(BrokenProcessPool):
        ocr._in_child(_crash, str(tmp_path / "bad.pdf"))
    assert ocr.pdf_page(Path(__file__).parent / "fixtures/passport_scan.pdf", 0).size  # a fresh helper takes over


def _text_pdf(lines):
    """A digital (not scanned) one-page PDF with these lines of text."""
    body = "BT /F1 14 Tf 72 720 Td " + " ".join(f"({t}) Tj 0 -24 Td" for t in lines) + " ET"
    objs = ["<</Type/Catalog/Pages 2 0 R>>", "<</Type/Pages/Kids[3 0 R]/Count 1>>",
            "<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]/Contents 4 0 R/Resources<</Font<</F1 5 0 R>>>>>>",
            f"<</Length {len(body)}>>stream\n{body}\nendstream", "<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>"]
    out, offsets = "%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj{o}endobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n" + "".join(f"{o:010} 00000 n \n" for o in offsets)
    return (out + f"trailer<</Size {len(objs) + 1}/Root 1 0 R>>\nstartxref\n{xref}\n%%EOF").encode()


def test_digital_pdfs_skip_ocr(tmp_path, monkeypatch):
    from sahl import ocr
    pdf = tmp_path / "statement.pdf"
    pdf.write_bytes(_text_pdf(["Monthly account statement", "Opening balance 1,200.00 AED"]))
    assert [t for t, _ in ocr.pdf_text(pdf)[0]] == ["Monthly account statement", "Opening balance 1,200.00 AED"]
    monkeypatch.setattr(ocr, "lines", lambda g: pytest.fail("OCR'd a page that has its own text"))
    monkeypatch.setattr(ocr, "pdf_page", lambda p, i: pytest.fail("rendered a page nothing needs"))
    assert vault.read_document(pdf) == ("other", {}, False)


def test_unchanged_files_are_not_read_again(client, monkeypatch):
    first = client.post("/vault/import", json={"path": str(ROOT / "demo/samples")}).json()
    monkeypatch.setattr(vault, "import_document", lambda f: pytest.fail(f"re-read {f}"))
    again = client.post("/vault/import", json={"path": str(ROOT / "demo/samples")}).json()
    assert again["people"] == first["people"]
    assert client.get("/vault/progress").json() == {"done": 0, "total": 0}  # nothing left to read


def test_a_failed_ai_reading_is_tried_again(client, tmp_path, monkeypatch):
    import shutil
    from sahl import ai
    lib = tmp_path / "library"
    lib.mkdir(exist_ok=True)
    shutil.copy(ROOT / "demo/samples/emirates_id_2.png", lib)  # an ID front: needs the AI
    working = ai.read_page
    monkeypatch.setattr(ai, "read_page", lambda g: None)  # the model hiccups
    assert client.post("/vault/sync").json()["people"] == []
    monkeypatch.setattr(ai, "read_page", working)
    monkeypatch.setattr(ai, "available", lambda: True)
    assert client.post("/vault/sync").json()["people"] == ["Priya Anil Menon"]  # read again, not left as empty
