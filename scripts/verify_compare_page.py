"""Offscreen smoke for the Compare page wired into MainWindow.

Run from the repository root:
    py -3 -X utf8 scripts/verify_compare_page.py
Settings go to a temporary ini file; no Bluetooth is used.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PyQt6.QtCore import QSettings
from PyQt6.QtWidgets import QApplication

from app.models import DeviceState


def check(cond: bool, msg: str) -> None:
    print(("PASS " if cond else "FAIL ") + msg)
    if not cond:
        sys.exit(1)


def main() -> int:
    app = QApplication.instance() or QApplication([])
    with TemporaryDirectory() as tmp:
        QSettings.setDefaultFormat(QSettings.Format.IniFormat)
        QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, tmp)
        app.setOrganizationName("CompareSmoke")
        app.setApplicationName("CompareSmoke")
        from app.windows.main_window import MainWindow

        win = MainWindow()
        addr = "AA:BB:CC:DD:EE:01"
        state = DeviceState(is_connected=True, device_address=addr, device_name="GIOS0801ST", device_number=9)
        win.states[addr] = state
        win.state = state
        win.active_address = addr
        win.refresh_pages()

        tab_labels = [win.tabs.tabText(i) for i in range(win.tabs.count())]
        check(tab_labels.index("Compare") == tab_labels.index("Waveform") + 1, f"Compare tab after Waveform: {tab_labels}")

        for page, label in ((win.ptu_page, "V_BUS"), (win.pru_page, "V_Rect")):
            rows = {page.table.item(r, 0).text(): r for r in range(page.table.rowCount())}
            act = page.build_context_menu(rows[label]).actions()[0]
            check(act.text() == "加入比較", f"{page.title} {label} menu says add")
            act.trigger()
        cp = win.compare_page
        check(len(cp.entries) == 2, f"2 entries: {[e.legend_name for e in cp.entries]}")
        check(len(cp._plots) == 1, "both mV -> 1 subplot")
        check(win.pru_page.build_context_menu(
            next(r for r in range(win.pru_page.table.rowCount()) if win.pru_page.table.item(r, 0).text() == "V_Rect")
        ).actions()[0].text() == "從比較移除", "menu now says remove")

        for i in range(5):
            state.ptu_bus_voltage = 12000 + i
            state.pru_dyn_vrect = 5000 + i
            win.compare_page.feed(addr, state, now=cp._t0 + i)
        cp.render()
        print("current cells:", [cp.table.item(r, 3).text() for r in range(2)])
        check(cp.table.item(0, 3).text() == "12004 mV", "V_BUS current value")

        win.pru_page.compare_open_requested.emit()
        check(win.tabs.currentWidget().widget() is cp, "open compare switches tab")

        win.resize(1200, 800)
        win.show()
        app.processEvents()
        out = Path(tmp) / "compare.png"
        check(cp.save_image(str(out)) and out.stat().st_size > 0, "save image")

        win._toggle_compare("PRU", "V_Rect")
        check(len(cp.entries) == 1, "toggle removes entry")
        win._toggle_compare("PTU", "T_BUS")
        check(len(cp._plots) == 2, "mV + C -> 2 subplots")
        win.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
