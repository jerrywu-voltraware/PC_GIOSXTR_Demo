# PC GIOSXTR Desktop Port Design

## Goal

Build a Windows PC desktop version of `Flutter_Gios040xst_Eng` using Python, PyQt6, bleak, and qasync. The PC version fully preserves the Flutter app's functional behavior while adapting the interface for desktop operation.

The Flutter project remains the source reference. The new PC application lives at `D:\jerry\Python\PC_GIOSXTR_Demo` and treats `D:\jerry\Python\PC_GIOSXTR_Demo\Flutter_Gios040xst_Eng` as read-only reference material.

## Chosen Approach

Use the existing `D:\jerry\Python\PC_GIOSXSR_Demo` project as the implementation pattern. It already proves the Windows stack of PyQt6, bleak, qasync, and PyInstaller. The GIOSXTR project will use the same event-loop and packaging style, but it will have its own XST protocol parser, device state model, UI pages, copied assets, CSV logger, and tests.

This avoids re-solving Windows BLE event-loop issues while keeping the GIOSXTR implementation independent from the older GIOSXSR code.

## Technology

- Python 3.10 or newer.
- PyQt6 for desktop UI.
- bleak for Windows BLE scanning, connecting, GATT notify, read, and write.
- qasync to bridge Qt's event loop with asyncio.
- pyqtgraph for live waveform charts.
- pytest for protocol parser tests.
- PyInstaller for Windows executable packaging.

## Project Structure

```text
PC_GIOSXTR_Demo/
├── main.py
├── requirements.txt
├── README.md
├── app/
│   ├── __init__.py
│   ├── assets.py
│   ├── ble_manager.py
│   ├── constants.py
│   ├── csv_logger.py
│   ├── models.py
│   ├── protocol.py
│   └── windows/
│       ├── __init__.py
│       ├── main_window.py
│       ├── scan_panel.py
│       ├── overview_page.py
│       ├── data_pages.py
│       ├── number_page.py
│       ├── waveform_page.py
│       ├── log_page.py
│       ├── error_page.py
│       └── demo_pages.py
├── assets/
│   └── copied Flutter image assets
└── tests/
    ├── test_protocol_iot.py
    ├── test_protocol_20b.py
    └── test_protocol_200b.py
```

Each file has a narrow responsibility. BLE transport, protocol decoding, state storage, CSV persistence, and UI rendering are separate so the protocol can be tested without hardware or Qt widgets.

## Desktop UI

The PC application uses a desktop layout instead of a phone-shaped one.

The main window contains a persistent left panel and a right content area. The left panel handles scan, connect, disconnect, connection status, selected device, RSSI, firmware revision, device number, packet counters, and a compact recent-log view. The right content area uses tabs or a navigation list for:

- `Overview`
- `PTU`
- `PRU`
- `Charger`
- `Number`
- `Waveform`
- `Log`
- `Error`
- `Demo1`
- `Demo2`
- `Demo3`

This preserves the Flutter feature set while making engineering workflows faster on a desktop monitor. PTU, PRU, and Charger data use dense tables grouped by system state, power, voltage/current, temperature, coil information, and efficiency. Waveform and log views are designed for repeated observation rather than mobile scrolling.

## BLE Behavior

Scanning supports the same device names as Flutter:

- `Central`
- `GIOS0003ST`
- `GIOS0007ST`
- `GIOS0403ST`
- `GIOS0404ST`
- `GIOS0701ST`
- `GIOS0801ST`

The scan filter keeps devices with RSSI greater than `-90 dBm`. Results are de-duplicated by BLE address. The scan table displays device name, address, RSSI, connection state, device number, firmware revision, raw advertising bytes, and parsed AD structures.

Connection flow:

1. Connect with bleak.
2. Discover services and characteristics.
3. Store write characteristics:
   - `6455e670-a146-11e2-9e96-0800200c9a68`
   - `6455fff1-a146-11e2-9e96-0800200c9a67`
4. Subscribe to notify characteristics:
   - `6455e670-a146-11e2-9e96-0800200c9a67` for 200B data.
   - `6455e670-a146-11e2-9e96-0800200c9a69` for 20B data.
   - `6455fff2-a146-11e2-9e96-0800200c9a67` for IOT data.
5. Dispatch notification bytes through a Qt signal before updating UI state.

The PC version does not implement Android or iOS permission handling because Windows BLE permissions are managed by the OS and bleak backend.

## Protocol Decoding

`app/protocol.py` ports the Flutter functions:

- `decodeBleReceivedIotData`
- `decodeBleReceived20bytesData`
- `decodeBleReceivedData`

The parser updates a `DeviceState` model with these groups:

- PTU: system state, input voltage/current, bus voltage/current, temperatures, coil values, firmware version, DCDC duty, MAC, array level.
- PRU: registration state, type, firmware version, dynamic rectifier/output values, Vrect min/set/max, MAC.
- Charger: voltage, current, power, temperature, efficiency, charger/system/supply/fault status, time remaining fields.
- Error: error code, error data, error limit, last error code.
- Packet counters: IOT, 20B, 200B.
- Derived values: input power, output power, system efficiency.

State-name mapping remains the same as Flutter:

- PTU: `Config`, `P_Save`, `L_Power`, `P_Transfer`, `Latch_Fault`, `Local_Fault`, `Count`, `OTA`, `Cooling`, `EXCEEDED_RANGE`, `High_Vrect`, `Unknown`.
- PRU: `Unused`, `Pre Connect`, `Fully Accepted`, `Waiting to connect`, `Connecting`, `Reg enable alert`, `PRU Stat RD`, `PTU Stat WR`, `PRU DY RD`, `PRU CTL SEND`, `PRU Registered`, `Unknown`.

State transitions append log entries. Error code changes trigger both a dialog and a log entry.

## CSV Logging

CSV logging follows the Flutter behavior:

- Automatically start when PRU state transitions into a connected state.
- Allow manual start and stop.
- Write one row per valid parsed packet when either PTU input voltage or PRU output voltage is non-zero.
- Keep the Flutter CSV header:

```text
Sys_time,PTU_state,V_in,I_in,V_bus,I_bus,T_bus,T_amp,T_IC,I1,I3,I1I3_Deg,DCDC_Duty,Array,EFF,V_rect,I_rect,V_out,I_out,T_sys,Vrect_min,Vrect_set,Vrect_max,Error_code,Error_data1,Error_data2
```

CSV files are saved under a local PC application logs directory, with filenames matching the Flutter style: `Log_YYYYMMDD_HHMMSS.csv`.

## Number Setting

The `Number` page writes to characteristic `6455fff1-a146-11e2-9e96-0800200c9a67`.

- Set device number: `[0xA1, selected_number]`, where selected number is 1 through 254.
- Reset default number: `[0xA1, 0xFF]`.

The page shows write progress, success, and failure messages. It does not hide BLE errors; failures display the exact exception text.

## Waveform

Waveform uses pyqtgraph and supports the same signal set as Flutter's `SignalType`:

- PTU voltage/current/power, bus values, temperatures, coil values, DCDC duty, array level, system efficiency.
- PRU Vrect/Irect/Vout/Iout/output power, temperature, Vrect min/set/max.
- Error code, error data, error limit.

Behavior:

- Up to 5 live charts.
- Add/remove individual charts.
- Reset a chart or reset all charts.
- Pause/resume drawing.
- Display window from 50 to 1000 samples.
- Stop drawing on disconnect and allow resume after reconnect.

All charts share a sample index timeline, matching the Flutter oscilloscope-style behavior.

## Demo Pages

The Flutter image assets are copied into the PC project and reused.

Demo pages preserve the three Flutter demo modes:

- `Demo1`: asset-based PTU/vehicle/battery status view.
- `Demo2`: desktop-adapted energy-flow view based on the Flutter custom painter concept.
- `Demo3`: alternate asset-based status view.

Demo controls include:

- Scooter Charging
- Bike Charging
- Scooter Full
- Bike Full
- Scooter Standby
- Bike Standby
- Engineering
- No Device

Animations use Qt timers. Battery images, PTU state images, cooling animation, position error animation, high-Vrect animation, and power-transfer image cycling are preserved with desktop sizing.

## Log And Error Views

The log view shows connection events, service discovery, notify subscription events, packet type counts, PTU state transitions, PRU state transitions, CSV state changes, number-write results, and BLE failures.

The error view shows:

- Error code in decimal and hex.
- Error description.
- Error data in decimal and hex.
- Error limit in decimal and hex.
- Latest occurrence time.

When the error code changes from the previous value to a non-zero value, the app opens an error dialog and records the event in the log.

## Update Behavior

The Flutter Android OTA update flow is not ported. The PC app is distributed through PyInstaller builds. Version checking for PC distribution is outside this port.

## Error Handling

BLE notification callbacks never update widgets directly. The flow is:

```text
bleak notify callback
→ BleManager callback
→ Qt signal
→ ProtocolDecoder
→ DeviceState
→ UI pages, CSV logger, waveform buffer, error detector
```

Disconnect behavior:

- Mark the device as disconnected.
- Stop waveform drawing.
- Keep the current CSV file consistent and closeable.
- Show a disconnect banner.
- Offer a reconnect action.
- On reconnect, discover services again, re-store write characteristics, re-enable notify, and resume state updates.

All BLE scan, connect, write, notify, and parse failures are logged. User-triggered operations show dialog messages when they fail.

## Testing

Automated tests cover parser behavior without requiring BLE hardware:

- IOT data shorter than 15 bytes is ignored.
- IOT data updates PTU, PRU, MAC, firmware, and efficiency fields at the same offsets as Flutter.
- 20B data updates PTU, PRU, error number, and efficiency fields at the same offsets as Flutter.
- 200B data requires at least 193 bytes and updates PTU, PRU, charger, error, and derived fields.
- Error code transition detection fires only when the code changes to non-zero.

Hardware smoke tests:

```powershell
python -m app.ble_manager --scan
python -m app.ble_manager --connect <address>
```

Manual UI tests:

- Scan and connect a supported device.
- Verify advertising data table and raw bytes.
- Verify PTU, PRU, Charger, Log, and Error views update from notify data.
- Start and stop CSV logging and confirm file contents.
- Write a device number and reset to default.
- Add, pause, reset, and remove waveform charts.
- Open Demo1, Demo2, and Demo3 and verify image states and animations.
- Disconnect and reconnect the device.

## Acceptance Criteria

The port is complete when:

- The PC application launches from `python main.py`.
- A supported BLE device can be scanned, connected, disconnected, and reconnected.
- All three notify packet types are decoded and displayed.
- PTU, PRU, Charger, Number, Waveform, Log, Error, Demo1, Demo2, and Demo3 pages exist.
- CSV output matches Flutter column names and data order.
- Device-number write and reset commands use the Flutter command bytes.
- Demo pages reuse Flutter assets and visibly animate state changes.
- Protocol parser tests pass with pytest.
- A PyInstaller executable can be built and launched on Windows.
