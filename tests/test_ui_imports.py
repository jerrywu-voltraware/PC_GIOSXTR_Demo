import os
from pathlib import Path


def test_ui_modules_import():
    from app.windows.data_pages import PruPage, PtuPage
    from app.windows.error_page import ErrorPage
    from app.windows.log_page import LogPage
    from app.windows.main_window import MainWindow
    from app.windows.number_page import NumberPage
    from app.windows.overview_page import OverviewPage
    from app.windows.scan_panel import ScanPanel
    from app.windows.settings_dialog import SettingsDialog
    from app.windows.waveform_page import WaveformPage

    assert MainWindow
    assert ScanPanel
    assert OverviewPage
    assert PtuPage
    assert PruPage
    assert NumberPage
    assert WaveformPage
    assert LogPage
    assert ErrorPage
    assert SettingsDialog


def test_main_window_imports_with_updater_enabled():
    from app.windows.main_window import MainWindow

    assert MainWindow is not None


def test_main_window_initial_adapter_result_updates_scan_panel(monkeypatch):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication, QMessageBox

    from app.ble_adapter import AdapterCheckResult, AdapterStatus
    from app.windows.main_window import MainWindow

    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    shown: list[tuple[str, str]] = []
    monkeypatch.setattr(QMessageBox, "warning", lambda _parent, title, body: shown.append((title, body)))

    window._handle_adapter_check_result(
        AdapterCheckResult(AdapterStatus.DISABLED, "Bluetooth radio off"),
        show_warning=True,
    )

    assert window._last_adapter_status is AdapterStatus.DISABLED
    assert shown[0][0] == "藍牙已關閉"
    assert not window.scan_panel.scan_btn.isEnabled()
    window.close()


def test_default_update_save_path_uses_asset_name(tmp_path):
    from app.updater import UpdateAsset
    from app.windows.main_window import _default_update_save_path

    asset = UpdateAsset(name="PC_GIOSXTR_Demo_V1.0.2.exe", download_url="https://example.test/app.exe")

    assert _default_update_save_path(asset, downloads_dir=str(tmp_path)) == tmp_path / asset.name


def test_main_window_tabs_do_not_include_removed_pages():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication

    from app.windows.main_window import MainWindow

    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    labels = [window.tabs.tabText(index) for index in range(window.tabs.count())]
    window.close()
    assert labels == [
        "Overview",
        "PTU",
        "PRU",
        "Number",
        "Waveform",
        "DEMO",
        "Log",
        "Error",
    ]


def test_main_window_shows_device_tabs_for_multiple_ptus():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication

    from app.models import DeviceState
    from app.windows.main_window import MainWindow

    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    first = DeviceState(is_connected=True, device_name="GIOS0801ST#45", device_address="AA:BB", device_number=45)
    second = DeviceState(is_connected=True, device_name="GIOS0801ST#60", device_address="CC:DD", device_number=60)
    window.states[first.device_address] = first
    window.states[second.device_address] = second
    window.active_address = first.device_address
    window.state = first

    window.refresh_pages()

    labels = [window.device_tabs.tabText(index) for index in range(window.device_tabs.count())]
    assert not window.device_tabs.isHidden()
    assert labels == ["PTU #45", "PTU #60"]

    window.close()


def test_main_window_device_tab_switches_active_ptu():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication

    from app.models import DeviceState
    from app.windows.main_window import MainWindow

    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    first = DeviceState(is_connected=True, device_name="A", device_address="AA:BB", device_number=45)
    second = DeviceState(is_connected=True, device_name="B", device_address="CC:DD", device_number=60)
    window.states[first.device_address] = first
    window.states[second.device_address] = second
    window.active_address = first.device_address
    window.state = first
    window.refresh_pages()

    window.device_tabs.setCurrentIndex(1)

    assert window.active_address == second.device_address
    assert window.state is second
    window.close()


def test_main_window_device_tabs_hide_for_single_ptu_after_disconnect():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication

    from app.models import DeviceState
    from app.windows.main_window import MainWindow

    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    first = DeviceState(is_connected=True, device_name="A", device_address="AA:BB", device_number=45)
    second = DeviceState(is_connected=True, device_name="B", device_address="CC:DD", device_number=60)
    window.states[first.device_address] = first
    window.states[second.device_address] = second
    window.managers[first.device_address] = object()
    window.managers[second.device_address] = object()
    window.active_address = second.device_address
    window.state = second
    window.refresh_pages()

    window._cleanup_address(second.device_address)

    assert window.active_address == first.device_address
    assert window.device_tabs.isHidden()
    assert window.device_tabs.count() == 1
    window._close_after_disconnect = True
    window.close()


def test_data_pages_do_not_show_group_column():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication

    from app.models import DeviceState
    from app.windows.data_pages import PruPage, PtuPage

    app = QApplication.instance() or QApplication([])
    state = DeviceState()
    for page in (PtuPage(), PruPage()):
        page.refresh(state)
        labels = [page.table.horizontalHeaderItem(index).text() for index in range(page.table.columnCount())]
        assert labels == ["Field", "Value"]
        assert page.table.columnCount() == 2


def test_main_window_has_manual_csv_recording_controls(tmp_path):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication

    from app.csv_logger import CsvLogger
    from app.models import DeviceState
    from app.windows.main_window import MainWindow

    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    state = DeviceState(is_connected=True, device_name="Bike", device_address="AA:BB", device_number=7)
    window.states[state.device_address] = state
    window.loggers[state.device_address] = CsvLogger(tmp_path)
    window.active_address = state.device_address
    window.state = state
    window.refresh_pages()

    assert not window.scan_panel.start_recording_btn.isHidden()
    assert not window.scan_panel.stop_recording_btn.isHidden()

    path = window.start_csv_recording_active()
    assert isinstance(path, Path)
    assert path.parent == tmp_path
    assert window.loggers[state.device_address].is_recording
    assert "CSV recording started" in window.state.log_messages[0]

    stopped_path = window.stop_csv_recording_active()
    assert stopped_path == path
    assert not window.loggers[state.device_address].is_recording
    assert "CSV recording stopped" in window.state.log_messages[0]
    window.close()


def test_demo_engineering_controls_are_hidden_by_default():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication

    from app.windows.main_window import MainWindow

    app = QApplication.instance() or QApplication([])
    window = MainWindow()

    assert window.demo2_page.engineering_controls.isHidden()
    window.close()


def test_demo_engineering_controls_can_be_enabled():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication

    from app.windows.main_window import MainWindow

    app = QApplication.instance() or QApplication([])
    window = MainWindow(engineering_mode=True)

    assert not window.demo2_page.engineering_controls.isHidden()
    window.close()


def test_demo_page_uses_image_logo():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication

    from app.windows.demo2_page import Demo2Page

    app = QApplication.instance() or QApplication([])
    page = Demo2Page()

    assert page.logo_label.pixmap() is not None
    assert not page.logo_label.pixmap().isNull()
    assert page.logo_label.pixmap().height() == 48


def test_demo_showcase_mode_can_open_and_cancel():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication

    from app.windows.demo2_page import Demo2Page

    app = QApplication.instance() or QApplication([])
    page = Demo2Page()

    page._open_showcase()
    assert page._showcase_dialog is not None
    assert page._showcase_dialog.stage is not None
    assert page._showcase_dialog.logo_label.pixmap() is not None
    assert page._showcase_dialog.logo_label.pixmap().height() == 64

    page._showcase_dialog.reject()
    assert page._showcase_dialog is None


def test_demo_showcase_entries_use_connected_states():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication

    from app.models import DeviceState
    from app.windows.demo2_page import Demo2Page

    app = QApplication.instance() or QApplication([])
    page = Demo2Page(demo_use_fake_data=True)
    first = DeviceState(device_name="GIOS0801ST#45", device_address="AA:BB", device_number=45)
    second = DeviceState(device_name="GIOS0801ST#60", device_address="CC:DD", device_number=60)

    page.set_showcase_states({first.device_address: first, second.device_address: second}, first.device_address)

    assert page._showcase_entries() == [("AA:BB", "MMEU  #45"), ("CC:DD", "MMEU  #60")]


def test_demo_multi_showcase_dialog_builds_quad_tiles():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication

    from app.models import DeviceState
    from app.windows.demo2_page import Demo2Page

    app = QApplication.instance() or QApplication([])
    page = Demo2Page(demo_use_fake_data=True)
    states = {
        "A": DeviceState(device_name="GIOS0801ST#45", device_address="A", device_number=45, pru_type_string="0403V1", pru_reg_item_state=4, pru_dyn_vout=5097, pru_dyn_iout=1200),
        "B": DeviceState(device_name="GIOS0801ST#60", device_address="B", device_number=60, pru_type_string="0404V1", pru_reg_item_state=4, pru_dyn_vout=3970, pru_dyn_iout=1200),
        "C": DeviceState(device_name="GIOS0801ST#69", device_address="C", device_number=69, pru_type_string="0403V1", pru_reg_item_state=4, pru_dyn_vout=5097, pru_dyn_iout=1200),
    }
    page.set_showcase_states(states, "A")

    page._open_multi_showcase(["A", "B", "C"], "quad")

    assert page._showcase_dialog is not None
    assert len(page._showcase_dialog.tiles) == 3
    assert page._showcase_dialog.tiles["A"].device_label.text() == "MMEU  #45"
    assert page._showcase_dialog.tiles["B"].device_label.text() == "MMEU  #60"
    assert page._showcase_dialog.tiles["A"].pct_label.text() == "76%"
    assert page._showcase_dialog.tiles["B"].pct_label.text() == "81%"

    page._showcase_dialog.reject()


def test_demo_multi_showcase_uses_per_device_fake_battery_values():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication

    from app.models import DeviceState
    from app.windows.demo2_page import Demo2Page

    app = QApplication.instance() or QApplication([])
    page = Demo2Page(
        demo_use_fake_data=True,
        demo_ebike_pct=76,
        demo_device_battery_pcts={"A": 72, "B": 84},
    )
    states = {
        "A": DeviceState(
            device_name="GIOS0801ST#4",
            device_address="A",
            device_number=4,
            pru_type_string="0403V1",
            pru_reg_item_state=4,
            pru_dyn_vout=5097,
            pru_dyn_iout=1200,
        ),
        "B": DeviceState(
            device_name="GIOS0801ST#6",
            device_address="B",
            device_number=6,
            pru_type_string="0403V1",
            pru_reg_item_state=4,
            pru_dyn_vout=5097,
            pru_dyn_iout=1200,
        ),
    }
    page.set_showcase_states(states, "A")

    page._open_multi_showcase(["A", "B"], "split")

    assert page._showcase_dialog is not None
    assert page._showcase_dialog.tiles["A"].pct_label.text() == "72%"
    assert page._showcase_dialog.tiles["B"].pct_label.text() == "84%"

    page._showcase_dialog.reject()


def test_demo_showcase_chooser_selects_first_four_by_default():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication

    from app.windows.demo2_page import _ShowcaseChooserDialog

    app = QApplication.instance() or QApplication([])
    entries = [(str(index), f"PTU #{index}") for index in range(1, 6)]
    dialog = _ShowcaseChooserDialog(entries)

    assert dialog.selected_addresses() == ["1", "2", "3", "4"]
    assert dialog.selected_layout_mode() == "auto"


def test_settings_toggle_controls_demo_engineering_mode():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication

    from app.windows.main_window import MainWindow

    app = QApplication.instance() or QApplication([])
    window = MainWindow()

    assert window.demo2_page.engineering_controls.isHidden()
    window.set_engineering_mode(True)
    assert not window.demo2_page.engineering_controls.isHidden()
    window.set_engineering_mode(False)
    assert window.demo2_page.engineering_controls.isHidden()
    window.close()


def test_settings_dialog_shows_version_and_engineering_toggle():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication, QLabel

    from app.constants import APP_VERSION
    from app.windows.settings_dialog import SettingsDialog

    app = QApplication.instance() or QApplication([])
    dialog = SettingsDialog(engineering_mode=True)
    labels = [label.text() for label in dialog.findChildren(QLabel)]

    assert APP_VERSION in labels
    assert dialog.engineering_box.isChecked()


def test_settings_dialog_has_demo_defaults():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication

    from app.windows.settings_dialog import SettingsDialog

    app = QApplication.instance() or QApplication([])
    dialog = SettingsDialog(engineering_mode=False)

    assert dialog.demo_fake_data_box.isChecked()
    assert dialog.demo_device_name_edit.text() == "MMEU"
    assert dialog.demo_ebike_spin.value() == 76
    assert dialog.demo_escooter_spin.value() == 81


def test_settings_dialog_shows_connected_device_fake_battery_controls():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication

    from app.windows.settings_dialog import SettingsDialog

    app = QApplication.instance() or QApplication([])
    dialog = SettingsDialog(
        engineering_mode=False,
        demo_device_battery_pcts={"A": 72},
        connected_demo_devices=[
            {"address": "A", "label": "MMEU #4", "default_pct": 76},
            {"address": "B", "label": "MMEU #6", "default_pct": 76},
        ],
    )

    assert dialog.demo_device_pct_spins["A"].value() == 72
    assert dialog.demo_device_pct_spins["B"].value() == 76


def test_main_window_builds_connected_demo_device_fake_battery_settings():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication

    from app.models import DeviceState
    from app.windows.main_window import MainWindow

    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    first = DeviceState(
        is_connected=True,
        device_name="GIOS0403ST#4",
        device_address="A",
        device_number=4,
        pru_type_string="0403V1",
    )
    second = DeviceState(
        is_connected=True,
        device_name="GIOS0404ST#6",
        device_address="B",
        device_number=6,
        pru_type_string="0404V1",
    )
    window.states[first.device_address] = first
    window.states[second.device_address] = second

    assert window._connected_demo_device_settings() == [
        {"address": "A", "label": "MMEU #4", "default_pct": 76},
        {"address": "B", "label": "MMEU #6", "default_pct": 81},
    ]
    window.close()


def test_demo_fake_battery_percent_overrides_charging_values():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication

    from app.windows.demo2_page import Demo2Page, EngMode

    app = QApplication.instance() or QApplication([])
    page = Demo2Page(
        engineering_mode=True,
        demo_use_fake_data=True,
        demo_ebike_pct=76,
        demo_escooter_pct=81,
    )

    page._set_eng_mode(EngMode.CHARGING_BIKE)
    assert page.pct_label.text() == "76%"

    page._set_eng_mode(EngMode.CHARGING_SCOOTER)
    assert page.pct_label.text() == "81%"


def test_demo_battery_panel_shows_device_name_and_number():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication

    from app.models import DeviceState
    from app.windows.demo2_page import Demo2Page

    app = QApplication.instance() or QApplication([])
    page = Demo2Page(demo_use_fake_data=False)
    state = DeviceState(
        device_name="GIOS0801ST#45",
        device_number=45,
        pru_type_string="0403V1",
        pru_reg_item_state=4,
        pru_dyn_vout=5097,
        pru_dyn_iout=1200,
    )

    page.refresh(state)

    assert page.device_label.text() == "GIOS0801ST  #45"


def test_demo_fake_device_name_can_be_customized():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication

    from app.windows.demo2_page import Demo2Page, EngMode

    app = QApplication.instance() or QApplication([])
    page = Demo2Page(engineering_mode=True, demo_use_fake_data=True, demo_device_name="SHOW", demo_ebike_pct=76)

    page.set_preview_device("GIOS0801ST#45", 45)
    page._set_eng_mode(EngMode.CHARGING_BIKE)

    assert page.device_label.text() == "SHOW  #45"


def test_demo_fake_name_uses_number_parsed_from_real_name():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication

    from app.models import DeviceState
    from app.windows.demo2_page import Demo2Page

    app = QApplication.instance() or QApplication([])
    page = Demo2Page(demo_use_fake_data=True)
    state = DeviceState(
        device_name="GIOS0801ST#45",
        device_number=None,
        pru_type_string="0403V1",
        pru_reg_item_state=4,
        pru_dyn_vout=5097,
        pru_dyn_iout=1200,
    )

    page.refresh(state)

    assert page.device_label.text() == "MMEU  #45"


def test_demo_real_name_uses_number_parsed_from_real_name():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication

    from app.models import DeviceState
    from app.windows.demo2_page import Demo2Page

    app = QApplication.instance() or QApplication([])
    page = Demo2Page(demo_use_fake_data=False)
    state = DeviceState(
        device_name="GIOS0801ST#45",
        device_number=None,
        pru_type_string="0403V1",
        pru_reg_item_state=4,
        pru_dyn_vout=5097,
        pru_dyn_iout=1200,
    )

    page.refresh(state)

    assert page.device_label.text() == "GIOS0801ST  #45"


def test_demo_battery_panel_uses_selected_preview_device_when_not_connected():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication

    from app.windows.demo2_page import Demo2Page, EngMode

    app = QApplication.instance() or QApplication([])
    page = Demo2Page(engineering_mode=True, demo_use_fake_data=True, demo_ebike_pct=76)

    page.set_preview_device("GIOS0801ST#45", 45)
    page._set_eng_mode(EngMode.CHARGING_BIKE)

    assert page.device_label.text() == "MMEU  #45"


def test_demo_device_name_label_is_readable():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication

    from app.windows.demo2_page import Demo2Page, EngMode

    app = QApplication.instance() or QApplication([])
    page = Demo2Page(engineering_mode=True, demo_use_fake_data=True)

    page.set_preview_device("GIOS0801ST#45", None)
    page._set_eng_mode(EngMode.CHARGING_BIKE)

    assert page.device_label.minimumHeight() >= 24
    assert "font-size: 16px" in page.device_label.styleSheet()


def test_main_window_selected_scan_device_updates_demo_card():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication

    from app.ble_manager import DeviceScanResult
    from app.windows.demo2_page import EngMode
    from app.windows.main_window import MainWindow

    app = QApplication.instance() or QApplication([])
    window = MainWindow(engineering_mode=True)
    result = DeviceScanResult(
        address="90:04:22:B6:96:00",
        name="GIOS0801ST#45",
        rssi=-60,
        raw_hex="",
        advertising_rows=[],
        device_number=45,
        firmware_revision=None,
    )

    window._set_demo_preview_device(result)
    window.demo2_page._set_eng_mode(EngMode.CHARGING_BIKE)

    assert window.demo2_page.device_label.text() == "MMEU  #45"
    window.close()


def test_demo_showcase_battery_icon_uses_flash_animation():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication

    from app.windows.demo2_page import Demo2Page, EngMode

    app = QApplication.instance() or QApplication([])
    page = Demo2Page(engineering_mode=True, demo_use_fake_data=True, demo_ebike_pct=76)

    page._set_eng_mode(EngMode.CHARGING_BIKE)
    page._open_showcase()
    assert page._showcase_dialog is not None
    assert page._showcase_dialog.pct_label.text() == "76%"
    assert page._showcase_dialog.battery_icon._pct == 75

    page._toggle_flash()
    assert page._showcase_dialog.battery_icon._pct == 100

    page._showcase_dialog.reject()


def test_demo_showcase_panel_shows_device_name_and_number():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication

    from app.models import DeviceState
    from app.windows.demo2_page import Demo2Page

    app = QApplication.instance() or QApplication([])
    page = Demo2Page(demo_use_fake_data=False)
    state = DeviceState(
        device_name="GIOS0801ST#45",
        device_number=45,
        pru_type_string="0403V1",
        pru_reg_item_state=4,
        pru_dyn_vout=5097,
        pru_dyn_iout=1200,
    )

    page.refresh(state)
    page._open_showcase()
    assert page._showcase_dialog is not None

    assert page._showcase_dialog.device_label.text() == "GIOS0801ST  #45"

    page._showcase_dialog.reject()


def test_demo_percent_label_has_room_for_large_text():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication

    from app.windows.demo2_page import Demo2Page, EngMode

    app = QApplication.instance() or QApplication([])
    page = Demo2Page(engineering_mode=True, demo_use_fake_data=True, demo_ebike_pct=76)

    page._set_eng_mode(EngMode.CHARGING_BIKE)

    assert page.pct_label.minimumHeight() >= 48
    assert page.panel.height() >= 132


def test_demo_showcase_percent_label_has_room_for_large_text():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication

    from app.windows.demo2_page import Demo2Page, EngMode

    app = QApplication.instance() or QApplication([])
    page = Demo2Page(engineering_mode=True, demo_use_fake_data=True, demo_ebike_pct=76)

    page._set_eng_mode(EngMode.CHARGING_BIKE)
    page._open_showcase()
    assert page._showcase_dialog is not None
    page._showcase_dialog.showNormal()
    page._showcase_dialog.resize(2048, 1080)
    app.processEvents()

    dialog = page._showcase_dialog
    pct_px = int(dialog.pct_label.styleSheet().split("font-size: ")[1].split("px")[0])
    assert dialog.pct_label.minimumHeight() >= int(pct_px * 1.5)
    assert dialog.panel.height() >= 198

    page._showcase_dialog.reject()


def test_demo_showcase_keeps_battery_panel_left_of_stage():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication

    from app.windows.demo2_page import Demo2Page, EngMode

    app = QApplication.instance() or QApplication([])
    page = Demo2Page(engineering_mode=True, demo_use_fake_data=True, demo_ebike_pct=76)

    page._set_eng_mode(EngMode.CHARGING_BIKE)
    page._open_showcase()
    assert page._showcase_dialog is not None
    page._showcase_dialog.showNormal()
    page._showcase_dialog.resize(2048, 1080)
    app.processEvents()

    dialog = page._showcase_dialog
    panel_right = dialog.panel.mapTo(dialog, dialog.panel.rect().topRight()).x()
    stage_left = dialog.stage.mapTo(dialog, dialog.stage.rect().topLeft()).x()
    assert panel_right < stage_left

    page._showcase_dialog.reject()


def test_demo_showcase_uses_readable_but_secondary_battery_panel():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication

    from app.windows.demo2_page import Demo2Page, EngMode

    app = QApplication.instance() or QApplication([])
    page = Demo2Page(engineering_mode=True, demo_use_fake_data=True, demo_ebike_pct=76)

    page._set_eng_mode(EngMode.CHARGING_BIKE)
    page._open_showcase()
    assert page._showcase_dialog is not None
    page._showcase_dialog.showNormal()
    page._showcase_dialog.resize(2048, 1080)
    app.processEvents()

    dialog = page._showcase_dialog
    assert 480 <= dialog.panel.width() <= 560
    assert 190 <= dialog.panel.height() <= 245
    assert dialog.battery_icon.width() >= 65
    assert "font-size: 7" in dialog.pct_label.styleSheet()
    assert dialog.stage.width() > dialog.left_rail.width() * 2

    page._showcase_dialog.reject()


def test_demo_real_battery_percent_uses_snapshot_values():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication

    from app.windows.demo2_page import Demo2Page, EngMode

    app = QApplication.instance() or QApplication([])
    page = Demo2Page(engineering_mode=True, demo_use_fake_data=False)

    page._set_eng_mode(EngMode.CHARGING_BIKE)
    assert page.pct_label.text() == "65%"

    page._set_eng_mode(EngMode.CHARGING_SCOOTER)
    assert page.pct_label.text() == "60%"


def test_main_window_demo_settings_update_demo_page():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication

    from app.windows.demo2_page import EngMode
    from app.windows.main_window import MainWindow

    app = QApplication.instance() or QApplication([])
    window = MainWindow(engineering_mode=True)

    window.set_demo_settings(True, 77, 82, "MMEU")
    window.demo2_page._set_eng_mode(EngMode.CHARGING_BIKE)
    assert window.demo2_page.pct_label.text() == "77%"

    window.demo2_page._set_eng_mode(EngMode.CHARGING_SCOOTER)
    assert window.demo2_page.pct_label.text() == "82%"
    window.close()


def test_pru_connected_event_does_not_auto_start_csv_recording(tmp_path):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication

    from app.models import DataEvent
    from app.csv_logger import CsvLogger
    from app.models import DeviceState
    from app.windows.main_window import MainWindow

    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    state = DeviceState(is_connected=True, device_name="Bike", device_address="AA:BB")
    window.states[state.device_address] = state
    window.loggers[state.device_address] = CsvLogger(tmp_path)
    window.active_address = state.device_address
    window.state = state

    window._handle_event(DataEvent("pru_connected", "PRU connected", 10))

    assert not window.loggers[state.device_address].is_recording
    assert not list(tmp_path.glob("*.csv"))
    window.close()


def test_main_window_error_event_uses_event_device_state(tmp_path):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication

    from app.models import DataEvent, DeviceState
    from app.windows.main_window import MainWindow

    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    active = DeviceState(is_connected=True, device_name="Active", device_address="AA:BB")
    other = DeviceState(is_connected=True, device_name="Other", device_address="CC:DD", error_num=0x11)
    window.states[active.device_address] = active
    window.states[other.device_address] = other
    window.active_address = active.device_address
    window.state = active
    shown: list[str] = []
    window._show_error_dialog = lambda state: shown.append(state.device_address)

    window._handle_event(DataEvent("error", "error", 0x11), other)

    assert shown == [other.device_address]
    window.close()


def test_waveform_page_keeps_rolling_scope_window():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication

    from app.models import DeviceState
    from app.windows.waveform_page import WaveformPage

    app = QApplication.instance() or QApplication([])
    page = WaveformPage()
    page.history_combo.setCurrentIndex(0)
    page.add_chart()

    state = DeviceState(is_connected=True, ptu_input_voltage=53000)
    for index in range(600):
        state.ptu_input_voltage = 53000 + index
        page.refresh(state)

    chart = page.charts[0]
    assert page.history_combo.currentData() == 500
    assert len(chart.x) == 500
    assert chart.y[-1] == 53599
    assert "samples 500" in chart.stats_label.text()


def test_waveform_page_has_no_device_selector_inside_waveform_controls():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication

    from app.windows.waveform_page import WaveformPage

    app = QApplication.instance() or QApplication([])
    page = WaveformPage()

    assert not hasattr(page, "device_combo")


def test_waveform_page_follows_active_device_tabs_and_preserves_device_history():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication

    from app.models import DeviceState
    from app.windows.waveform_page import WaveformPage

    app = QApplication.instance() or QApplication([])
    page = WaveformPage()
    page.add_chart()
    first = DeviceState(is_connected=True, device_name="PTU A", device_address="A", device_number=6, ptu_input_voltage=52000)
    second = DeviceState(is_connected=True, device_name="PTU B", device_address="B", device_number=10, ptu_input_voltage=54000)
    states = {first.device_address: first, second.device_address: second}
    page.set_devices(states, first.device_address)
    page.refresh_device(first, states, first.device_address)
    page.refresh_device(second, states, first.device_address)

    chart = page.charts[0]
    assert chart.series[first.device_address].y == [52000.0]
    assert chart.series[second.device_address].y == [54000.0]
    assert chart.x == [0.0]
    assert chart.y == [52000.0]
    assert "PTU #6" in chart.stats_label.text()
    assert "PTU #10" not in chart.stats_label.text()

    page.set_devices(states, second.device_address)

    assert chart.x == [0.0]
    assert chart.y == [54000.0]
    assert "PTU #6" not in chart.stats_label.text()
    assert "PTU #10" in chart.stats_label.text()


def test_waveform_page_can_overlay_all_connected_devices_in_one_chart():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication

    from app.models import DeviceState
    from app.windows.waveform_page import WaveformPage

    app = QApplication.instance() or QApplication([])
    page = WaveformPage()
    page.add_chart()
    first = DeviceState(is_connected=True, device_name="PTU A", device_address="A", device_number=6, ptu_input_voltage=52000)
    second = DeviceState(is_connected=True, device_name="PTU B", device_address="B", device_number=10, ptu_input_voltage=54000)
    states = {first.device_address: first, second.device_address: second}
    page.set_devices(states, first.device_address)
    page.refresh_device(first, states, first.device_address)
    page.refresh_device(second, states, first.device_address)

    chart = page.charts[0]
    assert chart.plot.plotItem.legend is not None
    assert page.scope_combo.currentData() == "current"
    assert chart.series[first.device_address].curve.isVisible()
    assert not chart.series[second.device_address].curve.isVisible()

    all_index = page.scope_combo.findData("all")
    assert all_index >= 0
    page.scope_combo.setCurrentIndex(all_index)

    assert chart.series[first.device_address].curve.isVisible()
    assert chart.series[second.device_address].curve.isVisible()
    assert "PTU #6" in chart.stats_label.text()
    assert "PTU #10" in chart.stats_label.text()


def test_waveform_page_preserves_last_waveform_when_device_disconnects():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication

    from app.models import DeviceState
    from app.windows.waveform_page import WaveformPage

    app = QApplication.instance() or QApplication([])
    page = WaveformPage()
    page.add_chart()
    state = DeviceState(is_connected=True, device_name="PTU A", device_address="A", device_number=6, ptu_input_voltage=52000)
    page.set_devices({state.device_address: state}, state.device_address)
    page.refresh_device(state, {state.device_address: state}, state.device_address)

    chart = page.charts[0]
    assert chart.y == [52000.0]
    assert chart.series[state.device_address].curve.isVisible()

    state.is_connected = False
    page.set_devices({}, "")

    assert chart.y == [52000.0]
    assert chart.series[state.device_address].curve.isVisible()
    assert "PTU #6" in chart.stats_label.text()
    assert "samples 1" in chart.stats_label.text()


def test_waveform_page_preserves_overlay_when_all_devices_disconnect():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication

    from app.models import DeviceState
    from app.windows.waveform_page import WaveformPage

    app = QApplication.instance() or QApplication([])
    page = WaveformPage()
    page.add_chart()
    first = DeviceState(is_connected=True, device_name="PTU A", device_address="A", device_number=6, ptu_input_voltage=52000)
    second = DeviceState(is_connected=True, device_name="PTU B", device_address="B", device_number=10, ptu_input_voltage=54000)
    states = {first.device_address: first, second.device_address: second}
    page.set_devices(states, first.device_address)
    page.refresh_device(first, states, first.device_address)
    page.refresh_device(second, states, first.device_address)
    page.scope_combo.setCurrentIndex(page.scope_combo.findData("all"))

    chart = page.charts[0]
    assert chart.series[first.device_address].curve.isVisible()
    assert chart.series[second.device_address].curve.isVisible()

    page.set_devices({}, "")

    assert chart.series[first.device_address].curve.isVisible()
    assert chart.series[second.device_address].curve.isVisible()
    assert "PTU #6" in chart.stats_label.text()
    assert "PTU #10" in chart.stats_label.text()


def test_waveform_page_saves_chart_image_from_chart_button(monkeypatch, tmp_path):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication

    import app.windows.waveform_page as waveform_module
    from app.windows.waveform_page import WaveformPage

    app = QApplication.instance() or QApplication([])
    page = WaveformPage()
    page.add_chart()
    chart = page.charts[0]
    target = tmp_path / "waveform.png"
    exported = {}

    class FakeImageExporter:
        def __init__(self, plot_item):
            exported["plot_item"] = plot_item

        def export(self, filename):
            exported["filename"] = filename
            Path(filename).write_bytes(b"png")

    monkeypatch.setattr(waveform_module, "ImageExporter", FakeImageExporter)
    monkeypatch.setattr(
        waveform_module.QFileDialog,
        "getSaveFileName",
        lambda *args, **kwargs: (str(target), "PNG Files (*.png)"),
    )

    chart.save_button.click()

    assert chart.save_button.text() == "儲存圖片"
    assert exported["plot_item"] is chart.plot.plotItem
    assert exported["filename"] == str(target)
    assert target.read_bytes() == b"png"


def test_main_window_waveform_stores_non_active_device_and_shows_it_when_tab_becomes_active(monkeypatch):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication

    import app.windows.main_window as main_window
    from app.models import DeviceState
    from app.windows.main_window import MainWindow

    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    first = DeviceState(is_connected=True, device_name="GIOS0403ST#6", device_address="A", device_number=6)
    second = DeviceState(is_connected=True, device_name="GIOS0403ST#10", device_address="B", device_number=10)
    window.states[first.device_address] = first
    window.states[second.device_address] = second
    window.active_address = first.device_address
    window.state = first
    window.waveform_page.add_chart()
    window.waveform_page.set_devices(window.states, window.active_address)

    def fake_parse(_data: bytes, _uuid: str, state: DeviceState):
        state.ptu_input_voltage = 54123
        return None

    monkeypatch.setattr(main_window, "parse_notify_packet", fake_parse)

    window._handle_notify(second.device_address, "uuid", b"packet")

    chart = window.waveform_page.charts[0]
    assert chart.series[second.device_address].y == [54123.0]
    assert chart.y == []

    window._set_active(second.device_address)

    assert chart.y == [54123.0]
    assert "PTU #10" in chart.stats_label.text()
    window.close()
