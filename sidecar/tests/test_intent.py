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
    assert model["calls"] == 0  # a clear choice needs no model: the panel shows the form, not a model's words


def test_a_question_is_answered_not_chosen(model):
    model.update(reply="It costs 100 AED a year.")
    r = intent.talk(me("How much does it cost to renew my Emirates ID?"), GUIDES)
    assert (r["kind"], r["guide"], r["reply"]) == ("about", "emirates-id-renewal", "It costs 100 AED a year.")
    assert "Needs, fees:" in model["talk"]["messages"][0]["content"]
    assert intent.talk(me("Can you help me renew my Emirates ID?"), GUIDES)["kind"] == "match"  # a request, not a question


def test_small_talk_never_names_a_form(model):
    model.update(reply="Hello!")
    for text in ("hi", "help", "thanks!", "a form", "what can you do?"):
        r = intent.talk(me(text), GUIDES)
        assert (r["kind"], r["options"]) == ("unsure", [])
        assert "Needs," not in model["talk"]["messages"][0]["content"]  # no form's details to blend into the answer


def test_rare_words_decide(model):
    known = intent.catalogue(GUIDES)
    assert intent.rank("renew my car registration", known)[0][1] == "tamm-renew-vehicle-registration"
    assert intent.rank("tell me about renewing residency", known)[0][1] == "residence-permit-renewal"
    assert intent._strong(intent.rank("renew my falconry passport", known)) == []  # a word no guide has keeps it open


def test_form_search(model):
    known = intent.catalogue(GUIDES)
    assert intent.search("emir", known)[0] in {"emirates-id-renewal", "tamm-citizen-emirates-id-renew"}  # a word half typed
    assert "medical-fitness" in intent.search("visa medical", known)[:3]
    assert len(intent.search("", known)) == len(known) and intent.GENERIC not in intent.search("", GUIDES)


def test_the_model_offers_a_guide(model):
    model.update(pick={"kind": "match", "guide": "medical-fitness", "name": ""}, reply="Sahl can help with that.")
    assert intent.talk(me("my visa needs a checkup"), GUIDES) == {
        "reply": "Sahl can help with that.", "kind": "match", "guide": "medical-fitness", "options": ["medical-fitness"], "name": ""}


def test_questions_get_a_reply_and_the_whole_conversation_is_sent(model):
    model.update(pick={"kind": "unsure", "guide": "", "name": ""}, reply="It's for your residence visa.")
    history = [*me("what is the medical test for?"), {"role": "assistant", "text": "Which one?"}, *me("why?")]
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
        r = intent.talk(me("get a falconry passport"), GUIDES)
        assert (r["kind"], r["guide"]) == ("unsure", None)


def test_a_form_sahl_has_no_guide_for(model):
    model.update(pick={"kind": "new", "guide": "", "name": "Falconry passport"}, reply="I don't have that one.")
    r = intent.talk(me("get a falconry passport"), GUIDES)
    assert (r["kind"], r["name"]) == ("new", "Falconry passport")


def test_no_model_running_gives_no_reply(model):
    assert intent.talk(me("help"), GUIDES) == {"reply": "", "kind": "unsure", "guide": None, "options": [], "name": ""}
    assert intent.talk([], GUIDES)["kind"] == "unsure"


def test_chat_endpoint(model, tmp_path, monkeypatch):
    monkeypatch.setenv("SAHL_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("SAHL_LIBRARY", str(tmp_path / "library"))
    c = TestClient(server.create_app("t0k", screen=lambda: [], typer=lambda *a: None), headers={"x-sahl-token": "t0k"})
    assert c.post("/chat", json={"messages": me("medical fitness")}).json()["guide"] == "medical-fitness"
    assert c.get("/guides/search", params={"q": "medical fitness"}).json()[0] == "medical-fitness"
    assert c.post("/chat", json={"messages": [{"role": "system", "text": "x"}]}).status_code == 422
    assert c.post("/chat", json={"messages": me("x")}, headers={"x-sahl-token": "no"}).status_code == 403


def test_the_model_size_is_chosen_and_kept(model, tmp_path, monkeypatch):
    monkeypatch.setenv("SAHL_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("SAHL_LIBRARY", str(tmp_path / "library"))
    monkeypatch.delenv("SAHL_INTENT_MODEL", raising=False)
    monkeypatch.setattr(ai, "installed", lambda: ["qwen3:0.6b", "qwen3-vl:4b-instruct"])
    monkeypatch.setattr(ai, "prepare", lambda: None)  # would start Ollama and download models
    c = TestClient(server.create_app("t0k", screen=lambda: [], typer=lambda *a: None), headers={"x-sahl-token": "t0k"})
    m = c.get("/models").json()
    assert m["tier"] == "standard" and {t["id"]: t["installed"] for t in m["tiers"]} == {
        "light": True, "standard": False, "strong": False}
    assert c.post("/models", json={"tier": "light"}).json()["tier"] == "light"
    assert ai.text_model() == "qwen3:0.6b" and ai.vision_model() == "qwen3-vl:4b-instruct"
    assert c.post("/models", json={"tier": "huge"}).status_code == 422


def test_missing_models_are_downloaded_after_starting_ollama(monkeypatch):
    pulled, have = [], []
    monkeypatch.setattr(ai, "start", lambda: True)
    monkeypatch.setattr(ai, "installed", lambda: have)
    monkeypatch.setattr(ai, "_pull", lambda m: (pulled.append(m), have.append(m)))
    monkeypatch.setattr(ai, "chat", lambda *a, **k: None)
    monkeypatch.setattr(ai.threading, "Thread", lambda target, daemon: type("T", (), {"start": staticmethod(target)}))
    ai.prepare()
    assert pulled == [ai.text_model(), ai.vision_model()]
    ai.prepare()  # now both are there
    assert pulled == [ai.text_model(), ai.vision_model()]
def test_the_reply_is_told_which_documents_are_held_but_no_values(model):
    model.update(pick={"kind": "unsure", "guide": "", "name": ""}, reply="You have a passport.")
    held = {"people": [{"id": "1", "name": "Priya", "docs": {"passport": 1, "emirates_id": 2}}], "unmatched": 1}
    intent.talk(me("What documents of mine do you have?"), GUIDES, held)
    system = model["talk"]["messages"][0]["content"]
    assert "Priya: 1 passport, 2 emirates id" in system and "1 not matched to anyone" in system


def test_the_model_only_sees_the_closest_guides(model, monkeypatch):
    many = {f"g{i}": {"id": f"g{i}", "service": {"en": f"Service number {i} xyzzy{i}"}, "about": f"thing {i}"} for i in range(50)}
    many["tl"] = {"id": "tl", "service": {"en": "Trade licence renewal"}, "about": "Renew a company trade licence."}
    assert intent.rank("licence for my company", many)[0][1] == "tl"
    seen = []
    monkeypatch.setattr(intent.ai, "chat", lambda body, **kw: seen.append(body))
    intent.pick("licence for my falcon farm", many)  # not settled by words: the model chooses among the closest
    enum = seen[0]["format"]["properties"]["guide"]["enum"]
    assert len(enum) <= 9 and "tl" in enum


def test_guides_follow_the_emirate_named():
    guides = server.load_guides()
    ajman = intent.in_emirate("apply for a boat licence in Ajman", guides)
    assert not any(g.get("authority") == "TAMM" for g in ajman.values())  # Abu Dhabi's own services are not Ajman's
    assert any(g.get("authority") == "ICP" for g in ajman.values())  # federal ones serve every emirate
    dubai = intent.in_emirate("تسجيل عقد إيجار في دبي", guides)
    assert any(g.get("authority") == "DLD" for g in dubai.values()) and not any(g.get("authority") == "TAMM" for g in dubai.values())
    assert intent.in_emirate("renew my emirates id", guides) == guides  # no emirate named: every guide


def test_a_named_service_must_be_in_their_own_words():
    assert intent._echoes("boat license", "apply for a boat licence in ajman")  # spelt the other way
    assert not intent._echoes("pharmacy licence renewal", "apply for a boat licence in ajman")  # made up


@pytest.mark.parametrize("text, asked", [
    ("the pages in my passport are finished, what now", True),
    ("my visa expired. how do I renew it", True),
    ("renew my emirates id", False),
    ("passport renewal, emirates id renewal", False),
])
def test_question_in_a_later_clause(text, asked):
    assert intent.is_question(text) is asked


def test_northern_emirates_health_services_are_not_dubais():
    guides = server.load_guides()
    assert not any(g.get("authority") == "EHS" for g in intent.in_emirate("birth certificate in Dubai", guides).values())
    assert any(g.get("authority") == "EHS" for g in intent.in_emirate("birth certificate in Sharjah", guides).values())


def test_federal_guide_first_when_scores_tie():
    ranked = intent.rank("كم رسوم تجديد الهوية؟", intent.catalogue(server.load_guides()))
    top = [i for s, i in ranked if s == ranked[0][0]]
    assert top[0] == "emirates-id-renewal"  # ICP serves everyone; TAMM's variants only Abu Dhabi


@pytest.mark.parametrize("a, b, same", [
    ("renew", "renewal", True), ("register", "registration", True), ("residence", "residency", True),
    ("licence", "license", True), ("certificate", "certificates", True),
    ("checkup", "check", False), ("passport", "pass", False), ("marriage", "married", False),
])
def test_word_forms(a, b, same):
    assert intent._same(a, b) is same
