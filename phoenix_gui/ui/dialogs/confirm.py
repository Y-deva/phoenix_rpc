"""Modal confirmation for a send operation."""

from __future__ import annotations

from decimal import Decimal

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

from ...core.formatting import format_nvc, shorten_address
from ..widgets.card import Divider, KeyValueRow, Pill
from ..widgets.icons import icon


class ConfirmSendDialog(QDialog):
    """Show every consequence of a transfer before the user commits."""

    def __init__(
        self,
        address: str,
        amount: Decimal,
        fee: Decimal,
        change: Decimal,
        comment: str,
        input_count: int,
        expert: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        """Initialize the ConfirmSendDialog instance."""
        super().__init__(parent)
        self.setWindowTitle("Подтверждение отправки")
        self.setModal(True)
        self.setMinimumWidth(500)
        self._build(address, amount, fee, change, comment, input_count, expert)
        QShortcut(QKeySequence("Ctrl+Return"), self, activated=self.accept)
        QShortcut(QKeySequence("Ctrl+Enter"), self, activated=self.accept)

    def _build(
        self,
        address: str,
        amount: Decimal,
        fee: Decimal,
        change: Decimal,
        comment: str,
        input_count: int,
        expert: bool,
    ) -> None:
        """Create the dialog content."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 20)
        layout.setSpacing(14)

        heading = QHBoxLayout()
        heading.setSpacing(10)
        badge = QLabel()
        badge.setPixmap(icon("send", "#FF8A3D", 22).pixmap(22, 22))
        badge.setFixedSize(40, 40)
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge.setObjectName("IconBadge")
        title_box = QVBoxLayout()
        title_box.setSpacing(1)
        title = QLabel("Отправить транзакцию?")
        title.setObjectName("SectionTitle")
        subtitle = QLabel(
            "Проверьте адрес и сумму. Отменить подтвержденную транзакцию нельзя."
        )
        subtitle.setObjectName("Muted")
        subtitle.setWordWrap(True)
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        heading.addWidget(badge, 0, Qt.AlignmentFlag.AlignTop)
        heading.addLayout(title_box, 1)
        layout.addLayout(heading)

        amount_label = QLabel(f"{format_nvc(amount)}")
        self.amount_label = amount_label
        amount_label.setObjectName("HeroValue")
        amount_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(amount_label)

        address_card = QWidget()
        address_card.setObjectName("SoftCard")
        address_layout = QVBoxLayout(address_card)
        address_layout.setContentsMargins(14, 12, 14, 12)
        address_layout.setSpacing(3)
        address_caption = QLabel("Получатель")
        address_caption.setObjectName("CardCaption")
        address_value = QLabel(shorten_address(address, 18, 12))
        self.address_label = address_value
        address_value.setObjectName("MonoStrong")
        address_value.setToolTip(address)
        address_value.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        address_full = QLabel(address)
        address_full.setObjectName("HintText")
        address_full.setWordWrap(True)
        address_full.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        address_layout.addWidget(address_caption)
        address_layout.addWidget(address_value)
        address_layout.addWidget(address_full)
        layout.addWidget(address_card)

        rows = QWidget()
        rows_layout = QVBoxLayout(rows)
        rows_layout.setContentsMargins(2, 0, 2, 0)
        rows_layout.setSpacing(6)
        rows_layout.addWidget(KeyValueRow("Комиссия", f"{format_nvc(fee)}"))
        rows_layout.addWidget(KeyValueRow("Итого", f"{format_nvc(amount + fee)}"))
        if change > 0:
            rows_layout.addWidget(KeyValueRow("Сдача", f"{format_nvc(change)}"))
        rows_layout.addWidget(KeyValueRow("Входов", str(input_count)))
        if comment:
            rows_layout.addWidget(KeyValueRow("Комментарий", comment))
        layout.addWidget(rows)

        if expert:
            layout.addWidget(Divider())
            note = QLabel(
                "Экспертный режим: входы выбраны вручную. Подпись выполнит прокси, "
                "приватные ключи не покидают кошелек."
            )
            note.setObjectName("HintText")
            note.setWordWrap(True)
            layout.addWidget(note)

        fee_pill_row = QHBoxLayout()
        fee_pill_row.addStretch(1)
        fee_ratio = (fee / amount * 100) if amount > 0 else Decimal("0")
        if fee_ratio >= 5:
            pill = Pill("Высокая комиссия", "warning")
            pill.setToolTip("Комиссия превышает 5 процентов суммы перевода.")
            fee_pill_row.addWidget(pill)
        fee_pill_row.addStretch(1)
        layout.addLayout(fee_pill_row)

        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        cancel = QPushButton("Отмена")
        cancel.setObjectName("GhostButton")
        cancel.setToolTip("Закрыть без отправки (Esc)")
        cancel.clicked.connect(self.reject)
        confirm = QPushButton("Подписать и отправить")
        confirm.setObjectName("AccentButton")
        confirm.setToolTip("Создать, подписать и транслировать транзакцию (Ctrl+Enter)")
        confirm.clicked.connect(self.accept)
        buttons.addWidget(cancel)
        buttons.addStretch(1)
        buttons.addWidget(confirm)
        layout.addLayout(buttons)
        confirm.setDefault(True)
