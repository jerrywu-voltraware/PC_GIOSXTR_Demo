import json
from urllib.error import HTTPError, URLError

import app.updater as updater
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
