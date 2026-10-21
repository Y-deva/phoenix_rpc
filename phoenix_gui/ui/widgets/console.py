"""Widgets used by the graphical JSON-RPC console."""

from __future__ import annotations

from typing import Iterable, Sequence

from PyQt6.QtCore import QStringListModel, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QKeyEvent, QTextCharFormat, QTextCursor
from PyQt6.QtWidgets import (
    QCompleter,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)

from ...core.rpc_methods import RpcMethod
from .fields import SearchField


class ConsoleInput(QLineEdit):
    """Command line with method completion and persistent history."""

    commandSubmitted = pyqtSignal(str)
    clearRequested = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        """Initialize the ConsoleInput instance."""
        super().__init__(parent)
        self.setObjectName("ConsoleInput")
        self.setPlaceholderText("Введите метод и параметры, например: getinfo")
        self.setToolTip(
            "RPC-команда: метод и параметры через пробел. Tab дополняет имя."
        )
        self.setClearButtonEnabled(False)
        self._history: list[str] = []
        self._history_index = 0
        self._draft = ""
        self._methods: tuple[str, ...] = ()
        self._completion_model = QStringListModel([], self)
        self._completer = QCompleter(self._completion_model, self)
        self._completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self._completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        self._completer.setFilterMode(Qt.MatchFlag.MatchStartsWith)
        self._completer.activated[str].connect(self._insert_completion)
        self.setCompleter(self._completer)
        self.returnPressed.connect(self._submit)
        self.textEdited.connect(self._on_text_edited)

    def set_methods(self, names: Iterable[str]) -> None:
        """Provide the method list for Tab completion."""
        self._methods = tuple(names)
        self._completion_model.setStringList(list(self._methods))

    def set_history(self, history: Sequence[str]) -> None:
        """Load previously executed commands."""
        self._history = [item for item in history if item][-100:]
        self._history_index = len(self._history)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802 - Qt API
        """Handle history, completion and clear shortcuts."""
        key = event.key()
        if key == Qt.Key.Key_Up:
            self._history_back()
            return
        if key == Qt.Key.Key_Down:
            self._history_forward()
            return
        if key == Qt.Key.Key_Tab:
            if self._completer.popup().isVisible():
                super().keyPressEvent(event)
            else:
                self._complete()
            return
        if (
            key == Qt.Key.Key_L
            and event.modifiers() & Qt.KeyboardModifier.ControlModifier
        ):
            self.clearRequested.emit()
            return
        super().keyPressEvent(event)

    def _submit(self) -> None:
        """Emit the current command and clear the input."""
        text = self.text().strip()
        if not text:
            return
        self._remember(text)
        self.clear()
        self.commandSubmitted.emit(text)

    def _remember(self, text: str) -> None:
        """Add a command to the local history."""
        if self._history and self._history[-1] == text:
            self._history_index = len(self._history)
            return
        self._history.append(text)
        self._history = self._history[-100:]
        self._history_index = len(self._history)

    def _history_back(self) -> None:
        """Move to the previous history entry."""
        if not self._history:
            return
        if self._history_index >= len(self._history):
            self._draft = self.text()
        self._history_index = max(0, self._history_index - 1)
        self.setText(self._history[self._history_index])
        self.selectAll()

    def _history_forward(self) -> None:
        """Move to the next history entry or restore the draft."""
        if not self._history:
            return
        if self._history_index < len(self._history) - 1:
            self._history_index += 1
            self.setText(self._history[self._history_index])
        else:
            self._history_index = len(self._history)
            self.setText(self._draft)
        self.selectAll()

    def _on_text_edited(self, _text: str) -> None:
        """Limit method completion to the first word."""
        if " " in self.text():
            self._completer.setCompletionPrefix("")
            return
        self._completer.setCompletionPrefix(self.text())

    def _complete(self) -> None:
        """Open the completion popup or complete a unique method."""
        prefix = self.text().strip().lower()
        if " " in prefix:
            return
        matches = [name for name in self._methods if name.startswith(prefix)]
        if not matches:
            return
        if len(matches) == 1:
            self.setText(matches[0] + " ")
            return
        self._completer.setCompletionPrefix(prefix)
        self._completer.complete()

    def _insert_completion(self, completion: str) -> None:
        """Insert the chosen method and a trailing space."""
        self.setText(completion + " ")
        self.setFocus()


class ConsoleOutput(QPlainTextEdit):
    """Read-only, bounded output view for console traffic."""

    def __init__(self, parent: QWidget | None = None) -> None:
        """Initialize the ConsoleOutput instance."""
        super().__init__(parent)
        self.setObjectName("ConsoleOutput")
        self.setReadOnly(True)
        self.setUndoRedoEnabled(False)
        self.setMaximumBlockCount(5000)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.setTabChangesFocus(False)

    def append_line(self, text: str, color: str = "", bold: bool = False) -> None:
        """Append one line with an optional color and weight."""
        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        char_format = QTextCharFormat()
        if color:
            char_format.setForeground(QColor(color))
        if bold:
            char_format.setFontWeight(QFont.Weight.DemiBold)
        cursor.insertText(text.rstrip("\n") + "\n", char_format)
        self.setTextCursor(cursor)
        self.ensureCursorVisible()

    def apply_theme(
        self, tokens: dict[str, str], mono_font: str, font_scale: int
    ) -> None:
        """Apply the monospace font and base text color."""
        font = QFont(mono_font)
        font.setPointSizeF(max(8.0, 10.0 * font_scale / 100))
        self.setFont(font)
        self.setStyleSheet(
            f"color: {tokens.get('text', '#E7ECF5')};"
            f"background: {tokens.get('surface_alt', '#101722')};"
        )


class MethodBrowser(QWidget):
    """Searchable catalogue of daemon methods."""

    methodActivated = pyqtSignal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        """Initialize the MethodBrowser instance."""
        super().__init__(parent)
        self._methods: list[RpcMethod] = []
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        self.search = SearchField()
        self.search.setPlaceholderText("Найти метод")
        self.search.searchChanged.connect(self._filter)
        self.list = QListWidget()
        self.list.setObjectName("MethodList")
        self.list.setUniformItemSizes(True)
        self.list.setToolTip("Двойной щелчок вставляет метод в командную строку")
        self.description = QLabel("Выберите метод, чтобы увидеть описание.")
        self.description.setObjectName("HintText")
        self.description.setWordWrap(True)
        self.description.setMinimumHeight(54)
        layout.addWidget(self.search)
        layout.addWidget(self.list, 1)
        layout.addWidget(self.description)
        self.list.currentItemChanged.connect(self._show_description)
        self.list.itemDoubleClicked.connect(self._activate_item)

    def set_methods(self, methods: Iterable[RpcMethod]) -> None:
        """Populate the browser from the RPC catalogue."""
        self._methods = list(methods)
        self.list.clear()
        for method in self._methods:
            item = QListWidgetItem(method.signature)
            item.setData(Qt.ItemDataRole.UserRole, method)
            item.setToolTip(f"{method.signature}\n{method.description}")
            self.list.addItem(item)

    def _filter(self, text: str) -> None:
        """Hide methods that do not match the query."""
        query = text.strip().casefold()
        for row in range(self.list.count()):
            item = self.list.item(row)
            method: RpcMethod = item.data(Qt.ItemDataRole.UserRole)
            visible = (
                not query
                or query in method.name.casefold()
                or query in method.description.casefold()
            )
            item.setHidden(not visible)

    def _show_description(
        self, current: QListWidgetItem | None, _previous=None
    ) -> None:
        """Show the selected method signature and description."""
        if current is None:
            self.description.setText("Выберите метод, чтобы увидеть описание.")
            return
        method: RpcMethod = current.data(Qt.ItemDataRole.UserRole)
        self.description.setText(f"{method.signature}\n{method.description}")

    def _activate_item(self, item: QListWidgetItem) -> None:
        """Emit the selected method name."""
        method: RpcMethod = item.data(Qt.ItemDataRole.UserRole)
        self.methodActivated.emit(method.name)
