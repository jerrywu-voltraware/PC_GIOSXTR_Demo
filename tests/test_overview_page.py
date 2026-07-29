from __future__ import annotations

import os


def test_temperature_summary_includes_all_ptu_and_pru_values():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from PyQt6.QtWidgets import QApplication

    from app.models import DeviceState
    from app.windows.overview_page import OverviewPage

    _app = QApplication.instance() or QApplication([])
    page = OverviewPage()
    state = DeviceState(
        bus_temp_deg_c=58,
        amp_temp_deg_c=39,
        ic_temp_deg_c=41,
        pru_dyn_temp=36,
    )

    page.refresh(state)

    assert page.labels["temp"].text() == (
        "PTU   BUS 58 °C   |   AMP 39 °C   |   IC 41 °C\n"
        "PRU   SYS 36 °C"
    )
    page.close()
