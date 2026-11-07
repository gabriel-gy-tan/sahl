import json
import socket
import time
import urllib.request

import pytest
from fastapi.testclient import TestClient

from sahl import bridge, web

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
    assert [f["element_id"] for f in out["fields"]] == ["f1", "f2", "f3"]
    assert [f["kind"] for f in out["fields"]] == ["text", "select", "date-parts"]
    assert out["fields"][0]["confidence"] == 100


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
