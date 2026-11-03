"""Entry point for the packed sidecar (PyInstaller can't run a module inside a package)."""
import multiprocessing

from sahl.server import main

if __name__ == "__main__":
    multiprocessing.freeze_support()  # the PDF helper re-runs this executable
    main()
