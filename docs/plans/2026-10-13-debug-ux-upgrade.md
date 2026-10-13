# Debug 與長時間紀錄 UX 升級

## 需求與驗收

- 提高不同電腦上的文字可讀性：預設 11pt，100–200% 可即時調整並記憶；重要操作不因放大被裁切。
- 錄製狀態在各分頁保持可見：目前裝置、錄製時間、實際成功寫入筆數、最近資料與檔案位置；斷線與寫檔失敗不能呈現正常錄製。
- 提供可拖曳側欄及可選擇的紀錄資料夾。
- 裝置 Log 可搜尋、篩選、暫停顯示及恢復追蹤；只影響畫面，CSV 持續寫入，記憶體保持有界。
- 每筆 CSV 既有欄位與分檔行為保留；同秒重新開始不能覆寫已存在紀錄。
- 通過既有回歸測試、offscreen UI 實跑與截圖檢查，另由 fresh agent 驗收。
- 真實 BLE／dongle、多實體螢幕 DPI 切換、數小時實機錄製若無法執行，交付明確步驟並標為未驗證。

## 已完成：調查

- 專案為 PyQt6；目前無專案 AGENTS.md / CLAUDE.md，已讀全域 03-judgment.md。
- 發現 ScanPanel 有固定 11–13px 字體、主窗側欄固定 380px。
- CSV 每筆 flush、已有自動分檔；尚無成功寫入統計與寫檔失敗狀態。
- MainWindow 每個封包都重建 device tabs，可能造成不必要配置與長時間記憶體成長。
- LogPage 每次通知整頁重畫；DeviceState.log_messages 已限制 500 筆。
- 既有使用者變更：韌體子模組、docs/superpowers/specs/image/、問題/；不修改這些內容。

## 進行中

- Typography：全域字級、設定及表列高度。
- Readable pages：側欄及資料頁的字級與內容尺寸適配。
- Debug log：搜尋、暫停、追蹤及有限緩衝。
- 主整合：錄製摘要、檔案位置、寫入統計與錯誤呈現、回歸驗證。

## 已完成：實作與第一輪整合

- 全域 11pt 及可記憶 100/125/150/175/200% 字級，設定頁可捲動。
- 主窗側欄改可拖曳分隔；跨分頁錄製摘要含實際寫入筆數、時間、分檔、最後寫入、檔案路徑。
- 錄製等待資料、等待重連、10 秒以上未寫入與檔案錯誤都有獨立文字提示。
- 可變更 CSV 目錄（錄製中鎖定），記住下次使用位置；失敗後可修正目錄重新開始。
- CSV 改 exclusive create 避免覆寫同秒紀錄；每筆 flush，成功後才累加計數；停止後保留統計。
- 每個 notification 仍解析與寫 CSV，畫面更新合併為最多約每 100ms；裝置 tabs 重用 widget。
- 裝置 Log 搜尋/過濾/暫停/追蹤/清除畫面完成，最多 500 筆；CSV 及 batch.txt 不受影響。

## 已取得測試證據

- `py -3 -X utf8 -m pytest tests/test_csv_and_ble_helpers.py tests/test_ui_imports.py -q` → **94 passed**, 92.29s, exit 0。
- `py -3 -X utf8 -m pytest tests/test_recording_ux.py -q` → **7 passed**, 4.56s, exit 0。
- 整合測試以 250 筆通知實寫 CSV，畫面暫停時仍保留全部 250 筆；第 1/125/250 筆欄位 read-back 都為預期值。
- 另有各子工作測試與 fresh reviewer 紀錄（同目錄）；整體 UI 截圖與全套測試進行中。

## 第二輪：真實字型與窄螢幕修正

- 第一輪全套：`264 passed in 144.13s`，exit 0。
- Windows offscreen 初始字型資料庫為空；UI 驗證腳本現在明確載入系統 Segoe UI、Microsoft JhengHei、Consolas，避免方框截圖造成錯誤驗收。
- 真實字型截圖揭露 200% 時分頁最小高度撐大主窗、Overview 區域重疊、成對側欄按鈕過寬。
- 已為分頁增加可捲動容器，Overview 提示分列，側欄成對按鈕在窄寬度自動直排。
- 200% light 下 1024×768 / 1366×768 實跑保持指定視窗尺寸、0 issues；另 10,000 筆通知加速模擬 CSV read-back 正確（非實機耐久測試）。
- 最終全套使用隔離 IniFormat QSettings；完整 20 組截圖與 fresh review 收尾中。
- 將產生 `dist/ux-preview/PC_GIOSXTR_Demo_V2.0.2.exe` 本機試用包，不更動現有 dist 根目錄的發佈檔，也不發佈 GitHub Release。

## 最終驗證紀錄

- 隔離 UserScope/SystemScope INI 設定後的完整回歸：**264 passed in 186.67s**，exit 0。
- `scripts/verify_debug_ux.py --samples 10000`：**20 組視窗／字級／主題矩陣，180 PNG，exit 0**；已載入真實 Windows 字型與波形曲線。
- 啟用波形的 10,000 筆合法通知加速模擬，CSV 實讀 10,006 列（含預置 6 列）、26 欄、12 個分檔，無遺失；Log 暫停不影響寫入，事件緩衝仍為每裝置 500 筆。
- Fresh reviewer 額外通過多裝置、磁碟故障、同秒並行檔名、跨分檔三筆 read-back；發現既有 waveform legend 變更倍率後未更新實際文字，已修並以 QTextDocument 實際 22pt 檢查通過。
- Waveform 最後的圖例與亮色標題對比修正，相關測試 **21 passed**；因該修正重建試用包以確保 EXE 含最新程式。
- 初版 PyInstaller build exit 0；最後試用包 startup-probe 與 fresh reviewer 最终結論待追加。
- 本輪測試暫存目錄已移至 `build/ux-test-evidence/`；既有使用者修改與原始紀錄未刪除或覆寫。
- Waveform 截圖追驗另外發現倍率切換會清掉軸標題；已保留軸文字、單位、前綴與可見性，補上同一張圖 5 倍率 × 亮暗完整循環驗證。
- 最後相關回歸 **22 passed**；fresh reviewer 波形追驗 **15 passed, 85 deselected**。定版圖表 `build/ux-review/waveform-final/report.json` 共 **10 組 pass / 0 issues**，標題與圖例已人工目視。
- **源碼與 UI fresh review 通過**，完整結論見 `2026-10-13-independent-review.md`；尚未驗證的實體 BLE/dongle、多螢幕切換、2 小時以上耐久錄製，README 已列實機操作步驟。

## 交付

- 最新程式已重新打包：`dist/ux-preview/PC_GIOSXTR_Demo_V2.0.2.exe`（143,876,614 bytes）。版本標示沿用 V2.0.2，此為本機 UX 試用包，未發佈。
- 最後 PyInstaller build **exit 0**；執行該 EXE `--startup-probe` **exit 0**，7.088 秒，stdout/stderr 空。
- 此 probe 僅驗證封裝 runtime/imports，沒有建立 QApplication；GUI 證據來自源碼 offscreen 實跑，不宣称 EXE 完整 GUI／硬體已實測。
- SHA-256：`84e3d1b907a07b9f23a4dbd81d5d3101b3e3f4a6be5a0d0829622a64e1a327c0`。
- 包裝證據：`build/ux-preview-package-verification.json`、`build/ux-preview-build-final.log`。
- 使用方式與尚待實機驗證的步驟：README「Debug 與長時間紀錄」。
