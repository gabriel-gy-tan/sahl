"""Draws the invented resident's passport and Emirates ID into demo/samples/. Not real documents.

Run it with the sidecar's Python: `python demo/make_samples.py`.
"""
import os
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).parent / "samples"
WINDOWS_FONTS = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"


def font(size, mono=False):
    mac = ["/System/Library/Fonts/Menlo.ttc"] if mono else ["/System/Library/Fonts/Helvetica.ttc"]
    win = [WINDOWS_FONTS / "consola.ttf"] if mono else [WINDOWS_FONTS / "arial.ttf"]
    for p in mac + win + (["DejaVuSansMono.ttf"] if mono else ["DejaVuSans.ttf"]):
        try:
            return ImageFont.truetype(p, size)
        except OSError:
            pass
    return ImageFont.load_default(size)


def check(s):
    w = (7, 3, 1)
    v = lambda c: int(c) if c.isdigit() else 0 if c == "<" else ord(c) - 55
    return str(sum(v(c) * w[i % 3] for i, c in enumerate(s)) % 10)


def passport(file="passport.png", surname="KUNNUMMAL", given="MOHAMMED RAFEEQ", num="X1234567<",
             dob="850314", born="14 MAR 1985", sex="M", exp="310902", expires="02 SEP 2031"):
    nat, pers = "IND", "<" * 14
    l1 = "P<IND" + surname + "<<" + given.replace(" ", "<")
    l1 += "<" * (44 - len(l1))
    l2 = num + check(num) + nat + dob + check(dob) + sex + exp + check(exp) + pers + check(pers)
    l2 += check(num + check(num) + dob + check(dob) + exp + check(exp) + pers + check(pers))
    img = Image.new("RGB", (1400, 900), "#f3efe6")
    d = ImageDraw.Draw(img)
    d.text((60, 40), "REPUBLIC OF SAMPLELAND · PASSPORT", fill="#333", font=font(40))
    d.text((60, 95), "SAMPLE · INVENTED · NOT A REAL DOCUMENT", fill="#b33", font=font(28))
    d.rectangle((60, 170, 400, 600), fill="#d9d4c7")
    rows = [("Surname", surname), ("Given names", given), ("Nationality", "INDIAN"),
            ("Date of birth", born), ("Passport No.", num.rstrip("<")), ("Date of expiry", expires)]
    for i, (k, v) in enumerate(rows):
        d.text((450, 170 + i * 70), k, fill="#666", font=font(24))
        d.text((450, 198 + i * 70), v, fill="#111", font=font(34))
    d.text((60, 700), l1, fill="#111", font=font(36, mono=True))
    d.text((60, 770), l2, fill="#111", font=font(36, mono=True))
    img.save(OUT / file)


def emirates_id(file="emirates_id.png", number="784-1985-0000001-0", name="MOHAMMAD RAFEEQ ABDULLA KUNNUMMAL",
                born="14/03/1985"):
    img = Image.new("RGB", (1400, 880), "#e8f0ee")
    d = ImageDraw.Draw(img)
    d.text((60, 40), "RESIDENT IDENTITY CARD", fill="#333", font=font(40))
    d.text((60, 95), "SAMPLE · INVENTED · NOT A REAL DOCUMENT", fill="#b33", font=font(28))
    d.rectangle((60, 170, 400, 600), fill="#cfdcd8")
    d.text((450, 180), "ID Number", fill="#666", font=font(24))
    d.text((450, 210), number, fill="#111", font=font(44))
    d.text((450, 300), "Name", fill="#666", font=font(24))
    d.text((450, 330), name, fill="#111", font=font(34))
    d.text((450, 410), "Nationality", fill="#666", font=font(24))
    d.text((450, 440), "INDIAN", fill="#111", font=font(34))
    d.text((450, 520), "Date of Birth", fill="#666", font=font(24))
    d.text((450, 550), born, fill="#111", font=font(34))
    img.save(OUT / file)


def visa_form(file="visa_form.png"):
    """A US-style visa application page: surname first, comma, given names."""
    img = Image.new("RGB", (1400, 900), "#ffffff")
    d = ImageDraw.Draw(img)
    d.text((60, 40), "NONIMMIGRANT VISA APPLICATION · CONFIRMATION", fill="#333", font=font(36))
    d.text((60, 95), "SAMPLE · INVENTED · NOT A REAL DOCUMENT", fill="#b33", font=font(28))
    rows = [("Name Provided", "KUNNUMMAL, MOHAMMED RAFEEQ"), ("Date of Birth", "14/03/1985"),
            ("Nationality", "INDIA"), ("Passport Number", "X1234567")]
    for i, (k, v) in enumerate(rows):
        d.text((60, 180 + i * 90), k, fill="#666", font=font(26))
        d.text((60, 212 + i * 90), v, fill="#111", font=font(36))
    img.save(OUT / file)


if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    passport()
    emirates_id()
    # a second invented resident in the same folder, to check documents are grouped by person
    passport("passport_2.png", "MENON", "PRIYA ANIL", "Z7654321<", "620805", "05 AUG 1962", "F", "290117", "17 JAN 2029")
    emirates_id("emirates_id_2.png", "784-1962-0000002-7", "PRIYA ANIL MENON", "05/08/1962")
    # his father: the father's name also appears inside the son's Emirates ID name
    passport("passport_3.png", "KUNNUMMAL", "ABDULLA", "Y1112223<", "550210", "10 FEB 1955", "M", "300606", "06 JUN 2030")
    visa_form()
    print("wrote", *sorted(p.name for p in OUT.iterdir()))
