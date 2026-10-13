"""Always-visible recording health and controls for the selected device."""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout

from ..csv_logger import CsvLogger
from ..models import DeviceState
from ..theme import current_tokens, theme_manager


def format_duration(seconds: float) -> str:
    total = max(0, int(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


class RecordingPanel(QFrame):
    start_requested = pyqtSignal()
    stop_requested = pyqtSignal()
    open_folder_requested = pyqtSignal()
    choose_folder_requested = pyqtSignal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("recordingPanel")
        self._severity = "idle"
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 10)
        root.setSpacing(5)
        top = QHBoxLayout()
        self.status_label = QLabel("尚未錄製 · 請先連線裝置")
        self.status_label.setWordWrap(True)
        self.status_label.setMinimumWidth(0)
        top.addWidget(self.status_label, 1)
        self.start_button = QPushButton("開始錄製")
        self.start_button.setToolTip("開始錄製目前選取的裝置")
        self.start_button.clicked.connect(self.start_requested.emit)
        self.stop_button = QPushButton("停止")
        self.stop_button.setToolTip("停止錄製目前選取的裝置")
        self.stop_button.clicked.connect(self.stop_requested.emit)
        top.addWidget(self.start_button)
        top.addWidget(self.stop_button)
        root.addLayout(top)
        self.metrics_label = QLabel("本次 00:00:00 · 已寫入 0 筆")
        self.metrics_label.setWordWrap(True)
        self.metrics_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        root.addWidget(self.metrics_label)
        self.summary_label = QLabel()
        self.summary_label.setWordWrap(True)
        root.addWidget(self.summary_label)
        path_row = QHBoxLayout()
        self.path_edit = QLineEdit()
        self.path_edit.setReadOnly(True)
        self.path_edit.setAccessibleName("CSV 檔案或儲存資料夾")
        path_row.addWidget(self.path_edit, 1)
        self.open_button = QPushButton("開啟資料夾")
        self.open_button.clicked.connect(self.open_folder_requested.emit)
        path_row.addWidget(self.open_button)
        self.choose_button = QPushButton("變更…")
        self.choose_button.setToolTip("變更 CSV 儲存資料夾；所有錄製停止後可變更")
        self.choose_button.clicked.connect(self.choose_folder_requested.emit)
        path_row.addWidget(self.choose_button)
        root.addLayout(path_row)
        theme_manager().theme_changed.connect(self._apply_theme)
        self._apply_theme()

    def _apply_theme(self, _tokens=None) -> None:
        tokens = current_tokens()
        background, border, foreground = tokens.surface, tokens.card_border, tokens.text_primary
        if self._severity == "error":
            background, border, foreground = tokens.error_bg, tokens.error_border, tokens.error_fg
        elif self._severity == "recording":
            background, border, foreground = tokens.ok_bg, tokens.ok_border, tokens.ok_fg
        elif self._severity == "waiting":
            border, foreground = tokens.warning, tokens.warning
        self.setStyleSheet(
            f"QFrame#recordingPanel {{ background: {background}; border: 1px solid {border}; border-radius: 8px; }}"
        )
        self.status_label.setStyleSheet(f"font-weight: 700; color: {foreground};")
        self.summary_label.setStyleSheet(f"color: {tokens.text_secondary};")

    def refresh(
        self,
        state: DeviceState,
        logger: CsvLogger | None,
        directory: Path,
        *,
        recording_count: int,
        device_count: int,
        disconnected_count: int,
        error_count: int,
        error: str = "",
        other_error: str = "",
    ) -> None:
        recording = logger is not None and logger.is_recording
        name = state.device_name or state.device_address or "請先連線裝置"
        age = logger.seconds_since_write if logger is not None else None
        if error:
            status, severity = "錄製失敗", "error"
        elif recording and not state.is_connected:
            status, severity = "錄製等待重連（未寫入）", "waiting"
        elif recording and age is not None and age >= 10:
            status, severity = f"錄製中 · 已 {int(age)} 秒無新寫入", "waiting"
        elif recording and not logger.rows_written:
            status, severity = "錄製已開啟 · 等待可寫入資料", "waiting"
        elif recording:
            status, severity = "● 錄製中", "recording"
        elif logger is not None and logger.started_at is not None:
            status, severity = "已停止錄製", "idle"
        else:
            status, severity = "尚未錄製", "idle"
        self.status_label.setText(f"{status} · {name}")
        rows = logger.rows_written if logger is not None else 0
        elapsed = logger.elapsed_seconds if logger is not None else 0
        parts = logger.parts_created if logger is not None else 0
        last_write = logger.last_write_at.strftime("%H:%M:%S") if logger and logger.last_write_at else "尚無"
        self.metrics_label.setText(
            f"本次 {format_duration(elapsed)} · 已寫入 {rows:,} 筆 · {parts} 個分檔 · 最後寫入 {last_write}"
        )
        summary = f"全體：{recording_count} 台開啟錄製 / {device_count} 台裝置"
        if disconnected_count:
            summary += f" · {disconnected_count} 台錄製等待重連"
        if error_count:
            summary += f" · {error_count} 台錄製失敗"
            severity = "error"
        if error:
            summary += f"\n{error[:200]}；請檢查儲存位置後重新開始錄製。"
        elif other_error:
            summary += f"\n最近失敗：{other_error[:200]}"
        self.summary_label.setText(summary)
        self.summary_label.setToolTip(error or other_error)
        path = str(logger.current_path if recording and logger.current_path else directory)
        if self.path_edit.text() != path:
            self.path_edit.setText(path)
            self.path_edit.setCursorPosition(0)
        self.path_edit.setToolTip(path)
        if logger and logger.current_path:
            self.metrics_label.setToolTip(f"本次最後檔案：{logger.current_path}")
        else:
            self.metrics_label.setToolTip("")
        self.start_button.setEnabled(bool(state.is_connected) and not recording)
        self.stop_button.setEnabled(recording)
        self.choose_button.setEnabled(recording_count == 0)
        if self._severity != severity:
            self._severity = severity
            self._apply_theme()
