import configparser
import subprocess
from pathlib import Path


def test_service_runs_as_desktop_user_with_restart_and_hardening() -> None:
    parser = configparser.ConfigParser(interpolation=None, strict=False)
    parser.read("packaging/local-remote-control.service")
    assert parser["Unit"]["After"] == "graphical-session.target"
    assert parser["Service"]["Restart"] == "on-failure"
    assert parser["Service"]["NoNewPrivileges"] == "true"
    assert "User" not in parser["Service"]
    assert parser["Service"].get("ProtectHome", "false") == "false"


def test_host_scripts_offer_help_without_changing_the_machine() -> None:
    for script in ("install.sh", "uninstall.sh", "diagnose.sh"):
        result = subprocess.run(["bash", f"scripts/{script}", "--help"], capture_output=True, text=True, check=False)
        assert result.returncode == 0, result.stderr
        assert "Uso:" in result.stdout


def test_installer_declares_the_web_rtc_ice_transport_dependency() -> None:
    result = subprocess.run(
        ["bash", "scripts/install.sh", "--print-dependencies"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "gstreamer1.0-nice" in result.stdout.splitlines()


def test_diagnostics_reports_each_web_rtc_transport_component() -> None:
    result = subprocess.run(
        ["bash", "scripts/diagnose.sh"],
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )

    assert result.returncode == 0, result.stderr
    assert "webrtcbin:" in result.stdout
    assert "nicesrc:" in result.stdout
    assert "nicesink:" in result.stdout
