# TODO

Active log. Add tasks when you start them; move them to Done with the PR link when merged. One task = one PR (see [AGENTS.md](AGENTS.md)).

## In progress

- [ ] Browser extension store-ready (`feat/extension-store-ready`): square icons, bridge on the first free port of 8765-8774 with the extension searching the range and checking an HMAC proof of the token, frames read, page address without query, install text no longer says "Load unpacked", packaging script and node tests. Still needed for the listing: hosted privacy policy, screenshots, listing text, the app available to download
- [ ] UI polish (`feat/ui-polish`): the extension popup fits Chrome's 600px limit (the list scrolls, the note and Fill button stay in a dock), one group each for "Ready to fill" and "New boxes" (the headers repeated before), a count on the Fill button, round checks, a loading skeleton; the island's first-run steps get their spacing back (a stray `}` in panel.css dropped the `.setup` rules), one corner size for controls (12px) and one for cards (16px), lit card edges, quieter sentence-case labels, a press state on buttons
- [ ] Design audit ([#33](https://github.com/gabriel-gy-tan/sahl/pull/33), `fix/design-audit`): focus rings, one type scale, 32 pt targets, one error card, reduced motion, step dots. Still to do: a label for the "Things you told me" count (ar/ur/ml strings with plurals), arrow keys in the radio groups, a "Try again" button on errors, and a look at the extension popup and the ring label on real portals
- [ ] Security audit fixes (`fix/security-audit-findings`): the extension pairing code works once, lasts 10 minutes and is burned by 5 wrong guesses; the never-ask rule catches joined (mPIN, TOTP), code-box (SMS code, 6-digit code) and Arabic password/PIN/OTP labels; a newline or tab in a value is typed as a space, never Enter or Tab
- [ ] UI overhaul, phase 1 of 5: first-run setup in the island: add documents, allow Screen Recording and Accessibility before the first read (`GET`/`POST /permissions`), then pick how Sahl helps; "Confirm, then fill" is now the default (`feat/first-run-onboarding`). Next phases: island stays open while working and scrolls, a first-person copy pass, extension look and languages matching the app, ⌥Space handing browser forms to the paired extension
- [ ] UI overhaul, phase 2 of 5: the island stays open while a form is in progress (Hide for now / Esc tucks it, and the folded island shows how far along you are), scrolls instead of running off the screen, Esc steps back one level; settings: Display merged into General, "Browser extension", "Privacy & reports" (`feat/island-shell`)
- [ ] Documents page (`feat/documents-page`): each person's documents with what Sahl read from each, a status per value (checked / check this / changed by you), edit in place (kept apart from the reading, so a re-read never undoes it; counts as verified), undo back to what was read, remove one document (Sahl's own copy goes to the Trash; a file in a folder you chose stays put and is no longer read), and what you told Sahl per person, edit or remove. Reached from Settings → Documents and "My documents" on the home screen
- [ ] UI overhaul, phase 3 of 5 (`feat/copy-pass`): Sahl speaks as "I" everywhere, in en/ar/ur/ml; no ports, check digits or raw sidecar messages on screen (the common ones are translated, the rest say "something went wrong" and go to the console); Windows gets its own screen and typing errors; the 8 browser-extension strings are translated
- [ ] UI overhaul, phase 4 of 5 (`feat/extension-parity`): the extension follows the panel's language (en/ar/ur/ml, right to left for Arabic and Urdu; strings in `extension/i18n.json`, language from the bridge's `/health`), speaks as "I", uses the app's black, teal and amber and the palm mark; page marks in the same colours; no match percentages or raw errors; "No, it's different" is remembered; Settings → Browser extension says whether a browser is paired and can Unpair (a new token locks every browser out)
- [ ] Browser extension: ring every safe box no guide knows, fill what the person told Sahl, ask for the rest in the popup; card details allowed, never passwords, PINs, one-time codes or the card security code (`feat/extension-taught-boxes`). Unknown date boxes (day/month/year together, or `type=date`) are not asked about yet
- [ ] Browser extension taught-field UI (`feat/extension-taught-ui`): one quiet ring per field or group, labels only on hover/focus and numbered amber badges for boxes Sahl doesn't know; the popup groups "Ready to fill" and "New fields" and collapses each tell form
- [ ] Teach Sahl unknown boxes: a box no guide knows gets "we don't know X, tell me so I can always remember it"; the answer is stored per person and reused under another name for the same detail (Company / Workplace) after a yes to the local model's suggestion; passwords, PINs and one-time codes never (`feat/teach-unknown-boxes`). Tested on drawn forms; not yet tried on a real portal. After a fill or skip the next prompt comes straight from the sidecar's state with no new screen read, and the local model's name suggestions run in the background (the panel still pauses ~0.65 s to fold before typing, and fill.py waits ~1 s for clicks to land). Scrolling after a read is handled when you tap Yes, fill it: Sahl finds the label again and moves the boxes, or stops without clicking if it can't (the ring does not yet follow a scroll between taps). Still to do: dropdowns and date boxes that are unknown, and a form with no known label at all
- [ ] Try Sahl on real UAE portals and log which boxes it finds, misses or rings wrong. Labels for the ICP Emirates ID renewal guide were copied from the signed-in form and not yet tried on the live page

## Next

- [ ] Security leads still to check on a real machine: the extension fills off-screen or clipped boxes; llama-server's port is freed before it binds and any `/health` answer is trusted; the llama-server API key sits in argv (visible to other users via `ps`); library images open in any Pillow format in-process (EPS → Ghostscript), not just PNG/JPEG; `build.py` runs the llama.cpp release with no pinned hash
- [ ] Packaged macOS app (`.dmg` built and launched on an M-series Mac; first launch ~40 s while macOS scans the files, later ones ~1 s; signing should shorten the first). Still untried: Screen Recording / Accessibility prompts, a full first-launch model download, a Mac with nothing installed, Intel Macs. The `.dmg` is not signed or notarized (needs an Apple Developer ID), so the first open is right-click → Open
- [ ] Sign and notarise the installers (Apple Developer ID, Windows certificate); Intel Mac build
- [ ] Windows: the `.exe` is built in CI only (`.github/workflows/release.yml`), never run on Windows; run the app and check the overlay, the shortcut and filling in Edge/Chrome, and a picker that takes files and folders together
- [ ] Windows: move the notch panel to the monitor the pointer reaches the top of (macOS does this already)
- [ ] Inputs with the label on the left, or without borders (ring may land wrong); check on real portals
- [ ] Dropdown dates on a real UAE portal (checked only on RoboForm's test form); searchable dropdowns and pop-up calendars are untested
- [ ] Box finding on real portals: drawn layouts pass ~96% (`tests/test_box_layouts.py`, `tests/test_choice_layouts.py`); weakest are tall boxes and boxes above their label (~87-90%). Check against real portal screenshots
- [ ] Form picker misses with llama.cpp: "title deed" offers verification, not the ownership certificate; "register a car in ras al khaimah" is offered an unrelated form
- [ ] Not reachable from the build machine, still to cover: u.ae, GDRFA, Dubai Police, DEWA, RTA, Dubai Courts, MOI, Customs; embassies, free zones, utilities and telecom, transport, finance, Sharjah and the northern emirates
- [ ] 94 TAMM guides not re-dated; fees elsewhere dated 2026-11-02/03
- [ ] Fill `fields` for the busiest services from "Help improve Sahl" reports on real portals (labels sit behind UAE PASS sign-in)
- [ ] More label variants in guides, from real portal results
- [ ] Split names for passports without readable `<<<` lines (only the MRZ says where the surname ends today)
- [ ] Native speakers to check the greeting, form-picker and guide strings (ar/ur/ml)

## Done

- [x] README and logo
- [x] First vertical slice: Tauri panel + click-through ring overlay, Python sidecar, OCR, label matching, fill with a landed check
- [x] Multi-monitor reading; overlay moves to the form's screen
- [x] Passport MRZ and Emirates ID parsing with check digits and OCR repairs
- [x] PDFs (rendered in a child process so a crash can't take Sahl down)
- [x] Folder drag-and-drop; Sahl documents folder that caches readings and syncs every 30 s
- [x] Local AI (Qwen3-VL 8B instruct, run by llama.cpp), only when check digits can't settle a page; retried when it fails
- [x] Several people in one folder ("Filling for"), matched by birth date and first name
- [x] Guides: medical fitness booking, and "any form" common details
- [x] Panel in English, Arabic, Urdu and Malayalam (RTL for Arabic and Urdu)
- [x] Sidecar restarts itself if it exits
- [x] Separate Surname / Given names boxes (DS-160), split by the passport MRZ
- [x] Read documents faster: one OCR per page, digital PDFs without OCR, one PDF helper (https://github.com/gabriel-gy-tan/sahl/pull/3)
- [x] Notch panel: black island that opens on hover, palm while starting, "What form?" chat with a small local model (https://github.com/gabriel-gy-tan/sahl/pull/4)
- [x] Windows port: sidecar path, `%APPDATA%\Sahl`, Recycle Bin, per-monitor DPI, UTF-8 files, `Ctrl+Alt+Space` (https://github.com/gabriel-gy-tan/sahl/pull/5)
- [x] UAE form matching: label normalising, EN/AR aliases, underlined and side-by-side boxes, Read again after a finished form, the island folds while typing (https://github.com/gabriel-gy-tan/sahl/pull/6)
- [x] Documents and settings: + in the text box, file and folder picker, documents in the conversation, settings pages, AI model size, opt-in "Help improve Sahl" reports (https://github.com/gabriel-gy-tan/sahl/pull/7)
- [x] Learn forms from portals: unrecognised labels in reports, official `requirements` in guides, Emirates ID and residence permit guides (https://github.com/gabriel-gy-tan/sahl/pull/8)
- [x] Dropdown dates: day, month and year boxes picked one by one (https://github.com/gabriel-gy-tan/sahl/pull/10)
- [x] Chat answers "what documents do I have?" from the vault (https://github.com/gabriel-gy-tan/sahl/pull/11)
- [x] The app downloads and runs its own AI: resumable, hash-checked, size shown first (https://github.com/gabriel-gy-tan/sahl/pull/12)
- [x] 409 UAE service guides from TAMM, ICP, MOHRE, MOHAP, DHA, KHDA, DLD, ADEK, DOH and more; the form picker ranks by rare words and answers questions (https://github.com/gabriel-gy-tan/sahl/pull/13)
- [x] Packaging: frozen sidecar and llama.cpp inside the `.dmg`; Windows scripts written (https://github.com/gabriel-gy-tan/sahl/pull/14)
- [x] Skip boxes the portal already filled; box finding on any side and shape; dropdowns, radio buttons and checkboxes (never ticked); picker evals (https://github.com/gabriel-gy-tan/sahl/pull/15)
- [x] Browser extension: read a page's real fields through a loopback bridge, find labels in table cells and beside their input wrapper, group RoboForm-style numbered date selects, treat date placeholders as empty, offer an opt-in replace for boxes that already hold a value, type text through the page's own input path and retry if it drops the value, replace stale content scripts after an extension reload, rank the guide with the local AI only when the page resembles a guide (8 s cap), show a reading animation in the popup and page, ring exact DOM boxes and fill verified values without submitting ([#16](https://github.com/gabriel-gy-tan/sahl/pull/16))
- [x] Run the local AI on llama.cpp instead of Ollama: `llama-server` ships inside the app, models download from Hugging Face once the person agrees ([#20](https://github.com/gabriel-gy-tan/sahl/pull/20)). Windows still to try
- [x] Browser bridge: start after a quick restart, and wait for port 8765 instead of giving up when it is busy ([#21](https://github.com/gabriel-gy-tan/sahl/pull/21))
