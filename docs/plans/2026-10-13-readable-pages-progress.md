# 可讀頁面與長時間監看進度

## 驗收項目

- 掃描與已連線裝置清單在 100%–200% 字體倍率下能完整閱讀，必要時可水平捲動。
- PTU/PRU、錯誤對照與錯誤通知表列依字體高度調整；文字更新保留選取項目。
- Overview 可捲動，狀態及 batch log 採可縮放字型，使用者閱讀歷史記錄時不強迫回到底部。
- 以 offscreen Qt 實跑涵蓋倍率變更、列表更新、狀態顯示及既有回歸測試。

## 2026-10-13：現況檢視

- 已讀取全域判斷守則；專案根目錄沒有 AGENTS.md / CLAUDE.md。
- 掃描頁大量正文固定 10–13px、清單禁止水平捲動；已連線清單每次更新全部重建。
- 資料表每次刷新重建 item，沒有依字體調整行高；錯誤頁同樣未設定自適應行高。
- Overview 的 batch log 滿額後整個清空且每筆新紀錄強制捲到底部。
- 字體介面由 typography 子代理提供；本次不修改通訊或 CSV 寫檔行為。

## 2026-10-13：頁面修正

- 掃描、Overview、資料表、錯誤頁及錯誤通知改用可縮放 point 字型；裝置編號頁也套用一致標題。
- 掃描清單與外層允許必要的水平捲動，已連線裝置以原 widget 更新封包/錄製狀態，保留目前選取與捲動位置。
- PTU/PRU 採依內容調整欄寬與行高、重用 table item；錯誤摘要採可捲動容器與兩欄資訊卡。
- Overview 摘要可垂直捲動，batch log 在閱讀歷史時不強制回底部。保留既有 batch 2000 行整批輪替規格，新增 document 行數上限防護。
- 新增 6 個 offscreen 回歸案例，首輪新案例全通過；合併既有測試為 29 passed / 2 failed。兩項分別為舊 wordWrap 行為（保留修正）及舊 AlwaysOff 水平捲動期待（依新版需求改為 AsNeeded）。

## 2026-10-13：驗證及波形頁補強

- 掃描、Overview、batch log、裝置編號與新案例合併測試：`31 passed in 5.88s`，exit 0。
- 波形工具列改放入水平捲動區，統計與游標各佔一行且可換行；圖軸、圖例、A/B 與圖上標記採同一倍率。
- 新增圖軸、標記與工具列倍率測試；`pytest tests/test_readable_pages.py tests/test_ui_imports.py -k 'readable or waveform_page' -q`：`21 passed, 68 deselected in 4.30s`，exit 0。
- 七個變更頁面 compileall 通過，diff whitespace check 通過。已送主代理安排 fresh reviewer 與全專案整合驗收。
- 本機未連真實 BLE/dongle；所有頁面測試使用 Qt offscreen 與合成 DeviceState，不宣稱已驗證真機長時間連線。

## 2026-10-13：真字型與窄螢幕整合修正

- 整合驗收發現 Windows offscreen 預設字型庫空；頁面回歸測試現會在必要時載入系統 Segoe UI、微軟正黑體及 Consolas，使用真實字形尺寸驗證。
- Overview batch 提示獨立成列，避免大字級同列互擠；可捲動摘要維持 120 邏輯像素最小高度，避免倍率200%把全窗撐高。
- 掃描頁三組成對按鈕依側欄可用寬度自動切换橫排／直排，避免錄製按鈕列將其他按鈕撐出可視區；新增按鈕完整可見性驗證。
- 配合主代理加入各 tab 捲動容器，實跑 `scripts/verify_debug_ux.py --scales 200 --themes light --samples 0 --output build/ux-review-readable`：1366×768 與 1024×768 均保持指定尺寸且 `0 issues`，exit 0。
- 真字型版 `tests/test_readable_pages.py`：`7 passed in 1.63s`，exit 0。完整矩陣已交 debug_log 子代理接續驗證。

## 2026-10-13：Fresh review 波形文字修正與定版

- 目視驗收發現 light 主題圖上標題使用一般正文深色，已改用深底圖表專用 `plot_axis_text`。
- Fresh reviewer 以 rendered HTML 查出 pyqtgraph 圖例切倍率僅更新 options、沒有重建文字；現對既有圖例重新 `setText`，同步字級與圖表文字色。
- 回歸新增讀取文字 document fragment 的實際 pointSize／foreground，驗證圖例100→200%實際22pt與標題顏色，而非僅检查options。
- `pytest tests/test_readable_pages.py tests/test_ui_imports.py -k 'readable or waveform_page' -q`：`21 passed, 68 deselected in 5.88s`，exit 0。已通知主代理程式定版可重新封包，debug_log 補拍 light100／light200 波形截圖，fresh reviewer 複驗。

## 2026-10-13：波形 style setter 全面回歸

- 補拍與 fresh review 確認 `AxisItem.setLabel` 未傳文字會清空座標軸名稱；現保留軸文字、單位、前綴及可見性，新版 pyqtgraph 的單位次方／SI 前綴區間也保留。
- 檢查本機 pyqtgraph 的 `AxisItem.setLabel`、`setTextPen`、`setStyle`，以及 `LegendItem.addItem`、`LabelItem.setText` 真正行為，不再僅查 options。
- 新增同圖表五倍率（100/125/150/175/200）× light/dark 循環，驗證軸文字／單位／可見性／實際 HTML 字號及顏色、tick 字體、既有與每轮新增系列圖例、刷新後標題。另驗刻意隱藏的軸標題仍保持隱藏。
- targeted 回歸：`22 passed, 68 deselected in 7.72s`，exit 0。再次通知主代理、fresh reviewer 與截圖驗收代理此版本可複驗與封包。
