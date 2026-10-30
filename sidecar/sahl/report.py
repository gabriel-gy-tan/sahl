""""Help improve Sahl": off unless the person turns it on. Then each form gets a small report, on this computer, of which
of its boxes Sahl found, never saw, or typed into and missed, for whoever maintains the guides.

A report holds only what Sahl matched to a guide's own label words (the label as the form prints it) and where the
boxes sit as fractions of the screen. Never a value, never other text from the screen, never anything from the
documents. Nothing here sends anything: the person reads the report and chooses whether to share it.
"""
import json
import time

from . import vault


def _dir():
    p = vault.home() / "reports"
    p.mkdir(exist_ok=True)
    return p


def _flag():
    return vault.home() / "improve.json"


def enabled() -> bool:
    try:
        return json.loads(_flag().read_text(encoding="utf-8"))["on"] is True
    except (OSError, ValueError, KeyError):
        return False


def set_enabled(on: bool):
    _flag().write_text(json.dumps({"on": on}), encoding="utf-8")


def _file(guide_id: str):
    return _dir() / f"{time.strftime('%Y-%m-%d')}-{guide_id}.json"  # one report per form a day


def _load(guide_id: str) -> dict:
    try:
        return json.loads(_file(guide_id).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"guide": guide_id, "date": time.strftime("%Y-%m-%d"), "found": {}, "not_seen": [], "missed": []}


def _save(r: dict):
    r["not_seen"] = [i for i in r["not_seen"] if i not in r["found"]]
    _file(r["guide"]).write_text(json.dumps(r, ensure_ascii=False, indent=2), encoding="utf-8")


def record_read(guide: dict, fields: list[dict], monitor):
    """Adds one read of a form: each found box's printed label and where it is; the guide's boxes not seen."""
    if not enabled() or not monitor:
        return
    x0, y0, w, h = monitor
    rel = lambda b: [round((b[0] - x0) / w, 3), round((b[1] - y0) / h, 3), round((b[2] - x0) / w, 3), round((b[3] - y0) / h, 3)]
    r = _load(guide["id"])
    for f in fields:
        r["found"][f["id"]] = {"label": f["seen"][:80], "label_box": rel(f["label_box"]), "input_box": rel(f["input_box"])}
    r["not_seen"] = sorted(set(r["not_seen"]) | {f["id"] for f in guide["fields"]} - {f["id"] for f in fields})
    _save(r)


def record_miss(guide_id: str, field_id: str):
    """Sahl typed into a box and the screen didn't show it: the box was probably found in the wrong place."""
    if not enabled():
        return
    r = _load(guide_id)
    if field_id not in r["missed"]:
        r["missed"].append(field_id)
    _save(r)


def listing() -> list[dict]:
    """Each report, newest first, with its counts and its text (to copy into an issue)."""
    out = []
    for p in sorted(_dir().glob("*.json"), reverse=True):
        try:
            r = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        out.append({"file": p.name, "guide": r["guide"], "date": r["date"], "found": len(r["found"]),
                    "not_seen": len(r["not_seen"]), "missed": len(r["missed"]), "text": p.read_text(encoding="utf-8")})
    return out
