import os


def test_apply_light_theme_forces_qt_light_scheme_and_palette():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtCore import Qt
    from PyQt6.QtGui import QColor, QPalette
    from PyQt6.QtWidgets import QApplication

    from app.theme import apply_light_theme

    app = QApplication.instance() or QApplication([])
    app.styleHints().setColorScheme(Qt.ColorScheme.Dark)
    dark_palette = app.palette()
    dark_palette.setColor(QPalette.ColorRole.Window, QColor("#101010"))
    dark_palette.setColor(QPalette.ColorRole.WindowText, QColor("#F0F0F0"))
    dark_palette.setColor(QPalette.ColorRole.Base, QColor("#151515"))
    app.setPalette(dark_palette)
    app.setStyleSheet("")

    apply_light_theme(app)

    palette = app.palette()
    assert palette.color(QPalette.ColorRole.Window).lightness() > 220
    assert palette.color(QPalette.ColorRole.Base).lightness() > 240
    assert palette.color(QPalette.ColorRole.WindowText).lightness() < 80
    assert "QToolTip" in app.styleSheet()
