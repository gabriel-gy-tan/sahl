"""Box geometry on forms that do not use the demo portal's full-width bordered inputs."""
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from sahl.match import _input_box, _row, date_parts

ROOT = Path(__file__).resolve().parents[2]
FONT = ImageFont.load_default(24)


def form():
    image = Image.new("L", (900, 600), 255)
    draw = ImageDraw.Draw(image)
    draw.text((60, 50), "Full name", fill=0, font=FONT)
    return image, draw, draw.textbbox((60, 50), "Full name", font=FONT)


def test_finds_wide_underlined_box_below_label():
    image, draw, label = form()
    draw.line((60, 110, 800, 110), fill=0, width=2)
    left, top, right, bottom = _input_box(np.array(image), label, "auto")
    assert (left, bottom) == (60, 110)
    assert right >= 800 and top < bottom


def test_finds_bordered_box_below_label():
    image, draw, label = form()
    draw.rectangle((60, 100, 800, 150), outline=0, width=2)
    left, top, right, bottom = _input_box(np.array(image), label, "auto")
    assert left == 60 and right >= 800
    assert abs(top - 100) <= 2 and abs(bottom - 150) <= 2


def test_finds_bordered_box_to_the_right_of_label():
    image, draw, label = form()
    draw.rectangle((300, 45, 800, 90), outline=0, width=2)
    left, top, right, bottom = _input_box(np.array(image), label, "auto")
    assert left == 300 and right >= 800
    assert abs(top - 45) <= 2 and abs(bottom - 90) <= 2


def test_finds_underlined_box_to_the_right_of_label():
    image, draw, label = form()
    draw.line((300, 80, 800, 80), fill=0, width=2)
    left, top, right, bottom = _input_box(np.array(image), label, "auto")
    assert left == 300 and right >= 800 and bottom == 80
    assert top < bottom


def test_any_form_lets_the_layout_choose_the_side():
    guide = json.loads((ROOT / "guides/any-form.json").read_text(encoding="utf-8"))
    assert {f["box"] for f in guide["fields"]} == {"auto"}


def test_finds_day_month_year_dropdowns_in_a_row():
    image = Image.new("L", (900, 300), 255)
    draw = ImageDraw.Draw(image)
    draw.text((60, 50), "Date of birth", fill=0, font=FONT)
    label = draw.textbbox((60, 50), "Date of birth", font=FONT)
    lines = [("Date of birth", label)]
    for x, shown in ((60, "Year"), (260, "Day"), (460, "Month")):  # a year-first form
        draw.rectangle((x, 110, x + 160, 160), outline=0, width=2)
        lines.append((shown, (x + 10, 120, x + 80, 150)))
    row = _row(np.array(image), label)
    assert [r[0] for r in row] == [60, 260, 460]
    assert [p["kind"] for p in date_parts(row, lines)] == ["y", "d", "m"]
    joined = [lines[0], ("Year Day Month", (70, 120, 600, 150))]  # OCR often reads boxes in a row as one line
    assert [p["kind"] for p in date_parts(row, joined)] == ["y", "d", "m"]
    assert [p["kind"] for p in date_parts(row, [lines[0]])] == ["d", "m", "y"]  # no placeholders: the guide's order


def test_label_and_dropdowns_read_as_one_ocr_line():
    """OCR reads "Date Of Birth Month v Day v Year v", a label inline with its dropdowns, as a single line."""
    from sahl.match import match
    image = Image.new("L", (900, 300), 255)
    draw = ImageDraw.Draw(image)
    draw.text((80, 60), "Date Of Birth", fill=0, font=FONT)
    for left, right in ((304, 430), (441, 531), (541, 647)):
        draw.rectangle((left, 56, right, 100), outline=0, width=2)
    guide = json.loads((ROOT / "guides/any-form.json").read_text(encoding="utf-8"))
    for read in ("Date Of Birth Month - Day- Year -", "Date Of Birth Month- |Day-|Year -"):
        hit, = match([(read, (80, 56, 650, 100))], guide, np.array(image))
        assert hit["id"] == "dob" and hit["seen"] == "Date Of Birth"
        assert [p["kind"] for p in hit["parts"]] == ["m", "d", "y"]
        assert [p["box"][0] for p in hit["parts"]] == [304, 441, 541]
