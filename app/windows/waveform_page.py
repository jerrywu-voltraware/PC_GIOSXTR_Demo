"""Live waveform page using pyqtgraph."""

from __future__ import annotations

from dataclasses import dataclass, field

import pyqtgraph as pg
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ..constants import SIGNAL_DEFINITIONS
from ..models import DeviceState


@dataclass
class ChartItem:
    label: str
    field_name: str
    plot: pg.PlotWidget
    curve: pg.PlotDataItem
    stats_label: QLabel
    x: list[float] = field(default_factory=list)
    y: list[float] = field(default_factory=list)
    sample_index: int = 0


class WaveformPage(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.charts: list[ChartItem] = []
        self._pens = ("#2BA7FF", "#29D398", "#F2C94C", "#FF7A59", "#B084F5")
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        controls = QHBoxLayout()
        controls.setSpacing(8)
        self.signal_combo = QComboBox()
        for label, field_name in SIGNAL_DEFINITIONS:
            self.signal_combo.addItem(label, field_name)
        self.add_btn = QPushButton("Add Trace")
        self.add_btn.clicked.connect(self.add_chart)
        self.pause_box = QCheckBox("Pause")
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
        self.reset_btn = QPushButton("Reset All")
        self.reset_btn.clicked.connect(self.reset_all)
        controls.addWidget(QLabel("Signal"))
        controls.addWidget(self.signal_combo, 1)
        controls.addWidget(self.add_btn)
        controls.addWidget(self.pause_box)
        controls.addWidget(QLabel("History"))
        controls.addWidget(self.history_combo)
        controls.addWidget(self.reset_btn)
        root.addLayout(controls)

        self.notice = QLabel("Scope live")
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

    def set_connected(self, connected: bool) -> None:
        if not connected:
            self._disconnected_hold = True
            self.notice.setText("Disconnected")
        elif self._disconnected_hold:
            self.notice.setText("Scope live")
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
        pen = pg.mkPen(self._pens[len(self.charts) % len(self._pens)], width=1.6)
        plot = pg.PlotWidget(title=label)
        plot.setMinimumHeight(230)
        plot.setBackground("#081015")
        plot.showGrid(x=True, y=True, alpha=0.28)
        plot.setLabel("bottom", "Sample")
        plot.setLabel("left", label)
        plot.setMouseEnabled(x=True, y=True)
        plot.setDownsampling(auto=True, mode="peak")
        plot.setClipToView(True)
        plot.getAxis("bottom").setPen("#8EA2AD")
        plot.getAxis("left").setPen("#8EA2AD")
        plot.getAxis("bottom").setTextPen("#B9C7CE")
        plot.getAxis("left").setTextPen("#B9C7CE")
        curve = plot.plot([], [], pen=pen, name=label)
        stats_label = QLabel("latest --   min --   max --   samples 0")
        stats_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        stats_label.setStyleSheet("color: #52616A; font-family: Consolas;")
        item = ChartItem(label=label, field_name=field_name, plot=plot, curve=curve, stats_label=stats_label)
        remove_btn = QPushButton("Remove")
        reset_btn = QPushButton("Reset")
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
        top.addWidget(reset_btn)
        top.addWidget(remove_btn)
        card_layout.addLayout(top)
        card_layout.addWidget(plot)
        self.container_layout.insertWidget(self.container_layout.count() - 1, card)
        item.plot.setProperty("card", card)
        remove_btn.clicked.connect(lambda: self.remove_chart(item))
        reset_btn.clicked.connect(lambda: self.reset_chart(item))
        self.charts.append(item)

    def remove_chart(self, item: ChartItem) -> None:
        if item in self.charts:
            self.charts.remove(item)
        card = item.plot.property("card")
        if card is not None:
            card.deleteLater()

    def reset_chart(self, item: ChartItem) -> None:
        item.x.clear()
        item.y.clear()
        item.sample_index = 0
        item.curve.setData([], [])
        item.stats_label.setText("latest --   min --   max --   samples 0")

    def reset_all(self) -> None:
        for item in self.charts:
            self.reset_chart(item)

    def _apply_history_window(self) -> None:
        max_samples = self._history_limit()
        for item in self.charts:
            if len(item.x) > max_samples:
                item.x = item.x[-max_samples:]
                item.y = item.y[-max_samples:]
                item.curve.setData(item.x, item.y)
                self._update_plot_window(item, max_samples)
                self._update_stats(item)

    def refresh(self, state: DeviceState) -> None:
        self.set_connected(state.is_connected)
        if self.pause_box.isChecked():
            self.notice.setText("Paused")
            return
        if not state.is_connected:
            return
        self.notice.setText("Scope live")
        max_samples = self._history_limit()
        for item in self.charts:
            try:
                value = float(state.get_value(item.field_name))
            except ValueError:
                value = 0.0
            item.x.append(float(item.sample_index))
            item.y.append(value)
            item.sample_index += 1
            if len(item.x) > max_samples:
                item.x = item.x[-max_samples:]
                item.y = item.y[-max_samples:]
            item.curve.setData(item.x, item.y)
            self._update_plot_window(item, max_samples)
            self._update_stats(item)

    def _update_plot_window(self, item: ChartItem, max_samples: int) -> None:
        if not item.x:
            return
        right = item.x[-1]
        left = max(0.0, right - max_samples + 1)
        item.plot.setXRange(left, max(right, left + 1), padding=0.01)

    def _update_stats(self, item: ChartItem) -> None:
        if not item.y:
            item.stats_label.setText("latest --   min --   max --   samples 0")
            return
        latest = item.y[-1]
        item.stats_label.setText(
            f"latest {latest:.2f}   min {min(item.y):.2f}   max {max(item.y):.2f}   samples {len(item.y)}"
        )
