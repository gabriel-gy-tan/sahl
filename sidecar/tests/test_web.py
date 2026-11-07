import pytest
from fastapi.testclient import TestClient

from sahl import bridge, taught, web

GUIDE = {
    "id": "demo-form", "service": {"en": "Demo form"}, "about": "A demo web form.", "fields": [
        {"id": "name", "aliases": ["Full name"], "vault_key": "name", "input": "text", "help": {}},
        {"id": "nationality", "aliases": ["Nationality"], "vault_key": "nationality", "input": "select", "help": {}},
        {"id": "dob", "aliases": ["Date of birth"], "vault_key": "dob", "input": "date-parts", "help": {}},
        {"id": "agree", "aliases": ["I agree"], "vault_key": "name", "input": "checkbox", "help": {}},
    ],
}
GUIDES = {"demo-form": GUIDE}
VALUES = {"name": ("MOHAMMED RAFEEQ", True), "nationality": ("Indian", True), "dob": ("14/03/1985", True)}


def field(element_id, label, tag="input", kind="text", **extra):
    return {"element_id": element_id, "label": label, "tag": tag, "type": kind, "name": element_id, **extra}


@pytest.fixture(autouse=True)
def vault(monkeypatch, tmp_path):
    monkeypatch.setenv("SAHL_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("SAHL_LIBRARY", str(tmp_path / "library"))
    taught._asked.clear()
    monkeypatch.setattr(web.vault, "people", lambda: [{"id": "p1", "name": "Demo Person"}])
    monkeypatch.setattr(web.vault, "get", lambda key, person: {
        "value": VALUES[key][0], "verified": VALUES[key][1], "source": "passport"} if key in VALUES else None)


def page(**extra):
    return {"url": "https://example.test/form", "title": "Demo", "guide": "demo-form",
            "fields": [field("f1", "Full name"), field("f2", "Nationality", "select", "select",
                                                         options=[{"text": "India"}, {"text": "Pakistan"}]),
                       field("f3", "Date of birth", "date-parts", "date",
                             parts=[{"element_id": "d", "part": "d"}, {"element_id": "m", "part": "m"},
                                    {"element_id": "y", "part": "y"}]),
                       field("f4", "I agree", kind="checkbox"), field("f5", "Password", kind="password"),
                       field("f6", "Card number", autocomplete="cc-number")], **extra}


def test_weak_page_skips_the_local_model(monkeypatch):
    def boom(*_args, **_kwargs):
        raise AssertionError("the local model should not be asked about unrelated words")

    monkeypatch.setattr(web.intent, "pick", boom)
    assert web._guide_for({"title": "zzzz qqqq", "url": "https://zzzz.test/qqqq", "fields": []}, GUIDES) == (None, 0.0)


def test_plan_matches_fields_but_never_secrets_or_checkboxes():
    out = web.plan(page(), GUIDES)
    assert out["guide"]["id"] == "demo-form" and out["person"] == "p1"
    assert [f["element_id"] for f in out["fields"]] == ["f1", "f2", "f3", "f6"]  # card details are asked about, not secrets
    assert [f["kind"] for f in out["fields"]] == ["text", "select", "date-parts", "text"]
    assert out["fields"][0]["confidence"] == 100
    assert out["fields"][3]["unknown"] and not out["fields"][3]["told"]


def test_values_release_only_verified_values_for_the_chosen_fields():
    scan = web.plan(page(), GUIDES)
    out = web.values(scan, ["f1", "f2", "f3"])
    assert out["needs_person"] is False
    by_id = {v["element_id"]: v for v in out["values"]}
    assert by_id["f1"]["value"] == "MOHAMMED RAFEEQ"
    assert by_id["f2"]["option"] == "India"  # "Indian" releases the country list's word
    assert [p["element_id"] for p in by_id["f3"]["parts"]] == ["d", "m", "y"]
    assert by_id["f3"]["parts"][1]["value"] == "03"


def test_unverified_and_unknown_fields_are_not_released(monkeypatch):
    monkeypatch.setattr(web.vault, "get", lambda key, person: {"value": "x", "verified": False})
    out = web.values(web.plan(page(), GUIDES), ["f1", "f9"])
    assert out["values"] == []
    assert {m["element_id"] for m in out["missing"]} == {"f1", "f9"}


def test_bridge_needs_pairing_and_rejects_other_origins():
    state = bridge.State(GUIDES, token="a" * 64)
    c = TestClient(bridge.create_app(state))
    assert c.get("/health").json()["app"] == "Sahl"
    assert c.post("/pair", json={"code": state.code}, headers={"origin": "https://evil.test"}).status_code == 403
    assert c.post("/page", json=page()).status_code == 403
    assert c.post("/pair", json={"code": "000000"}, headers={"origin": "chrome-extension://abc"}).status_code in (403, 429)
    assert c.post("/pair", json={"code": state.code}, headers={"origin": "chrome-extension://abc"}).json()["token"] == "a" * 64


def test_bridge_scan_then_values():
    state = bridge.State(GUIDES, token="b" * 64)
    c = TestClient(bridge.create_app(state), headers={"x-sahl-ext-token": "b" * 64})
    assert c.post("/values", json={"element_ids": ["f1"]}).status_code == 409
    scan = c.post("/page", json=page()).json()
    assert scan["guide"]["id"] == "demo-form" and "_guide" not in scan and "_fields" not in scan
    out = c.post("/values", json={"element_ids": ["f1", "f2"]}).json()
    assert {v["element_id"] for v in out["values"]} == {"f1", "f2"}
    assert c.post("/clear").json() == {"ok": True}
    assert c.post("/values", json={"element_ids": ["f1"]}).status_code == 409


def card_page():
    return {"url": "https://shop.test/checkout", "title": "Checkout", "fields": [
        field("c1", "Credit Card Number", autocomplete="cc-number"),
        field("c2", "Credit Card Type", "select", "select", options=[{"text": "(Select Card Type)"}, {"text": "Visa"}]),
        field("c3", "Card Expiration Date", "select", "select", options=[{"text": "01"}, {"text": "02"}]),
        field("c4", "Card Expiration Date", "select", "select", options=[{"text": "2030"}, {"text": "2031"}]),
        field("c5", "Card Verification Code"), field("c6", "", name="card_cvv"), field("c7", "CVV2"),
        field("c8", "Code", placeholder="Security code"), field("c9", "PIN"), field("c10", "Code", autocomplete="one-time-code"),
        field("c11", "Code", autocomplete="cc-csc"), field("c12", "Password", kind="password"), field("c13", "Passcode"),
        field("c14", "Company"), field("c15", "I agree", kind="checkbox"), field("c16", "Shipping notes"),
    ]}


def test_card_details_are_asked_about_but_never_pins_passcodes_or_the_security_code():
    out = web.plan(card_page(), {})
    assert out["guide"] is None
    assert [(f["element_id"], f["label"]) for f in out["fields"]] == [
        ("c1", "Credit Card Number"), ("c2", "Credit Card Type"), ("c3", "Card Expiration Date 1"),
        ("c4", "Card Expiration Date 2"), ("c14", "Company"), ("c16", "Shipping notes")]
    assert all(f["unknown"] and not f["told"] for f in out["fields"])


@pytest.fixture
def ext():
    state = bridge.State({}, token="e" * 64)
    return TestClient(bridge.create_app(state), headers={"x-sahl-ext-token": "e" * 64})


def test_a_box_is_told_once_then_filled_from_the_popup(ext):
    first = {f["element_id"]: f for f in ext.post("/page", json=card_page()).json()["fields"]}
    assert ext.post("/values", json={"element_ids": ["c14"]}).json()["missing"][0]["reason"] == "not told yet"
    assert ext.post("/taught", json={"element_id": "c14", "value": "Acme Ltd"}).json() == {"concept": "Company"}
    assert ext.post("/taught", json={"element_id": "c2", "value": "Visa"}).status_code == 200
    assert ext.post("/taught", json={"element_id": "c5", "value": "123"}).status_code == 404  # the security code: never
    assert ext.post("/taught", json={"element_id": "c1", "value": "  "}).status_code == 422
    assert not first["c14"]["told"]
    again = {f["element_id"]: f for f in ext.post("/page", json=card_page()).json()["fields"]}
    assert again["c14"]["told"] and again["c2"]["told"] and not again["c1"]["told"]
    out = ext.post("/values", json={"element_ids": ["c14", "c2", "c1"]}).json()
    by_id = {v["element_id"]: v for v in out["values"]}
    assert by_id["c14"]["value"] == "Acme Ltd" and by_id["c2"]["option"] == "Visa"
    assert [m["element_id"] for m in out["missing"]] == ["c1"]


@pytest.mark.parametrize("month, year", [("March", "2030"), ("March 2030", "March 2030"), ("03/30", "03/30"), ("3", "30")])
def test_a_told_card_expiry_picks_the_menus_own_month_and_year(ext, month, year):
    page = {"url": "https://shop.test/checkout", "title": "Checkout", "fields": [
        field("m", "Card Expiration Date (month)", "select", "select", options=[{"text": f"{i:02d}"} for i in range(1, 13)]),
        field("y", "Card Expiration Date (year)", "select", "select", options=[{"text": str(y)} for y in range(2019, 2038)]),
    ]}
    ext.post("/page", json=page)
    ext.post("/taught", json={"element_id": "m", "value": month})
    ext.post("/taught", json={"element_id": "y", "value": year})
    ext.post("/page", json=page)
    out = ext.post("/values", json={"element_ids": ["m", "y"]}).json()
    assert {v["element_id"]: v["option"] for v in out["values"]} == {"m": "03", "y": "2030"}


def test_the_same_detail_under_another_name_once_the_person_agrees(ext, monkeypatch):
    taught.teach("Company", "Acme Ltd", "p1")
    monkeypatch.setattr(web.taught, "suggestions", lambda labels, person: {"Workplace": "Company"} if "Workplace" in labels else {})
    page = {"url": "https://jobs.test/apply", "title": "Apply", "fields": [field("w1", "Workplace")]}
    asked = ext.post("/page", json=page).json()["fields"][0]
    assert asked["suggest"] == "Company" and not asked["told"] and "Acme" not in str(asked)  # no value before a fill
    assert ext.post("/taught/alias", json={"element_id": "w1", "concept": "Nothing"}).status_code == 404
    assert ext.post("/taught/alias", json={"element_id": "w1", "concept": "Company"}).json() == {"ok": True}
    assert ext.post("/page", json=page).json()["fields"][0]["told"]
    assert ext.post("/values", json={"element_ids": ["w1"]}).json()["values"][0]["value"] == "Acme Ltd"


def test_whose_values_is_asked_only_when_the_vault_holds_more_than_one_person(monkeypatch):
    taught.teach("Company", "Acme Ltd", None)
    for people, asks in (([], False), ([{"id": "p1", "name": "A"}], False),
                         ([{"id": "p1", "name": "A"}, {"id": "p2", "name": "B"}], True)):
        monkeypatch.setattr(web.vault, "people", lambda people=people: people)
        out = web.values(web.plan(card_page(), {}), ["c14"])
        assert out["needs_person"] is asks
        assert asks or out["values"][0]["value"] == "Acme Ltd"
