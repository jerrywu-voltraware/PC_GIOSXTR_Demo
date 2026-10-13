# 2026-10-13 裝置 Log 顯示改善進度

## 範圍與查核

- 已讀 `app/windows/log_page.py`、`app/models.py`、`app/batch_log.py`、`app/windows/overview_page.py` 與 MainWindow 更新流程。
- 裝置 Log 由 `refresh(DeviceState)` 讀取最新在前的 `log_messages`，模型保留 500 筆。全域 `batch.txt` 在 Overview，CSV 寫入與本頁分離。
- 保留 `refresh`、`clear` 與 `text` 介面；現有 LogPage 沒有 `append_event`。

## 設計與驗收條件

- 裝置 Log 搜尋與嚴重度篩選，明示嚴重度由文字判定。
- 暫停僅凍結畫面；恢復後同步最近訊息，模型與檔案寫入不被改動。
- 手動檢視舊訊息時停止追蹤；可回到最新（頂端）。
- 清除僅影響本頁顯示，不清除 DeviceState、batch.txt 或 CSV。
- 顯示最多 500 筆；高流量更新合併到 150ms，每次沒有內容變化時避免重畫。
- 使用繼承字體，不設定固定像素字級。
- 必須通過離屏 Qt 元件實跑、功能測試與獨立審查。

## 執行紀錄

- 2026-10-13：完成資料流調查及設計；`py -3 -X utf8 -c "import PyQt6; import pytest"` 實跑成功（exit 0）。
- 2026-10-13：實作搜尋、警告／錯誤篩選、暫停與恢復、頂端追蹤、僅清除畫面，以及 150ms 合併刷新。清除邊界僅保留一個原始訊息物件參考，過期時釋放，不建立無界隱藏 ID 清單。
- 2026-10-13：匯入 `app.windows.log_page` 成功（exit 0）。
- 2026-10-13：`QT_QPA_PLATFORM=offscreen`，執行 `py -3 -X utf8 -m pytest tests/test_log_page.py -q --basetemp .pytest_tmp_debug_log_20261013`，**8 passed in 1.80s，exit 0**。
  - 實際寫入臨時 CSV 與 batch.txt，暫停畫面時兩者持續寫入；清除畫面不改事件來源或檔案。
  - 5,000 次事件更新合併為一次重畫，最多保留 500 筆；再刷相同內容沒有重畫。
  - 暫停期間 2,500 次更新不建立待顯示隊列，恢復只同步最新 500 筆。
  - 實際顯示離屏視窗並捲動：停用追蹤後保留可見事件，恢復追蹤回到頂端。
  - 搜尋、嚴重度、相同文字事件的清除邊界、裝置切換及多行訊息均通過。
- 待主 agent 整合與 fresh agent 獨立驗收；實體裝置長時間收資料仍需實機驗證。

## 整合 UI 驗證工具

- 新增 `scripts/verify_debug_ux.py`，隔離 INI QSettings、recent devices、CSV 與 batch.txt，建立兩部模擬裝置，產生 PNG 與 `build/ux-review/report.json`；不掃描或連線 BLE。
- Windows Qt offscreen 的字型資料庫起初為空，初版截圖連 ASCII 都是方框；驗證腳本已載入本機 Segoe UI、Microsoft JhengHei、Consolas，避免使用錯誤字形尺寸評估。
- 真實字型首輪 100% 於 1366×768、1024×768 正常；200% 因分頁最小高度將主窗撐到 870px。已通知主 agent，以分頁外層可捲動區修正；修正後兩個目標視窗尺寸均可維持。
- 改用可見區域的完整矩形檢查後，200% 側欄四個整列按鈕會被雙按鈕列撐寬（452px 按鈕、326px 視窗）；已交 responsive agent 修正，等待重跑完整矩陣。
- `py -3 -X utf8 scripts/verify_debug_ux.py --scales 100 --themes light --sizes 1024x768 --samples 10000 --output build/ux-review/stress` 實跑 **exit 0**：視窗尺寸及控制可及性零問題；10,000 次合法 20B 通知經真實 MainWindow 通知處理及 CSV，1.908 秒、200 次 event pump，實讀 10,006 資料列（含初始 6 列）、26 欄一致、12 個分檔。Log 畫面暫停保持不變，恢復後顯示 500 筆。
- 加速模擬證據不等同數小時實體 BLE 耐久測試，仍須明確保留此限制。
- 主窗分頁可捲動修正與側欄雙按鈕自適應直排修正完成後，執行 `py -3 -X utf8 scripts/verify_debug_ux.py --samples 10000`：**20 組矩陣通過、exit 0**，涵蓋 100/125/150/175/200%、亮／暗、1366×768／1024×768，8 個分頁均可到達，內容可捲到底，錄製面板及側欄所有按鈕可完整觸及，產出 180 張 PNG。
- 該次驗證已新增實際波形曲線及 120 筆預覽樣本；啟用曲線下 10,000 次通知壓測耗時 16.676 秒，200 次 event pump，全部 10,000 筆資料均寫入，最終 CSV 10,006 列、26 欄、12 分檔正確，兩裝置事件均維持 500 筆，暫停不影響寫入。證據 `build/ux-review/report.json`。
- 已目視 100/150/200% 的 Overview、Log、Waveform 亮暗代表截圖，控制文字清楚且沒有原先重疊；小視窗大字使用捲動。目視發現亮色主題的波形圖標題深字對深底對比不足，已交 responsive agent 改 plot 專用文字色，待針對重拍確認。
- 亮色波形標題及 legend 實際字級／顏色修正後，針對 100/200% 重拍確認標題與圖例已清楚；額外擷取 plot 完整元件發現切換倍率後 `Sample`／`V_in (mV)` 軸標題消失，已交 responsive agent 調查 `axis.setLabel` 的保留文字行為，驗證腳本亦增加非空軸標題斷言。證據位於 `build/ux-review/waveform-contrast/`，此項尚待修後確認。
- 軸標題保留修正完成後，執行 `py -3 -X utf8 scripts/verify_debug_ux.py --plot-only --sizes 1024x768 --samples 0 --output build/ux-review/waveform-final`：**亮／暗 × 100/125/150/175/200% 共 10 組通過，exit 0**；每組 `axis_titles` 皆保留 `Sample` 與 `V_in (mV)`，保存 20 張 Waveform 頁面／plot 截圖。已目視 100% 和 200% 的亮暗 plot：軸標題、刻度、圖例與圖表標題文字完整清楚。最終圖表證據應以 `build/ux-review/waveform-final/report.json` 與同目錄 PNG 為準。
- 已將完整矩陣、10,000 筆通知寫入結果及修後圖表專項交 fresh reviewer 獨立 read-back；未重跑與字色／軸標題無關的完整壓測。
