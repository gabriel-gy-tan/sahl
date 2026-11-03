"""Packs the sidecar into one executable that Tauri bundles beside the app.

Run from sidecar/ with the venv active:  python build.py
Writes ../app/src-tauri/binaries/sahl-sidecar-<rust target triple>[.exe]
"""
import re
import shutil
import subprocess
import sys
from pathlib import Path

here = Path(__file__).parent
# build outside the repo: synced folders (OneDrive) make PyInstaller's many small writes crawl
work = Path.home() / ".cache" / "sahl-sidecar-build"
triple = re.search(r"host: (\S+)", subprocess.run(["rustc", "-vV"], capture_output=True, text=True, check=True).stdout)[1]
subprocess.run(
    [sys.executable, "-m", "PyInstaller", "--noconfirm", "--onefile", "--name", "sahl-sidecar", "--paths", str(here), "--exclude-module", "pytest",
     "--collect-all", "indra_ocr", "--collect-all", "pypdfium2",
     "--distpath", str(work / "dist"), "--workpath", str(work / "build"), "--specpath", str(work),
     str(here / "run.py")],
    check=True,
)
exe = ".exe" if sys.platform == "win32" else ""
out = here.parent / "app" / "src-tauri" / "binaries"
out.mkdir(exist_ok=True)
shutil.copy(work / "dist" / f"sahl-sidecar{exe}", out / f"sahl-sidecar-{triple}{exe}")
print("wrote", out / f"sahl-sidecar-{triple}{exe}")
