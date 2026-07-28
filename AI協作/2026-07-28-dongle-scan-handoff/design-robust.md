# 設計文件：dongle 掃描交易穩健化（robust / 交易擁有權派）

日期：2026-07-28。基準碼：master 63800d5，行號皆以現碼實讀核對。
基準測試：176 passed（tests/ 全套）。

## 0. 設計立場與核心模型

以「掃描交易」（AT+SCAN → 5s 視窗 → AT+STOP → AT+LIST → 解析）為失效邊界：
交易內任一階段偵測到 transport 失效即整體作廢，絕不對「新世代」的 serial handle
續發舊交易的指令。三個 serial 指令擁有者與其擁有權機制：

| 擁有者 | 交易內容 | 擁有權機制 |
|---|---|---|
| scan 交易 | AT+SCAN/AT+STOP/AT+LIST（多指令） | 持 `_connect_lock` 整段（含自動重試 1 次） |
| connect 交易（manual + auto-reconnect） | AT+CONN + 等 CONNECTED；prepare_reconnect 的 AT+DISC | 既有 `_connect_lock`（現碼 device_source.py:678、569） |
| recovery | AT+DISC/AT+RESET/reopen/AT+STATUS probe | `_recovery_lock` + `_send_command` 的 recovering 守門（新增） |

兩個新原語：

1. **世代計數器 `_transport_generation`**：每次 transport 死亡或 recovery 實際重置
   時 +1。交易開頭抓快照，各階段（含 5 秒視窗內輪詢）比對；不符即拋
   `DongleTransactionAborted`。解決「scan 睡在 5 秒視窗時 reader thread 已宣告
   transport 死亡，醒來仍送 AT+STOP」的 TOCTOU（驗收 6 指名情境）。
2. **`_send_command` recovery 守門**：`_recovering=True` 期間，非 recovery 本身
   的任何寫入直接拋 `DongleTransactionAborted`（不標 transport failure——transport
   沒死，只是被 recovery 佔用）。這是硬保證：即使某條路徑繞過鎖（`_disconnect`、
   `write_device_number`、watchdog 路徑），也不可能與 recovery 的
   AT+DISC/AT+RESET/probe 序列交錯。

鎖階層（防死鎖規則）：`_connect_lock` → `_recovery_lock` 單向；任何路徑禁止先持
`_recovery_lock` 再取 `_connect_lock`。已審計現碼與本設計所有路徑符合
（recover() 內的 `_reset_link_state` 回呼只 create_task，不同步取鎖）。

Bleak 隔離：全部改動在 `DongleSource`／`DongleDeviceManager` 與 scan_panel 的
一個新 except 分支；`PcBleSource`/`BleManager` 零改動，scan_panel 靠例外型別
分流（Bleak 例外不是 `DongleTransactionAborted`，走原路徑）。

---

## 1. 改動點清單（檔案:行號，以現碼為準）

### app/device_source.py

| # | 位置（現碼行號） | 改動 |
|---|---|---|
| D1 | :222 之後（`_DONGLE_PROBE_ATTEMPTS = 3` 下一行） | 新增常數：`_DONGLE_SCAN_RETRY_ATTEMPTS = 1`（recovery 成功後整段掃描自動重試次數）、`_DONGLE_SCAN_ABORT_POLL_SECONDS = 0.2`（5 秒視窗的中止輪詢粒度）、`_DONGLE_SCAN_OWNERSHIP_WAIT_SECONDS = _DONGLE_PENDING_CONNECT_SCAN_WAIT_SECONDS`（=4.0，scan 取得匯流排擁有權的上限等待） |
| D2 | :155-157 區段註解之後（`# Nordic dongle source` 標頭下、:162 `_SOF0` 前） | 新增例外類別 `DongleTransactionAborted`（§2） |
| D3 | :486（`self._recovery_lock = asyncio.Lock()` 下一行） | 新增 `self._transport_generation: int = 0` |
| D4 | :557-579 `prepare_reconnect` | 在 :570 `async with self._connect_lock:` 之後、`_wait_for_scan_idle` 之前插入 `await self._ensure_recovered("reconnect preparation")`——reconnect 的 AT+DISC 永不落在待修復/修復中的 transport 上 |
| D5 | :584-629 `scan()` | 重寫為「擁有權取得 + 重試外殼」，原本文移入新私有方法 `_scan_once()`（§2、§3）。`_scan_idle` clear/set 保留（相容既有測試與 `_wait_for_scan_idle`），但移到鎖內執行 |
| D6 | :644-653 `_send_command` | 簽名加 `*, allow_during_recovery: bool = False`；開頭加 recovering 守門（§2） |
| D7 | :679、:689 `_connect` 內兩處 `_ensure_recovered` | 不改呼叫；`_ensure_recovered` 內部改為傳 `only_if_needed=True`（見 D10） |
| D8 | :773 `_handle_stream_stale` 內 `await self.recover(...)` | 改為 `await self._ensure_recovered(f"{message}; no disconnect acknowledgement")`——補上 coalescing 繞過缺口（驗收 2）。:771 已先設 `_needs_recovery = True`，語意不變 |
| D9 | :791-814 `_recover_if_connect_stuck` | 刪除（其兩個職責被吸收：needs_recovery 前置檢查 → `_scan_once` 開頭的 `_ensure_recovered`；wedged connect → `_acquire_scan_ownership` 的鎖逾時路徑）。全 repo grep 確認無測試直接引用此名 |
| D10 | :816-824 `_ensure_recovered` | `await self.recover(reason)` 改為 `await self.recover(reason, only_if_needed=True)` |
| D11 | :834-854 `_probe_firmware_alive` | :838 `self._send_command("AT+STATUS")` 改為 `self._send_command("AT+STATUS", allow_during_recovery=True)` |
| D12 | :856-909 `recover()` | (a) 簽名加 `*, only_if_needed: bool = False`；(b) 取得 `_recovery_lock` 後、:865 `_needs_recovery = True` 前，插入 coalesce 早退：`if only_if_needed and not self._needs_recovery: return`（前一個 recovery 已成功，佇列中的第二個直接放行）；(c) :866 `self._recovering = True` 下一行加 `self._transport_generation += 1`；(d) :876-879 兩個 `_send_command("AT+DISC")`/`("AT+RESET")` 加 `allow_during_recovery=True` |
| D13 | :1042-1052 `_handle_transport_failure` | :1049 `self._needs_recovery = True` 下一行加 `self._transport_generation += 1`（reader thread 經 call_soon_threadsafe 進 event-loop 執行，:1092；與協程同執行緒，無競態） |
| D14 | :922-929 `_fail_all_pending_operations` | scan future 的例外改設 `DongleTransactionAborted(message)`（connect/disconnect future 維持 `ConnectionError`，不動 `_connect` 既有語意） |

### app/windows/scan_panel.py

| # | 位置 | 改動 |
|---|---|---|
| S1 | :27-32 import 區 | 加 `from ..device_source import DongleTransactionAborted`（device_source 不 import scan_panel，無循環） |
| S2 | :550 `except Exception as exc:` 之前 | 插入專屬分支 `except DongleTransactionAborted as exc:`：顯示固定繁中文案（§5），原始 exc 寫入 `_write_scan_debug`，並設 `self._adapter_retry_allowed = True`（保證 :556-558 finally 一定重新啟用「搜尋裝置」按鈕，即使 `_adapter_available` 已被其他路徑翻 False） |

### app/windows/main_window.py

**零改動**。`_maybe_recover_source`（:604-626）已優先走 `ensure_recovered`，
reconnect 迴圈（:947-998）不變；本設計的序列化保證全部落在 DongleSource 層。

### tests（既有檔案的必要修改，2 處）

| # | 位置 | 原因與改法 |
|---|---|---|
| T1 | tests/test_dongle_source.py:265 `async def recover(reason)` | `_ensure_recovered` 改傳 kwarg 後會 TypeError。改為 `async def recover(reason: str, **_kwargs: object) -> None:` |
| T2 | tests/test_dongle_source.py:408 `async def recover_once(reason)` | 同上，加 `**_kwargs` |

---

## 2. 新增／修改的簽名

```python
# device_source.py 模組層（D2）
class DongleTransactionAborted(ConnectionError):
    """A dongle serial transaction (scan/connect preparation) was invalidated
    by a transport failure or an in-flight recovery.  Retryable on the new
    transport generation; the UI maps this to a friendly dongle message."""

# D6
def _send_command(self, text: str, *, allow_during_recovery: bool = False) -> None:
    if self._recovering and not allow_during_recovery:
        raise DongleTransactionAborted(
            f"dongle recovery in progress; refused to send {text.split('=')[0]}"
        )
    ...  # 原 body 不變

# D5 — scan 外殼（持鎖 + 重試）
async def scan(self, timeout: float = 5.0,
               supported_only: bool = True) -> list[DeviceScanResult]: ...
async def _acquire_scan_ownership(self) -> None:
    """Bounded _connect_lock acquire; a wedged in-flight connect is recovered
    (fails its future -> holder aborts -> lock released), then re-acquire.
    Raises DongleTransactionAborted if ownership still cannot be obtained."""
async def _scan_once(self, timeout: float) -> list[DeviceScanResult]:
    """One full scan transaction under an owned bus + a generation snapshot."""
async def _sleep_scan_window(self, timeout: float, generation: int) -> None:
    """Abortable advertisement window: poll every 0.2s, abort on generation
    change / needs_recovery / recovering instead of sleeping through failure."""
def _check_generation(self, generation: int, stage: str) -> None:
    """Raise DongleTransactionAborted when the snapshot is stale or the
    transport was flagged (needs_recovery / recovering) since the snapshot."""

# D12
async def recover(self, reason: str = "manual recovery",
                  *, only_if_needed: bool = False) -> None: ...
```

`scan()` / `_scan_once()` 的骨架（決定行為的部分全列）：

```python
async def scan(self, timeout=5.0, supported_only=True):
    await self._acquire_scan_ownership()          # 內含 wedged-connect 回收
    try:
        self._scan_idle.clear()
        last_error: Exception | None = None
        for attempt in range(1 + _DONGLE_SCAN_RETRY_ATTEMPTS):   # 共 2 次
            if attempt:
                _write_dongle_runtime_log("scan retry after recovery")
            try:
                await self._ensure_recovered("scan preflight")   # 交易開頭健康門
                return await self._scan_once(timeout)
            except DongleTransactionAborted as exc:
                last_error = exc
            except ConnectionError as exc:        # _send_command 途中炸掉
                last_error = exc
            # 只有 recovery 成功才值得重試；recovery 失敗直接放棄
            if attempt >= _DONGLE_SCAN_RETRY_ATTEMPTS:
                break
            try:
                await self._ensure_recovered(f"scan transaction aborted: {last_error}")
            except Exception as recover_exc:
                raise DongleTransactionAborted(
                    f"dongle unavailable after scan failure: {recover_exc}"
                ) from recover_exc
        raise DongleTransactionAborted(
            f"scan failed after retry: {last_error}") from last_error
    finally:
        self._scan_idle.set()
        self._connect_lock.release()

async def _scan_once(self, timeout):
    await self._wait_for_pending_disconnects()    # 既有 :591 語意保留
    generation = self._transport_generation       # 快照在 preflight 復原之後
    self._scan_lines, self._scan_expect = [], None
    self._scan_debug = True
    try:
        self._send_command("AT+SCAN")
        await self._sleep_scan_window(timeout, generation)
        self._check_generation(generation, "scan window")   # 驗收6：送 AT+STOP 前查旗標
        self._send_command("AT+STOP")
        future = self._loop.create_future()
        self._scan_future = future
        try:
            self._send_command("AT+LIST")
            await asyncio.wait_for(future, timeout=3.0)
        except asyncio.TimeoutError:
            if not self._scan_lines:              # 驗收7 裁量，見 §6
                self._needs_recovery = True
                raise DongleTransactionAborted(
                    "dongle did not answer AT+LIST and no live scan lines")
            _write_dongle_runtime_log(
                "AT+LIST timed out; returning live-collected scan lines")
        finally:
            self._consume_future_exception(future)
            self._scan_future = None
        self._check_generation(generation, "scan list")
        return self._parse_scan_results(self._scan_lines)
    finally:
        self._scan_debug = False
```

註：scan future 若被 `_fail_all_pending_operations` 設為
`DongleTransactionAborted`，`asyncio.wait_for(future)` 直接把它拋出 → 外殼捕捉
→ 重試。`supported_only` 參數維持既有忽略行為（dongle 韌體端已過濾）。

---

## 3. 鎖與旗標互動時序（三方文字時序圖）

參與者：`SCAN`（scan 交易協程）、`RDR`（reader thread）、`REC`（recovery，
在呼叫者協程內執行）、`ARC`（auto-reconnect 迴圈，main_window）、
`WD`（stream watchdog task）。

### 時序 A：5 秒視窗中 transport 死亡 → 中止 → coalesced recovery → 自動重試一次

```
SCAN: _acquire_scan_ownership() -> 持 _connect_lock；gen=G
SCAN: AT+SCAN 送出；進入 _sleep_scan_window(5s, G)（0.2s 輪詢）
RDR : serial.read 拋 OSError -> call_soon_threadsafe(_handle_transport_failure)
loop: _handle_transport_failure: needs_recovery=True; gen=G+1;
      _fail_all_pending_operations(scan future 尚未建立，無事);
      _reset_link_state -> managers 收 _dispatch_disconnect -> UI 排 ARC(1s 後)
SCAN: 下一個 0.2s 輪詢 -> _check_generation(G) 不符 -> DongleTransactionAborted
      （絕不送 AT+STOP 到舊/新 handle —— 驗收 1、6）
SCAN: 外殼捕捉 -> _ensure_recovered("scan transaction aborted")
      -> recover(only_if_needed=True)：取 _recovery_lock -> needs_recovery 仍 True
      -> _recovering=True; gen=G+2; AT+DISC/AT+RESET(allow_during_recovery)
      -> reopen -> probe AT+STATUS -> needs_recovery=False; _recovering=False
ARC : 1s 延遲到 -> _reconnect_device -> prepare_reconnect
      -> async with _connect_lock  ★被 SCAN 持有，排隊★
SCAN: 重試 attempt=1：_scan_once（gen=G+2 快照）AT+SCAN..AT+STOP..AT+LIST
      -> SCAN LIST 回 -> 回傳結果 -> finally 釋放 _connect_lock
ARC : 取得 _connect_lock -> _ensure_recovered(no-op) -> AT+DISC=<mac> -> 釋放
      -> _connect：取鎖 -> AT+CONN=<mac>
```
關鍵不變量：**recovery 後的掃描重試發生在同一次 `_connect_lock` 持有期內，
auto-reconnect 的 AT+DISC/AT+CONN 只能排在整個掃描交易（含重試）之後**——
「recovery 後的重試不與 reconnect 指令交錯」由鎖直接保證，不靠時間差。

### 時序 B：watchdog 觸發 recovery 與 scan 併發（coalescing）

```
WD  : _handle_stream_stale -> _disconnect(mac)（AT+DISC，單指令，鎖外，見 §8-R3）
      5s 無 DISCONNECTED -> needs_recovery=True
WD  : （D8 改）_ensure_recovered(...) -> recover(only_if_needed=True) 開始
      -> _recovering=True; gen+1
SCAN: 使用者此刻按「搜尋」-> _acquire_scan_ownership -> 取得 _connect_lock（空閒）
SCAN: _ensure_recovered("scan preflight") -> 見 _recovering=True
      -> async with _recovery_lock: pass  ★等 WD 的 recovery 收尾★
WD  : recovery 成功 -> needs_recovery=False -> 釋放 _recovery_lock
SCAN: needs_recovery=False -> 不重複 reset（coalesced，驗收 2）-> _scan_once 正常跑
（若 WD 的 recovery 失敗：needs_recovery 仍 True -> SCAN 呼叫
 recover(only_if_needed=True) -> 旗標為 True -> 再試一輪完整 reset；
 再敗 -> scan 外殼放棄 -> DongleTransactionAborted -> UI 友善訊息）
```
若反向併發（SCAN 先進 `_ensure_recovered` 且兩者同時看到 needs_recovery=True）：
兩者都呼叫 `recover(only_if_needed=True)`，`_recovery_lock` 序列化，第一個完成
reset 清旗標，第二個進鎖後早退——**同一故障絕不重置兩次**。

### 時序 C：掃描要求落在 wedged connect 上（鎖逾時逃生）

```
ARC : _connect 持 _connect_lock，AT+CONN 已送，韌體 wedged（35s 內無回應）
SCAN: _acquire_scan_ownership:
      wait_for(_connect_lock.acquire(), 4.0s) -> TimeoutError
      -> 有 pending connect future -> needs_recovery=True
      -> recover("scan requested over an unresponsive connect")   # 強制，非 only_if_needed
      -> _fail_all_pending_operations -> ARC 的 connect future 收 ConnectionError
ARC : wait_for(future) 立刻拋 -> _connect finally 清 _active_connect_mac -> 釋放鎖
      -> reconnect 迴圈記一次失敗，_maybe_recover_source 看 needs_recovery=False 跳過
SCAN: 二次 wait_for(_connect_lock.acquire(), 4.0s) -> 成功 -> 正常掃描
      （二次仍失敗 -> DongleTransactionAborted -> UI 友善訊息，按鈕可再按）
```
健康的 connect（含 0.8s settle）在 4 秒內完成並釋放鎖，SCAN 第一次等待即取得，
不會誤殺——門檻沿用現碼 `_DONGLE_PENDING_CONNECT_SCAN_WAIT_SECONDS = 4.0` 的語意。

---

## 4. 重試語意（次數、邊界、何時放棄）

| 操作 | 重試 | 邊界 | 放棄條件 |
|---|---|---|---|
| scan 交易 | 自動重試 **1** 次（`_DONGLE_SCAN_RETRY_ATTEMPTS=1`，共 2 次嘗試），單次使用者點擊內 | 重試前必須 `_ensure_recovered` 成功；重試在同一 `_connect_lock` 持有期內 | (a) recovery 拋例外（dongle 拔除/reopen 失敗）→ 立即放棄；(b) 第 2 次嘗試仍中止 → 放棄。兩者皆拋 `DongleTransactionAborted` → UI 友善訊息 + 按鈕可再按（使用者手動重試，不自動 loop） |
| recover() | 呼叫內不重試；probe 內建 3 次 × 1.5s（現碼 :221-222，不變） | `_recovery_lock` 序列化；`only_if_needed` 早退防重複 reset | reopen 6s 逾時或 probe 全敗 → 拋 ConnectionError，`needs_recovery` 保持 True，下一個觸發點（check_ready / 下次 scan / reconnect 的 ensure）再走完整 cycle |
| connect（manual/reconnect） | `_connect` 本身不重試（不變） | 逾時 35s / recovery 守門拒送 → 拋例外 | 交給呼叫者：manual → 對話框；reconnect 迴圈 → 快 ramp 1/3/5/10s ×10 後 30s 永久慢速（main_window.py:91-96，不變） |
| prepare_reconnect | 不重試（AT+DISC 失敗僅記 log，現碼 :576-579 不變） | D4 的 ensure + D6 守門 | — |

無限迴圈不可能：scan 至多 2 次嘗試；recovery 每次呼叫單 cycle；reconnect 迴圈
是既有的刻意永久慢速（unattended recording 需求，V1.0.26），不在本次改動範圍。

## 5. UI 錯誤訊息文案（繁中）

scan_panel.py `scan()` 新分支（S2）：

- QMessageBox 標題：`接收器連線中斷`
- 內文：
  ```
  與 Nordic dongle 的連線在掃描時中斷，程式已自動重置接收器並重試，但掃描仍未完成。

  請確認：
  1. dongle 已插緊在 USB 埠上
  2. 沒有其他程式正在使用該序列埠

  等待約 5 秒後，再按一次「搜尋裝置」即可重試。
  ```
- 清單空狀態（`_show_empty_result`）：標題 `接收器連線中斷`、說明
  `請檢查 dongle 後再按一次「搜尋裝置」。`
- `_set_scan_state("接收器連線中斷", "已自動重置接收器，請再搜尋一次。")`
- 原始例外字串只進 `_write_scan_debug` / `dongle_runtime.log`，**不進對話框**
  （驗收 4：不出現 pyserial 例外字串）。既有 `except Exception` 分支（:550）保持
  原樣，Bleak 路徑訊息不變。

## 6. 驗收條件 7（AT+LIST 靜默 timeout）表態

**本次修，但分兩檔**：(a) AT+LIST 逾時且 `_scan_lines` 為空 → 視為韌體無回應，
設 `needs_recovery` 並中止交易（走重試/友善錯誤）；(b) 逾時但掃描視窗已收到
FOUND/UPDATE 即時行（現碼 :1246-1248 本來就在收）→ 回傳已收結果、記 runtime log、
**不**設 needs_recovery。理由：(a) 正是本任務的失效類別，靜默空清單會把
transport 死亡偽裝成「附近沒裝置」，是隱蔽缺陷；(b) 若有即時行，BLE 與 CDC
明顯活著，只是 AT+LIST 回覆慢/被吞——此時標 recovery 會讓下一次 check_ready
重置 dongle、砍掉錄製中的健康連線，違反「交易穩健優先」。

## 7. 測試計畫

### 7.1 新增測試（tests/test_dongle_source.py，沿用 FakeSerial 家族 :40-69 與 `_make_source_with_fake_serial` :66-69）

| 測試名 | 模擬的失效階段 | 用的 fake / 手法 |
|---|---|---|
| `test_scan_aborts_before_at_stop_when_transport_dies_in_window` | 5 秒視窗中 reader 死亡（驗收 1、6 指名情境） | FakeSerial；scan(timeout=0.3) 跑到視窗中呼叫 `src._handle_transport_failure("x")`；斷言舊世代**沒有** AT+STOP、writes 出現第二個 AT+SCAN（重試），餵 `SCAN LIST: 0` 後回 `[]` |
| `test_scan_checks_needs_recovery_flag_before_at_stop` | 視窗中只設 `_needs_recovery=True`（無 transport 例外） | FakeSerial；斷言送 AT+STOP 前先走 recovery（writes 順序：AT+SCAN → AT+SCAN → AT+STOP → AT+LIST） |
| `test_scan_send_failure_mid_transaction_recovers_and_retries` | AT+STOP 送出時 serial write 炸 | 新 fake `FlakyWriteSerial(FakeSerial)`：第 N 次 write 拋 OSError，之後正常（加進 FakeSerial 家族） |
| `test_scan_gives_up_after_one_retry` | 兩次嘗試都中止 | FakeSerial + 每次進視窗就 `_handle_transport_failure`；斷言恰 2 個 AT+SCAN、拋 `DongleTransactionAborted`（驗收 3） |
| `test_scan_raises_transaction_aborted_when_recovery_fails` | 視窗中失效且 recovery 失敗（dongle 拔除） | `_owns_serial=True` + monkeypatch `_reopen_serial` 拋 OSError、`_DONGLE_POST_RESET_SETTLE_SECONDS=0`；斷言例外型別、`needs_recovery` 仍 True |
| `test_at_list_timeout_without_lines_aborts_and_retries` | AT+LIST 無回應且無即時行（驗收 7a） | FakeSerial + monkeypatch wait 逾時；第 2 次嘗試餵 `SCAN LIST: 0`；斷言第一次逾時後 `needs_recovery` 曾為 True |
| `test_at_list_timeout_with_live_lines_returns_results_no_recovery` | AT+LIST 無回應但收過 FOUND/UPDATE（驗收 7b） | FakeSerial；視窗中 `_on_line("FOUND 1: ...")`；斷言回傳 1 筆、`needs_recovery is False` |
| `test_concurrent_recovery_triggers_reset_only_once` | scan preflight 與 stream-stale 同時要求 recovery（驗收 2） | monkeypatch `_reopen_serial` 計數（`_owns_serial=True`、probe 由測試餵 STATUS 行）；兩個併發 `_ensure_recovered`；斷言 reset 恰 1 次 |
| `test_send_command_refused_during_recovery` | recovery 進行中第三方寫入 | FakeSerial；`_recovering=True` 手動設；`_send_command("AT+CONN=X")` 拋 `DongleTransactionAborted` 且 writes 為空；`allow_during_recovery=True` 可寫 |
| `test_scan_retry_serializes_ahead_of_reconnect_connect` | 三方時序 A 的核心不變量 | FakeSerial；scan 視窗中觸發 transport failure，同時 create_task 一個 `manager.connect(mac)`；斷言 writes 中 AT+CONN 出現在重試掃描的 AT+LIST 之後 |
| `test_scan_recovers_wedged_connect_then_scans`（改寫既有 :588 情境的補充） | 鎖被 wedged connect 佔住（時序 C） | FakeSerial；先起 `_connect`（不餵 CONNECTED），monkeypatch `_DONGLE_SCAN_OWNERSHIP_WAIT_SECONDS=0.05`；斷言 connect future 收 ConnectionError、掃描完成 |

### 7.2 新增測試（tests/test_scan_panel.py，沿用 :331 的 fake-ble 模式）

| 測試名 | 驗證 |
|---|---|
| `test_scan_panel_friendly_message_on_dongle_transaction_abort` | fake ble 的 `scan` 拋 `DongleTransactionAborted("serial write failed on COM3: ...")`; 斷言對話框文字含「dongle」且**不含** "COM3"/"serial"；`scan_btn.isEnabled()` 為 True（驗收 4） |
| `test_scan_panel_generic_error_path_unchanged_for_bleak` | fake ble 拋一般 `Exception`；斷言走原「掃描失敗」文案（驗收 5 回歸鎖） |

### 7.3 既有 176 測試衝擊面（逐一評估過的風險點）

- **需修改 2 個**：test_dongle_source.py:265、:408 的 monkeypatch fake `recover`
  加 `**_kwargs`（D10/D12 kwarg 所致，§1 T1/T2）。
- **驗證過應不變的高風險測試**：
  - `test_dongle_scan_waits_for_pending_disconnect_before_starting`（:523）——
    pending disconnect future 建立於 scan 取鎖前且不需要鎖；`_sleep_scan_window`
    對 timeout=0.01 睡 min(0.2, 0.01)；write 順序不變。
  - `test_scan_recovers_when_connect_left_dongle_wedged`（:588）——needs_recovery
    → preflight `_ensure_recovered` → recover(only_if_needed=True, 旗標 True →
    照常 reset；`_owns_serial=False` 跳過 reopen)；events/writes 斷言不變。
    世代快照在 preflight 之後抓，重試不會誤觸發。
  - `test_connect_waits_for_in_progress_scan`（:568）——`_wait_for_scan_idle`
    保留在 `_connect`（:683），測試手動 clear `_scan_idle` 的行為不變。
  - `test_ensure_recovered_waits_without_queueing_second_reset`（:349）——流程中
    needs_recovery 被清，monkeypatched recover 永不被呼叫，kwarg 不觸發。
  - `test_manager_stays_registered_when_recovery_precedes_connect`（:303）——
    recover 走 `_owns_serial=False` 路徑，`_recovering` 在 AT+CONN 送出前已 False，
    D6 守門不攔。
  - `test_recover_fails_pending_connect_and_resets_state`（:616）等直呼
    `recover()` 的測試——預設 `only_if_needed=False`，強制 reset 語意不變。
  - test_ui_imports.py 的 fake source（:347-2085）——自帶 `recover`/
    `ensure_recovered`，MainWindow 只傳單一位置參數（main_window.py:623 不改），
    不受影響。
  - test_scan_panel.py 既有掃描測試——只在新例外型別才走新分支。
- 其餘（protocol/csv/theme/updater/keeper 等）與改動無交集。
- 回歸門檻：全套 pytest = 176 通過 + 新增 13 全綠。

---

## 8. 對 8 條驗收條件的逐條對應

| # | 驗收條件 | 對應設計 |
|---|---|---|
| 1 | AT+SCAN／5 秒等待／AT+STOP／AT+LIST 任一階段 transport 失效 → 中止舊 transaction | 世代快照 + `_check_generation` 於視窗輪詢（`_sleep_scan_window`）、AT+STOP 前、AT+LIST 後三個檢查點（D5）；`_send_command` 失敗本身拋 ConnectionError 由外殼接手；scan future 由 `_fail_all_pending_operations` 設 `DongleTransactionAborted`（D14）。舊交易醒來只會拋例外，不會再寫任何指令 |
| 2 | coalesced recovery，不重複重置；補 `_handle_stream_stale` 繞過缺口 | D8 改走 `_ensure_recovered`；D12 的 `only_if_needed` 早退把「兩個呼叫者同時看到旗標、先後排進 `_recovery_lock`」的雙重 reset 窗口關死；`test_concurrent_recovery_triggers_reset_only_once` 驗證 |
| 3 | recovery 成功後自動重試完整掃描一次；有限次數 | scan 外殼 `_DONGLE_SCAN_RETRY_ATTEMPTS=1`（共 2 次嘗試）；重試前提是 `_ensure_recovered` 成功；`test_scan_gives_up_after_one_retry` 驗證上限 |
| 4 | 最終失敗 UI 顯示可理解的 dongle/COM 錯誤、無 pyserial 字串；按鈕可再按 | `DongleTransactionAborted` 型別分流 + 固定繁中文案（S2、§5）；原始字串只進 log；except 分支設 `_adapter_retry_allowed=True` 保證 finally 重新啟用按鈕；`test_scan_panel_friendly_message_on_dongle_transaction_abort` 驗證 |
| 5 | 不影響 PcBleSource/Bleak | PcBleSource/BleManager 零 diff；main_window 零 diff；scan_panel 僅新增例外分支，Bleak 例外不是該型別走原路；`test_scan_panel_generic_error_path_unchanged_for_bleak` 回歸鎖 |
| 6 | 與 auto-reconnect / pending disconnect / scan-connect lock 的競爭；視窗中 reader 設旗標 → 送 AT+STOP 前先查 | scan 交易整段持 `_connect_lock`（D5）→ reconnect 的 prepare/AT+CONN 只能排隊在掃描（含重試）之後（時序 A）；pending disconnect 沿用 `_wait_for_pending_disconnects`；wedged connect 走鎖逾時逃生（時序 C）；「先查旗標再送 AT+STOP」由 `_check_generation`（含 needs_recovery/recovering 檢查）直接實作，並有專測 `test_scan_checks_needs_recovery_flag_before_at_stop`；recovery 期間任何第三方寫入被 D6 守門硬拒 |
| 7 | AT+LIST 靜默 timeout 是否本次修——表態 | 修，分兩檔：無即時行 → 標 recovery + 中止重試；有即時行 → 回傳結果不標 recovery。理由與 trade-off 見 §6，兩個專測分別覆蓋 |
| 8 | 測試計畫：無硬體各階段失效、recovery 後同一次操作完成掃描、最終失敗仍可重試、全 pytest 不退步 | §7：13 個新測試全用 FakeSerial 家族（含新增 FlakyWriteSerial）無硬體；「同一次操作完成」由 retry-in-lock 測試（`test_scan_aborts_before_at_stop...` 斷言單次 scan() 呼叫回傳結果）；「仍可重試」由 scan_panel 按鈕測試；176 基準 + 2 處既有測試小改（T1/T2）已逐一評估 |

## 9. 殘餘風險（誠實列出）

- R1 `_sleep_scan_window` 0.2s 輪詢：失效偵測最壞延遲 0.2s（僅影響中止速度，
  不影響正確性）；換成 event 可即時但增加狀態面，判定不值得。
- R2 scan 持鎖使 manual connect 最多排隊 ~8s（視窗 5s + AT+LIST 3s）；UI 本就以
  `_is_scanning` 擋掃描中連線（scan_panel.py:628），實際入口已被 UI 序列化，
  鎖只是防禦縱深。
- R3 `_disconnect`（AT+DISC 單指令）仍在鎖外：watchdog 的 stale 斷線不必等掃描
  8 秒，且單指令不構成可被交錯的「交易」；recovery 期間由 D6 守門擋住。已接受。
- R4 `_transport_generation` 僅在 event-loop 執行緒變動（D13 經
  call_soon_threadsafe），無鎖但無競態；若未來有人在 reader thread 直接呼叫
  `_handle_transport_failure` 會破壞此假設——D13 處加註解防守。
- R5 韌體在 AT+STOP 與 AT+LIST 之間自行 reset 且 CDC 未斷（無任何失效訊號）：
  世代不變、AT+LIST 無回應 → 落入驗收 7a 路徑（重試一次），已覆蓋。
