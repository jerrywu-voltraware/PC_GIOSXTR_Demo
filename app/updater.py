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
    target_path: Path | None = None,
    timeout: float = DOWNLOAD_TIMEOUT_SECONDS,
) -> Path:
    if target_path is not None:
        destination = target_path
        destination.parent.mkdir(parents=True, exist_ok=True)
    else:
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
