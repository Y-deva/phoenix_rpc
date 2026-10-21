"""Read-only transaction details dialog."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ...core.formatting import (
    format_json,
    format_nvc,
    format_timestamp,
    shorten_txid,
)
from ...rpc.models import Transaction
from ..widgets.card import Divider, KeyValueRow, Pill
from ..widgets.icons import icon


class TxDetailsDialog(QDialog):
    """Display every known field of a history entry."""

    def __init__(
        self,
        transaction: Transaction,
        tokens: dict[str, str],
        verbosity: int = 1,
        parent: QWidget | None = None,
    ) -> None:
        """Initialize the TxDetailsDialog instance."""
        super().__init__(parent)
        self._transaction = transaction
        self._tokens = tokens
        self.setWindowTitle("Детали транзакции")
        self.setModal(True)
        self.setMinimumSize(560, 560)
        self.resize(620, 680)
        self._build(transaction, verbosity)
        QShortcut(QKeySequence("Ctrl+C"), self, activated=self._copy_txid)
        QShortcut(QKeySequence("Esc"), self, activated=self.reject)

    def _build(self, transaction: Transaction, verbosity: int) -> None:
        """Create the detail layout."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 20)
        layout.setSpacing(12)

        header = QHBoxLayout()
        header.setSpacing(10)
        badge = QLabel()
        color = {
            "receive": self._tokens.get("positive", "#4ED19E"),
            "send": self._tokens.get("accent", "#FF8A3D"),
            "mine": self._tokens.get("warning", "#F3C969"),
            "immature": self._tokens.get("warning", "#F3C969"),
        }.get(transaction.kind, self._tokens.get("muted", "#A7B1C2"))
        icon_name = {"receive": "receive", "send": "send", "mine": "coins"}.get(
            transaction.kind, "transactions"
        )
        badge.setPixmap(icon(icon_name, color, 24).pixmap(24, 24))
        badge.setFixedSize(44, 44)
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge.setObjectName("IconBadge")
        heading = QVBoxLayout()
        heading.setSpacing(2)
        title = QLabel(transaction.label)
        title.setObjectName("SectionTitle")
        subtitle = QLabel(
            format_timestamp(transaction.timestamp, "%d.%m.%Y %H:%M:%S")
            if transaction.timestamp
            else "Время неизвестно"
        )
        subtitle.setObjectName("Muted")
        heading.addWidget(title)
        heading.addWidget(subtitle)
        header.addWidget(badge, 0, Qt.AlignmentFlag.AlignTop)
        header.addLayout(heading, 1)
        status = Pill(transaction.status_label, transaction.status_level)
        header.addWidget(status, 0, Qt.AlignmentFlag.AlignTop)
        layout.addLayout(header)

        amount = QLabel(f"{format_nvc(transaction.amount)}")
        self.amount_label = amount
        amount.setObjectName("HeroValue")
        amount.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(amount)

        details = QWidget()
        details_layout = QVBoxLayout(details)
        details_layout.setContentsMargins(0, 0, 0, 0)
        details_layout.setSpacing(7)
        self.txid_row = KeyValueRow("TxID", shorten_txid(transaction.txid), mono=True)
        details_layout.addWidget(self.txid_row)
        details_layout.addWidget(
            KeyValueRow("Адрес", transaction.address or "-", mono=True)
        )
        details_layout.addWidget(KeyValueRow("Аккаунт", transaction.account or "-"))
        details_layout.addWidget(KeyValueRow("Тип", transaction.category))
        details_layout.addWidget(
            KeyValueRow("Комиссия", f"{format_nvc(transaction.fee)}")
        )
        details_layout.addWidget(
            KeyValueRow("Подтверждения", str(transaction.confirmations))
        )
        details_layout.addWidget(
            KeyValueRow(
                "Высота блока",
                str(transaction.block_height)
                if transaction.block_height is not None
                else "-",
            )
        )
        if transaction.comment:
            details_layout.addWidget(KeyValueRow("Комментарий", transaction.comment))
        layout.addWidget(details)

        layout.addWidget(Divider())
        if verbosity >= 2 and transaction.raw:
            raw_title = QLabel("Сырые данные RPC")
            raw_title.setObjectName("CardCaption")
            layout.addWidget(raw_title)
            raw_view = QPlainTextEdit()
            raw_view.setObjectName("ConsoleOutput")
            raw_view.setReadOnly(True)
            raw_view.setPlainText(format_json(transaction.raw))
            raw_view.setMaximumHeight(180)
            raw_view.setToolTip("Полный ответ listtransactions для этой записи")
            layout.addWidget(raw_view, 1)
        else:
            layout.addStretch(1)

        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        copy_button = QPushButton("Копировать TxID")
        copy_button.setObjectName("GhostButton")
        copy_button.setIcon(icon("copy", self._tokens.get("muted", "#A7B1C2"), 15))
        copy_button.setToolTip("Скопировать идентификатор транзакции (Ctrl+C)")
        copy_button.clicked.connect(self._copy_txid)
        close_button = QPushButton("Закрыть")
        close_button.setObjectName("AccentButton")
        close_button.setToolTip("Закрыть окно (Esc)")
        close_button.clicked.connect(self.accept)
        self.copy_hint = QLabel("")
        self.copy_hint.setObjectName("HintText")
        buttons.addWidget(self.copy_hint, 1)
        buttons.addWidget(copy_button)
        buttons.addWidget(close_button)
        layout.addLayout(buttons)

    def _copy_txid(self) -> None:
        """Copy the transaction id to the clipboard."""
        QApplication.clipboard().setText(self._transaction.txid)
        self.copy_hint.setText("TxID скопирован")
