import hashlib
import hmac
import json
import socket
import time
import urllib.request
from pathlib import Path

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
    def get(key, person):  # like vault.get: one key, or the first of several that has a value
        key = next((k for k in key if k in VALUES), None) if isinstance(key, list) else key
        return {"value": VALUES[key][0], "verified": VALUES[key][1], "source": "passport"} if key in VALUES else None
    monkeypatch.setattr(web.vault, "get", get)


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


def test_a_pairing_code_works_once_expires_and_is_burned_by_guessing(monkeypatch):
    state = bridge.State(GUIDES, token="c" * 64)
    c = TestClient(bridge.create_app(state))
    code = state.fresh_code()
    assert state.fresh_code() == code  # Settings shows the same code until it is used or expires
    assert c.post("/pair", json={"code": code}).json()["token"] == "c" * 64
    assert c.post("/pair", json={"code": code}).status_code == 403  # single use

    code = state.fresh_code()
    for _ in range(bridge.MAX_MISSES):
        assert c.post("/pair", json={"code": "999999" if code != "999999" else "000000"}).status_code == 403
    assert c.post("/pair", json={"code": code}).status_code == 403  # guessing burned it
    assert state.fresh_code() != ""

    code = state.fresh_code()
    later = bridge.time.monotonic() + bridge.CODE_LIFE + 1
    monkeypatch.setattr(bridge.time, "monotonic", lambda: later)
    assert c.post("/pair", json={"code": code}).status_code == 403  # expired
    assert state.fresh_code() != code


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


def test_unknown_fields_are_listed_in_the_order_they_appear_on_the_page():
    page = {"url": "https://example.test/form", "title": "Demo", "fields": [
        field("lower", "Lower field", rect=[10, 300, 100, 20]),
        field("upper", "Upper field", rect=[10, 100, 100, 20])]}
    out = web.plan(page, {})
    assert [f["label"] for f in out["fields"]] == ["Upper field", "Lower field"]


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
def _wait(ready, seconds=5):
    deadline = time.monotonic() + seconds
    while not ready() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert ready()


def _answers(port):
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=2) as r:
        return json.load(r)["running"] is True


def test_bridge_waits_for_a_busy_port_then_serves():
    holder = socket.socket()
    holder.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    holder.bind(("127.0.0.1", 0))
    holder.listen()
    port = holder.getsockname()[1]
    state = bridge.State(GUIDES, token="c" * 64, port=port)
    bridge.start(state, retry=0.01)
    _wait(lambda: state.error)
    assert not state.running
    holder.close()
    _wait(lambda: state.running and not state.error)
    _wait(lambda: _answers(port))


def _free_ports(n):
    socks = [socket.socket() for _ in range(n)]
    for k in socks:
        k.bind(("127.0.0.1", 0))
    ports = [k.getsockname()[1] for k in socks]
    for k in socks:
        k.close()
    return ports


def test_bridge_takes_the_next_free_port_when_the_first_is_busy():
    busy, free = _free_ports(2)
    holder = socket.socket()
    holder.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    holder.bind(("127.0.0.1", busy))
    holder.listen()
    try:
        state = bridge.State(GUIDES, token="f" * 64, ports=(busy, free))
        bridge.start(state, retry=60)  # a retry would take a minute: the second port must be used at once
        _wait(lambda: state.running)
        assert state.port == free and not state.error
        _wait(lambda: _answers(free))
    finally:
        holder.close()


def test_bridge_ports_are_the_range_the_extension_looks_through():
    manifest = json.loads((Path(__file__).parents[2] / "extension" / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["host_permissions"] == [f"http://127.0.0.1:{p}/*" for p in bridge.PORTS]
    assert bridge.PORT == bridge.PORTS[0]


def test_health_proves_it_holds_the_token_only_when_asked():
    state = bridge.State(GUIDES, token="a" * 64)
    c = TestClient(bridge.create_app(state))
    assert "proof" not in c.get("/health").json()
    proof = c.get("/health", params={"nonce": "00ff"}).json()["proof"]
    assert proof == hmac.new(b"a" * 64, f"00ff:{state.port}".encode(), hashlib.sha256).hexdigest()  # bound to the port
    other = TestClient(bridge.create_app(bridge.State(GUIDES, token="b" * 64)))
    assert other.get("/health", params={"nonce": "00ff"}).json()["proof"] != proof  # another Sahl cannot fake it
    assert c.get("/health", params={"nonce": "zz"}).status_code == 422
    assert c.get("/health", params={"nonce": "0" * 65}).status_code == 422


def test_bridge_starts_over_connections_left_by_a_closed_sahl():
    old = socket.socket()
    old.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    old.bind(("127.0.0.1", 0))
    old.listen()
    port = old.getsockname()[1]
    client = socket.create_connection(("127.0.0.1", port))
    accepted, _ = old.accept()
    accepted.close()  # the server side closes first, so the port is left in TIME_WAIT with nothing listening
    client.recv(1)
    client.close()
    old.close()
    state = bridge.State(GUIDES, token="d" * 64, port=port)
    bridge.start(state, retry=60)  # a retry would take a minute: it must bind at the first try
    _wait(lambda: state.running)
    assert not state.error


def test_unpair_locks_out_every_browser_and_the_extension_follows_the_panels_language():
    state = bridge.State(GUIDES, token="d" * 64)
    c = TestClient(bridge.create_app(state))
    assert not state.paired
    c.post("/pair", json={"code": state.fresh_code()})
    assert state.paired
    state.unpair()
    assert not state.paired and state.token != "d" * 64 and len(state.token) == 64
    assert c.post("/clear", json={}, headers={"x-sahl-ext-token": "d" * 64}).status_code == 403  # the old token is dead
    assert bridge._load_token() == state.token  # and the new one survives a restart

    assert c.get("/health").json()["lang"] == "en"
    bridge.set_language("ar")
    assert c.get("/health").json()["lang"] == "ar"


ANY = json.loads((Path(__file__).parents[2] / "guides" / "any-form.json").read_text())


def test_name_and_name_in_english_are_both_filled_even_when_the_page_has_its_own_guide(monkeypatch):
    monkeypatch.setattr(web.vault, "get", lambda key, person: {"value": "NOOR AHMAD KHALIL", "verified": True})
    scan = web.plan({"url": "https://example.test", "guide": "demo-form",
                     "fields": [field("a", "Name in English"), field("b", "Name")]}, {**GUIDES, "any-form": ANY}, "p1")
    by = {f["element_id"]: f for f in scan["fields"]}
    assert by["a"]["field_id"] == "full_name" and not by["a"].get("unknown")
    assert by["b"]["field_id"] == "full_name"  # "Name" and "Name in English" are the same detail: both get the name
    assert web.values(scan, ["a"], "p1")["values"][0]["value"] == "NOOR AHMAD KHALIL"


def test_the_arabic_name_is_written_from_the_english_one(monkeypatch):
    monkeypatch.setitem(VALUES, "passport.name", ("NOOR AHMAD KHALIL", True))
    monkeypatch.setattr(web.ai, "chat", lambda body, timeout, tries=2: {"arabic": "نور أحمد خليل"})
    web._arabic_names.clear()
    scan = web.plan({"url": "https://example.test", "guide": "demo-form",
                     "fields": [field("a", "Name in English"), field("c", "Name in Arabic")]}, {**GUIDES, "any-form": ANY}, "p1")
    assert {f["element_id"]: f["field_id"] for f in scan["fields"]} == {"a": "full_name", "c": "full_name_ar"}
    assert web.values(scan, ["c"], "p1")["values"][0]["value"] == "نور أحمد خليل"
    monkeypatch.setattr(web.ai, "chat", lambda body, timeout, tries=2: {"arabic": "Noor"})  # not Arabic: nothing is typed
    web._arabic_names.clear()
    assert web.values(scan, ["c"], "p1")["missing"]


@pytest.mark.parametrize("label,field_id", [
    ("Applicant full name", "full_name"), ("Name in English", "full_name"), ("Name", "full_name"),
    ("Full legal name (as in passport)", "full_name"), ("Name in Arabic", "full_name_ar"), ("الاسم بالعربية", "full_name_ar"),
    ("Birth date", "dob"), ("Passport No", "passport_number"),
])
def test_a_box_is_recognised_by_what_it_asks_for(label, field_id):
    scan = web.plan({"url": "https://example.test", "guide": "any-form", "fields": [field("x", label)]}, {"any-form": ANY}, "p1")
    assert [f["field_id"] for f in scan["fields"] if not f.get("unknown")] == [field_id]


@pytest.mark.parametrize("label", ["Father's name", "Mother name", "Account Owner Name", "Spouse full name", "Company name",
                                   "Sponsor name", "Middle name", "Place of birth", "Username"])
def test_a_box_about_someone_else_is_never_filled_with_the_persons_own_detail(label):
    scan = web.plan({"url": "https://example.test", "guide": "any-form", "fields": [field("x", label)]}, {"any-form": ANY}, "p1")
    assert not [f for f in scan["fields"] if not f.get("unknown")]


def test_the_browsers_own_hint_decides_when_the_label_is_odd():
    scan = web.plan({"url": "https://example.test", "guide": "any-form",
                     "fields": [field("x", "Who are you?", autocomplete="family-name")]}, {"any-form": ANY}, "p1")
    assert [f["field_id"] for f in scan["fields"]] == ["surname"]


def test_a_page_like_a_guide_is_answered_now_and_the_model_picks_for_next_time(monkeypatch):
    other = {**GUIDE, "id": "other-form", "service": {"en": "Other form"}}
    calls = []
    monkeypatch.setattr(web.intent, "rank", lambda text, guides: [(0.5, "demo-form"), (0.45, "other-form")])
    monkeypatch.setattr(web.intent, "pick", lambda text, guides, timeout=20: calls.append(1) or {"guide": "other-form"})
    monkeypatch.setattr(web.taught, "_spawn", lambda fn, *a: fn(*a))  # the background pick, here at once
    web._picked.clear()
    page = {"url": "https://example.test/form?session=1", "title": "Demo", "fields": [field("f1", "Full name")]}
    assert web.plan(page, {"demo-form": GUIDE, "other-form": other})["guide"]["id"] == "demo-form"  # the closest, at once
    assert calls == [1]  # asked once, in the background (tests run it at once)
    assert web.plan(page, {"demo-form": GUIDE, "other-form": other})["guide"]["id"] == "other-form"  # then the model's pick
    assert calls == [1]


def test_each_box_says_whether_there_is_a_value_and_whether_the_ai_writes_it(monkeypatch):
    monkeypatch.setattr(web.vault, "get", lambda key, person: {"value": "LAYLA HADDAD", "verified": True}
                        if key in ("passport.name", ["passport.name", "eid.name", "other.name"]) else None)
    monkeypatch.setattr(web.ai, "have", lambda model: False)
    scan = web.plan({"url": "https://example.test", "guide": "any-form", "fields": [
        field("a", "Name in English"), field("b", "Name in Arabic"), field("c", "Passport number")]}, {"any-form": ANY}, "p1")
    by = {f["element_id"]: f for f in scan["fields"]}
    assert by["a"]["has_value"] and not by["a"]["ai"]
    assert by["b"]["ai"] and not by["b"]["has_value"]  # no text model on this computer: nothing to write it with
    assert not by["c"]["has_value"]  # no passport number in the vault
    assert "value" not in by["a"]  # whether there is one, never the value itself


def test_the_pairing_code_names_the_port_it_was_shown_for():
    for port in (bridge.PORTS[0], bridge.PORTS[3]):
        state = bridge.State(GUIDES, token="a" * 64, port=port)
        assert state.fresh_code()[-1] == str(port - bridge.PORTS[0])


def test_the_icp_entry_permit_form_is_read_box_by_box(monkeypatch):
    guides = {**GUIDES, "any-form": ANY, "icp-visa-issue": json.loads((Path(__file__).parents[2] / "guides" / "icp-visa-issue.json").read_text())}
    monkeypatch.setitem(VALUES, "passport.name", ("NOOR AHMAD KHALIL", True))
    monkeypatch.setitem(VALUES, "passport.number", ("X1234567", True))
    labels = ["Full Name (English)", "Full Name (Arabic)", "Current Nationality", "Date of Birth", "Passport No.", "Expiry Date",
              "Mother's First Name (English)", "Previous Nationality", "Mobile No.", "Permanent Mobile No."]
    scan = web.plan({"url": "https://smartservices.icp.gov.ae/x", "title": "Entry permit", "guide": "icp-visa-issue",
                     "fields": [field(f"f{i}", label, "select" if "Nationality" in label else "input") for i, label in enumerate(labels)]},
                    guides, "p1")
    got = {f["label"]: f.get("field_id") or "unknown" for f in scan["fields"]}
    assert scan["guide"]["id"] == "icp-visa-issue"
    assert got["Full Name (English)"] == "full_name_english" and got["Full Name (Arabic)"] == "full_name_arabic"
    assert got["Passport No."] == "passport_number" and got["Date of Birth"] == "date_of_birth"
    assert got["Expiry Date"] == "passport_expiry" and got["Current Nationality"] == "current_nationality"
    out = web.values(scan, [f["element_id"] for f in scan["fields"]], "p1")
    filled = {v["element_id"]: v.get("value") for v in out["values"]}
    assert filled["f0"] == "NOOR AHMAD KHALIL" and filled["f4"] == "X1234567"
    assert "f6" not in filled  # the mother's name is someone else's: never the person's own
