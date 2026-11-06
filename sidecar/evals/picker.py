"""The form picker against real phrasings, with the local model running (llama.cpp). Not part of pytest: it is slow and
needs the model. Run from sidecar/:  .venv/bin/python -m evals.picker [dev|heldout|fresh|all]

Each case is (message, kind wanted, guides that count as right). "dev" is what the picker was fixed against; "heldout"
and "fresh" were written later and measured before anything was fixed from them (heldout 11/15 on its first run, fresh
11/15); the fixes they then showed were general ones (emirates, word forms), so they no longer measure untouched
behaviour either. Add new phrasings to a new set, and keep one untouched to measure on.
"""
import sys
import time

from sahl import intent, server

EID = {"emirates-id-renewal", "tamm-citizen-emirates-id-renew", "tamm-emirates-id-residency-renew-expat"}
RES = {"residence-permit-renewal", "tamm-emirates-id-residency-renew-expat"}
BIRTH = {"tamm-newborn-birth-certificate", "tamm-birth-notification", "tamm-birth-certificate-abroad-newborn",
         "dha-birth-certificate", "ehs-birth-certificate"}  # the Dubai and Abu Dhabi health authorities issue them too
PASS = {"icp-passport-renewal", "tamm-citizen-passport-issue-renew"}
DW = {"mohre-domestic-worker-work-permit", "mohre-domestic-worker-contract", "tamm-domestic-worker-new-contract", "tamm-domestic-worker-file-open"}
PASSPORT = {"icp-passport-renewal", "icp-passport-replace-details", "icp-passport-new", "tamm-citizen-passport-issue-renew",
            "tamm-citizen-passport-replace-data", "tamm-citizen-passport-lost-damaged", "icp-passport-replace-lost"}
EID = {"emirates-id-replacement", "emirates-id-renewal", "icp-new-emirates-id"}

SETS = {
    "dev": [  # (text, kind wanted, guides that count as right)
    ("I want to renew my Emirates ID", "match", EID),
    ("help me fill in the medical fitness form", "match", {"medical-fitness"}),
    ("renew my car registration", "match", {"tamm-renew-vehicle-registration"}),
    ("I need to pay my traffic fines", "match", {"tamm-pay-traffic-fines"}),
    ("apply for a marriage loan", "match", {"tamm-marriage-loan"}),
    ("register my newborn baby", "match", BIRTH),
    ("book my visa medical", "match", {"medical-fitness"}),
    ("I'm on the passport renewal page now", "match", PASS),
    ("أريد تجديد الإقامة", "match", RES),
    ("start the emirates id renewal", "match", EID),
    ("How do I renew my Emirates ID?", "about", EID),
    ("Can you tell me about the marriage loan?", "about", {"tamm-marriage-loan"}),
    ("What documents do I need for a domestic worker visa?", "about", DW),
    ("How much does passport renewal cost?", "about", PASS),
    ("What is the medical fitness test for?", "about", {"medical-fitness"}),
    ("tell me about renewing residency", "about", RES),
    ("how long does a birth certificate take", "about", BIRTH),
    ("كم رسوم تجديد الهوية؟", "about", EID),
    ("my visa needs the blood test", "match", {"medical-fitness"}),
    ("I lost my Emirates ID card", "match", {"emirates-id-replacement"}),
    ("my passport is full, need a new one", "match", {"icp-passport-replace-details", "tamm-citizen-passport-replace-data"}),
    ("transfer my car to my brother", "match", {"tamm-transfer-vehicle-ownership"}),
    ("I want to hire a maid", "match", DW | {"mohre-domestic-worker-contract"}),
    ("sponsor my wife's visa", "match", {"tamm-family-visa-private-sector", "tamm-family-visa-government-sector", "tamm-family-visa-citizen", "tamm-family-residency-and-emirates-id-private"}),
    ("is the marriage loan only for citizens?", "about", {"tamm-marriage-loan"}),
    ("do I need an appointment for the visa medical?", "about", {"medical-fitness"}),
    ("Can you help me renew my Emirates ID?", "match", EID),
    ("explain the golden visa for graduates", "about", {"icp-golden-visa-graduates"}),
    ("ما هي الوثائق المطلوبة لتجديد جواز السفر؟", "about", PASS),
    ("hi", "unsure", set()),
    ("good morning", "unsure", set()),
    ("can you hear me", "unsure", set()),
    ("I'm confused", "unsure", set()),
    ("help", "unsure", set()),
    ("what can you do?", "unsure", set()),
    ("a form", "unsure", set()),
    ("thanks!", "unsure", set()),
    ("what documents do I have?", "unsure", set()),
    ("renew my falconry passport", "new", set()),
    ("apply for a fishing licence in Fujairah", "new", set()),
    ],
    "heldout": [
    ("my passport ran out of pages", "match", PASSPORT),
    ("the pages in my passport are finished, what now", "about", PASSPORT),
    ("I lost my emirates id card", "match", EID),
    ("my emirates id got damaged", "match", EID),
    ("I need to renew my driving licence in abu dhabi", "match", {"tamm-renew-driving-licence"}),
    ("how much is it to renew my car registration", "about", {"tamm-renew-vehicle-registration"}),
    ("register a tenancy contract in dubai", "match", {"dld-tenancy-contract-registration", "dld-tenancy-dubai-now"}),
    ("what documents do i need for a marriage contract", "about", {"moj-marriage-contract"}),
    ("cancel a work permit", "match", {"mohre-cancel-work-permit"}),
    ("renew my hunting licence", "new", set()),
    ("I want a permit to keep a pet camel", "new", set()),
    ("apply for a boat licence in ajman", "new", set()),
    ("good evening sahl", "unsure", set()),
    ("ok", "unsure", set()),
    ("golden visa for investors", "match", {"added-golden-visa-investor", "dld-golden-visa-investor", "icp-golden-visa-public-investor"}),
    ],
    "fresh": [
    ("death certificate in dubai", "match", {"dha-death-certificate"}),
    ("I need a birth certificate for my baby in Dubai", "match", {"dha-birth-certificate"}),
    # DLD issues the title deed when a sale is registered; its "ownership certificate" is a To Whom It May Concern letter
    ("how do I get a title deed for my flat in dubai", "about", {"dld-property-sale-registration", "dld-title-deed-verification"}),
    ("pay my traffic fines in abu dhabi", "match", {"tamm-pay-traffic-fines"}),
    ("renew my residence visa", "match", {"residence-permit-renewal"}),
    ("medical test for residence visa", "match", {"medical-fitness"}),
    ("how much is the medical fitness test", "about", {"medical-fitness"}),
    ("تجديد جواز السفر", "match", {"icp-passport-renewal", "tamm-citizen-passport-issue-renew"}),
    ("كم رسوم تجديد الهوية؟", "about", {"emirates-id-renewal"}),
    ("renew my trade licence in sharjah", "new", set()),
    ("register a car in ras al khaimah", "new", set()),
    ("get a liquor licence", "new", set()),
    ("thank you so much", "unsure", set()),
    ("my emirates id expired last week, what should I do", "about", {"emirates-id-renewal"}),
    ("I want to transfer my school child in dubai", "match", None),  # any KHDA guide
    ],
}


def run(name: str, cases: list) -> int:
    guides, ok = server.load_guides(), 0
    for text, kind, want in cases:
        t0 = time.time()
        r = intent.talk([{"role": "user", "text": text}], guides)
        if want is None:  # any guide from Dubai's schools authority
            good = r["kind"] == kind and any(guides[i].get("authority") == "KHDA" for i in r["options"])
        else:
            good = r["kind"] == kind and (not want or bool(set(r["options"]) & want))
        ok += good
        print(f"{'OK ' if good else 'BAD'} {time.time() - t0:4.1f}s {text!r} -> {r['kind']} {r['options']} {r['name']!r}")
    print(f"{name}: {ok}/{len(cases)}\n")
    return ok


if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    for name, cases in SETS.items():
        if which in (name, "all"):
            run(name, cases)
