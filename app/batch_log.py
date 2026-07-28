"""Persistent application-wide batch log with a live Qt event stream."""

from __future__ import annotations

import asyncio
import sys
import threading
import traceback
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import QObject, QStandardPaths, Qt, pyqtSignal


BATCH_LOG_FILENAME = "batch.txt"
BATCH_DISPLAY_LINE_LIMIT = 2000


class _BatchLogBus(QObject):
    line_written = pyqtSignal(str)


_lock = threading.RLock()
_bus: _BatchLogBus | None = None
_path: Path | None = None
_display_lines: list[str] = []
_exception_hooks_installed = False
_previous_sys_hook = None
_previous_thread_hook = None
_installed_sys_hook = None
_installed_thread_hook = None
_asyncio_handlers: dict[asyncio.AbstractEventLoop, tuple[object, object]] = {}


def _default_path() -> Path:
    return Path.cwd() / "logs" / BATCH_LOG_FILENAME


def _fallback_path() -> Path:
    base = QStandardPaths.writableLocation(
        QStandardPaths.StandardLocation.AppLocalDataLocation
    )
    if base:
        return Path(base) / "logs" / BATCH_LOG_FILENAME
    return Path.home() / ".giosxtr" / "logs" / BATCH_LOG_FILENAME


def _prepare_path(path: Path) -> None:
    """Create and verify a path can be opened for append without truncation."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline=""):
        pass


def _ensure_bus_locked() -> _BatchLogBus:
    """Return a live signal bus. The caller must hold ``_lock``."""
    global _bus
    if _bus is not None:
        try:
            # QApplication teardown can delete the underlying C++ QObject while
            # this Python wrapper is still referenced.
            _bus.thread()
        except RuntimeError:
            _bus = None
    if _bus is None:
        _bus = _BatchLogBus()
    return _bus


def batch_log_bus() -> _BatchLogBus:
    """Return the process-wide Qt signal bus, created on the caller's thread."""
    with _lock:
        return _ensure_bus_locked()


def subscribe_batch_log(
    receiver: Callable[[str], None],
) -> tuple[_BatchLogBus, list[str]]:
    """Atomically subscribe a live viewer and return its initial screen batch.

    Connecting and taking the snapshot under the same lock prevents a dongle
    reader event from falling into the gap between those two operations.
    """
    with _lock:
        bus = _ensure_bus_locked()
        bus.line_written.connect(
            receiver,
            type=Qt.ConnectionType.QueuedConnection,
        )
        return bus, list(_display_lines)


def initialize_batch_log(path: Path | None = None) -> Path:
    """Select the persistent file and start a fresh on-screen batch.

    The file is opened in append mode and is never truncated. Only the in-memory
    display batch is reset between application sessions.
    """
    global _path
    selected = Path(path) if path is not None else _default_path()
    fallback = _fallback_path()
    failures: list[str] = []
    with _lock:
        _path = None
        _display_lines.clear()
        for candidate in dict.fromkeys((selected, fallback)):
            try:
                _prepare_path(candidate)
            except OSError as exc:
                failures.append(f"{candidate}: {exc}")
                continue
            _path = candidate
            break
        active_path = _path

    if active_path is None:
        batch_log(
            "LOGGER",
            "batch.txt could not be created; history is available on screen only. "
            + " | ".join(failures),
            level="ERROR",
        )
        return selected
    if active_path != selected:
        batch_log(
            "LOGGER",
            f"Primary batch path unavailable; using fallback {active_path}. "
            + " | ".join(failures),
            level="WARNING",
        )
    return active_path


def disable_batch_log_file(*, clear_display: bool = True) -> None:
    """Disable persistence; intended for isolated tests."""
    global _path
    with _lock:
        _path = None
        if clear_display:
            _display_lines.clear()


def batch_log_path() -> Path:
    with _lock:
        return _path or _default_path()


def current_batch_lines() -> list[str]:
    with _lock:
        return list(_display_lines)


def _clean_message(message: object) -> str:
    # One event always occupies one physical line, making the 2000-line display
    # boundary deterministic even when an exception contains embedded newlines.
    return " ".join(str(message).replace("\r", "\n").splitlines()).strip()


def _format_line(category: object, message: object, level: object) -> str:
    timestamp = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    category_text = str(category or "APP").strip().upper()
    level_text = str(level or "INFO").strip().upper()
    return (
        f"{timestamp} | {level_text:<7} | {category_text:<10} | "
        f"{_clean_message(message)}"
    )


def _append_display_locked(line: str) -> None:
    if len(_display_lines) >= BATCH_DISPLAY_LINE_LIMIT:
        _display_lines.clear()
    _display_lines.append(line)


def _write_line(path: Path, line: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="") as file:
        file.write(line + "\n")


def batch_log(category: str, message: object, *, level: str = "INFO") -> str:
    """Append one timestamped event to batch.txt and notify live viewers."""
    global _bus, _path

    with _lock:
        # Timestamping, persistence, and emission share one ordering lock so
        # simultaneous dongle/worker events stay in the same order everywhere.
        line = _format_line(category, message, level)
        _append_display_locked(line)
        emitted_lines = [line]
        selected_path = _path
        if selected_path is not None:
            try:
                _write_line(selected_path, line)
            except OSError as exc:
                fallback = _fallback_path()
                fallback_error: OSError | None = None
                fallback_succeeded = False
                if fallback != selected_path:
                    try:
                        _prepare_path(fallback)
                        _write_line(fallback, line)
                    except OSError as retry_exc:
                        fallback_error = retry_exc
                    else:
                        _path = fallback
                        fallback_succeeded = True
                if fallback_succeeded:
                    diagnostic = _format_line(
                        "LOGGER",
                        f"Writing {selected_path} failed ({exc}); switched to {fallback}",
                        "WARNING",
                    )
                    _append_display_locked(diagnostic)
                    emitted_lines.append(diagnostic)
                    try:
                        _write_line(fallback, diagnostic)
                    except OSError as diagnostic_exc:
                        _path = None
                        stopped = _format_line(
                            "LOGGER",
                            f"batch.txt persistence stopped after fallback failed: "
                            f"{diagnostic_exc}",
                            "ERROR",
                        )
                        _append_display_locked(stopped)
                        emitted_lines.append(stopped)
                else:
                    _path = None
                    retry_detail = (
                        f"; fallback {fallback} failed ({fallback_error})"
                        if fallback_error is not None
                        else ""
                    )
                    diagnostic = _format_line(
                        "LOGGER",
                        f"batch.txt persistence stopped: {selected_path} failed ({exc})"
                        f"{retry_detail}",
                        "ERROR",
                    )
                    _append_display_locked(diagnostic)
                    emitted_lines.append(diagnostic)
        active_bus = _bus
        if active_bus is not None:
            try:
                # Keep emit within the ordering lock. QueuedConnection ensures
                # the widget slot itself still runs later on the UI thread.
                for emitted_line in emitted_lines:
                    active_bus.line_written.emit(emitted_line)
            except RuntimeError:
                # Persistence already succeeded. Drop only the stale live-view
                # bus; the next OverviewPage recreates it on the UI thread.
                if _bus is active_bus:
                    _bus = None
    return line


def batch_log_exception(
    category: str,
    message: object,
    exc_type=None,
    exc_value=None,
    exc_traceback=None,
) -> None:
    """Persist an exception summary and its traceback as individual events."""
    if exc_type is None:
        exc_type, exc_value, exc_traceback = sys.exc_info()
    trace_lines: list[str] = []
    if exc_type is not None:
        for trace_line in traceback.format_exception(exc_type, exc_value, exc_traceback):
            trace_lines.extend(
                physical_line
                for physical_line in trace_line.rstrip().splitlines()
                if physical_line.strip()
            )
    with _lock:
        batch_log(category, message, level="ERROR")
        for physical_line in trace_lines:
            batch_log(category, physical_line, level="ERROR")


def install_exception_logging(loop: asyncio.AbstractEventLoop | None = None) -> None:
    """Capture uncaught exceptions without stacking duplicate wrappers."""
    global _exception_hooks_installed
    global _installed_sys_hook, _installed_thread_hook
    global _previous_sys_hook, _previous_thread_hook

    with _lock:
        if not _exception_hooks_installed:
            _previous_sys_hook = sys.excepthook
            _previous_thread_hook = threading.excepthook

            def sys_hook(exc_type, exc_value, exc_traceback) -> None:
                try:
                    batch_log_exception(
                        "EXCEPTION",
                        f"Uncaught exception: {exc_value}",
                        exc_type,
                        exc_value,
                        exc_traceback,
                    )
                finally:
                    _previous_sys_hook(exc_type, exc_value, exc_traceback)

            def thread_hook(args: threading.ExceptHookArgs) -> None:
                try:
                    batch_log_exception(
                        "THREAD",
                        f"Uncaught exception in {args.thread.name}: {args.exc_value}",
                        args.exc_type,
                        args.exc_value,
                        args.exc_traceback,
                    )
                finally:
                    _previous_thread_hook(args)

            _installed_sys_hook = sys_hook
            _installed_thread_hook = thread_hook
            sys.excepthook = sys_hook
            threading.excepthook = thread_hook
            _exception_hooks_installed = True

        if loop is not None and loop not in _asyncio_handlers:
            previous_asyncio_handler = loop.get_exception_handler()

            def asyncio_handler(active_loop, context) -> None:
                try:
                    message = context.get("message", "Unhandled asyncio exception")
                    exception = context.get("exception")
                    if exception is None:
                        batch_log("ASYNC", message, level="ERROR")
                    else:
                        batch_log_exception(
                            "ASYNC",
                            f"{message}: {exception}",
                            type(exception),
                            exception,
                            exception.__traceback__,
                        )
                finally:
                    if previous_asyncio_handler is None:
                        active_loop.default_exception_handler(context)
                    else:
                        previous_asyncio_handler(active_loop, context)

            _asyncio_handlers[loop] = (previous_asyncio_handler, asyncio_handler)
            loop.set_exception_handler(asyncio_handler)


def uninstall_exception_logging(
    loop: asyncio.AbstractEventLoop | None = None,
) -> None:
    """Restore hooks installed by :func:`install_exception_logging` (tests/tools)."""
    global _exception_hooks_installed
    global _installed_sys_hook, _installed_thread_hook
    global _previous_sys_hook, _previous_thread_hook

    with _lock:
        loops = [loop] if loop is not None else list(_asyncio_handlers)
        for active_loop in loops:
            saved = _asyncio_handlers.pop(active_loop, None)
            if saved is None:
                continue
            previous_handler, installed_handler = saved
            try:
                if active_loop.get_exception_handler() is installed_handler:
                    active_loop.set_exception_handler(previous_handler)
            except RuntimeError:
                pass

        if sys.excepthook is _installed_sys_hook:
            sys.excepthook = _previous_sys_hook
        if threading.excepthook is _installed_thread_hook:
            threading.excepthook = _previous_thread_hook
        _previous_sys_hook = None
        _previous_thread_hook = None
        _installed_sys_hook = None
        _installed_thread_hook = None
        _exception_hooks_installed = False
