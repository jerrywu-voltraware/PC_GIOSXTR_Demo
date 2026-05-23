"""Error status page with current fault summary and code reference."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QBrush, QColor, QFont
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..constants import ERROR_CODES
from ..models import DeviceState
from ..protocol import error_description, error_name


class ErrorPage(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        title = QLabel("錯誤狀態")
        title.setStyleSheet("font-size: 20px; font-weight: 800; color: #1D3038;")
        root.addWidget(title)

        self.banner = QFrame()
        self.banner.setObjectName("errorBanner")
        banner_layout = QHBoxLayout(self.banner)
        banner_layout.setContentsMargins(14, 12, 14, 12)
        banner_layout.setSpacing(12)

        self.banner_badge = QLabel("OK")
        self.banner_badge.setFixedWidth(54)
        self.banner_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.banner_badge.setStyleSheet("font-size: 18px; font-weight: 900;")
        banner_layout.addWidget(self.banner_badge)

        banner_text = QVBoxLayout()
        banner_text.setSpacing(4)
        self.banner_code = QLabel("目前錯誤代碼: 0x00 (0)")
        self.banner_code.setStyleSheet("font-size: 15px; font-weight: 800;")
        self.banner_name = QLabel("ERROR_NONE")
        self.banner_name.setStyleSheet("font-size: 12px; font-family: Consolas;")
        self.banner_desc = QLabel("無錯誤")
        self.banner_desc.setStyleSheet("font-size: 12px;")
        banner_text.addWidget(self.banner_code)
        banner_text.addWidget(self.banner_name)
        banner_text.addWidget(self.banner_desc)
        banner_layout.addLayout(banner_text, 1)
        root.addWidget(self.banner)

        metrics = QGridLayout()
        metrics.setHorizontalSpacing(10)
        metrics.setVerticalSpacing(8)
        self.error_data_card = self._make_metric_card("Error Data", "0x0 (0)")
        self.error_limit_card = self._make_metric_card("Error Limit", "0x0 (0)")
        self.time_card = self._make_metric_card("Last Error Time", "-")
        self.device_card = self._make_metric_card("Device", "-")
        metrics.addWidget(self.error_data_card, 0, 0)
        metrics.addWidget(self.error_limit_card, 0, 1)
        metrics.addWidget(self.time_card, 0, 2)
        metrics.addWidget(self.device_card, 0, 3)
        root.addLayout(metrics)

        reference_label = QLabel("錯誤碼對照")
        reference_label.setStyleSheet("font-size: 13px; font-weight: 800; color: #40545B;")
        root.addWidget(reference_label)

        self.table = QTableWidget(len(ERROR_CODES), 3)
        self.table.setHorizontalHeaderLabels(["Code", "Name", "Description"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.table.setAlternatingRowColors(True)
        self.table.setStyleSheet(
            """
            QTableWidget {
                background: #FFFFFF;
                alternate-background-color: #F6F8F9;
                border: 1px solid #DDE7EA;
                gridline-color: #D6E0E4;
            }
            QHeaderView::section {
                background: #EDF3F5;
                border: 0;
                border-bottom: 1px solid #D6E0E4;
                padding: 6px;
                font-weight: 800;
                color: #31464F;
            }
            """
        )
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        for row, (code, name, desc) in enumerate(ERROR_CODES):
            code_item = QTableWidgetItem(f"0x{code:02X} ({code})")
            code_item.setFont(QFont("Consolas"))
            name_item = QTableWidgetItem(name)
            name_item.setFont(QFont("Consolas"))
            desc_item = QTableWidgetItem(desc)
            for item in (code_item, name_item, desc_item):
                item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            self.table.setItem(row, 0, code_item)
            self.table.setItem(row, 1, name_item)
            self.table.setItem(row, 2, desc_item)
        root.addWidget(self.table, 1)

        self._set_banner_style(error=False)

    def _make_metric_card(self, label: str, value: str) -> QFrame:
        card = QFrame()
        card.setObjectName("metricCard")
        card.setStyleSheet(
            """
            QFrame#metricCard {
                background: #FFFFFF;
                border: 1px solid #DDE7EA;
                border-radius: 6px;
            }
            """
        )
        layout = QVBoxLayout(card)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(3)
        title = QLabel(label)
        title.setStyleSheet("font-size: 11px; color: #6A7D84; font-weight: 700;")
        value_label = QLabel(value)
        value_label.setObjectName("value")
        value_label.setStyleSheet("font-size: 13px; color: #1D3038; font-family: Consolas;")
        layout.addWidget(title)
        layout.addWidget(value_label)
        return card

    @staticmethod
    def _set_metric_value(card: QFrame, value: str) -> None:
        value_label = card.findChild(QLabel, "value")
        if value_label is not None:
            value_label.setText(value)

    def _set_banner_style(self, error: bool) -> None:
        if error:
            self.banner.setStyleSheet(
                "QFrame#errorBanner { background: #FDECEA; border: 1px solid #E79D97; border-radius: 8px; }"
            )
            self.banner_badge.setText("ERR")
            self.banner_badge.setStyleSheet(
                "background: #C0392B; color: white; border-radius: 6px; font-size: 18px; font-weight: 900;"
            )
            self.banner_code.setStyleSheet("font-size: 15px; font-weight: 800; color: #A93226;")
            self.banner_name.setStyleSheet("font-size: 12px; color: #A93226; font-family: Consolas;")
            self.banner_desc.setStyleSheet("font-size: 12px; color: #7B241C;")
        else:
            self.banner.setStyleSheet(
                "QFrame#errorBanner { background: #E8F8F0; border: 1px solid #9AD7B4; border-radius: 8px; }"
            )
            self.banner_badge.setText("OK")
            self.banner_badge.setStyleSheet(
                "background: #1E8449; color: white; border-radius: 6px; font-size: 18px; font-weight: 900;"
            )
            self.banner_code.setStyleSheet("font-size: 15px; font-weight: 800; color: #166534;")
            self.banner_name.setStyleSheet("font-size: 12px; color: #166534; font-family: Consolas;")
            self.banner_desc.setStyleSheet("font-size: 12px; color: #255C3B;")

    def refresh(self, state: DeviceState) -> None:
        code = state.error_num
        is_error = code != 0
        self._set_banner_style(error=is_error)
        self.banner_code.setText(f"目前錯誤代碼: 0x{code:02X} ({code})")
        self.banner_name.setText(error_name(code))
        self.banner_desc.setText(error_description(code))
        self._set_metric_value(self.error_data_card, f"0x{state.error_data:X} ({state.error_data})")
        self._set_metric_value(self.error_limit_card, f"0x{state.error_limit:X} ({state.error_limit})")
        self._set_metric_value(self.time_card, state.latest_error_time or "-")
        device = state.device_name or state.device_address or "-"
        if state.device_number is not None:
            device = f"#{state.device_number} {device}"
        self._set_metric_value(self.device_card, device)

        highlight_bg = QBrush(QColor("#FADBD8"))
        normal_bg = QBrush(QColor("#FFFFFF"))
        alt_bg = QBrush(QColor("#F6F8F9"))
        highlight_fg = QBrush(QColor("#A93226"))
        normal_fg = QBrush(QColor("#1D3038"))
        active_row = -1
        for row, (row_code, _name, _desc) in enumerate(ERROR_CODES):
            hit = row_code == code
            if hit:
                active_row = row
            row_bg = highlight_bg if (hit and is_error) else (normal_bg if row % 2 == 0 else alt_bg)
            row_fg = highlight_fg if (hit and is_error) else normal_fg
            for col in range(3):
                item = self.table.item(row, col)
                if item is None:
                    continue
                item.setBackground(row_bg)
                item.setForeground(row_fg)
                font = item.font()
                font.setBold(hit and is_error)
                item.setFont(font)
        if active_row >= 0 and is_error:
            self.table.scrollToItem(self.table.item(active_row, 0), QAbstractItemView.ScrollHint.PositionAtCenter)
