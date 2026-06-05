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
    from PyQt6.QtWidgets import QApplication

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

    assert "重新連線中" in panel.connected_list.item(0).text()
    assert "90:6C:0A:C9:96:00" in panel._reconnecting_addresses


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
