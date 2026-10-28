"""Reads an identity document page with a local vision model (Ollama on this computer, nothing sent out).

Its answers are treated as proposals: vault.py checks them against the machine-readable zone and
the document number formats before anything is marked verified.
"""
import base64
import json
import os
import urllib.error
import urllib.request
from io import BytesIO

import numpy as np
from PIL import Image

OLLAMA = os.environ.get("SAHL_OLLAMA", "http://127.0.0.1:11434")
MODEL = os.environ.get("SAHL_MODEL", "qwen3-vl:8b-instruct")  # instruct: answers directly, no hidden reasoning

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


def available() -> bool:
    try:
        with urllib.request.urlopen(OLLAMA + "/api/tags", timeout=2) as r:
            return any(m["name"].startswith(MODEL) for m in json.load(r)["models"])
    except (urllib.error.URLError, OSError, KeyError, ValueError):
        return False


def read_page(gray: np.ndarray) -> dict | None:
    """The model's reading of one page, or None when the model isn't running."""
    img = Image.fromarray(gray)
    img.thumbnail((1280, 1280))  # plenty for ID text, keeps each call to a few seconds
    buf = BytesIO()
    img.save(buf, "PNG")
    body = {
        "model": MODEL,
        "stream": False,
        "think": False,
        "format": SCHEMA,
        "keep_alive": "30m",  # stay loaded while a folder is read
        "options": {"temperature": 0, "num_predict": 300},  # the answer is ~100 tokens; stop any runaway output
        "messages": [{"role": "user", "content": PROMPT, "images": [base64.b64encode(buf.getvalue()).decode()]}],
    }
    for _ in range(2):  # one retry: a busy or just-loading model sometimes returns nothing usable
        req = urllib.request.Request(OLLAMA + "/api/chat", json.dumps(body).encode(), {"content-type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=180) as r:
                out = json.loads(json.load(r)["message"]["content"])
            return {k: str(out.get(k, "")).strip() for k in FIELDS}
        except (urllib.error.URLError, OSError, KeyError, ValueError):
            continue
    return None
