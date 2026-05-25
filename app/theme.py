"""Global Qt theme configuration."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QPalette
from PyQt6.QtWidgets import QApplication, QStyleFactory


_LIGHT_STYLE_SHEET = """
QWidget {
    selection-background-color: #DDF7F4;
    selection-color: #102A33;
}
QMainWindow, QDialog, QMessageBox {
    background-color: #F7F9FB;
}
QToolTip {
    color: #172A31;
    background-color: #FFFFFF;
    border: 1px solid #C6D3D8;
}
QMenu, QMenuBar {
    background-color: #FFFFFF;
    color: #172A31;
}
QMenu::item:selected {
    background-color: #DDF7F4;
    color: #102A33;
}
QComboBox QAbstractItemView {
    background-color: #FFFFFF;
    color: #172A31;
    selection-background-color: #DDF7F4;
    selection-color: #102A33;
}
"""


def _light_palette() -> QPalette:
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor("#F7F9FB"))
    palette.setColor(QPalette.ColorRole.WindowText, QColor("#172A31"))
    palette.setColor(QPalette.ColorRole.Base, QColor("#FFFFFF"))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor("#F4F6F7"))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor("#FFFFFF"))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor("#172A31"))
    palette.setColor(QPalette.ColorRole.Text, QColor("#172A31"))
    palette.setColor(QPalette.ColorRole.Button, QColor("#FFFFFF"))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor("#172A31"))
    palette.setColor(QPalette.ColorRole.BrightText, QColor("#FFFFFF"))
    palette.setColor(QPalette.ColorRole.Link, QColor("#1F77B4"))
    palette.setColor(QPalette.ColorRole.Highlight, QColor("#DDF7F4"))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#102A33"))
    palette.setColor(QPalette.ColorRole.PlaceholderText, QColor("#8A9AA0"))
    palette.setColor(QPalette.ColorRole.Light, QColor("#FFFFFF"))
    palette.setColor(QPalette.ColorRole.Midlight, QColor("#E7EEF1"))
    palette.setColor(QPalette.ColorRole.Mid, QColor("#CEDBE0"))
    palette.setColor(QPalette.ColorRole.Dark, QColor("#8A9AA0"))
    palette.setColor(QPalette.ColorRole.Shadow, QColor("#A6B4BA"))

    disabled = QPalette.ColorGroup.Disabled
    palette.setColor(disabled, QPalette.ColorRole.WindowText, QColor("#8A9AA0"))
    palette.setColor(disabled, QPalette.ColorRole.Text, QColor("#AAB6BA"))
    palette.setColor(disabled, QPalette.ColorRole.ButtonText, QColor("#AAB6BA"))
    palette.setColor(disabled, QPalette.ColorRole.Base, QColor("#F6F8F9"))
    palette.setColor(disabled, QPalette.ColorRole.Button, QColor("#F6F8F9"))
    return palette


def apply_light_theme(app: QApplication) -> None:
    """Force the app to stay light regardless of the OS color mode."""
    style_hints = app.styleHints()
    if hasattr(style_hints, "setColorScheme"):
        style_hints.setColorScheme(Qt.ColorScheme.Light)

    fusion = QStyleFactory.create("Fusion")
    if fusion is not None:
        app.setStyle(fusion)

    app.setPalette(_light_palette())
    app.setStyleSheet(_LIGHT_STYLE_SHEET)
