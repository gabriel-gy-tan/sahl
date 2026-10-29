"""Screen capture and Indra OCR. Everything stays on this computer."""
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
