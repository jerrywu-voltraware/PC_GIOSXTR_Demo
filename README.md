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

## Release And Auto Update

Auto update checks use public GitHub Releases from:

```text
https://github.com/jerrywu-voltraware/PC_GIOSXTR_Demo
```

Release tags must use lowercase `v` semantic versions:

```text
v1.0.1
```

Release assets should use the matching PyInstaller executable name:

```text
PC_GIOSXTR_Demo_V1.0.1.exe
```

Before publishing a release:

```powershell
python -m pytest -q
pyinstaller PC_GIOSXTR_Demo.spec
.\dist\PC_GIOSXTR_Demo_V1.0.1.exe
```

Open and verify the packaged executable locally before creating the GitHub Release. Users only see updates after a GitHub Release is published with an `.exe` asset.
