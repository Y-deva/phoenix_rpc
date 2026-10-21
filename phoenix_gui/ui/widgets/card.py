"""Reusable surface widgets: cards, section headers, pills and empty states."""

from __future__ import annotations

from typing import Iterable

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtCore import QSize
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLayout,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from .icons import icon


class Card(QFrame):
    """A rounded panel with a vertical content layout."""

    def __init__(
        self,
        parent: QWidget | None = None,
        padding: int = 18,
        spacing: int = 12,
        object_name: str = "Card",
    ) -> None:
        """Initialize the Card instance."""
        super().__init__(parent)
        self.setObjectName(object_name)
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(padding, padding, padding, padding)
        self.body.setSpacing(spacing)

    def add(self, widget: QWidget, stretch: int = 0) -> QWidget:
        """Append a widget to the card body."""
        self.body.addWidget(widget, stretch)
        return widget

    def add_layout(self, layout: QLayout, stretch: int = 0) -> QLayout:
        """Append a child layout to the card body."""
        self.body.addLayout(layout, stretch)
        return layout

    def add_stretch(self, stretch: int = 1) -> None:
        """Push the remaining content upwards."""
        self.body.addStretch(stretch)


class SectionHeader(QWidget):
    """A page or section heading with optional actions."""

    def __init__(
        self,
        title: str,
        subtitle: str = "",
        parent: QWidget | None = None,
        level: str = "section",
    ) -> None:
        """Initialize the SectionHeader instance."""
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        text_column = QVBoxLayout()
        text_column.setContentsMargins(0, 0, 0, 0)
        text_column.setSpacing(2)
        self.title_label = QLabel(title)
        self.title_label.setObjectName(
            "PageTitle" if level == "page" else "SectionTitle"
        )
        self.title_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self.subtitle_label = QLabel(subtitle)
        self.subtitle_label.setObjectName(
            "PageSubtitle" if level == "page" else "SectionHint"
        )
        self.subtitle_label.setWordWrap(True)
        self.subtitle_label.setVisible(bool(subtitle))
        text_column.addWidget(self.title_label)
        text_column.addWidget(self.subtitle_label)
        layout.addLayout(text_column, 1)
        self.actions = QHBoxLayout()
        self.actions.setContentsMargins(0, 0, 0, 0)
        self.actions.setSpacing(8)
        layout.addLayout(self.actions)

    def add_action(self, widget: QWidget) -> QWidget:
        """Add a control aligned to the right of the heading."""
        self.actions.addWidget(widget, 0, Qt.AlignmentFlag.AlignVCenter)
        return widget

    def set_subtitle(self, text: str) -> None:
        """Update the secondary line."""
        self.subtitle_label.setText(text)
        self.subtitle_label.setVisible(bool(text))

    def set_title(self, text: str) -> None:
        """Update the main heading."""
        self.title_label.setText(text)


class Pill(QLabel):
    """A compact status label with semantic colors."""

    LEVELS = {"neutral", "success", "warning", "danger", "accent"}

    def __init__(
        self, text: str = "", level: str = "neutral", parent: QWidget | None = None
    ) -> None:
        """Initialize the Pill instance."""
        super().__init__(text, parent)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        self._level = "neutral"
        self.set_level(level)

    @property
    def level(self) -> str:
        """Return the semantic color level."""
        return self._level

    def set_level(self, level: str) -> None:
        """Restyle the pill for a semantic level."""
        selected = level if level in self.LEVELS else "neutral"
        self._level = selected
        names = {
            "neutral": "PillNeutral",
            "success": "PillSuccess",
            "warning": "PillWarning",
            "danger": "PillDanger",
            "accent": "Pill",
        }
        self.setObjectName(names[selected])
        self.style().unpolish(self)
        self.style().polish(self)

    def set_text(self, text: str) -> None:
        """Update the label without disturbing the pill style."""
        self.setText(text)


class Divider(QFrame):
    """A one pixel horizontal separator."""

    def __init__(self, parent: QWidget | None = None) -> None:
        """Initialize the Divider instance."""
        super().__init__(parent)
        self.setObjectName("Divider")
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setFixedHeight(1)


class IconBadge(QFrame):
    """A soft square holding a single icon."""

    def __init__(
        self, icon_name: str, color: str, size: int = 36, parent: QWidget | None = None
    ) -> None:
        """Initialize the IconBadge instance."""
        super().__init__(parent)
        self.setObjectName("IconBadge")
        self.setFixedSize(size, size)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.label = QLabel(self)
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.label.setPixmap(icon(icon_name, color, 18).pixmap(18, 18))
        layout.addWidget(self.label)

    def set_icon(self, icon_name: str, color: str) -> None:
        """Swap the displayed icon."""
        self.label.setPixmap(icon(icon_name, color, 18).pixmap(18, 18))


class StatCard(Card):
    """A dashboard metric with title, value, caption and icon."""

    clicked = pyqtSignal()

    def __init__(
        self,
        title: str,
        value: str = "0",
        caption: str = "",
        icon_name: str = "wallet",
        accent: str = "#FF8A3D",
        parent: QWidget | None = None,
    ) -> None:
        """Initialize the StatCard instance."""
        super().__init__(parent, padding=16, spacing=8)
        self.setProperty("hoverable", True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(8)
        self.title_label = QLabel(title)
        self.title_label.setObjectName("CardTitle")
        top.addWidget(self.title_label, 1)
        self.badge = IconBadge(icon_name, accent, 32)
        top.addWidget(self.badge)
        self.body.addLayout(top)
        self.value_label = QLabel(value)
        self.value_label.setObjectName("MetricValue")
        self.value_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self.body.addWidget(self.value_label)
        self.caption_label = QLabel(caption)
        self.caption_label.setObjectName("CardCaption")
        self.caption_label.setWordWrap(True)
        self.body.addWidget(self.caption_label)

    def set_value(self, value: str) -> None:
        """Update the primary metric."""
        self.value_label.setText(value)

    def set_caption(self, text: str) -> None:
        """Update the explanatory line."""
        self.caption_label.setText(text)

    def set_icon(self, icon_name: str, color: str) -> None:
        """Update the decorative icon."""
        self.badge.set_icon(icon_name, color)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 - Qt API
        """Emit a click when the card is activated with the left button."""
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(event)


class KeyValueRow(QWidget):
    """A label and a selectable value, used in detail dialogs."""

    def __init__(
        self,
        label: str,
        value: str = "",
        mono: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        """Initialize the KeyValueRow instance."""
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        self.key_label = QLabel(label)
        self.key_label.setObjectName("Muted")
        self.key_label.setMinimumWidth(112)
        self.value_label = QLabel(value or "-")
        self.value_label.setObjectName("MonoStrong" if mono else "")
        self.value_label.setWordWrap(True)
        self.value_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        layout.addWidget(self.key_label, 0, Qt.AlignmentFlag.AlignTop)
        layout.addWidget(self.value_label, 1)

    def set_value(self, value: str) -> None:
        """Update the displayed value."""
        self.value_label.setText(value or "-")


class EmptyState(QWidget):
    """A calm placeholder for empty tables and lists."""

    def __init__(
        self,
        title: str,
        description: str = "",
        icon_name: str = "info",
        action_text: str = "",
        parent: QWidget | None = None,
    ) -> None:
        """Initialize the EmptyState instance."""
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 28, 24, 28)
        layout.setSpacing(8)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.icon_label = QLabel(self)
        self.icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.icon_label.setPixmap(icon(icon_name, "#748094", 30).pixmap(30, 30))
        self.title_label = QLabel(title)
        self.title_label.setObjectName("SectionTitle")
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.description_label = QLabel(description)
        self.description_label.setObjectName("Muted")
        self.description_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.description_label.setWordWrap(True)
        self.action_button = QPushButton(action_text, self)
        self.action_button.setObjectName("GhostButton")
        self.action_button.setVisible(bool(action_text))
        layout.addWidget(self.icon_label)
        layout.addWidget(self.title_label)
        layout.addWidget(self.description_label)
        layout.addWidget(self.action_button, 0, Qt.AlignmentFlag.AlignCenter)


def make_label(
    text: str = "", object_name: str = "", parent: QWidget | None = None
) -> QLabel:
    """Create a label with a standard object name."""
    label = QLabel(text, parent)
    if object_name:
        label.setObjectName(object_name)
    return label


def action_button(
    text: str,
    icon_name: str = "",
    object_name: str = "",
    color: str = "",
    parent: QWidget | None = None,
) -> QPushButton:
    """Create a consistently styled push button."""
    button = QPushButton(text, parent)
    if icon_name:
        button.setIcon(icon(icon_name, color or "#A7B1C2", 17))
        button.setIconSize(QSize(17, 17))
    if object_name:
        button.setObjectName(object_name)
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    return button


def set_icon(button, icon_name: str, color: str, size: int = 17) -> None:
    """Assign a themed icon to an existing button."""
    button.setIcon(icon(icon_name, color, size))
    button.setIconSize(QSize(size, size))


def add_widgets(layout: QLayout, widgets: Iterable[QWidget]) -> None:
    """Add several widgets to a layout in order."""
    for widget in widgets:
        layout.addWidget(widget)
