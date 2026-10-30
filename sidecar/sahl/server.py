"""Local API the Sahl window talks to. Listens on 127.0.0.1 only; every call needs the launch token.

Run: SAHL_TOKEN=... python -m sahl.server   (prints SAHL_PORT=<n> once it is listening)
"""
import json
import os
import secrets
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Literal

import numpy as np
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from rapidfuzz import fuzz

from . import ai, fill, intent, library, match, ocr, report, vault

GUIDES = Path(os.environ.get("SAHL_GUIDES", Path(__file__).resolve().parents[2] / "guides"))


def load_guides() -> dict:
    return {g["id"]: g for g in (json.loads(p.read_text(encoding="utf-8")) for p in sorted(GUIDES.glob("*.json")))}


class Read(BaseModel):
    guide: str
    person: str | None = None  # whose documents fill this form; the only person if there is just one
    exclude: list[tuple[float, float, float, float]] = []  # screen boxes in points to blank, e.g. Sahl's own panel
    restart: bool = False  # the Read form button: start this form from the first box again


class Improve(BaseModel):
    on: bool


class Tier(BaseModel):
    tier: Literal[tuple(ai.TIERS)]


class FieldRef(BaseModel):
    field_id: str


class ImportDoc(BaseModel):
    path: str


class Turn(BaseModel):
    role: Literal["user", "assistant"]
    text: str = Field(max_length=2000)


class Chat(BaseModel):
    messages: list[Turn] = Field(max_length=50)


def _matches(seen: str, want: str) -> bool:
    """Whether OCR's reading of a box is the value Sahl typed. Short values get more room for an OCR slip."""
    seen = "".join(c for c in seen.upper() if c.isalnum())
    want = "".join(c for c in want.upper() if c.isalnum())
    if not seen or not want:
        return False
    if seen == want or (len(want) >= 3 and want in seen):
        return True
    score = fuzz.ratio(seen, want)
    if score >= 90 or (len(want) <= 12 and score >= 85) or (len(want) <= 6 and score >= 80):
        return True
    return len(seen) >= 4 and fuzz.partial_ratio(seen, want) >= 92


def _needs(vault_key) -> str | None:
    """The document a field's value comes from first ("passport" or "eid"), to ask for when it's missing."""
    first = (vault_key if isinstance(vault_key, str) else (vault_key or [""])[0]).split(".")[0]
    return first if first in ("passport", "eid") else None


def create_app(token: str, screen=ocr.screenshots, typer=fill.type_into) -> FastAPI:
    app = FastAPI()
    # the Tauri webview's origins in dev and in a built app
    app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:1420", "tauri://localhost", "http://tauri.localhost"],
                       allow_methods=["*"], allow_headers=["*"])
    guides = load_guides()
    state = {"guide": None, "fields": {}, "confirmed": set(), "monitor": None, "scale": 1.0}

    def auth(x_sahl_token: str = Header("")):
        if not secrets.compare_digest(x_sahl_token, token):
            raise HTTPException(403)

    @app.get("/guides", dependencies=[Depends(auth)])
    def list_guides():
        return [{"id": g["id"], "service": g["service"]} for g in guides.values()]

    @app.post("/chat", dependencies=[Depends(auth)])
    def chat(body: Chat):
        """Sahl's next message in the "what form?" conversation, maybe offering a guide."""
        return intent.talk([t.model_dump() for t in body.messages], guides)

    @app.post("/read", dependencies=[Depends(auth)])
    def read(body: Read):
        g = guides.get(body.guide)
        if not g:
            raise HTTPException(404, "unknown guide")
        try:
            shots = screen()
        except Exception as e:  # macOS without Screen Recording permission, or a capture error on Windows
            raise HTTPException(409, f"screen capture failed: {e}")
        best, monitor, best_scale = [], None, 1.0
        for gray, scale, mon in shots:  # the form is on whichever monitor matches the most fields
            gray = gray.copy()
            H, W = gray.shape
            for x0, y0, x1, y1 in body.exclude:  # the panel shows field names that would match as labels
                c = lambda v, o, n: min(max(int((v - o) * scale), 0), n)
                gray[c(y0, mon[1], H):c(y1, mon[1], H), c(x0, mon[0], W):c(x1, mon[0], W)] = 255
            hits = match.match(ocr.lines(gray), g, gray, scale, mon[:2])
            if len(hits) > len(best):
                best, monitor, best_scale = hits, mon, scale
        everyone = vault.people()
        person = body.person if any(p["id"] == body.person for p in everyone) else (
            everyone[0]["id"] if len(everyone) == 1 else None)
        if body.restart or state["guide"] != (g["id"], person):  # Read again, or a new form/person: start from the first box
            state.update(guide=(g["id"], person), confirmed=set())
        spec = {f["id"]: f for f in g["fields"]}
        fields = []
        for m in best:
            f = spec[m["id"]]
            fields.append({**m, "label": f["aliases"][0], "input": f["input"], "help": f["help"], "vault": vault.get(f["vault_key"], person),
                           "needs": _needs(f["vault_key"]), "confirmed": m["id"] in state["confirmed"]})
        state["fields"] = {f["id"]: f for f in fields}
        state["monitor"] = monitor
        state["scale"] = best_scale
        report.record_read(g, fields, monitor)
        nxt = next((f["id"] for f in fields if not f["confirmed"]), None)
        return {"fields": fields, "next": nxt, "monitor": monitor, "person": person, "people": everyone}

    def _field(field_id):
        f = state["fields"].get(field_id)
        if not f:
            raise HTTPException(404, "field not on screen at last read")
        return f

    @app.post("/confirm", dependencies=[Depends(auth)])
    def confirm(body: FieldRef):
        _field(body.field_id)
        state["confirmed"].add(body.field_id)
        return {"ok": True}

    @app.post("/fill", dependencies=[Depends(auth)])
    def do_fill(body: FieldRef):
        f = _field(body.field_id)
        v = f["vault"]
        if f["input"] != "text":
            raise HTTPException(422, "Sahl only types into plain text boxes")
        if not v or not v["verified"]:
            raise HTTPException(422, "no verified value for this box")
        box = f["input_box"]  # screen points
        if sys.platform == "win32":  # pynput's SetCursorPos uses physical pixels once mss makes the process DPI-aware
            box = tuple(round(v * state["scale"]) for v in box)
        try:
            typer(box, v["value"])
        except Exception as e:  # no permission to type, or the form is elevated
            raise HTTPException(409, f"typing failed: {e}")
        time.sleep(0.3)
        landed = _landed(f["input_box"], v["value"])
        if landed:  # only move on when the box visibly shows what was typed
            state["confirmed"].add(body.field_id)
        else:
            report.record_miss(state["guide"][0], body.field_id)
        return {"ok": True, "landed": landed}

    def _landed(box, value) -> bool:
        """Re-reads one box from the screen and checks it now shows the value."""
        for gray, scale, mon in screen():
            if tuple(mon) != tuple(state["monitor"]):
                continue
            x0, y0, x1, y1 = ((v - mon[i % 2]) * scale for i, v in enumerate(box))
            pad = 6 * scale  # OCR needs a margin round the text
            crop = gray[max(0, int(y0 - pad)):int(y1 + pad), max(0, int(x0 - pad)):int(x1 + pad)]
            if crop.size == 0:
                return False
            if _matches("".join(t for t, _ in ocr.lines(crop)), value):
                return True
            if crop.shape[1] < 400 or crop.shape[0] < 80:  # a small input, whose text OCR may miss at native size
                from PIL import Image
                big = np.array(Image.fromarray(crop).resize(
                    (crop.shape[1] * 2, crop.shape[0] * 2), Image.Resampling.LANCZOS))
                return _matches("".join(t for t, _ in ocr.lines(big)), value)
            return False
        return False

    @app.post("/vault/import", dependencies=[Depends(auth)])
    def vault_import(body: ImportDoc):
        """A dropped file or folder is copied into the documents folder, which is then read."""
        p = Path(body.path).expanduser()
        if not p.exists():
            raise HTTPException(404, "file not found")
        if p.is_file() and p.suffix.lower() not in vault.DOCUMENTS:
            raise HTTPException(422, "Sahl reads PDF, PNG and JPG files")
        lib = library.folder()
        before = vault.documents()  # before the copy, so a background read of it still counts as this import's
        if not p.resolve().is_relative_to(lib.resolve()):
            library.add(p)
        return _sync(before)

    def _sync(before=None):
        """read: the documents this sync read, as {person (their name, or None), type}, for the panel to say so."""
        before = vault.documents() if before is None else before
        found, skipped = vault.sync(library.folder())
        names = {x["id"]: x["name"] for x in vault.people()}
        read = [{"person": names.get(pid), "type": doc} for path, (m, pid, doc) in vault.documents().items()
                if before.get(path, (None,))[0] != m]
        return {"people": [names[str(i)] for i in found if str(i) in names], "read": read, "skipped": skipped,
                "ai": ai.available()}

    @app.post("/vault/sync", dependencies=[Depends(auth)])
    def vault_sync():
        return _sync()

    @app.get("/library", dependencies=[Depends(auth)])
    def get_library():
        return {"path": str(library.folder())}

    @app.post("/library", dependencies=[Depends(auth)])
    def set_library(body: ImportDoc):
        p = Path(body.path).expanduser()
        if not p.is_dir():
            raise HTTPException(404, "folder not found")
        library.set_folder(p)
        return {"path": str(p), **_sync()}

    @app.get("/vault/progress", dependencies=[Depends(auth)])
    def vault_progress():
        return vault.PROGRESS

    @app.get("/models", dependencies=[Depends(auth)])
    def get_models():
        """The model sizes to choose from, and whether this computer has each pair downloaded."""
        have = ai.installed()
        on = lambda m: any(n.startswith(m) for n in have)
        return {"tier": ai.tier(), "running": bool(have), "tiers": [
            {"id": i, "text": t, "vision": v, "installed": on(t) and on(v)} for i, (t, v) in ai.TIERS.items()]}

    @app.post("/models", dependencies=[Depends(auth)])
    def set_models(body: Tier):
        ai.set_tier(body.tier)
        intent.warm()  # load the new text model now, so the next question isn't slow
        return get_models()

    @app.get("/improve", dependencies=[Depends(auth)])
    def get_improve():
        return {"on": report.enabled(), "folder": str(report._dir()), "reports": report.listing()}

    @app.post("/improve", dependencies=[Depends(auth)])
    def set_improve(body: Improve):
        report.set_enabled(body.on)
        return get_improve()

    @app.post("/improve/reveal", dependencies=[Depends(auth)])
    def reveal_reports():
        """Opens the reports folder in Finder / File Explorer, for the person to look at or attach."""
        folder = str(report._dir())
        if sys.platform == "win32":
            os.startfile(folder)
        else:
            subprocess.run(["open" if sys.platform == "darwin" else "xdg-open", folder], check=False)
        return {"ok": True}

    @app.get("/vault/summary", dependencies=[Depends(auth)])
    def vault_summary():
        return vault.summary()

    @app.get("/people", dependencies=[Depends(auth)])
    def list_people():
        return vault.people()

    @app.post("/vault/forget", dependencies=[Depends(auth)])
    def vault_forget():
        with vault._IMPORT_LOCK:  # the background reader must not re-read files mid-forget
            try:
                library.forget()
            except (OSError, subprocess.SubprocessError):
                raise HTTPException(409, "couldn't move the documents to the Trash")
            vault.forget_all()
        return {"ok": True}

    return app


def main():
    import uvicorn
    token = os.environ.get("SAHL_TOKEN") or secrets.token_urlsafe(24)
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    print(f"SAHL_PORT={sock.getsockname()[1]}", flush=True)
    if "SAHL_TOKEN" not in os.environ:
        print(f"SAHL_TOKEN={token}", flush=True)
    intent.warm()
    ocr.engine()  # load the model before the first read
    library.watch()  # read new documents in the background
    uvicorn.Server(uvicorn.Config(create_app(token), log_level="warning")).run(sockets=[sock])


if __name__ == "__main__":
    main()
