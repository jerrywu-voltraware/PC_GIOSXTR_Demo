"""Main desktop window for the GIOSXTR PyQt6 application."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

from PyQt6.QtCore import QStandardPaths, QTimer, Qt, QUrl, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QDesktopServices, QIcon
from PyQt6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QMainWindow,
    QMessageBox,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)
from qasync import asyncSlot

from ..ble_manager import BleManager, DeviceScanResult
from ..constants import APP_ICON_FILENAME, APP_VERSION, APP_WINDOW_TITLE
from ..csv_logger import CsvLogger
from ..models import DataEvent, DeviceState
from ..protocol import parse_notify_packet
from ..recent_devices import RecentDevice, RecentDeviceStore
from ..resources import resource_path
from ..updater import UpdateAsset, UpdateCheckResult, UpdateStatus, check_for_update, download_asset
from .data_pages import PruPage, PtuPage
from .demo2_page import Demo2Page
from .error_page import ErrorPage
from .log_page import LogPage
from .number_page import NumberPage
from .overview_page import OverviewPage
from .scan_panel import ScanPanel
from .settings_dialog import SettingsDialog
from .waveform_page import WaveformPage


def _device_tag(state: DeviceState) -> str:
    if state.device_number is not None:
        return f"{state.device_number:03d}"
    addr = state.device_address.replace(":", "").replace("-", "")
    return addr[-6:].upper() if addr else "dev"


def _default_update_save_path(asset: UpdateAsset, downloads_dir: str | None = None) -> Path:
    base_dir = downloads_dir or QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DownloadLocation)
    base_path = Path(base_dir) if base_dir else Path.home() / "Downloads"
    return base_path / asset.name


class MainWindow(QMainWindow):
    notify_received = pyqtSignal(str, str, bytes)
    disconnected = pyqtSignal(str)

    def __init__(self, *, engineering_mode: bool = False) -> None:
        super().__init__()
        self.setWindowTitle(APP_WINDOW_TITLE)
        icon = QIcon(str(resource_path(APP_ICON_FILENAME)))
        if not icon.isNull():
            self.setWindowIcon(icon)
        self.resize(1280, 820)

        self.log_dir = Path.cwd() / "logs"
        self.managers: dict[str, BleManager] = {}
        self.states: dict[str, DeviceState] = {}
        self.loggers: dict[str, CsvLogger] = {}
        self.recent_device_store = RecentDeviceStore()
        self._close_after_disconnect = False
        self.engineering_mode = engineering_mode
        self.demo_use_fake_data = True
        self.demo_device_name = "MMEU"
        self.demo_ebike_pct = 76
        self.demo_escooter_pct = 81
        self.demo_device_battery_pcts: dict[str, int] = {}
        self.active_address: str = ""
        self.scan_ble = BleManager()
        self.state = DeviceState()
        self._update_check_running = False

        self.notify_received.connect(self._handle_notify)
        self.disconnected.connect(self._handle_disconnect)

        central = QWidget()
        layout = QHBoxLayout(central)
        layout.setContentsMargins(8, 8, 8, 8)
        self.scan_panel = ScanPanel(self.scan_ble)
        self.scan_panel.setFixedWidth(380)
        self.scan_panel.device_connect_requested.connect(self._connect_device)
        self.scan_panel.disconnect_requested.connect(self._disconnect_active)
        self.scan_panel.disconnect_all_requested.connect(self._disconnect_all)
        self.scan_panel.active_changed.connect(self._set_active)
        self.scan_panel.selected_device_changed.connect(self._set_demo_preview_device)
        self.scan_panel.recording_start_requested.connect(self.start_csv_recording_active)
        self.scan_panel.recording_stop_requested.connect(self.stop_csv_recording_active)
        self.scan_panel.recording_start_all_requested.connect(self.start_csv_recording_all)
        self.scan_panel.recording_stop_all_requested.connect(self.stop_csv_recording_all)
        layout.addWidget(self.scan_panel)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(4)

        self.device_tabs = QTabWidget()
        self.device_tabs.setDocumentMode(True)
        self.device_tabs.setTabPosition(QTabWidget.TabPosition.North)
        self.device_tabs.currentChanged.connect(self._on_device_tab_changed)
        self.device_tabs.hide()
        content_layout.addWidget(self.device_tabs)

        self.tabs = QTabWidget()
        self.settings_btn = QToolButton()
        self.settings_btn.setText("⚙")
        self.settings_btn.setToolTip("設定")
        self.settings_btn.setAutoRaise(True)
        self.settings_btn.clicked.connect(self._open_settings)
        self.tabs.setCornerWidget(self.settings_btn, Qt.Corner.TopRightCorner)
        self.overview_page = OverviewPage()
        self.ptu_page = PtuPage()
        self.pru_page = PruPage()
        self.number_page = NumberPage(self._active_manager)
        self.waveform_page = WaveformPage()
        self.demo2_page = Demo2Page(
            engineering_mode=self.engineering_mode,
            demo_use_fake_data=self.demo_use_fake_data,
            demo_device_name=self.demo_device_name,
            demo_ebike_pct=self.demo_ebike_pct,
            demo_escooter_pct=self.demo_escooter_pct,
            demo_device_battery_pcts=self.demo_device_battery_pcts,
        )
        self.log_page = LogPage()
        self.error_page = ErrorPage()
        self.number_page.log_message.connect(self._append_log)

        for label, widget in (
            ("Overview", self.overview_page),
            ("PTU", self.ptu_page),
            ("PRU", self.pru_page),
            ("Number", self.number_page),
            ("Waveform", self.waveform_page),
            ("DEMO", self.demo2_page),
            ("Log", self.log_page),
            ("Error", self.error_page),
        ):
            self.tabs.addTab(widget, label)
        content_layout.addWidget(self.tabs, 1)
        layout.addWidget(content, 1)
        self.setCentralWidget(central)
        self.refresh_pages()
        self.scan_panel.set_recent_devices(self.recent_device_store.load())
        if os.getenv("QT_QPA_PLATFORM", "").lower() != "offscreen":
            QTimer.singleShot(1500, self._start_automatic_update_check)

    def set_engineering_mode(self, enabled: bool) -> None:
        self.engineering_mode = enabled
        self.demo2_page.set_engineering_mode(enabled)

    def set_demo_settings(
        self,
        use_fake_data: bool,
        ebike_pct: int,
        escooter_pct: int,
        device_name: str,
        device_battery_pcts: dict[str, int] | None = None,
    ) -> None:
        self.demo_use_fake_data = use_fake_data
        self.demo_device_name = device_name.strip() or "MMEU"
        self.demo_ebike_pct = ebike_pct
        self.demo_escooter_pct = escooter_pct
        if device_battery_pcts is not None:
            self.demo_device_battery_pcts = {
                str(address).strip(): max(0, min(100, int(pct)))
                for address, pct in device_battery_pcts.items()
                if str(address).strip()
            }
        self.demo2_page.set_demo_settings(
            use_fake_data=use_fake_data,
            device_name=self.demo_device_name,
            ebike_pct=ebike_pct,
            escooter_pct=escooter_pct,
            device_battery_pcts=self.demo_device_battery_pcts,
        )

    def _open_settings(self) -> None:
        dialog = SettingsDialog(
            engineering_mode=self.engineering_mode,
            demo_use_fake_data=self.demo_use_fake_data,
            demo_device_name=self.demo_device_name,
            demo_ebike_pct=self.demo_ebike_pct,
            demo_escooter_pct=self.demo_escooter_pct,
            demo_device_battery_pcts=self.demo_device_battery_pcts,
            connected_demo_devices=self._connected_demo_device_settings(),
            parent=self,
        )
        dialog.engineering_mode_changed.connect(self.set_engineering_mode)
        dialog.demo_settings_changed.connect(self.set_demo_settings)
        dialog.check_updates_requested.connect(lambda: self._start_manual_update_check(dialog))
        dialog.exec()

    def _start_automatic_update_check(self) -> None:
        if self._update_check_running:
            return
        asyncio.create_task(self._check_for_updates(automatic=True))

    def _start_manual_update_check(self, dialog: SettingsDialog) -> None:
        if self._update_check_running:
            return
        dialog.set_update_checking(True)
        asyncio.create_task(self._check_for_updates(automatic=False, settings_dialog=dialog))

    async def _check_for_updates(
        self,
        *,
        automatic: bool,
        settings_dialog: SettingsDialog | None = None,
    ) -> None:
        self._update_check_running = True
        try:
            result = await asyncio.to_thread(check_for_update, APP_VERSION)
        finally:
            self._update_check_running = False
            if settings_dialog is not None:
                settings_dialog.set_update_checking(False)

        if automatic and result.status is not UpdateStatus.UPDATE_AVAILABLE:
            return
        self._show_update_result(result, automatic=automatic)

    def _show_update_result(self, result: UpdateCheckResult, *, automatic: bool) -> None:
        if result.status is UpdateStatus.UPDATE_AVAILABLE and result.info is not None:
            info = result.info
            answer = QMessageBox.question(
                self,
                "Update available",
                (
                    f"Current version: {info.current_version}\n"
                    f"Latest version: {info.latest_version}\n\n"
                    "Download the new version now?"
                ),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes,
            )
            if answer is QMessageBox.StandardButton.Yes:
                asyncio.create_task(self._download_update(info.asset))
            return

        if automatic:
            return

        title = "Update check"
        if result.status is UpdateStatus.UP_TO_DATE:
            QMessageBox.information(self, title, result.message or "This app is already up to date.")
        elif result.status is UpdateStatus.REPO_UNAVAILABLE:
            QMessageBox.information(
                self,
                title,
                result.message or "The GitHub repository or release is not available yet.",
            )
        else:
            QMessageBox.warning(self, title, result.message or "The update check did not complete.")

    async def _download_update(self, asset: UpdateAsset) -> None:
        target_path = self._select_update_download_path(asset)
        if target_path is None:
            return

        try:
            path = await asyncio.to_thread(download_asset, asset, target_path=target_path)
        except Exception as exc:
            QMessageBox.warning(self, "Update download failed", str(exc))
            return

        answer = QMessageBox.question(
            self,
            "Update downloaded",
            (
                f"Downloaded:\n{path}\n\n"
                "Open the downloaded version now? Close this version before using the new one."
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if answer is QMessageBox.StandardButton.Yes:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def _select_update_download_path(self, asset: UpdateAsset) -> Path | None:
        selected_path, _selected_filter = QFileDialog.getSaveFileName(
            self,
            "Save update as",
            str(_default_update_save_path(asset)),
            "Windows executable (*.exe);;All files (*)",
        )
        if not selected_path:
            return None
        path = Path(selected_path)
        if not path.suffix and asset.name.lower().endswith(".exe"):
            path = path.with_suffix(".exe")
        return path

    def _set_demo_preview_device(self, result: DeviceScanResult) -> None:
        self.demo2_page.set_preview_device(result.name, result.device_number)

    def _connected_demo_device_settings(self) -> list[dict[str, object]]:
        items: list[dict[str, object]] = []
        for address, state in self.states.items():
            if not state.is_connected:
                continue
            items.append(
                {
                    "address": address,
                    "label": self._demo_settings_device_label(state),
                    "default_pct": self._default_demo_battery_pct(state),
                }
            )
        return items

    def _demo_settings_device_label(self, state: DeviceState) -> str:
        number = state.device_number
        if number is None:
            _base, sep, suffix = state.device_name.rpartition("#")
            if sep and suffix.strip().isdigit():
                number = int(suffix.strip())
        if number is not None:
            return f"{self.demo_device_name} #{number}"
        return state.device_name.strip() or state.device_address

    def _default_demo_battery_pct(self, state: DeviceState) -> int:
        if state.pru_type_string == "0404V1" or "0404" in state.device_name:
            return self.demo_escooter_pct
        return self.demo_ebike_pct

    def _device_tab_label(self, state: DeviceState) -> str:
        base = "PTU"
        if state.device_number is not None:
            label = f"{base} #{state.device_number}"
        elif state.device_name:
            label = state.device_name
        else:
            label = _device_tag(state)
        logger = self.loggers.get(state.device_address)
        if logger is not None and logger.is_recording:
            label = f"{label} REC"
        if state.error_num:
            label = f"{label} ERR"
        return label

    def _refresh_device_tabs(self) -> None:
        self.device_tabs.blockSignals(True)
        try:
            self.device_tabs.clear()
            for address, state in self.states.items():
                page = QWidget()
                page.setProperty("address", address)
                self.device_tabs.addTab(page, self._device_tab_label(state))
                if address == self.active_address:
                    self.device_tabs.setCurrentIndex(self.device_tabs.count() - 1)
            self.device_tabs.setVisible(len(self.states) > 1)
        finally:
            self.device_tabs.blockSignals(False)

    def _on_device_tab_changed(self, index: int) -> None:
        widget = self.device_tabs.widget(index)
        if widget is None:
            return
        address = widget.property("address")
        if isinstance(address, str) and address and address != self.active_address:
            self._set_active(address)

    def _active_manager(self) -> BleManager | None:
        return self.managers.get(self.active_address)

    def _active_logger(self) -> CsvLogger | None:
        return self.loggers.get(self.active_address)

    def _make_notify_emitter(self):
        def emit(address: str, uuid: str, data: bytes) -> None:
            self.notify_received.emit(address, uuid, data)
        return emit

    def _make_disconnect_emitter(self):
        def emit(address: str) -> None:
            self.disconnected.emit(address)
        return emit

    @asyncSlot(object)
    async def _connect_device(self, result: DeviceScanResult) -> None:
        address = result.address
        if address in self.managers:
            self._set_active(address)
            return
        manager = BleManager()
        manager.set_notify_callback(self._make_notify_emitter())
        manager.set_disconnect_callback(self._make_disconnect_emitter())
        try:
            await manager.connect(address)
        except Exception as exc:
            QMessageBox.warning(self, "Connect failed", str(exc))
            return

        state = DeviceState()
        state.is_connected = True
        state.device_name = result.name
        state.device_address = address
        state.rssi = result.rssi
        state.device_number = result.device_number
        state.advertising_raw = result.raw_hex
        state.advertising_rows = result.advertising_rows
        state.add_log(f"Connected to {result.name} ({address})")
        self._remember_recent_device(result)

        self.managers[address] = manager
        self.states[address] = state
        self.loggers[address] = CsvLogger(self.log_dir)
        self.active_address = address
        self.state = state
        self._refresh_device_tabs()

        try:
            await manager.enable_default_notifications()
        except Exception as exc:
            state.add_log(f"Enable notifications failed: {exc}")
        try:
            await manager.request_200b()
        except Exception as exc:
            state.add_log(f"Initial 200B request skipped: {exc}")
        self.refresh_pages()

    def _remember_recent_device(self, result: DeviceScanResult) -> None:
        try:
            self.recent_device_store.remember(
                RecentDevice(
                    address=result.address,
                    name=result.name,
                    device_number=result.device_number,
                    rssi=result.rssi,
                )
            )
            self.scan_panel.set_recent_devices(self.recent_device_store.load())
        except OSError:
            pass

    @pyqtSlot(str)
    def _set_active(self, address: str) -> None:
        if not address or address not in self.states:
            return
        self.active_address = address
        self.state = self.states[address]
        self.refresh_pages()

    @asyncSlot()
    async def _disconnect_active(self) -> None:
        addr = self.active_address
        if not addr:
            return
        await self._disconnect_address(addr)

    @asyncSlot()
    async def _disconnect_all(self) -> None:
        for addr in list(self.managers.keys()):
            await self._disconnect_address(addr)

    async def _disconnect_address(self, address: str) -> None:
        manager = self.managers.get(address)
        if manager is None:
            return
        try:
            await manager.disconnect()
        finally:
            self._cleanup_address(address)

    def _cleanup_address(self, address: str) -> None:
        logger = self.loggers.pop(address, None)
        if logger is not None and logger.is_recording:
            path = logger.stop()
            if path is not None:
                state = self.states.get(address)
                if state is not None:
                    state.add_log(f"CSV recording stopped: {path.name}")
        state = self.states.pop(address, None)
        if state is not None:
            state.is_connected = False
            state.add_log("Disconnected")
        self.managers.pop(address, None)
        if self.active_address == address:
            next_addr = next(iter(self.managers), "")
            self.active_address = next_addr
            self.state = self.states.get(next_addr, DeviceState()) if next_addr else DeviceState()
        self._refresh_device_tabs()
        self.refresh_pages()

    @pyqtSlot(str)
    def _handle_disconnect(self, address: str) -> None:
        self._cleanup_address(address)

    @pyqtSlot(str, str, bytes)
    def _handle_notify(self, address: str, uuid: str, data: bytes) -> None:
        state = self.states.get(address)
        if state is None:
            return
        event = parse_notify_packet(data, uuid, state)
        if event is not None:
            self._handle_event(event, state)
        logger = self.loggers.get(address)
        if logger is not None and logger.is_recording:
            logger.write_state(state)
        if address == self.active_address:
            self.refresh_pages()
        else:
            self._refresh_device_tabs()
            self.scan_panel.refresh_connected_devices(self._connected_summary(), self.active_address)

    def _handle_event(self, event: DataEvent, state: DeviceState | None = None) -> None:
        if event.kind == "error":
            self._show_error_dialog(state or self.state)

    def _show_error_dialog(self, state: DeviceState) -> None:
        from ..protocol import error_description

        code = state.error_num
        code_hex = f"0x{code:02X}"
        desc = error_description(code)
        msg = QMessageBox(self)
        msg.setIcon(QMessageBox.Icon.Warning)
        msg.setWindowTitle("錯誤通知")
        msg.setTextFormat(Qt.TextFormat.RichText)
        device_line = ""
        if state.device_name or state.device_address:
            device_line = (
                f"<div style='color:#666; font-size:11px;'>"
                f"裝置:{state.device_name} ({state.device_address})</div>"
            )
        details = ""
        if state.error_data != 0 or state.error_limit != 0:
            details = (
                "<hr>"
                "<div style='color:#555; font-size:11px;'>錯誤詳細資訊:</div>"
                "<table cellpadding='4'>"
                f"<tr><td>條件值 (Error Data):</td>"
                f"<td align='right'><b>0x{state.error_data:X} ({state.error_data})</b></td></tr>"
                f"<tr><td>限制值 (Error Limit):</td>"
                f"<td align='right'><b>0x{state.error_limit:X} ({state.error_limit})</b></td></tr>"
                "</table>"
            )
        msg.setText(
            f"<div style='background:#FDECEA; padding:8px; border-radius:6px;'>"
            f"<span style='font-size:20px; font-weight:700; color:#C0392B; font-family:Consolas;'>{code_hex}</span>"
            f"&nbsp;&nbsp;<span style='color:#C0392B; font-weight:600;'>{desc}</span>"
            f"</div>"
            f"{device_line}"
            f"{details}"
        )
        msg.setStandardButtons(QMessageBox.StandardButton.Ok)
        msg.exec()

    def start_csv_recording_active(self) -> Path | None:
        addr = self.active_address
        if not addr:
            self.scan_panel.set_recording_state(False, False)
            return None
        return self._start_recording(addr)

    def stop_csv_recording_active(self) -> Path | None:
        addr = self.active_address
        if not addr:
            return None
        return self._stop_recording(addr)

    def start_csv_recording_all(self) -> None:
        for addr in list(self.managers.keys()):
            self._start_recording(addr)

    def stop_csv_recording_all(self) -> None:
        for addr in list(self.loggers.keys()):
            self._stop_recording(addr)

    def _start_recording(self, address: str) -> Path | None:
        state = self.states.get(address)
        logger = self.loggers.get(address)
        if state is None or logger is None or not state.is_connected:
            return None
        if logger.is_recording:
            return logger.current_path
        path = logger.start(_device_tag(state))
        state.add_log(f"CSV recording started: {path.name}")
        self.refresh_pages()
        return path

    def _stop_recording(self, address: str) -> Path | None:
        state = self.states.get(address)
        logger = self.loggers.get(address)
        if logger is None or not logger.is_recording:
            return None
        path = logger.stop()
        if path is not None and state is not None:
            state.add_log(f"CSV recording stopped: {path.name}")
        self.refresh_pages()
        return path

    @pyqtSlot(str)
    def _append_log(self, message: str) -> None:
        if self.active_address:
            self.state.add_log(message)
        self.refresh_pages()

    def _connected_summary(self) -> list[dict[str, str]]:
        items: list[dict[str, str]] = []
        for addr, state in self.states.items():
            logger = self.loggers.get(addr)
            items.append(
                {
                    "address": addr,
                    "name": state.device_name,
                    "device_number": "" if state.device_number is None else str(state.device_number),
                    "recording": "1" if (logger is not None and logger.is_recording) else "0",
                    "packets": str(state.total_packet_count),
                }
            )
        return items

    def refresh_pages(self) -> None:
        state = self.state
        self._refresh_device_tabs()
        self.demo2_page.set_showcase_states(self.states, self.active_address)
        pages = (
            self.overview_page,
            self.ptu_page,
            self.pru_page,
            self.waveform_page,
            self.demo2_page,
            self.log_page,
            self.error_page,
        )
        for page in pages:
            page.refresh(state)
        active_logger = self._active_logger()
        rec_active = active_logger is not None and active_logger.is_recording
        rec_path = str(active_logger.current_path) if (active_logger and active_logger.current_path) else ""
        self.overview_page.set_csv_recording(rec_active, rec_path)
        self.scan_panel.refresh(state)
        self.scan_panel.set_recording_state(state.is_connected, rec_active, rec_path)
        self.scan_panel.refresh_connected_devices(self._connected_summary(), self.active_address)

    def closeEvent(self, event) -> None:
        if self.managers and not self._close_after_disconnect:
            event.ignore()
            self.setEnabled(False)
            self.scan_panel.status.setText("正在中斷裝置連線，完成後關閉 APP ...")
            asyncio.create_task(self._disconnect_then_close())
            return

        for logger in self.loggers.values():
            logger.stop()
        super().closeEvent(event)

    async def _disconnect_then_close(self) -> None:
        for addr in list(self.managers.keys()):
            try:
                await self._disconnect_address(addr)
            except Exception:
                self._cleanup_address(addr)
        self._close_after_disconnect = True
        self.setEnabled(True)
        self.close()
