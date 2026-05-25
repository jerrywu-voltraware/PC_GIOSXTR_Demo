# PC GIOSXTR 自動更新設計

## 目標

替目前的 PyInstaller Windows 桌面版 APP 加入輕量自動更新機制，讓已部署給使用者的版本可以在開發者發布新版後，偵測並下載新的執行檔。

APP 會使用公開的 GitHub Releases：

```text
jerrywu-voltraware/PC_GIOSXTR_Demo
```

實作期間這個 repository 不一定要已經存在。若 repository 尚未建立，或尚未有 release，自動檢查必須安靜失敗；只有使用者手動按「檢查更新」時，才顯示可讀的說明。

## 採用方案

採用半自動更新流程：

1. APP 檢查 GitHub Releases 最新公開版本。
2. 如果 release 版本比目前執行中的 APP 版本新，APP 詢問使用者是否下載。
3. APP 將 release 裡的 exe 下載到使用者可寫入的位置。
4. 下載完成後，APP 提醒使用者關閉目前版本，並開啟下載好的新版 exe。

這個方案不需要額外維護 `updater.exe`，也不需要導入 installer。對目前單一 PyInstaller exe 的發佈方式來說，這是最穩定、風險最低的做法。

## Release 規則

更新程式讀取：

```text
https://api.github.com/repos/jerrywu-voltraware/PC_GIOSXTR_Demo/releases/latest
```

Release tag 必須使用小寫 `v` 開頭的語意化版本：

```text
v1.0.1
v1.1.0
v2.0.0
```

APP 執行中的版本仍由 `app/constants.py` 定義：

```python
APP_VERSION = "V1.0.0"
```

版本比較時會忽略開頭的 `v` 或 `V`。

Release asset 必須包含同版本的 Windows exe：

```text
PC_GIOSXTR_Demo_V1.0.1.exe
```

如果找不到完全符合命名的檔案，更新程式可以退而選擇第一個 `.exe` asset；但正式發佈規則仍以同版本檔名為準。

## 開發者發佈流程

每次發佈新版時，流程是：

```text
更新 APP_VERSION 與 exe 名稱
-> 執行測試
-> 使用 PyInstaller 打包
-> 在本機開啟產生的 exe 並確認可正常使用
-> 建立或更新公開 GitHub repository
-> 建立 GitHub Release vX.Y.Z
-> 上傳已驗證的 PC_GIOSXTR_Demo_VX.Y.Z.exe
-> 使用者透過 APP 更新檢查取得新版
```

開發者必須先在本機開啟並驗證打包後的 exe，確認沒問題後，才能發布 GitHub Release。

## APP 啟動行為

正常啟動時，主視窗顯示後才排程一次背景更新檢查。

自動檢查不能阻塞 BLE 掃描、UI 顯示或 APP 關閉。

自動檢查遇到下列狀況時保持安靜：

- 無網路
- GitHub API 無法連線
- repository 不存在
- 尚未建立 release
- release 資料格式錯誤
- release 裡沒有可下載的 exe asset

如果發現新版，APP 顯示對話框，內容包含：

- 目前版本
- 最新版本
- 是否立即下載
- 略過選項

## 手動檢查行為

設定視窗的「關於」頁加入「檢查更新」按鈕。

手動檢查必須在所有情況都顯示結果：

- 目前已是最新版本
- 有新版可下載
- repository 或 release 尚未建立
- 網路連線失敗
- release 裡沒有 exe asset
- GitHub 回傳資料格式異常

手動檢查與自動檢查使用同一個更新服務。

## 下載行為

下載預設放在使用者可寫入的位置，例如 Windows 下載資料夾，或必要時使用系統暫存目錄：

```text
%TEMP%\PC_GIOSXTR_Demo\updates\
```

下載檔名保留 GitHub asset 名稱。若檔案已存在，更新程式可以覆蓋或由使用者重新指定儲存位置。

下載完成後，APP 顯示下載路徑，並詢問是否開啟新版 exe。

APP 不嘗試直接替換目前正在執行的 exe。這樣可以避免 Windows 檔案鎖定問題，讓第一版更新機制更可靠。

## UI 整合

主視窗右上角現有設定按鈕仍是設定入口。

設定視窗變更：

- 「關於」頁顯示 APP 名稱與目前版本。
- 「關於」頁加入「檢查更新」按鈕。
- 檢查中按鈕停用，文字顯示檢查中。
- 結果使用 `QMessageBox` 顯示。

主視窗變更：

- 啟動後排程一次自動檢查。
- 若有新版，從主視窗顯示更新提示。
- 若使用者選擇下載，非同步下載並顯示完成或失敗訊息。

## 模組設計

建立 `app/updater.py`，不依賴 Qt widget。

責任：

- 正規化與比較版本
- 從 GitHub 取得 latest release JSON
- 找出可下載的 exe asset
- 回傳結構化的更新檢查結果
- 下載使用者選擇的 asset

UI 層負責 `QMessageBox` 提示與按鈕狀態。

建議資料型別：

```python
UpdateAsset(name, download_url, size)
UpdateInfo(current_version, latest_version, release_url, asset)
UpdateCheckResult(status, info, message)
```

狀態：

```text
up_to_date
update_available
repo_unavailable
no_release
no_asset
network_error
invalid_response
```

## 錯誤處理

網路操作使用短 timeout，避免啟動檢查卡住 APP。

GitHub `404` 視為 repository 或 release 尚未建立。這符合目前 repository 可能還不存在的狀態。

自動更新失敗時不顯示對話框。若 APP 之後有適合的 log 介面，可以只寫入 log。

手動更新失敗時顯示簡短、可理解的中文訊息。

## 測試

單元測試涵蓋：

- 版本正規化與比較
- 沒有新版
- 有新版
- release 沒有 exe asset
- repository 不存在
- 回應資料格式錯誤
- 符合命名規則的 asset 選擇
- fallback `.exe` asset 選擇

手動驗證涵蓋：

- 執行 `python main.py`
- repository 尚未有 release 時，開啟「設定 -> 關於 -> 檢查更新」
- 使用 PyInstaller 打包
- 在發布前，本機開啟打包後的 exe 並確認可正常使用

## 完成條件

功能完成時必須符合：

- APP 可以檢查 `jerrywu-voltraware/PC_GIOSXTR_Demo` GitHub Releases
- repository 尚未有 release 時，啟動檢查不會阻塞或破壞 APP
- 手動檢查會顯示可理解的狀態
- 有新版且 release 包含 `.exe` asset 時，APP 會提示使用者下載
- 使用者可以開啟下載後的 exe
- 測試通過
- README 記錄發佈與本機驗證流程
