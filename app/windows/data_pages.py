"""PTU, PRU, and charger data table pages."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QBrush, QColor
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..models import DeviceState
from ..theme import ThemeTokens, current_tokens, theme_manager


class DataTablePage(QWidget):
    def __init__(self, title: str, parent=None) -> None:
        super().__init__(parent)
        self.title = title
        root = QVBoxLayout(self)
        self._title_label = QLabel(title)
        root.addWidget(self._title_label)
        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["Field", "Value"])
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        root.addWidget(self.table, 1)
        self._last_rows: list[tuple[str, str]] = []
        self._apply_theme(current_tokens())
        theme_manager().theme_changed.connect(self._on_theme_changed)

    def _apply_theme(self, tokens: ThemeTokens) -> None:
        self._tokens = tokens
        self._title_label.setStyleSheet(
            f"font-size: 18px; font-weight: 700; color: {tokens.text_primary};"
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

    def _on_theme_changed(self, tokens: ThemeTokens) -> None:
        self._apply_theme(tokens)
        if self._last_rows:
            self.set_rows(self._last_rows)

    def set_rows(self, rows: list[tuple[str, str]]) -> None:
        self._last_rows = list(rows)
        field_brush = QBrush(QColor(self._tokens.accent))
        value_brush = QBrush(QColor(self._tokens.text_primary))
        self.table.setRowCount(len(rows))
        for row, (field, value) in enumerate(rows):
            for col, text in enumerate((field, value)):
                item = QTableWidgetItem(text)
                if col == 0:
                    item.setForeground(field_brush)
                else:
                    item.setForeground(value_brush)
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.table.setItem(row, col, item)

    def refresh(self, state: DeviceState) -> None:
        raise NotImplementedError


class PtuPage(DataTablePage):
    def __init__(self, parent=None) -> None:
        super().__init__("PTU", parent)

    def refresh(self, state: DeviceState) -> None:
        self.set_rows(
            [
                ("SYS_STATE", state.ptu_system_state_string),
                ("FW_Version", str(state.ptu_firmware_version)),
                ("Array_Level", str(state.ptu_array_level)),
                ("V_IN", f"{state.ptu_input_voltage} mV"),
                ("I_IN", f"{state.ptu_input_current} mA"),
                ("Power", f"{state.input_power_w:.2f} W"),
                ("V_BUS", f"{state.ptu_bus_voltage} mV"),
                ("I_BUS", f"{state.ptu_bus_current} mA"),
                ("DCDC_Duty", str(state.ptu_dcdc_duty)),
                ("T_BUS", f"{state.bus_temp_deg_c} C"),
                ("T_AMP", f"{state.amp_temp_deg_c} C"),
                ("T_IC", f"{state.ic_temp_deg_c} C"),
                ("V1_Voltage", f"{state.v1_voltage * 10} mV"),
                ("I1_Deg", f"{state.i1_deg} deg"),
                ("I3_Current", f"{state.i3_current} mA"),
                ("I3_Deg", f"{state.i3_deg} deg"),
                ("I1I3_Deg", f"{state.i1_i3_phase_diff_deg} deg"),
                ("PTU_MAC", state.ptu_mac or "-"),
                ("System_EFF", f"{state.system_eff:.2f} %"),
            ]
        )


class PruPage(DataTablePage):
    def __init__(self, parent=None) -> None:
        super().__init__("PRU", parent)

    def refresh(self, state: DeviceState) -> None:
        self.set_rows(
            [
                ("SYS_STATE", state.pru_reg_item_state_string),
                ("Type", state.pru_type_string or "-"),
                ("FW_Version", str(state.pru_firmware_version)),
                ("PRU_MAC", state.pru_mac or "-"),
                ("V_Rect", f"{state.pru_dyn_vrect} mV"),
                ("I_Rect", f"{state.pru_dyn_irect} mA"),
                ("V_Out", f"{state.pru_dyn_vout} mV"),
                ("I_Out", f"{state.pru_dyn_iout} mA"),
                ("Power", f"{state.output_power_w:.2f} W"),
                ("T_Sys", f"{state.pru_dyn_temp} C"),
                ("Vrect_Min", f"{state.pru_dyn_vrect_min} mV"),
                ("Vrect_Set", f"{state.pru_dyn_vrect_set} mV"),
                ("Vrect_Max", f"{state.pru_dyn_vrect_max} mV"),
                ("System_EFF", f"{state.system_eff:.2f} %"),
            ]
        )
