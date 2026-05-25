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
