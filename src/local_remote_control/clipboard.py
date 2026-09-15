"""Bounded, text-only X11 clipboard synchronization."""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass


class ClipboardTooLarge(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ClipboardUpdate:
    revision: str
    text: str
    source: str


class ClipboardBridge:
    def __init__(
        self,
        reader: Callable[[], Awaitable[bytes]],
        writer: Callable[[bytes], Awaitable[None]],
        max_bytes: int,
    ) -> None:
        self._reader = reader
        self._writer = writer
        self._max_bytes = max_bytes
        self._last = b""
        self._remote_echo: bytes | None = None
        self._revision = 0

    async def read(self) -> ClipboardUpdate | None:
        raw = await self._reader()
        if len(raw) > self._max_bytes:
            return None
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            return None
        if raw == self._remote_echo:
            self._last = raw
            self._remote_echo = None
            return None
        if raw == self._last:
            return None
        self._last = raw
        self._revision += 1
        return ClipboardUpdate(str(self._revision), text, "host")

    async def write(self, text: str, remote_revision: str) -> None:
        raw = text.encode("utf-8")
        if len(raw) > self._max_bytes:
            raise ClipboardTooLarge("clipboard text is too large")
        self._remote_echo = raw
        await self._writer(raw)

    async def watch(self, interval: float = 0.25) -> AsyncIterator[ClipboardUpdate]:
        while True:
            update = await self.read()
            if update is not None:
                yield update
            await asyncio.sleep(interval)


def xclip_bridge(display: str, max_bytes: int) -> ClipboardBridge:
    environment = {**os.environ, "DISPLAY": display}

    async def reader() -> bytes:
        process = await asyncio.create_subprocess_exec(
            "xclip", "-selection", "clipboard", "-out", env=environment,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
        )
        output, _ = await process.communicate()
        return output[: max_bytes + 1]

    async def writer(data: bytes) -> None:
        process = await asyncio.create_subprocess_exec(
            "xclip", "-selection", "clipboard", "-in", env=environment,
            stdin=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
        )
        await process.communicate(data)

    return ClipboardBridge(reader, writer, max_bytes)
