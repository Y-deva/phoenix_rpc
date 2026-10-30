"""Modal unlock or creation of the local encrypted key store."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..widgets.fields import PasswordField
from ..widgets.icons import icon


class WalletPasswordDialog(QDialog):
    """Ask for the key-store password without opening a terminal."""

    def __init__(
        self,
        create: bool,
        parent: QWidget | None = None,
    ) -> None:
        """Initialize the dialog for unlock or first-time creation."""
        super().__init__(parent)
        self.create = create
        self.setWindowTitle(
            "Создание хранилища ключей" if create else "Разблокировка кошелька"
        )
        self.setModal(True)
        self.setMinimumWidth(520)
        self._build()
        QShortcut(QKeySequence("Escape"), self, activated=self.reject)
        QShortcut(QKeySequence("Ctrl+Return"), self, activated=self._accept)
        QShortcut(QKeySequence("Ctrl+Enter"), self, activated=self._accept)

    def _build(self) -> None:
        """Create the compact security form."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 20)
        layout.setSpacing(12)

        heading = QHBoxLayout()
        badge = QLabel()
        badge.setPixmap(icon("lock", "#FF8A3D", 22).pixmap(22, 22))
        badge.setFixedSize(40, 40)
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge.setObjectName("IconBadge")
        titles = QVBoxLayout()
        title = QLabel(
            "Придумайте пароль" if self.create else "Введите пароль кошелька"
        )
        title.setObjectName("SectionTitle")
        subtitle = QLabel(
            "Пароль защищает Falcon-ключи в keypair.bin. "
            "Он не передается в сеть и не может быть восстановлен."
        )
        subtitle.setObjectName("Muted")
        subtitle.setWordWrap(True)
        titles.addWidget(title)
        titles.addWidget(subtitle)
        heading.addWidget(badge, 0, Qt.AlignmentFlag.AlignTop)
        heading.addLayout(titles, 1)
        layout.addLayout(heading)

        self.password = PasswordField()
        self.password.setPlaceholderText("Пароль")
        self.password.setToolTip("Минимум 8 символов; хранится только в памяти")
        layout.addWidget(self.password)

        self.repeat = PasswordField() if self.create else None
        if self.repeat is not None:
            self.repeat.setPlaceholderText("Повторите пароль")
            self.repeat.setToolTip("Повторный ввод для защиты от опечатки")
            self.repeat.textChanged.connect(self._update_match)
            layout.addWidget(self.repeat)

        self.hint = QLabel(
            "Пароль нужно вводить при каждом запуске кошелька."
            if not self.create
            else "Не используйте пароль от других сервисов."
        )
        self.hint.setObjectName("HintText")
        self.hint.setWordWrap(True)
        layout.addWidget(self.hint)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = QPushButton("Отмена")
        cancel.setObjectName("GhostButton")
        cancel.clicked.connect(self.reject)
        self.submit = QPushButton("Разблокировать" if not self.create else "Создать")
        self.submit.setObjectName("AccentButton")
        self.submit.setDefault(True)
        self.submit.clicked.connect(self._accept)
        buttons.addWidget(cancel)
        buttons.addWidget(self.submit)
        layout.addLayout(buttons)
        self.password.setFocus()

    def _update_match(self) -> None:
        """Disable creation until both fields are equal."""
        if self.repeat is None:
            return
        match = self.password.text() == self.repeat.text()
        self.submit.setEnabled(match and len(self.password.text()) >= 8)
        if self.repeat.text() and not match:
            self.hint.setText("Пароли не совпадают.")
            self.hint.setStyleSheet("color: #FF7070;")
        else:
            self.hint.setText("Не используйте пароль от других сервисов.")
            self.hint.setStyleSheet("")

    def _accept(self) -> None:
        """Validate the form before accepting."""
        value = self.password.text()
        if not value:
            self.password.setFocus()
            return
        if self.create:
            if len(value) < 8:
                self.hint.setText("Минимум 8 символов.")
                self.hint.setStyleSheet("color: #FF7070;")
                return
            if self.repeat is None or value != self.repeat.text():
                self.hint.setText("Пароли не совпадают.")
                self.hint.setStyleSheet("color: #FF7070;")
                return
        self.accept()

    def password_value(self) -> str:
        """Return the typed secret."""
        return self.password.text()
