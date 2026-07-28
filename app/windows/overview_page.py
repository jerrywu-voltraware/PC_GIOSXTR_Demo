"""Desktop overview page."""

from __future__ import annotations

from PyQt6.QtCore import QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..batch_log import (
    BATCH_DISPLAY_LINE_LIMIT,
    batch_log,
    batch_log_path,
    subscribe_batch_log,
)
from ..models import DeviceState
from ..theme import ThemeTokens, current_tokens, theme_manager


class OverviewPage(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        root = QVBoxLayout(self)
        title = QLabel("Overview")
        title.setStyleSheet("font-size: 20px; font-weight: 700;")
        root.addWidget(title)
        self.grid = QGridLayout()
        root.addLayout(self.grid)
        self.labels: dict[str, QLabel] = {}
        self._caption_labels: list[QLabel] = []
        fields = [
            ("Device", "device"),
            ("Connection", "connection"),
            ("PTU State", "ptu"),
            ("PRU State", "pru"),
            ("Input Power", "input"),
            ("Output Power", "output"),
            ("Efficiency", "eff"),
            ("Temperature", "temp"),
            ("Packets", "packets"),
            ("CSV", "csv"),
        ]
        for index, (caption, key) in enumerate(fields):
            row, col = divmod(index, 2)
            label = QLabel(caption)
            value = QLabel("-")
            self.grid.addWidget(label, row * 2, col)
            self.grid.addWidget(value, row * 2 + 1, col)
            self.labels[key] = value
            self._caption_labels.append(label)

        batch_header = QHBoxLayout()
        self.batch_title = QLabel("Batch Log")
        self.batch_title.setObjectName("batchLogTitle")
        self.batch_hint = QLabel(
            f"畫面最多 {BATCH_DISPLAY_LINE_LIMIT} 行；完整歷程保存在 batch.txt"
        )
        self.batch_hint.setObjectName("batchLogHint")
        self.batch_hint.setWordWrap(True)
        self.open_batch_log_button = QPushButton("開啟 batch.txt")
        self.open_batch_log_button.clicked.connect(self.open_batch_log)
        batch_header.addWidget(self.batch_title)
        batch_header.addWidget(self.batch_hint, 1)
        batch_header.addWidget(self.open_batch_log_button)
        root.addLayout(batch_header)

        self.batch_log_text = QPlainTextEdit()
        self.batch_log_text.setObjectName("batchLogText")
        self.batch_log_text.setReadOnly(True)
        self.batch_log_text.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.batch_log_text.setPlaceholderText("APP 狀態與錯誤會即時顯示在這裡。")
        self._batch_bus, initial_lines = subscribe_batch_log(
            self.append_batch_log_line
        )
        self._batch_visible_line_count = len(initial_lines)
        self.batch_log_text.setPlainText("\n".join(initial_lines))
        root.addWidget(self.batch_log_text, 1)
        self._apply_theme(current_tokens())
        theme_manager().theme_changed.connect(self._apply_theme)

    def _apply_theme(self, tokens: ThemeTokens) -> None:
        for label in self._caption_labels:
            label.setStyleSheet(f"font-weight: 700; color: {tokens.text_secondary};")
        value_style = (
            f"font-size: 16px; padding: 10px;"
            f" border: 1px solid {tokens.card_border};"
            f" background: {tokens.surface};"
            f" color: {tokens.text_primary};"
        )
        for value in self.labels.values():
            value.setStyleSheet(value_style)
        self.batch_title.setStyleSheet(
            f"font-size: 13px; font-weight: 800; color: {tokens.text_secondary};"
        )
        self.batch_hint.setStyleSheet(
            f"font-size: 11px; color: {tokens.text_muted};"
        )
        self.batch_log_text.setStyleSheet(
            f"font-family: Consolas, monospace; font-size: 11px;"
            f" border: 1px solid {tokens.card_border};"
            f" background: {tokens.surface}; color: {tokens.text_primary};"
        )

    def append_batch_log_line(self, line: str) -> None:
        if self._batch_visible_line_count >= BATCH_DISPLAY_LINE_LIMIT:
            self.batch_log_text.clear()
            self._batch_visible_line_count = 0
        self.batch_log_text.appendPlainText(line)
        self._batch_visible_line_count += 1
        scrollbar = self.batch_log_text.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def open_batch_log(self) -> None:
        path = batch_log_path()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8"):
                pass
        except OSError as exc:
            batch_log("FILES", f"Unable to create batch log {path}: {exc}", level="ERROR")
            QMessageBox.warning(self, "無法開啟 batch.txt", str(exc))
            return
        batch_log("FILES", f"Opening batch log: {path}")
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(path))):
            batch_log("FILES", f"System could not open batch log: {path}", level="ERROR")
            QMessageBox.warning(self, "無法開啟 batch.txt", f"請手動開啟：\n{path}")

    def set_csv_recording(self, is_recording: bool, path: str = "") -> None:
        self.labels["csv"].setText("Recording" if is_recording else "Stopped")
        if path:
            self.labels["csv"].setToolTip(path)

    def refresh(self, state: DeviceState) -> None:
        self.labels["device"].setText(f"{state.device_name or '-'}\n{state.device_address or '-'}")
        self.labels["connection"].setText("Connected" if state.is_connected else "Disconnected")
        self.labels["ptu"].setText(state.ptu_system_state_string)
        self.labels["pru"].setText(state.pru_reg_item_state_string)
        self.labels["input"].setText(f"{state.input_power_w:.2f} W")
        self.labels["output"].setText(f"{state.output_power_w:.2f} W")
        self.labels["eff"].setText(f"{state.system_eff:.2f} %")
        self.labels["temp"].setText(
            f"Bus {state.bus_temp_deg_c} C / Amp {state.amp_temp_deg_c} C / PRU {state.pru_dyn_temp} C"
        )
        self.labels["packets"].setText(
            f"IOT {state.packet_count_iot} / 20B {state.packet_count_20b} / 200B {state.packet_count_200b}"
        )
