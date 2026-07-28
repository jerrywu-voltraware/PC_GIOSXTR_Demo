# 任務進度：dongle 掃描中途 transport 失效（2026-07-28）

## 任務
1. A 層（PC App）：scan 交易中途 transport 失效 → coalesced recovery → 自動重試一次 → 有限次數 → 友善錯誤訊息；不影響 Bleak 路徑。
2. B 層（韌體）：0xFF03 NRF_FAULT_ID_APP_MEMACC 根因 + fault PC 跨 reset 診斷。
3. 測試：無硬體測試涵蓋各階段失效；全 pytest（基準 176 passed）。

## 已知背景（來自 memory dongle-reconnect-rootcause）
- 2026-07-21 曾修：PC 無限慢速重試、握手驗證 recover()、韌體 WDT（未上機驗證）。
- 韌體是巢狀 git repo：PTU_to_Azure/NRF52840-DONGLE/Rpi_USB_BLE/.git。
- DIAG RESETREAS 於 main.c ~L1764 開機讀取；SREQ=0x04；last_err=0xFF03 本次觀察到。

## 進度
- [x] 讀 playbook 02/04 + memory
- [x] Phase 1a：PC 端路徑分析完成。**TOCTOU 證實**。重點：
  - scan()（device_source.py:584-629）中途無保護；_send_command(644-653) 失敗設旗標後直接 raise ConnectionError。
  - _handle_transport_failure(1042-1052) 不觸發 recover；唯一修復點是下次 check_ready(497-535)→_ensure_recovered(518)。
  - coalescing 缺口：_handle_stream_stale(773) 直呼 recover() 繞過 _recovery_lock；recover(856-909) 無健康早退守門。
  - ScanPanel.scan()（scan_panel.py:550-551）str(exc) 直進 QMessageBox；失敗後按鈕仍可按。
  - 競態：reconnect 首延遲 1s（main_window.py:91），掃描中失效 → 斷線回呼 → reconnect 可搶 _connect_lock 跑 recover()，與 scan 後續指令同 handle 交錯。
  - 隱蔽缺陷：AT+LIST timeout 被吞（613-620）→ 靜默空清單、不設 _needs_recovery。
  - Bleak 隔離安全（ScanPanel 鴨子型別；BleManager 無 recover）。
  - 測試資源：tests/test_dongle_source.py FakeSerial/ReadFailSerial/WriteFailSerial(40-69)；test_scan_panel.py:357-394 只蓋 check_ready 失敗。
- [x] 設計 Workflow（wf_7d590556-79f）完成：hybrid 定稿 → scratchpad\design-final.md。裁決：
  - scan 交易（含 1 次自動重試）全程持 _connect_lock；鎖階層單向 _connect_lock→_recovery_lock（審計無死鎖）。
  - 骨架＝世代計數器＋0.2s 可中止等待視窗＋_send_command recovery 守門；嫁接 recover() 本體 coalescing 守門（簽名不變）。
  - AT+LIST 靜默 timeout 修（最窄：timeout∧零行∧無 header）；UI 只認 DongleTransactionAborted.user_message 繁中文案。
  - 健康判定一律排除 _running（評審抓到 minimal 案設計級缺陷：注入 serial 的 recovery 永不恢復 _running）。
  - 殘餘風險：失敗路徑最長持鎖 ~28s；generation counter 免鎖依賴 event-loop 執行緒紀律。
- [x] 實作 Workflow（wf_07dbe008-8a7）產出已由 Codex 接手驗收與補正：
  - `_check_generation()` 補回 `_needs_recovery` 判定，避免 scan window 失效後仍送 `AT+STOP`。
  - 韌體 `DIAG2:`／`WARN:`／`ERROR:SCAN` 均持久化；readiness 對話框不再洩漏 COM／pyserial 原始錯誤。
  - scan transaction、coalesced recovery、有限重試、UI 友善訊息測試已落地。
- [x] Phase 1b：韌體分析完成（報告 scratchpad\firmware-analysis.md）。要點：
  - 0xFF03 直接根因靜態無法定案 → 核心交付＝跨 reset fault 記錄區（0x20038000，IRAM1 0x30000→0x28000 排除於 execution region）＋開機 DIAG 附 fault_pc/fault_id/fault_info/n ＋ DIAG2 行。
  - 已修 5 處同症狀缺陷（斷線中 SD API 合法失敗被 APP_ERROR_CHECK 炸機：scan_start/CONN_PARAM_UPDATE_REQ/PHY_UPDATE_REQ/GATTC+GATTS_EVT_TIMEOUT）——不解釋本次 0xFF03，已誠實區分。
  - 推測 P1-P5（含 WDT handler 寫 GPREGRET 可能偽造 0xFF03）；排除 stack 溢位/conn_handle 索引/USB ring buffer/ISR 優先權/critical region。
  - 意外：NRF_LOG 無 backend（警告全進空氣）；ble_db_discovery_start 疑似死碼（未確認）。
  - 改動：main.c 多段 + uvprojx:304 IRAM1；需使用者 Keil build + flash + 重現後回貼 DIAG/DIAG2。
- [x] 韌體審查 Workflow（wf_be718d8f-993）完成：16 findings（完整 JSON 在 tasks\w1bpqyb1n.output）。major：
  - WDT 標記 0xFF02 與 SDK-assert 撞號（判讀誤導）。
  - _build hex/map 是 7/21 舊產物、flash 腳本硬編指向 → 直接燒會部署無 patch 韌體；patch 從未過編譯器。
  - PC 端 device_source.py:1315 只記 "DIAG:" 前綴 → DIAG2/WARN/ERROR 行遺失（**PC 端修正扣住待實作 workflow 收工，避免同檔互踩**）。
  - minor 群：第二 target IRAM1 仍涵蓋 0x20038000（報告 §8.3 宣稱錯）、HardFault 6 參數呼叫違反免堆疊註解、wdt_event_handler 直寫 POWER 可能偽造 0xFF03、單槽記錄連續 fault 遺失、bootloader 未確認。
- [x] 韌體 findings 修正：WDT handler 改空、暫時性 SoftDevice 錯誤精準放行、第二 target IRAM1 修正、HardFault 註解修正、flash 腳本加入 stale HEX/MAP 防護；完整處置見 `firmware-analysis.md` 最新狀態表。
- [x] 基準線 pytest：**176 passed in 45.72s**（exit 0，與使用者說的基準一致）
- [x] Phase 2：PC 端實作與分階段無硬體測試完成。
- [x] Phase 3：獨立 fresh 驗收完成：第一次 **192 passed**；隱藏 readiness 原始錯誤後補 1 測試，最終 **193 passed in 50.58s**。
- [x] Phase 4：雙層總結與上機步驟已更新；未寫入工具私有 memory。

## Codex 接手收尾紀錄

- PC 全套 pytest：最後一次完整回歸 `193 passed in 50.58s`（exit 0）。
- Python bytecode 編譯：`py -3 -X utf8 -m compileall -q main.py app tests`，exit 0。
- 韌體 Keil ARMCC V5.06 update 7 rebuild：`0 Error(s), 0 Warning(s)`；
  `Code=71684, RO-data=6596, RW-data=12776, ZI-data=25352`。
- MAP：有 `fault_record_store`；`RW_IRAM1 Max: 0x00028000`；HEX 時間晚於 `main.c`／`.uvprojx`。
- Keil XML：兩個 target 的 IRAM1 終點均為 `0x20038000`。
- `flash_app_sectorerase.ps1` PowerShell parser 通過；**未燒錄**。使用者已指定後續韌體編譯與燒錄由使用者自行操作。
- 尚未驗證：實機「連線 → 中斷 → 立刻搜尋」、bootloader 是否保留 `0x20038000` fault record、`0xFF03` 的實際 `fault_pc`。

## Ultracode 註記（2026-07-28 使用者開啟）
- Phase 2/3 改用 Workflow 工具編排；驗證採對抗式多數決。
- 韌體改動仍無法本機編譯——驗證上限是語法/邏輯多 agent 交叉審查 + 使用者上機步驟。

## 禁區
- .gitignore 使用者已改，勿覆蓋。
- PTU_to_Azure/ 未追蹤目錄，勿刪勿重建。
