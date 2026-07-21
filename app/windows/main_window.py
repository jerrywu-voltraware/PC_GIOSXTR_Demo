"""Main desktop window for the GIOSXTR PyQt6 application."""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

from PyQt6.QtCore import QCoreApplication, QSettings, QStandardPaths, QTimer, Qt, QUrl, pyqtSignal, pyqtSlot
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

from ..ble_adapter import AdapterCheckResult, AdapterStatus, check_bluetooth_adapter, user_facing_message
from ..ble_manager import BleManager, DeviceScanResult
from ..ble_manager import _write_scan_debug
from ..device_source import DeviceManager, DeviceSource, PcBleSource, _write_dongle_runtime_log
from ..constants import (
    APP_ICON_FILENAME,
    APP_NAME,
    APP_VERSION,
    APP_WINDOW_TITLE,
    DEFAULT_DEMO_CHARGER_MODE,
    DEFAULT_DEMO_EBIKE_STYLE,
    DEFAULT_DEMO_DEVICE_NAME,
    DEFAULT_RECORD_SPLIT_ROWS,
    UUID_IOT_NOTIFY,
    UUID_NOTIFY_20B,
    UUID_NOTIFY_200B,
    normalize_demo_charger_mode,
    normalize_demo_ebike_style,
    normalize_record_split_rows,
)
from ..csv_logger import CsvLogger
from ..models import DataEvent, DeviceState
from ..protocol import parse_notify_packet
from ..recent_devices import RecentDevice, RecentDeviceStore
from ..resources import resource_path
from ..updater import UpdateAsset, UpdateCheckResult, UpdateStatus, check_for_update, download_asset
from .data_pages import PruPage, PtuPage
from .demo2_page import Demo2Page
from .error_log_dialog import ErrorLogDialog
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


def _is_stream_payload(uuid: str, data: bytes) -> bool:
    """Return whether a notification is long enough to contain real data."""
    uuid_l = uuid.lower()
    return (
        (uuid_l == UUID_IOT_NOTIFY and len(data) >= 15)
        or (uuid_l == UUID_NOTIFY_20B and len(data) >= 20)
        or (uuid_l == UUID_NOTIFY_200B and len(data) >= 193)
    )


def _default_update_save_path(asset: UpdateAsset, downloads_dir: str | None = None) -> Path:
    base_dir = downloads_dir or QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DownloadLocation)
    base_path = Path(base_dir) if base_dir else Path.home() / "Downloads"
    return base_path / asset.name


AUTO_RECONNECT_SETTINGS_KEY = "connection/autoReconnect"
AUTO_RECONNECT_DEFAULT = True
DEMO_CHARGER_MODE_SETTINGS_KEY = "demo/chargerMode"
DEMO_EBIKE_STYLE_SETTINGS_KEY = "demo/ebikeStyle"
RECORD_SPLIT_ROWS_SETTINGS_KEY = "recording/splitRows"
SETTINGS_ORGANIZATION = "GIOSXTR"
RECONNECT_DELAYS_SECONDS = (1.0, 3.0, 5.0, 10.0)
RECONNECT_MAX_ATTEMPTS = 10
# After the fast ramp above is exhausted, reconnect never gives up: it keeps
# retrying forever at this steady, capped interval so a device dropped during a
# long unattended run is always recovered once it comes back.
SLOW_RECONNECT_INTERVAL_SECONDS = 30.0
# Background safety net: periodically re-arm any kept-but-disconnected device
# whose reconnect task died, so reconnect can never be permanently lost.
RECONNECT_HEALTH_INTERVAL_MS = 30_000
# Longer than the dongle's 12s stream watchdog plus its 5s disconnect wait, so
# the safety timer cannot release a second AT+CONN while recovery is starting.
CONNECT_READY_GUARD_TIMEOUT_MS = 20_000


def _ensure_settings_identity() -> None:
    if not QCoreApplication.organizationName():
        QCoreApplication.setOrganizationName(SETTINGS_ORGANIZATION)
    if QCoreApplication.applicationName().strip().lower() in {"", "python"}:
        QCoreApplication.setApplicationName(APP_NAME)


def _settings_bool(key: str, default: bool = False) -> bool:
    _ensure_settings_identity()
    value = QSettings().value(key, default)
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _settings_demo_charger_mode() -> str:
    _ensure_settings_identity()
    value = QSettings().value(DEMO_CHARGER_MODE_SETTINGS_KEY, DEFAULT_DEMO_CHARGER_MODE)
    return normalize_demo_charger_mode(value)


def _settings_demo_ebike_style() -> str:
    _ensure_settings_identity()
    value = QSettings().value(DEMO_EBIKE_STYLE_SETTINGS_KEY, DEFAULT_DEMO_EBIKE_STYLE)
    return normalize_demo_ebike_style(value)


def _settings_record_split_rows() -> int:
    _ensure_settings_identity()
    value = QSettings().value(RECORD_SPLIT_ROWS_SETTINGS_KEY, DEFAULT_RECORD_SPLIT_ROWS)
    return normalize_record_split_rows(value)


class MainWindow(QMainWindow):
    notify_received = pyqtSignal(str, str, bytes)
    disconnected = pyqtSignal(str)

    def __init__(self, *, source: DeviceSource | None = None, engineering_mode: bool = False) -> None:
        super().__init__()
        # Data-source backend (PC built-in Bluetooth by default). The dongle
        # source is injected from main(); everything below is source-agnostic.
        self.source: DeviceSource = source or PcBleSource()
        self.setWindowTitle(APP_WINDOW_TITLE)
        icon = QIcon(str(resource_path(APP_ICON_FILENAME)))
        if not icon.isNull():
            self.setWindowIcon(icon)
        self.resize(1280, 820)

        self.log_dir = Path.cwd() / "logs"
        self.managers: dict[str, DeviceManager] = {}
        self.states: dict[str, DeviceState] = {}
        self.loggers: dict[str, CsvLogger] = {}
        self.recent_device_store = RecentDeviceStore()
        self._close_after_disconnect = False
        self.engineering_mode = engineering_mode
        self.demo_use_fake_data = True
        self.demo_device_name = DEFAULT_DEMO_DEVICE_NAME
        self.demo_ebike_pct = 76
        self.demo_escooter_pct = 81
        self.demo_charger_mode = _settings_demo_charger_mode()
        self.demo_ebike_style = _settings_demo_ebike_style()
        self.demo_device_battery_pcts: dict[str, int] = {}
        self.record_split_rows = _settings_record_split_rows()
        self.active_address: str = ""
        self.state = DeviceState()
        self._update_check_running = False
        self._last_adapter_status: AdapterStatus | None = None
        self.auto_reconnect_enabled = _settings_bool(AUTO_RECONNECT_SETTINGS_KEY, AUTO_RECONNECT_DEFAULT)
        self._manual_disconnect_addresses: set[str] = set()
        # Addresses that are connecting OR connected-but-not-yet-streaming.
        # The dongle cannot start a new connection while a previous link is
        # still in GATT discovery, so we block new connects until the current
        # device's first packet arrives (see requires_ready_before_next_connect).
        self._connect_in_progress: set[str] = set()
        self._reconnect_tasks: dict[str, asyncio.Task[None]] = {}
        self._reconnecting_addresses: set[str] = set()
        self._reconnect_delays = RECONNECT_DELAYS_SECONDS
        self._reconnect_max_attempts = RECONNECT_MAX_ATTEMPTS
        # Number of leading attempts that use the fast ramp; afterwards reconnect
        # keeps retrying forever at the slow interval (never gives up).
        self._reconnect_fast_attempts = len(RECONNECT_DELAYS_SECONDS)
        self._slow_reconnect_interval = SLOW_RECONNECT_INTERVAL_SECONDS
        # Pending error dialogs awaiting 200B data/limit values, per device.
        # Maps address -> error_num just observed; resolved either when a 200B
        # arrives with non-zero data/limit, or by a 2s fallback timer.
        self._pending_error_codes: dict[str, int] = {}
        self._error_dialog_max_wait_ms = 2000
        self._error_log_dialog: ErrorLogDialog | None = None

        self.notify_received.connect(self._handle_notify)
        self.disconnected.connect(self._handle_disconnect)

        central = QWidget()
        layout = QHBoxLayout(central)
        layout.setContentsMargins(8, 8, 8, 8)
        self.scan_panel = ScanPanel(self.source)
        self.scan_panel.setFixedWidth(380)
        self.scan_panel.device_connect_requested.connect(self._connect_device)
        self.scan_panel.disconnect_requested.connect(self._disconnect_active)
        self.scan_panel.disconnect_all_requested.connect(self._disconnect_all)
        self.scan_panel.packet_counts_clear_requested.connect(self.clear_packet_counts_active)
        self.scan_panel.active_changed.connect(self._set_active)
        self.scan_panel.selected_device_changed.connect(self._set_demo_preview_device)
        self.scan_panel.recording_start_requested.connect(self.start_csv_recording_active)
        self.scan_panel.recording_stop_requested.connect(self.stop_csv_recording_active)
        self.scan_panel.recording_start_all_requested.connect(self.start_csv_recording_all)
        self.scan_panel.recording_stop_all_requested.connect(self.stop_csv_recording_all)
        self.scan_panel.open_log_folder_requested.connect(self._open_log_folder)
        self.scan_panel.auto_reconnect_changed.connect(self.set_auto_reconnect_enabled)
        self.scan_panel.set_auto_reconnect_enabled(self.auto_reconnect_enabled)
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
            demo_charger_mode=self.demo_charger_mode,
            demo_ebike_style=self.demo_ebike_style,
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
            QTimer.singleShot(0, self._start_initial_adapter_check)
        if os.getenv("QT_QPA_PLATFORM", "").lower() != "offscreen":
            QTimer.singleShot(1500, self._start_automatic_update_check)

        # Background safety net: no matter how a reconnect loop exited (crash,
        # never-scheduled, transport wedge), this periodically re-arms every
        # kept-but-disconnected device so reconnect can never be lost for good.
        self._reconnect_health_timer = QTimer(self)
        self._reconnect_health_timer.setInterval(RECONNECT_HEALTH_INTERVAL_MS)
        self._reconnect_health_timer.timeout.connect(self._reconnect_health_tick)
        self._reconnect_health_timer.start()

    def _start_initial_adapter_check(self) -> None:
        asyncio.create_task(self._run_initial_adapter_check())

    async def _run_initial_adapter_check(self) -> None:
        # Route through the data source so the dongle reports serial-port
        # readiness instead of the OS Bluetooth adapter. PcBleSource.check_ready
        # delegates to check_bluetooth_adapter, so the PC path is unchanged.
        result = await self.source.check_ready()
        _write_scan_debug(f"startup adapter check: {result.status.value} {result.detail}")
        self._handle_adapter_check_result(result, show_warning=True)

    def _handle_adapter_check_result(self, result: AdapterCheckResult, *, show_warning: bool) -> None:
        self._last_adapter_status = result.status
        if result.status in (AdapterStatus.NO_ADAPTER, AdapterStatus.DISABLED):
            title, body = user_facing_message(result)
            if show_warning:
                QMessageBox.warning(self, title, body)
            self.scan_panel.set_adapter_unavailable(result.status, body)
            return
        if result.status is AdapterStatus.OK:
            self.scan_panel.set_adapter_available()
            return
        if result.status is AdapterStatus.UNKNOWN_ERROR:
            self.scan_panel.status.setText(f"藍牙狀態檢測失敗: {result.detail}")

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
        demo_charger_mode: str = DEFAULT_DEMO_CHARGER_MODE,
        demo_ebike_style: str = DEFAULT_DEMO_EBIKE_STYLE,
        *,
        persist: bool = True,
    ) -> None:
        self.demo_use_fake_data = use_fake_data
        self.demo_device_name = device_name.strip() or DEFAULT_DEMO_DEVICE_NAME
        self.demo_ebike_pct = ebike_pct
        self.demo_escooter_pct = escooter_pct
        self.demo_charger_mode = normalize_demo_charger_mode(demo_charger_mode)
        self.demo_ebike_style = normalize_demo_ebike_style(demo_ebike_style)
        if persist:
            _ensure_settings_identity()
            QSettings().setValue(DEMO_CHARGER_MODE_SETTINGS_KEY, self.demo_charger_mode)
            QSettings().setValue(DEMO_EBIKE_STYLE_SETTINGS_KEY, self.demo_ebike_style)
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
            demo_charger_mode=self.demo_charger_mode,
            demo_ebike_style=self.demo_ebike_style,
            device_battery_pcts=self.demo_device_battery_pcts,
        )

    def _open_settings(self) -> None:
        dialog = SettingsDialog(
            engineering_mode=self.engineering_mode,
            demo_use_fake_data=self.demo_use_fake_data,
            demo_device_name=self.demo_device_name,
            demo_ebike_pct=self.demo_ebike_pct,
            demo_escooter_pct=self.demo_escooter_pct,
            demo_charger_mode=self.demo_charger_mode,
            demo_ebike_style=self.demo_ebike_style,
            demo_device_battery_pcts=self.demo_device_battery_pcts,
            connected_demo_devices=self._connected_demo_device_settings(),
            auto_reconnect_enabled=self.auto_reconnect_enabled,
            record_split_rows=self.record_split_rows,
            source_display_name=getattr(self.source, "display_name", ""),
            parent=self,
        )
        dialog.engineering_mode_changed.connect(self.set_engineering_mode)
        dialog.demo_settings_changed.connect(self.set_demo_settings)
        dialog.auto_reconnect_changed.connect(self.set_auto_reconnect_enabled)
        dialog.record_split_rows_changed.connect(self.set_record_split_rows)
        dialog.check_updates_requested.connect(lambda: self._start_manual_update_check(dialog))
        dialog.switch_source_requested.connect(lambda: self._handle_switch_source(dialog))
        dialog.exec()

    def _handle_switch_source(self, dialog: SettingsDialog) -> None:
        reply = QMessageBox.question(
            self,
            "切換連線方式",
            "切換連線方式需要重新啟動程式，目前的連線會中斷。\n\n要繼續嗎？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        dialog.accept()
        # Release the serial port so the relaunched instance can open it.
        try:
            self.source.shutdown()
        except Exception:
            pass
        self._relaunch_app()

    def _relaunch_app(self) -> None:
        from PyQt6.QtCore import QProcess
        from PyQt6.QtWidgets import QApplication

        if getattr(sys, "frozen", False):
            # PyInstaller bundle: sys.argv[0] is the exe itself.
            QProcess.startDetached(sys.executable, sys.argv[1:])
        else:
            # Script mode: re-run "python main.py ...".
            QProcess.startDetached(sys.executable, sys.argv)
        QApplication.quit()

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
                "發現新版",
                (
                    f"目前版本：{info.current_version}\n"
                    f"最新版本：{info.latest_version}\n\n"
                    "是否立即下載新版？"
                ),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes,
            )
            if answer is QMessageBox.StandardButton.Yes:
                asyncio.create_task(self._download_update(info.asset))
            return

        if automatic:
            return

        title = "檢查更新"
        if result.status is UpdateStatus.UP_TO_DATE:
            QMessageBox.information(self, title, result.message or "目前已是最新版本。")
        elif result.status is UpdateStatus.REPO_UNAVAILABLE:
            QMessageBox.information(
                self,
                title,
                result.message or "GitHub repository 或 release 尚未建立。",
            )
        else:
            QMessageBox.warning(self, title, result.message or "更新檢查未完成。")

    async def _download_update(self, asset: UpdateAsset) -> None:
        target_path = self._select_update_download_path(asset)
        if target_path is None:
            return

        try:
            path = await asyncio.to_thread(download_asset, asset, target_path=target_path)
        except Exception as exc:
            QMessageBox.warning(self, "更新下載失敗", str(exc))
            return

        answer = QMessageBox.question(
            self,
            "更新已下載",
            (
                f"已下載：\n{path}\n\n"
                "是否現在開啟新版？使用新版前請先關閉目前版本。"
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if answer is QMessageBox.StandardButton.Yes:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def _select_update_download_path(self, asset: UpdateAsset) -> Path | None:
        selected_path, _selected_filter = QFileDialog.getSaveFileName(
            self,
            "儲存更新檔",
            str(_default_update_save_path(asset)),
            "Windows 執行檔 (*.exe);;所有檔案 (*)",
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

    def _active_manager(self) -> DeviceManager | None:
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

    def _create_ble_manager(self) -> DeviceManager:
        return self.source.create_manager()

    async def _maybe_recover_source(self, exc: Exception) -> bool:
        """Reset the data source after a connect timeout so the dongle does not
        stay wedged (which would otherwise need an app restart). Returns True if
        a recovery was attempted."""
        recover = getattr(self.source, "recover", None)
        ensure_recovered = getattr(self.source, "ensure_recovered", None)
        recovery_state = getattr(self.source, "needs_recovery", None)
        if recovery_state is None:
            recovery_action = recover
            should_recover = isinstance(exc, (TimeoutError, ConnectionError))
        else:
            # A transport-aware source knows whether the whole adapter is
            # unhealthy.  A peripheral-specific ConnectionError must not reset
            # the dongle and disconnect other healthy recording sessions.
            recovery_action = ensure_recovered or recover
            should_recover = bool(recovery_state)
        if recovery_action is None or not should_recover:
            return False
        try:
            await recovery_action("connect failed")
        except Exception:
            return False
        return True

    def _show_warning(self, title: str, message: str) -> None:
        box = QMessageBox(
            QMessageBox.Icon.Warning,
            title,
            message,
            QMessageBox.StandardButton.Ok,
            self,
        )
        box.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        box.open()

    def set_record_split_rows(self, rows: int, *, persist: bool = True) -> None:
        self.record_split_rows = normalize_record_split_rows(rows)
        if persist:
            _ensure_settings_identity()
            QSettings().setValue(RECORD_SPLIT_ROWS_SETTINGS_KEY, self.record_split_rows)

    def set_auto_reconnect_enabled(self, enabled: bool, *, persist: bool = True) -> None:
        self.auto_reconnect_enabled = bool(enabled)
        scan_panel = getattr(self, "scan_panel", None)
        if scan_panel is not None:
            scan_panel.set_auto_reconnect_enabled(self.auto_reconnect_enabled)
        if persist:
            _ensure_settings_identity()
            QSettings().setValue(AUTO_RECONNECT_SETTINGS_KEY, self.auto_reconnect_enabled)
        if not self.auto_reconnect_enabled:
            for task in list(self._reconnect_tasks.values()):
                if not task.done():
                    task.cancel()
            self._reconnect_tasks.clear()
            self._reconnecting_addresses.clear()
            self.refresh_pages()
        else:
            # Re-enabling must re-arm every kept-but-disconnected device that is
            # not currently connecting; otherwise a device that dropped while the
            # toggle was off would stay stranded.
            self._rearm_disconnected_devices()
            self.refresh_pages()

    def _rearm_disconnected_devices(self) -> None:
        """Schedule reconnect for kept devices that are down and have no live task.

        Shared by the auto-reconnect toggle and the periodic health tick so a
        reconnect can never be permanently lost, no matter how its loop exited.
        """
        if not self.auto_reconnect_enabled:
            return
        for address, state in list(self.states.items()):
            if state.is_connected:
                continue
            if address in self._manual_disconnect_addresses:
                continue
            if address in self._connect_in_progress:
                continue
            task = self._reconnect_tasks.get(address)
            if task is not None and not task.done():
                continue
            self._reconnecting_addresses.add(address)
            self._schedule_reconnect(address)

    def _reconnect_health_tick(self) -> None:
        self._rearm_disconnected_devices()

    @asyncSlot(object)
    async def _connect_device(self, result: DeviceScanResult) -> None:
        address = result.address
        if address in self._connect_in_progress:
            if address in self.states:
                self._set_active(address)
            return
        if address in self.managers:
            self._set_active(address)
            return
        existing_state = self.states.get(address)
        if existing_state is not None and (
            existing_state.is_connected or address in self._reconnecting_addresses
        ):
            self._set_active(address)
            return

        # 防呆：dongle 無法在前一個連線仍在 GATT discovery 時發起新連線，否則會
        # 卡住。若目前有裝置「連線中／已連線但尚未開始收資料」，擋下這次連線。
        if (
            getattr(self.source, "requires_ready_before_next_connect", False)
            and self._connect_in_progress
        ):
            self._show_warning(
                "請稍候",
                "目前有裝置正在連線中（尚未開始接收資料）。\n\n"
                "請等資料開始進來後，再連線下一台裝置。",
            )
            return

        manager = self._create_ble_manager()
        manager.set_notify_callback(self._make_notify_emitter())
        manager.set_disconnect_callback(self._make_disconnect_emitter())
        self._connect_in_progress.add(address)
        try:
            await manager.connect(address)
        except Exception as exc:
            self._connect_in_progress.discard(address)
            recovered = await self._maybe_recover_source(exc)
            if recovered:
                self._show_warning(
                    "連線逾時",
                    "連線逾時,已自動重置接收器。\n\n請重新搜尋裝置後再試一次。",
                )
            else:
                self._show_warning("Connect failed", str(exc))
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

        # 連上了但還在等第一個封包；_handle_notify 收到資料時會解除。安全網：
        # 萬一連上卻一直沒資料，watchdog/recovery 之外仍保留 20 秒安全網。
        if address in self._connect_in_progress:
            QTimer.singleShot(
                CONNECT_READY_GUARD_TIMEOUT_MS,
                lambda a=address, m=manager: self._expire_connect_guard(a, m),
            )

        try:
            await manager.enable_default_notifications()
        except Exception as exc:
            state.add_log(f"Enable notifications failed: {exc}")
        try:
            await manager.request_200b()
        except Exception as exc:
            state.add_log(f"Initial 200B request skipped: {exc}")
        manager.start_200b_keeper()
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
        for addr in list({*self.states.keys(), *self.managers.keys()}):
            await self._disconnect_address(addr)

    @pyqtSlot()
    def clear_packet_counts_active(self) -> None:
        addr = self.active_address
        if not addr:
            return
        state = self.states.get(addr)
        if state is None or not state.is_connected:
            return
        state.reset_packet_counts()
        state.add_log("Packet counters cleared")
        self.refresh_pages()

    async def _disconnect_address(self, address: str) -> None:
        self._manual_disconnect_addresses.add(address)
        self._cancel_reconnect(address)
        manager = self.managers.get(address)
        if manager is None:
            self._cleanup_address(address)
            self._manual_disconnect_addresses.discard(address)
            return
        try:
            await manager.disconnect()
        finally:
            self._cleanup_address(address)
            self._manual_disconnect_addresses.discard(address)

    def _cleanup_address(self, address: str, *, allow_reconnect: bool = False) -> None:
        # A disconnect (or failed setup) clears the connect-in-progress guard.
        self._connect_in_progress.discard(address)
        if allow_reconnect:
            self.managers.pop(address, None)
            state = self.states.get(address)
            if state is not None:
                state.is_connected = False
                state.add_log("裝置斷線，準備自動重新連線")
                self._reconnecting_addresses.add(address)
            self._pending_error_codes.pop(address, None)
            self._refresh_device_tabs()
            self.refresh_pages()
            self._schedule_reconnect(address)
            return

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
        self._reconnecting_addresses.discard(address)
        self._pending_error_codes.pop(address, None)
        if self.active_address == address:
            next_addr = next(iter(self.managers), "")
            self.active_address = next_addr
            self.state = self.states.get(next_addr, DeviceState()) if next_addr else DeviceState()
        self._refresh_device_tabs()
        self.refresh_pages()

    @pyqtSlot(str)
    def _handle_disconnect(self, address: str) -> None:
        manual = address in self._manual_disconnect_addresses
        self._manual_disconnect_addresses.discard(address)
        self._cleanup_address(address, allow_reconnect=self.auto_reconnect_enabled and not manual)

    def _cancel_reconnect(self, address: str) -> None:
        task = self._reconnect_tasks.pop(address, None)
        if task is not None and not task.done():
            task.cancel()
        self._reconnecting_addresses.discard(address)

    def _schedule_reconnect(self, address: str) -> None:
        if not self.auto_reconnect_enabled or address not in self.states:
            return
        task = self._reconnect_tasks.get(address)
        if task is not None and not task.done():
            return
        coro = self._run_reconnect_loop(address)
        try:
            new_task = asyncio.create_task(coro)
        except RuntimeError:
            # No running event loop in unit tests or during teardown; keep state
            # preserved and let the next user action handle the device.
            coro.close()
            return
        self._reconnect_tasks[address] = new_task
        new_task.add_done_callback(
            lambda finished, a=address: self._on_reconnect_task_done(a, finished)
        )

    def _on_reconnect_task_done(self, address: str, task: asyncio.Task[None]) -> None:
        """Last-resort guard: an exception must never silently kill reconnect.

        The reconnect loop already swallows its own errors, but if anything
        unexpected escapes it, log it (device state log + runtime log) and
        re-arm the device so it is never stranded in the reconnecting state.
        """
        if task.cancelled():
            return
        try:
            exc = task.exception()
        except asyncio.CancelledError:
            return
        if exc is None:
            return
        _write_dongle_runtime_log(f"reconnect loop crashed for {address}: {exc!r}")
        state = self.states.get(address)
        if state is not None:
            state.add_log(f"重新連線流程異常，重新排程: {exc}")
        if self._reconnect_tasks.get(address) is task:
            self._reconnect_tasks.pop(address, None)
        if (
            self.auto_reconnect_enabled
            and address in self.states
            and not self.states[address].is_connected
            and address not in self._manual_disconnect_addresses
        ):
            self._reconnecting_addresses.add(address)
            self._schedule_reconnect(address)

    def _reconnect_delay(self, attempt_index: int) -> float:
        delays = self._reconnect_delays
        if delays:
            if attempt_index < len(delays):
                return delays[attempt_index]
            # Within the fast window but past a (possibly test-shortened) ramp,
            # reuse the last ramp step rather than jumping straight to the slow
            # interval.
            if attempt_index < self._reconnect_fast_attempts:
                return delays[-1]
        # Past the fast ramp: keep retrying forever at a steady slow interval.
        return self._slow_reconnect_interval

    async def _run_reconnect_loop(self, address: str) -> None:
        # Never give up: while auto-reconnect is on and the device is still kept
        # (in self.states) and not manually disconnected, retry forever — the
        # fast ramp first, then a steady slow interval indefinitely.  Exits only
        # on: auto-reconnect off, address removed, a successful reconnect, or
        # task cancellation (manual disconnect).
        attempt_index = 0
        try:
            while True:
                if not self.auto_reconnect_enabled or address not in self.states:
                    return
                await asyncio.sleep(self._reconnect_delay(attempt_index))
                if not self.auto_reconnect_enabled or address not in self.states:
                    return
                state = self.states.get(address)
                if state is not None and state.is_connected:
                    # Reconnected by another path (e.g. manual connect); done.
                    self._reconnecting_addresses.discard(address)
                    return
                try:
                    await self._reconnect_device(address)
                    return
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    # A raising _maybe_recover_source / refresh_pages must never
                    # kill the loop or strand the address; keep retrying.
                    try:
                        recovered = await self._maybe_recover_source(exc)
                    except asyncio.CancelledError:
                        raise
                    except Exception as recover_exc:
                        recovered = False
                        _write_dongle_runtime_log(
                            f"reconnect recover failed for {address}: {recover_exc!r}"
                        )
                    state = self.states.get(address)
                    if state is not None:
                        recovery_note = "；已重置 dongle" if recovered else ""
                        try:
                            state.add_log(
                                f"重新連線失敗 (第 {attempt_index + 1} 次): "
                                f"{exc}{recovery_note}"
                            )
                            self.refresh_pages()
                        except Exception:
                            pass
                attempt_index += 1
        except asyncio.CancelledError:
            pass
        finally:
            self._reconnect_tasks.pop(address, None)

    async def _reconnect_device(self, address: str) -> None:
        state = self.states.get(address)
        if state is None:
            return
        # A dongle must finish GATT discovery/start streaming for one link
        # before another AT+CONN is issued.  Unexpected dongle reset can make
        # several reconnect loops wake together, so serialize them through the
        # same first-packet guard used by manual connections.
        if getattr(self.source, "requires_ready_before_next_connect", False):
            while any(
                pending_address != address
                for pending_address in self._connect_in_progress
            ):
                await asyncio.sleep(0.1)
                if address not in self.states or not self.auto_reconnect_enabled:
                    return
            self._connect_in_progress.add(address)
        # Clear any latched firmware link state for this device before AT+CONN
        # (dongle only; no-op for PC Bluetooth).  Prevents a stale half-open
        # link from rejecting or racing the fresh connect, and settles the
        # firmware before the connect goes out.
        prepare_reconnect = getattr(self.source, "prepare_reconnect", None)
        if prepare_reconnect is not None:
            try:
                await prepare_reconnect(address)
            except Exception as exc:
                state.add_log(f"重連前清除連線狀態略過: {exc}")
        manager = self._create_ble_manager()
        manager.set_notify_callback(self._make_notify_emitter())
        manager.set_disconnect_callback(self._make_disconnect_emitter())
        try:
            await manager.connect(address)
            await manager.enable_default_notifications()
            try:
                await manager.request_200b()
            except Exception as exc:
                state.add_log(f"重新連線 200B 要求略過: {exc}")
            manager.start_200b_keeper()
        except Exception:
            self._connect_in_progress.discard(address)
            try:
                if manager.is_connected:
                    await manager.disconnect()
            except Exception:
                pass
            raise

        self.managers[address] = manager
        self._reconnecting_addresses.discard(address)
        state.is_connected = True
        state.add_log("已重新連線")
        if address in self._connect_in_progress:
            QTimer.singleShot(
                CONNECT_READY_GUARD_TIMEOUT_MS,
                lambda a=address, m=manager: self._expire_connect_guard(a, m),
            )
        if not self.active_address:
            self.active_address = address
        if self.active_address == address:
            self.state = state
        self._refresh_device_tabs()
        self.refresh_pages()

    @pyqtSlot(str, str, bytes)
    def _handle_notify(self, address: str, uuid: str, data: bytes) -> None:
        # Only a complete data packet proves GATT discovery/streaming is ready.
        # Dongle control frames and truncated notifications must not release the
        # guard and allow another AT+CONN too early.
        if _is_stream_payload(uuid, data):
            self._connect_in_progress.discard(address)
        state = self.states.get(address)
        if state is None:
            return
        event = parse_notify_packet(data, uuid, state)
        if event is not None:
            self._handle_event(event, state)
        # After parsing, if this packet carried data/limit (200B), see whether
        # it satisfies a pending error dialog.
        self._maybe_resolve_pending_error(address, state)
        logger = self.loggers.get(address)
        if logger is not None and logger.is_recording:
            logger.write_state(state)
        self.waveform_page.refresh_device(state, self.states, self.active_address)
        if address == self.active_address:
            self.refresh_pages()
        else:
            self._refresh_device_tabs()
            self.scan_panel.refresh_connected_devices(
                self._connected_summary(), self.active_address
            )

    def _expire_connect_guard(self, address: str, manager: DeviceManager) -> None:
        """Expire only the attempt that created this safety timer."""
        if self.managers.get(address) is manager:
            self._connect_in_progress.discard(address)

    def _handle_event(self, event: DataEvent, state: DeviceState | None = None) -> None:
        if event.kind == "error":
            self._schedule_error_dialog(state or self.state)

    def _schedule_error_dialog(self, state: DeviceState) -> None:
        """Defer the error dialog until the matching 200B brings data/limit.

        20B packets carry only error_num; data/limit only arrive in 200B.
        Showing the dialog the moment a 20B trips the error gives the user
        a blank details section. Wait briefly so the BLE keeper / firmware
        push fills in the values, then fall back to showing whatever we have.
        """
        address = state.device_address
        code = state.error_num
        if code == 0:
            return
        # If data/limit already present (e.g. 200B triggered the event), show
        # immediately and skip the wait.
        if state.error_data != 0 or state.error_limit != 0:
            self._show_error_dialog(state)
            return
        self._pending_error_codes[address] = code
        QTimer.singleShot(
            self._error_dialog_max_wait_ms,
            lambda: self._flush_pending_error(address),
        )

    def _maybe_resolve_pending_error(self, address: str, state: DeviceState) -> None:
        pending_code = self._pending_error_codes.get(address)
        if pending_code is None:
            return
        if state.error_num != pending_code:
            # Error cleared or changed before data arrived — drop the pending one.
            self._pending_error_codes.pop(address, None)
            return
        if state.error_data == 0 and state.error_limit == 0:
            return
        self._pending_error_codes.pop(address, None)
        self._show_error_dialog(state)

    def _flush_pending_error(self, address: str) -> None:
        pending_code = self._pending_error_codes.pop(address, None)
        if pending_code is None:
            return
        state = self.states.get(address)
        if state is None or state.error_num != pending_code:
            return
        self._show_error_dialog(state)

    def _ensure_error_log_dialog(self) -> ErrorLogDialog:
        if self._error_log_dialog is None:
            self._error_log_dialog = ErrorLogDialog(self)
        return self._error_log_dialog

    def _show_error_dialog(self, state: DeviceState) -> None:
        dialog = self._ensure_error_log_dialog()
        dialog.append_error(state)

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

    def _open_log_folder(self) -> None:
        try:
            self.log_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            QMessageBox.warning(self, "開啟錄製資料夾失敗", str(exc))
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.log_dir)))

    def _start_recording(self, address: str) -> Path | None:
        state = self.states.get(address)
        logger = self.loggers.get(address)
        if state is None or logger is None or not state.is_connected:
            return None
        if logger.is_recording:
            return logger.current_path
        path = logger.start(_device_tag(state), max_rows=self.record_split_rows)
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
                    "connected": "1" if state.is_connected else "0",
                    "reconnecting": "1" if addr in self._reconnecting_addresses else "0",
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
            self.demo2_page,
            self.log_page,
            self.error_page,
        )
        for page in pages:
            page.refresh(state)
        self.waveform_page.set_devices(self.states, self.active_address)
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

        timer = getattr(self, "_reconnect_health_timer", None)
        if timer is not None:
            timer.stop()
        for logger in self.loggers.values():
            logger.stop()
        for addr in list(self._reconnect_tasks):
            self._cancel_reconnect(addr)
        self._reconnecting_addresses.clear()
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
