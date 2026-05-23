"""GIOS040XST BLE packet decoding."""

from __future__ import annotations

from datetime import datetime

from .constants import UUID_IOT_NOTIFY, UUID_NOTIFY_200B, UUID_NOTIFY_20B
from .models import DataEvent, DeviceState


def le_u16(data: list[int], offset: int) -> int:
    return data[offset] | (data[offset + 1] << 8)


def le_u32(data: list[int], offset: int) -> int:
    return (
        data[offset]
        | (data[offset + 1] << 8)
        | (data[offset + 2] << 16)
        | (data[offset + 3] << 24)
    )


def signed16(value: int) -> int:
    return value - 65536 if value > 32767 else value


def mac_string(data: list[int]) -> str:
    return ":".join(f"{byte:02X}" for byte in data)


def ptu_state_string(state: int) -> str:
    return {
        0: "Config",
        1: "P_Save",
        2: "L_Power",
        3: "P_Transfer",
        4: "Latch_Fault",
        5: "Local_Fault",
        6: "Count",
        7: "OTA",
        8: "Cooling",
        9: "EXCEEDED_RANGE",
        10: "High_Vrect",
    }.get(state, "Unknown")


def pru_state_string(state: int) -> str:
    return {
        0: "Unused",
        1: "Pre Connect",
        2: "Fully Accepted",
        3: "Waiting to connect",
        4: "Connecting",
        5: "Reg enable alert",
        6: "PRU Stat RD",
        7: "PTU Stat WR",
        8: "PRU DY RD",
        9: "PRU CTL SEND",
        10: "PRU Registered",
    }.get(state, "Unknown")


def error_description(code: int) -> str:
    from .constants import ERROR_DESCRIPTIONS

    return ERROR_DESCRIPTIONS.get(code, "未知錯誤")


def error_name(code: int) -> str:
    from .constants import ERROR_NAMES

    return ERROR_NAMES.get(code, "UNKNOWN")


def is_pru_connected_state(state: int) -> bool:
    return state >= 4


def _set_ptu_state(state: DeviceState, value: int) -> DataEvent | None:
    old = state.ptu_system_state
    state.ptu_system_state = value
    state.ptu_system_state_string = ptu_state_string(value)
    if old != value:
        message = f"PTU State Change: {state.ptu_system_state_string}"
        state.add_log(message)
        return DataEvent("ptu_state", message, value)
    return None


def _set_pru_state(state: DeviceState, value: int) -> DataEvent | None:
    old = state.pru_reg_item_state
    state.pru_reg_item_state = value
    state.pru_reg_item_state_string = pru_state_string(value)
    if old != value:
        message = f"PRU Reg State Change: {state.pru_reg_item_state_string}"
        state.add_log(message)
        if not is_pru_connected_state(old) and is_pru_connected_state(value):
            return DataEvent("pru_connected", "PRU connected", value)
        return DataEvent("pru_state", message, value)
    return None


def _check_error_change(state: DeviceState) -> DataEvent | None:
    if state.error_num == state.last_error_num:
        return None
    state.last_error_num = state.error_num
    if state.error_num == 0:
        return None
    state.latest_error_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    description = error_description(state.error_num)
    message = (
        f"Error code 0x{state.error_num:02X} ({state.error_num}) - {description}; "
        f"data={state.error_data}; limit={state.error_limit}"
    )
    state.add_log(message)
    return DataEvent("error", message, state.error_num)


def parse_notify_packet(data: list[int] | bytes | bytearray, uuid: str, state: DeviceState) -> DataEvent | None:
    payload = list(data)
    uuid_l = uuid.lower()
    if uuid_l == UUID_IOT_NOTIFY:
        state.packet_count_iot += 1
        return decode_iot_packet(payload, state)
    if uuid_l == UUID_NOTIFY_20B:
        state.packet_count_20b += 1
        return decode_20b_packet(payload, state)
    if uuid_l == UUID_NOTIFY_200B:
        state.packet_count_200b += 1
        return decode_200b_packet(payload, state)
    state.add_log(f"Unknown notify UUID: {uuid}")
    return DataEvent("unknown_notify", f"Unknown notify UUID: {uuid}")


def decode_iot_packet(data: list[int] | bytes | bytearray, state: DeviceState) -> DataEvent | None:
    payload = list(data)
    if len(payload) < 15:
        return None

    event = _set_ptu_state(state, payload[0])

    if len(payload) >= 7:
        state.ptu_input_voltage = le_u16(payload, 1)
        state.ptu_input_current = le_u16(payload, 3)
        state.ptu_bus_voltage = le_u16(payload, 5)

    if len(payload) >= 15:
        state.v1_voltage = le_u16(payload, 7)
        state.i1_deg = signed16(le_u16(payload, 11))
        state.i3_deg = signed16(le_u16(payload, 13))
        state.i1_i3_phase_diff_deg = state.i3_deg - state.i1_deg

    if len(payload) >= 17:
        state.amp_temp_deg_c = payload[15]
        state.ptu_firmware_version = payload[16]

    if len(payload) >= 18:
        event = _set_pru_state(state, payload[17]) or event

    if len(payload) >= 25:
        state.pru_dyn_vrect = le_u16(payload, 18) * 10
        state.pru_dyn_vout = le_u16(payload, 20) * 10
        state.pru_dyn_iout = le_u16(payload, 22)
        state.pru_dyn_temp = payload[24]

    if len(payload) > 25:
        state.pru_type_string = {0x01: "0403V1", 0x02: "0404V1"}.get(payload[25], "-")

    if len(payload) > 31:
        state.pru_mac = mac_string(payload[26:32])

    if len(payload) > 32:
        state.pru_firmware_version = payload[32]

    if len(payload) > 48:
        state.ptu_mac = mac_string(payload[43:49])

    state.update_efficiency()
    return event


def decode_20b_packet(data: list[int] | bytes | bytearray, state: DeviceState) -> DataEvent | None:
    payload = list(data)
    if len(payload) < 20:
        return None

    event = _set_ptu_state(state, payload[0])
    state.ptu_input_voltage = le_u16(payload, 1)
    state.ptu_input_current = le_u16(payload, 3)
    state.ptu_bus_voltage = le_u16(payload, 5) * 10

    new_i3_current = le_u16(payload, 7)
    if new_i3_current > 0:
        state.i3_current = new_i3_current

    state.amp_temp_deg_c = payload[9]
    state.ptu_firmware_version = payload[10]
    event = _set_pru_state(state, payload[11]) or event
    state.pru_dyn_vrect = le_u16(payload, 12) * 10
    state.pru_dyn_vout = le_u16(payload, 14) * 10
    state.pru_dyn_iout = le_u16(payload, 16)
    state.pru_dyn_temp = payload[18]
    state.error_num = payload[19]
    event = _check_error_change(state) or event
    state.update_efficiency()
    return event


def decode_200b_packet(data: list[int] | bytes | bytearray, state: DeviceState) -> DataEvent | None:
    payload = list(data)
    if len(payload) < 193:
        return None

    event = _set_ptu_state(state, payload[0])
    state.ptu_input_voltage = le_u16(payload, 4)
    state.ptu_input_current = le_u16(payload, 6)
    state.ptu_bus_voltage = le_u32(payload, 8)
    state.ptu_bus_current = le_u16(payload, 12)
    state.bus_temp_deg_c = payload[20]
    state.amp_temp_deg_c = payload[21]
    state.ic_temp_deg_c = payload[22]

    new_i3_current = le_u16(payload, 26)
    if new_i3_current > 0:
        state.i3_current = new_i3_current

    state.v1_voltage = le_u16(payload, 28)
    state.i1_i3_phase_diff_deg = signed16(le_u16(payload, 30))
    state.ptu_firmware_version = le_u16(payload, 44)
    pru_state_value = le_u16(payload, 48)
    event = _set_pru_state(state, pru_state_value) or event
    state.pru_dyn_vrect = le_u16(payload, 52) * 10
    state.pru_dyn_irect = le_u16(payload, 54)
    state.pru_dyn_vout = le_u16(payload, 56) * 10
    state.pru_dyn_iout = le_u16(payload, 58)
    state.pru_dyn_temp = le_u16(payload, 60)
    state.pru_dyn_vrect_min = le_u16(payload, 62)
    state.pru_dyn_vrect_set = le_u16(payload, 64)
    state.pru_dyn_vrect_max = le_u16(payload, 66)

    state.pru_chg_tel_ofv = le_u16(payload, 74)
    state.pru_chg_t_bat = le_u16(payload, 76)
    state.pru_chg_p_out = le_u16(payload, 78)
    state.pru_chg_p_in = le_u16(payload, 80)
    state.pru_chg_eff = le_u16(payload, 82)
    state.pru_chg_i_out = le_u16(payload, 84)
    state.pru_chg_i_in = le_u16(payload, 86)
    state.pru_chg_v_bat = le_u16(payload, 88)
    state.pru_chg_v_in = le_u16(payload, 90)
    state.pru_chg_v_inr = le_u16(payload, 92)
    state.pru_chg_status_ofv = payload[94]
    state.pru_chg_charger = payload[95]
    state.pru_chg_system = payload[96]
    state.pru_chg_supply = payload[97]
    state.pru_chg_ts0_remain = payload[98]
    state.pru_chg_ts1_remain = payload[99]
    state.pru_chg_ts2_remain = payload[100]
    state.pru_chg_ts3_remain = payload[101]
    state.pru_chg_faults = payload[102]
    state.pru_chg_lt8491_status = payload[103]
    state.ptu_array_level = payload[188]
    state.ptu_dcdc_duty = le_u16(payload, 190)

    if len(payload) >= 204:
        state.error_num = payload[192]
        state.error_data = le_u32(payload, 196)
        state.error_limit = le_u32(payload, 200)
        event = _check_error_change(state) or event
    elif len(payload) > 192:
        state.error_num = payload[192]
        event = _check_error_change(state) or event

    state.update_efficiency()
    return event
