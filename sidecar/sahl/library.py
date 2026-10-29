"""Sahl's documents folder: put documents here once, and Sahl keeps its readings up to date.

Default ~/Documents/Sahl; the choice is saved in SAHL_HOME/settings.json. Dropped files are copied
in, so the originals can be moved or deleted. Removing a file from the folder makes Sahl forget it.
"""
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

from . import vault

INTERVAL = 30  # seconds between background checks; a check of an unchanged folder only stats files


def _settings() -> Path:
    return vault.home() / "settings.json"


def default() -> Path:
    return Path(os.environ.get("SAHL_LIBRARY", Path.home() / "Documents/Sahl"))


def folder() -> Path:
    try:
        p = Path(json.loads(_settings().read_text(encoding="utf-8"))["library"])
    except (OSError, ValueError, KeyError):
        p = default()
    p.mkdir(parents=True, exist_ok=True)
    return p


def set_folder(p: Path):
    _settings().write_text(json.dumps({"library": str(p)}), encoding="utf-8")


def add(p: Path):
    """Copies a dropped file or folder into the documents folder, never overwriting a different file."""
    lib = folder()
    dest = lib / p.name
    if p.is_dir():
        shutil.copytree(p, dest, dirs_exist_ok=True)
        return
    n = 1
    while dest.exists() and dest.stat().st_size != p.stat().st_size:
        dest = lib / f"{p.stem} ({n}){p.suffix}"
        n += 1
    if not dest.exists():
        shutil.copy2(p, dest)


def watch():
    """Background thread: keeps the vault in line with the folder."""
    def loop():
        while True:
            try:
                vault.sync(folder())
            except Exception as e:  # never let a bad file stop the watcher
                print(f"library sync failed: {e}", flush=True)
            time.sleep(INTERVAL)
    threading.Thread(target=loop, daemon=True).start()


def forget():
    """Forgetting everything: Sahl's own folder goes to the Trash / Recycle Bin (recoverable); a folder
    you chose is never touched, Sahl just stops reading it."""
    lib = folder()
    if lib.resolve() != default().resolve():
        _settings().unlink(missing_ok=True)
        return
    for p in lib.iterdir():
        if p.name.startswith("."):
            continue
        if sys.platform == "darwin":
            subprocess.run(["osascript", "-e", 'on run argv\ntell application "Finder" to delete (POSIX file (item 1 of argv) as alias)\nend run',
                            str(p)], check=True, capture_output=True)
        else:
            from send2trash import send2trash
            send2trash(str(p))
