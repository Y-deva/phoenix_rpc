"""Theme tokens, accessible palette and the global Qt stylesheet.

The stylesheet is generated from tokens so the three built-in themes
share one layout. Object names such as ``Card`` and ``AccentButton`` are
the contract used by every widget module.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import tempfile
from typing import Mapping

from PyQt6.QtCore import QObject, QPointF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QFontDatabase, QPainter, QPalette, QPen, QPixmap
from PyQt6.QtWidgets import QApplication

from ...settings import Settings

THEME_ORDER = ("phoenix", "aurora", "daylight")


@dataclass(frozen=True)
class Theme:
    """One complete visual theme."""

    key: str
    name: str
    dark: bool
    tokens: Mapping[str, str]

    def color(self, name: str) -> QColor:
        """Return a token as a QColor."""
        return QColor(self.tokens.get(name, "#000000"))

    def rgba(self, name: str, alpha: int) -> str:
        """Return a token as a CSS rgba() string."""
        color = self.color(name)
        red, green, blue = color.red(), color.green(), color.blue()
        return f"rgba({red}, {green}, {blue}, {max(0, min(255, alpha))})"


PHOENIX = Theme(
    key="phoenix",
    name="Novacoin Dark",
    dark=True,
    tokens={
        "bg": "#0A0C10",
        "bg_alt": "#10141B",
        "sidebar": "#0C0F15",
        "surface": "#151A23",
        "surface_alt": "#1B2130",
        "surface_hover": "#232B3B",
        "input": "#0F131A",
        "border": "#262E3C",
        "border_strong": "#3A4558",
        "text": "#F3F6FB",
        "muted": "#A7B1C2",
        "faint": "#748094",
        "accent": "#FF8A3D",
        "accent_hover": "#FFA15F",
        "accent_pressed": "#E87528",
        "accent_text": "#1B0D04",
        "accent_soft": "#FFC59B",
        "accent_border": "#74462A",
        "nav_bg": "#2B1C12",
        "nav_text": "#FFB07A",
        "positive": "#3DD6A0",
        "negative": "#FF7070",
        "warning": "#F2C86B",
        "info": "#73BEFF",
        "scroll": "#2C3545",
        "tooltip": "#1C2330",
        "chart_grid": "#29313F",
        "chart_axis": "#7D889A",
        "shadow": "#05070A",
    },
)

AURORA = Theme(
    key="aurora",
    name="Aurora Dark",
    dark=True,
    tokens={
        "bg": "#061012",
        "bg_alt": "#0A181A",
        "sidebar": "#081417",
        "surface": "#0F1F22",
        "surface_alt": "#142A2E",
        "surface_hover": "#1B363A",
        "input": "#0A181B",
        "border": "#1E373C",
        "border_strong": "#2E5056",
        "text": "#ECF8F7",
        "muted": "#9CB8B6",
        "faint": "#6A8887",
        "accent": "#42DCC6",
        "accent_hover": "#69E8D5",
        "accent_pressed": "#2CC2AD",
        "accent_text": "#04211D",
        "accent_soft": "#A6F2E7",
        "accent_border": "#27665E",
        "nav_bg": "#0F302C",
        "nav_text": "#77EADB",
        "positive": "#7BE0A6",
        "negative": "#FF7E86",
        "warning": "#E9CC74",
        "info": "#7FC7FF",
        "scroll": "#274347",
        "tooltip": "#102528",
        "chart_grid": "#1D363A",
        "chart_axis": "#72908E",
        "shadow": "#02090A",
    },
)

DAYLIGHT = Theme(
    key="daylight",
    name="Daylight",
    dark=False,
    tokens={
        "bg": "#F1F4F9",
        "bg_alt": "#E7ECF4",
        "sidebar": "#EAEEF5",
        "surface": "#FFFFFF",
        "surface_alt": "#F5F7FB",
        "surface_hover": "#E9EFF8",
        "input": "#FFFFFF",
        "border": "#D9E1EC",
        "border_strong": "#BCC9D9",
        "text": "#18212E",
        "muted": "#566476",
        "faint": "#8793A5",
        "accent": "#B85A16",
        "accent_hover": "#A34D0F",
        "accent_pressed": "#8E420B",
        "accent_text": "#FFFFFF",
        "accent_soft": "#F6DCC9",
        "accent_border": "#E7BC9E",
        "nav_bg": "#F7E4D5",
        "nav_text": "#8F430C",
        "positive": "#117A58",
        "negative": "#B93A3A",
        "warning": "#8A5A00",
        "info": "#1D5F9E",
        "scroll": "#C3CFDE",
        "tooltip": "#1D2634",
        "chart_grid": "#DCE3ED",
        "chart_axis": "#667486",
        "shadow": "#B7C2D1",
    },
)

CUSTOM_TOKENS = ("bg", "sidebar", "surface", "accent", "text")


def mix_colors(first: str, second: str, weight: float) -> str:
    """Mix two hex colors, where weight is the share of the second color."""
    ratio = max(0.0, min(1.0, weight))
    a = QColor(first)
    b = QColor(second)
    if not a.isValid():
        a = QColor("#000000")
    if not b.isValid():
        b = QColor("#FFFFFF")
    return QColor(
        round(a.red() * (1 - ratio) + b.red() * ratio),
        round(a.green() * (1 - ratio) + b.green() * ratio),
        round(a.blue() * (1 - ratio) + b.blue() * ratio),
    ).name()


def _shade(color: str, amount: float) -> str:
    """Lighten a color for positive amounts or darken it for negative ones."""
    target = "#FFFFFF" if amount > 0 else "#000000"
    return mix_colors(color, target, abs(amount))


def customize_theme(base: Theme, overrides: Mapping[str, str]) -> Theme:
    """Return a coherent theme with selected seed colors replaced.

    Only five primary colors are exposed to the user. Borders, hover
    states, muted text and navigation tints are derived from them so a
    custom palette never turns into an unreadable patchwork.
    """
    valid: dict[str, str] = {}
    for key in CUSTOM_TOKENS:
        value = str(overrides.get(key, "")).strip()
        color = QColor(value)
        if value and color.isValid():
            valid[key] = color.name()
    if not valid:
        return base

    tokens = dict(base.tokens)
    tokens.update(valid)
    bg = tokens["bg"]
    surface = tokens["surface"]
    text = tokens["text"]
    accent = tokens["accent"]
    light = not base.dark
    tokens["bg_alt"] = mix_colors(bg, surface, 0.34)
    if "sidebar" not in valid:
        tokens["sidebar"] = mix_colors(bg, surface, 0.16)
    if light:
        tokens["surface_alt"] = mix_colors(surface, "#000000", 0.045)
        tokens["surface_hover"] = mix_colors(surface, "#000000", 0.075)
        tokens["border"] = mix_colors(surface, text, 0.14)
        tokens["border_strong"] = mix_colors(surface, text, 0.25)
        tokens["input"] = "#FFFFFF"
        tokens["scroll"] = mix_colors(surface, text, 0.25)
        tokens["chart_grid"] = mix_colors(surface, text, 0.10)
        tokens["tooltip"] = mix_colors(text, bg, 0.18)
        tokens["shadow"] = mix_colors(bg, text, 0.28)
    else:
        tokens["surface_alt"] = mix_colors(surface, "#FFFFFF", 0.065)
        tokens["surface_hover"] = mix_colors(surface, "#FFFFFF", 0.12)
        tokens["border"] = mix_colors(surface, text, 0.16)
        tokens["border_strong"] = mix_colors(surface, text, 0.30)
        tokens["input"] = mix_colors(bg, surface, 0.45)
        tokens["scroll"] = mix_colors(surface, text, 0.26)
        tokens["chart_grid"] = mix_colors(surface, text, 0.13)
        tokens["tooltip"] = mix_colors(surface, bg, 0.55)
        tokens["shadow"] = mix_colors(bg, "#000000", 0.55)
    tokens["muted"] = mix_colors(text, bg, 0.38)
    tokens["faint"] = mix_colors(text, bg, 0.55)
    tokens["accent_hover"] = _shade(accent, 0.12 if not light else -0.10)
    tokens["accent_pressed"] = _shade(accent, -0.14 if not light else 0.14)
    tokens["accent_text"] = (
        "#FFFFFF" if contrast_ratio(accent, "#FFFFFF") >= 4.5 else "#121212"
    )
    tokens["accent_soft"] = mix_colors(accent, surface, 0.72)
    tokens["accent_border"] = mix_colors(accent, surface, 0.38)
    tokens["nav_bg"] = mix_colors(accent, bg, 0.82)
    tokens["nav_text"] = tokens["accent_hover"]
    tokens["chart_axis"] = tokens["muted"]
    name = f"{base.name} (своя)"
    return Theme(key=base.key, name=name, dark=base.dark, tokens=tokens)


THEMES: dict[str, Theme] = {theme.key: theme for theme in (PHOENIX, AURORA, DAYLIGHT)}


def _linear_channel(value: int) -> float:
    """Convert an 8-bit sRGB channel to linear light."""
    channel = value / 255.0
    if channel <= 0.04045:
        return channel / 12.92
    return ((channel + 0.055) / 1.055) ** 2.4


def relative_luminance(color: QColor) -> float:
    """Return WCAG relative luminance for a color."""
    return (
        0.2126 * _linear_channel(color.red())
        + 0.7152 * _linear_channel(color.green())
        + 0.0722 * _linear_channel(color.blue())
    )


def contrast_ratio(first: QColor | str, second: QColor | str) -> float:
    """Return the WCAG contrast ratio between two colors."""
    color_a = QColor(first) if isinstance(first, str) else first
    color_b = QColor(second) if isinstance(second, str) else second
    lum_a = relative_luminance(color_a)
    lum_b = relative_luminance(color_b)
    lighter, darker = max(lum_a, lum_b), min(lum_a, lum_b)
    return (lighter + 0.05) / (darker + 0.05)


def choose_font() -> str:
    """Pick the best available UI font for this platform."""
    families = set(QFontDatabase.families())
    for candidate in (
        "Inter",
        "SF Pro Text",
        "Segoe UI",
        "Ubuntu",
        "Noto Sans",
        "Cantarell",
        "DejaVu Sans",
    ):
        if candidate in families:
            return candidate
    return QApplication.font().family()


def choose_mono_font() -> str:
    """Pick a readable monospace font for hashes and the console."""
    families = set(QFontDatabase.families())
    for candidate in (
        "JetBrains Mono",
        "Cascadia Mono",
        "SF Mono",
        "Consolas",
        "Ubuntu Mono",
        "Noto Sans Mono",
        "DejaVu Sans Mono",
    ):
        if candidate in families:
            return candidate
    return "Monospace"


def build_palette(theme: Theme) -> QPalette:
    """Build a QPalette so native dialogs follow the theme."""
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, theme.color("bg"))
    palette.setColor(QPalette.ColorRole.WindowText, theme.color("text"))
    palette.setColor(QPalette.ColorRole.Base, theme.color("input"))
    palette.setColor(QPalette.ColorRole.AlternateBase, theme.color("surface_alt"))
    palette.setColor(QPalette.ColorRole.Text, theme.color("text"))
    palette.setColor(QPalette.ColorRole.Button, theme.color("surface_alt"))
    palette.setColor(QPalette.ColorRole.ButtonText, theme.color("text"))
    palette.setColor(QPalette.ColorRole.ToolTipBase, theme.color("tooltip"))
    palette.setColor(QPalette.ColorRole.ToolTipText, theme.color("text"))
    palette.setColor(QPalette.ColorRole.Highlight, theme.color("accent"))
    palette.setColor(QPalette.ColorRole.HighlightedText, theme.color("accent_text"))
    palette.setColor(QPalette.ColorRole.PlaceholderText, theme.color("faint"))
    palette.setColor(QPalette.ColorRole.Link, theme.color("accent"))
    palette.setColor(QPalette.ColorRole.BrightText, theme.color("negative"))
    for role in (
        QPalette.ColorRole.WindowText,
        QPalette.ColorRole.Text,
        QPalette.ColorRole.ButtonText,
    ):
        palette.setColor(QPalette.ColorGroup.Disabled, role, theme.color("faint"))
    palette.setColor(
        QPalette.ColorGroup.Disabled,
        QPalette.ColorRole.Base,
        theme.color("surface_alt"),
    )
    palette.setColor(
        QPalette.ColorGroup.Disabled,
        QPalette.ColorRole.Button,
        theme.color("surface_alt"),
    )
    return palette


def _font_sizes(scale: int) -> dict[str, float]:
    """Compute the small type scale used by the stylesheet."""
    base = 10.5 * max(80, min(140, scale)) / 100.0
    return {
        "fs": base,
        "fs_sm": base * 0.92,
        "fs_xs": base * 0.8,
        "fs_lg": base * 1.2,
        "fs_xl": base * 1.66,
        "fs_hero": base * 2.45,
        "fs_mono": base * 0.9,
    }


def _qss_icon(kind: str, color: str, size: int = 14) -> str:
    """Render a tiny check or chevron for stylesheet sub-controls."""
    try:
        from PyQt6.QtCore import QStandardPaths

        base = QStandardPaths.writableLocation(
            QStandardPaths.StandardLocation.CacheLocation
        )
    except Exception:
        base = ""
    folder = Path(base or tempfile.gettempdir()) / "phoenix-qss"
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"{kind}-{color.lstrip('#')}.png"
    if target.exists():
        return target.as_posix()
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    pen = QPen(QColor(color), 2.0)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    if kind == "check":
        painter.drawPolyline(
            QPointF(2.5, 7.1),
            QPointF(5.5, 10.2),
            QPointF(11.5, 3.8),
        )
    elif kind == "chevron_up":
        painter.drawPolyline(
            QPointF(2.8, 9.0),
            QPointF(7.0, 4.9),
            QPointF(11.2, 9.0),
        )
    else:
        painter.drawPolyline(
            QPointF(2.8, 5.2),
            QPointF(7.0, 9.3),
            QPointF(11.2, 5.2),
        )
    painter.end()
    pixmap.save(str(target), "PNG")
    return target.as_posix()


def build_stylesheet(
    theme: Theme,
    font_family: str,
    mono_family: str,
    font_scale: int = 100,
) -> str:
    """Generate the complete application stylesheet for a theme."""
    tokens = dict(theme.tokens)
    tokens.update(_font_sizes(font_scale))
    tokens["font"] = font_family
    tokens["check_icon"] = _qss_icon(
        "check", theme.tokens.get("accent_text", "#FFFFFF")
    )
    tokens["chevron_icon"] = _qss_icon("chevron", theme.tokens.get("text", "#FFFFFF"))
    tokens["chevron_up_icon"] = _qss_icon(
        "chevron_up", theme.tokens.get("text", "#FFFFFF")
    )
    tokens["mono"] = mono_family
    for name in (
        "surface",
        "surface_alt",
        "sidebar",
        "nav_bg",
        "input",
        "accent",
        "border",
        "text",
        "tooltip",
        "positive",
        "warning",
        "negative",
        "info",
    ):
        color = theme.color(name)
        tokens[f"{name}_a"] = (
            f"rgba({color.red()}, {color.green()}, {color.blue()}, 242)"
        )
        tokens[f"{name}_soft"] = (
            f"rgba({color.red()}, {color.green()}, {color.blue()}, 38)"
        )
        tokens[f"{name}_faint"] = (
            f"rgba({color.red()}, {color.green()}, {color.blue()}, 18)"
        )
    stylesheet = _STYLESHEET
    for key, value in tokens.items():
        stylesheet = stylesheet.replace(f"@{key}@", str(value))
    return stylesheet


_STYLESHEET = """
* {
    outline: none;
}

QWidget {
    color: @text@;
    font-family: "@font@";
    font-size: @fs@pt;
}

QMainWindow, QDialog {
    background: @bg@;
}

QWidget#RootBackdrop, QWidget#Content, QWidget#Page, QStackedWidget {
    background: transparent;
}

QLabel {
    background: transparent;
}

QLabel#PageTitle {
    font-size: @fs_xl@pt;
    font-weight: 700;
    color: @text@;
}

QLabel#PageSubtitle {
    font-size: @fs_sm@pt;
    color: @muted@;
}

QLabel#SectionTitle {
    font-size: @fs_lg@pt;
    font-weight: 600;
    color: @text@;
}

QLabel#SectionHint {
    font-size: @fs_sm@pt;
    color: @muted@;
}

QLabel#CardTitle {
    font-size: @fs_sm@pt;
    font-weight: 600;
    color: @muted@;
}

QLabel#MetricValue {
    font-size: @fs_xl@pt;
    font-weight: 700;
    color: @text@;
}

QLabel#CardValue {
    font-size: @fs_lg@pt;
    font-weight: 700;
    color: @text@;
}

QLabel#HeroValue {
    font-size: @fs_hero@pt;
    font-weight: 700;
    color: @text@;
}

QLabel#CardCaption {
    font-size: @fs_xs@pt;
    color: @faint@;
}

QLabel#HintText {
    font-size: @fs_xs@pt;
    color: @faint@;
}

QLabel#ErrorText {
    font-size: @fs_xs@pt;
    color: @negative@;
}

QLabel#WarningText {
    font-size: @fs_xs@pt;
    color: @warning@;
}

QLabel#Muted {
    color: @muted@;
}

QLabel#Faint {
    color: @faint@;
}

QLabel#Mono {
    font-family: "@mono@";
    font-size: @fs_mono@pt;
    color: @muted@;
}

QLabel#MonoStrong {
    font-family: "@mono@";
    font-size: @fs_mono@pt;
    color: @text@;
}

QLabel#Pill {
    background: @nav_bg@;
    color: @nav_text@;
    border-radius: 9px;
    padding: 3px 8px;
    font-size: @fs_xs@pt;
    font-weight: 600;
}

QLabel#PillSuccess {
    background: @positive_soft@;
    color: @positive@;
    border-radius: 9px;
    padding: 3px 8px;
    font-size: @fs_xs@pt;
    font-weight: 600;
}

QLabel#PillWarning {
    background: @warning_soft@;
    color: @warning@;
    border-radius: 9px;
    padding: 3px 8px;
    font-size: @fs_xs@pt;
    font-weight: 600;
}

QLabel#PillDanger {
    background: @negative_soft@;
    color: @negative@;
    border-radius: 9px;
    padding: 3px 8px;
    font-size: @fs_xs@pt;
    font-weight: 600;
}

QLabel#PillNeutral {
    background: @surface_alt@;
    color: @muted@;
    border-radius: 9px;
    padding: 3px 8px;
    font-size: @fs_xs@pt;
    font-weight: 600;
}

QFrame#Sidebar {
    background: @sidebar_a@;
    border-right: 1px solid @border@;
}

QFrame#Card {
    background: @surface_a@;
    border: 1px solid @border@;
    border-radius: 16px;
}

QFrame#DataRow {
    background: transparent;
    border: none;
    border-radius: 10px;
}

QFrame#DataRow:hover {
    background: @surface_hover@;
}

QFrame#DataRow QLabel {
    background: transparent;
}

QLabel#AmountPositive {
    color: @positive@;
    font-weight: 700;
}

QLabel#AmountNegative {
    color: @negative@;
    font-weight: 700;
}

QLabel#AmountNeutral {
    color: @text@;
    font-weight: 700;
}

QFrame#IconBadge {
    background: @nav_bg@;
    border: none;
    border-radius: 10px;
}

QFrame#SoftCard {
    background: @surface_alt@;
    border: 1px solid @border@;
    border-radius: 14px;
}

QFrame#HeroCard {
    background: @surface_alt@;
    border: 1px solid @accent_border@;
    border-radius: 18px;
}

QFrame#Banner {
    background: @warning_soft@;
    border: 1px solid @warning@;
    border-radius: 12px;
}

QFrame#ErrorBanner {
    background: @negative_soft@;
    border: 1px solid @negative@;
    border-radius: 12px;
}

QFrame#Divider {
    background: @border@;
    max-height: 1px;
    border: none;
}

QFrame#ToastSuccess {
    background: @surface_a@;
    border: 1px solid @border@;
    border-left: 3px solid @positive@;
    border-radius: 10px;
}

QFrame#ToastError {
    background: @surface_a@;
    border: 1px solid @border@;
    border-left: 3px solid @negative@;
    border-radius: 10px;
}

QFrame#ToastInfo {
    background: @surface_a@;
    border: 1px solid @border@;
    border-left: 3px solid @info@;
    border-radius: 10px;
}

QPushButton, QToolButton {
    background: @surface_alt@;
    border: 1px solid @border@;
    border-radius: 10px;
    padding: 8px 14px;
    color: @text@;
    font-weight: 500;
}

QPushButton:hover, QToolButton:hover {
    background: @surface_hover@;
    border-color: @border_strong@;
}

QPushButton:pressed, QToolButton:pressed {
    background: @input@;
}

QPushButton:disabled, QToolButton:disabled {
    color: @faint@;
    background: @surface_alt@;
    border-color: @border@;
}

QPushButton#AccentButton, QToolButton#AccentButton {
    background: @accent@;
    border: 1px solid @accent@;
    color: @accent_text@;
    font-weight: 700;
}

QPushButton#AccentButton:hover, QToolButton#AccentButton:hover {
    background: @accent_hover@;
    border-color: @accent_hover@;
}

QPushButton#AccentButton:pressed, QToolButton#AccentButton:pressed {
    background: @accent_pressed@;
    border-color: @accent_pressed@;
}

QPushButton#AccentButton:disabled, QToolButton#AccentButton:disabled {
    background: @surface_alt@;
    border-color: @border@;
    color: @faint@;
}

QPushButton#GhostButton, QToolButton#GhostButton {
    background: transparent;
    border: 1px solid transparent;
    color: @muted@;
}

QPushButton#GhostButton:hover, QToolButton#GhostButton:hover {
    background: @surface_hover@;
    color: @text@;
}

QPushButton#DangerButton, QToolButton#DangerButton {
    background: @negative_soft@;
    border: 1px solid @negative@;
    color: @negative@;
    font-weight: 600;
}

QPushButton#DangerButton:hover, QToolButton#DangerButton:hover {
    background: @negative@;
    color: @bg@;
}

QPushButton#IconButton, QToolButton#IconButton {
    background: transparent;
    border: 1px solid transparent;
    border-radius: 8px;
    padding: 6px;
    min-width: 30px;
    min-height: 30px;
}

QPushButton#IconButton:hover, QToolButton#IconButton:hover {
    background: @surface_hover@;
    border-color: @border@;
}

QPushButton#SegmentButton {
    background: transparent;
    border: 1px solid transparent;
    border-radius: 8px;
    padding: 6px 11px;
    color: @muted@;
    font-weight: 500;
}

QPushButton#SegmentButton:hover {
    color: @text@;
    background: @surface_hover@;
}

QPushButton#SegmentButton:checked {
    background: @surface@;
    color: @text@;
    border-color: @border@;
    font-weight: 600;
}

QFrame#Segment {
    background: @surface_alt@;
    border: 1px solid @border@;
    border-radius: 10px;
}

QPushButton#NavButton {
    background: transparent;
    border: 1px solid transparent;
    border-radius: 10px;
    padding: 9px 12px;
    text-align: left;
    color: @muted@;
    font-weight: 500;
}

QPushButton#NavButton:hover {
    background: @surface_hover@;
    color: @text@;
}

QPushButton#NavButton:checked {
    background: @nav_bg@;
    color: @nav_text@;
    font-weight: 700;
}

QPushButton#NavButton:checked:hover {
    background: @nav_bg@;
}

QLineEdit, QPlainTextEdit, QTextEdit, QComboBox, QSpinBox, QDoubleSpinBox {
    background: @input@;
    border: 1px solid @border@;
    border-radius: 10px;
    padding: 8px 10px;
    color: @text@;
    selection-background-color: @accent@;
    selection-color: @accent_text@;
}

QLineEdit:hover, QPlainTextEdit:hover, QTextEdit:hover,
QComboBox:hover, QSpinBox:hover, QDoubleSpinBox:hover {
    border-color: @border_strong@;
}

QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus,
QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {
    border: 1px solid @accent@;
}

QLineEdit:disabled, QPlainTextEdit:disabled, QTextEdit:disabled,
QComboBox:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled {
    color: @faint@;
    background: @surface_alt@;
}

QLineEdit[error="true"] {
    border: 1px solid @negative@;
}

QComboBox QAbstractItemView {
    background: @surface@;
    border: 1px solid @border@;
    border-radius: 8px;
    selection-background-color: @nav_bg@;
    selection-color: @text@;
    padding: 4px;
    outline: none;
}

QComboBox::drop-down {
    border: none;
    width: 24px;
    background: transparent;
}

QComboBox::down-arrow {
    image: url(@chevron_icon@);
    width: 12px;
    height: 12px;
}

QSpinBox::up-button, QDoubleSpinBox::up-button {
    subcontrol-origin: border;
    subcontrol-position: top right;
    background: transparent;
    border-left: 1px solid @border@;
    border-bottom: 1px solid @border@;
    width: 20px;
}

QSpinBox::down-button, QDoubleSpinBox::down-button {
    subcontrol-origin: border;
    subcontrol-position: bottom right;
    background: transparent;
    border-left: 1px solid @border@;
    width: 20px;
}

QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {
    image: url(@chevron_up_icon@);
    width: 9px;
    height: 9px;
}

QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {
    image: url(@chevron_icon@);
    width: 9px;
    height: 9px;
}

QCheckBox, QRadioButton {
    spacing: 8px;
    color: @text@;
}

QCheckBox::indicator, QRadioButton::indicator {
    width: 16px;
    height: 16px;
    border: 1px solid @border_strong@;
    border-radius: 5px;
    background: @input@;
}

QRadioButton::indicator {
    border-radius: 8px;
}

QCheckBox::indicator:hover, QRadioButton::indicator:hover {
    border-color: @accent@;
}

QCheckBox::indicator:checked, QRadioButton::indicator:checked {
    background: @accent@;
    border-color: @accent@;
    image: url(@check_icon@);
}

QCheckBox::indicator:disabled, QRadioButton::indicator:disabled {
    background: @surface_alt@;
    border-color: @border@;
}

QTableView::indicator, QListView::indicator {
    width: 16px;
    height: 16px;
    border: 1px solid @border_strong@;
    border-radius: 4px;
    background: @input@;
}

QTableView::indicator:hover, QListView::indicator:hover {
    border-color: @accent@;
}

QTableView::indicator:checked, QListView::indicator:checked {
    background: @accent@;
    border-color: @accent@;
    image: url(@check_icon@);
}

QSlider::groove:horizontal {
    height: 4px;
    background: @input@;
    border-radius: 2px;
}

QSlider::sub-page:horizontal {
    background: @accent@;
    border-radius: 2px;
}

QSlider::handle:horizontal {
    background: @text@;
    border: 2px solid @accent@;
    width: 14px;
    height: 14px;
    margin: -6px 0;
    border-radius: 8px;
}

QTableView#DataTable {
    background: transparent;
    alternate-background-color: @surface_alt_faint@;
    border: none;
    gridline-color: @border@;
    selection-background-color: @nav_bg@;
    selection-color: @text@;
    outline: none;
}

QTableView#DataTable::item {
    padding: 8px 6px;
    border-bottom: 1px solid @border@;
}

QTableView#DataTable::item:hover {
    background: @surface_hover@;
}

QTableView#DataTable::item:selected {
    background: @nav_bg@;
    color: @text@;
}

QHeaderView {
    background: transparent;
}

QHeaderView::section {
    background: transparent;
    color: @muted@;
    border: none;
    border-bottom: 1px solid @border@;
    padding: 9px 22px 9px 6px;
    font-size: @fs_sm@pt;
    font-weight: 600;
}

QHeaderView::section:hover {
    color: @text@;
}

QHeaderView::up-arrow, QHeaderView::down-arrow {
    image: none;
    width: 0;
    height: 0;
}

QTableCornerButton::section {
    background: transparent;
    border: none;
}

QScrollArea {
    border: none;
    background: transparent;
}

QScrollArea > QWidget > QWidget {
    background: transparent;
}

QAbstractScrollArea::corner {
    background: transparent;
}

QScrollBar:vertical {
    background: transparent;
    width: 10px;
    margin: 3px 2px;
}

QScrollBar::handle:vertical {
    background: @scroll@;
    min-height: 28px;
    border-radius: 4px;
}

QScrollBar::handle:vertical:hover {
    background: @border_strong@;
}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0;
    background: transparent;
}

QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
    background: transparent;
}

QScrollBar:horizontal {
    background: transparent;
    height: 10px;
    margin: 2px 3px;
}

QScrollBar::handle:horizontal {
    background: @scroll@;
    min-width: 28px;
    border-radius: 4px;
}

QScrollBar::handle:horizontal:hover {
    background: @border_strong@;
}

QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
    width: 0;
    background: transparent;
}

QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {
    background: transparent;
}

QProgressBar {
    background: @input@;
    border: none;
    border-radius: 4px;
    min-height: 8px;
    max-height: 8px;
    text-align: center;
    color: transparent;
}

QProgressBar::chunk {
    background: @accent@;
    border-radius: 4px;
}

QProgressBar#LargeProgress {
    min-height: 12px;
    max-height: 12px;
    border-radius: 6px;
    color: @muted@;
    font-size: @fs_xs@pt;
}

QProgressBar#LargeProgress::chunk {
    border-radius: 6px;
}

QSplitter::handle {
    background: @border@;
}

QSplitter::handle:horizontal {
    width: 1px;
}

QSplitter::handle:vertical {
    height: 1px;
}

QMenuBar {
    background: @sidebar_a@;
    color: @muted@;
    border-bottom: 1px solid @border@;
    padding: 2px 6px;
}

QMenuBar::item {
    background: transparent;
    padding: 5px 9px;
    border-radius: 6px;
}

QMenuBar::item:selected {
    background: @surface_hover@;
    color: @text@;
}

QMenu {
    background: @surface@;
    border: 1px solid @border@;
    border-radius: 10px;
    padding: 6px;
}

QMenu::item {
    padding: 7px 30px 7px 12px;
    border-radius: 6px;
    color: @text@;
}

QMenu::item:selected {
    background: @nav_bg@;
    color: @nav_text@;
}

QMenu::item:disabled {
    color: @faint@;
}

QMenu::separator {
    height: 1px;
    background: @border@;
    margin: 5px 8px;
}

QMenu::indicator {
    width: 14px;
    height: 14px;
}

QStatusBar {
    background: @sidebar_a@;
    border-top: 1px solid @border@;
    color: @muted@;
    min-height: 24px;
}

QStatusBar::item {
    border: none;
}

QStatusBar QLabel {
    color: @muted@;
    background: transparent;
}

QToolTip {
    background: @tooltip@;
    color: @text@;
    border: 1px solid @border_strong@;
    border-radius: 6px;
    padding: 6px 8px;
}

QTabWidget::pane {
    border: none;
    background: transparent;
}

QTabBar::tab {
    background: transparent;
    color: @muted@;
    padding: 7px 12px;
    border-radius: 8px;
    margin-right: 2px;
}

QTabBar::tab:hover {
    background: @surface_hover@;
    color: @text@;
}

QTabBar::tab:selected {
    background: @nav_bg@;
    color: @nav_text@;
    font-weight: 600;
}

QListWidget {
    background: @surface@;
    border: 1px solid @border@;
    border-radius: 12px;
    padding: 4px;
    outline: none;
}

QListWidget::item {
    padding: 8px;
    border-radius: 8px;
}

QListWidget::item:selected {
    background: @nav_bg@;
    color: @text@;
}

QGroupBox {
    border: 1px solid @border@;
    border-radius: 12px;
    margin-top: 12px;
    padding-top: 10px;
    font-weight: 600;
}

QGroupBox::title {
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 4px;
    color: @muted@;
}

QMessageBox {
    background: @surface@;
}

QMessageBox QLabel {
    color: @text@;
}

QSizeGrip {
    background: transparent;
}
"""


class ThemeManager(QObject):
    """Apply themes and typography to the running application.

    The manager listens to settings changes so the appearance page can
    simply write ``appearance/theme`` without knowing about QSS.
    """

    changed = pyqtSignal(object)

    def __init__(
        self,
        settings: Settings,
        app: QApplication | None = None,
        parent: QObject | None = None,
    ) -> None:
        """Initialize the ThemeManager instance."""
        super().__init__(parent)
        self._settings = settings
        self._app = app or QApplication.instance()
        self._ui_font = choose_font()
        self._mono_font = choose_mono_font()
        self._applying = False
        key = settings.theme if settings.theme in THEMES else PHOENIX.key
        self._base_key = key
        self._theme = customize_theme(THEMES[key], settings.custom_colors)
        settings.changed.connect(self._on_setting_changed)
        self.apply(key, persist=False)

    @property
    def theme(self) -> Theme:
        """Return the active theme, including custom color overrides."""
        return self._theme

    @property
    def base_key(self) -> str:
        """Return the built-in theme key behind the active palette."""
        return self._base_key

    @property
    def customized(self) -> bool:
        """Return whether the active palette has user color overrides."""
        return bool(self._settings.custom_colors)

    @property
    def tokens(self) -> Mapping[str, str]:
        """Return the active theme token mapping."""
        return self._theme.tokens

    @property
    def ui_font(self) -> str:
        """Return the selected interface font family."""
        return self._ui_font

    @property
    def mono_font(self) -> str:
        """Return the selected monospace font family."""
        return self._mono_font

    @property
    def mono_family(self) -> str:
        """Alias used by table and console widgets."""
        return self._mono_font

    @property
    def is_dark(self) -> bool:
        """Return whether the active theme is dark."""
        return self._theme.dark

    def apply(self, key: str | None = None, persist: bool = True) -> None:
        """Apply a theme by key, or the stored theme when key is None."""
        requested = key or self._settings.theme
        selected = THEMES.get(requested, PHOENIX)
        if self._base_key != selected.key or not self._settings.custom_colors:
            self._base_key = selected.key
        custom = self._settings.custom_colors
        effective = customize_theme(selected, custom)
        self._theme = effective
        scale = self._settings.font_scale
        self._applying = True
        try:
            if key and key != self._settings.theme:
                self._settings.set_custom_colors({})
                custom = {}
                effective = customize_theme(selected, {})
                self._theme = effective
            if persist:
                self._settings.theme = selected.key
            scale_factor = max(80, min(140, scale)) / 100.0
            font = QFont(self._ui_font)
            font.setPointSizeF(10.5 * scale_factor)
            font.setHintingPreference(QFont.HintingPreference.PreferDefaultHinting)
            self._app.setFont(font)
            self._app.setPalette(build_palette(effective))
            self._app.setStyleSheet(
                build_stylesheet(effective, self._ui_font, self._mono_font, scale)
            )
        finally:
            self._applying = False
        self.changed.emit(effective)

    def cycle(self) -> None:
        """Switch to the next built-in theme."""
        current = (
            THEME_ORDER.index(self._base_key) if self._base_key in THEME_ORDER else 0
        )
        self.apply(THEME_ORDER[(current + 1) % len(THEME_ORDER)])

    def toggle_light(self) -> None:
        """Switch between the primary dark theme and daylight."""
        self.apply("daylight" if self._theme.dark else "phoenix")

    def _on_setting_changed(self, key: str, value: object) -> None:
        """Reapply when appearance settings change elsewhere."""
        if self._applying:
            return
        if key == "appearance/theme":
            self.apply(str(value))
        elif key in {
            "appearance/font_scale",
            "appearance/density",
            "appearance/custom_colors",
            "appearance/batch",
        }:
            self.apply(self._settings.theme, persist=False)
