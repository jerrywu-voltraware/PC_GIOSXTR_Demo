"""Independent reviewer checks. Run with pytest; never touch user settings."""

from concurrent.futures import ThreadPoolExecutor
import csv
from datetime import datetime
import os
from pathlib import Path
import sys
from threading import Barrier

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.csv_logger import CsvLogger
from app.models import DeviceState


class FrozenDatetime(datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 10, 13, 12, 34, 56, tzinfo=tz)


@pytest.fixture
def fixed_clock(monkeypatch):
    monkeypatch.setattr("app.csv_logger.datetime", FrozenDatetime)


def test_sixteen_simultaneous_recordings_never_replace_data(tmp_path, fixed_clock):
    barrier = Barrier(16)

    def write_one(index):
        logger = CsvLogger(tmp_path)
        barrier.wait()
        path = logger.start("same-device")
        state = DeviceState(ptu_input_voltage=10000 + index)
        logger.write_state(state)
        logger.stop()
        return path, state.ptu_input_voltage

    with ThreadPoolExecutor(max_workers=16) as pool:
        results = list(pool.map(write_one, range(16)))
    assert len({path for path, _ in results}) == 16
    for path, voltage in results:
        with path.open(encoding="utf-8", newline="") as handle:
            rows = list(csv.reader(handle))
        assert len(rows) == 2
        assert int(rows[1][2]) == voltage


def test_rollover_collision_preserves_existing_measurements(tmp_path, fixed_clock):
    logger = CsvLogger(tmp_path)
    first = logger.start("same-device", max_rows=1)
    logger.write_state(DeviceState(ptu_input_voltage=11000))
    second = first.with_name(first.name.replace("p001", "p002"))
    second.write_bytes(b"existing measurement\r\n")
    with pytest.raises(FileExistsError):
        logger.write_state(DeviceState(ptu_input_voltage=12000))
    assert second.read_bytes() == b"existing measurement\r\n"
    assert not logger.is_recording
    assert logger.rows_written == 1
    assert logger.parts_created == 1
    logger.stop()


def test_three_known_rows_read_back_across_split_files(tmp_path):
    logger = CsvLogger(tmp_path)
    logger.start("readback", max_rows=2)
    expected = [11111, 22222, 33333]
    for voltage in expected:
        logger.write_state(DeviceState(ptu_input_voltage=voltage))
    logger.stop()
    actual = []
    for path in sorted(tmp_path.glob("*.csv")):
        with path.open(encoding="utf-8", newline="") as handle:
            actual.extend(int(row[2]) for row in list(csv.reader(handle))[1:])
    assert actual == expected
    assert logger.rows_written == 3
    assert logger.parts_created == 2


def test_failed_flush_is_not_counted_and_stop_releases_handle(tmp_path):
    logger = CsvLogger(tmp_path)
    logger.start("failure")
    real_handle = logger._file

    class FailedFlush:
        def flush(self):
            raise OSError("injected disk full")

        def close(self):
            real_handle.close()

    logger._file = FailedFlush()
    with pytest.raises(OSError, match="disk full"):
        logger.write_state(DeviceState(ptu_input_voltage=11000))
    assert logger.rows_written == 0
    assert logger.last_write_at is None
    with pytest.raises(OSError, match="disk full"):
        logger.stop()
    assert real_handle.closed
    assert not logger.is_recording
    assert logger._writer is None


def test_header_flush_failure_closes_file_and_does_not_advertise_recording(tmp_path, monkeypatch):
    real_open = Path.open
    handles = []

    class FailedHeaderFlush:
        def __init__(self, handle):
            self.handle = handle

        def write(self, value):
            return self.handle.write(value)

        def flush(self):
            raise OSError("injected header flush failure")

        def close(self):
            self.handle.close()

    def open_with_bad_flush(path, *args, **kwargs):
        handle = real_open(path, *args, **kwargs)
        handles.append(handle)
        return FailedHeaderFlush(handle)

    monkeypatch.setattr(Path, "open", open_with_bad_flush)
    logger = CsvLogger(tmp_path)
    with pytest.raises(OSError, match="header flush"):
        logger.start("header-failure")
    assert handles and all(handle.closed for handle in handles)
    assert not logger.is_recording
    assert logger.parts_created == 0
    assert logger.current_path is None


@pytest.fixture
def two_device_window(tmp_path, monkeypatch):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtCore import QSettings
    from PyQt6.QtWidgets import QApplication
    from app.recent_devices import RecentDeviceStore
    from app.theme import apply_theme
    from app.windows.main_window import MainWindow

    previous_format = QSettings.defaultFormat()
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    for scope in (QSettings.Scope.UserScope, QSettings.Scope.SystemScope):
        QSettings.setPath(QSettings.Format.IniFormat, scope, str(tmp_path / scope.name))
    app = QApplication.instance() or QApplication([])
    previous_identity = app.organizationName(), app.applicationName()
    app.setOrganizationName("Independent Review")
    app.setApplicationName("Two Device Checks")
    apply_theme(app, "light")
    monkeypatch.setattr("app.windows.main_window.RecentDeviceStore", lambda: RecentDeviceStore(tmp_path / "recent.json"))
    monkeypatch.setattr("app.windows.main_window.parse_notify_packet", lambda *_: None)
    window = MainWindow()
    window.log_dir = tmp_path
    for address, voltage in (("AA:AA", 11000), ("BB:BB", 22000)):
        window.states[address] = DeviceState(device_address=address, device_name=address, is_connected=True, ptu_input_voltage=voltage)
        window.loggers[address] = CsvLogger(tmp_path)
        window.managers[address] = object()
    window._set_active("AA:AA")
    yield window, app
    window._close_after_disconnect = True
    window.close()
    window.deleteLater()
    app.processEvents()
    app.setOrganizationName(previous_identity[0])
    app.setApplicationName(previous_identity[1])
    QSettings.setDefaultFormat(previous_format)


def test_all_recordings_continue_through_selection_pause_and_reconnection(two_device_window, monkeypatch):
    window, app = two_device_window
    window.start_csv_recording_all()
    paths = {address: logger.current_path for address, logger in window.loggers.items()}
    assert all(logger.is_recording for logger in window.loggers.values())
    assert "2 台開啟錄製 / 2 台裝置" in window.recording_panel.summary_label.text()
    window.log_page.pause_button.setChecked(True)
    for address in paths:
        window._handle_notify(address, "test", b"data")
    window._set_active("BB:BB")
    assert not window.log_page.pause_button.isChecked()
    assert window.recording_panel.path_edit.text() == str(paths["BB:BB"])
    assert "已寫入 1 筆" in window.recording_panel.metrics_label.text()
    reconnects = []
    monkeypatch.setattr(window, "_schedule_reconnect", reconnects.append)
    window._handle_disconnect("AA:AA")
    assert reconnects == ["AA:AA"]
    assert window.loggers["AA:AA"].is_recording
    assert "1 台錄製等待重連" in window.recording_panel.summary_label.text()
    window._set_active("AA:AA")
    assert "等待重連" in window.recording_panel.status_label.text()
    window.states["AA:AA"].is_connected = True
    window.managers["AA:AA"] = object()
    for address in paths:
        window._handle_notify(address, "test", b"data")
    window.stop_csv_recording_all()
    for address, path in paths.items():
        assert window.loggers[address].rows_written == 2
        assert window.loggers[address].current_path == path
        with path.open(encoding="utf-8", newline="") as handle:
            rows = list(csv.reader(handle))
        assert len(rows) == 3
        assert [int(row[2]) for row in rows[1:]] == [window.states[address].ptu_input_voltage] * 2


def test_one_recording_failure_does_not_stop_other_device(two_device_window, monkeypatch):
    window, app = two_device_window
    window.start_csv_recording_all()
    first, second = window.loggers.values()
    second_path = second.current_path
    window._set_active("BB:BB")

    def disk_full(_state):
        raise OSError("review disk full")

    monkeypatch.setattr(first, "write_state", disk_full)
    window._handle_notify("AA:AA", "test", b"data")
    window._handle_notify("BB:BB", "test", b"data")
    window.refresh_pages()
    assert not first.is_recording
    assert second.is_recording and second.rows_written == 1
    assert "review disk full" in window.recording_panel.summary_label.text()
    assert "AA:AA" in window.recording_panel.summary_label.text()
    assert window.recording_panel._severity == "error"
    assert window.recording_panel.stop_button.isEnabled()
    assert not window.recording_panel.choose_button.isEnabled()
    assert window._start_recording("AA:AA") is not None
    assert window._recording_errors == {}
    assert second.current_path == second_path


def test_folder_selection_is_blocked_by_background_recording(two_device_window, tmp_path, monkeypatch):
    from PyQt6.QtWidgets import QFileDialog

    window, app = two_device_window
    window._start_recording("BB:BB")
    calls = []
    chosen = tmp_path / "chosen"
    chosen.mkdir()

    def select_folder(*_):
        calls.append(True)
        return str(chosen)

    monkeypatch.setattr(QFileDialog, "getExistingDirectory", select_folder)
    window._choose_log_folder()
    assert not calls
    assert window.log_dir == tmp_path
    window.stop_csv_recording_all()
    window._choose_log_folder()
    assert calls == [True]
    assert window.log_dir == chosen
    assert all(logger.directory == chosen for logger in window.loggers.values())
    assert window.recording_panel.path_edit.text() == str(chosen)


def test_manual_disconnect_flush_failure_remains_visible(two_device_window):
    window, app = two_device_window
    window.start_csv_recording_active()
    logger = window.loggers["AA:AA"]
    handle = logger._file

    class FailedFlush:
        def flush(self):
            raise OSError("review close disk full")

        def close(self):
            handle.close()

    logger._file = FailedFlush()
    window._cleanup_address("AA:AA")
    assert handle.closed
    assert "AA:AA" not in window.states
    assert window.active_address == "BB:BB"
    assert "review close disk full" in window.recording_panel.summary_label.text()
    assert window.recording_panel._severity == "error"


def test_existing_waveform_legend_updates_rendered_point_size(two_device_window):
    from app.typography import typography_manager

    window, app = two_device_window
    manager = typography_manager()
    manager.set_scale(100, persist=False)
    page = window.waveform_page
    page.add_chart()
    page.refresh_device(window.state, window.states, window.active_address)
    legend = page.charts[0].plot.plotItem.legend
    axes = [page.charts[0].plot.getAxis(name) for name in ("bottom", "left")]
    labels = [axis.labelText for axis in axes]
    assert legend.items
    assert labels[0] == "Sample"
    assert labels[1]
    try:
        manager.set_scale(200, persist=False)
        app.processEvents()
        for _, label in legend.items:
            fragment = label.item.document().begin().begin().fragment()
            assert fragment.charFormat().fontPointSize() == 22
        assert [axis.labelText for axis in axes] == labels
        assert all(axis.label.isVisible() for axis in axes)
    finally:
        manager.set_scale(100, persist=False)
