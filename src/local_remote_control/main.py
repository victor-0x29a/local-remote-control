"""Command-line entry point for the Ubuntu host service."""

from __future__ import annotations

import argparse
import asyncio
import functools
import ssl
import subprocess
from pathlib import Path

from aiohttp import web

from .clipboard import xclip_bridge
from .config import Settings
from .input import InputAdapter, run_x11_command
from .lease import ControllerLease
from .media import WebRtcDesktop, probe_encoders, select_encoder
from .security import AuthManager
from .web import Dependencies, create_app


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(description="Controle remoto local para Ubuntu")
    command.add_argument("--config", type=Path, required=True, help="arquivo de configuração privado")
    return command


def _screen_size(display: str) -> tuple[int, int]:
    result = subprocess.run(
        ["xdotool", "getdisplaygeometry", "--shell"],
        check=True,
        capture_output=True,
        text=True,
        env={"DISPLAY": display},
    )
    values = dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)
    return int(values["WIDTH"]), int(values["HEIGHT"])


def build_app(settings: Settings) -> web.Application:
    clipboard = xclip_bridge(settings.display, settings.max_clipboard_bytes)
    dimensions = _screen_size(settings.display)

    async def runner(*args: str) -> None:
        await run_x11_command(*args, display=settings.display)

    async def paste(text: str) -> None:
        await clipboard.write(text, "keyboard")
        await runner("xdotool", "key", "ctrl+v")

    encoder = select_encoder(probe_encoders())
    media_factory = functools.partial(WebRtcDesktop, encoder, display=settings.display)
    dependencies = Dependencies(
        settings=settings,
        auth=AuthManager(settings.password_hash, settings.session_idle_seconds),
        lease=ControllerLease(),
        input_adapter=InputAdapter(runner, lambda: dimensions, paste),
        media_factory=media_factory,
        clipboard=clipboard,
    )
    return create_app(dependencies)


def main() -> None:
    arguments = parser().parse_args()
    settings = Settings.load(arguments.config)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(settings.certificate, settings.private_key)
    web.run_app(
        build_app(settings),
        host=settings.bind_host,
        port=settings.port,
        ssl_context=context,
        print=lambda message: print(message, flush=True),
    )


if __name__ == "__main__":
    main()
