<img src="assets/logo.png" alt="Sahl" width="240">

A free, open-source desktop helper that looks at the form on your screen, tells you in your language which box comes next, and helps you autofill and confirm the details. Fill a form in seconds to minutes. Everything runs on your own computer: completely local AI. The government side changes nothing.

> Status: concept. No code yet. This repo currently holds the plan.
> (Early planning documents call this project "Handover".)

## How it works

1. **See** – a screenshot of the form, taken on your computer.
2. **Read** – local OCR (Indra, already working in Yahmi) finds labels and boxes; a small local vision model handles layout and unlabelled boxes. Accessibility-tree data is used first when the app exposes it.
3. **Look up** – the form guide for the chosen service, then your own documents in the local vault.
4. **Show** – voice and card in your language: next box, the value, and a photo of where it came from.
5. **Stop** – never logs in, never handles UAE PASS or payment, never presses submit.

### Modes
- **Show only** – tells you what goes in the next box.
- **Confirm, then fill** – types the value after you tap yes. Every section is confirmed first, because filled values can hide mistakes.

### Languages of the guide
English, العربية, اردو, മലയാളം (first set; more later).

## Principles

- **Local-first.** No screen or document leaves the machine unless the user explicitly chooses a cloud mode.
- **Read-only toward the portal.** No installs on portals, no APIs, no modification. It reads what is already on the resident's screen.
- **Source-backed.** Every answer shows where it came from (official guide, or the user's own document) and says when it cannot verify something.
- **User in control.** Screen access is visible and pausable; screenshots are not stored by default; no automatic submission, payment, or CAPTCHA handling.
- **Open guide format.** Any entity can later publish its own form guide in the same open format.

## Architecture (planned)

| Layer | Role | Candidate |
|---|---|---|
| Desktop UI | Floating panel: form picker, card, approvals, settings | Tauri + React + TypeScript |
| Screen understanding | Accessibility tree → screenshot → OCR fallback; active-window info | Platform accessibility APIs; Indra OCR (Datalab); evaluate `open-computer-use` |
| Local AI | Explain fields, pick values, cite sources; replaceable model | Ollama / llama.cpp |
| Public knowledge | Form guides: documents, fees, steps, field explanations, source URL, last-verified date | SQLite + FTS |
| Private vault | User-approved documents and confirmed profile values, with source | Local files + SQLite; separate from public store |
| Action | Show, copy, or fill after confirmation | Mouse/keyboard (fragile: date pickers, dropdowns) |

The public catalogue and the private vault are separate stores so a passport scan can never end up in the shared catalogue. Optionally expose both through local MCP tools (`identify_current_form`, `get_service_requirements`, `explain_field`, `search_my_documents`, `get_profile_value`, `suggest_field_value`, `set_field_value`).

## Roadmap

1. **Knowledge layer** – 10–15 form guides from public service pages (first: residency medical fitness booking, MOHAP), each answer linked to its source.
2. **Screen awareness** – read-only identification of a supported form; manual selection when unsure.
3. **Vault** – import, index locally, save confirmed values with source; delete and privacy controls from day one.
4. **Guided completion** – per-field explanation and suggestions, then fill with confirmation.
5. **Per-OS packaging** – develop on one OS, validate permissions and integrations on each before claiming support.

Out of scope for the first milestone: autonomous submission, payment flows, CAPTCHA, unrestricted file access.

## What is real and what is not

| Part | Status | Note |
|---|---|---|
| Screen reading and card | Not built | Only a scripted concept so far. |
| Indra OCR | Reused from Yahmi | `indra-ocr` (Datalab), local CPU/ONNX, ~76 MB weights, 80+ languages; returns text lines with boxes, Tesseract as fallback. Yahmi's wrapper (`yahmi/extract.py`) is the starting point. Published Arabic 69.2 and Malayalam 65.0 on the maker's benchmark; handwriting weak. Not yet measured on forms or screenshots. |
| Form guides | Planned | One MOHAP page checked; target 15. Reuse terms unchecked per source. |
| Translations | Unchecked | Not yet reviewed by native speakers. |
| Time saved | Not measured | Planned 10-person timed test, with and without. |
| Sample documents | Invented | No real passport or Emirates ID is ever used in demos. |

## Known weak spots

- Filling by mouse and keyboard is fragile (date pickers, dropdowns, layout changes).
- Filled values can hide mistakes, hence per-section confirmation.
- iPhone does not allow reading other apps' screens, so this is a computer app.
- Indra's weights are under a modified OpenRAIL-M licence (no competing with Datalab's API); check it fits Sahl's Apache-2.0 distribution before bundling.
- Government content licences vary; the UAE Federal Open Data License needs attribution and no misleading representation. Keep a per-source licence and attribution record.

## Licence

Code: Apache License 2.0 (see [LICENSE](LICENSE)). The form-guide catalogue, models, and dependencies carry their own terms and will be tracked separately. Sahl is not an official government service and uses no government seals.
