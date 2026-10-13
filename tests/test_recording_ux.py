from __future__ import annotations

import csv
import os
from datetime import datetime

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QSettings
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QFileDialog

from app.csv_logger import CsvLogger
from app.models import DeviceState
from app.windows.main_window import MainWindow, RECORD_DIRECTORY_SETTINGS_KEY


@pytest.fixture
def window(tmp_path):
    app = QApplication.instance() or QApplication([])
    previous_identity = app.organizationName(), app.applicationName()
    previous_format = QSettings.defaultFormat()
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path / "settings"))
    app.setOrganizationName("RecordingUxTest")
    app.setApplicationName("RecordingUxTest")
    widget = MainWindow()
    widget.log_dir = tmp_path
    state = DeviceState(device_address="AA:BB", device_name="Debug PTU", is_connected=True, ptu_input_voltage=12000)
    widget.states[state.device_address] = state
    widget.loggers[state.device_address] = CsvLogger(tmp_path)
    widget.active_address = state.device_address
    widget.state = state
    widget.refresh_pages()
    yield widget
    widget._close_after_disconnect = True
    widget.close()
    widget.deleteLater()
    app.processEvents()
    app.setOrganizationName(previous_identity[0])
    app.setApplicationName(previous_identity[1])
    QSettings.setDefaultFormat(previous_format)


def test_csv_success_metrics_span_parts_and_survive_stop(tmp_path):
    logger = CsvLogger(tmp_path)
    logger.start("test", max_rows=2)
    logger.write_state(DeviceState())
    assert logger.rows_written == 0
    state = DeviceState(ptu_input_voltage=10000)
    for _ in range(3):
        logger.write_state(state)
    assert logger.rows_written == 3
    assert logger.parts_created == 2
    assert logger.last_write_at is not None
    assert logger.seconds_since_write is not None
    logger.stop()
    assert logger.rows_written == 3
    assert logger.parts_created == 2
    elapsed = logger.elapsed_seconds
    assert logger.elapsed_seconds == elapsed
    rows = []
    for path in sorted(tmp_path.glob("*.csv")):
        with path.open(encoding="utf-8", newline="") as handle:
            rows.extend(list(csv.reader(handle))[1:])
    assert [row[2] for row in rows] == ["10000"] * 3


def test_csv_same_second_start_never_overwrites_existing_file(tmp_path, monkeypatch):
    import app.csv_logger as module

    class FrozenDateTime:
        @staticmethod
        def now():
            return datetime(2026, 10, 13, 10, 0, 0)

    monkeypatch.setattr(module, "datetime", FrozenDateTime)
    first = CsvLogger(tmp_path)
    first_path = first.start("005")
    first.write_state(DeviceState(ptu_input_voltage=10000))
    first.stop()
    before = first_path.read_bytes()
    second = CsvLogger(tmp_path)
    second_path = second.start("005")
    second.write_state(DeviceState(ptu_input_voltage=20000))
    second.stop()
    assert first_path != second_path
    assert first_path.read_bytes() == before
    assert ",20000," in second_path.read_text(encoding="utf-8")


def test_recording_panel_reports_written_rows_waiting_and_stopped(window):
    path = window.start_csv_recording_active()
    assert path is not None
    assert "等待可寫入資料" in window.recording_panel.status_label.text()
    logger = window._active_logger()
    logger.write_state(window.state)
    window._refresh_recording_status()
    assert "已寫入 1 筆" in window.recording_panel.metrics_label.text()
    assert "錄製中" in window.recording_panel.status_label.text()
    assert window.recording_panel.path_edit.text() == str(path)
    assert not window.recording_panel.choose_button.isEnabled()
    window.state.is_connected = False
    window._refresh_recording_status()
    assert "等待重連" in window.recording_panel.status_label.text()
    assert window.recording_panel.stop_button.isEnabled()
    window.stop_csv_recording_active()
    assert "已停止錄製" in window.recording_panel.status_label.text()
    assert "已寫入 1 筆" in window.recording_panel.metrics_label.text()


def test_notify_coalesces_ui_without_dropping_csv_rows_while_log_paused(window, monkeypatch):
    import app.windows.main_window as module

    monkeypatch.setattr(module, "parse_notify_packet", lambda *_args: None)
    path = window.start_csv_recording_active()
    window.log_page.pause_button.setChecked(True)
    original_tab = window.device_tabs.widget(0)
    refreshes = []
    original_refresh = window.overview_page.refresh

    def refresh(state):
        refreshes.append(state)
        original_refresh(state)

    monkeypatch.setattr(window.overview_page, "refresh", refresh)
    for _ in range(250):
        window._handle_notify(window.active_address, "test", b"data")
    assert window._active_logger().rows_written == 250
    assert refreshes == []
    QTest.qWait(220)
    assert len(refreshes) == 1
    assert window.device_tabs.widget(0) is original_tab
    window.stop_csv_recording_active()
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.reader(handle))
    assert len(rows) == 251
    assert rows[1][2] == rows[125][2] == rows[-1][2] == "12000"


def test_storage_failure_stops_recording_and_stays_visible(window, monkeypatch):
    logger = window._active_logger()
    window.start_csv_recording_active()

    def fail_write(_state):
        raise OSError("Disk full")

    monkeypatch.setattr(logger, "write_state", fail_write)
    window._handle_notify(window.active_address, "test", b"data")
    window.refresh_pages()
    assert not logger.is_recording
    assert "錄製失敗" in window.recording_panel.status_label.text()
    assert "Disk full" in window.recording_panel.summary_label.text()
    assert window.recording_panel.start_button.isEnabled()
    assert window._start_recording(window.active_address) is not None
    assert window._recording_errors == {}
    window.stop_csv_recording_active()


def test_start_failure_and_folder_change_are_recoverable(window, tmp_path, monkeypatch):
    blocked_path = tmp_path / "not_a_directory"
    blocked_path.write_text("existing data", encoding="utf-8")
    window._active_logger().directory = blocked_path
    assert window.start_csv_recording_active() is None
    assert not window._active_logger().is_recording
    assert "錄製失敗" in window.recording_panel.status_label.text()
    selected = tmp_path / "new_records"
    selected.mkdir()
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *_args: str(selected))
    window._choose_log_folder()
    assert window.log_dir == selected
    assert QSettings().value(RECORD_DIRECTORY_SETTINGS_KEY) == str(selected)
    path = window.start_csv_recording_active()
    assert path.parent == selected
    assert blocked_path.read_text(encoding="utf-8") == "existing data"
    window.stop_csv_recording_active()


def test_background_device_recording_failure_is_visible_from_other_device(window):
    window._recording_errors["CC:DD"] = "Disk full"
    window._refresh_recording_status()
    assert "1 台錄製失敗" in window.recording_panel.summary_label.text()
    assert window.recording_panel._severity == "error"
