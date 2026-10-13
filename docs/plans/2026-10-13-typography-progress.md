# 字體與縮放改善進度

## 驗收條件

- 預設應用程式字體使用 11 pt，讓 Qt 依螢幕 DPI 處理像素大小。
- 外觀設定可即時切換 100%、125%、150%、175%、200%，並儲存到 QSettings。
- 既有主題樣式可在縮放時同步更新；表格列高跟隨字體度量。
- 大字級下設定頁可捲動，不會將控制項擠出視窗。
- 執行 offscreen Qt 測試，驗證即時切換、持久化、表格列高與設定頁。

## 2026-10-13

- 已閱讀全域判斷守則。專案根目錄沒有 AGENTS.md 或 CLAUDE.md。
- 已檢查 theme.py、settings_dialog.py、現有主題測試與全專案字體設定。
- 問題來源：未指定應用程式基準字級，且多個頁面將資訊文字鎖定在 10–13 px。
- 已向主代理協調 helper API：font_size(points)、scaled_px(px)、typography_manager().set_scale(percent)。
- 已新增 `app/typography.py`：11 pt 基準、五種倍率、QSettings 儲存與容錯、樣式/尺寸 helper、全域表格列高更新。
- 已整合 `theme.py`：首次啟動載入字級，重套主題保留現有字級；字級更新會通知頁面重新套用樣式。
- 已更新 `settings_dialog.py`：介面字級選單、即時文字預覽、外部倍率同步；所有設定分頁可捲動，表單可折行。
- 實跑 `py -3 -X utf8 -c "import PyQt6; import app.typography; import app.theme; import app.windows.settings_dialog; print('imports: OK')"`：exit 0。
- 實跑 `py -3 -X utf8 -m pytest tests/test_typography.py tests/test_theme.py -q`：15 passed，exit 0。
- 實跑 `py -3 -X utf8 -m pytest tests/test_ui_imports.py -k settings_dialog -q`：10 passed、72 deselected，exit 0。
- 額外用 `QT_SCALE_FACTOR=1.5` 的獨立程序執行 typography/theme 測試：15 passed，exit 0；確認 Qt 顯示縮放與應用程式字級倍率可同時作用。
- 驗證已涵蓋 QSS 小數 pt、200% 現有/新表格、縮回預設、倍率儲存/重載、無效值容錯、外觀控制項即時同步與主題重套。
- 尚待主代理整合後 fresh agent 驗收；真實多螢幕/不同電腦 DPI 顯示仍須硬體確認。
