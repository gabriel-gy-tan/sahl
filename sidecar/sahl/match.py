"""Finds each guide field's label among the OCR lines, then the input box that belongs to it."""
import numpy as np
from rapidfuzz import fuzz

THRESHOLD = 85


def _score(text: str, aliases: list[str]) -> float:
    t = text.lower().strip(" :*")
    # ratio, not WRatio: partial matching lets "Passport number" score high against "Passport expiry date"
    return max(fuzz.ratio(t, a.lower()) for a in aliases)


def _input_box(gray, label, hint):
    """The input rectangle next to a label, found from its border lines in the screenshot.

    ponytail: border scan on light, bordered inputs; falls back to a box sized from the label.
    Upgrade to the accessibility tree when real portals break this.
    """
    x0, y0, x1, y1 = (int(v) for v in label)
    h = max(y1 - y0, 8)
    guess = (x0, y1 + 0.5 * h, x0 + 20 * h, y1 + 3.2 * h) if hint == "below" else (x1 + h, y0 - h, x1 + 21 * h, y1 + h)
    if gray is None:
        return guess
    H, W = gray.shape
    gx0, gy0, gx1, gy1 = (int(max(0, v)) for v in guess)
    gx1, gy1 = min(gx1, W), min(gy1 + 2 * h, H)
    probe = slice(gx0 + 2 * h, min(gx0 + 8 * h, W))  # columns well inside the box, clear of rounded corners
    if probe.start >= probe.stop or gy0 >= gy1:
        return guess
    strip = gray[gy0:gy1, probe].astype(int)
    bg = np.median(gray[max(0, y0 - h):y0, probe])
    edge = [gy0 + i for i, row in enumerate(strip) if np.mean(np.abs(row - bg) > 12) > 0.9]
    if len(edge) < 2:
        return guess
    top = edge[0]
    bottom = next((y for y in edge if y - top > h), None)
    if bottom is None:
        return guess
    # walk the top border outward from the probe until it ends
    on = np.abs(gray[top, :].astype(int) - bg) > 12
    lx, rx = probe.start, probe.stop - 1
    while lx > 0 and on[lx - 1]:
        lx -= 1
    while rx < W - 1 and on[rx + 1]:
        rx += 1
    return (lx, top, rx, bottom)


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
        out.append({"id": f["id"], "label_box": to_pt(label), "input_box": to_pt(_input_box(gray, label, f["box"]))})
    return out
