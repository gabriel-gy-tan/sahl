"""Local API the Sahl window talks to. Listens on 127.0.0.1 only; every call needs the launch token.

Run: SAHL_TOKEN=... python -m sahl.server   (prints SAHL_PORT=<n> once it is listening)
"""
import json
import os
import secrets
import socket
import subprocess
import time
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from rapidfuzz import fuzz

from . import ai, fill, library, match, ocr, vault

GUIDES = Path(os.environ.get("SAHL_GUIDES", Path(__file__).resolve().parents[2] / "guides"))


def load_guides() -> dict:
    return {g["id"]: g for g in (json.loads(p.read_text()) for p in sorted(GUIDES.glob("*.json")))}


class Read(BaseModel):
    guide: str
    person: str | None = None  # whose documents fill this form; the only person if there is just one
    exclude: list[tuple[float, float, float, float]] = []  # screen boxes in points to blank, e.g. Sahl's own panel


class FieldRef(BaseModel):
    field_id: str


class ImportDoc(BaseModel):
    path: str


def create_app(token: str, screen=ocr.screenshots, typer=fill.type_into) -> FastAPI:
    app = FastAPI()
    # the Tauri webview's origins in dev and in a built app
    app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:1420", "tauri://localhost", "http://tauri.localhost"],
                       allow_methods=["*"], allow_headers=["*"])
    guides = load_guides()
    state = {"guide": None, "fields": {}, "confirmed": set(), "monitor": None}

    def auth(x_sahl_token: str = Header("")):
        if not secrets.compare_digest(x_sahl_token, token):
            raise HTTPException(403)

    @app.get("/guides", dependencies=[Depends(auth)])
    def list_guides():
        return [{"id": g["id"], "service": g["service"]} for g in guides.values()]

    @app.post("/read", dependencies=[Depends(auth)])
    def read(body: Read):
        g = guides.get(body.guide)
        if not g:
            raise HTTPException(404, "unknown guide")
        try:
            shots = screen()
        except Exception as e:  # macOS without Screen Recording permission lands here
            raise HTTPException(409, f"screen capture failed: {e}")
        best, monitor = [], None
        for gray, scale, mon in shots:  # the form is on whichever monitor matches the most fields
            gray = gray.copy()
            H, W = gray.shape
            for x0, y0, x1, y1 in body.exclude:  # the panel shows field names that would match as labels
                c = lambda v, o, n: min(max(int((v - o) * scale), 0), n)
                gray[c(y0, mon[1], H):c(y1, mon[1], H), c(x0, mon[0], W):c(x1, mon[0], W)] = 255
            hits = match.match(ocr.lines(gray), g, gray, scale, mon[:2])
            if len(hits) > len(best):
                best, monitor = hits, mon
        everyone = vault.people()
        person = body.person if any(p["id"] == body.person for p in everyone) else (
            everyone[0]["id"] if len(everyone) == 1 else None)
        if state["guide"] != (g["id"], person):  # a new form, or a different person: start from the first box
            state.update(guide=(g["id"], person), confirmed=set())
        spec = {f["id"]: f for f in g["fields"]}
        fields = []
        for m in best:
            f = spec[m["id"]]
            fields.append({**m, "label": f["aliases"][0], "input": f["input"], "help": f["help"], "vault": vault.get(f["vault_key"], person),
                           "confirmed": m["id"] in state["confirmed"]})
        state["fields"] = {f["id"]: f for f in fields}
        state["monitor"] = monitor
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
        try:
            typer(f["input_box"], v["value"])
        except Exception as e:  # macOS without Accessibility permission lands here
            raise HTTPException(409, f"typing failed: {e}")
        time.sleep(0.3)
        landed = _landed(f["input_box"], v["value"])
        if landed:  # only move on when the box visibly shows what was typed
            state["confirmed"].add(body.field_id)
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
            seen = "".join(t for t, _ in ocr.lines(crop)).replace(" ", "").upper()
            want = value.replace(" ", "").upper()
            # a narrow box shows only part of a long value
            return fuzz.ratio(seen, want) >= 90 or (len(seen) >= 6 and fuzz.partial_ratio(seen, want) >= 92)
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
        if not p.resolve().is_relative_to(lib.resolve()):
            library.add(p)
        return _sync()

    def _sync():
        found, skipped = vault.sync(library.folder())
        names = {x["id"]: x["name"] for x in vault.people()}
        return {"people": [names[str(i)] for i in found if str(i) in names], "skipped": skipped, "ai": ai.available()}

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

    @app.get("/people", dependencies=[Depends(auth)])
    def list_people():
        return vault.people()

    @app.post("/vault/forget", dependencies=[Depends(auth)])
    def vault_forget():
        with vault._IMPORT_LOCK:  # the background reader must not re-read files mid-forget
            try:
                library.forget()
            except subprocess.CalledProcessError:
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
    ocr.engine()  # load the model before the first read
    library.watch()  # read new documents in the background
    uvicorn.Server(uvicorn.Config(create_app(token), log_level="warning")).run(sockets=[sock])


if __name__ == "__main__":
    main()
