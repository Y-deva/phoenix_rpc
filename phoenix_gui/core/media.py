"""Animated, dimmed backdrop with local image and video support.

The artwork is painted behind the whole interface. A generated abstract
backdrop is always available; a user can drop a local image or video on
the window. Media never leaves the machine, and unsupported files fall
back silently to the generated artwork.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Mapping

from PyQt6.QtCore import QPointF, QSize, Qt, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import (
    QColor,
    QImage,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)
from PyQt6.QtWidgets import QWidget

try:  # QtMultimedia is present in the standard PyQt6 wheel.
    from PyQt6.QtMultimedia import QAudioOutput, QMediaPlayer, QVideoSink
except ImportError:  # pragma: no cover - graceful degradation on minimal builds
    QAudioOutput = QMediaPlayer = QVideoSink = None  # type: ignore[assignment]

from ..settings import Settings

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tif", ".tiff"}
VIDEO_SUFFIXES = {".mp4", ".m4v", ".webm", ".mkv", ".mov", ".avi", ".wmv"}


def _color(tokens: Mapping[str, str], name: str, fallback: str = "#101014") -> QColor:
    """Return a theme color with a safe fallback."""
    value = tokens.get(name, fallback)
    color = QColor(value)
    if not color.isValid():
        color = QColor(fallback)
    return color


def _with_alpha(color: QColor, alpha: int) -> QColor:
    """Return a copy of a color with a new alpha component."""
    result = QColor(color)
    result.setAlpha(max(0, min(255, int(alpha))))
    return result


def render_default_artwork(tokens: Mapping[str, str], size: QSize) -> QPixmap:
    """Render the generated geometric backdrop for a given size."""
    width = max(1, size.width())
    height = max(1, size.height())
    pixmap = QPixmap(width, height)
    pixmap.fill(_color(tokens, "bg"))
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

    accent = _color(tokens, "accent", "#ff8a3d")
    border = _color(tokens, "border", "#2a2a2a")
    short = min(width, height)

    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(_with_alpha(accent, 12))
    painter.drawEllipse(
        QPointF(width * 0.82, height * 0.18), short * 0.38, short * 0.38
    )
    painter.setBrush(_with_alpha(accent, 8))
    painter.drawEllipse(QPointF(width * 0.1, height * 0.88), short * 0.28, short * 0.28)

    grid_pen = _with_alpha(border, 30)
    painter.setPen(grid_pen)
    step = max(52, int(short / 13))
    for x in range(0, width + step, step):
        painter.drawLine(x, 0, x, height)
    for y in range(0, height + step, step):
        painter.drawLine(0, y, width, y)

    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.setPen(_with_alpha(accent, 52))
    radius = int(short * 0.31)
    center = QPointF(width * 0.82, height * 0.24)
    painter.drawEllipse(center, radius, radius)
    painter.setPen(_with_alpha(accent, 26))
    painter.drawEllipse(center, int(radius * 1.2), int(radius * 1.2))

    painter.setPen(QPen(_with_alpha(accent, 24), 1))
    path = QPainterPath()
    path.moveTo(width * 0.58, height)
    path.lineTo(width, height * 0.36)
    painter.drawPath(path)
    painter.end()
    return pixmap


class MediaBackdrop(QWidget):
    """Full-window backdrop that honours theme and media settings."""

    mediaError = pyqtSignal(str)
    mediaDropped = pyqtSignal(str)
    _MEDIA_KEYS = {
        "media/enabled",
        "media/path",
        "media/dim",
        "media/blur",
        "media/pan",
        "appearance/animations",
    }

    def __init__(
        self, settings: Settings, theme: Any = None, parent: QWidget | None = None
    ) -> None:
        """Initialize the MediaBackdrop instance."""
        super().__init__(parent)
        self._settings = settings
        self._tokens: Mapping[str, str] = getattr(theme, "tokens", {}) if theme else {}
        self._dark = bool(getattr(theme, "dark", True))
        self._image: QImage | None = None
        self._source_path = ""
        self._cached: QPixmap | None = None
        self._cache_key: tuple[int, int, str, int, bool] | None = None
        self._phase = 0.0
        self._error_reported = ""
        self._player = None
        self._audio = None
        self._sink = None
        self._frame: QImage | None = None
        self._pan_timer = QTimer(self)
        self._pan_timer.setInterval(45)
        self._pan_timer.timeout.connect(self._advance_pan)
        self.setAcceptDrops(True)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        settings.changed.connect(self._on_setting_changed)
        self.refresh_media()

    @property
    def source_path(self) -> str:
        """Return the media file currently in use."""
        return self._source_path

    @property
    def has_media(self) -> bool:
        """Return whether a custom image or video is active."""
        return self._image is not None or self._frame is not None

    def set_theme(self, theme: Any) -> None:
        """Apply a theme and invalidate the generated artwork cache."""
        self._tokens = getattr(theme, "tokens", {}) if theme else {}
        self._dark = bool(getattr(theme, "dark", True))
        self._cached = None
        self._cache_key = None
        self.update()

    def _on_setting_changed(self, key: str, _value: object) -> None:
        """Reload only when a backdrop-related preference changed."""
        if key in self._MEDIA_KEYS:
            self.refresh_media()

    def refresh_media(self) -> None:
        """Reload the media source and restart the pan animation."""
        enabled = self._settings.media_enabled
        path_text = self._settings.media_path.strip() if enabled else ""
        path = Path(path_text).expanduser() if path_text else None
        if path is None or not path.is_file():
            if path_text:
                self._report_error(f"Файл фона не найден: {path_text}")
            self._stop_video()
            self._image = None
            self._source_path = ""
        elif path.suffix.lower() in VIDEO_SUFFIXES:
            self._image = None
            self._source_path = str(path)
            self._start_video(path)
        else:
            self._stop_video()
            image = QImage(str(path))
            if image.isNull():
                self._report_error(f"Не удалось открыть изображение: {path.name}")
                self._image = None
                self._source_path = ""
            else:
                self._image = image
                self._source_path = str(path)
                self._error_reported = ""
        self._cached = None
        self._cache_key = None
        self._update_pan_timer()
        self.update()

    def _report_error(self, message: str) -> None:
        """Emit a media error once per distinct message."""
        if message != self._error_reported:
            self._error_reported = message
            self.mediaError.emit(message)

    def _update_pan_timer(self) -> None:
        """Run the pan timer only when there is media to pan."""
        should_pan = (
            self._settings.media_enabled
            and self._settings.media_pan
            and self._settings.animations
            and self.isVisible()
            and (self._image is not None or self._frame is not None)
        )
        if should_pan and not self._pan_timer.isActive():
            self._pan_timer.start()
        elif not should_pan and self._pan_timer.isActive():
            self._pan_timer.stop()

    def _advance_pan(self) -> None:
        """Advance the slow Ken Burns movement."""
        self._phase = (self._phase + 0.0022) % (math.pi * 2)
        self.update()

    def showEvent(self, event) -> None:  # noqa: N802 - Qt API
        """Start animation when the window becomes visible."""
        super().showEvent(event)
        self._update_pan_timer()

    def hideEvent(self, event) -> None:  # noqa: N802 - Qt API
        """Pause animation while the window is hidden."""
        self._pan_timer.stop()
        super().hideEvent(event)

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt API
        """Invalidate the scaled cache when the window changes size."""
        self._cached = None
        self._cache_key = None
        super().resizeEvent(event)

    def _start_video(self, path: Path) -> None:
        """Create a muted looping player for a local video."""
        self._stop_video()
        if QMediaPlayer is None or QVideoSink is None or QAudioOutput is None:
            self._report_error("Воспроизведение видео недоступно в этой сборке Qt")
            return
        try:
            self._player = QMediaPlayer(self)
            self._audio = QAudioOutput(self)
            self._audio.setMuted(True)
            self._player.setAudioOutput(self._audio)
            self._sink = QVideoSink(self)
            self._player.setVideoOutput(self._sink)
            self._sink.videoFrameChanged.connect(self._on_video_frame)
            self._player.setSource(QUrl.fromLocalFile(str(path)))
            self._player.setLoops(QMediaPlayer.Loops.Infinite)
            self._player.play()
        except Exception as exc:  # pragma: no cover - platform multimedia quirks
            self._report_error(f"Не удалось воспроизвести видео: {exc}")
            self._stop_video()

    def _stop_video(self) -> None:
        """Stop and release the video player."""
        if self._player is not None:
            try:
                self._player.stop()
                self._player.setSource(QUrl())
            except Exception:
                pass
            self._player.deleteLater()
        self._player = None
        self._audio = None
        self._sink = None
        self._frame = None

    def _on_video_frame(self, frame: Any) -> None:
        """Keep the latest decoded video frame."""
        if not frame.isValid():
            return
        image = frame.toImage()
        if image.isNull():
            return
        self._frame = image
        self._cached = None
        self._cache_key = None
        self.update()

    def _blurred(self, image: QImage, radius: int) -> QImage:
        """Use fast down/up scaling as a cheap, good-looking blur."""
        if radius <= 0:
            return image
        factor = max(2, int(radius * 0.9))
        small = image.scaled(
            max(1, image.width() // factor),
            max(1, image.height() // factor),
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        return small.scaled(
            image.width(),
            image.height(),
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )

    def _cover_pixmap(self, image: QImage, overscan: float = 1.0) -> QPixmap:
        """Scale and crop an image so it fills the widget without gaps."""
        width = max(1, self.width())
        height = max(1, self.height())
        target_width = int(width * overscan)
        target_height = int(height * overscan)
        scaled = image.scaled(
            target_width,
            target_height,
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        )
        x = max(0, (scaled.width() - target_width) // 2)
        y = max(0, (scaled.height() - target_height) // 2)
        cropped = scaled.copy(x, y, target_width, target_height)
        return QPixmap.fromImage(cropped)

    def _ensure_cache(self) -> QPixmap | None:
        """Build and cache the current backdrop image."""
        image = self._image if self._image is not None else self._frame
        if image is None:
            return None
        key = (
            self.width(),
            self.height(),
            self._source_path,
            self._settings.media_blur,
            self._settings.media_pan,
        )
        if self._cached is not None and self._cache_key == key:
            return self._cached
        processed = self._blurred(image, self._settings.media_blur)
        self._cached = self._cover_pixmap(
            processed, 1.07 if self._settings.media_pan else 1.0
        )
        self._cache_key = key
        return self._cached

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt API
        """Paint artwork, media and a readability overlay."""
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        painter.fillRect(self.rect(), _color(self._tokens, "bg"))
        media = self._ensure_cache() if self._settings.media_enabled else None
        if media is not None:
            if self._settings.media_pan:
                span_x = max(0, media.width() - self.width())
                span_y = max(0, media.height() - self.height())
                offset_x = int((math.sin(self._phase) * 0.5 + 0.5) * span_x)
                offset_y = int((math.cos(self._phase * 0.7) * 0.5 + 0.5) * span_y)
                painter.drawPixmap(-offset_x, -offset_y, media)
            else:
                painter.drawPixmap(0, 0, media)
        else:
            if self._cached is None or self._cache_key != (
                "generated",
                self.width(),
                self.height(),
            ):
                self._cached = render_default_artwork(self._tokens, self.size())
                self._cache_key = ("generated", self.width(), self.height())
            painter.drawPixmap(0, 0, self._cached)

        if media is not None:
            tint = _color(self._tokens, "bg")
            alpha = int(255 * self._settings.media_dim / 100)
            painter.fillRect(self.rect(), _with_alpha(tint, alpha))
            painter.fillRect(self.rect(), _with_alpha(tint, 26))
        painter.end()

    def dragEnterEvent(self, event) -> None:  # noqa: N802 - Qt API
        """Accept local images and videos dropped on the window."""
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                suffix = Path(url.toLocalFile()).suffix.lower()
                if suffix in IMAGE_SUFFIXES or suffix in VIDEO_SUFFIXES:
                    event.acceptProposedAction()
                    return
        event.ignore()

    def dropEvent(self, event) -> None:  # noqa: N802 - Qt API
        """Emit the path of the first supported dropped file."""
        for url in event.mimeData().urls():
            path = Path(url.toLocalFile())
            if (
                path.is_file()
                and path.suffix.lower() in IMAGE_SUFFIXES | VIDEO_SUFFIXES
            ):
                self.mediaDropped.emit(str(path))
                event.acceptProposedAction()
                return
        event.ignore()
