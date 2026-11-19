"""QR code widget rendered without external image libraries."""

from __future__ import annotations

from PyQt6.QtCore import QRectF, QSize, Qt
from PyQt6.QtGui import QColor, QImage, QPainter
from PyQt6.QtWidgets import QSizePolicy, QWidget

try:
    import qrcode
except ImportError:  # pragma: no cover - optional dependency
    qrcode = None


class QrCode(QWidget):
    """Paint a QR matrix scaled to the available square area."""

    def __init__(self, parent: QWidget | None = None) -> None:
        """Initialize the QrCode instance."""
        super().__init__(parent)
        self._matrix: list[list[bool]] = []
        self._text = ""
        self._dark = QColor("#0B111A")
        self._light = QColor("#F7F9FC")
        self.setMinimumSize(160, 160)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt API
        """Preferred square size."""
        return QSize(220, 220)

    def set_data(self, text: str) -> None:
        """Encode text into a QR matrix."""
        self._text = text.strip()
        self._matrix = []
        if self._text and qrcode is not None:
            code = qrcode.QRCode(
                error_correction=qrcode.constants.ERROR_CORRECT_M, border=2, box_size=1
            )
            code.add_data(self._text)
            code.make(fit=True)
            self._matrix = code.get_matrix()
        self.update()

    def set_colors(self, dark: str, light: str) -> None:
        """Set module and background colors."""
        self._dark = QColor(dark)
        self._light = QColor(light)
        self.update()

    def text(self) -> str:
        """Return the encoded payload."""
        return self._text

    def save_png(self, path: str, size: int = 512) -> bool:
        """Render the current matrix to a PNG file, if it has payload data."""
        if not self._matrix:
            return False
        image = QImage(size, size, QImage.Format.Format_ARGB32)
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        self._paint_matrix(painter, QRectF(0, 0, size, size))
        painter.end()
        return image.save(path)

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt API
        """Draw modules centered inside a light quiet zone."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        side = min(self.width(), self.height())
        target = QRectF(
            (self.width() - side) / 2,
            (self.height() - side) / 2,
            side,
            side,
        )
        self._paint_matrix(painter, target)
        painter.end()

    def _paint_matrix(self, painter: QPainter, target: QRectF) -> None:
        """Paint the matrix or a compact placeholder."""
        if not self._matrix:
            card = target.adjusted(10, 10, -10, -10)
            painter.setPen(QColor("#E2E7EF"))
            painter.setBrush(self._light)
            painter.drawRoundedRect(card, 12, 12)
            painter.setPen(QColor("#748094"))
            font = painter.font()
            font.setPointSizeF(10.5)
            painter.setFont(font)
            painter.drawText(
                card.adjusted(22, 22, -22, -22),
                Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap,
                "QR-код появится после создания адреса",
            )
            return
        painter.fillRect(target, self._light)
        rows = len(self._matrix)
        columns = len(self._matrix[0]) if rows else 0
        if not rows or not columns:
            return
        cell = min(target.width() / columns, target.height() / rows)
        offset_x = target.left() + (target.width() - cell * columns) / 2
        offset_y = target.top() + (target.height() - cell * rows) / 2
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self._dark)
        for row_index, row in enumerate(self._matrix):
            for column_index, module in enumerate(row):
                if module:
                    painter.drawRect(
                        QRectF(
                            offset_x + column_index * cell,
                            offset_y + row_index * cell,
                            cell + 0.2,
                            cell + 0.2,
                        )
                    )
