"""Screen capture and Indra OCR. Everything stays on this computer."""
import os

import numpy as np

_INDRA = None


def engine():
    """Indra (local, CPU, ONNX), loaded once. The weights download on first use and are not shipped with Sahl."""
    global _INDRA
    if _INDRA is None:
        import indra_ocr
        _INDRA = indra_ocr.load(threads=int(os.environ.get("SAHL_OCR_THREADS", "4")))
    return _INDRA


def lines(gray: np.ndarray) -> list[tuple[str, tuple[float, float, float, float]]]:
    """(text, (x0, y0, x1, y1)) for every line Indra finds, in image pixels."""
    return [(l.text, tuple(l.box)) for l in engine().ocr(gray).lines]


def _render_pdf(path: str) -> list[np.ndarray]:
    import indra_ocr
    return [gray for _, gray in indra_ocr.load_pages(path, dpi=200)]  # yields (page index, gray)


def pages(path, render=_render_pdf) -> list[np.ndarray]:
    """Grayscale pages of a document: every page of a PDF, or one photo turned upright.

    PDFs render in a throwaway child process: pdfium can crash on a malformed file, and that
    must take down only the child (raising BrokenProcessPool here), never Sahl.
    """
    if str(path).lower().endswith(".pdf"):
        import multiprocessing as mp
        from concurrent.futures import ProcessPoolExecutor
        with ProcessPoolExecutor(1, mp_context=mp.get_context("spawn")) as ex:
            return ex.submit(render, str(path)).result(timeout=180)
    from PIL import Image, ImageOps
    return [np.array(ImageOps.exif_transpose(Image.open(path)).convert("L"))]


def screenshots() -> list[tuple[np.ndarray, float, tuple[int, int, int, int]]]:
    """One grayscale capture per monitor, with its pixels-per-point scale and its (left, top, width, height) in points."""
    import mss
    out = []
    with mss.mss() as sct:
        for mon in sct.monitors[1:]:
            shot = sct.grab(mon)
            rgb = np.frombuffer(shot.rgb, np.uint8).reshape(shot.height, shot.width, 3)
            gray = (rgb @ np.array([0.299, 0.587, 0.114])).astype(np.uint8)
            out.append((gray, shot.width / mon["width"], (mon["left"], mon["top"], mon["width"], mon["height"])))
    return out
