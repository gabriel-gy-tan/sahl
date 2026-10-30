"""Finds each guide field's label among the OCR lines, then the input box that belongs to it."""
import re
import unicodedata

import numpy as np
from rapidfuzz import fuzz

THRESHOLD = 85
ARABIC = str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا", "ى": "ي", "ة": "ه"})


def _norm(text: str) -> str:
    """A label as OCR and forms write it: punctuation, spacing and Arabic spelling differ."""
    t = unicodedata.normalize("NFKC", text).casefold().translate(ARABIC)
    t = t.replace("'", "").replace("’", "").replace("`", "").replace("&", " and ")
    t = re.sub(r"[\u064b-\u065f\u0670\u0640]", "", t)  # Arabic diacritics and tatweel
    t = re.sub(r"[^\w\s\u0600-\u06ff]", " ", t)
    return " ".join(t.split())


def _score(text: str, aliases: list[str]) -> float:
    t = _norm(text)
    # ratio, not WRatio: partial matching lets "Passport number" score high against "Passport expiry date"
    return max(fuzz.ratio(t, _norm(a)) for a in aliases)


def _runs(on):
    """Start/end of each run of True in a 1-D mask."""
    at = np.flatnonzero(on)
    if not len(at):
        return []
    cuts = np.flatnonzero(np.diff(at) > 1)
    starts = np.r_[at[0], at[cuts + 1]]
    ends = np.r_[at[cuts], at[-1]] + 1
    return list(zip(starts.tolist(), ends.tolist()))


def _lines(gray, bg, x0, x1, y0, y1, min_len):
    """Horizontal ink segments long enough to be a field border or an underline, not text."""
    x0, x1, y0, y1 = (int(v) for v in (x0, x1, y0, y1))
    ink = lambda row: np.abs(row.astype(np.int16) - bg) > 12
    out = []
    for y in range(max(0, y0), min(gray.shape[0], y1)):
        out.extend((y, s + x0, e + x0) for s, e in _runs(ink(gray[y, x0:x1])) if e - s >= min_len)
    # a 2 px border is two rows; keep one
    kept = []
    for line in sorted(out):
        if kept and line[0] - kept[-1][0] <= 1 and abs(line[1] - kept[-1][1]) <= 2 and abs(line[2] - kept[-1][2]) <= 2:
            continue
        kept.append(line)
    return kept


def _bg(gray, label):
    x0, y0, x1, y1 = (int(v) for v in label)
    h = max(y1 - y0, 8)
    patch = gray[max(0, y0 - h):max(0, y0), max(0, x0 - h):min(gray.shape[1], x1 + h)]
    return np.median(patch) if patch.size else np.median(gray)


def _guess(label, hint):
    x0, y0, x1, y1 = (int(v) for v in label)
    h = max(y1 - y0, 8)
    return (x0, y1 + 0.5 * h, x0 + 20 * h, y1 + 3.2 * h) if hint != "right" else (x1 + h, y0 - h, x1 + 21 * h, y1 + h)


def _below(gray, label):
    """A bordered input, then an underline, directly below a label. Returns (score, box) or None."""
    x0, y0, x1, y1 = (int(v) for v in label)
    h = max(y1 - y0, 8)
    H, W = gray.shape
    bg = _bg(gray, label)
    lines = _lines(gray, bg, max(0, x0 - 3 * h), W, y1 + 0.2 * h, min(H, y1 + 10 * h), max(4 * h, 40))
    rects = []
    for i, (top, tx0, tx1) in enumerate(lines):
        for bottom, bx0, bx1 in lines[i + 1:]:
            height = bottom - top
            if height < h:  # the same border, or a hairline
                continue
            if height > 5 * h:
                break
            left, right = max(tx0, bx0), min(tx1, bx1)
            if right - left < 3.5 * h or left > x1 + 4 * h:
                continue
            score = (top - y1) / h + 0.2 * abs(left - x0) / h - 0.01 * (right - left) / h
            rects.append((score, (left, top, right, bottom)))
    if rects:
        return min(rects)
    for y, left, right in lines:  # an underline, with no box top or bottom
        if right - left < 4 * h or left > x1 + 4 * h or not 0.8 * h <= y - y1 <= 6 * h:
            continue
        top = max(y1 + 2, y - int(2.6 * h))
        score = (y - y1) / h + 0.2 * abs(left - x0) / h - 0.01 * (right - left) / h
        return score, (left, top, right, y)
    return None


def _right(gray, label):
    """A bordered input, then an underline, to the right of a label. Returns (score, box) or None."""
    x0, y0, x1, y1 = (int(v) for v in label)
    h = max(y1 - y0, 8)
    H, W = gray.shape
    bg = _bg(gray, label)
    lines = _lines(gray, bg, x1 + h // 2, min(W, x1 + 40 * h), max(0, y0 - 2 * h), min(H, y1 + 3 * h),
                   max(4 * h, 40))
    rects = []
    for i, (top, tx0, tx1) in enumerate(lines):
        for bottom, bx0, bx1 in lines[i + 1:]:
            height = bottom - top
            if height < h:
                continue
            if height > 5 * h:
                break
            left, right = max(tx0, bx0), min(tx1, bx1)
            if right - left < 4 * h or left < x1 + h // 2:
                continue
            score = abs(left - (x1 + h)) / h + 0.3 * abs((top + bottom) / 2 - (y0 + y1) / 2) / h
            rects.append((score, (left, top, right, bottom)))
    if rects:
        return min(rects)
    for y, left, right in lines:
        if left < x1 + h // 2 or right - left < 4 * h:
            continue
        score = abs(left - (x1 + h)) / h + abs(y - (y0 + y1) / 2) / h
        return score, (left, max(y0, y - int(2.6 * h)), right, y)
    return None


def _input_box(gray, label, hint):
    """The input rectangle next to a label, found from its border lines in the screenshot.

    Border first, then an underline, then a box sized from the label. "auto" lets generic forms
    put the box below or beside the label; existing guides keep their explicit side.
    """
    if gray is None:
        return _guess(label, hint)
    found = []
    if hint in ("below", "auto"):
        found.append(("below", _below(gray, label)))
    if hint in ("right", "auto"):
        found.append(("right", _right(gray, label)))
    found = [(side, box) for side, box in found if box]
    if not found:
        return _guess(label, hint)
    if len(found) == 1:
        return found[0][1][1]
    return min(found, key=lambda item: item[1][0])[1][1]


def match(lines, guide, gray=None, scale=1.0, origin=(0, 0)):
    """Guide fields visible on screen, in guide order, with boxes in screen points."""
    pairs = sorted(
        ((_score(text, f["aliases"]), fi, li)
         for fi, f in enumerate(guide["fields"]) for li, (text, _) in enumerate(lines)),
        reverse=True)
    used_f, used_l, hits = set(), set(), {}
    for score, fi, li in pairs:
        if score < THRESHOLD:
            break
        if fi in used_f or li in used_l:
            continue
        used_f.add(fi), used_l.add(li)
        hits[fi] = li
    to_pt = lambda b: tuple(round(v / scale + origin[i % 2], 1) for i, v in enumerate(b))
    out = []
    for fi, f in enumerate(guide["fields"]):
        if fi not in hits:
            continue
        label = lines[hits[fi]][1]
        out.append({"id": f["id"], "seen": lines[hits[fi]][0], "label_box": to_pt(label),
                    "input_box": to_pt(_input_box(gray, label, f["box"]))})
    return out
