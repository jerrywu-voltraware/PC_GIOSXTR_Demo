"""Application launcher for the GIOSXTR PyQt6 desktop app."""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication, QMessageBox
from qasync import QEventLoop

from app.batch_log import batch_log, initialize_batch_log, install_exception_logging
from app.constants import APP_ICON_FILENAME, APP_NAME, APP_VERSION, APP_WINDOW_TITLE, ENGINEERING_MODE_ENV
from app.device_source import DeviceSource, PcBleSource
from app.resources import resource_path
from app.theme import apply_light_theme
from app.windows.main_window import MainWindow
from app.windows.source_select_dialog import SOURCE_DONGLE, SourceSelectDialog


APP_ORGANIZATION = "GIOSXTR"


def _parse_args(argv: list[str]) -> tuple[argparse.Namespace, list[str]]:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--engineering", action="store_true", help="Enable internal engineering controls")
    parser.add_argument(
        "--startup-probe",
        action="store_true",
        help="Verify the packaged Python runtime and imports, then exit",
    )
    parser.add_argument("-h", "--help", action="help", help="Show this help message and exit")
    return parser.parse_known_args(argv)


def _env_engineering_enabled() -> bool:
    value = os.getenv(ENGINEERING_MODE_ENV, "")
    return value.strip().lower() in {"1", "true", "yes", "on"}


def main() -> int:
    args, qt_args = _parse_args(sys.argv[1:])
    if args.startup_probe:
        return 0
    engineering_mode = bool(args.engineering or _env_engineering_enabled())

    app = QApplication([sys.argv[0], *qt_args])
    app.setOrganizationName(APP_ORGANIZATION)
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_WINDOW_TITLE)
    app.setApplicationVersion(APP_VERSION.removeprefix("V"))
    apply_light_theme(app)
    icon = QIcon(str(resource_path(APP_ICON_FILENAME)))
    if not icon.isNull():
        app.setWindowIcon(icon)

    loop = QEventLoop(app)
    asyncio.set_event_loop(loop)
    batch_path = initialize_batch_log(Path.cwd() / "logs" / "batch.txt")
    install_exception_logging(loop)
    batch_log(
        "APP",
        f"Session started version={APP_VERSION} engineering={engineering_mode} "
        f"batch_file={batch_path}",
    )

    # Choose the data source before building the main window. The PC built-in
    # Bluetooth path is unchanged; the dongle path feeds the same UI over USB.
    # Loop so a failed dongle open (busy/missing port) re-prompts instead of
    # crashing the app.
    source: DeviceSource
    while True:
        selection = SourceSelectDialog.ask()
        if selection is None:
            batch_log("APP", "Source selection cancelled; application exiting")
            return 0

        if selection.source == SOURCE_DONGLE and selection.port:
            from app.device_source import DongleSource

            try:
                source = DongleSource(selection.port, loop=loop)
            except Exception as exc:
                batch_log(
                    "DONGLE",
                    f"Failed to open serial port {selection.port}: {exc}",
                    level="ERROR",
                )
                QMessageBox.critical(
                    None,
                    "無法開啟序列埠",
                    f"開啟 {selection.port} 失敗：\n{exc}\n\n"
                    "請確認：\n"
                    "• 沒有其他程式佔用此埠（另一個本程式視窗、序列埠監看工具、"
                    "PuTTY / Tera Term / nRF Connect 等）\n"
                    "• dongle 已正確插入並燒錄新韌體\n\n"
                    "排除後請重新選擇。",
                )
                continue
            batch_log("APP", f"Data source opened: Nordic dongle port={selection.port}")
        else:
            source = PcBleSource()
            batch_log("APP", "Data source opened: PC Bluetooth")
        break

    window = MainWindow(source=source, engineering_mode=engineering_mode)
    window.show()
    batch_log("APP", "Main window shown")

    with loop:
        loop.run_forever()
    batch_log("APP", "Session ended")
    return 0


if __name__ == "__main__":
    sys.exit(main())
