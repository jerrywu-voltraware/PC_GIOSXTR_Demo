"""Application launcher for the GIOSXTR PyQt6 desktop app."""

from __future__ import annotations

import asyncio
import argparse
import os
import sys

from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication
from qasync import QEventLoop

from app.constants import APP_ICON_FILENAME, APP_NAME, APP_VERSION, APP_WINDOW_TITLE, ENGINEERING_MODE_ENV
from app.resources import resource_path
from app.windows.main_window import MainWindow


def _parse_args(argv: list[str]) -> tuple[argparse.Namespace, list[str]]:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--engineering", action="store_true", help="Enable internal engineering controls")
    parser.add_argument("-h", "--help", action="help", help="Show this help message and exit")
    return parser.parse_known_args(argv)


def _env_engineering_enabled() -> bool:
    value = os.getenv(ENGINEERING_MODE_ENV, "")
    return value.strip().lower() in {"1", "true", "yes", "on"}


def main() -> int:
    args, qt_args = _parse_args(sys.argv[1:])
    engineering_mode = bool(args.engineering or _env_engineering_enabled())

    app = QApplication([sys.argv[0], *qt_args])
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_WINDOW_TITLE)
    app.setApplicationVersion(APP_VERSION.removeprefix("V"))
    icon = QIcon(str(resource_path(APP_ICON_FILENAME)))
    if not icon.isNull():
        app.setWindowIcon(icon)

    loop = QEventLoop(app)
    asyncio.set_event_loop(loop)

    window = MainWindow(engineering_mode=engineering_mode)
    window.show()

    with loop:
        loop.run_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
