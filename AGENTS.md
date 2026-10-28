# AGENTS.md

Rules and context for any coding agent (and human) working on Sahl.

## Rules

1. **Never reference yourself.** No agent names, model names, "Generated with", `Co-Authored-By` lines or tool links in any commit message, PR title, PR body, code comment or file. Commits are authored as the human you are working for.
2. **One change, one PR.** Every new feature, research spike or bug fix gets its own branch and its own PR. Don't bundle unrelated work. Branch names: `feat/…`, `fix/…`, `research/…`, `docs/…`.
3. **Keep [TODO.md](TODO.md) current.** Add a task when you start it, move it to Done (with the PR link) when it merges.
4. **Never touch real personal data.** Don't print, log, commit or screenshot values from someone's real documents. Inspect the vault only by counts and types. Test data is invented (`demo/make_samples.py`).
5. **Tests stay in tmp.** Tests set `SAHL_HOME` and `SAHL_LIBRARY` to temp folders; never point them at a real vault or `~/Documents/Sahl`.
6. **Sahl never logs in, pays or submits.** No code path presses Enter, clicks Submit, or types into password or payment fields.
7. **Nothing leaves the computer.** OCR and AI run locally. No network calls except to the local sidecar and local Ollama.
8. Run `cd sidecar && .venv/bin/pytest -q` (Windows: `.venv\Scripts\pytest -q`) before opening a PR.

## How it works

- **`app/`**: Tauri 2 (Rust) + React/TS. Two windows: `panel` (the card UI) and `overlay` (full-screen, click-through, draws the ring). ⌥/Alt+Space triggers a read. Rust starts and supervises the Python sidecar with a random token and port.
- **`sidecar/`**: Python 3.12, FastAPI on 127.0.0.1. Every request needs the `x-sahl-token` header.
  - `ocr.py`: screenshots of every monitor (`mss`) and Indra OCR. PDFs render in a child process because pdfium can crash.
  - `match.py`: matches OCR lines to a guide's label aliases (rapidfuzz) and finds the input box below.
  - `vault.py`: reads documents (passport MRZ, Emirates ID, printed text, then local AI only if needed), groups them into people, stores readings in SQLite. Only check-digit- or page-confirmed values are "verified", and only verified values are typed.
  - `ai.py`: local vision model via Ollama (`qwen3-vl:8b-instruct`). Its answers are proposals, never trusted alone.
  - `library.py`: the Sahl documents folder, synced every 30 s.
  - `fill.py`: clicks and types with `pynput`.
- **`guides/`**: one JSON per form: field aliases (EN/AR), which vault key fills it, help text in en/ar/ur/ml.
- **`demo/`**: an invented portal page and invented sample documents.

## Windows port

A collaborator is building the Windows version. Known macOS-only spots:

| Where | macOS today | Windows needs |
|---|---|---|
| `app/src-tauri/src/lib.rs` | starts `sidecar/.venv/bin/python` | `sidecar\.venv\Scripts\python.exe` |
| `app/src-tauri/src/lib.rs` | `apply_vibrancy` (behind `cfg(target_os = "macos")`) | optional `apply_mica` / `apply_acrylic` from `window-vibrancy` |
| `sidecar/sahl/vault.py` `home()` | `~/Library/Application Support/Sahl` | `%APPDATA%\Sahl` |
| `sidecar/sahl/library.py` `forget()` | Finder via `osascript` to move files to Trash | move to Recycle Bin (e.g. `send2trash`, or the shell API) |
| `sidecar/sahl/fill.py` | already uses Ctrl instead of Cmd off macOS | check that the double click and timings work in Edge/Chrome |
| `sidecar/sahl/ocr.py` | `mss` monitor coordinates in points | check DPI scaling: screen points vs physical pixels |
| Overlay | `macOSPrivateApi` for transparency | check click-through and transparency on Windows |

Keep platform branches small (`sys.platform`, `#[cfg(...)]`) and in the file that owns the behaviour. Don't fork whole modules per platform.
