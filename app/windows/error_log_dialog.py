"""Non-modal dialog that accumulates error notifications as a running list."""

from __future__ import annotations

from datetime import datetime

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
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
from ..protocol import error_description
from ..theme import ThemeTokens, current_tokens, theme_manager


class ErrorLogDialog(QDialog):
    """Accumulates error notifications instead of stacking modal dialogs.

    Each call to :meth:`append_error` adds one row at the bottom of the table.
    The dialog is non-modal so the user can keep interacting with the main
    window; closing the dialog only hides it — subsequent errors reopen it
    with the prior rows preserved.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("錯誤通知")
        self.setModal(False)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, False)
        self.resize(640, 360)

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)

        self.header = QLabel("錯誤通知 (0)")
        header_font = QFont()
        header_font.setBold(True)
        header_font.setPointSize(11)
        self.header.setFont(header_font)
        root.addWidget(self.header)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            ["時間", "代碼", "描述", "讀取值 / 條件值", "裝置"]
        )
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setAlternatingRowColors(True)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        root.addWidget(self.table, 1)

        button_row = QHBoxLayout()
        self.clear_button = QPushButton("清除清單")
        self.clear_button.clicked.connect(self._clear_rows)
        button_row.addWidget(self.clear_button)
        button_row.addStretch(1)
        self.button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        self.button_box.rejected.connect(self.close)
        self.button_box.accepted.connect(self.close)
        close_btn = self.button_box.button(QDialogButtonBox.StandardButton.Close)
        if close_btn is not None:
            close_btn.setText("關閉")
        button_row.addWidget(self.button_box)
        root.addLayout(button_row)

        self._tokens = current_tokens()
        self._apply_theme(self._tokens)
        theme_manager().theme_changed.connect(self._apply_theme)

    def append_error(self, state: DeviceState) -> None:
        code = state.error_num
        code_hex = f"0x{code:02X}"
        desc = error_description(code)
        timestamp = datetime.now().strftime("%H:%M:%S")
        if state.error_data != 0 or state.error_limit != 0:
            trigger = (
                f"{state.error_data} / {state.error_limit}"
                f"  ({state.error_data} > {state.error_limit})"
            )
        else:
            trigger = "-"
        device = ""
        if state.device_name and state.device_address:
            device = f"{state.device_name} ({state.device_address})"
        elif state.device_name:
            device = state.device_name
        elif state.device_address:
            device = state.device_address

        row = self.table.rowCount()
        self.table.insertRow(row)
        items = [
            QTableWidgetItem(timestamp),
            QTableWidgetItem(code_hex),
            QTableWidgetItem(desc),
            QTableWidgetItem(trigger),
            QTableWidgetItem(device),
        ]
        mono = QFont("Consolas")
        items[0].setFont(mono)
        items[1].setFont(mono)
        items[3].setFont(mono)
        items[1].setForeground(self._error_brush())
        for item in items:
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        for col, item in enumerate(items):
            self.table.setItem(row, col, item)

        self.table.scrollToBottom()
        self._update_header()

        if not self.isVisible():
            self.show()
        self.raise_()

    def _clear_rows(self) -> None:
        self.table.setRowCount(0)
        self._update_header()

    def _update_header(self) -> None:
        self.header.setText(f"錯誤通知 ({self.table.rowCount()})")

    def _error_brush(self):
        from PyQt6.QtGui import QBrush, QColor

        return QBrush(QColor(self._tokens.error_fg))

    def _apply_theme(self, tokens: ThemeTokens) -> None:
        self._tokens = tokens
        self.setStyleSheet(
            f"QDialog {{ background: {tokens.card_bg}; color: {tokens.text_primary}; }}"
        )
        self.header.setStyleSheet(f"color: {tokens.error_fg};")
        self.table.setStyleSheet(
            f"""
            QTableWidget {{
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
                padding: 6px;
                font-weight: 700;
                color: {tokens.text_secondary};
            }}
            """
        )
        brush = self._error_brush()
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 1)
            if item is not None:
                item.setForeground(brush)
