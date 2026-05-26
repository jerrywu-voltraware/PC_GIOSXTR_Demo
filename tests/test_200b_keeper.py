"""Verifies BleManager's 200B watchdog re-requests when notifications go stale."""

from __future__ import annotations

import asyncio

from app.ble_manager import BleManager
from app.constants import UUID_NOTIFY_200B


class _FakeSender:
    def __init__(self, uuid: str) -> None:
        self.uuid = uuid


def _make_manager(*, connected: bool = True) -> tuple[BleManager, list[str]]:
    """Build a BleManager wired with a stub client and a recording request_200b."""
    manager = BleManager()
    requests: list[str] = []

    class _Client:
        is_connected = connected

        async def stop_notify(self, _uuid):  # pragma: no cover - not exercised
            pass

        async def disconnect(self):  # pragma: no cover - not exercised
            pass

    manager.client = _Client()  # type: ignore[assignment]
    manager.address = "AA:BB:CC:DD:EE:FF"
    manager.iot_write_uuid = "fake-iot-write"

    async def fake_request_200b():
        requests.append("0xA2")

    manager.request_200b = fake_request_200b  # type: ignore[assignment]
    return manager, requests


def test_keeper_requests_200b_when_never_received():
    async def run():
        manager, requests = _make_manager()
        manager.start_200b_keeper(interval=0.05, stale_after=0.0)
        await asyncio.sleep(0.12)
        manager.stop_200b_keeper()
        assert len(requests) >= 1

    asyncio.run(run())


def test_keeper_skips_request_when_200b_fresh():
    async def run():
        manager, requests = _make_manager()
        manager._last_200b_at = asyncio.get_running_loop().time()
        manager.start_200b_keeper(interval=0.05, stale_after=10.0)
        await asyncio.sleep(0.12)
        manager.stop_200b_keeper()
        assert requests == []

    asyncio.run(run())


def test_keeper_stops_when_client_disconnects():
    async def run():
        manager, requests = _make_manager()
        manager.start_200b_keeper(interval=0.05, stale_after=0.0)
        await asyncio.sleep(0.06)
        manager.client.is_connected = False  # type: ignore[attr-defined]
        await asyncio.sleep(0.15)
        count_after_disconnect = len(requests)
        await asyncio.sleep(0.15)
        assert len(requests) == count_after_disconnect
        manager.stop_200b_keeper()

    asyncio.run(run())


def test_200b_notification_updates_timestamp(monkeypatch):
    """The notify handler must stamp last_200b_at when receiving 200B."""

    async def run():
        manager = BleManager()
        manager.address = "AA"
        captured: list[float | None] = []

        class _Client:
            is_connected = True

            async def start_notify(self, uuid, handler):
                # Simulate firmware pushing a 200B packet right away.
                handler(_FakeSender(UUID_NOTIFY_200B), bytearray(b"\x00" * 204))
                captured.append(manager._last_200b_at)

        manager.client = _Client()  # type: ignore[assignment]
        await manager.enable_notify(UUID_NOTIFY_200B)
        assert captured and captured[0] is not None

    asyncio.run(run())


def test_20b_notification_does_not_update_200b_timestamp():
    """A 20B notification must not refresh the 200B keeper timestamp."""
    from app.constants import UUID_NOTIFY_20B

    async def run():
        manager = BleManager()
        manager.address = "AA"

        class _Client:
            is_connected = True

            async def start_notify(self, uuid, handler):
                handler(_FakeSender(UUID_NOTIFY_20B), bytearray(b"\x00" * 20))

        manager.client = _Client()  # type: ignore[assignment]
        await manager.enable_notify(UUID_NOTIFY_20B)
        assert manager._last_200b_at is None

    asyncio.run(run())


def test_default_notifications_skip_20b():
    """Default subscription set must mirror the iOS strategy: IOT + 200B only.

    Subscribing to 20B brings back the unit/width race on shared DeviceState
    fields. This test guards against accidental reintroduction.
    """
    from app.constants import UUID_IOT_NOTIFY, UUID_NOTIFY_200B, UUID_NOTIFY_20B

    async def run():
        manager = BleManager()
        manager.address = "AA"
        subscribed: list[str] = []

        class _Client:
            is_connected = True

            async def start_notify(self, uuid, _handler):
                subscribed.append(uuid)

        manager.client = _Client()  # type: ignore[assignment]
        await manager.enable_default_notifications()

        assert UUID_IOT_NOTIFY in subscribed
        assert UUID_NOTIFY_200B in subscribed
        assert UUID_NOTIFY_20B not in subscribed

    asyncio.run(run())
