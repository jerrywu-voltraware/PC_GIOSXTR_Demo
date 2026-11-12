"""Compare page: mix different signals (and devices) in one table + stacked plots."""

from __future__ import annotations

import bisect
import json
import time
from collections import deque
from dataclasses import asdict, dataclass

import pyqtgraph as pg
from PyQt6.QtCore import QSettings, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..models import DeviceState
from ..theme import ThemeTokens, current_tokens, theme_manager
from ..typography import font_size, scaled_px

COMPARE_SETTINGS_KEY = "compare/entries"
BUFFER_MAXLEN = 12000  # about 10 minutes at 20 samples/s
RENDER_INTERVAL_MS = 100
EMPTY_HINT = "在 PTU / PRU 分頁的欄位上按右鍵 →「加入比較」"
TIME_WINDOWS = (("30 秒", 30), ("1 分", 60), ("5 分", 300), ("10 分", 600))
PALETTE = (
    "#1F77B4", "#FF7F0E", "#2CA02C", "#D62728", "#9467BD",
    "#8C564B", "#E377C2", "#17BECF", "#BCBD22", "#7F7F7F",
)

# (source, row label) -> (field_name, unit). Rows not listed are not comparable.
COMPARABLE_FIELDS: dict[tuple[str, str], tuple[str, str]] = {
    ("PTU", "Array_Level"): ("ptuArrayLevel", ""),
    ("PTU", "V_IN"): ("ptuInputVoltage", "mV"),
    ("PTU", "I_IN"): ("ptuInputCurrent", "mA"),
    ("PTU", "Power"): ("inputPower", "W"),
    ("PTU", "V_BUS"): ("ptuBusVoltage", "mV"),
    ("PTU", "I_BUS"): ("ptuBusCurrent", "mA"),
    ("PTU", "DCDC_Duty"): ("ptuDcdcDuty", ""),
    ("PTU", "T_BUS"): ("busTempDegC", "C"),
    ("PTU", "T_AMP"): ("ampTempDegC", "C"),
    ("PTU", "T_IC"): ("icTempDegC", "C"),
    ("PTU", "V1_Voltage"): ("v1Voltage", "mV"),
    ("PTU", "I1_Deg"): ("i1Deg", "deg"),
    ("PTU", "I3_Current"): ("i3Current", "mA"),
    ("PTU", "I3_Deg"): ("i3Deg", "deg"),
    ("PTU", "I1I3_Deg"): ("i1I3PhaseDiffDeg", "deg"),
    ("PTU", "System_EFF"): ("systemEff", "%"),
    ("PRU", "V_Rect"): ("pruDynVrect", "mV"),
    ("PRU", "I_Rect"): ("pruDynIrect", "mA"),
    ("PRU", "V_Out"): ("pruDynVout", "mV"),
    ("PRU", "I_Out"): ("pruDynIout", "mA"),
    ("PRU", "Power"): ("pruOutputPower", "W"),
    ("PRU", "T_Sys"): ("pruDynTemp", "C"),
    ("PRU", "Vrect_Min"): ("pruDynVrectMin", "mV"),
    ("PRU", "Vrect_Set"): ("pruDynVrectSet", "mV"),
    ("PRU", "Vrect_Max"): ("pruDynVrectMax", "mV"),
    ("PRU", "System_EFF"): ("systemEff", "%"),
}


def comparable_field(source: str, row_label: str) -> tuple[str, str] | None:
    return COMPARABLE_FIELDS.get((source, row_label))


@dataclass
class CompareEntry:
    address: str
    device_label: str
    source: str
    row_label: str
    field_name: str
    unit: str

    @property
    def key(self) -> tuple[str, str]:
        return (self.address, self.field_name)

    @property
    def signal_name(self) -> str:
        return f"{self.source} {self.row_label}"

    @property
    def legend_name(self) -> str:
        return f"{self.row_label} @ {self.device_label}"


def device_label(state: DeviceState, fallback: str = "") -> str:
    name = state.device_name.strip() or state.device_address or fallback or "目前裝置"
    if state.device_number is not None and "#" not in name:
        name = f"{name}#{state.device_number}"
    return name


def load_entries(settings: QSettings | None = None) -> list[CompareEntry]:
    """Read the saved list. Any malformed content yields an empty/partial list."""
    settings = settings or QSettings()
    try:
        raw = settings.value(COMPARE_SETTINGS_KEY, "")
        data = json.loads(str(raw or "[]"))
        if not isinstance(data, list):
            return []
    except (ValueError, TypeError):
        return []
    entries: list[CompareEntry] = []
    seen: set[tuple[str, str]] = set()
    for item in data:
        try:
            entry = CompareEntry(
                address=str(item["address"]),
                device_label=str(item["device_label"]),
                source=str(item["source"]),
                row_label=str(item["row_label"]),
                field_name=str(item["field_name"]),
                unit=str(item["unit"]),
            )
        except (KeyError, TypeError):
            continue
        if entry.key not in seen:
            seen.add(entry.key)
            entries.append(entry)
    return entries


def save_entries(entries: list[CompareEntry], settings: QSettings | None = None) -> None:
    settings = settings or QSettings()
    settings.setValue(COMPARE_SETTINGS_KEY, json.dumps([asdict(e) for e in entries], ensure_ascii=False))


COL_COLOR, COL_SIGNAL, COL_DEVICE, COL_CURRENT, COL_MIN, COL_MAX, COL_AVG, COL_CURSOR, COL_SHOW, COL_REMOVE = range(10)
HEADERS = ["", "訊號", "裝置", "目前值", "最小", "最大", "平均", "游標值", "顯示", ""]


class ComparePage(QWidget):
    entries_changed = pyqtSignal()

    def __init__(self, parent=None, settings: QSettings | None = None) -> None:
        super().__init__(parent)
        self._settings = settings
        self._t0 = time.monotonic()
        self._entries: list[CompareEntry] = []
        self._colors: dict[tuple[str, str], str] = {}
        self._hidden: set[tuple[str, str]] = set()
        self._samples: dict[tuple[str, str], deque] = {}
        self._connected: dict[str, bool] = {}
        self._paused = False
        self._dirty = False
        self._window_s = 60
        self._cursor_t: float | None = None
        self._plots: dict[str, pg.PlotWidget] = {}
        self._curves: dict[tuple[str, str], pg.PlotDataItem] = {}
        self._vlines: list[pg.InfiniteLine] = []
        self._tokens = current_tokens()

        root = QVBoxLayout(self)
        bar = QHBoxLayout()
        self.pause_btn = QPushButton("暫停")
        self.pause_btn.setCheckable(True)
        self.pause_btn.toggled.connect(self._on_pause)
        self.clear_btn = QPushButton("清除資料")
        self.clear_btn.clicked.connect(self.clear_data)
        self.remove_all_btn = QPushButton("全部移除")
        self.remove_all_btn.clicked.connect(self.remove_all)
        self.window_combo = QComboBox()
        for text, secs in TIME_WINDOWS:
            self.window_combo.addItem(text, secs)
        self.window_combo.setCurrentIndex(1)
        self.window_combo.currentIndexChanged.connect(self._on_window_changed)
        self.crosshair_check = QCheckBox("十字準線")
        self.crosshair_check.setChecked(True)
        self.crosshair_check.toggled.connect(self._on_crosshair_toggled)
        self.save_btn = QPushButton("存圖")
        self.save_btn.clicked.connect(self._on_save_clicked)
        for w in (self.pause_btn, self.clear_btn, self.remove_all_btn, QLabel("時間窗"), self.window_combo,
                  self.crosshair_check, self.save_btn):
            bar.addWidget(w)
        bar.addStretch(1)
        root.addLayout(bar)

        self.empty_label = QLabel(EMPTY_HINT)
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(self.empty_label)

        self.table = QTableWidget(0, len(HEADERS))
        self.table.setHorizontalHeaderLabels(HEADERS)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setStretchLastSection(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.table.setMaximumHeight(scaled_px(260))
        root.addWidget(self.table)

        self.plot_container = QWidget()
        self.plot_layout = QVBoxLayout(self.plot_container)
        self.plot_layout.setContentsMargins(0, 0, 0, 0)
        root.addWidget(self.plot_container, 1)

        self._render_timer = QTimer(self)
        self._render_timer.setInterval(RENDER_INTERVAL_MS)
        self._render_timer.timeout.connect(self._on_render_tick)
        self._render_timer.start()

        for entry in load_entries(self._settings):
            self._add_internal(entry)
        self._rebuild_structure()
        self._apply_theme(self._tokens)
        theme_manager().theme_changed.connect(self._on_theme_changed)

    # ---- entry management -------------------------------------------------
    @property
    def entries(self) -> list[CompareEntry]:
        return list(self._entries)

    def has_entry(self, address: str, field_name: str) -> bool:
        return (address, field_name) in self._samples

    def _add_internal(self, entry: CompareEntry) -> bool:
        if entry.key in self._samples:
            return False
        used = set(self._colors.values())
        color = next((c for c in PALETTE if c not in used), PALETTE[len(self._entries) % len(PALETTE)])
        self._colors[entry.key] = color
        self._samples[entry.key] = deque(maxlen=BUFFER_MAXLEN)
        self._entries.append(entry)
        return True

    def add_entry(self, entry: CompareEntry) -> bool:
        if not self._add_internal(entry):
            return False
        self._after_structure_change()
        return True

    def remove_entry(self, key: tuple[str, str]) -> bool:
        if key not in self._samples:
            return False
        self._entries = [e for e in self._entries if e.key != key]
        self._samples.pop(key, None)
        self._colors.pop(key, None)
        self._hidden.discard(key)
        self._after_structure_change()
        return True

    def remove_all(self) -> None:
        if not self._entries:
            return
        self._entries.clear()
        self._samples.clear()
        self._colors.clear()
        self._hidden.clear()
        self._after_structure_change()

    def _after_structure_change(self) -> None:
        save_entries(self._entries, self._settings)
        self._rebuild_structure()
        self.entries_changed.emit()

    def clear_data(self) -> None:
        for buf in self._samples.values():
            buf.clear()
        self._t0 = time.monotonic()
        self._cursor_t = None
        self._dirty = True
        self.render()

    # ---- data in ----------------------------------------------------------
    def feed(self, address: str, state: DeviceState, now: float | None = None) -> None:
        """Record one sample for every entry bound to `address`."""
        t = (time.monotonic() if now is None else now) - self._t0
        hit = False
        for entry in self._entries:
            if entry.address != address:
                continue
            try:
                value = float(state.get_value(entry.field_name))
            except (TypeError, ValueError):
                continue
            self._samples[entry.key].append((t, value))
            hit = True
        if hit:
            self._dirty = True

    def set_devices(self, states: dict[str, DeviceState], active_address: str = "") -> None:
        changed = False
        for address, state in states.items():
            self._connected[address] = state.is_connected
            label = device_label(state, address)
            for entry in self._entries:
                if entry.address == address and entry.device_label != label:
                    entry.device_label = label
                    changed = True
        if changed:
            self._rebuild_structure()
        self._dirty = True

    # ---- stats ------------------------------------------------------------
    def _latest_t(self) -> float:
        return max((buf[-1][0] for buf in self._samples.values() if buf), default=0.0)

    def stats(self, key: tuple[str, str]) -> tuple[float, float, float, float] | None:
        """(current, min, max, avg) over the current time window, or None."""
        buf = self._samples.get(key)
        if not buf:
            return None
        start = self._latest_t() - self._window_s
        values = [v for t, v in buf if t >= start]
        if not values:
            return None
        return buf[-1][1], min(values), max(values), sum(values) / len(values)

    def cursor_value(self, key: tuple[str, str], t: float | None = None) -> float | None:
        t = self._cursor_t if t is None else t
        buf = self._samples.get(key)
        if t is None or not buf:
            return None
        times = [s[0] for s in buf]
        i = bisect.bisect_left(times, t)
        candidates = [j for j in (i - 1, i) if 0 <= j < len(times)]
        best = min(candidates, key=lambda j: abs(times[j] - t))
        return buf[best][1]

    @staticmethod
    def format_value(value: float, unit: str) -> str:
        text = f"{value:.2f}" if unit in ("W", "%") else (str(int(value)) if value == int(value) else f"{value:.2f}")
        return f"{text} {unit}".strip()

    # ---- rendering --------------------------------------------------------
    def _on_render_tick(self) -> None:
        if self._dirty and not self._paused and self.isVisible():
            self.render()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self._dirty and not self._paused:
            self.render()

    def render(self) -> None:
        self._dirty = False
        latest = self._latest_t()
        for key, curve in self._curves.items():
            buf = self._samples.get(key)
            if buf:
                xs, ys = zip(*buf)
                curve.setData(list(xs), list(ys))
        first = next(iter(self._plots.values()), None)
        if first is not None and not self._paused:
            first.setXRange(max(0.0, latest - self._window_s), max(latest, 1.0), padding=0)
        self._refresh_table_values()

    def _refresh_table_values(self) -> None:
        for row, entry in enumerate(self._entries):
            connected = self._connected.get(entry.address, False)
            st = self.stats(entry.key)
            if st is None:
                texts = ["-", "-", "-", "-"]
            else:
                cur, lo, hi, avg = (self.format_value(v, entry.unit) for v in st)
                texts = [cur if connected else "-", lo, hi, avg]
            if not connected:
                texts[0] = "- (未連線)"
            cv = self.cursor_value(entry.key)
            texts.append("-" if cv is None else self.format_value(cv, entry.unit))
            for offset, text in enumerate(texts):
                item = self.table.item(row, COL_CURRENT + offset)
                if item is not None and item.text() != text:
                    item.setText(text)

    def _rebuild_structure(self) -> None:
        # Table
        self.table.setRowCount(len(self._entries))
        for row, entry in enumerate(self._entries):
            swatch = QTableWidgetItem("")
            swatch.setBackground(QColor(self._colors[entry.key]))
            self.table.setItem(row, COL_COLOR, swatch)
            self.table.setItem(row, COL_SIGNAL, QTableWidgetItem(entry.signal_name))
            self.table.setItem(row, COL_DEVICE, QTableWidgetItem(entry.device_label))
            for col in range(COL_CURRENT, COL_CURSOR + 1):
                item = QTableWidgetItem("-")
                item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.table.setItem(row, col, item)
            check = QCheckBox()
            check.setChecked(entry.key not in self._hidden)
            check.toggled.connect(lambda on, k=entry.key: self._on_show_toggled(k, on))
            self.table.setCellWidget(row, COL_SHOW, check)
            btn = QPushButton("移除")
            btn.clicked.connect(lambda _=False, k=entry.key: self.remove_entry(k))
            self.table.setCellWidget(row, COL_REMOVE, btn)
        has = bool(self._entries)
        self.empty_label.setVisible(not has)
        self.table.setVisible(has)
        self.plot_container.setVisible(has)

        # Plots: one per unit, X linked.
        while self.plot_layout.count():
            w = self.plot_layout.takeAt(0).widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        self._plots.clear()
        self._curves.clear()
        self._vlines.clear()
        master = None
        for entry in self._entries:
            if entry.unit in self._plots:
                continue
            plot = pg.PlotWidget()
            plot.setMinimumHeight(scaled_px(160))
            plot.showGrid(x=True, y=True, alpha=0.25)
            plot.setLabel("left", entry.unit or "(無單位)")
            plot.setLabel("bottom", "秒")
            plot.addLegend()
            plot.setMouseEnabled(x=True, y=True)
            if master is None:
                master = plot
            else:
                plot.setXLink(master)
            line = pg.InfiniteLine(angle=90, movable=False)
            line.setVisible(False)
            plot.addItem(line, ignoreBounds=True)
            self._vlines.append(line)
            plot.scene().sigMouseMoved.connect(lambda pos, p=plot: self._on_mouse_moved(p, pos))
            self._plots[entry.unit] = plot
            self.plot_layout.addWidget(plot, 1)
        for entry in self._entries:
            plot = self._plots[entry.unit]
            curve = plot.plot([], [], pen=pg.mkPen(self._colors[entry.key], width=2), name=entry.legend_name)
            curve.setVisible(entry.key not in self._hidden)
            self._curves[entry.key] = curve
        self._apply_plot_theme()
        self._dirty = True
        if self._entries:
            self.render()

    # ---- interaction ------------------------------------------------------
    def _on_pause(self, paused: bool) -> None:
        self._paused = paused
        self.pause_btn.setText("繼續" if paused else "暫停")
        if not paused:
            self.render()

    def _on_window_changed(self) -> None:
        self._window_s = int(self.window_combo.currentData())
        self.render()

    def _on_show_toggled(self, key: tuple[str, str], on: bool) -> None:
        if on:
            self._hidden.discard(key)
        else:
            self._hidden.add(key)
        curve = self._curves.get(key)
        if curve is not None:
            curve.setVisible(on)

    def _on_crosshair_toggled(self, on: bool) -> None:
        for line in self._vlines:
            line.setVisible(on and self._cursor_t is not None)
        if not on:
            self._cursor_t = None
            self._refresh_table_values()

    def _on_mouse_moved(self, plot: pg.PlotWidget, pos) -> None:
        if not self.crosshair_check.isChecked():
            return
        if not plot.sceneBoundingRect().contains(pos):
            return
        self.set_cursor(plot.plotItem.vb.mapSceneToView(pos).x())

    def set_cursor(self, t: float | None) -> None:
        self._cursor_t = t
        for line in self._vlines:
            if t is not None:
                line.setPos(t)
            line.setVisible(t is not None and self.crosshair_check.isChecked())
        self._refresh_table_values()

    def save_image(self, path: str) -> bool:
        return bool(self.plot_container.grab().save(path))

    def _on_save_clicked(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "存圖", "compare.png", "PNG (*.png)")
        if path:
            self.save_image(path)

    # ---- theme ------------------------------------------------------------
    def _on_theme_changed(self, tokens: ThemeTokens) -> None:
        self._apply_theme(tokens)

    def _apply_theme(self, tokens: ThemeTokens) -> None:
        self._tokens = tokens
        self.empty_label.setStyleSheet(f"font-size: {font_size(14)}; color: {tokens.text_secondary};")
        self.table.setStyleSheet(
            f"""
            QTableWidget {{
                font-size: {font_size(11)};
                background: {tokens.table_bg};
                alternate-background-color: {tokens.table_alt};
                border: 1px solid {tokens.card_border};
                gridline-color: {tokens.table_grid};
                color: {tokens.text_primary};
            }}
            QHeaderView::section {{
                background: {tokens.table_header_bg};
                border: 0;
                border-bottom: 1px solid {tokens.table_grid};
                padding: 4px;
                font-weight: 800;
                color: {tokens.text_secondary};
            }}
            """
        )
        self._apply_plot_theme()

    def _apply_plot_theme(self) -> None:
        t = self._tokens
        for plot in self._plots.values():
            plot.setBackground(t.plot_bg)
            for name in ("bottom", "left"):
                axis = plot.getAxis(name)
                axis.setPen(t.plot_axis)
                axis.setTextPen(t.plot_axis_text)
            legend = plot.plotItem.legend
            if legend is not None:
                bg = pg.mkColor(t.plot_bg)
                bg.setAlpha(200)
                legend.setBrush(pg.mkBrush(bg))
                legend.setPen(pg.mkPen(t.plot_legend_pen))
                legend.setLabelTextColor(t.plot_axis_text)
        for line in self._vlines:
            line.setPen(pg.mkPen(t.plot_axis_text, style=Qt.PenStyle.DashLine))
