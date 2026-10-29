"""Screen capture and Indra OCR. Everything stays on this computer."""
import atexit
import os
import sys

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


DPI = 200  # PDF pages render at this; text-layer boxes are given in the same pixels
_POOL = None


def _in_child(fn, *args):
    """Runs fn in Sahl's one PDF helper process. pdfium can crash or hang on a malformed file, and that
    must take down only the helper (raising BrokenProcessPool or TimeoutError here), never Sahl.
    The helper stays up between documents, so each PDF doesn't pay for a new Python process.
    """
    global _POOL
    import multiprocessing as mp
    from concurrent.futures import ProcessPoolExecutor
    from concurrent.futures.process import BrokenProcessPool
    if _POOL is None:
        _POOL = ProcessPoolExecutor(1, mp_context=mp.get_context("spawn"))
        atexit.register(_POOL.shutdown)  # stop the helper before the interpreter tears down
    try:
        return _POOL.submit(fn, *args).result(timeout=180)
    except (BrokenProcessPool, TimeoutError):
        pool, _POOL = _POOL, None  # the next call starts a fresh helper
        for p in list((pool._processes or {}).values()):
            p.kill()  # a hung pdfium must not outlive its timeout
        pool.shutdown(wait=False, cancel_futures=True)
        raise


def _pdf_text(path: str) -> list[list | None]:
    """Per page: the text layer as OCR-style lines for a digital page, or None for a scanned one."""
    import pypdfium2 as pdfium
    import pypdfium2.raw as c
    doc = pdfium.PdfDocument(path)
    try:
        out, k = [], DPI / 72
        for page in doc:
            w, h = page.get_size()
            pictured = sum((r - l) * (t - b) for o in page.get_objects(filter=(c.FPDF_PAGEOBJ_IMAGE,))
                           for l, b, r, t in [o.get_bounds()])
            tp = page.get_textpage()
            lines = []
            for i in range(tp.count_rects()):
                l, b, r, t = tp.get_rect(i)
                if s := tp.get_text_bounded(l, b, r, t).strip():
                    lines.append((s, (l * k, (h - t) * k, r * k, (h - b) * k)))
            # a scan (one big picture, maybe with a scanner's hidden OCR layer) or an empty page goes to Indra
            out.append(None if pictured > 0.5 * w * h or sum(len(s) for s, _ in lines) < 20 else lines)
        return out
    finally:
        doc.close()


def _pdf_render(path: str, i: int) -> np.ndarray:
    import pypdfium2 as pdfium
    doc = pdfium.PdfDocument(path)
    try:
        arr = doc[i].render(scale=DPI / 72, grayscale=True).to_numpy()
        return np.ascontiguousarray(arr[..., 0] if arr.ndim == 3 else arr)
    finally:
        doc.close()


def pdf_text(path) -> list[list | None]:
    return _in_child(_pdf_text, str(path))


def pdf_page(path, i: int) -> np.ndarray:
    return _in_child(_pdf_render, str(path), i)


def image(path) -> np.ndarray:
    """A photo or scan, turned upright, in grayscale."""
    from PIL import Image, ImageOps
    return np.array(ImageOps.exif_transpose(Image.open(path)).convert("L"))


def _windows_scale(mon) -> float:
    """Pixels per point for the monitor at the centre of a Windows rectangle.

    mss reports Windows monitor rectangles in physical pixels. Tauri and the ring use points,
    so the physical rectangle is divided by this scale before it leaves screenshots().
    """
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    user32.MonitorFromPoint.argtypes = [wintypes.POINT, wintypes.DWORD]
    user32.MonitorFromPoint.restype = wintypes.HMONITOR
    point = wintypes.POINT(mon["left"] + mon["width"] // 2, mon["top"] + mon["height"] // 2)
    handle = user32.MonitorFromPoint(point, 2)  # MONITOR_DEFAULTTONEAREST
    dpi_x, dpi_y = wintypes.UINT(), wintypes.UINT()
    try:
        shcore = ctypes.windll.shcore
        shcore.GetDpiForMonitor.argtypes = [wintypes.HMONITOR, ctypes.c_int,
                                            ctypes.POINTER(wintypes.UINT), ctypes.POINTER(wintypes.UINT)]
        if shcore.GetDpiForMonitor(handle, 0, ctypes.byref(dpi_x), ctypes.byref(dpi_y)) == 0 and dpi_x.value:
            return dpi_x.value / 96.0
    except (AttributeError, OSError):
        pass
    dc = user32.GetDC(None)  # older Windows: system DPI is the best available answer
    try:
        dpi = ctypes.windll.gdi32.GetDeviceCaps(dc, 88)  # LOGPIXELSX
    finally:
        user32.ReleaseDC(None, dc)
    return dpi / 96.0 if dpi else 1.0


def screenshots() -> list[tuple[np.ndarray, float, tuple[float, float, float, float]]]:
    """One grayscale capture per monitor, with its pixels-per-point scale and its (left, top, width, height) in points."""
    import mss
    out = []
    with mss.mss() as sct:
        for mon in sct.monitors[1:]:
            shot = sct.grab(mon)
            rgb = np.frombuffer(shot.rgb, np.uint8).reshape(shot.height, shot.width, 3)
            gray = (rgb @ np.array([0.299, 0.587, 0.114])).astype(np.uint8)
            scale = _windows_scale(mon) if sys.platform == "win32" else shot.width / mon["width"]
            points = tuple(v / scale for v in (mon["left"], mon["top"], mon["width"], mon["height"]))
            out.append((gray, scale, points))
    return out
