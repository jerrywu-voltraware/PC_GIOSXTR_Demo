"""Hardware-free tests for the Nordic dongle data source.

These exercise the byte-stream demux, CRC validation, frame->notify routing,
and AT scan-list parsing against the exact formats produced by the firmware
(send_binary_packet / scan_device_print / CONNECTED messages).
"""

from __future__ import annotations

import asyncio

import pytest

from app import device_source as ds
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


def test_disconnected_line_dispatches_to_manager():
    src = _make_source()
    events: list[str] = []
    mgr = src.create_manager()
    mgr.set_disconnect_callback(lambda addr: events.append(addr))
    mac = "AA:BB:CC:01:10:90"
    mgr.address = mac  # connect() sets this in the real flow
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
