"""Reusable transaction row for the dashboard and history lists."""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from ...core.formatting import format_signed_nvc, format_timestamp, shorten_address
from ...rpc.models import Transaction
from .card import IconBadge, Pill


def _kind_icon(kind: str) -> tuple[str, str]:
    """Return an icon name and semantic color for a transaction kind."""
    if kind == "receive":
        return "receive", "positive"
    if kind == "send":
        return "send", "negative"
    if kind == "mine":
        return "coins", "positive"
    if kind == "immature":
        return "clock", "warning"
    return "info", "muted"


class TransactionRow(QFrame):
    """One clickable history entry with amount and status."""

    clicked = pyqtSignal(object)

    def __init__(
        self,
        transaction: Transaction,
        tokens: dict[str, str],
        compact: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        """Initialize the TransactionRow instance."""
        super().__init__(parent)
        self.transaction = transaction
        self.tokens = tokens
        self.setObjectName("DataRow")
        self.setProperty("hoverable", True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(self._tooltip())
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 7, 8, 7)
        layout.setSpacing(10)
        icon_name, color_name = _kind_icon(transaction.kind)
        badge = IconBadge(
            icon_name, tokens.get(color_name, tokens.get("muted", "#A7B1C2")), 34
        )
        layout.addWidget(badge)
        text_column = QVBoxLayout()
        text_column.setContentsMargins(0, 0, 0, 0)
        text_column.setSpacing(1)
        title = QLabel(transaction.label)
        title.setObjectName("CardTitle")
        subtitle_text = format_timestamp(transaction.timestamp)
        if transaction.address:
            subtitle_text = f"{subtitle_text} / {shorten_address(transaction.address)}"
        subtitle = QLabel(subtitle_text)
        subtitle.setObjectName("HintText")
        text_column.addWidget(title)
        text_column.addWidget(subtitle)
        layout.addLayout(text_column, 1)
        if not compact:
            level = {
                "confirmed": "success",
                "pending": "warning",
                "immature": "warning",
                "conflicted": "danger",
            }.get(transaction.status, "neutral")
            if transaction.status != "confirmed":
                layout.addWidget(Pill(transaction.status_label, level))
        amount = QLabel(f"{format_signed_nvc(transaction.amount)} NVC")
        object_name = "AmountPositive" if transaction.amount >= 0 else "AmountNegative"
        amount.setObjectName(object_name)
        amount.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        amount.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(amount)

    def _tooltip(self) -> str:
        """Build a compact tooltip with technical details."""
        transaction = self.transaction
        parts = [
            f"Категория: {transaction.label}",
            f"TXID: {transaction.txid}",
            f"Подтверждений: {transaction.confirmations}",
        ]
        if transaction.address:
            parts.append(f"Адрес: {transaction.address}")
        if transaction.comment:
            parts.append(f"Комментарий: {transaction.comment}")
        return "\n".join(parts)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 - Qt API
        """Emit the transaction when clicked with the left button."""
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.transaction)
        super().mouseReleaseEvent(event)
