import os
import threading

import pytest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app.batch_log import (
    BATCH_DISPLAY_LINE_LIMIT,
    batch_log,
    current_batch_lines,
    disable_batch_log_file,
    initialize_batch_log,
)


@pytest.fixture(scope="module", autouse=True)
def qt_application():
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def isolated_batch_file(tmp_path):
    path = tmp_path / "batch.txt"
    initialize_batch_log(path)
    try:
        yield path
    finally:
        disable_batch_log_file(clear_display=True)


def test_batch_file_keeps_full_history_when_display_batch_rolls_over(
    isolated_batch_file,
):
    for index in range(BATCH_DISPLAY_LINE_LIMIT + 1):
        batch_log("TEST", f"event-{index:04d}")

    persisted_lines = isolated_batch_file.read_text(encoding="utf-8").splitlines()

    assert len(persisted_lines) == BATCH_DISPLAY_LINE_LIMIT + 1
    assert "event-0000" in persisted_lines[0]
    assert f"event-{BATCH_DISPLAY_LINE_LIMIT:04d}" in persisted_lines[-1]
    assert len(current_batch_lines()) == 1
    assert f"event-{BATCH_DISPLAY_LINE_LIMIT:04d}" in current_batch_lines()[0]


def test_overview_keeps_only_the_new_batch_on_the_2001st_line(
    isolated_batch_file,
    qt_application,
):
    from app.windows.overview_page import OverviewPage

    page = OverviewPage()
    try:
        for index in range(BATCH_DISPLAY_LINE_LIMIT + 1):
            batch_log("SCREEN", f"screen-event-{index:04d}")
        qt_application.processEvents()

        assert page._batch_visible_line_count == 1
        assert page.batch_log_text.document().blockCount() == 1
        assert (
            f"screen-event-{BATCH_DISPLAY_LINE_LIMIT:04d}"
            in page.batch_log_text.toPlainText()
        )
    finally:
        page.close()
        page.deleteLater()
        qt_application.processEvents()


def test_batch_file_is_appended_across_application_sessions(tmp_path):
    path = tmp_path / "batch.txt"
    try:
        initialize_batch_log(path)
        batch_log("APP", "first session")
        initialize_batch_log(path)
        batch_log("APP", "second session")

        persisted_lines = path.read_text(encoding="utf-8").splitlines()
        assert len(persisted_lines) == 2
        assert "first session" in persisted_lines[0]
        assert "second session" in persisted_lines[1]
        assert len(current_batch_lines()) == 1
    finally:
        disable_batch_log_file(clear_display=True)


def test_concurrent_writers_keep_file_and_live_view_in_the_same_order(
    isolated_batch_file,
    qt_application,
):
    from app.windows.overview_page import OverviewPage

    page = OverviewPage()
    start = threading.Barrier(5)

    def write_events(worker: int) -> None:
        start.wait()
        for index in range(50):
            batch_log("THREAD", f"worker={worker} event={index}")

    threads = [threading.Thread(target=write_events, args=(worker,)) for worker in range(4)]
    try:
        for thread in threads:
            thread.start()
        start.wait()
        for thread in threads:
            thread.join()
        qt_application.processEvents()

        persisted_lines = isolated_batch_file.read_text(encoding="utf-8").splitlines()
        visible_lines = page.batch_log_text.toPlainText().splitlines()
        assert len(persisted_lines) == 200
        assert visible_lines == persisted_lines
    finally:
        page.close()
        page.deleteLater()
        qt_application.processEvents()


def test_gui_hidden_events_stay_in_batch_file_but_not_overview(
    isolated_batch_file,
    qt_application,
):
    from app.windows.overview_page import OverviewPage

    batch_log(
        "DONGLE",
        "serial read failed on COM7: ClearCommError failed",
        level="ERROR",
        show_in_gui=False,
    )
    batch_log("DEVICE", "裝置斷線，準備自動重新連線")

    page = OverviewPage()
    try:
        batch_log(
            "DONGLE",
            "firmware DIAG: last_err=0x0011",
            level="ERROR",
            show_in_gui=False,
        )
        batch_log("DEVICE", "已重新連線")
        qt_application.processEvents()

        persisted_text = isolated_batch_file.read_text(encoding="utf-8")
        visible_text = page.batch_log_text.toPlainText()

        assert "ClearCommError failed" in persisted_text
        assert "last_err=0x0011" in persisted_text
        assert "ClearCommError failed" not in visible_text
        assert "last_err=0x0011" not in visible_text
        assert "裝置斷線，準備自動重新連線" in visible_text
        assert "已重新連線" in visible_text
        assert page._batch_visible_line_count == 2
        assert len(current_batch_lines()) == 2
    finally:
        page.close()
        page.deleteLater()
        qt_application.processEvents()


def test_device_state_can_keep_technical_detail_out_of_batch_gui(
    isolated_batch_file,
):
    from app.models import DeviceState

    state = DeviceState(device_address="90:04:22:B6:96:00")
    detail = "重新連線失敗: ClearCommError failed"

    state.add_log(detail, show_in_batch_gui=False)

    assert detail in isolated_batch_file.read_text(encoding="utf-8")
    assert detail in state.log_messages[0]
    assert all(detail not in line for line in current_batch_lines())


def test_device_state_log_is_mirrored_with_identity_and_error_level(
    isolated_batch_file,
):
    from app.models import DeviceState

    state = DeviceState(
        device_name="GIOS0801ST#45",
        device_address="90:04:22:B6:96:00",
    )

    state.add_log("Reconnect failed: transport unavailable")

    persisted_line = isolated_batch_file.read_text(encoding="utf-8").strip()
    assert "| ERROR" in persisted_line
    assert "| DEVICE" in persisted_line
    assert "[90:04:22:B6:96:00]" in persisted_line
    assert "Reconnect failed: transport unavailable" in persisted_line
    assert "Reconnect failed: transport unavailable" in state.log_messages[0]
