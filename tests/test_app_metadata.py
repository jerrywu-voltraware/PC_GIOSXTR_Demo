import os
from pathlib import Path


def test_app_metadata_uses_requested_version_and_icon():
    from app.constants import APP_ICON_FILENAME, APP_NAME, APP_VERSION, APP_WINDOW_TITLE
    from app.resources import resource_path

    icon_path = resource_path(APP_ICON_FILENAME)

    assert APP_NAME == "PC GIOSXTR Demo"
    assert APP_VERSION == "V1.0.24"
    assert APP_WINDOW_TITLE == "PC GIOSXTR Demo V1.0.24"
    assert APP_ICON_FILENAME == "1024.png"
    assert icon_path.exists()


def test_main_window_uses_versioned_title_and_icon():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication

    from app.constants import APP_WINDOW_TITLE
    from app.windows.main_window import MainWindow

    app = QApplication.instance() or QApplication([])
    window = MainWindow()

    assert window.windowTitle() == APP_WINDOW_TITLE
    assert not window.windowIcon().isNull()
    window.close()


def test_pyinstaller_spec_uses_versioned_exe_icon_and_version_info():
    spec = Path("PC_GIOSXTR_Demo.spec").read_text(encoding="utf-8")
    version_info = Path("version_info.txt").read_text(encoding="utf-8")

    assert "collect_submodules" in spec
    assert 'collect_submodules("numpy._core")' in spec
    assert 'collect_submodules("winrt")' in spec
    assert '("1024.png", ".")' in spec
    assert 'name="PC_GIOSXTR_Demo_V1.0.24"' in spec
    assert 'icon="app_icon.ico"' in spec
    assert 'version="version_info.txt"' in spec
    assert Path("app_icon.ico").exists()
    assert "filevers=(1, 0, 24, 0)" in version_info
    assert "StringStruct('FileVersion', 'V1.0.24')" in version_info
    assert "StringStruct('ProductVersion', 'V1.0.24')" in version_info


def test_settings_dialog_exposes_manual_update_check_button():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication, QPushButton

    from app.windows.settings_dialog import SettingsDialog

    app = QApplication.instance() or QApplication([])
    dialog = SettingsDialog(
        engineering_mode=False,
        demo_use_fake_data=True,
        demo_device_name="MMEU",
        demo_ebike_pct=76,
        demo_escooter_pct=81,
    )
    emitted: list[bool] = []
    dialog.check_updates_requested.connect(lambda: emitted.append(True))

    buttons = dialog.findChildren(QPushButton)
    update_buttons = [button for button in buttons if "檢查更新" in button.text()]

    assert update_buttons
    update_buttons[0].click()
    assert emitted == [True]
    dialog.close()
