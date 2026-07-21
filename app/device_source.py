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
import time
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
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

    async def prepare_reconnect(self, address: str) -> None:
        """Clear any latched per-device link state before a reconnect connects.

        Default: no-op (the OS Bluetooth stack keeps no per-device latch).
        Sources that hold firmware-side connection state (the dongle) override
        this to force a disconnect/clear that settles before the next connect.
        """
        return None

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
_IOT_PACKET_LEN = 50  # legacy IOT packet size (sizeof iot_packet_t)
_MIN_200B_PACKET_LEN = 193  # shortest payload accepted by decode_200b_packet()

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
# After a link drops, the dongle's BLE central needs a brief moment to release
# the connection before it can start a new one. Issuing AT+CONN too soon wedges
# the firmware (it then emits neither CONNECTED nor an error, so the connect
# future blocks the full timeout). Only applied when a disconnect happened
# recently, so a first connect after a scan is not slowed.
_DONGLE_POST_DISCONNECT_SETTLE_SECONDS = 0.8
# How long a scan waits for an in-flight connect to finish before treating it as
# wedged and recovering the dongle. Healthy connects resolve well within this;
# a wedged one (no CONNECTED/error within the 35s connect timeout) does not.
_DONGLE_PENDING_CONNECT_SCAN_WAIT_SECONDS = 4.0
# How long a connect waits for an in-progress scan to finish before proceeding.
# Bounds the wait so a stuck scan can never block connects forever.
_DONGLE_SCAN_IDLE_WAIT_SECONDS = 12.0
# The firmware requests a fresh 200B packet every two seconds when the stream is
# stale.  If the PC still sees no frame for this long, the BLE link or USB path
# is no longer healthy even when no DISCONNECTED line made it across CDC.
_DONGLE_STREAM_WATCHDOG_INTERVAL_SECONDS = 2.0
_DONGLE_STREAM_STALE_SECONDS = 12.0
# A reset temporarily removes the CDC device from Windows.  Reopen in an
# executor and allow enough time for the same dongle to enumerate again.
_DONGLE_REOPEN_TIMEOUT_SECONDS = 6.0
_DONGLE_POST_RESET_SETTLE_SECONDS = 1.0
_DONGLE_SERIAL_WRITE_TIMEOUT_SECONDS = 1.0
# After a reset+reopen we must prove the firmware actually answers before
# declaring recovery a success.  A reopened CDC handle does NOT prove the
# nRF52840 survived the reset (AT+RESET may never have reached a wedged MCU
# whose writes were timing out).  Send a lightweight AT+STATUS and require a
# reply; if none arrives, keep needs_recovery set so the next attempt retries.
_DONGLE_PROBE_TIMEOUT_SECONDS = 1.5
_DONGLE_PROBE_ATTEMPTS = 3


def _write_dongle_runtime_log(message: str) -> None:
    """Persist transport/recovery events even when verbose scan logging is off."""
    try:
        log_dir = Path.cwd() / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        with (log_dir / "dongle_runtime.log").open("a", encoding="utf-8") as file:
            file.write(f"{timestamp} {message}\n")
    except Exception:
        pass


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
        self._last_notify_monotonic: float | None = None
        self._keeper_task: asyncio.Task[None] | None = None

    @property
    def is_connected(self) -> bool:
        return self._connected

    def set_notify_callback(self, callback: NotifyCallback | None) -> None:
        self._notify_callback = callback

    def set_disconnect_callback(self, callback: DisconnectCallback | None) -> None:
        self._disconnect_callback = callback

    async def connect(self, address: str) -> None:
        self.address = address.upper()
        try:
            # Registration happens inside the source's connect lock, after any
            # pending dongle recovery.  Otherwise recovery would clear this
            # not-yet-connected manager and every later frame would be dropped.
            await self._source._connect(self.address, self)
            if not self._source._manager_has_active_link(self.address, self):
                raise ConnectionError(
                    f"Dongle link disappeared while connecting to {self.address}"
                )
        except Exception:
            self._source._unregister_manager(self.address)
            raise
        self._connected = True
        self._last_notify_monotonic = self._source._loop.time()

    async def disconnect(self) -> None:
        address = self.address
        self.stop_200b_keeper()
        if address and self._connected:
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

    def start_200b_keeper(
        self,
        *,
        interval: float = _DONGLE_STREAM_WATCHDOG_INTERVAL_SECONDS,
        stale_after: float = _DONGLE_STREAM_STALE_SECONDS,
        **_kwargs: object,
    ) -> None:
        """Watch the PC-facing stream, not only the firmware's BLE state.

        The dongle firmware already re-requests 200B notifications.  This
        second-level watchdog covers failures for which neither BLE nor CDC
        delivered a DISCONNECTED line (reader failure, firmware reset, or a
        logically-connected peripheral that stopped producing data).
        """
        self.stop_200b_keeper()
        if not self._connected:
            return
        self._keeper_task = self._source._loop.create_task(
            self._run_stream_watchdog(interval, stale_after)
        )

    def stop_200b_keeper(self) -> None:
        task = self._keeper_task
        self._keeper_task = None
        try:
            current_task = asyncio.current_task()
        except RuntimeError:
            current_task = None
        if (
            task is not None
            and not task.done()
            and task is not current_task
        ):
            task.cancel()

    async def _run_stream_watchdog(self, interval: float, stale_after: float) -> None:
        try:
            while self._connected:
                await asyncio.sleep(interval)
                if not self._connected:
                    return
                last = self._last_notify_monotonic
                if last is None:
                    last = self._source._loop.time()
                    self._last_notify_monotonic = last
                if (self._source._loop.time() - last) <= stale_after:
                    continue
                # Stream went silent.  Escalate to a disconnect/recovery, but do
                # NOT stop watching: if the disconnect/recovery did not take (the
                # transport is still wedged and this link is somehow still
                # flagged connected), the loop must re-detect staleness and
                # escalate again instead of leaving the link unmonitored.  A
                # successful escalation clears self._connected, so the loop then
                # exits on its own.
                try:
                    await self._source._handle_stream_stale(self)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    _write_dongle_runtime_log(
                        f"stream watchdog escalation failed for {self.address}: {exc}"
                    )
                # Reset the clock so a still-connected but wedged link waits a
                # full stale window before re-escalating (avoids a tight loop).
                self._last_notify_monotonic = self._source._loop.time()
        except asyncio.CancelledError:
            pass
        finally:
            if self._keeper_task is asyncio.current_task():
                self._keeper_task = None

    async def write_device_number(self, number: int) -> None:
        self._source._send_command(f"AT+DEVNUM={self.address},{number}")

    async def reset_device_number(self) -> None:
        self._source._send_command(f"AT+DEVNUM={self.address},255")

    # -- called by the source (in the event-loop thread) ---------------------

    def _dispatch_notify(self, uuid: str, payload: bytes) -> None:
        self._last_notify_monotonic = self._source._loop.time()
        if self._notify_callback is not None:
            self._notify_callback(self.address, uuid, payload)

    def _dispatch_disconnect(self) -> None:
        self._connected = False
        self.stop_200b_keeper()
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
        self._baudrate = baudrate
        self._serial_vid: int | None = None
        self._serial_pid: int | None = None
        self._serial_number: str | None = None
        self._serial_location: str | None = None
        # When we created the serial port ourselves we may close/reopen it to
        # recover a wedged dongle; an injected (test) port is never reopened.
        self._owns_serial = serial_port is None
        if serial_port is not None:
            # Injected for testing.
            self._serial = serial_port
        else:
            import serial  # imported lazily so the app runs without pyserial

            self._serial = serial.Serial(
                port,
                baudrate,
                timeout=0.1,
                write_timeout=_DONGLE_SERIAL_WRITE_TIMEOUT_SECONDS,
            )
            self._remember_serial_identity(port)
        self._write_lock = threading.Lock()

        self._managers: dict[str, DongleDeviceManager] = {}
        self._devid_to_mac: dict[int, str] = {}
        self._handle_to_mac: dict[int, str] = {}
        # Handles for which a disconnect timed out: the firmware still owes a
        # (now stale) DISCONNECTED line. The first DISCONNECTED for such a handle
        # is swallowed so it cannot tear down a link that reused the handle.
        self._stale_disconnect_handles: set[int] = set()

        self._rxbuf = bytearray()
        self._running = True

        # Async coordination for scan / connect.
        self._scan_future: asyncio.Future[bool] | None = None
        self._scan_lines: list[str] = []
        self._scan_expect: int | None = None
        self._scan_debug = False  # log every received line during scan() window
        self._connect_futures: dict[str, asyncio.Future[bool]] = {}
        self._disconnect_futures: dict[str, asyncio.Future[bool]] = {}
        # Resolved by the reader when the firmware answers a liveness probe
        # (AT+STATUS -> "STATUS links=...").  Used to handshake-gate recovery.
        self._probe_future: asyncio.Future[bool] | None = None
        self._connect_lock = asyncio.Lock()
        self._active_connect_mac: str | None = None
        # Set while a scan is running so a concurrent connect waits for it to
        # finish instead of multiplexing AT+CONN onto the busy serial link.
        self._scan_idle = asyncio.Event()
        self._scan_idle.set()
        # Monotonic time of the most recent disconnect (line or timeout), used to
        # gate the post-disconnect settle before the next AT+CONN.
        self._last_disconnect_monotonic: float | None = None
        # Set when a connect timed out (firmware wedged); the next scan resets
        # the dongle so it does not require an app restart.
        self._needs_recovery = False
        self._recovering = False
        self._last_transport_error = ""
        self._recovery_lock = asyncio.Lock()

        self._reader: threading.Thread | None = None
        if start_reader:
            self._reader = threading.Thread(
                target=self._read_loop, name="dongle-reader", daemon=True
            )
            self._reader.start()

    # -- DeviceSource API ----------------------------------------------------

    async def check_ready(self) -> AdapterCheckResult:
        if self._serial is not None and getattr(self._serial, "is_open", False):
            if self._reader is not None and not self._reader.is_alive():
                detail = self._last_transport_error or "Dongle reader thread stopped"
                return AdapterCheckResult(AdapterStatus.NO_ADAPTER, detail)
            if self._needs_recovery:
                detail = self._last_transport_error or "Dongle recovery required"
                return AdapterCheckResult(AdapterStatus.NO_ADAPTER, detail)
            return AdapterCheckResult(AdapterStatus.OK, f"Dongle on {self._port_name}")
        return AdapterCheckResult(
            AdapterStatus.NO_ADAPTER, "Dongle serial port is not open"
        )

    @property
    def needs_recovery(self) -> bool:
        return self._needs_recovery

    async def ensure_recovered(self, reason: str) -> None:
        """Coalesce callers that only need recovery when transport is unhealthy."""
        await self._ensure_recovered(reason)

    async def prepare_reconnect(self, address: str) -> None:
        """Force a per-device AT+DISC before a reconnect's AT+CONN.

        A reconnect must clear the firmware's latched per-device link state
        (a half-open link whose DISCONNECTED line was lost, or m_connecting
        left set for this MAC) before AT+CONN, otherwise the fresh connect can
        be rejected or race the stale link.  A per-device AT+DISC=<mac> is used
        (not the global AT+DISC) so other healthy recording sessions are not
        torn down.  The disconnect timestamp is recorded so the AT+CONN that
        follows honours the firmware-settle window.
        """
        mac = address.upper()
        async with self._connect_lock:
            await self._wait_for_scan_idle()
            await self._wait_for_pending_disconnects()
            try:
                self._send_command(f"AT+DISC={mac}")
                self._last_disconnect_monotonic = self._loop.time()
                _write_scan_debug(f"dongle reconnect: cleared {mac} before AT+CONN")
            except Exception as exc:
                _write_dongle_runtime_log(
                    f"reconnect pre-disconnect failed for {mac}: {exc}"
                )

    def create_manager(self) -> DeviceManager:
        return DongleDeviceManager(self)

    async def scan(
        self, timeout: float = 5.0, supported_only: bool = True
    ) -> list[DeviceScanResult]:
        # Hold off concurrent connects (they would multiplex AT+CONN onto the
        # serial link mid-scan) and let any pending disconnect finish first.
        self._scan_idle.clear()
        try:
            await self._wait_for_pending_disconnects()
            # A connect that never completed leaves the firmware wedged so it
            # cannot service AT+SCAN. Recover the dongle before scanning, so the
            # user does not have to restart the app.
            await self._recover_if_connect_stuck()
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
            try:
                self._send_command("AT+LIST")
                await asyncio.wait_for(future, timeout=3.0)
            except asyncio.TimeoutError:
                _write_scan_debug(
                    "dongle scan: AT+LIST timed out (no SCAN LIST received)"
                )
            finally:
                self._consume_future_exception(future)
                self._scan_future = None
                self._scan_debug = False
            results = self._parse_scan_results(self._scan_lines)
            _write_scan_debug(
                f"dongle scan: parsed {len(results)} device(s) from "
                f"{len(self._scan_lines)} collected line(s)"
            )
            return results
        finally:
            self._scan_debug = False
            self._scan_idle.set()

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
                if not getattr(self._serial, "is_open", False):
                    raise OSError("serial port is closed")
                self._serial.write((text + "\r\n").encode("ascii"))
        except Exception as exc:
            message = f"serial write failed on {self._port_name}: {exc}"
            self._handle_transport_failure(message)
            raise ConnectionError(message) from exc

    # -- manager registry ----------------------------------------------------

    def _register_manager(self, mac: str, manager: DongleDeviceManager) -> None:
        self._managers[mac] = manager

    def _manager_has_active_link(
        self, mac: str, manager: DongleDeviceManager
    ) -> bool:
        return (
            self._managers.get(mac) is manager
            and mac in self._handle_to_mac.values()
        )

    def _unregister_manager(self, mac: str) -> None:
        self._managers.pop(mac, None)
        for dev_id in [d for d, m in self._devid_to_mac.items() if m == mac]:
            self._devid_to_mac.pop(dev_id, None)
        for handle in [h for h, m in self._handle_to_mac.items() if m == mac]:
            self._handle_to_mac.pop(handle, None)

    async def _connect(
        self, mac: str, manager: DongleDeviceManager | None = None
    ) -> None:
        async with self._connect_lock:
            await self._ensure_recovered("transport/connect state requires recovery")
            # Never multiplex a connect onto the serial link while a scan runs,
            # and never issue AT+CONN while a previous link is still tearing down
            # (a pending AT+DISC) — both wedge the firmware's BLE central.
            await self._wait_for_scan_idle()
            await self._wait_for_pending_disconnects()
            await self._settle_after_disconnect()
            # Recovery may have started while any of the waits above yielded.
            # Recheck immediately before registration/AT+CONN; no await occurs
            # between this check and creation of the coordination future.
            await self._ensure_recovered(
                "transport changed while connect was waiting"
            )
            if manager is not None:
                self._register_manager(mac, manager)
            future: asyncio.Future[bool] = self._loop.create_future()
            self._connect_futures[mac] = future
            self._active_connect_mac = mac
            try:
                self._send_command(f"AT+CONN={mac}")
                await asyncio.wait_for(future, timeout=_DONGLE_CONNECT_TIMEOUT_SECONDS)
            except asyncio.TimeoutError as exc:
                # Firmware never answered: it is wedged. Flag recovery so the
                # next scan resets the dongle instead of returning empty.
                self._needs_recovery = True
                _write_scan_debug(f"dongle connect: timed out for {mac}; flagged for recovery")
                raise TimeoutError(f"Dongle connect timed out for {mac}") from exc
            finally:
                self._connect_futures.pop(mac, None)
                self._consume_future_exception(future)
                if self._active_connect_mac == mac:
                    self._active_connect_mac = None

    async def _wait_for_scan_idle(self) -> None:
        if self._scan_idle.is_set():
            return
        _write_scan_debug("dongle connect: waiting for in-progress scan to finish")
        try:
            await asyncio.wait_for(
                self._scan_idle.wait(), timeout=_DONGLE_SCAN_IDLE_WAIT_SECONDS
            )
        except asyncio.TimeoutError:
            _write_scan_debug("dongle connect: scan-idle wait timed out; proceeding")

    async def _settle_after_disconnect(self) -> None:
        last = self._last_disconnect_monotonic
        if last is None:
            return
        remaining = _DONGLE_POST_DISCONNECT_SETTLE_SECONDS - (self._loop.time() - last)
        if remaining > 0:
            _write_scan_debug(f"dongle connect: settling {remaining:.2f}s before AT+CONN")
            await asyncio.sleep(remaining)

    async def _disconnect(self, mac: str) -> None:
        future: asyncio.Future[bool] = self._loop.create_future()
        self._disconnect_futures[mac] = future
        try:
            self._send_command(f"AT+DISC={mac}")
            await asyncio.wait_for(future, timeout=_DONGLE_DISCONNECT_TIMEOUT_SECONDS)
        except asyncio.TimeoutError:
            # Firmware did not acknowledge the disconnect: its link may still be
            # alive. Record the time so the next connect still settles, flag
            # recovery so a stale link gets cleared before the next operation,
            # and remember that the (late) DISCONNECTED for this handle must be
            # swallowed so it cannot tear down a reused-handle link later.
            self._last_disconnect_monotonic = self._loop.time()
            self._needs_recovery = True
            for handle in [h for h, m in self._handle_to_mac.items() if m == mac]:
                self._stale_disconnect_handles.add(handle)
            _write_scan_debug(f"dongle disconnect timed out for {mac}; flagged for recovery")
        finally:
            self._disconnect_futures.pop(mac, None)
            self._consume_future_exception(future)

    async def _handle_stream_stale(self, manager: DongleDeviceManager) -> None:
        """Turn a silent stream into a real disconnect/reconnect workflow."""
        mac = manager.address
        if not mac or self._managers.get(mac) is not manager or not manager.is_connected:
            return
        age = self._loop.time() - (manager._last_notify_monotonic or self._loop.time())
        message = f"stream stale for {mac} ({age:.1f}s without a frame)"
        _write_scan_debug(f"dongle: {message}")
        _write_dongle_runtime_log(message)
        try:
            await self._disconnect(mac)
        except Exception as exc:
            _write_dongle_runtime_log(f"stale-stream disconnect failed for {mac}: {exc}")

        # A normal DISCONNECTED line removes the manager and drives the UI.  If
        # the line/transport was lost, force source recovery so the same UI path
        # still runs and recording state is retained for auto-reconnect.
        if self._managers.get(mac) is manager:
            self._needs_recovery = True
            try:
                await self.recover(f"{message}; no disconnect acknowledgement")
            except Exception as exc:
                _write_dongle_runtime_log(f"stale-stream recovery pending: {exc}")

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

    async def _recover_if_connect_stuck(self) -> None:
        """Reset the dongle if a connect attempt left it wedged.

        A wedged firmware (no CONNECTED / error within the connect timeout, or a
        disconnect that was never acknowledged) cannot service AT+SCAN, so the
        scan would silently return nothing. Recovering here means the user no
        longer has to close and reopen the app.
        """
        if self._needs_recovery or self._recovering:
            await self._ensure_recovered(
                "previous connect/disconnect left the dongle wedged"
            )
            return
        pending = [f for f in self._connect_futures.values() if not f.done()]
        if not pending:
            return
        _write_scan_debug(
            f"dongle scan: {len(pending)} connect(s) in flight; waiting briefly"
        )
        _, still_pending = await asyncio.wait(
            pending, timeout=_DONGLE_PENDING_CONNECT_SCAN_WAIT_SECONDS
        )
        if still_pending:
            await self.recover("scan requested over an unresponsive connect")

    async def _ensure_recovered(self, reason: str) -> None:
        """Wait for an active recovery, then reset only if it is still needed."""
        if self._recovering:
            # Do not queue a second reset behind the first one.  The recovery
            # lock is released only after needs_recovery reflects its outcome.
            async with self._recovery_lock:
                pass
        if self._needs_recovery:
            await self.recover(reason)

    async def _probe_firmware_alive(self) -> bool:
        """Return True only if the firmware answers a lightweight AT+STATUS.

        A reopened CDC handle does not prove the nRF52840 survived the reset, so
        recovery must not declare success until the MCU actually replies.  Sends
        AT+STATUS (which the firmware answers with a "STATUS links=..." line) and
        waits briefly; retries a few times before giving up.
        """
        for _ in range(_DONGLE_PROBE_ATTEMPTS):
            future: asyncio.Future[bool] = self._loop.create_future()
            self._probe_future = future
            try:
                self._send_command("AT+STATUS")
            except Exception as exc:
                self._consume_future_exception(future)
                if self._probe_future is future:
                    self._probe_future = None
                _write_dongle_runtime_log(f"dongle probe send failed: {exc}")
                return False
            try:
                await asyncio.wait_for(future, timeout=_DONGLE_PROBE_TIMEOUT_SECONDS)
                return True
            except asyncio.TimeoutError:
                continue
            finally:
                self._consume_future_exception(future)
                if self._probe_future is future:
                    self._probe_future = None
        return False

    async def recover(self, reason: str = "manual recovery") -> None:
        """Reset BLE/CDC state and reopen the physical dongle.

        Closing a CDC handle does *not* reset an nRF52840.  New firmware accepts
        AT+RESET; AT+DISC remains a compatibility fallback for older firmware.
        """
        async with self._recovery_lock:
            _write_scan_debug(f"dongle recovery: {reason}")
            _write_dongle_runtime_log(f"recovery started: {reason}")
            self._needs_recovery = True
            self._recovering = True
            self._fail_all_pending_operations(f"dongle reset: {reason}")
            # Notify the UI before touching the port.  This is what preserves
            # state/CSV recording and schedules auto-reconnect.
            self._reset_link_state()
            try:
                if self._owns_serial:
                    # Best effort: old firmware understands AT+DISC; the fixed
                    # firmware then performs a real MCU reset via AT+RESET.
                    try:
                        self._send_command("AT+DISC")
                        await asyncio.sleep(0.15)
                        self._send_command("AT+RESET")
                        await asyncio.sleep(0.2)
                    except Exception as exc:
                        _write_scan_debug(f"dongle recovery command failed: {exc}")
                    await self._loop.run_in_executor(None, self._reopen_serial)
                    await asyncio.sleep(_DONGLE_POST_RESET_SETTLE_SECONDS)
                    if (
                        not getattr(self._serial, "is_open", False)
                        or self._reader is None
                        or not self._reader.is_alive()
                    ):
                        raise OSError("dongle reader did not survive CDC reopen")
                    # Handshake gate: a reopened port is not proof the MCU reset
                    # took.  Require a live AT+STATUS reply before declaring
                    # success; otherwise keep needs_recovery set so the next
                    # attempt retries (and escalates through this full
                    # close/reopen + MCU-reset cycle again).
                    if not await self._probe_firmware_alive():
                        raise OSError(
                            "dongle did not answer AT+STATUS after reset"
                        )
            except Exception as exc:
                self._last_transport_error = f"dongle reopen failed: {exc}"
                _write_scan_debug(f"dongle recovery: {self._last_transport_error}")
                _write_dongle_runtime_log(self._last_transport_error)
                self._needs_recovery = True
                raise ConnectionError(self._last_transport_error) from exc
            finally:
                self._recovering = False
            self._last_transport_error = ""
            self._needs_recovery = False
            _write_dongle_runtime_log(f"recovery completed on {self._port_name}")

    def _fail_all_pending_connects(self, error: Exception) -> None:
        for future in list(self._connect_futures.values()):
            if not future.done():
                future.set_exception(error)

    @staticmethod
    def _consume_future_exception(future: asyncio.Future[object]) -> None:
        """Mark a synchronously failed coordination future as observed."""
        if future.done() and not future.cancelled():
            future.exception()

    def _fail_all_pending_operations(self, message: str) -> None:
        """Release every coroutine waiting on a transport that has died."""
        self._fail_all_pending_connects(ConnectionError(message))
        if self._scan_future is not None and not self._scan_future.done():
            self._scan_future.set_exception(ConnectionError(message))
        for future in list(self._disconnect_futures.values()):
            if not future.done():
                future.set_exception(ConnectionError(message))

    def _reopen_serial(self) -> None:
        """Close/reopen CDC after firmware reset, following a changed COM name."""
        import serial  # lazy import, mirrors __init__

        self._running = False
        old = self._serial
        try:
            if old is not None and getattr(old, "is_open", False):
                old.close()
        except Exception:
            pass
        reader = self._reader
        if (
            reader is not None
            and reader.is_alive()
            and reader is not threading.current_thread()
        ):
            reader.join(timeout=1.5)
            if reader.is_alive():
                raise OSError("dongle reader did not stop before CDC reopen")
        deadline = time.monotonic() + _DONGLE_REOPEN_TIMEOUT_SECONDS
        last_error: Exception | None = None
        while True:
            for candidate in self._serial_port_candidates():
                try:
                    self._serial = serial.Serial(
                        candidate,
                        self._baudrate,
                        timeout=0.1,
                        write_timeout=_DONGLE_SERIAL_WRITE_TIMEOUT_SECONDS,
                    )
                    self._port_name = candidate
                    self._remember_serial_identity(candidate)
                    last_error = None
                    break
                except Exception as exc:  # pragma: no cover - hardware dependent
                    last_error = exc
            if last_error is None and getattr(self._serial, "is_open", False):
                break
            if time.monotonic() >= deadline:
                raise last_error or OSError("dongle did not re-enumerate")
            time.sleep(0.25)
        self._rxbuf = bytearray()
        self._running = True
        self._reader = threading.Thread(
            target=self._read_loop, name="dongle-reader", daemon=True
        )
        self._reader.start()
        _write_scan_debug("dongle recovery: serial reopened, reader restarted")

    def _remember_serial_identity(self, port: str) -> None:
        try:
            from serial.tools import list_ports

            for info in list_ports.comports():
                if str(info.device).upper() != str(port).upper():
                    continue
                self._serial_vid = info.vid
                self._serial_pid = info.pid
                self._serial_number = info.serial_number
                self._serial_location = info.location
                return
        except Exception:
            pass

    def _serial_port_candidates(self) -> list[str]:
        candidates: list[str] = []
        try:
            from serial.tools import list_ports

            matches: list[str] = []
            for info in list_ports.comports():
                if self._serial_number and info.serial_number == self._serial_number:
                    matches.insert(0, info.device)
                    continue
                if (
                    self._serial_vid is not None
                    and info.vid == self._serial_vid
                    and info.pid == self._serial_pid
                    and (
                        not self._serial_location
                        or not info.location
                        or info.location == self._serial_location
                    )
                ):
                    matches.append(info.device)
            candidates.extend(matches)
        except Exception:
            pass
        # Prefer the remembered USB identity in case Windows assigned a new COM
        # number; fall back to the original name when enumeration has not yet
        # repopulated.
        candidates.append(self._port_name)
        return list(dict.fromkeys(str(candidate) for candidate in candidates if candidate))

    def _reset_link_state(self) -> None:
        """Drop every link mapping and tell managers their link is gone."""
        managers = list(self._managers.values())
        self._handle_to_mac.clear()
        self._stale_disconnect_handles.clear()
        self._devid_to_mac.clear()
        self._managers.clear()
        self._active_connect_mac = None
        for manager in managers:
            # A manager registered for an in-flight AT+CONN is not a live link;
            # emitting its callback would start a duplicate UI reconnect task.
            if manager.is_connected:
                manager._dispatch_disconnect()
            else:
                manager.stop_200b_keeper()

    def _handle_transport_failure(self, message: str) -> None:
        """Mark a dead CDC transport and surface it as device disconnects."""
        self._last_transport_error = message
        _write_scan_debug(f"dongle transport: {message}")
        _write_dongle_runtime_log(message)
        if self._recovering or not self._running:
            return
        self._needs_recovery = True
        self._running = False
        self._fail_all_pending_operations(message)
        self._reset_link_state()

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
            except Exception as exc:
                if self._running:
                    message = f"serial read failed on {self._port_name}: {exc}"
                    self._loop.call_soon_threadsafe(
                        self._handle_transport_failure, message
                    )
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
        # Firmware also emits tiny binary control frames for connect/disconnect
        # events.  They are not BLE notifications and must not refresh the
        # stream watchdog or release the UI's first-data connection guard.
        if length == _IOT_PACKET_LEN:
            uuid = UUID_IOT_NOTIFY
        elif length >= _MIN_200B_PACKET_LEN:
            uuid = UUID_NOTIFY_200B
        else:
            return True
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
        if line.startswith("DIAG:"):
            _write_dongle_runtime_log(f"firmware {line}")
        if self._scan_debug:
            _write_scan_debug(f"dongle rx: {line!r}")
        if self._scan_debug and self._collect_scan_line(line):
            return

        # Liveness probe reply (AT+STATUS -> "STATUS links=u/u connecting=..").
        # Proves the firmware is actually responsive after a reset/reopen.
        if line.startswith("STATUS "):
            future = self._probe_future
            if future is not None and not future.done():
                future.set_result(True)
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
            # A disconnect that previously timed out still owes one DISCONNECTED.
            # Swallow that stale line so it cannot tear down a link that has
            # since reused the same handle number.
            if handle in self._stale_disconnect_handles:
                self._stale_disconnect_handles.discard(handle)
                _write_scan_debug(f"dongle: swallowing stale DISCONNECTED handle={handle}")
                return
            mac = self._handle_to_mac.pop(handle, None)
            if mac is not None:
                self._last_disconnect_monotonic = self._loop.time()
                future = self._disconnect_futures.get(mac)
                if future is not None and not future.done():
                    future.set_result(True)
                manager = self._managers.get(mac)
                if manager is not None:
                    if manager.is_connected:
                        manager._dispatch_disconnect()
                    else:
                        manager.stop_200b_keeper()
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
