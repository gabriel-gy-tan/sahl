"""Finds each guide field's label among the OCR lines, then the input box that belongs to it."""
import calendar
import re
import unicodedata

import numpy as np
from rapidfuzz import fuzz

THRESHOLD = 85
INK = 8  # how far a pixel is from the page to count as a line or shading (#f3f3f3 boxes on white are 12)
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
    ink = lambda row: np.abs(row.astype(np.int16) - bg) > INK
    out = []
    for y in range(max(0, y0), min(gray.shape[0], y1)):
        out.extend((y, s + x0, e + x0) for s, e in _runs(ink(gray[y, x0:x1])) if e - s >= min_len)
    # stack runs that continue on the next row: a 2 px border is two rows, a shaded box with no border is a whole band
    bands = []  # [first, last]
    for line in sorted(out):
        b = next((b for b in reversed(bands[-8:]) if line[0] - b[1][0] <= 1 and abs(line[1] - b[1][1]) <= 6
                  and abs(line[2] - b[1][2]) <= 6), None)
        if b:
            b[1] = line
        else:
            bands.append([line, line])
    # a band cut by the window (a tall shaded box running past it) has no edge there: keep only edges where it stops
    goes_on = lambda y, s, e: 0 <= y < gray.shape[0] and np.mean(ink(gray[y, s:e])) > 0.9
    kept = []
    for first, last in bands:  # a border keeps one line; a band gives its top and bottom, like a bordered box
        if not goes_on(first[0] - 1, first[1], first[2]):
            kept.append(first)
        if last[0] - first[0] >= 4 and not goes_on(last[0] + 1, last[1], last[2]):
            kept.append(last)
    return sorted(kept)


def _bg(gray, label):
    """The colour the label sits on: the commonest shade inside its own box, between the letters. (A strip beside it
    can be a box hugging the label, which made the real page look like ink everywhere.)"""
    x0, y0, x1, y1 = (int(v) for v in label)
    patch = gray[max(0, y0):max(0, y1), max(0, x0):min(gray.shape[1], x1)]
    if patch.size < 16:
        h = max(y1 - y0, 8)
        patch = gray[max(0, y0 - h):max(0, y0), max(0, x0 - h):min(gray.shape[1], x1 + h)]
    return float(np.bincount(patch.ravel().astype(np.uint8), minlength=256).argmax()) if patch.size else float(np.median(gray))


def _guess(label, hint):
    x0, y0, x1, y1 = (int(v) for v in label)
    h = max(y1 - y0, 8)
    return (x0, y1 + 0.5 * h, x0 + 20 * h, y1 + 3.2 * h) if hint != "right" else (x1 + h, y0 - h, x1 + 21 * h, y1 + h)


def _tight(rects):
    """Candidates (score, box) without any box that holds another candidate: the border above or below a neighbouring
    input pairs with this one's to make a taller phantom, which can score better than the real box."""
    area = lambda b: (b[2] - b[0]) * (b[3] - b[1])
    inside = lambda a, b: area(a) < area(b) and a[0] >= b[0] - 6 and a[1] >= b[1] - 6 and a[2] <= b[2] + 6 and a[3] <= b[3] + 6
    return [r for r in rects if not any(inside(o[1], r[1]) for o in rects)]


def _real(gray, bg, rect, h):
    """Whether a rectangle made of two lines is one input, not the gap between two inputs: it is shaded inside,
    or it has a left and a right side (a few px off the lines' ends where the corners are rounded)."""
    left, top, right, bottom = (int(v) for v in rect)
    if _cover(gray, bg, (left + right) // 2, top, bottom) >= 0.85:  # the gap between two stacked boxes is not shaded
        return True
    lim = min(14, h)
    q = min(14, (bottom - top) // 4)
    rows = gray[top + q:bottom - q + 1]
    if not len(rows):
        return False

    def closed(a, b):  # on (nearly) every row there is line near this end: a straight side, or the curve of a pill
        band = np.abs(rows[:, max(0, a):max(0, b)].astype(np.int16) - bg) > INK
        return band.size and float(band.any(axis=1).mean()) >= 0.85
    return closed(left - lim, left + lim) and closed(right - lim, right + lim)


def _claimed(gray, bg, rect, gap, h):
    """Whether other text sits under the box, closer to it than the label above it is: then the box is that
    text's (a form with labels under their boxes), not this label's."""
    left, top, right, bottom = (int(v) for v in rect)
    y0, y1 = bottom + 3, bottom + max(3, int(gap))
    x1 = min(right, left + 12 * h, gray.shape[1])
    if y1 <= y0 or y0 >= gray.shape[0]:
        return False
    ink = np.abs(gray[y0:y1, left:x1].astype(np.int16) - bg) > 40
    for i, row in enumerate(ink):  # drop the long runs of a border; what is left is text
        for a, b in _runs(row):
            if b - a >= 3 * h:
                ink[i, a:b] = False
    return int(ink.sum()) >= h


def _aligned(left, right, x0, x1, h):
    """Whether a box under (or over) a label lines up with it, as a label and its own box do: the label starts where
    the box starts (or a little inside it), or ends where the box ends in right-to-left forms. A box further along is
    another field's, with its own label beside it."""
    return (left - 2 * h <= x0 <= left + 2 * h or right - 2 * h <= x1 <= right + 2 * h) and right > x0 and left < x1 + 2 * h


def _joined(gray, bg, top, left, right, h):
    """The ends of a box together with any box touching it along its top edge (the two parts of a split phone box,
    however short the other part is): alignment with the label is judged on the whole, as the eye reads it."""
    lim = min(14, h) + 8  # rounded corners leave a few px of page between two touching boxes' top lines
    rows = gray[max(0, top - 1):top + 3].astype(np.int16)
    if not len(rows):
        return left, right
    ink = (np.abs(rows - bg) > INK).any(axis=0)

    def reach(x, step):  # follow the top edge while gaps stay shorter than a rounded corner
        last, gap = x, 0
        while 0 <= x + step < len(ink) and gap <= lim:
            x += step
            gap = 0 if ink[x] else gap + 1
            if ink[x]:
                last = x
        return last

    far_left, far_right = reach(left, -1), reach(right - 1, 1) + 1
    return (far_left if left - far_left >= 2 * h else left), (far_right if far_right - right >= 2 * h else right)


def _below(gray, label, underline=True):
    """A bordered or shaded input, then an underline, directly below a label. Returns (score, box) or None."""
    x0, y0, x1, y1 = (int(v) for v in label)
    h = max(y1 - y0, 8)
    H, W = gray.shape
    bg = _bg(gray, label)
    lines = _lines(gray, bg, max(0, x0 - 3 * h), W, y1 + 0.2 * h, min(H, y1 + 16 * h), max(4 * h, 40))
    rects, edges = [], set()  # edges: lines that are a real box's top or bottom, so never an underline
    for i, (top, tx0, tx1) in enumerate(lines):
        if top - y1 > 6 * h:  # too far below to be this label's box
            break
        for bottom, bx0, bx1 in lines[i + 1:]:
            height = bottom - top
            if height < h:  # the same border, or a hairline
                continue
            if height > 15 * h:  # taller than a text area
                break
            left, right = max(tx0, bx0), min(tx1, bx1)
            if right - left < 3.5 * h or not _aligned(*_joined(gray, bg, top, left, right, h), x0, x1, h):
                continue
            if not _real(gray, bg, (left, top, right, bottom), h):
                continue
            edges.update((top, bottom))
            if _claimed(gray, bg, (left, top, right, bottom), top - y1, h):
                continue
            score = (top - y1) / h + 0.2 * abs(left - x0) / h - 0.01 * (right - left) / h
            rects.append((score, (left, top, right, bottom)))
    if rects:
        return min(_tight(rects))
    for y, left, right in lines if underline else ():  # an underline, with no box top or bottom
        if right - left < 4 * h or not _aligned(left, right, x0, x1, h) or not 0.8 * h <= y - y1 <= 6 * h or y in edges:
            continue
        top = max(y1 + 2, y - int(2.6 * h))
        if _claimed(gray, bg, (left, top, right, y), top - y1, h):  # gap from the label to the box's top, not the line
            continue
        score = (top - y1) / h + 0.2 * abs(left - x0) / h - 0.01 * (right - left) / h
        return score, (left, top, right, y)
    return None


def _right(gray, label):
    """A bordered or shaded input, then an underline, to the right of a label and on its row. Returns (score, box) or None."""
    x0, y0, x1, y1 = (int(v) for v in label)
    h = max(y1 - y0, 8)
    H, W = gray.shape
    bg = _bg(gray, label)
    far = x1 + 40 * h  # the box must start within this; it may run on past it to the screen's edge
    start = x1 + h // 2
    lines = _lines(gray, bg, start, W, max(0, y0 - 10 * h), min(H, y1 + 10 * h), max(4 * h, 40))
    # a line that runs on to the left of where the search starts belongs to a box above or below the label, not beside it
    cut = lambda y, left: left <= start + 1 and start >= 1 and abs(float(gray[y, start - 1]) - bg) > INK
    q = (y1 - y0) // 4  # beside means on the label's own line: the box covers part of the text's height
    rects = []
    for i, (top, tx0, tx1) in enumerate(lines):
        if top > y1 + h // 2:  # the box must reach up to the label's row
            break
        for bottom, bx0, bx1 in lines[i + 1:]:
            height = bottom - top
            if height < h:
                continue
            if height > 15 * h:
                break
            left, right = max(tx0, bx0), min(tx1, bx1)
            if right - left < 4 * h or left < start or left > far or bottom <= y0 + q or top >= y1 - q:
                continue
            if cut(top, left) or cut(bottom, left) or not _real(gray, bg, (left, top, right, bottom), h):
                continue
            score = abs(left - (x1 + h)) / h + 0.3 * abs((top + bottom) / 2 - (y0 + y1) / 2) / h
            rects.append((score, (left, top, right, bottom)))
    if rects:
        return min(_tight(rects))
    for y, left, right in lines:
        if left < start or left > far or right - left < 4 * h or not y1 - h // 2 <= y <= y1 + 3 * h or cut(y, left):
            continue
        score = abs(left - (x1 + h)) / h + abs(y - (y0 + y1) / 2) / h
        return score, (left, max(y0, y - int(2.6 * h)), right, y)
    return None


def _left(gray, label):
    """A box to the left of the label (right-to-left forms): the right-hand search on the mirrored screen."""
    W = gray.shape[1]
    x0, y0, x1, y1 = label
    found = _right(gray[:, ::-1], (W - x1, y0, W - x0, y1))
    if not found:
        return None
    score, (l, t, r, b) = found
    return score, (W - r, t, W - l, b)


def _above(gray, label):
    """A box above the label: the below search on the screen turned upside down."""
    H = gray.shape[0]
    x0, y0, x1, y1 = label
    found = _below(gray[::-1], (x0, H - y1, x1, H - y0), underline=False)  # an underline above a label is the field before's
    if not found:
        return None
    score, (l, t, r, b) = found
    return score, (l, H - b, r, H - t)


def _cover(gray, bg, x, top, bottom):
    """How much of a column between top and bottom (corners aside) differs from the page: 1 for a side or a fill."""
    q = min(14, (bottom - top) // 4)  # past rounded corners, but most of the height: a gap between boxes shows
    if not 0 <= x < gray.shape[1] or bottom - top < 4:
        return 0.0
    return float(np.mean(np.abs(gray[top + q:bottom - q + 1, x].astype(np.int16) - bg) > INK))


def _widen(gray, bg, box, h):
    """Rounded corners shorten a box's straight top and bottom: move each end out to the real side. The side is
    furthest out on the box's middle row, for a square corner and a pill's round end alike."""
    x0, y0, x1, y1 = (int(v) for v in box)
    lim = min(14, h)
    mid = (y0 + y1) // 2
    if not 0 <= mid < gray.shape[0]:
        return box
    top = np.abs(gray[max(0, y0 - 1):y0 + 2, x0:x0 + lim].astype(np.int16) - bg) > INK
    if not top.any():  # an underline: no top edge, no sides to find (its middle row may cross the label's text)
        return box
    ink = (np.abs(gray[max(0, mid - 1):mid + 2].astype(np.int16) - bg) > INK).any(axis=0)

    def side(x, step):
        if 0 <= x < len(ink) and ink[x]:  # a fill or the side itself: follow it out
            while 0 <= x + step < len(ink) and abs(x + step - start) <= lim and ink[x + step]:
                x += step
            return x
        for k in range(1, lim + 1):  # a border a few px further out
            if 0 <= x + k * step < len(ink) and ink[x + k * step]:
                return x + k * step
        return x

    start = x0
    left = side(x0, -1)
    start = x1 - 1
    right = side(x1 - 1, 1) + 1
    return (left, y0, right, y1)


def _part(gray, bg, box, h):
    """A phone box split in two, a country code you pick (00971) beside the number you type: the part to type in.
    The other part must touch this one, share its top and bottom, and look different (shaded, not blank)."""
    x0, y0, x1, y1 = (int(v) for v in box)
    rows = [y for y in range(y0, y0 + 3) if 0 <= y < gray.shape[0]]
    inside = lambda a, b: np.median(gray[y0 + 3:y1 - 2, a:b]) if b - a > 4 and y1 - y0 > 6 else bg
    mid = (y0 + y1) // 2
    if 0 <= mid < gray.shape[0]:  # one outline holding both parts: a shaded part at one end of it
        for a, b in _runs(np.abs(gray[mid, x0:x1].astype(np.int16) - bg) > INK):
            a, b = a + x0, b + x0
            at_end = a - x0 <= 4 or x1 - b <= 4
            if at_end and 4 * h <= b - a <= 0.7 * (x1 - x0) and _cover(gray, bg, (a + b) // 2, y0, y1) >= 0.85:
                rest = (b, y0, x1, y1) if a - x0 <= 4 else (x0, y0, a, y1)
                if abs(inside(a + 3, b - 3) - bg) - abs(inside(rest[0] + 3, rest[2] - 3) - bg) >= 8:
                    return rest
    here = abs(inside(x0 + 3, x1 - 3) - bg)
    H, W = gray.shape
    lim = min(14, h) + 8  # rounded corners start a box's top and bottom lines a few px in from where it touches
    lines = _lines(gray, bg, max(0, x0 - 60 * h), min(W, x1 + 60 * h), max(0, y0 - 3), min(H, y1 + 4), max(4 * h, 40))
    tops = [l for l in lines if abs(l[0] - y0) <= 4]
    bottoms = [l for l in lines if abs(l[0] - (y1 - 1)) <= 4 or abs(l[0] - y1) <= 4]
    for t in tops:  # a neighbouring box with the same top and bottom that touches this one, on either side
        for b in bottoms:
            left, right = max(t[1], b[1]), min(t[2], b[2])
            touches = x1 - 2 <= left <= x1 + lim or x0 - lim <= right <= x0 + 2
            if not touches or right - left < 4 * h or not _real(gray, bg, (left, y0, right, y1), h):
                continue
            if here - abs(inside(left + 6, right - 3) - bg) >= 8:  # this part is shaded and the other is blank
                return (left, y0, right, y1)
    return box
    return best or box


def _rects(gray, bg, region, min_len, h):
    """Bordered boxes in a region: pairs of border lines with the same left and right ends (a rounded corner shifts them a few px)."""
    lines = _lines(gray, bg, region[0], region[1], region[2], region[3], min_len)
    pairs = []
    for i, (top, tx0, tx1) in enumerate(lines):
        for bottom, bx0, bx1 in lines[i + 1:]:
            if 0.8 * h <= bottom - top <= 5 * h and abs(tx0 - bx0) <= 6 and abs(tx1 - bx1) <= 6:
                pairs.append((tx0, top, tx1, bottom))
    found = []
    for r in sorted(pairs, key=lambda r: (r[2] - r[0]) * (r[3] - r[1])):  # tightest first: a neighbour's border can pair with this box's to make a taller one
        if not any(abs(f[0] - r[0]) <= 6 and abs(f[1] - r[1]) <= 6 for f in found):  # the same box, from its other border rows
            found.append(r)
    area = lambda b: (b[2] - b[0]) * (b[3] - b[1])
    inside = lambda a, b: area(a) < area(b) and a[0] >= b[0] - 6 and a[1] >= b[1] - 6 and a[2] <= b[2] + 6 and a[3] <= b[3] + 6
    return [r for r in found if not any(inside(f, r) for f in found)]  # a box that holds another is a phantom made of its neighbours' borders


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
        spans = [m.span() for m in re.finditer(r"\w+", text)]  # OCR also puts "-", "|" or "v" where a dropdown's arrow is
        words = [text[i:j] for i, j in spans]
        if len(crossed) == 1:
            texts[crossed[0]] += words
        elif crossed:
            kept = [w for w in words if len(w) > 1] if len([w for w in words if len(w) > 1]) == len(crossed) else words
            if len(kept) == len(crossed):
                for i, w in zip(crossed, kept):
                    texts[i].append(w)
            else:
                for w, (i, j) in zip(words, spans):
                    x = a + (c - a) * (i + j) / 2 / len(text)
                    texts[next((k for k in crossed if rects[k][0] <= x <= rects[k][2]), crossed[0])].append(w)
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
    if kinds.count(None) == 1 and len(set(kinds) - {None}) == 2:  # a filled-in date: "21" shows no kind, but it is what is left
        kinds[kinds.index(None)] = next(k for k in "dmy" if k not in kinds)
    if sorted(kinds, key=str) != ["d", "m", "y"]:
        kinds = list(order)
    return [{"kind": k, "box": r} for k, r in zip(kinds, rects)]


def _mark(gray, text, side=None):
    """The radio circle or checkbox square beside an option's text: a compact mark about the text's height just
    before it, or just after it in right-to-left forms. OCR often reads the mark as the line's first character
    ("O India"), so the start of the text's own box is looked at first. Returns (box, checked) or None."""
    if gray is None:
        return None
    x0, y0, x1, y1 = (int(v) for v in text)
    h = max(y1 - y0, 8)
    H, W = gray.shape
    bg = _bg(gray, text)
    top, bottom = max(0, int(y0 - 0.4 * h)), min(H, int(y1 + 0.4 * h))  # its own row only, not the next option's
    found = []
    for step in ((-1, 1) if side is None else (side,)):
        a, b = (max(0, x0 - 4 * h), min(W, x0 + 2 * h)) if step == -1 else (max(0, x1 - 2 * h), min(W, x1 + 4 * h))
        if b - a < 4:
            continue
        ink = np.abs(gray[top:bottom, a:b].astype(np.int16) - bg) > 30
        runs = _runs(ink.any(axis=0))

        def shaped(i):
            c0, c1 = runs[i]
            rows = _rows_at(ink[:, c0:c1], (y0 + y1) / 2 - top)
            if rows is None:
                return None
            w, ht = c1 - c0, rows[1] - rows[0]
            if not (0.3 * h <= w <= 2.2 * h and 0.3 * h <= ht <= 2.2 * h and 0.6 <= w / ht <= 1.6):
                return None
            return (a + c0, rows[0] + top, a + c1, rows[1] + top)

        edge = x0 - a if step == -1 else x1 - a  # the text box's own edge, in window columns
        # in or across the text box's edge: the first thing in it, from the mark's side
        inside = [i for i, (c0, c1) in enumerate(runs) if (c1 > edge - 2 if step == -1 else c0 < edge + 2)]
        inside = inside[:1] if step == -1 else inside[-1:]
        for i in inside:  # a mark OCR took into the line: a clear space between it and the text
            text_at = i - step  # the text is on the far side from the mark
            if 0 <= text_at < len(runs):
                space = runs[text_at][0] - runs[i][1] if step == -1 else runs[i][0] - runs[text_at][1]
            else:
                space = 99
            box = shaped(i)
            if box and space >= 0.22 * h:
                found.append((0, box, _ticked(gray, bg, box)))
        outside = [i for i, (c0, c1) in enumerate(runs) if (c1 <= edge - 2 if step == -1 else c0 >= edge + 2)]
        for i in (reversed(outside) if step == -1 else outside):  # else the nearest mark outside the text
            c0, c1 = runs[i]
            gap = (edge - c1) if step == -1 else (c0 - edge)
            if gap > 1.5 * h:
                break
            box = shaped(i)
            if box:
                found.append((gap, box, _ticked(gray, bg, box)))
                break
    if not found:
        return None
    _, box, checked = min(found, key=lambda f: f[0])
    return box, checked


def _rows_at(ink, centre):
    """The rows of the inked block nearest a row (the text's middle): the next option's mark in a tight list
    sits in the same columns, a little lower, with clear rows between."""
    rows = np.flatnonzero(ink.any(axis=1))
    if not len(rows):
        return None
    cuts = np.flatnonzero(np.diff(rows) > 1)
    blocks = [(rows[a], rows[b] + 1) for a, b in zip(np.r_[0, cuts + 1], np.r_[cuts, len(rows) - 1])]
    return min(blocks, key=lambda r: 0 if r[0] <= centre < r[1] else min(abs(r[0] - centre), abs(r[1] - centre)))


def _ticked(gray, bg, box):
    """Whether a mark is chosen: there is a dot or a tick inside its ring or square, past the line itself. The line's
    thickness is taken on its thinnest side (a tick can touch the line on one side), and a chosen mark has clearly
    more ink than a bare line of that thickness."""
    x0, y0, x1, y1 = (int(v) for v in box)
    ink = np.abs(gray[y0:y1, x0:x1].astype(np.int16) - bg) > 30
    if ink.shape[0] < 3 or ink.shape[1] < 3:
        return False
    hh, w = ink.shape
    run = lambda line: next((i for i, v in enumerate(line) if not v), len(line))
    t = max(1, min(run(ink[hh // 2]), run(ink[hh // 2][::-1]), run(ink[:, w // 2]), run(ink[:, w // 2][::-1])))
    if 2 * t >= min(w, hh) - 1:  # inked right across: a dot filling a small ring
        return True
    # the middle of what is inside the line: a dot or a tick crosses it; a ring's curve near the corners does not
    a, b = t + 1, max(t + 2, int(0.2 * (min(w, hh) - 2 * t - 2)) + t + 1)
    core = ink[hh // 2 - (min(w, hh) // 2 - b):hh // 2 + (min(w, hh) // 2 - b) + 1,
               w // 2 - (min(w, hh) // 2 - b):w // 2 + (min(w, hh) // 2 - b) + 1]
    if not core.size:
        core = ink[hh // 2:hh // 2 + 1, w // 2:w // 2 + 1]
    return float(core.mean()) > 0.15


def _words_on_screen(gray, text, box):
    """Where each of an OCR line's words sits: the line's widest gaps, one fewer than its words, are the spaces
    between them. None when the picture doesn't split into that many pieces."""
    words = text.split()
    x0, y0, x1, y1 = (int(v) for v in box)
    if gray is None or len(words) < 2:
        return None
    patch = gray[max(0, y0):y1, max(0, x0):x1]
    if not patch.size:
        return None
    bg = float(np.bincount(patch.ravel().astype(np.uint8), minlength=256).argmax())
    runs = _runs((np.abs(patch.astype(np.int16) - bg) > 30).any(axis=0))
    if len(runs) < len(words):
        return None
    gaps = sorted(range(len(runs) - 1), key=lambda i: runs[i + 1][0] - runs[i][1], reverse=True)[:len(words) - 1]
    cuts = sorted(gaps)
    starts = [0] + [i + 1 for i in cuts]
    ends = cuts + [len(runs) - 1]
    return [(x0 + runs[a][0], y0, x0 + runs[b][1], y1) for a, b in zip(starts, ends)]


def _option_box(text, box, option, gray=None):
    """Where one option's words sit inside an OCR line that holds several ("O Male O Female"): measured from the
    picture when it splits into the line's words, else estimated by character offset."""
    t, o = _norm(text), _norm(option)
    m = re.search(r"(?<!\w)" + re.escape(o) + r"(?!\w)", t) if o else None  # a whole word: "male" is not in "female"
    if not m:
        return None
    words = text.split()
    placed = _words_on_screen(gray, text, box)
    if placed:
        want = o.split()
        norm = [_norm(w) for w in words]
        for i in range(len(norm) - len(want) + 1):
            if norm[i:i + len(want)] == want:
                return (placed[i][0], box[1], placed[i + len(want) - 1][2], box[3])
    at = m.start()
    x0, y0, x1, y1 = box
    per = (x1 - x0) / len(t)
    return (x0 + at * per, y0, x0 + (at + len(o)) * per, y1)


def choices(lines, label, options, gray):
    """A radio group's options near its question label (on its row either side, or in the lines below it), each
    with the mark beside it: [{text, box, mark, checked}] in screen pixels, or [] when they aren't on screen.
    Every option's mark is on the same side of its text, so the side is chosen for the whole group."""
    x0, y0, x1, y1 = label
    h = max(y1 - y0, 8)
    found = []  # (option, text box, the OCR line it was in)
    for opt in options:  # each option: its aliases as printed (English, Arabic)
        best = None
        for li, (text, box) in enumerate(lines):
            if tuple(box) == tuple(label):
                continue
            bx0, by0, bx1, by1 = box
            same_row = abs((by0 + by1) / 2 - (y0 + y1) / 2) <= h
            below = 0 < by0 - y1 <= 16 * h and bx1 >= x0 - 30 * h and bx0 <= x1 + 30 * h  # a long list runs well down
            if not (same_row or below):
                continue
            for alias in opt:
                ob = _option_box(text, box, alias, gray)
                if ob:
                    d = abs(by0 - y0) + abs(bx0 - x0) / 10
                    if best is None or d < best[0]:
                        best = (d, ob, li)
        if best:
            found.append((opt, best[1], best[2]))
    if gray is None:
        return [{"text": o[0], "box": b, "mark": None, "checked": False} for o, b, _ in found]
    marks = {}
    sides = {}
    for side in (-1, 1):
        sides[side] = {i: _mark(gray, b, side) for i, (_, b, _) in enumerate(found) if i not in marks}
    side = max((-1, 1), key=lambda s: sum(1 for m in sides[s].values() if m))  # ties go to the left
    marks.update({i: m for i, m in sides[side].items() if m})
    return [{"text": o[0], "box": b, "mark": marks[i][0] if i in marks else None,
             "checked": bool(i in marks and marks[i][1])} for i, (o, b, _) in enumerate(found)]


def _input_box(gray, label, hint):
    """The input rectangle next to a label, found from its border lines or shading in the screenshot.

    "auto" (every guide uses it) looks below, to the right, to the left (right-to-left forms) and above the label and
    keeps the closest fit; the left and above are rarer, so they need a clearly better fit to win. Then the box is
    widened past rounded corners, and a split phone box gives the part you type in.
    """
    if gray is None:
        return _guess(label, hint)
    sides = {"below": (_below, 0.0), "right": (_right, 0.0), "left": (_left, 1.0), "above": (_above, 1.5)}
    use = sides if hint in ("auto", None) else {hint: sides[hint]} if hint in sides else sides
    found = [(r[0] + penalty, r[1]) for fn, penalty in use.values() if (r := fn(gray, label))]
    if not found:
        return _guess(label, hint)
    box = min(found)[1]
    x0, y0, x1, y1 = (int(v) for v in label)
    h = max(y1 - y0, 8)
    bg = _bg(gray, label)
    box = _widen(gray, bg, box, h)
    part = _part(gray, bg, box, h)
    return box if part is box else _widen(gray, bg, part, h)


PLACEHOLDERS = re.compile(r"(?:[\W_]+(?:month|day|year|mm|dd|yyyy|yy)\b)+[\W_vV]*$", re.I)  # OCR puts "-", "|" or "v" for a dropdown's arrow


VALUES = re.compile(r"(?:[\W_]+(?:%s|\d{1,4}))+[\W_]*$" % "|".join(
    [m.casefold() for m in calendar.month_name[1:]] + [m.casefold() for m in calendar.month_abbr[1:]]), re.I)


def _labels(lines, gray, dates=()):
    """The lines as labels: OCR reads a label with the date dropdowns beside it ("Date of birth Month v Day v Year v")
    as one line, so cut it back to the label and its box to where the first dropdown's border starts."""
    out, tails = [], []
    for text, box in lines:
        m = PLACEHOLDERS.search(text)
        v = VALUES.search(text)  # a filled-in date ("Date of birth Mar 21 2009"), only when what is left is a date label
        if not m and v and dates and _score(text[:v.start()], dates) >= THRESHOLD:
            m = v
        if gray is None or not m or not text[:m.start()].strip():
            out.append((text, box))
            tails.append((text, box))
            continue
        x0, y0, x1, y1 = box
        h = max(int(y1 - y0), 8)
        rects = _rects(gray, _bg(gray, box), (int(x0), int(x1) + h, max(0, int(y0 - 2 * h)), min(gray.shape[0], int(y1 + 2 * h))), max(1.5 * h, 24), h)
        lefts = [r[0] for r in rects if r[0] > x0 + 2 * h]
        cut = min(lefts) - h // 2 - 8 if lefts else x0 + (x1 - x0) * m.start() / len(text) * 0.8
        out.append((text[:m.start()].strip(), (x0, y0, cut, y1)))
        tails.append((text[m.start():].strip(), (cut, y0, x1, y1)))  # what the dropdowns show, apart from the label
    return out, tails


def match(lines, guide, gray=None, scale=1.0, origin=(0, 0)):
    """Guide fields visible on screen, in guide order, with boxes in screen points."""
    labels, tails = _labels(lines, gray, [a for f in guide["fields"] if f["input"] == "date-parts" for a in f["aliases"]])
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
        if f["input"] == "checkbox":  # the label is the box's own text; the mark sits beside it
            m = _mark(gray, label)
            if m:
                hit.update(input_box=to_pt(m[0]), checked=m[1])
        if f["input"] == "radio":
            opts = choices(labels, label, [o["aliases"] for o in f.get("options", [])], gray)
            if opts:
                hit["options"] = [{"text": o["text"], "checked": o["checked"],
                                   "box": to_pt(o["mark"] or o["box"])} for o in opts]
                every = [o["mark"] or o["box"] for o in opts] + [label]
                hit["input_box"] = to_pt((min(b[0] for b in every[:-1]), min(b[1] for b in every[:-1]),
                                          max(b[2] for b in every[:-1]), max(b[3] for b in every[:-1])))
        row = _row(gray, label) if f["input"] == "date-parts" and gray is not None else None
        if row:
            parts = date_parts(row, tails, f.get("parts", "dmy"))
            hit["parts"] = [{"kind": p["kind"], "box": to_pt(p["box"])} for p in parts]
            hit["input_box"] = to_pt((min(r[0] for r in row), min(r[1] for r in row), max(r[2] for r in row), max(r[3] for r in row)))
        out.append(hit)
    return out


def _own_box(gray, box) -> bool:
    """Whether a box's border crosses the line of text's middle to its right: it has an input of its own on its row."""
    cy, x0 = int((box[1] + box[3]) / 2), int(box[2]) + 4
    row = gray[min(cy, gray.shape[0] - 1), x0:x0 + max(600, int(30 * (box[3] - box[1])))].astype(int)
    return row.size > 1 and int((abs(np.diff(row)) >= 20).sum()) >= 2


def _wrapped(lines, gray=None):
    """Lines with a label that wraps onto a second line joined ("Card Customer Service" + "Phone"): a line directly
    under another, tight against it and lined up with it on the right or the left (the other column's lines in
    between don't matter). The joined label keeps the first line's box, which is the one the input sits beside."""
    out = []
    for text, box in sorted(lines, key=lambda l: (l[1][1], l[1][0])):
        for i, (t, b) in enumerate(out):
            h, gap = max(b[3] - b[1], 8), box[1] - b[3]
            if -0.3 * h <= gap <= 1.2 * h and (abs(box[2] - b[2]) <= 1.5 * h or abs(box[0] - b[0]) <= 1.5 * h) \
                    and len(text.split()) <= 3 and len((t + " " + text).split()) <= 5 \
                    and (gray is None or not _own_box(gray, box)):  # a second line has no input beside it
                out[i] = (t + " " + text, b)
                break
        else:
            out.append((text, box))
    return out


def _unmatched(lines, guide, gray, known: set[str], numbered=False):
    """(text, box) of printed labels no alias of the guide matches.

    Only short text with no digits (but "Address line 1" when `numbered`) that has an input border next to it (a value
    sits inside a box, not beside one), and never text that is one of the person's own values (`known`, already
    normalised)."""
    if gray is None:
        return
    aliases = [a for f in guide["fields"] for a in f["aliases"]]
    for text, box in _wrapped(lines, gray):
        t = _norm(text)
        digits = re.sub(r"(?<=\D)\s\d{1,2}$", "", t) if numbered else t
        if not 3 <= len(t) <= 40 or len(t.split()) > 5 or re.search(r"\d", digits) or _score(text, aliases) >= THRESHOLD:
            continue
        if any(t in k or k in t for k in known) or not (_below(gray, box) or _right(gray, box)):
            continue
        yield text, box


def unknown_labels(lines, guide, gray, known: set[str]) -> list[str]:
    """Printed labels no alias of the guide matches, to learn new aliases from."""
    return [text.strip(" :*") for text, _ in _unmatched(lines, guide, gray, known)]


def _overlap(a, b) -> float:
    """How much of the smaller box the two share."""
    w, h = min(a[2], b[2]) - max(a[0], b[0]), min(a[3], b[3]) - max(a[1], b[1])
    return max(w, 0) * max(h, 0) / max(min((a[2] - a[0]) * (a[3] - a[1]), (b[2] - b[0]) * (b[3] - b[1])), 1e-6)


def unknown_boxes(lines, guide, gray, known: set[str], taken, scale=1.0, origin=(0, 0)) -> list[dict]:
    """Boxes the guide doesn't know: [{label, label_box, input_box}] in screen points, top to bottom, left to right.

    `taken` are the input boxes of the fields that did match; a box one of them already owns is not unknown, and
    neither is text inside one (a value already typed in)."""
    to_pt = lambda b: tuple(round(v / scale + origin[i % 2], 1) for i, v in enumerate(b))
    inside = lambda b, r: r[0] < (b[0] + b[2]) / 2 < r[2] and r[1] < (b[1] + b[3]) / 2 < r[3]
    taken_px = [tuple((v - origin[i % 2]) * scale for i, v in enumerate(t)) for t in taken]
    cands = [(text, box, _input_box(gray, box, "auto")) for text, box in _unmatched(lines, guide, gray, known, numbered=True)]
    held = [[o for _, o in lines if o != box and inside(o, raw)] for _, box, raw in cands]
    values = [h[0] for h in held if len(h) == 1]  # a box with one line of text in it: that line is its value, not a label
    out = []
    for (text, box, raw), inner in zip(cands, held):
        if inner or any(inside(box, v) or box == v for v in values) or any(inside(box, t) for t in taken_px):
            continue  # a panel around other fields, a box already filled, or text inside a box: a value
        found = to_pt(raw)
        if any(_overlap(found, t) > 0.3 for t in [*taken, *(u["input_box"] for u in out)]):
            continue
        out.append({"label": text.strip(" :*"), "label_box": to_pt(box), "input_box": found})
    if taken:  # the form is where the known fields are: not the menu bar, tabs or navigation far above or below it
        top, bottom = min(t[1] for t in taken) - 150, max(t[3] for t in taken) + 300
        out = [u for u in out if top <= u["label_box"][1] <= bottom]
    return sorted(out, key=lambda u: (round(u["label_box"][1] / 12), u["label_box"][0]))


def reading_order(items: list[dict]) -> list[dict]:
    """Fields in the order a person fills them: down each column of boxes, left column first, when the form has
    long columns (three boxes or more); otherwise row by row, left to right. By each field's `input_box`."""
    items = sorted(items, key=lambda f: f["input_box"][0])
    cols = []  # boxes whose left edges line up (within 60 points) are one column
    for f in items:
        if cols and f["input_box"][0] - cols[-1][0]["input_box"][0] <= 60:
            cols[-1].append(f)
        else:
            cols.append([f])
    tall = [c for c in cols if len(c) >= 3]
    if len(tall) >= 2:
        for c in cols:
            if c not in tall:  # a short stray box joins the nearest long column
                for f in c:
                    min(tall, key=lambda t: abs(t[0]["input_box"][0] - f["input_box"][0])).append(f)
        return [f for c in tall for f in sorted(c, key=lambda f: f["input_box"][1])]
    rows = []
    for f in sorted(items, key=lambda f: f["input_box"][1]):
        y0, y1 = f["input_box"][1], f["input_box"][3]
        if rows and y0 - rows[-1][0] <= 0.5 * (y1 - y0):
            rows[-1][1].append(f)
        else:
            rows.append((y0, [f]))
    return [f for _, row in rows for f in sorted(row, key=lambda f: f["input_box"][0])]
