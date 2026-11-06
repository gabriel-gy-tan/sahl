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


def test_passwords_and_payment_are_never_remembered():
    for label in ("Password", "Credit Card Number", "Card Verification Code", "Card Expiration Date", "PIN", "CVV"):
        assert not taught.allowed(label)
    assert taught.allowed("Company") and taught.allowed("Social Security Number")


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
    im = Image.new("L", (1600, 120 + 140 * len(labels)), 255)
    d, font = ImageDraw.Draw(im), ImageFont.load_default(28)
    for i, text in enumerate(labels):
        y = 60 + 140 * i
        d.text((100, y), text, fill=0, font=font)
        d.rectangle((100, y + 50, 700, y + 105), outline=150, width=2)
    return np.array(im)


@pytest.fixture
def client():
    page, typed = _form("Full name", "Company", "Password"), []
    app = server.create_app("t0k", screen=lambda: [(page, 1.0, (0, 0, 1600, page.shape[0]))],
                            typer=lambda box, value: typed.append(value))
    c = TestClient(app, headers={"x-sahl-token": "t0k"})
    c.page, c.typed = page, typed
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
    f = _unknown(client.read())["Workplace"]
    assert f["vault"] is None and f["suggest"] == {"concept": "Company", "value": "Acme Ltd"}  # asked, not assumed
    assert client.post("/taught/alias", json={"label": "Workplace", "concept": "Company"}).status_code == 200
    assert _unknown(client.read())["Workplace"]["vault"]["value"] == "Acme Ltd"
    assert client.get("/taught").json() == [{"concept": "Company", "value": "Acme Ltd", "labels": ["company", "workplace"]}]
    client.post("/taught/forget", json={"concept": "Company"})
    assert client.get("/taught").json() == []
