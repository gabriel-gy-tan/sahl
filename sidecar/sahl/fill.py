"""Types one confirmed value into one box. Never presses Enter, so nothing gets submitted."""
import sys
import time


def _allowed():
    """macOS drops synthetic clicks and keys without a word unless the app has Accessibility permission."""
    if sys.platform != "darwin":
        return
    import ctypes
    lib = ctypes.cdll.LoadLibrary("/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices")
    lib.AXIsProcessTrusted.restype = ctypes.c_bool
    if not lib.AXIsProcessTrusted():
        raise PermissionError("Accessibility permission is off")


def type_into(box, value: str):
    _allowed()
    from pynput.keyboard import Controller as Keys, Key
    from pynput.mouse import Button, Controller as Mouse

    x0, y0, x1, y1 = box
    mouse, keys = Mouse(), Keys()
    mouse.position = ((x0 + x1) / 2, (y0 + y1) / 2)
    time.sleep(0.12)  # the cursor move can land late; clicking at once hits the previous position
    # the browser is in the background (you just tapped Sahl's panel), so the first click only brings
    # its window forward; the second puts the cursor in the box. pynput sends each as a single click.
    mouse.click(Button.left)
    time.sleep(0.3)
    mouse.click(Button.left)
    time.sleep(0.25)  # let the page move focus into the box
    mod = Key.cmd if sys.platform == "darwin" else Key.ctrl
    with keys.pressed(mod):
        keys.tap("a")  # replace whatever is already in the box
    time.sleep(0.1)  # a still-held modifier eats the first typed character
    for ch in value:
        keys.type(ch)
        time.sleep(0.01)


def pick_from(box, text: str):
    """Chooses an option in a dropdown by typing its start. Tab, never Enter, commits it."""
    _allowed()
    from pynput.keyboard import Controller as Keys, Key
    from pynput.mouse import Button, Controller as Mouse

    x0, y0, x1, y1 = box
    mouse, keys = Mouse(), Keys()
    mouse.position = ((x0 + x1) / 2, (y0 + y1) / 2)
    time.sleep(0.12)
    mouse.click(Button.left)  # brings a background browser forward, or opens the list if it was already in front
    time.sleep(0.3)
    keys.tap(Key.esc)  # closes the list either way, so the next click opens it exactly once
    time.sleep(0.15)
    mouse.click(Button.left)
    time.sleep(0.3)
    for ch in text:
        keys.type(ch)
        time.sleep(0.05)
    time.sleep(0.1)
    keys.tap(Key.tab)
    time.sleep(0.2)
