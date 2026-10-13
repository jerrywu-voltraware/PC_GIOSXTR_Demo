"""Offscreen, isolated UI layout and streaming verification.

Run from the repository root:
    py -3 -X utf8 scripts/verify_debug_ux.py

PNG captures and a machine-readable report go to build/ux-review. Settings,
CSV files, recent devices and batch logs stay in an automatically removed
temporary directory. No Bluetooth connection or scan is performed.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from time import perf_counter
from unittest.mock import patch

os.environ["QT_QPA_PLATFORM"] = "offscreen"
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PyQt6.QtCore import QPoint, QRect, QSettings, Qt
from PyQt6.QtGui import QFont, QFontDatabase
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QScrollArea

from app.batch_log import disable_batch_log_file, initialize_batch_log
from app.constants import UUID_NOTIFY_20B
from app.csv_logger import CsvLogger
from app.models import DeviceState
from app.recent_devices import RecentDeviceStore
from app.theme import apply_theme, theme_manager
from app.typography import typography_manager
from app.windows.main_window import MainWindow


def rect_info(rect):
    return [rect.x(), rect.y(), rect.width(), rect.height()]


def widget_info(widget, window):
    return {
        "rect": rect_info(QRect(widget.mapTo(window, QPoint()), widget.size())),
        "visible_rect": rect_info(widget.visibleRegion().boundingRect()),
        "size_hint": [widget.sizeHint().width(), widget.sizeHint().height()],
        "minimum_size_hint": [widget.minimumSizeHint().width(), widget.minimumSizeHint().height()],
        "font_points": widget.font().pointSizeF(),
        "fully_visible": widget.isVisible() and widget.visibleRegion().boundingRect().contains(widget.rect()),
    }


def sample_packet(index):
    payload = bytearray(20)
    payload[0] = 3
    payload[1:3] = (12000 + index % 200).to_bytes(2, "little")
    payload[3:5] = (1450).to_bytes(2, "little")
    payload[5:7] = (2400).to_bytes(2, "little")
    payload[7:9] = (1300).to_bytes(2, "little")
    payload[9] = 36
    payload[10] = 12
    payload[11] = 10
    payload[12:14] = (1800).to_bytes(2, "little")
    payload[14:16] = (1200).to_bytes(2, "little")
    payload[16:18] = (1250).to_bytes(2, "little")
    payload[18] = 32
    return bytes(payload)


def seed_recordings(window, directory):
    for index in range(2):
        address = f"AA:BB:CC:DD:EE:{index + 1:02X}"
        state = DeviceState(
            device_address=address,
            device_name=f"VOLTRAWARE Debug {index + 1:03d}",
            device_number=index + 1,
            is_connected=True,
            ptu_input_voltage=12000,
            ptu_input_current=1450,
            ptu_system_state=3,
            ptu_system_state_string="P_Transfer",
            pru_reg_item_state=10,
            pru_reg_item_state_string="PRU Registered",
            pru_dyn_vout=12000,
            pru_dyn_iout=1250,
            amp_temp_deg_c=36,
            bus_temp_deg_c=38,
            ic_temp_deg_c=35,
            pru_dyn_temp=32,
        )
        state.update_efficiency()
        for message in ("Connected: ready for long recording", "Warning: test warning", "Debug measurement active"):
            state.add_log(message)
        logger = CsvLogger(directory)
        logger.start(f"debug{index + 1:03d}", max_rows=1000)
        for _ in range(3):
            logger.write_state(state)
        window.states[address] = state
        window.loggers[address] = logger
    window.active_address = next(iter(window.states))
    window.state = window.states[window.active_address]
    window.log_dir = directory
    window.refresh_pages()
    # Exercise an actual chart as well as the waveform toolbar. These chart
    # preview samples are intentionally independent of the CSV stress counts.
    window.waveform_page.add_chart()
    for sample in range(120):
        for state in window.states.values():
            state.ptu_input_voltage = 12000 + sample % 40 * 5
            window.waveform_page.refresh_device(state, window.states, window.active_address)


def save_report(report, output):
    (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def capture_matrix(window, app, output, args, report):
    sidebar_names = (
        "scan_btn", "connect_btn", "clear_packet_counts_btn", "disconnect_btn",
        "disconnect_all_btn", "start_recording_btn", "stop_recording_btn",
        "start_recording_all_btn", "stop_recording_all_btn", "open_log_folder_btn",
    )
    panel_names = ("start_button", "stop_button", "open_button", "choose_button")
    for scale in args.scales:
        typography_manager().set_scale(scale, persist=False)
        for theme in args.themes:
            theme_manager().set_theme(theme, persist=False)
            for size in args.sizes:
                width, height = map(int, size.split("x"))
                window.resize(width, height)
                app.processEvents()
                window.resize(width, height)
                window.splitter.setSizes([min(340, width // 3), width - min(340, width // 3)])
                QTest.qWait(30)
                key = f"{theme}-{scale}-{size}"
                entry = {"id": key, "scale": scale, "theme": theme, "requested_size": [width, height],
                         "actual_size": [window.width(), window.height()], "issues": [], "pages": [],
                         "screenshots": [], "sidebar": {}, "recording_panel": {}}
                if window.width() > width or window.height() > height:
                    entry["issues"].append("Window minimum layout exceeds the requested size")
                for index in range(window.tabs.count()):
                    if args.plot_only and window.tabs.tabText(index) != "Waveform":
                        continue
                    window.tabs.setCurrentIndex(index)
                    app.processEvents()
                    page = window.tabs.currentWidget()
                    tab_rect = window.tabs.tabBar().tabRect(index)
                    info = {"name": window.tabs.tabText(index), "widget": widget_info(page, window),
                            "tab_rect": rect_info(tab_rect),
                            "tab_reachable": window.tabs.tabBar().rect().intersects(tab_rect)}
                    if not page.isVisible() or page.width() <= 0 or page.height() <= 0 or not info["tab_reachable"]:
                        entry["issues"].append(f"Tab is not reachable: {info['name']}")
                    if isinstance(page, QScrollArea):
                        content = page.widget()
                        info["content"] = widget_info(content, window)
                        info["scroll_range"] = {
                            "horizontal": page.horizontalScrollBar().maximum(),
                            "vertical": page.verticalScrollBar().maximum(),
                        }
                        page.verticalScrollBar().setValue(page.verticalScrollBar().maximum())
                        page.horizontalScrollBar().setValue(page.horizontalScrollBar().maximum())
                        app.processEvents()
                        bottom_right = content.mapTo(page.viewport(), content.rect().bottomRight())
                        info["content_bottom_right_reachable"] = page.viewport().rect().contains(bottom_right)
                        if not info["content_bottom_right_reachable"]:
                            entry["issues"].append(f"Page content cannot be reached by scrolling: {info['name']}")
                        page.verticalScrollBar().setValue(0)
                        page.horizontalScrollBar().setValue(0)
                        app.processEvents()
                    filename = f"{key}-{info['name'].lower()}.png"
                    if not window.grab().save(str(output / filename)):
                        entry["issues"].append(f"Screenshot failed: {filename}")
                    entry["screenshots"].append(filename)
                    if info["name"] == "Waveform" and window.waveform_page.charts:
                        plot = window.waveform_page.charts[0].plot
                        info["axis_titles"] = {
                            name: plot.getAxis(name).labelText for name in ("bottom", "left")
                        }
                        if not all(info["axis_titles"].values()):
                            entry["issues"].append("Waveform axis title disappeared after theme/text-scale change")
                        plot_filename = f"{key}-waveform-plot.png"
                        plot.grab().save(str(output / plot_filename))
                        entry["screenshots"].append(plot_filename)
                    entry["pages"].append(info)
                for name in panel_names:
                    widget = getattr(window.recording_panel, name)
                    info = widget_info(widget, window)
                    entry["recording_panel"][name] = info
                    if not info["fully_visible"]:
                        entry["issues"].append(f"Recording control clipped: {name}")
                for name in (() if args.plot_only else sidebar_names):
                    widget = getattr(window.scan_panel, name)
                    window.scan_panel.scroll_area.ensureWidgetVisible(widget, 8, 8)
                    app.processEvents()
                    info = widget_info(widget, window)
                    entry["sidebar"][name] = info
                    if not info["fully_visible"]:
                        entry["issues"].append(f"Sidebar control inaccessible after scrolling: {name}")
                if not args.plot_only:
                    filename = f"{key}-sidebar-recording.png"
                    window.grab().save(str(output / filename))
                    entry["screenshots"].append(filename)
                window.scan_panel.scroll_area.verticalScrollBar().setValue(0)
                window.scan_panel.scroll_area.horizontalScrollBar().setValue(0)
                report["matrix"].append(entry)
                save_report(report, output)
                print(f"{key}: {window.width()}x{window.height()}, {len(entry['issues'])} issues", flush=True)


def simulate_stream(window, app, directory, samples):
    if samples <= 0:
        return {"samples": 0, "skipped": True}
    for index in range(window.tabs.count()):
        page = window.tabs.widget(index)
        if page is window.log_page or (isinstance(page, QScrollArea) and page.widget() is window.log_page):
            window.tabs.setCurrentIndex(index)
            break
    window.log_page.pause_button.setChecked(True)
    frozen = window.log_page.text.toPlainText()
    addresses = list(window.states)
    before = {address: logger.rows_written for address, logger in window.loggers.items()}
    started = perf_counter()
    heartbeats = 0
    for index in range(samples):
        address = addresses[index % len(addresses)]
        window._handle_notify(address, UUID_NOTIFY_20B, sample_packet(index))
        if index % 10 < 2:
            window.states[address].add_log(f"Simulation received sample {index}")
        if index % 50 == 0:
            app.processEvents()
            heartbeats += 1
    QTest.qWait(250)
    paused_unchanged = window.log_page.text.toPlainText() == frozen
    window.log_page.pause_button.setChecked(False)
    elapsed = perf_counter() - started
    written = sum(logger.rows_written - before[address] for address, logger in window.loggers.items())
    paths = sorted(directory.glob("*.csv"))
    persisted_rows = 0
    file_checks = []
    for path in paths:
        with path.open(encoding="utf-8", newline="") as handle:
            rows = list(csv.reader(handle))
        persisted_rows += len(rows) - 1
        file_checks.append({"name": path.name, "data_rows": len(rows) - 1, "column_count": len(rows[0]),
                            "consistent_columns": all(len(row) == len(rows[0]) for row in rows)})
    return {
        "samples": samples, "seconds": round(elapsed, 3), "event_pump_cycles": heartbeats,
        "written_rows": written, "persisted_rows": persisted_rows,
        "expected_persisted_rows": samples + sum(before.values()),
        "paused_display_unchanged": paused_unchanged,
        "device_event_counts": {address: len(state.log_messages) for address, state in window.states.items()},
        "display_blocks": window.log_page.text.document().blockCount(), "csv_files": file_checks,
        "pass": written == samples and persisted_rows == samples + sum(before.values())
                and paused_unchanged and window.log_page.text.document().blockCount() <= 500
                and all(check["consistent_columns"] for check in file_checks),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "build" / "ux-review")
    parser.add_argument("--scales", nargs="+", type=int, default=[100, 125, 150, 175, 200])
    parser.add_argument("--themes", nargs="+", default=["light", "dark"])
    parser.add_argument("--sizes", nargs="+", default=["1366x768", "1024x768"])
    parser.add_argument("--samples", type=int, default=5000)
    parser.add_argument("--plot-only", action="store_true", help="Capture only waveform for targeted typography review")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    report = {"platform": "offscreen", "settings_isolated": True, "hardware_used": False,
              "capture_scope": "waveform" if args.plot_only else "all-pages", "matrix": [], "stress": None}
    with TemporaryDirectory(prefix="giosxtr-ux-") as temporary:
        directory = Path(temporary)
        QSettings.setDefaultFormat(QSettings.Format.IniFormat)
        QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(directory / "settings"))
        QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.SystemScope, str(directory / "system-settings"))
        app = QApplication.instance() or QApplication([])
        app.setOrganizationName("GIOSXTR-UX-Verification")
        app.setApplicationName("Isolated Debug UX Review")
        # Windows' offscreen plugin starts with an empty font database. Load
        # real system fonts explicitly so screenshots measure real glyphs.
        if not QFontDatabase.families():
            font_directory = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
            for font_name in ("segoeui.ttf", "msjh.ttc", "consola.ttf"):
                font_path = font_directory / font_name
                if font_path.exists():
                    QFontDatabase.addApplicationFont(str(font_path))
            if "Segoe UI" in QFontDatabase.families():
                app.setFont(QFont("Segoe UI", 11))
        report["font_families"] = QFontDatabase.families()
        report["base_font"] = app.font().toString()
        apply_theme(app, "light")
        initialize_batch_log(directory / "batch.txt")
        store = RecentDeviceStore(directory / "recent_devices.json")
        with patch("app.windows.main_window.RecentDeviceStore", return_value=store):
            window = MainWindow()
        try:
            seed_recordings(window, directory)
            window.show()
            app.processEvents()
            capture_matrix(window, app, args.output, args, report)
            report["stress"] = simulate_stream(window, app, directory, args.samples)
            report["pass"] = not any(entry["issues"] for entry in report["matrix"]) and (
                report["stress"].get("pass", report["stress"].get("skipped", False)))
            save_report(report, args.output)
            print(json.dumps({"pass": report["pass"], "matrix_cases": len(report["matrix"]),
                              "stress": report["stress"], "report": str(args.output / "report.json")},
                             ensure_ascii=False, indent=2), flush=True)
        finally:
            window.close()
            window.deleteLater()
            app.processEvents()
            disable_batch_log_file(clear_display=True)
    return 0 if report.get("pass") else 1


if __name__ == "__main__":
    raise SystemExit(main())
