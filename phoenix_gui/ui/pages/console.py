"""Graphical JSON-RPC console page."""

from __future__ import annotations

import time
from typing import Any

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from ...core.console import ConsoleParseError, parse_command
from ...core.errors import humanize_error
from ...core.formatting import format_json
from ...core.rpc_methods import METHODS, find_method
from ...core.tasks import run_async
from ..widgets.card import Card
from ..widgets.console import ConsoleInput, ConsoleOutput, MethodBrowser
from ..widgets.fields import IconButton
from ..widgets.icons import icon
from ..widgets.progress import Spinner
from .base import BasePage


class ConsolePage(BasePage):
    """Execute arbitrary proxy RPC methods from a comfortable terminal."""

    page_id = "console"
    page_title = "Консоль"
    page_subtitle = "Прямой доступ к JSON-RPC через локальный прокси"
    auto_refresh = False

    def __init__(self, context: Any, parent: QWidget | None = None) -> None:
        """Initialize the ConsolePage instance."""
        super().__init__(context, parent)
        self._busy = False
        self._build()
        self.apply_theme()
        self._welcome()

    def _build(self) -> None:
        """Create toolbar, terminal and method browser."""
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(10)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)
        self.status_label = QLabel("Готово к работе")
        self.status_label.setObjectName("Muted")
        self.spinner = Spinner(size=18)
        self.clear_button = IconButton(
            "trash", self.tokens.get("muted", "#A7B1C2"), "Очистить вывод (Ctrl+L)", 34
        )
        self.clear_button.clicked.connect(self._clear)
        self.help_button = QPushButton("Методы")
        self.help_button.setObjectName("GhostButton")
        self.help_button.setCheckable(True)
        self.help_button.setChecked(True)
        self.help_button.setIcon(
            icon("terminal", self.tokens.get("muted", "#A7B1C2"), 15)
        )
        self.help_button.setToolTip("Показать или скрыть каталог методов")
        self.help_button.clicked.connect(self._toggle_browser)
        toolbar.addWidget(self.status_label)
        toolbar.addWidget(self.spinner)
        toolbar.addStretch(1)
        toolbar.addWidget(self.help_button)
        toolbar.addWidget(self.clear_button)
        root.addLayout(toolbar)

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setChildrenCollapsible(False)
        console_card = Card(padding=14)
        self.output = ConsoleOutput()
        self.output.setMinimumHeight(300)
        console_card.add(self.output, 1)
        input_row = QHBoxLayout()
        input_row.setSpacing(8)
        prompt = QLabel(">")
        prompt.setObjectName("MonoStrong")
        prompt.setToolTip("Приглашение консоли")
        self.input = ConsoleInput()
        self.input.set_history(self.settings.console_history())
        self.input.set_methods(method.name for method in METHODS)
        self.input.commandSubmitted.connect(self.execute)
        self.input.clearRequested.connect(self._clear)
        self.run_button = QPushButton("Выполнить")
        self.run_button.setObjectName("AccentButton")
        self.run_button.setIcon(
            icon("play", self.tokens.get("accent_text", "#1A1208"), 14)
        )
        self.run_button.setToolTip("Выполнить команду (Enter)")
        self.run_button.clicked.connect(self._submit_current)
        input_row.addWidget(prompt)
        input_row.addWidget(self.input, 1)
        input_row.addWidget(self.run_button)
        console_card.add_layout(input_row)
        self.hint = QLabel(
            "Enter - выполнить, Tab - дополнить, стрелки - история, Ctrl+L - очистить."
        )
        self.hint.setObjectName("HintText")
        console_card.add(self.hint)
        self.splitter.addWidget(console_card)
        self.splitter.setStretchFactor(0, 3)

        self.method_card = Card(padding=12)
        browser_title = QLabel("Каталог методов")
        browser_title.setObjectName("CardTitle")
        self.method_card.add(browser_title)
        self.browser = MethodBrowser()
        self.browser.set_methods(METHODS)
        self.browser.methodActivated.connect(self._insert_method)
        self.method_card.add(self.browser, 1)
        self.splitter.addWidget(self.method_card)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setSizes([780, 320])
        root.addWidget(self.splitter, 1)

        self.footer = QLabel(
            "Запросы идут через локальный прокси и сохраняются только в выводе."
        )
        self.footer.setObjectName("Muted")
        root.addWidget(self.footer)

    def refresh(self) -> None:
        """The console has no background data to refresh."""
        self._loaded = True

    def _welcome(self) -> None:
        """Print a short welcome block."""
        muted = self.tokens.get("muted", "#A7B1C2")
        accent = self.tokens.get("accent", "#FF8A3D")
        self.output.append_line(self.tr_text("Консоль Novacoin RPC"), accent, bold=True)
        self.output.append_line(
            self.tr_text("Введите help для справки демона или выберите метод справа."),
            muted,
        )
        self.output.append_line("", muted)

    def _submit_current(self) -> None:
        """Execute the text currently in the input."""
        text = self.input.text().strip()
        if not text:
            return
        if self._busy:
            self.statusMessage.emit("Дождитесь завершения текущего запроса", 2500)
            return
        self.execute(text)

    def execute(self, line: str) -> None:
        """Parse and run a console command."""
        if self._busy:
            self.statusMessage.emit("Дождитесь завершения текущего запроса", 2500)
            return
        try:
            command = parse_command(line)
        except ConsoleParseError as error:
            self.output.append_line(
                f"Ошибка разбора: {error}", self.tokens.get("negative", "#FF7070")
            )
            return
        method = find_method(command.method)
        if (
            method is not None
            and method.danger
            and not self._confirm_danger(method.signature)
        ):
            self.output.append_line(
                "Выполнение отменено.", self.tokens.get("warning", "#F3C969")
            )
            return
        self._remember(line)
        self.input.clear()
        self.output.append_line(
            f"> {command.signature}", self.tokens.get("accent", "#FF8A3D"), bold=True
        )
        self._busy = True
        self.busyChanged.emit(True)
        self.spinner.start()
        self.run_button.setEnabled(False)
        self.status_label.setText("Выполняется запрос...")
        started = time.monotonic()
        run_async(
            lambda: self.service.call(command.method, command.params),
            lambda result: self._on_result(result, started),
            self._on_error,
            self._on_done,
        )

    def _remember(self, line: str) -> None:
        """Persist the command in the shared console history."""
        history = list(self.settings.console_history())
        if not history or history[-1] != line:
            history.append(line)
        self.settings.set_console_history(history[-100:])

    def _on_result(self, result: Any, started: float) -> None:
        """Print a formatted RPC result."""
        text = result if isinstance(result, str) else format_json(result)
        self.output.append_line(text, self.tokens.get("text", "#E7ECF5"))
        if self.settings.verbosity >= 2:
            elapsed = int((time.monotonic() - started) * 1000)
            self.output.append_line(
                f"OK, {elapsed} ms", self.tokens.get("muted", "#A7B1C2")
            )
        self.status_label.setText("Запрос выполнен")

    def _on_error(self, error: object) -> None:
        """Print a readable error without hiding the console."""
        message = humanize_error(error)
        self.output.append_line(
            f"Ошибка: {message}", self.tokens.get("negative", "#FF7070")
        )
        self.status_label.setText("Запрос завершился ошибкой")

    def _on_done(self) -> None:
        """Restore input controls."""
        self._busy = False
        self.busyChanged.emit(False)
        self.spinner.stop()
        self.run_button.setEnabled(True)
        self.input.setFocus()

    def _confirm_danger(self, signature: str) -> bool:
        """Ask before executing a potentially destructive RPC method."""
        box = QMessageBox(self)
        box.setWindowTitle("Подтверждение")
        box.setIcon(QMessageBox.Icon.Warning)
        box.setText(f"Выполнить опасную команду?\n\n{signature}")
        box.setInformativeText("Команда может изменить кошелек или остановить демон.")
        run = box.addButton("Выполнить", QMessageBox.ButtonRole.AcceptRole)
        cancel = box.addButton("Отмена", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(cancel)
        box.exec()
        return box.clickedButton() is run

    def _insert_method(self, name: str) -> None:
        """Insert a method from the browser into the input."""
        method = find_method(name)
        text = name + (" " if method is None or method.params else "")
        self.input.setText(text)
        self.input.setFocus()
        self.input.setCursorPosition(len(text))

    def _clear(self) -> None:
        """Clear the output and show the welcome block again."""
        self.output.clear()
        self._welcome()
        self.status_label.setText("Готово к работе")
        self.input.setFocus()

    def _toggle_browser(self, checked: bool) -> None:
        """Show or hide the method catalogue."""
        self.method_card.setVisible(checked)
        if checked:
            self.splitter.setSizes([780, 320])

    def apply_theme(self) -> None:
        """Recolor console widgets and icons for the active theme."""
        self.output.apply_theme(
            dict(self.tokens), self.themes.mono_font, self.settings.font_scale
        )
        muted = self.tokens.get("muted", "#A7B1C2")
        self.clear_button.set_icon_name("trash")
        self.help_button.setIcon(icon("terminal", muted, 15))
        self.run_button.setIcon(
            icon("play", self.tokens.get("accent_text", "#1A1208"), 14)
        )
