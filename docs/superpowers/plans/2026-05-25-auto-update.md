# PC GIOSXTR Auto Update Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a GitHub Releases based update check and download flow to the PyInstaller desktop app.

**Architecture:** `app/updater.py` contains all network, version, release parsing, and download logic without Qt dependencies. `MainWindow` owns asynchronous update checks and dialogs, while `SettingsDialog` only exposes a manual check button signal and button busy state.

**Tech Stack:** Python standard library `urllib`, `json`, `tempfile`, `dataclasses`, `Enum`; PyQt6; qasync; pytest; PyInstaller.

---

## File Structure

- Create `app/updater.py`: pure update service for GitHub Releases, version comparison, asset selection, and downloads.
- Create `tests/test_updater.py`: unit tests for updater behavior without live network calls.
- Modify `app/windows/settings_dialog.py`: add a manual update check button on the About tab and expose `check_updates_requested`.
- Modify `app/windows/main_window.py`: schedule one startup update check, handle manual checks, prompt for download, download in a background thread, and open the downloaded executable.
- Modify `README.md`: document the release naming contract, local exe verification step, GitHub Release publishing flow, and user update behavior.

## Task 1: Updater Tests

**Files:**
- Create: `tests/test_updater.py`

- [ ] **Step 1: Write tests for version comparison and asset selection**

Create `tests/test_updater.py` with these first tests:

```python
from app.updater import (
    UpdateStatus,
    expected_asset_name,
    is_newer_version,
    normalize_version,
    parse_release_response,
    select_executable_asset,
)


def test_normalize_version_strips_prefix_and_spaces():
    assert normalize_version(" V1.2.3 ") == "1.2.3"
    assert normalize_version("v2.0.0") == "2.0.0"


def test_is_newer_version_compares_numeric_parts():
    assert is_newer_version("v1.0.1", "V1.0.0")
    assert is_newer_version("v1.1.0", "V1.0.9")
    assert not is_newer_version("v1.0.0", "V1.0.0")
    assert not is_newer_version("v1.0.0", "V1.0.1")


def test_expected_asset_name_uses_uppercase_app_version_prefix():
    assert expected_asset_name("v1.2.3") == "PC_GIOSXTR_Demo_V1.2.3.exe"


def test_select_executable_asset_prefers_exact_versioned_exe():
    assets = [
        {
            "name": "PC_GIOSXTR_Demo_V1.2.3_portable.exe",
            "browser_download_url": "https://example.test/fallback.exe",
            "size": 100,
        },
        {
            "name": "PC_GIOSXTR_Demo_V1.2.3.exe",
            "browser_download_url": "https://example.test/exact.exe",
            "size": 200,
        },
    ]

    asset = select_executable_asset(assets, "v1.2.3")

    assert asset is not None
    assert asset.name == "PC_GIOSXTR_Demo_V1.2.3.exe"
    assert asset.download_url == "https://example.test/exact.exe"
    assert asset.size == 200


def test_select_executable_asset_falls_back_to_first_exe():
    assets = [
        {
            "name": "notes.txt",
            "browser_download_url": "https://example.test/notes.txt",
            "size": 10,
        },
        {
            "name": "custom-release.exe",
            "browser_download_url": "https://example.test/custom.exe",
            "size": 20,
        },
    ]

    asset = select_executable_asset(assets, "v1.2.3")

    assert asset is not None
    assert asset.name == "custom-release.exe"
    assert asset.download_url == "https://example.test/custom.exe"
```

- [ ] **Step 2: Run updater tests and confirm the module is missing**

Run:

```powershell
python -m pytest tests/test_updater.py -q
```

Expected:

```text
ModuleNotFoundError: No module named 'app.updater'
```

- [ ] **Step 3: Add release parsing tests**

Append these tests to `tests/test_updater.py`:

```python
def _release_payload(tag_name: str, assets: list[dict[str, object]]) -> dict[str, object]:
    return {
        "tag_name": tag_name,
        "html_url": f"https://github.com/jerrywu-voltraware/PC_GIOSXTR_Demo/releases/tag/{tag_name}",
        "assets": assets,
    }


def test_parse_release_response_returns_update_available():
    payload = _release_payload(
        "v1.0.1",
        [
            {
                "name": "PC_GIOSXTR_Demo_V1.0.1.exe",
                "browser_download_url": "https://example.test/PC_GIOSXTR_Demo_V1.0.1.exe",
                "size": 1234,
            }
        ],
    )

    result = parse_release_response(payload, "V1.0.0")

    assert result.status is UpdateStatus.UPDATE_AVAILABLE
    assert result.info is not None
    assert result.info.current_version == "V1.0.0"
    assert result.info.latest_version == "v1.0.1"
    assert result.info.asset.name == "PC_GIOSXTR_Demo_V1.0.1.exe"


def test_parse_release_response_returns_up_to_date():
    payload = _release_payload(
        "v1.0.0",
        [
            {
                "name": "PC_GIOSXTR_Demo_V1.0.0.exe",
                "browser_download_url": "https://example.test/PC_GIOSXTR_Demo_V1.0.0.exe",
                "size": 1234,
            }
        ],
    )

    result = parse_release_response(payload, "V1.0.0")

    assert result.status is UpdateStatus.UP_TO_DATE
    assert result.info is None


def test_parse_release_response_returns_no_asset_for_new_release_without_exe():
    payload = _release_payload(
        "v1.0.1",
        [
            {
                "name": "release-notes.txt",
                "browser_download_url": "https://example.test/release-notes.txt",
                "size": 1234,
            }
        ],
    )

    result = parse_release_response(payload, "V1.0.0")

    assert result.status is UpdateStatus.NO_ASSET
    assert result.info is None


def test_parse_release_response_rejects_missing_tag():
    result = parse_release_response({"assets": []}, "V1.0.0")

    assert result.status is UpdateStatus.INVALID_RESPONSE
    assert result.info is None
```

- [ ] **Step 4: Run updater tests and confirm failures still point to missing implementation**

Run:

```powershell
python -m pytest tests/test_updater.py -q
```

Expected:

```text
ModuleNotFoundError: No module named 'app.updater'
```

- [ ] **Step 5: Commit the failing tests**

Run:

```powershell
git add tests/test_updater.py
git commit -m "test: add updater release parsing coverage"
```

Expected:

```text
[master <hash>] test: add updater release parsing coverage
```

## Task 2: Pure Updater Module

**Files:**
- Create: `app/updater.py`
- Test: `tests/test_updater.py`

- [ ] **Step 1: Create updater data types and version helpers**

Create `app/updater.py` with:

```python
"""GitHub Releases update checks for the PC GIOSXTR app."""

from __future__ import annotations

import json
import shutil
import tempfile
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


GITHUB_OWNER = "jerrywu-voltraware"
GITHUB_REPO = "PC_GIOSXTR_Demo"
GITHUB_API_URL = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"
APP_EXECUTABLE_PREFIX = "PC_GIOSXTR_Demo"
DEFAULT_TIMEOUT_SECONDS = 8.0
DOWNLOAD_TIMEOUT_SECONDS = 60.0


class UpdateStatus(str, Enum):
    UP_TO_DATE = "up_to_date"
    UPDATE_AVAILABLE = "update_available"
    REPO_UNAVAILABLE = "repo_unavailable"
    NO_RELEASE = "no_release"
    NO_ASSET = "no_asset"
    NETWORK_ERROR = "network_error"
    INVALID_RESPONSE = "invalid_response"


@dataclass(frozen=True)
class UpdateAsset:
    name: str
    download_url: str
    size: int | None = None


@dataclass(frozen=True)
class UpdateInfo:
    current_version: str
    latest_version: str
    release_url: str
    asset: UpdateAsset


@dataclass(frozen=True)
class UpdateCheckResult:
    status: UpdateStatus
    info: UpdateInfo | None = None
    message: str = ""


def normalize_version(value: str) -> str:
    stripped = value.strip()
    if stripped[:1].lower() == "v":
        stripped = stripped[1:]
    return stripped


def _version_parts(value: str) -> tuple[int, ...]:
    normalized = normalize_version(value)
    if not normalized:
        return (0,)
    parts: list[int] = []
    for part in normalized.split("."):
        if not part.isdigit():
            digits = "".join(ch for ch in part if ch.isdigit())
            parts.append(int(digits or "0"))
        else:
            parts.append(int(part))
    return tuple(parts)


def is_newer_version(latest_version: str, current_version: str) -> bool:
    latest = _version_parts(latest_version)
    current = _version_parts(current_version)
    max_len = max(len(latest), len(current))
    latest = latest + (0,) * (max_len - len(latest))
    current = current + (0,) * (max_len - len(current))
    return latest > current


def expected_asset_name(version: str) -> str:
    return f"{APP_EXECUTABLE_PREFIX}_V{normalize_version(version)}.exe"
```

- [ ] **Step 2: Run the version helper tests**

Run:

```powershell
python -m pytest tests/test_updater.py::test_normalize_version_strips_prefix_and_spaces tests/test_updater.py::test_is_newer_version_compares_numeric_parts tests/test_updater.py::test_expected_asset_name_uses_uppercase_app_version_prefix -q
```

Expected:

```text
3 passed
```

- [ ] **Step 3: Add asset selection and release parsing**

Append this code to `app/updater.py`:

```python
def _coerce_asset(raw_asset: dict[str, Any]) -> UpdateAsset | None:
    name = raw_asset.get("name")
    download_url = raw_asset.get("browser_download_url")
    if not isinstance(name, str) or not isinstance(download_url, str):
        return None
    raw_size = raw_asset.get("size")
    size = raw_size if isinstance(raw_size, int) else None
    return UpdateAsset(name=name, download_url=download_url, size=size)


def select_executable_asset(raw_assets: list[dict[str, Any]], latest_version: str) -> UpdateAsset | None:
    assets: list[UpdateAsset] = []
    for raw_asset in raw_assets:
        asset = _coerce_asset(raw_asset)
        if asset is not None and asset.name.lower().endswith(".exe"):
            assets.append(asset)
    if not assets:
        return None

    expected_name = expected_asset_name(latest_version).lower()
    for asset in assets:
        if asset.name.lower() == expected_name:
            return asset
    return assets[0]


def parse_release_response(payload: dict[str, Any], current_version: str) -> UpdateCheckResult:
    tag_name = payload.get("tag_name")
    release_url = payload.get("html_url")
    raw_assets = payload.get("assets")

    if not isinstance(tag_name, str) or not tag_name.strip():
        return UpdateCheckResult(
            UpdateStatus.INVALID_RESPONSE,
            message="GitHub release response does not include a valid version tag.",
        )
    if not isinstance(release_url, str):
        return UpdateCheckResult(
            UpdateStatus.INVALID_RESPONSE,
            message="GitHub release response does not include a release URL.",
        )
    if not isinstance(raw_assets, list):
        return UpdateCheckResult(
            UpdateStatus.INVALID_RESPONSE,
            message="GitHub release response does not include an assets list.",
        )

    if not is_newer_version(tag_name, current_version):
        return UpdateCheckResult(
            UpdateStatus.UP_TO_DATE,
            message=f"{current_version} is already the latest version.",
        )

    executable_assets = [asset for asset in raw_assets if isinstance(asset, dict)]
    asset = select_executable_asset(executable_assets, tag_name)
    if asset is None:
        return UpdateCheckResult(
            UpdateStatus.NO_ASSET,
            message=f"Release {tag_name} does not include a Windows .exe asset.",
        )

    return UpdateCheckResult(
        UpdateStatus.UPDATE_AVAILABLE,
        info=UpdateInfo(
            current_version=current_version,
            latest_version=tag_name,
            release_url=release_url,
            asset=asset,
        ),
        message=f"Version {tag_name} is available.",
    )
```

- [ ] **Step 4: Run updater unit tests**

Run:

```powershell
python -m pytest tests/test_updater.py -q
```

Expected:

```text
9 passed
```

- [ ] **Step 5: Add network check and download helpers**

Append this code to `app/updater.py`:

```python
def _fetch_latest_release(url: str = GITHUB_API_URL, timeout: float = DEFAULT_TIMEOUT_SECONDS) -> dict[str, Any]:
    request = Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": f"{APP_EXECUTABLE_PREFIX}-updater",
        },
    )
    with urlopen(request, timeout=timeout) as response:
        data = response.read()
    parsed = json.loads(data.decode("utf-8"))
    if not isinstance(parsed, dict):
        raise ValueError("GitHub release response is not a JSON object.")
    return parsed


def check_for_update(current_version: str, url: str = GITHUB_API_URL) -> UpdateCheckResult:
    try:
        payload = _fetch_latest_release(url)
    except HTTPError as exc:
        if exc.code == 404:
            return UpdateCheckResult(
                UpdateStatus.REPO_UNAVAILABLE,
                message="GitHub repository or release was not found.",
            )
        if exc.code == 403:
            return UpdateCheckResult(
                UpdateStatus.NETWORK_ERROR,
                message="GitHub API rate limit or access restriction blocked the update check.",
            )
        return UpdateCheckResult(
            UpdateStatus.NETWORK_ERROR,
            message=f"GitHub returned HTTP {exc.code} during update check.",
        )
    except URLError as exc:
        return UpdateCheckResult(
            UpdateStatus.NETWORK_ERROR,
            message=f"Network error during update check: {exc.reason}",
        )
    except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
        return UpdateCheckResult(
            UpdateStatus.INVALID_RESPONSE,
            message="GitHub returned an unreadable release response.",
        )

    return parse_release_response(payload, current_version)


def default_update_download_dir() -> Path:
    return Path(tempfile.gettempdir()) / APP_EXECUTABLE_PREFIX / "updates"


def download_asset(
    asset: UpdateAsset,
    target_dir: Path | None = None,
    timeout: float = DOWNLOAD_TIMEOUT_SECONDS,
) -> Path:
    destination_dir = target_dir or default_update_download_dir()
    destination_dir.mkdir(parents=True, exist_ok=True)
    destination = destination_dir / asset.name

    request = Request(
        asset.download_url,
        headers={"User-Agent": f"{APP_EXECUTABLE_PREFIX}-updater"},
    )
    with urlopen(request, timeout=timeout) as response:
        with destination.open("wb") as output:
            shutil.copyfileobj(response, output)
    return destination
```

- [ ] **Step 6: Add tests for network status mapping**

Append these tests to `tests/test_updater.py`:

```python
import json
from urllib.error import HTTPError, URLError

import app.updater as updater


def test_check_for_update_maps_404_to_repo_unavailable(monkeypatch):
    def raise_404(_url: str):
        raise HTTPError(_url, 404, "not found", hdrs=None, fp=None)

    monkeypatch.setattr(updater, "_fetch_latest_release", raise_404)

    result = updater.check_for_update("V1.0.0")

    assert result.status is UpdateStatus.REPO_UNAVAILABLE


def test_check_for_update_maps_url_error_to_network_error(monkeypatch):
    def raise_url_error(_url: str):
        raise URLError("offline")

    monkeypatch.setattr(updater, "_fetch_latest_release", raise_url_error)

    result = updater.check_for_update("V1.0.0")

    assert result.status is UpdateStatus.NETWORK_ERROR


def test_check_for_update_maps_bad_json_to_invalid_response(monkeypatch):
    def raise_bad_json(_url: str):
        raise json.JSONDecodeError("bad", "x", 0)

    monkeypatch.setattr(updater, "_fetch_latest_release", raise_bad_json)

    result = updater.check_for_update("V1.0.0")

    assert result.status is UpdateStatus.INVALID_RESPONSE
```

- [ ] **Step 7: Run updater tests**

Run:

```powershell
python -m pytest tests/test_updater.py -q
```

Expected:

```text
12 passed
```

- [ ] **Step 8: Commit updater module**

Run:

```powershell
git add app/updater.py tests/test_updater.py
git commit -m "feat: add GitHub release updater service"
```

Expected:

```text
[master <hash>] feat: add GitHub release updater service
```

## Task 3: Settings Dialog Manual Update Trigger

**Files:**
- Modify: `app/windows/settings_dialog.py`
- Test: `tests/test_app_metadata.py`

- [ ] **Step 1: Add a UI test for the manual update signal**

Append this test to `tests/test_app_metadata.py`:

```python
def test_settings_dialog_exposes_manual_update_check_button():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication, QPushButton

    from app.windows.settings_dialog import SettingsDialog

    app = QApplication.instance() or QApplication([])
    dialog = SettingsDialog(
        engineering_mode=False,
        demo_use_fake_data=True,
        demo_device_name="MMEU",
        demo_ebike_pct=76,
        demo_escooter_pct=81,
    )
    emitted: list[bool] = []
    dialog.check_updates_requested.connect(lambda: emitted.append(True))

    buttons = dialog.findChildren(QPushButton)
    update_buttons = [button for button in buttons if "update" in button.text().lower()]

    assert update_buttons
    update_buttons[0].click()
    assert emitted == [True]
    dialog.close()
```

- [ ] **Step 2: Run the new UI test and confirm missing signal failure**

Run:

```powershell
python -m pytest tests/test_app_metadata.py::test_settings_dialog_exposes_manual_update_check_button -q
```

Expected:

```text
AttributeError: 'SettingsDialog' object has no attribute 'check_updates_requested'
```

- [ ] **Step 3: Update SettingsDialog imports**

In `app/windows/settings_dialog.py`, add `QPushButton` to the widget imports:

```python
from PyQt6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)
```

- [ ] **Step 4: Add the manual update signal**

Inside `class SettingsDialog(QDialog):`, add the signal next to the existing signals:

```python
class SettingsDialog(QDialog):
    engineering_mode_changed = pyqtSignal(bool)
    demo_settings_changed = pyqtSignal(bool, int, int, str)
    check_updates_requested = pyqtSignal()
```

- [ ] **Step 5: Add the About tab button and busy-state method**

Replace `_about_tab` with this implementation:

```python
def _about_tab(self) -> QWidget:
    page = QWidget()
    layout = QFormLayout(page)
    layout.setContentsMargins(14, 14, 14, 14)
    layout.setSpacing(10)
    app_label = QLabel(APP_NAME)
    app_label.setStyleSheet("font-weight: 800;")
    version_label = QLabel(APP_VERSION)
    self.update_check_button = QPushButton("Check for updates")
    self.update_check_button.clicked.connect(self.check_updates_requested.emit)
    layout.addRow("?蝔?", app_label)
    layout.addRow("?", version_label)
    layout.addRow("", self.update_check_button)
    return page

def set_update_checking(self, checking: bool) -> None:
    self.update_check_button.setEnabled(not checking)
    self.update_check_button.setText("Checking..." if checking else "Check for updates")
```

- [ ] **Step 6: Run the settings dialog test**

Run:

```powershell
python -m pytest tests/test_app_metadata.py::test_settings_dialog_exposes_manual_update_check_button -q
```

Expected:

```text
1 passed
```

- [ ] **Step 7: Run existing metadata tests**

Run:

```powershell
python -m pytest tests/test_app_metadata.py -q
```

Expected:

```text
4 passed
```

- [ ] **Step 8: Commit settings dialog update**

Run:

```powershell
git add app/windows/settings_dialog.py tests/test_app_metadata.py
git commit -m "feat: add manual update check entry point"
```

Expected:

```text
[master <hash>] feat: add manual update check entry point
```

## Task 4: Main Window Update Flow

**Files:**
- Modify: `app/windows/main_window.py`
- Test: `tests/test_ui_imports.py`

- [ ] **Step 1: Add an import smoke test for updater-enabled main window**

Append this test to `tests/test_ui_imports.py`:

```python
def test_main_window_imports_with_updater_enabled():
    from app.windows.main_window import MainWindow

    assert MainWindow is not None
```

- [ ] **Step 2: Run the smoke test**

Run:

```powershell
python -m pytest tests/test_ui_imports.py::test_main_window_imports_with_updater_enabled -q
```

Expected:

```text
1 passed
```

- [ ] **Step 3: Update MainWindow imports**

In `app/windows/main_window.py`, update imports:

```python
import asyncio
from pathlib import Path

from PyQt6.QtCore import QTimer, Qt, QUrl, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QDesktopServices, QIcon
```

Add updater imports below existing app imports:

```python
from ..constants import APP_ICON_FILENAME, APP_VERSION, APP_WINDOW_TITLE
from ..updater import UpdateCheckResult, UpdateStatus, check_for_update, download_asset
```

- [ ] **Step 4: Initialize update state and schedule startup check**

In `MainWindow.__init__`, after `self.state = DeviceState()`, add:

```python
self._update_check_running = False
```

At the end of `MainWindow.__init__`, after `self.scan_panel.set_recent_devices(self.recent_device_store.load())`, add:

```python
QTimer.singleShot(1500, self._start_automatic_update_check)
```

- [ ] **Step 5: Connect the Settings dialog manual check signal**

In `_open_settings`, after creating `dialog`, connect the signal:

```python
dialog.check_updates_requested.connect(lambda: self._start_manual_update_check(dialog))
```

Keep the existing engineering and demo signal connections unchanged.

- [ ] **Step 6: Add update check methods to MainWindow**

Add these methods before `_set_demo_preview_device`:

```python
def _start_automatic_update_check(self) -> None:
    if self._update_check_running:
        return
    asyncio.create_task(self._check_for_updates(automatic=True))

def _start_manual_update_check(self, dialog: SettingsDialog) -> None:
    if self._update_check_running:
        return
    dialog.set_update_checking(True)
    asyncio.create_task(self._check_for_updates(automatic=False, settings_dialog=dialog))

async def _check_for_updates(
    self,
    *,
    automatic: bool,
    settings_dialog: SettingsDialog | None = None,
) -> None:
    self._update_check_running = True
    try:
        result = await asyncio.to_thread(check_for_update, APP_VERSION)
    finally:
        self._update_check_running = False
        if settings_dialog is not None:
            settings_dialog.set_update_checking(False)

    if automatic and result.status is not UpdateStatus.UPDATE_AVAILABLE:
        return
    self._show_update_result(result, automatic=automatic)

def _show_update_result(self, result: UpdateCheckResult, *, automatic: bool) -> None:
    if result.status is UpdateStatus.UPDATE_AVAILABLE and result.info is not None:
        info = result.info
        answer = QMessageBox.question(
            self,
            "Update available",
            (
                f"Current version: {info.current_version}\n"
                f"Latest version: {info.latest_version}\n\n"
                "Download the new version now?"
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if answer is QMessageBox.StandardButton.Yes:
            asyncio.create_task(self._download_update(info.asset))
        return

    if automatic:
        return

    title = "Update check"
    if result.status is UpdateStatus.UP_TO_DATE:
        QMessageBox.information(self, title, result.message or "This app is already up to date.")
    elif result.status is UpdateStatus.REPO_UNAVAILABLE:
        QMessageBox.information(
            self,
            title,
            result.message or "The GitHub repository or release is not available yet.",
        )
    else:
        QMessageBox.warning(self, title, result.message or "The update check did not complete.")

async def _download_update(self, asset) -> None:
    try:
        path = await asyncio.to_thread(download_asset, asset)
    except Exception as exc:
        QMessageBox.warning(self, "Update download failed", str(exc))
        return

    answer = QMessageBox.question(
        self,
        "Update downloaded",
        (
            f"Downloaded:\n{path}\n\n"
            "Open the downloaded version now? Close this version before using the new one."
        ),
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        QMessageBox.StandardButton.Yes,
    )
    if answer is QMessageBox.StandardButton.Yes:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
```

- [ ] **Step 7: Run import and metadata tests**

Run:

```powershell
python -m pytest tests/test_ui_imports.py tests/test_app_metadata.py -q
```

Expected:

```text
all tests pass
```

- [ ] **Step 8: Run the app manually from source**

Run:

```powershell
python main.py
```

Expected:

```text
The app window opens. Settings -> About -> Check for updates reports that the GitHub repository or release is not available yet because the repository has not been published.
```

- [ ] **Step 9: Commit main window update flow**

Run:

```powershell
git add app/windows/main_window.py tests/test_ui_imports.py
git commit -m "feat: wire update checks into desktop UI"
```

Expected:

```text
[master <hash>] feat: wire update checks into desktop UI
```

## Task 5: Documentation And Verification

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Update README release instructions**

In `README.md`, replace the line:

```markdown
The executable will be created under `dist\`.
```

with:

```markdown
The executable will be created under `dist\`.

## Release And Auto Update

Auto update checks use public GitHub Releases from:

```text
https://github.com/jerrywu-voltraware/PC_GIOSXTR_Demo
```

Release tags must use lowercase `v` semantic versions:

```text
v1.0.1
```

Release assets should use the matching PyInstaller executable name:

```text
PC_GIOSXTR_Demo_V1.0.1.exe
```

Before publishing a release:

```powershell
python -m pytest -q
pyinstaller PC_GIOSXTR_Demo.spec
.\dist\PC_GIOSXTR_Demo_V1.0.1.exe
```

Open and verify the packaged executable locally before creating the GitHub Release. Users only see updates after a GitHub Release is published with an `.exe` asset.
```

- [ ] **Step 2: Run all tests**

Run:

```powershell
python -m pytest -q
```

Expected:

```text
all tests pass
```

- [ ] **Step 3: Build the executable**

Run:

```powershell
pyinstaller PC_GIOSXTR_Demo.spec
```

Expected:

```text
dist\PC_GIOSXTR_Demo_V1.0.0.exe exists
```

- [ ] **Step 4: Open the packaged executable for local verification**

Run:

```powershell
Start-Process -FilePath .\dist\PC_GIOSXTR_Demo_V1.0.0.exe
```

Expected:

```text
The packaged app opens. Settings -> About -> Check for updates displays a readable message while the GitHub repository has no published release.
```

- [ ] **Step 5: Commit docs**

Run:

```powershell
git add README.md
git commit -m "docs: document auto update release workflow"
```

Expected:

```text
[master <hash>] docs: document auto update release workflow
```

## Self-Review

- Spec coverage: the plan covers GitHub latest release checks, semantic version comparison, expected `.exe` asset names, quiet automatic failures, manual result dialogs, temp-directory downloads, no in-place executable replacement, startup scheduling, Settings About tab integration, tests, and README release workflow.
- Placeholder scan: the plan contains concrete file paths, code blocks, commands, and expected outcomes for each task.
- Type consistency: `UpdateStatus`, `UpdateAsset`, `UpdateInfo`, `UpdateCheckResult`, `check_for_update`, and `download_asset` are introduced in Task 2 before UI code imports them in Task 4.
