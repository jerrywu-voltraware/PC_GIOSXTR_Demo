import os

import pytest


@pytest.fixture
def app_with_typography(tmp_path):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtCore import QSettings
    from PyQt6.QtWidgets import QApplication

    from app.theme import THEME_LIGHT, apply_theme
    from app.typography import typography_manager

    app = QApplication.instance() or QApplication([])
    previous_names = (app.organizationName(), app.applicationName())
    app.setOrganizationName("GIOSXTR Typography Tests")
    app.setApplicationName(tmp_path.name)
    QSettings().clear()
    apply_theme(app, THEME_LIGHT)
    typography_manager().set_scale(100, persist=False)
    yield app
    typography_manager().set_scale(100, persist=False)
    app.processEvents()
    QSettings().clear()
    app.setOrganizationName(previous_names[0])
    app.setApplicationName(previous_names[1])


def test_default_font_uses_readable_points_and_scales_live(app_with_typography):
    from PyQt6.QtWidgets import QLabel

    from app.typography import typography_manager

    app = app_with_typography
    label = QLabel("錄製中 · 48.25 V")
    label.show()
    app.processEvents()
    assert app.font().pointSizeF() == 11
    assert app.font().pixelSize() == -1
    initial_height = label.fontMetrics().height()

    typography_manager().set_scale(150, persist=False)
    app.processEvents()
    assert label.font().pointSizeF() == 16.5
    assert label.fontMetrics().height() > initial_height
    label.close()


def test_scaled_qss_supports_fractional_point_sizes(app_with_typography):
    from PyQt6.QtWidgets import QLabel

    from app.typography import font_size, typography_manager

    typography_manager().set_scale(125, persist=False)
    label = QLabel("字級預覽")
    label.setStyleSheet(f"font-size: {font_size(13)};")
    label.ensurePolished()
    assert label.font().pointSizeF() == pytest.approx(16.25)


def test_scale_is_saved_and_loaded_by_a_new_manager(app_with_typography):
    from PyQt6.QtCore import QSettings

    from app.typography import (
        UI_SCALE_SETTINGS_KEY,
        _TypographyManager,
        typography_manager,
    )

    typography_manager().set_scale(175)
    assert QSettings().value(UI_SCALE_SETTINGS_KEY, type=int) == 175
    restarted = _TypographyManager()
    restarted.install(app_with_typography)
    assert restarted.scale() == 175
    assert app_with_typography.font().pointSizeF() == 19.25
    app_with_typography.removeEventFilter(restarted)


@pytest.mark.parametrize("stored", ["bad", "150.5", 0, -1, 999, None])
def test_invalid_saved_scale_falls_back_to_default(app_with_typography, stored):
    from PyQt6.QtCore import QSettings

    from app.typography import UI_SCALE_SETTINGS_KEY, load_saved_scale

    QSettings().setValue(UI_SCALE_SETTINGS_KEY, stored)
    assert load_saved_scale() == 100


def test_existing_and_new_table_rows_fit_scaled_text(app_with_typography):
    from PyQt6.QtWidgets import QTableWidget, QTableWidgetItem

    from app.typography import typography_manager

    app = app_with_typography
    table = QTableWidget(1, 1)
    table.setItem(0, 0, QTableWidgetItem("2026-10-13 12:34:56"))
    table.show()
    app.processEvents()
    initial_height = table.rowHeight(0)

    typography_manager().set_scale(200, persist=False)
    app.processEvents()
    assert table.rowHeight(0) > initial_height
    assert table.rowHeight(0) >= table.fontMetrics().height() + 10

    later_table = QTableWidget(1, 1)
    later_table.show()
    app.processEvents()
    assert later_table.rowHeight(0) >= later_table.fontMetrics().height() + 10

    typography_manager().set_scale(100, persist=False)
    app.processEvents()
    assert table.rowHeight(0) == initial_height
    table.close()
    later_table.close()


def test_appearance_selector_applies_and_syncs_without_restarting(app_with_typography):
    from PyQt6.QtCore import QSettings
    from PyQt6.QtWidgets import QScrollArea

    from app.typography import UI_SCALE_SETTINGS_KEY, typography_manager
    from app.windows.settings_dialog import SettingsDialog

    app = app_with_typography
    dialog = SettingsDialog(engineering_mode=False)
    dialog.tabs.setCurrentIndex(1)
    dialog.show()
    dialog.text_scale_combo.setCurrentIndex(dialog.text_scale_combo.findData(200))
    app.processEvents()
    assert app.font().pointSizeF() == 22
    assert dialog.text_scale_preview.font().pointSizeF() == 22
    assert QSettings().value(UI_SCALE_SETTINGS_KEY, type=int) == 200
    assert all(isinstance(dialog.tabs.widget(i), QScrollArea) for i in range(dialog.tabs.count()))

    typography_manager().set_scale(125, persist=False)
    assert dialog.text_scale_combo.currentData() == 125
    dialog.close()


def test_reapplying_theme_preserves_active_scale(app_with_typography):
    from app.theme import THEME_DARK, apply_theme, theme_manager
    from app.typography import typography_manager

    manager = typography_manager()
    manager.set_scale(150, persist=False)
    observed = []

    def record_refresh(tokens):
        observed.append(tokens.name)

    theme_manager().theme_changed.connect(record_refresh)
    try:
        manager.set_scale(175, persist=False)
        assert observed
        apply_theme(app_with_typography, THEME_DARK)
        assert manager.scale() == 175
        assert app_with_typography.font().pointSizeF() == 19.25
    finally:
        theme_manager().theme_changed.disconnect(record_refresh)
