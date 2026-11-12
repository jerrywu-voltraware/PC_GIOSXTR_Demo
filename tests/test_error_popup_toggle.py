"""Error popup on/off setting, unread reminder, and waveform left-bound fix."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QSettings  # noqa: E402
from PyQt6.QtTest import QTest  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from app.models import DeviceState  # noqa: E402
from app.windows.main_window import ERROR_POPUP_SETTINGS_KEY, MainWindow  # noqa: E402
from app.windows.settings_dialog import SettingsDialog  # noqa: E402
from app.windows.waveform_page import WaveformPage  # noqa: E402


@pytest.fixture
def isolated_settings(tmp_path):
    app = QApplication.instance() or QApplication([])
    previous_identity = app.organizationName(), app.applicationName()
    previous_format = QSettings.defaultFormat()
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path / "settings"))
    app.setOrganizationName("ErrorPopupTest")
    app.setApplicationName("ErrorPopupTest")
    yield app
    app.setOrganizationName(previous_identity[0])
    app.setApplicationName(previous_identity[1])
    QSettings.setDefaultFormat(previous_format)


def _make_window(app):
    window = MainWindow()
    return window


def _close(app, window):
    if window._error_log_dialog is not None:
        window._error_log_dialog.hide()
    window._close_after_disconnect = True
    window.close()
    window.deleteLater()
    app.processEvents()


def _error_state(code=0x01, data=-12, limit=10):
    return DeviceState(
        device_address="90:2F:EC:DD:96:00",
        device_name="GIOS0801ST#9",
        is_connected=True,
        error_num=code,
        error_data=data,
        error_limit=limit,
    )


def test_popup_enabled_by_default_shows_dialog_without_reminder(isolated_settings):
    app = isolated_settings
    window = _make_window(app)
    try:
        assert window.error_popup_enabled is True
        window._show_error_dialog(_error_state())
        dialog = window._error_log_dialog
        assert dialog is not None and dialog.isVisible()
        assert dialog.table.rowCount() == 1
        assert window._unread_error_count == 0
        assert not window.error_alert_btn.isVisibleTo(window)
    finally:
        _close(app, window)


def test_popup_disabled_records_errors_and_shows_unread_reminder(isolated_settings):
    app = isolated_settings
    window = _make_window(app)
    try:
        window.set_error_popup_enabled(False)
        assert QSettings().value(ERROR_POPUP_SETTINGS_KEY) in (False, "false")
        window._show_error_dialog(_error_state(0x01))
        window._show_error_dialog(_error_state(0x03))
        dialog = window._error_log_dialog
        assert dialog is not None
        assert not dialog.isVisible()
        assert dialog.table.rowCount() == 2  # still recorded
        assert window._unread_error_count == 2
        assert window.error_alert_btn.isVisibleTo(window)
        assert "2 筆錯誤" in window.error_alert_btn.text()
        assert "0x03" in window.error_alert_btn.toolTip()  # latest error summary

        window.error_alert_btn.click()
        assert dialog.isVisible()
        assert window._unread_error_count == 0
        assert not window.error_alert_btn.isVisibleTo(window)
    finally:
        _close(app, window)


def test_new_error_while_list_is_open_does_not_count_as_unread(isolated_settings):
    app = isolated_settings
    window = _make_window(app)
    try:
        window.set_error_popup_enabled(False)
        window._show_error_dialog(_error_state(0x01))
        window._open_error_log_from_alert()
        window._show_error_dialog(_error_state(0x03))
        assert window._error_log_dialog.table.rowCount() == 2
        assert window._unread_error_count == 0
        assert not window.error_alert_btn.isVisibleTo(window)
    finally:
        _close(app, window)


def test_clearing_list_resets_unread(isolated_settings):
    app = isolated_settings
    window = _make_window(app)
    try:
        window.set_error_popup_enabled(False)
        window._show_error_dialog(_error_state())
        assert window._unread_error_count == 1
        window._error_log_dialog.clear_button.click()
        assert window._unread_error_count == 0
        assert not window.error_alert_btn.isVisibleTo(window)
    finally:
        _close(app, window)


def test_dialog_checkbox_and_setting_stay_in_sync(isolated_settings):
    app = isolated_settings
    window = _make_window(app)
    try:
        window._show_error_dialog(_error_state())
        dialog = window._error_log_dialog
        assert dialog.suppress_popup_box.isChecked() is False
        dialog.suppress_popup_box.setChecked(True)  # "don't pop up"
        assert window.error_popup_enabled is False
        assert QSettings().value(ERROR_POPUP_SETTINGS_KEY) in (False, "false")
        window.set_error_popup_enabled(True)
        assert dialog.suppress_popup_box.isChecked() is False
        assert dialog.popup_enabled is True
    finally:
        _close(app, window)


def test_setting_persists_across_windows(isolated_settings):
    app = isolated_settings
    first = _make_window(app)
    first.set_error_popup_enabled(False)
    _close(app, first)
    second = _make_window(app)
    try:
        assert second.error_popup_enabled is False
        second._show_error_dialog(_error_state())
        assert not second._error_log_dialog.isVisible()
        assert second._unread_error_count == 1
    finally:
        _close(app, second)


def test_popup_disabled_via_real_schedule_paths(isolated_settings):
    """Errors arriving through the 20B-then-200B and immediate paths."""
    app = isolated_settings
    window = _make_window(app)
    try:
        window.set_error_popup_enabled(False)
        # 200B already carries data/limit -> recorded immediately.
        immediate = _error_state(0x01)
        window.states[immediate.device_address] = immediate
        window._schedule_error_dialog(immediate)
        assert window._unread_error_count == 1
        # 20B first (no data/limit) -> pending; the matching 200B resolves it.
        pending = _error_state(0x03, data=0, limit=0)
        window.states[pending.device_address] = pending
        window._schedule_error_dialog(pending)
        assert window._unread_error_count == 1  # still waiting for 200B
        pending.error_data, pending.error_limit = -12, 10
        window._maybe_resolve_pending_error(pending.device_address, pending)
        dialog = window._error_log_dialog
        assert dialog.table.rowCount() == 2
        assert not dialog.isVisible()
        assert window._unread_error_count == 2
    finally:
        _close(app, window)


def test_settings_dialog_notification_tab(isolated_settings):
    dialog = SettingsDialog(engineering_mode=False, error_popup_enabled=False)
    labels = [dialog.tabs.tabText(i) for i in range(dialog.tabs.count())]
    assert "通知" in labels
    assert dialog.error_popup_box.isChecked() is False
    received: list[bool] = []
    dialog.error_popup_changed.connect(received.append)
    dialog.error_popup_box.setChecked(True)
    assert received == [True]
    dialog.deleteLater()


def test_waveform_late_chart_fills_view_instead_of_starting_at_zero(isolated_settings):
    page = WaveformPage()
    page.resize(1200, 800)
    page.show()
    fields = [name for _label, name in __import__("app.constants", fromlist=["x"]).SIGNAL_DEFINITIONS]
    state = DeviceState(is_connected=True, device_name="PTU A", device_address="A", device_number=6)
    states = {"A": state}
    early = page.add_chart(fields[0])
    for i in range(300):
        state.ptu_input_voltage = 1000 + i
        page.refresh_device(state, states, "A")
    page.remove_chart(early)
    late = page.add_chart(fields[1])  # added after 300 samples streamed
    for i in range(50):
        state.ptu_input_current = 200 + i
        page.refresh_device(state, states, "A")
    QTest.qWait(150)  # let the ~20 fps render timer apply the shared x window
    series = late.series["A"]
    left, right = late.plot.plotItem.vb.viewRange()[0]
    assert series.x[0] >= 300
    # The view starts near the first sample, not at 0 (old behaviour left
    # ~85% of this plot empty).
    assert left >= series.x[0] - 2
    assert right >= series.x[-1]
    page.deleteLater()


def _fields():
    from app.constants import SIGNAL_DEFINITIONS

    return [name for _label, name in SIGNAL_DEFINITIONS]


def test_waveform_older_chart_keeps_its_history_visible(isolated_settings):
    page = WaveformPage()
    page.resize(1200, 800)
    page.show()
    state = DeviceState(is_connected=True, device_name="PTU A", device_address="A", device_number=6)
    states = {"A": state}
    early = page.add_chart(_fields()[0])  # starts at x=0
    for i in range(300):
        state.ptu_input_voltage = 1000 + i
        page.refresh_device(state, states, "A")
    late = page.add_chart(_fields()[1])  # starts at x=300
    for i in range(50):
        state.ptu_input_current = 200 + i
        page.refresh_device(state, states, "A")
    QTest.qWait(150)
    left, _right = late.plot.plotItem.vb.viewRange()[0]
    # The shared window must still cover the early chart's oldest sample.
    assert early.series["A"].x[0] == 0.0
    assert left <= 0.5
    page.deleteLater()


def test_waveform_window_is_capped_by_history_length(isolated_settings):
    page = WaveformPage()
    page.resize(1200, 800)
    page.show()
    index = page.history_combo.findData(500)
    assert index >= 0
    page.history_combo.setCurrentIndex(index)
    state = DeviceState(is_connected=True, device_name="PTU A", device_address="A", device_number=6)
    states = {"A": state}
    chart = page.add_chart(_fields()[0])
    for i in range(2000):
        state.ptu_input_voltage = 1000 + (i % 50)
        page.refresh_device(state, states, "A")
    QTest.qWait(150)
    left, right = chart.plot.plotItem.vb.viewRange()[0]
    last = chart.series["A"].x[-1]
    expected_left = last - 500 + 1
    span = last - expected_left
    # viewRange includes setXRange(padding=0.01) on each side.
    assert abs(left - expected_left) <= span * 0.02 + 1
    assert right >= last
    page.deleteLater()
