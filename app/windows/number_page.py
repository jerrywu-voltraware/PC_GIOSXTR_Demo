"""Device number setting page."""

from __future__ import annotations

from typing import Callable

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)
from qasync import asyncSlot

from ..ble_manager import BleManager


class NumberPage(QWidget):
    log_message = pyqtSignal(str)

    def __init__(self, ble_provider: Callable[[], BleManager | None], parent=None) -> None:
        super().__init__(parent)
        self._ble_provider = ble_provider
        root = QVBoxLayout(self)
        title = QLabel("Device Number")
        title.setStyleSheet("font-size: 20px; font-weight: 700;")
        root.addWidget(title)
        hint = QLabel("Operates on the currently active connected device.")
        hint.setStyleSheet("color: #888;")
        root.addWidget(hint)
        row = QHBoxLayout()
        self.combo = QComboBox()
        for number in range(1, 255):
            self.combo.addItem(f"Number {number}", number)
        self.write_btn = QPushButton("Write")
        self.write_btn.clicked.connect(self.write_number)
        row.addWidget(self.combo, 1)
        row.addWidget(self.write_btn)
        root.addLayout(row)
        self.reset_btn = QPushButton("Reset to Default")
        self.reset_btn.clicked.connect(self.reset_number)
        root.addWidget(self.reset_btn)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        root.addWidget(self.status)
        root.addStretch(1)

    def _ble(self) -> BleManager | None:
        return self._ble_provider()

    @asyncSlot()
    async def write_number(self) -> None:
        ble = self._ble()
        if ble is None or not ble.is_connected:
            self.status.setText("No active connected device")
            return
        number = int(self.combo.currentData())
        self.write_btn.setEnabled(False)
        self.status.setText(f"Writing number {number} ...")
        try:
            await ble.write_device_number(number)
            self.status.setText(f"Number set to {number}")
            self.log_message.emit(f"Device number set to {number}")
            QMessageBox.information(
                self,
                "裝置編號已更新",
                f"裝置編號已設定為 {number}。\n將在下次掃描後看到新的編號。",
            )
        except Exception as exc:
            self.status.setText(f"Write failed: {exc}")
            self.log_message.emit(f"Device number write failed: {exc}")
        finally:
            self.write_btn.setEnabled(True)

    @asyncSlot()
    async def reset_number(self) -> None:
        ble = self._ble()
        if ble is None or not ble.is_connected:
            self.status.setText("No active connected device")
            return
        self.reset_btn.setEnabled(False)
        self.status.setText("Resetting device number ...")
        try:
            await ble.reset_device_number()
            self.status.setText("Device number reset to default")
            self.log_message.emit("Device number reset to default")
        except Exception as exc:
            self.status.setText(f"Reset failed: {exc}")
            self.log_message.emit(f"Device number reset failed: {exc}")
        finally:
            self.reset_btn.setEnabled(True)
