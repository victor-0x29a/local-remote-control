import asyncio

from local_remote_control.lease import ControllerLease


async def test_allows_exactly_one_simultaneous_controller() -> None:
    lease = ControllerLease(clock=lambda: 1.0)
    first, second = await asyncio.gather(lease.acquire("one"), lease.acquire("two"))
    assert sum(handle is not None for handle in (first, second)) == 1


async def test_only_owner_handle_can_release() -> None:
    lease = ControllerLease(clock=lambda: 1.0)
    owner = await lease.acquire("one")
    assert owner is not None
    await lease.release("not-owner")
    assert await lease.acquire("two") is None
    await lease.release(owner.id)
    assert await lease.acquire("two") is not None


async def test_heartbeat_refreshes_and_stale_lease_is_reaped() -> None:
    now = [0.0]
    lease = ControllerLease(timeout=15.0, clock=lambda: now[0])
    owner = await lease.acquire("one")
    assert owner is not None
    now[0] = 14.0
    assert await lease.heartbeat(owner.id)
    now[0] = 28.0
    assert not await lease.reap()
    now[0] = 30.0
    assert await lease.reap()
    assert await lease.acquire("two") is not None


async def test_validates_lease_ownership_without_exposing_session() -> None:
    lease = ControllerLease(clock=lambda: 1.0)
    owner = await lease.acquire("private-session")
    assert owner is not None
    assert await lease.owns(owner.id, "private-session")
    assert not await lease.owns(owner.id, "different-session")
