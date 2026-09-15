import asyncio
from pathlib import Path

from aiohttp.test_utils import TestClient, TestServer
from argon2 import PasswordHasher

from local_remote_control.config import Settings
from local_remote_control.lease import ControllerLease
from local_remote_control.security import AuthManager
from local_remote_control.web import Dependencies, create_app


async def client_for_app() -> TestClient:
    hasher = PasswordHasher(time_cost=1, memory_cost=1024, parallelism=1)
    settings = Settings("0.0.0.0", 8443, "room.local", hasher.hash("secret"), Path("cert"), Path("key"), 60, 1024, ":0", "/bin/bash")
    app = create_app(Dependencies(settings, AuthManager(settings.password_hash, 60, hasher=hasher), ControllerLease()))
    client = TestClient(TestServer(app))
    await client.start_server()
    return client


async def test_login_sets_hardened_cookie_and_returns_csrf() -> None:
    client = await client_for_app()
    try:
        response = await client.post("/api/login", json={"password": "secret"})
        body = await response.json()
        cookie = response.headers["Set-Cookie"]
        assert response.status == 200
        assert body["csrf"]
        assert "Secure" in cookie and "HttpOnly" in cookie and "SameSite=Strict" in cookie
    finally:
        await client.close()


async def test_wrong_password_and_private_health_response() -> None:
    client = await client_for_app()
    try:
        assert (await client.post("/api/login", json={"password": "wrong"})).status == 401
        response = await client.get("/healthz")
        health = await response.json()
        assert health == {"ok": True, "authenticated": False}
        assert response.headers["X-Content-Type-Options"] == "nosniff"
        assert response.headers["X-Frame-Options"] == "DENY"
        assert "default-src 'self'" in response.headers["Content-Security-Policy"]
    finally:
        await client.close()


async def test_mutation_requires_csrf_and_only_one_lease() -> None:
    client = await client_for_app()
    try:
        login = await client.post("/api/login", json={"password": "secret"})
        csrf = (await login.json())["csrf"]
        cookie = login.cookies["lrc_session"].value
        headers = {"Cookie": f"lrc_session={cookie}", "X-CSRF-Token": csrf, "Origin": "https://room.local:8443"}
        assert (await client.post("/api/lease", headers={"Cookie": f"lrc_session={cookie}"})).status == 403
        first = await client.post("/api/lease", headers=headers)
        assert first.status == 200
        assert (await client.post("/api/lease", headers=headers)).status == 409
    finally:
        await client.close()


async def test_media_signaling_carries_the_negotiation_generation() -> None:
    fake = FakeMediaFactory()
    hasher = PasswordHasher(time_cost=1, memory_cost=1024, parallelism=1)
    settings = Settings("0.0.0.0", 8443, "room.local", hasher.hash("secret"), Path("cert"), Path("key"), 60, 1024, ":0", "/bin/bash")
    dependencies = Dependencies(
        settings,
        AuthManager(settings.password_hash, 60, hasher=hasher),
        ControllerLease(),
        media_factory=fake,
    )
    client = TestClient(TestServer(create_app(dependencies)))
    await client.start_server()
    try:
        login = await client.post("/api/login", json={"password": "secret"})
        csrf = (await login.json())["csrf"]
        cookie = login.cookies["lrc_session"].value
        headers = {
            "Cookie": f"lrc_session={cookie}",
            "X-CSRF-Token": csrf,
            "Origin": "https://room.local:8443",
        }
        lease_response = await client.post("/api/lease", headers=headers)
        lease = (await lease_response.json())["lease"]
        socket = await client.ws_connect(
            f"/ws/signal?lease={lease}",
            headers={"Cookie": f"lrc_session={cookie}", "Origin": headers["Origin"]},
        )

        assert await socket.receive_json() == {
            "type": "offer",
            "negotiation": 12,
            "sdp": "v=0\r\n",
        }
        assert await socket.receive_json() == {
            "type": "ice",
            "negotiation": 12,
            "mline": 0,
            "candidate": "candidate:host",
        }
        await socket.send_json({"type": "answer", "negotiation": 12, "sdp": "answer"})
        await socket.send_json({"type": "ice", "negotiation": 12, "mline": 0, "candidate": "browser"})
        await asyncio.wait_for(fake.received.wait(), timeout=1)

        assert fake.answers == [("answer", 12)]
        assert fake.ice == [("browser", 0, 12)]
        await socket.close()
    finally:
        await client.close()


class FakeMediaFactory:
    def __init__(self) -> None:
        self.answers: list[tuple[str, int]] = []
        self.ice: list[tuple[str, int, int]] = []
        self.received = asyncio.Event()

    def __call__(self, *, on_offer, on_ice, on_error):
        factory = self

        class FakeMedia:
            def start(self) -> None:
                on_offer(12, "v=0\r\n")
                on_ice(12, 0, "candidate:host")

            def set_remote_answer(self, sdp: str, generation: int) -> None:
                factory.answers.append((sdp, generation))
                if factory.ice:
                    factory.received.set()

            def add_ice(self, candidate: str, mline: int, generation: int) -> None:
                factory.ice.append((candidate, mline, generation))
                if factory.answers:
                    factory.received.set()

            def stop(self) -> None:
                pass

        return FakeMedia()
