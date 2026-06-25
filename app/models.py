"""Shared application state models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class DataEvent:
    kind: str
    message: str
    value: int | None = None


@dataclass
class DeviceState:
    # PTU data
    ptu_system_state: int = 0
    ptu_system_state_string: str = "-"
    ptu_input_voltage: int = 0
    ptu_input_current: int = 0
    ptu_bus_voltage: int = 0
    ptu_bus_current: int = 0
    bus_temp_deg_c: int = 0
    amp_temp_deg_c: int = 0
    ic_temp_deg_c: int = 0
    i3_current: int = 0
    v1_voltage: int = 0
    i1_i3_phase_diff_deg: int = 0
    i1_deg: int = 0
    i3_deg: int = 0
    ptu_firmware_version: int = 0
    ptu_dcdc_duty: int = 0
    ptu_mac: str = ""
    ptu_array_level: int = 0

    # PRU data
    pru_mac: str = ""
    pru_reg_item_state: int = 0
    pru_reg_item_state_string: str = "-"
    pru_type_string: str = ""
    pru_firmware_version: int = 0
    pru_dyn_vrect: int = 0
    pru_dyn_irect: int = 0
    pru_dyn_vout: int = 0
    pru_dyn_iout: int = 0
    pru_dyn_temp: int = 0
    pru_dyn_vrect_min: int = 0
    pru_dyn_vrect_set: int = 0
    pru_dyn_vrect_max: int = 0

    # Charger data
    pru_chg_tel_ofv: int = 0
    pru_chg_t_bat: int = 0
    pru_chg_p_out: int = 0
    pru_chg_p_in: int = 0
    pru_chg_v_in: int = 0
    pru_chg_eff: int = 0
    pru_chg_i_out: int = 0
    pru_chg_i_in: int = 0
    pru_chg_v_bat: int = 0
    pru_chg_v_inr: int = 0
    pru_chg_status_ofv: int = 0
    pru_chg_charger: int = 0
    pru_chg_system: int = 0
    pru_chg_supply: int = 0
    pru_chg_faults: int = 0
    pru_chg_ts0_remain: int = 0
    pru_chg_ts1_remain: int = 0
    pru_chg_ts2_remain: int = 0
    pru_chg_ts3_remain: int = 0
    pru_chg_lt8491_status: int = 0

    # Error and counters
    error_num: int = 0
    last_error_num: int = 0
    error_data: int = 0
    error_limit: int = 0
    packet_count_200b: int = 0
    packet_count_20b: int = 0
    packet_count_iot: int = 0
    system_eff: float = 0.0

    # UI state
    is_connected: bool = False
    device_name: str = ""
    device_address: str = ""
    rssi: int = 0
    device_number: int | None = None
    advertising_raw: str = ""
    advertising_rows: list[dict[str, str]] = field(default_factory=list)
    log_messages: list[str] = field(default_factory=list)
    latest_error_time: str = ""

    def add_log(self, message: str) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        self.log_messages.insert(0, f"{timestamp}  {message}")
        del self.log_messages[500:]

    @property
    def input_power_w(self) -> float:
        return (self.ptu_input_voltage / 1000.0) * (self.ptu_input_current / 1000.0)

    @property
    def output_power_w(self) -> float:
        return (self.pru_dyn_vout / 1000.0) * (self.pru_dyn_iout / 1000.0)

    @property
    def total_packet_count(self) -> int:
        return self.packet_count_200b + self.packet_count_20b + self.packet_count_iot

    def reset_packet_counts(self) -> None:
        self.packet_count_200b = 0
        self.packet_count_20b = 0
        self.packet_count_iot = 0

    def update_efficiency(self) -> None:
        if self.input_power_w > 0 and self.output_power_w > 0:
            self.system_eff = self.output_power_w / self.input_power_w * 100.0
        else:
            self.system_eff = 0.0

    def get_value(self, field_name: str) -> str:
        value_map: dict[str, Any] = {
            "ptuInputVoltage": self.ptu_input_voltage,
            "ptuInputCurrent": self.ptu_input_current,
            "inputPower": f"{self.input_power_w:.2f}",
            "ptuBusVoltage": self.ptu_bus_voltage,
            "ptuBusCurrent": self.ptu_bus_current,
            "v1Voltage": self.v1_voltage * 10,
            "i3Current": self.i3_current,
            "i1Deg": self.i1_deg,
            "i3Deg": self.i3_deg,
            "i1I3PhaseDiffDeg": self.i1_i3_phase_diff_deg,
            "busTempDegC": self.bus_temp_deg_c,
            "ampTempDegC": self.amp_temp_deg_c,
            "icTempDegC": self.ic_temp_deg_c,
            "ptuDcdcDuty": self.ptu_dcdc_duty,
            "ptuArrayLevel": self.ptu_array_level,
            "pruDynVrect": self.pru_dyn_vrect,
            "pruDynIrect": self.pru_dyn_irect,
            "pruDynVout": self.pru_dyn_vout,
            "pruDynIout": self.pru_dyn_iout,
            "pruOutputPower": f"{self.output_power_w:.2f}",
            "pruDynTemp": self.pru_dyn_temp,
            "pruDynVrectMin": self.pru_dyn_vrect_min,
            "pruDynVrectSet": self.pru_dyn_vrect_set,
            "pruDynVrectMax": self.pru_dyn_vrect_max,
            "errorNum": self.error_num,
            "errorData": self.error_data,
            "errorLimit": self.error_limit,
            "pruChgVIn": f"{self.pru_chg_v_in / 100.0:.2f}",
            "pruChgIIn": self.pru_chg_i_in,
            "pruChgVBat": f"{self.pru_chg_v_bat / 100.0:.2f}",
            "pruChgIOut": self.pru_chg_i_out,
            "pruChgPIn": f"{self.pru_chg_p_in / 100.0:.2f}",
            "pruChgPOut": f"{self.pru_chg_p_out / 100.0:.2f}",
            "pruChgTBat": f"{self.pru_chg_t_bat / 10.0:.1f}",
            "pruChgEff": f"{self.pru_chg_eff / 100.0:.2f}",
            "systemEff": f"{self.system_eff:.2f}",
        }
        return str(value_map.get(field_name, "0"))

    def csv_values(self) -> list[str]:
        return [
            datetime.now().isoformat(sep=" ", timespec="seconds"),
            self.ptu_system_state_string,
            str(self.ptu_input_voltage),
            str(self.ptu_input_current),
            str(self.ptu_bus_voltage),
            str(self.ptu_bus_current),
            str(self.bus_temp_deg_c),
            str(self.amp_temp_deg_c),
            str(self.ic_temp_deg_c),
            str(self.v1_voltage * 10),
            str(self.i3_current),
            str(self.i1_i3_phase_diff_deg),
            str(self.ptu_dcdc_duty),
            str(self.ptu_array_level),
            f"{self.system_eff:.1f}",
            str(self.pru_dyn_vrect),
            str(self.pru_dyn_irect),
            str(self.pru_dyn_vout),
            str(self.pru_dyn_iout),
            str(self.pru_dyn_temp),
            str(self.pru_dyn_vrect_min),
            str(self.pru_dyn_vrect_set),
            str(self.pru_dyn_vrect_max),
            str(self.error_num),
            str(self.error_data),
            str(self.error_limit),
        ]
