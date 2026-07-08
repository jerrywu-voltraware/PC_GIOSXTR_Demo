from app.ble_manager import (
    build_advertising_table,
    fallback_device_display_base_name,
    format_device_display_name,
    is_supported_device_advertisement,
)
from app.csv_logger import CsvLogger
from app.models import DeviceState


def test_csv_logger_writes_flutter_header_and_rows(tmp_path):
    state = DeviceState()
    state.ptu_system_state_string = "P_Transfer"
    state.ptu_input_voltage = 10000
    state.pru_dyn_vout = 5000
    state.error_num = 7

    logger = CsvLogger(tmp_path)
    path = logger.start()
    logger.write_state(state)
    logger.stop()

    content = path.read_text(encoding="utf-8").splitlines()
    assert content[0].startswith("Sys_time,PTU_state,V_in,I_in")
    assert ",P_Transfer,10000," in content[1]
    assert content[1].endswith(",7,0,0")


def test_csv_logger_skips_empty_rows(tmp_path):
    state = DeviceState()
    logger = CsvLogger(tmp_path)
    path = logger.start()

    logger.write_state(state)
    logger.stop()

    assert len(path.read_text(encoding="utf-8").splitlines()) == 1


def _non_empty_state() -> DeviceState:
    state = DeviceState()
    state.ptu_input_voltage = 10000  # non-zero so write_state does not skip it
    return state


def test_csv_logger_filename_carries_part_number(tmp_path):
    logger = CsvLogger(tmp_path)
    path = logger.start("005")
    logger.stop()
    assert path.name.endswith("_005_p001.csv")


def test_csv_logger_splits_after_max_rows(tmp_path):
    logger = CsvLogger(tmp_path)
    first = logger.start("005", max_rows=2)
    assert first.name.endswith("_005_p001.csv")

    logger.write_state(_non_empty_state())  # part 1, row 1
    logger.write_state(_non_empty_state())  # part 1, row 2 -> marks pending roll
    assert logger.current_path is not None
    # Lazy roll: the next file is not opened until a real row needs it.
    assert logger.current_path.name.endswith("_005_p001.csv")
    logger.write_state(_non_empty_state())  # opens part 2, writes its first row
    assert logger.current_path.name.endswith("_005_p002.csv")
    logger.stop()

    files = sorted(p.name for p in tmp_path.glob("Log_*.csv"))
    assert len(files) == 2
    # part 1: header + 2 data rows; part 2: header + 1 data row
    assert len((tmp_path / files[0]).read_text(encoding="utf-8").splitlines()) == 3
    assert len((tmp_path / files[1]).read_text(encoding="utf-8").splitlines()) == 2
    # both parts share the same timestamp+suffix stem
    assert files[0][:-len("_p001.csv")] == files[1][:-len("_p002.csv")]


def test_csv_logger_no_trailing_empty_file_on_exact_multiple(tmp_path):
    logger = CsvLogger(tmp_path)
    logger.start("005", max_rows=2)
    for _ in range(4):  # exactly two full parts' worth of rows
        logger.write_state(_non_empty_state())
    logger.stop()

    files = sorted(p.name for p in tmp_path.glob("Log_*.csv"))
    assert len(files) == 2  # p001 and p002 only -- no empty p003
    for name in files:
        # every part carries header + 2 data rows; none is header-only
        assert len((tmp_path / name).read_text(encoding="utf-8").splitlines()) == 3


def test_csv_logger_no_split_when_max_rows_none(tmp_path):
    logger = CsvLogger(tmp_path)
    logger.start("005")  # default: no splitting
    for _ in range(5):
        logger.write_state(_non_empty_state())
    logger.stop()

    files = list(tmp_path.glob("Log_*.csv"))
    assert len(files) == 1
    assert len(files[0].read_text(encoding="utf-8").splitlines()) == 6  # header + 5 rows


def test_build_advertising_table_extracts_device_number_and_revision():
    rows, raw_hex, number, firmware = build_advertising_table(
        name="GIOS0403ST",
        tx_power=-4,
        service_uuids=[],
        service_data={},
        manufacturer_data={0x1234: bytes([0x10, 0x20, 0xEE, 0xEE, 5, 0x63, 0x03])},
        connectable=True,
    )

    assert number == 5
    assert firmware == "867"
    assert raw_hex.startswith("0x")
    assert any(row["TYPE"] == "0xFF" for row in rows)


def test_build_advertising_table_extracts_zero_number_from_separate_eeee_record():
    rows, raw_hex, number, firmware = build_advertising_table(
        name="GIOS0701ST",
        tx_power=0,
        service_uuids=[],
        service_data={},
        manufacturer_data={
            0x0501: bytes([0x2F, 0xEC, 0x17, 0xC9, 0xB4, 0x81]),
            0xEEEE: bytes([0x00, 0x75, 0x03]),
        },
        connectable=True,
    )

    assert number == 0
    assert firmware == "885"
    assert raw_hex.endswith("06FFEEEE007503")
    assert any(row["VALUE"] == "0xEEEE007503" for row in rows)
    assert format_device_display_name("GIOS0701ST", number) == "GIOS0701ST#0"


def test_format_device_display_name_only_omits_missing_number():
    assert format_device_display_name("GIOS0403ST", None) == "GIOS0403ST"


def test_supported_device_accepts_gios_manufacturer_number_without_name():
    assert is_supported_device_advertisement("", {0xEEEE: bytes([0x3C])})
    assert fallback_device_display_base_name("", {0xEEEE: bytes([0x3C])}) == "GIOS Device"


def test_supported_device_accepts_split_eeee_manufacturer_record():
    manufacturer_data = {0x0501: bytes([0x90, 0x04, 0x22, 0xB6, 0x96, 0x00, 0xEE, 0xEE, 0x3C])}

    assert is_supported_device_advertisement("", manufacturer_data)


def test_supported_device_accepts_any_gios_prefix_name():
    assert is_supported_device_advertisement("GIOS-S20-GW01", {})
    assert is_supported_device_advertisement("GIOS9999ST#71", {})
    assert not is_supported_device_advertisement("OTHER-S20-GW01", {})
