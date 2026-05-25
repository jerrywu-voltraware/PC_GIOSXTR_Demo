"""Left-side BLE scan and connection panel."""

from __future__ import annotations

from PyQt6.QtCore import QSize, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)
from qasync import asyncSlot

from ..ble_adapter import AdapterStatus, check_bluetooth_adapter, user_facing_message
from ..ble_manager import BleManager, DeviceScanResult
from ..ble_manager import _write_scan_debug
from ..models import DeviceState
from ..recent_devices import RecentDevice


class ScanPanel(QWidget):
    device_connect_requested = pyqtSignal(object)
    selected_device_changed = pyqtSignal(object)
    disconnect_requested = pyqtSignal()
    disconnect_all_requested = pyqtSignal()
    active_changed = pyqtSignal(str)
    recording_start_requested = pyqtSignal()
    recording_stop_requested = pyqtSignal()
    recording_start_all_requested = pyqtSignal()
    recording_stop_all_requested = pyqtSignal()

    def __init__(self, ble: BleManager, parent=None) -> None:
        super().__init__(parent)
        self.ble = ble
        self.results: list[DeviceScanResult] = []
        self.recent_devices: list[RecentDevice] = []
        self._is_scanning = False
        self._adapter_available = True
        self._connected_addresses: set[str] = set()
        self._active_address: str = ""
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(10)
        self.setObjectName("scanPanel")
        self._apply_style()

        title = QLabel("藍牙裝置")
        title.setObjectName("panelTitle")
        root.addWidget(title)

        self.scan_state = QFrame()
        self.scan_state.setObjectName("scanState")
        scan_state_layout = QVBoxLayout(self.scan_state)
        scan_state_layout.setContentsMargins(12, 10, 12, 10)
        scan_state_layout.setSpacing(4)
        self.scan_state_title = QLabel("準備搜尋附近裝置")
        self.scan_state_title.setObjectName("scanStateTitle")
        self.scan_state_detail = QLabel("按下掃描後，只會顯示支援的 VOLTRAWARE 裝置。")
        self.scan_state_detail.setObjectName("scanStateDetail")
        self.scan_state_detail.setWordWrap(True)
        self.scan_progress = QProgressBar()
        self.scan_progress.setRange(0, 0)
        self.scan_progress.setTextVisible(False)
        self.scan_progress.setFixedHeight(4)
        self.scan_progress.hide()
        scan_state_layout.addWidget(self.scan_state_title)
        scan_state_layout.addWidget(self.scan_state_detail)
        scan_state_layout.addWidget(self.scan_progress)
        root.addWidget(self.scan_state)

        self.scan_btn = QPushButton("搜尋裝置")
        self.scan_btn.setObjectName("primaryButton")
        self.scan_btn.clicked.connect(self.scan)
        root.addWidget(self.scan_btn)

        self.list_widget = QListWidget()
        self.list_widget.setObjectName("deviceList")
        self.list_widget.itemDoubleClicked.connect(self.connect_selected)
        self.list_widget.currentItemChanged.connect(self._on_selection_changed)
        self.list_widget.setMinimumHeight(220)
        self.list_widget.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        root.addWidget(self.list_widget, 3)
        self._show_empty_result("尚未掃描", "按下搜尋裝置後，附近可連線的裝置會出現在這裡。")

        self.connect_btn = QPushButton("連線所選裝置")
        self.connect_btn.setObjectName("secondaryButton")
        self.connect_btn.clicked.connect(self.connect_selected)
        root.addWidget(self.connect_btn)

        connected_title = QLabel("已連線裝置")
        connected_title.setObjectName("sectionTitle")
        root.addWidget(connected_title)
        self.connected_list = QListWidget()
        self.connected_list.setObjectName("connectedList")
        self.connected_list.currentItemChanged.connect(self._on_connected_selection_changed)
        self.connected_list.setMinimumHeight(140)
        self.connected_list.setMaximumHeight(220)
        self.connected_list.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        root.addWidget(self.connected_list, 2)

        disc_row = QHBoxLayout()
        disc_row.setSpacing(8)
        self.disconnect_btn = QPushButton("中斷目前裝置")
        self.disconnect_btn.setObjectName("secondaryButton")
        self.disconnect_btn.clicked.connect(self.disconnect_requested.emit)
        disc_row.addWidget(self.disconnect_btn)
        self.disconnect_all_btn = QPushButton("中斷全部")
        self.disconnect_all_btn.setObjectName("secondaryButton")
        self.disconnect_all_btn.clicked.connect(self.disconnect_all_requested.emit)
        disc_row.addWidget(self.disconnect_all_btn)
        root.addLayout(disc_row)

        rec_active_row = QHBoxLayout()
        rec_active_row.setSpacing(8)
        self.start_recording_btn = QPushButton("開始錄製(目前)")
        self.start_recording_btn.setObjectName("secondaryButton")
        self.start_recording_btn.clicked.connect(self.recording_start_requested.emit)
        rec_active_row.addWidget(self.start_recording_btn)
        self.stop_recording_btn = QPushButton("停止錄製(目前)")
        self.stop_recording_btn.setObjectName("secondaryButton")
        self.stop_recording_btn.clicked.connect(self.recording_stop_requested.emit)
        rec_active_row.addWidget(self.stop_recording_btn)
        root.addLayout(rec_active_row)

        rec_all_row = QHBoxLayout()
        rec_all_row.setSpacing(8)
        self.start_recording_all_btn = QPushButton("開始錄製(全部)")
        self.start_recording_all_btn.setObjectName("secondaryButton")
        self.start_recording_all_btn.clicked.connect(self.recording_start_all_requested.emit)
        rec_all_row.addWidget(self.start_recording_all_btn)
        self.stop_recording_all_btn = QPushButton("停止錄製(全部)")
        self.stop_recording_all_btn.setObjectName("secondaryButton")
        self.stop_recording_all_btn.clicked.connect(self.recording_stop_all_requested.emit)
        rec_all_row.addWidget(self.stop_recording_all_btn)
        root.addLayout(rec_all_row)

        self.recording_status = QLabel("CSV:未錄製")
        self.recording_status.setObjectName("subtleStatus")
        self.recording_status.setWordWrap(True)
        root.addWidget(self.recording_status)

        self.status = QLabel("待機中")
        self.status.setObjectName("subtleStatus")
        self.status.setWordWrap(True)
        root.addWidget(self.status)

        self.advanced_title = QLabel("進階資料")
        self.advanced_title.setObjectName("sectionTitle")
        root.addWidget(self.advanced_title)
        self.adv_raw = QTextEdit()
        self.adv_raw.setObjectName("rawData")
        self.adv_raw.setReadOnly(True)
        self.adv_raw.setPlaceholderText("選擇裝置後顯示廣播資料")
        self.adv_raw.setMaximumHeight(52)
        root.addWidget(self.adv_raw)

        self.adv_table = QTableWidget(0, 3)
        self.adv_table.setObjectName("advTable")
        self.adv_table.setHorizontalHeaderLabels(["LEN", "TYPE", "VALUE"])
        self.adv_table.verticalHeader().setVisible(False)
        self.adv_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.adv_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        root.addWidget(self.adv_table, 2)
        self._set_advanced_visible(False)
        self.set_recording_state(False, False)

    def _apply_style(self) -> None:
        self.setStyleSheet(
            """
            QWidget#scanPanel {
                background: #F4F6F7;
                color: #172A31;
                font-size: 12px;
            }
            QLabel#panelTitle {
                font-size: 18px;
                font-weight: 800;
                color: #102A33;
                padding: 2px 0 4px 0;
            }
            QLabel#sectionTitle {
                font-size: 12px;
                font-weight: 800;
                color: #40545B;
                padding-top: 4px;
            }
            QFrame#scanState {
                background: #FFFFFF;
                border: 1px solid #DDE7EA;
                border-radius: 8px;
            }
            QLabel#scanStateTitle {
                font-size: 13px;
                font-weight: 800;
                color: #19343C;
            }
            QLabel#scanStateDetail, QLabel#subtleStatus {
                color: #6C7F86;
                font-size: 11px;
            }
            QPushButton {
                min-height: 26px;
                border-radius: 6px;
                padding: 4px 10px;
                font-weight: 700;
            }
            QPushButton#primaryButton {
                background: #4F6F7B;
                color: white;
                border: 1px solid #425F6A;
            }
            QPushButton#primaryButton:hover {
                background: #45636E;
            }
            QPushButton#primaryButton:disabled {
                background: #A9B7BC;
                border-color: #A9B7BC;
            }
            QPushButton#secondaryButton {
                background: #FFFFFF;
                color: #243B43;
                border: 1px solid #CEDBE0;
            }
            QPushButton#secondaryButton:hover {
                background: #EDF4F6;
            }
            QPushButton#secondaryButton:disabled {
                color: #AAB6BA;
                background: #F6F8F9;
            }
            QListWidget#deviceList, QListWidget#connectedList, QTextEdit#rawData, QTableWidget#advTable {
                background: #FFFFFF;
                border: 1px solid #DDE7EA;
                border-radius: 8px;
                padding: 4px;
                selection-background-color: #DDF7F4;
                selection-color: #102A33;
            }
            QListWidget::item {
                border-radius: 6px;
                margin: 2px;
            }
            QProgressBar {
                background: #E7EEF1;
                border: 0;
                border-radius: 2px;
            }
            QProgressBar::chunk {
                background: #25C7B7;
                border-radius: 2px;
            }
            QHeaderView::section {
                background: #F5F8F9;
                border: 0;
                border-bottom: 1px solid #DDE7EA;
                padding: 4px;
                font-weight: 700;
                color: #52656C;
            }
            """
        )

    def _set_scan_state(self, title: str, detail: str, *, busy: bool = False) -> None:
        self.scan_state_title.setText(title)
        self.scan_state_detail.setText(detail)
        self.status.setText(detail)
        self.scan_progress.setVisible(busy)

    def _set_advanced_visible(self, visible: bool) -> None:
        self.advanced_title.setVisible(visible)
        self.adv_raw.setVisible(visible)
        self.adv_table.setVisible(visible)

    def _show_empty_result(self, title: str, detail: str) -> None:
        self.list_widget.clear()
        item = QListWidgetItem()
        item.setFlags(Qt.ItemFlag.NoItemFlags)
        item.setSizeHint(QSize(320, 54))
        self.list_widget.addItem(item)

        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(2)
        title_label = QLabel(title)
        title_label.setStyleSheet("font-size: 12px; font-weight: 800; color: #52656C;")
        detail_label = QLabel(detail)
        detail_label.setWordWrap(True)
        detail_label.setStyleSheet("font-size: 11px; color: #8A9AA0;")
        layout.addWidget(title_label)
        layout.addWidget(detail_label)
        self.list_widget.setItemWidget(item, widget)

    def set_adapter_unavailable(self, _status: AdapterStatus, hint: str) -> None:
        """Disable scan controls and show an actionable adapter hint."""
        self._adapter_available = False
        self.scan_btn.setEnabled(False)
        self.scan_btn.setText("藍牙不可用")
        first_line = hint.splitlines()[0] if hint.splitlines() else hint
        self._set_scan_state("藍牙不可用", first_line)
        self._show_empty_result("藍牙不可用", hint)

    def set_adapter_available(self) -> None:
        self._adapter_available = True
        self.scan_btn.setText("搜尋裝置")
        self.scan_btn.setEnabled(not self._is_scanning)
        if self._is_scanning or self.results:
            return
        if self.recent_devices:
            self._show_recent_devices()
            return
        detail = "按下搜尋裝置後，只會顯示支援的 VOLTRAWARE 裝置。"
        self._show_empty_result("準備搜尋", detail)
        self._set_scan_state("準備搜尋附近裝置", detail)

    @staticmethod
    def _rssi_quality(rssi: int) -> str:
        if rssi >= -55:
            return "訊號佳"
        if rssi >= -70:
            return "訊號穩定"
        return "訊號較弱"

    def _add_scan_result(self, result: DeviceScanResult) -> None:
        item = QListWidgetItem()
        item.setData(Qt.ItemDataRole.UserRole, result)
        item.setSizeHint(QSize(320, 62))
        self.list_widget.addItem(item)

        is_connected = result.address in self._connected_addresses
        is_active = is_connected and result.address == self._active_address

        widget = QWidget()
        if is_active:
            widget.setStyleSheet("background: #DDF7F4; border-radius: 6px;")
        elif is_connected:
            widget.setStyleSheet("background: #EAF6F1; border-radius: 6px;")
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setSpacing(2)

        name_row = QHBoxLayout()
        name_row.setSpacing(6)
        name_text = result.name or "未命名裝置"
        name = QLabel(name_text)
        name_color = "#0E7A5F" if is_connected else "#19343C"
        name.setStyleSheet(f"font-size: 13px; font-weight: 800; color: {name_color};")
        name_row.addWidget(name, 1)

        if is_connected:
            badge_text = "● 連線中" if is_active else "● 已連線"
            badge = QLabel(badge_text)
            badge.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            badge.setStyleSheet("font-size: 10px; color: #0E7A5F; font-weight: 800;")
            name_row.addWidget(badge)

        quality = QLabel(f"{self._rssi_quality(result.rssi)}  {result.rssi} dBm")
        quality.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        quality.setStyleSheet("font-size: 10px; color: #4F6F7B; font-weight: 700;")
        name_row.addWidget(quality)

        address = QLabel(result.address)
        address.setStyleSheet("font-size: 10px; color: #7D9097;")

        layout.addLayout(name_row)
        layout.addWidget(address)
        self.list_widget.setItemWidget(item, widget)

    def _recent_to_scan_result(self, device: RecentDevice) -> DeviceScanResult:
        return DeviceScanResult(
            address=device.address,
            name=device.name,
            rssi=device.rssi,
            raw_hex="",
            advertising_rows=[],
            device_number=device.device_number,
            firmware_revision=None,
            device=None,
        )

    def set_recent_devices(self, devices: list[RecentDevice]) -> None:
        self.recent_devices = devices[:8]
        if not self.results and not self._is_scanning:
            self._show_recent_devices()

    def _show_recent_devices(self) -> None:
        if not self.recent_devices:
            self._show_empty_result("尚未掃描", "按下搜尋裝置後，附近可連線的裝置會出現在這裡。")
            return
        self.list_widget.clear()
        for device in self.recent_devices:
            self._add_recent_device(device)
        self._set_scan_state("可嘗試重新連線", "這些是最近連線過的裝置；若掃描不到，可以先選擇上一台裝置重新連線。")

    def _add_recent_device(self, device: RecentDevice) -> None:
        result = self._recent_to_scan_result(device)
        item = QListWidgetItem()
        item.setData(Qt.ItemDataRole.UserRole, result)
        item.setSizeHint(QSize(320, 62))
        self.list_widget.addItem(item)

        is_connected = device.address in self._connected_addresses
        is_active = is_connected and device.address == self._active_address

        widget = QWidget()
        if is_active:
            widget.setStyleSheet("background: #DDF7F4; border-radius: 6px;")
        elif is_connected:
            widget.setStyleSheet("background: #EAF6F1; border-radius: 6px;")
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setSpacing(2)

        name_row = QHBoxLayout()
        name_row.setSpacing(6)
        name = QLabel(device.name)
        name_color = "#0E7A5F" if is_connected else "#19343C"
        name.setStyleSheet(f"font-size: 13px; font-weight: 800; color: {name_color};")
        badge_text = "目前連線" if is_active else ("已連線" if is_connected else "最近連線")
        badge = QLabel(badge_text)
        badge.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        badge_color = "#0E7A5F" if is_connected else "#4F6F7B"
        badge.setStyleSheet(f"font-size: 10px; color: {badge_color}; font-weight: 800;")
        name_row.addWidget(name, 1)
        name_row.addWidget(badge)

        detail = QLabel(f"{device.address}  可直接嘗試連線")
        detail.setStyleSheet("font-size: 10px; color: #7D9097;")

        layout.addLayout(name_row)
        layout.addWidget(detail)
        self.list_widget.setItemWidget(item, widget)

    def _rebuild_recent_list(self) -> None:
        self.list_widget.blockSignals(True)
        current_addr = ""
        current = self.list_widget.currentItem()
        if current is not None:
            data = current.data(Qt.ItemDataRole.UserRole)
            if isinstance(data, DeviceScanResult):
                current_addr = data.address
        self.list_widget.clear()
        for device in self.recent_devices:
            self._add_recent_device(device)
        if current_addr:
            for i in range(self.list_widget.count()):
                data = self.list_widget.item(i).data(Qt.ItemDataRole.UserRole)
                if isinstance(data, DeviceScanResult) and data.address == current_addr:
                    self.list_widget.setCurrentRow(i)
                    break
        self.list_widget.blockSignals(False)

    @asyncSlot()
    async def scan(self) -> None:
        self._is_scanning = True
        self.scan_btn.setEnabled(False)
        self.list_widget.clear()
        self.adv_table.setRowCount(0)
        self.adv_raw.clear()
        self._set_advanced_visible(False)
        self._set_scan_state("正在搜尋附近裝置", "掃描約需 5 秒，請讓裝置靠近充電板。", busy=True)
        try:
            if not await self._adapter_ready_for_scan():
                return
            self.results = await self.ble.scan(timeout=5.0, supported_only=True)
            for result in self.results:
                self._add_scan_result(result)
            if self.results:
                self._set_scan_state(
                    "已找到可連線裝置",
                    f"找到 {len(self.results)} 個支援裝置，選擇後即可連線。",
                )
            else:
                if self.recent_devices:
                    self._show_recent_devices()
                    self._set_scan_state(
                        "沒有掃到新廣播",
                        "可能仍維持在上一個連線狀態。請選擇最近連線裝置嘗試重新連線。",
                    )
                else:
                    self._show_empty_result("沒有找到支援裝置", "請確認裝置已開機，並靠近充電板後再搜尋一次。")
                    self._set_scan_state("沒有找到支援裝置", "請確認裝置已開機，並靠近充電板後再搜尋一次。")
        except Exception as exc:
            QMessageBox.warning(self, "掃描失敗", str(exc))
            self._show_empty_result("掃描失敗", "藍牙掃描未完成，請確認藍牙已開啟後重試。")
            self._set_scan_state("掃描失敗", str(exc))
        finally:
            self._is_scanning = False
            self.scan_btn.setEnabled(self._adapter_available)
            self.scan_progress.hide()

    async def _adapter_ready_for_scan(self) -> bool:
        result = await check_bluetooth_adapter()
        _write_scan_debug(f"adapter check before scan: {result.status.value} {result.detail}")
        if result.status in (AdapterStatus.NO_ADAPTER, AdapterStatus.DISABLED):
            title, body = user_facing_message(result)
            QMessageBox.information(self, title, body)
            self.set_adapter_unavailable(result.status, body)
            return False
        if result.status is AdapterStatus.OK:
            self.set_adapter_available()
        elif result.status is AdapterStatus.UNKNOWN_ERROR:
            self.status.setText(f"藍牙狀態檢測失敗: {result.detail}")
        return True

    def _on_selection_changed(self, current: QListWidgetItem | None) -> None:
        if current is None:
            return
        result = current.data(Qt.ItemDataRole.UserRole)
        if not isinstance(result, DeviceScanResult):
            return
        self.selected_device_changed.emit(result)
        has_advanced = bool(result.raw_hex or result.advertising_rows)
        self._set_advanced_visible(has_advanced)
        self.adv_raw.setPlainText(result.raw_hex)
        self.adv_table.setRowCount(len(result.advertising_rows))
        for row, adv_row in enumerate(result.advertising_rows):
            for col, key in enumerate(("LEN", "TYPE", "VALUE")):
                self.adv_table.setItem(row, col, QTableWidgetItem(adv_row.get(key, "")))

    def connect_selected(self) -> None:
        item = self.list_widget.currentItem()
        if item is None:
            QMessageBox.information(self, "尚未選擇", "請先選擇一個裝置。")
            return
        result = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(result, DeviceScanResult):
            QMessageBox.information(self, "尚未選擇", "請先選擇一個裝置。")
            return
        self._set_scan_state("正在連線", f"正在連線 {result.name} ...")
        self.device_connect_requested.emit(result)

    def _on_connected_selection_changed(self, current: QListWidgetItem | None) -> None:
        if current is None:
            return
        address = current.data(Qt.ItemDataRole.UserRole)
        if isinstance(address, str) and address:
            self.active_changed.emit(address)

    def refresh(self, state: DeviceState) -> None:
        if self._is_scanning:
            return
        if not self._adapter_available:
            return
        if state.is_connected:
            self._set_scan_state(
                "目前裝置已連線",
                f"{state.device_name}  封包 {state.total_packet_count}",
            )
            self.status.setToolTip(state.device_address)
        else:
            self._set_scan_state("準備搜尋附近裝置", "按下搜尋裝置後，只會顯示支援的 VOLTRAWARE 裝置。")
            self.status.setToolTip("")

    def refresh_connected_devices(
        self,
        devices: list[dict[str, str]],
        active_address: str = "",
    ) -> None:
        new_connected = {dev.get("address", "") for dev in devices if dev.get("address")}
        connected_changed = (
            new_connected != self._connected_addresses
            or active_address != self._active_address
        )
        self._connected_addresses = new_connected
        self._active_address = active_address

        self.connected_list.blockSignals(True)
        self.connected_list.clear()
        for dev in devices:
            num = dev.get("device_number", "")
            num_part = f"#{num} " if num else ""
            rec_part = "  [錄製中]" if dev.get("recording") == "1" else ""
            label = f"{num_part}{dev.get('name', '')} ({dev.get('address', '')})  封包={dev.get('packets', '0')}{rec_part}"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, dev.get("address", ""))
            self.connected_list.addItem(item)
            if dev.get("address") == active_address:
                self.connected_list.setCurrentItem(item)
        self.connected_list.blockSignals(False)

        if connected_changed and not self._is_scanning:
            if self.results:
                self._rebuild_scan_list()
            elif self.recent_devices:
                self._rebuild_recent_list()

    def _rebuild_scan_list(self) -> None:
        self.list_widget.blockSignals(True)
        current_addr = ""
        current = self.list_widget.currentItem()
        if current is not None:
            data = current.data(Qt.ItemDataRole.UserRole)
            if isinstance(data, DeviceScanResult):
                current_addr = data.address
        self.list_widget.clear()
        for result in self.results:
            self._add_scan_result(result)
        if current_addr:
            for i in range(self.list_widget.count()):
                data = self.list_widget.item(i).data(Qt.ItemDataRole.UserRole)
                if isinstance(data, DeviceScanResult) and data.address == current_addr:
                    self.list_widget.setCurrentRow(i)
                    break
        self.list_widget.blockSignals(False)

    def set_recording_state(self, connected: bool, recording: bool, path: str = "") -> None:
        self.start_recording_btn.setEnabled(connected and not recording)
        self.stop_recording_btn.setEnabled(recording)
        if recording:
            self.recording_status.setText("CSV:錄製中(目前裝置)")
            self.recording_status.setToolTip(path)
        else:
            self.recording_status.setText("CSV:未錄製")
            self.recording_status.setToolTip("")

    def set_recording_controls_visible(self, visible: bool) -> None:
        for widget in (
            self.start_recording_btn,
            self.stop_recording_btn,
            self.start_recording_all_btn,
            self.stop_recording_all_btn,
            self.recording_status,
        ):
            widget.setVisible(visible)
