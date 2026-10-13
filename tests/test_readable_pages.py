"""UI regressions for readable text and stable long-running monitoring views."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont, QFontDatabase, QFontMetrics
from PyQt6.QtWidgets import QApplication, QLabel

from app.models import DeviceState
from app.theme import theme_manager
from app.typography import typography_manager
from app.windows.data_pages import PtuPage
from app.windows.error_log_dialog import ErrorLogDialog
from app.windows.error_page import ErrorPage
from app.windows.overview_page import OverviewPage
from app.windows.scan_panel import ScanPanel


@pytest.fixture(scope="module")
def qt_app():
    app = QApplication.instance() or QApplication([])
    # Windows offscreen can have no fonts. Exercise actual glyph metrics, not
    # the placeholder metrics used by a completely empty font database.
    if not QFontDatabase.families():
        fonts = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
        for filename in ("segoeui.ttf", "msjh.ttc", "consola.ttf"):
            if (fonts / filename).exists():
                QFontDatabase.addApplicationFont(str(fonts / filename))
        if "Segoe UI" in QFontDatabase.families():
            app.setFont(QFont("Segoe UI", 11))
    theme_manager().install(app, "light")
    yield app


@pytest.fixture(autouse=True)
def reset_text_scale(qt_app):
    previous = typography_manager().scale()
    typography_manager().set_scale(100, persist=False)
    yield
    typography_manager().set_scale(previous, persist=False)
    qt_app.processEvents()


def _show(widget, qt_app, width=620, height=550):
    widget.resize(width, height)
    widget.show()
    qt_app.processEvents()
    qt_app.processEvents()


def _dispose(widget, qt_app):
    widget.close()
    widget.deleteLater()
    qt_app.processEvents()


@pytest.mark.parametrize("scale", [100, 150, 200])
def test_data_table_rows_fit_text_and_keep_selected_items(qt_app, scale):
    page = PtuPage()
    page.refresh(DeviceState(ptu_input_voltage=12000))
    _show(page, qt_app)
    page.table.selectRow(3)
    original = page.table.item(3, 1)

    typography_manager().set_scale(scale, persist=False)
    page.refresh(DeviceState(ptu_input_voltage=14000))
    qt_app.processEvents()

    assert page.table.item(3, 1) is original
    assert original.text() == "14000 mV"
    assert original.isSelected()
    assert page.table.font().pointSizeF() >= 11 * scale / 100
    for row in range(page.table.rowCount()):
        assert page.table.rowHeight(row) >= QFontMetrics(page.table.font()).height() + 2
    _dispose(page, qt_app)


def test_connected_rows_resize_without_recreating_widgets_or_emitting_selection(qt_app):
    panel = ScanPanel(object())
    devices = [{"address": "90:6C:0A:C9:96:00", "name": "GIOS0403ST#4",
                "packets": "12", "recording": "1", "connected": "1"}]
    address = devices[0]["address"]
    panel.refresh_connected_devices(devices, address)
    _show(panel, qt_app, width=360, height=760)
    original = panel.connected_list.itemWidget(panel.connected_list.item(0))
    base_height = panel.connected_list.item(0).sizeHint().height()
    selection_events = []
    panel.active_changed.connect(selection_events.append)

    devices[0]["packets"] = "9999999"
    panel.refresh_connected_devices(devices, address)
    typography_manager().set_scale(200, persist=False)
    qt_app.processEvents()

    item = panel.connected_list.item(0)
    assert panel.connected_list.itemWidget(item) is original
    assert not selection_events
    assert item.sizeHint().height() > base_height
    assert item.sizeHint().height() >= original.sizeHint().height()
    for label in original.findChildren(QLabel):
        assert label.font().pointSizeF() >= 22
        assert label.height() >= label.fontMetrics().height()
    status = original.findChild(QLabel, "connectedDeviceStatusLabel")
    assert "9999999" in status.text()
    assert panel.connected_list.horizontalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAsNeeded
    assert panel.connected_list.horizontalScrollBar().maximum() > 0
    for button in (panel.scan_btn, panel.connect_btn, panel.start_recording_btn,
                   panel.stop_recording_btn, panel.open_log_folder_btn):
        panel.scroll_area.ensureWidgetVisible(button)
        qt_app.processEvents()
        assert panel.scroll_area.viewport().width() >= button.width()
        assert button.visibleRegion().boundingRect().contains(button.rect())
    _dispose(panel, qt_app)


def test_overview_large_text_can_scroll_and_does_not_interrupt_log_reading(qt_app):
    page = OverviewPage()
    typography_manager().set_scale(200, persist=False)
    page.refresh(DeviceState(device_name="Long running logger", bus_temp_deg_c=37))
    _show(page, qt_app, width=650, height=540)

    assert page.summary_scroll.verticalScrollBar().maximum() > 0
    assert page.batch_log_text.font().pointSizeF() >= 22
    for index in range(80):
        page.append_batch_log_line(f"historical event {index:04}")
    qt_app.processEvents()
    scroll = page.batch_log_text.verticalScrollBar()
    assert scroll.maximum() > 0
    scroll.setValue(5)
    page.append_batch_log_line("new event while reading history")
    assert scroll.value() == 5
    scroll.setValue(scroll.maximum())
    page.append_batch_log_line("new event while following latest")
    assert scroll.value() == scroll.maximum()
    _dispose(page, qt_app)


def test_error_tables_scale_existing_rows_and_preserve_reference_position(qt_app):
    page = ErrorPage()
    dialog = ErrorLogDialog()
    state = DeviceState(error_num=1, error_data=100, error_limit=90)
    page.refresh(state)
    dialog.append_error(state)
    _show(page, qt_app, width=700, height=550)
    _show(dialog, qt_app)
    original_height = dialog.table.rowHeight(0)

    typography_manager().set_scale(200, persist=False)
    qt_app.processEvents()
    assert dialog.table.rowHeight(0) > original_height
    for table in (page.table, dialog.table):
        for row in range(table.rowCount()):
            assert table.rowHeight(row) >= QFontMetrics(table.item(row, 0).font()).height() + 2
    page.table.verticalScrollBar().setValue(page.table.verticalScrollBar().maximum())
    before = page.table.verticalScrollBar().value()
    page.refresh(state)
    assert page.table.verticalScrollBar().value() == before
    _dispose(page, qt_app)
    _dispose(dialog, qt_app)


def test_waveform_axes_markers_and_controls_follow_text_scale(qt_app):
    from app.windows.waveform_page import WaveformPage

    page = WaveformPage()
    page.add_chart()
    page.refresh(DeviceState(device_address="AA:BB:CC:DD:EE:01", device_name="PTU #1", is_connected=True))
    _show(page, qt_app, width=850, height=600)
    chart = page.charts[0]
    marker = page.add_marker(chart, 1, 5, "Test marker")
    typography_manager().set_scale(200, persist=False)
    qt_app.processEvents()

    assert chart.plot.getAxis("bottom").style["tickFont"].pointSizeF() >= 22
    assert marker.label.textItem.font().pointSizeF() >= 22
    assert chart.a_label.textItem.font().pointSizeF() >= 22
    legend_label = chart.plot.plotItem.legend.items[0][1]
    text_format = legend_label.item.document().begin().begin().fragment().charFormat()
    assert text_format.fontPointSize() >= 22
    title_format = chart.plot.plotItem.titleLabel.item.document().begin().begin().fragment().charFormat()
    assert title_format.foreground().color().name() == page._tokens.plot_axis_text.lower()
    assert page.controls_scroll.horizontalScrollBar().maximum() > 0
    assert page.minimumSizeHint().width() < 1000
    assert page.pause_box.height() >= page.pause_box.fontMetrics().height()
    _dispose(page, qt_app)


def test_waveform_style_cycle_preserves_rendered_axes_titles_and_existing_and_new_legends(qt_app):
    from app.windows.waveform_page import WaveformPage

    page = WaveformPage()
    page.add_chart()
    chart = page.charts[0]
    first = DeviceState(device_address="AA:BB:CC:DD:EE:01", device_name="First device", is_connected=True)
    page.scope_combo.setCurrentIndex(1)
    page.refresh(first)
    _show(page, qt_app, width=850, height=600)
    x_axis = chart.plot.getAxis("bottom")
    y_axis = chart.plot.getAxis("left")
    # Exercise nonempty units as well as the app's usual labels with units
    # embedded in their text.
    x_axis.setLabel("Sample", units="s")
    original_y = y_axis.labelText
    existing_legend = chart.plot.plotItem.legend.items[0][1]

    def rendered_format(item):
        return item.document().begin().begin().fragment().charFormat()

    for scale in (100, 125, 150, 175, 200):
        for theme in ("light", "dark"):
            typography_manager().set_scale(scale, persist=False)
            theme_manager().set_theme(theme, persist=False)
            qt_app.processEvents()
            expected_size = 11 * scale / 100
            expected_color = page._tokens.plot_axis_text.lower()
            for axis, text, units in ((x_axis, "Sample", "s"), (y_axis, original_y, "")):
                assert axis.labelText == text
                assert axis.labelUnits == units
                assert axis.label.isVisible()
                assert text in axis.label.toPlainText()
                assert rendered_format(axis.label).fontPointSize() == pytest.approx(expected_size)
                assert rendered_format(axis.label).foreground().color().name() == expected_color
                assert axis.style["tickFont"].pointSizeF() == pytest.approx(expected_size)
            assert existing_legend.item.toPlainText() == "First device"
            assert existing_legend.isVisible()
            assert rendered_format(existing_legend.item).fontPointSize() == pytest.approx(expected_size)
            assert rendered_format(existing_legend.item).foreground().color().name() == expected_color

            # New series use LegendItem's current options; existing labels use
            # the HTML-refresh path. Both must render at the current scale.
            curve = chart.plot.plot([0, 1], [1, 2], name="New device")
            new_label = chart.plot.plotItem.legend.items[-1][1]
            assert new_label.item.toPlainText() == "New device"
            assert new_label.isVisible()
            assert rendered_format(new_label.item).fontPointSize() == pytest.approx(expected_size)
            assert rendered_format(new_label.item).foreground().color().name() == expected_color
            chart.plot.removeItem(curve)

            # Updating the live title after styling must retain the text style.
            page.refresh(first)
            title = chart.plot.plotItem.titleLabel
            assert "First device" in title.item.toPlainText()
            assert title.isVisible()
            assert rendered_format(title.item).fontPointSize() == pytest.approx(13 * scale / 100)
            assert rendered_format(title.item).foreground().color().name() == expected_color

    x_axis.showLabel(False)
    theme_manager().set_theme("light", persist=False)
    assert x_axis.labelText == "Sample"
    assert x_axis.labelUnits == "s"
    assert not x_axis.label.isVisible()
    _dispose(page, qt_app)
