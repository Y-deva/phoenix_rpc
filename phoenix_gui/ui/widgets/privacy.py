"""Global privacy mode for blurring financial statistics."""

from __future__ import annotations

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import QGraphicsBlurEffect, QWidget

from ...settings import Settings


class PrivacyManager(QObject):
    """Blur registered widgets when privacy mode is active.

    The manager owns one blur effect per registered widget. Widgets are kept
    alive by their page, so a plain dictionary is sufficient and avoids the
    overhead of a Qt object registry on every refresh.
    """

    changed = pyqtSignal(bool)

    def __init__(self, settings: Settings, parent: QObject | None = None) -> None:
        """Create the manager and restore the persisted privacy state."""
        super().__init__(parent)
        self._settings = settings
        self._hidden = bool(settings.get("privacy/hidden", False))
        self._widgets: dict[int, tuple[QWidget, float]] = {}
        self._effects: dict[int, QGraphicsBlurEffect] = {}

    @property
    def hidden(self) -> bool:
        """Return whether statistics are currently hidden."""
        return self._hidden

    def set_hidden(self, hidden: bool) -> None:
        """Persist and apply a new privacy state."""
        hidden = bool(hidden)
        if hidden == self._hidden:
            return
        self._hidden = hidden
        self._settings.set("privacy/hidden", hidden)
        self._apply_all()
        self.changed.emit(hidden)

    def toggle(self) -> None:
        """Flip privacy mode."""
        self.set_hidden(not self._hidden)

    def register(self, *widgets: QWidget, radius: float = 9.0) -> None:
        """Mark widgets as sensitive and blur them if mode is active."""
        for widget in widgets:
            if widget is None:
                continue
            key = id(widget)
            self._widgets[key] = (widget, float(radius))
            self._apply_widget(key)

    def _apply_all(self) -> None:
        """Apply the current state to every registered widget."""
        for key in list(self._widgets):
            self._apply_widget(key)

    def _apply_widget(self, key: int) -> None:
        """Apply or clear the blur effect for one widget."""
        entry = self._widgets.get(key)
        if entry is None:
            return
        widget, radius = entry
        try:
            if self._hidden:
                if key in self._effects:
                    return
                effect = QGraphicsBlurEffect(widget)
                effect.setBlurRadius(radius)
                effect.setBlurHints(QGraphicsBlurEffect.BlurHint.PerformanceHint)
                widget.setGraphicsEffect(effect)
                self._effects[key] = effect
            else:
                effect = self._effects.pop(key, None)
                if effect is not None:
                    if widget.graphicsEffect() is effect:
                        widget.setGraphicsEffect(None)
                    effect.deleteLater()
        except RuntimeError:
            # The page was destroyed while the application is shutting down.
            self._widgets.pop(key, None)
            self._effects.pop(key, None)

    def unregister(self, *widgets: QWidget) -> None:
        """Remove widgets from privacy tracking."""
        for widget in widgets:
            key = id(widget)
            effect = self._effects.pop(key, None)
            if effect is not None:
                try:
                    if widget.graphicsEffect() is effect:
                        widget.setGraphicsEffect(None)
                    effect.deleteLater()
                except RuntimeError:
                    pass
            self._widgets.pop(key, None)
