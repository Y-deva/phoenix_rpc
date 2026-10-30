"""Vector icon factory drawn with QPainter.

Keeping icons as code avoids binary assets and makes every glyph follow
the active theme. All geometry is authored on a 24x24 grid.
"""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import (
    QColor,
    QFont,
    QIcon,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)

_ICON_CACHE: dict[tuple[str, str, int], QIcon] = {}
_LOGO_CACHE: dict[tuple[str, int], QPixmap] = {}


def logo_path() -> Path:
    """Return the bundled Phoenix/NovaCoin logo when it is available."""
    return Path(__file__).resolve().parents[3] / "nvc_logo.png"


def brand_logo(size: int = 36) -> QPixmap:
    """Load and cache the supplied project logo, scaled for a widget."""
    path = logo_path()
    key = (str(path), size)
    cached = _LOGO_CACHE.get(key)
    if cached is not None:
        return cached
    pixmap = QPixmap(str(path))
    if pixmap.isNull():
        return QPixmap()
    scaled = pixmap.scaled(
        size,
        size,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
    _LOGO_CACHE[key] = scaled
    return scaled


def _line(painter: QPainter, *points: tuple[float, float]) -> None:
    """Draw a connected polyline."""
    path = QPainterPath(QPointF(*points[0]))
    for point in points[1:]:
        path.lineTo(QPointF(*point))
    painter.drawPath(path)


def _poly(painter: QPainter, *points: tuple[float, float], close: bool = False) -> None:
    """Draw a polygon, optionally closed."""
    path = QPainterPath(QPointF(*points[0]))
    for point in points[1:]:
        path.lineTo(QPointF(*point))
    if close:
        path.closeSubpath()
    painter.drawPath(path)


def _rounded(
    painter: QPainter, x: float, y: float, w: float, h: float, radius: float = 2.0
) -> None:
    """Draw a rounded rectangle outline."""
    painter.drawRoundedRect(QRectF(x, y, w, h), radius, radius)


def _dot(painter: QPainter, x: float, y: float, radius: float = 1.2) -> None:
    """Draw a filled dot."""
    painter.save()
    painter.setBrush(painter.pen().color())
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawEllipse(QPointF(x, y), radius, radius)
    painter.restore()


def _draw(painter: QPainter, name: str) -> None:
    """Draw one named icon using the current pen."""
    if name == "home":
        _poly(painter, (3.5, 11.5), (12, 4), (20.5, 11.5))
        _poly(painter, (6, 10), (6, 20), (18, 20), (18, 10))
        _poly(painter, (10, 20), (10, 14), (14, 14), (14, 20))
    elif name == "send":
        _line(painter, (5, 19), (19, 5))
        _poly(painter, (10, 5), (19, 5), (19, 14))
    elif name == "receive":
        _line(painter, (19, 5), (5, 19))
        _poly(painter, (5, 10), (5, 19), (14, 19))
    elif name == "transactions":
        for y in (6.5, 12, 17.5):
            _dot(painter, 5.5, y, 1.1)
            _line(painter, (9, y), (19, y))
    elif name == "coins":
        _rounded(painter, 4, 4, 16, 6, 3)
        _poly(painter, (4, 10), (4, 17), (20, 17), (20, 10))
        _poly(painter, (4, 17), (4, 20), (20, 20), (20, 17))
        _line(painter, (9, 7), (15, 7))
    elif name == "chart":
        _poly(painter, (3, 3), (3, 21), (21, 21))
        _poly(painter, (6, 16), (10, 10.5), (13.5, 13.5), (19, 6.5))
        _dot(painter, 19, 6.5, 1.4)
    elif name == "terminal":
        _rounded(painter, 3, 4, 18, 16, 3)
        _poly(painter, (7, 9), (10, 12), (7, 15))
        _line(painter, (12.5, 15.5), (17, 15.5))
    elif name == "settings":
        painter.drawEllipse(QPointF(12, 12), 3.2, 3.2)
        painter.drawEllipse(QPointF(12, 12), 8.2, 8.2)
        for dx, dy in (
            (0, -1),
            (0, 1),
            (-1, 0),
            (1, 0),
            (-0.72, -0.72),
            (0.72, -0.72),
            (-0.72, 0.72),
            (0.72, 0.72),
        ):
            painter.drawLine(
                QPointF(12 + dx * 6.0, 12 + dy * 6.0),
                QPointF(12 + dx * 9.6, 12 + dy * 9.6),
            )
    elif name == "search":
        painter.drawEllipse(QPointF(10.5, 10.5), 6.3, 6.3)
        _line(painter, (15.3, 15.3), (20, 20))
    elif name == "refresh":
        painter.drawArc(QRectF(4, 4, 16, 16), 35 * 16, 285 * 16)
        _poly(painter, (15.5, 3.6), (19.6, 5.2), (17.4, 9.0))
    elif name == "close":
        _line(painter, (6, 6), (18, 18))
        _line(painter, (18, 6), (6, 18))
    elif name == "minimize":
        _line(painter, (5, 12), (19, 12))
    elif name == "maximize":
        _rounded(painter, 5, 5, 14, 14, 2.5)
    elif name == "restore":
        _rounded(painter, 4, 8, 11, 11, 2)
        _poly(painter, (8, 8), (8, 4), (20, 4), (20, 16), (16, 16))
    elif name == "copy":
        _rounded(painter, 8, 8, 11, 11, 2.5)
        _poly(painter, (5, 15), (4, 15), (4, 4), (15, 4), (15, 5))
    elif name == "check":
        _poly(painter, (4.5, 12.5), (9.5, 17.5), (19.5, 6.5))
    elif name == "plus":
        _line(painter, (12, 5), (12, 19))
        _line(painter, (5, 12), (19, 12))
    elif name == "minus":
        _line(painter, (5, 12), (19, 12))
    elif name == "wallet":
        _rounded(painter, 3, 6, 18, 13, 3)
        _poly(painter, (3, 9), (17, 9), (21, 8))
        _dot(painter, 17, 13.5, 1.3)
    elif name == "lock":
        _rounded(painter, 5, 11, 14, 9, 2.5)
        painter.drawArc(QRectF(8, 4, 8, 12), 0, 180 * 16)
        _dot(painter, 12, 15.2, 1.1)
    elif name == "qr":
        for x, y in ((4, 4), (14, 4), (4, 14)):
            _rounded(painter, x, y, 6, 6, 1.5)
            _rounded(painter, x + 2, y + 2, 2, 2, 0.4)
        _dot(painter, 15, 15, 1.4)
        _dot(painter, 19, 15, 1.4)
        _dot(painter, 15, 19, 1.4)
        _dot(painter, 19, 19, 1.4)
    elif name == "external":
        _poly(painter, (13, 4), (20, 4), (20, 11))
        _line(painter, (20, 4), (11, 13))
        _poly(painter, (17, 14), (17, 20), (4, 20), (4, 7), (10, 7))
    elif name == "chevron-down":
        _poly(painter, (6, 9), (12, 15), (18, 9))
    elif name == "chevron-up":
        _poly(painter, (6, 15), (12, 9), (18, 15))
    elif name == "chevron-right":
        _poly(painter, (9, 5), (16, 12), (9, 19))
    elif name == "chevron-left":
        _poly(painter, (15, 5), (8, 12), (15, 19))
    elif name == "trash":
        _line(painter, (4, 7), (20, 7))
        _poly(painter, (6, 7), (7, 20), (17, 20), (18, 7))
        _poly(painter, (9, 7), (9, 4), (15, 4), (15, 7))
        _line(painter, (10, 11), (10, 16))
        _line(painter, (14, 11), (14, 16))
    elif name == "edit":
        _poly(painter, (4, 20), (5, 15), (16, 4), (20, 8), (9, 19), (4, 20))
        _line(painter, (14, 6), (18, 10))
    elif name == "filter":
        _line(painter, (4, 6), (20, 6))
        _line(painter, (7, 12), (17, 12))
        _line(painter, (10, 18), (14, 18))
    elif name == "download":
        _poly(painter, (12, 3), (12, 15))
        _poly(painter, (6, 9), (12, 15), (18, 9))
        _poly(painter, (4, 17), (4, 21), (20, 21), (20, 17))
    elif name == "upload":
        _poly(painter, (12, 15), (12, 3))
        _poly(painter, (6, 9), (12, 3), (18, 9))
        _poly(painter, (4, 17), (4, 21), (20, 21), (20, 17))
    elif name == "clock":
        painter.drawEllipse(QPointF(12, 12), 8.5, 8.5)
        _poly(painter, (12, 7), (12, 12), (16, 14))
    elif name == "shield":
        _poly(
            painter, (12, 3), (20, 6), (20, 12), (12, 21), (4, 12), (4, 6), close=True
        )
        _poly(painter, (8.5, 12), (11, 14.5), (16, 8.5))
    elif name == "info":
        painter.drawEllipse(QPointF(12, 12), 8.8, 8.8)
        _dot(painter, 12, 7.6, 1.1)
        _line(painter, (12, 11), (12, 16.5))
    elif name == "warning":
        _poly(painter, (12, 3.5), (21, 20), (3, 20), close=True)
        _line(painter, (12, 9), (12, 14))
        _dot(painter, 12, 17, 1.0)
    elif name == "error":
        painter.drawEllipse(QPointF(12, 12), 8.8, 8.8)
        _line(painter, (8.5, 8.5), (15.5, 15.5))
        _line(painter, (15.5, 8.5), (8.5, 15.5))
    elif name == "play":
        _poly(painter, (7, 4), (20, 12), (7, 20), close=True)
    elif name == "pause":
        _line(painter, (8.5, 5), (8.5, 19))
        _line(painter, (15.5, 5), (15.5, 19))
    elif name == "folder":
        _poly(painter, (3, 6), (9, 6), (11, 9), (21, 9), (21, 19), (3, 19), close=True)
        _line(painter, (3, 9), (21, 9))
    elif name == "file":
        _poly(painter, (6, 3), (14, 3), (19, 8), (19, 21), (6, 21), close=True)
        _poly(painter, (14, 3), (14, 8), (19, 8))
    elif name == "image":
        _rounded(painter, 3, 4, 18, 16, 2.5)
        _dot(painter, 8.5, 9, 1.5)
        _poly(painter, (4, 18), (9.5, 12), (13, 15.5), (16, 12), (20, 17))
    elif name == "moon":
        path = QPainterPath()
        path.addEllipse(QPointF(12, 12), 8.5, 8.5)
        cut = QPainterPath()
        cut.addEllipse(QPointF(16.5, 8.5), 8.0, 8.0)
        painter.drawPath(path.subtracted(cut))
    elif name == "sun":
        painter.drawEllipse(QPointF(12, 12), 4.2, 4.2)
        for index in range(8):
            import math

            angle = index * math.pi / 4
            painter.drawLine(
                QPointF(12 + math.cos(angle) * 7.0, 12 + math.sin(angle) * 7.0),
                QPointF(12 + math.cos(angle) * 9.5, 12 + math.sin(angle) * 9.5),
            )
    elif name == "palette":
        path = QPainterPath()
        path.addEllipse(QPointF(12, 12), 8.7, 8.7)
        painter.drawPath(path)
        for x, y in ((8, 8), (15, 8), (7, 13), (16, 14)):
            _dot(painter, x, y, 1.25)
    elif name == "keyboard":
        _rounded(painter, 2.5, 6, 19, 12, 2.5)
        for y in (10, 14):
            for x in (6, 9, 12, 15, 18):
                _dot(painter, x, y, 0.7)
        _line(painter, (8, 17), (16, 17))
    elif name == "server":
        _rounded(painter, 3, 4, 18, 7, 2)
        _rounded(painter, 3, 13, 18, 7, 2)
        _dot(painter, 7, 7.5, 1.0)
        _dot(painter, 7, 16.5, 1.0)
        _line(painter, (11, 7.5), (17, 7.5))
        _line(painter, (11, 16.5), (17, 16.5))
    elif name == "link":
        path = QPainterPath()
        path.moveTo(9.5, 14.5)
        path.lineTo(14.5, 9.5)
        painter.drawPath(path)
        painter.drawArc(QRectF(2.5, 9.5, 9, 9), 90 * 16, 180 * 16)
        painter.drawArc(QRectF(12.5, 5.5, 9, 9), 270 * 16, 180 * 16)
    elif name == "dots":
        for x in (6, 12, 18):
            _dot(painter, x, 12, 1.5)
    elif name == "sort":
        _poly(painter, (8, 4), (8, 20))
        _poly(painter, (4, 8), (8, 4), (12, 8))
        _poly(painter, (16, 20), (16, 4))
        _poly(painter, (12, 16), (16, 20), (20, 16))
    elif name == "eye":
        path = QPainterPath()
        path.moveTo(2.5, 12)
        path.cubicTo(7, 5.5, 17, 5.5, 21.5, 12)
        path.cubicTo(17, 18.5, 7, 18.5, 2.5, 12)
        painter.drawPath(path)
        painter.drawEllipse(QPointF(12, 12), 3.0, 3.0)
    elif name == "eye-off":
        _line(painter, (3, 3), (21, 21))
        _poly(painter, (7, 8), (4, 10), (7, 14), (10, 15))
        _poly(painter, (14, 15), (17, 14), (20, 10), (17, 8))
        _line(painter, (9, 9), (15, 15))
    else:
        _dot(painter, 12, 12, 1.5)


def icon_pixmap(
    name: str, color: str | QColor, size: int = 20, scale: int = 1
) -> QPixmap:
    """Render one icon at a given pixel density."""
    actual = max(8, int(size * scale))
    pixmap = QPixmap(actual, actual)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
    painter.scale(actual / 24.0, actual / 24.0)
    pen = QPen(QColor(color), 1.8)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    try:
        _draw(painter, name)
    finally:
        painter.end()
    pixmap.setDevicePixelRatio(float(scale))
    return pixmap


def icon(name: str, color: str | QColor, size: int = 20) -> QIcon:
    """Return a cached, high-DPI aware QIcon."""
    color_name = QColor(color).name()
    key = (name, color_name, size)
    cached = _ICON_CACHE.get(key)
    if cached is not None:
        return cached
    result = QIcon()
    result.addPixmap(
        icon_pixmap(name, color_name, size, 1), QIcon.Mode.Normal, QIcon.State.Off
    )
    result.addPixmap(
        icon_pixmap(name, color_name, size, 2), QIcon.Mode.Normal, QIcon.State.Off
    )
    _ICON_CACHE[key] = result
    return result


def nav_icon(name: str, theme, active: bool, size: int = 20) -> QIcon:
    """Return a navigation icon tinted for the current state."""
    color = theme.color("nav_text" if active else "muted")
    return icon(name, color, size)


def brand_mark(theme, size: int = 36) -> QPixmap:
    """Draw the Phoenix application mark as a rounded badge."""
    scale = 2
    pixmap = QPixmap(size * scale, size * scale)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.scale(size * scale / 40.0, size * scale / 40.0)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(theme.color("accent")))
    painter.drawRoundedRect(QRectF(0, 0, 40, 40), 12, 12)
    painter.setPen(QPen(theme.color("accent_text"), 2.2))
    font = QFont("DejaVu Sans")
    font.setPixelSize(22)
    font.setWeight(QFont.Weight.Bold)
    painter.setFont(font)
    painter.drawText(QRectF(0, 0, 40, 40), Qt.AlignmentFlag.AlignCenter, "P")
    painter.end()
    pixmap.setDevicePixelRatio(float(scale))
    return pixmap


def app_icon(theme) -> QIcon:
    """Build a multi-size window icon from the project logo."""
    result = QIcon()
    for size in (16, 24, 32, 48, 64, 128, 256):
        logo = brand_logo(size)
        result.addPixmap(logo if not logo.isNull() else brand_mark(theme, size))
    return result
