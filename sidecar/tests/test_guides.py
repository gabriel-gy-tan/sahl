import re
from urllib.parse import urlparse

import pytest

from sahl import server

GUIDES = server.load_guides()
GOV = (".gov.ae", ".abudhabi", ".ae")  # official hosts only; tamm.abudhabi has no .gov.ae
KEYS = {f"{d}.{k}" for d in ("passport", "eid", "other") for k in ("name", "given", "surname", "dob", "nationality")} | {
    "passport.number", "passport.expiry", "eid.number", "eid.expiry", "profile.mobile"}


@pytest.mark.parametrize("g", GUIDES.values(), ids=list(GUIDES))
def test_guide_shape(g):
    assert {"en", "ar"} <= g["service"].keys() and (g.get("about") or g["id"] == "any-form")
    if g.get("requirements"):  # a fact needs its source and the day it was read
        assert urlparse(g["source"]).scheme == "https" and urlparse(g["source"]).hostname.endswith(GOV)
        assert re.fullmatch(r"\d{4}-\d\d-\d\d", g["checked"])
        assert all(isinstance(v, list) and v and all(isinstance(x, str) for x in v) for v in g["requirements"].values())
    for f in g["fields"]:
        keys = f["vault_key"] if isinstance(f["vault_key"], list) else [f["vault_key"]]
        assert set(keys) - {None} <= KEYS, keys  # None: a box Sahl shows but never fills
