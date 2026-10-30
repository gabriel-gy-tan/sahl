# AGENTS.md

Rules and context for any coding agent (and human) working on Sahl.

## Rules

1. **Never reference yourself.** No agent names, model names, "Generated with", `Co-Authored-By` lines or tool links in any commit message, PR title, PR body, code comment or file. Commits are authored as the human you are working for.
2. **One significant change, one PR.** A significant new feature, research spike or bug fix gets its own branch and its own PR. Small fixes and tweaks go on the PR already open for that work; don't open a PR for them. Branch names: `feat/…`, `fix/…`, `research/…`, `docs/…`.
3. **Keep [TODO.md](TODO.md) current.** Add a task when you start it, move it to Done (with the PR link) when it merges.
4. **Never touch real personal data.** Don't print, log, commit or screenshot values from someone's real documents. Inspect the vault only by counts and types. Test data is invented (`demo/make_samples.py`).
5. **Tests stay in tmp.** Tests set `SAHL_HOME` and `SAHL_LIBRARY` to temp folders; never point them at a real vault or `~/Documents/Sahl`.
6. **Sahl never logs in, pays or submits.** No code path presses Enter, clicks Submit, or types into password or payment fields.
7. **Nothing leaves the computer.** OCR and AI run locally. No network calls except to the local sidecar and local Ollama. The mic button hands over to the OS's own dictation (macOS Dictation, Windows Voice Typing), which runs on the device for supported languages; for other languages the OS may use its own servers, so keep it a button the person chooses to press.
8. Run `cd sidecar && .venv/bin/pytest -q` (Windows: `.venv\Scripts\pytest -q`) before opening a PR.

## How it works

- **`app/`**: Tauri 2 (Rust) + React/TS. Two windows: `panel` (a black island hanging from the notch, or a notch-sized tab at the top centre on screens without one; opens on hover) and `overlay` (full-screen, click-through, draws the ring). ⌥Space (Ctrl+Alt+Space on Windows, where Alt+Space is the window menu) triggers a read. Rust starts and supervises the Python sidecar with a random token and port.
- **`sidecar/`**: Python 3.12, FastAPI on 127.0.0.1. Every request needs the `x-sahl-token` header.
  - `ocr.py`: screenshots of every monitor (`mss`) and Indra OCR. PDFs render in a child process because pdfium can crash.
  - `match.py`: matches OCR lines to a guide's label aliases (rapidfuzz) and finds the input box below.
  - `vault.py`: reads documents (passport MRZ, Emirates ID, printed text, then local AI only if needed), groups them into people, stores readings in SQLite. Only check-digit- or page-confirmed values are "verified", and only verified values are typed.
  - `ai.py`: local vision model via Ollama (`qwen3-vl:8b-instruct` by default; `TIERS` holds the lighter and stronger pairs that Settings → General → AI model switches between). Its answers are proposals, never trusted alone.
  - `intent.py`: "what form do you want to work on?" A guide name typed plainly matches at once; otherwise a small local text model (`qwen3:1.7b` by default) picks a guide id, which is only kept if it is a real guide. The person still confirms it.
  - `library.py`: the Sahl documents folder, synced every 30 s.
  - `fill.py`: clicks and types with `pynput`.
  - `report.py`: "Help improve Sahl", off by default. When on, each form gets a report in `SAHL_HOME/reports`: the labels Sahl matched (only text that matched a guide alias), box positions as screen fractions, and which boxes it never saw or missed. Never a value. It sends nothing; the person copies or attaches a report themselves.
- **`guides/`**: one JSON per form: field aliases (EN/AR), which vault key fills it, help text in en/ar/ur/ml, and an `about` sentence (what the form is for) that the form picker reads.
- **`demo/`**: an invented portal page and invented sample documents.

## Windows port

The Windows code paths are in place and the app builds and launches; a live run on a portal and in Edge/Chrome, plus mixed-DPI checks, still need doing.

| Where | Windows behaviour |
|---|---|
| `app/src-tauri/src/lib.rs` | starts `sidecar\.venv\Scripts\python.exe` with `CREATE_NO_WINDOW` |
| `app/src-tauri/src/lib.rs` `find_notch`/`island` | no camera notch: a 190×8 tab at the top centre of the primary monitor; one `SetWindowPos` for size and position; still to check it stays above the taskbar and doesn't jump when it opens. Moving it to the screen whose top the pointer reaches is in TODO |
| `app/src-tauri/src/lib.rs` `SHORTCUT` | `Ctrl+Alt+Space`, because Alt+Space opens the window menu |
| `app/src-tauri/src/lib.rs` `dictate` | presses Win+H for Voice Typing |
| `app/src-tauri/src/lib.rs` `pick_documents` | returns `None`, so the panel opens the plugin's file picker: files only (on macOS one picker takes files and folders); folders can still be dropped on the island |
| `sidecar/sahl/vault.py` `home()` | `%APPDATA%\Sahl` (`SAHL_HOME` still overrides it) |
| `sidecar/sahl/library.py` `forget()` | `send2trash`, so files go to the Recycle Bin |
| `sidecar/sahl/ocr.py` | `mss` reports physical pixels; `screenshots()` divides each monitor by its DPI scale |
| `sidecar/sahl/server.py` | a fill converts screen points back to physical pixels before `pynput` clicks |
| `sidecar/sahl/fill.py` | uses Ctrl instead of Cmd off macOS; double-click timings still to check in Edge/Chrome |
| Overlay | transparent + click-through is requested through Tauri; still to check on Windows |

Keep platform branches small (`sys.platform`, `#[cfg(...)]`) and in the file that owns the behaviour. Don't fork whole modules per platform.
