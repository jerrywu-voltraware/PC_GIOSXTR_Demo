# 設計：DongleSource 掃描中途 transport 失效容錯（最小 diff 派）

設計角度：最小改動、最低風險。所有行號經本 agent 於 2026-07-28 親自開檔核對現碼。
改動只落在 2 個檔案：`app/device_source.py`（主體）與 `app/windows/scan_panel.py`（3 行）。
**不新增鎖、不改鎖結構、不動 Bleak 路徑、不動 main_window.py。**

核心構想（3 句話）：

1. 把現有 `scan()`（device_source.py:584-629）原封改名為 `_scan_once()`，外面套一層新的
   `scan()` wrapper：捕捉 `ConnectionError` → 走既有 `_ensure_recovered()` 做 coalesced
   recovery → 完整重跑一次 → 再敗就拋出「訊息本身就是繁中友善文案」的
   `DongleScanUnavailableError`。
2. coalescing 缺口（`_handle_stream_stale` 直呼 `recover()` 繞過 `_ensure_recovered`）
   不改呼叫端，改在 `recover()` 本體加「進 lock 後旗標已被前一位清掉就直接 return」
   守門——一處改動同時修好所有繞過點。
3. UI 端 scan_panel 的 except 分支已經是 `str(exc)` 直出；只要新例外的 `str()` 就是
   友善繁中文案，UI 幾乎零改動（僅 3 行讓空清單提示不再誤稱「藍牙」）。

---

## 1. 改動點清單（檔案:行號 + 插入位置）

### app/device_source.py

| # | 位置（現碼行號） | 改動 |
|---|---|---|
| C1 | :221-222（`_DONGLE_PROBE_ATTEMPTS = 3` 之後） | 新增常數：`_DONGLE_SCAN_TRANSPORT_RETRIES = 1`、`_DONGLE_SCAN_LIST_TIMEOUT_SECONDS = 3.0`（把 :612 的魔數 `3.0` 抽出，供測試 monkeypatch）、兩則繁中文案常數 `_SCAN_UNAVAILABLE_MESSAGE`、`_SCAN_RECOVERY_FAILED_MESSAGE`（全文見 §5） |
| C2 | :248（`_crc16_ccitt` 之後、`class DongleDeviceManager`（:250）之前） | 新增兩個模組層例外類別（簽名見 §2） |
| C3 | :584-629 | 現有 `scan()` 整段改名 `_scan_once(self, timeout, supported_only)`。其中：<br>(a) 刪掉開頭 `self._scan_idle.clear()`（:589）與 finally 裡的 `self._scan_idle.set()`（:629）——搬到 wrapper，讓「attempt1+recovery+attempt2」整段交易都持有 scan-busy；finally 只留 `self._scan_debug = False`（:628）。<br>(b) 在 `await asyncio.sleep(timeout)`（:602）之後、`AT+STOP`（:604）之前插入 `self._raise_if_scan_transport_unhealthy("scan-wait")`——這就是驗收 6 明點名的「5 秒等待結束先查旗標再送 AT+STOP」。<br>(c) :612 的 `timeout=3.0` 改用 `_DONGLE_SCAN_LIST_TIMEOUT_SECONDS`。<br>(d) AT+LIST 靜默 timeout 修補（驗收 7，表態見 §8）：在 :613-620 的 `except asyncio.TimeoutError` 記一個 `list_timed_out = True` 局部旗標，於 finally 區塊之後（:621 `results = ...` 之前）插入：`if list_timed_out and not self._scan_lines and self._scan_expect is None: self._needs_recovery = True; raise DongleScanTransportError("AT+LIST no response and no scan lines")` |
| C4 | :584（`_scan_once` 之前） | 新增 wrapper `async def scan(...)`：持有 `_scan_idle`、retry 迴圈、最終包裝成 `DongleScanUnavailableError`（完整碼見 §2） |
| C5 | :584 附近（wrapper 旁） | 新增小工具 `def _raise_if_scan_transport_unhealthy(self, stage: str) -> None`：`if self._needs_recovery or self._recovering or not self._running: raise DongleScanTransportError(...)` |
| C6 | `recover()` :856-909 | 兩行守門：<br>(a) 在 `async with self._recovery_lock:`（:862）**之前**加 `self._needs_recovery = True`（先宣告意圖再排隊）。<br>(b) 進 lock 後第一句（:863 之前）加：`if not self._needs_recovery: _write_dongle_runtime_log(f"recovery skipped (a concurrent recovery already completed): {reason}"); return`。<br>原 :865 的 `self._needs_recovery = True` 保留不動（無害，語意清楚）。 |

**明確不改**：`_handle_stream_stale` :773 的 `await self.recover(...)` 與
`_recover_if_connect_stuck` :814 的直呼 `recover()` 都**不必改**——C6 讓 `recover()`
自帶 coalescing：前者在 :771 已先設 `_needs_recovery=True`，若排隊時前一場 recovery
已把旗標清掉就自動跳過；後者屬「強制重置」語意，由 C6(a) 在 lock 前自行設旗標，
語意不變。`_ensure_recovered`（:816-824）完全不動。

### app/windows/scan_panel.py

| # | 位置 | 改動 |
|---|---|---|
| C7 | :550-553（`except Exception as exc:` 分支） | 改為：<br>`friendly = getattr(exc, "user_facing", False)`<br>`hint = str(exc) if friendly else "藍牙掃描未完成，請確認藍牙已開啟後重試。"`<br>`QMessageBox.warning(self, "掃描失敗", str(exc))`（原樣）<br>`self._show_empty_result("掃描失敗", hint)`<br>`self._set_scan_state("掃描失敗", hint)` |

duck-typing（`getattr(exc, "user_facing", False)`）而非 import，維持 :565/:569/:580
既有的鴨子型別風格，Bleak/測試 stub 完全不受影響。finally（:554-559）不動：失敗發生在
check_ready 之後時 `_adapter_available` 已為 True，按鈕本來就會重新啟用（驗收 4 後半）。

---

## 2. 新增/修改的函式與例外類別簽名

```python
# device_source.py 模組層（C2，插在 :248 之後）

class DongleScanTransportError(ConnectionError):
    """A scan transaction was aborted because the dongle transport turned
    unhealthy mid-flight (flag set by the reader thread or a failed write).
    Internal to DongleSource: scan()'s retry wrapper consumes it."""


class DongleScanUnavailableError(ConnectionError):
    """Final scan failure after coalesced recovery + one full retry.

    str(exc) IS the user-facing zh-TW message (safe to show in a QMessageBox);
    the technical detail is kept on .detail and written to dongle_runtime.log.
    """
    user_facing = True

    def __init__(self, user_message: str, detail: str = "") -> None:
        super().__init__(user_message)
        self.detail = detail
```

```python
# DongleSource（C4/C5；_scan_once 為原 :584-629 改名，內容如 C3）

async def scan(
    self, timeout: float = 5.0, supported_only: bool = True
) -> list[DeviceScanResult]:
    """Run one scan transaction; on transport failure, recover once and retry
    the whole transaction once. Holds _scan_idle across the entire attempt
    sequence so connects keep waiting instead of interleaving AT+CONN."""
    self._scan_idle.clear()
    last_error: Exception = ConnectionError("scan did not start")
    give_up_message = _SCAN_UNAVAILABLE_MESSAGE
    try:
        for attempt in range(1 + _DONGLE_SCAN_TRANSPORT_RETRIES):
            if attempt:
                _write_dongle_runtime_log(
                    f"scan retry {attempt}/{_DONGLE_SCAN_TRANSPORT_RETRIES} "
                    "after transport recovery"
                )
            try:
                return await self._scan_once(timeout, supported_only)
            except ConnectionError as exc:
                last_error = exc
                _write_dongle_runtime_log(f"scan attempt {attempt + 1} failed: {exc}")
                if attempt >= _DONGLE_SCAN_TRANSPORT_RETRIES:
                    break
                try:
                    await self._ensure_recovered("scan transaction aborted mid-flight")
                except Exception as recovery_exc:
                    last_error = recovery_exc
                    give_up_message = _SCAN_RECOVERY_FAILED_MESSAGE
                    break
        detail = self._last_transport_error or str(last_error)
        _write_dongle_runtime_log(f"scan gave up: {detail}")
        raise DongleScanUnavailableError(give_up_message, detail) from last_error
    finally:
        self._scan_idle.set()

def _raise_if_scan_transport_unhealthy(self, stage: str) -> None:
    if self._needs_recovery or self._recovering or not self._running:
        raise DongleScanTransportError(
            f"dongle transport unhealthy during scan ({stage})"
        )

async def _scan_once(
    self, timeout: float, supported_only: bool
) -> list[DeviceScanResult]:
    ...  # 原 :590-628 內容 + C3(b)(c)(d)，不含 _scan_idle 操作
```

`recover()` 簽名不變（`async def recover(self, reason: str = "manual recovery") -> None`），
只加 C6 兩行。只捕 `ConnectionError`（兩個新例外都是其子類）：`TimeoutError`、
`RuntimeError`、`asyncio.CancelledError` 全部原樣穿透，行為與今天一致。

### 各失效階段如何落入 retry（驗收 1 覆蓋圖）

| 階段 | 失效表現（現碼） | 進 retry 的路徑 |
|---|---|---|
| AT+SCAN 寫入（:601） | `_send_command`（:644-653）→ `_handle_transport_failure`（:1042）設旗標 → raise ConnectionError | wrapper 捕捉 → recovery → 重試 |
| 5 秒等待（:602） | reader thread 死亡 → `call_soon_threadsafe(_handle_transport_failure)` 只設旗標、不拋例外 | C3(b) 新檢查在 AT+STOP 前拋 `DongleScanTransportError` |
| AT+STOP 寫入（:604） | 同 AT+SCAN | wrapper 捕捉 → recovery → 重試 |
| AT+LIST 寫入（:611） | 同 AT+SCAN | 同上（:617-620 既有 finally 仍會清 `_scan_future`） |
| AT+LIST 等待（:612） | transport 死 → `_fail_all_pending_operations`（:922-929）對 `_scan_future` set_exception(ConnectionError) → `wait_for` 拋 ConnectionError（**不是** TimeoutError，不會被 :613 吞掉） | wrapper 捕捉 → recovery → 重試 |
| AT+LIST 靜默 timeout | 現碼吞掉、靜默回空清單 | C3(d)：零收集行 + 無 header 才視為 transport 可疑 → 設旗標 → retry |

---

## 3. 鎖與旗標互動時序（文字時序圖）

參與者：reader thread（RT）、event loop 上的 scan wrapper（S）、recover（R，持
`_recovery_lock`）、auto-reconnect 迴圈（A，main_window.py:947 `_run_reconnect_loop` →
:1000 `_reconnect_device` → device_source `_connect` :675，持 `_connect_lock`）。

### 時序圖一：5 秒等待中 transport 死亡 → coalesced recovery → 重試成功

```
RT                        S (scan)                          A (auto-reconnect)
--                        --------                          ------------------
                          scan(): _scan_idle.clear()
                          _scan_once: AT+SCAN, sleep 5s
read() 例外
 call_soon_threadsafe →
                          _handle_transport_failure (loop thread):
                            _needs_recovery=True, _running=False
                            fail 所有 pending futures
                            _reset_link_state → 各 manager
                            _dispatch_disconnect
                                                            disconnected signal →
                                                            排程 reconnect loop，
                                                            先 sleep ≥1s (RECONNECT_DELAYS)
                          sleep 結束 →
                          _raise_if_scan_transport_unhealthy
                            → DongleScanTransportError
                            （AT+STOP 沒送出去）
                          wrapper: _ensure_recovered
                            → recover(): 設旗標 → 取 _recovery_lock
                              → AT+DISC/AT+RESET → reopen → probe OK
                              → _needs_recovery=False → 釋放 lock
                                                            醒來 → _reconnect_device
                                                            → _connect: 取 _connect_lock
                                                              → _ensure_recovered:
                                                                _recovering=False、
                                                                旗標 False → no-op
                                                              → _wait_for_scan_idle
                                                                （S 仍 clear → 等，上限 12s）
                          attempt 2: _scan_once
                            AT+SCAN → 5s → AT+STOP → AT+LIST
                            → SCAN LIST → 回傳結果
                          finally: _scan_idle.set()
                                                            scan_idle set → AT+CONN 送出
```

關鍵：wrapper 全程持 `_scan_idle`，A 的 AT+CONN 被既有 `_wait_for_scan_idle`（:712-721，
上限 `_DONGLE_SCAN_IDLE_WAIT_SECONDS=12s`）擋在外面；attempt 2 淨時長 ≤ 5+3=8s < 12s，
一般情況不會 timeout 放行（超界情況見 §9-R1）。

### 時序圖二：多方同時觸發 recovery（coalescing，驗收 2）

```
S (scan retry)                 W (stream watchdog             K (check_ready)
                                _handle_stream_stale)
_ensure_recovered:
  旗標 True → recover():
  設旗標 → 取 _recovery_lock ─┐
                               │ :771 _needs_recovery=True
                               │ :773 recover(): 設旗標 →
                               │ 等 _recovery_lock（排隊）
  reset/reopen/probe 成功      │                              _ensure_recovered:
  _needs_recovery=False        │                                _recovering=True →
  釋放 lock ──────────────────┘                                async with lock: pass（排隊）
                               取得 lock → C6 守門：
                               旗標已 False → log + return
                               （不做第二次 reset）
                                                              取得又釋放 lock →
                                                              旗標 False → 不呼叫 recover
```

一場物理 reset 服務三個觸發者。`_handle_stream_stale` 的繞過缺口由 C6 在 `recover()`
本體堵住，呼叫端零改動。

### 時序圖三：recovery 失敗 → 友善放棄

```
S: attempt 1 ConnectionError
   → _ensure_recovered → recover(): reopen 失敗（:899-904）
     → _last_transport_error 設定、旗標保持 True → raise ConnectionError
   → wrapper: give_up_message=_SCAN_RECOVERY_FAILED_MESSAGE, break
   → raise DongleScanUnavailableError(繁中文案, detail=_last_transport_error)
   → finally _scan_idle.set()
UI: QMessageBox「掃描失敗」+ 繁中文案；finally(:554-559) 重新啟用按鈕
下一次按「搜尋裝置」→ check_ready(:497) → _ensure_recovered(:518) 再走完整重置循環
```

### 死鎖分析

- S 不取任何 asyncio lock（只操作自己擁有的 `_scan_idle` Event），呼叫的
  `_ensure_recovered`/`recover` 只取 `_recovery_lock`。
- A 的 `_connect` 持 `_connect_lock` 時依序：`_ensure_recovered`（取又放
  `_recovery_lock`）→ `_wait_for_scan_idle`（**有界** 12s）→ … 。持 `_recovery_lock`
  期間從不等 `_scan_idle` 或 `_connect_lock`。
- 鎖序唯一方向：`_connect_lock` → `_recovery_lock`；`_scan_idle` 等待皆有界。
  無環 → 無死鎖。**刻意不讓 scan 拿 `_connect_lock`**：若拿了，A 持 `_connect_lock`
  等 scan-idle、S 持 scan-idle 等 `_connect_lock`，就是 12s 的假死循環——不改鎖結構
  在此不只是保守，是正確。

---

## 4. 重試語意

- **次數**：`_DONGLE_SCAN_TRANSPORT_RETRIES = 1` → 每次使用者按鈕最多 2 次完整掃描
  attempt、最多 2 次 recovery（attempt1 前的 `_recover_if_connect_stuck` 那次不另計，
  它是既有行為）。
- **重試的觸發**：`_scan_once` 拋出任何 `ConnectionError`（含兩個新例外）。其他例外
  不重試、原樣穿透。
- **邊界／何時放棄**：
  1. attempt 用罄（第 2 次仍 ConnectionError）→ 放棄。
  2. attempt 間的 `_ensure_recovered` 自己拋例外（transport 救不回來）→ **立即**放棄，
     不再燒第二次 attempt，且文案切換為「無法自動恢復」版本。
  3. 放棄 = 拋 `DongleScanUnavailableError`；`_needs_recovery` 保持 True，下一次
     按鈕由 `check_ready`（:497-535）接手重置——與既有「never give up」層銜接，
     不會無限 loop（每次 loop 都要使用者按一次鈕）。
- **最壞牆鐘時間**：attempt1(≤8s) + recovery(≤~12s：reopen 6s + settle 1s + probe
  3×1.5s) + attempt2(≤8s) ≈ 28s，有界。
- auto-reconnect 的重試（main_window RECONNECT_DELAYS :91、never-give-up :947-998）
  **不改**，它與 scan retry 靠 `_scan_idle`/`_recovery_lock` 既有機制協調（§3）。

---

## 5. UI 錯誤訊息文案（繁中）

```python
_SCAN_UNAVAILABLE_MESSAGE = (
    "Nordic dongle 連線中斷，程式已自動重置 dongle 並重試掃描，但仍未成功。\n\n"
    "請確認 dongle 已插好、未被其他程式佔用序列埠；"
    "若剛重新插拔，請等待數秒後再按一次「搜尋裝置」。"
)
_SCAN_RECOVERY_FAILED_MESSAGE = (
    "Nordic dongle 已中斷連線，且自動重新連接失敗。\n\n"
    "請重新插拔 dongle，等待 Windows 重新辨識（約數秒）後，"
    "再按一次「搜尋裝置」。"
)
```

- QMessageBox 標題沿用既有「掃描失敗」（scan_panel.py:551），本文 = `str(exc)` = 上述文案。
- pyserial 原始字串（`ClearCommError` 等）只進 `exc.detail` → `dongle_runtime.log`，
  永不上 UI（驗收 4）。
- 空清單面板提示（C7 的 `hint`）同文案；非 dongle 例外維持原「藍牙掃描未完成…」。

---

## 6. 測試計畫（無硬體）

關鍵槓桿：注入 serial 時 `_owns_serial=False`（:435），`recover()` 會跳過
AT+RESET/reopen/probe（:872 `if self._owns_serial:`），直接清旗標「成功」——所以
FakeSerial 家族天然可以模擬「recovery 成功」，只要 fake 在失效一次後恢復正常。

新增 fake（tests/test_dongle_source.py，加在 WriteFailSerial :61-63 之後）：

```python
class FlakyWriteSerial(FakeSerial):
    """Fail writes whose command matches `fail_on`, `times` times, then heal."""
    def __init__(self, fail_on: str, times: int = 1) -> None: ...
```

| 測試名稱 | 模擬的失效階段 | 用的 fake / 手法 |
|---|---|---|
| `test_scan_retries_once_after_at_scan_write_failure` | AT+SCAN 寫入失敗 | `FlakyWriteSerial("AT+SCAN", 1)` + `_make_source_with_fake_serial` 模式；驅動 scan(timeout=0.01)，餵 `SCAN LIST: 0`；斷言 writes 序列 = [第二輪的 AT+SCAN, AT+STOP, AT+LIST]（第一輪失敗寫不進 list）、回傳 []、`_needs_recovery is False` |
| `test_scan_aborts_before_at_stop_when_transport_dies_mid_wait` | 5 秒等待期 reader 死亡 | FakeSerial；scan(timeout=0.2) 進行中呼叫 `src._handle_transport_failure("simulated")`；斷言第一輪**沒有** AT+STOP、第二輪完整 AT+SCAN/AT+STOP/AT+LIST（驗收 6 的旗標先查） |
| `test_scan_retries_after_at_stop_write_failure` | AT+STOP 寫入失敗 | `FlakyWriteSerial("AT+STOP", 1)`；斷言重試後成功 |
| `test_scan_gives_up_with_user_facing_error_when_transport_stays_dead` | 全程寫入失敗 | `WriteFailSerial`（既有 :61-63）；`pytest.raises(DongleScanUnavailableError)`；斷言 `"serial write failed" not in str(exc)`、`exc.user_facing is True`、`"dongle" in str(exc)`、`exc.detail` 含原始錯誤、`_needs_recovery is True` |
| `test_scan_at_list_silent_timeout_with_no_lines_flags_recovery_and_retries` | AT+LIST 靜默無回應 | FakeSerial + monkeypatch `_DONGLE_SCAN_LIST_TIMEOUT_SECONDS=0.02`；不餵任何行；斷言拋 `DongleScanUnavailableError`（兩輪都靜默）且期間 `_needs_recovery` 曾為 True |
| `test_scan_at_list_timeout_with_live_lines_returns_partial_results` | AT+LIST 無回應但 FOUND 行有到 | 同上 monkeypatch；掃描窗內餵 `FOUND 0: #7 ...` 行；斷言回傳 1 筆、**不** retry（writes 只有一輪）、旗標 False——保住現有寬容行為 |
| `test_recover_coalesces_concurrent_callers_into_one_reset` | 併發 recovery（驗收 2） | 包裝 spy 到 `src._reset_link_state`；`loop.run_until_complete(asyncio.gather(src.recover("a"), src.recover("b")))`；斷言 spy 恰被呼叫 1 次、旗標 False |
| `test_stream_stale_recover_skips_when_already_recovered` | `_handle_stream_stale` 繞過缺口 | 先手動完成一場 recover 清旗標後，再直呼 `src.recover("late stale")` 前把旗標壓 False 的情境改為：task1 recover 進行中（用事件卡住 `_fail_all_pending_operations` 的 spy 不可行——改卡 `_reset_link_state` 內 await？同步函式不可卡）→ 簡化：連續兩次 `gather(recover, recover)` 已覆蓋；本測試改驗證「recover 後旗標 False 時，`_ensure_recovered` 不再觸發 reset」（spy 0 次） |
| `test_scan_panel_shows_friendly_message_and_keeps_button`（tests/test_scan_panel.py，比照 :357-394 風格） | UI 層（驗收 4） | stub source 的 `scan` 直接 raise `DongleScanUnavailableError(文案, "ClearCommError ...")`；monkeypatch QMessageBox.warning 收參數；斷言訊息含「dongle」不含「ClearCommError」、`scan_btn.isEnabled()` 為 True |

回歸防護：
- 既有 `test_scan_recovers_when_connect_left_dongle_wedged`（:588-613）斷言 writes ==
  `["AT+SCAN","AT+STOP","AT+LIST"]`——wrapper 快樂路徑不多寫任何指令，注入 serial 的
  recover 不寫指令，此測試不受影響（設計時已核對）。
- `test_recover_fails_pending_connect_and_resets_state`（:616-634）直呼
  `recover("test")`：C6(a) 先設旗標 → 守門看到 True → 照常執行，結尾斷言旗標 False
  不變。
- 全 pytest：基準 176 passed + 上述 ~9 個新測試，0 fail 才算過。

---

## 7. 對 8 條驗收條件的逐條對應

| # | 驗收條件 | 對應設計 |
|---|---|---|
| 1 | AT+SCAN／5 秒等待／AT+STOP／AT+LIST 任一階段失效 → 中止舊 transaction | §2 覆蓋圖：寫入階段由 `_send_command` 既有 ConnectionError 中止；等待階段由 C3(b) 新檢查中止；AT+LIST 等待由 `_fail_all_pending_operations` 對 `_scan_future` 的 set_exception 中止。舊 transaction 的 future 清理沿用既有 finally（:617-620） |
| 2 | coalesced recovery，不重複重置；補 `_handle_stream_stale` 繞過缺口 | C6：`recover()` 本體「lock 前宣告意圖、lock 後旗標已清即跳過」。scan retry、watchdog、check_ready、connect 全部收斂到同一場 reset（時序圖二）。呼叫端零改動 |
| 3 | recovery 成功後自動重試完整掃描一次；有限次數 | §4：`_DONGLE_SCAN_TRANSPORT_RETRIES = 1`，重跑的是完整 `_scan_once`（含 AT+SCAN 起頭）；放棄條件明確、最壞 ~28s 有界；不會無限 loop |
| 4 | 最終失敗 UI 顯示可理解訊息（無 pyserial 字串），按鈕仍可按 | §5 文案 + `DongleScanUnavailableError.user_facing`；`str(exc)` 即友善文案，pyserial 細節只進 log；按鈕由既有 finally（scan_panel:554-559）重新啟用（`_adapter_available` 在 check_ready 通過時已為 True），並有 `check_ready` 作下一按的恢復層 |
| 5 | 不影響 PcBleSource/Bleak | 改動全在 DongleSource 類內 + scan_panel except 分支的 `getattr(exc,"user_facing",False)` 鴨子判斷；PcBleSource 沒有該屬性 → 走原字串分支，行為位元級不變。main_window 零改動 |
| 6 | 與 auto-reconnect／pending disconnect／scan-connect lock 的競爭；等待結束先查旗標再送 AT+STOP | 旗標先查 = C3(b)。auto-reconnect：wrapper 全程持 `_scan_idle`，reconnect 的 `_connect` 被既有 12s 有界等待擋開（時序圖一）；recovery 互斥靠 `_recovery_lock`。pending disconnect：`_wait_for_pending_disconnects` 留在 `_scan_once` 內 → 每個 attempt 都重新等待。鎖序單向無死鎖（§3）。殘餘競態誠實列於 §9 |
| 7 | AT+LIST 靜默 timeout 修不修——表態 | **修，但收最窄**（§8）：只有「timeout ∧ 零收集行 ∧ 無 SCAN LIST header」才視為 transport 可疑；有任何活動跡象維持現行寬容回傳。理由見 §8 |
| 8 | 測試計畫：各階段失效、recovery 後同次操作完成、最終失敗仍可重試、全 pytest 不退步 | §6：9 個新測試逐階段對應；`test_scan_retries_once_after_at_scan_write_failure` 驗證「同一次 scan() 呼叫內完成」；`test_scan_gives_up_...` + scan_panel 測試驗證失敗後按鈕可再按；回歸點逐一核對過現有斷言 |

---

## 8. 驗收 7 表態：AT+LIST 靜默 timeout 本次修

**修，但條件收到最窄。** 理由：

1. 實際故障劇本（0xFF03 fault 後韌體死透）正是「AT+LIST 永遠沒回應」——不修的話，
   本設計的 retry 機制對這個真實案例只有 `_send_command` 碰巧失敗時才觸發；若 CDC
   handle 還活著但韌體死了（寫入成功、永無回音），使用者看到的是說謊的
   「沒有找到支援裝置」，且不設旗標 → check_ready 下次也不救。這是本次故障的
   主幹路徑之一，不修等於驗收 1 的 AT+LIST 階段沒真正覆蓋。
2. 風險控制：加上「零收集行 ∧ 無 header」雙重門檻後，只要 transport 有任何生命跡象
   （FOUND/UPDATE 行、SCAN LIST header）就維持今日行為，現有測試與真機寬容度不受
   影響。誤判面（韌體活著但 3 秒內連 header 都不回）在現有韌體行為下不存在
   （header 是 AT+LIST 的同步回覆）。
3. 順手收益：抽出 `_DONGLE_SCAN_LIST_TIMEOUT_SECONDS` 常數本來就是測試計畫的前置需求。

若評審裁決不修：刪 C3(d) 與對應 2 個測試即可，其餘設計不依賴它。

---

## 9. 誠實列出「選擇接受」的殘餘競態與後果

- **R1（最主要）scan-idle 12s 有界等待被撐爆**：recovery 最壞 ~12s（reopen 6s +
  settle 1s + probe 4.5s），若 reconnect 的 `_connect` 在 recovery 早期就開始等
  `_scan_idle`，12s timeout 可能在 attempt 2 進行中到期 →「proceeding」（:721）→
  AT+CONN 與 AT+SCAN 交錯 → 可能再度 wedge 韌體。**後果**：該次掃描或連線失敗，
  由 never-give-up reconnect（:947）與下一次 check_ready 再救回，不會永久卡死。
  **不修理由**：根治需要 scan/connect 統一指令擁有權（改鎖結構），超出最小 diff
  邊界；機率低（需 recovery 逼近上限且 reconnect 恰在窗口內醒來）。
- **R2 檢查點 TOCTOU**：C3(b) 查旗標與 AT+STOP 寫入之間 reader 仍可能死。**後果**：
  AT+STOP 的 `_send_command` 拋 ConnectionError，落回同一個 retry 漏斗；沒有消除，
  只是收攏，行為正確。
- **R3 recover 成功與旗標清除間的新故障**：probe 成功（:895）到 `_needs_recovery=False`
  （:908）之間無 await，同 loop 的 `call_soon_threadsafe` 不可能插隊；但物理上這瞬間
  發生的新故障要等下一個 loop turn 才設旗標。**後果**：最多多付一輪「操作失敗→
  下次恢復」，不會丟失。
- **R4 掃描交易佔住 `_scan_idle` 最長 ~28s**：期間所有 connect（含 reconnect）排隊
  或 12s 超時放行（見 R1）。**後果**：斷線裝置的重連最多晚 ~28s；對錄製場景可接受，
  never-give-up 保證最終重連。
- **R5 無關的 `_needs_recovery`（如 disconnect timeout）在 5 秒等待中被設起**：C3(b)
  會中止一個其實健康的掃描並觸發 reset+retry。**後果**：該次掃描多花 ~10s 但結果
  正確；與既有 `_recover_if_connect_stuck` 的「wedge 嫌疑即重置」哲學一致。
- **R6 C3(d) 誤判**：韌體活著但 3 秒內對 AT+LIST 連 header 都不回（現有韌體無此
  行為）→ 多做一次 reset。**後果**：掃描慢 ~15s，結果正確。
- **R7 `_wait_for_scan_idle` 的既有 12s 放行本身未修**（它是 R1 的機制根源）：維持
  現狀是刻意的——它同時是「scan 卡死不能永久堵死 connect」的保險絲，拆掉它風險
  更大。
