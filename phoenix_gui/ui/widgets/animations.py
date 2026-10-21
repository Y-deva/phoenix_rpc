"""Small, opt-out motion helpers for the interface.

Qt stylesheets cannot animate state changes, so hover feedback and page
transitions use short opacity animations. All durations are derived from
the user's animation speed and the master animation switch.
"""

from __future__ import annotations

from typing import Any

from PyQt6.QtCore import (
    QEasingCurve,
    QEvent,
    QObject,
    QPropertyAnimation,
    Qt,
)
from PyQt6.QtWidgets import (
    QAbstractButton,
    QApplication,
    QGraphicsOpacityEffect,
    QWidget,
)

from ...settings import Settings


class Motion(QObject):
    """Own the application-wide hover filter and transition helpers."""

    def __init__(self, settings: Settings, parent: QObject | None = None) -> None:
        """Install hover tracking on the running application."""
        super().__init__(parent)
        self._settings = settings
        self._app = QApplication.instance()
        self._animations: dict[int, QPropertyAnimation] = {}
        self._effects: dict[int, QGraphicsOpacityEffect] = {}
        self._hovered: set[int] = set()
        self._enabled = False
        self._hover_enabled = False
        self._transitions_enabled = False
        self._speed = 100
        self._refresh_flags()
        settings.changed.connect(self._on_setting_changed)
        if self._app is not None:
            self._app.installEventFilter(self)

    @property
    def enabled(self) -> bool:
        """Return whether any interface motion is enabled."""
        return self._enabled

    @property
    def hover_enabled(self) -> bool:
        """Return whether hover feedback is enabled."""
        return self._enabled and self._hover_enabled

    @property
    def transitions_enabled(self) -> bool:
        """Return whether page transitions are enabled."""
        return self._enabled and self._transitions_enabled

    def duration(self, base_ms: int) -> int:
        """Scale a nominal duration by the configured animation speed."""
        return max(1, round(base_ms * 100 / self._speed))

    def shutdown(self) -> None:
        """Detach the application event filter and stop pending motion."""
        if self._app is not None:
            self._app.removeEventFilter(self)
            self._app = None
        for animation in list(self._animations.values()):
            animation.stop()
            animation.deleteLater()
        self._animations.clear()
        self._effects.clear()
        self._hovered.clear()

    def fade_in(self, widget: QWidget, base_ms: int = 180) -> None:
        """Fade a widget in without leaving a permanent graphics effect."""
        if not self.enabled:
            return
        self._animate(widget, 0.0, 1.0, self.duration(base_ms), remove=True)

    def page_in(self, widget: QWidget) -> None:
        """Run the short page-change transition."""
        if not self.transitions_enabled:
            return
        self._animate(widget, 0.35, 1.0, self.duration(190), remove=True)

    def _animate(
        self,
        widget: QWidget,
        start: float,
        end: float,
        duration: int,
        remove: bool,
    ) -> None:
        """Animate a widget's opacity, replacing any previous animation."""
        if widget.graphicsEffect() is not None:
            effect = self._effects.get(id(widget))
            if effect is None:
                return
        else:
            effect = QGraphicsOpacityEffect(widget)
            effect.setOpacity(start)
            widget.setGraphicsEffect(effect)
            self._effects[id(widget)] = effect
        effect.setOpacity(start)
        animation = QPropertyAnimation(effect, b"opacity", widget)
        animation.setDuration(duration)
        animation.setStartValue(start)
        animation.setEndValue(end)
        animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        previous = self._animations.get(id(widget))
        if previous is not None:
            previous.stop()
            previous.deleteLater()
        self._animations[id(widget)] = animation

        def finished() -> None:
            """Drop the effect once the animation has fully finished."""
            if remove and id(widget) not in self._hovered:
                self._drop_effect(widget)
            self._animations.pop(id(widget), None)

        animation.finished.connect(finished)
        animation.start()

    def _drop_effect(self, widget: QWidget) -> None:
        """Remove our opacity effect, keeping foreign effects untouched."""
        effect = self._effects.pop(id(widget), None)
        if effect is None:
            return
        if widget.graphicsEffect() is effect:
            widget.setGraphicsEffect(None)

    def _refresh_flags(self) -> None:
        """Read the motion switches once, not on every application event."""
        try:
            self._enabled = bool(self._settings.animations)
            self._hover_enabled = bool(self._settings.hover_effects)
            self._transitions_enabled = bool(self._settings.page_transitions)
            self._speed = max(50, min(200, self._settings.animation_speed))
        except RuntimeError:
            self._enabled = False
            self._hover_enabled = False
            self._transitions_enabled = False
            self._speed = 100

    def _on_setting_changed(self, key: str, value: object) -> None:
        """Refresh flags after appearance settings are applied."""
        if key in {
            "appearance/animations",
            "appearance/hover_effects",
            "appearance/page_transitions",
            "appearance/animation_speed",
            "appearance/batch",
        }:
            self._refresh_flags()
            if not self.hover_enabled:
                self._hovered.clear()

    def eventFilter(self, obj: Any, event: QEvent) -> bool:  # noqa: N802
        """Animate hover feedback for buttons and clickable cards."""
        if not self.hover_enabled or not isinstance(obj, QWidget):
            return False
        event_type = event.type()
        if event_type not in (QEvent.Type.Enter, QEvent.Type.Leave):
            return False
        clickable = isinstance(obj, QAbstractButton) or bool(obj.property("hoverable"))
        if not clickable or not obj.isEnabled() or not obj.isVisible():
            return False
        if event_type == QEvent.Type.Enter:
            self._hovered.add(id(obj))
            if obj.cursor().shape() == Qt.CursorShape.ArrowCursor:
                obj.setCursor(Qt.CursorShape.PointingHandCursor)
            self._animate(obj, 1.0, 0.88, self.duration(120), remove=False)
        else:
            self._hovered.discard(id(obj))
            self._animate(obj, 0.88, 1.0, self.duration(150), remove=True)
        return False
