# PC GIOSXTR Desktop Port Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a PyQt6 Windows desktop application that fully ports the Flutter GIOS040XST BLE engineering app.

**Architecture:** The app separates BLE transport, protocol parsing, state storage, CSV logging, and UI rendering. `bleak` callbacks flow through Qt signals into a shared `DeviceState`, which feeds data pages, CSV logging, waveform charts, log/error views, and demo pages.

**Tech Stack:** Python 3.10+, PyQt6, bleak, qasync, pyqtgraph, pytest, PyInstaller.

---

### Task 1: Project Skeleton

**Files:**
- Create: `requirements.txt`
- Create: `main.py`
- Create: `app/__init__.py`
- Create: `app/windows/__init__.py`

- [ ] **Step 1: Create runtime dependencies**

```text
PyQt6>=6.6
bleak>=0.22
qasync>=0.27
pyqtgraph>=0.13
pytest>=8.0
pyinstaller>=6.0
```

- [ ] **Step 2: Create the Qt/qasync launcher**

```python
from __future__ import annotations

import asyncio
import sys

from PyQt6.QtWidgets import QApplication
from qasync import QEventLoop

from app.windows.main_window import MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    loop = QEventLoop(app)
    asyncio.set_event_loop(loop)
    window = MainWindow()
    window.show()
    with loop:
        loop.run_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 3: Verify imports fail until app modules exist**

Run: `python -m pytest -q`
Expected: FAIL until tests and modules are added.

### Task 2: Data Model And Protocol Parser

**Files:**
- Create: `app/models.py`
- Create: `app/protocol.py`
- Create: `tests/test_protocol.py`

- [ ] **Step 1: Write parser tests first**

```python
from app.models import DeviceState
from app.protocol import decode_iot_packet, decode_20b_packet, decode_200b_packet


def test_iot_short_packet_is_ignored():
    state = DeviceState()
    decode_iot_packet([1, 2, 3], state)
    assert state.ptu_system_state_string == "-"


def test_20b_packet_updates_core_values():
    state = DeviceState()
    data = [3, 0x10, 0x27, 0x20, 0x4E, 0x01, 0x02, 0x34, 0x12, 45, 8, 10, 0x20, 0x03, 0x30, 0x04, 0x40, 0x05, 30, 7]
    decode_20b_packet(data, state)
    assert state.ptu_system_state_string == "P_Transfer"
    assert state.ptu_input_voltage == 10000
    assert state.ptu_input_current == 20000
    assert state.pru_reg_item_state_string == "PRU Registered"
    assert state.error_num == 7


def test_200b_packet_updates_charger_and_error_fields():
    state = DeviceState()
    data = [0] * 204
    data[0] = 8
    data[4] = 0x10
    data[5] = 0x27
    data[6] = 0x20
    data[7] = 0x4E
    data[48] = 10
    data[52] = 0x20
    data[53] = 0x03
    data[56] = 0x30
    data[57] = 0x04
    data[58] = 0x40
    data[59] = 0x05
    data[76] = 0xE8
    data[77] = 0x03
    data[88] = 0x10
    data[89] = 0x27
    data[192] = 0x11
    data[196] = 1
    data[200] = 2
    decode_200b_packet(data, state)
    assert state.ptu_system_state_string == "Cooling"
    assert state.pru_reg_item_state_string == "PRU Registered"
    assert state.pru_chg_t_bat == 1000
    assert state.pru_chg_v_bat == 10000
    assert state.error_num == 0x11
    assert state.error_data == 1
    assert state.error_limit == 2
```

- [ ] **Step 2: Run tests and confirm missing modules fail**

Run: `pytest tests/test_protocol.py -q`
Expected: FAIL with import errors.

- [ ] **Step 3: Implement dataclasses and parser functions**

Create `DeviceState` with all Flutter fields and pure parser functions for IOT, 20B, and 200B packets.

- [ ] **Step 4: Run parser tests**

Run: `pytest tests/test_protocol.py -q`
Expected: PASS.

### Task 3: BLE, CSV, Assets, And UI

**Files:**
- Create: `app/constants.py`
- Create: `app/ble_manager.py`
- Create: `app/csv_logger.py`
- Create: `app/assets.py`
- Create: `app/windows/main_window.py`
- Create: `app/windows/scan_panel.py`
- Create: `app/windows/overview_page.py`
- Create: `app/windows/data_pages.py`
- Create: `app/windows/number_page.py`
- Create: `app/windows/waveform_page.py`
- Create: `app/windows/log_page.py`
- Create: `app/windows/error_page.py`
- Create: `app/windows/demo_pages.py`

- [ ] **Step 1: Implement BLE manager**

Use bleak scan/connect/write/start_notify APIs, expose callback registration, and provide CLI commands `--scan` and `--connect`.

- [ ] **Step 2: Implement CSV logger**

Write the Flutter-compatible header and append rows from `DeviceState`.

- [ ] **Step 3: Implement assets helper**

Resolve copied PNG files under `assets/` for demo pages.

- [ ] **Step 4: Implement PyQt6 UI pages**

Create a main window with a left scan/control panel and right-side tabs for Overview, PTU, PRU, Charger, Number, Waveform, Log, Error, Demo1, Demo2, and Demo3.

- [ ] **Step 5: Copy Flutter assets**

Copy PNG assets from `Flutter_Gios040xst_Eng/assets/` into `assets/`.

- [ ] **Step 6: Run app import smoke check**

Run: `python -c "from app.windows.main_window import MainWindow; print('ok')"`
Expected: `ok`.

### Task 4: Docs, Packaging, And Verification

**Files:**
- Create: `README.md`
- Create: `PC_GIOSXTR_Demo.spec`

- [ ] **Step 1: Document setup and smoke tests**

Include venv setup, `pip install -r requirements.txt`, `python main.py`, CLI BLE scan/connect, pytest, and PyInstaller build commands.

- [ ] **Step 2: Create PyInstaller spec**

Include Python modules and copied assets.

- [ ] **Step 3: Run verification**

Run:

```powershell
pytest -q
python -c "from app.protocol import decode_20b_packet; from app.windows.main_window import MainWindow; print('imports ok')"
python -m app.ble_manager --help
```

Expected: tests pass, imports print `imports ok`, and BLE CLI help prints usage.

## Self-Review

- Spec coverage: BLE scan/connect, notify decode, PTU/PRU/Charger pages, Number, Waveform, Log, Error, Demo1/2/3, CSV, assets, docs, packaging, and tests are all covered by tasks.
- Placeholder scan: no planned step depends on an unspecified file or function name.
- Type consistency: parser functions update `DeviceState`; UI pages read the same model; CSV logger consumes `DeviceState`.
