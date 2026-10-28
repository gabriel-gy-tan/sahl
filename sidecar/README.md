# Running Sahl (dev)

Needs Python 3.12, Node, and Rust (`rustup`).

```bash
python3.12 -m venv sidecar/.venv
sidecar/.venv/bin/pip install -r sidecar/requirements.txt
sidecar/.venv/bin/python demo/make_samples.py
cd sidecar && .venv/bin/pytest -q && cd ..
cd app && npm install && npm run tauri dev
```

For reading documents, run the local AI (Ollama, offline after the download):

```bash
brew install ollama
ollama serve
```

```bash
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

On macOS, allow **Screen Recording** (to read the form) and **Accessibility** (to type into it) for the app or terminal that runs it, in System Settings → Privacy & Security.

PDF, PNG and JPG documents work; drop a folder to read them all.

Try it: open `demo/portal.html` in a browser, click **Add a document** and pick `demo/samples/passport.png`, then `emirates_id.png`, and press **⌥ Space**.
