"""Application log viewer with export and clearing controls."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import QTimer, QUrl, Qt
from PyQt6.QtGui import QDesktopServices, QFontDatabase, QTextCursor
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ...core.logs import clear_log, export_log, log_directory, log_file, read_log
from ..widgets.card import Card
from ..widgets.icons import icon
from .base import BasePage


class LogsPage(BasePage):
    """Show, filter, export and clear the rotating application log."""

    page_id = "logs"
    page_title = "Журнал"
    page_subtitle = "События приложения, ошибки и диагностика без терминала"
    auto_refresh = False

    def __init__(self, context, parent: QWidget | None = None) -> None:
        """Initialize the LogsPage instance."""
        super().__init__(context, parent)
        self._text = ""
        self._build_ui()
        self._timer = QTimer(self)
        self._timer.setInterval(2000)
        self._timer.timeout.connect(self.refresh)

    def _build_ui(self) -> None:
        """Create the filter toolbar and the log viewer."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 18, 24, 24)
        layout.setSpacing(12)

        toolbar = Card(padding=14, spacing=8)
        path_row = QHBoxLayout()
        path_row.setSpacing(8)
        self.path_label = QLabel(str(log_file()))
        self.path_label.setObjectName("HintText")
        self.path_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self.path_label.setWordWrap(True)
        self.folder_button = QPushButton("Открыть папку")
        self.folder_button.setObjectName("GhostButton")
        self.folder_button.setIcon(
            icon("folder", self.tokens.get("muted", "#A7B1C2"), 16)
        )
        self.folder_button.clicked.connect(self._open_folder)
        path_row.addWidget(self.path_label, 1)
        path_row.addWidget(self.folder_button)
        toolbar.add_layout(path_row)

        filters = QHBoxLayout()
        filters.setSpacing(8)
        self.level = QComboBox()
        self.level.addItem("Все записи", "all")
        self.level.addItem("Ошибки", "error")
        self.level.addItem("Предупреждения", "warning")
        self.level.setFixedWidth(170)
        self.level.setToolTip("Показывать только выбранный уровень важности")
        self.level.currentIndexChanged.connect(self._render)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Фильтр по тексту журнала")
        self.search.setClearButtonEnabled(True)
        self.search.setToolTip("Поиск по сообщению, модулю или адресу")
        self.search.textChanged.connect(self._render)
        self.follow = QCheckBox("Следовать за журналом")
        self.follow.setChecked(True)
        self.follow.setToolTip("Прокручивать вниз при появлении новых строк")
        self.refresh_button = QPushButton("Обновить")
        self.refresh_button.setObjectName("GhostButton")
        self.refresh_button.setIcon(
            icon("refresh", self.tokens.get("muted", "#A7B1C2"), 16)
        )
        self.refresh_button.clicked.connect(self.refresh)
        filters.addWidget(self.level)
        filters.addWidget(self.search, 1)
        filters.addWidget(self.follow)
        filters.addWidget(self.refresh_button)
        toolbar.add_layout(filters)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        self.export_button = QPushButton("Выгрузить")
        self.export_button.setObjectName("AccentButton")
        self.export_button.setIcon(
            icon("download", self.tokens.get("accent_text", "#1B0D04"), 16)
        )
        self.export_button.setToolTip("Сохранить журнал в текстовый файл")
        self.export_button.clicked.connect(self._export)
        self.clear_button = QPushButton("Очистить")
        self.clear_button.setObjectName("DangerButton")
        self.clear_button.setToolTip("Удалить все записи журнала")
        self.clear_button.clicked.connect(self._clear)
        actions.addStretch(1)
        actions.addWidget(self.export_button)
        actions.addWidget(self.clear_button)
        toolbar.add_layout(actions)
        layout.addWidget(toolbar)

        viewer_card = Card(padding=14, spacing=8)
        title = QLabel("События")
        title.setObjectName("CardTitle")
        viewer_card.add(title)
        self.view = QPlainTextEdit()
        self.view.setObjectName("LogView")
        self.view.setReadOnly(True)
        self.view.setUndoRedoEnabled(False)
        self.view.setMaximumBlockCount(6000)
        self.view.setPlaceholderText("Журнал пока пуст")
        self.view.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        font.setPointSizeF(9.5)
        self.view.setFont(font)
        self.view.setToolTip("Выделяйте и копируйте нужные строки")
        viewer_card.add(self.view, 1)
        self.footer = QLabel("")
        self.footer.setObjectName("HintText")
        viewer_card.add(self.footer)
        layout.addWidget(viewer_card, 1)

    def showEvent(self, event) -> None:  # noqa: N802 - Qt API
        """Refresh and start polling while the page is visible."""
        super().showEvent(event)
        self._timer.start()
        self.refresh()

    def hideEvent(self, event) -> None:  # noqa: N802 - Qt API
        """Stop polling when the page is hidden."""
        self._timer.stop()
        super().hideEvent(event)

    def refresh(self) -> None:
        """Read the log tail and update the view."""
        self._text = read_log()
        self.path_label.setText(str(log_file()))
        self._render()
        self._loaded = True

    def _render(self) -> None:
        """Apply level and text filters to the current log tail."""
        lines = self._text.splitlines()
        level = self.level.currentData()
        if level == "error":
            lines = [
                line for line in lines if " ERROR " in line or " CRITICAL " in line
            ]
        elif level == "warning":
            lines = [
                line
                for line in lines
                if " WARNING " in line or " ERROR " in line or " CRITICAL " in line
            ]
        query = self.search.text().strip().lower()
        if query:
            lines = [line for line in lines if query in line.lower()]
        bar = self.view.verticalScrollBar()
        at_bottom = bar.value() >= bar.maximum() - 4
        scroll_value = bar.value()
        cursor = self.view.textCursor()
        cursor_position = cursor.position()
        anchor = cursor.anchor()
        self.view.setPlainText("\n".join(lines))
        if self.follow.isChecked() and at_bottom:
            bar.setValue(bar.maximum())
        else:
            # Keep the reader's place when live refresh adds new lines.
            restored = self.view.textCursor()
            restored.setPosition(min(anchor, len(self.view.toPlainText())))
            restored.setPosition(
                min(cursor_position, len(self.view.toPlainText())),
                QTextCursor.MoveMode.KeepAnchor,
            )
            self.view.setTextCursor(restored)
            bar.setValue(min(scroll_value, bar.maximum()))
        path = log_file()
        size = path.stat().st_size if path.is_file() else 0
        self.footer.setText(
            f"Строк: {len(lines)} | файл: {size / 1024:.1f} КБ | "
            "пароли и приватные ключи не записываются"
        )

    def _export(self) -> None:
        """Ask for a destination and write one combined log file."""
        suggested = str(
            Path.home()
            / f"phoenix-wallet-{datetime.now().strftime('%Y%m%d-%H%M%S')}.log"
        )
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Выгрузить журнал",
            suggested,
            "Текстовый файл (*.log *.txt)",
        )
        if not path:
            return
        try:
            destination = export_log(Path(path))
        except OSError as error:
            self.fail(error)
            return
        self.notify(f"Журнал сохранен: {destination}", 5000)

    def _clear(self) -> None:
        """Confirm and empty the log."""
        self.ask(
            "Очистить журнал",
            "Все записи и ротированные копии будут удалены. "
            "Это действие нельзя отменить.",
            self._do_clear,
            "Очистить",
            True,
        )

    def _do_clear(self) -> None:
        """Clear log files and refresh the viewer."""
        clear_log()
        self.refresh()
        self.notify("Журнал очищен", 3500)

    def _open_folder(self) -> None:
        """Open the log folder in the system file manager."""
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(log_directory())))
