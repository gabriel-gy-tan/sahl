"""A short conversation that helps someone find the form they want, with a small local text model.

Two jobs, two calls: one model call only writes Sahl's reply, another only decides whether to offer a guide.
A 1.7B model does each well and both badly at once. The offer is checked against the guide list, and the person
still chooses it.
"""
import os
import threading
from concurrent.futures import ThreadPoolExecutor

from rapidfuzz import fuzz

from . import ai

MODEL = os.environ.get("SAHL_INTENT_MODEL", "qwen3:1.7b")
GENERIC = "any-form"  # used when Sahl has no guide for the form; never offered as a match

PICK = """You help a UAE resident find the government form they want to fill in.
These are the forms you know, one per line as id: names | what it is for.
{catalogue}

The person wrote: "{text}"

Answer JSON only.
- kind "match" and guide = its id, when they clearly want to fill in, book or start one of the forms above.
- kind "new" and name = the service in a few of their own words (same language), when they want to fill in a specific service or form that is not above.
- kind "unsure" for anything else: a question about a form, a greeting, or vague words like "help", "a form" or "hi".
Never pick a form just because it shares a word; it must be the thing they are asking to do."""

TALK = """You are Sahl, a calm helper on a UAE resident's own computer. You help them with government forms.
The forms you have a guide for, as names | what it is for:
{catalogue}

Their last message is in {language}: reply in {language}, in one to three short, kind sentences. Plain words only: no lists,
no JSON, no web addresses.
- Explain a form only with what is written above. You don't know fees, required documents, deadlines, places or
  rules: when asked, say you aren't sure and that the official government website has it. Never guess them.
- Never ask for their personal details: Sahl reads those from their own documents later.
- When they want one of the forms above, say Sahl can help them fill it in.
You can't log in, pay or submit anything for them."""


def catalogue(guides: dict) -> dict:
    return {i: g for i, g in guides.items() if i != GENERIC}


def _names(g: dict) -> list[str]:
    return [s.split("·")[0].strip() for s in g["service"].values()]  # "Residency medical fitness · booking" -> head


def _instant(text: str, guides: dict) -> str | None:
    """A guide whose name is plainly in the text, with no model call."""
    t = text.casefold()
    best, score = None, 0.0
    for i, g in guides.items():
        for n in _names(g):
            if len(n) < 5:
                continue
            s = fuzz.partial_ratio(n.casefold(), t)
            if s > score:
                best, score = i, s
    return best if score >= 90 else None


def pick(text: str, guides: dict) -> dict:
    """{kind: match|new|unsure, guide: id or None, name: the service in their words for "new"}."""
    known = catalogue(guides)
    text = text.strip()[:300]
    if not text:
        return {"kind": "unsure", "guide": None, "name": ""}
    if hit := _instant(text, known):
        return {"kind": "match", "guide": hit, "name": ""}
    lines = "\n".join(f"{i}: {' / '.join(dict.fromkeys(_names(g)))} | {g.get('about', '')}" for i, g in known.items())
    out = ai.chat({
        "model": MODEL,
        "stream": False,
        "think": True,  # a short think is what tells "medical for my visa" apart from a new service
        "format": {
            "type": "object",
            "properties": {"kind": {"type": "string", "enum": ["match", "new", "unsure"]},
                           "guide": {"type": "string", "enum": [*known, ""]},
                           "name": {"type": "string"}},
            "required": ["kind", "guide", "name"],
        },
        "keep_alive": "30m",
        "options": {"temperature": 0, "num_predict": 600},
        "messages": [{"role": "user", "content": PICK.format(catalogue=lines, text=text.replace('"', "'"))}],
    }, timeout=20, tries=1)
    if not isinstance(out, dict):
        return {"kind": "unsure", "guide": None, "name": ""}
    kind, guide, name = out.get("kind"), out.get("guide"), str(out.get("name", "")).strip()[:60]
    if kind == "match" and guide in known:  # the model's id is only trusted if it is a real guide
        return {"kind": "match", "guide": guide, "name": ""}
    # small models sometimes call a vague "help" a new service and name it after a known guide
    if (kind == "new" and name and fuzz.token_set_ratio(name.casefold(), text.casefold()) >= 60
            and not any(_instant(name, {i: g}) for i, g in known.items())):
        return {"kind": "new", "guide": None, "name": name}
    return {"kind": "unsure", "guide": None, "name": ""}


def _language(text: str) -> str:
    """The small model often answers in English; naming the language keeps it in theirs."""
    if any("\u0d00" <= c <= "\u0d7f" for c in text):
        return "Malayalam"
    if any(c in "ٹڈڑںےۓہھ" for c in text):  # letters Urdu has and Arabic doesn't
        return "Urdu"
    if any("\u0600" <= c <= "\u06ff" for c in text):
        return "Arabic"
    return "English"


def reply(turns: list[dict], guides: dict) -> str:
    """Sahl's words back, or "" when the model isn't running."""
    lines = "\n".join(f"{' / '.join(dict.fromkeys(_names(g)))} | {g.get('about', '')}" for g in catalogue(guides).values())
    out = ai.chat({
        "model": MODEL,
        "stream": False,
        "think": False,  # plain conversation; the offer is decided by pick()
        "format": {"type": "object", "properties": {"reply": {"type": "string"}}, "required": ["reply"]},
        "keep_alive": "30m",
        "options": {"temperature": 0.3, "num_predict": 200},
        "messages": [{"role": "system", "content": TALK.format(catalogue=lines, language=_language(turns[-1]["content"]))}, *turns],
    }, timeout=30, tries=1)
    return str(out.get("reply", "")).strip()[:600] if isinstance(out, dict) else ""


def talk(history: list[dict], guides: dict) -> dict:
    """Sahl's next message. history is [{role: user|assistant, text}], oldest first, ending with the person's message.

    Returns {reply, kind, guide, name}: kind "match" offers guide, "new" means they want a form Sahl has no guide for
    (name, in their words), "unsure" is only a reply. reply is "" when the model isn't running.
    """
    turns = [{"role": "assistant" if h["role"] == "assistant" else "user", "content": h["text"].strip()[:500]} for h in history[-10:]]
    last = next((t["content"] for t in reversed(turns) if t["role"] == "user"), "")
    if not last:
        return {"reply": "", "kind": "unsure", "guide": None, "name": ""}
    with ThreadPoolExecutor(2) as pool:  # Ollama answers both at once when it can, so the wait is one call, not two
        offer, words = pool.submit(pick, last, guides), pool.submit(reply, turns, guides)
        return {"reply": words.result(), **offer.result()}


def warm():
    """Loads the model in the background so the first question is quick."""
    threading.Thread(target=ai.chat, args=({"model": MODEL, "messages": [], "keep_alive": "30m"}, 60, 1), daemon=True).start()
