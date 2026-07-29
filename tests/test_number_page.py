from __future__ import annotations

import asyncio
import os


class _ConnectedBle:
    is_connected = True

    def __init__(self) -> None:
        self.written_numbers: list[int] = []

    async def write_device_number(self, number: int) -> None:
        await asyncio.sleep(0)
        self.written_numbers.append(number)


def test_write_number_uses_nonblocking_confirmation(monkeypatch):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QApplication, QMessageBox

    from app.windows.number_page import NumberPage

    _app = QApplication.instance() or QApplication([])
    ble = _ConnectedBle()
    page = NumberPage(lambda: ble)  # type: ignore[arg-type]
    page.combo.setCurrentIndex(6)  # Number 7
    opened: list[QMessageBox] = []
    logs: list[str] = []
    page.log_message.connect(logs.append)

    def blocking_information(*_args, **_kwargs):
        raise AssertionError("write_number must not enter a modal QMessageBox loop")

    monkeypatch.setattr(QMessageBox, "information", blocking_information)
    monkeypatch.setattr(QMessageBox, "open", lambda box: opened.append(box))

    asyncio.run(page.write_number.__wrapped__(page))

    assert ble.written_numbers == [7]
    assert logs == ["Device number set to 7"]
    assert page.status.text() == "Number set to 7"
    assert page.write_btn.isEnabled()
    assert len(opened) == 1
    assert opened[0].windowTitle() == "裝置編號已更新"
    assert "裝置編號已設定為 7" in opened[0].text()
    assert opened[0].testAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
    page.close()
