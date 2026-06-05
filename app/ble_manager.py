"""BLE manager built on bleak, plus advertisement parsing helpers."""

from __future__ import annotations

import argparse
import asyncio
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from bleak import BleakClient, BleakScanner
from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData

from .constants import (
    RSSI_MINIMUM,
    SUPPORTED_DEVICES,
    UUID_IOT_NOTIFY,
    UUID_IOT_WRITE,
    UUID_NOTIFY_200B,
    UUID_NOTIFY_20B,
    UUID_WRITE_200B,
)


NotifyCallback = Callable[[str, str, bytes], None]
DisconnectCallback = Callable[[str], None]


@dataclass
class DeviceScanResult:
    address: str
    name: str
    rssi: int
    raw_hex: str
    advertising_rows: list[dict[str, str]]
    device_number: int | None
    firmware_revision: str | None
    device: BLEDevice | None = None


def _to_hex(data: list[int] | bytes | bytearray) -> str:
    return "".join(f"{byte:02X}" for byte in data)


def _maybe_16bit_uuid(uuid_value: Any) -> list[int] | None:
    uuid_str = str(uuid_value).lower()
    if len(uuid_str) == 36 and uuid_str.endswith("-0000-1000-8000-00805f9b34fb"):
        value = int(uuid_str[4:8], 16)
        return [value & 0xFF, (value >> 8) & 0xFF]
    return None


def _add_record(records: list[dict[str, Any]], type_: int, value: list[int]) -> None:
    records.append({"type": type_, "value": value})


def format_device_display_name(name: str, device_number: int | None) -> str:
    if device_number is None:
        return name
    return f"{name}#{device_number}"


def _manufacturer_has_device_number_record(
    manufacturer_data: dict[int, bytes | bytearray | list[int]],
) -> bool:
    if 0xEEEE in manufacturer_data:
        return True
    for payload_value in manufacturer_data.values():
        payload = list(payload_value)
        for index in range(max(0, len(payload) - 1)):
            if payload[index] == 0xEE and payload[index + 1] == 0xEE:
                return True
    return False


def is_supported_device_advertisement(
    name: str,
    manufacturer_data: dict[int, bytes | bytearray | list[int]],
) -> bool:
    clean_name = str(name or "")
    if clean_name.startswith("GIOS"):
        return True
    if clean_name in SUPPORTED_DEVICES:
        return True
    if any(clean_name.startswith(f"{supported}#") for supported in SUPPORTED_DEVICES):
        return True
    return _manufacturer_has_device_number_record(manufacturer_data)


def fallback_device_display_base_name(
    name: str,
    manufacturer_data: dict[int, bytes | bytearray | list[int]],
) -> str:
    clean_name = str(name or "")
    if clean_name:
        return clean_name
    if _manufacturer_has_device_number_record(manufacturer_data):
        return "GIOS Device"
    return ""


def _write_scan_debug(message: str) -> None:
    if os.environ.get("PC_GIOSXTR_BLE_SCAN_DEBUG") != "1":
        return
    try:
        log_dir = Path.cwd() / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        with (log_dir / "ble_scan_debug.log").open("a", encoding="utf-8") as file:
            file.write(f"{timestamp} {message}\n")
    except Exception:
        pass


def build_advertising_table(
    *,
    name: str,
    tx_power: int | None,
    service_uuids: list[Any],
    service_data: dict[Any, bytes | bytearray | list[int]],
    manufacturer_data: dict[int, bytes | bytearray | list[int]],
    connectable: bool,
) -> tuple[list[dict[str, str]], str, int | None, str | None]:
    records: list[dict[str, Any]] = []
    device_number: int | None = None
    firmware_revision: str | None = None

    if connectable:
        _add_record(records, 0x01, [0x06])

    if tx_power is not None:
        _add_record(records, 0x0A, [tx_power & 0xFF])

    if name:
        _add_record(records, 0x09, list(name.encode("utf-8")))

    for uuid_value in service_uuids:
        uuid16 = _maybe_16bit_uuid(uuid_value)
        if uuid16 is not None:
            _add_record(records, 0x03, uuid16)

    for uuid_value, payload in service_data.items():
        uuid16 = _maybe_16bit_uuid(uuid_value)
        if uuid16 is not None:
            _add_record(records, 0x16, [*uuid16, *list(payload)])

    for company_id, payload_value in manufacturer_data.items():
        payload = list(payload_value)

        if company_id == 0xEEEE:
            if payload:
                device_number = payload[0]
            if len(payload) >= 3:
                firmware_revision = str(payload[1] | (payload[2] << 8))
            _add_record(records, 0xFF, [0xEE, 0xEE, *payload])
            continue

        marker_index = -1
        for index in range(max(0, len(payload) - 1)):
            if payload[index] == 0xEE and payload[index + 1] == 0xEE:
                marker_index = index
                break

        if marker_index > 0:
            first_data = payload[:marker_index]
            second_data = payload[marker_index + 2 :]
            if second_data:
                device_number = second_data[0]
            if len(second_data) >= 3:
                firmware_revision = str(second_data[1] | (second_data[2] << 8))

            _add_record(
                records,
                0xFF,
                [company_id & 0xFF, (company_id >> 8) & 0xFF, *first_data],
            )
            _add_record(records, 0xFF, [0xEE, 0xEE, *second_data])
            continue

        _add_record(
            records,
            0xFF,
            [company_id & 0xFF, (company_id >> 8) & 0xFF, *payload],
        )

    rows: list[dict[str, str]] = []
    raw: list[int] = []
    for record in records:
        value = list(record["value"])
        type_ = int(record["type"])
        length = len(value) + 1
        rows.append(
            {
                "LEN": str(length),
                "TYPE": f"0x{type_:02X}",
                "VALUE": f"0x{_to_hex(value)}",
            }
        )
        raw.extend([length, type_, *value])

    return rows, f"0x{_to_hex(raw)}", device_number, firmware_revision


class BleManager:
    def __init__(self) -> None:
        self.client: BleakClient | None = None
        self.device: BLEDevice | None = None
        self.address: str = ""
        self._notify_callback: NotifyCallback | None = None
        self._disconnect_callback: DisconnectCallback | None = None
        self._notified: set[str] = set()
        self.write_200b_uuid: str | None = None
        self.iot_write_uuid: str | None = None
        # Loop monotonic timestamp of the most recent 200B notification.
        # None means "no 200B received yet since this manager connected".
        self._last_200b_at: float | None = None
        self._keeper_task: asyncio.Task[None] | None = None

    @staticmethod
    async def scan(timeout: float = 5.0, supported_only: bool = True) -> list[DeviceScanResult]:
        discovered = await BleakScanner.discover(timeout=timeout, return_adv=True)
        _write_scan_debug(f"discover returned {len(discovered)} item(s), supported_only={supported_only}")
        results: list[DeviceScanResult] = []
        for device, adv in discovered.values():
            name = adv.local_name or device.name or ""
            rssi = int(adv.rssi or -999)
            manufacturer_data = dict(adv.manufacturer_data or {})
            _write_scan_debug(
                "candidate "
                f"address={device.address} name={name!r} rssi={rssi} "
                f"manufacturer_ids={[hex(key) for key in manufacturer_data.keys()]}"
            )
            if supported_only and not is_supported_device_advertisement(name, manufacturer_data):
                _write_scan_debug(f"filtered unsupported address={device.address} name={name!r}")
                continue
            if rssi <= RSSI_MINIMUM:
                _write_scan_debug(f"filtered rssi address={device.address} name={name!r} rssi={rssi}")
                continue
            rows, raw_hex, device_number, revision = build_advertising_table(
                name=name,
                tx_power=getattr(adv, "tx_power", None),
                service_uuids=list(adv.service_uuids or []),
                service_data=dict(adv.service_data or {}),
                manufacturer_data=manufacturer_data,
                connectable=bool(getattr(adv, "connectable", True)),
            )
            display_base_name = fallback_device_display_base_name(name, manufacturer_data)
            display_name = format_device_display_name(display_base_name, device_number)
            results.append(
                DeviceScanResult(
                    address=device.address,
                    name=display_name,
                    rssi=rssi,
                    raw_hex=raw_hex,
                    advertising_rows=rows,
                    device_number=device_number,
                    firmware_revision=revision,
                    device=device,
                )
            )
            _write_scan_debug(f"accepted address={device.address} display={display_name!r} rssi={rssi}")
        results.sort(key=lambda item: item.rssi, reverse=True)
        _write_scan_debug(f"returning {len(results)} item(s)")
        return results

    async def connect(self, address: str) -> None:
        await self.disconnect()
        self.address = address
        self.client = BleakClient(address, disconnected_callback=self._on_disconnected)
        await self.client.connect()
        self.write_200b_uuid = None
        self.iot_write_uuid = None
        self._last_200b_at = None
        await self._cache_write_characteristics()

    async def _cache_write_characteristics(self) -> None:
        if self.client is None:
            return
        for service in self.client.services:
            for char in service.characteristics:
                uuid = str(char.uuid).lower()
                props = set(char.properties)
                if uuid == UUID_WRITE_200B and "write" in props:
                    self.write_200b_uuid = uuid
                if uuid == UUID_IOT_WRITE and "write" in props:
                    self.iot_write_uuid = uuid

    def _on_disconnected(self, _client: BleakClient) -> None:
        self._notified.clear()
        self.stop_200b_keeper()
        if self._disconnect_callback is not None:
            self._disconnect_callback(self.address)

    def set_notify_callback(self, callback: NotifyCallback | None) -> None:
        self._notify_callback = callback

    def set_disconnect_callback(self, callback: DisconnectCallback | None) -> None:
        self._disconnect_callback = callback

    @property
    def is_connected(self) -> bool:
        return self.client is not None and self.client.is_connected

    async def disconnect(self) -> None:
        self.stop_200b_keeper()
        if self.client is not None and self.client.is_connected:
            try:
                for uuid in list(self._notified):
                    try:
                        await self.client.stop_notify(uuid)
                    except Exception:
                        pass
                await self.client.disconnect()
            finally:
                self._notified.clear()
        self.client = None

    async def write(self, char_uuid: str, data: list[int] | bytes | bytearray) -> None:
        if self.client is None or not self.client.is_connected:
            raise RuntimeError("Not connected")
        await self.client.write_gatt_char(char_uuid, bytearray(data), response=True)

    async def write_device_number(self, number: int) -> None:
        if self.iot_write_uuid is None:
            raise RuntimeError("IOT write characteristic not found")
        await self.write(self.iot_write_uuid, [0xA1, number])

    async def reset_device_number(self) -> None:
        if self.iot_write_uuid is None:
            raise RuntimeError("IOT write characteristic not found")
        await self.write(self.iot_write_uuid, [0xA1, 0xFF])

    async def request_200b(self) -> None:
        if self.iot_write_uuid is not None:
            await self.write(self.iot_write_uuid, [0xA2])
        elif self.write_200b_uuid is not None:
            await self.write(self.write_200b_uuid, [0x01])
        else:
            raise RuntimeError("No 200B request characteristic found")

    async def enable_notify(self, uuid: str) -> None:
        if self.client is None or not self.client.is_connected:
            raise RuntimeError("Not connected")
        uuid_l = uuid.lower()
        if uuid_l in self._notified:
            return

        def handler(sender: Any, data: bytearray) -> None:
            sender_uuid = str(getattr(sender, "uuid", uuid_l)).lower()
            if sender_uuid == UUID_NOTIFY_200B:
                try:
                    self._last_200b_at = asyncio.get_running_loop().time()
                except RuntimeError:
                    pass
            if self._notify_callback is not None:
                self._notify_callback(self.address, sender_uuid, bytes(data))

        await self.client.start_notify(uuid_l, handler)
        self._notified.add(uuid_l)

    async def enable_default_notifications(self) -> None:
        # Skip UUID_NOTIFY_20B on purpose (mirrors the Flutter iOS strategy).
        # With three notify streams writing the same DeviceState fields under
        # three different unit/width conventions (notably ptu_bus_voltage:
        # IOT=raw u16, 20B=raw u16 * 10, 200B=u32 mV), the last writer wins
        # and values jitter visibly. Subscribing only to IOT + 200B keeps a
        # single high-fidelity source for everything 200B carries and avoids
        # the race entirely; the 200B keeper guarantees 200B keeps flowing.
        for uuid in (UUID_IOT_NOTIFY, UUID_NOTIFY_200B):
            try:
                await self.enable_notify(uuid)
            except Exception:
                continue

    def start_200b_keeper(self, *, interval: float = 2.0, stale_after: float = 3.0) -> None:
        """Background poker that re-requests 200B when the firmware stops sending.

        Mirrors the Flutter iOS strategy: every `interval` seconds, if more than
        `stale_after` seconds have passed since the last 200B notification, send
        0xA2 again. This guarantees error_data / error_limit stay populated when
        the firmware otherwise sends only 20B packets.
        """
        if self._keeper_task is not None and not self._keeper_task.done():
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        self._keeper_task = loop.create_task(self._run_200b_keeper(interval, stale_after))

    def stop_200b_keeper(self) -> None:
        task = self._keeper_task
        self._keeper_task = None
        if task is not None and not task.done():
            task.cancel()

    async def _run_200b_keeper(self, interval: float, stale_after: float) -> None:
        try:
            while self.is_connected:
                await asyncio.sleep(interval)
                if not self.is_connected:
                    break
                now = asyncio.get_running_loop().time()
                last = self._last_200b_at
                if last is None or (now - last) > stale_after:
                    try:
                        await self.request_200b()
                    except Exception:
                        # Non-fatal: firmware/connection issue, try again next tick.
                        continue
        except asyncio.CancelledError:
            pass

    def services_text(self) -> str:
        if self.client is None:
            return ""
        lines: list[str] = []
        for service in self.client.services:
            lines.append(f"[Service] {service.uuid}")
            for char in service.characteristics:
                lines.append(f"  - {char.uuid} ({','.join(char.properties)})")
        return "\n".join(lines)


async def _cli_scan(timeout: float) -> None:
    print(f"Scanning {timeout:.1f}s ...")
    results = await BleManager.scan(timeout=timeout, supported_only=False)
    for result in results:
        print(f"{result.rssi:>4} dBm  {result.address}  {result.name}")
    if not results:
        print("No BLE devices found.")


async def _cli_connect(address: str) -> None:
    manager = BleManager()
    print(f"Connecting {address} ...")
    await manager.connect(address)
    print("Connected.")
    print(manager.services_text())
    await manager.disconnect()
    print("Disconnected.")


def _main() -> None:
    parser = argparse.ArgumentParser(description="GIOSXTR BLE smoke-test helper")
    parser.add_argument("--scan", action="store_true", help="Scan BLE devices")
    parser.add_argument("--timeout", type=float, default=5.0, help="Scan timeout seconds")
    parser.add_argument("--connect", metavar="ADDRESS", help="Connect and list services")
    args = parser.parse_args()

    if args.scan:
        asyncio.run(_cli_scan(args.timeout))
    elif args.connect:
        asyncio.run(_cli_connect(args.connect))
    else:
        parser.print_help()


if __name__ == "__main__":
    _main()
