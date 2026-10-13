from __future__ import annotations

import csv
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from app.models import DeviceState
from app.windows.log_page import LogPage


@pytest.fixture(scope="module")
def qt_application():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def page(qt_application):
    widget = LogPage()
    yield widget
    widget.close()
    widget.deleteLater()
    qt_application.processEvents()


def _wait_for_refresh():
    QTest.qWait(LogPage.REFRESH_INTERVAL_MS + 60)


def test_search_and_severity_filters_combine_without_changing_source(page):
    state = DeviceState(log_messages=[
        "12:00:04  ERROR: USB failed",
        "12:00:03  Warning: BLE skipped",
        "12:00:02  Connected USB",
        "12:00:01  裝置錯誤：過熱",
    ])
    original = list(state.log_messages)
    page.refresh(state)
    assert page.text.toPlainText().splitlines() == original
    page.search_input.setText("uSb")
    assert page.text.toPlainText().splitlines() == [original[0], original[2]]
    page.level_filter.setCurrentIndex(1)
    assert page.text.toPlainText() == original[0]
    page.search_input.clear()
    assert len(page.text.toPlainText().splitlines()) == 3
    page.level_filter.setCurrentIndex(2)
    assert page.text.toPlainText().splitlines() == [original[0], original[3]]
    assert state.log_messages == original
    assert "顯示 2 / 4 筆" in page.status_label.text()


def test_pause_and_clear_keep_csv_and_persistent_events_recording(page, tmp_path):
    from app.batch_log import disable_batch_log_file, initialize_batch_log
    from app.csv_logger import CsvLogger

    batch_path = tmp_path / "batch.txt"
    initialize_batch_log(batch_path)
    logger = CsvLogger(tmp_path)
    path = logger.start("log-view-test")
    try:
        state = DeviceState(ptu_input_voltage=10000)
        state.add_log("first event")
        logger.write_state(state)
        page.refresh(state)
        frozen = page.text.toPlainText()
        page.pause_button.click()
        state.add_log("second event")
        logger.write_state(state)
        page.refresh(state)
        _wait_for_refresh()
        assert page.text.toPlainText() == frozen
        assert "已暫停畫面" in page.status_label.text()
        assert "second event" in batch_path.read_text(encoding="utf-8")
        with path.open(encoding="utf-8", newline="") as handle:
            rows = list(csv.reader(handle))
        assert len(rows) == 3
        assert rows[1][2] == rows[2][2] == "10000"

        page.pause_button.click()
        assert "second event" in page.text.toPlainText()
        source_before_clear = list(state.log_messages)
        file_before_clear = batch_path.read_bytes()
        page.clear()
        assert page.text.toPlainText() == ""
        assert state.log_messages == source_before_clear
        assert batch_path.read_bytes() == file_before_clear
        state.add_log("third event")
        logger.write_state(state)
        page.refresh(state)
        _wait_for_refresh()
        assert "third event" in page.text.toPlainText()
        assert "second event" not in page.text.toPlainText()
        assert len(path.read_text(encoding="utf-8").splitlines()) == 4
    finally:
        logger.stop()
        disable_batch_log_file(clear_display=True)


def test_clear_boundary_distinguishes_identical_events_and_ages_out(page):
    old = "12:00:00.000  repeated event"
    state = DeviceState(log_messages=[old])
    page.refresh(state)
    page.clear()
    duplicate = old.encode().decode()
    assert duplicate == old and duplicate is not old
    state.log_messages.insert(0, duplicate)
    page.refresh(state)
    _wait_for_refresh()
    assert page.text.toPlainText() == duplicate
    state.log_messages[:] = [f"new event {index}" for index in range(500)]
    page.refresh(state)
    _wait_for_refresh()
    assert page.text.document().blockCount() == 500
    assert page._clear_anchor is None


def test_high_volume_refresh_is_coalesced_and_bounded(page):
    state = DeviceState()
    page.refresh(state)
    changes: list[bool] = []
    page.text.textChanged.connect(lambda: changes.append(True))
    for index in range(5000):
        state.log_messages.insert(0, f"event {index}")
        del state.log_messages[500:]
        page.refresh(state)
    assert changes == []
    _wait_for_refresh()
    assert changes == [True]
    assert page.text.document().blockCount() == 500
    assert len(page._snapshot) == 500
    assert page.text.toPlainText().splitlines()[0] == "event 4999"
    assert page.text.toPlainText().splitlines()[-1] == "event 4500"
    page.refresh(state)
    _wait_for_refresh()
    assert changes == [True]


def test_pause_resumes_latest_bounded_history_without_backlog(page):
    state = DeviceState(log_messages=["before pause"])
    page.refresh(state)
    page.pause_button.click()
    for index in range(2500):
        state.log_messages.insert(0, f"new event {index}")
        del state.log_messages[500:]
        page.refresh(state)
    assert page.text.toPlainText() == "before pause"
    assert not page._refresh_timer.isActive()
    page.pause_button.click()
    assert page.text.document().blockCount() == 500
    assert page.text.toPlainText().splitlines()[0] == "new event 2499"
    assert "before pause" not in page.text.toPlainText()


def test_reading_history_keeps_visible_event_and_follow_returns_to_top(page, qt_application):
    page.resize(900, 450)
    page.show()
    state = DeviceState(log_messages=[f"event {index}" for index in range(200)])
    page.refresh(state)
    qt_application.processEvents()
    scrollbar = page.text.verticalScrollBar()
    assert scrollbar.maximum() > 80
    scrollbar.setValue(80)
    anchor = page.text.firstVisibleBlock().text()
    assert not page.follow_checkbox.isChecked()
    state.log_messages.insert(0, "newest event")
    page.refresh(state)
    _wait_for_refresh()
    assert page.text.firstVisibleBlock().text() == anchor
    page.follow_checkbox.setChecked(True)
    assert scrollbar.value() == scrollbar.minimum()
    assert page.text.firstVisibleBlock().text() == "newest event"


def test_switching_device_replaces_a_paused_or_cleared_view(page):
    first = DeviceState(log_messages=["device A"])
    second = DeviceState(log_messages=["device B"])
    page.refresh(first)
    page.clear()
    page.pause_button.click()
    page.refresh(second)
    assert not page.pause_button.isChecked()
    assert page.text.toPlainText() == "device B"
    assert page.follow_checkbox.isChecked()
    assert first.log_messages == ["device A"]


def test_multiline_events_remain_one_event_per_block(page):
    state = DeviceState(log_messages=[f"event {index}\n detail\r\ntrace" for index in range(600)])
    page.refresh(state)
    assert page.text.document().blockCount() == 500
    assert len(page.text.toPlainText().splitlines()) == 500
    assert page.text.toPlainText().splitlines()[0] == "event 0  detail trace"
    assert len(state.log_messages) == 600
