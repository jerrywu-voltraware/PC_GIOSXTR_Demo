"""Application settings dialog."""

from __future__ import annotations

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..constants import APP_NAME, APP_VERSION


class SettingsDialog(QDialog):
    engineering_mode_changed = pyqtSignal(bool)
    demo_settings_changed = pyqtSignal(bool, int, int, str)
    check_updates_requested = pyqtSignal()

    def __init__(
        self,
        *,
        engineering_mode: bool,
        demo_use_fake_data: bool = True,
        demo_device_name: str = "MMEU",
        demo_ebike_pct: int = 76,
        demo_escooter_pct: int = 81,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setMinimumWidth(380)

        root = QVBoxLayout(self)
        tabs = QTabWidget()
        tabs.addTab(self._about_tab(), "About")
        tabs.addTab(self._demo_tab(demo_use_fake_data, demo_device_name, demo_ebike_pct, demo_escooter_pct), "DEMO")
        tabs.addTab(self._engineering_tab(engineering_mode), "Engineering")
        root.addWidget(tabs)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _about_tab(self) -> QWidget:
        page = QWidget()
        layout = QFormLayout(page)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        app_label = QLabel(APP_NAME)
        app_label.setStyleSheet("font-weight: 800;")
        version_label = QLabel(APP_VERSION)
        self.update_check_button = QPushButton("Check for updates")
        self.update_check_button.clicked.connect(self.check_updates_requested.emit)

        layout.addRow("Application", app_label)
        layout.addRow("Version", version_label)
        layout.addRow("", self.update_check_button)
        return page

    def set_update_checking(self, checking: bool) -> None:
        self.update_check_button.setEnabled(not checking)
        self.update_check_button.setText("Checking..." if checking else "Check for updates")

    def _engineering_tab(self, engineering_mode: bool) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(8)

        self.engineering_box = QCheckBox("Enable engineering controls")
        self.engineering_box.setChecked(engineering_mode)
        self.engineering_box.toggled.connect(self.engineering_mode_changed.emit)
        layout.addWidget(self.engineering_box)

        detail = QLabel("Engineering mode shows internal DEMO controls for development and validation.")
        detail.setWordWrap(True)
        detail.setStyleSheet("color: #66757C;")
        layout.addWidget(detail)
        layout.addStretch(1)
        return page

    def _demo_tab(self, use_fake_data: bool, device_name: str, ebike_pct: int, escooter_pct: int) -> QWidget:
        page = QWidget()
        layout = QFormLayout(page)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        self.demo_fake_data_box = QCheckBox("Use fake demo data when no live device data is available")
        self.demo_fake_data_box.setChecked(use_fake_data)
        self.demo_fake_data_box.toggled.connect(self._emit_demo_settings)
        layout.addRow("Data source", self.demo_fake_data_box)

        self.demo_device_name_edit = QLineEdit()
        self.demo_device_name_edit.setText(device_name)
        self.demo_device_name_edit.setPlaceholderText("MMEU")
        self.demo_device_name_edit.textChanged.connect(self._emit_demo_settings)
        layout.addRow("Demo device name", self.demo_device_name_edit)

        self.demo_ebike_spin = QSpinBox()
        self.demo_ebike_spin.setRange(0, 100)
        self.demo_ebike_spin.setSuffix(" %")
        self.demo_ebike_spin.setValue(ebike_pct)
        self.demo_ebike_spin.valueChanged.connect(self._emit_demo_settings)
        layout.addRow("EBIKE battery", self.demo_ebike_spin)

        self.demo_escooter_spin = QSpinBox()
        self.demo_escooter_spin.setRange(0, 100)
        self.demo_escooter_spin.setSuffix(" %")
        self.demo_escooter_spin.setValue(escooter_pct)
        self.demo_escooter_spin.valueChanged.connect(self._emit_demo_settings)
        layout.addRow("ESCOOTER battery", self.demo_escooter_spin)

        detail = QLabel("These values drive the DEMO page preview when fake data is enabled.")
        detail.setWordWrap(True)
        detail.setStyleSheet("color: #66757C;")
        layout.addRow("", detail)
        return page

    def _emit_demo_settings(self, *_args) -> None:
        self.demo_settings_changed.emit(
            self.demo_fake_data_box.isChecked(),
            self.demo_ebike_spin.value(),
            self.demo_escooter_spin.value(),
            self.demo_device_name_edit.text().strip() or "MMEU",
        )
