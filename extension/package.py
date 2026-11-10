"""Zip the extension for the Chrome Web Store: python3 extension/package.py  ->  dist/sahl-extension-<version>.zip
Only the files the extension runs are included (no make_icons.py, no tests)."""
import json, pathlib, zipfile

here = pathlib.Path(__file__).parent
version = json.loads((here / "manifest.json").read_text())["version"]
files = ["manifest.json", "background.js", "content.js", "popup.html", "popup.css", "popup.js", "i18n.json", "palm.png",
         *sorted(f"icons/{p.name}" for p in (here / "icons").glob("icon*.png"))]
out = here.parent / "dist" / f"sahl-extension-{version}.zip"
out.parent.mkdir(exist_ok=True)
with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
    for f in files:
        z.write(here / f, f)
print(out, len(files), "files")
