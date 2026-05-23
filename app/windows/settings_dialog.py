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
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..constants import APP_NAME, APP_VERSION


class SettingsDialog(QDialog):
    engineering_mode_changed = pyqtSignal(bool)
    demo_settings_changed = pyqtSignal(bool, int, int, str)

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
        self.setWindowTitle("設定")
        self.setMinimumWidth(380)

        root = QVBoxLayout(self)
        tabs = QTabWidget()
        tabs.addTab(self._about_tab(), "關於")
        tabs.addTab(self._demo_tab(demo_use_fake_data, demo_device_name, demo_ebike_pct, demo_escooter_pct), "DEMO")
        tabs.addTab(self._engineering_tab(engineering_mode), "工程")
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
        layout.addRow("應用程式", app_label)
        layout.addRow("版本", version_label)
        return page

    def _engineering_tab(self, engineering_mode: bool) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(8)

        self.engineering_box = QCheckBox("啟用工程模式")
        self.engineering_box.setChecked(engineering_mode)
        self.engineering_box.toggled.connect(self.engineering_mode_changed.emit)
        layout.addWidget(self.engineering_box)

        detail = QLabel("工程模式會顯示 DEMO 頁面的內部測試按鈕，用於開發檢視。")
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

        self.demo_fake_data_box = QCheckBox("使用假資料（關閉後使用真實數據）")
        self.demo_fake_data_box.setChecked(use_fake_data)
        self.demo_fake_data_box.toggled.connect(self._emit_demo_settings)
        layout.addRow("資料來源", self.demo_fake_data_box)

        self.demo_device_name_edit = QLineEdit()
        self.demo_device_name_edit.setText(device_name)
        self.demo_device_name_edit.setPlaceholderText("MMEU")
        self.demo_device_name_edit.textChanged.connect(self._emit_demo_settings)
        layout.addRow("假資料裝置名稱", self.demo_device_name_edit)

        self.demo_ebike_spin = QSpinBox()
        self.demo_ebike_spin.setRange(0, 100)
        self.demo_ebike_spin.setSuffix(" %")
        self.demo_ebike_spin.setValue(ebike_pct)
        self.demo_ebike_spin.valueChanged.connect(self._emit_demo_settings)
        layout.addRow("EBIKE 電池數值", self.demo_ebike_spin)

        self.demo_escooter_spin = QSpinBox()
        self.demo_escooter_spin.setRange(0, 100)
        self.demo_escooter_spin.setSuffix(" %")
        self.demo_escooter_spin.setValue(escooter_pct)
        self.demo_escooter_spin.valueChanged.connect(self._emit_demo_settings)
        layout.addRow("ESCOOTER 電池數值", self.demo_escooter_spin)

        detail = QLabel("假資料只會套用在 DEMO 頁面的充電情境；切換為真實數據時會回到 PRU 電壓換算。")
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
