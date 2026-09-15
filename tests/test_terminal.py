import json

import pytest

from local_remote_control.terminal import TerminalInput, TerminalProtocolError, TerminalResize, parse_terminal_message


def test_parses_terminal_input_and_resize() -> None:
    assert parse_terminal_message(b"ls\n") == TerminalInput(b"ls\n")
    assert parse_terminal_message('{"type":"resize","rows":40,"cols":120}') == TerminalResize(40, 120)


@pytest.mark.parametrize(
    "message",
    [b"x" * 65537, '{"type":"resize","rows":1,"cols":80}', '{"type":"resize","rows":40,"cols":501}', '{"type":"other"}'],
)
def test_rejects_unbounded_or_unknown_terminal_messages(message: bytes | str) -> None:
    with pytest.raises(TerminalProtocolError):
        parse_terminal_message(message)
