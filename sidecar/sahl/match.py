"""Finds each guide field's label among the OCR lines, then the input box that belongs to it."""
import calendar
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
        if any(line[0] - k[0] <= 1 and abs(line[1] - k[1]) <= 6 and abs(line[2] - k[2]) <= 6 for k in kept[-8:]):
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


def _rects(gray, bg, region, min_len, h):
    """Bordered boxes in a region: pairs of border lines with the same left and right ends (a rounded corner shifts them a few px)."""
    lines = _lines(gray, bg, region[0], region[1], region[2], region[3], min_len)
    found = []
    for i, (top, tx0, tx1) in enumerate(lines):
        for bottom, bx0, bx1 in lines[i + 1:]:
            if 0.8 * h <= bottom - top <= 5 * h and abs(tx0 - bx0) <= 6 and abs(tx1 - bx1) <= 6:
                if not any(abs(r[0] - tx0) <= 6 and abs(r[1] - top) <= 6 for r in found):  # the same box, from its other border rows
                    found.append((tx0, top, tx1, bottom))
    return found


def _row(gray, label, count=3):
    """`count` bordered boxes in reading order beside or below a label: a date's day, month and year, which a narrow
    form may wrap onto a second line."""
    x0, y0, x1, y1 = (int(v) for v in label)
    h = max(y1 - y0, 8)
    H, W = gray.shape
    bg = _bg(gray, label)
    best = None
    for side, region in (("below", (max(0, x0 - h), W, y1 + 0.2 * h, y1 + 10 * h)),
                         ("right", (x1 + h // 2, min(W, x1 + 60 * h), max(0, y0 - 2 * h), y1 + 6 * h))):
        rects = sorted((r for r in _rects(gray, bg, (region[0], region[1], max(0, int(region[2])), min(H, int(region[3]))), max(1.5 * h, 24), h)
                        if r[0] > region[0] + 6),  # a box cut off by the region's edge is part of a wider one
                       key=lambda r: (r[1], r[0]))
        for first in rects:
            line = sorted(r for r in rects if abs(r[1] - first[1]) <= h)  # its row
            wrapped = sorted(r for r in rects if first[1] + h < r[1] <= first[1] + 4 * h and r[0] >= first[0] - 6)
            row = (line + wrapped)[:count] if line[0] == first or len(line) < count else line[:count]
            if len(row) < count or row[0] != first and first[0] > row[0][0]:
                continue
            score = (first[1] - y1) / h + 0.2 * abs(first[0] - x0) / h if side == "below" else abs(first[0] - (x1 + h)) / h + 0.3 * abs(first[1] - y0) / h
            if best is None or score < best[0]:
                best = (score, row)
    return best[1] if best else None


def _inside(rects, lines):
    """The text shown in each box. OCR joins neighbouring boxes into one line ("Month Day v"), so when a line crosses
    several boxes its words go to them in order (one-letter junk like a chevron dropped), else by character position."""
    texts = [[] for _ in rects]
    for text, (a, b, c, d) in lines:
        crossed = sorted((i for i, r in enumerate(rects) if r[1] <= (b + d) / 2 <= r[3] and r[0] <= c and a <= r[2]),
                         key=lambda i: rects[i][0])
        words = text.split()
        if len(crossed) == 1:
            texts[crossed[0]] += words
        elif crossed:
            kept = [w for w in words if len(w) > 1] if len([w for w in words if len(w) > 1]) == len(crossed) else words
            if len(kept) == len(crossed):
                for i, w in zip(crossed, kept):
                    texts[i].append(w)
            else:
                at = 0
                for w in words:
                    x = a + (c - a) * (at + len(w) / 2) / len(text)
                    at += len(w) + 1
                    texts[next((i for i in crossed if rects[i][0] <= x <= rects[i][2]), crossed[0])].append(w)
    return [" ".join(t) for t in texts]


def date_parts(rects, lines, order="dmy"):
    """Which box is the day, month and year: from the placeholder each shows ("Month", "DD", "YYYY"), else the guide's order."""
    months = {m.casefold() for m in calendar.month_name[1:]} | {m.casefold() for m in calendar.month_abbr[1:]}
    kinds = []
    for shown in _inside(rects, lines):
        words = set(_norm(shown).split())
        kinds.append("y" if words & {"year", "yyyy", "yy"} or any(re.fullmatch(r"\d{4}", w) for w in words)
                     else "m" if words & {"month", "mm"} or words & months
                     else "d" if words & {"day", "dd"} else None)
    if sorted(kinds, key=str) != ["d", "m", "y"]:
        kinds = list(order)
    return [{"kind": k, "box": r} for k, r in zip(kinds, rects)]


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


PLACEHOLDERS = re.compile(r"(?:\s+(?:month|day|year|mm|dd|yyyy|yy)\b[\s\-–—vV∨⌄ˇ▾▼>]*)+$", re.I)


def _labels(lines, gray):
    """The lines as labels: OCR reads a label with the date dropdowns beside it ("Date of birth Month v Day v Year v")
    as one line, so cut it back to the label and its box to where the first dropdown's border starts."""
    out = []
    for text, box in lines:
        m = PLACEHOLDERS.search(text)
        if gray is None or not m or not text[:m.start()].strip():
            out.append((text, box))
            continue
        x0, y0, x1, y1 = box
        h = max(int(y1 - y0), 8)
        rects = _rects(gray, _bg(gray, box), (int(x0), int(x1) + h, max(0, int(y0 - 2 * h)), min(gray.shape[0], int(y1 + 2 * h))), max(1.5 * h, 24), h)
        lefts = [r[0] for r in rects if r[0] > x0 + 2 * h]
        cut = min(lefts) - h // 2 - 8 if lefts else x0 + (x1 - x0) * m.start() / len(text) * 0.8
        out.append((text[:m.start()].strip(), (x0, y0, cut, y1)))
    return out


def match(lines, guide, gray=None, scale=1.0, origin=(0, 0)):
    """Guide fields visible on screen, in guide order, with boxes in screen points."""
    labels = _labels(lines, gray)
    pairs = sorted(
        ((_score(text, f["aliases"]), fi, li)
         for fi, f in enumerate(guide["fields"]) for li, (text, _) in enumerate(labels)),
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
        label = labels[hits[fi]][1]
        hit = {"id": f["id"], "seen": labels[hits[fi]][0], "label_box": to_pt(label),
               "input_box": to_pt(_input_box(gray, label, f["box"]))}
        row = _row(gray, label) if f["input"] == "date-parts" and gray is not None else None
        if row:
            parts = date_parts(row, lines, f.get("parts", "dmy"))
            hit["parts"] = [{"kind": p["kind"], "box": to_pt(p["box"])} for p in parts]
            hit["input_box"] = to_pt((min(r[0] for r in row), min(r[1] for r in row), max(r[2] for r in row), max(r[3] for r in row)))
        out.append(hit)
    return out


def unknown_labels(lines, guide, gray, known: set[str]) -> list[str]:
    """Printed labels no alias of the guide matches, to learn new aliases from.

    Only short text with no digits that has an input border next to it (a value sits inside a box, not beside one),
    and never text that is one of the person's own values (`known`, already normalised)."""
    if gray is None:
        return []
    aliases = [a for f in guide["fields"] for a in f["aliases"]]
    out = []
    for text, box in lines:
        t = _norm(text)
        if not 3 <= len(t) <= 40 or len(t.split()) > 5 or re.search(r"\d", t) or _score(text, aliases) >= THRESHOLD:
            continue
        if any(t in k or k in t for k in known) or not (_below(gray, box) or _right(gray, box)):
            continue
        out.append(text.strip(" :*"))
    return out
