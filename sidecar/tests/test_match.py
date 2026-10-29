"""UAE portal labels vary in punctuation, spelling and language; these are the field-picking cases."""
import json
from pathlib import Path

import pytest

from sahl import match

ROOT = Path(__file__).resolve().parents[2]
GUIDE = json.loads((ROOT / "guides/any-form.json").read_text(encoding="utf-8"))


def matched(*labels):
    lines = [(text, (0, i * 40, 200, i * 40 + 20)) for i, text in enumerate(labels)]
    return [hit["id"] for hit in match.match(lines, GUIDE)]


@pytest.mark.parametrize("label, expected", [
    ("Applicant's Full Name", ["full_name"]),
    ("Applicant’s Full Name", ["full_name"]),
    ("Applicant Full Name", ["full_name"]),
    ("Name as per Emirates ID", ["full_name"]),
    ("Name as per passport", ["full_name"]),
    ("Name of Applicant", ["full_name"]),
    ("Customer Name", ["full_name"]),
    ("الاسمُ الكامل", ["full_name"]),
    ("Date of Birth (DD/MM/YYYY)", ["dob"]),
    ("Date of Birth :", ["dob"]),
    ("Applicant's Date of Birth", ["dob"]),
    ("Nationality (Country)", ["nationality"]),
    ("Country of Nationality", ["nationality"]),
    ("Applicant's Nationality", ["nationality"]),
    ("الجنسية", ["nationality"]),
    ("Passport No.", ["passport_number"]),
    ("PASSPORT NO.", ["passport_number"]),
    ("Passport #", ["passport_number"]),
    ("Applicant's Passport Number", ["passport_number"]),
    ("Passport Expiry", ["passport_expiry"]),
    ("Date of Expiry", ["passport_expiry"]),
    ("Applicant's Passport Expiry Date", ["passport_expiry"]),
    ("EID No.", ["emirates_id"]),
    ("Emirates ID No", ["emirates_id"]),
    ("ID No.", ["emirates_id"]),
    ("Applicant's Emirates ID Number", ["emirates_id"]),
    ("رقم الهوية", ["emirates_id"]),
    ("Sponsor Name", []),
    ("Sponsor's Name", []),
    ("Sponsor ID No.", []),
    ("Application ID No.", []),
    ("Father's Name", []),
    ("Company Name", []),
    ("Date of Issue", []),
    ("Passport issue date", []),
    ("Email Address", []),
])
def test_uae_label_variants(label, expected):
    assert matched(label) == expected


def test_common_uae_form_ignores_other_boxes():
    labels = [
        "Sponsor Name", "Date of Issue", "Applicant's Full Name", "Passport No.",
        "Date of Birth", "Nationality (Country)", "EID No.", "Email Address",
    ]
    assert matched(*labels) == ["full_name", "dob", "nationality", "passport_number", "emirates_id"]
