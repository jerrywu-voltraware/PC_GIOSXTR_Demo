"""DPI-aware application typography and persistent user text scaling."""

from __future__ import annotations

from PyQt6.QtCore import QEvent, QObject, QSettings, QTimer, pyqtSignal
from PyQt6.QtGui import QFont, QFontMetrics
from PyQt6.QtWidgets import QApplication, QTableView


BASE_FONT_POINTS = 11.0
UI_SCALE_CHOICES = (100, 125, 150, 175, 200)
UI_SCALE_SETTINGS_KEY = "appearance/text_scale_percent"


def normalize_scale(value: object) -> int:
    """Accept supported percentages and recover safely from stale settings."""
    try:
        number = int(str(value))
    except (TypeError, ValueError):
        return 100
    return number if number in UI_SCALE_CHOICES else 100


def load_saved_scale() -> int:
    return normalize_scale(QSettings().value(UI_SCALE_SETTINGS_KEY, 100))


def save_scale(percent: int) -> None:
    QSettings().setValue(UI_SCALE_SETTINGS_KEY, normalize_scale(percent))


def font_size(points: float = BASE_FONT_POINTS) -> str:
    """Return a QSS point size, leaving display DPI handling to Qt."""
    return f"{points * typography_manager().scale() / 100:g}pt"


def scaled_px(logical_px: float) -> int:
    """Scale a layout dimension in Qt logical pixels, without multiplying DPI."""
    return round(logical_px * typography_manager().scale() / 100)


class _TypographyManager(QObject):
    scale_changed = pyqtSignal(int)

    def __init__(self) -> None:
        super().__init__()
        self._scale = 100
        self._app: QApplication | None = None
        self._base_font: QFont | None = None
        self._refresh_pending = False

    def install(self, app: QApplication) -> None:
        """Install once per application; theme changes retain the active scale."""
        if self._app is not app:
            self._app = app
            self._base_font = QFont(app.font())
            self._refresh_pending = False
            app.installEventFilter(self)
            self.set_scale(load_saved_scale(), persist=False)
        else:
            self._apply_font()

    def scale(self) -> int:
        return self._scale

    def set_scale(self, percent: int, *, persist: bool = True) -> None:
        percent = normalize_scale(percent)
        changed = percent != self._scale
        self._scale = percent
        self._apply_font()
        if persist:
            save_scale(percent)
        if changed:
            self.scale_changed.emit(percent)
        self._queue_table_refresh()

    def _apply_font(self) -> None:
        if self._app is None or self._base_font is None:
            return
        font = QFont(self._base_font)
        font.setPointSizeF(BASE_FONT_POINTS * self._scale / 100)
        self._app.setFont(font)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if isinstance(watched, QTableView) and event.type() in (
            QEvent.Type.Show,
            QEvent.Type.Polish,
            QEvent.Type.FontChange,
            QEvent.Type.StyleChange,
        ):
            self._queue_table_refresh()
        return False

    def _queue_table_refresh(self) -> None:
        if self._app is not None and not self._refresh_pending:
            self._refresh_pending = True
            QTimer.singleShot(0, self._refresh_tables)

    def _refresh_tables(self) -> None:
        """Adjust default rows, including tables created after installation."""
        self._refresh_pending = False
        if self._app is None:
            return
        for widget in self._app.allWidgets():
            if not isinstance(widget, QTableView):
                continue
            row_height = max(24, QFontMetrics(widget.font()).height() + scaled_px(10))
            header = widget.verticalHeader()
            header.setMinimumSectionSize(row_height)
            header.setDefaultSectionSize(row_height)


_manager: _TypographyManager | None = None


def typography_manager() -> _TypographyManager:
    global _manager
    if _manager is not None:
        try:
            _manager.objectName()
        except RuntimeError:
            _manager = None
    if _manager is None:
        _manager = _TypographyManager()
    return _manager
