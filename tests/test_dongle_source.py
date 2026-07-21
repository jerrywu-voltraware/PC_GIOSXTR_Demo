"""Hardware-free tests for the Nordic dongle data source.

These exercise the byte-stream demux, CRC validation, frame->notify routing,
and AT scan-list parsing against the exact formats produced by the firmware
(send_binary_packet / scan_device_print / CONNECTED messages).
"""

from __future__ import annotations

import asyncio

import pytest

from app import device_source as ds
from app.ble_adapter import AdapterStatus
from app.constants import UUID_IOT_NOTIFY, UUID_NOTIFY_200B
from app.device_source import DongleSource, _crc16_ccitt


def _build_frame(site_id: int, dev_id: int, seq: int, payload: bytes, rssi: int) -> bytes:
    """Replicate firmware send_binary_packet framing."""
    body = bytearray()
    body += site_id.to_bytes(2, "little")
    body += bytes([dev_id])
    body += seq.to_bytes(2, "little")
    body += bytes([len(payload)])
    body += payload
    body += bytes([rssi & 0xFF])  # int8 RSSI
    crc = _crc16_ccitt(bytes(body))
    return bytes([0xAA, 0x55]) + bytes(body) + crc.to_bytes(2, "little")


def _make_source() -> DongleSource:
    loop = asyncio.new_event_loop()
    return DongleSource(
        "TEST", loop, serial_port=object(), start_reader=False
    )


class FakeSerial:
    is_open = True

    def __init__(self) -> None:
        self.writes: list[str] = []

    def write(self, data: bytes) -> None:
        self.writes.append(data.decode("ascii").strip())

    def read(self, _size: int) -> bytes:
        return b""

    def close(self) -> None:
        self.is_open = False


class ReadFailSerial(FakeSerial):
    def read(self, _size: int) -> bytes:
        raise OSError("simulated serial read failure")


class WriteFailSerial(FakeSerial):
    def write(self, _data: bytes) -> None:
        raise OSError("simulated serial write failure")


def _make_source_with_fake_serial() -> tuple[DongleSource, FakeSerial]:
    loop = asyncio.new_event_loop()
    serial = FakeSerial()
    return DongleSource("TEST", loop, serial_port=serial, start_reader=False), serial


def test_crc16_ccitt_known_vector():
    # CRC16-CCITT (FALSE) of "123456789" is 0x29B1.
    assert _crc16_ccitt(b"123456789") == 0x29B1


def _route_one(payload: bytes) -> tuple[str, str, bytes]:
    """Feed a single frame and return the (addr, uuid, data) it routed to."""
    src = _make_source()
    received: list[tuple[str, str, bytes]] = []
    mgr = src.create_manager()
    mgr.set_notify_callback(lambda addr, uuid, data: received.append((addr, uuid, data)))
    mac = "AA:BB:CC:01:10:90"
    mgr.address = mac  # connect() sets this in the real flow
    src._register_manager(mac, mgr)  # type: ignore[attr-defined]
    src._devid_to_mac[7] = mac
    frame = _build_frame(site_id=1, dev_id=7, seq=3, payload=payload, rssi=-65)
    src._rxbuf.extend(frame)  # type: ignore[attr-defined]
    src._consume()  # type: ignore[attr-defined]
    src._loop.run_until_complete(asyncio.sleep(0))  # flush call_soon_threadsafe
    assert len(received) == 1
    return received[0]


def test_200b_length_frame_routes_to_200b_uuid():
    payload = bytes(i % 256 for i in range(200))  # 200B-sized payload
    addr, uuid, data = _route_one(payload)
    assert addr == "AA:BB:CC:01:10:90"
    assert uuid == UUID_NOTIFY_200B
    assert data == payload


def test_50_byte_frame_routes_to_iot_uuid():
    payload = bytes(range(50))  # legacy IOT packet size
    addr, uuid, data = _route_one(payload)
    assert uuid == UUID_IOT_NOTIFY
    assert data == payload


def test_tiny_control_frames_do_not_dispatch_notifications():
    src = _make_source()
    received: list[bytes] = []
    mgr = src.create_manager()
    mgr.set_notify_callback(lambda _a, _u, data: received.append(data))
    mac = "AA:BB:CC:01:10:90"
    mgr.address = mac
    src._register_manager(mac, mgr)  # type: ignore[attr-defined]
    src._devid_to_mac[7] = mac  # type: ignore[attr-defined]

    for seq, payload in enumerate((bytes(range(6)), b"\x13")):
        src._rxbuf.extend(_build_frame(1, 7, seq, payload, 0))  # type: ignore[attr-defined]
    src._consume()  # type: ignore[attr-defined]
    src._loop.run_until_complete(asyncio.sleep(0))

    assert received == []
    assert mgr._last_notify_monotonic is None  # type: ignore[attr-defined]


def test_bad_crc_frame_is_dropped():
    src = _make_source()
    received: list[bytes] = []
    mgr = src.create_manager()
    mgr.set_notify_callback(lambda a, u, d: received.append(d))
    mac = "AA:BB:CC:01:10:90"
    src._register_manager(mac, mgr)  # type: ignore[attr-defined]
    src._devid_to_mac[7] = mac

    frame = bytearray(_build_frame(1, 7, 0, bytes(50), -50))
    frame[-1] ^= 0xFF  # corrupt CRC high byte
    src._rxbuf.extend(frame)  # type: ignore[attr-defined]
    src._consume()  # type: ignore[attr-defined]
    src._loop.run_until_complete(asyncio.sleep(0))

    assert received == []


def test_mixed_text_and_binary_stream():
    src = _make_source()
    received: list[bytes] = []
    mgr = src.create_manager()
    mgr.set_notify_callback(lambda a, u, d: received.append(d))
    mac = "AA:BB:CC:01:10:90"
    src._register_manager(mac, mgr)  # type: ignore[attr-defined]
    src._devid_to_mac[7] = mac

    payload = bytes(range(50))
    frame = _build_frame(1, 7, 1, payload, -55)
    stream = b"SCAN STARTED\r\n" + frame + b"STATUS links=1/8\r\n"
    src._rxbuf.extend(stream)  # type: ignore[attr-defined]
    src._consume()  # type: ignore[attr-defined]
    src._loop.run_until_complete(asyncio.sleep(0))

    assert received == [payload]


def test_connected_line_builds_devid_mapping():
    src = _make_source()
    src._on_line("CONNECTED handle=2 #7 GIOS0403ST#7 MAC=AA:BB:CC:01:10:90")  # type: ignore[attr-defined]
    assert src._devid_to_mac.get(7) == "AA:BB:CC:01:10:90"  # type: ignore[attr-defined]
    assert src._handle_to_mac.get(2) == "AA:BB:CC:01:10:90"  # type: ignore[attr-defined]


def test_dongle_connect_commands_are_serialized():
    src, serial = _make_source_with_fake_serial()
    loop = src._loop  # type: ignore[attr-defined]

    first = loop.create_task(src._connect("AA:BB:CC:01:10:90"))  # type: ignore[attr-defined]
    second = loop.create_task(src._connect("AA:BB:CC:01:10:91"))  # type: ignore[attr-defined]
    loop.run_until_complete(asyncio.sleep(0))

    assert serial.writes == ["AT+CONN=AA:BB:CC:01:10:90"]

    src._on_line("CONNECTED handle=0 #7 GIOS0403ST#7 MAC=AA:BB:CC:01:10:90")  # type: ignore[attr-defined]
    loop.run_until_complete(asyncio.sleep(0))

    assert serial.writes == [
        "AT+CONN=AA:BB:CC:01:10:90",
        "AT+CONN=AA:BB:CC:01:10:91",
    ]

    src._on_line("CONNECTED handle=1 #8 GIOS0403ST#8 MAC=AA:BB:CC:01:10:91")  # type: ignore[attr-defined]
    loop.run_until_complete(asyncio.gather(first, second))


def test_dongle_connect_error_fails_active_connect_immediately():
    src, serial = _make_source_with_fake_serial()
    loop = src._loop  # type: ignore[attr-defined]
    task = loop.create_task(src._connect("AA:BB:CC:01:10:90"))  # type: ignore[attr-defined]
    loop.run_until_complete(asyncio.sleep(0))

    assert serial.writes == ["AT+CONN=AA:BB:CC:01:10:90"]

    src._on_line("ERROR:CONN 0x0008")  # type: ignore[attr-defined]
    with pytest.raises(RuntimeError, match="ERROR:CONN"):
        loop.run_until_complete(task)


def test_reader_exception_disconnects_all_managers_and_marks_source_unready():
    loop = asyncio.new_event_loop()
    source = DongleSource(
        "TEST",
        loop,
        serial_port=ReadFailSerial(),
        start_reader=False,
    )
    disconnects: list[str] = []
    pending_connect = loop.create_future()
    pending_scan = loop.create_future()
    pending_disconnect = loop.create_future()
    source._connect_futures["AA:BB:CC:01:10:92"] = pending_connect  # type: ignore[attr-defined]
    source._scan_future = pending_scan  # type: ignore[attr-defined]
    source._disconnect_futures["AA:BB:CC:01:10:93"] = pending_disconnect  # type: ignore[attr-defined]

    for index, mac in enumerate(
        ("AA:BB:CC:01:10:90", "AA:BB:CC:01:10:91")
    ):
        manager = source.create_manager()
        manager.address = mac
        manager._connected = True  # type: ignore[attr-defined]
        manager.set_disconnect_callback(disconnects.append)
        source._register_manager(mac, manager)  # type: ignore[attr-defined]
        source._handle_to_mac[index] = mac  # type: ignore[attr-defined]

    # Exercise the reader body synchronously, then flush any event-loop callback
    # that the transport-failure path scheduled from the reader thread.
    source._read_loop()  # type: ignore[attr-defined]
    loop.run_until_complete(asyncio.sleep(0))
    readiness = loop.run_until_complete(source.check_ready())

    assert disconnects == ["AA:BB:CC:01:10:90", "AA:BB:CC:01:10:91"]
    assert source._managers == {}  # type: ignore[attr-defined]
    assert source._needs_recovery is True  # type: ignore[attr-defined]
    assert isinstance(pending_connect.exception(), ConnectionError)
    assert isinstance(pending_scan.exception(), ConnectionError)
    assert isinstance(pending_disconnect.exception(), ConnectionError)
    assert readiness.status is not AdapterStatus.OK
    loop.close()


def test_serial_write_exception_fails_connect_immediately_and_marks_recovery():
    loop = asyncio.new_event_loop()
    source = DongleSource(
        "TEST",
        loop,
        serial_port=WriteFailSerial(),
        start_reader=False,
    )
    mac = "AA:BB:CC:01:10:90"

    # The outer timeout is only a test safety net. The expected failure must be
    # the serial write error itself, not the dongle's 35-second connect timeout.
    with pytest.raises(Exception, match="simulated serial write failure"):
        loop.run_until_complete(
            asyncio.wait_for(source._connect(mac), timeout=0.25)  # type: ignore[attr-defined]
        )

    assert source._needs_recovery is True  # type: ignore[attr-defined]


def test_manager_stays_registered_when_recovery_precedes_connect():
    source, serial = _make_source_with_fake_serial()
    loop = source._loop  # type: ignore[attr-defined]
    mac = "AA:BB:CC:01:10:90"
    manager = source.create_manager()
    notifications: list[bytes] = []
    disconnects: list[str] = []
    manager.set_notify_callback(lambda _a, _u, data: notifications.append(data))
    manager.set_disconnect_callback(disconnects.append)
    source._needs_recovery = True  # type: ignore[attr-defined]

    task = loop.create_task(manager.connect(mac))
    loop.run_until_complete(asyncio.sleep(0))
    assert serial.writes == [f"AT+CONN={mac}"]

    source._on_line(f"CONNECTED handle=0 #7 GIOS0403ST#7 MAC={mac}")  # type: ignore[attr-defined]
    loop.run_until_complete(task)
    assert source._managers.get(mac) is manager  # type: ignore[attr-defined]
    assert disconnects == []

    payload = bytes(index % 256 for index in range(200))
    source._rxbuf.extend(_build_frame(1, 7, 1, payload, -50))  # type: ignore[attr-defined]
    source._consume()  # type: ignore[attr-defined]
    loop.run_until_complete(asyncio.sleep(0))
    assert notifications == [payload]


def test_manager_connect_fails_if_link_drops_before_coroutine_resumes():
    source, _serial = _make_source_with_fake_serial()
    loop = source._loop  # type: ignore[attr-defined]
    mac = "AA:BB:CC:01:10:90"
    manager = source.create_manager()
    disconnects: list[str] = []
    manager.set_disconnect_callback(disconnects.append)

    task = loop.create_task(manager.connect(mac))
    loop.run_until_complete(asyncio.sleep(0))
    source._on_line(f"CONNECTED handle=0 #7 GIOS0403ST#7 MAC={mac}")  # type: ignore[attr-defined]
    source._on_line("DISCONNECTED handle=0 #7 GIOS0403ST#7 reason=0x13")  # type: ignore[attr-defined]

    with pytest.raises(ConnectionError, match="link disappeared"):
        loop.run_until_complete(task)
    assert manager.is_connected is False
    assert disconnects == []


def test_ensure_recovered_waits_without_queueing_second_reset(monkeypatch):
    source, _serial = _make_source_with_fake_serial()
    loop = source._loop  # type: ignore[attr-defined]
    loop.run_until_complete(source._recovery_lock.acquire())  # type: ignore[attr-defined]
    source._recovering = True  # type: ignore[attr-defined]
    source._needs_recovery = True  # type: ignore[attr-defined]
    recover_calls: list[str] = []

    async def unexpected_recover(reason: str) -> None:
        recover_calls.append(reason)

    monkeypatch.setattr(source, "recover", unexpected_recover)
    task = loop.create_task(source.ensure_recovered("test"))
    loop.run_until_complete(asyncio.sleep(0))
    assert not task.done()

    source._needs_recovery = False  # type: ignore[attr-defined]
    source._recovering = False  # type: ignore[attr-defined]
    source._recovery_lock.release()  # type: ignore[attr-defined]
    loop.run_until_complete(task)
    assert recover_calls == []


def test_reopen_serial_rejects_reader_that_does_not_stop():
    source, serial = _make_source_with_fake_serial()
    loop = source._loop  # type: ignore[attr-defined]

    class StuckReader:
        def __init__(self) -> None:
            self.join_timeouts: list[float | None] = []

        @staticmethod
        def is_alive() -> bool:
            return True

        def join(self, timeout: float | None = None) -> None:
            self.join_timeouts.append(timeout)

    reader = StuckReader()
    source._reader = reader  # type: ignore[assignment]

    with pytest.raises(OSError, match="reader did not stop"):
        source._reopen_serial()  # type: ignore[attr-defined]

    assert serial.is_open is False
    assert reader.join_timeouts == [1.5]
    assert source._reader is reader  # type: ignore[attr-defined]
    loop.close()


def test_connect_rechecks_recovery_after_preflight_waits(monkeypatch):
    source, serial = _make_source_with_fake_serial()
    loop = source._loop  # type: ignore[attr-defined]
    mac = "AA:BB:CC:01:10:90"
    recover_calls: list[str] = []

    async def transport_changes_while_waiting() -> None:
        source._needs_recovery = True  # type: ignore[attr-defined]

    async def recover_once(reason: str) -> None:
        recover_calls.append(reason)
        source._needs_recovery = False  # type: ignore[attr-defined]

    monkeypatch.setattr(source, "_settle_after_disconnect", transport_changes_while_waiting)
    monkeypatch.setattr(source, "recover", recover_once)
    task = loop.create_task(source._connect(mac))  # type: ignore[attr-defined]
    loop.run_until_complete(asyncio.sleep(0))

    assert recover_calls == ["transport changed while connect was waiting"]
    assert serial.writes == [f"AT+CONN={mac}"]
    source._on_line(f"CONNECTED handle=0 #7 GIOS0403ST#7 MAC={mac}")  # type: ignore[attr-defined]
    loop.run_until_complete(task)


def test_recover_rejects_a_dead_reopened_reader(monkeypatch):
    source, _serial = _make_source_with_fake_serial()
    loop = source._loop  # type: ignore[attr-defined]
    source._owns_serial = True  # type: ignore[attr-defined]
    monkeypatch.setattr(ds, "_DONGLE_POST_RESET_SETTLE_SECONDS", 0.0)

    class DeadReader:
        @staticmethod
        def is_alive() -> bool:
            return False

    def reopen_with_dead_reader() -> None:
        source._running = True  # type: ignore[attr-defined]
        source._reader = DeadReader()  # type: ignore[attr-defined]

    monkeypatch.setattr(source, "_reopen_serial", reopen_with_dead_reader)
    with pytest.raises(ConnectionError, match="reader did not survive"):
        loop.run_until_complete(source.recover("test dead reader"))

    assert source._needs_recovery is True  # type: ignore[attr-defined]
    assert source._recovering is False  # type: ignore[attr-defined]
    loop.close()


def test_dongle_keeper_recovers_stale_connection_when_no_frames_arrive():
    source, _serial = _make_source_with_fake_serial()
    loop = source._loop  # type: ignore[attr-defined]
    manager = source.create_manager()
    mac = "AA:BB:CC:01:10:90"

    connect_task = loop.create_task(manager.connect(mac))
    loop.run_until_complete(asyncio.sleep(0))
    source._on_line(  # type: ignore[attr-defined]
        f"CONNECTED handle=0 #7 GIOS0403ST#7 MAC={mac}"
    )
    loop.run_until_complete(connect_task)

    stale_managers: list[object] = []

    async def recover_stale(stale_manager: object) -> None:
        stale_managers.append(stale_manager)
        manager._connected = False  # type: ignore[attr-defined]

    source._handle_stream_stale = recover_stale  # type: ignore[method-assign]

    async def exercise_keeper() -> None:
        manager.start_200b_keeper(interval=0.01, stale_after=0.02)
        await asyncio.sleep(0.08)
        manager.stop_200b_keeper()

    loop.run_until_complete(exercise_keeper())

    assert stale_managers == [manager]
    loop.close()


def test_disconnected_line_dispatches_to_manager():
    src = _make_source()
    events: list[str] = []
    mgr = src.create_manager()
    mgr.set_disconnect_callback(lambda addr: events.append(addr))
    mac = "AA:BB:CC:01:10:90"
    mgr.address = mac  # connect() sets this in the real flow
    mgr._connected = True  # type: ignore[attr-defined]
    src._register_manager(mac, mgr)  # type: ignore[attr-defined]
    src._handle_to_mac[2] = mac  # type: ignore[attr-defined]

    src._on_line("DISCONNECTED handle=2 #7 GIOS0403ST#7 reason=0x13")  # type: ignore[attr-defined]
    assert events == [mac]


def test_dongle_disconnect_waits_for_disconnected_line_before_unregistering():
    src, serial = _make_source_with_fake_serial()
    loop = src._loop  # type: ignore[attr-defined]
    events: list[str] = []
    mgr = src.create_manager()
    mgr.set_disconnect_callback(lambda addr: events.append(addr))
    mac = "AA:BB:CC:01:10:90"
    mgr.address = mac  # connect() sets this in the real flow
    mgr._connected = True  # type: ignore[attr-defined]
    src._register_manager(mac, mgr)  # type: ignore[attr-defined]
    src._handle_to_mac[2] = mac  # type: ignore[attr-defined]
    src._devid_to_mac[7] = mac  # type: ignore[attr-defined]

    task = loop.create_task(mgr.disconnect())
    loop.run_until_complete(asyncio.sleep(0))

    assert serial.writes == [f"AT+DISC={mac}"]
    assert src._managers.get(mac) is mgr  # type: ignore[attr-defined]
    assert src._handle_to_mac.get(2) == mac  # type: ignore[attr-defined]

    src._on_line("DISCONNECTED handle=2 #7 GIOS0403ST#7 reason=0x13")  # type: ignore[attr-defined]
    loop.run_until_complete(task)

    assert events == [mac]
    assert mac not in src._managers  # type: ignore[attr-defined]
    assert 2 not in src._handle_to_mac  # type: ignore[attr-defined]
    assert 7 not in src._devid_to_mac  # type: ignore[attr-defined]


def test_dongle_scan_waits_for_pending_disconnect_before_starting():
    src, serial = _make_source_with_fake_serial()
    loop = src._loop  # type: ignore[attr-defined]
    mac = "AA:BB:CC:01:10:90"
    future = loop.create_future()
    src._disconnect_futures[mac] = future  # type: ignore[attr-defined]

    task = loop.create_task(src.scan(timeout=0.01))
    loop.run_until_complete(asyncio.sleep(0))

    assert serial.writes == []

    future.set_result(True)
    loop.run_until_complete(asyncio.sleep(0.05))
    assert serial.writes == ["AT+SCAN", "AT+STOP", "AT+LIST"]

    src._on_line("SCAN LIST: 0")  # type: ignore[attr-defined]
    assert loop.run_until_complete(task) == []


def test_connect_settles_after_recent_disconnect_before_at_conn():
    # A connect that follows a recent disconnect must wait the firmware-settle
    # window before issuing AT+CONN, so the dongle is not asked to connect while
    # its BLE central is still releasing the previous link.
    src, serial = _make_source_with_fake_serial()
    loop = src._loop  # type: ignore[attr-defined]
    mac = "AA:BB:CC:01:10:90"
    # Simulate a disconnect that just happened.
    src._last_disconnect_monotonic = loop.time()  # type: ignore[attr-defined]

    task = loop.create_task(src._connect(mac))  # type: ignore[attr-defined]
    loop.run_until_complete(asyncio.sleep(0))
    # Still inside the settle window -> AT+CONN not sent yet.
    assert serial.writes == []

    # After the settle window elapses, AT+CONN goes out.
    loop.run_until_complete(
        asyncio.sleep(ds._DONGLE_POST_DISCONNECT_SETTLE_SECONDS + 0.05)
    )
    assert serial.writes == [f"AT+CONN={mac}"]

    src._on_line(f"CONNECTED handle=0 #7 GIOS0403ST#7 MAC={mac}")  # type: ignore[attr-defined]
    loop.run_until_complete(task)


def test_connect_waits_for_in_progress_scan():
    # A connect must not multiplex AT+CONN onto the serial link while a scan is
    # running; it waits until the scan marks itself idle.
    src, serial = _make_source_with_fake_serial()
    loop = src._loop  # type: ignore[attr-defined]
    mac = "AA:BB:CC:01:10:90"
    src._scan_idle.clear()  # type: ignore[attr-defined]  # pretend a scan is running

    task = loop.create_task(src._connect(mac))  # type: ignore[attr-defined]
    loop.run_until_complete(asyncio.sleep(0))
    assert serial.writes == []  # blocked on scan-idle

    src._scan_idle.set()  # type: ignore[attr-defined]  # scan finished
    loop.run_until_complete(asyncio.sleep(0))
    assert serial.writes == [f"AT+CONN={mac}"]

    src._on_line(f"CONNECTED handle=0 #7 GIOS0403ST#7 MAC={mac}")  # type: ignore[attr-defined]
    loop.run_until_complete(task)


def test_scan_recovers_when_connect_left_dongle_wedged():
    # A connect that timed out flags recovery; the next scan must reset link
    # state (drop managers/handles) before issuing AT+SCAN.
    src, serial = _make_source_with_fake_serial()
    loop = src._loop  # type: ignore[attr-defined]
    mac = "AA:BB:CC:01:10:90"
    mgr = src.create_manager()
    events: list[str] = []
    mgr.set_disconnect_callback(lambda addr: events.append(addr))
    mgr.address = mac
    mgr._connected = True  # type: ignore[attr-defined]
    src._register_manager(mac, mgr)  # type: ignore[attr-defined]
    src._handle_to_mac[0] = mac  # type: ignore[attr-defined]
    src._needs_recovery = True  # type: ignore[attr-defined]

    task = loop.create_task(src.scan(timeout=0.01))
    loop.run_until_complete(asyncio.sleep(0.05))

    # Recovery dropped the stale link and notified the manager, then scanned.
    assert events == [mac]
    assert mac not in src._managers  # type: ignore[attr-defined]
    assert src._needs_recovery is False  # type: ignore[attr-defined]
    assert serial.writes == ["AT+SCAN", "AT+STOP", "AT+LIST"]

    src._on_line("SCAN LIST: 0")  # type: ignore[attr-defined]
    assert loop.run_until_complete(task) == []


def test_recover_fails_pending_connect_and_resets_state():
    src, _serial = _make_source_with_fake_serial()
    loop = src._loop  # type: ignore[attr-defined]
    mac = "AA:BB:CC:01:10:90"
    future = loop.create_future()
    src._connect_futures[mac] = future  # type: ignore[attr-defined]
    src._handle_to_mac[3] = mac  # type: ignore[attr-defined]
    src._devid_to_mac[5] = mac  # type: ignore[attr-defined]
    mgr = src.create_manager()
    mgr.address = mac
    src._register_manager(mac, mgr)  # type: ignore[attr-defined]

    loop.run_until_complete(src.recover("test"))

    assert future.done() and future.exception() is not None
    assert src._handle_to_mac == {}  # type: ignore[attr-defined]
    assert src._devid_to_mac == {}  # type: ignore[attr-defined]
    assert src._managers == {}  # type: ignore[attr-defined]
    assert src._needs_recovery is False  # type: ignore[attr-defined]


def test_disconnect_timeout_swallows_stale_disconnected_on_reused_handle(monkeypatch):
    # When AT+DISC times out, the firmware still owes a (now stale) DISCONNECTED.
    # If the same handle number is later reused by a fresh link, that stale line
    # must NOT tear the fresh link down.
    monkeypatch.setattr(ds, "_DONGLE_DISCONNECT_TIMEOUT_SECONDS", 0.02)
    src, serial = _make_source_with_fake_serial()
    loop = src._loop  # type: ignore[attr-defined]
    mac = "AA:BB:CC:01:10:90"

    # First link on handle 0; disconnect it but the firmware never acks.
    mgr1 = src.create_manager()
    mgr1.address = mac
    mgr1._connected = True  # type: ignore[attr-defined]
    src._register_manager(mac, mgr1)  # type: ignore[attr-defined]
    src._handle_to_mac[0] = mac  # type: ignore[attr-defined]
    task = loop.create_task(mgr1.disconnect())
    # Drive the disconnect to its timeout (no DISCONNECTED line arrives).
    loop.run_until_complete(asyncio.sleep(0.1))
    loop.run_until_complete(task)
    assert 0 in src._stale_disconnect_handles  # type: ignore[attr-defined]

    # Reconnect reuses handle 0 for a fresh manager.
    events: list[str] = []
    mgr2 = src.create_manager()
    mgr2.address = mac
    mgr2._connected = True  # type: ignore[attr-defined]
    mgr2.set_disconnect_callback(lambda addr: events.append(addr))
    src._register_manager(mac, mgr2)  # type: ignore[attr-defined]
    src._on_line(f"CONNECTED handle=0 #7 GIOS0403ST#7 MAC={mac}")  # type: ignore[attr-defined]

    # The belated DISCONNECTED for the OLD link finally arrives.
    src._on_line("DISCONNECTED handle=0 #7 GIOS0403ST#7 reason=0x13")  # type: ignore[attr-defined]
    assert events == []  # fresh link NOT torn down
    assert src._managers.get(mac) is mgr2  # type: ignore[attr-defined]
    assert 0 not in src._stale_disconnect_handles  # type: ignore[attr-defined]

    # A subsequent real DISCONNECTED for the fresh link tears it down normally.
    src._on_line("DISCONNECTED handle=0 #7 GIOS0403ST#7 reason=0x13")  # type: ignore[attr-defined]
    assert events == [mac]


def test_scan_results_parsed_from_at_list():
    # Real firmware emits the base name with the device id in the "#" field;
    # the display name must combine them like the PC scan does.
    results = DongleSource._parse_scan_results(
        [
            "1: #45 GIOS0801ST RSSI=-48 MAC=90:04:22:B6:96:00",
            "2: #- GIOS0403ST RSSI=-70 MAC=AA:BB:CC:DD:EE:FF",
        ]
    )
    assert [r.address for r in results] == ["90:04:22:B6:96:00", "AA:BB:CC:DD:EE:FF"]
    assert results[0].name == "GIOS0801ST#45"  # base name + device number
    assert results[0].device_number == 45
    assert results[0].rssi == -48
    assert results[1].name == "GIOS0403ST"
    assert results[1].device_number is None


def test_scan_name_not_double_numbered_when_firmware_includes_hash():
    results = DongleSource._parse_scan_results(
        ["1: #4 GIOS0403ST#4 RSSI=-55 MAC=90:6C:0A:C9:96:00"]
    )
    assert results[0].name == "GIOS0403ST#4"  # no double "#4#4"
    assert results[0].device_number == 4


def test_scan_results_parsed_from_live_found_update_lines():
    results = DongleSource._parse_scan_results(
        [
            "FOUND 1: #0 GIOS0403ST RSSI=-73 MAC=2F:F7:DD:71:B4:81",
            "UPDATE 1: #71 GIOS0403ST RSSI=-73 MAC=2F:F7:DD:71:B4:81",
            "FOUND 2: #0 GIOS-S20-GW01 RSSI=-38 MAC=A0:DD:6C:A3:70:F2",
            "FOUND 3: #0 GIOS0801ST RSSI=-31 MAC=90:04:22:B6:96:00",
            "UPDATE 3: #45 GIOS0801ST RSSI=-31 MAC=90:04:22:B6:96:00",
        ]
    )

    assert [(result.address, result.name, result.device_number) for result in results] == [
        ("2F:F7:DD:71:B4:81", "GIOS0403ST#71", 71),
        ("A0:DD:6C:A3:70:F2", "GIOS-S20-GW01#0", 0),
        ("90:04:22:B6:96:00", "GIOS0801ST#45", 45),
    ]


def test_scan_collects_live_found_update_before_at_list():
    src = _make_source()
    future = src._loop.create_future()  # type: ignore[attr-defined]
    src._scan_debug = True  # type: ignore[attr-defined]

    src._on_line("FOUND 3: #0 GIOS0801ST RSSI=-31 MAC=90:04:22:B6:96:00")  # type: ignore[attr-defined]
    src._on_line("UPDATE 3: #45 GIOS0801ST RSSI=-31 MAC=90:04:22:B6:96:00")  # type: ignore[attr-defined]
    src._scan_future = future  # type: ignore[attr-defined]
    src._on_line("SCAN LIST: 0")  # type: ignore[attr-defined]

    results = DongleSource._parse_scan_results(src._scan_lines)  # type: ignore[attr-defined]
    assert [(result.address, result.name, result.device_number) for result in results] == [
        ("90:04:22:B6:96:00", "GIOS0801ST#45", 45),
    ]


class _LiveReader:
    @staticmethod
    def is_alive() -> bool:
        return True


def test_recover_keeps_needs_recovery_when_firmware_probe_gets_no_response(monkeypatch):
    # A reopened CDC handle is NOT proof the MCU reset took.  When the firmware
    # never answers the AT+STATUS liveness probe, recover() must NOT clear
    # needs_recovery / log false success; it must fail so the next attempt
    # retries the full reset cycle.
    source, serial = _make_source_with_fake_serial()
    loop = source._loop  # type: ignore[attr-defined]
    source._owns_serial = True  # type: ignore[attr-defined]
    monkeypatch.setattr(ds, "_DONGLE_POST_RESET_SETTLE_SECONDS", 0.0)
    monkeypatch.setattr(ds, "_DONGLE_PROBE_TIMEOUT_SECONDS", 0.01)
    monkeypatch.setattr(ds, "_DONGLE_PROBE_ATTEMPTS", 2)

    def reopen_ok() -> None:
        # Serial reopened and reader alive, but nothing feeds a STATUS line.
        serial.is_open = True
        source._reader = _LiveReader()  # type: ignore[attr-defined]

    monkeypatch.setattr(source, "_reopen_serial", reopen_ok)

    with pytest.raises(ConnectionError, match="did not answer AT\\+STATUS"):
        loop.run_until_complete(source.recover("probe timeout test"))

    assert source._needs_recovery is True  # type: ignore[attr-defined]
    assert source._recovering is False  # type: ignore[attr-defined]
    assert "AT+STATUS" in serial.writes  # the probe actually went out on the wire
    loop.close()


def test_recover_succeeds_when_firmware_answers_probe(monkeypatch):
    # When the firmware replies to AT+STATUS, the handshake gate passes and
    # recovery clears needs_recovery as before.
    source, serial = _make_source_with_fake_serial()
    loop = source._loop  # type: ignore[attr-defined]
    source._owns_serial = True  # type: ignore[attr-defined]
    monkeypatch.setattr(ds, "_DONGLE_POST_RESET_SETTLE_SECONDS", 0.0)
    monkeypatch.setattr(ds, "_DONGLE_PROBE_TIMEOUT_SECONDS", 1.0)

    def reopen_ok() -> None:
        serial.is_open = True
        source._reader = _LiveReader()  # type: ignore[attr-defined]

    monkeypatch.setattr(source, "_reopen_serial", reopen_ok)

    async def answer_probe() -> None:
        for _ in range(200):
            if source._probe_future is not None:  # type: ignore[attr-defined]
                break
            await asyncio.sleep(0.005)
        source._on_line("STATUS links=0/8 connecting=0 scanning=0")  # type: ignore[attr-defined]

    async def drive() -> None:
        answer = loop.create_task(answer_probe())
        await source.recover("probe ok test")
        await answer

    loop.run_until_complete(drive())

    assert source._needs_recovery is False  # type: ignore[attr-defined]
    assert source._recovering is False  # type: ignore[attr-defined]
    loop.close()


def test_prepare_reconnect_sends_per_device_disc_before_at_conn():
    # A reconnect must clear the firmware's latched per-device link with a
    # per-device AT+DISC (not the global AT+DISC that would drop other links).
    src, serial = _make_source_with_fake_serial()
    loop = src._loop  # type: ignore[attr-defined]
    mac = "AA:BB:CC:01:10:90"

    loop.run_until_complete(src.prepare_reconnect(mac))

    assert serial.writes == [f"AT+DISC={mac}"]
    # The disconnect timestamp is recorded so the following AT+CONN settles.
    assert src._last_disconnect_monotonic is not None  # type: ignore[attr-defined]
    loop.close()
