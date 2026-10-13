"""Flutter-compatible CSV logging."""

from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path
from time import monotonic
from typing import TextIO

from .constants import CSV_HEADER
from .models import DeviceState


class CsvLogger:
    def __init__(self, directory: str | Path | None = None) -> None:
        self.directory = Path(directory) if directory is not None else Path.cwd() / "logs"
        self.current_path: Path | None = None
        self._file: TextIO | None = None
        self._writer: csv.writer | None = None
        # Split state. When max_rows is set, the logger rolls to a fresh file
        # once the current one reaches max_rows written data rows. The base
        # timestamp and suffix stay fixed for the whole recording so every part
        # (_p001, _p002, ...) shares one stem and sorts together.
        self.max_rows: int | None = None
        self._row_count = 0
        self._base_timestamp: str | None = None
        self._suffix = ""
        self._part = 0
        self._pending_roll = False
        self.rows_written = 0
        self.parts_created = 0
        self.started_at: datetime | None = None
        self.last_write_at: datetime | None = None
        self._started_monotonic: float | None = None
        self._stopped_monotonic: float | None = None
        self._last_write_monotonic: float | None = None

    @property
    def elapsed_seconds(self) -> float:
        if self._started_monotonic is None:
            return 0.0
        end = self._stopped_monotonic if self._stopped_monotonic is not None else monotonic()
        return max(0.0, end - self._started_monotonic)

    @property
    def seconds_since_write(self) -> float | None:
        if self._last_write_monotonic is None:
            return None
        return max(0.0, monotonic() - self._last_write_monotonic)

    @property
    def is_recording(self) -> bool:
        return self._file is not None

    def start(self, suffix: str | None = None, max_rows: int | None = None) -> Path:
        self.stop()
        self.directory.mkdir(parents=True, exist_ok=True)
        self._base_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self._suffix = suffix or ""
        # Treat non-positive limits as "no split" so a bad setting never rolls
        # on every single row.
        self.max_rows = max_rows if (max_rows is not None and max_rows > 0) else None
        self._row_count = 0
        self._part = 1
        self._pending_roll = False
        self.rows_written = 0
        self.parts_created = 0
        self.started_at = None
        self.last_write_at = None
        self._started_monotonic = None
        self._stopped_monotonic = None
        self._last_write_monotonic = None
        self.current_path = None
        # Exclusive creation protects existing measurements, including two
        # recordings started within the same second or by another process.
        base_timestamp = self._base_timestamp
        attempt = 0
        while True:
            self._base_timestamp = base_timestamp if not attempt else f"{base_timestamp}_r{attempt:02d}"
            try:
                path = self._open_part()
                break
            except FileExistsError:
                attempt += 1
        self.started_at = datetime.now()
        self._started_monotonic = monotonic()
        return path

    def _open_part(self) -> Path:
        suffix_part = f"_{self._suffix}" if self._suffix else ""
        name = f"Log_{self._base_timestamp}{suffix_part}_p{self._part:03d}.csv"
        path = self.directory / name
        handle = path.open("x", newline="", encoding="utf-8")
        try:
            writer = csv.writer(handle)
            writer.writerow(CSV_HEADER)
            handle.flush()
        except OSError:
            try:
                handle.close()
            except OSError:
                pass
            raise
        self.current_path = path
        self._file = handle
        self._writer = writer
        self.parts_created += 1
        return path

    def stop(self) -> Path | None:
        path = self.current_path
        handle = self._file
        self._file = None
        self._writer = None
        self.max_rows = None
        self._row_count = 0
        self._base_timestamp = None
        self._suffix = ""
        self._part = 0
        self._pending_roll = False
        if self._started_monotonic is not None and self._stopped_monotonic is None:
            self._stopped_monotonic = monotonic()
        if handle is not None:
            try:
                handle.flush()
            finally:
                handle.close()
        return path

    def _open_next_part(self) -> None:
        """Close the current part and open the next one within the same recording."""
        handle = self._file
        self._file = None
        self._writer = None
        if handle is not None:
            try:
                handle.flush()
            finally:
                handle.close()
        self._part += 1
        self._row_count = 0
        self._open_part()

    def write_state(self, state: DeviceState) -> None:
        if self._writer is None or self._file is None:
            return
        if state.ptu_input_voltage == 0 and state.pru_dyn_vout == 0:
            return
        # Roll lazily: open the next part only when a real row actually needs
        # it. This way a recording whose row count is an exact multiple of
        # max_rows does not leave a trailing header-only file behind.
        if self._pending_roll:
            self._open_next_part()
            self._pending_roll = False
        self._writer.writerow(state.csv_values())
        self._file.flush()
        self._row_count += 1
        self.rows_written += 1
        self.last_write_at = datetime.now()
        self._last_write_monotonic = monotonic()
        if self.max_rows is not None and self._row_count >= self.max_rows:
            self._pending_roll = True
