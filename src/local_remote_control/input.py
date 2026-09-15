"""Safe translation from validated browser events to X11 commands."""

from __future__ import annotations

import asyncio
import inspect
import os
from collections.abc import Awaitable, Callable

from .protocol import KeyEvent, MouseButton, MouseMove, MouseWheel, TextInput


_SPECIAL_KEYS = {
    "Backspace": "BackSpace", "CapsLock": "Caps_Lock", "Delete": "Delete", "End": "End",
    "Enter": "Return", "Escape": "Escape", "Home": "Home", "Insert": "Insert",
    "PageDown": "Page_Down", "PageUp": "Page_Up", "Space": "space", "Tab": "Tab",
    "ArrowDown": "Down", "ArrowLeft": "Left", "ArrowRight": "Right", "ArrowUp": "Up",
    "Minus": "minus", "Equal": "equal", "BracketLeft": "bracketleft",
    "BracketRight": "bracketright", "Backslash": "backslash", "Semicolon": "semicolon",
    "Quote": "apostrophe", "Backquote": "grave", "Comma": "comma", "Period": "period",
    "Slash": "slash", "ControlLeft": "Control_L", "ControlRight": "Control_R",
    "ShiftLeft": "Shift_L", "ShiftRight": "Shift_R", "AltLeft": "Alt_L", "AltRight": "Alt_R",
    "MetaLeft": "Super_L", "MetaRight": "Super_R",
}
_MODIFIERS = {"Alt": "alt", "Control": "ctrl", "Meta": "super", "Shift": "shift"}


class InputAdapter:
    def __init__(
        self,
        runner: Callable[..., Awaitable[None]],
        screen_size: Callable[[], tuple[int, int]],
        paste_text: Callable[[str], object],
    ) -> None:
        self._runner = runner
        self._screen_size = screen_size
        self._paste_text = paste_text
        self._lock = asyncio.Lock()

    async def apply(self, event: MouseMove | MouseButton | MouseWheel | KeyEvent | TextInput) -> None:
        async with self._lock:
            if isinstance(event, MouseMove):
                width, height = self._screen_size()
                await self._runner("xdotool", "mousemove", str(round(event.x * (width - 1))), str(round(event.y * (height - 1))))
            elif isinstance(event, MouseButton):
                await self._runner("xdotool", "mousedown" if event.pressed else "mouseup", str(event.button))
            elif isinstance(event, MouseWheel):
                arguments: list[str] = ["xdotool"]
                for delta, negative, positive in ((event.dy, "5", "4"), (event.dx, "7", "6")):
                    for _ in range(round(abs(delta))):
                        arguments.extend(("click", negative if delta < 0 else positive))
                if len(arguments) > 1:
                    await self._runner(*arguments)
            elif isinstance(event, KeyEvent):
                key = _key_name(event.code)
                chord = "+".join([*(_MODIFIERS[item] for item in event.modifiers), key])
                await self._runner("xdotool", "keydown" if event.pressed else "keyup", chord)
            elif isinstance(event, TextInput):
                result = self._paste_text(event.text)
                if inspect.isawaitable(result):
                    await result


def _key_name(code: str) -> str:
    if code.startswith("Key"):
        return code[3:].lower()
    if code.startswith("Digit"):
        return code[5:]
    if code.startswith("F") and code[1:].isdigit():
        return code
    return _SPECIAL_KEYS[code]


async def run_x11_command(*args: str, display: str = ":0") -> None:
    environment = {**os.environ, "DISPLAY": display}
    process = await asyncio.create_subprocess_exec(
        *args,
        env=environment,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    _, error = await process.communicate()
    if process.returncode:
        raise RuntimeError(error.decode("utf-8", "replace").strip())
