# nRF52840 Dongle 韌體 0xFF03 (NRF_FAULT_ID_APP_MEMACC) 分析與修復

日期: 2026-07-28
韌體: `d:\jerry\Python\PC_GIOSXTR_Demo\PTU_to_Azure\NRF52840-DONGLE\Rpi_USB_BLE\examples\ble_central\ble_app_multilink_central\main.c`
巢狀 repo: `PTU_to_Azure\NRF52840-DONGLE\Rpi_USB_BLE\.git` (branch 上有未 commit 的 2026-07-21 WDT 改動)

現象: PC App 按「中斷目前裝置」→ 韌體 fault → `app_error_fault_handler` 存 `last_err=0xFF03` →
`NVIC_SystemReset()` → `RESETREAS=0x00000004 [SREQ]` → Windows 重新列舉 USB CDC。

---

## 0. 結論摘要（先讀這段）

**0xFF03 的根因目前無法從靜態分析證實，必須靠故障 PC 定位。** 這是本次交付的核心：已實作
跨 reset 的 fault 記錄（id / pc / info / err_code / line / file 指標 / SCB 故障暫存器），
開機時附在既有 DIAG 行後面輸出。**下一步必須上機重現一次，把 `fault_pc` 交回來才能定案。**

同時，在「PC 下斷線指令」這條路徑上找到 **5 處證據鏈完整、會導致晶片重置的缺陷**
（`APP_ERROR_CHECK` 掛在 SoftDevice 合法回傳錯誤的呼叫上）。這些會造成同樣的
「dongle 忽然重置 → USB 重新列舉」症狀，但它們產生的 `last_err` 是 SDK 錯誤碼
（例如 `0x0008` / `0x0013`），**不是 0xFF03**，所以它們是「另一組同症狀的 bug」，
不是本次觀察到的 0xFF03 的解釋。已全部修掉。

### 2026-07-28 Codex 接手後的收尾狀態

本節是最新狀態，若與後面的 Claude 分析當時狀態衝突，以本節為準。

| 審查項目 | 處置 | 驗證 |
|---|---|---|
| WDT handler 直接寫 `NRF_POWER` 可能再觸發 APP_MEMACC，且 `0xFF02` 與 SDK assert 撞碼 | **已修正**：handler 保持空白，只靠 `RESETREAS.DOG` 辨識 WDT；不再寫 GPREGRET | Keil 完整 rebuild 通過 |
| 5 個 SoftDevice API 回傳碼被過度忽略 | **已修正**：只放行已知的暫時性 `NRF_ERROR_RESOURCES`／`NRF_ERROR_INVALID_STATE`／`NRF_ERROR_BUSY`，其他錯誤仍進 `APP_ERROR_CHECK` | Keil 完整 rebuild 通過 |
| 第二個 Keil target 的 IRAM1 仍覆蓋 `0x20038000` | **已修正**：`0x200043A8 / 0x33C58`，終點同樣停在 `0x20038000` | XML 解析確認兩個 target 均不覆蓋 fault record |
| HardFault 註解宣稱全程不使用 stack | **已修正註解**：只有先寫 GPREGRET 的步驟不依賴 helper call；擴充記錄明確標為 best-effort | 原始碼審查 + Keil build |
| PC 端只保存 `DIAG:`，遺失 `DIAG2:`／`WARN:`／`ERROR:SCAN` | **已修正並補測試**：上述韌體診斷均寫入 `dongle_runtime.log` | pytest 覆蓋 |
| HEX／MAP 是舊產物，可能燒到未套 patch 韌體 | **已修正**：主 target 已重建；燒錄腳本會拒絕過期 HEX、缺少 `fault_record_store` 或 IRAM1 上限錯誤的 MAP | ARMCC 0 error/0 warning；MAP 符號與區域檢查通過 |
| 單槽 fault record 可能被連續 fault 覆寫 | **接受的限制**：目前保存最後一筆，`n=` 保留累積次數；若實機證實有重置迴圈再改雙槽 | 尚需實機 |
| bootloader 是否清除／使用保留 RAM | **尚未驗證**：若 `last_err=0xFF03` 但沒有 fault record，需依實測再搬移位址 | 尚需實機 |

2026-07-28 本機以 Keil ARMCC V5.06 update 7 重建 `nrf52840_xxaa`：
`Code=71684, RO-data=6596, RW-data=12776, ZI-data=25352`，結果為
**0 Error(s), 0 Warning(s)**。MAP 可找到 `fault_record_store`，且
`RW_IRAM1 Max: 0x00028000`。這證明 patch 可編譯與連結，但不能取代 dongle 實機重現。

---

## 1. 0xFF03 的語意（已查證，非推測）

`components\softdevice\s140\headers\nrf_sdm.h:178-182`

> `NRF_FAULT_ID_APP_MEMACC` — Application invalid memory access. The info parameter will
> contain **0x00000000, in case of SoftDevice RAM access violation**. In case of SoftDevice
> peripheral register violation the info parameter will contain the **sub-region number of
> PREGION[0]**, on whose address range the **disallowed write access** caused the memory
> access fault.

三個關鍵推論：

1. **只有「寫入」會觸發**（`disallowed write access`）。所以陣列的「越界讀取」不會產生 0xFF03。
2. `info == 0` ⇒ app 寫到了 **SoftDevice RAM**（本專案為 `0x20000000..0x2000FFFF`，
   因為 Keil IRAM1 起點是 `0x20010000`，見 `_build\nrf52840_xxaa.sct`）。
3. `info != 0` ⇒ app 寫到了 **被封鎖的週邊暫存器**，`info` 就是 PREGION[0] 的 4KB 子區號
   （子區 N ⇔ 位址 `0x4000N000`）。

`nrf_sdm.h:281` 另有一條對本次實作很重要的限制：**fault callback 跑在 HardFault context，
不得呼叫任何 SVC（即任何 `sd_*`）**。所以 fault handler 內只能直接寫暫存器 / RAM。

⇒ **`info` 欄位本身就是二分法**：一次上機重現就能立刻分辨「寫到 SD RAM」還是
「寫到禁用週邊」，再配合 `pc` 直接定位到程式碼行。這就是必須先做診斷的理由。

---

## 2. 已證實的缺陷（證據鏈完整）

> 分類標記：**[已證實-重置路徑]** = 證據鏈完整、確實會造成「斷線後晶片重置」，
> 但**不是** 0xFF03 的成因。**[防禦性]** = 低風險加固，未證實與本次故障有關。

### 2.1 [已證實-重置路徑] `scan_start()` 對 `nrf_ble_scan_start()` 用 `APP_ERROR_CHECK`

證據鏈：

1. `main.c:1472`（斷線事件）、`main.c:1501`（連線逾時）、`main.c:1059`
   （`NRF_BLE_SCAN_EVT_CONNECTING_ERROR`）都會呼叫 `scan_start()`。
   **`main.c:1472` 正是 PC 下 `AT+DISC` / `AT+DISC=<MAC>` 之後必經的路徑。**
2. `scan_start()` 原本第 1113 行是 `APP_ERROR_CHECK(ret)`。
3. `components\ble\nrf_ble_scan\nrf_ble_scan.c:1109-1142`：`nrf_ble_scan_start()`
   **只吞掉 `NRF_ERROR_INVALID_STATE`**（1134-1138），其餘錯誤原封不動回傳給呼叫者。
4. `components\softdevice\s140\headers\ble_gap.h:2571`：`sd_ble_gap_scan_start()` 在
   role slot 不足時回 `NRF_ERROR_RESOURCES`——連線建立/拆除期間正是 role slot 最緊的時刻。
5. `APP_ERROR_CHECK` → `app_error_handler` → `app_error_fault_handler` → `NVIC_SystemReset()`。

⇒ 斷線瞬間任何暫時性 scan 啟動錯誤都會重置晶片。**已修**：改為回報
`ERROR:SCAN START 0x%04X` 並保持 `m_scanning=false`，讓下一次 `AT+SCAN` 重試。
（產生的 `last_err` 會是 `0x0013` 等 SDK 碼，故不解釋 0xFF03。）

### 2.2 [已證實-重置路徑] 連線拆除競態下的 4 個 `APP_ERROR_CHECK`

以下 4 處呼叫的 SoftDevice API 在「連線正在拆除」狀態下**依文件會合法回傳錯誤**
（`NRF_ERROR_INVALID_STATE` / `NRF_ERROR_BUSY`），但原本都掛 `APP_ERROR_CHECK` → 重置晶片：

| 位置（改動前行號） | 呼叫 | 拆除期典型回傳 |
|---|---|---|
| `main.c:1512` `BLE_GAP_EVT_CONN_PARAM_UPDATE_REQUEST` | `sd_ble_gap_conn_param_update` | INVALID_STATE / BUSY |
| `main.c:1523` `BLE_GAP_EVT_PHY_UPDATE_REQUEST` | `sd_ble_gap_phy_update` | INVALID_STATE |
| `main.c:1533` `BLE_GATTC_EVT_TIMEOUT` | `sd_ble_gap_disconnect` | INVALID_STATE（已斷線） |
| `main.c:1543` `BLE_GATTS_EVT_TIMEOUT` | `sd_ble_gap_disconnect` | INVALID_STATE（已斷線） |

情境非常具體：PC 下 `AT+DISC` → `sd_ble_gap_disconnect()` 發出 → 對端此時剛好送出
排隊中的 PHY / conn-param update request → 事件到達時連線已在拆除 → app 回應失敗 → 重置。

⇒ **已修**：改為輸出 `WARN:...` 一行並繼續執行。這些不會遮蔽真正的記憶體故障
（它們是 API 回傳值，不是 fault），所以不違反「不要用 recovery 掩蓋 crash」。

### 2.3 [防禦性] `main.c:1483` `m_device_rssi[conn_handle]` 漏掉邊界檢查

同一個 `BLE_GAP_EVT_DISCONNECTED` case 內，所有其他 `m_device_*[conn_handle]` 存取都包在
`if (p_gap_evt->conn_handle < NRF_SDH_BLE_CENTRAL_LINK_COUNT)`（`main.c:1453`）之內，
**只有第 1483 行的 `int8_t last_rssi = m_device_rssi[p_gap_evt->conn_handle];` 在檢查之外。**

誠實評估：這是**越界讀取**，依 §1 推論 1（MWU 只抓寫入）**不會**產生 0xFF03；而且
`NRF_SDH_BLE_TOTAL_LINK_COUNT == NRF_SDH_BLE_CENTRAL_LINK_COUNT == 8`（sdk_config.h:11603/11610），
斷線事件的 conn_handle 實務上恆為 0..7。⇒ 純加固，已修。

### 2.4 [防禦性] `main.c:1639` `db_disc_handler()` 以 conn_handle 索引 `m_lbs_c[]` 無邊界檢查

`ble_lbs_on_db_disc_evt(&m_lbs_c[p_evt->conn_handle], p_evt)` — 取的是位址並交給
會**寫入**該指標的函式。但索引為 unsigned，只會往高位址偏移（app RAM 方向），
**不可能落到 0x20010000 以下的 SD RAM**，所以同樣不解釋 0xFF03。已加邊界檢查。
（附帶發現：`ble_db_discovery_start()` 在整個 main.c 內從未被呼叫，此 handler 疑似死碼——未確認。）

---

## 3. 已排除的假設（附排除理由，避免下次重複繞路）

| 假設 | 排除理由 |
|---|---|
| ISR 優先權踩到 SoftDevice 保留區 (0/1/4) → SVC 從高優先權 ISR 呼叫失敗 | sdk_config.h 內**每一個** `*_CONFIG_IRQ_PRIORITY` 都是 6（WDT:4948/6275、APP_TIMER:6418、USBD:4856/6200…）。只有未編譯的 DTM 是 2/3。`_PRIO_APP_LOW = 6`（app_util_platform.h:75-84）> SVC 的 4 ⇒ 合法 |
| `CRITICAL_REGION` 嵌套（`usb_printf` 內再呼叫 `usb_send`）造成狀態損毀 | `app_util_platform.c:64-90` 走 `sd_nvic_critical_region_enter(&nested)`，巢狀由 SoftDevice 的 `nrf_nvic_state` 追蹤，正確 |
| 堆疊溢位灌進 SoftDevice RAM | `_build\nrf52840_xxaa.map:8364,9942`：`STACK` 位於 `0x200174C8`，大小 8192，`__initial_sp = 0x200194C8`（map:8913）。堆疊往下長會先吃掉 0x20010000..0x200174C8 這 29,896 bytes 的 app ZI，**碰不到 0x20010000 以下**。故直接溢位≠MEMACC |
| `ble_lbs_c` 的 notify 緩衝溢位 | `ble_lbs_c.c:421-433` 有 `copy_len = min(hvx_len, BLE_LBS_C_MAX_NOTIFY_DATA_LEN=244)`，且 main.c 端 `notifydata[384] >= 244`，安全 |
| `ble_lbs_c` 把 stack-local 緩衝交給 SoftDevice | `nrf_ble_gq.c:77-85` 用 `nrf_memobj_alloc` + `nrf_memobj_write` **深拷貝**，stack-local 不需存活 |
| `ble_lbs_c` 內有 conn_handle 索引越界 | 該檔完全沒有以 conn_handle 為索引的陣列（全部走 caller 提供的 `ble_lbs_c_t*`） |
| USB CDC RX 的 `static uint8_t index` 越界 / `arr[index-1]` 下標為 -1 | 逐步追過迴圈：`index` 在讀取點恆為 1..243，`sizeof(m_cdc_data_array)=BLE_NUS_MAX_DATA_LEN=244`（MTU 247），且 244 < 256 不會 uint8_t 溢位。安全 |
| USB TX ring buffer 索引越界 | `usb_tx_kick()` 的 `chunk = min(count, 4096 - tail, 256)`，`m_tx_active[256]`，邊界正確 |
| 2026-07-21 的 WDT 改動導致 0xFF03 | `RESETREAS = 0x04` **只有 SREQ、沒有 DOG 位元 (0x02)** ⇒ 看門狗根本沒觸發，`wdt_event_handler` 未執行。WDT 亦非 SoftDevice 封鎖週邊，reload 15000ms → CRV=491520 合法 |
| `app_error_fault_handler` 自己寫 `NRF_POWER->GPREGRET` 就是那個 MEMACC | 它跑在 HardFault context（`nrf_sdm.h:281`），MWU IRQ（SD 用 prio 0/1）無法插隊，不會遞迴故障；而且 0xFF03 確實被成功寫入並讀回，證明該路徑可完成 |

---

## 4. 推測清單（未證實，各附驗證方法）

### P1 — `wdt_event_handler` 在 SD 啟用中直接寫 `NRF_POWER->GPREGRET`（**latent，會偽造 0xFF03**）
`main.c:1783-1784`（改動前）在 **WDT ISR 的正常中斷 context** 寫 POWER 暫存器。
POWER 位於 `0x40000000` = PREGION[0] 子區 **0**。若 SoftDevice 把 POWER 列入 MWU 監看，
這個寫入會產生 `NRF_FAULT_ID_APP_MEMACC` **且 `info == 0`**（與「寫到 SD RAM」無法區分）。
- **本次故障不是它**（無 DOG 位元），但這是個定時炸彈：一旦 WDT 真的逾時，DIAG 會顯示
  `last_err=0xFF03` 而誤導方向。
- 驗證方法：把主迴圈餵狗暫時註解掉，等 ~15s 讓 WDT 逾時，看 DIAG 是否出現
  `RESETREAS=...[DOG SREQ]` 且 `fault_pc` 指向 `wdt_event_handler`。
- 建議修法（未套用，屬行為改動）：`wdt_event_handler` 改成空函式（純靠
  `RESETREAS` 的 DOG 位元判斷來源即可），或改用 `sd_power_gpregret_set()`。

### P2 — 掃描 window == interval（100% duty cycle）造成射頻餓死與連線風暴
`main.c:1090-1091`：`m_scan.scan_params.interval = NRF_BLE_SCAN_SCAN_INTERVAL;`
接著 `m_scan.scan_params.window = NRF_BLE_SCAN_SCAN_INTERVAL;` ← **window 被設成 interval**。
sdk_config.h:250 `NRF_BLE_SCAN_SCAN_INTERVAL = 160` ⇒ 100ms/100ms = 連續掃描。
搭配最多 8 條連線、`NRF_SDH_BLE_GAP_EVENT_LENGTH = 6`（7.5ms），射頻嚴重超訂。
- 這可能是 §2.1 的 `NRF_ERROR_RESOURCES` 真正頻繁發生的原因，也可能是 PC 端看到
  「莫名斷線」的來源。**不是 MEMACC 的成因。**
- 驗證方法：把 window 改成 interval 的一半（80）後長時間跑，統計 `DISCONNECTED reason=0x08`
  （supervision timeout）與 `ERROR:SCAN START` 的次數變化。
- 未套用：改掃描時序是行為改動，且需長時間現場統計才能判斷是否更好。

### P3 — `scan_resume_fast()` 是多餘的重複武裝，且會誤清 `m_scanning`
`nrf_ble_scan.c:949-957` 顯示 **module 自己會在呼叫 app handler 之後**無條件
`sd_ble_gap_scan_start(NULL, &scan_buffer)` 重新武裝掃描器。因此 `main.c:947-964` 的
`scan_resume_fast()` 是重複動作。副作用：若它的兩次呼叫都失敗，會把 `m_scanning` 設成
false 並回報錯誤，但緊接著 module 又成功武裝 ⇒ **狀態旗標與硬體反相**（掃描器在跑但
`m_scanning==false`）。後續 `AT+SCAN` / `scan_start()` 會走完整重啟路徑，可自我修正，
故非致命，但也非必要。
- 驗證方法：註解掉 `scan_resume_fast()` 呼叫，確認 `AT+SCANDBG` 仍持續有 MATCH/OTHER 輸出。
- 未套用：屬「移除既有防護」，無硬體無法驗證。

### P4 — 共用格式化緩衝 + ZI 被踩壞後產生野指標寫入 SD RAM
`usb_printf` 用全域 `usb_printf_data[384]`，`send_binary_packet` 的 `OUT_UART_BINARY` 分支
也用同一塊。雖然 `usb_printf` 整段包在 critical region 內（`main.c:2603-2610`），但
`send_binary_packet` 的那段沒有。若這類共用狀態被踩壞，理論上可能產生一個落在
`0x20000000..0x2000FFFF` 的野寫入 → 0xFF03。**這是純推測，沒有證據鏈。**
- 驗證方法：等 `fault_pc` 出來後直接比對是否落在這些函式範圍內。

### P5 — bootloader 是否會清掉 fault 記錄區（影響診斷本身）
soft reset 後 MBR → bootloader → app。若 bootloader 的堆疊落在 RAM 頂端，可能覆寫記錄區。
本次刻意把記錄放在 `0x20038000`（IRAM1 之外），**上方留約 32KB** 給 bootloader 堆疊。
- 驗證方法：見 §6 步驟 5。若 `last_err` 有值（例如 0xFF03）但 `fault_pc=0x00000000`
  且沒有 DIAG2 行，就是記錄區被清掉了 → 改把 `FAULT_RECORD_ADDR` 往下移
  （例如 `0x20030000`，並把 IRAM1 改成 `0x20000`）再試。

---

## 5. 已套用的改動

檔案 1：`...\examples\ble_central\ble_app_multilink_central\main.c`

行號取自 `git diff --unified=0` 的 hunk header（改動後檔案，共 2802 行）。

| 行號（改動後） | 內容 | 分類 |
|---|---|---|
| 117-206 | 新增跨 reset fault 記錄區：`FAULT_RECORD_ADDR 0x20038000`、`FAULT_RECORD_MAGIC`、`fault_record_t`（64 bytes / 16 words）、12 個 `m_fault_*` 開機快照變數、`fault_record_store()` | **診斷（必做）** |
| 1202-1217 | `scan_start()`：只有 `NRF_ERROR_RESOURCES` 視為暫時性並回報；其他錯誤仍進 `APP_ERROR_CHECK`；失敗時保持 `m_scanning=false` | [已證實-重置路徑] §2.1 |
| 1584-1590 | `BLE_GAP_EVT_DISCONNECTED`：`m_device_rssi[conn_handle]` 加邊界檢查（超界回 0） | [防禦性] §2.3 |
| 1619-1624 | `CONN_PARAM_UPDATE_REQUEST`：改為 `WARN:CONN_PARAM_UPDATE` 不重置 | [已證實-重置路徑] §2.2 |
| 1635-1640 | `PHY_UPDATE_REQUEST`：改為 `WARN:PHY_UPDATE` 不重置 | [已證實-重置路徑] §2.2 |
| 1650-1655 | `BLE_GATTC_EVT_TIMEOUT`：改為 `WARN:GATTC_TIMEOUT_DISC` 不重置 | [已證實-重置路徑] §2.2 |
| 1665-1669 | `BLE_GATTS_EVT_TIMEOUT`：改為 `WARN:GATTS_TIMEOUT_DISC` 不重置 | [已證實-重置路徑] §2.2 |
| 1765-1770 | `db_disc_handler()`：conn_handle 邊界檢查 | [防禦性] §2.4 |
| 1823-1844 | `first_message_timer_handler()`：DIAG 行**附加** `fault_pc= fault_id= fault_info= n=`；有記錄時多輸出一行 `DIAG2: err= line= file= hfsr= cfsr= bfar= mmfar=` | **診斷（必做）** |
| 1885-1912 | `app_error_fault_handler()`：解析 `error_info_t` / `assert_info_t` 取出 err_code/line/file 指標，呼叫 `fault_record_store(id, pc, info, ...)`。GPREGRET 行為與原本完全相同 | **診斷（必做）** |
| 1928-1934 | `HardFault_Handler()`：先寫 GPREGRET（不需堆疊），再記 SCB 的 `HFSR/CFSR/BFAR/MMFAR` | **診斷（必做）** |
| 1967-1985 | `main()`：開機讀回 fault 記錄到 `m_fault_*`，之後只清 `magic`（刻意保留 `count`/`count_magic`） | **診斷（必做）** |

未列入上表的 diff hunk（`+77`、`+1038`、`+2034`、`+2051`）**不是本次改動**，是 2026-07-21
那次未 commit 的 WDT 啟用（`nrf_drv_wdt.h` include、`scan_resume_fast` 回傳碼檢查、
`main()` 內的 WDT init 與餵狗）。

檔案 2：`...\pca10056\s140\arm5_no_packs\ble_app_multilink_central_pca10056_s140.uvprojx`

| 行號 | 內容 |
|---|---|
| 304 | target `nrf52840_xxaa` 的 `OCR_RVCT9`（= IRAM1）`<Size>` 由 `0x30000` → `0x28000` |

### 為什麼用「縮小 IRAM1 + 固定位址」而不是 `.noinit` section

- 專案是 **ARM Compiler 5 / armcc**（`uvprojx:14` `<uAC6>0</uAC6>`），且
  **沒有手寫 scatter file**（`uvprojx:373` `<ScatterFile>` 為空 ⇒ Keil 每次 build
  自動產生 `_build\nrf52840_xxaa.sct`）。
- 自動產生的 scatter 只有一句 `RW_IRAM1 0x20010000 0x00030000 { .ANY (+RW +ZI) }`
  ——`.ANY` 會吃掉任何自訂 section 名稱，而該 execution region **沒有 `UNINIT` 屬性**，
  所以 `__attribute__((section(".noinit"), zero_init))` 仍會被 scatter-load 清零。
  map 檔全域搜尋 `noinit` 也是 0 命中（確認目前沒有任何 UNINIT 區）。
- 換成手寫 .sct 會放棄「Use Memory Layout from Target Dialog」，維護成本高。
- 因此改為 **把 IRAM1 由 0x30000 縮成 0x28000**，讓 `0x20038000` 起完全落在任何
  execution region 之外 ⇒ 連結器不配置、scatter-load 不清零、SREQ 軟重置不清 RAM。
- 餘裕檢查：目前 RW+ZI 只用 **38,088 bytes**（map:10082 `Total RW Size ... 38088`），
  縮到 0x28000 = 163,840 bytes 仍有 4 倍餘裕。
- `0x20038040..0x20040000` 約 32KB 刻意留白，給 MBR/bootloader 的堆疊，降低被覆寫的風險（見 P5）。
- ⚠ **維護規則**：日後若在 Keil Target 對話框調整 IRAM1 大小，必須同步檢查
  `main.c` 的 `FAULT_RECORD_ADDR`。此規則已寫成 main.c:127-133 的註解。

### 當時沒有動的東西（歷史紀錄）

- **PC 端 `app/`、`tests/`：本次任務未觸碰。**
  但主 repo 的工作區內確實有 5 個 PC 端檔案被修改：
  `app/device_source.py`、`app/windows/main_window.py`、`app/windows/scan_panel.py`、
  `tests/test_dongle_source.py`、`tests/test_scan_panel.py`（mtime 2026-07-28 14:46-14:48，
  早於本次 main.c 的 15:14）。**那是 PC 端容錯的另一個 agent 的產出，不是本次韌體任務改的。**
  已用 `git status --short` 與 mtime 交叉確認，本次工作只寫入韌體 repo 內的 2 個檔案。
- 主 repo 的 `.gitignore`：未觸碰。
- `PTU_to_Azure/` 目錄未刪除、未重建。
- `sdk_config.h`：**未由本次改動修改**（diff 中的 8 行是 2026-07-21 那次 WDT 啟用留下的未 commit 改動）。
- `_build/*`、`JLinkLog.txt`、`*.uvoptx`、`*.uvguix.*`：這是 Claude 分析完成時的狀態；Codex 接手後已實際 rebuild，因此 build artifacts 現在已更新。

### git diff --stat 驗證（在巢狀 repo `PTU_to_Azure\NRF52840-DONGLE\Rpi_USB_BLE` 內執行）

只針對本次應該被改的三個原始檔：

```
 .../ble_central/ble_app_multilink_central/main.c   | 255 ++++++++++++++++++++-
 ...ble_app_multilink_central_pca10056_s140.uvprojx |  12 +-
 .../pca10056/s140/config/sdk_config.h              |   8 +-
 3 files changed, 259 insertions(+), 16 deletions(-)
```

逐檔核對：
- `main.c` 255 行 = 本次新增的診斷+修補 **加上** 2026-07-21 未 commit 的 WDT/scan_resume_fast 改動。
- `uvprojx` 12 行：實際 diff 只有 3 個 hunk — 我改的 `0x30000→0x28000` **1 行**，
  另外兩個 hunk（各 5 行）是 2026-07-21 加入 `nrfx_wdt.c` 到兩個 target 的檔案清單。
- `sdk_config.h` 8 行：全部是 2026-07-21 的 WDT 開關，**本次未動**。
- XML well-formed 已用 `xml.etree.ElementTree` 驗證通過；解析後確認
  target `nrf52840_xxaa` 的 IRAM1 = `0x20010000 / 0x28000`。

完整 `git diff --stat` 另含 11 個 build artifact（`_build/*`、`JLinkLog.txt`、
`*.uvoptx`、`*.uvguix.USER01`），皆為對話開始前就已存在的未 commit 變更。

### Claude 分析階段的靜態檢查（其後已由實際編譯取代）

- 括號/大括號/方括號平衡：自製 tokenizer（會正確跳過註解與字串字面值）掃全檔 → 完全平衡、
  0 個 mismatch。檔案實際共 **2802 行**（該 tokenizer 因為會吞掉區塊註解內的換行，
  自報 2633 行——不影響平衡判定，但別誤用它的行數）。
- printf 格式符 vs 參數個數逐一手數：DIAG 11:11、DIAG2 7:7、4 個 `WARN:` 各 2:2、
  `ERROR:SCAN START` 1:1 → 全部相符。
- 型別確認：`error_info_t{ uint32_t line_num; uint8_t const* p_file_name; uint32_t err_code; }`
  與 `assert_info_t{ uint32_t line_num; uint8_t const* p_file_name; }`
  已對照 `components\libraries\util\app_error.h:80-93` 確認欄位名稱與型別。
- `SCB->HFSR/CFSR/BFAR/MMFAR`：CMSIS-Core(M4) `SCB_Type` 標準成員。CMSIS 標頭來自 Keil
  安裝目錄（SDK 樹內沒有 `core_cm4.h`），但本檔既有的 `NVIC_SystemReset()` 已在用同一組
  標頭並成功編譯過，故 `SCB` 一定可見。
- 非 ASCII 註解：本檔原本就含中文與 emoji（`1️⃣`…`8️⃣`）並成功 build 過，故新增的中文註解無風險。

---

## 6. 使用者驗證步驟

1. **Keil build**
   開啟 `...\pca10056\s140\arm5_no_packs\ble_app_multilink_central_pca10056_s140.uvprojx`，
   target 選 `nrf52840_xxaa`，Rebuild。
   - 若 Keil 提示 target 記憶體設定已變更，接受即可（IRAM1 應顯示 start `0x20010000`、
     size `0x28000`）。
   - build 後檢查 `_build\nrf52840_xxaa.map`：`Execution Region RW_IRAM1` 的 `Max:` 應為
     `0x00028000`，`Size:` 應仍在 0x9500 附近（新增變數只有 ~50 bytes）。
   - 順手確認 `_build\nrf52840_xxaa.sct` 內是 `RW_IRAM1 0x20010000 0x00028000`。

2. **燒錄**
   ```powershell
   cd d:\jerry\Python\PC_GIOSXTR_Demo\PTU_to_Azure\NRF52840-DONGLE\Rpi_USB_BLE
   .\flash_app_sectorerase.ps1
   ```
   （會先驗 FICR PART = nRF52840 與 S140 7.2.0 metadata，只做 `--sectorerase`，
   保留 SoftDevice 與 bootloader，最後 `--pinreset`。）

3. **先確認乾淨上電的輸出格式**
   開 COM port，應看到（`n=0`、且**沒有** DIAG2 行）：
   ```
   DIAG: RESETREAS=0x00000001 [PIN ] last_err=0x0000 fault_pc=0x00000000 fault_id=0x00000000 fault_info=0x00000000 n=0
   ```
   ⇒ 證明既有欄位格式沒被破壞、PC 端解析仍相容。

4. **重現故障**
   照原本的方式：連上裝置 → PC App 按「中斷目前裝置」（或直接對 COM port 下
   `AT+DISC` / `AT+DISC=<MAC>`）。
   - 若故障已不再發生（因為 §2.1/§2.2 的重置路徑被修掉了）：那原本的重置有一部分
     其實是那些 `APP_ERROR_CHECK`。此時請留意有沒有出現新的
     `ERROR:SCAN START 0x....` / `WARN:PHY_UPDATE ...` 等行——**把這些行回報**，
     它們就是原本被 `APP_ERROR_CHECK` 吃掉的真實錯誤碼。
   - 若 dongle 仍然重置 → 進步驟 5。

5. **看 DIAG 判讀（關鍵）**
   重新列舉後開 port，看第一批輸出：
   ```
   DIAG: RESETREAS=0x00000004 [SREQ ] last_err=0xFF03 fault_pc=0x000XXXXX fault_id=0x00001001 fault_info=0x00000000 n=1
   DIAG2: err=0x00000000 line=0 file=0x00000000 hfsr=... cfsr=... bfar=... mmfar=...
   ```
   判讀規則：
   - **`fault_id` 對照表**（已核對 `nrf_sdm.h:171-182` / `app_error.h:70-75` 的數值）：

     | fault_id | 意義 | 對應 last_err |
     |---|---|---|
     | `0x00000001` | `NRF_FAULT_ID_SD_ASSERT`（SoftDevice assert） | `0xFF01` |
     | `0x00001001` | `NRF_FAULT_ID_APP_MEMACC` ← **本次要抓的那個** | `0xFF03` |
     | `0x00004001` | `NRF_FAULT_ID_SDK_ERROR`（`APP_ERROR_CHECK` 失敗） | 該 SDK 錯誤碼 |
     | `0x00004002` | `NRF_FAULT_ID_SDK_ASSERT`（`ASSERT()` 失敗） | `0xFF02` |
     | `0xFFFF0004` | 本地 HardFault 標記 | `0xFF04` |

   - **`fault_info=0x00000000`** ⇒ 寫到了 **SoftDevice RAM**（`0x20000000..0x2000FFFF`）。
   - **`fault_info` 非 0** ⇒ 寫到了**被封鎖的週邊暫存器**，位址約為
     `0x40000000 + (fault_info × 0x1000)`。例如 `fault_info=0` 之外若看到 `16` ⇒ `0x40010000` (WDT)。
   - **`fault_pc`** 就是出事的指令位址。反查方式（任一）：
     - 開 `_build\nrf52840_xxaa.htm`（linker listing）找涵蓋該位址的函式；
     - 或在 `_build\nrf52840_xxaa.map` 的 symbol 表找 `fault_pc` 落在哪個 `i.<函式名>` 區間；
     - 或 `fromelf --text -c -o dis.txt _build\nrf52840_xxaa.axf` 後搜該位址。
   - **`n=`** 是自**上電**以來累積的 fault 次數（`count` 用獨立的 `count_magic` 標記，
     開機讀取時刻意不清除，所以能跨多次軟重置累積；只有真正斷電拔插才歸零）。
     `n=1` = 單次故障；`n` 持續往上跳 = 重置迴圈。
   - **`DIAG2` 的 `hfsr/cfsr/bfar/mmfar` 只在 `fault_id=0xFFFF0004`（HardFault）時才有意義**；
     其他 fault_id 抓到的可能是上一次的殘值，請忽略。`err=`/`line=`/`file=` 則只在
     `fault_id=0x00004001`（SDK_ERROR）或 `0x00004002`（SDK_ASSERT）時有意義。
   - **若 `last_err=0xFF03` 但 `fault_pc=0x00000000` 且沒有 DIAG2 行** ⇒ RAM 記錄區被
     bootloader 清掉了（見 P5），請回報，我把 `FAULT_RECORD_ADDR` 往低位址移再試。

6. **回報內容**
   請把步驟 3 與步驟 5 的完整 `DIAG:` / `DIAG2:` 兩行（連同前後幾行）貼回來，
   加上是否出現任何 `ERROR:SCAN START` / `WARN:*` 行。有 `fault_pc` 就能定案根因。

---

## 7. 已審查的其他提案（部分仍需硬體驗證）

| # | 提案 | 風險 | 為什麼沒動 |
|---|---|---|---|
| A1 | `wdt_event_handler` 不再寫 `NRF_POWER->GPREGRET`（改空函式，靠 RESETREAS 的 DOG 位元判斷） | 低 | **已套用**；避免 handler 自己觸發 APP_MEMACC，並消除 0xFF02 撞碼 |
| A2 | 掃描 `window` 改為 `interval` 的一半（160 → 80） | 中（改射頻時序） | 見 P2。需長時間現場統計才知是否更好 |
| A3 | 移除多餘的 `scan_resume_fast()`（module 已自行 re-arm） | 中 | 見 P3。移除既有防護，無硬體無法驗證 |
| A4 | HardFault 取得堆疊上的 PC（需 `__asm` naked stub 判斷 EXC_RETURN 選 MSP/PSP，或改用 SDK 的 `components\libraries\hardfault`） | 中高 | armcc AC5 專屬內嵌組語，無法本機編譯驗證。目前 HardFault 靠 `CFSR/BFAR/MMFAR` 定位，已足夠分辨故障型態 |
| A5 | `usb_printf`／`send_binary_packet` 改用各自獨立的格式化緩衝 | 低 | 見 P4，純推測，等 `fault_pc` 出來再決定 |
| A6 | `send_binary_packet` 的 `OUT_UART_BINARY` 分支也包 critical region | 低 | 同 A5，且該分支疑似未啟用（`debug_mode.h` 開關）——未確認 |

---

## 8. 附帶發現

1. **`NRF_LOG_ENABLED = 1` 但 `NRF_LOG_BACKEND_RTT_ENABLED = 0`**
   （sdk_config.h:7927 / 7849），且 `NRF_LOG_DEFERRED = 0`。
   ⇒ 所有 `NRF_LOG_INFO/WARNING/DEBUG` 都在花 CPU 做同步格式化，**但沒有任何後端輸出**。
   這正是為什麼原本那些 `NRF_LOG_WARNING("... failed: 0x%x")` 的錯誤完全看不見。
   本次新增的錯誤回報刻意改用 `usb_printf`（走 USB CDC），才看得到。
   建議：要嘛開 RTT backend，要嘛把 `NRF_LOG_ENABLED` 關掉省 CPU 與 flash。

2. **`db_disc_handler` / `m_db_disc` 疑似死碼**：`ble_db_discovery_start()` 在 main.c 內
   從未被呼叫（服務發現走 `ble_lbs_c_pc_discovery_start`）。若確認為死碼，
   `BLE_DB_DISCOVERY_ARRAY_DEF(m_db_disc, 8)` 可省下一塊 RAM。未確認。

3. **RAM 餘裕很大**。最新 build 的 `RW-data + ZI-data = 38,128 bytes`；主 target
   IRAM1 上限為 `0x28000`。第二個 target `flash_s140_nrf52_7.2.0_softdevice` 也已縮成
   `0x200043A8 / 0x33C58`，兩者終點均為 `0x20038000`，不覆蓋 fault record。

4. **`nrf_ble_scan_stop()` 完全沒有狀態追蹤**（`nrf_ble_scan.c:1045-1050` 只有一行
   `sd_ble_gap_scan_stop()`，回傳值丟棄），module 內部沒有「是否正在掃描」的旗標。
   所以 `m_scanning` 是唯一的真相來源，而 P3 指出它可能與硬體反相——這解釋了先前
   session 追過的「silent-scanner latch」現象的根源在 SDK 這一側。
