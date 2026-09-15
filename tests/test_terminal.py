import json

import pytest

from local_remote_control.terminal import PtySession, TerminalInput, TerminalProtocolError, TerminalResize, parse_terminal_message


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


@pytest.mark.asyncio
async def test_pty_preserves_the_desktop_session_bus_environment(tmp_path) -> None:
    shell = tmp_path / "print-environment"
    shell.write_text("#!/bin/sh\n/usr/bin/env\n", encoding="utf-8")
    shell.chmod(0o700)
    session = await PtySession.start(
        str(shell),
        {
            "HOME": "/home/remote",
            "PATH": "/usr/bin:/bin",
            "XDG_RUNTIME_DIR": "/run/user/1000",
            "DBUS_SESSION_BUS_ADDRESS": "unix:path=/run/user/1000/bus",
            "PRIVATE_VALUE": "must-not-leak",
        },
    )

    output = b"".join([chunk async for chunk in session.read_chunks()]).decode()
    await session.close()

    assert "XDG_RUNTIME_DIR=/run/user/1000" in output
    assert "DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus" in output
    assert "PRIVATE_VALUE=" not in output
