"""Appearance staging, custom palettes and motion integration tests."""

from __future__ import annotations

import json
from PyQt6.QtCore import QEvent, QPoint, QPointF, Qt
from PyQt6.QtGui import QWheelEvent
from PyQt6.QtWidgets import QApplication

from phoenix_gui.ui.widgets.chart import MplCanvas
from phoenix_gui.ui.widgets.theme import (
    THEME_ORDER,
    THEMES,
    contrast_ratio,
    customize_theme,
)


def test_custom_theme_derives_coherent_tokens():
    """Custom seed colors keep readable text and honour the sidebar color."""
    custom = customize_theme(
        THEMES["phoenix"],
        {
            "bg": "#101820",
            "sidebar": "#182430",
            "surface": "#1b2733",
            "accent": "#00aa88",
            "text": "#f3f6fb",
        },
    )
    assert custom.tokens["sidebar"] == "#182430"
    assert custom.tokens["accent"] == "#00aa88"
    assert contrast_ratio(custom.color("text"), custom.color("bg")) >= 4.5
    assert custom.tokens["accent_text"] in ("#FFFFFF", "#121212")
    assert custom.name.endswith("(своя)")


def test_appearance_requires_apply_and_persists(window, qtbot):
    """Theme, colors and motion are staged until the Apply button is used."""
    window.navigate("settings")
    page = window._pages["settings"]
    original = window.settings.theme
    page.theme_combo.setCurrentIndex(1)
    assert window.settings.theme == original
    assert page.apply_button.isEnabled()
    page._draft_custom = {"accent": "#00AA88"}
    page._refresh_color_buttons()
    page._mark_appearance_dirty()
    page.apply_button.click()
    qtbot.wait(250)
    assert window.settings.theme == THEME_ORDER[1]
    assert window.themes.theme.key == THEME_ORDER[1]
    assert window.themes.tokens["accent"].lower() == "#00aa88"
    assert window.settings.custom_colors == {"accent": "#00AA88"}
    assert page.apply_button.isEnabled() is False


def test_custom_colors_persist_in_settings(window, qtbot):
    """Stored custom colors survive a new ThemeManager instance."""
    window.settings.set("appearance/custom_colors", json.dumps({"bg": "#101820"}))
    window.themes.apply()
    assert window.themes.tokens["bg"].lower() == "#101820"


def test_hover_animation_uses_opacity_effect(window, qtbot):
    """Enabled motion fades controls in and out on hover."""
    window.settings.set("appearance/animations", True)
    window.settings.set("appearance/hover_effects", True)
    button = window.refresh_button
    QApplication.sendEvent(button, QEvent(QEvent.Type.Enter))
    qtbot.wait(60)
    assert button.graphicsEffect() is not None
    QApplication.sendEvent(button, QEvent(QEvent.Type.Leave))
    qtbot.wait(350)
    assert button.graphicsEffect() is None


def test_page_transition_runs_and_cleans_effect(window, qtbot):
    """Page switching fades the incoming page and removes the effect."""
    window.settings.set("appearance/animations", True)
    window.settings.set("appearance/page_transitions", True)
    window.navigate("analytics")
    page = window.current_page
    assert page.graphicsEffect() is not None
    qtbot.waitUntil(lambda: page.graphicsEffect() is None, timeout=2500)


def test_mouse_wheel_over_chart_scrolls_page(window, qtbot):
    """Wheel gestures over matplotlib move the surrounding page."""
    window.navigate("analytics")
    page = window.current_page
    qtbot.waitUntil(lambda: not page._refreshing, timeout=6000)
    bar = page.scroll.verticalScrollBar()
    bar.setValue(0)
    panel = page.findChild(MplCanvas)
    assert panel is not None
    event = QWheelEvent(
        QPointF(40, 40),
        QPointF(40, 40),
        QPoint(0, 0),
        QPoint(0, -120),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.NoScrollPhase,
        False,
    )
    QApplication.sendEvent(panel, event)
    qtbot.wait(80)
    assert bar.value() > 0


def test_logo_asset_is_used(window):
    """The sidebar brand uses the supplied logo image."""
    assert not window.brand_label.pixmap().isNull()
    assert window.brand_label.pixmap().width() >= 30


def test_theme_switch_discards_custom_palette(window):
    """Cycling a preset theme clears the previous custom palette."""
    window.settings.set_custom_colors({"accent": "#00AA88"})
    window.themes.apply()
    assert window.themes.tokens["accent"].lower() == "#00aa88"
    window.themes.cycle()
    assert window.settings.custom_colors == {}
    assert window.themes.tokens["accent"].lower() != "#00aa88"
