"""BLE adapter availability detection."""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass
from enum import Enum


class AdapterStatus(Enum):
    OK = "ok"
    NO_ADAPTER = "no_adapter"
    DISABLED = "disabled"
    UNSUPPORTED_OS = "unsupported_os"
    UNKNOWN_ERROR = "unknown_error"


@dataclass(frozen=True)
class AdapterCheckResult:
    status: AdapterStatus
    detail: str

    @property
    def is_usable(self) -> bool:
        return self.status in (AdapterStatus.OK, AdapterStatus.UNSUPPORTED_OS)


_CACHE_TTL_SECONDS = 30.0
_last_check_at = 0.0
_last_result: AdapterCheckResult | None = None


def reset_adapter_cache() -> None:
    global _last_check_at, _last_result
    _last_check_at = 0.0
    _last_result = None


async def check_bluetooth_adapter(*, force_refresh: bool = False) -> AdapterCheckResult:
    """Check whether the current platform has a usable BLE adapter.

    Only successful Windows checks are cached. Unavailable results are always
    rechecked so a newly inserted USB Bluetooth dongle can be detected.
    """
    global _last_check_at, _last_result

    now = time.monotonic()
    if (
        not force_refresh
        and _last_result is not None
        and _last_result.status is AdapterStatus.OK
        and now - _last_check_at < _CACHE_TTL_SECONDS
    ):
        return _last_result

    if sys.platform == "win32":
        result = await _check_windows()
    else:
        result = AdapterCheckResult(
            AdapterStatus.UNSUPPORTED_OS,
            f"adapter check not implemented on {sys.platform}",
        )

    if result.status is AdapterStatus.OK:
        _last_check_at = now
        _last_result = result
    else:
        reset_adapter_cache()
    return result


async def _check_windows() -> AdapterCheckResult:
    try:
        from winrt.windows.devices.radios import Radio, RadioKind, RadioState
        from bleak.backends.winrt.client import FutureLike
        from bleak.backends.winrt.util import assert_mta
    except Exception as exc:
        return AdapterCheckResult(
            AdapterStatus.UNKNOWN_ERROR,
            f"winrt radios module unavailable: {exc!r}",
        )

    try:
        await assert_mta()
        radios = await FutureLike(Radio.get_radios_async())
    except Exception as exc:
        return AdapterCheckResult(
            AdapterStatus.UNKNOWN_ERROR,
            f"Radio.get_radios_async failed: {exc!r}",
        )

    bluetooth_kind = getattr(RadioKind, "BLUETOOTH", None)
    if bluetooth_kind is None:
        bluetooth_kind = getattr(RadioKind, "bluetooth", None)
    on_state = getattr(RadioState, "ON", None)
    if on_state is None:
        on_state = getattr(RadioState, "on", None)
    bt_radios = [
        radios.get_at(index)
        for index in range(int(radios.size))
        if radios.get_at(index).kind == bluetooth_kind
    ]

    if not bt_radios:
        return AdapterCheckResult(
            AdapterStatus.NO_ADAPTER,
            "no Bluetooth radio reported by WinRT",
        )

    if not any(radio.state == on_state for radio in bt_radios):
        states = ", ".join(str(radio.state) for radio in bt_radios)
        return AdapterCheckResult(
            AdapterStatus.DISABLED,
            f"found {len(bt_radios)} Bluetooth radio(s) but none in state ON: {states}",
        )

    return AdapterCheckResult(AdapterStatus.OK, f"{len(bt_radios)} Bluetooth radio(s) ON")


def user_facing_message(result: AdapterCheckResult) -> tuple[str, str]:
    """Return (title, body) suitable for QMessageBox in Traditional Chinese."""
    if result.status is AdapterStatus.NO_ADAPTER:
        return (
            "找不到藍牙介面",
            "這台電腦目前沒有可用的藍牙裝置。\n\n"
            "若是桌上型電腦，請插入支援 BLE 4.0 以上的 USB 藍牙接收器，"
            "並確認 Windows 已完成安裝驅動程式。\n\n"
            "若是筆電，請確認藍牙驅動程式已安裝。",
        )
    if result.status is AdapterStatus.DISABLED:
        return (
            "藍牙已關閉",
            "偵測到藍牙介面，但目前處於關閉狀態。\n\n"
            "請從「設定 → 藍牙與裝置」開啟藍牙，或關閉飛航模式後再試一次。",
        )
    if result.status is AdapterStatus.UNKNOWN_ERROR:
        return (
            "無法檢測藍牙狀態",
            f"檢測藍牙介面時發生錯誤，程式仍會嘗試啟動。\n\n詳細訊息: {result.detail}",
        )
    return ("", "")
