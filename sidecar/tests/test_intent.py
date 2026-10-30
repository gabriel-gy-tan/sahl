import pytest
from fastapi.testclient import TestClient

from sahl import ai, intent, server

GUIDES = server.load_guides()
me = lambda text: [{"role": "user", "text": text}]


@pytest.fixture
def model(monkeypatch):
    """What the local text model answers (tests don't need Ollama running); None = not running.

    "pick" is the answer to the which-form call, "reply" the words of the conversation call.
    """
    said = {"pick": None, "reply": None, "calls": 0, "talk": None}

    def chat(body, timeout, tries=2):
        said["calls"] += 1
        if "reply" in body.get("format", {}).get("properties", {}):  # warm() sends no format
            said["talk"] = body
            return None if said["reply"] is None else {"reply": said["reply"]}
        return said["pick"]
    monkeypatch.setattr(ai, "chat", chat)
    return said


def test_a_named_guide_is_offered_without_asking_the_model_which(model):
    r = intent.talk(me("I need to book my residency medical fitness"), GUIDES)
    assert (r["kind"], r["guide"]) == ("match", "medical-fitness")
    assert intent.talk(me("الفحص الطبي للإقامة"), GUIDES)["guide"] == "medical-fitness"
    assert model["calls"] == 2  # only the two replies


def test_the_model_offers_a_guide(model):
    model.update(pick={"kind": "match", "guide": "medical-fitness", "name": ""}, reply="Sahl can help with that.")
    assert intent.talk(me("my visa needs the blood test"), GUIDES) == {
        "reply": "Sahl can help with that.", "kind": "match", "guide": "medical-fitness", "name": ""}


def test_questions_get_a_reply_and_the_whole_conversation_is_sent(model):
    model.update(pick={"kind": "unsure", "guide": "", "name": ""}, reply="It's for your residence visa.")
    history = [*me("what is the medical test for?"), {"role": "assistant", "text": "Which one?"}, *me("the visa one")]
    r = intent.talk(history, GUIDES)
    assert (r["kind"], r["reply"]) == ("unsure", "It's for your residence visa.")
    sent = model["talk"]["messages"]
    assert sent[0]["role"] == "system" and [m["role"] for m in sent[1:]] == ["user", "assistant", "user"]


def test_the_reply_is_given_what_a_form_needs(model):
    model.update(pick={"kind": "unsure", "guide": "", "name": ""}, reply="Bring your passport.")
    intent.talk(me("what do I need to renew my Emirates ID?"), GUIDES)
    system = model["talk"]["messages"][0]["content"]
    assert "Needs, documents: Passport" in system and "Needs, fees:" in system


def test_the_reply_is_asked_for_in_their_language(model):
    model.update(pick={"kind": "unsure", "guide": "", "name": ""}, reply="مرحبا")
    intent.talk(me("مرحبا، ما هو الفحص الطبي؟"), GUIDES)
    assert "in Arabic" in model["talk"]["messages"][0]["content"]


def test_a_made_up_or_generic_guide_is_not_trusted(model):
    for bad in ("driving-licence-renewal", "any-form"):
        model.update(pick={"kind": "match", "guide": bad, "name": ""}, reply="Sure.")
        r = intent.talk(me("renew my driving licence"), GUIDES)
        assert (r["kind"], r["guide"]) == ("unsure", None)


def test_a_form_sahl_has_no_guide_for(model):
    model.update(pick={"kind": "new", "guide": "", "name": "Driving licence renewal"}, reply="I don't have that one.")
    r = intent.talk(me("renew my driving licence"), GUIDES)
    assert (r["kind"], r["name"]) == ("new", "Driving licence renewal")


def test_no_model_running_gives_no_reply(model):
    assert intent.talk(me("help"), GUIDES) == {"reply": "", "kind": "unsure", "guide": None, "name": ""}
    assert intent.talk([], GUIDES)["kind"] == "unsure"


def test_chat_endpoint(model, tmp_path, monkeypatch):
    monkeypatch.setenv("SAHL_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("SAHL_LIBRARY", str(tmp_path / "library"))
    c = TestClient(server.create_app("t0k", screen=lambda: [], typer=lambda *a: None), headers={"x-sahl-token": "t0k"})
    assert c.post("/chat", json={"messages": me("medical fitness")}).json()["guide"] == "medical-fitness"
    assert c.post("/chat", json={"messages": [{"role": "system", "text": "x"}]}).status_code == 422
    assert c.post("/chat", json={"messages": me("x")}, headers={"x-sahl-token": "no"}).status_code == 403


def test_the_model_size_is_chosen_and_kept(model, tmp_path, monkeypatch):
    monkeypatch.setenv("SAHL_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("SAHL_LIBRARY", str(tmp_path / "library"))
    monkeypatch.delenv("SAHL_INTENT_MODEL", raising=False)
    monkeypatch.setattr(ai, "installed", lambda: ["qwen3:0.6b", "qwen3-vl:4b-instruct"])
    c = TestClient(server.create_app("t0k", screen=lambda: [], typer=lambda *a: None), headers={"x-sahl-token": "t0k"})
    m = c.get("/models").json()
    assert m["tier"] == "standard" and {t["id"]: t["installed"] for t in m["tiers"]} == {
        "light": True, "standard": False, "strong": False}
    assert c.post("/models", json={"tier": "light"}).json()["tier"] == "light"
    assert ai.text_model() == "qwen3:0.6b" and ai.vision_model() == "qwen3-vl:4b-instruct"
    assert c.post("/models", json={"tier": "huge"}).status_code == 422
