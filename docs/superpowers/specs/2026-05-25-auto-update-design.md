# PC GIOSXTR Auto Update Design

## Goal

Add a lightweight auto-update mechanism to the PyInstaller Windows desktop app so deployed users can discover and download new versions after the developer publishes a verified release.

The app will use the public GitHub Releases feed for:

```text
jerrywu-voltraware/PC_GIOSXTR_Demo
```

The repository does not need to exist during implementation. Until it exists and has at least one release, update checks must fail quietly during automatic checks and show a readable explanation during manual checks.

## Chosen Approach

Use a semi-automatic update flow:

1. The app checks GitHub Releases for the latest public release.
2. If the release version is newer than the running app version, the app asks the user whether to download it.
3. The app downloads the release executable to the user's temporary download area.
4. After download, the app asks the user to close the current app and open the downloaded executable.

This avoids maintaining an external updater process and avoids installer-level complexity. It is the safest fit for the current single-file PyInstaller packaging flow.

## Release Contract

The updater reads:

```text
https://api.github.com/repos/jerrywu-voltraware/PC_GIOSXTR_Demo/releases/latest
```

Release tags must use semantic versions with a leading `v`:

```text
v1.0.1
v1.1.0
v2.0.0
```

The running app version remains defined in `app/constants.py`:

```python
APP_VERSION = "V1.0.0"
```

Version comparison ignores a leading `v` or `V`.

Release assets must include a Windows executable named with the same version:

```text
PC_GIOSXTR_Demo_V1.0.1.exe
```

The updater may select the first `.exe` asset if the exact expected name is not found, but the release contract remains the versioned filename above.

## Developer Release Workflow

The release workflow is:

```text
Update APP_VERSION and executable name
-> Run tests
-> Build with PyInstaller
-> Open the generated exe locally and verify it
-> Create or update the public GitHub repository
-> Create GitHub Release vX.Y.Z
-> Upload the verified PC_GIOSXTR_Demo_VX.Y.Z.exe asset
-> Users discover the release through the app update check
```

The developer must not publish a GitHub Release until the packaged executable has been opened and verified locally.

## App Startup Behavior

On normal startup, the app starts a background update check after the main window is visible.

Automatic checks must not block BLE scanning, UI rendering, or app shutdown.

Automatic checks are quiet on failure:

- no network connection
- GitHub API unavailable
- repository not found
- no releases
- malformed release data
- no downloadable executable asset

If a newer version exists, the app shows a dialog with:

- current version
- latest version
- release page URL
- option to download now
- option to skip

## Manual Check Behavior

The settings dialog About tab gains a `Check for updates` button.

Manual checks show a result in all cases:

- up to date
- newer version available
- repository or release not found
- network failure
- no executable asset in release
- unexpected GitHub response

Manual checks use the same update service as automatic checks.

## Download Behavior

Downloads go to a local user-writable update directory under the system temp directory, for example:

```text
%TEMP%\PC_GIOSXTR_Demo\updates\
```

Downloaded filenames keep the GitHub asset name. If a file already exists, the updater may overwrite it.

After download completes, the app shows the downloaded path and offers to open the executable.

The app will not attempt to replace the currently running executable. That avoids Windows file-locking problems and keeps the first implementation reliable.

## UI Integration

The existing settings button in the top-right tab corner remains the entry point.

Settings dialog changes:

- About tab displays app name and current version.
- About tab adds a `Check for updates` button.
- While checking, the button is disabled and shows progress text.
- Results are shown with QMessageBox dialogs.

Main window changes:

- After startup, schedule one automatic check.
- If an update is available, display the update prompt from the main window.
- If the user chooses download, run the download asynchronously and show completion/failure dialogs.

## Module Design

Create `app/updater.py` with no Qt widget dependencies.

Responsibilities:

- normalize and compare versions
- fetch latest release JSON from GitHub
- identify an executable asset
- return structured update results
- download the selected asset

The UI layer handles QMessageBox prompts and button state.

Suggested data types:

```python
UpdateAsset(name, download_url, size)
UpdateInfo(current_version, latest_version, release_url, asset)
UpdateCheckResult(status, info, message)
```

Statuses:

```text
up_to_date
update_available
repo_unavailable
no_release
no_asset
network_error
invalid_response
```

## Error Handling

Network operations use short timeouts so startup checks cannot hang the app.

The updater treats GitHub `404` as repository or release unavailable. This supports the current state where the repository has not yet been created.

Automatic update failures are logged only if the app already has an appropriate logging surface. They do not show dialogs.

Manual update failures show concise user-facing messages.

## Testing

Unit tests cover:

- version normalization and comparison
- no-update result
- update-available result
- missing asset result
- repository unavailable result
- malformed response handling
- expected asset-name selection
- fallback `.exe` asset selection

Manual verification covers:

- running `python main.py`
- opening Settings -> About -> Check for updates before the repo exists
- building the PyInstaller exe
- opening the packaged exe locally before publishing

## Acceptance Criteria

The feature is complete when:

- the app can check `jerrywu-voltraware/PC_GIOSXTR_Demo` GitHub Releases
- startup update checks do not block or break the app when the repo has no release
- manual update checks report a useful status
- a newer release with an `.exe` asset prompts the user to download it
- the downloaded executable can be opened by the user
- tests pass
- README documents the release and verification workflow
