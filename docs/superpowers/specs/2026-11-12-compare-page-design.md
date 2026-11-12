# Compare 比較頁 設計規格（2026-11-12）

## 目的

使用者想把不同來源的訊號（PTU 的 V_BUS、PRU 的 V_Rect…，甚至不同裝置的同一訊號）
放在同一頁對照數值與波形。現有 Waveform 頁一張圖只畫「一個訊號 × 多台裝置」，
無法混搭不同訊號，因此新增獨立的 Compare 頁。

## 已定案的決策（使用者 2026-11-12 同意推薦預設）

1. **單位不同 → 依單位自動分上下子圖，X 軸連動**（同單位的訊號疊在同一張子圖）。
2. **訊號綁定「加入當下的裝置」**：條目以 `(address, field_name)` 為身分，
   顯示為「V_BUS @ GIOS0801ST#9」，可跨裝置比較同一訊號。
3. **比較清單持久化**：存 QSettings，下次啟動自動帶回（資料不帶回，只帶回清單）。

## 行為規格

### A. PTU / PRU 表格右鍵選單（app/windows/data_pages.py）

- 在數值列按右鍵 → 選單：
  - 未加入：「加入比較」；已加入（目前裝置 + 該 field 已在清單）：「從比較移除」
  - 「開啟比較頁」（切換到 Compare 分頁）
- 不可比較的列（SYS_STATE、Type、FW_Version、PTU_MAC、PRU_MAC）：選單項目 disabled，
  文字「此欄位無法加入比較」。
- 列標籤 → field_name 對照（field_name 為 `DeviceState.get_value()` 的 key，
  與 `app/constants.py` 的 `SIGNAL_DEFINITIONS` 一致）：

| 頁 | 列標籤 | field_name | 單位 |
|---|---|---|---|
| PTU | Array_Level | ptuArrayLevel | （無） |
| PTU | V_IN | ptuInputVoltage | mV |
| PTU | I_IN | ptuInputCurrent | mA |
| PTU | Power | inputPower | W |
| PTU | V_BUS | ptuBusVoltage | mV |
| PTU | I_BUS | ptuBusCurrent | mA |
| PTU | DCDC_Duty | ptuDcdcDuty | （無） |
| PTU | T_BUS | busTempDegC | C |
| PTU | T_AMP | ampTempDegC | C |
| PTU | T_IC | icTempDegC | C |
| PTU | V1_Voltage | v1Voltage | mV（注意 PTU 頁顯示 `v1_voltage * 10`，比較頁數值必須與 PTU 頁一致） |
| PTU | I1_Deg | i1Deg | deg |
| PTU | I3_Current | i3Current | mA |
| PTU | I3_Deg | i3Deg | deg |
| PTU | I1I3_Deg | i1I3PhaseDiffDeg | deg |
| PTU | System_EFF | systemEff | % |
| PRU | V_Rect | pruDynVrect | mV |
| PRU | I_Rect | pruDynIrect | mA |
| PRU | V_Out | pruDynVout | mV |
| PRU | I_Out | pruDynIout | mA |
| PRU | Power | pruOutputPower | W |
| PRU | T_Sys | pruDynTemp | C |
| PRU | Vrect_Min | pruDynVrectMin | mV |
| PRU | Vrect_Set | pruDynVrectSet | mV |
| PRU | Vrect_Max | pruDynVrectMax | mV |
| PRU | System_EFF | systemEff | % |

- System_EFF 在 PTU、PRU 都有，同一 `(address, field_name)` 只算一個條目（不重複加入）。

### B. Compare 分頁（新檔 app/windows/compare_page.py）

- 分頁標籤「Compare」，放在 Waveform 之後。
- **工具列**：暫停、清除資料（保留清單只清曲線）、全部移除、時間窗（30 秒 / 1 分 / 5 分 / 10 分，預設 1 分）、
  十字準線開關、存圖。
- **上方數值表**，每個條目一列：顏色色塊、訊號（如「PTU V_BUS」）、裝置名稱、目前值+單位、
  最小、最大、平均（以目前時間窗內資料計算）、游標值（十字準線位置的值，無則「-」）、
  顯示勾選、移除按鈕。裝置未連線時目前值顯示「-」且標示未連線。
- **下方圖表**：依單位分組，每組一張 pyqtgraph 子圖，垂直堆疊；所有子圖 X 軸 `setXLink` 連動。
  - X 軸 = 秒（以 Compare 頁開始取樣的 `time.monotonic()` 為 0），讓不同裝置的取樣能對齊時間。
  - 每條曲線顏色與表格色塊一致、圖例顯示「訊號 @ 裝置」。
  - 子圖左側 Y 軸標單位；條目移除後該單位無訊號 → 子圖移除。
  - 十字準線：垂直線同步出現在所有子圖，表格「游標值」欄顯示最近取樣值。
- 清單為空時顯示提示：「在 PTU / PRU 分頁的欄位上按右鍵 →『加入比較』」。
- 效能：每次 notify 都收資料（不漏樣本），重畫用計時器合併（約 100 ms），
  每條緩衝有上限（例如 10 分鐘 × 合理取樣率，或 deque maxlen）。
- 主題：跟隨 `theme_manager().theme_changed`，與 Waveform 頁風格一致。

### C. 主視窗接線（app/windows/main_window.py）

- 建立 ComparePage、加入 tabs（Waveform 之後）。
- 在 `_handle_notify` 呼叫 waveform 的同一位置，也餵資料給 Compare 頁（所有裝置都餵，
  Compare 頁只保留清單內 address 的資料）。
- `refresh_pages` 時更新裝置名稱/連線狀態。
- PTU/PRU 頁右鍵事件 → 主視窗用 `active_address` 與裝置名稱建立條目並加入/移除；
  「開啟比較頁」切換分頁。

### D. 持久化

- QSettings key：`compare/entries`，存 JSON list：`[{address, device_label, source, row_label, field_name, unit}]`。
- 啟動時讀回；JSON 壞掉時忽略並清空，不得讓程式啟動失敗。

## 不在範圍內

- 不改版本號、不發版、不 commit（使用者另行決定）。
- 不改 Waveform 頁既有行為。
- 不匯出比較資料 CSV（日後可加）。

## 進度

- [x] 規格（本檔）
- [x] 實作
- [x] 測試 + offscreen smoke
- [x] 獨立驗收（2026-11-12：pytest 274 passed、smoke exit 0、數值與 PTU/PRU 頁 25 項一致、啟動不覆寫已存清單）
- [ ] 使用者實機（真實 BLE 裝置）測試
- [ ] commit / 發版（待使用者決定）
