import asyncio


def test_user_facing_messages_cover_adapter_failures():
    from app.ble_adapter import AdapterCheckResult, AdapterStatus, user_facing_message

    no_adapter_title, no_adapter_body = user_facing_message(
        AdapterCheckResult(AdapterStatus.NO_ADAPTER, "no radio")
    )
    disabled_title, disabled_body = user_facing_message(
        AdapterCheckResult(AdapterStatus.DISABLED, "off")
    )
    unknown_title, unknown_body = user_facing_message(
        AdapterCheckResult(AdapterStatus.UNKNOWN_ERROR, "boom")
    )
    ok_title, ok_body = user_facing_message(AdapterCheckResult(AdapterStatus.OK, "ready"))
    unsupported_title, unsupported_body = user_facing_message(
        AdapterCheckResult(AdapterStatus.UNSUPPORTED_OS, "linux")
    )

    assert no_adapter_title == "找不到藍牙介面"
    assert "USB 藍牙接收器" in no_adapter_body
    assert disabled_title == "藍牙已關閉"
    assert "設定" in disabled_body
    assert unknown_title == "無法檢測藍牙狀態"
    assert "boom" in unknown_body
    assert (ok_title, ok_body) == ("", "")
    assert (unsupported_title, unsupported_body) == ("", "")


def test_bluetooth_adapter_check_caches_ok_result_for_30_seconds(monkeypatch):
    from app import ble_adapter
    from app.ble_adapter import AdapterCheckResult, AdapterStatus

    calls = 0
    now = [1000.0]

    async def fake_check_windows():
        nonlocal calls
        calls += 1
        return AdapterCheckResult(AdapterStatus.OK, f"call {calls}")

    monkeypatch.setattr(ble_adapter.sys, "platform", "win32")
    monkeypatch.setattr(ble_adapter.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(ble_adapter, "_check_windows", fake_check_windows)
    ble_adapter.reset_adapter_cache()

    first = asyncio.run(ble_adapter.check_bluetooth_adapter())
    now[0] += 5
    second = asyncio.run(ble_adapter.check_bluetooth_adapter())
    now[0] += 31
    third = asyncio.run(ble_adapter.check_bluetooth_adapter())

    assert first.detail == "call 1"
    assert second.detail == "call 1"
    assert third.detail == "call 2"
    assert calls == 2


def test_bluetooth_adapter_check_does_not_cache_unavailable_result(monkeypatch):
    from app import ble_adapter
    from app.ble_adapter import AdapterCheckResult, AdapterStatus

    results = [
        AdapterCheckResult(AdapterStatus.NO_ADAPTER, "missing"),
        AdapterCheckResult(AdapterStatus.OK, "inserted"),
    ]

    async def fake_check_windows():
        return results.pop(0)

    monkeypatch.setattr(ble_adapter.sys, "platform", "win32")
    monkeypatch.setattr(ble_adapter, "_check_windows", fake_check_windows)
    ble_adapter.reset_adapter_cache()

    first = asyncio.run(ble_adapter.check_bluetooth_adapter())
    second = asyncio.run(ble_adapter.check_bluetooth_adapter())

    assert first.status is AdapterStatus.NO_ADAPTER
    assert second.status is AdapterStatus.OK
