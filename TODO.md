# TODO

Active log. Add tasks when you start them; move them to Done with the PR link when merged. One task = one PR (see [AGENTS.md](AGENTS.md)).

## In progress

- [ ] Notch panel: black island that opens on hover, palm while starting, "What form?" box picked by a small local model (`feat/notch-panel`)
- [ ] Try Sahl on real UAE portals and log which boxes it finds, misses or rings wrong

## Next

- [ ] **Windows version**: see the table in AGENTS.md (sidecar path, vault folder, Recycle Bin, DPI, overlay)
- [ ] Split names for passports without readable `<<<` lines (only the MRZ says where the surname ends today)
- [ ] More label variants in guides, from real portal results
- [ ] Inputs with the label on the left, or without borders (ring lands wrong today)
- [ ] Dropdowns and date pickers (show-only today)
- [ ] Start Ollama automatically, or tell the user clearly when it isn't running
- [ ] Packaging: bundle the sidecar (PyInstaller) so no dev setup is needed
- [ ] Read each document page once instead of twice (ID check and reading both OCR it)
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
