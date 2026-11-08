import contextlib

import pytest

from sahl import fill


class Keys:
    typed: list[str] = []

    def type(self, ch):
        Keys.typed.append(ch)

    def tap(self, key):
        pass

    @contextlib.contextmanager
    def pressed(self, key):
        yield


class Mouse:
    position = (0, 0)

    def click(self, button):
        pass


@pytest.fixture
def keys(monkeypatch):
    import pynput.keyboard
    import pynput.mouse
    monkeypatch.setattr(pynput.keyboard, "Controller", Keys)
    monkeypatch.setattr(pynput.mouse, "Controller", Mouse)
    monkeypatch.setattr(fill, "_allowed", lambda: None)
    monkeypatch.setattr(fill.time, "sleep", lambda s: None)
    Keys.typed = []
    return Keys.typed


@pytest.mark.parametrize("typer", [fill.type_into, fill.pick_from, fill.open_and_type])
def test_a_newline_or_tab_in_a_value_is_never_typed_as_enter_or_tab(keys, typer):
    typer((0, 0, 10, 10), "TESTA\nDUMMYB\r\tX")
    assert "".join(keys) == "TESTA DUMMYB X"


def test_letters_that_join_arabic_and_urdu_names_are_kept():
    assert fill._plain("علي‌رضا") == "علي‌رضا"
