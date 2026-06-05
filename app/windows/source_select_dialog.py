"""Startup dialog: choose the data source (PC Bluetooth vs Nordic dongle)."""

from __future__ import annotations

from dataclasses import dataclass

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

# Nordic Semiconductor USB Vendor ID (nRF52840 dongle CDC).
NORDIC_VID = 0x1915

SOURCE_PC = "pc"
SOURCE_DONGLE = "dongle"


@dataclass
class SourceSelection:
    """Result of the source-selection dialog."""

    source: str  # SOURCE_PC | SOURCE_DONGLE
    port: str | None = None  # serial port device for the dongle, e.g. "COM5"


def list_serial_ports() -> list[tuple[str, str, bool]]:
    """Return [(device, label, is_nordic)] for the available serial ports.

    Kept import-tolerant: if pyserial is unavailable the list is simply empty.
    """
    try:
        from serial.tools import list_ports
    except Exception:
        return []

    ports: list[tuple[str, str, bool]] = []
    for info in list_ports.comports():
        is_nordic = getattr(info, "vid", None) == NORDIC_VID
        description = (info.description or "").strip()
        label = f"{info.device} — {description}" if description else info.device
        if is_nordic:
            label += "  (Nordic)"
        ports.append((info.device, label, is_nordic))
    # Show likely-dongle ports first.
    ports.sort(key=lambda item: (not item[2], item[0]))
    return ports


class SourceSelectDialog(QDialog):
    """Modal startup dialog returning a :class:`SourceSelection`."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("選擇連線方式")
        self.setModal(True)
        self.setMinimumWidth(420)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 16)
        layout.setSpacing(10)

        title = QLabel("請選擇本次使用的資料來源：")
        title.setStyleSheet("font-weight: 600;")
        layout.addWidget(title)

        self._group = QButtonGroup(self)

        self._pc_radio = QRadioButton("PC 內建藍牙")
        self._pc_radio.setChecked(True)
        self._group.addButton(self._pc_radio)
        layout.addWidget(self._pc_radio)
        pc_hint = QLabel("使用電腦內建/USB 藍牙介面卡，直接連線裝置（現有方式）。")
        pc_hint.setStyleSheet("color: #666; margin-left: 24px;")
        layout.addWidget(pc_hint)

        self._dongle_radio = QRadioButton("Nordic dongle")
        self._group.addButton(self._dongle_radio)
        layout.addWidget(self._dongle_radio)
        dongle_hint = QLabel("無內建藍牙時，透過 nRF52840 dongle 連線裝置。")
        dongle_hint.setStyleSheet("color: #666; margin-left: 24px;")
        layout.addWidget(dongle_hint)

        # COM port chooser (only meaningful for the dongle).
        self._port_combo = QComboBox()
        self._port_combo.setEnabled(False)
        self._refresh_btn = QPushButton("重新整理")
        self._refresh_btn.setEnabled(False)
        port_row = QWidget()
        from PyQt6.QtWidgets import QHBoxLayout  # local import keeps top tidy

        port_layout = QHBoxLayout(port_row)
        port_layout.setContentsMargins(24, 0, 0, 0)
        port_layout.addWidget(QLabel("序列埠："))
        port_layout.addWidget(self._port_combo, 1)
        port_layout.addWidget(self._refresh_btn)
        layout.addWidget(port_row)

        self._buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        layout.addWidget(self._buttons)

        self._pc_radio.toggled.connect(self._update_port_enabled)
        self._dongle_radio.toggled.connect(self._update_port_enabled)
        self._refresh_btn.clicked.connect(self._reload_ports)
        self._buttons.accepted.connect(self._on_accept)
        self._buttons.rejected.connect(self.reject)

        self._selection: SourceSelection | None = None
        self._reload_ports()

    # -- internals -----------------------------------------------------------

    def _update_port_enabled(self) -> None:
        is_dongle = self._dongle_radio.isChecked()
        self._port_combo.setEnabled(is_dongle)
        self._refresh_btn.setEnabled(is_dongle)

    def _reload_ports(self) -> None:
        self._port_combo.clear()
        ports = list_serial_ports()
        if not ports:
            self._port_combo.addItem("找不到序列埠", userData=None)
            return
        for device, label, _is_nordic in ports:
            self._port_combo.addItem(label, userData=device)

    def _on_accept(self) -> None:
        if self._dongle_radio.isChecked():
            port = self._port_combo.currentData()
            if not port:
                from PyQt6.QtWidgets import QMessageBox

                QMessageBox.warning(self, "無序列埠", "未偵測到 dongle 序列埠，請插入後重新整理。")
                return
            self._selection = SourceSelection(SOURCE_DONGLE, str(port))
        else:
            self._selection = SourceSelection(SOURCE_PC, None)
        self.accept()

    # -- public --------------------------------------------------------------

    def selection(self) -> SourceSelection | None:
        return self._selection

    @staticmethod
    def ask(parent: QWidget | None = None) -> SourceSelection | None:
        dialog = SourceSelectDialog(parent)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            return dialog.selection()
        return None
