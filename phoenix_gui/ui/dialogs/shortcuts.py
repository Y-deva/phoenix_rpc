"""Keyboard shortcut reference dialog."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ..widgets.card import Card, Divider, SectionHeader

SHORTCUTS: tuple[tuple[str, tuple[tuple[str, str], ...]], ...] = (
    (
        "Навигация",
        (
            ("Alt+1 ... Alt+8", "Перейти к странице по номеру"),
            ("Ctrl+,", "Открыть настройки"),
            ("F1", "Показать этот список"),
            ("Esc", "Закрыть диалог"),
        ),
    ),
    (
        "Кошелек",
        (
            ("Ctrl+R, F5", "Обновить текущую страницу"),
            ("Ctrl+Shift+T", "Переключить тему"),
            ("Ctrl+Q", "Выйти из приложения"),
        ),
    ),
    (
        "Консоль",
        (
            ("Enter", "Выполнить команду"),
            ("Tab", "Дополнить имя метода"),
            ("Стрелки вверх и вниз", "Листать историю команд"),
            ("Ctrl+L", "Очистить вывод"),
        ),
    ),
    (
        "Таблицы и текст",
        (
            ("Ctrl+C", "Скопировать выделенное"),
            ("Ctrl+A", "Выделить все строки или входы"),
            ("Ctrl+E", "Экспортировать историю в CSV"),
            ("Ctrl+Enter", "Подтвердить отправку"),
            ("Двойной щелчок", "Открыть подробности транзакции"),
        ),
    ),
)


class ShortcutsDialog(QDialog):
    """Display every global and context-specific shortcut."""

    def __init__(self, tokens: dict[str, str], parent: QWidget | None = None) -> None:
        """Initialize the ShortcutsDialog instance."""
        super().__init__(parent)
        self._tokens = tokens
        self.setWindowTitle("Сочетания клавиш")
        self.setModal(True)
        self.setMinimumSize(540, 620)
        self.resize(580, 680)
        self._build()

    def _build(self) -> None:
        """Create the scrollable reference."""
        outer = QVBoxLayout(self)
        outer.setContentsMargins(22, 20, 22, 18)
        outer.setSpacing(12)
        header = SectionHeader(
            "Сочетания клавиш",
            "Работают в любом месте приложения, если не перехвачены полем ввода",
            level="page",
        )
        outer.addWidget(header)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        content = QWidget()
        body = QVBoxLayout(content)
        body.setContentsMargins(0, 0, 4, 0)
        body.setSpacing(12)
        for title, rows in SHORTCUTS:
            card = Card(padding=16, spacing=8)
            caption = QLabel(title)
            caption.setObjectName("CardTitle")
            card.add(caption)
            card.add(Divider())
            for index, (keys, description) in enumerate(rows):
                row = QHBoxLayout()
                row.setSpacing(10)
                key_label = QLabel(keys)
                key_label.setObjectName("MonoStrong")
                key_label.setMinimumWidth(170)
                key_label.setToolTip(keys)
                description_label = QLabel(description)
                description_label.setObjectName("Muted")
                description_label.setWordWrap(True)
                row.addWidget(key_label)
                row.addWidget(description_label, 1)
                card.add_layout(row)
                if index < len(rows) - 1:
                    card.add(Divider())
            body.addWidget(card)
        body.addStretch(1)
        scroll.setWidget(content)
        outer.addWidget(scroll, 1)
        close_row = QHBoxLayout()
        close_row.addStretch(1)
        close_button = QPushButton("Закрыть")
        close_button.setObjectName("AccentButton")
        close_button.setToolTip("Закрыть окно (Esc)")
        close_button.clicked.connect(self.accept)
        close_row.addWidget(close_button)
        outer.addLayout(close_row)
        close_button.setFocus(Qt.FocusReason.OtherFocusReason)
