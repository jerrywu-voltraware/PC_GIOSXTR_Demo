"""Startup dialog: choose the data source (PC Bluetooth vs Nordic dongle)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PyQt6.QtCore import (
    QObject,
    QProcess,
    QRunnable,
    QStandardPaths,
    QThreadPool,
    pyqtSignal,
    pyqtSlot,
)
from PyQt6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from ..batch_log import batch_log
from ..constants import APP_VERSION
from ..updater import UpdateAsset, UpdateCheckResult, UpdateStatus, check_for_update, download_asset

# Nordic Semiconductor USB Vendor ID (nRF52840 dongle CDC).
NORDIC_VID = 0x1915

SOURCE_PC = "pc"
SOURCE_DONGLE = "dongle"


@dataclass
class SourceSelection:
    """Result of the source-selection dialog."""

    source: str  # SOURCE_PC | SOURCE_DONGLE
    port: str | None = None  # serial port device for the dongle, e.g. "COM5"


class _WorkerSignals(QObject):
    completed = pyqtSignal(object)
    failed = pyqtSignal(str)


class _UpdateCheckWorker(QRunnable):
    """Run the startup GitHub request without blocking the source dialog."""

    def __init__(self) -> None:
        super().__init__()
        self.signals = _WorkerSignals()

    @pyqtSlot()
    def run(self) -> None:
        try:
            self.signals.completed.emit(check_for_update(APP_VERSION))
        except Exception as exc:  # unexpected failure outside updater's mapping
            self.signals.failed.emit(str(exc))


class _UpdateDownloadWorker(QRunnable):
    """Download an accepted update while keeping the startup dialog responsive."""

    def __init__(self, asset: UpdateAsset, target_path: Path) -> None:
        super().__init__()
        self.asset = asset
        self.target_path = target_path
        self.signals = _WorkerSignals()

    @pyqtSlot()
    def run(self) -> None:
        try:
            self.signals.completed.emit(
                download_asset(self.asset, target_path=self.target_path)
            )
        except Exception as exc:
            self.signals.failed.emit(str(exc))


def _start_worker(worker: QRunnable) -> None:
    """Submit a startup worker (small seam for hardware/network-free tests)."""
    QThreadPool.globalInstance().start(worker)


def _start_detached_update(path: Path) -> bool:
    """Launch a downloaded EXE independently of the current application."""
    result = QProcess.startDetached(str(path), [], str(path.parent))
    if isinstance(result, tuple):
        return bool(result[0])
    return bool(result)


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

        self._update_status = QLabel("準備檢查是否有新版本...")
        self._update_status.setObjectName("startupUpdateStatus")
        self._update_status.setWordWrap(True)
        self._update_status.setStyleSheet("color: #555; padding: 4px 0 6px 0;")
        layout.addWidget(self._update_status)

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
        self._update_check_started = False
        self._update_check_running = False
        self._update_download_running = False
        self._update_worker: _UpdateCheckWorker | _UpdateDownloadWorker | None = None
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
            batch_log("STARTUP", f"Selected data source: Nordic dongle port={port}")
        else:
            self._selection = SourceSelection(SOURCE_PC, None)
            batch_log("STARTUP", "Selected data source: PC Bluetooth")
        self.accept()

    def _set_ok_enabled(self, enabled: bool) -> None:
        button = self._buttons.button(QDialogButtonBox.StandardButton.Ok)
        if button is not None:
            button.setEnabled(enabled)

    def _start_automatic_update_check(self) -> None:
        if self._update_check_started:
            return
        self._update_check_started = True
        self._update_check_running = True
        batch_log("UPDATE", f"Startup update check started; current={APP_VERSION}")
        self._set_ok_enabled(False)
        self._update_status.setText("正在檢查是否有新版本，完成後即可繼續...")

        worker = _UpdateCheckWorker()
        self._update_worker = worker
        worker.signals.completed.connect(self._handle_update_check_result)
        worker.signals.failed.connect(self._handle_update_check_failure)
        _start_worker(worker)

    @pyqtSlot(object)
    def _handle_update_check_result(self, result: UpdateCheckResult) -> None:
        self._update_check_running = False
        self._update_worker = None
        self._set_ok_enabled(True)
        latest = result.info.latest_version if result.info is not None else ""
        level = "ERROR" if result.status in (
            UpdateStatus.NETWORK_ERROR,
            UpdateStatus.INVALID_RESPONSE,
        ) else (
            "WARNING"
            if result.status not in (
                UpdateStatus.UP_TO_DATE,
                UpdateStatus.UPDATE_AVAILABLE,
            )
            else "INFO"
        )
        batch_log(
            "UPDATE",
            f"Startup update check completed status={result.status.value} "
            f"latest={latest} detail={result.message}",
            level=level,
        )

        if result.status is UpdateStatus.UPDATE_AVAILABLE and result.info is not None:
            info = result.info
            self._update_status.setText(
                f"發現新版 {info.latest_version}；可立即下載或稍後再更新。"
            )
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
                batch_log("UPDATE", f"User accepted download for {info.latest_version}")
                target_path = self._select_update_download_path(info.asset)
                if target_path is not None:
                    self._start_update_download(info.asset, target_path)
                else:
                    batch_log("UPDATE", f"User cancelled download for {info.latest_version}")
            else:
                batch_log("UPDATE", f"User deferred update {info.latest_version}")
            return

        if result.status is UpdateStatus.UP_TO_DATE:
            self._update_status.setText(result.message or f"目前版本 {APP_VERSION} 已是最新版本。")
        else:
            # Automatic startup checks stay non-blocking when GitHub/network is
            # unavailable. The Settings dialog still offers a detailed manual
            # check after entering the application.
            self._update_status.setText("暫時無法檢查更新；仍可繼續選擇連線方式。")

    @pyqtSlot(str)
    def _handle_update_check_failure(self, detail: str) -> None:
        self._update_check_running = False
        self._update_worker = None
        self._set_ok_enabled(True)
        self._update_status.setText("暫時無法檢查更新；仍可繼續選擇連線方式。")
        batch_log("UPDATE", f"Startup update check failed: {detail}", level="ERROR")

    def _select_update_download_path(self, asset: UpdateAsset) -> Path | None:
        downloads_dir = QStandardPaths.writableLocation(
            QStandardPaths.StandardLocation.DownloadLocation
        )
        base_dir = Path(downloads_dir) if downloads_dir else Path.home() / "Downloads"
        selected_path, _selected_filter = QFileDialog.getSaveFileName(
            self,
            "儲存更新檔",
            str(base_dir / asset.name),
            "Windows 執行檔 (*.exe);;所有檔案 (*)",
        )
        if not selected_path:
            return None
        path = Path(selected_path)
        if not path.suffix and asset.name.lower().endswith(".exe"):
            path = path.with_suffix(".exe")
        return path

    def _start_update_download(self, asset: UpdateAsset, target_path: Path) -> None:
        if self._update_download_running:
            return
        self._update_download_running = True
        batch_log("UPDATE", f"Downloading {asset.name} to {target_path}")
        self._set_ok_enabled(False)
        self._update_status.setText(f"正在下載 {asset.name} ...")

        worker = _UpdateDownloadWorker(asset, target_path)
        self._update_worker = worker
        worker.signals.completed.connect(self._handle_update_downloaded)
        worker.signals.failed.connect(self._handle_update_download_failure)
        _start_worker(worker)

    @pyqtSlot(object)
    def _handle_update_downloaded(self, path: Path) -> None:
        self._update_download_running = False
        self._update_worker = None
        self._set_ok_enabled(True)
        self._update_status.setText(f"新版已下載：{path.name}")
        batch_log("UPDATE", f"Update downloaded successfully: {path}")
        answer = QMessageBox.question(
            self,
            "更新已下載",
            f"已下載：\n{path}\n\n是否現在開啟新版？成功開啟後，目前版本會自動關閉。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if answer is QMessageBox.StandardButton.Yes:
            if not _start_detached_update(path):
                detail = f"無法啟動新版：{path}"
                self._update_status.setText("新版已下載，但無法自動開啟。")
                batch_log("UPDATE", detail, level="ERROR")
                QMessageBox.warning(self, "無法開啟新版", detail)
                return
            batch_log("UPDATE", f"Launched {path}; closing current version")
            self._update_status.setText("新版已開啟；目前版本即將自動關閉。")
            # Rejecting the startup dialog makes main() return before creating
            # the main window, so the old executable exits cleanly while the
            # detached new executable continues independently.
            self.reject()

    @pyqtSlot(str)
    def _handle_update_download_failure(self, detail: str) -> None:
        self._update_download_running = False
        self._update_worker = None
        self._set_ok_enabled(True)
        self._update_status.setText("新版下載失敗；仍可繼續使用目前版本。")
        batch_log("UPDATE", f"Update download failed: {detail}", level="ERROR")
        QMessageBox.warning(self, "更新下載失敗", detail)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._start_automatic_update_check()

    # -- public --------------------------------------------------------------

    def selection(self) -> SourceSelection | None:
        return self._selection

    @staticmethod
    def ask(parent: QWidget | None = None) -> SourceSelection | None:
        dialog = SourceSelectDialog(parent)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            return dialog.selection()
        return None
