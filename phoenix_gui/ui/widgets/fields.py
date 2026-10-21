"""Form controls used across pages and dialogs."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from PyQt6.QtCore import QRegularExpression, QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QGuiApplication, QRegularExpressionValidator
from PyQt6.QtWidgets import (
    QButtonGroup,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ...core.formatting import parse_amount
from .icons import icon


def copy_to_clipboard(text: str) -> bool:
    """Copy text to the system clipboard and report success."""
    clipboard = QGuiApplication.clipboard()
    if clipboard is None or not text:
        return False
    clipboard.setText(text)
    return True


class SearchField(QLineEdit):
    """A compact search box with a leading icon and debouncing."""

    searchChanged = pyqtSignal(str)

    def __init__(
        self, placeholder: str = "Поиск", parent: QWidget | None = None
    ) -> None:
        """Initialize the SearchField instance."""
        super().__init__(parent)
        self.setObjectName("SearchField")
        self.setPlaceholderText(placeholder)
        self.setClearButtonEnabled(True)
        self.setMinimumWidth(180)
        self.setToolTip("Поиск по содержимому таблицы или списка")
        QTimer.singleShot(0, self._prepare_clear_button)
        self._color = "#748094"
        self._search_action = None
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(170)
        self._timer.timeout.connect(lambda: self.searchChanged.emit(self.text()))
        self.textChanged.connect(lambda _text: self._timer.start())
        self._refresh_icon()

    def _prepare_clear_button(self) -> None:
        """Label the built-in clear button once Qt has created it."""
        for clear_button in self.findChildren(QToolButton):
            clear_button.setToolTip("Очистить поиск")

    def _refresh_icon(self) -> None:
        """Refresh the search glyph after a theme change."""
        if self._search_action is not None:
            self.removeAction(self._search_action)
        self._search_action = self.addAction(
            icon("search", self._color, 16), QLineEdit.ActionPosition.LeadingPosition
        )

    def set_icon_color(self, color: str) -> None:
        """Tint the leading icon for the active theme."""
        self._color = color
        self._refresh_icon()


class CopyLineEdit(QLineEdit):
    """A read-only value field with a one click copy action."""

    copied = pyqtSignal(str)

    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        """Initialize the CopyLineEdit instance."""
        super().__init__(text, parent)
        self.setReadOnly(True)
        self.setCursorPosition(0)
        self._color = "#A7B1C2"
        self._copy_action = self.addAction(
            icon("copy", self._color, 16), QLineEdit.ActionPosition.TrailingPosition
        )
        self._copy_action.setToolTip("Копировать")
        self._copy_action.triggered.connect(self.copy_value)
        self._reset_timer = QTimer(self)
        self._reset_timer.setSingleShot(True)
        self._reset_timer.timeout.connect(self._reset_icon)

    def copy_value(self) -> None:
        """Copy the current value and show a short confirmation."""
        if copy_to_clipboard(self.text()):
            self._copy_action.setIcon(icon("check", "#3DD6A0", 16))
            self._reset_timer.start(1200)
            self.copied.emit(self.text())

    def _reset_icon(self) -> None:
        """Restore the copy glyph."""
        self._copy_action.setIcon(icon("copy", self._color, 16))

    def set_icon_color(self, color: str) -> None:
        """Tint the copy glyph for the active theme."""
        self._color = color
        self._reset_icon()


class CopyButton(QPushButton):
    """Icon-only copy button for table and card actions."""

    copied = pyqtSignal(str)

    def __init__(
        self,
        value: str = "",
        color: str = "#A7B1C2",
        tooltip: str = "Копировать",
        parent: QWidget | None = None,
    ) -> None:
        """Initialize the CopyButton instance."""
        super().__init__("", parent)
        self.setObjectName("IconButton")
        self.setIcon(icon("copy", color, 16))
        self.setIconSize(QSize(16, 16))
        self.setFixedSize(30, 30)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(tooltip)
        self._value = value
        self._color = color
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._reset_icon)
        self.clicked.connect(self._copy)

    def set_value(self, value: str) -> None:
        """Update the value that will be copied."""
        self._value = value

    def _copy(self) -> None:
        """Copy the configured value and flash a check mark."""
        if copy_to_clipboard(self._value):
            self.setIcon(icon("check", "#3DD6A0", 16))
            self._timer.start(1200)
            self.copied.emit(self._value)

    def _reset_icon(self) -> None:
        """Restore the copy icon."""
        self.setIcon(icon("copy", self._color, 16))


class AmountField(QWidget):
    """A decimal amount input with an NVC suffix."""

    textChanged = pyqtSignal(str)
    editingFinished = pyqtSignal()

    def __init__(self, parent: QWidget | None = None, suffix: str = "NVC") -> None:
        """Initialize the AmountField instance."""
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        self.edit = QLineEdit(self)
        self.edit.setPlaceholderText("0.00000000")
        self.edit.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.edit.setToolTip("Сумма перевода в NVC. Можно ввести точку или запятую.")
        self.edit.setMinimumWidth(160)
        expression = QRegularExpression(r"^\d{0,12}([.,]\d{0,8})?$")
        self._validator = QRegularExpressionValidator(expression, self.edit)
        self.edit.setValidator(self._validator)
        self.edit.textChanged.connect(self.textChanged.emit)
        self.edit.editingFinished.connect(self.editingFinished.emit)
        self.suffix_label = QLabel(suffix, self)
        self.suffix_label.setObjectName("Muted")
        self.suffix_label.setVisible(bool(suffix))
        layout.addWidget(self.edit, 1)
        layout.addWidget(self.suffix_label)

    def text(self) -> str:
        """Return the raw input text."""
        return self.edit.text()

    def setText(self, value: str) -> None:  # noqa: N802 - Qt API
        """Set the raw input text."""
        self.edit.setText(value)

    def clear(self) -> None:
        """Clear the field."""
        self.edit.clear()

    def value(self) -> Decimal | None:
        """Parse the field, returning None for empty or invalid input."""
        try:
            return parse_amount(self.edit.text())
        except ValueError:
            return None

    def set_placeholder(self, text: str) -> None:
        """Change the placeholder text."""
        self.edit.setPlaceholderText(text)

    def set_read_only(self, read_only: bool) -> None:
        """Toggle editability."""
        self.edit.setReadOnly(read_only)

    def set_error(self, error: bool) -> None:
        """Highlight the field when validation fails."""
        self.edit.setProperty("error", bool(error))
        self.edit.style().unpolish(self.edit)
        self.edit.style().polish(self.edit)

    def setFocus(self) -> None:  # noqa: N802 - Qt API
        """Forward focus to the inner line edit."""
        self.edit.setFocus()

    def set_suffix(self, text: str) -> None:
        """Change the unit displayed after the number."""
        self.suffix_label.setText(text)
        self.suffix_label.setVisible(bool(text))


class LabeledField(QWidget):
    """A labeled input with optional hint and validation error."""

    def __init__(
        self,
        label: str,
        field: QWidget,
        hint: str = "",
        parent: QWidget | None = None,
    ) -> None:
        """Initialize the LabeledField instance."""
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        self.label = QLabel(label)
        self.label.setObjectName("Muted")
        header.addWidget(self.label)
        header.addStretch(1)
        self.hint_label = QLabel(hint)
        self.hint_label.setObjectName("HintText")
        self.hint_label.setVisible(bool(hint))
        header.addWidget(self.hint_label)
        layout.addLayout(header)
        self.field = field
        layout.addWidget(field)
        self.error_label = QLabel("")
        self.error_label.setObjectName("ErrorText")
        self.error_label.setWordWrap(True)
        self.error_label.setVisible(False)
        layout.addWidget(self.error_label)

    def set_error(self, message: str = "") -> None:
        """Show or clear a validation message."""
        self.error_label.setText(message)
        self.error_label.setVisible(bool(message))
        if isinstance(self.field, AmountField):
            self.field.set_error(bool(message))
        elif isinstance(self.field, (QLineEdit, QWidget)):
            self.field.setProperty("error", bool(message))
            self.field.style().unpolish(self.field)
            self.field.style().polish(self.field)

    def set_hint(self, text: str) -> None:
        """Update the small hint beside the label."""
        self.hint_label.setText(text)
        self.hint_label.setVisible(bool(text))


class PathField(QWidget):
    """A path input paired with a native browse dialog."""

    pathChanged = pyqtSignal(str)

    def __init__(
        self,
        mode: str = "file",
        caption: str = "Выбрать",
        filter_text: str = "",
        parent: QWidget | None = None,
    ) -> None:
        """Initialize the PathField instance."""
        super().__init__(parent)
        self._mode = mode
        self._caption = caption
        self._filter = filter_text
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        self.edit = QLineEdit(self)
        self.edit.setPlaceholderText("Путь не выбран")
        self.edit.setToolTip("Путь к файлу или папке на этом компьютере")
        self.edit.textChanged.connect(self.pathChanged.emit)
        self.browse = QPushButton(self)
        self.browse.setObjectName("IconButton")
        self.browse.setIcon(icon("folder", "#A7B1C2", 17))
        self.browse.setIconSize(QSize(17, 17))
        self.browse.setFixedSize(36, 36)
        self.browse.setCursor(Qt.CursorShape.PointingHandCursor)
        self.browse.setToolTip(caption)
        self.browse.clicked.connect(self._browse)
        layout.addWidget(self.edit, 1)
        layout.addWidget(self.browse)

    def path(self) -> str:
        """Return the current path text."""
        return self.edit.text().strip()

    def set_path(self, value: str) -> None:
        """Set the displayed path."""
        self.edit.setText(value or "")

    def _browse(self) -> None:
        """Open the appropriate native file dialog."""
        if self._mode == "dir":
            selected = QFileDialog.getExistingDirectory(
                self, self._caption, self.path() or str(Path.home())
            )
        else:
            selected, _ = QFileDialog.getOpenFileName(
                self, self._caption, self.path() or str(Path.home()), self._filter
            )
        if selected:
            self.edit.setText(selected)


class SegmentedControl(QFrame):
    """A small row of mutually exclusive pill buttons."""

    valueChanged = pyqtSignal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        """Initialize the SegmentedControl instance."""
        super().__init__(parent)
        self.setObjectName("Segment")
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(3, 3, 3, 3)
        self._layout.setSpacing(3)
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._buttons: dict[str, QPushButton] = {}
        self._value = ""
        self._group.buttonClicked.connect(self._on_clicked)

    def add_segment(self, value: str, text: str, tooltip: str = "") -> QPushButton:
        """Append one segment."""
        button = QPushButton(text, self)
        button.setObjectName("SegmentButton")
        button.setCheckable(True)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setToolTip(tooltip or f"Выбрать: {text}")
        self._group.addButton(button)
        self._layout.addWidget(button)
        self._buttons[value] = button
        if not self._value:
            self._value = value
            button.setChecked(True)
        return button

    def set_segments(self, items: list[tuple[str, str]]) -> None:
        """Replace all segments with a new list of value and label pairs."""
        for button in self._buttons.values():
            self._group.removeButton(button)
            button.deleteLater()
        self._buttons.clear()
        self._value = ""
        for value, label in items:
            self.add_segment(value, label)
        self.set_value(self._value)

    def set_value(self, value: str) -> None:
        """Select a segment without emitting the change signal."""
        button = self._buttons.get(value)
        if button is not None:
            button.setChecked(True)
            self._value = value

    def value(self) -> str:
        """Return the selected value."""
        return self._value

    def _on_clicked(self, button: QPushButton) -> None:
        """Translate a button click into a value signal."""
        for value, candidate in self._buttons.items():
            if candidate is button:
                self._value = value
                self.valueChanged.emit(value)
                return


class PasswordField(QLineEdit):
    """A password input with a reveal toggle."""

    def __init__(self, parent: QWidget | None = None) -> None:
        """Initialize the PasswordField instance."""
        super().__init__(parent)
        self.setEchoMode(QLineEdit.EchoMode.Password)
        self.setToolTip("Пароль для подключения к локальному прокси")
        self._color = "#A7B1C2"
        self._action = self.addAction(
            icon("eye", self._color, 16), QLineEdit.ActionPosition.TrailingPosition
        )
        self._action.setToolTip("Показать")
        self._action.triggered.connect(self._toggle)

    def _toggle(self) -> None:
        """Switch between masked and plain text."""
        visible = self.echoMode() == QLineEdit.EchoMode.Normal
        self.setEchoMode(
            QLineEdit.EchoMode.Password if visible else QLineEdit.EchoMode.Normal
        )
        self._action.setIcon(icon("eye-off" if visible else "eye", self._color, 16))
        self._action.setToolTip("Показать" if visible else "Скрыть")


class IconButton(QPushButton):
    """A fixed size icon-only button with a tooltip."""

    def __init__(
        self,
        icon_name: str,
        color: str,
        tooltip: str = "",
        size: int = 32,
        parent: QWidget | None = None,
    ) -> None:
        """Initialize the IconButton instance."""
        super().__init__("", parent)
        self.setObjectName("IconButton")
        self.setFixedSize(size, size)
        self.setIcon(icon(icon_name, color, 17))
        self.setIconSize(QSize(17, 17))
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        if tooltip:
            self.setToolTip(tooltip)
        self._color = color

    def set_icon_name(self, icon_name: str) -> None:
        """Swap the glyph while keeping the theme color."""
        self.setIcon(icon(icon_name, self._color, 17))


def set_button_icon(
    button: QPushButton, icon_name: str, color: str, size: int = 17
) -> None:
    """Assign a themed icon and icon size to a button."""
    button.setIcon(icon(icon_name, color, size))
    button.setIconSize(QSize(size, size))


def labeled_row(label: str, widget: QWidget, hint: str = "") -> LabeledField:
    """Shorthand for a labeled field."""
    return LabeledField(label, widget, hint)
