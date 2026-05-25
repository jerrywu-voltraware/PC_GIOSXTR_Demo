import os


def test_recent_device_item_becomes_active_after_connect_without_scan_results():
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
                "recording": "0",
                "packets": "0",
            }
        ],
        "90:6C:0A:C9:96:00",
    )

    item_widget = panel.list_widget.itemWidget(panel.list_widget.item(0))

    assert item_widget is not None
    assert "#DDF7F4" in item_widget.styleSheet()


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
