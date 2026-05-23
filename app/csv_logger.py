"""Flutter-compatible CSV logging."""

from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path
from typing import TextIO

from .constants import CSV_HEADER
from .models import DeviceState


class CsvLogger:
    def __init__(self, directory: str | Path | None = None) -> None:
        self.directory = Path(directory) if directory is not None else Path.cwd() / "logs"
        self.current_path: Path | None = None
        self._file: TextIO | None = None
        self._writer: csv.writer | None = None

    @property
    def is_recording(self) -> bool:
        return self._file is not None

    def start(self, suffix: str | None = None) -> Path:
        self.stop()
        self.directory.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        suffix_part = f"_{suffix}" if suffix else ""
        name = f"Log_{timestamp}{suffix_part}.csv"
        self.current_path = self.directory / name
        self._file = self.current_path.open("w", newline="", encoding="utf-8")
        self._writer = csv.writer(self._file)
        self._writer.writerow(CSV_HEADER)
        self._file.flush()
        return self.current_path

    def stop(self) -> Path | None:
        path = self.current_path
        if self._file is not None:
            self._file.flush()
            self._file.close()
        self._file = None
        self._writer = None
        return path

    def write_state(self, state: DeviceState) -> None:
        if self._writer is None or self._file is None:
            return
        if state.ptu_input_voltage == 0 and state.pru_dyn_vout == 0:
            return
        self._writer.writerow(state.csv_values())
        self._file.flush()
