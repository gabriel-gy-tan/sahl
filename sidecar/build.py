"""Packs the sidecar into one executable that Tauri bundles beside the app.

Run from sidecar/ with the venv active:  python build.py
Writes the folder ../app/src-tauri/sidecar/ (a one-file build would unpack ~260 MB on every launch and
macOS would scan it each time, which took Sahl about 40 seconds to start)
"""
import shutil
import subprocess
import sys
from pathlib import Path

here = Path(__file__).parent
# build outside the repo: synced folders (OneDrive) make PyInstaller's many small writes crawl
work = Path.home() / ".cache" / "sahl-sidecar-build"
subprocess.run(
    [sys.executable, "-m", "PyInstaller", "--noconfirm", "--onedir", "--name", "sahl-sidecar", "--paths", str(here), "--exclude-module", "pytest",
     "--collect-all", "indra_ocr", "--collect-all", "pypdfium2",
     "--distpath", str(work / "dist"), "--workpath", str(work / "build"), "--specpath", str(work),
     str(here / "run.py")],
    check=True,
)
out = here.parent / "app" / "src-tauri" / "sidecar"
shutil.rmtree(out, ignore_errors=True)
shutil.copytree(work / "dist" / "sahl-sidecar", out)
print("wrote", out)
