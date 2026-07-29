import os
from pathlib import Path


def test_source_dialog_checks_for_updates_as_soon_as_it_is_shown(monkeypatch):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication, QDialogButtonBox

    from app.updater import UpdateCheckResult, UpdateStatus
    from app.windows import source_select_dialog as source_dialog_module
    from app.windows.source_select_dialog import SourceSelectDialog

    app = QApplication.instance() or QApplication([])
    workers = []
    monkeypatch.setattr(source_dialog_module, "_start_worker", workers.append)

    dialog = SourceSelectDialog()
    dialog.show()
    app.processEvents()

    ok_button = dialog._buttons.button(QDialogButtonBox.StandardButton.Ok)
    assert len(workers) == 1
    assert dialog._update_check_started
    assert dialog._update_check_running
    assert ok_button is not None and not ok_button.isEnabled()
    assert "正在檢查" in dialog._update_status.text()

    workers[0].signals.completed.emit(
        UpdateCheckResult(UpdateStatus.UP_TO_DATE, message="目前已是最新版本。")
    )
    app.processEvents()

    assert not dialog._update_check_running
    assert ok_button.isEnabled()
    assert dialog._update_status.text() == "目前已是最新版本。"
    dialog.close()


def test_source_dialog_prompts_for_available_update_before_main_window(monkeypatch):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication, QMessageBox

    from app.updater import UpdateAsset, UpdateCheckResult, UpdateInfo, UpdateStatus
    from app.windows.source_select_dialog import SourceSelectDialog

    app = QApplication.instance() or QApplication([])
    dialog = SourceSelectDialog()
    shown: list[tuple[object, str, str]] = []
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda parent, title, body, *_args: (
            shown.append((parent, title, body))
            or QMessageBox.StandardButton.No
        ),
    )
    result = UpdateCheckResult(
        UpdateStatus.UPDATE_AVAILABLE,
        info=UpdateInfo(
            current_version="V1.0.26",
            latest_version="V1.0.27",
            release_url="https://example.test/release",
            asset=UpdateAsset(
                name="PC_GIOSXTR_Demo_V1.0.27.exe",
                download_url="https://example.test/app.exe",
            ),
        ),
    )

    dialog._handle_update_check_result(result)

    assert len(shown) == 1
    parent, title, body = shown[0]
    assert parent is dialog
    assert title == "發現新版"
    assert "V1.0.26" in body
    assert "V1.0.27" in body
    assert "發現新版 V1.0.27" in dialog._update_status.text()
    dialog.close()


def test_main_window_no_longer_owns_automatic_startup_update_check():
    from app.windows.main_window import MainWindow

    assert not hasattr(MainWindow, "_start_automatic_update_check")


def test_downloaded_update_launches_detached_and_closes_old_startup_dialog(monkeypatch):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication, QMessageBox

    from app.windows import source_select_dialog as source_dialog_module
    from app.windows.source_select_dialog import SourceSelectDialog

    app = QApplication.instance() or QApplication([])
    launched: list[Path] = []
    monkeypatch.setattr(
        source_dialog_module,
        "_start_detached_update",
        lambda path: launched.append(path) or True,
    )
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *_args: QMessageBox.StandardButton.Yes,
    )

    dialog = SourceSelectDialog()
    close_requests: list[bool] = []
    monkeypatch.setattr(dialog, "reject", lambda: close_requests.append(True))
    update_path = Path("C:/Users/test/Downloads/PC_GIOSXTR_Demo_V2.0.1.exe")
    dialog._handle_update_downloaded(update_path)

    assert launched == [update_path]
    assert close_requests == [True]
    assert "自動關閉" in dialog._update_status.text()
    dialog.close()
    app.processEvents()


def test_downloaded_update_keeps_old_dialog_open_when_launch_fails(monkeypatch):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication, QMessageBox

    from app.windows import source_select_dialog as source_dialog_module
    from app.windows.source_select_dialog import SourceSelectDialog

    app = QApplication.instance() or QApplication([])
    warnings: list[str] = []
    monkeypatch.setattr(source_dialog_module, "_start_detached_update", lambda _path: False)
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *_args: QMessageBox.StandardButton.Yes,
    )
    monkeypatch.setattr(
        QMessageBox,
        "warning",
        lambda _parent, _title, detail: warnings.append(detail),
    )

    dialog = SourceSelectDialog()
    close_requests: list[bool] = []
    monkeypatch.setattr(dialog, "reject", lambda: close_requests.append(True))
    dialog._handle_update_downloaded(Path("C:/missing/update.exe"))

    assert close_requests == []
    assert warnings == ["無法啟動新版：C:\\missing\\update.exe"]
    assert "無法自動開啟" in dialog._update_status.text()
    dialog.close()
    app.processEvents()
