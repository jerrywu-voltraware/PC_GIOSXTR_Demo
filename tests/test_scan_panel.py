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
