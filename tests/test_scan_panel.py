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


def test_scan_panel_moves_connected_result_out_of_available_list():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QApplication

    from app.ble_manager import DeviceScanResult
    from app.windows.scan_panel import ScanPanel

    app = QApplication.instance() or QApplication([])
    panel = ScanPanel(ble=object())
    connected_result = DeviceScanResult(
        address="90:04:22:B6:96:00",
        name="GIOS0801ST#45",
        rssi=-52,
        raw_hex="",
        advertising_rows=[],
        device_number=45,
        firmware_revision=None,
    )
    available_result = DeviceScanResult(
        address="2E:7C:13:57:B4:81",
        name="GIOS0403ST#0",
        rssi=-61,
        raw_hex="",
        advertising_rows=[],
        device_number=0,
        firmware_revision=None,
    )
    panel.results = [connected_result, available_result]
    panel._rebuild_scan_list()

    panel.refresh_connected_devices(
        [
            {
                "address": connected_result.address,
                "name": connected_result.name,
                "device_number": "45",
                "connected": "1",
                "reconnecting": "0",
                "recording": "0",
                "packets": "139",
            }
        ],
        connected_result.address,
    )

    assert panel.list_widget.count() == 1
    remaining = panel.list_widget.item(0).data(Qt.ItemDataRole.UserRole)
    assert isinstance(remaining, DeviceScanResult)
    assert remaining.address == available_result.address
    assert panel.connected_list.count() == 1
    assert (
        panel.connected_list.item(0).data(Qt.ItemDataRole.UserRole)
        == connected_result.address
    )

    # A manual disconnect removes the address from the lower tracked list, so
    # the still-valid result from the last scan can be selected again.
    panel.refresh_connected_devices([], "")

    visible_addresses = {
        panel.list_widget.item(row).data(Qt.ItemDataRole.UserRole).address
        for row in range(panel.list_widget.count())
    }
    assert visible_addresses == {connected_result.address, available_result.address}


def test_scan_panel_hides_reconnecting_result_from_available_list():
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
                "connected": "0",
                "reconnecting": "1",
                "recording": "0",
                "packets": "139",
            }
        ],
        result.address,
    )

    assert panel.list_widget.count() == 0
    assert panel.connected_list.count() == 1


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


def test_connected_device_context_menu_disconnects_the_clicked_address(monkeypatch):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QApplication

    from app.windows import scan_panel as scan_panel_module
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
                "recording": "0",
                "packets": "7",
            },
            {
                "address": "2F:7C:13:57:B4:81",
                "name": "GIOS0403ST#0",
                "device_number": "0",
                "connected": "1",
                "reconnecting": "0",
                "recording": "0",
                "packets": "3",
            },
        ],
        "90:04:22:B6:96:00",
    )
    menu_labels: list[str] = []

    class FakeMenu:
        def __init__(self, _parent):
            self.action = object()

        def addAction(self, label):
            menu_labels.append(label)
            return self.action

        def exec(self, _position):
            return self.action

    monkeypatch.setattr(scan_panel_module, "QMenu", FakeMenu)
    requested: list[str] = []
    panel.device_disconnect_requested.connect(requested.append)
    panel.resize(380, 820)
    panel.show()
    app.processEvents()
    second_item = panel.connected_list.item(1)
    click_position = panel.connected_list.visualItemRect(second_item).center()

    panel._show_connected_context_menu(click_position)

    assert (
        panel.connected_list.contextMenuPolicy()
        is Qt.ContextMenuPolicy.CustomContextMenu
    )
    assert menu_labels == ["中斷此裝置"]
    assert requested == ["2F:7C:13:57:B4:81"]
    panel.close()


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


def test_scan_panel_dongle_failure_keeps_recovery_retry_available(monkeypatch):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    import asyncio

    from PyQt6.QtWidgets import QApplication, QMessageBox

    from app.ble_adapter import AdapterCheckResult, AdapterStatus
    from app.windows.scan_panel import ScanPanel

    class FakeDongle:
        readiness_retry_allowed = True

        async def check_ready(self):
            return AdapterCheckResult(
                AdapterStatus.NO_ADAPTER,
                "serial read failed on COM8",
            )

        def readiness_error_message(self, result):
            return "Nordic dongle 無法使用", f"Dongle error: {result.detail}"

    app = QApplication.instance() or QApplication([])
    panel = ScanPanel(ble=FakeDongle())
    shown: list[tuple[str, str]] = []
    monkeypatch.setattr(
        QMessageBox,
        "information",
        lambda _parent, title, body: shown.append((title, body)),
    )

    allowed = asyncio.run(panel._adapter_ready_for_scan())

    assert not allowed
    assert shown == [
        ("Nordic dongle 無法使用", "Dongle error: serial read failed on COM8")
    ]
    assert panel.scan_btn.isEnabled()
    assert panel.scan_btn.text() == "重新連接 dongle"


def test_scan_panel_friendly_message_on_dongle_transaction_abort(monkeypatch):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    import asyncio

    from PyQt6.QtWidgets import QApplication, QMessageBox

    from app.ble_adapter import AdapterCheckResult, AdapterStatus
    from app.device_source import _SCAN_UNAVAILABLE_MESSAGE, DongleTransactionAborted
    from app.windows.scan_panel import ScanPanel

    class FakeDongle:
        readiness_retry_allowed = True

        async def check_ready(self):
            return AdapterCheckResult(AdapterStatus.OK, "ok")

        async def scan(self, *, timeout: float, supported_only: bool):
            raise DongleTransactionAborted(
                "serial write failed on COM3: ClearCommError failed",
                user_message=_SCAN_UNAVAILABLE_MESSAGE,
            )

    app = QApplication.instance() or QApplication([])
    panel = ScanPanel(ble=FakeDongle())
    shown: list[tuple[str, str]] = []
    monkeypatch.setattr(
        QMessageBox,
        "warning",
        lambda _parent, title, body: shown.append((title, body)),
    )

    asyncio.run(panel.scan.__wrapped__(panel))

    assert len(shown) == 1
    title, body = shown[0]
    assert title == "接收器連線中斷"
    assert "dongle" in body
    assert "COM3" not in body
    assert "serial" not in body
    assert "ClearCommError" not in body
    assert panel.scan_btn.isEnabled()


def test_scan_panel_generic_error_path_unchanged_for_bleak(monkeypatch):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    import asyncio

    from PyQt6.QtWidgets import QApplication, QMessageBox

    from app.ble_adapter import AdapterCheckResult, AdapterStatus
    from app.windows.scan_panel import ScanPanel

    class FakeBle:
        async def check_ready(self):
            return AdapterCheckResult(AdapterStatus.OK, "ok")

        async def scan(self, *, timeout: float, supported_only: bool):
            raise Exception("boom")

    app = QApplication.instance() or QApplication([])
    panel = ScanPanel(ble=FakeBle())
    shown: list[tuple[str, str]] = []
    monkeypatch.setattr(
        QMessageBox,
        "warning",
        lambda _parent, title, body: shown.append((title, body)),
    )

    asyncio.run(panel.scan.__wrapped__(panel))

    assert shown == [("掃描失敗", "boom")]
    assert panel.scan_state_title.text() == "掃描失敗"
