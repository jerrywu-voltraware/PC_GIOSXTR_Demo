# PC_GIOSXTR_Demo

Windows desktop port of `Flutter_Gios040xst_Eng`, implemented with Python, PyQt6, bleak, qasync, and pyqtgraph.

## Features

- BLE scan, connect, disconnect, and reconnect workflow.
- Supported-device filtering for Central and GIOS ST device names.
- Advertising data reconstruction with raw bytes and AD structure table.
- IOT, 20B, and 200B notify packet decoding.
- PTU, PRU, Number, Waveform, Log, and Error pages.
- Manual CSV recording with Start Recording and Stop Recording controls.
- Device-number write and reset commands.
- Live waveform plots with up to 5 selected signals.
- Readable 11 pt text with persistent 100–200% text scaling in Settings → Appearance.
- Always-visible CSV health: elapsed time, successfully written rows, split count, last write, and storage errors.
- Searchable device events with pause/follow controls; CSV recording continues while the log view is paused.

Android OTA update is intentionally not ported. PC distribution uses PyInstaller builds and GitHub Releases for desktop update checks.

## Requirements

- Windows 10 1703 or newer.
- Python 3.10 or newer.
- BLE-capable Bluetooth adapter.

## Setup

```powershell
cd D:\jerry\Python\PC_GIOSXTR_Demo
python -m pip install -r requirements.txt
```

## Run

```powershell
python main.py
```

Internal DEMO scenario buttons are hidden by default. For development builds, enable them with either:

```powershell
python main.py --engineering
$env:PC_GIOSXTR_ENGINEERING="1"; python main.py
```

## Tests

```powershell
python -m pytest -q
```

## Debug 與長時間紀錄

- **調整字體**：右上「設定 → 外觀 → 介面字級」可選 100%、125%、150%、175%、200%；立即生效且自動記住。作業系統 DPI 由 Qt 處理。左右區域之間可拖曳；小螢幕的大字內容可捲動查看。
- **檢查是否真的有寫入**：上方錄製列會顯示目前裝置的實際成功寫入筆數、經過時間、分檔數與最後寫入時間。等待首筆資料、斷線等待重連、超過 10 秒沒有新寫入、儲存失敗均有文字提示。停止後保留本次統計。
- **儲存位置**：錄製列可開啟資料夾或用「變更…」指定 CSV 目錄；全部停止錄製後可變更，並記住下次使用的位置。錄製中顯示目前 CSV 完整路徑，可選取複製。`batch.txt` 仍使用既有應用程式紀錄位置，可從 Overview 開啟。
- **檢視 Log**：可搜尋、只顯示警告／錯誤、暫停畫面或追蹤最新。這些操作與「清除畫面」都不會停止 CSV 或刪除紀錄檔。畫面最多保留目前裝置最近 500 筆，完整技術歷程見 `batch.txt`。嚴重度篩選依訊息關鍵字判定。
- **資料保護**：每筆 CSV 仍會 flush；分檔及欄位格式保留。同一秒重啟錄製使用新檔名，避免覆寫既有檔案。寫入失敗會停止該裝置錄製並顯示原因，排除後需手動重新開始。

可重跑的離屏 UI 驗證（使用隔離設定與暫存資料，無需藍牙）：

```powershell
py -3 -X utf8 scripts/verify_debug_ux.py
```

截圖與報告位於 `build/ux-review/`。實機驗收請以 PC 藍牙及 Nordic dongle 各錄製至少 2 小時：確認筆數持續增加、分檔接續且內容可讀；拔除／恢復裝置後確認等待重連提示與續錄；在 Windows 100/125/150/200% 顯示縮放及跨螢幕移動時確認字型、按鈕、表列與捲動正常。這些硬體及長時間項目不由離屏測試取代。

## BLE Smoke Tests

```powershell
python -m app.ble_manager --scan
python -m app.ble_manager --connect <BLE_ADDRESS>
```

## Build EXE

```powershell
pyinstaller PC_GIOSXTR_Demo.spec
```

The executable will be created under `dist\`.

## 發佈與自動更新

自動更新會檢查這個公開 GitHub Releases：

```text
https://github.com/jerrywu-voltraware/PC_GIOSXTR_Demo
```

Release tag 必須使用小寫 `v` 開頭的語意化版本：

```text
v1.0.1
```

Release asset 必須上傳對應版本的 PyInstaller 執行檔：

```text
PC_GIOSXTR_Demo_V1.0.1.exe
```

每次發布前請先在本機完成驗證：

```powershell
python -m pytest -q
pyinstaller PC_GIOSXTR_Demo.spec
.\dist\PC_GIOSXTR_Demo_V1.0.1.exe
```

確認打包後的 exe 可以正常開啟與使用後，才建立 GitHub Release 並上傳該 exe。使用者只會在 GitHub Release 發布且包含 `.exe` asset 後收到更新提示。
