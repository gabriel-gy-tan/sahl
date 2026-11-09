"""A loopback bridge for the browser extension.

The extension holds a long-lived token from a one-time pairing code shown in Sahl's settings. It sends page
metadata only; this bridge matches a guide and releases values from the local vault per field, never the page's
own values or the whole vault.
"""
import hashlib
import hmac
import os
import re
import secrets
import socket
import threading
import time
from collections import deque

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from . import vault, web

PORTS = tuple(range(8765, 8775))  # the first free one is used; the extension looks through all of them (its host permissions list the same)
PORT = PORTS[0]
TOKEN_FILE = "extension-token"
PAIRED_FILE = "extension-paired"  # a browser was given the token; gone after Unpair
LANG_FILE = "lang"  # the panel's language, so the extension speaks the same one
LANGS = ("en", "ar", "ur", "ml")
CODE_LIFE = 600  # seconds a pairing code stays usable
MAX_MISSES = 5  # wrong guesses that burn a code
EXTENSION = re.compile(r"^(?:chrome|moz)-extension://")


class Pairing(BaseModel):
    code: str = Field(max_length=12)
    name: str = Field("browser", max_length=80)


class Page(BaseModel):
    url: str = Field("", max_length=2000)
    title: str = Field("", max_length=500)
    headings: str = Field("", max_length=2000)
    person: str | None = None
    guide: str | None = None
    fields: list[dict] = Field(default_factory=list, max_length=500)


class Values(BaseModel):
    element_ids: list[str] = Field(max_length=200)
    person: str | None = None


class Tell(BaseModel):
    element_id: str = Field(max_length=100)
    value: str = Field(min_length=1, max_length=500)
    person: str | None = None


class Same(BaseModel):
    element_id: str = Field(max_length=100)
    concept: str = Field(max_length=80)


class State:
    def __init__(self, guides: dict, token: str | None = None, port: int | None = None, ports: tuple[int, ...] = PORTS):
        self.guides = guides
        self.ports = (port,) if port else tuple(ports)
        self.port = self.ports[0]  # the one in use, once bound
        self.token = token or _load_token()
        self.scans: dict[str, dict] = {}
        self.attempts: deque[float] = deque()
        self.running = False
        self.error = ""
        self.lock = threading.Lock()
        self.code, self.expires, self.misses = "", 0.0, 0
        self.fresh_code()

    def fresh_code(self) -> str:
        """The code shown in Settings: works once, for CODE_LIFE seconds, and dies after MAX_MISSES wrong guesses."""
        with self.lock:
            if not self.code or time.monotonic() > self.expires:
                self.code = f"{secrets.randbelow(1_000_000):06d}"
                self.expires = time.monotonic() + CODE_LIFE
                self.misses = 0
            return self.code

    def pair(self, code: str) -> str:
        now = time.monotonic()
        with self.lock:
            while self.attempts and now - self.attempts[0] > 60:
                self.attempts.popleft()
            if len(self.attempts) >= 8:
                raise HTTPException(429, "too many pairing attempts")
            self.attempts.append(now)
            if not self.code or now > self.expires or not secrets.compare_digest(code.strip(), self.code):
                self.misses += 1
                if self.misses >= MAX_MISSES:
                    self.code = ""  # guessing burns the code; Settings shows a new one when next opened
                raise HTTPException(403, "wrong or expired pairing code: open Sahl's Settings for a new one")
            self.code = ""  # one pairing per code
            self.attempts.clear()
            _paired_path().touch()
            return self.token

    @property
    def paired(self) -> bool:
        return _paired_path().exists()

    def unpair(self):
        """Every paired browser loses access: a new token, and a new code for the next pairing."""
        with self.lock:
            self.token = _new_token()
            self.scans.clear()
            self.code = ""
            _paired_path().unlink(missing_ok=True)
        self.fresh_code()


def _token_path():
    return vault.home() / TOKEN_FILE


def _paired_path():
    return vault.home() / PAIRED_FILE


def _new_token() -> str:
    token = secrets.token_hex(32)
    p = _token_path()
    try:
        p.write_text(token, encoding="ascii")
        os.chmod(p, 0o600)
    except OSError:
        pass
    return token


def _load_token() -> str:
    try:
        token = _token_path().read_text(encoding="ascii").strip()
    except OSError:
        token = ""
    return token if re.fullmatch(r"[0-9a-f]{64}", token) else _new_token()


def language() -> str:
    try:
        lang = (vault.home() / LANG_FILE).read_text(encoding="ascii").strip()
    except OSError:
        lang = ""
    return lang if lang in LANGS else "en"


def set_language(lang: str):
    (vault.home() / LANG_FILE).write_text(lang, encoding="ascii")


def _origin(origin: str = Header("")):
    if origin and not EXTENSION.match(origin):
        raise HTTPException(403, "this bridge is for the Sahl browser extension")


def _auth(state: State, token: str = Header("", alias="x-sahl-ext-token")):
    if not secrets.compare_digest(token, state.token):
        raise HTTPException(403, "pair with Sahl first")
    return token


def _public(scan: dict) -> dict:
    return {k: v for k, v in scan.items() if not k.startswith("_")}


def create_app(state: State) -> FastAPI:
    app = FastAPI()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[],
        allow_origin_regex=r"^(?:chrome|moz)-extension://.*$",
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["content-type", "x-sahl-ext-token"],
        max_age=600,
    )

    @app.middleware("http")
    async def loopback_only(request: Request, call_next):
        host = request.headers.get("host", "").split(":")[0].lower()
        if host not in ("127.0.0.1", "localhost", "testserver"):
            return JSONResponse({"detail": "loopback only"}, status_code=403)
        return await call_next(request)

    def auth(token: str = Header("", alias="x-sahl-ext-token")):
        return _auth(state, token)

    @app.get("/health")
    def health(nonce: str = Query("", max_length=64, pattern="^[0-9a-f]*$")):
        """Who answers. With a nonce, also a proof that this bridge holds the extension's token (an HMAC of the nonce), so a
        paired extension only sends its token and page details to the real one, whichever port it found it on."""
        out = {"app": "Sahl", "port": state.port, "running": state.running, "lang": language()}
        if nonce:
            out["proof"] = hmac.new(state.token.encode(), nonce.encode(), hashlib.sha256).hexdigest()
        return out

    @app.post("/pair")
    def pair(body: Pairing, _: None = Depends(_origin)):
        return {"token": state.pair(body.code), "name": body.name}

    @app.post("/page")
    def page(body: Page, token: str = Depends(auth)):
        scan = web.plan(body.model_dump(), state.guides, body.person, language())
        state.scans[token] = scan
        return _public(scan)

    @app.post("/values")
    def values(body: Values, token: str = Depends(auth)):
        scan = state.scans.get(token)
        if not scan:
            raise HTTPException(409, "scan the page first")
        return web.values(scan, body.element_ids, body.person)

    @app.post("/taught")
    def tell(body: Tell, token: str = Depends(auth)):
        """The person typed what goes in a box from the last scan that no guide knows."""
        if not body.value.strip():
            raise HTTPException(422, "type what goes in this box")
        concept = web.teach(state.scans.get(token) or {}, body.element_id, body.value.strip(), body.person)
        if not concept:
            raise HTTPException(404, "scan the page again")
        return {"concept": concept}

    @app.post("/taught/alias")
    def same(body: Same, token: str = Depends(auth)):
        """The person agreed a box from the last scan is a detail they told Sahl about under another name."""
        if not web.alias(state.scans.get(token) or {}, body.element_id, body.concept):
            raise HTTPException(404, "Sahl was not told about that")
        return {"ok": True}

    @app.post("/clear")
    def clear(token: str = Depends(auth)):
        state.scans.pop(token, None)
        return {"ok": True}

    return app


def _bind(state: State, retry: float) -> socket.socket:
    """Takes the first free port of the range; when every one is busy, says why in settings and tries again."""
    while True:
        why = ""
        for port in state.ports:
            sock = socket.socket()
            if os.name == "posix":  # a just-closed Sahl's connections linger on the port; on Windows this would let us share a live one
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind(("127.0.0.1", port))
                state.port = port
                return sock
            except OSError as e:
                sock.close()
                why = str(e)
        state.error = why
        time.sleep(retry)


def start(state: State, retry: float = 1.0):
    """Start the bridge in the background on the first free loopback port, as soon as there is one."""

    def run():
        import uvicorn
        sock = _bind(state, retry)
        state.error = ""
        state.running = True
        try:
            uvicorn.Server(uvicorn.Config(create_app(state), log_level="warning")).run(sockets=[sock])
        except Exception as e:
            state.error = str(e)
        finally:
            state.running = False

    threading.Thread(target=run, name="sahl-extension-bridge", daemon=True).start()
