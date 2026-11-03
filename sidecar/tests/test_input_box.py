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
    for read in ("Date Of Birth Month - Day- Year -", "Date Of Birth Month- |Day-|Year -", "Date Of Birth Mar 21 2009"):
        hit, = match([(read, (80, 56, 650, 100))], guide, np.array(image))
        assert hit["id"] == "dob" and hit["seen"] == "Date Of Birth"
        assert [p["kind"] for p in hit["parts"]] == ["m", "d", "y"]
        assert [p["box"][0] for p in hit["parts"]] == [304, 441, 541]


def test_a_numbered_label_is_not_cut_back_like_a_date():
    from sahl.match import _labels
    lines = [("Address line 2", (80, 56, 300, 100))]
    assert _labels(lines, np.full((300, 900), 255, np.uint8), ["Date of birth"])[0] == lines


def test_a_row_of_dropdowns_between_two_text_boxes_is_not_mistaken_for_one_tall_box():
    """The bottom of the box above and the top of the box below pair into a phantom box that hides the real ones."""
    image = Image.new("L", (900, 300), 255)
    draw = ImageDraw.Draw(image)
    draw.text((60, 120), "Date Of Birth", fill=0, font=FONT)
    label = draw.textbbox((60, 120), "Date Of Birth", font=FONT)
    draw.rectangle((300, 60, 800, 100), outline=0, width=2)    # a text box above
    for left, right in ((300, 420), (428, 530), (538, 650)):   # the dropdowns, a few px apart
        draw.rectangle((left, 112, right, 150), outline=0, width=2)
    draw.rectangle((300, 160, 800, 200), outline=0, width=2)   # a text box below
    assert [r[0] for r in _row(np.array(image), label)] == [300, 428, 538]


def test_a_candidate_that_holds_another_is_dropped_but_near_twins_stay():
    """On RoboForm the box above's bottom border paired with this box's bottom border, a taller phantom that won on
    a one-pixel tie; the real box lies inside it."""
    from sahl.match import _tight
    phantom, real = (0.1, (423, 525, 593, 562)), (0.2, (424, 531, 592, 562))
    assert _tight([phantom, real]) == [real]
    twin = (0.3, (425, 531, 593, 562))
    assert _tight([real, twin]) == [real, twin]


def shaded_form(side):
    """Rows of labels with grey, borderless inputs, like a portal that fills boxes in for you: on the right of
    each label (a table of fields), or below it (a stacked form)."""
    image = Image.new("L", (1100, 700), 255)
    draw = ImageDraw.Draw(image)
    rows = []
    for i in range(6):
        y = 40 + i * 100
        label = draw.textbbox((44, y), f"Field number {i}", font=FONT)
        if side == "right":
            box = (580, y - 18, 1050, y + 42)
        else:
            box = (44, y + 40, 1050, y + 90)
        draw.rectangle(box, fill=235)
        draw.rectangle((box[0], box[1], box[0] + 4, box[3]), fill=120)  # the coloured bar some portals add
        draw.text((box[0] + 20, box[1] + 14), f"value {i}", fill=70, font=FONT)
        rows.append((label, box))
    return np.array(image), rows


def test_shaded_boxes_to_the_right_of_stacked_labels():
    gray, rows = shaded_form("right")
    for label, box in rows:
        left, top, right, bottom = _input_box(gray, label, "auto")
        assert abs(left - box[0]) <= 4 and abs(right - box[2]) <= 4, (label, box, (left, top, right, bottom))
        assert abs(top - box[1]) <= 4 and abs(bottom - box[3]) <= 4


def test_shaded_boxes_below_stacked_labels():
    gray, rows = shaded_form("below")
    for label, box in rows:
        left, top, right, bottom = _input_box(gray, label, "auto")
        assert abs(left - box[0]) <= 4 and abs(right - box[2]) <= 4, (label, box, (left, top, right, bottom))
        assert abs(top - box[1]) <= 4 and abs(bottom - box[3]) <= 4


def test_two_columns_of_labels_above_boxes_keep_their_own_box():
    image = Image.new("L", (2000, 300), 255)
    draw = ImageDraw.Draw(image)
    left_label = draw.textbbox((35, 40), "First Name English", font=FONT)
    draw.text((35, 40), "First Name English", fill=0, font=FONT)
    draw.text((1032, 40), "First Name Arabic", fill=0, font=FONT)
    for box in ((35, 80, 977, 140), (1032, 80, 1975, 140)):
        draw.rectangle(box, fill=235)
    left, top, right, bottom = _input_box(np.array(image), left_label, "auto")
    assert abs(left - 35) <= 4 and abs(right - 977) <= 4 and abs(top - 80) <= 4


def _layout(boxes, label_at, text="Mobile Number", size=(1400, 400)):
    """A label and boxes: each box is (rect, fill or None for a 2 px border, rounded corner radius)."""
    image = Image.new("L", size, 255)
    draw = ImageDraw.Draw(image)
    draw.text(label_at, text, fill=0, font=FONT)
    for rect, fill, radius in boxes:
        if fill is None:
            draw.rounded_rectangle(rect, radius=radius, outline=0, width=2)
        else:
            draw.rounded_rectangle(rect, radius=radius, fill=fill, outline=200)
    return np.array(image), draw.textbbox(label_at, text, font=FONT)


def _near(got, want, slack=6):
    return all(abs(a - b) <= slack for a, b in zip(got, want))


import pytest  # noqa: E402


@pytest.mark.parametrize("name, boxes, label_at, want", [
    ("box left of the label (Arabic)", [((60, 45, 700, 95), None, 0)], (900, 55), (60, 45, 700, 95)),
    ("box above the label", [((60, 40, 800, 90), None, 0)], (60, 110), (60, 40, 800, 90)),
    ("tall text area below", [((60, 100, 800, 300), None, 0)], (60, 50), (60, 100, 800, 300)),
    ("rounded box below", [((60, 100, 800, 150), None, 12)], (60, 50), (60, 100, 800, 150)),
    ("rounded shaded box right", [((400, 40, 1100, 100), 235, 10)], (60, 55), (400, 40, 1100, 100)),
])
def test_box_on_any_side_and_shape(name, boxes, label_at, want):
    gray, label = _layout(boxes, label_at)
    assert _near(_input_box(gray, label, "auto"), want), name


def _split(code, number, label_at, code_side="left"):
    """A phone box in two parts: a shaded country code you pick (00971) and the part you type in."""
    image = Image.new("L", (1400, 400), 255)
    draw = ImageDraw.Draw(image)
    draw.text(label_at, "Mobile Number", fill=0, font=FONT)
    draw.rectangle(code, fill=230, outline=200)
    draw.text((code[0] + 20, code[1] + 18), "00971 - UNITED ARAB", fill=60, font=FONT)
    bar = (code[2], code[1], code[2] + 4, code[3]) if code_side == "left" else (code[0] - 5, code[1], code[0] - 1, code[3])
    draw.rectangle(bar, fill=150)  # the coloured bar between them
    draw.rectangle(number, outline=200, width=2)
    return np.array(image), draw.textbbox(label_at, "Mobile Number", font=FONT)


@pytest.mark.parametrize("code, number, label_at, side", [
    ((60, 100, 440, 160), (446, 100, 1000, 160), (60, 50), "left"),    # below the label
    ((680, 230, 1060, 290), (1066, 230, 1380, 290), (60, 250), "left"),  # right of the label
    ((640, 100, 1000, 160), (60, 100, 634, 160), (60, 50), "right"),   # code on the right, as in Arabic
])
def test_split_phone_box_rings_the_part_you_type_in(code, number, label_at, side):
    gray, label = _split(code, number, label_at, side)
    assert _near(_input_box(gray, label, "auto"), number)
