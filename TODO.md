# TODO

Active log. Add tasks when you start them; move them to Done with the PR link when merged. One task = one PR (see [AGENTS.md](AGENTS.md)).

## In progress

- [ ] Dropdown dates (issue #9): day, month and year boxes found as a row and picked one by one, boxes sized from their own borders (`fix/dropdown-date-parts`). Checked on RoboForm's test form; still to check on a real UAE portal
- [ ] Start Ollama and download the models from inside the app, no Terminal (`feat/ollama-autostart`). Bundling Ollama itself is still open
- [ ] Chat answers "what documents do I have?" from the vault's types and counts (`feat/chat-knows-documents`)
- [ ] Documents and settings: + in the text box, a picker for files and folders, "Read Priya's passport" in the conversation, a nudge for a missing document, what Sahl holds per person, settings in pages with icons, AI model size, opt-in "Help improve Sahl" reports (`feat/documents-flow`)
- [ ] Try Sahl on real UAE portals and log which boxes it finds, misses or rings wrong

- [ ] Learn forms from portals: report lists unrecognised labels beside input boxes; guides carry official `requirements` (fees, documents, timing) that the form-picker chat reads (Emirates ID renewal/replacement, residence permit new/renewal from icp.gov.ae) (`feat/documents-flow`)
- [ ] More UAE service guides (`uae-form-data`): 409 guides from TAMM, ICP, MOHRE, MOHAP, DHA, KHDA, DLD, ADEK, DOH, ADDED, DMT, FTA, MOFA, MOE, MOJ, EHS and more, all `fields: []` except 5 forms with printed labels; the form picker ranks by rare words, answers questions, and has a search box; the form screen shows what a service needs. Fees dated 2026-11-02/03; 94 TAMM guides not re-dated; translations unreviewed

## Next

- [ ] Not reachable from the build machine, still to cover: u.ae, GDRFA, Dubai Police, DEWA, RTA, Dubai Courts, MOI, Customs; embassies, free zones, utilities and telecom, transport, finance, Sharjah and the northern emirates
- [ ] Fill `fields` for the busiest services from "Help improve Sahl" reports on real portals (labels sit behind UAE PASS sign-in)

- [ ] Windows: run the app and check the overlay, the shortcut and filling in Edge/Chrome, and a picker that takes files and folders together
- [ ] Platform-specific screen/typing error copy (the panel currently names macOS settings on Windows too)
- [ ] Split names for passports without readable `<<<` lines (only the MRZ says where the surname ends today)
- [ ] More label variants in guides, from real portal results
- [ ] Inputs with the label on the left, or without borders (ring lands wrong today)
- [ ] Other dropdowns and date pickers (show-only today)
- [ ] Packaging: bundle the sidecar (PyInstaller) so no dev setup is needed
- [ ] More guides (Emirates ID renewal, …) with an `about` line each, so the form picker has more to find
- [ ] Windows: move the notch panel to the monitor the pointer reaches the top of (macOS does this already)
- [ ] Native speakers to check the new greeting and form-picker strings (ar/ur/ml)

## Done

- [x] README and logo
- [x] First vertical slice: Tauri panel + click-through ring overlay, Python sidecar, OCR, label matching, fill with a landed check
- [x] Multi-monitor reading; overlay moves to the form's screen
- [x] Passport MRZ and Emirates ID parsing with check digits and OCR repairs
- [x] PDFs (rendered in a child process so a crash can't take Sahl down)
- [x] Folder drag-and-drop; Sahl documents folder that caches readings and syncs every 30 s
- [x] Local AI (Qwen3-VL 8B instruct via Ollama), only when check digits can't settle a page; retried when it fails
- [x] Several people in one folder ("Filling for"), matched by birth date and first name
- [x] Guides: medical fitness booking, and "any form" common details
- [x] Panel in English, Arabic, Urdu and Malayalam (RTL for Arabic and Urdu)
- [x] Sidecar restarts itself if it exits
- [x] Separate Surname / Given names boxes (DS-160), split by the passport MRZ
- [x] Read documents faster: one OCR per page, digital PDFs without OCR, one PDF helper (https://github.com/gabriel-gy-tan/sahl/pull/3)
- [x] Notch panel: black island that opens on hover, palm while starting, "What form?" chat with a small local model (https://github.com/gabriel-gy-tan/sahl/pull/4)
- [x] Windows port: sidecar path, `%APPDATA%\Sahl`, Recycle Bin, per-monitor DPI, UTF-8 files, `Ctrl+Alt+Space` (https://github.com/gabriel-gy-tan/sahl/pull/5)
- [x] UAE form matching: label normalising, EN/AR aliases, underlined and side-by-side boxes, Read again after a finished form, the island folds while typing (https://github.com/gabriel-gy-tan/sahl/pull/6)
