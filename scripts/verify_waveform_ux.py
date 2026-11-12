"""Offscreen smoke test for the Waveform page UX (layout, x-link, screenshots).

Usage: py -3 -X utf8 scripts/verify_waveform_ux.py [output_dir]  (default: a temp dir, never the repo)
"""

from __future__ import annotations

import math
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PyQt6.QtWidgets import QApplication  # noqa: E402

from app.models import DeviceState  # noqa: E402
from app.windows.waveform_page import WaveformPage  # noqa: E402

FIELDS = ("ptuInputVoltage", "ptuInputCurrent", "ptuBusVoltage", "pruDynVout")


def main() -> int:
    out_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(tempfile.mkdtemp(prefix="waveform_ux_"))
    out_dir.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    page = WaveformPage()
    page.resize(1600, 1000)
    page.show()
    for name in FIELDS:
        page.add_chart(name)
    devices = [
        DeviceState(is_connected=True, device_name="A", device_address="A", device_number=6),
        DeviceState(is_connected=True, device_name="B", device_address="B", device_number=10),
    ]
    states = {d.device_address: d for d in devices}
    page.scope_combo.setCurrentIndex(page.scope_combo.findData("all"))
    for i in range(400):
        for k, dev in enumerate(devices):
            dev.ptu_input_voltage = 52000 + 800 * math.sin(i / 15 + k)
            dev.ptu_input_current = 1200 + 300 * math.sin(i / 9 + k)
            dev.ptu_bus_voltage = 12000 + 500 * math.cos(i / 20 + k)
            dev.pru_dyn_vout = 5000 + 200 * math.sin(i / 11 - k)
            page.refresh_device(dev, states, "A")
    for _ in range(4):
        app.processEvents()
    page._flush_dirty()
    app.processEvents()

    viewport = page.scroll.viewport()
    failures = []
    for chart in page.charts:
        bottom = chart.plot.mapTo(viewport, chart.plot.rect().bottomLeft()).y()
        top = chart.plot.mapTo(viewport, chart.plot.rect().topLeft()).y()
        print(f"{chart.field_name}: plot y {top}..{bottom} viewport h {viewport.height()} plot h {chart.plot.height()}")
        if top < 0 or bottom > viewport.height():
            failures.append(f"{chart.field_name} outside viewport")
    if page.scroll.verticalScrollBar().isVisible() or page.scroll.verticalScrollBar().maximum() > 0:
        failures.append("vertical scrollbar needed")
    ranges = [c.plot.plotItem.vb.viewRange()[0] for c in page.charts]
    print("x ranges:", ranges)
    for r in ranges[1:]:
        if abs(r[0] - ranges[0][0]) > 1e-6 or abs(r[1] - ranges[0][1]) > 1e-6:
            failures.append("x ranges differ")
    shot_a = out_dir / "waveform_ux_a_expanded.png"
    page.grab().save(str(shot_a))

    page.set_chart_collapsed(page.charts[1], True)
    page.delta_box.setChecked(True)
    page.crosshair_box.setChecked(True)
    page._place_delta_cursor(page.charts[0], 250.0)
    page._place_delta_cursor(page.charts[0], 330.0)
    for _ in range(3):
        app.processEvents()
    shot_b = out_dir / "waveform_ux_b_collapsed_analysis.png"
    page.grab().save(str(shot_b))
    page.set_chart_collapsed(page.charts[1], False)
    for _ in range(3):
        app.processEvents()
    heights = [c.cursor_label.height() for c in page.charts if c.cursor_label.isVisible()]
    line_h = page.charts[0].cursor_label.fontMetrics().height()
    print("cursor label heights:", heights, "line height:", line_h)
    if any(h > line_h + 8 for h in heights):
        failures.append("cursor label taller than one line")
    shot_c = out_dir / "waveform_ux_c_delta_compact.png"
    page.grab().save(str(shot_c))
    for shot in (shot_a, shot_b, shot_c):
        print("saved", shot, shot.exists() and shot.stat().st_size)
        if not shot.exists():
            failures.append(f"missing {shot}")
    if failures:
        print("FAIL:", failures)
        return 1
    print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
