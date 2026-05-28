"""Live waveform page using pyqtgraph."""

from __future__ import annotations

import bisect
import math
from dataclasses import dataclass, field

import pyqtgraph as pg
from pyqtgraph.exporters import ImageExporter
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ..constants import SIGNAL_DEFINITIONS
from ..models import DeviceState
from ..theme import ThemeTokens, current_tokens, theme_manager


@dataclass
class DeviceSeries:
    address: str
    label: str
    curve: pg.PlotDataItem
    x: list[float] = field(default_factory=list)
    y: list[float] = field(default_factory=list)
    sample_index: int = 0


@dataclass
class WaveformMarker:
    x: float
    y: float
    text: str
    line: pg.InfiniteLine
    label: pg.TextItem


@dataclass
class ChartItem:
    label: str
    field_name: str
    plot: pg.PlotWidget
    stats_label: QLabel
    save_button: QPushButton
    series: dict[str, DeviceSeries] = field(default_factory=dict)
    curve: pg.PlotDataItem | None = None
    x: list[float] = field(default_factory=list)
    y: list[float] = field(default_factory=list)
    markers: list[WaveformMarker] = field(default_factory=list)
    cursor_label: QLabel | None = None
    vline: pg.InfiniteLine | None = None
    hline: pg.InfiniteLine | None = None
    mouse_proxy: object | None = None
    a_line: pg.InfiniteLine | None = None
    b_line: pg.InfiniteLine | None = None
    a_label: pg.TextItem | None = None
    b_label: pg.TextItem | None = None
    a_x: float | None = None
    b_x: float | None = None
    a_dots: dict[str, pg.ScatterPlotItem] = field(default_factory=dict)
    b_dots: dict[str, pg.ScatterPlotItem] = field(default_factory=dict)
    delta_links: dict[str, pg.PlotDataItem] = field(default_factory=dict)
    last_mouse_x: float | None = None
    region: pg.LinearRegionItem | None = None


class WaveformPage(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.charts: list[ChartItem] = []
        self._pens = ("#2BA7FF", "#29D398", "#F2C94C", "#FF7A59", "#B084F5", "#56CCF2", "#EB5757", "#6FCF97")
        self._states: dict[str, DeviceState] = {}
        self._active_address = ""
        self._held_addresses: set[str] = set()
        self._connected_addresses: set[str] = set()
        self._seen_addresses: set[str] = set()
        self._resumed_addresses: set[str] = set()
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        controls = QHBoxLayout()
        controls.setSpacing(8)
        self.signal_combo = QComboBox()
        for label, field_name in SIGNAL_DEFINITIONS:
            self.signal_combo.addItem(label, field_name)
        self.scope_combo = QComboBox()
        self.scope_combo.addItem("目前裝置", "current")
        self.scope_combo.addItem("全部裝置", "all")
        self.scope_combo.currentIndexChanged.connect(self._apply_device_filter)
        self.add_btn = QPushButton("新增曲線")
        self.add_btn.clicked.connect(self.add_chart)
        self.pause_box = QCheckBox("暫停")
        self.crosshair_box = QCheckBox("十字準線")
        self.crosshair_box.toggled.connect(self._on_crosshair_toggled)
        self.delta_box = QCheckBox("Δ 游標 (A/B)")
        self.delta_box.toggled.connect(self._on_delta_toggled)
        self.delta_clear_btn = QPushButton("清除 A/B")
        self.delta_clear_btn.setEnabled(False)
        self.delta_clear_btn.clicked.connect(self._clear_delta)
        self.region_box = QCheckBox("框選統計")
        self.region_box.toggled.connect(self._on_region_toggled)
        self.region_clear_btn = QPushButton("清除框選")
        self.region_clear_btn.setEnabled(False)
        self.region_clear_btn.clicked.connect(self._clear_region)
        self._region_color = "#FF7A59"
        self._region_syncing = False
        self.delta_highlight_box = QCheckBox("醒目顯示 Δ")
        self.delta_highlight_box.setChecked(True)
        self.delta_highlight_box.toggled.connect(self._refresh_all_delta_labels)
        self.delta_percent_box = QCheckBox("顯示百分比")
        self.delta_percent_box.setChecked(True)
        self.delta_percent_box.toggled.connect(self._refresh_all_delta_labels)
        self.delta_visual_box = QCheckBox("Δ 視覺輔助")
        self.delta_visual_box.setChecked(True)
        self.delta_visual_box.toggled.connect(self._on_delta_visual_toggled)
        self.delta_preview_box = QCheckBox("即時預覽 vs A")
        self.delta_preview_box.setChecked(True)
        self.delta_preview_box.toggled.connect(self._refresh_all_delta_labels)
        self._delta_pending: str = "A"
        self._delta_a_color = "#FFEA00"
        self._delta_b_color = "#29D398"
        self._delta_aux_color = "#B084F5"
        self.history_combo = QComboBox()
        for label, value in (
            ("500 samples", 500),
            ("2,000 samples", 2000),
            ("5,000 samples", 5000),
            ("10,000 samples", 10000),
            ("30,000 samples", 30000),
        ):
            self.history_combo.addItem(label, value)
        self.history_combo.setCurrentIndex(2)
        self.history_combo.currentIndexChanged.connect(self._apply_history_window)
        self.reset_btn = QPushButton("全部重設")
        self.reset_btn.clicked.connect(self.reset_all)
        controls.addWidget(QLabel("裝置"))
        controls.addWidget(self.scope_combo)
        controls.addWidget(QLabel("訊號"))
        controls.addWidget(self.signal_combo, 1)
        controls.addWidget(self.add_btn)
        controls.addWidget(self.pause_box)
        controls.addWidget(self.crosshair_box)
        controls.addWidget(self.delta_box)
        controls.addWidget(self.delta_clear_btn)
        controls.addWidget(self.region_box)
        controls.addWidget(self.region_clear_btn)
        self.settings_btn = QPushButton("波形設定⚙")
        self.settings_btn.setToolTip("Δ 游標顯示與量測選項")
        self.settings_btn.clicked.connect(self._open_settings_dialog)
        self._settings_dialog: QDialog | None = None
        controls.addWidget(self.settings_btn)
        controls.addWidget(QLabel("歷史"))
        controls.addWidget(self.history_combo)
        controls.addWidget(self.reset_btn)
        root.addLayout(controls)

        self.notice = QLabel("波形即時顯示")
        root.addWidget(self.notice)
        self._chart_cards: list[QWidget] = []
        self._chart_titles: list[QLabel] = []
        self._tokens: ThemeTokens = current_tokens()
        self._apply_theme(self._tokens)
        theme_manager().theme_changed.connect(self._on_theme_changed)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.container = QWidget()
        self.container_layout = QVBoxLayout(self.container)
        self.container_layout.addStretch(1)
        self.scroll.setWidget(self.container)
        root.addWidget(self.scroll, 1)
        self._disconnected_hold = False

    @staticmethod
    def _state_address(state: DeviceState, fallback: str = "") -> str:
        return state.device_address or fallback or "__current__"

    @staticmethod
    def _device_label(state: DeviceState) -> str:
        if state.device_number is not None:
            return f"PTU #{state.device_number}"
        name = state.device_name.strip()
        return name or state.device_address or "目前裝置"

    def set_devices(self, states: dict[str, DeviceState], active_address: str) -> None:
        connected_addresses = {address for address, state in states.items() if state.is_connected}
        resumed_addresses = {
            address
            for address in connected_addresses
            if address in self._seen_addresses and address not in self._connected_addresses
        }
        self._resumed_addresses.update(resumed_addresses)
        self._connected_addresses = connected_addresses
        self._seen_addresses.update(connected_addresses)
        self._states = dict(states)
        self._active_address = active_address
        self._apply_device_filter()
        self.set_connected(any(state.is_connected for state in self._states.values()))

    def set_connected(self, connected: bool) -> None:
        if not connected:
            self._disconnected_hold = True
            self.notice.setText("未連線，波形已暫停")
        elif self._disconnected_hold:
            self.notice.setText("波形即時顯示")
            self._disconnected_hold = False

    def _history_limit(self) -> int:
        value = self.history_combo.currentData()
        return int(value) if value is not None else 5000

    def add_chart(self) -> None:
        if len(self.charts) >= 5:
            return
        label = self.signal_combo.currentText()
        field_name = str(self.signal_combo.currentData())
        if any(chart.field_name == field_name for chart in self.charts):
            return
        plot = pg.PlotWidget(title=label)
        plot.setMinimumHeight(230)
        self._style_plot(plot)
        plot.showGrid(x=True, y=True, alpha=0.28)
        plot.setLabel("bottom", "Sample")
        plot.setLabel("left", label)
        plot.getAxis("left").setWidth(72)
        plot.setMouseEnabled(x=True, y=True)
        plot.setDownsampling(auto=True, mode="peak")
        plot.setClipToView(True)
        legend = plot.addLegend(offset=(12, 12))
        self._style_legend(legend)
        stats_label = QLabel("latest --   min --   max --   samples 0")
        stats_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        stats_label.setStyleSheet(f"color: {self._tokens.text_secondary}; font-family: Consolas;")
        cursor_label = QLabel("游標 --")
        cursor_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        cursor_label.setStyleSheet(f"color: {self._tokens.text_secondary}; font-family: Consolas;")
        cursor_label.setVisible(self.crosshair_box.isChecked() or self.delta_box.isChecked())
        save_btn = QPushButton("儲存圖片")
        item = ChartItem(label=label, field_name=field_name, plot=plot, stats_label=stats_label, save_button=save_btn)
        item.cursor_label = cursor_label
        remove_btn = QPushButton("移除")
        reset_btn = QPushButton("重設")
        clear_markers_btn = QPushButton("清除標籤")
        card = QWidget()
        card.setObjectName("waveformCard")
        self._style_card(card)
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(10, 8, 10, 10)
        card_layout.setSpacing(8)
        top = QHBoxLayout()
        title = QLabel(label)
        title.setStyleSheet(f"font-weight: 700; color: {self._tokens.text_primary};")
        self._chart_cards.append(card)
        self._chart_titles.append(title)
        top.addWidget(title)
        top.addWidget(cursor_label, 1)
        top.addWidget(stats_label, 1)
        top.addWidget(save_btn)
        top.addWidget(reset_btn)
        top.addWidget(clear_markers_btn)
        top.addWidget(remove_btn)
        card_layout.addLayout(top)
        card_layout.addWidget(plot)
        self.container_layout.insertWidget(self.container_layout.count() - 1, card)
        item.plot.setProperty("card", card)
        remove_btn.clicked.connect(lambda: self.remove_chart(item))
        reset_btn.clicked.connect(lambda: self.reset_chart(item))
        clear_markers_btn.clicked.connect(lambda: self.clear_markers(item))
        save_btn.clicked.connect(lambda: self.save_chart_image(item))
        plot.scene().sigMouseClicked.connect(lambda event, chart=item: self._handle_plot_click(chart, event))
        self._install_crosshair(item)
        self._install_delta_lines(item)
        self._install_region(item)
        self.charts.append(item)

    def remove_chart(self, item: ChartItem) -> None:
        self.clear_markers(item)
        self._clear_delta_visuals(item)
        for graphics_item in (item.vline, item.hline, item.a_line, item.b_line, item.a_label, item.b_label, item.region):
            if graphics_item is not None:
                try:
                    item.plot.removeItem(graphics_item)
                except Exception:
                    pass
        item.vline = None
        item.hline = None
        item.a_line = None
        item.b_line = None
        item.a_label = None
        item.b_label = None
        item.region = None
        item.a_x = None
        item.b_x = None
        item.mouse_proxy = None
        if item in self.charts:
            self.charts.remove(item)
        card = item.plot.property("card")
        if card is not None:
            if card in self._chart_cards:
                idx = self._chart_cards.index(card)
                self._chart_cards.pop(idx)
                if idx < len(self._chart_titles):
                    self._chart_titles.pop(idx)
            card.deleteLater()

    def reset_chart(self, item: ChartItem) -> None:
        for series in item.series.values():
            series.x.clear()
            series.y.clear()
            series.sample_index = 0
            series.curve.setData([], [])
        self.clear_markers(item)
        item.x = []
        item.y = []
        item.stats_label.setText("latest --   min --   max --   samples 0")

    def reset_all(self) -> None:
        for item in self.charts:
            self.reset_chart(item)

    def _open_settings_dialog(self) -> None:
        dialog = self._settings_dialog
        if dialog is not None and dialog.isVisible():
            dialog.raise_()
            dialog.activateWindow()
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("波形設定")
        dialog.setModal(False)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        delta_group = QGroupBox("Δ 游標顯示")
        delta_layout = QVBoxLayout(delta_group)
        delta_layout.setSpacing(6)
        for box in (
            self.delta_highlight_box,
            self.delta_percent_box,
            self.delta_visual_box,
            self.delta_preview_box,
        ):
            delta_layout.addWidget(box)
        hint = QLabel(
            "提示：「即時預覽 vs A」只在「已放下 A、尚未放下 B」時顯示。\n"
            "已放下 B 之後會改顯示固定的 Δ 行；按「清除 A/B」可重新試。"
        )
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color: {self._tokens.text_secondary};")
        delta_layout.addWidget(hint)
        layout.addWidget(delta_group)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(dialog.close)
        buttons.accepted.connect(dialog.close)
        for button in buttons.buttons():
            button.setText("關閉")
        layout.addWidget(buttons)

        dialog.setMinimumWidth(320)
        self._settings_dialog = dialog
        dialog.show()

    def _install_crosshair(self, item: ChartItem) -> None:
        pen = pg.mkPen(self._tokens.plot_axis_text, width=1, style=Qt.PenStyle.DashLine)
        vline = pg.InfiniteLine(angle=90, movable=False, pen=pen)
        hline = pg.InfiniteLine(angle=0, movable=False, pen=pen)
        vline.setZValue(15)
        hline.setZValue(15)
        visible = self.crosshair_box.isChecked()
        vline.setVisible(False)
        hline.setVisible(False)
        item.plot.addItem(vline, ignoreBounds=True)
        item.plot.addItem(hline, ignoreBounds=True)
        item.vline = vline
        item.hline = hline
        if item.cursor_label is not None:
            item.cursor_label.setVisible(visible)
        item.mouse_proxy = pg.SignalProxy(
            item.plot.scene().sigMouseMoved,
            rateLimit=60,
            slot=lambda event, chart=item: self._on_crosshair_mouse_moved(chart, event),
        )

    def _install_delta_lines(self, item: ChartItem) -> None:
        a_pen = pg.mkPen(self._delta_a_color, width=2, style=Qt.PenStyle.SolidLine)
        b_pen = pg.mkPen(self._delta_b_color, width=2, style=Qt.PenStyle.SolidLine)
        a_line = pg.InfiniteLine(angle=90, movable=False, pen=a_pen)
        b_line = pg.InfiniteLine(angle=90, movable=False, pen=b_pen)
        a_line.setZValue(18)
        b_line.setZValue(18)
        a_line.setVisible(False)
        b_line.setVisible(False)
        a_label = pg.TextItem(
            text="A",
            color="#000000",
            anchor=(0.5, 1),
            fill=pg.mkBrush(self._delta_a_color),
        )
        b_label = pg.TextItem(
            text="B",
            color="#000000",
            anchor=(0.5, 1),
            fill=pg.mkBrush(self._delta_b_color),
        )
        a_label.setFont(pg.Qt.QtGui.QFont("Consolas", 10, 700))
        b_label.setFont(pg.Qt.QtGui.QFont("Consolas", 10, 700))
        a_label.setZValue(19)
        b_label.setZValue(19)
        a_label.setVisible(False)
        b_label.setVisible(False)
        item.plot.addItem(a_line, ignoreBounds=True)
        item.plot.addItem(b_line, ignoreBounds=True)
        item.plot.addItem(a_label, ignoreBounds=True)
        item.plot.addItem(b_label, ignoreBounds=True)
        item.a_line = a_line
        item.b_line = b_line
        item.a_label = a_label
        item.b_label = b_label

    def _install_region(self, item: ChartItem) -> None:
        brush = pg.mkBrush(255, 122, 89, 55)
        hover_brush = pg.mkBrush(255, 122, 89, 95)
        pen = pg.mkPen(self._region_color, width=2)
        region = pg.LinearRegionItem(
            values=(0.0, 0.0),
            orientation="vertical",
            brush=brush,
            hoverBrush=hover_brush,
            pen=pen,
            movable=True,
        )
        region.setZValue(14)
        region.setVisible(False)
        item.plot.addItem(region, ignoreBounds=True)
        item.region = region
        region.sigRegionChanged.connect(lambda _r, chart=item: self._on_region_changed(chart))

    def _on_region_toggled(self, enabled: bool) -> None:
        self.region_clear_btn.setEnabled(enabled)
        if enabled:
            x1: float | None = None
            x2: float | None = None
            for chart in self.charts:
                latest = self._latest_chart_x(chart)
                if latest is None or latest < 2:
                    continue
                left = max(0.0, latest * 0.6)
                right = max(left + 1.0, latest * 0.85)
                x1, x2 = left, right
                break
            if x1 is None:
                x1, x2 = 0.0, 100.0
            self._region_syncing = True
            try:
                for chart in self.charts:
                    if chart.region is None:
                        continue
                    chart.region.setRegion((x1, x2))
                    chart.region.setVisible(True)
            finally:
                self._region_syncing = False
        else:
            for chart in self.charts:
                if chart.region is not None:
                    chart.region.setVisible(False)
        for chart in self.charts:
            self._update_stats(chart)

    def _on_region_changed(self, source: ChartItem) -> None:
        if self._region_syncing or source.region is None:
            return
        x1, x2 = source.region.getRegion()
        self._region_syncing = True
        try:
            for chart in self.charts:
                if chart is source or chart.region is None:
                    continue
                chart.region.setRegion((x1, x2))
        finally:
            self._region_syncing = False
        for chart in self.charts:
            self._update_stats(chart)

    def _clear_region(self) -> None:
        self.region_box.setChecked(False)

    def _on_delta_toggled(self, enabled: bool) -> None:
        self.delta_clear_btn.setEnabled(enabled)
        cursor_visible = enabled or self.crosshair_box.isChecked()
        for chart in self.charts:
            self._set_delta_visible(chart, enabled)
            if chart.cursor_label is not None:
                chart.cursor_label.setVisible(cursor_visible)
        if enabled:
            self._refresh_all_delta_labels()
        else:
            for chart in self.charts:
                if chart.cursor_label is not None and not self.crosshair_box.isChecked():
                    chart.cursor_label.setText("游標 --")

    def _on_delta_visual_toggled(self, _enabled: bool) -> None:
        self._refresh_all_delta_labels()

    def _set_delta_visible(self, chart: ChartItem, enabled: bool) -> None:
        show_a = enabled and chart.a_x is not None
        show_b = enabled and chart.b_x is not None
        if chart.a_line is not None:
            chart.a_line.setVisible(show_a)
        if chart.b_line is not None:
            chart.b_line.setVisible(show_b)
        if chart.a_label is not None:
            chart.a_label.setVisible(show_a)
        if chart.b_label is not None:
            chart.b_label.setVisible(show_b)

    def _clear_delta(self) -> None:
        for chart in self.charts:
            chart.a_x = None
            chart.b_x = None
            self._set_delta_visible(chart, False)
            self._clear_delta_visuals(chart)
        self._delta_pending = "A"
        self._refresh_all_delta_labels()

    def _place_delta_cursor(self, source: ChartItem, x_value: float) -> None:
        source_latest = self._latest_chart_x(source)
        offset_from_right = (source_latest - x_value) if source_latest is not None else 0.0
        slot = self._delta_pending
        for chart in self.charts:
            if chart is source:
                target_x = x_value
            else:
                chart_latest = self._latest_chart_x(chart)
                target_x = (chart_latest - offset_from_right) if chart_latest is not None else x_value
            if slot == "A":
                chart.a_x = target_x
                if chart.a_line is not None:
                    chart.a_line.setPos(target_x)
            else:
                chart.b_x = target_x
                if chart.b_line is not None:
                    chart.b_line.setPos(target_x)
        self._delta_pending = "B" if slot == "A" else "A"
        self._refresh_all_delta_labels()

    def _refresh_all_delta_labels(self) -> None:
        if not self.delta_box.isChecked():
            return
        for chart in self.charts:
            self._set_delta_visible(chart, True)
            self._update_delta_labels_for(chart)
            self._render_chart_delta_text(chart)

    def _update_delta_labels_for(self, chart: ChartItem) -> None:
        y_min, y_max = chart.plot.plotItem.vb.viewRange()[1]
        y_top = y_min + (y_max - y_min) * 0.97
        if chart.a_label is not None and chart.a_x is not None:
            chart.a_label.setPos(chart.a_x, y_top)
        if chart.b_label is not None and chart.b_x is not None:
            chart.b_label.setPos(chart.b_x, y_top)

    @staticmethod
    def _format_delta_pct(base: float, delta: float) -> str:
        if not math.isfinite(base) or abs(base) < 1e-9:
            return ""
        return f" ({delta / base * 100:+.1f}%)"

    def _render_chart_delta_text(self, chart: ChartItem) -> None:
        if chart.cursor_label is None:
            return
        selected_addresses = self._selected_addresses()
        visible_series = [
            series
            for address, series in chart.series.items()
            if address in selected_addresses and series.x
        ]
        if chart.a_x is None and chart.b_x is None:
            chart.cursor_label.setText("Δ: 點擊圖上設定 A，再點擊設定 B")
            self._clear_delta_visuals(chart)
            return
        show_pct = self.delta_percent_box.isChecked()
        highlight = self.delta_highlight_box.isChecked()
        preview = self.delta_preview_box.isChecked()
        lines: list[str] = []
        a_values: dict[str, float] = {}
        b_values: dict[str, float] = {}
        if chart.a_x is not None:
            parts = [f"A Sample {chart.a_x:.1f}"]
            for series in visible_series:
                yv = self._sample_value_at(series, chart.a_x)
                if yv is None or not math.isfinite(yv):
                    parts.append(f"{series.label}: --")
                else:
                    a_values[series.address] = yv
                    parts.append(f"{series.label}: {yv:.2f}")
            lines.append("   ".join(parts))
        if chart.b_x is not None:
            parts = [f"B Sample {chart.b_x:.1f}"]
            for series in visible_series:
                yv = self._sample_value_at(series, chart.b_x)
                if yv is None or not math.isfinite(yv):
                    parts.append(f"{series.label}: --")
                else:
                    b_values[series.address] = yv
                    parts.append(f"{series.label}: {yv:.2f}")
            lines.append("   ".join(parts))
        if chart.a_x is not None and chart.b_x is not None:
            dx = chart.b_x - chart.a_x
            parts = [f"Δ Sample {dx:+.1f}"]
            for series in visible_series:
                ay = a_values.get(series.address)
                by = b_values.get(series.address)
                if ay is None or by is None:
                    parts.append(f"Δ{series.label}: --")
                else:
                    dy = by - ay
                    suffix = self._format_delta_pct(ay, dy) if show_pct else ""
                    parts.append(f"Δ{series.label}: {dy:+.2f}{suffix}")
            delta_line = "   ".join(parts)
            if highlight:
                delta_line = f"⟦ {delta_line} ⟧"
            lines.append(delta_line)
            if preview:
                lines.append("（預覽：A/B 已放下，目前顯示固定 Δ；按「清除 A/B」可重設）")
        elif chart.a_x is not None and preview and chart.last_mouse_x is not None:
            mx = chart.last_mouse_x
            parts = [f"vs A @Sample {mx:.1f}"]
            for series in visible_series:
                ay = a_values.get(series.address)
                cy = self._sample_value_at(series, mx)
                if ay is None or cy is None or not math.isfinite(cy):
                    parts.append(f"Δ{series.label}: --")
                else:
                    dy = cy - ay
                    suffix = self._format_delta_pct(ay, dy) if show_pct else ""
                    parts.append(f"Δ{series.label}: {dy:+.2f}{suffix}")
            preview_line = "   ".join(parts)
            if highlight:
                preview_line = f"⟦ {preview_line} ⟧"
            lines.append(preview_line)
            lines.append(f"(下一個點擊放 {self._delta_pending})")
        else:
            lines.append(f"(下一個點擊放 {self._delta_pending})")
        chart.cursor_label.setText("\n".join(lines))
        self._apply_delta_highlight_style(chart)
        self._update_delta_visuals(chart, visible_series, a_values, b_values)

    def _apply_delta_highlight_style(self, chart: ChartItem) -> None:
        if chart.cursor_label is None:
            return
        if self.delta_box.isChecked() and self.delta_highlight_box.isChecked() and (
            chart.a_x is not None or chart.b_x is not None
        ):
            chart.cursor_label.setStyleSheet(
                f"color: {self._tokens.text_primary}; font-family: Consolas; "
                f"font-weight: 700; font-size: 11pt; "
                f"background: rgba(176,132,245,0.18); padding: 4px 6px; border-radius: 4px;"
            )
        else:
            chart.cursor_label.setStyleSheet(
                f"color: {self._tokens.text_secondary}; font-family: Consolas;"
            )

    def _clear_delta_visuals(self, chart: ChartItem) -> None:
        for dot in list(chart.a_dots.values()) + list(chart.b_dots.values()):
            try:
                chart.plot.removeItem(dot)
            except Exception:
                pass
        chart.a_dots.clear()
        chart.b_dots.clear()
        for link in chart.delta_links.values():
            try:
                chart.plot.removeItem(link)
            except Exception:
                pass
        chart.delta_links.clear()

    def _update_delta_visuals(
        self,
        chart: ChartItem,
        visible_series: list[DeviceSeries],
        a_values: dict[str, float],
        b_values: dict[str, float],
    ) -> None:
        if not self.delta_box.isChecked() or not self.delta_visual_box.isChecked():
            self._clear_delta_visuals(chart)
            return
        wanted_addresses = {series.address for series in visible_series}
        for addr in list(chart.a_dots.keys()):
            if addr not in wanted_addresses:
                try:
                    chart.plot.removeItem(chart.a_dots.pop(addr))
                except Exception:
                    chart.a_dots.pop(addr, None)
        for addr in list(chart.b_dots.keys()):
            if addr not in wanted_addresses:
                try:
                    chart.plot.removeItem(chart.b_dots.pop(addr))
                except Exception:
                    chart.b_dots.pop(addr, None)
        for addr in list(chart.delta_links.keys()):
            if addr not in wanted_addresses:
                try:
                    chart.plot.removeItem(chart.delta_links.pop(addr))
                except Exception:
                    chart.delta_links.pop(addr, None)
        for series in visible_series:
            addr = series.address
            ay = a_values.get(addr)
            by = b_values.get(addr)
            if chart.a_x is not None and ay is not None and math.isfinite(ay):
                dot = chart.a_dots.get(addr)
                if dot is None:
                    dot = pg.ScatterPlotItem(
                        size=11,
                        brush=pg.mkBrush(self._delta_a_color),
                        pen=pg.mkPen("#000000", width=1),
                    )
                    dot.setZValue(17)
                    chart.plot.addItem(dot, ignoreBounds=True)
                    chart.a_dots[addr] = dot
                dot.setData([chart.a_x], [ay])
                dot.setVisible(True)
            elif addr in chart.a_dots:
                chart.a_dots[addr].setVisible(False)
            if chart.b_x is not None and by is not None and math.isfinite(by):
                dot = chart.b_dots.get(addr)
                if dot is None:
                    dot = pg.ScatterPlotItem(
                        size=11,
                        brush=pg.mkBrush(self._delta_b_color),
                        pen=pg.mkPen("#000000", width=1),
                    )
                    dot.setZValue(17)
                    chart.plot.addItem(dot, ignoreBounds=True)
                    chart.b_dots[addr] = dot
                dot.setData([chart.b_x], [by])
                dot.setVisible(True)
            elif addr in chart.b_dots:
                chart.b_dots[addr].setVisible(False)
            if (
                chart.a_x is not None
                and chart.b_x is not None
                and ay is not None
                and by is not None
                and math.isfinite(ay)
                and math.isfinite(by)
            ):
                link = chart.delta_links.get(addr)
                if link is None:
                    link = chart.plot.plot(
                        [],
                        [],
                        pen=pg.mkPen(self._delta_aux_color, width=1.5, style=Qt.PenStyle.DashLine),
                    )
                    link.setZValue(16)
                    chart.delta_links[addr] = link
                link.setData([chart.a_x, chart.b_x], [ay, by])
                link.setVisible(True)
            elif addr in chart.delta_links:
                chart.delta_links[addr].setVisible(False)

    def _on_crosshair_toggled(self, enabled: bool) -> None:
        cursor_visible = enabled or self.delta_box.isChecked()
        for item in self.charts:
            if item.cursor_label is not None:
                item.cursor_label.setVisible(cursor_visible)
            if not enabled:
                if item.vline is not None:
                    item.vline.setVisible(False)
                if item.hline is not None:
                    item.hline.setVisible(False)
                if item.cursor_label is not None and not self.delta_box.isChecked():
                    item.cursor_label.setText("游標 --")
        if self.delta_box.isChecked():
            self._refresh_all_delta_labels()

    def _on_crosshair_mouse_moved(self, item: ChartItem, event) -> None:
        crosshair_on = self.crosshair_box.isChecked()
        delta_on = self.delta_box.isChecked()
        if not crosshair_on and not delta_on:
            return
        if not event:
            return
        scene_pos = event[0]
        view_box = item.plot.plotItem.vb
        if not view_box.sceneBoundingRect().contains(scene_pos):
            self._hide_all_crosshairs()
            return
        point = view_box.mapSceneToView(scene_pos)
        x_value = float(point.x())
        y_value = float(point.y())
        if crosshair_on:
            self._broadcast_crosshair(item, x_value, y_value)
        elif delta_on and self.delta_preview_box.isChecked():
            source_latest = self._latest_chart_x(item)
            offset_from_right = (source_latest - x_value) if source_latest is not None else 0.0
            for chart in self.charts:
                if chart is item:
                    chart.last_mouse_x = x_value
                else:
                    chart_latest = self._latest_chart_x(chart)
                    chart.last_mouse_x = (
                        chart_latest - offset_from_right if chart_latest is not None else x_value
                    )
                self._render_chart_delta_text(chart)

    def _hide_all_crosshairs(self) -> None:
        crosshair_on = self.crosshair_box.isChecked()
        for chart in self.charts:
            if chart.vline is not None:
                chart.vline.setVisible(False)
            if chart.hline is not None:
                chart.hline.setVisible(False)
            chart.last_mouse_x = None
            if not crosshair_on and self.delta_box.isChecked():
                self._render_chart_delta_text(chart)
            elif chart.cursor_label is not None and not self.delta_box.isChecked():
                chart.cursor_label.setText("游標 --")

    def _broadcast_crosshair(self, source: ChartItem, x_value: float, y_value: float) -> None:
        selected_addresses = self._selected_addresses()
        source_latest = self._latest_chart_x(source)
        offset_from_right = (source_latest - x_value) if source_latest is not None else 0.0
        for chart in self.charts:
            is_source = chart is source
            if is_source:
                target_x = x_value
            else:
                chart_latest = self._latest_chart_x(chart)
                target_x = (chart_latest - offset_from_right) if chart_latest is not None else x_value
            chart.last_mouse_x = target_x
            if chart.vline is not None:
                chart.vline.setPos(target_x)
                chart.vline.setVisible(True)
            if chart.hline is not None:
                if is_source:
                    chart.hline.setPos(y_value)
                    chart.hline.setVisible(True)
                else:
                    chart.hline.setVisible(False)
            if chart.cursor_label is None:
                continue
            if self.delta_box.isChecked():
                self._render_chart_delta_text(chart)
                continue
            visible_series = [
                series
                for address, series in chart.series.items()
                if address in selected_addresses and series.x
            ]
            parts = [f"Sample {target_x:.1f}"]
            for series in visible_series:
                yv = self._sample_value_at(series, target_x)
                if yv is None or not math.isfinite(yv):
                    parts.append(f"{series.label}: --")
                else:
                    parts.append(f"{series.label}: {yv:.2f}")
            if is_source:
                parts.append(f"y={y_value:.2f}")
            chart.cursor_label.setText("   ".join(parts))

    @staticmethod
    def _sample_value_at(series: DeviceSeries, x_value: float) -> float | None:
        if not series.x:
            return None
        idx = bisect.bisect_left(series.x, x_value)
        if idx >= len(series.x):
            idx = len(series.x) - 1
        elif idx > 0:
            if abs(series.x[idx - 1] - x_value) <= abs(series.x[idx] - x_value):
                idx -= 1
        return series.y[idx]

    def _handle_plot_click(self, item: ChartItem, event) -> None:
        is_double_click = getattr(event, "double", lambda: False)()
        if event.button() != Qt.MouseButton.LeftButton:
            return
        view_box = item.plot.plotItem.vb
        scene_pos = event.scenePos()
        if not view_box.sceneBoundingRect().contains(scene_pos):
            return
        if self.delta_box.isChecked() and not is_double_click:
            point = view_box.mapSceneToView(scene_pos)
            self._place_delta_cursor(item, float(point.x()))
            event.accept()
            return
        if not is_double_click:
            return
        point = view_box.mapSceneToView(scene_pos)
        x_value = float(point.x())
        y_value = float(point.y())
        default_text = f"標記 {len(item.markers) + 1}"
        text, accepted = QInputDialog.getText(
            self,
            "新增波形標籤",
            "標籤內容",
            QLineEdit.EchoMode.Normal,
            default_text,
        )
        if not accepted or not text.strip():
            return
        self.add_marker(item, x_value, y_value, text.strip())
        event.accept()

    def add_marker(self, item: ChartItem, x_value: float, y_value: float, text: str) -> WaveformMarker:
        y_min, y_max = item.plot.plotItem.vb.viewRange()[1]
        y_top = y_min + (y_max - y_min) * 0.93
        if not math.isfinite(y_value):
            y_value = y_top
        else:
            y_value = min(max(y_value, y_min), y_top)
        display_text = f"{text}\nSample {x_value:.0f}"
        marker_color = "#FFEA00"
        marker_pen = pg.mkPen(marker_color, width=2.2, style=Qt.PenStyle.DashLine)
        line = pg.InfiniteLine(pos=x_value, angle=90, movable=False, pen=marker_pen)
        line.setZValue(20)
        label = pg.TextItem(
            text=display_text,
            color="#FFFFFF",
            anchor=(0, 1),
            fill=pg.mkBrush(0, 0, 0, 245),
            border=pg.mkPen(marker_color, width=2),
        )
        label.setFont(pg.Qt.QtGui.QFont("Consolas", 10, 700))
        label.setPos(x_value, y_value)
        label.setZValue(21)
        item.plot.addItem(line, ignoreBounds=True)
        item.plot.addItem(label, ignoreBounds=True)
        marker = WaveformMarker(x=x_value, y=y_value, text=text, line=line, label=label)
        item.markers.append(marker)
        return marker

    def clear_markers(self, item: ChartItem) -> None:
        for marker in item.markers:
            for graphics_item in (marker.line, marker.label):
                try:
                    item.plot.removeItem(graphics_item)
                except Exception:
                    pass
        item.markers.clear()

    def _apply_history_window(self) -> None:
        max_samples = self._history_limit()
        for item in self.charts:
            for series in item.series.values():
                if len(series.x) > max_samples:
                    series.x = series.x[-max_samples:]
                    series.y = series.y[-max_samples:]
            self._refresh_chart_display(item)

    def _selected_addresses(self) -> set[str]:
        held_with_data = {
            address
            for item in self.charts
            for address, series in item.series.items()
            if address in self._held_addresses and series.y
        }
        if self.scope_combo.currentData() == "all":
            connected = {address for address, state in self._states.items() if state.is_connected}
            return connected | held_with_data if connected else held_with_data
        active_state = self._states.get(self._active_address)
        if active_state is None or not active_state.is_connected:
            return held_with_data
        return {self._active_address}

    def save_chart_image(self, item: ChartItem) -> None:
        filename, _selected_filter = QFileDialog.getSaveFileName(
            self,
            "儲存波形圖片",
            f"{item.field_name}.png",
            "PNG Files (*.png)",
        )
        if not filename:
            return
        if not filename.lower().endswith(".png"):
            filename = f"{filename}.png"
        try:
            ImageExporter(item.plot.plotItem).export(filename)
        except Exception as exc:  # pragma: no cover - depends on Qt/OS exporter failures
            QMessageBox.warning(self, "儲存失敗", f"無法儲存圖片：{exc}")

    def _ensure_series(self, item: ChartItem, state: DeviceState, address: str) -> DeviceSeries:
        if address in item.series:
            return item.series[address]
        color = self._pens[len(item.series) % len(self._pens)]
        label = self._device_label(state)
        curve = item.plot.plot([], [], pen=pg.mkPen(color, width=1.6), name=label)
        series = DeviceSeries(address=address, label=label, curve=curve)
        item.series[address] = series
        return series

    @staticmethod
    def _finite_values(values: list[float]) -> list[float]:
        return [value for value in values if math.isfinite(value)]

    def _latest_chart_x(self, item: ChartItem) -> float | None:
        latest_values = [
            x_value
            for series in item.series.values()
            for x_value in series.x
            if math.isfinite(x_value)
        ]
        return max(latest_values) if latest_values else None

    def _align_series_to_latest(self, item: ChartItem, series: DeviceSeries) -> None:
        latest_x = self._latest_chart_x(item)
        if latest_x is None:
            return
        target_index = int(latest_x) + 1
        if target_index <= series.sample_index:
            return
        if series.x and target_index - 1 > series.x[-1]:
            series.x.append(float(target_index - 1))
            series.y.append(math.nan)
        series.sample_index = target_index

    def _append_sample(
        self,
        item: ChartItem,
        state: DeviceState,
        address: str,
        *,
        align_to_latest: bool = False,
    ) -> None:
        series = self._ensure_series(item, state, address)
        if align_to_latest:
            self._align_series_to_latest(item, series)
        try:
            value = float(state.get_value(item.field_name))
        except ValueError:
            value = 0.0
        series.x.append(float(series.sample_index))
        series.y.append(value)
        series.sample_index += 1
        max_samples = self._history_limit()
        if len(series.x) > max_samples:
            series.x = series.x[-max_samples:]
            series.y = series.y[-max_samples:]
        self._refresh_chart_display(item)

    def refresh_device(
        self,
        state: DeviceState,
        states: dict[str, DeviceState] | None = None,
        active_address: str = "",
    ) -> None:
        address = self._state_address(state, active_address)
        if states is None:
            states = {address: state}
        elif address not in states:
            states = {**states, address: state}
        self.set_devices(states, active_address or address)
        if self.pause_box.isChecked():
            self.notice.setText("已暫停")
            return
        if not state.is_connected:
            return
        self.notice.setText("波形即時顯示")
        align_to_latest = address in self._resumed_addresses
        for item in self.charts:
            self._append_sample(item, state, address, align_to_latest=align_to_latest)
        self._resumed_addresses.discard(address)

    def refresh(self, state: DeviceState) -> None:
        address = self._state_address(state)
        self.refresh_device(state, {address: state}, address)

    def _apply_device_filter(self) -> None:
        for item in self.charts:
            self._refresh_chart_display(item)

    def _refresh_chart_display(self, item: ChartItem) -> None:
        selected_addresses = self._selected_addresses()
        visible_series: list[DeviceSeries] = []
        for address, series in item.series.items():
            visible = address in selected_addresses
            series.curve.setVisible(visible)
            series.curve.setData(series.x if visible else [], series.y if visible else [])
            if visible:
                visible_series.append(series)
        visible_with_data = {series.address for series in visible_series if series.y}
        if visible_with_data:
            self._held_addresses = visible_with_data
        legend = item.plot.plotItem.legend
        if legend is not None:
            legend.clear()
            for series in visible_series:
                legend.addItem(series.curve, series.label)
        if visible_series:
            item.curve = visible_series[0].curve
            item.x = visible_series[0].x
            item.y = visible_series[0].y
            title_suffix = visible_series[0].label if len(visible_series) == 1 else "全部裝置"
            item.plot.setTitle(f"{item.label} - {title_suffix}")
        else:
            item.curve = None
            item.x = []
            item.y = []
            item.plot.setTitle(item.label)
        self._update_plot_window(item)
        self._update_stats(item, visible_series)
        if self.delta_box.isChecked() and (item.a_x is not None or item.b_x is not None):
            self._update_delta_labels_for(item)
            self._render_chart_delta_text(item)

    def _update_plot_window(self, item: ChartItem) -> None:
        visible = [series for address, series in item.series.items() if address in self._selected_addresses() and series.x]
        if not visible:
            return
        right = max(series.x[-1] for series in visible)
        max_samples = self._history_limit()
        left = max(0.0, right - max_samples + 1)
        item.plot.setXRange(left, max(right, left + 1), padding=0.01)

    def _style_plot(self, plot: pg.PlotWidget) -> None:
        t = self._tokens
        plot.setBackground(t.plot_bg)
        plot.getAxis("bottom").setPen(t.plot_axis)
        plot.getAxis("left").setPen(t.plot_axis)
        plot.getAxis("bottom").setTextPen(t.plot_axis_text)
        plot.getAxis("left").setTextPen(t.plot_axis_text)

    def _style_legend(self, legend) -> None:
        t = self._tokens
        bg = pg.mkColor(t.plot_bg)
        bg.setAlpha(200)
        legend.setBrush(pg.mkBrush(bg))
        legend.setPen(pg.mkPen(t.plot_legend_pen))

    def _style_card(self, card: QWidget) -> None:
        t = self._tokens
        card.setStyleSheet(
            f"""
            QWidget#waveformCard {{
                background: {t.surface_alt};
                border: 1px solid {t.card_border};
                border-radius: 6px;
            }}
            """
        )

    def _apply_theme(self, tokens: ThemeTokens) -> None:
        self._tokens = tokens
        self.notice.setStyleSheet(f"color: {tokens.text_secondary};")

    def _on_theme_changed(self, tokens: ThemeTokens) -> None:
        self._apply_theme(tokens)
        for card in self._chart_cards:
            self._style_card(card)
        for title in self._chart_titles:
            title.setStyleSheet(f"font-weight: 700; color: {tokens.text_primary};")
        for item in self.charts:
            self._style_plot(item.plot)
            # Recreate the legend so its colors update.
            try:
                legend = item.plot.plotItem.legend
            except AttributeError:
                legend = None
            if legend is not None:
                self._style_legend(legend)
            item.stats_label.setStyleSheet(
                f"color: {tokens.text_secondary}; font-family: Consolas;"
            )
            if item.cursor_label is not None:
                item.cursor_label.setStyleSheet(
                    f"color: {tokens.text_secondary}; font-family: Consolas;"
                )
            crosshair_pen = pg.mkPen(tokens.plot_axis_text, width=1, style=Qt.PenStyle.DashLine)
            if item.vline is not None:
                item.vline.setPen(crosshair_pen)
            if item.hline is not None:
                item.hline.setPen(crosshair_pen)
            self._apply_delta_highlight_style(item)

    def _update_stats(self, item: ChartItem, visible_series: list[DeviceSeries] | None = None) -> None:
        if visible_series is None:
            visible_series = [
                series for address, series in item.series.items() if address in self._selected_addresses()
            ]
        visible_with_data = [series for series in visible_series if self._finite_values(series.y)]
        if not visible_with_data:
            item.stats_label.setText("latest --   min --   max --   samples 0")
            return
        show_region = (
            self.region_box.isChecked()
            and item.region is not None
            and item.region.isVisible()
        )
        region_lo = region_hi = None
        if show_region and item.region is not None:
            r1, r2 = item.region.getRegion()
            region_lo, region_hi = (r1, r2) if r1 <= r2 else (r2, r1)
        lines = []
        for series in visible_with_data:
            values = self._finite_values(series.y)
            latest = values[-1]
            line = (
                f"{series.label}: latest {latest:.2f}   min {min(values):.2f}   "
                f"max {max(values):.2f}   samples {len(values)}"
            )
            if region_lo is not None and region_hi is not None:
                in_range = [
                    series.y[i]
                    for i, xv in enumerate(series.x)
                    if region_lo <= xv <= region_hi and math.isfinite(series.y[i])
                ]
                if in_range:
                    rmin = min(in_range)
                    rmax = max(in_range)
                    line += (
                        f"   框選[{region_lo:.0f}~{region_hi:.0f}]: "
                        f"min {rmin:.2f}  max {rmax:.2f}  Δ {rmax - rmin:.2f}  n={len(in_range)}"
                    )
                else:
                    line += f"   框選[{region_lo:.0f}~{region_hi:.0f}]: --"
            lines.append(line)
        item.stats_label.setText("\n".join(lines))
