"""Progress, spinner and connection indicator widgets."""

from __future__ import annotations

from PyQt6.QtCore import QRectF, QTimer, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPen
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from .icons import icon


class Spinner(QWidget):
    """A small indeterminate arc used while work is running."""

    def __init__(
        self, size: int = 18, color: str = "#FF8A3D", parent: QWidget | None = None
    ) -> None:
        """Initialize the Spinner instance."""
        super().__init__(parent)
        self._color = QColor(color)
        self._angle = 0
        self._active = False
        self._timer = QTimer(self)
        self._timer.setInterval(24)
        self._timer.timeout.connect(self._tick)
        self.setFixedSize(size, size)
        self.hide()

    def set_color(self, color: str) -> None:
        """Change the arc color."""
        self._color = QColor(color)
        self.update()

    def start(self) -> None:
        """Start spinning."""
        self._active = True
        if not self._timer.isActive():
            self._timer.start()
        self.show()

    def stop(self) -> None:
        """Stop and hide the spinner."""
        self._active = False
        self._timer.stop()
        self.hide()

    def is_running(self) -> bool:
        """Return whether the spinner is active."""
        return self._active

    def _tick(self) -> None:
        """Advance the arc angle."""
        self._angle = (self._angle + 9) % 360
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt API
        """Draw the arc with a rounded cap."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        pen = QPen(self._color, 2.2)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        rect = QRectF(self.rect()).adjusted(3.0, 3.0, -3.0, -3.0)
        painter.drawArc(rect, self._angle * 16, 260 * 16)
        painter.end()


class StatusDot(QWidget):
    """A small colored status circle."""

    def __init__(
        self, color: str = "#748094", size: int = 10, parent: QWidget | None = None
    ) -> None:
        """Initialize the StatusDot instance."""
        super().__init__(parent)
        self._color = QColor(color)
        self.setFixedSize(size, size)

    def set_color(self, color: str) -> None:
        """Update the dot color."""
        self._color = QColor(color)
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt API
        """Draw a filled circle."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self._color)
        painter.drawEllipse(self.rect().adjusted(1, 1, -1, -1))
        painter.end()


class ConnectionBadge(QWidget):
    """Dot plus label describing the proxy connection."""

    def __init__(self, parent: QWidget | None = None) -> None:
        """Initialize the ConnectionBadge instance."""
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self.dot = StatusDot("#748094", 9, self)
        self.label = QLabel("Проверка связи", self)
        self.label.setObjectName("Muted")
        layout.addWidget(self.dot)
        layout.addWidget(self.label)
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)

    def set_status(self, text: str, color: str) -> None:
        """Update the indicator text and color."""
        self.dot.set_color(color)
        self.label.setText(text)

    def set_busy(self, text: str = "Подключение...") -> None:
        """Show a neutral in-progress state."""
        self.set_status(text, "#73BEFF")


class BusyIndicator(QWidget):
    """Spinner with an optional caption."""

    def __init__(
        self,
        text: str = "Загрузка...",
        color: str = "#FF8A3D",
        parent: QWidget | None = None,
    ) -> None:
        """Initialize the BusyIndicator instance."""
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        self.spinner = Spinner(16, color, self)
        self.label = QLabel(text, self)
        self.label.setObjectName("Muted")
        layout.addWidget(self.spinner)
        layout.addWidget(self.label)
        self.spinner.hide()

    def start(self, text: str | None = None) -> None:
        """Show the spinner and update the caption."""
        if text is not None:
            self.label.setText(text)
        self.spinner.start()
        self.show()

    def stop(self) -> None:
        """Hide the indicator."""
        self.spinner.stop()
        self.hide()


class TaskProgress(QFrame):
    """A labeled progress bar with an optional cancel button."""

    cancelRequested = pyqtSignal()

    def __init__(self, parent: QWidget | None = None, cancelable: bool = False) -> None:
        """Initialize the TaskProgress instance."""
        super().__init__(parent)
        self.setObjectName("SoftCard")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(6)
        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(8)
        self.status_label = QLabel("Готово", self)
        self.status_label.setObjectName("Muted")
        self.counter_label = QLabel("", self)
        self.counter_label.setObjectName("HintText")
        top.addWidget(self.status_label, 1)
        top.addWidget(self.counter_label)
        self.cancel_button = QPushButton(self)
        self.cancel_button.setObjectName("IconButton")
        self.cancel_button.setIcon(icon("close", "#A7B1C2", 14))
        self.cancel_button.setFixedSize(24, 24)
        self.cancel_button.setToolTip("Отменить")
        self.cancel_button.setVisible(cancelable)
        self.cancel_button.clicked.connect(self.cancelRequested.emit)
        top.addWidget(self.cancel_button)
        layout.addLayout(top)
        self.bar = QProgressBar(self)
        self.bar.setObjectName("LargeProgress")
        self.bar.setTextVisible(False)
        self.bar.setRange(0, 1000)
        self.bar.setValue(0)
        layout.addWidget(self.bar)

    def set_status(self, text: str) -> None:
        """Update the caption above the bar."""
        self.status_label.setText(text)

    def set_progress(self, current: int, total: int) -> None:
        """Set a determinate value and counter caption."""
        total = max(1, int(total))
        current = max(0, min(total, int(current)))
        self.bar.setRange(0, 1000)
        self.bar.setValue(int(current * 1000 / total))
        self.counter_label.setText(f"{current} / {total}")

    def set_percent(self, percent: int, caption: str = "") -> None:
        """Set a percentage value with an optional caption."""
        self.bar.setRange(0, 100)
        self.bar.setValue(max(0, min(100, int(percent))))
        self.counter_label.setText(caption)

    def set_busy(self, text: str = "Выполняется...") -> None:
        """Switch to an indeterminate animation."""
        self.status_label.setText(text)
        self.counter_label.setText("")
        self.bar.setRange(0, 0)

    def finish(self, text: str = "Готово") -> None:
        """Fill the bar and show a completion caption."""
        self.bar.setRange(0, 100)
        self.bar.setValue(100)
        self.status_label.setText(text)
        self.counter_label.setText("")
        self.cancel_button.setVisible(False)
