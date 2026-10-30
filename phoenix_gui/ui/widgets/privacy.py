"""Privacy plaques that hide financial values without blurring the layout."""

from __future__ import annotations

import math
from typing import Any, Iterable

from PyQt6.QtCore import QEvent, QObject, QRectF, QTimer, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import (
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTableWidget,
    QWidget,
)

from ...settings import Settings

_FALLBACK_TOKENS = {
    "surface_alt": "#161E2A",
    "border": "#2A3446",
    "accent": "#FF8A3D",
}


def _tokens(theme_manager: Any | None) -> dict[str, str]:
    """Read theme tokens defensively so privacy also works in isolated tests."""
    tokens = getattr(theme_manager, "tokens", None)
    if isinstance(tokens, dict):
        return {**_FALLBACK_TOKENS, **tokens}
    return dict(_FALLBACK_TOKENS)


def _paint_plaque(
    painter: QPainter,
    rect: QRectF,
    phase: float,
    tokens: dict[str, str],
) -> None:
    """Paint one opaque rounded plaque with slow moving particles."""
    if rect.width() < 4 or rect.height() < 4:
        return
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    radius = min(8.0, rect.height() / 2.0, rect.width() / 2.0)
    path = QPainterPath()
    path.addRoundedRect(rect, radius, radius)
    painter.fillPath(path, QColor(tokens.get("surface_alt", "#161E2A")))
    painter.setPen(QPen(QColor(tokens.get("border", "#2A3446")), 1))
    painter.drawPath(path)
    painter.setClipPath(path)

    # Particles drift upward. Their count and positions are independent of the
    # hidden value, so the number of digits cannot be inferred from the plaque.
    accent = QColor(tokens.get("accent", "#FF8A3D"))
    muted = QColor(tokens.get("muted", "#778199"))

    # A static dot grid gives large chart covers a deliberate texture.
    if rect.width() > 220 and rect.height() > 90:
        columns, rows = 5, 3
        for row in range(rows):
            for column in range(columns):
                gx = rect.x() + (column + 0.5) / columns * rect.width()
                gy = rect.y() + (row + 0.5) / rows * rect.height()
                gx += math.sin(phase * 0.22 + row * 1.7 + column) * 2.0
                gy += math.cos(phase * 0.18 + column * 1.4 + row) * 2.0
                color = QColor(muted)
                color.setAlpha(34 + (row + column) % 3 * 8)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(color)
                painter.drawEllipse(QRectF(gx, gy, 2.4, 2.4))

    count = max(8, min(22, int(rect.width() / 34) + 6))
    for index in range(count):
        base_x = ((index * 0.173 + 0.11) % 1.0) * rect.width()
        speed = 0.35 + (index % 4) * 0.11
        y = (rect.height() + 8) - ((phase * speed + index * 9.7) % (rect.height() + 16))
        x = rect.x() + base_x + math.sin(phase * 0.35 + index) * 3.0
        size = 1.8 + (index % 4) * 1.0
        color = QColor(accent)
        color.setAlpha(105 + (index % 5) * 18)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        painter.drawEllipse(QRectF(x, rect.y() + y, size, size))

    # Soft bokeh blobs make the plaque read as a deliberate cover instead of
    # an empty loading skeleton, without ever exposing the hidden text.
    if rect.width() > 220 and rect.height() > 90:
        for index in range(3):
            radius = 4.5 + (index % 2) * 2.5
            x = rect.x() + ((0.23 + index * 0.29) % 1.0) * rect.width()
            y = rect.y() + (
                (0.5 + 0.23 * math.sin(phase * 0.28 + index * 2.1)) * rect.height()
            )
            color = QColor(accent)
            color.setAlpha(14 + index * 4)
            painter.setBrush(color)
            painter.drawEllipse(QRectF(x - radius, y - radius, radius * 2, radius * 2))
    painter.restore()


class PrivacyCover(QWidget):
    """Opaque particle plaque placed over one sensitive widget."""

    def __init__(
        self,
        target: QWidget,
        theme_manager: Any | None = None,
    ) -> None:
        """Create a cover that tracks the target widget geometry."""
        super().__init__(target)
        self.setObjectName("PrivacyCover")
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._tokens = _tokens(theme_manager)
        self._phase = 0.0
        self.setGeometry(target.rect())
        target.installEventFilter(self)
        self.raise_()
        self.hide()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802
        """Keep the overlay aligned with its parent widget."""
        if event.type() in (QEvent.Type.Resize, QEvent.Type.Show):
            self.setGeometry(self.parentWidget().rect())
            self.raise_()
        return False

    def set_theme(self, theme_manager: Any | None) -> None:
        """Refresh colors after a theme change."""
        self._tokens = _tokens(theme_manager)
        self.update()

    def advance(self, phase: float) -> None:
        """Animate particles without repainting hidden pages."""
        self._phase = phase
        if self.isVisible():
            self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt API
        """Draw the opaque particle plaque."""
        painter = QPainter(self)
        _paint_plaque(
            painter,
            QRectF(self.rect()).adjusted(1.0, 1.0, -1.0, -1.0),
            self._phase,
            self._tokens,
        )


class PrivacyCellDelegate(QStyledItemDelegate):
    """Replace amount cells with a particle plaque while privacy is active."""

    def __init__(
        self,
        table: QTableWidget,
        theme_manager: Any | None = None,
    ) -> None:
        """Create a delegate tied to one table viewport."""
        super().__init__(table)
        self._table = table
        self._tokens = _tokens(theme_manager)
        self._hidden = False
        self._phase = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(50)
        self._timer.timeout.connect(self._tick)

    @property
    def hidden(self) -> bool:
        """Return whether the delegate is currently covering values."""
        return self._hidden

    def set_hidden(self, hidden: bool) -> None:
        """Enable or disable the plaque and its animation."""
        self._hidden = bool(hidden)
        if self._hidden:
            self._timer.start()
        else:
            self._timer.stop()
        self._table.viewport().update()

    def set_theme(self, theme_manager: Any | None) -> None:
        """Refresh colors after a theme change."""
        self._tokens = _tokens(theme_manager)
        self._table.viewport().update()

    def _tick(self) -> None:
        """Advance the particle field."""
        self._phase += 0.05
        self._table.viewport().update()

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        index,
    ) -> None:
        """Paint normal content when visible and a plaque when hidden."""
        if not self._hidden:
            super().paint(painter, option, index)
            return
        painter.save()
        painter.fillRect(option.rect, option.palette.base())
        _paint_plaque(
            painter,
            QRectF(option.rect).adjusted(2.0, 4.0, -2.0, -4.0),
            self._phase,
            self._tokens,
        )
        painter.restore()


class PrivacyManager(QObject):
    """Coordinate privacy plaques for labels, charts and table amount columns."""

    changed = pyqtSignal(bool)

    def __init__(
        self,
        settings: Settings,
        themes: Any | None = None,
        parent: QObject | None = None,
    ) -> None:
        """Create the manager and apply the persisted privacy state."""
        super().__init__(parent)
        self._settings = settings
        self._themes = themes
        self._hidden = bool(settings.get("privacy/hidden", False))
        self._covers: dict[int, PrivacyCover] = {}
        self._tables: list[tuple[QTableWidget, PrivacyCellDelegate]] = []
        self._timer = QTimer(self)
        self._timer.setInterval(50)
        self._timer.timeout.connect(self._advance)
        self._phase = 0.0

    @property
    def hidden(self) -> bool:
        """Return whether financial values are currently covered."""
        return self._hidden

    def set_hidden(self, hidden: bool) -> None:
        """Persist and apply a new privacy state."""
        hidden = bool(hidden)
        if hidden == self._hidden:
            return
        self._hidden = hidden
        self._settings.set("privacy/hidden", hidden)
        self._prune_covers()
        for cover in self._covers.values():
            cover.setVisible(hidden)
        for _table, delegate in self._tables:
            delegate.set_hidden(hidden)
        self._update_timer()
        self.changed.emit(hidden)

    def toggle(self) -> None:
        """Flip privacy mode."""
        self.set_hidden(not self._hidden)

    def register(self, *widgets: QWidget, radius: float = 9.0) -> None:
        """Cover widgets with particle plaques when privacy is active."""
        del radius  # accepted for compatibility with older call sites
        self._prune_covers()
        for widget in widgets:
            if widget is None:
                continue
            key = id(widget)
            if key in self._covers:
                self._covers[key].setVisible(self._hidden)
                continue
            cover = PrivacyCover(widget, self._themes)
            cover.setVisible(self._hidden)
            self._covers[key] = cover
            cover.raise_()
        self._update_timer()

    def register_table(
        self,
        table: QTableWidget,
        columns: Iterable[int],
    ) -> None:
        """Cover only the amount columns of a table, keeping labels readable."""
        delegate = PrivacyCellDelegate(table, self._themes)
        for column in columns:
            if 0 <= int(column) < table.columnCount():
                table.setItemDelegateForColumn(int(column), delegate)
        delegate.set_hidden(self._hidden)
        self._tables.append((table, delegate))

    def refresh_theme(self) -> None:
        """Propagate theme colors to every active plaque."""
        self._prune_covers()
        for cover in self._covers.values():
            cover.set_theme(self._themes)
        for _table, delegate in self._tables:
            try:
                delegate.set_theme(self._themes)
            except RuntimeError:
                pass

    def is_covered(self, widget: QWidget) -> bool:
        """Return whether a widget has an active visible plaque."""
        cover = self._covers.get(id(widget))
        if cover is None:
            return False
        try:
            return bool(cover.isVisible())
        except RuntimeError:
            self._covers.pop(id(widget), None)
            return False

    def _update_timer(self) -> None:
        """Run the shared particle clock only while privacy is active."""
        active = self._hidden and (bool(self._covers) or bool(self._tables))
        if active and not self._timer.isActive():
            self._timer.start()
        elif not active:
            self._timer.stop()

    def _prune_covers(self) -> None:
        """Drop covers whose page widgets were rebuilt or destroyed."""
        for key, cover in list(self._covers.items()):
            try:
                cover.isVisible()
            except RuntimeError:
                self._covers.pop(key, None)

    def _advance(self) -> None:
        """Advance all plaques from one timer."""
        self._phase += 0.05
        for key, cover in list(self._covers.items()):
            try:
                cover.advance(self._phase)
            except RuntimeError:
                self._covers.pop(key, None)

    def unregister(self, *widgets: QWidget) -> None:
        """Remove covers from widgets that are no longer sensitive."""
        for widget in widgets:
            cover = self._covers.pop(id(widget), None)
            if cover is not None:
                cover.deleteLater()
        self._update_timer()
