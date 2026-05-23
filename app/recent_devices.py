"""Persistence for recently connected BLE devices."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class RecentDevice:
    address: str
    name: str
    device_number: int | None = None
    rssi: int = -999


class RecentDeviceStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or Path.home() / ".pc_giosxtr_demo" / "recent_devices.json"

    def load(self) -> list[RecentDevice]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        devices: list[RecentDevice] = []
        for item in data if isinstance(data, list) else []:
            if not isinstance(item, dict):
                continue
            address = str(item.get("address", "")).strip()
            name = str(item.get("name", "")).strip()
            if not address or not name:
                continue
            raw_number = item.get("device_number")
            device_number = raw_number if isinstance(raw_number, int) else None
            raw_rssi = item.get("rssi")
            rssi = raw_rssi if isinstance(raw_rssi, int) else -999
            devices.append(RecentDevice(address=address, name=name, device_number=device_number, rssi=rssi))
        return devices[:8]

    def remember(self, device: RecentDevice) -> None:
        devices = [item for item in self.load() if item.address != device.address]
        devices.insert(0, device)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = [asdict(item) for item in devices[:8]]
        self.path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
