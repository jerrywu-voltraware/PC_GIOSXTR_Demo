import os


def _qapp():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    app.setOrganizationName("GIOSXTR")
    app.setApplicationName("PC GIOSXTR Demo Test")
    return app


def test_apply_light_theme_forces_qt_light_scheme_and_palette():
    from PyQt6.QtCore import Qt
    from PyQt6.QtGui import QColor, QPalette

    from app.theme import apply_light_theme, theme_manager, THEME_LIGHT

    app = _qapp()
    app.styleHints().setColorScheme(Qt.ColorScheme.Dark)
    dark_palette = app.palette()
    dark_palette.setColor(QPalette.ColorRole.Window, QColor("#101010"))
    dark_palette.setColor(QPalette.ColorRole.WindowText, QColor("#F0F0F0"))
    dark_palette.setColor(QPalette.ColorRole.Base, QColor("#151515"))
    app.setPalette(dark_palette)
    app.setStyleSheet("")

    theme_manager().set_theme(THEME_LIGHT, persist=False)
    apply_light_theme(app)
    theme_manager().set_theme(THEME_LIGHT, persist=False)

    palette = app.palette()
    assert palette.color(QPalette.ColorRole.Window).lightness() > 220
    assert palette.color(QPalette.ColorRole.Base).lightness() > 240
    assert palette.color(QPalette.ColorRole.WindowText).lightness() < 80
    assert "QToolTip" in app.styleSheet()


def test_set_theme_dark_switches_palette_to_dark():
    from PyQt6.QtGui import QPalette

    from app.theme import apply_light_theme, theme_manager, THEME_DARK, THEME_LIGHT

    app = _qapp()
    apply_light_theme(app)
    theme_manager().set_theme(THEME_LIGHT, persist=False)

    theme_manager().set_theme(THEME_DARK, persist=False)
    palette = app.palette()
    assert palette.color(QPalette.ColorRole.Window).lightness() < 80
    assert palette.color(QPalette.ColorRole.WindowText).lightness() > 200
    assert theme_manager().name() == THEME_DARK

    theme_manager().set_theme(THEME_LIGHT, persist=False)
    palette = app.palette()
    assert palette.color(QPalette.ColorRole.Window).lightness() > 220
    assert theme_manager().name() == THEME_LIGHT


def test_theme_changed_signal_fires_only_on_change():
    from app.theme import apply_light_theme, theme_manager, THEME_DARK, THEME_LIGHT

    app = _qapp()
    apply_light_theme(app)
    theme_manager().set_theme(THEME_LIGHT, persist=False)

    received: list[str] = []
    theme_manager().theme_changed.connect(lambda tokens: received.append(tokens.name))

    theme_manager().set_theme(THEME_LIGHT, persist=False)  # no change
    assert received == []

    theme_manager().set_theme(THEME_DARK, persist=False)
    assert received == [THEME_DARK]

    theme_manager().set_theme(THEME_DARK, persist=False)  # no change
    assert received == [THEME_DARK]

    theme_manager().set_theme(THEME_LIGHT, persist=False)  # restore
