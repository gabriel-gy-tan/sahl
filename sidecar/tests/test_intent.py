import pytest
from fastapi.testclient import TestClient

from sahl import ai, intent, server

GUIDES = server.load_guides()
me = lambda text: [{"role": "user", "text": text}]


@pytest.fixture
def model(monkeypatch):
    """What the local text model answers (tests don't need llama.cpp running); None = not running.

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
    monkeypatch.setattr(ai, "have", lambda m: m in ("qwen3-0.6b", "qwen3-vl-4b"))
    monkeypatch.setattr(ai, "prepare", lambda: None)  # would download models and start the text model
    c = TestClient(server.create_app("t0k", screen=lambda: [], typer=lambda *a: None), headers={"x-sahl-token": "t0k"})
    m = c.get("/models").json()
    assert m["tier"] == "standard" and {t["id"]: t["installed"] for t in m["tiers"]} == {
        "light": True, "standard": False, "strong": False}
    assert c.post("/models", json={"tier": "light"}).json()["tier"] == "light"
    assert ai.text_model() == "qwen3-0.6b" and ai.vision_model() == "qwen3-vl-4b"
    assert c.post("/models", json={"tier": "huge"}).status_code == 422


@pytest.fixture
def pulls(monkeypatch, tmp_path):
    """llama-server is there and nothing is downloaded; `results` says how each try goes. Returns (tries, results)."""
    monkeypatch.setenv("SAHL_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("SAHL_MODELS", str(tmp_path / "models"))
    tries, results = [], []
    def pull(m):
        tries.append(m)
        ok = results.pop(0) if results else True
        if ok:
            (tmp_path / "models").mkdir(exist_ok=True)
            for f, _ in ai.MODELS[m][1]:
                (tmp_path / "models" / f).write_text("x")
        return ok
    started = []
    monkeypatch.setattr(ai, "binary", lambda: "llama-server")
    monkeypatch.setattr(ai._Server, "ensure", lambda self, model, wait=0: started.append(model) or True)
    monkeypatch.setattr(ai, "free_gb", lambda: 500.0)
    monkeypatch.setattr(ai, "_pull", pull)
    monkeypatch.setattr(ai.time, "sleep", lambda s: None)
    monkeypatch.setattr(ai.threading, "Thread", lambda target, daemon: type("T", (), {"start": staticmethod(target)}))
    ai._stop.clear()
    return tries, results, started


def test_nothing_is_downloaded_until_the_person_agrees(pulls):
    tries, _, _ = pulls
    assert ai.consent() == "ask"
    ai.prepare()
    assert tries == []
    ai.set_consent("no")
    ai.prepare()
    assert tries == [] and ai.consent() == "no"
    ai.set_tier("light")  # the size is kept beside the answer, not instead of it
    assert ai.consent() == "no"


def test_missing_models_are_downloaded_once_agreed_and_the_text_one_started(pulls):
    tries, _, started = pulls
    ai.set_consent("yes")
    assert tries == [ai.text_model(), ai.vision_model()] and started == [ai.text_model()]
    ai.prepare()  # now both are there
    assert tries == [ai.text_model(), ai.vision_model()]


def test_a_dropped_connection_is_retried_until_it_finishes(pulls):
    tries, results, _ = pulls
    results[:] = [False, False]  # internet down twice, then back
    ai.set_consent("yes")
    assert tries == [ai.text_model()] * 3 + [ai.vision_model()]


def test_a_full_disk_waits_instead_of_trying(pulls, monkeypatch):
    tries, _, _ = pulls
    free = iter([0.1, 0.1, 500.0] * 4)
    monkeypatch.setattr(ai, "free_gb", lambda: next(free))
    ai.set_consent("yes")
    assert tries == [ai.text_model(), ai.vision_model()] and ai.PULL["reason"] == ""  # it waited for room, then carried on


def test_saying_no_stops_a_download(pulls):
    tries, _, _ = pulls
    def pull(m):
        tries.append(m)
        ai.set_consent("no")  # the person turns it off while it downloads
        return False
    ai._pull = pull
    ai._save(download="yes")
    ai.prepare()
    assert tries == [ai.text_model()] and ai.consent() == "no"


def test_the_download_size_is_shown_before_agreeing(model, tmp_path, monkeypatch):
    monkeypatch.setenv("SAHL_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("SAHL_LIBRARY", str(tmp_path / "library"))
    monkeypatch.setattr(ai, "have", lambda m: m == "qwen3-1.7b")
    monkeypatch.setattr(ai, "prepare", lambda: None)
    c = TestClient(server.create_app("t0k", screen=lambda: [], typer=lambda *a: None), headers={"x-sahl-token": "t0k"})
    m = c.get("/models").json()
    assert m["consent"] == "ask" and m["free_gb"] > 0
    assert {t["id"]: t["need_gb"] for t in m["tiers"]}["standard"] == 6.2  # the text model is already there
    assert c.post("/models/download", json={"answer": "no"}).json()["consent"] == "no"
    assert c.post("/models/download", json={"answer": "maybe"}).status_code == 422


def test_requests_are_sent_to_llama_server_in_its_own_shape():
    body = {"model": "m", "think": True, "format": {"type": "object"}, "options": {"temperature": 0.3, "num_predict": 200},
            "messages": [{"role": "system", "content": "s"}, {"role": "user", "content": "look", "images": ["QUJD"]}]}
    r = ai._request(body)
    assert r["messages"][0] == {"role": "system", "content": "s"}
    assert r["messages"][1]["content"] == [{"type": "text", "text": "look"}, {"type": "image_url", "image_url": {"url": "data:image/png;base64,QUJD"}}]
    assert r["chat_template_kwargs"] == {"enable_thinking": True} and r["max_tokens"] == 200 and r["temperature"] == 0.3
    assert r["response_format"]["json_schema"]["schema"] == {"type": "object"}
    assert "response_format" not in ai._request({**body, "format": None})


class _Host:
    """A stand-in for Hugging Face: a redirect to storage that serves byte ranges, and can drop the connection part-way."""

    def __init__(self, data: bytes, lie_about_hash=False):
        import hashlib, http.server, threading
        host = self
        host.data, host.drop_after, host.ranges = data, None, []
        digest = "0" * 64 if lie_about_hash else hashlib.sha256(data).hexdigest()

        class H(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a): pass

            def do_HEAD(self): self.do_GET()

            def do_GET(self):
                if self.path.startswith("/storage/"):
                    start = int((self.headers.get("range") or "bytes=0-").split("=")[1].split("-")[0])
                    host.ranges.append(start)
                    body = host.data[start:]
                    self.send_response(206 if start else 200)
                    self.send_header("content-length", str(len(body)))
                    self.end_headers()
                    if self.command == "GET":
                        cut = host.drop_after
                        host.drop_after = None
                        self.wfile.write(body[:cut] if cut else body)
                        self.wfile.flush()
                    return
                self.send_response(302)
                self.send_header("location", "/storage/" + self.path.rsplit("/", 1)[1])
                self.send_header("x-linked-size", str(len(host.data)))
                self.send_header("x-linked-etag", f'"{digest}"')
                self.end_headers()

        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.httpd.server_port}"


@pytest.fixture
def host(monkeypatch, tmp_path):
    monkeypatch.setenv("SAHL_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("SAHL_MODELS", str(tmp_path / "models"))
    monkeypatch.setitem(ai.MODELS, "tiny", ("o/tiny-GGUF", (("tiny.gguf", 0.000003),)))
    ai._stop.clear()
    def make(data, **kw):
        h = _Host(data, **kw)
        monkeypatch.setattr(ai, "HF", h.url)
        return h
    yield make


def test_a_download_cut_short_carries_on_from_where_it_stopped(host, tmp_path):
    data = bytes(range(256)) * 4000  # 1 MB
    h = host(data)
    h.drop_after = 300_000  # the connection drops part-way
    assert ai._pull("tiny") is False and ai.PULL["error"] and ai.PULL["reason"] == "network"
    part = tmp_path / "models" / "tiny.gguf.part"
    assert 0 < part.stat().st_size < len(data) and not ai.have("tiny")
    assert ai._pull("tiny") is True and ai.have("tiny")
    assert h.ranges[0] == 0 and h.ranges[1] > 0  # the second try asked for the rest, not the start
    assert (tmp_path / "models" / "tiny.gguf").read_bytes() == data and not part.exists()


def test_a_download_that_does_not_match_its_hash_is_thrown_away(host, tmp_path):
    host(b"abc" * 1000, lie_about_hash=True)
    assert ai._pull("tiny") is False and ai.PULL["reason"] == "other"
    assert not ai.have("tiny") and not (tmp_path / "models" / "tiny.gguf.part").exists()


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


FAKE_SERVER = """#!/usr/bin/env python3
import http.server, json, sys
a = sys.argv
port = int(a[a.index("--port") + 1])
class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *x): pass
    def do_GET(self):
        self.send_response(200); self.end_headers(); self.wfile.write(b"{{}}")
    def do_POST(self):
        n = int(self.headers["content-length"]); req = json.loads(self.rfile.read(n))
        ok = self.headers["authorization"].startswith("Bearer ") and req["messages"][-1]["content"] == "hi"
        out = json.dumps({{"choices": [{{"message": {{"content": json.dumps({{"ok": ok, "args": a[1:]}})}}}}]}}).encode()
        self.send_response(200); self.send_header("content-length", str(len(out))); self.end_headers(); self.wfile.write(out)
http.server.HTTPServer(("127.0.0.1", port), H).serve_forever()
"""


@pytest.fixture
def llama(monkeypatch, tmp_path):
    """A llama-server stand-in on disk, and a models folder holding the light tier."""
    import stat
    exe = tmp_path / "llama-server"
    exe.write_text(FAKE_SERVER.format())
    exe.chmod(exe.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setenv("SAHL_LLAMA_SERVER", str(exe))
    monkeypatch.setenv("SAHL_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("SAHL_MODELS", str(tmp_path / "models"))
    (tmp_path / "models").mkdir()
    for m in ("qwen3-0.6b", "qwen3-vl-4b"):
        for f, _ in ai.MODELS[m][1]:
            (tmp_path / "models" / f).write_text("x")
    ai.set_tier("light")
    yield
    ai.stop_all()


def test_a_model_runs_in_its_own_server_and_is_stopped(llama, tmp_path):
    out = ai.chat({"model": "qwen3-0.6b", "messages": [{"role": "user", "content": "hi"}], "think": False}, timeout=10)
    assert out["ok"] and "--reasoning-budget" in out["args"] and "--mmproj" not in out["args"]
    text = ai._SERVERS["text"]
    assert text.healthy() and ai.running()
    pid = text.proc.pid
    vision = ai.chat({"model": "qwen3-vl-4b", "messages": [{"role": "user", "content": "hi"}]}, timeout=10)
    assert "--mmproj" in vision["args"] and ai._SERVERS["vision"].proc.pid != pid  # the image encoder rides with the vision model
    ai.stop_all()
    assert not text.alive() and not text.pidfile.exists() and not ai.running()


def test_a_server_left_over_from_a_killed_sidecar_is_stopped(llama, tmp_path):
    import subprocess
    old = subprocess.Popen([str(tmp_path / "llama-server"), "--port", "1"], stdout=subprocess.DEVNULL)  # a server whose sidecar was killed
    ai._SERVERS["text"].pidfile.parent.mkdir(parents=True, exist_ok=True)
    ai._SERVERS["text"].pidfile.write_text(str(old.pid))
    assert ai.chat({"model": "qwen3-0.6b", "messages": [{"role": "user", "content": "hi"}]}, timeout=10)["ok"]
    assert old.wait(5) is not None  # the old one was stopped when the new one started


def test_no_server_when_the_model_is_not_downloaded(llama, tmp_path):
    (tmp_path / "models" / "Qwen3-0.6B-Q8_0.gguf").unlink()
    assert ai.chat({"model": "qwen3-0.6b", "messages": [{"role": "user", "content": "hi"}]}, timeout=2) is None
    assert not ai._SERVERS["text"].alive()
