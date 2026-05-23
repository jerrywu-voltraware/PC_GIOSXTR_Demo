from app.recent_devices import RecentDevice, RecentDeviceStore


def test_recent_device_store_keeps_latest_first_and_deduplicates(tmp_path):
    store = RecentDeviceStore(tmp_path / "recent.json")

    store.remember(RecentDevice("AA:BB", "Bike", 12, -55))
    store.remember(RecentDevice("CC:DD", "Scooter", 8, -60))
    store.remember(RecentDevice("AA:BB", "Bike Renamed", 13, -50))

    devices = store.load()

    assert [device.address for device in devices] == ["AA:BB", "CC:DD"]
    assert devices[0].name == "Bike Renamed"
    assert devices[0].device_number == 13
    assert devices[0].rssi == -50
