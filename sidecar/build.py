"""Packs the sidecar into one executable that Tauri bundles beside the app, and fetches llama.cpp's llama-server.

Run from sidecar/ with the venv active:  python build.py
Writes the folder ../app/src-tauri/sidecar/ (a one-file build would unpack ~260 MB on every launch and
macOS would scan it each time, which took Sahl about 40 seconds to start) and ../app/src-tauri/llama/.
`python build.py llama` does only the second, which is all a checkout needs to run the local AI.
"""
import hashlib
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
import zipfile
from pathlib import Path

here = Path(__file__).parent
LLAMA = "b11922"  # the llama.cpp release to carry
RELEASE = f"https://github.com/ggml-org/llama.cpp/releases/download/{LLAMA}/llama-{LLAMA}-bin-"
# SHA-256 of each asset, from the release's own metadata (gh api repos/ggml-org/llama.cpp/releases/tags/<tag>, "digest"); change with LLAMA
DIGESTS = {
    "macos-arm64.tar.gz": "bb277dc73d1d452ce4d6269656b999a6e993e064e77775feda06cf695fd825f7",
    "win-vulkan-x64.zip": "add8916ff14512cfefede6f09c5d469af3adfbc7f483ae2b824bce855759a8fe",
}
# only llama-server and the libraries it loads (the Mac release also carries a dozen other tools)
MAC_FILES = ("llama-server", "LICENSE", "libllama-server-impl.dylib", "libllama-common.0.dylib", "libmtmd.0.dylib", "libllama.0.dylib",
             "libggml.0.dylib", "libggml-base.0.dylib", "libggml-cpu.0.dylib", "libggml-blas.0.dylib", "libggml-metal.0.dylib", "libggml-rpc.0.dylib")


def fetch(asset, dest):
    urllib.request.urlretrieve(RELEASE + asset, dest)
    got = hashlib.sha256(Path(dest).read_bytes()).hexdigest()
    if got != DIGESTS[asset]:
        sys.exit(f"{asset}: sha256 {got} is not the pinned {DIGESTS[asset]}")


def llama():
    out = here.parent / "app" / "src-tauri" / "llama"
    shutil.rmtree(out, ignore_errors=True)
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        if sys.platform == "win32":  # Vulkan runs on NVIDIA, AMD and Intel graphics, and falls back to the processor without one
            fetch("win-vulkan-x64.zip", tmp / "llama.zip")
            with zipfile.ZipFile(tmp / "llama.zip") as z:
                z.extractall(out)
        else:
            fetch("macos-arm64.tar.gz", tmp / "llama.tar.gz")
            with tarfile.open(tmp / "llama.tar.gz") as t:
                t.extractall(tmp, filter="tar")
            out.mkdir(parents=True)
            for name in MAC_FILES:
                shutil.copy2(tmp / f"llama-{LLAMA}" / name, out / name)
    subprocess.run([str(out / ("llama-server.exe" if sys.platform == "win32" else "llama-server")), "--version"], check=True)
    print("wrote", out)


llama()
if sys.argv[1:] == ["llama"]:
    sys.exit()

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
