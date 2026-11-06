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

For reading documents, Sahl runs a local AI with llama.cpp's `llama-server` (offline after the download). The app carries its own;
from a checkout, run `.venv/bin/python build.py llama` (Apple Silicon and Windows; the dev app also needs that `app/src-tauri/llama` folder to exist),
or install it with `brew install llama.cpp`, or point `SAHL_LLAMA_SERVER` at any `llama-server`. Then start
Sahl: the first time, the panel asks whether to download the models (a Hugging Face download of 3 to 25 GB depending on the size, shown
first), resumes it if the connection drops, and checks each file's hash. They are kept in `models/` in Sahl's folder
(`SAHL_MODELS` moves them). The vision model reads documents; the small text model works out which form someone means from what they type
("the medical test for my visa"). Without it, Sahl only finds a form whose name is typed.

The **Standard** AI model in Settings → General is `Qwen3-VL-8B-Instruct` + `Qwen3-1.7B`. **Lighter** (`Qwen3-VL-4B-Instruct` + `Qwen3-0.6B`)
is faster on smaller computers; **Stronger** (`Qwen3-VL-30B-A3B-Instruct` + `Qwen3-8B`) needs about 32 GB of memory. `MODELS` in `sahl/ai.py` lists the files.

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

## Evals

The form picker against real phrasings, with the models downloaded (slow, so not in pytest):

```bash
cd sidecar && .venv/bin/python -m evals.picker all
```

Box, radio-button and checkbox finding are measured on random drawn forms inside pytest (`tests/test_box_layouts.py`, `tests/test_choice_layouts.py`).
