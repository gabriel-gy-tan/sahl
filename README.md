<p align="center">
<img src="assets/logo.png" alt="Sahl" width="240">
</p>

A free, open-source desktop helper that looks at the form on your screen, tells you in your language which box comes next, and helps you autofill and confirm the details. Fill a form in seconds to minutes. Everything runs on your own computer: completely local AI. The government side changes nothing.

> Status: working on macOS and running on Windows, in testing. The app reads a form on screen, rings the next box, and types verified values after you confirm. In Chrome and Edge a browser extension reads the page's real fields instead of the screenshot. Boxes no guide knows are asked about once and remembered per person. It is not signed or notarized, it has not yet been tried on live UAE portals. See [TODO.md](TODO.md).
> (Early planning documents call this project "Handover".)

To run it from a checkout, see [sidecar/README.md](sidecar/README.md). Rules for contributors and agents, and how the code fits together, are in [AGENTS.md](AGENTS.md).

## How it works

1. **See** – a screenshot of the form, taken on your computer.
2. **Read** – local OCR (Indra, already working in Yahmi) finds labels and boxes; a small local vision model handles layout and unlabelled boxes. Accessibility-tree data is used first when the app exposes it.
3. **Look up** – the form guide for the chosen service, then your own documents in the local vault.
4. **Show** – voice and card in your language: next box, the value, and a photo of where it came from.
5. **Ask** – a box no guide knows ("Company", "Workplace") gets "we don't know this, tell me"; the answer is kept for that person and offered again when another form uses another name for it, once you say yes.
6. **Stop** – never logs in, never handles UAE PASS, PINs or a card's security code, never presses submit.

### Modes
- **Show only** – tells you what goes in the next box.
- **Confirm, then fill** – types the value after you tap yes. Every section is confirmed first, because filled values can hide mistakes.

### Languages of the guide
English, العربية, اردو, മലയാളം (first set; more later).

## Browser extension

`extension/` is a Manifest V3 Chrome extension that reads the form on a web page, rings the boxes and fills verified values through the app's loopback bridge. It does nothing without the Sahl app running. The bridge takes the first free port from 8765 to 8774 and the extension looks through the same ten; a paired browser only sends its token and the page's details to the Sahl that proves it holds the same token. The page's address is sent without its query or fragment; forms inside frames are read too.

- Privacy: [PRIVACY.md](PRIVACY.md) says what the app and the extension read, keep and send.
- Try it from a checkout: Chrome → Extensions → Developer mode → Load unpacked → `extension/`, then open Settings → Browser extension in the app for the pairing code.
- Demo: `sh demo/pitch.sh` runs Sahl on invented documents only (your own vault is untouched) and serves `demo/refund-portal.html`, a sample portal with every case on one page; [demo/PITCH.md](demo/PITCH.md) is the run-sheet.
- Checks: `node --test extension/`; `python3 extension/package.py` writes the Chrome Web Store zip to `dist/`; `sidecar/.venv/bin/python extension/make_icons.py` redraws the icons from `extension/palm.png`.

## Principles

- **Local-first.** No screen or document leaves the machine unless the user explicitly chooses a cloud mode.
- **Read-only toward the portal.** No installs on portals, no APIs, no modification. It reads what is already on the resident's screen.
- **Source-backed.** Every answer shows where it came from (official guide, or the user's own document) and says when it cannot verify something.
- **User in control.** Screen access is visible and pausable; screenshots are not stored by default; no automatic submission, payment, or CAPTCHA handling.
- **Open guide format.** Any entity can later publish its own form guide in the same open format.

## Architecture

| Layer | Role | Candidate |
|---|---|---|
| Desktop UI | Floating panel: form picker, card, approvals, settings | Tauri 2 (Rust) + React + TypeScript: a notch panel and a click-through ring overlay |
| Screen understanding | Accessibility tree → screenshot → OCR fallback; active-window info | Screenshots of every monitor, Indra OCR, then box finding on any side of a label (accessibility tree not used yet) |
| Browser extension | Read and fill a page's real fields in Chrome and Edge | `extension/`, talking to the sidecar over a loopback bridge on `127.0.0.1:8765` |
| Local AI | Explain fields, pick values, cite sources; replaceable model | llama.cpp |
| Public knowledge | Form guides: documents, fees, steps, field explanations, source URL, last-verified date | One JSON per form in `guides/` |
| Private vault | User-approved documents and confirmed profile values, with source | Documents folder + SQLite, plus the values the person told Sahl for unknown boxes; separate from the guides |
| Action | Show, copy, or fill after confirmation | `pynput` mouse and keyboard; checkboxes are never ticked |

The public catalogue and the private vault are separate stores so a passport scan can never end up in the shared catalogue. Exposing both through local MCP tools is an idea, not built.

## Roadmap

1. **Knowledge layer** – done for coverage: 409 guides from TAMM, ICP, MOHRE, MOHAP, DHA, KHDA, DLD and more carry requirements, fees and timing (dated 2026-11-02/03); 6 guides carry field labels. Still to cover: u.ae, GDRFA, Dubai Police, DEWA, RTA and others.
2. **Screen awareness** – done on drawn layouts and a test portal; still to prove on real portals.
3. **Vault** – done: passport MRZ, Emirates ID and printed text, several people, local AI only when check digits cannot settle a page.
4. **Guided completion** – done: text boxes, split dates, dropdowns and radio buttons from verified values, and boxes no guide knows from what the person told Sahl. Pop-up calendars, unknown dropdowns and unknown date boxes are not handled yet.
5. **Per-OS packaging** – macOS `.dmg` builds (unsigned); the Windows `.exe` builds in CI and runs (unsigned).

Out of scope for the first milestone: autonomous submission, payment flows, CAPTCHA, unrestricted file access.

## What is real and what is not

| Part | Status | Note |
|---|---|---|
| Screen reading, ring and fill | Built (macOS) | Box finding on drawn layouts passes about 96% (`sidecar/tests`); not yet measured on real portal screenshots. |
| Browser extension | Built (Chrome, Edge) | Loaded unpacked from `extension/`; tried on test forms, not yet on live UAE portals. |
| Unknown boxes | Built | Asked once, remembered per person, reused under another name only after a yes. Never passwords, PINs, one-time codes or a card's security code. |
| Indra OCR | In use | `indra-ocr` (Datalab), local CPU/ONNX, ~76 MB weights, 80+ languages. Published Arabic 69.2 and Malayalam 65.0 on the maker's benchmark; handwriting weak. |
| Local AI | Built | llama.cpp's `llama-server` ships inside the app and runs Qwen3-VL (documents) and Qwen3 (form picker, and "is Workplace the same as Company?" suggestions). Models download from Hugging Face after the person agrees, size shown first. |
| Form guides | 409 | Mostly requirements only (`fields: []`); 6 have field labels. Reuse terms unchecked per source; 94 TAMM guides not re-dated. |
| Form picker | Measured | Dev 40/40, held out 15/15, fresh 13/15 (`sidecar/evals/picker.py`). |
| Translations | Unchecked | Not yet reviewed by native speakers. |
| Windows | Running | Used by a collaborator on Windows; mixed-DPI screens and filling on live portals still to check. |
| Time saved | Not measured | Planned 10-person timed test, with and without. |
| Sample documents | Invented | No real passport or Emirates ID is ever used in demos. |

## Known weak spots

- Filling by mouse and keyboard is fragile (date pickers, dropdowns, layout changes).
- Filled values can hide mistakes, hence per-section confirmation.
- iPhone does not allow reading other apps' screens, so this is a computer app.
- The macOS `.dmg` is not signed or notarized, so the first open is right-click → Open.
- Indra's weights are under a modified OpenRAIL-M licence (no competing with Datalab's API); check it fits Sahl's Apache-2.0 distribution before bundling.
- Government content licences vary; the UAE Federal Open Data License needs attribution and no misleading representation. Keep a per-source licence and attribution record.

## Building the installers

The macOS `.dmg` and the Windows `.exe` are built by `.github/workflows/release.yml` (push a tag like `v0.1.0`, or run it by hand). To build the `.dmg` on a Mac yourself:

```bash
cd sidecar && .venv/bin/pip install -r requirements-build.txt && .venv/bin/python build.py
cd ../app && npm run tauri build -- --bundles dmg
```

`build.py` packs the sidecar into a folder (not one file, which unpacks on every launch and takes about 40 seconds to start) and fetches llama.cpp's `llama-server`; Tauri bundles both as resources, beside the guides. The installers are not signed yet, so macOS and Windows warn on first open. The AI models download on first launch, after the person agrees.

## Licence

Code: Apache License 2.0 (see [LICENSE](LICENSE)). The form-guide catalogue, models, and dependencies carry their own terms and will be tracked separately. Sahl is not an official government service and uses no government seals.
