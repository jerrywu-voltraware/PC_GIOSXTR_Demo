"""Live waveform page using pyqtgraph."""

from __future__ import annotations

from dataclasses import dataclass, field

import pyqtgraph as pg
from pyqtgraph.exporters import ImageExporter
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ..constants import SIGNAL_DEFINITIONS
from ..models import DeviceState


@dataclass
class DeviceSeries:
    address: str
    label: str
    curve: pg.PlotDataItem
    x: list[float] = field(default_factory=list)
    y: list[float] = field(default_factory=list)
    sample_index: int = 0


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


class WaveformPage(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.charts: list[ChartItem] = []
        self._pens = ("#2BA7FF", "#29D398", "#F2C94C", "#FF7A59", "#B084F5", "#56CCF2", "#EB5757", "#6FCF97")
        self._states: dict[str, DeviceState] = {}
        self._active_address = ""
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
        controls.addWidget(QLabel("歷史"))
        controls.addWidget(self.history_combo)
        controls.addWidget(self.reset_btn)
        root.addLayout(controls)

        self.notice = QLabel("波形即時顯示")
        self.notice.setStyleSheet("color: #52616A;")
        root.addWidget(self.notice)

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
        self._states = dict(states)
        self._active_address = active_address
        self._apply_device_filter()
        self.set_connected(any(state.is_connected for state in self._states.values()))

    def set_connected(self, connected: bool) -> None:
        if not connected:
            self._disconnected_hold = True
            self.notice.setText("未連線")
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
        plot.setBackground("#081015")
        plot.showGrid(x=True, y=True, alpha=0.28)
        plot.setLabel("bottom", "Sample")
        plot.setLabel("left", label)
        plot.setMouseEnabled(x=True, y=True)
        plot.setDownsampling(auto=True, mode="peak")
        plot.setClipToView(True)
        legend = plot.addLegend(offset=(12, 12))
        legend.setBrush(pg.mkBrush(8, 16, 21, 190))
        legend.setPen(pg.mkPen("#425866"))
        plot.getAxis("bottom").setPen("#8EA2AD")
        plot.getAxis("left").setPen("#8EA2AD")
        plot.getAxis("bottom").setTextPen("#B9C7CE")
        plot.getAxis("left").setTextPen("#B9C7CE")
        stats_label = QLabel("latest --   min --   max --   samples 0")
        stats_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        stats_label.setStyleSheet("color: #52616A; font-family: Consolas;")
        save_btn = QPushButton("儲存圖片")
        item = ChartItem(label=label, field_name=field_name, plot=plot, stats_label=stats_label, save_button=save_btn)
        remove_btn = QPushButton("移除")
        reset_btn = QPushButton("重設")
        card = QWidget()
        card.setObjectName("waveformCard")
        card.setStyleSheet(
            """
            QWidget#waveformCard {
                background: #F5F7F8;
                border: 1px solid #DCE5E9;
                border-radius: 6px;
            }
            """
        )
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(10, 8, 10, 10)
        card_layout.setSpacing(8)
        top = QHBoxLayout()
        title = QLabel(label)
        title.setStyleSheet("font-weight: 700; color: #1D3038;")
        top.addWidget(title)
        top.addWidget(stats_label, 1)
        top.addWidget(save_btn)
        top.addWidget(reset_btn)
        top.addWidget(remove_btn)
        card_layout.addLayout(top)
        card_layout.addWidget(plot)
        self.container_layout.insertWidget(self.container_layout.count() - 1, card)
        item.plot.setProperty("card", card)
        remove_btn.clicked.connect(lambda: self.remove_chart(item))
        reset_btn.clicked.connect(lambda: self.reset_chart(item))
        save_btn.clicked.connect(lambda: self.save_chart_image(item))
        self.charts.append(item)

    def remove_chart(self, item: ChartItem) -> None:
        if item in self.charts:
            self.charts.remove(item)
        card = item.plot.property("card")
        if card is not None:
            card.deleteLater()

    def reset_chart(self, item: ChartItem) -> None:
        for series in item.series.values():
            series.x.clear()
            series.y.clear()
            series.sample_index = 0
            series.curve.setData([], [])
        item.x = []
        item.y = []
        item.stats_label.setText("latest --   min --   max --   samples 0")

    def reset_all(self) -> None:
        for item in self.charts:
            self.reset_chart(item)

    def _apply_history_window(self) -> None:
        max_samples = self._history_limit()
        for item in self.charts:
            for series in item.series.values():
                if len(series.x) > max_samples:
                    series.x = series.x[-max_samples:]
                    series.y = series.y[-max_samples:]
            self._refresh_chart_display(item)

    def _selected_addresses(self) -> set[str]:
        if self.scope_combo.currentData() == "all":
            return {address for address, state in self._states.items() if state.is_connected}
        active_state = self._states.get(self._active_address)
        if active_state is None or not active_state.is_connected:
            return set()
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

    def _append_sample(self, item: ChartItem, state: DeviceState, address: str) -> None:
        series = self._ensure_series(item, state, address)
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
        for item in self.charts:
            self._append_sample(item, state, address)

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

    def _update_plot_window(self, item: ChartItem) -> None:
        visible = [series for address, series in item.series.items() if address in self._selected_addresses() and series.x]
        if not visible:
            return
        right = max(series.x[-1] for series in visible)
        max_samples = self._history_limit()
        left = max(0.0, right - max_samples + 1)
        item.plot.setXRange(left, max(right, left + 1), padding=0.01)

    def _update_stats(self, item: ChartItem, visible_series: list[DeviceSeries] | None = None) -> None:
        if visible_series is None:
            visible_series = [
                series for address, series in item.series.items() if address in self._selected_addresses()
            ]
        visible_with_data = [series for series in visible_series if series.y]
        if not visible_with_data:
            item.stats_label.setText("latest --   min --   max --   samples 0")
            return
        lines = []
        for series in visible_with_data:
            latest = series.y[-1]
            lines.append(
                f"{series.label}: latest {latest:.2f}   min {min(series.y):.2f}   "
                f"max {max(series.y):.2f}   samples {len(series.y)}"
            )
        item.stats_label.setText("\n".join(lines))
