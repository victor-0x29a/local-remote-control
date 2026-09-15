"""Strict JSON protocol for latency-sensitive remote input."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass


class ProtocolError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class MouseMove:
    x: float
    y: float


@dataclass(frozen=True, slots=True)
class MouseButton:
    button: int
    pressed: bool


@dataclass(frozen=True, slots=True)
class MouseWheel:
    dx: float
    dy: float


@dataclass(frozen=True, slots=True)
class KeyEvent:
    code: str
    pressed: bool
    modifiers: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TextInput:
    text: str


@dataclass(frozen=True, slots=True)
class Heartbeat:
    pass


ControlEvent = MouseMove | MouseButton | MouseWheel | KeyEvent | TextInput | Heartbeat

_KEY_CODES = {
    *(f"Key{letter}" for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"),
    *(f"Digit{digit}" for digit in "0123456789"),
    *(f"F{number}" for number in range(1, 13)),
    "AltLeft", "AltRight", "Backspace", "CapsLock", "ControlLeft", "ControlRight",
    "Delete", "End", "Enter", "Escape", "Home", "Insert", "MetaLeft", "MetaRight",
    "PageDown", "PageUp", "ShiftLeft", "ShiftRight", "Space", "Tab",
    "ArrowDown", "ArrowLeft", "ArrowRight", "ArrowUp", "Minus", "Equal",
    "BracketLeft", "BracketRight", "Backslash", "Semicolon", "Quote", "Backquote",
    "Comma", "Period", "Slash",
}
_MODIFIERS = {"Alt", "Control", "Meta", "Shift"}


def parse_control_message(raw: str) -> ControlEvent:
    if not isinstance(raw, str) or len(raw.encode("utf-8")) > 8192:
        raise ProtocolError("message is too large")
    try:
        value = json.loads(raw, parse_constant=lambda value: (_raise(f"invalid {value}")))
    except (json.JSONDecodeError, TypeError) as error:
        raise ProtocolError("invalid JSON") from error
    if not isinstance(value, dict) or not isinstance(value.get("type"), str):
        raise ProtocolError("message must be an object with a type")
    kind = value["type"]
    if kind == "move":
        _fields(value, {"type", "x", "y"})
        return MouseMove(_number(value["x"], "x", 0, 1), _number(value["y"], "y", 0, 1))
    if kind == "button":
        _fields(value, {"type", "button", "pressed"})
        button = value["button"]
        if isinstance(button, bool) or not isinstance(button, int) or not 1 <= button <= 5:
            raise ProtocolError("button must be between 1 and 5")
        return MouseButton(button, _boolean(value["pressed"], "pressed"))
    if kind == "wheel":
        _fields(value, {"type", "dx", "dy"})
        return MouseWheel(_number(value["dx"], "dx", -20, 20), _number(value["dy"], "dy", -20, 20))
    if kind == "key":
        _fields(value, {"type", "code", "pressed", "modifiers"})
        code = value["code"]
        modifiers = value["modifiers"]
        if code not in _KEY_CODES or not isinstance(modifiers, list) or any(m not in _MODIFIERS for m in modifiers):
            raise ProtocolError("key is not allowed")
        return KeyEvent(code, _boolean(value["pressed"], "pressed"), tuple(sorted(set(modifiers))))
    if kind == "text":
        _fields(value, {"type", "text"})
        text = value["text"]
        if not isinstance(text, str) or len(text.encode("utf-8")) > 4096:
            raise ProtocolError("text is too large")
        return TextInput(text)
    if kind == "heartbeat":
        _fields(value, {"type"})
        return Heartbeat()
    raise ProtocolError("unknown message type")


def _fields(value: dict[str, object], expected: set[str]) -> None:
    if value.keys() != expected:
        raise ProtocolError("message has missing or unknown fields")


def _number(value: object, name: str, minimum: float, maximum: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ProtocolError(f"{name} must be a finite number")
    result = float(value)
    if not minimum <= result <= maximum:
        raise ProtocolError(f"{name} is out of range")
    return result


def _boolean(value: object, name: str) -> bool:
    if not isinstance(value, bool):
        raise ProtocolError(f"{name} must be a boolean")
    return value


def _raise(message: str) -> None:
    raise ProtocolError(message)
