"""Local AI for Sahl: llama.cpp's llama-server runs the models on this computer, nothing is sent out.

A vision model reads one page of an identity document, and a small text model helps pick the form (intent.py).
The models are GGUF files from Hugging Face, downloaded only once the person agrees. Each model runs in its own
llama-server process, started when first needed and stopped after half an hour unused. The answers are treated as
proposals: vault.py checks them against the machine-readable zone and the document number formats before anything
is marked verified.
"""
import atexit
import base64
import hashlib
import http.client
import json
import os
import secrets
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from io import BytesIO
from pathlib import Path

import numpy as np
from PIL import Image

HF = os.environ.get("SAHL_MODEL_HOST", "https://huggingface.co")
# name -> (Hugging Face repo, ((file, GB), ...)). One file is a text model; two (model, then its mmproj image encoder) a vision model.
MODELS = {
    "qwen3-0.6b": ("Qwen/Qwen3-0.6B-GGUF", (("Qwen3-0.6B-Q8_0.gguf", 0.64),)),
    "qwen3-1.7b": ("Qwen/Qwen3-1.7B-GGUF", (("Qwen3-1.7B-Q8_0.gguf", 1.83),)),
    "qwen3-8b": ("Qwen/Qwen3-8B-GGUF", (("Qwen3-8B-Q4_K_M.gguf", 5.03),)),
    "qwen3-vl-4b": ("Qwen/Qwen3-VL-4B-Instruct-GGUF", (("Qwen3VL-4B-Instruct-Q4_K_M.gguf", 2.50), ("mmproj-Qwen3VL-4B-Instruct-F16.gguf", 0.84))),
    "qwen3-vl-8b": ("Qwen/Qwen3-VL-8B-Instruct-GGUF", (("Qwen3VL-8B-Instruct-Q4_K_M.gguf", 5.03), ("mmproj-Qwen3VL-8B-Instruct-F16.gguf", 1.16))),
    "qwen3-vl-30b": ("Qwen/Qwen3-VL-30B-A3B-Instruct-GGUF", (("Qwen3VL-30B-A3B-Instruct-Q4_K_M.gguf", 18.56), ("mmproj-Qwen3VL-30B-A3B-Instruct-F16.gguf", 1.08))),
}
# The person picks how big a pair of local models to run: (text model for the form picker, vision model for documents).
# Lighter is faster on a small computer; stronger needs a lot of memory. instruct: answers directly, no hidden reasoning.
TIERS = {
    "light": ("qwen3-0.6b", "qwen3-vl-4b"),
    "standard": ("qwen3-1.7b", "qwen3-vl-8b"),
    "strong": ("qwen3-8b", "qwen3-vl-30b"),
}


def _home() -> Path:
    from . import vault  # vault imports this module
    return vault.home()


def _tier_file() -> Path:
    return _home() / "models.json"


def _settings() -> dict:
    try:
        d = json.loads(_tier_file().read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _save(**kw):
    f = _tier_file()
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps({**_settings(), **kw}), encoding="utf-8")


def tier() -> str:
    t = _settings().get("tier")
    return t if t in TIERS else "standard"


def set_tier(t: str):
    _save(tier=t)


def consent() -> str:
    """Whether the person agreed to the model download: "ask" (not asked yet), "yes" or "no"."""
    c = _settings().get("download")
    return c if c in ("yes", "no") else "ask"


def set_consent(answer: str):
    _save(download=answer)
    if answer == "yes":
        _stop.clear()
        prepare()
    else:
        _stop.set()  # a download in progress stops; what is already on disk stays for later


def text_model() -> str:
    return TIERS[tier()][0]


def vision_model() -> str:
    return TIERS[tier()][1]


def models_dir() -> Path:
    return Path(os.environ.get("SAHL_MODELS") or _home() / "models")


def _files(model: str) -> tuple:
    return MODELS[model][1]


def have(model: str) -> bool:
    return all((models_dir() / f).is_file() for f, _ in _files(model))


def available(model: str | None = None) -> bool:
    return have(model or vision_model())


def need_gb(t: str) -> float:
    """What is still to download for a tier."""
    return round(sum(gb for m in TIERS[t] if not have(m) for _, gb in _files(m)), 1)


def free_gb() -> float:
    d = models_dir()
    while not d.exists() and d != d.parent:
        d = d.parent
    return round(shutil.disk_usage(d).free / 1e9, 1)


FIELDS = ["doc_type", "full_name", "nationality", "date_of_birth", "passport_number", "emirates_id_number", "expiry_date"]
SCHEMA = {
    "type": "object",
    "properties": {
        "doc_type": {"type": "string", "enum": ["passport", "emirates_id", "other"]},
        **{k: {"type": "string"} for k in FIELDS[1:]},
    },
    "required": FIELDS,
}
PROMPT = """You are reading one page of a personal document for the person it belongs to.
Return JSON only. Copy text exactly as printed in the human-readable part of the document, in English.
- doc_type: "passport", "emirates_id" (UAE resident identity card), or "other".
- full_name: the holder's full name, given names first, then surname, with normal spaces.
- nationality: the holder's nationality as printed (for example "Indian" or "India").
- date_of_birth, expiry_date: DD/MM/YYYY.
- passport_number: only on a passport.
- emirates_id_number: the 15-digit number starting 784, as 784-YYYY-NNNNNNN-N.
Use "" for anything not on this page. Do not guess."""


def binary() -> str | None:
    """Where llama-server is: SAHL_LLAMA_SERVER (set by the app, which carries its own), a checkout after build.py, or an install."""
    name = "llama-server.exe" if sys.platform == "win32" else "llama-server"
    built = Path(__file__).resolve().parents[2] / "app/src-tauri/llama" / name
    for path in (os.environ.get("SAHL_LLAMA_SERVER"), built, shutil.which("llama-server"),
                 "/opt/homebrew/bin/llama-server", "/usr/local/bin/llama-server"):
        if path and os.path.isfile(path):
            return str(path)
    return None


def _alive(pid: int) -> bool:
    """Whether pid is a llama-server (a pid file can outlive the process and its number be reused)."""
    try:
        if sys.platform == "win32":
            out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"], capture_output=True, text=True, creationflags=0x08000000).stdout
        else:
            out = subprocess.run(["ps", "-p", str(pid), "-o", "command="], capture_output=True, text=True).stdout
    except OSError:
        return False
    return "llama-server" in out


def _kill(pid: int):
    if sys.platform == "win32":
        subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True, creationflags=0x08000000)
    else:
        os.kill(pid, 15)


class _Server:
    """One llama-server process for one model. The sidecar can be killed without a chance to stop it, so the pid is
    kept in a file and a server left over from last time is stopped when the next one starts."""

    def __init__(self, role: str, context: int, slots: int, extra: tuple = ()):
        self.role, self.context, self.slots, self.extra = role, context, slots, extra
        self.proc, self.model, self.port, self.used = None, None, 0, 0.0
        self.token = secrets.token_urlsafe(16)
        self.lock = threading.Lock()

    @property
    def pidfile(self) -> Path:
        return _home() / f"llama-{self.role}.pid"

    def alive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def healthy(self) -> bool:
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{self.port}/health", timeout=2).close()
            return self.alive()
        except (urllib.error.URLError, OSError):
            return False

    def stop(self):
        if self.alive():
            self.proc.terminate()
            try:
                self.proc.wait(5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        self.proc = None
        self.pidfile.unlink(missing_ok=True)

    def ensure(self, model: str, wait: float = 180) -> bool:
        """The model is answering on its port, starting its server if needed; False when it can't be (not downloaded, no
        llama-server, too slow to load within `wait`: then it keeps loading and a later call finds it ready)."""
        with self.lock:
            self.used = time.time()
            if not (self.alive() and self.model == model):
                exe = binary()
                if not exe or not have(model):
                    return False
                self.stop()
                self._reap_stale()
                with socket.socket() as s:
                    s.bind(("127.0.0.1", 0))
                    self.port = s.getsockname()[1]
                files = [str(models_dir() / f) for f, _ in _files(model)]
                cmd = [exe, "-m", files[0], "--host", "127.0.0.1", "--port", str(self.port), "--api-key", self.token,
                       "-c", str(self.context), "-np", str(self.slots)]
                cmd += self.extra
                if len(files) > 1:
                    cmd += ["--mmproj", files[1]]
                log = open(os.environ["SAHL_LLAMA_LOG"] + self.role, "ab") if os.environ.get("SAHL_LLAMA_LOG") else subprocess.DEVNULL
                flags = {"creationflags": 0x08000000} if sys.platform == "win32" else {}  # no console window
                self.proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=log, stderr=log, cwd=os.path.dirname(exe), **flags)
                self.model = model
                self.pidfile.write_text(str(self.proc.pid))
                _watch_idle()
            end = time.time() + wait
            while time.time() < end:
                if not self.alive():
                    return False
                if self.healthy():
                    return True
                time.sleep(0.5)
            return False

    def _reap_stale(self):
        try:
            pid = int(self.pidfile.read_text())
        except (OSError, ValueError):
            return
        if _alive(pid):
            _kill(pid)
        self.pidfile.unlink(missing_ok=True)


# The text model answers short questions, two at a time, and may think up to 450 tokens before it must answer (the reply
# is cut off at 600 in intent.py, so an unfinished think would leave no answer); the vision model reads one page at a time.
_SERVERS = {"text": _Server("text", 16384, 2, ("--reasoning-budget", "450")), "vision": _Server("vision", 8192, 1)}
IDLE = 1800  # seconds unused before a model's memory is given back
_watching = threading.Lock()


def _watch_idle():
    """Once per run: a thread that stops a server nobody has used for IDLE seconds."""
    if not _watching.acquire(blocking=False):
        return

    def loop():
        while True:
            time.sleep(60)
            for s in _SERVERS.values():
                if s.alive() and time.time() - s.used > IDLE and s.lock.acquire(blocking=False):
                    try:
                        s.stop()
                    finally:
                        s.lock.release()
    threading.Thread(target=loop, daemon=True).start()


@atexit.register
def stop_all():
    for s in _SERVERS.values():
        s.stop()


def _server(model: str) -> _Server:
    return _SERVERS["vision" if len(_files(model)) > 1 else "text"]


def running() -> bool:
    return _SERVERS["text"].healthy()


PULL = {"model": None, "error": False, "reason": ""}  # the download in progress, for the panel
_pulling = threading.Lock()
_stop = threading.Event()  # set when the person says no, to end a download in progress
_SIZE: dict[str, int] = {}  # exact bytes of each file, as the host reports them


def progress(t: str | None = None) -> tuple[int, int]:
    """Bytes on disk and bytes in all for a tier's files (default: the chosen one), finished or part-way."""
    done = total = 0
    for m in TIERS[t or tier()]:
        for f, gb in _files(m):
            total += _SIZE.get(f) or int(gb * 1e9)
            for p in (models_dir() / f, models_dir() / (f + ".part")):
                if p.is_file():
                    done += p.stat().st_size
                    break
    return min(done, total), total


class _Direct(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None  # keep the host's own answer, which carries the file's size and hash


def _expected(url: str) -> tuple[int, str]:
    """(size, sha256) the host says this file has; (0, "") when it doesn't say."""
    try:
        urllib.request.build_opener(_Direct).open(urllib.request.Request(url, method="HEAD"), timeout=30).close()
        return 0, ""
    except urllib.error.HTTPError as e:  # Hugging Face answers a redirect to its storage, with the file's details in the headers
        h = e.headers
        return int(h.get("x-linked-size") or h.get("content-length") or 0), (h.get("x-linked-etag") or "").strip('"')


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(1 << 20):
            h.update(chunk)
    return h.hexdigest()


def _pull(model: str) -> bool:
    """One try at downloading a model's files. A part-way file is carried on from where it stopped, and checked against the
    host's hash at the end; a failed try leaves what it has for the next one."""
    repo, files = MODELS[model]
    PULL.update(model=model, error=False, reason="")
    models_dir().mkdir(parents=True, exist_ok=True)
    try:
        for name, _ in files:
            dest = models_dir() / name
            if dest.is_file():
                continue
            url = f"{HF}/{repo}/resolve/main/{name}"
            size, digest = _expected(url)
            if size:
                _SIZE[name] = size
            part = dest.with_name(name + ".part")
            got = part.stat().st_size if part.is_file() else 0
            if size and got > size:
                part.unlink()
                got = 0
            if not (size and got == size):
                req = urllib.request.Request(url, headers={"range": f"bytes={got}-"} if got else {})
                with urllib.request.urlopen(req, timeout=60) as r:  # 60 s of silence = the connection dropped
                    if got and r.status != 206:
                        got = 0  # the host sent the whole file again
                    with open(part, "ab" if got else "wb") as out:
                        while chunk := r.read(1 << 20):
                            if _stop.is_set():
                                PULL["model"] = None
                                return False
                            out.write(chunk)
                            got += len(chunk)
                if size and got != size:
                    raise OSError("cut short")
            if digest and _sha256(part) != digest:
                part.unlink()
                raise ValueError("the file did not match its hash")
            part.replace(dest)
    except (urllib.error.URLError, OSError, ValueError, http.client.HTTPException) as e:
        PULL.update(error=True, reason="space" if getattr(e, "errno", 0) == 28 else "other" if isinstance(e, ValueError) else "network")
        return False
    PULL["model"] = None
    return True


def _download(model: str):
    """Keeps trying (internet drops, disk is full) until the model is there or the person says no."""
    wait = 5
    while not _stop.is_set() and not have(model):
        left = sum(gb for _, gb in _files(model)) - sum(
            ((models_dir() / (f + ".part")).stat().st_size / 1e9 if (models_dir() / (f + ".part")).is_file() else 0) for f, _ in _files(model))
        if left * 1.1 > free_gb():
            PULL.update(model=model, error=True, reason="space")
        else:
            PULL.update(error=False, reason="")
            if _pull(model):
                return
        for _ in range(wait * 2):  # sleep in small steps so a "no" is heard at once
            if _stop.is_set():
                return
            time.sleep(0.5)
        wait = min(wait * 2, 60)


def prepare():
    """In the background: download the chosen models if the person agreed, then start the text model so the first question is quick."""
    def work():
        if not _pulling.acquire(blocking=False):
            return  # ponytail: a size picked mid-download starts after the current model; no restart of the loop
        _stop.clear()
        try:
            if binary():
                while consent() == "yes" and not _stop.is_set():
                    todo = [m for m in (text_model(), vision_model()) if not have(m)]
                    if not todo:
                        break
                    _download(todo[0])
                if have(text_model()):
                    _server(text_model()).ensure(text_model())
        finally:
            _pulling.release()
    threading.Thread(target=work, daemon=True).start()


def _request(body: dict) -> dict:
    """The chat request in the shape callers write (messages with images, think, format, options) as llama-server's OpenAI one."""
    messages = []
    for m in body["messages"]:
        content = m["content"]
        if m.get("images"):
            content = [{"type": "text", "text": content},
                       *({"type": "image_url", "image_url": {"url": "data:image/png;base64," + i}} for i in m["images"])]
        messages.append({"role": m["role"], "content": content})
    out = {"messages": messages, "stream": False, "chat_template_kwargs": {"enable_thinking": bool(body.get("think"))}}
    if "temperature" in body.get("options", {}):
        out["temperature"] = body["options"]["temperature"]
    if "num_predict" in body.get("options", {}):
        out["max_tokens"] = body["options"]["num_predict"]
    if body.get("format"):
        out["response_format"] = {"type": "json_schema", "json_schema": {"name": "answer", "schema": body["format"]}}
    return out


def chat(body: dict, timeout: float, tries: int = 2) -> dict | None:
    """One structured-output chat call to the local model named in body["model"]; the parsed JSON answer, or None."""
    srv = _server(body["model"])
    for _ in range(tries):  # a busy or just-loading model sometimes returns nothing usable
        if not srv.ensure(body["model"], wait=timeout):
            return None
        srv.used = time.time()
        req = urllib.request.Request(f"http://127.0.0.1:{srv.port}/v1/chat/completions", json.dumps(_request(body)).encode(),
                                     {"content-type": "application/json", "authorization": "Bearer " + srv.token})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(json.load(r)["choices"][0]["message"]["content"])
        except (urllib.error.URLError, OSError, KeyError, IndexError, ValueError, http.client.HTTPException):
            continue
    return None


def read_page(gray: np.ndarray) -> dict | None:
    """The model's reading of one page, or None when the model isn't running."""
    img = Image.fromarray(gray)
    img.thumbnail((1280, 1280))  # plenty for ID text, keeps each call to a few seconds
    buf = BytesIO()
    img.save(buf, "PNG")
    body = {
        "model": vision_model(),
        "think": False,
        "format": SCHEMA,
        "options": {"temperature": 0, "num_predict": 300},  # the answer is ~100 tokens; stop any runaway output
        "messages": [{"role": "user", "content": PROMPT, "images": [base64.b64encode(buf.getvalue()).decode()]}],
    }
    out = chat(body, timeout=180)
    return {k: str(out.get(k, "")).strip() for k in FIELDS} if isinstance(out, dict) else None
