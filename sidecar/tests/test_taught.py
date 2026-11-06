"""Boxes the guides don't know: the person tells Sahl once, and it is remembered under any spelling of the label."""
import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw, ImageFont

from sahl import ai, server, taught, vault


@pytest.fixture(autouse=True)
def home(monkeypatch, tmp_path):
    monkeypatch.setenv("SAHL_HOME", str(tmp_path / "home"))  # never the real vault
    monkeypatch.setenv("SAHL_LIBRARY", str(tmp_path / "library"))
    taught._asked.clear()  # what the model proposed earlier belongs to the earlier test's vault


def test_told_once_known_by_any_spelling_of_the_label():
    taught.teach("Company", "Acme Ltd", None)
    assert taught.get("company:", None)["value"] == "Acme Ltd"  # case and punctuation
    assert taught.get("Compary", None)["concept"] == "Company"  # a letter OCR dropped
    assert taught.get("Fax", None) is None
    taught.teach("Address Line 1", "1 Main Street", None)
    assert taught.get("Address Line 2", None) is None  # close in letters, a different box


def test_a_value_is_one_persons():
    taught.teach("Company", "Acme", "1")
    taught.teach("Company", "Beta", "2")
    assert taught.get("Company", "1")["value"] == "Acme" and taught.get("Company", "2")["value"] == "Beta"
    taught.teach("Fax", "123", None)  # told before any document: everyone's
    assert taught.get("Fax", "2")["value"] == "123"


def test_another_name_for_the_same_detail_once_the_person_agrees():
    taught.teach("Company", "Acme", None)
    assert taught.get("Workplace", None) is None
    assert taught.alias("Workplace", "Company") and taught.get("Workplace", None)["value"] == "Acme"
    assert not taught.alias("Employer", "Nothing")
    taught.teach("Workplace", "Acme Holdings", None)  # told again under the new name: the same detail, new value
    assert taught.get("Company", None)["value"] == "Acme Holdings"


def test_the_model_only_proposes_from_what_it_was_shown(monkeypatch):
    taught.teach("Company", "Acme", None)
    seen = {}

    def chat(body, timeout, tries=2):
        seen["prompt"] = body["messages"][0]["content"]
        return {"matches": [{"label": "Workplace", "means": "Company"}, {"label": "Invented", "means": "Company"},
                            {"label": "Fax", "means": "Salary"}]}
    monkeypatch.setattr(ai, "chat", chat)
    assert taught.similar(["Workplace", "Fax"], None) == {"Workplace": "Company"}
    assert "Company" in seen["prompt"] and "Acme" not in seen["prompt"]  # names go to the model, never the values
    monkeypatch.setattr(ai, "chat", lambda *a, **k: None)
    assert taught.similar(["Workplace"], None) == {}  # no model, no suggestion


def test_nothing_told_means_no_model_call(monkeypatch):
    monkeypatch.setattr(ai, "chat", lambda *a, **k: pytest.fail("asked the model with nothing to compare"))
    assert taught.similar(["Workplace"], None) == {}


def test_passwords_are_never_remembered():
    for label in ("Password", "Passcode", "PIN", "One-time code"):
        assert not taught.allowed(label)
    assert taught.allowed("Company") and taught.allowed("Social Security Number")
    assert all(taught.allowed(x) for x in ("Credit Card Number", "Card Verification Code", "Card Expiration Date", "Card User Name", "IBAN"))


def test_forgetting_one_and_everything():
    taught.teach("Company", "Acme", None)
    taught.alias("Workplace", "Company")
    taught.forget("Company")
    assert taught.get("Workplace", None) is None and taught.listing(None) == []
    taught.teach("Fax", "1", None)
    vault.forget_all()
    assert taught.listing(None) == []


def _form(*labels):
    """An invented form: each label with an empty box below it, like a portal's."""
    im = Image.new("L", (1600, 1000), 255)  # room to scroll in
    d, font = ImageDraw.Draw(im), ImageFont.load_default(28)
    for i, text in enumerate(labels):
        y = 60 + 140 * i
        d.text((100, y), text, fill=0, font=font)
        d.rectangle((100, y + 50, 700, y + 105), outline=150, width=2)
    return np.array(im)


@pytest.fixture
def client():
    page, typed, boxes = _form("Full name", "Company", "Password"), [], []
    def typer(box, value):  # draws the value into the box, like a real page would show it
        typed.append(value)
        boxes.append(box)
        if not value.startswith("MISS"):
            img = Image.fromarray(page)
            ImageDraw.Draw(img).text((box[0] + 12, box[1] + 10), value, fill=0, font=ImageFont.load_default(28))
            page[:] = np.array(img)

    app = server.create_app("t0k", screen=lambda: [(page.copy(), 1.0, (0, 0, 1600, page.shape[0]))], typer=typer)
    c = TestClient(app, headers={"x-sahl-token": "t0k"})
    c.page, c.typed, c.boxes = page, typed, boxes
    c.read = lambda: c.post("/read", json={"guide": "any-form"}).json()
    return c


def _unknown(r):
    return {f["label"]: f for f in r["fields"] if f.get("unknown")}


def test_an_unknown_box_is_asked_then_remembered_and_typed(client):
    u = _unknown(client.read())
    assert "Company" in u and u["Company"]["vault"] is None  # nothing told yet: the panel asks
    assert "Password" not in u  # never offered
    assert client.post("/taught", json={"label": "Company", "value": "Acme Ltd"}).json() == {"concept": "Company"}
    f = _unknown(client.read())["Company"]
    assert f["vault"]["value"] == "Acme Ltd" and f["vault"]["verified"] and f["id"] == "taught:company"
    assert client.post("/fill", json={"field_id": f["id"]}).status_code == 200
    assert client.typed == ["Acme Ltd"]  # typed like any verified value, into the box it was found beside
    assert client.post("/taught", json={"label": "Password", "value": "x"}).status_code == 422


def test_the_same_detail_under_another_name_is_offered_then_used(client, monkeypatch):
    client.post("/taught", json={"label": "Company", "value": "Acme Ltd"})
    client.page[:] = _form("Full name", "Workplace", "Password")
    monkeypatch.setattr(ai, "chat", lambda *a, **k: {"matches": [{"label": "Workplace", "means": "Company"}]})
    monkeypatch.setattr(taught, "_spawn", lambda fn, *a: fn(*a))  # the model is asked in the background; here, at once
    f = _unknown(client.read())["Workplace"]
    assert f["vault"] is None and f["suggest"] == {"concept": "Company", "value": "Acme Ltd"}  # asked, not assumed
    assert client.post("/taught/alias", json={"label": "Workplace", "concept": "Company"}).status_code == 200
    assert _unknown(client.read())["Workplace"]["vault"]["value"] == "Acme Ltd"
    assert client.get("/taught").json() == [{"concept": "Company", "value": "Acme Ltd", "labels": ["company", "workplace"]}]
    client.post("/taught/forget", json={"concept": "Company"})
    assert client.get("/taught").json() == []


def test_a_few_letters_that_ocr_cannot_read_still_land(client):
    client.read()
    client.post("/taught", json={"label": "Company", "value": "Mr."})
    client.read()
    assert client.post("/fill", json={"field_id": "taught:company"}).json()["landed"] is True  # the box visibly changed


def test_a_click_that_missed_does_not_land(client):
    client.read()
    client.post("/taught", json={"label": "Company", "value": "MISS"})
    client.read()
    assert client.post("/fill", json={"field_id": "taught:company"}).json()["landed"] is False  # nothing was drawn


def test_only_boxes_near_the_known_fields_are_asked_about():
    from sahl import match
    taken = [(300, 300, 500, 340)]
    lines = [("Menu", (20, 10, 80, 30)), ("Company", (100, 360, 250, 390))]
    gray = np.full((900, 900), 255, np.uint8)
    for y in (30, 390):  # a box under each label
        gray[y + 10:y + 12, 100:700] = gray[y + 50:y + 52, 100:700] = 150
        gray[y + 10:y + 52, 100:102] = gray[y + 10:y + 52, 698:700] = 150
    guide = {"fields": [{"aliases": ["Full name"]}]}
    got = match.unknown_boxes(lines, guide, gray, set(), taken)
    assert [u["label"] for u in got] == ["Company"]


def test_a_label_that_wraps_is_one_label():
    from sahl import match
    lines = [("Card Customer Service", (100, 100, 400, 125)), ("Phone", (330, 130, 400, 155)),
             ("Company", (100, 250, 250, 275)), ("Position", (100, 320, 250, 345))]  # rows a line apart stay apart
    assert [t for t, _ in match._wrapped(lines)] == ["Card Customer Service Phone", "Company", "Position"]


def test_fields_go_in_the_order_they_are_on_the_page():
    from sahl import match
    box = lambda x, y: {"input_box": (x, y, x + 200, y + 40)}
    two = [{"id": "r1", **box(600, 100)}, {"id": "l2", **box(100, 150)}, {"id": "l1", **box(100, 100)}, {"id": "l3", **box(100, 200)},
           {"id": "r2", **box(600, 150)}, {"id": "r3", **box(610, 200)}, {"id": "stray", **box(380, 260)}]
    assert [f["id"] for f in match.reading_order(two)] == ["l1", "l2", "l3", "r1", "r2", "r3", "stray"]  # down the left, then the right
    rows = [{"id": "b", **box(400, 100)}, {"id": "a", **box(100, 102)}, {"id": "c", **box(100, 160)}]
    assert [f["id"] for f in match.reading_order(rows)] == ["a", "b", "c"]  # short columns: row by row


def test_a_short_value_does_not_hide_labels_that_contain_it():
    from sahl import match
    gray = np.full((300, 900), 255, np.uint8)
    gray[40:42, 100:700] = gray[90:92, 100:700] = gray[40:92, 100:102] = gray[40:92, 698:700] = 150
    lines = [("State / Province", (100, 10, 300, 35))]
    guide = {"fields": [{"aliases": ["Full name"]}]}
    for known in ({"v"}, {"mr"}, {"00000"}):  # a middle initial, a title, a code the person told Sahl
        assert [u["label"] for u in match.unknown_boxes(lines, guide, gray, known, [])] == ["State / Province"]


def _scrolled(page, dy):
    """The page with its content moved dy pixels down (up when negative), blank where nothing scrolled in."""
    out = np.full_like(page, 255)
    if dy >= 0:
        out[dy:] = page[:page.shape[0] - dy]
    else:
        out[:dy] = page[-dy:]
    return out


@pytest.mark.parametrize("dy", [0, 37, -41, 140, -140, 3])
def test_a_scroll_between_reading_and_filling_still_types_in_the_right_box(client, dy):
    client.page[:] = _form("Full name", "Address Line 1", "Address Line 2")  # rows that differ by one character
    client.read()
    client.post("/taught", json={"label": "Address Line 2", "value": "Flat 2"})
    f = _unknown(client.read())["Address Line 2"]
    box = f["input_box"]
    client.page[:] = _scrolled(client.page, dy)  # the person scrolls
    r = client.post("/fill", json={"field_id": f["id"]})
    assert r.status_code == 200 and r.json()["landed"] is True
    assert client.boxes == [pytest.approx((box[0], box[1] + dy, box[2], box[3] + dy), abs=2)]  # clicked where the box is now


def test_a_box_scrolled_out_of_sight_is_not_clicked(client):
    client.read()
    client.post("/taught", json={"label": "Company", "value": "Acme"})
    f = _unknown(client.read())["Company"]
    client.page[:] = _scrolled(client.page, -400)  # the label is gone
    r = client.post("/fill", json={"field_id": f["id"]})
    assert r.status_code == 409 and r.json()["detail"].startswith("moved") and client.boxes == []


def test_a_read_never_waits_for_the_model(client, monkeypatch):
    client.post("/taught", json={"label": "Company", "value": "Acme Ltd"})
    client.page[:] = _form("Full name", "Workplace", "Password")
    asked = []
    monkeypatch.setattr(taught, "_spawn", lambda fn, *a: asked.append(fn))  # a model that has not answered yet
    monkeypatch.setattr(ai, "chat", lambda *a, **k: pytest.fail("a read called the model itself"))
    assert "suggest" not in _unknown(client.read())["Workplace"] and len(asked) == 1
    client.read()
    assert len(asked) == 1  # asked once, not on every read


def test_a_fill_answers_with_the_next_box_without_reading_the_screen_again(client):
    client.read()
    client.post("/taught", json={"label": "Company", "value": "Acme"})
    r = client.read()
    first = r["next"]
    done = client.post("/fill", json={"field_id": "taught:company"}).json()
    assert done["landed"] and done["reading"]["next"] != "taught:company"
    assert [f["id"] for f in done["reading"]["fields"]] == [f["id"] for f in r["fields"]]  # same order, no new read
    assert next(f for f in done["reading"]["fields"] if f["id"] == "taught:company")["confirmed"]
    skipped = client.post("/confirm", json={"field_id": done["reading"]["next"]}).json()
    assert skipped["reading"]["next"] not in (first, done["reading"]["next"])


def test_similar_reaches_llama_server_as_a_schema_restricted_request(monkeypatch):
    taught.teach("Company", "Acme", "1")
    seen = []
    monkeypatch.setattr(ai, "chat", lambda body, **k: seen.append(body) or {"matches": [{"label": "Workplace", "means": "Company"}]})
    assert taught.similar(["Workplace"], "1") == {"Workplace": "Company"}
    sent = ai._request(seen[0])
    props = sent["response_format"]["json_schema"]["schema"]["properties"]["matches"]["items"]["properties"]
    assert props["label"]["enum"] == ["Workplace"] and props["means"]["enum"] == ["Company", ""]
    assert sent["stream"] is False and "keep_alive" not in sent
