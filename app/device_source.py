"""Pluggable device data sources for PC_GIOSXTR_Demo.

The app supports two ways of reaching the GIOSXTR devices:

* **PC built-in Bluetooth** (`PcBleSource`) — the original behaviour: bleak talks
  to the OS Bluetooth radio directly. Unchanged.
* **Nordic dongle** (`DongleSource`) — for PCs without built-in Bluetooth. The
  nRF52840 dongle is the BLE central; the PC drives it over USB CDC (AT commands
  for scan/connect/disconnect, binary frames carrying the raw 200B payload).

`MainWindow` talks to a `DeviceSource` instead of constructing `BleManager`
directly, so the same UI / decoding / chart / CSV pipeline is fed by either
backend. Both sources produce the same `(address, uuid, data)` notifications and
the same `DeviceScanResult` list, so nothing downstream of the source changes.
"""

from __future__ import annotations

import asyncio
import re
import threading
from abc import ABC, abstractmethod
from typing import Callable, Protocol, runtime_checkable

from .ble_adapter import AdapterCheckResult, AdapterStatus, check_bluetooth_adapter
from .ble_manager import BleManager, DeviceScanResult, _write_scan_debug
from .constants import UUID_IOT_NOTIFY, UUID_NOTIFY_200B

NotifyCallback = Callable[[str, str, bytes], None]
DisconnectCallback = Callable[[str], None]


@runtime_checkable
class DeviceManager(Protocol):
    """Per-device connection handle used by MainWindow.

    `BleManager` already satisfies this protocol structurally; `DongleSource`
    provides its own implementation that maps each call onto an AT command.
    """

    address: str

    @property
    def is_connected(self) -> bool: ...

    def set_notify_callback(self, callback: NotifyCallback | None) -> None: ...

    def set_disconnect_callback(self, callback: DisconnectCallback | None) -> None: ...

    async def connect(self, address: str) -> None: ...

    async def disconnect(self) -> None: ...

    async def enable_default_notifications(self) -> None: ...

    async def request_200b(self) -> None: ...

    def start_200b_keeper(self, **kwargs: object) -> None: ...

    def stop_200b_keeper(self) -> None: ...

    async def write_device_number(self, number: int) -> None: ...

    async def reset_device_number(self) -> None: ...


class DeviceSource(ABC):
    """A backend that can scan for devices and hand out per-device managers."""

    #: Human-readable name shown in the source-selection dialog.
    display_name: str = "Device source"

    #: Whether PC->device control writes (set/reset device number) are available.
    supports_control: bool = True

    #: When True, the UI must wait until a freshly-connected device starts
    #: streaming (first packet) before initiating the next connection. The
    #: dongle cannot initiate a new connection while a previous link is still in
    #: GATT discovery, so connecting too early hangs it.
    requires_ready_before_next_connect: bool = False

    @abstractmethod
    async def scan(
        self, timeout: float = 5.0, supported_only: bool = True
    ) -> list[DeviceScanResult]:
        """Return the list of connectable devices."""

    @abstractmethod
    def create_manager(self) -> DeviceManager:
        """Create a fresh per-device connection handle."""

    async def check_ready(self) -> AdapterCheckResult:
        """Readiness gate evaluated before scanning.

        Default checks the OS Bluetooth adapter (PC built-in Bluetooth). Sources
        that do not rely on the OS radio (e.g. the dongle) override this.
        """
        return await check_bluetooth_adapter()

    async def close(self) -> None:
        """Release any backend resources (serial port, tasks). Default: no-op."""
        self.shutdown()

    def shutdown(self) -> None:
        """Synchronous resource release (serial port, threads). Default: no-op.

        Used before an app restart where awaiting close() is not possible.
        """
        return None


class PcBleSource(DeviceSource):
    """PC built-in Bluetooth via bleak. Thin wrapper over the original path."""

    display_name = "PC 內建藍牙"
    supports_control = True

    async def scan(
        self, timeout: float = 5.0, supported_only: bool = True
    ) -> list[DeviceScanResult]:
        return await BleManager.scan(timeout=timeout, supported_only=supported_only)

    def create_manager(self) -> DeviceManager:
        return BleManager()


# ---------------------------------------------------------------------------
# Nordic dongle source (USB CDC bridge)
# ---------------------------------------------------------------------------

# Binary uplink frame layout (see firmware send_binary_packet):
#   AA 55 | SITE_ID(2,LE) | DEV_ID(1) | SEQ(2,LE) | LEN(1) | PAYLOAD(LEN) |
#   RSSI(1) | CRC16(2,LE)
_SOF0 = 0xAA
_SOF1 = 0x55
_PKT_HEADER = 8  # SOF(2)+SITE_ID(2)+DEV_ID(1)+SEQ(2)+LEN(1)
_PKT_FOOTER = 3  # RSSI(1)+CRC16(2)
_IOT_PACKET_LEN = 50  # legacy IOT packet size (sizeof iot_packet_t); else 200B

# AT response line patterns emitted by the firmware.
_SCAN_LIST_HDR = re.compile(r"^SCAN LIST:\s+(\d+)")
_SCAN_LINE = re.compile(
    r"^\s*(\d+):\s+#(\d+|-)\s+(.+?)\s+RSSI=(-?\d+)\s+MAC=([0-9A-Fa-f:]{17})\s*$"
)
_SCAN_EVENT_LINE = re.compile(
    r"^\s*(?:FOUND|UPDATE)\s+(\d+):\s+#(\d+|-)\s+(.+?)\s+RSSI=(-?\d+)\s+MAC=([0-9A-Fa-f:]{17})\s*$"
)
_CONNECTED = re.compile(
    r"^CONNECTED handle=(\d+)\s+#(\d+|-)\s+(.+?)\s+MAC=([0-9A-Fa-f:]{17})"
)
_DISCONNECTED = re.compile(r"^DISCONNECTED handle=(\d+)")
_CONNECT_ERROR_PREFIXES = (
    "ERROR:CONN",
    "ERROR:CONNECTING",
    "ERROR:MAX LINKS",
    "ERROR:NOTFOUND",
    "ERROR:INDEX",
    "ERROR:MAC",
    "CONNECT ERROR:",
    "CONNECT TIMEOUT",
)
_DONGLE_CONNECT_TIMEOUT_SECONDS = 35.0
_DONGLE_DISCONNECT_TIMEOUT_SECONDS = 5.0


def _crc16_ccitt(data: bytes) -> int:
    """CRC16-CCITT (FALSE): init 0xFFFF, poly 0x1021, MSB-first. Matches firmware."""
    crc = 0xFFFF
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = ((crc << 1) ^ 0x1021) & 0xFFFF
            else:
                crc = (crc << 1) & 0xFFFF
    return crc


class DongleDeviceManager:
    """Per-device handle for the dongle backend; maps calls onto AT commands.

    Structurally satisfies the DeviceManager protocol used by MainWindow.
    """

    def __init__(self, source: "DongleSource") -> None:
        self._source = source
        self.address: str = ""
        self._notify_callback: NotifyCallback | None = None
        self._disconnect_callback: DisconnectCallback | None = None
        self._connected = False

    @property
    def is_connected(self) -> bool:
        return self._connected

    def set_notify_callback(self, callback: NotifyCallback | None) -> None:
        self._notify_callback = callback

    def set_disconnect_callback(self, callback: DisconnectCallback | None) -> None:
        self._disconnect_callback = callback

    async def connect(self, address: str) -> None:
        self.address = address.upper()
        self._source._register_manager(self.address, self)
        try:
            await self._source._connect(self.address)
        except Exception:
            self._source._unregister_manager(self.address)
            raise
        self._connected = True

    async def disconnect(self) -> None:
        address = self.address
        if address:
            try:
                await self._source._disconnect(address)
            finally:
                self._connected = False
                self._source._unregister_manager(address)
        else:
            self._connected = False

    async def enable_default_notifications(self) -> None:
        # The dongle subscribes to the device's 200B characteristic itself.
        return None

    async def request_200b(self) -> None:
        # The firmware runs its own 200B keeper; nothing to do here.
        return None

    def start_200b_keeper(self, **kwargs: object) -> None:
        return None

    def stop_200b_keeper(self) -> None:
        return None

    async def write_device_number(self, number: int) -> None:
        self._source._send_command(f"AT+DEVNUM={self.address},{number}")

    async def reset_device_number(self) -> None:
        self._source._send_command(f"AT+DEVNUM={self.address},255")

    # -- called by the source (in the event-loop thread) ---------------------

    def _dispatch_notify(self, uuid: str, payload: bytes) -> None:
        if self._notify_callback is not None:
            self._notify_callback(self.address, uuid, payload)

    def _dispatch_disconnect(self) -> None:
        self._connected = False
        if self._disconnect_callback is not None:
            self._disconnect_callback(self.address)


class DongleSource(DeviceSource):
    """nRF52840 dongle over USB CDC.

    A single serial connection multiplexes every device. A background reader
    thread demuxes the byte stream into binary 200B frames (routed to the right
    DongleDeviceManager by device id) and AT response lines (scan list, connect
    / disconnect notifications). AT commands are written from the asyncio side.
    """

    display_name = "Nordic dongle"
    supports_control = True
    requires_ready_before_next_connect = True

    def __init__(
        self,
        port: str,
        loop: asyncio.AbstractEventLoop,
        baudrate: int = 115200,
        *,
        serial_port: object | None = None,
        start_reader: bool = True,
    ) -> None:
        self._loop = loop
        self._port_name = port
        if serial_port is not None:
            # Injected for testing.
            self._serial = serial_port
        else:
            import serial  # imported lazily so the app runs without pyserial

            self._serial = serial.Serial(port, baudrate, timeout=0.1)
        self._write_lock = threading.Lock()

        self._managers: dict[str, DongleDeviceManager] = {}
        self._devid_to_mac: dict[int, str] = {}
        self._handle_to_mac: dict[int, str] = {}

        self._rxbuf = bytearray()
        self._running = True

        # Async coordination for scan / connect.
        self._scan_future: asyncio.Future[bool] | None = None
        self._scan_lines: list[str] = []
        self._scan_expect: int | None = None
        self._scan_debug = False  # log every received line during scan() window
        self._connect_futures: dict[str, asyncio.Future[bool]] = {}
        self._disconnect_futures: dict[str, asyncio.Future[bool]] = {}
        self._connect_lock = asyncio.Lock()
        self._active_connect_mac: str | None = None

        self._reader: threading.Thread | None = None
        if start_reader:
            self._reader = threading.Thread(
                target=self._read_loop, name="dongle-reader", daemon=True
            )
            self._reader.start()

    # -- DeviceSource API ----------------------------------------------------

    async def check_ready(self) -> AdapterCheckResult:
        if self._serial is not None and self._serial.is_open:
            return AdapterCheckResult(AdapterStatus.OK, f"Dongle on {self._port_name}")
        return AdapterCheckResult(
            AdapterStatus.NO_ADAPTER, "Dongle serial port is not open"
        )

    def create_manager(self) -> DeviceManager:
        return DongleDeviceManager(self)

    async def scan(
        self, timeout: float = 5.0, supported_only: bool = True
    ) -> list[DeviceScanResult]:
        await self._wait_for_pending_disconnects()
        # Start scanning, let advertisements accumulate, then pull the list.
        self._scan_lines = []
        self._scan_expect = None
        _write_scan_debug("dongle scan: AT+SCAN")
        self._scan_debug = True
        self._send_command("AT+SCAN")
        await asyncio.sleep(timeout)
        _write_scan_debug("dongle scan: AT+STOP")
        self._send_command("AT+STOP")

        future: asyncio.Future[bool] = self._loop.create_future()
        self._scan_future = future
        self._scan_expect = None
        _write_scan_debug("dongle scan: AT+LIST")
        self._send_command("AT+LIST")
        try:
            await asyncio.wait_for(future, timeout=3.0)
        except asyncio.TimeoutError:
            _write_scan_debug("dongle scan: AT+LIST timed out (no SCAN LIST received)")
        finally:
            self._scan_future = None
            self._scan_debug = False
        results = self._parse_scan_results(self._scan_lines)
        _write_scan_debug(
            f"dongle scan: parsed {len(results)} device(s) from "
            f"{len(self._scan_lines)} collected line(s)"
        )
        return results

    async def close(self) -> None:
        self.shutdown()

    def shutdown(self) -> None:
        self._running = False
        try:
            if self._serial is not None and self._serial.is_open:
                self._serial.close()
        except Exception:
            pass

    # -- command sending -----------------------------------------------------

    def _send_command(self, text: str) -> None:
        try:
            with self._write_lock:
                self._serial.write((text + "\r\n").encode("ascii"))
        except Exception:
            pass

    # -- manager registry ----------------------------------------------------

    def _register_manager(self, mac: str, manager: DongleDeviceManager) -> None:
        self._managers[mac] = manager

    def _unregister_manager(self, mac: str) -> None:
        self._managers.pop(mac, None)
        for dev_id in [d for d, m in self._devid_to_mac.items() if m == mac]:
            self._devid_to_mac.pop(dev_id, None)
        for handle in [h for h, m in self._handle_to_mac.items() if m == mac]:
            self._handle_to_mac.pop(handle, None)

    async def _connect(self, mac: str) -> None:
        async with self._connect_lock:
            future: asyncio.Future[bool] = self._loop.create_future()
            self._connect_futures[mac] = future
            self._active_connect_mac = mac
            self._send_command(f"AT+CONN={mac}")
            try:
                await asyncio.wait_for(future, timeout=_DONGLE_CONNECT_TIMEOUT_SECONDS)
            except asyncio.TimeoutError as exc:
                raise TimeoutError(f"Dongle connect timed out for {mac}") from exc
            finally:
                self._connect_futures.pop(mac, None)
                if self._active_connect_mac == mac:
                    self._active_connect_mac = None

    async def _disconnect(self, mac: str) -> None:
        future: asyncio.Future[bool] = self._loop.create_future()
        self._disconnect_futures[mac] = future
        self._send_command(f"AT+DISC={mac}")
        try:
            await asyncio.wait_for(future, timeout=_DONGLE_DISCONNECT_TIMEOUT_SECONDS)
        except asyncio.TimeoutError:
            _write_scan_debug(f"dongle disconnect timed out for {mac}")
        finally:
            self._disconnect_futures.pop(mac, None)

    async def _wait_for_pending_disconnects(self) -> None:
        futures = [future for future in self._disconnect_futures.values() if not future.done()]
        if not futures:
            return
        _write_scan_debug(f"dongle scan: waiting for {len(futures)} pending disconnect(s)")
        done, pending = await asyncio.wait(
            futures,
            timeout=_DONGLE_DISCONNECT_TIMEOUT_SECONDS,
        )
        if pending:
            _write_scan_debug(
                f"dongle scan: {len(pending)} pending disconnect(s) still incomplete"
            )

    @staticmethod
    def _parse_scan_results(lines: list[str]) -> list[DeviceScanResult]:
        results_by_mac: dict[str, DeviceScanResult] = {}
        for line in lines:
            match = _SCAN_LINE.match(line) or _SCAN_EVENT_LINE.match(line)
            if not match:
                continue
            dev_id_text = match.group(2)
            base_name = match.group(3).strip()
            device_number = None if dev_id_text == "-" else int(dev_id_text)
            # Mirror the PC scan display: combine base name + device number
            # ("GIOS0801ST" + 45 -> "GIOS0801ST#45"). Guard against firmware
            # names that already carry a "#".
            if device_number is not None and "#" not in base_name:
                display_name = f"{base_name}#{device_number}"
            else:
                display_name = base_name
            mac = match.group(5).upper()
            results_by_mac[mac] = DeviceScanResult(
                address=mac,
                name=display_name,
                rssi=int(match.group(4)),
                raw_hex="",
                advertising_rows=[],
                device_number=device_number,
                firmware_revision=None,
            )
        return list(results_by_mac.values())

    # -- reader thread -------------------------------------------------------

    def _read_loop(self) -> None:
        while self._running:
            try:
                chunk = self._serial.read(256)
            except Exception:
                break
            if not chunk:
                continue
            self._rxbuf.extend(chunk)
            self._consume()

    def _consume(self) -> None:
        buf = self._rxbuf
        while buf:
            if buf[0] == _SOF0:
                if len(buf) < 2:
                    break
                if buf[1] == _SOF1:
                    if len(buf) < _PKT_HEADER:
                        break
                    length = buf[7]
                    total = _PKT_HEADER + length + _PKT_FOOTER
                    if len(buf) < total:
                        break
                    frame = bytes(buf[:total])
                    if self._handle_frame(frame):
                        del buf[:total]
                    else:
                        del buf[:1]  # bad CRC: drop one byte and resync
                    continue
                # 0xAA not followed by 0x55 -> treat the stray byte as text.
                del buf[:1]
                continue

            # Text path: emit up to the next newline or the next frame start.
            aa = buf.find(b"\xaa")
            nl = buf.find(b"\n")
            if aa != -1 and (nl == -1 or aa < nl):
                line = bytes(buf[:aa])
                del buf[:aa]
                self._emit_text(line)
                continue
            if nl == -1:
                if len(buf) > 4096:  # guard against unbounded garbage
                    del buf[: len(buf)]
                break
            line = bytes(buf[:nl])
            del buf[: nl + 1]
            self._emit_text(line)

    def _handle_frame(self, frame: bytes) -> bool:
        if _crc16_ccitt(frame[2:-2]) != (frame[-2] | (frame[-1] << 8)):
            return False
        dev_id = frame[4]
        length = frame[7]
        payload = frame[_PKT_HEADER : _PKT_HEADER + length]
        # Route to the right decoder by payload length, mirroring the PC's dual
        # IOT + 200B subscription: 50 bytes is the legacy IOT packet, larger is
        # the 200B packet. Other (tiny) control payloads fall through to the
        # 200B decoder, which ignores anything shorter than a full 200B packet.
        uuid = UUID_IOT_NOTIFY if length == _IOT_PACKET_LEN else UUID_NOTIFY_200B
        self._loop.call_soon_threadsafe(self._on_frame, dev_id, uuid, payload)
        return True

    def _emit_text(self, raw: bytes) -> None:
        line = raw.decode("ascii", errors="replace").strip()
        if line:
            self._loop.call_soon_threadsafe(self._on_line, line)

    # -- handlers (run in the event-loop thread) -----------------------------

    def _on_frame(self, dev_id: int, uuid: str, payload: bytes) -> None:
        mac = self._devid_to_mac.get(dev_id)
        if mac is None:
            return
        manager = self._managers.get(mac)
        if manager is not None:
            manager._dispatch_notify(uuid, payload)

    def _on_line(self, line: str) -> None:
        if self._scan_debug:
            _write_scan_debug(f"dongle rx: {line!r}")
        if self._scan_debug and self._collect_scan_line(line):
            return

        match = _CONNECTED.match(line)
        if match:
            handle = int(match.group(1))
            dev_id_text = match.group(2)
            mac = match.group(4).upper()
            self._handle_to_mac[handle] = mac
            if dev_id_text != "-":
                self._devid_to_mac[int(dev_id_text)] = mac
            future = self._connect_futures.get(mac)
            if future is not None and not future.done():
                future.set_result(True)
            return

        if line.startswith(_CONNECT_ERROR_PREFIXES):
            self._fail_active_connect(line)
            return

        match = _DISCONNECTED.match(line)
        if match:
            handle = int(match.group(1))
            mac = self._handle_to_mac.pop(handle, None)
            if mac is not None:
                future = self._disconnect_futures.get(mac)
                if future is not None and not future.done():
                    future.set_result(True)
                manager = self._managers.get(mac)
                if manager is not None:
                    manager._dispatch_disconnect()
                self._unregister_manager(mac)
            return

    def _fail_active_connect(self, message: str) -> None:
        mac = self._active_connect_mac
        if mac is None:
            return
        future = self._connect_futures.get(mac)
        if future is not None and not future.done():
            future.set_exception(RuntimeError(message))

    def _collect_scan_line(self, line: str) -> bool:
        header = _SCAN_LIST_HDR.match(line)
        if header:
            self._scan_expect = int(header.group(1))
            if self._scan_expect == 0 and self._scan_future and not self._scan_future.done():
                self._scan_future.set_result(True)
            return True
        if _SCAN_EVENT_LINE.match(line):
            self._scan_lines.append(line)
            return True
        if self._scan_expect is not None and _SCAN_LINE.match(line):
            self._scan_lines.append(line)
            if (
                len(self._scan_lines) >= self._scan_expect
                and self._scan_future
                and not self._scan_future.done()
            ):
                self._scan_future.set_result(True)
            return True
        return False
