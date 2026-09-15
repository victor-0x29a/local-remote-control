"""Bounded terminal protocol and PTY lifecycle."""

from __future__ import annotations

import asyncio
import fcntl
import json
import os
import pty
import signal
import struct
import termios
from dataclasses import dataclass
from typing import AsyncIterator


class TerminalProtocolError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class TerminalInput:
    data: bytes


@dataclass(frozen=True, slots=True)
class TerminalResize:
    rows: int
    cols: int


def parse_terminal_message(raw: bytes | str) -> TerminalInput | TerminalResize:
    if isinstance(raw, bytes):
        if len(raw) > 65_536:
            raise TerminalProtocolError("terminal input is too large")
        return TerminalInput(raw)
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as error:
        raise TerminalProtocolError("invalid terminal message") from error
    if not isinstance(value, dict) or value.keys() != {"type", "rows", "cols"} or value.get("type") != "resize":
        raise TerminalProtocolError("unknown terminal message")
    rows, cols = value["rows"], value["cols"]
    if isinstance(rows, bool) or not isinstance(rows, int) or not 2 <= rows <= 300:
        raise TerminalProtocolError("rows out of range")
    if isinstance(cols, bool) or not isinstance(cols, int) or not 2 <= cols <= 500:
        raise TerminalProtocolError("cols out of range")
    return TerminalResize(rows, cols)


class PtySession:
    def __init__(self, master_fd: int, process: asyncio.subprocess.Process) -> None:
        self._master_fd = master_fd
        self._process = process

    @classmethod
    async def start(cls, shell: str, environment: dict[str, str]) -> "PtySession":
        master_fd, slave_fd = pty.openpty()
        allowed = {
            "HOME", "USER", "LOGNAME", "PATH", "SHELL", "TERM", "LANG", "DISPLAY", "XAUTHORITY",
            "XDG_RUNTIME_DIR", "DBUS_SESSION_BUS_ADDRESS",
        }
        child_environment = {key: value for key, value in environment.items() if key in allowed}
        child_environment.setdefault("TERM", "xterm-256color")
        try:
            process = await asyncio.create_subprocess_exec(
                shell,
                "-l",
                stdin=slave_fd,
                stdout=slave_fd,
                stderr=slave_fd,
                env=child_environment,
                start_new_session=True,
            )
        finally:
            os.close(slave_fd)
        return cls(master_fd, process)

    async def write(self, data: bytes) -> None:
        if len(data) > 65_536:
            raise TerminalProtocolError("terminal input is too large")
        await asyncio.to_thread(os.write, self._master_fd, data)

    def resize(self, rows: int, cols: int) -> None:
        parse_terminal_message(json.dumps({"type": "resize", "rows": rows, "cols": cols}))
        fcntl.ioctl(self._master_fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))

    async def read_chunks(self) -> AsyncIterator[bytes]:
        while self._process.returncode is None:
            try:
                chunk = await asyncio.to_thread(os.read, self._master_fd, 16_384)
            except OSError:
                break
            if not chunk:
                break
            yield chunk

    async def close(self) -> None:
        if self._process.returncode is None:
            os.killpg(self._process.pid, signal.SIGTERM)
            try:
                await asyncio.wait_for(self._process.wait(), timeout=1.0)
            except TimeoutError:
                os.killpg(self._process.pid, signal.SIGKILL)
                await self._process.wait()
        os.close(self._master_fd)
