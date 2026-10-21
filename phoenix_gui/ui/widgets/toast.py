"""Non-blocking toast notifications anchored to the window corner."""

from __future__ import annotations

from PyQt6.QtCore import (
    QEasingCurve,
    QEvent,
    QObject,
    QPoint,
    QPropertyAnimation,
    QTimer,
    Qt,
    pyqtSignal,
)
from PyQt6.QtWidgets import (
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from .icons import icon

LEVEL_COLORS = {
    "success": "#3DD6A0",
    "error": "#FF7070",
    "warning": "#F2C86B",
    "info": "#73BEFF",
}
LEVEL_ICONS = {
    "success": "check",
    "error": "error",
    "warning": "warning",
    "info": "info",
}
OBJECT_NAMES = {
    "success": "ToastSuccess",
    "error": "ToastError",
    "warning": "ToastInfo",
    "info": "ToastInfo",
}


class Toast(QFrame):
    """A single notification card."""

    closed = pyqtSignal(object)

    def __init__(
        self,
        title: str,
        message: str,
        level: str,
        duration: int = 4200,
        parent: QWidget | None = None,
        animations: bool = True,
    ) -> None:
        """Initialize the Toast instance."""
        super().__init__(parent)
        self._animations = animations
        self.setObjectName(OBJECT_NAMES.get(level, "ToastInfo"))
        self.setFixedWidth(360)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum)
        self._level = level if level in LEVEL_COLORS else "info"
        self._closing = False
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 12, 10, 12)
        layout.setSpacing(10)
        self.icon_label = QLabel(self)
        self.icon_label.setPixmap(
            icon(LEVEL_ICONS[self._level], LEVEL_COLORS[self._level], 18).pixmap(18, 18)
        )
        self.icon_label.setFixedSize(24, 24)
        self.icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.icon_label, 0, Qt.AlignmentFlag.AlignTop)
        text_column = QVBoxLayout()
        text_column.setContentsMargins(0, 0, 0, 0)
        text_column.setSpacing(2)
        self.title_label = QLabel(title or "Уведомление", self)
        self.title_label.setObjectName("SectionTitle")
        self.title_label.setStyleSheet(
            "font-size: 10pt; font-weight: 700; background: transparent;"
        )
        self.message_label = QLabel(message, self)
        self.message_label.setObjectName("Muted")
        self.message_label.setWordWrap(True)
        self.message_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        text_column.addWidget(self.title_label)
        text_column.addWidget(self.message_label)
        layout.addLayout(text_column, 1)
        self.close_button = QPushButton(self)
        self.close_button.setObjectName("IconButton")
        self.close_button.setIcon(icon("close", "#A7B1C2", 14))
        self.close_button.setFixedSize(24, 24)
        self.close_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.close_button.setToolTip("Закрыть")
        self.close_button.clicked.connect(self.dismiss)
        layout.addWidget(self.close_button, 0, Qt.AlignmentFlag.AlignTop)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.dismiss)
        if duration > 0:
            self._timer.start(duration)
        self._effect = QGraphicsOpacityEffect(self)
        self._effect.setOpacity(0.0)
        self.setGraphicsEffect(self._effect)
        self._fade = QPropertyAnimation(self._effect, b"opacity", self)
        self._fade.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._fade.setDuration(180)

    def fade_in(self) -> None:
        """Animate the card into view, or show it instantly when disabled."""
        if not self._animations:
            self._effect.setOpacity(1.0)
            return
        self._fade.stop()
        self._fade.setStartValue(0.0)
        self._fade.setEndValue(1.0)
        self._fade.start()

    def dismiss(self) -> None:
        """Fade out and report closure."""
        if self._closing:
            return
        self._closing = True
        self._timer.stop()
        if not self._animations:
            self._finish()
            return
        self._fade.stop()
        self._fade.setStartValue(self._effect.opacity())
        self._fade.setEndValue(0.0)
        self._fade.finished.connect(self._finish)
        self._fade.start()

    def _finish(self) -> None:
        """Emit closure once the fade completes."""
        self.closed.emit(self)
        self.deleteLater()

    def enterEvent(self, event) -> None:  # noqa: N802 - Qt API
        """Pause the auto-dismiss timer while the pointer is over the card."""
        self._timer.stop()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802 - Qt API
        """Resume a short dismissal delay after the pointer leaves."""
        if not self._closing:
            self._timer.start(1800)
        super().leaveEvent(event)


class ToastManager(QObject):
    """Owns toast lifetime, stacking and positioning."""

    def __init__(
        self,
        host: QWidget,
        parent: QObject | None = None,
        animations: bool = True,
    ) -> None:
        """Initialize the ToastManager instance."""
        super().__init__(parent)
        self._host = host
        self._animations = animations
        self._toasts: list[Toast] = []
        self._host.installEventFilter(self)

    def set_animations(self, enabled: bool) -> None:
        """Toggle fade animations for future and visible toasts."""
        self._animations = bool(enabled)
        for toast in self._toasts:
            toast._animations = self._animations

    def show(
        self,
        message: str,
        level: str = "info",
        title: str = "",
        duration: int = 4200,
    ) -> Toast:
        """Display a toast, replacing the oldest one when the stack is full."""
        while len(self._toasts) >= 4:
            oldest = self._toasts[0]
            oldest.dismiss()
            self._toasts.remove(oldest)
            oldest.hide()
        toast = Toast(
            title,
            message,
            level,
            duration,
            self._host,
            animations=self._animations,
        )
        toast.closed.connect(self._on_closed)
        self._toasts.append(toast)
        toast.show()
        toast.adjustSize()
        self._reposition()
        toast.fade_in()
        toast.raise_()
        return toast

    def success(
        self, message: str, title: str = "Готово", duration: int = 4200
    ) -> Toast:
        """Show a success toast."""
        return self.show(message, "success", title, duration=duration)

    def error(self, message: str, title: str = "Ошибка", duration: int = 6500) -> Toast:
        """Show an error toast."""
        return self.show(message, "error", title, duration=duration)

    def info(self, message: str, title: str = "", duration: int = 4200) -> Toast:
        """Show an informational toast."""
        return self.show(message, "info", title, duration=duration)

    def warning(
        self, message: str, title: str = "Внимание", duration: int = 5600
    ) -> Toast:
        """Show a warning toast."""
        return self.show(message, "warning", title, duration=duration)

    def shutdown(self) -> None:
        """Detach the resize filter and close remaining notifications."""
        self._host.removeEventFilter(self)
        for toast in list(self._toasts):
            toast._animations = False
            toast.hide()
            toast.deleteLater()
        self._toasts.clear()

    def clear(self) -> None:
        """Dismiss every visible toast."""
        for toast in list(self._toasts):
            toast.dismiss()

    def _on_closed(self, toast: Toast) -> None:
        """Remove a closed toast and re-stack the rest."""
        if toast in self._toasts:
            self._toasts.remove(toast)
        self._reposition()

    def _reposition(self) -> None:
        """Place toasts at the bottom right, newest nearest the corner."""
        margin = 22
        spacing = 10
        bottom = self._host.height() - margin
        for toast in reversed(self._toasts):
            toast.adjustSize()
            height = toast.sizeHint().height()
            toast.setFixedWidth(360)
            toast.move(
                QPoint(self._host.width() - toast.width() - margin, bottom - height)
            )
            bottom -= height + spacing

    def eventFilter(self, watched, event) -> bool:  # noqa: N802 - Qt API
        """Reposition when the host widget is resized."""
        if watched is self._host and event.type() == QEvent.Type.Resize:
            self._reposition()
        return super().eventFilter(watched, event)
