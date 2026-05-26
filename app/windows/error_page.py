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
from ..theme import ThemeTokens, current_tokens, theme_manager


class ErrorPage(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        self.title = QLabel("錯誤狀態")
        root.addWidget(self.title)

        self.banner = QFrame()
        self.banner.setObjectName("errorBanner")
        banner_layout = QHBoxLayout(self.banner)
        banner_layout.setContentsMargins(14, 12, 14, 12)
        banner_layout.setSpacing(12)

        self.banner_badge = QLabel("OK")
        self.banner_badge.setFixedWidth(54)
        self.banner_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        banner_layout.addWidget(self.banner_badge)

        banner_text = QVBoxLayout()
        banner_text.setSpacing(4)
        self.banner_code = QLabel("目前錯誤代碼: 0x00 (0)")
        self.banner_name = QLabel("ERROR_NONE")
        self.banner_desc = QLabel("無錯誤")
        banner_text.addWidget(self.banner_code)
        banner_text.addWidget(self.banner_name)
        banner_text.addWidget(self.banner_desc)
        banner_layout.addLayout(banner_text, 1)
        root.addWidget(self.banner)

        metrics = QGridLayout()
        metrics.setHorizontalSpacing(10)
        metrics.setVerticalSpacing(8)
        self.error_data_card = self._make_metric_card("讀取值 (Error Data1)", "0x0 (0)")
        self.error_limit_card = self._make_metric_card("條件值 (Error Data2)", "0x0 (0)")
        self.time_card = self._make_metric_card("Last Error Time", "-")
        self.device_card = self._make_metric_card("Device", "-")
        metrics.addWidget(self.error_data_card, 0, 0)
        metrics.addWidget(self.error_limit_card, 0, 1)
        metrics.addWidget(self.time_card, 0, 2)
        metrics.addWidget(self.device_card, 0, 3)
        root.addLayout(metrics)

        self.reference_label = QLabel("錯誤碼對照")
        root.addWidget(self.reference_label)

        self.table = QTableWidget(len(ERROR_CODES), 3)
        self.table.setHorizontalHeaderLabels(["Code", "Name", "Description"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.table.setAlternatingRowColors(True)
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

        self._last_is_error: bool = False
        self._last_code: int = 0
        self._apply_theme(current_tokens())
        theme_manager().theme_changed.connect(self._apply_theme)

    def _make_metric_card(self, label: str, value: str) -> QFrame:
        card = QFrame()
        card.setObjectName("metricCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(3)
        title = QLabel(label)
        title.setObjectName("metricTitle")
        value_label = QLabel(value)
        value_label.setObjectName("value")
        layout.addWidget(title)
        layout.addWidget(value_label)
        return card

    @staticmethod
    def _set_metric_value(card: QFrame, value: str) -> None:
        value_label = card.findChild(QLabel, "value")
        if value_label is not None:
            value_label.setText(value)

    def _apply_theme(self, tokens: ThemeTokens) -> None:
        self._tokens = tokens
        self.title.setStyleSheet(
            f"font-size: 20px; font-weight: 800; color: {tokens.text_primary};"
        )
        self.reference_label.setStyleSheet(
            f"font-size: 13px; font-weight: 800; color: {tokens.text_secondary};"
        )
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
                font-weight: 800;
                color: {tokens.text_secondary};
            }}
            """
        )
        for card in (self.error_data_card, self.error_limit_card, self.time_card, self.device_card):
            card.setStyleSheet(
                f"""
                QFrame#metricCard {{
                    background: {tokens.card_bg};
                    border: 1px solid {tokens.card_border};
                    border-radius: 6px;
                }}
                """
            )
            title_label = card.findChild(QLabel, "metricTitle")
            if title_label is not None:
                title_label.setStyleSheet(
                    f"font-size: 11px; color: {tokens.text_muted}; font-weight: 700;"
                )
            value_label = card.findChild(QLabel, "value")
            if value_label is not None:
                value_label.setStyleSheet(
                    f"font-size: 13px; color: {tokens.text_primary}; font-family: Consolas;"
                )
        self._set_banner_style(self._last_is_error)
        self._restyle_table_rows(self._last_code, self._last_is_error)

    def _set_banner_style(self, error: bool) -> None:
        tokens = getattr(self, "_tokens", current_tokens())
        if error:
            self.banner.setStyleSheet(
                f"QFrame#errorBanner {{ background: {tokens.error_bg};"
                f" border: 1px solid {tokens.error_border}; border-radius: 8px; }}"
            )
            self.banner_badge.setText("ERR")
            self.banner_badge.setStyleSheet(
                f"background: {tokens.error_badge_bg}; color: white;"
                f" border-radius: 6px; font-size: 18px; font-weight: 900;"
            )
            self.banner_code.setStyleSheet(
                f"font-size: 15px; font-weight: 800; color: {tokens.error_fg};"
            )
            self.banner_name.setStyleSheet(
                f"font-size: 12px; color: {tokens.error_fg}; font-family: Consolas;"
            )
            self.banner_desc.setStyleSheet(f"font-size: 12px; color: {tokens.error_fg};")
        else:
            self.banner.setStyleSheet(
                f"QFrame#errorBanner {{ background: {tokens.ok_bg};"
                f" border: 1px solid {tokens.ok_border}; border-radius: 8px; }}"
            )
            self.banner_badge.setText("OK")
            self.banner_badge.setStyleSheet(
                f"background: {tokens.ok_badge_bg}; color: white;"
                f" border-radius: 6px; font-size: 18px; font-weight: 900;"
            )
            self.banner_code.setStyleSheet(
                f"font-size: 15px; font-weight: 800; color: {tokens.ok_fg};"
            )
            self.banner_name.setStyleSheet(
                f"font-size: 12px; color: {tokens.ok_fg}; font-family: Consolas;"
            )
            self.banner_desc.setStyleSheet(f"font-size: 12px; color: {tokens.ok_fg};")

    def _restyle_table_rows(self, code: int, is_error: bool) -> None:
        tokens = getattr(self, "_tokens", current_tokens())
        highlight_bg = QBrush(QColor(tokens.table_highlight_bg))
        normal_bg = QBrush(QColor(tokens.table_bg))
        alt_bg = QBrush(QColor(tokens.table_alt))
        highlight_fg = QBrush(QColor(tokens.table_highlight_fg))
        normal_fg = QBrush(QColor(tokens.text_primary))
        for row, (row_code, _name, _desc) in enumerate(ERROR_CODES):
            hit = row_code == code
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

    def refresh(self, state: DeviceState) -> None:
        code = state.error_num
        is_error = code != 0
        self._last_code = code
        self._last_is_error = is_error
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

        self._restyle_table_rows(code, is_error)
        active_row = -1
        for row, (row_code, _name, _desc) in enumerate(ERROR_CODES):
            if row_code == code:
                active_row = row
                break
        if active_row >= 0 and is_error:
            self.table.scrollToItem(
                self.table.item(active_row, 0),
                QAbstractItemView.ScrollHint.PositionAtCenter,
            )
