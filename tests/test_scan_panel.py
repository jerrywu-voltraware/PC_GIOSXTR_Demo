import os


def test_recent_devices_are_not_shown_in_scan_results():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication

    from PyQt6.QtCore import Qt

    from app.ble_manager import DeviceScanResult
    from app.recent_devices import RecentDevice
    from app.windows.scan_panel import ScanPanel

    app = QApplication.instance() or QApplication([])
    panel = ScanPanel(ble=object())
    panel.set_recent_devices(
        [
            RecentDevice(
                address="90:6C:0A:C9:96:00",
                name="GIOS0403ST#4",
                device_number=4,
                rssi=-55,
            )
        ]
    )

    item = panel.list_widget.item(0)
    assert item is not None
    assert not isinstance(item.data(Qt.ItemDataRole.UserRole), DeviceScanResult)


def test_empty_scan_does_not_fall_back_to_recent_devices():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    import asyncio

    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QApplication

    from app.ble_adapter import AdapterCheckResult, AdapterStatus
    from app.ble_manager import DeviceScanResult
    from app.recent_devices import RecentDevice
    from app.windows.scan_panel import ScanPanel

    class FakeBle:
        async def check_ready(self):
            return AdapterCheckResult(AdapterStatus.OK, "ok")

        async def scan(self, *, timeout: float, supported_only: bool):
            return []

    app = QApplication.instance() or QApplication([])
    panel = ScanPanel(ble=FakeBle())
    panel.set_recent_devices(
        [
            RecentDevice(
                address="90:6C:0A:C9:96:00",
                name="GIOS0403ST#4",
                device_number=4,
                rssi=-55,
            )
        ]
    )

    asyncio.run(panel.scan.__wrapped__(panel))

    item = panel.list_widget.item(0)
    assert item is not None
    assert not isinstance(item.data(Qt.ItemDataRole.UserRole), DeviceScanResult)
    assert panel.scan_state_title.text() == "沒有找到支援裝置"


def test_connected_device_list_marks_reconnecting_device():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication, QLabel

    from app.recent_devices import RecentDevice
    from app.windows.scan_panel import ScanPanel

    app = QApplication.instance() or QApplication([])
    panel = ScanPanel(ble=object())
    panel.set_recent_devices(
        [
            RecentDevice(
                address="90:6C:0A:C9:96:00",
                name="GIOS0403ST#4",
                device_number=4,
                rssi=-55,
            )
        ]
    )

    panel.refresh_connected_devices(
        [
            {
                "address": "90:6C:0A:C9:96:00",
                "name": "GIOS0403ST#4",
                "device_number": "4",
                "connected": "0",
                "reconnecting": "1",
                "recording": "0",
                "packets": "12",
            }
        ],
        "90:6C:0A:C9:96:00",
    )

    status_label = panel.connected_list.itemWidget(panel.connected_list.item(0)).findChild(
        QLabel, "connectedDeviceStatusLabel"
    )
    assert status_label is not None
    assert "12" in status_label.text()
    assert "90:6C:0A:C9:96:00" in panel._reconnecting_addresses


def test_scan_panel_connected_scan_result_switches_active_without_reconnect():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication

    from app.ble_manager import DeviceScanResult
    from app.windows.scan_panel import ScanPanel

    app = QApplication.instance() or QApplication([])
    panel = ScanPanel(ble=object())
    result = DeviceScanResult(
        address="90:04:22:B6:96:00",
        name="GIOS0801ST#45",
        rssi=-52,
        raw_hex="",
        advertising_rows=[],
        device_number=45,
        firmware_revision=None,
    )
    panel.results = [result]
    panel.refresh_connected_devices(
        [
            {
                "address": result.address,
                "name": result.name,
                "device_number": "45",
                "connected": "1",
                "reconnecting": "0",
                "recording": "0",
                "packets": "139",
            }
        ],
        result.address,
    )
    panel.list_widget.setCurrentRow(0)
    connect_requests: list[str] = []
    active_changes: list[str] = []
    panel.device_connect_requested.connect(lambda item: connect_requests.append(item.address))
    panel.active_changed.connect(active_changes.append)

    panel.connect_selected()

    assert connect_requests == []
    assert active_changes == [result.address]


def test_connected_device_list_colors_recording_device_red_and_splits_status():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtGui import QColor
    from PyQt6.QtWidgets import QApplication, QLabel

    from app.windows.scan_panel import ScanPanel

    app = QApplication.instance() or QApplication([])
    panel = ScanPanel(ble=object())

    panel.refresh_connected_devices(
        [
            {
                "address": "90:04:22:B6:96:00",
                "name": "GIOS0801ST#45",
                "device_number": "45",
                "connected": "1",
                "reconnecting": "0",
                "recording": "1",
                "packets": "88",
            },
            {
                "address": "A0:DD:6C:A3:64:5E",
                "name": "GIOS-S20-GW02",
                "device_number": "",
                "connected": "1",
                "reconnecting": "0",
                "recording": "0",
                "packets": "12",
            },
        ],
        "90:04:22:B6:96:00",
    )

    recording_item = panel.connected_list.item(0)
    idle_item = panel.connected_list.item(1)
    recording_widget = panel.connected_list.itemWidget(recording_item)
    idle_widget = panel.connected_list.itemWidget(idle_item)
    recording_name = recording_widget.findChild(QLabel, "connectedDeviceNameLabel")
    recording_status = recording_widget.findChild(QLabel, "connectedDeviceStatusLabel")
    recording_address = recording_widget.findChild(QLabel, "connectedDeviceAddressLabel")
    idle_name = idle_widget.findChild(QLabel, "connectedDeviceNameLabel")

    assert recording_item.text() == ""
    assert idle_item.text() == ""
    assert recording_name is not None
    assert recording_status is not None
    assert recording_address is not None
    assert idle_name is not None
    assert "88" in recording_status.text()
    assert recording_status.wordWrap()
    assert QColor(panel._tokens.error_fg).name().lower() in recording_name.styleSheet().lower()
    assert QColor(panel._tokens.error_fg).name().lower() in recording_status.styleSheet().lower()
    assert QColor(panel._tokens.error_fg).name().lower() in recording_address.styleSheet().lower()
    assert QColor(panel._tokens.text_primary).name().lower() in idle_name.styleSheet().lower()


def test_scan_panel_uses_scroll_area_and_flexible_list_heights():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QApplication

    from app.windows.scan_panel import ScanPanel

    app = QApplication.instance() or QApplication([])
    panel = ScanPanel(ble=object())

    assert panel.scroll_area.widgetResizable()
    assert panel.scroll_area.horizontalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
    assert panel.list_widget.horizontalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
    assert panel.connected_list.horizontalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
    assert panel.list_widget.minimumHeight() <= 160
    assert panel.connected_list.minimumHeight() <= 96


def test_scan_panel_auto_reconnect_toggle_is_visible_and_emits():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication

    from app.windows.scan_panel import ScanPanel

    app = QApplication.instance() or QApplication([])
    panel = ScanPanel(ble=object())
    received: list[bool] = []
    panel.auto_reconnect_changed.connect(received.append)

    panel.set_auto_reconnect_enabled(True)
    assert panel.auto_reconnect_box.isChecked()
    assert received == []

    panel.auto_reconnect_box.setChecked(False)

    assert received == [False]


def test_scan_panel_scan_result_rows_fit_custom_widgets():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication

    from app.ble_manager import DeviceScanResult
    from app.windows.scan_panel import ScanPanel

    app = QApplication.instance() or QApplication([])
    panel = ScanPanel(ble=object())
    result = DeviceScanResult(
        address="90:04:22:B6:96:00",
        name="GIOS0801ST#45",
        rssi=-45,
        raw_hex="",
        advertising_rows=[],
        device_number=45,
        firmware_revision=None,
        device=None,
    )

    panel._add_scan_result(result)
    item = panel.list_widget.item(panel.list_widget.count() - 1)
    widget = panel.list_widget.itemWidget(item)

    assert widget is not None
    assert item.sizeHint().height() >= widget.sizeHint().height()


def test_scan_panel_adapter_unavailable_disables_scan_button():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication

    from app.ble_adapter import AdapterStatus
    from app.windows.scan_panel import ScanPanel

    app = QApplication.instance() or QApplication([])
    panel = ScanPanel(ble=object())

    panel.set_adapter_unavailable(AdapterStatus.NO_ADAPTER, "請插入支援 BLE 4.0 以上的 USB 藍牙接收器。")

    assert not panel.scan_btn.isEnabled()
    assert panel.scan_btn.text() == "藍牙不可用"
    assert panel.scan_state_title.text() == "藍牙不可用"
    assert "USB 藍牙接收器" in panel.scan_state_detail.text()


def test_scan_panel_adapter_available_restores_scan_button():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication

    from app.ble_adapter import AdapterStatus
    from app.windows.scan_panel import ScanPanel

    app = QApplication.instance() or QApplication([])
    panel = ScanPanel(ble=object())
    panel.set_adapter_unavailable(AdapterStatus.DISABLED, "藍牙已關閉。")

    panel.set_adapter_available()

    assert panel.scan_btn.isEnabled()
    assert panel.scan_btn.text() == "搜尋裝置"


def test_scan_panel_adapter_precheck_blocks_ble_scan(monkeypatch):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    import asyncio

    from PyQt6.QtWidgets import QApplication, QMessageBox

    from app.ble_adapter import AdapterCheckResult, AdapterStatus
    from app.windows import scan_panel as scan_panel_module
    from app.windows.scan_panel import ScanPanel

    class FakeBle:
        called = False

        async def scan(self, *, timeout: float, supported_only: bool):
            self.called = True
            return []

    async def fake_check_adapter():
        return AdapterCheckResult(AdapterStatus.NO_ADAPTER, "missing")

    app = QApplication.instance() or QApplication([])
    ble = FakeBle()
    panel = ScanPanel(ble=ble)
    shown: list[tuple[str, str]] = []
    monkeypatch.setattr(scan_panel_module, "check_bluetooth_adapter", fake_check_adapter)
    monkeypatch.setattr(
        QMessageBox,
        "information",
        lambda _parent, title, body: shown.append((title, body)),
    )

    allowed = asyncio.run(panel._adapter_ready_for_scan())

    assert not allowed
    assert not ble.called
    assert shown[0][0] == "找不到藍牙介面"
    assert not panel.scan_btn.isEnabled()
