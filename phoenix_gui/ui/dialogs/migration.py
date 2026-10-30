"""Guided import of legacy NovaCoin keys without using a terminal."""

from __future__ import annotations

from decimal import Decimal
from functools import partial
from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ...core.config import ProjectConfig
from ...core.formatting import format_nvc, shorten_txid
from ...core.migration import (
    MigrationReport,
    import_wif,
    import_wallet_file,
    sweep_all,
    validate_destination,
    validate_wif,
)
from ...core.tasks import run_async
from ...settings import Settings
from ..widgets.card import Divider
from ..widgets.fields import PasswordField, PathField, SegmentedControl
from ..widgets.icons import icon
from ..widgets.progress import TaskProgress


class MigrationDialog(QDialog):
    """Import WIF or wallet.dat keys and sweep the balance to Phoenix."""

    completed = pyqtSignal()

    def __init__(
        self,
        project: ProjectConfig,
        settings: Settings,
        tokens: dict[str, str],
        destination: str = "",
        parent: QWidget | None = None,
    ) -> None:
        """Initialize the migration dialog."""
        super().__init__(parent)
        self.project = project
        self.settings = settings
        self.tokens = tokens
        self._report: MigrationReport | None = None
        self._sent = False
        self._busy = False
        self.setWindowTitle("Перенос старого кошелька")
        self.setModal(True)
        self.setMinimumSize(720, 660)
        self._build(destination)
        QShortcut(QKeySequence("Escape"), self, activated=self.reject)

    def _build(self, destination: str) -> None:
        """Build the fixed wizard layout."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 18)
        layout.setSpacing(12)

        heading = QHBoxLayout()
        badge = QLabel()
        badge.setPixmap(icon("download", "#FF8A3D", 22).pixmap(22, 22))
        badge.setFixedSize(42, 42)
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge.setObjectName("IconBadge")
        titles = QVBoxLayout()
        title = QLabel("Перенос средств из старого кошелька")
        title.setObjectName("PageTitle")
        subtitle = QLabel(
            "NovaCoin с ECDSA-ключами несовместим с Falcon-ключами Phoenix. "
            "Мастер импортирует старые ключи в резервный кошелек демона "
            "и выведет баланс на ваш Phoenix-адрес."
        )
        subtitle.setObjectName("Muted")
        subtitle.setWordWrap(True)
        titles.addWidget(title)
        titles.addWidget(subtitle)
        heading.addWidget(badge, 0, Qt.AlignmentFlag.AlignTop)
        heading.addLayout(titles, 1)
        layout.addLayout(heading)

        warning = QLabel(
            "Сначала сделайте копию keypair.bin и исходного wallet.dat. "
            "Перенос необратим, а старые ключи остаются в локальном кошельке "
            "демона до его восстановления из резервной копии. Никому не "
            "передавайте WIF и пароль."
        )
        warning.setObjectName("WarningText")
        warning.setWordWrap(True)
        layout.addWidget(warning)

        self.mode = SegmentedControl()
        self.mode.add_segment("wif", "Ключ WIF", "Вставить приватный ключ")
        self.mode.add_segment("wallet", "wallet.dat", "Загрузить файл старого кошелька")
        self.mode.valueChanged.connect(self._on_mode_changed)
        layout.addWidget(self.mode)

        self.pages = QStackedWidget()
        self.pages.addWidget(self._build_wif_page())
        self.pages.addWidget(self._build_wallet_page())
        layout.addWidget(self.pages)

        destination_label = QLabel("Ваш Phoenix-адрес")
        destination_label.setObjectName("CardCaption")
        layout.addWidget(destination_label)
        self.destination = QLineEdit()
        self.destination.setPlaceholderText("Вставьте адрес из раздела Получить")
        self.destination.setToolTip("Сюда будет выведен весь перенесенный баланс")
        self.destination.setText(destination)
        layout.addWidget(self.destination)

        steps = QFrame()
        steps.setObjectName("SoftCard")
        steps_layout = QVBoxLayout(steps)
        steps_layout.setContentsMargins(14, 12, 14, 12)
        steps_layout.setSpacing(4)
        steps_title = QLabel("Как это работает")
        steps_title.setObjectName("CardCaption")
        steps_layout.addWidget(steps_title)
        for number, text in (
            ("1.", "Ключи добавляются в резервный кошелек локального демона."),
            ("2.", "Мастер проверяет баланс и количество найденных входов."),
            ("3.", "Средства отправляются на указанный Phoenix-адрес."),
        ):
            row_label = QLabel(f"{number} {text}")
            row_label.setObjectName("HintText")
            row_label.setWordWrap(True)
            steps_layout.addWidget(row_label)
        layout.addWidget(steps)

        self.result = QLabel("")
        self.result.setObjectName("HintText")
        self.result.setWordWrap(True)
        layout.addWidget(self.result)

        self.progress = TaskProgress()
        self.progress.setVisible(False)
        layout.addWidget(self.progress)

        layout.addStretch(1)
        layout.addWidget(Divider())
        buttons = QHBoxLayout()
        close = QPushButton("Закрыть")
        close.setObjectName("GhostButton")
        close.clicked.connect(self.reject)
        self.scan_button = QPushButton("Импортировать ключи")
        self.scan_button.setObjectName("GhostButton")
        self.scan_button.setToolTip(
            "Добавить ключи в резервный кошелек и узнать баланс"
        )
        self.scan_button.clicked.connect(self._scan)
        self.sweep_button = QPushButton("Перевести в Phoenix")
        self.sweep_button.setObjectName("AccentButton")
        self.sweep_button.setToolTip("Вывести весь найденный баланс на указанный адрес")
        self.sweep_button.setEnabled(False)
        self.sweep_button.clicked.connect(self._sweep)
        buttons.addWidget(close)
        buttons.addStretch(1)
        buttons.addWidget(self.scan_button)
        buttons.addWidget(self.sweep_button)
        layout.addLayout(buttons)

    def _build_wif_page(self) -> QWidget:
        """Create the WIF import form."""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 4, 0, 4)
        layout.setSpacing(6)
        caption = QLabel("Приватный ключ WIF")
        caption.setObjectName("CardCaption")
        self.wif = PasswordField()
        self.wif.setPlaceholderText("Начинается с 5 или 9, длина 51-52 символа")
        self.wif.setToolTip("Ключ вводится только в память и не сохраняется")
        layout.addWidget(caption)
        layout.addWidget(self.wif)
        hint = QLabel(
            "WIF можно получить в старом кошельке командой dumpprivkey. "
            "Если ключей несколько, повторите импорт для каждого."
        )
        hint.setObjectName("HintText")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        return page

    def _build_wallet_page(self) -> QWidget:
        """Create the wallet.dat import form."""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 4, 0, 4)
        layout.setSpacing(6)
        caption = QLabel("Файл wallet.dat")
        caption.setObjectName("CardCaption")
        self.wallet_path = PathField(
            mode="file",
            caption="Выбрать",
            filter_text="Кошелек NovaCoin (wallet.dat);;Все файлы (*)",
        )
        self.wallet_path.setToolTip("Копия файла загружается в изолированный демон")
        layout.addWidget(caption)
        layout.addWidget(self.wallet_path)
        pass_caption = QLabel("Пароль wallet.dat, если он зашифрован")
        pass_caption.setObjectName("CardCaption")
        self.wallet_password = PasswordField()
        self.wallet_password.setPlaceholderText("Можно оставить пустым")
        self.wallet_password.setToolTip("Пароль используется только для чтения копии")
        layout.addWidget(pass_caption)
        layout.addWidget(self.wallet_password)
        hint = QLabel(
            "Оригинальный wallet.dat не изменяется. Ключи извлекаются в "
            "изолированном процессе без сети и не покидают компьютер."
        )
        hint.setObjectName("HintText")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        return page

    def _on_mode_changed(self, value: str) -> None:
        """Switch source forms without losing the destination."""
        self.pages.setCurrentIndex(0 if value == "wif" else 1)
        self._report = None
        self._sent = False
        self.sweep_button.setEnabled(False)
        self.result.setText("")

    def _set_busy(self, busy: bool, text: str = "") -> None:
        """Disable actions while a background import runs."""
        self._busy = busy
        self.scan_button.setEnabled(not busy)
        self.sweep_button.setEnabled(
            not busy and self._report is not None and not self._sent
        )
        self.mode.setEnabled(not busy)
        self.progress.setVisible(busy)
        if busy:
            self.progress.set_busy(text)

    def _scan(self) -> None:
        """Import keys in a worker and show the discovered balance."""
        if self._busy:
            return
        try:
            if self.mode.value() == "wif":
                wif = validate_wif(self.wif.text())
                worker = partial(import_wif, self.project, wif)
            else:
                path = Path(self.wallet_path.path())
                if not self.wallet_path.path():
                    raise ValueError("Выберите wallet.dat")
                passphrase = self.wallet_password.text()
                worker = partial(
                    import_wallet_file, self.project, self.settings, path, passphrase
                )
        except ValueError as exc:
            self.result.setText(str(exc))
            return
        self.result.setText("Импорт ключей. Это может занять несколько минут.")
        self._set_busy(True, "Импорт ключей и сканирование блокчейна...")
        run_async(worker, self._on_scan_ok, self._on_error, self._on_done)

    def _on_scan_ok(self, report: object) -> None:
        """Show balance and enable the sweep action."""
        if not isinstance(report, MigrationReport):
            return
        self._report = report
        self.result.setText(
            f"Найдено: {format_nvc(report.balance)} NVC, "
            f"входов: {report.inputs}, ключей: {report.keys}. "
            "Проверьте адрес и нажмите Перевести в Phoenix."
        )
        self.sweep_button.setEnabled(report.balance > 0)
        if report.balance <= 0:
            self.result.setText(
                "Ключи импортированы, но баланс не найден. "
                "Демон мог еще не синхронизироваться; повторите позже."
            )

    def _on_error(self, error: object) -> None:
        """Show a safe error without exposing key material."""
        self.result.setText(str(error)[:500])

    def _on_done(self) -> None:
        """Restore controls after a worker finishes."""
        self._set_busy(False)
        if self.progress.bar.maximum() == 0:
            self.progress.finish("Импорт завершен")

    def _sweep(self) -> None:
        """Confirm and send the whole imported balance to Phoenix."""
        if self._busy or self._report is None:
            return
        try:
            destination = validate_destination(self.destination.text(), self.project)
        except ValueError as exc:
            self.result.setText(str(exc))
            return
        amount = self._report.balance - Decimal("0.001")
        if amount <= 0:
            self.result.setText("Недостаточно средств для вывода.")
            return
        answer = QMessageBox.question(
            self,
            "Перевод в Phoenix",
            f"Вывести {format_nvc(amount)} NVC на адрес\n{destination}?\n\n"
            "Комиссия старого кошелька удерживается автоматически.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._set_busy(True, "Отправка перевода...")
        run_async(
            lambda: sweep_all(self.project, destination),
            self._on_sweep_ok,
            self._on_error,
            self._on_done,
        )

    def _on_sweep_ok(self, result: object) -> None:
        """Show the txid and notify pages to refresh."""
        txid, amount = result if isinstance(result, tuple) else ("", Decimal("0"))
        self.result.setText(
            f"Отправлено {format_nvc(amount)} NVC. TxID: {shorten_txid(txid)}. "
            "После подтверждения баланс появится в Phoenix."
        )
        self._sent = True
        self.sweep_button.setEnabled(False)
        self.completed.emit()
