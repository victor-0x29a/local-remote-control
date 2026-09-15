from argon2 import PasswordHasher

from local_remote_control.security import AuthManager


def manager() -> AuthManager:
    hasher = PasswordHasher(time_cost=1, memory_cost=1024, parallelism=1)
    return AuthManager(hasher.hash("correct horse"), 30, hasher=hasher)


def test_valid_password_creates_independent_browser_session() -> None:
    auth = manager()
    assert auth.verify_password("192.168.1.20", "correct horse", 1.0)
    session = auth.create_session(1.0)
    assert session.token != session.csrf
    assert auth.authenticate(session.token, 2.0) is session


def test_invalid_password_is_rejected() -> None:
    assert not manager().verify_password("192.168.1.20", "wrong", 1.0)


def test_sixth_immediate_attempt_is_throttled_even_with_valid_password() -> None:
    auth = manager()
    for moment in range(5):
        assert not auth.verify_password("192.168.1.20", "wrong", float(moment))
    assert not auth.verify_password("192.168.1.20", "correct horse", 4.1)


def test_success_clears_failure_history() -> None:
    auth = manager()
    assert not auth.verify_password("192.168.1.20", "wrong", 0.0)
    assert auth.verify_password("192.168.1.20", "correct horse", 3.0)
    assert not auth.verify_password("192.168.1.20", "wrong", 3.1)


def test_session_expires_after_idle_period() -> None:
    auth = manager()
    session = auth.create_session(10.0)
    assert auth.authenticate(session.token, 39.9)
    assert auth.authenticate(session.token, 70.0) is None


def test_revoked_session_cannot_authenticate() -> None:
    auth = manager()
    session = auth.create_session(1.0)
    auth.revoke(session.token)
    assert auth.authenticate(session.token, 2.0) is None
