"""Global Qt theme configuration with light/dark mode support."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from PyQt6.QtCore import QObject, Qt, QSettings, pyqtSignal
from PyQt6.QtGui import QColor, QPalette
from PyQt6.QtWidgets import QApplication, QStyleFactory


THEME_LIGHT = "light"
THEME_DARK = "dark"
_SETTINGS_KEY = "appearance/theme"


@dataclass(frozen=True)
class ThemeTokens:
    """Semantic color tokens that pages reference instead of raw hex strings."""

    name: str
    # Surfaces
    window_bg: str
    surface: str
    surface_alt: str
    surface_subtle: str
    panel_bg: str
    panel_border: str
    card_bg: str
    card_border: str
    # Text
    text_primary: str
    text_secondary: str
    text_muted: str
    text_inverse: str
    # Accents
    accent: str
    accent_soft: str
    accent_text: str
    link: str
    # Borders / dividers
    border: str
    divider: str
    # Status
    error_bg: str
    error_border: str
    error_fg: str
    error_badge_bg: str
    ok_bg: str
    ok_border: str
    ok_fg: str
    ok_badge_bg: str
    warning: str
    # Tables
    table_bg: str
    table_alt: str
    table_header_bg: str
    table_grid: str
    table_highlight_bg: str
    table_highlight_fg: str
    # Buttons (scan_panel uses a styled primary button)
    button_primary_bg: str
    button_primary_hover: str
    button_primary_border: str
    button_primary_text: str
    button_secondary_bg: str
    button_secondary_hover: str
    button_secondary_border: str
    button_secondary_text: str
    button_disabled_bg: str
    button_disabled_text: str
    # Waveform plot
    plot_bg: str
    plot_axis: str
    plot_axis_text: str
    plot_legend_pen: str
    # Demo2 specific
    demo_pct_text: str
    demo_status_text: str
    demo_detail_text: str
    demo_device_text: str
    demo_filler_text: str
    demo_eng_selected_bg: str
    demo_eng_selected_text: str
    demo_eng_unselected_bg: str
    demo_eng_unselected_text: str
    demo_eng_border: str


_LIGHT = ThemeTokens(
    name=THEME_LIGHT,
    window_bg="#F7F9FB",
    surface="#FFFFFF",
    surface_alt="#F4F6F7",
    surface_subtle="#FBFCFD",
    panel_bg="#FFFFFF",
    panel_border="#E8F1EF",
    card_bg="#FFFFFF",
    card_border="#DDE7EA",
    text_primary="#172A31",
    text_secondary="#40545B",
    text_muted="#66757C",
    text_inverse="#FFFFFF",
    accent="#1F77B4",
    accent_soft="#DDF7F4",
    accent_text="#102A33",
    link="#1F77B4",
    border="#CEDBE0",
    divider="#D6E0E4",
    error_bg="#FDECEA",
    error_border="#E79D97",
    error_fg="#A93226",
    error_badge_bg="#C0392B",
    ok_bg="#E8F8F0",
    ok_border="#9AD7B4",
    ok_fg="#166534",
    ok_badge_bg="#1E8449",
    warning="#E67E22",
    table_bg="#FFFFFF",
    table_alt="#F6F8F9",
    table_header_bg="#EDF3F5",
    table_grid="#D6E0E4",
    table_highlight_bg="#FADBD8",
    table_highlight_fg="#A93226",
    button_primary_bg="#4F6F7B",
    button_primary_hover="#45636E",
    button_primary_border="#425F6A",
    button_primary_text="#FFFFFF",
    button_secondary_bg="#FFFFFF",
    button_secondary_hover="#EDF4F6",
    button_secondary_border="#CEDBE0",
    button_secondary_text="#243B43",
    button_disabled_bg="#F6F8F9",
    button_disabled_text="#AAB6BA",
    plot_bg="#081015",
    plot_axis="#8EA2AD",
    plot_axis_text="#B9C7CE",
    plot_legend_pen="#425866",
    demo_pct_text="#202124",
    demo_status_text="#4C5A5D",
    demo_detail_text="#78909C",
    demo_device_text="#546E7A",
    demo_filler_text="#D6E6E8",
    demo_eng_selected_bg="#546E7A",
    demo_eng_selected_text="#FFFFFF",
    demo_eng_unselected_bg="#FFFFFF",
    demo_eng_unselected_text="#37474F",
    demo_eng_border="#CFD8DC",
)


_DARK = ThemeTokens(
    name=THEME_DARK,
    window_bg="#1B1F22",
    surface="#23282C",
    surface_alt="#2A3035",
    surface_subtle="#1F2326",
    panel_bg="#262C30",
    panel_border="#363D43",
    card_bg="#262C30",
    card_border="#363D43",
    text_primary="#E6EAEC",
    text_secondary="#B8C2C7",
    text_muted="#8A969C",
    text_inverse="#1B1F22",
    accent="#4FB3D9",
    accent_soft="#1F3D44",
    accent_text="#DDF7F4",
    link="#5BBCE0",
    border="#3A4248",
    divider="#323A40",
    error_bg="#3A1F1C",
    error_border="#7A3A33",
    error_fg="#F2867B",
    error_badge_bg="#C0392B",
    ok_bg="#1B3328",
    ok_border="#3F6E54",
    ok_fg="#7BD9A1",
    ok_badge_bg="#1E8449",
    warning="#F2A24A",
    table_bg="#23282C",
    table_alt="#262C30",
    table_header_bg="#2D343A",
    table_grid="#3A4248",
    table_highlight_bg="#4A2421",
    table_highlight_fg="#F2867B",
    button_primary_bg="#3F7287",
    button_primary_hover="#4A8298",
    button_primary_border="#5A95AA",
    button_primary_text="#FFFFFF",
    button_secondary_bg="#2A3035",
    button_secondary_hover="#343B41",
    button_secondary_border="#454D54",
    button_secondary_text="#E6EAEC",
    button_disabled_bg="#262B2F",
    button_disabled_text="#5C666B",
    plot_bg="#0B1217",
    plot_axis="#7C8E98",
    plot_axis_text="#A4B3BB",
    plot_legend_pen="#4A5862",
    demo_pct_text="#E6EAEC",
    demo_status_text="#B8C2C7",
    demo_detail_text="#8A969C",
    demo_device_text="#9FB0B6",
    demo_filler_text="#3A4248",
    demo_eng_selected_bg="#5A95AA",
    demo_eng_selected_text="#FFFFFF",
    demo_eng_unselected_bg="#2A3035",
    demo_eng_unselected_text="#E6EAEC",
    demo_eng_border="#454D54",
)


def _palette_for(tokens: ThemeTokens) -> QPalette:
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(tokens.window_bg))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(tokens.text_primary))
    palette.setColor(QPalette.ColorRole.Base, QColor(tokens.surface))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(tokens.surface_alt))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(tokens.surface))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor(tokens.text_primary))
    palette.setColor(QPalette.ColorRole.Text, QColor(tokens.text_primary))
    palette.setColor(QPalette.ColorRole.Button, QColor(tokens.surface))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(tokens.text_primary))
    palette.setColor(QPalette.ColorRole.BrightText, QColor(tokens.text_inverse))
    palette.setColor(QPalette.ColorRole.Link, QColor(tokens.link))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(tokens.accent_soft))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor(tokens.accent_text))
    palette.setColor(QPalette.ColorRole.PlaceholderText, QColor(tokens.text_muted))
    palette.setColor(QPalette.ColorRole.Light, QColor(tokens.surface))
    palette.setColor(QPalette.ColorRole.Midlight, QColor(tokens.surface_alt))
    palette.setColor(QPalette.ColorRole.Mid, QColor(tokens.border))
    palette.setColor(QPalette.ColorRole.Dark, QColor(tokens.text_muted))
    palette.setColor(QPalette.ColorRole.Shadow, QColor(tokens.border))

    disabled = QPalette.ColorGroup.Disabled
    palette.setColor(disabled, QPalette.ColorRole.WindowText, QColor(tokens.text_muted))
    palette.setColor(disabled, QPalette.ColorRole.Text, QColor(tokens.button_disabled_text))
    palette.setColor(disabled, QPalette.ColorRole.ButtonText, QColor(tokens.button_disabled_text))
    palette.setColor(disabled, QPalette.ColorRole.Base, QColor(tokens.button_disabled_bg))
    palette.setColor(disabled, QPalette.ColorRole.Button, QColor(tokens.button_disabled_bg))
    return palette


def _style_sheet_for(tokens: ThemeTokens) -> str:
    return f"""
QWidget {{
    selection-background-color: {tokens.accent_soft};
    selection-color: {tokens.accent_text};
}}
QMainWindow, QDialog, QMessageBox {{
    background-color: {tokens.window_bg};
}}
QToolTip {{
    color: {tokens.text_primary};
    background-color: {tokens.surface};
    border: 1px solid {tokens.border};
}}
QMenu, QMenuBar {{
    background-color: {tokens.surface};
    color: {tokens.text_primary};
}}
QMenu::item:selected {{
    background-color: {tokens.accent_soft};
    color: {tokens.accent_text};
}}
QComboBox QAbstractItemView {{
    background-color: {tokens.surface};
    color: {tokens.text_primary};
    selection-background-color: {tokens.accent_soft};
    selection-color: {tokens.accent_text};
}}
QTabBar::tab {{
    background: {tokens.surface_alt};
    color: {tokens.text_secondary};
    padding: 6px 12px;
    border: 1px solid {tokens.border};
    border-bottom: none;
}}
QTabBar::tab:selected {{
    background: {tokens.surface};
    color: {tokens.text_primary};
}}
QTabWidget::pane {{
    border: 1px solid {tokens.border};
    background: {tokens.window_bg};
}}
"""


class _ThemeManager(QObject):
    """Holds the active theme and broadcasts changes."""

    theme_changed = pyqtSignal(object)  # emits ThemeTokens

    def __init__(self) -> None:
        super().__init__()
        self._tokens: ThemeTokens = _LIGHT
        self._app: QApplication | None = None

    def install(self, app: QApplication, theme_name: str | None = None) -> None:
        """Apply the chosen theme to the app and remember the QApplication."""
        self._app = app
        fusion = QStyleFactory.create("Fusion")
        if fusion is not None:
            app.setStyle(fusion)
        if theme_name is None:
            theme_name = load_saved_theme()
        self.set_theme(theme_name, persist=False)

    def current(self) -> ThemeTokens:
        return self._tokens

    def name(self) -> str:
        return self._tokens.name

    def set_theme(self, theme_name: str, *, persist: bool = True) -> None:
        tokens = _DARK if theme_name == THEME_DARK else _LIGHT
        if self._app is not None:
            style_hints = self._app.styleHints()
            if hasattr(style_hints, "setColorScheme"):
                style_hints.setColorScheme(
                    Qt.ColorScheme.Dark if tokens.name == THEME_DARK else Qt.ColorScheme.Light
                )
            self._app.setPalette(_palette_for(tokens))
            self._app.setStyleSheet(_style_sheet_for(tokens))
        changed = tokens.name != self._tokens.name
        self._tokens = tokens
        if persist:
            save_theme(tokens.name)
        if changed:
            self.theme_changed.emit(tokens)


_manager: _ThemeManager | None = None


def _manager_is_alive(manager: _ThemeManager) -> bool:
    try:
        manager.objectName()
    except RuntimeError:
        return False
    return True


def theme_manager() -> _ThemeManager:
    """Return the singleton ThemeManager, recreating it if its C++ side died.

    Recreated lazily because _ThemeManager is a QObject; in test runs that
    teardown and recreate QApplication, the underlying C++ object can be
    deleted while the Python wrapper still exists.
    """
    global _manager
    if _manager is None or not _manager_is_alive(_manager):
        _manager = _ThemeManager()
    return _manager


def current_tokens() -> ThemeTokens:
    return theme_manager().current()


def load_saved_theme() -> str:
    settings = QSettings()
    value = settings.value(_SETTINGS_KEY, THEME_LIGHT)
    return THEME_DARK if str(value) == THEME_DARK else THEME_LIGHT


def save_theme(name: str) -> None:
    settings = QSettings()
    settings.setValue(_SETTINGS_KEY, THEME_DARK if name == THEME_DARK else THEME_LIGHT)


def apply_light_theme(app: QApplication) -> None:
    """Backwards-compatible entry point used at startup."""
    theme_manager().install(app, theme_name=load_saved_theme())


def apply_theme(app: QApplication, theme_name: str) -> None:
    theme_manager().install(app, theme_name=theme_name)


def on_theme_changed(callback: Callable[[ThemeTokens], None]) -> None:
    """Convenience helper for widgets to subscribe to theme changes."""
    theme_manager().theme_changed.connect(callback)
