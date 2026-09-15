import pytest

from local_remote_control.clipboard import ClipboardBridge, ClipboardTooLarge


async def test_emits_local_changes_once_and_suppresses_remote_echo() -> None:
    current = [b"first"]
    writes: list[bytes] = []

    async def read() -> bytes:
        return current[0]

    async def write(value: bytes) -> None:
        writes.append(value)
        current[0] = value

    bridge = ClipboardBridge(read, write, max_bytes=20)
    first = await bridge.read()
    assert first is not None and first.text == "first"
    assert await bridge.read() is None
    await bridge.write("remote", "browser-1")
    assert writes == [b"remote"]
    assert await bridge.read() is None


async def test_rejects_oversized_or_invalid_text() -> None:
    async def no_write(value: bytes) -> None:
        raise AssertionError("must not write")

    bridge = ClipboardBridge(lambda: async_value(b"bad\xff"), no_write, max_bytes=4)
    assert await bridge.read() is None
    with pytest.raises(ClipboardTooLarge):
        await bridge.write("12345", "revision")


async def async_value(value: bytes) -> bytes:
    return value
