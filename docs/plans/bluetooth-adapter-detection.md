# 計畫:藍牙介面檢測 (Bluetooth Adapter Detection)

## 背景

PC GIOSXTR Demo 是一個 PyQt6 + bleak 的桌面應用程式,透過 BLE 連線與多顆 GIOS 充電板/PTU 裝置通訊。

目前的問題:
- 程式假設使用者的電腦一定有可用的 BLE 介面卡。
- 當電腦**沒有藍牙硬體**(常見於桌機)、藍牙服務未啟動、藍牙被停用、或使用者拔掉 USB dongle 時,使用者按下「搜尋裝置」會收到一段不友善的底層錯誤訊息(來自 bleak/WinRT),很難理解該怎麼處理。
- 我們希望在**程式啟動時**先檢測一次,並在使用者按搜尋時也能優雅地處理 adapter 消失的情況,給出明確的引導性訊息。

## 目標

1. 在 `MainWindow` 初始化時(顯示視窗前)做一次藍牙介面檢測。
2. 若偵測到沒有可用 BLE adapter,跳出明確、可操作的中文訊息對話框,而非神秘的 bleak/WinRT exception。
3. 在「搜尋裝置」流程也加入相同檢測,涵蓋程式執行中 dongle 被拔掉的情境。
4. 不破壞既有的掃描/連線流程;當 adapter 正常存在時,行為不變。

## 不在範圍內 (Non-goals)

- 不自動安裝驅動程式。
- 不嘗試「修復」藍牙(例如重啟服務),只負責檢測 + 通知使用者。
- 不支援藍牙閘道 (Pi/ESP32) 等替代架構,這是未來題目。

---

## 設計

### 1. 新增 `app/ble_adapter.py`

放一個獨立模組,負責跨平台的 BLE adapter 檢測。為什麼獨立: bleak 在不同 OS 後端不同,日後若要擴充 Linux/macOS 檢測,集中在一個地方好維護。

```python
"""BLE adapter availability detection."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from enum import Enum


class AdapterStatus(Enum):
    OK = "ok"                          # 偵測到至少一個可用 adapter
    NO_ADAPTER = "no_adapter"          # 完全沒有藍牙硬體 / 沒裝驅動
    DISABLED = "disabled"              # 有硬體但被關閉 (例:飛航模式)
    UNSUPPORTED_OS = "unsupported_os"  # 目前實作只覆蓋 Windows;其他 OS 回此值,但仍嘗試使用
    UNKNOWN_ERROR = "unknown_error"    # 檢測過程拋例外


@dataclass
class AdapterCheckResult:
    status: AdapterStatus
    detail: str  # 給 log 的詳細英文訊息

    @property
    def is_usable(self) -> bool:
        # UNSUPPORTED_OS 視為「就試試看」,不擋
        return self.status in (AdapterStatus.OK, AdapterStatus.UNSUPPORTED_OS)


async def check_bluetooth_adapter() -> AdapterCheckResult:
    """Async — 因為 WinRT Radio.GetRadiosAsync 是 awaitable。"""
    if sys.platform == "win32":
        return await _check_windows()
    return AdapterCheckResult(AdapterStatus.UNSUPPORTED_OS, f"adapter check not implemented on {sys.platform}")


async def _check_windows() -> AdapterCheckResult:
    """
    使用 WinRT 直接列舉 Radio 物件,而不是丟一次 BleakScanner.discover()。
    原因:
      - discover 即使沒 adapter 也可能要等好幾秒才丟錯,使用者體驗差。
      - Radio 列舉是同步且毫秒級的。
    依賴:已透過 bleak 帶入 winrt-runtime,可以直接 import。
    """
    try:
        from winrt.windows.devices.radios import Radio, RadioKind, RadioState
    except Exception as exc:  # ImportError or others
        return AdapterCheckResult(
            AdapterStatus.UNKNOWN_ERROR,
            f"winrt radios module unavailable: {exc!r}",
        )

    try:
        radios = await Radio.get_radios_async()
    except Exception as exc:
        return AdapterCheckResult(
            AdapterStatus.UNKNOWN_ERROR,
            f"Radio.get_radios_async failed: {exc!r}",
        )

    bt_radios = [r for r in radios if r.kind == RadioKind.BLUETOOTH]
    if not bt_radios:
        return AdapterCheckResult(
            AdapterStatus.NO_ADAPTER,
            "no Bluetooth radio reported by WinRT",
        )

    any_on = any(r.state == RadioState.ON for r in bt_radios)
    if not any_on:
        return AdapterCheckResult(
            AdapterStatus.DISABLED,
            f"found {len(bt_radios)} Bluetooth radio(s) but none in state ON",
        )

    return AdapterCheckResult(AdapterStatus.OK, f"{len(bt_radios)} radio(s) ON")
```

**重點決策:**

- `UNSUPPORTED_OS` 不擋使用者 — 我們只有 Windows 客戶,但若有人在 Mac/Linux 跑開發版,讓 bleak 自己嘗試比硬擋好。
- 不嘗試判斷 dongle 廠牌或晶片 — 那不是這個檢測該做的事。
- 函數是 async,因為 WinRT API 是 awaitable;呼叫端已經在 qasync 事件迴圈中。

### 2. 提供「面向使用者」的訊息對應

放在同一個模組,方便 UI 端直接拿:

```python
def user_facing_message(result: AdapterCheckResult) -> tuple[str, str]:
    """Return (title, body) suitable for QMessageBox in Traditional Chinese."""
    if result.status == AdapterStatus.NO_ADAPTER:
        return (
            "找不到藍牙介面",
            "這台電腦目前沒有可用的藍牙裝置。\n\n"
            "若是桌上型電腦,請插入支援 BLE 4.0 以上的 USB 藍牙接收器,"
            "等系統自動安裝驅動程式後再開啟本程式。\n\n"
            "若是筆電,請確認藍牙驅動程式已安裝。",
        )
    if result.status == AdapterStatus.DISABLED:
        return (
            "藍牙已關閉",
            "偵測到藍牙介面,但目前處於關閉狀態。\n\n"
            "請從「設定 → 藍牙與裝置」開啟藍牙,或關閉飛航模式後再試一次。",
        )
    if result.status == AdapterStatus.UNKNOWN_ERROR:
        return (
            "無法檢測藍牙狀態",
            f"檢測藍牙介面時發生錯誤,程式仍會嘗試啟動。\n\n詳細訊息:{result.detail}",
        )
    # OK / UNSUPPORTED_OS:不該被呼叫,但保險起見回個無害值
    return ("", "")
```

### 3. 整合到 `MainWindow.__init__`

修改 `app/windows/main_window.py`:

- `MainWindow.__init__` 末尾(或 `main.py` 在 `window.show()` 之前) 觸發一次檢測。
- 因為檢測是 async 而 `__init__` 是同步,**用 `QTimer.singleShot(0, ...)` 排隊到事件迴圈啟動後執行**,然後用 `asyncSlot` 或直接 `asyncio.ensure_future` 跑檢測。這樣不會阻塞主視窗顯示。
- 結果為 `NO_ADAPTER` / `DISABLED` → 跳 `QMessageBox.warning`,讓使用者按確定後**繼續使用程式**(不要 sys.exit;他們可能想看歷史錄製檔)。但同時把 `scan_panel` 的「搜尋裝置」按鈕禁用 + 改 placeholder 文字提示。
- 結果為 `OK` → 啟用搜尋按鈕(預設就啟用,所以無動作)。
- 結果為 `UNKNOWN_ERROR` / `UNSUPPORTED_OS` → 只 log,不擋使用者。

具體插入點建議在 `MainWindow.__init__` 的最後一行 `self._refresh_active_recording_status()` 之後加:

```python
QTimer.singleShot(0, self._run_initial_adapter_check)
```

並新增方法:

```python
@asyncSlot()
async def _run_initial_adapter_check(self) -> None:
    from ..ble_adapter import AdapterStatus, check_bluetooth_adapter, user_facing_message
    result = await check_bluetooth_adapter()
    self._last_adapter_status = result.status
    if result.status in (AdapterStatus.NO_ADAPTER, AdapterStatus.DISABLED):
        title, body = user_facing_message(result)
        QMessageBox.warning(self, title, body)
        self.scan_panel.set_adapter_unavailable(result.status, body)
    elif result.status == AdapterStatus.UNKNOWN_ERROR:
        # 不擋,但寫到 status bar 提示
        self.scan_panel.status.setText(f"藍牙狀態檢測失敗:{result.detail}")
```

### 4. `ScanPanel` 新增 `set_adapter_unavailable`

在 `app/windows/scan_panel.py`:

```python
def set_adapter_unavailable(self, status, hint: str) -> None:
    """Disable scan button and show hint when no usable BLE adapter."""
    self.scan_btn.setEnabled(False)
    self.scan_btn.setText("藍牙不可用")
    self._set_scan_state("藍牙不可用", hint.splitlines()[0])
    self._show_empty_result("藍牙不可用", hint)
```

並提供配對的 `set_adapter_available` 給使用者後續插入 dongle 並重試時用(見步驟 5)。

### 5. 「重新檢測」入口

讓使用者插上 dongle 後不必重啟程式:

- 在 `ScanPanel.scan()` **內部**(也就是按下「搜尋裝置」時),每次都先呼叫一次 `check_bluetooth_adapter()`。
- 若這次回 `OK`,就繼續原本的 `await self.ble.scan(...)`。
- 若仍是 `NO_ADAPTER` / `DISABLED`,跳一次 `QMessageBox.information` 顯示對應訊息,不要丟 exception。
- 為避免每次點搜尋都多出 ~50ms WinRT 呼叫,可以加一個 cache:30 秒內若上次是 OK 就跳過再檢測。`AdapterCheckResult` 在 `ble_adapter.py` 內維護一個簡單的 module-level cache 即可(`_last_check_at: float, _last_result: AdapterCheckResult | None`)。

### 6. Log 紀錄

把 `AdapterCheckResult.detail` 寫到 `logs/ble_scan_debug.log`(沿用 `_write_scan_debug`),方便日後追問題。狀態為 `OK` 也寫,但只記一行。

---

## 檔案改動清單

| 檔案 | 動作 | 內容 |
|------|------|------|
| `app/ble_adapter.py` | **新增** | 上述 `check_bluetooth_adapter`、`AdapterStatus`、`AdapterCheckResult`、`user_facing_message`、cache 邏輯 |
| `app/windows/main_window.py` | **修改** | `__init__` 末尾排程 `_run_initial_adapter_check`;新增該方法 |
| `app/windows/scan_panel.py` | **修改** | 新增 `set_adapter_unavailable` / `set_adapter_available`;`scan()` 內加入檢測前置 |
| `tests/test_ble_adapter.py` | **新增** | 對 `AdapterStatus`→訊息映射、cache 行為做單元測試;WinRT 部分用 mock |

---

## 測試計畫

### 自動測試 (`tests/test_ble_adapter.py`)

1. `user_facing_message` 對每個 `AdapterStatus` 都回傳非空 title(除了 OK / UNSUPPORTED_OS)。
2. Cache: 連續呼叫兩次 `check_bluetooth_adapter()`,第二次在 30 秒內應該回 cached result(用 monkeypatch `_check_windows` 計數)。
3. Cache 過期: 偽造時間戳讓 cache > 30s,應重新呼叫底層。

### 手動測試

按以下情境逐一驗證,記錄結果:

| # | 情境 | 預期 |
|---|------|------|
| 1 | 筆電有藍牙且已開啟 | 程式正常啟動,不跳對話框,「搜尋裝置」可用 |
| 2 | 筆電有藍牙但從 Windows 設定關閉 | 啟動時跳「藍牙已關閉」對話框,搜尋按鈕禁用、文字變「藍牙不可用」 |
| 3 | 桌機沒有藍牙硬體 | 啟動時跳「找不到藍牙介面」對話框,搜尋按鈕禁用 |
| 4 | 啟動後插入 USB dongle → 按搜尋 | scan() 內重新檢測通過,正常開始掃描 |
| 5 | 啟動正常 → 中途拔掉 dongle → 按搜尋 | 跳「找不到藍牙介面」,不丟 exception |
| 6 | 飛航模式開啟 | 與情境 2 相同訊息 |

---

## 風險與權衡

- **WinRT import 失敗**: bleak 在 Windows 一定會帶入 winrt-runtime,理論上 import 不會失敗。若使用者用了非常老的 bleak 版本(<0.20),需要在 requirements 確認最低版本。**建議在 `pyproject.toml` 確認 `bleak>=0.21` 並在計畫實作時順手檢查一次。**
- **誤判 disabled**: 某些虛擬機環境會把 adapter 報成 RadioKind.OTHER,可能誤判為 NO_ADAPTER。可接受,因為這種環境本來就沒法用 BLE。
- **30 秒 cache**: 若使用者在 30 秒內反覆插拔 dongle,會看到「藍牙不可用」短暫殘留。權衡:減少 WinRT 呼叫頻率 vs 即時性。30 秒是個保守值,可調整。

## 驗收標準

1. 沒有藍牙的桌機開啟程式,出現「找不到藍牙介面」對話框,訊息中包含「請插入支援 BLE 4.0 以上的 USB 藍牙接收器」。
2. 搜尋按鈕在無 adapter 狀態下被禁用且文字變為「藍牙不可用」。
3. 既有有 adapter 的環境:從啟動到第一次搜尋,目視無新增延遲(< 100ms 增量)。
4. 拔除 dongle 後按搜尋,**不**會出現原生 bleak/WinRT exception traceback;只會看到中文訊息對話框。
5. `tests/test_ble_adapter.py` 全綠。
