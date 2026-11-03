"""Random radio groups and checkboxes, drawn: circles or squares of any size, line and colour, ticked or not,
options side by side or stacked, on light or dark pages, with the mark before the text or after it (right to left),
and OCR reading each option alone or the whole row as one line. Sahl must find each option's mark and whether it is ticked."""
import collections
import random

import numpy as np
import pytest
from PIL import Image, ImageDraw, ImageFont

from sahl.match import _mark, choices

OPTIONS = [["Male", "ذكر"], ["Female", "أنثى"], ["Yes"], ["No"], ["Single"], ["Married"], ["Divorced"], ["Other"],
           ["Arabic"], ["English"], ["Government"], ["Private or Free Zone"]]


def group(rng):
    size = rng.choice([14, 16, 18, 20, 24, 28])
    font = ImageFont.load_default(size)
    dark = rng.random() < 0.15
    page = rng.choice([30, 40]) if dark else rng.choice([255, 250, 244])
    ink = rng.choice([200, 225]) if dark else rng.choice([0, 50, 80])
    line = rng.choice([110, 150]) if dark else rng.choice([60, 120, 170])
    shape = rng.choice(["circle", "circle", "square"])
    rtl = rng.random() < 0.2
    across = rng.random() < 0.6
    one_line = across and rng.random() < 0.5
    takes_mark = not one_line and rng.random() < 0.4
    im = Image.new("L", (1600, 700), page)
    d = ImageDraw.Draw(im)
    qx, qy = (rng.randint(40, 200), rng.randint(60, 200)) if not rtl else (rng.randint(1100, 1300), rng.randint(60, 200))
    question = d.textbbox((qx, qy), "Gender", font=font)
    d.text((qx, qy), "Gender", fill=ink, font=font)
    h = question[3] - question[1]
    opts = rng.sample(OPTIONS, rng.randint(2, 4))
    pick = rng.randrange(len(opts))
    r = int(h * rng.uniform(0.75, 1.3))  # radios and checkboxes are about the text's height, often a little more
    gap = int(h * rng.uniform(0.3, 0.9))
    x = (question[2] + int(h * rng.uniform(1, 4))) if across and not rtl else (question[0] if not rtl else question[0] - 600)
    y = qy if across else question[3] + int(h * rng.uniform(0.6, 1.5))
    drawn, texts = [], []
    for i, o in enumerate(opts):
        tb = d.textbbox((0, 0), o[0], font=font)
        tw = tb[2] - tb[0]
        cy = y + (question[3] - question[1]) // 2 + 2
        if not rtl:
            mark = (x, cy - r // 2 - 2, x + r, cy + r // 2 - 2)
            tx = x + r + gap
        else:
            tx = x if across else question[2] - tw - gap - r  # stacked: right-aligned under the question
            mark = (tx + tw + gap, cy - r // 2 - 2, tx + tw + gap + r, cy + r // 2 - 2)
        width = rng.choice([1, 2, 2, 3])
        if shape == "circle":
            d.ellipse(mark, outline=line, width=width)
            if i == pick:
                k = max(2, r // 4)
                d.ellipse((mark[0] + k, mark[1] + k, mark[2] - k, mark[3] - k), fill=ink)
        else:
            d.rounded_rectangle(mark, radius=rng.choice([0, 2, 4]), outline=line, width=width)
            if i == pick:
                d.line((mark[0] + r * 0.2, mark[1] + r * 0.55, mark[0] + r * 0.45, mark[3] - r * 0.2, mark[2] - r * 0.15, mark[1] + r * 0.2),
                       fill=ink, width=max(2, r // 6))
        d.text((tx, y), o[0], fill=ink, font=font)
        tb = d.textbbox((tx, y), o[0], font=font)
        if takes_mark:  # OCR reads the mark as the line's first character ("O India"), so its box covers the mark
            tb = (min(tb[0], mark[0]), tb[1], max(tb[2], mark[2]), tb[3])
            texts.append((("O " + o[0]) if not rtl else (o[0] + " O"), tb))
        else:
            texts.append((o[0], tb))
        drawn.append((mark, i == pick))
        if across:
            x = (tx + tw + int(h * rng.uniform(1.2, 4))) if not rtl else x + tw + gap + r + int(h * rng.uniform(1.2, 4))
        else:
            y += int(h * rng.uniform(1.6, 2.6))
    if one_line:  # the whole row as OCR reads it: marks and words in screen order, the box around all of them
        every = [b for b, _ in drawn] + [b for _, b in texts]
        u = (min(b[0] for b in every), min(b[1] for _, b in texts), max(b[2] for b in every), max(b[3] for _, b in texts))
        words = [("O " + t) if not rtl else (t + " O") for t, _ in texts]
        lines = [(" ".join(words), u)]
    else:
        lines = texts
    return np.array(im), question, opts, drawn, lines + [("Gender", question)], dict(shape=shape, rtl=rtl, across=across, one_line=one_line, dark=dark, size=size, takes_mark=takes_mark)


@pytest.mark.parametrize("seed", [5, 6, 7])
def test_random_radio_groups(seed):
    rng = random.Random(seed)
    seen = collections.defaultdict(lambda: [0, 0])
    for _ in range(300):
        gray, question, opts, drawn, lines, meta = group(rng)
        got = choices(lines, question, opts, gray)
        h = question[3] - question[1]
        ok = len(got) == len(drawn) and all(
            g["mark"] and all(abs(a - b) <= max(4, 0.3 * h) for a, b in zip(g["mark"], m)) and g["checked"] == c
            for g, (m, c) in zip(got, drawn))
        for key in ("all", meta["shape"], "rtl" if meta["rtl"] else "ltr", "one line" if meta["one_line"] else "own lines",
                    "dark" if meta["dark"] else "light", "mark in line" if meta["takes_mark"] else "mark apart"):
            seen[key][0] += ok
            seen[key][1] += 1
    rate = {k: round(a / b, 3) for k, (a, b) in seen.items()}
    print(rate)
    assert rate["all"] >= 0.97, rate  # 99.2-99.4% when this was written
    assert min(rate.values()) >= 0.9, rate


def test_checkbox_mark_beside_its_text():
    image = Image.new("L", (900, 200), 255)
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(20)
    text = draw.textbbox((100, 50), "I confirm the information is correct", font=font)
    draw.text((100, 50), "I confirm the information is correct", fill=0, font=font)
    draw.rectangle((72, 52, 90, 70), outline=80, width=2)
    box, checked = _mark(np.array(image), text)
    assert abs(box[0] - 72) <= 2 and abs(box[2] - 91) <= 2 and checked is False
