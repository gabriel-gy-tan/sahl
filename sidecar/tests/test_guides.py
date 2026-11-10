import re
from urllib.parse import urlparse

import pytest

from sahl import server

GUIDES = server.load_guides()
GOV = (".ae", ".abudhabi", ".gov")  # official hosts only; tamm.abudhabi has no .gov.ae; embassies are on their own .gov.<country>


def official(host: str) -> bool:
    return host.endswith(GOV) or ".gov." in host or host.endswith(".gov.uk")
KEYS = {f"{d}.{k}" for d in ("passport", "eid", "other") for k in ("name", "given", "surname", "dob", "nationality")} | {
    "passport.number", "passport.expiry", "eid.number", "eid.expiry", "profile.mobile", "ar:passport.name"}


@pytest.mark.parametrize("g", GUIDES.values(), ids=list(GUIDES))
def test_guide_shape(g):
    assert {"en", "ar"} <= g["service"].keys() and (g.get("about") or g["id"] == "any-form")
    if g.get("requirements"):  # a fact needs its source and the day it was read
        assert urlparse(g["source"]).scheme == "https" and official(urlparse(g["source"]).hostname)
        assert re.fullmatch(r"\d{4}-\d\d-\d\d", g["checked"])
        assert all(isinstance(v, list) and v and all(isinstance(x, str) for x in v) for v in g["requirements"].values())
    for f in g["fields"]:
        keys = f["vault_key"] if isinstance(f["vault_key"], list) else [f["vault_key"]]
        assert set(keys) - {None} <= KEYS, keys  # None: a box Sahl shows but never fills
        assert f["input"] in {"text", "date", "select", "date-parts", "radio", "checkbox"} and f.get("box") in {"auto", "below", "right", "left", None}
        assert f["input"] != "radio" or f.get("options"), f["id"]  # a radio group lists what it offers
        for o in f.get("options", []):
            assert o["aliases"] and all(isinstance(a, str) and a for a in o["aliases"]), f["id"]
        assert f["input"] != "checkbox" or f["vault_key"] is None, f["id"]  # Sahl never ticks a box
        assert f["aliases"] and all(isinstance(a, str) and a.strip() for a in f["aliases"]) and {"en", "ar"} <= f["help"].keys()
