"""Square toolbar and store icons from palm.png: the white palm on the island's black, in a rounded square.

Run from the repo with sidecar/.venv (Pillow): `sidecar/.venv/bin/python extension/make_icons.py`.
The 128 px icon keeps 16 px of transparent margin all round, as the Chrome Web Store asks; the small ones fill their square.
"""
from pathlib import Path

from PIL import Image, ImageDraw

HERE = Path(__file__).parent
SS = 8  # draw at 8x and shrink, so the small sizes stay crisp


def icon(size: int) -> Image.Image:
    big = size * SS
    margin = round(size * 0.125) * SS if size >= 128 else 0
    side = big - 2 * margin
    canvas = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    ImageDraw.Draw(canvas).rounded_rectangle([margin, margin, big - margin - 1, big - margin - 1], radius=round(side * 0.22), fill=(0, 0, 0, 255))
    palm = Image.open(HERE / "palm.png").convert("RGBA")
    height = round(side * 0.62)
    palm = palm.resize((round(palm.width * height / palm.height), height), Image.LANCZOS)
    canvas.alpha_composite(palm, ((big - palm.width) // 2, (big - palm.height) // 2 + round(side * 0.02)))
    return canvas.resize((size, size), Image.LANCZOS)


if __name__ == "__main__":
    (HERE / "icons").mkdir(exist_ok=True)
    for n in (16, 32, 48, 128):
        icon(n).save(HERE / "icons" / f"icon{n}.png", optimize=True)
        print("icons/icon%d.png" % n)
