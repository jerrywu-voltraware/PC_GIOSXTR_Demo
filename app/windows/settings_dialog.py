"""Application settings dialog."""

from __future__ import annotations

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..constants import APP_NAME, APP_VERSION
from ..theme import THEME_DARK, THEME_LIGHT, theme_manager


class SettingsDialog(QDialog):
    engineering_mode_changed = pyqtSignal(bool)
    demo_settings_changed = pyqtSignal(bool, int, int, str, object)
    check_updates_requested = pyqtSignal()
    auto_reconnect_changed = pyqtSignal(bool)

    def __init__(
        self,
        *,
        engineering_mode: bool,
        auto_reconnect_enabled: bool = False,
        demo_use_fake_data: bool = True,
        demo_device_name: str = "MMEU",
        demo_ebike_pct: int = 76,
        demo_escooter_pct: int = 81,
        demo_device_battery_pcts: dict[str, int] | None = None,
        connected_demo_devices: list[dict[str, object]] | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("設定")
        self.setMinimumWidth(520)
        self.demo_device_battery_pcts = dict(demo_device_battery_pcts or {})
        self.connected_demo_devices = list(connected_demo_devices or [])
        self.demo_device_pct_spins: dict[str, QSpinBox] = {}

        root = QVBoxLayout(self)
        tabs = QTabWidget()
        tabs.addTab(self._about_tab(), "關於")
        tabs.addTab(self._appearance_tab(), "外觀")
        tabs.addTab(self._connection_tab(auto_reconnect_enabled), "連線")
        tabs.addTab(self._demo_tab(demo_use_fake_data, demo_device_name, demo_ebike_pct, demo_escooter_pct), "DEMO")
        tabs.addTab(self._engineering_tab(engineering_mode), "工程模式")
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
        self.update_check_button = QPushButton("檢查更新")
        self.update_check_button.clicked.connect(self.check_updates_requested.emit)

        layout.addRow("應用程式", app_label)
        layout.addRow("版本", version_label)
        layout.addRow("", self.update_check_button)
        return page

    def set_update_checking(self, checking: bool) -> None:
        self.update_check_button.setEnabled(not checking)
        self.update_check_button.setText("檢查中..." if checking else "檢查更新")

    def _appearance_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(8)

        current = theme_manager().name()
        self.theme_light_radio = QRadioButton("亮色系 (Light)")
        self.theme_dark_radio = QRadioButton("暗色系 (Dark)")
        self.theme_light_radio.setChecked(current != THEME_DARK)
        self.theme_dark_radio.setChecked(current == THEME_DARK)

        self._theme_group = QButtonGroup(self)
        self._theme_group.addButton(self.theme_light_radio)
        self._theme_group.addButton(self.theme_dark_radio)
        self.theme_light_radio.toggled.connect(self._on_theme_radio_toggled)
        self.theme_dark_radio.toggled.connect(self._on_theme_radio_toggled)

        layout.addWidget(self.theme_light_radio)
        layout.addWidget(self.theme_dark_radio)

        detail = QLabel("切換後立即套用，設定會自動記住，下次啟動時恢復。")
        detail.setWordWrap(True)
        layout.addWidget(detail)
        layout.addStretch(1)
        return page

    def _connection_tab(self, auto_reconnect_enabled: bool) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(8)

        self.auto_reconnect_box = QCheckBox("斷線後自動重新連線")
        self.auto_reconnect_box.setChecked(auto_reconnect_enabled)
        self.auto_reconnect_box.toggled.connect(self.auto_reconnect_changed.emit)
        layout.addWidget(self.auto_reconnect_box)

        detail = QLabel("僅在裝置意外斷線時啟動；使用者手動中斷連線時不會自動連回。")
        detail.setWordWrap(True)
        layout.addWidget(detail)
        layout.addStretch(1)
        return page

    def _on_theme_radio_toggled(self, _checked: bool) -> None:
        target = THEME_DARK if self.theme_dark_radio.isChecked() else THEME_LIGHT
        if theme_manager().name() != target:
            theme_manager().set_theme(target)

    def _engineering_tab(self, engineering_mode: bool) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(8)

        self.engineering_box = QCheckBox("啟用工程控制項")
        self.engineering_box.setChecked(engineering_mode)
        self.engineering_box.toggled.connect(self.engineering_mode_changed.emit)
        layout.addWidget(self.engineering_box)

        detail = QLabel("工程模式會顯示內部 DEMO 控制項，供開發與驗證使用。")
        detail.setWordWrap(True)
        layout.addWidget(detail)
        layout.addStretch(1)
        return page

    def _demo_tab(self, use_fake_data: bool, device_name: str, ebike_pct: int, escooter_pct: int) -> QWidget:
        page = QWidget()
        layout = QFormLayout(page)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        self.demo_fake_data_box = QCheckBox("沒有即時裝置資料時使用 DEMO 假資料")
        self.demo_fake_data_box.setChecked(use_fake_data)
        self.demo_fake_data_box.toggled.connect(self._emit_demo_settings)
        layout.addRow("資料來源", self.demo_fake_data_box)

        self.demo_device_name_edit = QLineEdit()
        self.demo_device_name_edit.setText(device_name)
        self.demo_device_name_edit.setPlaceholderText("MMEU")
        self.demo_device_name_edit.textChanged.connect(self._emit_demo_settings)
        layout.addRow("DEMO 裝置名稱", self.demo_device_name_edit)

        self.demo_ebike_spin = QSpinBox()
        self.demo_ebike_spin.setRange(0, 100)
        self.demo_ebike_spin.setSuffix(" %")
        self.demo_ebike_spin.setValue(ebike_pct)
        self.demo_ebike_spin.valueChanged.connect(self._emit_demo_settings)
        layout.addRow("EBIKE 電量", self.demo_ebike_spin)

        self.demo_escooter_spin = QSpinBox()
        self.demo_escooter_spin.setRange(0, 100)
        self.demo_escooter_spin.setSuffix(" %")
        self.demo_escooter_spin.setValue(escooter_pct)
        self.demo_escooter_spin.valueChanged.connect(self._emit_demo_settings)
        layout.addRow("ESCOOTER 電量", self.demo_escooter_spin)

        if self.connected_demo_devices:
            section = QLabel("已連線裝置假資料")
            section.setStyleSheet("font-weight: 800; padding-top: 8px;")
            layout.addRow("", section)
            for device in self.connected_demo_devices:
                address = str(device.get("address", "")).strip()
                if not address:
                    continue
                label = str(device.get("label", address)).strip() or address
                raw_default = device.get("default_pct", self.demo_ebike_spin.value())
                default_pct = raw_default if isinstance(raw_default, int) else self.demo_ebike_spin.value()
                spin = QSpinBox()
                spin.setRange(0, 100)
                spin.setSuffix(" %")
                spin.setValue(int(self.demo_device_battery_pcts.get(address, default_pct)))
                spin.valueChanged.connect(self._emit_demo_settings)
                self.demo_device_pct_spins[address] = spin
                layout.addRow(label, spin)

        detail = QLabel(
            "預設值會用於 DEMO 預覽；多裝置全螢幕模式會優先使用各已連線裝置的設定值。"
        )
        detail.setWordWrap(True)
        layout.addRow("", detail)
        return page

    def _device_battery_pcts(self) -> dict[str, int]:
        return {address: spin.value() for address, spin in self.demo_device_pct_spins.items()}

    def _emit_demo_settings(self, *_args) -> None:
        self.demo_settings_changed.emit(
            self.demo_fake_data_box.isChecked(),
            self.demo_ebike_spin.value(),
            self.demo_escooter_spin.value(),
            self.demo_device_name_edit.text().strip() or "MMEU",
            self._device_battery_pcts(),
        )
