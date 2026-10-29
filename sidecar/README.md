# Running Sahl (dev)

Needs Python 3.12, Node, and Rust (`rustup`). On Windows also install the MSVC build tools and WebView2,
which `npm run tauri dev` uses.

macOS / Linux:

```bash
python3.12 -m venv sidecar/.venv
sidecar/.venv/bin/pip install -r sidecar/requirements.txt
sidecar/.venv/bin/python demo/make_samples.py
cd sidecar && .venv/bin/pytest -q && cd ..
cd app && npm install && npm run tauri dev
```

Windows (PowerShell):

```powershell
python -m venv sidecar\.venv
sidecar\.venv\Scripts\python.exe -m pip install -r sidecar\requirements.txt
cd sidecar; .venv\Scripts\python.exe -m pytest -q; cd ..
cd app; npm install; npm run tauri dev
```

The demo samples are already in `demo/samples/`; run `demo/make_samples.py` only to redraw them (the fonts
differ per OS).

For reading documents, run the local AI (Ollama, offline after the download). Install it on macOS with
`brew install ollama`, or with the Windows installer, then:

```bash
ollama serve
ollama pull qwen3-vl:8b
ollama pull qwen3:1.7b
```

`qwen3-vl:8b` reads documents; the small `qwen3:1.7b` works out which form someone means from what they type ("the medical test for my visa"). Without it, Sahl only finds a form whose name is typed.

Without it Sahl still reads the machine-readable lines, but won't type names it can't confirm.

To see the tab Sahl draws on screens without a notch (external monitors, older Macs) on a notched Mac:

```bash
cd app && SAHL_NO_NOTCH=1 npm run tauri dev
```

The app starts the sidecar itself. The Indra OCR weights (about 76 MB) download on first run.

On macOS, allow **Screen Recording** (to read the form) and **Accessibility** (to type into it) for the
app or terminal that runs it, in System Settings → Privacy & Security. Windows needs no screen-capture
permission; if you run Sahl as administrator, the browser must run elevated too or Windows blocks the
typing.

PDF, PNG and JPG documents work; drop a folder to read them all. On Windows the vault lives in
`%APPDATA%\Sahl` and the default documents folder is `%USERPROFILE%\Documents\Sahl`.

Try it: open `demo/portal.html` in a browser, click **Add a document** and pick `demo/samples/passport.png`,
then `emirates_id.png`, and press **⌥ Space** (macOS) or **Ctrl+Alt+Space** (Windows).
