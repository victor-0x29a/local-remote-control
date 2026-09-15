"""Authenticated HTTP and WebSocket gateway."""

from __future__ import annotations

import asyncio
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from aiohttp import WSMsgType, web

from .clipboard import ClipboardBridge, ClipboardTooLarge
from .config import Settings
from .lease import ControllerLease
from .protocol import Heartbeat, ProtocolError, parse_control_message
from .security import AuthManager, Session
from .terminal import PtySession, TerminalInput, TerminalProtocolError, TerminalResize, parse_terminal_message


@dataclass(slots=True)
class Dependencies:
    settings: Settings
    auth: AuthManager
    lease: ControllerLease
    input_adapter: Any = None
    media_factory: Callable[..., Any] | None = None
    clipboard: ClipboardBridge | None = None
    terminal_factory: Callable[..., Any] = PtySession.start


DEPENDENCIES_KEY = web.AppKey("dependencies", Dependencies)


def create_app(dependencies: Dependencies) -> web.Application:
    app = web.Application(client_max_size=65_536)
    app[DEPENDENCIES_KEY] = dependencies
    app.router.add_get("/", _index)
    app.router.add_post("/api/login", _login)
    app.router.add_post("/api/logout", _logout)
    app.router.add_get("/api/status", _status)
    app.router.add_post("/api/lease", _acquire_lease)
    app.router.add_delete("/api/lease/{lease_id}", _release_lease)
    app.router.add_get("/ws/control", _control_socket)
    app.router.add_get("/ws/signal", _signal_socket)
    app.router.add_get("/ws/terminal", _terminal_socket)
    app.router.add_get("/ws/clipboard", _clipboard_socket)
    app.router.add_get("/healthz", _health)
    static = Path(__file__).with_name("static")
    if static.exists():
        app.router.add_static("/static", static, append_version=True)
    return app


async def _index(request: web.Request) -> web.StreamResponse:
    index = Path(__file__).with_name("static") / "index.html"
    if not index.exists():
        raise web.HTTPServiceUnavailable(text="Interface ainda não instalada")
    return web.FileResponse(index)


async def _login(request: web.Request) -> web.Response:
    deps = _deps(request)
    try:
        body = await request.json()
    except (json.JSONDecodeError, TypeError):
        raise web.HTTPBadRequest(text="JSON inválido")
    password = body.get("password") if isinstance(body, dict) else None
    if not isinstance(password, str) or not deps.auth.verify_password(_remote(request), password, time.monotonic()):
        raise web.HTTPUnauthorized(text="Senha incorreta ou tentativas temporariamente bloqueadas")
    session = deps.auth.create_session(time.monotonic())
    response = web.json_response({"csrf": session.csrf})
    response.set_cookie("lrc_session", session.token, secure=True, httponly=True, samesite="Strict", path="/")
    return response


async def _logout(request: web.Request) -> web.Response:
    session = _require_mutation(request)
    _deps(request).auth.revoke(session.token)
    response = web.json_response({"ok": True})
    response.del_cookie("lrc_session", path="/")
    return response


async def _status(request: web.Request) -> web.Response:
    return web.json_response({"authenticated": _session(request) is not None})


async def _acquire_lease(request: web.Request) -> web.Response:
    session = _require_mutation(request)
    handle = await _deps(request).lease.acquire(session.token)
    if handle is None:
        raise web.HTTPConflict(text="Outro navegador já está controlando este computador")
    return web.json_response({"lease": handle.id})


async def _release_lease(request: web.Request) -> web.Response:
    session = _require_mutation(request)
    lease_id = request.match_info["lease_id"]
    if not await _deps(request).lease.owns(lease_id, session.token):
        raise web.HTTPForbidden()
    await _deps(request).lease.release(lease_id)
    return web.json_response({"ok": True})


async def _control_socket(request: web.Request) -> web.WebSocketResponse:
    session, lease_id = await _require_socket(request)
    deps = _deps(request)
    socket = web.WebSocketResponse(max_msg_size=8192, heartbeat=5)
    await socket.prepare(request)
    try:
        async for message in socket:
            if message.type != WSMsgType.TEXT:
                await socket.close(code=1003, message=b"text only")
                break
            try:
                event = parse_control_message(message.data)
                if isinstance(event, Heartbeat):
                    await deps.lease.heartbeat(lease_id)
                elif deps.input_adapter is not None:
                    await deps.input_adapter.apply(event)
            except ProtocolError as error:
                await socket.send_json({"error": str(error)})
    finally:
        await deps.lease.release(lease_id)
    return socket


async def _signal_socket(request: web.Request) -> web.WebSocketResponse:
    _, _ = await _require_socket(request)
    deps = _deps(request)
    if deps.media_factory is None:
        raise web.HTTPServiceUnavailable(text="Mídia indisponível")
    socket = web.WebSocketResponse(max_msg_size=65_536)
    await socket.prepare(request)
    loop = asyncio.get_running_loop()

    def send(payload: dict[str, object]) -> None:
        loop.call_soon_threadsafe(asyncio.create_task, socket.send_json(payload))

    media = deps.media_factory(
        on_offer=lambda sdp: send({"type": "offer", "sdp": sdp}),
        on_ice=lambda mline, candidate: send({"type": "ice", "mline": mline, "candidate": candidate}),
        on_error=lambda error: send({"type": "error", "message": error}),
    )
    try:
        media.start()
        async for message in socket:
            if message.type != WSMsgType.TEXT:
                continue
            value = json.loads(message.data)
            if value.get("type") == "answer" and isinstance(value.get("sdp"), str):
                media.set_remote_answer(value["sdp"])
            elif value.get("type") == "ice" and isinstance(value.get("candidate"), str):
                media.add_ice(value["candidate"], int(value.get("mline", 0)))
    finally:
        media.stop()
    return socket


async def _terminal_socket(request: web.Request) -> web.WebSocketResponse:
    _, _ = await _require_socket(request)
    deps = _deps(request)
    terminal = await deps.terminal_factory(deps.settings.shell, os.environ)
    socket = web.WebSocketResponse(max_msg_size=65_536)
    await socket.prepare(request)

    async def output() -> None:
        async for chunk in terminal.read_chunks():
            await socket.send_bytes(chunk)

    output_task = asyncio.create_task(output())
    try:
        async for message in socket:
            try:
                parsed = parse_terminal_message(message.data)
                if isinstance(parsed, TerminalInput):
                    await terminal.write(parsed.data)
                elif isinstance(parsed, TerminalResize):
                    terminal.resize(parsed.rows, parsed.cols)
            except TerminalProtocolError as error:
                await socket.send_json({"error": str(error)})
    finally:
        output_task.cancel()
        await terminal.close()
    return socket


async def _clipboard_socket(request: web.Request) -> web.WebSocketResponse:
    _, _ = await _require_socket(request)
    clipboard = _deps(request).clipboard
    if clipboard is None:
        raise web.HTTPServiceUnavailable(text="Clipboard indisponível")
    socket = web.WebSocketResponse(max_msg_size=_deps(request).settings.max_clipboard_bytes + 1024)
    await socket.prepare(request)

    async def host_updates() -> None:
        async for update in clipboard.watch():
            await socket.send_json({"type": "clipboard", "revision": update.revision, "text": update.text})

    update_task = asyncio.create_task(host_updates())
    try:
        async for message in socket:
            if message.type == WSMsgType.TEXT:
                try:
                    value = json.loads(message.data)
                    await clipboard.write(value["text"], value["revision"])
                except (KeyError, TypeError, json.JSONDecodeError, ClipboardTooLarge) as error:
                    await socket.send_json({"error": str(error)})
    finally:
        update_task.cancel()
    return socket


async def _health(request: web.Request) -> web.Response:
    return web.json_response({"ok": True, "authenticated": _session(request) is not None})


def _deps(request: web.Request) -> Dependencies:
    return request.app[DEPENDENCIES_KEY]


def _session(request: web.Request) -> Session | None:
    token = request.cookies.get("lrc_session", "")
    return _deps(request).auth.authenticate(token, time.monotonic()) if token else None


def _require_mutation(request: web.Request) -> Session:
    session = _session(request)
    if session is None:
        raise web.HTTPUnauthorized()
    expected_origin = f"https://{_deps(request).settings.public_host}:{_deps(request).settings.port}"
    if request.headers.get("Origin") != expected_origin or request.headers.get("X-CSRF-Token") != session.csrf:
        raise web.HTTPForbidden(text="Origem ou CSRF inválido")
    return session


async def _require_socket(request: web.Request) -> tuple[Session, str]:
    session = _session(request)
    if session is None:
        raise web.HTTPUnauthorized()
    expected_origin = f"https://{_deps(request).settings.public_host}:{_deps(request).settings.port}"
    lease_id = request.query.get("lease", "")
    if request.headers.get("Origin") != expected_origin or not await _deps(request).lease.owns(lease_id, session.token):
        raise web.HTTPForbidden()
    return session, lease_id


def _remote(request: web.Request) -> str:
    return request.remote or "unknown"
