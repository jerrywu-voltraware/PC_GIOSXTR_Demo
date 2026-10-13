# Independent review — 2026-10-13 debug UX upgrade

## 範圍與狀態

Fresh reviewer 已讀全域 `03-judgment.md`。本輪先查 typography/theme/settings、LogPage、CsvLogger；MainWindow / RecordingPanel 仍由主 agent 整合，尚未作整體完成判定。

## 第一輪證據

- 命令：`$env:QT_QPA_PLATFORM='offscreen'; py -3 -X utf8 -m pytest tests/test_typography.py tests/test_log_page.py tests/test_csv_and_ble_helpers.py tests/test_readable_pages.py -q -p no:cacheprovider --basetemp='.pytest_tmp_review_20261013'`
- 結果：`38 passed in 3.84s`，exit code 0。
- 已閱讀 LogPage 搜尋／嚴重度／暫停／clear anchor／500 筆緩衝邏輯。
- 新 typography fixture 以獨立 organization + test application 名稱儲存並清除設定；既有 test_ui_imports.py 的部分 QSettings 測試尚待整體測試隔離確認。
- 正在補獨立 failure-injection / DPI / no-overwrite 驗證，尚未有最終結論。

## 獨立邊界驗證

- 新 reviewer 測試：`docs/plans/review_debug_ux_checks.py`。命令 `py -3 -X utf8 -m pytest docs/plans/review_debug_ux_checks.py -q -p no:cacheprovider --basetemp='.pytest_tmp_review_csv_20261013'`，結果 `5 passed in 0.31s`，exit 0。
- 同秒 16 個 thread 以相同裝置 suffix 開始錄製：16 條獨立路徑，逐檔 read-back 每筆值相符，無覆寫。
- 分檔路徑預先存在：拋出 FileExistsError，既存檔案 bytes 完整保留；logger 不再標記 recording。
- 已知 3 筆輸入跨檔 read-back：11111 → 11111、22222 → 22222、33333 → 33333；成功寫入 3 筆、2 個分檔。
- 資料列 flush / header flush 注入 OSError：失敗列不增加成功計數；stop 清除 writer/file 參照並關閉 handle；header 建立失敗不宣稱 recording。
- Qt DPI 模擬在獨立 subprocess 下使用 `QT_SCALE_FACTOR=1 / 1.5 / 2`，三者 exit 0，觀察 devicePixelRatio 分別 1 / 1.5 / 2；各自切換 100→125→150→175→200→100%，QApplication 與 SettingsDialog 預覽字級皆為 11→13.75→16.5→19.25→22→11pt，table row height 為 25→30→37→44→49→25 logical pixels，無重複 DPI 倍乘。
- DPI 檢查使用 TemporaryDirectory 下的 IniFormat QSettings；read-back 確認設定路徑在 temp 下，未用使用者正式 registry 設定。

## 目前結論／待辦

上述已完成元件在本輪未發現需要阻擋交付的問題。主窗與錄製摘要仍在整合，尚未審查實際 MainWindow 寫檔例外處理、全套測試與各分頁最終布局；不是整體驗收通過。

未驗證：真實 BLE/dongle、跨實體螢幕 DPI 切換、數小時硬體錄製。Qt offscreen 的 DPI 模擬不能代表多螢幕實機切換。

## 最終整合 review（新增獨立案例）

- 已 read-through MainWindow/RecordingPanel 及 responsive pages 的差異；reviewer 未修改實作。
- reviewer 腳本擴充至 9 個獨立案例，再與 `tests/test_recording_ux.py` 合跑：`16 passed in 11.90s`，exit 0。命令 `py -3 -X utf8 -m pytest docs/plans/review_debug_ux_checks.py tests/test_recording_ux.py -q -p no:cacheprovider --basetemp='.pytest_tmp_review_integrated_20261013'`。
- 獨立雙裝置實跑：全體錄製、切換裝置、暫停 Log、A 斷線等待重連、B 繼續寫入、A 恢復連線、停止全體；兩份 CSV 各 2 筆且電壓 read-back 正確，路徑不中斷重建。
- A 寫檔失敗時 B 繼續寫入；B 選取中的畫面顯示 A 位址與失敗原因，仍可停止 B，資料夾變更保持停用；A 重新開始清除該錯誤，B 路徑保持不變。
- 選取未錄製的 A，但 B 正在錄製時，直接呼叫 folder chooser 也無法變更；停錄後可更改，所有 logger.directory 與目前顯示同步。
- 人工中斷 A 時 flush 失敗：handle 仍關閉、A 移除後自動選 B，原錯誤持續顯示，不會無聲消失。
- 獨立 UI fixture 同時把 UserScope/SystemScope QSettings 改為測試 temporary 目錄下的 IniFormat，recent_devices 也導向測試目錄；本次不讀寫正式設定與近期裝置清單。

整合邏輯目前未發現 blocking bug。仍待主 agent 全套回歸與 screenshot agent 的最終布局證據 read-back；因此此時尚未作整體完成宣告。

## 最終畫面 review 發現與修復追驗

- 已 read-back `build/ux-review/report.json`：20 種倍率／主題／尺寸组合（100/125/150/175/200%，light/dark，1366×768/1024×768），180 張 PNG 全存在、幾何 issues 為空。
- 已人工檢視代表 Overview、Log、PTU、200%側欄直排與 Waveform 截圖。README 的設定路徑、全體停錄後更改目錄、500 筆顯示上限、手動重新錄製恢復及實機驗收步驟與實作相符。
- **發現並回報實際字型 bug**：既有 Waveform legend 切 100→200% 時 opts 變 22pt，但 QTextDocument 實際 fragment.fontPointSize 仍 11pt。獨立 subprocess 實跑輸出：`scale 100 ... rendered points 11.0`、`scale 200 ... rendered points 11.0`。原因為當地 pyqtgraph 的 `LegendItem.setLabelTextSize()` 僅呼叫 `LabelItem.setAttr()`，不重新產生顯示 HTML。
- responsive agent 收到回報後修正；reviewer 新增 `test_existing_waveform_legend_updates_rendered_point_size` 直接檢查既有圖例文字 fragment，而非僅查 opts。追驗 `1 passed, 9 deselected in 2.04s`，exit 0。
- 另 screenshot agent 已回報 light 模式波形標題對比不足並交修正；需要最後新截圖 read-back，不能以原先的幾何 pass 代替視覺確認。

- 定版後 reviewer 全部獨立案例 10 項 + readable pages 7 項合併：`17 passed in 46.41s`，exit 0。命令 `py -3 -X utf8 -m pytest docs/plans/review_debug_ux_checks.py tests/test_readable_pages.py -q -p no:cacheprovider --basetemp='build/pytest-review-final'`。
- 此輪包含實際 legend 字型、plot title foreground、圖軸與標記縮放追驗；先前 legend 缺陷已修復。

- **第二項波形退化（最後圖像 read-back）**：100% 圖有 `Sample` 與 `V_in (mV)` 軸標題，200% 圖兩者消失。查當地 `AxisItem.setLabel()`，省略 text 時會清空 labelText 並 hide；新 `_style_plot()` 只傳 font-size 造成。
- reviewer 擴充獨立既有圖測試後實跑重現：`AssertionError: assert ['', ''] == ['Sample', 'V_in (mV)']`，`1 failed, 9 deselected in 2.21s`（exit 1）。已交 responsive agent 修正保留軸文字／units，暫緩最終驗收，待重新跑同一案例及截圖。

## 源碼與 UI 最終獨立驗收結論

**通過。** 先前發現的兩項 Waveform 字級退化（既有圖例未重繪、切換倍率清空軸標題）皆已修復，無剩餘阻擋源碼/UI交付的問題。

- 修後 reviewer 與既有 waveform 針對回歸：`15 passed, 85 deselected in 16.38s`，exit 0。命令 `py -3 -X utf8 -m pytest docs/plans/review_debug_ux_checks.py tests/test_readable_pages.py tests/test_ui_imports.py -k 'existing_waveform_legend or waveform_style_cycle or waveform_page or waveform_axes' -q -p no:cacheprovider --basetemp='build/pytest-review-waveform-fixed'`。
- 最終 read-back：`build/ux-review/waveform-final/report.json`，5 倍率 × 亮暗共 10 個案例均 pass、0 issues；每例軸文字皆 `Sample` / `V_in (mV)`。
- 人工重新檢視 `waveform-final/light-200-1024x768-waveform-plot.png` 與 `dark-100-1024x768-waveform-plot.png`：軸標題、刻度、圖例、圖名均完整可讀；200% 放大確實作用於實際文字。
- 主代理回報最後完整回歸 `264 passed in 186.67s`、exit 0（隔離 IniFormat）；最後波形修正由上述針對回歸及最終畫面覆核。
- 前述首輪測試暫存已由主代理移至 `build/ux-test-evidence/`，後续 reviewer 測試一律使用 build 子目錄。

| 驗收項目 | 結果與證據 |
| --- | --- |
| 11pt 預設、100–200% 即時且記憶 | typography 測試、DPR 1/1.5/2 獨立實跑、真字型矩陣 |
| 小螢幕重要操作可用 | 20 組尺寸/主題/倍率矩陣、重要按鈕可視幾何檢查、代表畫面人工檢視 |
| 錄製狀態／失敗不誤報 | 獨立雙裝置、斷線、故障注入與恢復案例 |
| Log 操作不阻斷寫檔且有界 | 38項元件回歸；10,000通知報告read-back、兩裝置各500筆上限 |
| CSV 欄位／分檔／不覆寫 | 3筆值read-back、16路同秒並行與分檔碰撞、10,006資料列/26欄/12分檔報告 |
| 設定隔離 | reviewer以測試IniFormat與recent_devices temp目錄執行；UI腳本同樣隔離 |
| 使用說明 | README新段落與操作／限制一致、附2小時與DPI實機步驟 |

打包 EXE 的 runtime/import probe 與檔案 hash 尚由主代理完成；`--startup-probe` 不建立 QApplication，所以不能視為打包版GUI與真實硬體驗證。真實 BLE/dongle、跨實體螢幕與數小時耐久錄製依 README 步驟待實機驗證。

## 打包交付 read-back 尾註

- 已獨立讀取 `build/ux-preview-package-verification.json`，確認 `--startup-probe` exit 0、7.088 秒、stdout/stderr 皆空；scope 明確為 packaged runtime/imports。
- 已以 `Get-Item` 確認 EXE 存在，大小 **143876614 bytes**；以 `Get-FileHash -Algorithm SHA256` 獨立計算結果與記錄一致：`84e3d1b907a07b9f23a4dbd81d5d3101b3e3f4a6be5a0d0829622a64e1a327c0`。
- 檔案：`dist/ux-preview/PC_GIOSXTR_Demo_V2.0.2.exe`。本輪 fresh review 已完成，源碼/UI及本機試用包交付證據齊全；未宣稱打包版 GUI、真實硬體、多實體螢幕切換或數小時耐久已驗證。
