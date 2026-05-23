from app.models import DeviceState
from app.protocol import (
    decode_20b_packet,
    decode_200b_packet,
    decode_iot_packet,
    parse_notify_packet,
)


def test_iot_short_packet_is_ignored():
    state = DeviceState()

    decode_iot_packet([1, 2, 3], state)

    assert state.ptu_system_state_string == "-"


def test_iot_packet_updates_core_values():
    state = DeviceState()
    data = [0] * 49
    data[0] = 3
    data[1] = 0x10
    data[2] = 0x27
    data[3] = 0x20
    data[4] = 0x4E
    data[5] = 0x34
    data[6] = 0x12
    data[7] = 0x44
    data[8] = 0x33
    data[11] = 0xFF
    data[12] = 0xFF
    data[13] = 0x01
    data[14] = 0x00
    data[15] = 45
    data[16] = 8
    data[17] = 10
    data[18] = 0x20
    data[19] = 0x03
    data[20] = 0x30
    data[21] = 0x04
    data[22] = 0x40
    data[23] = 0x05
    data[24] = 30
    data[25] = 2
    data[26:32] = [1, 2, 3, 4, 5, 6]
    data[32] = 9
    data[43:49] = [10, 11, 12, 13, 14, 15]

    decode_iot_packet(data, state)

    assert state.ptu_system_state_string == "P_Transfer"
    assert state.ptu_input_voltage == 10000
    assert state.ptu_input_current == 20000
    assert state.ptu_bus_voltage == 0x1234
    assert state.v1_voltage == 0x3344
    assert state.i1_deg == -1
    assert state.i3_deg == 1
    assert state.i1_i3_phase_diff_deg == 2
    assert state.amp_temp_deg_c == 45
    assert state.ptu_firmware_version == 8
    assert state.pru_reg_item_state_string == "PRU Registered"
    assert state.pru_dyn_vrect == 8000
    assert state.pru_dyn_vout == 10720
    assert state.pru_dyn_iout == 1344
    assert state.pru_dyn_temp == 30
    assert state.pru_type_string == "0404V1"
    assert state.pru_mac == "01:02:03:04:05:06"
    assert state.ptu_mac == "0A:0B:0C:0D:0E:0F"


def test_20b_packet_updates_core_values():
    state = DeviceState()
    data = [
        3,
        0x10,
        0x27,
        0x20,
        0x4E,
        0x01,
        0x02,
        0x34,
        0x12,
        45,
        8,
        10,
        0x20,
        0x03,
        0x30,
        0x04,
        0x40,
        0x05,
        30,
        7,
    ]

    event = decode_20b_packet(data, state)

    assert state.ptu_system_state_string == "P_Transfer"
    assert state.ptu_input_voltage == 10000
    assert state.ptu_input_current == 20000
    assert state.ptu_bus_voltage == 5130
    assert state.i3_current == 0x1234
    assert state.amp_temp_deg_c == 45
    assert state.ptu_firmware_version == 8
    assert state.pru_reg_item_state_string == "PRU Registered"
    assert state.pru_dyn_vrect == 8000
    assert state.pru_dyn_vout == 10720
    assert state.pru_dyn_iout == 1344
    assert state.pru_dyn_temp == 30
    assert state.error_num == 7
    assert event and event.kind == "error"
    assert state.latest_error_time


def test_200b_short_packet_is_ignored():
    state = DeviceState()

    decode_200b_packet([1, 2, 3], state)

    assert state.ptu_system_state_string == "-"


def test_200b_packet_updates_charger_and_error_fields():
    state = DeviceState()
    data = [0] * 204
    data[0] = 8
    data[4] = 0x10
    data[5] = 0x27
    data[6] = 0x20
    data[7] = 0x4E
    data[8] = 1
    data[12] = 0x22
    data[13] = 0x11
    data[20] = 25
    data[21] = 35
    data[22] = 45
    data[26] = 0x34
    data[27] = 0x12
    data[28] = 0x78
    data[29] = 0x56
    data[30] = 0xFF
    data[31] = 0xFF
    data[44] = 0x63
    data[45] = 0x03
    data[48] = 10
    data[52] = 0x20
    data[53] = 0x03
    data[54] = 0x66
    data[55] = 0x01
    data[56] = 0x30
    data[57] = 0x04
    data[58] = 0x40
    data[59] = 0x05
    data[60] = 33
    data[62] = 1
    data[64] = 2
    data[66] = 3
    data[76] = 0xE8
    data[77] = 0x03
    data[78] = 0x10
    data[79] = 0x27
    data[80] = 0x20
    data[81] = 0x4E
    data[82] = 0x30
    data[83] = 0x75
    data[84] = 0x44
    data[85] = 0x33
    data[86] = 0x55
    data[87] = 0x22
    data[88] = 0x10
    data[89] = 0x27
    data[90] = 0x20
    data[91] = 0x4E
    data[94] = 1
    data[95] = 2
    data[96] = 3
    data[97] = 4
    data[98] = 5
    data[99] = 6
    data[100] = 7
    data[101] = 8
    data[102] = 9
    data[103] = 10
    data[188] = 4
    data[190] = 0x11
    data[191] = 0x22
    data[192] = 0x11
    data[196] = 1
    data[200] = 2

    event = decode_200b_packet(data, state)

    assert state.ptu_system_state_string == "Cooling"
    assert state.ptu_input_voltage == 10000
    assert state.ptu_input_current == 20000
    assert state.ptu_bus_voltage == 1
    assert state.ptu_bus_current == 0x1122
    assert state.i1_i3_phase_diff_deg == -1
    assert state.ptu_firmware_version == 0x0363
    assert state.ptu_array_level == 4
    assert state.ptu_dcdc_duty == 0x2211
    assert state.pru_reg_item_state_string == "PRU Registered"
    assert state.pru_dyn_vrect == 8000
    assert state.pru_dyn_irect == 0x0166
    assert state.pru_dyn_vout == 10720
    assert state.pru_dyn_iout == 1344
    assert state.pru_chg_t_bat == 1000
    assert state.pru_chg_v_bat == 10000
    assert state.error_num == 0x11
    assert state.error_data == 1
    assert state.error_limit == 2
    assert event and event.kind == "error"


def test_200b_pru_connected_transition_returns_event_without_error():
    state = DeviceState()
    data = [0] * 204
    data[48] = 10

    event = decode_200b_packet(data, state)

    assert event and event.kind == "pru_connected"


def test_parse_notify_packet_routes_by_uuid():
    state = DeviceState()
    data = [0] * 20
    data[0] = 1

    parse_notify_packet(data, "6455e670-a146-11e2-9e96-0800200c9a69", state)

    assert state.packet_count_20b == 1
    assert state.ptu_system_state_string == "P_Save"
