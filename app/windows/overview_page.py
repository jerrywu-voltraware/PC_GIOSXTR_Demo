"""Desktop overview page."""

from __future__ import annotations

from PyQt6.QtWidgets import QGridLayout, QLabel, QVBoxLayout, QWidget

from ..models import DeviceState


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
            label.setStyleSheet("font-weight: 700; color: #334;")
            value = QLabel("-")
            value.setStyleSheet(
                "font-size: 16px; padding: 10px; border: 1px solid #cfd6df; background: #f7f9fb;"
            )
            self.grid.addWidget(label, row * 2, col)
            self.grid.addWidget(value, row * 2 + 1, col)
            self.labels[key] = value
        root.addStretch(1)

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
