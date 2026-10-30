"""Local API the Sahl window talks to. Listens on 127.0.0.1 only; every call needs the launch token.

Run: SAHL_TOKEN=... python -m sahl.server   (prints SAHL_PORT=<n> once it is listening)
"""
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

from . import ai, fill, intent, library, match, ocr, vault

GUIDES = Path(os.environ.get("SAHL_GUIDES", Path(__file__).resolve().parents[2] / "guides"))


def load_guides() -> dict:
    return {g["id"]: g for g in (json.loads(p.read_text(encoding="utf-8")) for p in sorted(GUIDES.glob("*.json")))}


class Read(BaseModel):
    guide: str
    person: str | None = None  # whose documents fill this form; the only person if there is just one
    exclude: list[tuple[float, float, float, float]] = []  # screen boxes in points to blank, e.g. Sahl's own panel
    restart: bool = False  # the Read form button: start this form from the first box again


class FieldRef(BaseModel):
    field_id: str


class PickRef(FieldRef):
    value: str


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


MONTH_NAMES = "January February March April May June July August September October November December".split()


def _flat(text: str) -> str:
    return "".join(c for c in text.casefold() if c.isalnum())


def _value_variants(value: str) -> set[str]:
    """The ways a portal may spell a verified value: country vs nationality, or a date."""
    out = {value}
    m = re.fullmatch(r"(\d{1,2})[./-](\d{1,2})[./-](\d{4})", value.strip())
    if m:
        day, month, year = (int(v) for v in m.groups())
        if 1 <= month <= 12:
            name = MONTH_NAMES[month - 1]
            short = vault.MONTHS[month - 1].title()
            out.update((f"{day}/{month}/{year}", f"{day}-{month}-{year}", f"{day} {month} {year}",
                        f"{day} {name} {year}", f"{day} {short} {year}", f"{name} {day}, {year}",
                        f"{short} {day}, {year}", f"{year}-{month:02d}-{day:02d}", f"{year} {name} {day}"))
    for country, nationality in vault.NATIONS.values():
        if value.casefold() in (country.casefold(), nationality.casefold()):
            out.update((country, nationality))
    return out


def _option_score(value: str, text: str) -> float:
    """How closely one visible dropdown or calendar label matches a verified value."""
    seen = _flat(text)
    if not seen:
        return 0
    date = re.fullmatch(r"(\d{1,2})[./-](\d{1,2})[./-](\d{4})", value.strip())
    if date:
        day, month, year = (int(v) for v in date.groups())
        tokens = set(re.findall(r"[a-z]+|\d+", text.casefold()))
        day_ok = str(day) in tokens or f"{day:02d}" in tokens
        month_ok = (str(month) in tokens or f"{month:02d}" in tokens
                    or MONTH_NAMES[month - 1].casefold() in tokens
                    or vault.MONTHS[month - 1].casefold() in tokens) if 1 <= month <= 12 else False
        return 100 if day_ok and month_ok and str(year) in tokens else 0
    best = 0.0
    for variant in _value_variants(value):
        want = _flat(variant)
        if not want:
            continue
        if want == seen:
            return 100
        if min(len(want), len(seen)) >= 3 and (want in seen or seen in want):
            best = max(best, 96)
        best = max(best, fuzz.ratio(want, seen), fuzz.partial_ratio(want, seen))
    return best


def _option_candidates(lines, field, scale, mon):
    """Lines that appeared below (or above) the opened control, in screen points."""
    x0, y0, x1, y1 = field["input_box"]
    w, h = max(x1 - x0, 8), max(y1 - y0, 8)
    below, above = [], []
    for text, box in lines:
        text = text.strip()
        if not text or len(text) > 70:
            continue
        left, top = box[0] / scale + mon[0], box[1] / scale + mon[1]
        right, bottom = box[2] / scale + mon[0], box[3] / scale + mon[1]
        cx, cy = (left + right) / 2, (top + bottom) / 2
        if not x0 - 0.75 * w <= cx <= x1 + 0.75 * w:
            continue
        item = (cy, cx, text, (left, top, right, bottom))
        if y1 + 0.05 * h < cy <= y1 + 24 * h:
            below.append(item)
        elif y0 - 24 * h <= cy < y0 - 0.05 * h:
            above.append(item)
    chosen = below if len(below) >= 2 else above if len(above) >= 2 else []
    out, seen = [], set()
    for _, _, text, box in sorted(chosen, key=lambda item: (item[0], item[1])):
        key = (text.casefold(), round(box[1]))
        if key in seen:
            continue
        seen.add(key)
        out.append({"label": text, "box": box})
        if len(out) == 60:
            break
    return out


def create_app(token: str, screen=ocr.screenshots, typer=fill.type_into,
               opener=fill.open_list, picker=fill.pick_option) -> FastAPI:
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
                           "confirmed": m["id"] in state["confirmed"]})
        state["fields"] = {f["id"]: f for f in fields}
        state["monitor"] = monitor
        state["scale"] = best_scale
        nxt = next((f["id"] for f in fields if not f["confirmed"]), None)
        return {"fields": fields, "next": nxt, "monitor": monitor, "person": person, "people": everyone}

    def _field(field_id):
        f = state["fields"].get(field_id)
        if not f:
            raise HTTPException(404, "field not on screen at last read")
        return f

    def _physical(box):
        # pynput's SetCursorPos uses physical pixels once mss makes the process DPI-aware
        return tuple(round(v * state["scale"]) for v in box) if sys.platform == "win32" else box

    def _open_options(f):
        if state["monitor"] is None:
            raise HTTPException(409, "list failed: no form on screen")
        try:
            opener(_physical(f["input_box"]))
        except Exception as e:  # no permission to click, or the form is elevated
            raise HTTPException(409, f"list failed: {e}")
        time.sleep(0.35)
        try:
            shots = screen()
        except Exception as e:
            raise HTTPException(409, f"screen capture failed: {e}")
        for gray, scale, mon in shots:
            if tuple(mon) == tuple(state["monitor"]):
                return _option_candidates(ocr.lines(gray), f, scale, mon)
        raise HTTPException(409, "list failed: the form's screen is gone")

    def _best_option(value, options):
        scored = [(_option_score(value, option["label"]), option) for option in options]
        return max(scored, default=(0, None), key=lambda pair: pair[0])

    def _pick_option(f, option):
        try:
            picker(_physical(option["box"]))
        except Exception as e:
            raise HTTPException(409, f"list failed: {e}")
        time.sleep(0.3)
        landed = _landed(f["input_box"], option["label"])
        if landed:
            state["confirmed"].add(f["id"])
        return landed

    def _type_verified(f, value):
        try:
            typer(_physical(f["input_box"]), value)
        except Exception as e:
            raise HTTPException(409, f"typing failed: {e}")
        time.sleep(0.3)
        landed = _landed(f["input_box"], value)
        if landed:
            state["confirmed"].add(f["id"])
        return landed

    @app.post("/confirm", dependencies=[Depends(auth)])
    def confirm(body: FieldRef):
        _field(body.field_id)
        state["confirmed"].add(body.field_id)
        return {"ok": True}

    @app.post("/options", dependencies=[Depends(auth)])
    def options(body: FieldRef):
        f = _field(body.field_id)
        if f["input"] not in ("select", "date", "choice"):
            raise HTTPException(422, "this box is not a list or date")
        return {"options": _open_options(f)}

    @app.post("/choose", dependencies=[Depends(auth)])
    def choose(body: PickRef):
        f = _field(body.field_id)
        if f["input"] not in ("select", "date", "choice"):
            raise HTTPException(422, "this box is not a list or date")
        options = _open_options(f)
        score, option = _best_option(body.value, options)
        if not option or score < 82:
            return {"landed": False, "options": options}
        landed = _pick_option(f, option)
        return {"landed": landed, "options": options if not landed else []}

    @app.post("/fill", dependencies=[Depends(auth)])
    def do_fill(body: FieldRef):
        f = _field(body.field_id)
        v = f["vault"]
        if not v or not v["verified"]:
            raise HTTPException(422, "no verified value for this box")
        if f["input"] == "text":
            return {"ok": True, "landed": _type_verified(f, v["value"])}
        if f["input"] not in ("select", "date", "choice"):
            raise HTTPException(422, "Sahl can't fill this kind of box")
        if f["input"] in ("date", "choice") and _type_verified(f, v["value"]):
            return {"ok": True, "landed": True, "options": []}  # a plain text or native date input
        options = _open_options(f)
        score, option = _best_option(v["value"], options)
        if option and score >= 88 and _pick_option(f, option):
            return {"ok": True, "landed": True, "options": []}
        return {"ok": True, "landed": False, "options": options}

    def _landed(box, value) -> bool:
        """Re-reads one box from the screen and checks it now shows the value."""
        for gray, scale, mon in screen():
            if tuple(mon) != tuple(state["monitor"]):
                continue
            x0, y0, x1, y1 = ((v - mon[i % 2]) * scale for i, v in enumerate(box))
            pad = 6 * scale
            crops = [gray[max(0, int(y0)):int(y1), max(0, int(x0)):int(x1)],
                     gray[max(0, int(y0 - pad)):int(y1 + pad), max(0, int(x0 - pad)):int(x1 + pad)]]
            for crop in crops:
                if crop.size and _matches("".join(t for t, _ in ocr.lines(crop)), value):
                    return True
            if any(crop.size and (crop.shape[1] < 400 or crop.shape[0] < 80) for crop in crops):
                from PIL import Image
                for crop in crops:
                    if not crop.size:
                        continue
                    big = np.array(Image.fromarray(crop).resize(
                        (crop.shape[1] * 2, crop.shape[0] * 2), Image.Resampling.LANCZOS))
                    if _matches("".join(t for t, _ in ocr.lines(big)), value):
                        return True
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
