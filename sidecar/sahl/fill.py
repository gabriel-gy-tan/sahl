"""Types one confirmed value into one box. Never presses Enter, so nothing gets submitted."""
import sys
import time
import unicodedata


_AX = "/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices"


def can_type() -> bool:
    """macOS drops synthetic clicks and keys without a word unless the app has Accessibility permission."""
    if sys.platform != "darwin":
        return True
    import ctypes
    lib = ctypes.cdll.LoadLibrary(_AX)
    lib.AXIsProcessTrusted.restype = ctypes.c_bool
    return bool(lib.AXIsProcessTrusted())


def ask_type():
    """macOS's own "allow Sahl to control this computer?" prompt, which also lists Sahl under Accessibility."""
    if sys.platform != "darwin":
        return
    import ctypes
    ax, cf = ctypes.cdll.LoadLibrary(_AX), ctypes.cdll.LoadLibrary(
        "/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")
    key = ctypes.c_void_p.in_dll(ax, "kAXTrustedCheckOptionPrompt")
    yes = ctypes.c_void_p.in_dll(cf, "kCFBooleanTrue")
    cf.CFDictionaryCreate.restype = ctypes.c_void_p
    cf.CFDictionaryCreate.argtypes = [ctypes.c_void_p] * 3 + [ctypes.c_long] + [ctypes.c_void_p] * 2
    keys, values = (ctypes.c_void_p * 1)(key), (ctypes.c_void_p * 1)(yes)
    options = cf.CFDictionaryCreate(None, keys, values, 1,
                                    ctypes.addressof(ctypes.c_char.in_dll(cf, "kCFTypeDictionaryKeyCallBacks")),
                                    ctypes.addressof(ctypes.c_char.in_dll(cf, "kCFTypeDictionaryValueCallBacks")))
    ax.AXIsProcessTrustedWithOptions.argtypes = [ctypes.c_void_p]
    ax.AXIsProcessTrustedWithOptions(options)
    cf.CFRelease.argtypes = [ctypes.c_void_p]
    cf.CFRelease(options)


def _allowed():
    if not can_type():
        raise PermissionError("Accessibility permission is off")


def _plain(text: str) -> str:
    """pynput types a newline as Enter and a tab as Tab, so control characters become spaces before anything is typed."""
    return " ".join("".join(" " if unicodedata.category(c) == "Cc" else c for c in text).split())


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
    for ch in _plain(value):
        keys.type(ch)
        time.sleep(0.01)


def pick_from(box, text: str):
    """Chooses an option in a dropdown by typing its start into the closed, focused select. Tab moves on; never Enter."""
    _allowed()
    from pynput.keyboard import Controller as Keys, Key
    from pynput.mouse import Button, Controller as Mouse

    x0, y0, x1, y1 = box
    mouse, keys = Mouse(), Keys()
    mouse.position = ((x0 + x1) / 2, (y0 + y1) / 2)
    time.sleep(0.12)
    mouse.click(Button.left)  # brings a background browser forward, or opens the list if it was already in front
    time.sleep(0.8)  # a browser that was in the background needs this long to come forward before it takes keys
    keys.tap(Key.esc)  # closes the list either way, so the next click opens it exactly once
    time.sleep(0.15)
    mouse.click(Button.left)
    time.sleep(0.5)
    keys.tap(Key.esc)  # an open list only highlights what you type; a closed, focused one selects it
    time.sleep(0.3)
    for ch in _plain(text):
        keys.type(ch)
        time.sleep(0.12)
    time.sleep(0.1)
    keys.tap(Key.tab)
    time.sleep(0.2)


def open_and_type(box, text: str):
    """Opens a dropdown and types into it: a searchable list filters to it, a native one jumps to it, and a closed,
    focused one picks it. Sahl then finds the option on screen and clicks it (click_at). Never Enter."""
    _allowed()
    from pynput.keyboard import Controller as Keys, Key
    from pynput.mouse import Button, Controller as Mouse

    x0, y0, x1, y1 = box
    mouse, keys = Mouse(), Keys()
    mouse.position = ((x0 + x1) / 2, (y0 + y1) / 2)
    time.sleep(0.12)
    mouse.click(Button.left)  # brings a background browser forward, or opens the list if it was already in front
    time.sleep(0.8)
    keys.tap(Key.esc)  # closes the list either way, so the next click opens it exactly once
    time.sleep(0.15)
    mouse.click(Button.left)
    time.sleep(0.5)
    for ch in _plain(text):
        keys.type(ch)
        time.sleep(0.08)
    time.sleep(0.4)  # a searchable list filters as you type


def click_at(point, wake: bool = False):
    """One click at a screen point: an option in an open list, or a radio button (wake=True clicks once more first,
    to bring a background browser forward; a second click on a radio keeps it chosen)."""
    _allowed()
    from pynput.mouse import Button, Controller as Mouse

    mouse = Mouse()
    mouse.position = point
    time.sleep(0.12)
    if wake:
        mouse.click(Button.left)
        time.sleep(0.3)
    mouse.click(Button.left)
    time.sleep(0.2)


def close_list():
    """Closes a list Sahl opened but could not choose from. Esc only closes; it never submits."""
    _allowed()
    from pynput.keyboard import Controller as Keys, Key
    Keys().tap(Key.esc)
