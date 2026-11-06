"""A loopback bridge for the browser extension.

The extension holds a long-lived token from a one-time pairing code shown in Sahl's settings. It sends page
metadata only; this bridge matches a guide and releases values from the local vault per field, never the page's
own values or the whole vault.
"""
import os
import re
import secrets
import socket
import threading
import time
from collections import deque

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from . import vault, web

PORT = 8765
TOKEN_FILE = "extension-token"
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


class State:
    def __init__(self, guides: dict, token: str | None = None, port: int = PORT):
        self.guides = guides
        self.port = port
        self.token = token or _load_token()
        self.code = f"{secrets.randbelow(1_000_000):06d}"
        self.scans: dict[str, dict] = {}
        self.attempts: deque[float] = deque()
        self.running = False
        self.error = ""
        self.lock = threading.Lock()

    def pair(self, code: str) -> str:
        now = time.monotonic()
        with self.lock:
            while self.attempts and now - self.attempts[0] > 60:
                self.attempts.popleft()
            if len(self.attempts) >= 8:
                raise HTTPException(429, "too many pairing attempts")
            self.attempts.append(now)
            if not secrets.compare_digest(code.strip(), self.code):
                raise HTTPException(403, "wrong pairing code")
            self.attempts.clear()
            return self.token


def _token_path():
    return vault.home() / TOKEN_FILE


def _load_token() -> str:
    p = _token_path()
    try:
        token = p.read_text(encoding="ascii").strip()
    except OSError:
        token = ""
    if not re.fullmatch(r"[0-9a-f]{64}", token):
        token = secrets.token_hex(32)
        try:
            p.write_text(token, encoding="ascii")
            os.chmod(p, 0o600)
        except OSError:
            pass
    return token


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
    def health():
        return {"app": "Sahl", "port": state.port, "running": state.running}

    @app.post("/pair")
    def pair(body: Pairing, _: None = Depends(_origin)):
        return {"token": state.pair(body.code), "name": body.name}

    @app.post("/page")
    def page(body: Page, token: str = Depends(auth)):
        scan = web.plan(body.model_dump(), state.guides, body.person)
        state.scans[token] = scan
        return _public(scan)

    @app.post("/values")
    def values(body: Values, token: str = Depends(auth)):
        scan = state.scans.get(token)
        if not scan:
            raise HTTPException(409, "scan the page first")
        return web.values(scan, body.element_ids, body.person)

    @app.post("/clear")
    def clear(token: str = Depends(auth)):
        state.scans.pop(token, None)
        return {"ok": True}

    return app


def start(state: State):
    """Start the bridge on its fixed loopback port, if it is free. A failure is shown in settings."""
    probe = socket.socket()
    try:
        probe.bind(("127.0.0.1", state.port))
    except OSError as e:
        state.error = str(e)
        return False
    finally:
        probe.close()

    def run():
        import uvicorn
        state.running = True
        try:
            uvicorn.Server(uvicorn.Config(create_app(state), host="127.0.0.1", port=state.port, log_level="warning")).run()
        except Exception as e:
            state.error = str(e)
        finally:
            state.running = False

    threading.Thread(target=run, name="sahl-extension-bridge", daemon=True).start()
    for _ in range(50):
        if state.running:
            return True
        time.sleep(0.02)
    return state.running
