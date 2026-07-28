# 最終設計：DongleSource 掃描交易容錯（評審裁決版）

日期：2026-07-28。基準碼：master 63800d5。基準測試：**176 passed（評審親自實跑確認）**。
兩份候選設計（design-minimal.md、design-robust.md）引用的行號已由評審逐一開檔抽查，
全部屬實（scan :584-629、_send_command :644-653、recover :856-909、_ensure_recovered
:816-824、_handle_stream_stale :771-773、_handle_transport_failure :1042-1052、
_fail_all_pending_operations :922-929、_reopen_serial :931-979、scan_panel :550-559、
main_window :91/:947/:1000、test_dongle_source :40-69/:265/:408/:523/:568/:588/:616）。

## 0. 評審裁決摘要

**主方案：robust（交易擁有權派）為骨架，嫁接 minimal 的四個優點。混合（hybrid）。**

三條指名裁決：

- **(a) 鎖**：**用鎖，用既有 `_connect_lock`**。scan 交易（含 recovery 後的自動重試）
  全程持有 `_connect_lock`；鎖階層單向 `_connect_lock` → `_recovery_lock`，全路徑
  已審計（見 §3 死鎖分析），**不會死鎖**。minimal 對「scan 拿 `_connect_lock` 會造成
  12s 假死循環」的批評不成立：其前提是「scan 持 scan-idle 等 connect-lock」，但本設計
  的 scan 先取鎖、取到鎖之後才 clear `_scan_idle`，不存在 hold-and-wait 環。
- **(b) AT+LIST 靜默 timeout**：**本次修**。兩位設計者一致主修，評審同意；條件採
  minimal 的最窄版：`timeout ∧ _scan_lines 為空 ∧ _scan_expect is None`（連
  `SCAN LIST:` header 都沒收到才視為 transport 可疑）。robust 的條件（只看 lines 為空）
  會把「header 說有 N 筆但行遺失」誤判為 transport 死亡——韌體明明活著（評審核對
  :1239-1257：header 到達即設 `_scan_expect`，N==0 直接 resolve future）。
- **(c) 重試上限**：**1 次自動重試（每次使用者點擊共 2 次完整 attempt）**。
  兩案一致，評審採納。recovery 失敗立即放棄不燒第二次 attempt。

嫁接自 minimal 的四點：

1. **coalescing 收在 `recover()` 本體**（minimal C6）取代 robust 的 `only_if_needed`
   kwarg：`recover()` 簽名不變 → robust 原需的 2 處既有測試修改（T1/T2，
   test_dongle_source.py:265/:408 的 fake recover）**全部免除**；且對現在與未來的
   所有呼叫端一體生效，`_handle_stream_stale`（:773）**不必改**（robust D8 作廢）。
2. AT+LIST 靜默判定的**最窄條件**（上述 (b)）。
3. **雙文案**：「重試仍失敗」與「recovery 本身失敗」給不同繁中訊息，掛在例外的
   `user_message` 屬性上由 UI 顯示。
4. （評審裁決，非任一原設計）**健康判定謂詞一律不含 `_running`**。評審實查：
   `_running` 只在 `__init__`（:460）與 `_reopen_serial`（:974）被設回 True；注入
   serial（`_owns_serial=False`）的 recovery 走 :872 分支跳過 reopen，`_running`
   永遠停在 False——minimal C5 的謂詞含 `not self._running`，其自家測試
   `test_scan_aborts_before_at_stop_when_transport_dies_mid_wait` 會因此在 attempt 2
   再度誤判失敗，是設計級缺陷。本設計以「generation 快照 + `_needs_recovery` +
   `_recovering`」判定（`_handle_transport_failure` :1049 先設 `_needs_recovery=True`
   才設 `_running=False`，故不漏接）。

捨棄自 robust 的三點（評審裁決）：D8（改 :773，已被嫁接 1 取代）、D10/D12(a)
（`only_if_needed` kwarg，同上）、D14（`_fail_all_pending_operations` 改例外型別——
不必要：scan 外殼統一捕 `ConnectionError` 後包成帶 `user_message` 的
`DongleTransactionAborted`，UI 分流只看最外層型別）。

---

## 1. 改動點清單（檔案:行號，以現碼 63800d5 為準）

### app/device_source.py

| # | 位置（現碼行號） | 改動 |
|---|---|---|
| F1 | :222 之後（`_DONGLE_PROBE_ATTEMPTS = 3` 下一行） | 新增常數：`_DONGLE_SCAN_RETRY_ATTEMPTS = 1`、`_DONGLE_SCAN_ABORT_POLL_SECONDS = 0.2`、`_DONGLE_SCAN_LIST_TIMEOUT_SECONDS = 3.0`（抽出 :612 魔數）、`_DONGLE_SCAN_OWNERSHIP_WAIT_SECONDS = 4.0`（沿用 `_DONGLE_PENDING_CONNECT_SCAN_WAIT_SECONDS` 的語意）、繁中文案常數 `_SCAN_UNAVAILABLE_MESSAGE`、`_SCAN_RECOVERY_FAILED_MESSAGE`（全文 §5） |
| F2 | :157 區段註解之後、:162 `_SOF0` 之前 | 新增模組層例外 `DongleTransactionAborted(ConnectionError)`（§2） |
| F3 | :486（`self._recovery_lock = asyncio.Lock()`）下一行 | 新增 `self._transport_generation: int = 0` |
| F4 | :569 `async with self._connect_lock:` 之後、:570 `_wait_for_scan_idle` 之前（prepare_reconnect） | 插入 `await self._ensure_recovered("reconnect preparation")`——reconnect 的 AT+DISC 永不落在待修復 transport 上 |
| F5 | :584-629 `scan()` | 整段重寫為「`_acquire_scan_ownership` + 重試外殼」；本文拆入新私有方法 `_scan_once` / `_sleep_scan_window` / `_check_generation`（完整骨架 §2）。`_scan_idle` clear/set 保留但移到取得鎖之後／釋放鎖之前 |
| F6 | :644 `_send_command` | 簽名加 `*, allow_during_recovery: bool = False`；函式第一行加 recovering 守門（§2）。原 body 不變 |
| F7 | :791-814 `_recover_if_connect_stuck` | **整段刪除**。兩個職責被吸收：needs_recovery 前置檢查 → scan 外殼每 attempt 的 `_ensure_recovered("scan preflight")`；wedged connect → `_acquire_scan_ownership` 的鎖逾時逃生。評審 grep 確認唯一呼叫點是 :595（scan 內），無測試直接引用此名 |
| F8 | :856-909 `recover()` | (a) :862 `async with self._recovery_lock:` **之前**加 `self._needs_recovery = True`（lock 前宣告意圖）；(b) 進 lock 後第一句加 coalesce 守門：`if not self._needs_recovery: _write_dongle_runtime_log(f"recovery skipped (already completed concurrently): {reason}"); return`；(c) :866 `self._recovering = True` 下一行加 `self._transport_generation += 1`；(d) :876 `AT+DISC`、:878 `AT+RESET` 兩個 `_send_command` 加 `allow_during_recovery=True`。原 :865 的 `self._needs_recovery = True` 保留（無害）。簽名**不變** |
| F9 | :838（`_probe_firmware_alive` 內） | `self._send_command("AT+STATUS")` → `self._send_command("AT+STATUS", allow_during_recovery=True)` |
| F10 | :1049（`_handle_transport_failure` 內 `self._needs_recovery = True`）下一行 | 加 `self._transport_generation += 1` + 註解「本方法必須經 call_soon_threadsafe 在 event-loop 執行緒執行（:1092），generation 才免鎖安全」 |

### app/windows/scan_panel.py

| # | 位置 | 改動 |
|---|---|---|
| S1 | :27-32 import 區 | 加 `DongleTransactionAborted` 到既有 `from ..device_source import ...`（device_source 不 import scan_panel，無循環） |
| S2 | :550 `except Exception as exc:` **之前** | 插入專屬分支（完整碼 §5）：顯示 `exc.user_message` 繁中文案、原始例外只進 `_write_scan_debug`、設 `self._adapter_retry_allowed = True` 保證 :556-558 finally 一定重新啟用「搜尋裝置」按鈕 |

### app/windows/main_window.py 與 tests/

**零改動**。`_maybe_recover_source`（:604）、reconnect 迴圈（:947-998）、
`RECONNECT_DELAYS_SECONDS`（:91）全部不動。既有 176 個測試**一個都不改**
（`recover()` 簽名不變，:265/:408 的單參數 fake 照常可用——這是嫁接 1 的直接收益）。

---

## 2. 新增／修改的簽名與骨架

```python
# device_source.py 模組層（F2）
class DongleTransactionAborted(ConnectionError):
    """A dongle serial transaction (scan) was invalidated by a transport
    failure or an in-flight recovery.  str(exc) is the technical detail
    (log-only); user_message, when set, is the zh-TW text safe for the UI."""

    def __init__(self, detail: str, *, user_message: str = "") -> None:
        super().__init__(detail)
        self.user_message = user_message


# F6
def _send_command(self, text: str, *, allow_during_recovery: bool = False) -> None:
    if self._recovering and not allow_during_recovery:
        raise DongleTransactionAborted(
            f"dongle recovery in progress; refused to send {text.split('=')[0]}"
        )
    ...  # 原 :645-653 body 一字不改
```

`scan()` 外殼與各新私有方法（決定行為的部分全列；實作者可照抄）：

```python
async def scan(
    self, timeout: float = 5.0, supported_only: bool = True
) -> list[DeviceScanResult]:
    await self._acquire_scan_ownership()
    try:
        self._scan_idle.clear()
        last_error: Exception = ConnectionError("scan did not start")
        user_message = _SCAN_UNAVAILABLE_MESSAGE
        for attempt in range(1 + _DONGLE_SCAN_RETRY_ATTEMPTS):      # 共 2 次
            if attempt:
                _write_dongle_runtime_log(
                    f"scan retry {attempt}/{_DONGLE_SCAN_RETRY_ATTEMPTS} "
                    "after transport recovery"
                )
            try:
                # 每個 attempt 開頭的健康門：attempt 1 吸收原 :595 的
                # needs_recovery 分支；attempt 2 就是「recovery 成功才重試」。
                await self._ensure_recovered("scan preflight")
            except Exception as exc:
                last_error = exc
                user_message = _SCAN_RECOVERY_FAILED_MESSAGE
                break                       # recovery 救不回來：立即放棄
            try:
                return await self._scan_once(timeout)
            except ConnectionError as exc:  # 含 DongleTransactionAborted
                last_error = exc
                _write_dongle_runtime_log(
                    f"scan attempt {attempt + 1} aborted: {exc}"
                )
        detail = self._last_transport_error or str(last_error)
        _write_dongle_runtime_log(f"scan gave up: {detail}")
        raise DongleTransactionAborted(
            detail, user_message=user_message
        ) from last_error
    finally:
        self._scan_idle.set()
        self._connect_lock.release()

async def _acquire_scan_ownership(self) -> None:
    """Bounded acquire of _connect_lock with two escape hatches."""
    try:
        await asyncio.wait_for(
            self._connect_lock.acquire(), _DONGLE_SCAN_OWNERSHIP_WAIT_SECONDS
        )
        return
    except asyncio.TimeoutError:
        pass
    pending = [f for f in self._connect_futures.values() if not f.done()]
    if pending:
        # 沿用原 _recover_if_connect_stuck :810-814 語意：>4s 未決的 connect
        # 視為 wedged，強制 recovery 使其 future 收錯、持鎖者退出釋放鎖。
        self._needs_recovery = True
        try:
            await self.recover("scan requested over an unresponsive connect")
        except Exception as exc:
            raise DongleTransactionAborted(
                f"recovery failed while freeing a wedged connect: {exc}",
                user_message=_SCAN_RECOVERY_FAILED_MESSAGE,
            ) from exc
    elif self._recovering or self._needs_recovery:
        # 持鎖者正在等一場 recovery（如 _connect 的 preflight）：等它收尾。
        try:
            await self._ensure_recovered("scan waiting for in-flight recovery")
        except Exception as exc:
            raise DongleTransactionAborted(
                f"recovery failed while scan waited for the bus: {exc}",
                user_message=_SCAN_RECOVERY_FAILED_MESSAGE,
            ) from exc
    try:
        await asyncio.wait_for(
            self._connect_lock.acquire(), _DONGLE_SCAN_OWNERSHIP_WAIT_SECONDS
        )
    except asyncio.TimeoutError:
        raise DongleTransactionAborted(
            "scan could not obtain the dongle command bus",
            user_message=_SCAN_UNAVAILABLE_MESSAGE,
        ) from None

async def _scan_once(self, timeout: float) -> list[DeviceScanResult]:
    await self._wait_for_pending_disconnects()        # 原 :591，每 attempt 重等
    generation = self._transport_generation           # 快照在 preflight 之後
    self._scan_lines = []
    self._scan_expect = None
    _write_scan_debug("dongle scan: AT+SCAN")
    self._scan_debug = True
    try:
        self._send_command("AT+SCAN")
        await self._sleep_scan_window(timeout, generation)
        # 驗收 6 指名情境：5 秒等待結束「先查旗標、再送 AT+STOP」。
        self._check_generation(generation, "scan window")
        _write_scan_debug("dongle scan: AT+STOP")
        self._send_command("AT+STOP")
        future: asyncio.Future[bool] = self._loop.create_future()
        self._scan_future = future
        self._scan_expect = None
        _write_scan_debug("dongle scan: AT+LIST")
        try:
            self._send_command("AT+LIST")
            await asyncio.wait_for(
                future, timeout=_DONGLE_SCAN_LIST_TIMEOUT_SECONDS
            )
        except asyncio.TimeoutError:
            if not self._scan_lines and self._scan_expect is None:
                # 驗收 7：零收集行且連 SCAN LIST header 都沒有 —— 韌體
                # 對 AT+LIST 完全沉默，transport 可疑，中止並走重試。
                self._needs_recovery = True
                raise DongleTransactionAborted(
                    "AT+LIST unanswered with no live scan lines"
                )
            _write_scan_debug(
                "dongle scan: AT+LIST timed out; using collected lines"
            )
        finally:
            self._consume_future_exception(future)
            self._scan_future = None
        self._check_generation(generation, "scan list")
        results = self._parse_scan_results(self._scan_lines)
        _write_scan_debug(
            f"dongle scan: parsed {len(results)} device(s) from "
            f"{len(self._scan_lines)} collected line(s)"
        )
        return results
    finally:
        self._scan_debug = False

async def _sleep_scan_window(self, timeout: float, generation: int) -> None:
    """Abortable advertisement window: poll instead of sleeping through death."""
    deadline = self._loop.time() + timeout
    while True:
        self._check_generation(generation, "scan window")
        remaining = deadline - self._loop.time()
        if remaining <= 0:
            return
        await asyncio.sleep(min(_DONGLE_SCAN_ABORT_POLL_SECONDS, remaining))

def _check_generation(self, generation: int, stage: str) -> None:
    # 謂詞刻意不含 _running（評審裁決，§0 嫁接 4）：注入 serial 的 recovery
    # 不會重設 _running；needs_recovery 已足夠（:1049 先於 :1050 設定）。
    if (
        generation != self._transport_generation
        or self._needs_recovery
        or self._recovering
    ):
        raise DongleTransactionAborted(
            f"dongle transport changed during scan ({stage})"
        )
```

`recover()` 開頭（F8 (a)(b)，其餘 body 沿用 :863-909 加 (c)(d)）：

```python
async def recover(self, reason: str = "manual recovery") -> None:
    # Declare intent before queueing so a recovery that completes while we
    # wait on the lock marks our failure as already serviced (coalescing).
    self._needs_recovery = True
    async with self._recovery_lock:
        if not self._needs_recovery:
            _write_dongle_runtime_log(
                f"recovery skipped (already completed concurrently): {reason}"
            )
            return
        ...  # 原 :863-909，含 (c) generation += 1、(d) allow_during_recovery
```

`scan()` 的 `supported_only` 參數維持既有忽略行為；`ConnectionError` 以外的例外
（TimeoutError、RuntimeError、CancelledError）原樣穿透不重試，行為與今天一致。

---

## 3. 鎖與旗標互動時序 + 死鎖分析

參與者：`SCAN`（scan 交易）、`RDR`（reader thread）、`REC`（recovery）、
`ARC`（auto-reconnect，main_window :947→:1000→device_source `_connect` :675）、
`WD`（stream watchdog → `_handle_stream_stale` :753）。

### 時序 A：5 秒視窗中 transport 死亡 → 中止 → recovery → 同鎖內重試成功

```
SCAN: _acquire_scan_ownership -> 持 _connect_lock；_scan_idle.clear()
SCAN: preflight no-op；_scan_once：gen 快照=G；AT+SCAN；進 0.2s 輪詢視窗
RDR : serial.read 拋例外 -> call_soon_threadsafe(_handle_transport_failure)
loop: needs_recovery=True; gen=G+1; _running=False; fail pending futures;
      _reset_link_state -> _dispatch_disconnect -> UI 排 ARC（1s 後醒）
SCAN: 下一輪詢點 _check_generation(G) 不符 -> DongleTransactionAborted
      （AT+STOP 一個位元組都沒送 —— 驗收 1、6）
SCAN: 外殼捕捉 -> attempt 2 preflight _ensure_recovered：
      旗標 True -> recover()：lock 前設旗標 -> 取 _recovery_lock
      -> gen=G+2 -> AT+DISC/AT+RESET(allow) -> reopen -> probe OK
      -> 旗標清除 -> 釋放 _recovery_lock
ARC : 1s 到 -> _reconnect_device -> prepare_reconnect
      -> async with _connect_lock ★被 SCAN 持有，排隊★
SCAN: attempt 2：gen 快照=G+2；AT+SCAN..AT+STOP..AT+LIST -> 結果
SCAN: finally：_scan_idle.set()；release _connect_lock
ARC : 取得鎖 -> F4 ensure(no-op) -> AT+DISC=<mac> -> ... -> AT+CONN
```

**核心不變量：recovery 後的掃描重試發生在同一次 `_connect_lock` 持有期內；
auto-reconnect 的 AT+DISC/AT+CONN 只能排在整個掃描交易（含重試）之後。**
由鎖直接保證，不靠時間差——這是本裁決選 robust 骨架的決定性理由：minimal 的
無鎖方案存在其自認的 R1 視窗（`_wait_for_scan_idle` 12s 到期「proceeding」:721
後 AT+CONN 與重試掃描交錯，正是本次要根治的韌體 wedge 類故障）。

### 時序 B：多方同時要求 recovery（coalescing，驗收 2）

```
WD  : :771 needs_recovery=True -> :773 recover()（不改）：lock 前設旗標 -> 排隊
SCAN: preflight _ensure_recovered -> 旗標 True -> recover()：lock 前設旗標 -> 排隊
先到者: 取 _recovery_lock -> 守門看旗標 True -> 完整 reset -> 旗標 False -> 釋放
後到者: 取 _recovery_lock -> 守門看旗標 False -> log + return（不做第二次 reset）
check_ready(:518)/_maybe_recover_source(:604) 走 _ensure_recovered：
  _recovering=True 時先 async with lock: pass 等收尾，旗標 False 即不再觸發
```

一場物理 reset 服務所有觸發者。守門在 `recover()` 本體，**所有**呼叫端（含
`_handle_stream_stale` 的直呼、未來新增的呼叫端）自動被涵蓋——minimal C6 的優點，
且 `recover()` 簽名不變，免改任何 fake。

### 時序 C：掃描落在 wedged connect 上（鎖逾時逃生）

```
ARC : _connect 持 _connect_lock，AT+CONN 已送，韌體 wedged（35s 無回應）
SCAN: wait_for(acquire, 4s) 逾時 -> 有未決 connect future
      -> recover("scan requested over an unresponsive connect")（強制）
      -> _fail_all_pending_operations -> ARC 的 future 收 ConnectionError
ARC : wait_for(future) 立即拋 -> finally 清理 -> 釋放 _connect_lock
SCAN: 二次 wait_for(acquire, 4s) 成功 -> 正常掃描
      （二次仍失敗 -> DongleTransactionAborted + 友善文案，按鈕可再按）
```

健康 connect（含 0.8s settle）4 秒內完成釋鎖，第一次等待即取得，不誤殺；
門檻沿用現碼 `_DONGLE_PENDING_CONNECT_SCAN_WAIT_SECONDS = 4.0` 的既有語意。

### 死鎖分析（裁決 (a) 的證明）

- **鎖階層單向：`_connect_lock` → `_recovery_lock`。** 逐路徑審計：
  - `_connect`（:678 取 connect → :679/:689 ensure → recovery lock）：順向。
  - `prepare_reconnect`（:569 取 connect → F4 ensure → recovery lock）：順向。
  - scan 外殼（持 connect → preflight ensure → recovery lock）：順向。
  - `_acquire_scan_ownership` 逃生路徑（**不持** connect lock 時取 recovery lock）：
    合法（順向的前綴）。
  - `check_ready` :518、`_maybe_recover_source`、`_handle_stream_stale` :773、
    `ensure_recovered` :553：只取 recovery lock，從不取 connect lock。
  - `recover()` body：從不 await `_connect_lock` 或 `_scan_idle`；
    `_reset_link_state` 對 UI 的通知只排 task，不同步取鎖（評審核對）。
- **`_scan_idle` 不構成環**：scan 只在**已取得** `_connect_lock` 之後才 clear
  `_scan_idle`；`_wait_for_scan_idle`（:712-721）只被持有 `_connect_lock` 的
  `_connect`/`prepare_reconnect` 呼叫——此時 scan 不可能持有 idle-clear 狀態
  （它要嘛在鎖外且 idle 已 set，要嘛排隊等鎖）。即使有殘餘情境，等待有界 12s。
- 無環、等待有界 → **無死鎖**。

---

## 4. 重試語意（裁決 (c)）

| 操作 | 重試 | 邊界 | 放棄條件 |
|---|---|---|---|
| scan 交易 | 自動重試 **1** 次（`_DONGLE_SCAN_RETRY_ATTEMPTS = 1`，共 2 次 attempt），單次使用者點擊內、同一 `_connect_lock` 持有期內 | 重試前提 = attempt 開頭的 `_ensure_recovered` 成功 | (a) recovery 拋例外 → **立即**放棄（不燒第二 attempt），文案切 `_SCAN_RECOVERY_FAILED_MESSAGE`；(b) 第 2 次 attempt 仍中止 → 放棄。兩者皆拋帶 `user_message` 的 `DongleTransactionAborted`；`_needs_recovery` 可能保持 True，下一次按鈕由 check_ready（:497-535）接手——與既有 never-give-up 層銜接，且每輪都需使用者按鍵，不會無限 loop |
| recover() | 呼叫內不重試；probe 內建 3×1.5s（:221-222 不變） | `_recovery_lock` 序列化 + 本體 coalesce 守門 | reopen 6s 逾時或 probe 全敗 → 拋 ConnectionError、旗標保持 True |
| connect（manual/auto） | `_connect` 本身不重試（不變） | 35s timeout / recovering 守門拒送 | manual → 對話框；auto → 既有 1/3/5/10s ×N 後 30s 永久慢速（main_window :91-96，不變） |

觸發重試的例外：`_scan_once` 拋出的任何 `ConnectionError`（含
`DongleTransactionAborted`、`_send_command` 的寫入失敗、scan future 被
`_fail_all_pending_operations` :926 設的 ConnectionError）。其他例外原樣穿透。

最壞牆鐘時間：ownership（≤4+~12+4≈20s，僅 wedged-connect 病態路徑）+
attempt1（≤5+3=8s）+ recovery（≤~12s）+ attempt2（≤8s）≈ 48s 絕對上界；
典型失敗路徑 ~28s。有界，無限迴圈不可能。

---

## 5. UI 錯誤訊息文案（繁中）

```python
# device_source.py（F1）
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

```python
# scan_panel.py scan() 內，插在 :550 既有 except Exception 之前（S2）
except DongleTransactionAborted as exc:
    message = exc.user_message or _SCAN_UNAVAILABLE_MESSAGE
    _write_scan_debug(f"dongle scan aborted: {exc}")
    self._adapter_retry_allowed = True   # 保證 finally(:556-558) 重新啟用按鈕
    QMessageBox.warning(self, "接收器連線中斷", message)
    self._show_empty_result("接收器連線中斷", "請檢查 dongle 後再按一次「搜尋裝置」。")
    self._set_scan_state("接收器連線中斷", "請檢查 dongle 後再按一次「搜尋裝置」。")
```

- pyserial 原始字串（`ClearCommError` 等）只存在於 `str(exc)` → `_write_scan_debug`
  與 `dongle_runtime.log`，**永不上對話框**（驗收 4）。
- 既有 `except Exception` 分支（:550-553）一字不改：Bleak/PcBleSource 例外不是
  `DongleTransactionAborted`，走原路徑，訊息位元級不變（驗收 5）。

---

## 6. 測試計畫（無硬體；FakeSerial 家族 :40-69 + `_make_source_with_fake_serial` :66-69）

槓桿：注入 serial 時 `_owns_serial=False`，`recover()` 跳過 reset/reopen/probe
（:872 分支）直接清旗標「成功」——fake 天然模擬 recovery 成功。
**注意（評審驗證過的陷阱）**：`_handle_transport_failure` 會把 `_running` 壓 False
且注入 serial 的 recovery 不會恢復它；本設計所有健康謂詞不含 `_running`，
測試也不得斷言 `_running`。

新 fake（加在 WriteFailSerial :61-63 之後）：

```python
class FlakyWriteSerial(FakeSerial):
    """Fail writes whose command starts with `fail_on`, `times` times, then heal."""
    def __init__(self, fail_on: str, times: int = 1) -> None: ...
```

### 6.1 tests/test_dongle_source.py 新增（11 個）

| 測試名 | 失效階段 | 手法與關鍵斷言 |
|---|---|---|
| `test_scan_aborts_before_at_stop_when_transport_dies_in_window` | 5s 視窗中 reader 死亡（驗收 1、6 指名） | scan(timeout=0.3) 視窗中呼叫 `src._handle_transport_failure("x")`；斷言第一 attempt **無** AT+STOP、出現第二個 AT+SCAN；餵 `SCAN LIST: 0` 後回 `[]`、`_needs_recovery is False` |
| `test_scan_checks_needs_recovery_flag_before_at_stop` | 視窗中只設 `_needs_recovery=True`（無例外、無 gen 變化以外訊號） | 斷言 writes 順序 = AT+SCAN → AT+SCAN → AT+STOP → AT+LIST（旗標先查再送） |
| `test_scan_send_failure_mid_transaction_recovers_and_retries` | AT+STOP 寫入炸 | `FlakyWriteSerial("AT+STOP", 1)`；斷言重試後成功、同一次 scan() 呼叫內回傳 |
| `test_scan_gives_up_after_one_retry` | 兩次 attempt 都中止 | 每次進視窗就 `_handle_transport_failure`；斷言恰 2 個 AT+SCAN、`pytest.raises(DongleTransactionAborted)`、`exc.user_message == _SCAN_UNAVAILABLE_MESSAGE`（驗收 3） |
| `test_scan_raises_recovery_failed_message_when_recovery_fails` | 視窗中失效且 recovery 失敗 | `_owns_serial=True` + monkeypatch `_reopen_serial` 拋 OSError、settle=0；斷言 `exc.user_message == _SCAN_RECOVERY_FAILED_MESSAGE`、`"serial" not in exc.user_message`、旗標保持 True、恰 1 個 AT+SCAN（不燒第二 attempt） |
| `test_at_list_timeout_without_lines_aborts_and_retries` | AT+LIST 全靜默（驗收 7 主檔） | monkeypatch `_DONGLE_SCAN_LIST_TIMEOUT_SECONDS=0.02`；attempt 1 不餵任何行、attempt 2 餵 `SCAN LIST: 0`；斷言重試發生且最終成功 |
| `test_at_list_timeout_with_live_lines_returns_partial_results` | AT+LIST 無回應但視窗有 FOUND 行 | 同 monkeypatch；視窗中 `_on_line("FOUND 0: #7 ...")`；斷言回傳 1 筆、單一 AT+SCAN（不重試）、旗標 False |
| `test_at_list_timeout_with_header_but_no_rows_is_lenient` | header 到了、行遺失（最窄條件的邊界） | 餵 `SCAN LIST: 2` 後不餵行；斷言回傳 `[]`、不重試、旗標 False——鎖住裁決 (b) 的窄條件 |
| `test_concurrent_ensure_recovered_triggers_reset_only_once` | 併發 coalescing（驗收 2） | spy `_reset_link_state`；`gather(_ensure_recovered("a"), _ensure_recovered("b"))`（旗標預設 True）；斷言 spy 恰 1 次、旗標 False |
| `test_direct_concurrent_recover_calls_coalesce` | `recover()` 本體守門（含 `_handle_stream_stale` 直呼路徑） | spy `_reset_link_state`；`gather(recover("a"), recover("b"))`；斷言 spy 恰 1 次 |
| `test_send_command_refused_during_recovery` | recovery 期間第三方寫入 | `_recovering=True` 手動設；`_send_command("AT+CONN=X")` 拋 `DongleTransactionAborted` 且 `serial.writes == []`；`allow_during_recovery=True` 可寫；斷言 `_needs_recovery` 未被此路徑改動 |
| `test_scan_retry_serializes_ahead_of_reconnect_connect` | 時序 A 核心不變量（驗收 6） | 視窗中觸發 transport failure，同時 create_task `manager.connect(mac)`；斷言 writes 中 AT+CONN 在重試掃描的 AT+LIST 之後 |
| `test_scan_recovers_wedged_connect_then_scans` | 時序 C | 先起 `_connect`（不餵 CONNECTED）、monkeypatch `_DONGLE_SCAN_OWNERSHIP_WAIT_SECONDS=0.05`；斷言 connect future 收 ConnectionError、掃描完成 |

### 6.2 tests/test_scan_panel.py 新增（2 個）

| 測試名 | 驗證 |
|---|---|
| `test_scan_panel_friendly_message_on_dongle_transaction_abort` | stub source 的 `scan` 拋 `DongleTransactionAborted("serial write failed on COM3: ClearCommError", user_message=_SCAN_UNAVAILABLE_MESSAGE)`；monkeypatch QMessageBox.warning 收參數；斷言對話框文字含「dongle」、**不含** "COM3"/"serial"/"ClearCommError"；`scan_btn.isEnabled()` 為 True（驗收 4） |
| `test_scan_panel_generic_error_path_unchanged_for_bleak` | stub 拋一般 `Exception("boom")`；斷言走原「掃描失敗」文案（驗收 5 回歸鎖） |

### 6.3 既有 176 測試衝擊面（評審逐點核對）

- **零修改**（robust 原案的 T1/T2 因嫁接 1 而免除）。
- 高風險點逐一核對：
  - `test_scan_recovers_when_connect_left_dongle_wedged`（:588，斷言 writes ==
    `["AT+SCAN","AT+STOP","AT+LIST"]`）：新流程 = 取鎖（空閒，即得）→ preflight
    recover（`_owns_serial=False` 無寫入、events/[mac]/旗標斷言全部照舊）→
    AT+SCAN → 0.01s 視窗（`_sleep_scan_window` 睡 min(0.2, 0.01)）→ AT+STOP →
    AT+LIST → 測試餵 `SCAN LIST: 0` → 回 []。**通過**。
  - `test_dongle_scan_waits_for_pending_disconnect_before_starting`（:523）：
    `_wait_for_pending_disconnects` 保留在 `_scan_once` 開頭，順序不變。
  - `test_connect_waits_for_in_progress_scan`（:568）：`_wait_for_scan_idle`
    留在 `_connect`（:683）不動；測試手動 clear `_scan_idle` 的行為不變。
  - `test_recover_fails_pending_connect_and_resets_state`（:616）與其他直呼
    `recover()` 的測試（:743、:771、:423）：F8(a) 先設旗標 → 守門 True → 照常執行；
    結尾旗標斷言不變。
  - `test_ensure_recovered_waits_without_queueing_second_reset`（:349）、
    `test_readiness_check_recovers_owned_dongle_after_reader_failure`（:250 +
    :265 fake）、`test_connect_rechecks_recovery_after_preflight_waits`（:399 +
    :408 fake）：`recover()`/`_ensure_recovered` 簽名與呼叫形式不變，fake 照常。
  - `test_manager_stays_registered_when_recovery_precedes_connect`（:303）：
    AT+CONN 送出時 `_recovering` 已 False，F6 守門不攔。
  - test_ui_imports.py 的 fake source 自帶 recover/ensure_recovered，不受影響。
- 回歸門檻：**基準 176 全綠 + 新增 15 全綠，0 fail**。

---

## 7. 對 8 條驗收條件的逐條對應

| # | 驗收條件 | 對應設計 |
|---|---|---|
| 1 | AT+SCAN／5 秒等待／AT+STOP／AT+LIST 任一階段失效 → 中止舊 transaction | 寫入階段：`_send_command` 既有 ConnectionError + F6 守門；等待階段：`_sleep_scan_window` 0.2s 輪詢 + `_check_generation`（gen 快照）；AT+LIST 等待：`_fail_all_pending_operations`（:926）對 scan future set_exception；AT+LIST 靜默：§2 最窄條件。中止即拋例外，舊交易絕不對新世代 handle 再寫任何指令 |
| 2 | coalesced recovery，不重複重置；補 `_handle_stream_stale` 繞過缺口 | F8：守門收在 `recover()` 本體（lock 前宣告、lock 後旗標已清即跳過），:773 直呼零改動即被涵蓋；`_recovery_lock` 序列化。兩個併發專測鎖住行為 |
| 3 | recovery 成功後自動重試完整掃描一次；有限次數 | `_DONGLE_SCAN_RETRY_ATTEMPTS = 1`；重試 = 完整 `_scan_once`（AT+SCAN 起頭）；recovery 失敗立即放棄；最壞 ~28s（病態 ~48s）有界；`test_scan_gives_up_after_one_retry` 鎖上限 |
| 4 | 最終失敗 UI 顯示可理解訊息（無 pyserial 字串），按鈕仍可按 | `DongleTransactionAborted.user_message` 雙文案（§5）；原始字串只進 log；S2 分支設 `_adapter_retry_allowed=True` 保證 finally（:556-558）重新啟用按鈕；scan_panel 專測驗證 |
| 5 | 不影響 PcBleSource/Bleak | PcBleSource/BleManager/main_window 零 diff；scan_panel 僅新增型別分流分支，Bleak 例外走原路；`test_scan_panel_generic_error_path_unchanged_for_bleak` 回歸鎖 |
| 6 | 與 auto-reconnect／pending disconnect／scan-connect lock 的競爭；等待結束先查旗標再送 AT+STOP | scan 全程持 `_connect_lock` → reconnect 的 prepare/AT+CONN 排在整個交易（含重試）之後（時序 A，由鎖硬保證）；pending disconnect 沿用 `_wait_for_pending_disconnects` 每 attempt 重等；wedged connect 走鎖逾時逃生（時序 C）；「先查旗標再送 AT+STOP」= `_check_generation(generation, "scan window")`，專測覆蓋；recovery 期間任何第三方寫入被 F6 硬拒；鎖階層單向無死鎖（§3 證明） |
| 7 | AT+LIST 靜默 timeout 本次修不修——表態 | **修**（裁決 (b)）：timeout ∧ 零收集行 ∧ 無 header → 標 recovery + 中止重試；有 header 或有行 → 維持既有寬容回傳。0xFF03 故障劇本的主幹路徑（CDC 活著、韌體死透、AT+LIST 永無回音）因此被真正覆蓋，不再說謊「沒有找到支援裝置」；誤判面在現有韌體行為下不存在（header 是 AT+LIST 的同步回覆），邊界由 `test_at_list_timeout_with_header_but_no_rows_is_lenient` 鎖住 |
| 8 | 測試計畫：各階段失效、recovery 後同次操作完成、最終失敗仍可重試、全 pytest 不退步 | §6：15 個新測試逐階段對應、全用 FakeSerial 家族無硬體；「同次完成」由 retry 測試斷言單次 scan() 呼叫回傳結果；「仍可重試」由 scan_panel 按鈕測試；基準 176（評審實跑確認）零修改、逐點審計 |

---

## 8. 殘餘風險（最終設計選擇接受的）

- **R1 偵測延遲 0.2s**：視窗輪詢粒度；只影響中止速度不影響正確性。
- **R2 scan 持 `_connect_lock` 失敗路徑最長 ~28s**：期間 manual/auto connect 排隊。
  UI 本就以 `_is_scanning`（scan_panel:628 一帶）擋掃描中連線，auto-reconnect 由
  never-give-up 迴圈保證最終重連；鎖是防禦縱深。
- **R3 `_disconnect`（單指令 AT+DISC）仍在鎖外**：watchdog 的 stale 斷線不必等掃描；
  單指令不構成可交錯的交易；recovery 期間由 F6 守門擋住。接受。
- **R4 generation 免鎖依賴「只在 event-loop 執行緒變動」**：F10 加註解防守；
  若未來有人繞過 `call_soon_threadsafe` 直呼 `_handle_transport_failure` 會破壞假設。
- **R5 韌體在 AT+STOP 與 AT+LIST 間自行 reset 且 CDC 未斷**：無失效訊號、gen 不變 →
  落入驗收 7 路徑（重試一次），已覆蓋。
- **R6 7a 誤判**：韌體活著但 3 秒內連 header 都不回（現有韌體無此行為）→ 多一次
  reset、掃描慢 ~15s，結果正確。
- **R7 recovery 佔用期間 `_acquire_scan_ownership` 的無 future 路徑**：持鎖者若正等
  一場逼近 12s 上限的 recovery，scan 可能在 4+4s 後放棄並顯示友善訊息；使用者再按
  一次即成功。機率低、後果輕，不為此加第三層等待。
- **R8 probe 成功到旗標清除間的新故障**（無 await 區間，同 loop 不可插隊）：物理上
  該瞬間的新故障要等下一輪 loop 才設旗標，最多多付一輪「失敗→下次恢復」。
