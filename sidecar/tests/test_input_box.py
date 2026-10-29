"""Box geometry on forms that do not use the demo portal's full-width bordered inputs."""
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from sahl.match import _input_box

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
