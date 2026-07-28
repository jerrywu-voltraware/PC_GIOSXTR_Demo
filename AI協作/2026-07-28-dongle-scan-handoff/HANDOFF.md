# 交接文件：dongle 掃描中途 transport 失效（2026-07-28，Claude → Codex）

## 任務原文摘要
dongle（nRF52840，COM8）在「中斷目前裝置」後韌體 fault（0xFF03）→ SREQ 軟重置 → Windows 重新列舉 USB CDC → 使用者再按「搜尋裝置」時 pyserial 原始錯誤直達 UI。要求兩層修正：
- **A. PC App 容錯**：scan 交易（AT+SCAN → 5s → AT+STOP → AT+LIST）任一階段失效 → 中止舊交易 → coalesced recovery → 自動重試完整掃描一次（有限次數）→ 最終失敗顯示繁中友善錯誤；不影響 Bleak 路徑；處理與 auto-reconnect / pending disconnect / lock 的競爭。
- **B. 韌體根因**：0xFF03 = NRF_FAULT_ID_APP_MEMACC 根因分析＋跨 reset 保存 fault PC 的診斷。
- 測試：無硬體模擬各階段失效；全 pytest（基準 **176 passed**，已實測確認）。

## 已完成（有證據）

### 1. PC 端根因分析（TOCTOU 證實）
- `DongleSource.scan()`（app/device_source.py:584-629）只在入口做 recovery 檢查（:595），四階段全程無保護；`_send_command`（:644-653）失敗設旗標後直接 raise ConnectionError。
- `_handle_transport_failure`（:1042-1052）不觸發 recover；唯一修復點是下次 `check_ready`（:497-535）→`_ensure_recovered`（:518）——與日誌 38 秒無人救吻合。
- coalescing 缺口：`_handle_stream_stale`（:773）直呼 `recover()` 繞過 `_recovery_lock`；`recover()`（:856-909）無健康早退守門。
- UI：`ScanPanel.scan()`（app/windows/scan_panel.py:550-551）`str(exc)` 直進 QMessageBox；失敗後按鈕仍可按。
- 競態：auto-reconnect 首延遲 1s（app/windows/main_window.py:91），掃描中失效 → 斷線回呼 → reconnect 可搶 `_connect_lock` 跑 recover()，與 scan 後續指令同 handle 交錯。
- **隱蔽缺陷**：AT+LIST timeout 被吞（device_source.py:613-620）→ 靜默回傳空清單、不設 `_needs_recovery`。
- Bleak 隔離確認：ScanPanel 鴨子型別（scan_panel.py:565,569,580）；BleManager 無 recover——只改 DongleSource + dongle 分支即安全。
- （行號為 2026-07-28 修改前現碼；實作 workflow 動工後會位移，用符號名搜尋。）

### 2. PC 端設計定稿（兩案競爭＋評審裁決）
**唯一實作依據：本資料夾 `design-final.md`**（含可抄骨架、15 個新測試計畫、既有 176 測試逐點審計、8 條驗收條件對應表）。關鍵裁決：
- scan 交易（含 1 次自動重試，共 2 attempt）全程持既有 `_connect_lock`；鎖階層單向 `_connect_lock → _recovery_lock`（已審計無死鎖）。最壞牆鐘 ~28s 有界。
- 世代計數器 + 0.2s 可中止等待視窗（5s 等待期間 reader thread 設旗標 → 及早中止）+ `_send_command` recovery 守門。
- `recover()` 本體加 coalescing 守門（簽名不變 → 既有測試零修改）。
- AT+LIST 靜默 timeout 本次修，最窄判定：timeout ∧ 零收集行 ∧ 無 SCAN LIST header。
- UI 只認最外層 `DongleTransactionAborted.user_message`（繁中雙文案：recovery 失敗 vs 重試後仍失敗）。
- **健康判定謂詞一律不含 `_running`**（注入 serial 的 recovery 永不恢復 `_running`，只在 `_reopen_serial` 設回——評審抓到的設計級缺陷，勿回退）。
- main_window.py 與既有 176 測試應零改動。

### 3. 韌體分析＋patch（分析報告：本資料夾 `firmware-analysis.md`）
- **0xFF03 直接根因靜態無法定案**——需 fault PC。核心交付＝跨 reset fault 記錄區（0x20038000；arm5_no_packs 的 uvprojx IRAM1 0x30000→0x28000 使其落在 execution region 外）＋開機 DIAG 附 `fault_pc/fault_id/fault_info/n`＋新 DIAG2 行（err/line/file/hfsr/cfsr/bfar/mmfar）。
- 順手修 5 處「斷線中 SD API 合法失敗被 APP_ERROR_CHECK 炸機」（scan_start / CONN_PARAM_UPDATE_REQUEST / PHY_UPDATE_REQUEST / GATTC+GATTS_EVT_TIMEOUT）——同症狀但產 SDK 錯誤碼，**不解釋本次 0xFF03**。
- 已排除：stack 溢位、conn_handle 索引、USB ring buffer、ISR 優先權、critical region。推測 P1-P5 見報告（P1：wdt_event_handler 直寫 NRF_POWER->GPREGRET 可能偽造 0xFF03）。
- 意外發現：NRF_LOG_ENABLED=1 但無 backend → 既有警告全部不可見；`ble_db_discovery_start` 疑似死碼（未確認）。
- 韌體是巢狀 git repo：`PTU_to_Azure/NRF52840-DONGLE/Rpi_USB_BLE/.git`（主 repo 未追蹤 PTU_to_Azure/）。
- 三鏡頭對抗審查回報 **16 findings**（本資料夾 `firmware-review-16-findings.txt`），修正輪交接時仍在跑（見下）。

## 交接時仍在跑的背景工作（Codex 接手時先查這兩件）

1. **PC 端實作 workflow**（wf_07dbe008-8a7）：實作 design-final.md → 全 pytest → 4 鏡頭對抗審查 → 修正輪。改 `app/device_source.py`、`app/windows/scan_panel.py`、`tests/test_dongle_source.py`、`tests/test_scan_panel.py`。
   - 完成與否看：`git -C d:\jerry\Python\PC_GIOSXTR_Demo status` + `py -3 -X utf8 -m pytest -q`。
   - **判定規則**：pytest 全綠（≈176+15）且 diff 覆蓋 design-final.md 各改動點 → 大致完成，做下方「收尾清單」；pytest 紅或 diff 只有半套 → working tree 是半成品，依 design-final.md 補完（設計文件足夠自足）。
   - 逐 agent 結果（若 session 還留著）：`C:\Users\USER01\.claude\projects\d--jerry-Python-PC-GIOSXTR-Demo\ea077680-aea7-457b-a39f-69f62f90c8d0\subagents\workflows\wf_07dbe008-8a7\journal.jsonl`。
2. **韌體 findings 修正 agent**：正把 16 findings 逐條 fixed/rejected 並更新 firmware-analysis.md（scratchpad 版本較新；本資料夾是交接時快照）。
   - 完成與否看：巢狀 repo `git -C d:\jerry\Python\PC_GIOSXTR_Demo\PTU_to_Azure\NRF52840-DONGLE\Rpi_USB_BLE diff --stat`（應只有 main.c + uvprojx）＋ scratchpad `firmware-analysis.md` 是否已含 16 findings 處置表。
   - scratchpad 路徑：`C:\Users\USER01\AppData\Local\Temp\claude\d--jerry-Python-PC-GIOSXTR-Demo\ea077680-aea7-457b-a39f-69f62f90c8d0\scratchpad\`

## Codex 收尾清單（按序）

1. 判定實作 workflow 完成度（上述規則），必要時依 design-final.md 補完/修紅。
2. **PC 端補一刀（被刻意扣住避免同檔互踩）**：`app/device_source.py` `_on_line` 約 :1315 只持久化 `startswith("DIAG:")` 的行 → 放寬為 `startswith("DIAG")`（涵蓋新 DIAG2 行），並評估把韌體新 `WARN:*` / `ERROR:SCAN*` 行也寫進 dongle_runtime.log；補一個測試。
3. 韌體 16 findings 修正輪驗收：對照 `firmware-review-16-findings.txt` 逐條檢查 main.c / uvprojx / firmware-analysis.md 的處置（特別是 major：WDT 標記 0xFF02 與 SDK-assert 撞號、stale build 產物警告）。
4. 獨立驗收（不要自驗）：全 pytest 綠、8 條驗收條件逐條核對、`git status` 確認 `.gitignore` 未被動、PTU_to_Azure/ 完好、無範圍外檔案被改。
5. 更新韌體 nested repo 的 commit（若使用者要求才 commit；主 repo 同理）。

## 使用者上機驗證步驟（無硬體無法替代）
1. **必須先 Keil rebuild**——`_build/nrf52840_xxaa.hex`/`.map` 是 2026-07-21 舊產物（map 內無 fault_record_store 符號），直接跑 `flash_app_sectorerase.ps1` 會默默燒到沒有 patch 的舊韌體。build 後可 grep map 確認 `fault_record_store` 存在再燒。
2. 燒錄 → 重現斷線 → 把開機 `DIAG:` / `DIAG2:` 兩行回貼（`fault_info=0`＝寫到 SD RAM；非 0＝週邊子區號）。有 `fault_pc` 即可對 map 定位 0xFF03 真兇。
3. PC 端實測：連線 → 中斷 → 立刻搜尋，應看到自動恢復完成掃描（或繁中錯誤 + 可重按），不應再見 pyserial 字串。

## 禁區（不變）
- `.gitignore` 使用者已改，勿覆蓋。PTU_to_Azure/ 勿刪勿重建。未經使用者要求勿 commit。

## Codex 接手後狀態（2026-07-28）

Claude 留下的 PC 實作已完成驗收並補正；韌體 16 項審查意見也已收斂。最新詳情見
`task-progress.md` 與 `firmware-analysis.md` 開頭的「Codex 接手後」段落。

- PC：scan 中途 transport 失效會中止舊交易、coalesced recovery、完整自動重試一次；
  最終錯誤與 readiness 錯誤都不再把 COM／pyserial 原始文字放進對話框。
- 韌體：主 target 已以 Keil ARMCC 實際 rebuild（0 errors / 0 warnings），新的 HEX/MAP
  已產生；燒錄腳本會阻擋 stale 或缺少診斷 patch 的產物。
- 未執行燒錄或實機重現。下一步仍是由使用者確認後燒錄，再跑
  「連線 → 中斷 → 立刻搜尋」，並回貼 `DIAG:`／`DIAG2:`／`WARN:`。

## token 用量備註
本次已耗：分析 ~97k + 設計 wf ~345k + 韌體分析 ~228k + 韌體審查 wf ~300k + 實作 wf（進行中，未計）。
