"""Compare page: field mapping, entry list, grouping, stats and persistence."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QSettings
from PyQt6.QtWidgets import QApplication

from app.models import DeviceState
from app.windows.compare_page import (
    COMPARABLE_FIELDS,
    COMPARE_SETTINGS_KEY,
    CompareEntry,
    ComparePage,
    comparable_field,
    load_entries,
    save_entries,
)
from app.windows.data_pages import PruPage, PtuPage


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def settings(tmp_path):
    return QSettings(str(tmp_path / "compare.ini"), QSettings.Format.IniFormat)


def _entry(address="A1", source="PTU", row="V_BUS", device="DEV1"):
    field, unit = comparable_field(source, row)
    return CompareEntry(address, device, source, row, field, unit)


def test_label_to_field_mapping():
    assert comparable_field("PTU", "V_BUS") == ("ptuBusVoltage", "mV")
    assert comparable_field("PRU", "V_Rect") == ("pruDynVrect", "mV")
    assert comparable_field("PTU", "V1_Voltage") == ("v1Voltage", "mV")
    assert comparable_field("PTU", "T_BUS") == ("busTempDegC", "C")
    assert len(COMPARABLE_FIELDS) == 26
    for source, label in (("PTU", "SYS_STATE"), ("PTU", "FW_Version"), ("PTU", "PTU_MAC"),
                          ("PRU", "Type"), ("PRU", "PRU_MAC"), ("PRU", "SYS_STATE")):
        assert comparable_field(source, label) is None


def test_context_menu_states(qt_app):
    page = PtuPage()
    page.refresh(DeviceState())
    added: set[str] = set()
    page.compare_is_added = lambda s, r: r in added
    rows = {page.table.item(r, 0).text(): r for r in range(page.table.rowCount())}
    menu = page.build_context_menu(rows["V_BUS"])
    assert [a.text() for a in menu.actions()] == ["加入比較", "開啟比較頁"]
    added.add("V_BUS")
    assert page.build_context_menu(rows["V_BUS"]).actions()[0].text() == "從比較移除"
    disabled = page.build_context_menu(rows["PTU_MAC"]).actions()[0]
    assert disabled.text() == "此欄位無法加入比較" and not disabled.isEnabled()
    got = []
    page.compare_toggle_requested.connect(lambda s, r: got.append((s, r)))
    page.build_context_menu(rows["I_BUS"]).actions()[0].trigger()
    assert got == [("PTU", "I_BUS")]


def test_add_remove_dedupe(qt_app, settings):
    page = ComparePage(settings=settings)
    assert page.add_entry(_entry())
    assert not page.add_entry(_entry())  # duplicate
    # System_EFF exists on both PTU and PRU but is one entry per address.
    assert page.add_entry(_entry(source="PTU", row="System_EFF"))
    assert not page.add_entry(_entry(source="PRU", row="System_EFF"))
    assert len(page.entries) == 2
    assert page.remove_entry(("A1", "ptuBusVoltage"))
    assert not page.remove_entry(("A1", "ptuBusVoltage"))
    assert [e.field_name for e in page.entries] == ["systemEff"]
    page.remove_all()
    assert page.entries == []
    assert not page.empty_label.isHidden()


def test_subplots_grouped_by_unit(qt_app, settings):
    page = ComparePage(settings=settings)
    page.add_entry(_entry(row="V_BUS"))
    page.add_entry(_entry(source="PRU", row="V_Rect"))  # same unit mV
    assert len(page._plots) == 1
    page.add_entry(_entry(row="I_BUS"))  # mA
    page.add_entry(_entry(row="T_BUS"))  # C
    assert len(page._plots) == 3
    page.remove_entry(("A1", "busTempDegC"))
    assert len(page._plots) == 2


def test_stats_and_current_value(qt_app, settings):
    page = ComparePage(settings=settings)
    page.add_entry(_entry())
    state = DeviceState(is_connected=True, device_address="A1")
    for i, v in enumerate((100, 200, 300)):
        state.ptu_bus_voltage = v
        page.feed("A1", state, now=page._t0 + i)
    page.feed("OTHER", state, now=page._t0 + 5)  # not in list: ignored
    page.set_devices({"A1": state})
    page.render()
    key = ("A1", "ptuBusVoltage")
    assert page.stats(key) == (300.0, 100.0, 300.0, 200.0)
    cells = [page.table.item(0, c).text() for c in range(3, 8)]
    assert cells == ["300 mV", "100 mV", "300 mV", "200 mV", "-"]
    page.set_cursor(1.1)
    assert page.table.item(0, 7).text() == "200 mV"
    state.is_connected = False
    page.set_devices({"A1": state})
    page.render()
    assert page.table.item(0, 3).text().startswith("-")


def test_v1_voltage_matches_ptu_page(qt_app, settings):
    state = DeviceState(is_connected=True, v1_voltage=123)
    ptu = PtuPage()
    ptu.refresh(state)
    shown = next(
        ptu.table.item(r, 1).text() for r in range(ptu.table.rowCount()) if ptu.table.item(r, 0).text() == "V1_Voltage"
    )
    page = ComparePage(settings=settings)
    page.add_entry(_entry(row="V1_Voltage"))
    page.feed("A1", state, now=page._t0)
    assert page.stats(("A1", "v1Voltage"))[0] == 1230.0
    assert shown == "1230 mV"


def test_all_fields_match_pages(qt_app, settings):
    state = DeviceState(
        is_connected=True, ptu_input_voltage=19000, ptu_input_current=650, ptu_bus_current=55, bus_temp_deg_c=-5,
        pru_dyn_vrect=5100, pru_dyn_vout=5000, pru_dyn_iout=777, i1_deg=7,
    )
    pages = {"PTU": PtuPage(), "PRU": PruPage()}
    page = ComparePage(settings=settings)
    for (source, label), (field, unit) in COMPARABLE_FIELDS.items():
        pg = pages[source]
        pg.refresh(state)
        shown = next(pg.table.item(r, 1).text() for r in range(pg.table.rowCount()) if pg.table.item(r, 0).text() == label)
        value = float(state.get_value(field))
        assert page.format_value(value, unit) == shown, (source, label)


def test_persistence_roundtrip_and_bad_json(qt_app, settings):
    entries = [_entry(), _entry(source="PRU", row="V_Rect", device="X")]
    save_entries(entries, settings)
    assert load_entries(settings) == entries
    page = ComparePage(settings=settings)
    assert page.entries == entries
    for bad in ("{not json", "123", '{"a": 1}', '[{"address": "x"}, 5]', ""):
        settings.setValue(COMPARE_SETTINGS_KEY, bad)
        assert load_entries(settings) == []
        assert ComparePage(settings=settings).entries == []


def test_save_image(qt_app, settings, tmp_path):
    page = ComparePage(settings=settings)
    page.add_entry(_entry())
    page.resize(800, 600)
    out = tmp_path / "c.png"
    assert page.save_image(str(out)) and out.stat().st_size > 0
