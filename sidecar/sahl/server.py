"""Local API the Sahl window talks to. Listens on 127.0.0.1 only; every call needs the launch token.

Run: SAHL_TOKEN=... python -m sahl.server   (prints SAHL_PORT=<n> once it is listening)
"""
import calendar
import json
import os
import re
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


def _shows(seen: str, want: str) -> bool:
    """Whether a box's text is exactly the value (a DD/MM/YYYY date may be written another way round).
    No OCR-slip leeway: a different date must never pass as the right one, or Sahl would leave a wrong box alone."""
    norm = lambda t: "".join(c for c in t.upper() if c.isalnum())
    seen = norm(seen)
    forms = [want]
    if m := re.fullmatch(r"(\d\d)/(\d\d)/(\d{4})", want):
        forms += ["".join((m[3], m[2], m[1])), "".join((m[2], m[1], m[3]))]
    return any(norm(f) and norm(f) in seen for f in forms)


def _needs(vault_key) -> str | None:
    """The document a field's value comes from first ("passport" or "eid"), to ask for when it's missing."""
    first = (vault_key if isinstance(vault_key, str) else (vault_key or [""])[0]).split(".")[0]
    return first if first in ("passport", "eid") else None


def _part_texts(kind, value):
    """What a dropdown may show for one part of a DD/MM/YYYY date: what to type, then what to look for on screen."""
    d, m, y = value.split("/")
    if kind == "y":
        return y, [y]
    if kind == "d":
        return d, [d, str(int(d))]
    short = calendar.month_abbr[int(m)]  # "Mar" selects both "Mar" and "March" as type-ahead; the full name stops matching after "Mar" on abbreviated lists
    return short, [short, m, str(int(m))]


def create_app(token: str, screen=ocr.screenshots, typer=fill.type_into, picker=fill.pick_from) -> FastAPI:
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
        # what the service is and needs, from the official page, shown before the person starts on the form
        return [{"id": g["id"], "service": g["service"], "about": g.get("about", ""), "requirements": g.get("requirements", {}),
                 "checked": g.get("checked")} for g in guides.values()]

    @app.get("/guides/search", dependencies=[Depends(auth)])
    def search_guides(q: str = ""):
        """The form search box: ids, best first, for what is typed so far."""
        return intent.search(q, guides)

    @app.post("/chat", dependencies=[Depends(auth)])
    def chat(body: Chat):
        """Sahl's next message in the "what form?" conversation, maybe offering a guide."""
        return intent.talk([t.model_dump() for t in body.messages], guides, vault.summary())

    @app.post("/read", dependencies=[Depends(auth)])
    def read(body: Read):
        g = guides.get(body.guide)
        if not g:
            raise HTTPException(404, "unknown guide")
        try:
            shots = screen()
        except Exception as e:  # macOS without Screen Recording permission, or a capture error on Windows
            raise HTTPException(409, f"screen capture failed: {e}")
        best, monitor, best_scale, unknown = [], None, 1.0, []
        for gray, scale, mon in shots:  # the form is on whichever monitor matches the most fields
            gray = gray.copy()
            H, W = gray.shape
            for x0, y0, x1, y1 in body.exclude:  # the panel shows field names that would match as labels
                c = lambda v, o, n: min(max(int((v - o) * scale), 0), n)
                gray[c(y0, mon[1], H):c(y1, mon[1], H), c(x0, mon[0], W):c(x1, mon[0], W)] = 255
            text = ocr.lines(gray)
            hits = match.match(text, g, gray, scale, mon[:2])
            if len(hits) > len(best):
                best, monitor, best_scale, shot = hits, mon, scale, (text, gray)
        everyone = vault.people()
        person = body.person if any(p["id"] == body.person for p in everyone) else (
            everyone[0]["id"] if len(everyone) == 1 else None)
        if body.restart or state["guide"] != (g["id"], person):  # Read again, or a new form/person: start from the first box
            state.update(guide=(g["id"], person), confirmed=set())
        spec = {f["id"]: f for f in g["fields"]}
        fields = []
        for m in best:
            f = spec[m["id"]]
            v = vault.get(f["vault_key"], person)
            if v and v["verified"] and f["input"] == "text" and not m.get("parts") and m["id"] not in state["confirmed"] \
                    and _box_shows(shot[1], best_scale, monitor, m["input_box"], v["value"], _shows):
                state["confirmed"].add(m["id"])  # the portal (UAE PASS) already filled this one with the right value
                m = {**m, "prefilled": True}
            fields.append({**m, "label": f["aliases"][0], "input": f["input"], "help": f["help"], "vault": vault.get(f["vault_key"], person),
                           "needs": _needs(f["vault_key"]), "confirmed": m["id"] in state["confirmed"]})
        state["fields"] = {f["id"]: f for f in fields}
        state["monitor"] = monitor
        state["scale"] = best_scale
        if report.enabled() and best:
            known = {match._norm(str(v["value"])) for x in guides.values() for f in x["fields"]
                     if (v := vault.get(f["vault_key"], person))}
            unknown = match.unknown_labels(shot[0], g, shot[1], known)
        report.record_read(g, fields, monitor, unknown)
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
        if f["input"] not in ("text", "date-parts"):
            raise HTTPException(422, "Sahl only fills text boxes and dates")
        if not v or not v["verified"]:
            raise HTTPException(422, "no verified value for this box")
        if f.get("parts"):  # three dropdowns; a date in one box is typed like any text
            return _fill_date(f, v["value"], body.field_id)
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

    def _fill_date(f, value, field_id):
        landed = True
        for part in f["parts"]:
            box = part["box"]
            if sys.platform == "win32":
                box = tuple(round(v * state["scale"]) for v in box)
            text, seen = _part_texts(part["kind"], value)
            for _ in range(2):  # the first pick can lose its keys while the browser comes to the front
                try:
                    picker(box, text)
                except Exception as e:
                    raise HTTPException(409, f"typing failed: {e}")
                time.sleep(0.3)
                shown = _shown([p["box"] for p in f["parts"]])[f["parts"].index(part)]
                ok = any(_matches(shown, s) for s in seen)
                if ok:
                    break
            landed = ok and landed
        if landed:
            state["confirmed"].add(field_id)
        else:
            report.record_miss(state["guide"][0], field_id)
        return {"ok": True, "landed": landed}

    def _shown(boxes):
        """What each of a date's dropdowns shows now. OCR misses a few digits in a tight crop of one box, so it reads
        one strip around all of them, with room to see them in context, and shares the words out by box."""
        for gray, scale, mon in screen():
            if tuple(mon) != tuple(state["monitor"]):
                continue
            pts = [tuple((v - mon[i % 2]) * scale for i, v in enumerate(b)) for b in boxes]
            pad = int(40 * scale)
            left, top = max(0, int(min(p[0] for p in pts)) - pad), max(0, int(min(p[1] for p in pts)) - pad)
            crop = gray[top:int(max(p[3] for p in pts)) + pad, left:int(max(p[2] for p in pts)) + pad]
            if crop.size:
                return match._inside([(p[0] - left, p[1] - top, p[2] - left, p[3] - top) for p in pts], ocr.lines(crop))
        return [""] * len(boxes)

    def _box_shows(gray, scale, mon, box, value, same=_matches) -> bool:
        """Reads one box (screen points) from a screenshot and checks `same(text, value)`."""
        x0, y0, x1, y1 = ((v - mon[i % 2]) * scale for i, v in enumerate(box))
        pad = 6 * scale  # OCR needs a margin round the text
        crop = gray[max(0, int(y0 - pad)):int(y1 + pad), max(0, int(x0 - pad)):int(x1 + pad)]
        if crop.size == 0:
            return False
        if same("".join(t for t, _ in ocr.lines(crop)), value):
            return True
        if crop.shape[1] < 400 or crop.shape[0] < 80:  # a small input, whose text OCR may miss at native size
            from PIL import Image
            big = np.array(Image.fromarray(crop).resize(
                (crop.shape[1] * 2, crop.shape[0] * 2), Image.Resampling.LANCZOS))
            return same("".join(t for t, _ in ocr.lines(big)), value)
        return False

    def _landed(box, value) -> bool:
        """Re-reads one box from the screen and checks it now shows the value."""
        for gray, scale, mon in screen():
            if tuple(mon) == tuple(state["monitor"]):
                return _box_shows(gray, scale, mon, box, value)
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
        return {"tier": ai.tier(), "running": ai.running(), "ollama": ai.binary() is not None, "pulling": ai.PULL, "tiers": [
            {"id": i, "text": t, "vision": v, "installed": on(t) and on(v)} for i, (t, v) in ai.TIERS.items()]}

    @app.post("/models", dependencies=[Depends(auth)])
    def set_models(body: Tier):
        ai.set_tier(body.tier)
        ai.prepare()  # download and load the new models now, so the next question isn't slow
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
    ai.prepare()
    ocr.engine()  # load the model before the first read
    library.watch()  # read new documents in the background
    uvicorn.Server(uvicorn.Config(create_app(token), log_level="warning")).run(sockets=[sock])


if __name__ == "__main__":
    main()
