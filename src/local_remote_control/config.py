"""Private runtime configuration loading."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


class ConfigError(ValueError):
    """Raised when host configuration is missing or unsafe."""


_KEYS = {
    "BIND_HOST",
    "PORT",
    "PUBLIC_HOST",
    "PASSWORD_HASH",
    "CERTIFICATE",
    "PRIVATE_KEY",
    "SESSION_IDLE_SECONDS",
    "MAX_CLIPBOARD_BYTES",
    "DISPLAY",
    "SHELL",
}


@dataclass(frozen=True, slots=True)
class Settings:
    bind_host: str
    port: int
    public_host: str
    password_hash: str
    certificate: Path
    private_key: Path
    session_idle_seconds: int
    max_clipboard_bytes: int
    display: str
    shell: str

    @classmethod
    def load(cls, path: Path) -> "Settings":
        if path.stat().st_mode & 0o077:
            raise ConfigError(f"{path} must have mode 0600")

        values: dict[str, str] = {}
        for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                raise ConfigError(f"invalid line {line_number}")
            key, value = line.split("=", 1)
            if key not in _KEYS:
                raise ConfigError(f"unknown key {key}")
            if key in values:
                raise ConfigError(f"duplicate key {key}")
            values[key] = value

        missing = _KEYS - values.keys()
        if missing:
            raise ConfigError(f"missing keys: {', '.join(sorted(missing))}")

        port = _bounded_integer(values, "PORT", 1, 65535)
        idle = _bounded_integer(values, "SESSION_IDLE_SECONDS", 60, 86_400)
        clipboard = _bounded_integer(values, "MAX_CLIPBOARD_BYTES", 1, 16 * 1024 * 1024)
        public_host = values["PUBLIC_HOST"]
        if not public_host or "://" in public_host or "/" in public_host:
            raise ConfigError("PUBLIC_HOST must be a hostname or address without a scheme")

        return cls(
            bind_host=values["BIND_HOST"],
            port=port,
            public_host=public_host,
            password_hash=values["PASSWORD_HASH"],
            certificate=Path(values["CERTIFICATE"]),
            private_key=Path(values["PRIVATE_KEY"]),
            session_idle_seconds=idle,
            max_clipboard_bytes=clipboard,
            display=values["DISPLAY"],
            shell=values["SHELL"],
        )


def _bounded_integer(values: dict[str, str], key: str, minimum: int, maximum: int) -> int:
    try:
        value = int(values[key])
    except ValueError as error:
        raise ConfigError(f"{key} must be an integer") from error
    if not minimum <= value <= maximum:
        raise ConfigError(f"{key} must be between {minimum} and {maximum}")
    return value
