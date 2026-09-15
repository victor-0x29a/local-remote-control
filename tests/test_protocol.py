import json

import pytest

from local_remote_control.protocol import (
    Heartbeat,
    KeyEvent,
    MouseMove,
    ProtocolError,
    TextInput,
    parse_control_message,
)


def test_parses_normalized_pointer_move() -> None:
    assert parse_control_message('{"type":"move","x":0.25,"y":1}') == MouseMove(0.25, 1.0)


def test_parses_allowlisted_key_and_heartbeat() -> None:
    event = parse_control_message('{"type":"key","code":"KeyA","pressed":true,"modifiers":["Control"]}')
    assert event == KeyEvent("KeyA", True, ("Control",))
    assert parse_control_message('{"type":"heartbeat"}') == Heartbeat()


def test_parses_bounded_text() -> None:
    assert parse_control_message('{"type":"text","text":"olá"}') == TextInput("olá")
    with pytest.raises(ProtocolError, match="text"):
        parse_control_message(json.dumps({"type": "text", "text": "x" * 4097}))


@pytest.mark.parametrize(
    "raw",
    [
        "not json",
        '{"type":"move","x":-0.1,"y":0}',
        '{"type":"move","x":true,"y":0}',
        '{"type":"move","x":NaN,"y":0}',
        '{"type":"key","code":"LaunchShell","pressed":true,"modifiers":[]}',
        '{"type":"heartbeat","extra":1}',
        "x" * 8193,
    ],
)
def test_rejects_malformed_or_unbounded_messages(raw: str) -> None:
    with pytest.raises(ProtocolError):
        parse_control_message(raw)
