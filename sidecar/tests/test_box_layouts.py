"""Random form layouts, drawn: a label and its box on any side, at any distance, size, shape and colour, with the
neighbouring fields stacked the way that layout stacks them (and a label always closer to its own box than to the
next field, as forms are drawn). Sahl must ring the label's own box, or the part of a split phone box you type in."""
import collections
import random

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from sahl.match import _input_box

TEXTS = ["Mobile Number", "Date Of Birth", "Emirates ID Number", "Name", "Full name (as in passport)",
         "Detailed Address", "P.O. BOX", "Email", "Applicant Class Details", "City", "Passport No."]

def case(rng):
    size = rng.choice([14, 16, 18, 20, 24, 28, 32])
    font = ImageFont.load_default(size)
    dark = rng.random() < 0.15
    page = rng.choice([28, 36]) if dark else rng.choice([255, 255, 250, 244])
    ink = rng.choice([200, 230]) if dark else rng.choice([0, 40, 70, 90])
    side = rng.choice(["below", "below", "right", "right", "left", "above"])
    style = rng.choice(["border", "border", "shade", "shade+border", "underline"])
    if side in ("left", "above") and style == "underline":
        style = "border"
    split = side in ("below", "right") and rng.random() < 0.2 and style != "underline"
    text = rng.choice(TEXTS)
    W, H = 1600, 900
    im = Image.new("L", (W, H), page); d = ImageDraw.Draw(im)
    lx = rng.randint(40, 300) if side != "left" else rng.randint(900, 1200)
    ly = rng.randint(250, 400)
    lab = d.textbbox((lx, ly), text, font=font)
    h = lab[3] - lab[1]
    bh = int(h * rng.choice([1.6, 2, 2.5, 3, 3.5])) if rng.random() > 0.1 else int(h * rng.uniform(6, 10))
    bw = int(h * rng.uniform(8, 40))
    if side == "below":
        gap = int(h * rng.uniform(0.3, 2.0)); x0 = lab[0] + rng.randint(-4, 4); y0 = lab[3] + gap
    elif side == "above":
        gap = int(h * rng.uniform(0.3, 1.5)); x0 = lab[0]; y0 = lab[1] - gap - bh
    elif side == "right":
        gap = int(h * rng.uniform(0.6, 18)); x0 = lab[2] + gap; y0 = (lab[1] + lab[3]) // 2 - bh // 2 + rng.randint(-h // 3, h // 3)
    else:
        gap = int(h * rng.uniform(0.6, 12)); x0 = lab[0] - gap - bw; y0 = (lab[1] + lab[3]) // 2 - bh // 2
    x0 = max(5, x0); x1 = min(W - 5, x0 + bw); y1 = y0 + bh
    radius = rng.choice([0, 0, 4, 8, 12]) if style != "underline" else 0
    fill = (page + rng.choice([-25, -18, -12])) if not dark else page + rng.choice([18, 30])
    line = rng.choice([150, 190, 210]) if not dark else rng.choice([90, 120])
    want = (x0, y0, x1, y1)
    def box(r, typed=False, shade=None):
        if style == "underline":
            d.line((r[0], r[3], r[2], r[3]), fill=line, width=rng.choice([1, 2]))
        elif style == "border":
            d.rounded_rectangle(r, radius=radius, outline=line, width=rng.choice([1, 2, 3]))
        else:
            d.rounded_rectangle(r, radius=radius, fill=shade if shade is not None else fill, outline=line if style == "shade+border" else None)
    if split:
        cw = int(bw * rng.uniform(0.25, 0.45))
        if rng.random() < 0.7:  # country code on the left
            code = (x0, y0, x0 + cw, y1); num = (x0 + cw + 6, y0, x1, y1); bar = (code[2] + 1, y0, code[2] + 4, y1)
        else:  # on the right, as Arabic forms do
            code = (x1 - cw, y0, x1, y1); num = (x0, y0, x1 - cw - 6, y1); bar = (code[0] - 4, y0, code[0] - 1, y1)
        d.rounded_rectangle(code, radius=radius, fill=fill, outline=line)
        d.text((code[0] + 8, code[1] + (bh - h) // 2), "00971 - UAE", fill=ink, font=font)
        d.rectangle(bar, fill=rng.choice([120, 160]))
        d.rounded_rectangle(num, radius=radius, outline=line, width=2)
        want = num
    else:
        box(want)
        if rng.random() < 0.5 and style != "underline":  # a value or placeholder inside the box
            d.text((x0 + 10, y0 + max(2, (bh - h) // 2)), rng.choice(["0501234567", "INDIA", "Please select", text]),
                   fill=rng.choice([ink, 150]) if not dark else 180, font=font)
    d.text((lx, ly), text, fill=ink, font=font)
    # a neighbour stacked the way this layout stacks fields
    # forms keep a label closer to its own box than to the next field (the space between fields is the bigger one)
    step = (lab[3] - lab[1]) + bh + (2 * gap if side in ("below", "above") else 0) + int(h * rng.uniform(1, 3))
    for k in (-1, 1):
        if side in ("below", "above"):
            nl = (lx, ly + k * step)
        else:
            nl = (lx, ly + k * max(bh + h, int(h * rng.uniform(3, 5))))
        if not 0 < nl[1] < H - 3 * h: continue
        nb = d.textbbox(nl, rng.choice(TEXTS), font=font)
        d.text(nl, rng.choice(TEXTS), fill=ink, font=font)
        ox, oy = nl[0] - lx, nl[1] - ly
        r = (want[0] + ox if not split else x0 + ox, want[1] + oy, x1 + ox, want[3] + oy)
        if 0 < r[1] and r[3] < H: box(r)
    return np.array(im), lab, want, dict(side=side, style=style, split=split, radius=radius, size=size,
                                          dark=dark, tall=bh > 5 * h, gap=round(gap / h, 1))

def _ok(got, want, lab, meta):
    h = lab[3] - lab[1]
    slack = max(6, int(0.3 * h))
    cx, cy = (got[0] + got[2]) / 2, (got[1] + got[3]) / 2
    if meta["style"] == "underline":  # no top on screen: the line's ends and height count, and the click above it
        return all(abs(got[i] - want[i]) <= slack for i in (0, 2, 3)) and want[0] <= cx <= want[2] and want[3] - 4 * h <= cy < want[3]
    return want[0] <= cx <= want[2] and want[1] <= cy <= want[3] and all(abs(a - b) <= slack for a, b in zip(got, want))


def test_random_layouts():
    rng = random.Random(11)
    seen = collections.defaultdict(lambda: [0, 0])
    for _ in range(400):
        gray, lab, want, meta = case(rng)
        ok = _ok(tuple(int(v) for v in _input_box(gray, lab, "auto")), want, lab, meta)
        for key in ("all", meta["side"], "split" if meta["split"] else "whole", "tall" if meta["tall"] else "short"):
            seen[key][0] += ok
            seen[key][1] += 1
    rate = {k: a / b for k, (a, b) in seen.items()}
    assert rate["all"] >= 0.92, rate  # 95-96% when this was written; a drop means box finding got worse
    assert min(rate[k] for k in ("below", "right", "left", "above", "split", "tall")) >= 0.8, rate
