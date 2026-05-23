"""Manages multiple concurrent BLE connections, one BleManager per device."""

from __future__ import annotations

from typing import Callable

from .ble_manager import BleManager, DeviceScanResult


MultiNotifyCallback = Callable[[str, str, bytes], None]
MultiDisconnectCallback = Callable[[str], None]


class MultiBleManager:
    def __init__(self) -> None:
        self._managers: dict[str, BleManager] = {}
        self._notify_callback: MultiNotifyCallback | None = None
        self._disconnect_callback: MultiDisconnectCallback | None = None

    def set_notify_callback(self, callback: MultiNotifyCallback | None) -> None:
        self._notify_callback = callback
        for manager in self._managers.values():
            manager.set_notify_callback(callback)

    def set_disconnect_callback(self, callback: MultiDisconnectCallback | None) -> None:
        self._disconnect_callback = callback
        for manager in self._managers.values():
            manager.set_disconnect_callback(self._on_manager_disconnected)

    def _on_manager_disconnected(self, address: str) -> None:
        self._managers.pop(address, None)
        if self._disconnect_callback is not None:
            self._disconnect_callback(address)

    @staticmethod
    async def scan(timeout: float = 5.0, supported_only: bool = True) -> list[DeviceScanResult]:
        return await BleManager.scan(timeout=timeout, supported_only=supported_only)

    def is_connected(self, address: str) -> bool:
        manager = self._managers.get(address)
        return manager is not None and manager.is_connected

    @property
    def connected_addresses(self) -> list[str]:
        return [addr for addr, m in self._managers.items() if m.is_connected]

    def get(self, address: str) -> BleManager | None:
        return self._managers.get(address)

    async def connect(self, address: str) -> BleManager:
        existing = self._managers.get(address)
        if existing is not None and existing.is_connected:
            return existing
        manager = BleManager()
        manager.set_notify_callback(self._notify_callback)
        manager.set_disconnect_callback(self._on_manager_disconnected)
        await manager.connect(address)
        self._managers[address] = manager
        return manager

    async def disconnect(self, address: str) -> None:
        manager = self._managers.pop(address, None)
        if manager is not None:
            await manager.disconnect()

    async def disconnect_all(self) -> None:
        for address in list(self._managers.keys()):
            await self.disconnect(address)

    async def enable_default_notifications(self, address: str) -> None:
        manager = self._managers.get(address)
        if manager is not None:
            await manager.enable_default_notifications()

    async def request_200b(self, address: str) -> None:
        manager = self._managers.get(address)
        if manager is not None:
            await manager.request_200b()

    async def write_device_number(self, address: str, number: int) -> None:
        manager = self._managers.get(address)
        if manager is None:
            raise RuntimeError(f"Device {address} not connected")
        await manager.write_device_number(number)

    async def reset_device_number(self, address: str) -> None:
        manager = self._managers.get(address)
        if manager is None:
            raise RuntimeError(f"Device {address} not connected")
        await manager.reset_device_number()
