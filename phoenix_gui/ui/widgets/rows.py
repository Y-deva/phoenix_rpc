"""Reusable transaction row for the dashboard and history lists."""

from __future__ import annotations

from typing import Any

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
        translations: Any = None,
    ) -> None:
        """Initialize the TransactionRow instance."""
        super().__init__(parent)
        self.transaction = transaction
        self.tokens = tokens
        self._translations = translations
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
        title_text = self._tr(transaction.label)
        title = QLabel(title_text)
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
                layout.addWidget(Pill(self._tr(transaction.status_label), level))
        self.amount_label = QLabel(f"{format_signed_nvc(transaction.amount)} NVC")
        object_name = "AmountPositive" if transaction.amount >= 0 else "AmountNegative"
        self.amount_label.setObjectName(object_name)
        self.amount_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        self.amount_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        layout.addWidget(self.amount_label)

    def _tr(self, text: str) -> str:
        """Translate a label when a manager is available."""
        if self._translations is None:
            return text
        return self._translations.tr(text)

    def _tooltip(self) -> str:
        """Build a compact tooltip with technical details."""
        transaction = self.transaction
        parts = [
            f"{self._tr('Категория')}: {self._tr(transaction.label)}",
            f"TXID: {transaction.txid}",
            f"{self._tr('Подтверждений')}: {transaction.confirmations}",
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
