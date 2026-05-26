"""Application constants shared by BLE, protocol, CSV, and UI code."""

from __future__ import annotations

APP_NAME = "PC GIOSXTR Demo"
APP_VERSION = "V1.0.10"
APP_WINDOW_TITLE = f"{APP_NAME} {APP_VERSION}"
APP_ICON_FILENAME = "1024.png"
APP_EXECUTABLE_NAME = "PC_GIOSXTR_Demo_V1.0.10"
ENGINEERING_MODE_ENV = "PC_GIOSXTR_ENGINEERING"

SUPPORTED_DEVICES = (
    "Central",
    "GIOS0003ST",
    "GIOS0007ST",
    "GIOS0403ST",
    "GIOS0404ST",
    "GIOS0701ST",
    "GIOS0801ST",
)

RSSI_MINIMUM = -90

UUID_NOTIFY_200B = "6455e670-a146-11e2-9e96-0800200c9a67"
UUID_WRITE_200B = "6455e670-a146-11e2-9e96-0800200c9a68"
UUID_NOTIFY_20B = "6455e670-a146-11e2-9e96-0800200c9a69"
UUID_IOT_WRITE = "6455fff1-a146-11e2-9e96-0800200c9a67"
UUID_IOT_NOTIFY = "6455fff2-a146-11e2-9e96-0800200c9a67"

CSV_HEADER = (
    "Sys_time",
    "PTU_state",
    "V_in",
    "I_in",
    "V_bus",
    "I_bus",
    "T_bus",
    "T_amp",
    "T_IC",
    "V1",
    "I3",
    "I1I3_Deg",
    "DCDC_Duty",
    "Array",
    "EFF",
    "V_rect",
    "I_rect",
    "V_out",
    "I_out",
    "T_sys",
    "Vrect_min",
    "Vrect_set",
    "Vrect_max",
    "Error_code",
    "Error_data1",
    "Error_data2",
)

SIGNAL_DEFINITIONS = (
    ("V_in (mV)", "ptuInputVoltage"),
    ("I_in (mA)", "ptuInputCurrent"),
    ("Input Power (W)", "inputPower"),
    ("V_bus (mV)", "ptuBusVoltage"),
    ("I_bus (mA)", "ptuBusCurrent"),
    ("T_bus (C)", "busTempDegC"),
    ("T_amp (C)", "ampTempDegC"),
    ("T_IC (C)", "icTempDegC"),
    ("V1 (mV)", "v1Voltage"),
    ("I3 (mA)", "i3Current"),
    ("I1_Deg", "i1Deg"),
    ("I3_Deg", "i3Deg"),
    ("I1I3_Deg", "i1I3PhaseDiffDeg"),
    ("DCDC_Duty", "ptuDcdcDuty"),
    ("Array", "ptuArrayLevel"),
    ("EFF (%)", "systemEff"),
    ("V_rect (mV)", "pruDynVrect"),
    ("I_rect (mA)", "pruDynIrect"),
    ("V_out (mV)", "pruDynVout"),
    ("I_out (mA)", "pruDynIout"),
    ("Output Power (W)", "pruOutputPower"),
    ("T_sys (C)", "pruDynTemp"),
    ("Vrect_min (mV)", "pruDynVrectMin"),
    ("Vrect_set (mV)", "pruDynVrectSet"),
    ("Vrect_max (mV)", "pruDynVrectMax"),
    ("Error_code", "errorNum"),
    ("Error_data1", "errorData"),
    ("Error_data2", "errorLimit"),
)

ERROR_CODES: tuple[tuple[int, str, str], ...] = (
    (0x00, "ERROR_NONE", "無錯誤"),
    (0x01, "ERROR_PTU_OT_PA", "PTU PA 過溫"),
    (0x02, "ERROR_PTU_OT_DCDC", "PTU DCDC 過溫"),
    (0x03, "ERROR_PTU_OT_IC", "PTU IC 過溫"),
    (0x10, "ERROR_PTU_OC_I_IN", "PTU Iin 電流過流"),
    (0x11, "ERROR_PTU_OC_I_BUS", "PTU IBUS 電流過流"),
    (0x12, "ERROR_PTU_OC_I_1", "PTU I1 電流過流"),
    (0x13, "ERROR_PTU_OC_I_3", "PTU I3 電流過流"),
    (0x20, "ERROR_PTU_I1I3_DEG", "PTU I1/I3 相位異常"),
    (0x30, "ERROR_PTU_COMM_ERR", "PTU 通訊錯誤"),
    (0x40, "ERROR_PTU_TIMESET_FAIL", "PTU Timeset 失敗"),
    (0xA0, "ERROR_PRU_OV", "PRU 過壓"),
    (0xA1, "ERROR_PRU_OC", "PRU 過流"),
    (0xA2, "ERROR_PRU_OT", "PRU 過溫"),
    (0xA3, "ERROR_PRU_CHARGED", "PRU 已充滿"),
    (0xB0, "ERROR_PTU_LP_STUCK", "PTU Low Power 卡住"),
    (0xB1, "ERROR_PTU_PT_STUCK", "PTU Power Transfer 卡住"),
    (0xB2, "CHARGE_COMPLETE", "充電完成"),
    (0xB3, "CLEAR_COMPLETE", "重新啟動充電"),
)

ERROR_DESCRIPTIONS: dict[int, str] = {code: desc for code, _name, desc in ERROR_CODES}
ERROR_NAMES: dict[int, str] = {code: name for code, name, _desc in ERROR_CODES}
