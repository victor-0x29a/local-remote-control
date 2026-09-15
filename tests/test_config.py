from pathlib import Path

import pytest

from local_remote_control.config import ConfigError, Settings


VALID_CONFIG = """\
BIND_HOST=0.0.0.0
PORT=8443
PUBLIC_HOST=192.168.1.10
PASSWORD_HASH=$argon2id$v=19$example
CERTIFICATE=/tmp/cert.pem
PRIVATE_KEY=/tmp/key.pem
SESSION_IDLE_SECONDS=1800
MAX_CLIPBOARD_BYTES=1048576
DISPLAY=:0
SHELL=/bin/bash
"""


def write_config(tmp_path: Path, content: str = VALID_CONFIG, mode: int = 0o600) -> Path:
    path = tmp_path / "config.env"
    path.write_text(content, encoding="utf-8")
    path.chmod(mode)
    return path


def test_loads_private_environment_file(tmp_path: Path) -> None:
    settings = Settings.load(write_config(tmp_path))

    assert settings.port == 8443
    assert settings.display == ":0"
    assert settings.public_host == "192.168.1.10"


def test_rejects_group_readable_secrets(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="0600"):
        Settings.load(write_config(tmp_path, mode=0o640))


@pytest.mark.parametrize("port", ["0", "65536", "not-a-number"])
def test_rejects_invalid_ports(tmp_path: Path, port: str) -> None:
    content = VALID_CONFIG.replace("PORT=8443", f"PORT={port}")

    with pytest.raises(ConfigError, match="PORT"):
        Settings.load(write_config(tmp_path, content))


@pytest.mark.parametrize("host", ["https://room.local", "room.local/path", ""])
def test_rejects_unsafe_public_host(tmp_path: Path, host: str) -> None:
    content = VALID_CONFIG.replace("PUBLIC_HOST=192.168.1.10", f"PUBLIC_HOST={host}")

    with pytest.raises(ConfigError, match="PUBLIC_HOST"):
        Settings.load(write_config(tmp_path, content))


def test_rejects_unknown_keys(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="UNKNOWN"):
        Settings.load(write_config(tmp_path, VALID_CONFIG + "UNKNOWN=value\n"))
