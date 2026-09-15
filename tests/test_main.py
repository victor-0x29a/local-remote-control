import subprocess
import sys


def test_module_exposes_help_without_loading_native_media() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "local_remote_control.main", "--help"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "--config" in result.stdout
