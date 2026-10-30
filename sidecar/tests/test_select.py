"""Dropdowns and date lists: auto-pick a verified value, or let the person pick from the opened list."""
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw, ImageFont

from sahl import ai, server

ROOT = Path(__file__).resolve().parents[2]
FONT = ImageFont.load_default(24)
GUIDE = {
    "id": "test-select",
    "service": {"en": "Test select", "ar": "", "ur": "", "ml": ""},
    "fields": [{
        "id": "nationality",
        "vault_key": ["passport.nationality"],
        "input": "select",
        "box": "below",
        "aliases": ["Nationality"],
        "help": {"en": "The country on your passport.", "ar": "", "ur": "", "ml": ""},
    }],
}


@pytest.fixture
def picker_app(monkeypatch, tmp_path):
    monkeypatch.setenv("SAHL_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("SAHL_LIBRARY", str(tmp_path / "library"))
    monkeypatch.setattr(ai, "read_page", lambda gray: None)
    monkeypatch.setattr(server, "load_guides", lambda: {GUIDE["id"]: GUIDE})

    page = Image.new("L", (900, 700), 255)
    draw = ImageDraw.Draw(page)
    draw.text((60, 50), "Nationality", fill=0, font=FONT)
    draw.rectangle((60, 100, 500, 140), outline=0, width=2)
    draw.text((72, 110), "Choose...", fill=0, font=FONT)
    opened, picked = [], []

    def opener(box):
        opened.append(box)
        draw.rectangle((60, 142, 500, 270), fill=255, outline=0, width=2)
        for i, text in enumerate(("Choose...", "India", "Pakistan")):
            draw.text((72, 148 + i * 36), text, fill=0, font=FONT)

    def option_at(box):
        y = (box[1] + box[3]) / 2
        return "India" if y < 215 else "Pakistan" if y < 255 else "Choose..."

    def picker(box):
        picked.append(option_at(box))
        draw.rectangle((60, 105, 495, 136), fill=255)
        draw.rectangle((60, 142, 500, 270), fill=255)
        draw.text((72, 110), picked[-1], fill=0, font=FONT)

    app = server.create_app("t0k", screen=lambda: [(np.array(page), 1.0, (0, 0, 900, 700))],
                            opener=opener, picker=picker)
    client = TestClient(app, headers={"x-sahl-token": "t0k"})
    client.opened, client.picked = opened, picked
    return client


def read(client):
    return client.post("/read", json={"guide": GUIDE["id"]}).json()


def test_auto_picks_a_country_from_the_opened_list(picker_app):
    picker_app.post("/vault/import", json={"path": str(ROOT / "demo/samples/passport.png")})
    reading = read(picker_app)
    assert reading["next"] == "nationality"
    assert reading["fields"][0]["vault"]["value"] == "Indian"

    r = picker_app.post("/fill", json={"field_id": "nationality"})
    assert r.status_code == 200
    assert r.json()["landed"] is True and r.json()["options"] == []
    assert picker_app.opened and picker_app.picked == ["India"]
    assert read(picker_app)["next"] is None  # it was confirmed only after the box showed India


def test_manual_options_and_choice(picker_app):
    read(picker_app)
    opened = picker_app.post("/options", json={"field_id": "nationality"})
    assert opened.status_code == 200
    labels = [o["label"] for o in opened.json()["options"]]
    assert labels[1:] == ["India", "Pakistan"] and labels[0].startswith("Choose")

    r = picker_app.post("/choose", json={"field_id": "nationality", "value": "Pakistan"})
    assert r.status_code == 200 and r.json()["landed"] is True
    assert picker_app.picked == ["Pakistan"]
    assert read(picker_app)["next"] is None


def test_no_options_is_not_a_crash(monkeypatch, tmp_path):
    monkeypatch.setenv("SAHL_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("SAHL_LIBRARY", str(tmp_path / "library"))
    monkeypatch.setattr(server, "load_guides", lambda: {GUIDE["id"]: GUIDE})
    page = Image.new("L", (900, 700), 255)
    draw = ImageDraw.Draw(page)
    draw.text((60, 50), "Nationality", fill=0, font=FONT)
    draw.rectangle((60, 100, 500, 140), outline=0, width=2)
    app = server.create_app("t0k", screen=lambda: [(np.array(page), 1.0, (0, 0, 900, 700))],
                            opener=lambda box: None, picker=lambda box: None)
    client = TestClient(app, headers={"x-sahl-token": "t0k"})
    read(client)
    r = client.post("/options", json={"field_id": "nationality"})
    assert r.status_code == 200 and r.json()["options"] == []


def test_date_and_nationality_variants_score():
    assert server._option_score("14/03/1985", "14 March 1985") == 100
    assert server._option_score("14/03/1985", "1985-03-14") == 100
    assert server._option_score("Indian", "India") >= 90
    assert server._option_score("Indian", "Pakistan") < 80
    assert server._option_score("14/03/1985", "15 March 1985") < 88
