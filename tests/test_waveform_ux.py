"""Waveform page UX: shared x counter, x-link, checklist, collapse, export."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication  # noqa: E402

import app.windows.waveform_page as waveform_module  # noqa: E402
from app.models import DeviceState  # noqa: E402
from app.windows.waveform_page import MAX_CHARTS, WaveformPage  # noqa: E402
from app.constants import SIGNAL_DEFINITIONS  # noqa: E402

FIELDS = [name for _label, name in SIGNAL_DEFINITIONS]


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _device(address="A", number=6, **values):
    return DeviceState(
        is_connected=True,
        device_name=f"PTU {address}",
        device_address=address,
        device_number=number,
        **values,
    )


def _feed(page, state, count, *, start=0):
    states = {state.device_address: state}
    for i in range(count):
        state.ptu_input_voltage = 1000 + start + i
        state.ptu_input_current = 200 + start + i
        page.refresh_device(state, states, state.device_address)


def _x_range(chart):
    return chart.plot.plotItem.vb.viewRange()[0]


def test_shared_sample_counter_gives_same_x_on_every_chart(qapp):
    page = WaveformPage()
    first = page.add_chart(FIELDS[0])
    state = _device()
    _feed(page, state, 7)
    second = page.add_chart(FIELDS[1])  # added 7 samples late
    _feed(page, state, 3, start=7)

    s1 = first.series["A"]
    s2 = second.series["A"]
    # The late chart starts at the current counter, not at 0 ...
    assert s2.x[0] == 7.0
    # ... and the same notify has the same x on both charts.
    assert s1.x[-3:] == s2.x == [7.0, 8.0, 9.0]
    assert s1.y[-3:] == [1007.0, 1008.0, 1009.0]
    assert s2.y == [207.0, 208.0, 209.0]

    page._flush_dirty()
    ranges = [_x_range(chart) for chart in page.charts]
    assert ranges[0] == pytest.approx(ranges[1])


def test_reset_chart_keeps_counter_but_reset_all_zeroes_it(qapp):
    page = WaveformPage()
    chart = page.add_chart(FIELDS[0])
    state = _device()
    _feed(page, state, 4)
    page.reset_chart(chart)
    _feed(page, state, 1, start=4)
    assert chart.series["A"].x == [4.0]
    page.reset_all()
    _feed(page, state, 1)
    assert chart.series["A"].x[-1] == 0.0


def test_legend_hidden_for_one_device_and_shown_for_two(qapp):
    page = WaveformPage()
    chart = page.add_chart(FIELDS[0])
    first = _device("A", 6)
    second = _device("B", 10)
    states = {"A": first, "B": second}
    page.scope_combo.setCurrentIndex(page.scope_combo.findData("all"))
    page.refresh_device(first, {"A": first}, "A")
    assert not chart.plot.plotItem.legend.isVisible()
    page.refresh_device(first, states, "A")
    page.refresh_device(second, states, "A")
    assert chart.plot.plotItem.legend.isVisible()
    # Back to the current-device filter: only one visible series -> hidden.
    page.scope_combo.setCurrentIndex(page.scope_combo.findData("current"))
    assert not chart.plot.plotItem.legend.isVisible()


def test_only_bottom_expanded_chart_shows_x_ticks(qapp):
    page = WaveformPage()
    charts = [page.add_chart(name) for name in FIELDS[:3]]

    def shown():
        return [c.plot.getAxis("bottom").style["showValues"] for c in charts]

    assert shown() == [False, False, True]
    page.set_chart_collapsed(charts[2], True)
    assert shown() == [False, True, False]
    page.set_chart_collapsed(charts[1], True)
    assert shown() == [True, False, False]
    page.set_chart_collapsed(charts[2], False)
    assert shown() == [False, False, True]


def test_collapsed_chart_hides_plot_but_keeps_receiving_data(qapp):
    page = WaveformPage()
    chart = page.add_chart(FIELDS[0])
    state = _device()
    _feed(page, state, 2)
    page.set_chart_collapsed(chart, True)
    assert chart.plot.isHidden()
    assert chart.collapse_btn.text() == "▸"
    _feed(page, state, 3, start=2)
    assert chart.series["A"].x == [0.0, 1.0, 2.0, 3.0, 4.0]  # no gap
    assert "latest 1004" in chart.stats_label.text()  # header keeps showing latest
    page.set_chart_collapsed(chart, False)
    assert not chart.plot.isHidden()


def test_signal_checklist_syncs_both_ways_and_caps_at_eight(qapp):
    page = WaveformPage()
    boxes = page._signal_checks
    assert page.signal_btn.text().startswith("訊號 (0)")
    boxes[FIELDS[0]].setChecked(True)
    assert [c.field_name for c in page.charts] == [FIELDS[0]]
    assert page.signal_btn.text().startswith("訊號 (1)")
    # card menu -> remove unchecks the box
    page.charts[0].remove_action.trigger()
    assert not boxes[FIELDS[0]].isChecked()
    assert page.charts == []
    # unchecking the box removes the chart
    page.set_signal_checked(FIELDS[1], True)
    boxes[FIELDS[1]].setChecked(False)
    assert page.charts == []
    # cap
    for name in FIELDS[:MAX_CHARTS]:
        boxes[name].setChecked(True)
    assert len(page.charts) == MAX_CHARTS == 8
    extra = FIELDS[MAX_CHARTS]
    assert not boxes[extra].isEnabled()
    assert boxes[extra].toolTip() == "最多 8 張圖"
    assert boxes[FIELDS[0]].isEnabled()
    assert page.add_chart(extra) is None
    page.set_signal_checked(FIELDS[0], False)
    assert boxes[extra].isEnabled()
    # duplicate add is ignored
    assert page.add_chart(FIELDS[1]) is None


def test_analysis_menu_actions_are_checkable_and_button_text_shows_mode(qapp):
    page = WaveformPage()
    assert page.delta_box.isCheckable() and page.region_box.isCheckable()
    assert page.analysis_btn.text() == "分析工具 ▾"
    assert not page.delta_clear_btn.isEnabled()
    page.delta_box.setChecked(True)
    assert page.analysis_btn.text() == "分析工具 (Δ) ▾"
    assert page.delta_clear_btn.isEnabled()
    page.region_box.setChecked(True)
    assert page.analysis_btn.text() == "分析工具 (Δ+框選) ▾"
    page.delta_box.setChecked(False)
    assert page.analysis_btn.text() == "分析工具 (框選) ▾"
    page.region_clear_btn.trigger()
    assert not page.region_box.isChecked()
    assert page.analysis_btn.text() == "分析工具 ▾"
    menu_texts = [a.text() for a in page.analysis_btn.menu().actions() if not a.isSeparator()]
    assert menu_texts == ["Δ 游標 (A/B)", "清除 A/B", "框選統計", "清除框選", "波形設定…"]


def test_new_chart_joins_active_region_and_delta_modes(qapp):
    page = WaveformPage()
    page.add_chart(FIELDS[0])
    page.region_box.setChecked(True)
    page.delta_box.setChecked(True)
    late = page.add_chart(FIELDS[1])
    assert late.region.isVisible()
    assert late.cursor_label.isHidden() is False
    assert page.charts[0].region.getRegion() == pytest.approx(late.region.getRegion())


def test_save_image_exports_png_with_title_then_restores_empty_title(qapp, monkeypatch, tmp_path):
    page = WaveformPage()
    chart = page.add_chart(FIELDS[0])
    _feed(page, _device(), 5)
    target = tmp_path / "chart.png"
    monkeypatch.setattr(
        waveform_module.QFileDialog,
        "getSaveFileName",
        lambda *a, **k: (str(target), "PNG Files (*.png)"),
    )
    seen = {}
    real_exporter = waveform_module.ImageExporter

    class SpyExporter(real_exporter):
        def export(self, filename):
            plot_item = chart.plot.plotItem
            seen["title"] = plot_item.titleLabel.text
            seen["title_visible"] = plot_item.titleLabel.isVisible()
            seen["left_label"] = chart.plot.getAxis("left").label.isVisible()
            seen["x_values"] = chart.plot.getAxis("bottom").style["showValues"]
            return super().export(filename)

    monkeypatch.setattr(waveform_module, "ImageExporter", SpyExporter)
    page.charts[0].save_action.trigger()

    assert target.exists() and target.stat().st_size > 0
    assert target.read_bytes()[:4] == b"\x89PNG"
    assert seen["title"] == "V_in (mV) - PTU #6"
    assert seen["title_visible"] and seen["left_label"] and seen["x_values"]
    plot_item = chart.plot.plotItem
    assert not plot_item.titleLabel.isVisible()
    assert not plot_item.titleLabel.text
    assert not chart.plot.getAxis("left").label.isVisible()


def test_removed_chart_is_unlinked_and_no_longer_fed(qapp):
    page = WaveformPage()
    a = page.add_chart(FIELDS[0])
    b = page.add_chart(FIELDS[1])
    c = page.add_chart(FIELDS[2])
    vb = pytest.importorskip("pyqtgraph").ViewBox
    assert b.plot.plotItem.vb.linkedView(vb.XAxis) is a.plot.plotItem.vb
    assert c.plot.plotItem.vb.linkedView(vb.XAxis) is a.plot.plotItem.vb
    state = _device()
    _feed(page, state, 3)
    # Remove the link base: the survivors must relink to the new base.
    page.remove_chart(a)
    assert a not in page.charts
    assert a.series["A"].x == [0.0, 1.0, 2.0]  # frozen, no longer fed
    _feed(page, state, 2, start=3)
    assert a.series["A"].x == [0.0, 1.0, 2.0]
    assert b.plot.plotItem.vb.linkedView(vb.XAxis) is None
    assert c.plot.plotItem.vb.linkedView(vb.XAxis) is b.plot.plotItem.vb
    assert a.plot.plotItem.vb.linkedView(vb.XAxis) is None
    page.remove_chart(FIELDS[1])  # remove by field name
    assert [x.field_name for x in page.charts] == [FIELDS[2]]
    assert page.charts[0].plot.plotItem.vb.linkedView(vb.XAxis) is None
    page.charts[0].plot.setXRange(0, 10)  # must not touch a deleted widget


def test_plot_heights_split_viewport_evenly_without_scrolling(qapp):
    page = WaveformPage()
    page.resize(1600, 1000)
    page.show()
    for name in FIELDS[:4]:
        page.add_chart(name)
    for _ in range(3):
        qapp.processEvents()
    viewport = page.scroll.viewport()
    heights = [c.plot.height() for c in page.charts]
    assert max(heights) - min(heights) <= 1
    assert min(heights) >= 150
    for chart in page.charts:
        bottom = chart.plot.mapTo(viewport, chart.plot.rect().bottomLeft()).y()
        assert 0 <= bottom <= viewport.height()
    assert not page.scroll.verticalScrollBar().isVisible()
    # One expanded chart fills the space; collapsed charts drop out of the split.
    for chart in page.charts[1:]:
        page.set_chart_collapsed(chart, True)
    qapp.processEvents()
    assert page.charts[0].plot.height() > 2 * heights[0]
    page.close()


def test_delta_and_crosshair_info_is_single_line_with_full_tooltip(qapp):
    page = WaveformPage()
    page.resize(1600, 1000)
    page.show()
    for name in ("ptuInputVoltage", "ptuInputCurrent", "ptuBusVoltage", "pruDynVout"):
        page.add_chart(name)
    a, b = _device("A", 6), _device("B", 10)
    states = {"A": a, "B": b}
    page.scope_combo.setCurrentIndex(page.scope_combo.findData("all"))
    for i in range(60):
        for dev in (a, b):
            dev.ptu_input_voltage = 52000 + i
            page.refresh_device(dev, states, "A")
    page.delta_box.setChecked(True)
    page._place_delta_cursor(page.charts[0], 10.0)
    page._place_delta_cursor(page.charts[0], 40.0)
    for _ in range(3):
        qapp.processEvents()
    line_h = page.charts[0].cursor_label.fontMetrics().height()
    for chart in page.charts:
        label = chart.cursor_label
        assert label.isVisible()
        assert label.height() <= line_h + 8
        assert "\n" not in label.text()
        assert "Δ Sample" in label.toolTip()
        assert "A Sample 10.0" in label.toolTip()
        assert "B Sample 40.0" in label.toolTip()
    page.delta_box.setChecked(False)
    page.crosshair_box.setChecked(True)
    page._broadcast_crosshair(page.charts[0], 20.0, 52010.0)
    for _ in range(3):
        qapp.processEvents()
    for chart in page.charts:
        assert chart.cursor_label.height() <= line_h + 8
        assert "Sample 20.0" in chart.cursor_label.toolTip()


def test_delta_values_stay_visible_and_reelide_follows_resize(qapp):
    page = WaveformPage()
    page.resize(1600, 1000)
    page.show()
    page.add_chart("ptuInputVoltage")
    a, b = _device("A", 6), _device("B", 10)
    states = {"A": a, "B": b}
    page.scope_combo.setCurrentIndex(page.scope_combo.findData("all"))
    for i in range(60):
        for dev in (a, b):
            dev.ptu_input_voltage = 52000 + i
            page.refresh_device(dev, states, "A")
    page.delta_box.setChecked(True)
    chart = page.charts[0]
    page._place_delta_cursor(chart, 10.0)
    page._place_delta_cursor(chart, 40.0)
    for _ in range(5):
        qapp.processEvents()
    label = chart.cursor_label
    full_tooltip = label.toolTip()
    # The Δ segment leads the elided line, so both devices' Δ values are
    # readable without hovering.
    assert "ΔPTU #6:" in label.text()
    assert "ΔPTU #10:" in label.text()
    wide_text = label.text()

    page.resize(900, 1000)
    for _ in range(5):
        qapp.processEvents()
    narrow_text = label.text()
    assert len(narrow_text) < len(wide_text)
    assert label.fontMetrics().horizontalAdvance(narrow_text) <= label.contentsRect().width()
    assert label.toolTip() == full_tooltip

    # Growing back must re-elide against the new (wider) width, not a stale one.
    page.resize(1600, 1000)
    for _ in range(5):
        qapp.processEvents()
    assert label.text() == wide_text
    assert label.toolTip() == full_tooltip


def test_late_device_starts_at_current_max_count_and_is_visible(qapp):
    page = WaveformPage()
    page.resize(1600, 1000)
    page.show()
    page.add_chart("ptuInputVoltage")
    page.scope_combo.setCurrentIndex(page.scope_combo.findData("all"))
    page.history_combo.setCurrentIndex(page.history_combo.findData(500)
                                       if page.history_combo.findData(500) >= 0 else 0)
    a, b = _device("A", 6), _device("B", 10)
    _feed(page, a, 500)
    states = {"A": a, "B": b}
    for i in range(50):
        for dev in (a, b):
            dev.ptu_input_voltage = 1000 + i
            page.refresh_device(dev, states, "A")
    qapp.processEvents()
    page._flush_dirty()
    chart = page.charts[0]
    bx = chart.series["B"].x
    assert bx[0] == 501.0 and bx[-1] == 550.0
    lo, hi = _x_range(chart)
    assert lo <= bx[0] and bx[-1] <= hi
