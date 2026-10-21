"""Matplotlib charts and a lightweight sparkline for dashboard cards."""

from __future__ import annotations

from datetime import datetime
from typing import Iterable, Sequence

import matplotlib

matplotlib.use("QtAgg")

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg  # noqa: E402
from matplotlib.figure import Figure  # noqa: E402
from PyQt6.QtCore import QPointF, QRectF, Qt  # noqa: E402
from PyQt6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen  # noqa: E402
from PyQt6.QtWidgets import (  # noqa: E402
    QAbstractScrollArea,
    QApplication,
    QFrame,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ...core.formatting import format_amount  # noqa: E402


class MplCanvas(FigureCanvasQTAgg):
    """A transparent matplotlib canvas that fits the card background."""

    def __init__(self, parent: QWidget | None = None) -> None:
        """Initialize the MplCanvas instance."""
        self.figure = Figure(figsize=(4.2, 2.6), dpi=100)
        self.figure.patch.set_alpha(0.0)
        super().__init__(self.figure)
        self.setParent(parent)
        self.setStyleSheet("background: transparent;")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumHeight(190)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.axes = self.figure.add_subplot(111)
        self.axes.patch.set_alpha(0.0)

    def wheelEvent(self, event) -> None:  # noqa: N802 - Qt API
        """Forward wheel input to the surrounding page so charts never trap it."""
        parent = self.parentWidget()
        while parent is not None:
            if isinstance(parent, QAbstractScrollArea):
                QApplication.sendEvent(parent.viewport(), event)
                event.accept()
                return
            parent = parent.parentWidget()
        event.ignore()

    def clear(self) -> None:
        """Remove all axes content."""
        self.figure.clear()
        self.axes = self.figure.add_subplot(111)
        self.axes.patch.set_alpha(0.0)


class ChartPanel(QFrame):
    """Card with a title and a themed matplotlib chart."""

    def __init__(
        self, title: str, subtitle: str = "", parent: QWidget | None = None
    ) -> None:
        """Initialize the ChartPanel instance."""
        super().__init__(parent)
        self.setObjectName("Card")
        self._title = title
        self._subtitle = subtitle
        self._tokens: dict[str, str] = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 14)
        layout.setSpacing(6)
        self.title_label = QLabel(title, self)
        self.title_label.setObjectName("CardTitle")
        self.subtitle_label = QLabel(subtitle, self)
        self.subtitle_label.setObjectName("HintText")
        self.subtitle_label.setWordWrap(True)
        self.subtitle_label.setVisible(bool(subtitle))
        layout.addWidget(self.title_label)
        layout.addWidget(self.subtitle_label)
        self.canvas = MplCanvas(self)
        layout.addWidget(self.canvas, 1)

    def set_tokens(self, tokens: dict[str, str]) -> None:
        """Store the current theme colors used by the next draw."""
        self._tokens = dict(tokens)

    def set_subtitle(self, text: str) -> None:
        """Update the caption below the title."""
        self._subtitle = text
        self.subtitle_label.setText(text)
        self.subtitle_label.setVisible(bool(text))

    def show_message(self, text: str) -> None:
        """Show a centered message instead of a chart."""
        self.canvas.clear()
        axes = self.canvas.axes
        axes.set_axis_off()
        color = self._text_color()
        axes.text(
            0.5,
            0.5,
            text,
            ha="center",
            va="center",
            color=color,
            fontsize=10,
            wrap=True,
        )
        self.canvas.draw_idle()

    def plot_balance(
        self,
        labels: Sequence[str],
        values: Sequence[float],
        accent: str | None = None,
        unit: str = "NVC",
    ) -> None:
        """Draw a filled balance line with a subtle area gradient."""
        if not values:
            self.show_message("Недостаточно данных для графика")
            return
        accent = accent or self._tokens.get("accent", "#FF8A3D")
        self.canvas.clear()
        axes = self.canvas.axes
        x = list(range(len(values)))
        axes.plot(x, list(values), color=accent, linewidth=2.0, solid_capstyle="round")
        axes.fill_between(x, list(values), color=accent, alpha=0.13)
        axes.scatter([x[-1]], [values[-1]], color=accent, s=18, zorder=3)
        axes.set_xlim(0, max(1, len(values) - 1))
        self._style_axes(axes)
        self._set_x_labels(axes, labels)
        axes.yaxis.set_major_formatter(
            lambda value, _pos: format_amount(value, trim=True)
        )
        axes.set_ylabel(unit, color=self._muted_color(), fontsize=8, labelpad=6)
        self.canvas.figure.tight_layout(pad=0.6)
        self.canvas.draw_idle()

    def plot_activity(
        self,
        labels: Sequence[str],
        received: Sequence[float],
        sent: Sequence[float],
    ) -> None:
        """Draw stacked bars for incoming and outgoing volume."""
        if not labels:
            self.show_message("Нет операций за выбранный период")
            return
        self.canvas.clear()
        axes = self.canvas.axes
        x = list(range(len(labels)))
        negative_sent = [-abs(value) for value in sent]
        axes.bar(
            x,
            received,
            color=self._tokens.get("positive", "#4ED19E"),
            width=0.62,
            label="Получено",
        )
        axes.bar(
            x,
            negative_sent,
            color=self._tokens.get("negative", "#FF6B7A"),
            width=0.62,
            label="Отправлено",
        )
        axes.axhline(0, color=self._grid_color(), linewidth=0.8)
        self._style_axes(axes)
        self._set_x_labels(axes, labels)
        axes.yaxis.set_major_formatter(
            lambda value, _pos: format_amount(value, trim=True)
        )
        legend = axes.legend(
            loc="upper left",
            frameon=False,
            fontsize=8,
            ncols=2,
            handlelength=1.0,
            columnspacing=1.0,
        )
        for text in legend.get_texts():
            text.set_color(self._muted_color())
        self.canvas.figure.tight_layout(pad=0.6)
        self.canvas.draw_idle()

    def plot_distribution(
        self,
        items: Sequence[tuple[str, float]],
        colors: Sequence[str],
        center_title: str = "Всего",
        center_value: str = "",
    ) -> None:
        """Draw a donut chart for balance composition."""
        visible = [(label, value) for label, value in items if value > 0]
        if not visible:
            self.show_message("Нет средств для распределения")
            return
        self.canvas.clear()
        axes = self.canvas.axes
        values = [value for _label, value in visible]
        wedges, _texts = axes.pie(
            values,
            colors=list(colors)[: len(values)],
            startangle=90,
            counterclock=False,
            wedgeprops={"width": 0.38, "edgecolor": self._card_color(), "linewidth": 2},
        )
        axes.text(
            0,
            0.1,
            center_title,
            ha="center",
            va="center",
            color=self._muted_color(),
            fontsize=8,
        )
        axes.text(
            0,
            -0.1,
            center_value,
            ha="center",
            va="center",
            color=self._text_color(),
            fontsize=11,
            fontweight="bold",
        )
        legend = axes.legend(
            wedges,
            [f"{label}  {format_amount(value, trim=True)}" for label, value in visible],
            loc="center left",
            bbox_to_anchor=(1.0, 0.5),
            frameon=False,
            fontsize=7.5,
            handlelength=0.7,
            borderaxespad=0.0,
        )
        for text in legend.get_texts():
            text.set_color(self._muted_color())
        axes.set_aspect("equal")
        self.canvas.figure.subplots_adjust(left=0.0, right=0.68, top=0.96, bottom=0.04)
        self.canvas.draw_idle()

    def plot_top_addresses(
        self,
        items: Sequence[tuple[str, float]],
        accent: str | None = None,
    ) -> None:
        """Draw a horizontal bar chart for the busiest addresses."""
        visible = [(label, value) for label, value in items if value > 0]
        if not visible:
            self.show_message("Недостаточно данных по адресам")
            return
        accent = accent or self._tokens.get("accent", "#FF8A3D")
        self.canvas.clear()
        axes = self.canvas.axes
        labels = [label for label, _value in visible]
        values = [value for _label, value in visible]
        positions = list(range(len(values)))
        axes.barh(positions, values, color=accent, height=0.58, alpha=0.9)
        axes.set_yticks(positions)
        axes.set_yticklabels(labels, color=self._muted_color(), fontsize=8)
        axes.invert_yaxis()
        axes.xaxis.set_major_formatter(
            lambda value, _pos: format_amount(value, trim=True)
        )
        self._style_axes(axes, grid_axis="x")
        self.canvas.figure.tight_layout(pad=0.6)
        self.canvas.draw_idle()

    def plot_fees(self, labels: Sequence[str], values: Sequence[float]) -> None:
        """Draw a compact fee trend line."""
        if not values:
            self.show_message("Комиссии не начислялись")
            return
        self.canvas.clear()
        axes = self.canvas.axes
        x = list(range(len(values)))
        color = self._tokens.get("warning", "#F3C969")
        axes.bar(x, values, color=color, width=0.62, alpha=0.85)
        self._style_axes(axes)
        self._set_x_labels(axes, labels)
        axes.yaxis.set_major_formatter(
            lambda value, _pos: format_amount(value, trim=True)
        )
        self.canvas.figure.tight_layout(pad=0.6)
        self.canvas.draw_idle()

    def _style_axes(self, axes, grid_axis: str = "y") -> None:
        """Apply theme colors, grid and spines to an axes."""
        muted = self._muted_color()
        grid = self._grid_color()
        axes.tick_params(colors=muted, labelsize=8, length=0)
        axes.grid(True, axis=grid_axis, color=grid, linewidth=0.7, alpha=0.6)
        axes.set_axisbelow(True)
        for side in ("top", "right", "left", "bottom"):
            axes.spines[side].set_visible(False)
        for label in axes.get_xticklabels() + axes.get_yticklabels():
            label.set_color(muted)

    def _set_x_labels(self, axes, labels: Sequence[str]) -> None:
        """Place a few readable labels under the x axis."""
        count = len(labels)
        if count == 0:
            return
        if count <= 4:
            positions = list(range(count))
        else:
            positions = [0, count // 2, count - 1]
        axes.set_xticks(positions)
        axes.set_xticklabels(
            [labels[index] for index in positions],
            color=self._muted_color(),
            fontsize=8,
        )

    def _text_color(self) -> str:
        """Return the main text color."""
        return self._tokens.get("text", "#E7ECF5")

    def _muted_color(self) -> str:
        """Return the muted text color."""
        return self._tokens.get("muted", "#8B97AA")

    def _grid_color(self) -> str:
        """Return the grid color."""
        return self._tokens.get("border", "#243043")

    def _card_color(self) -> str:
        """Return the card background color."""
        return self._tokens.get("surface", "#131C29")


class Sparkline(QWidget):
    """A compact painted trend line for metric cards."""

    def __init__(self, parent: QWidget | None = None, color: str = "#FF8A3D") -> None:
        """Initialize the Sparkline instance."""
        super().__init__(parent)
        self._values: list[float] = []
        self._color = QColor(color)
        self.setMinimumHeight(34)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_values(self, values: Iterable[float], color: str | None = None) -> None:
        """Replace the series and repaint."""
        self._values = [float(value) for value in values]
        if color:
            self._color = QColor(color)
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt API
        """Draw a smooth line with a soft gradient fill."""
        if len(self._values) < 2:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(self.rect()).adjusted(1, 4, -1, -2)
        low = min(self._values)
        high = max(self._values)
        span = high - low or 1.0
        step = rect.width() / (len(self._values) - 1)
        points = [
            QPointF(
                rect.left() + index * step,
                rect.bottom() - (value - low) / span * rect.height(),
            )
            for index, value in enumerate(self._values)
        ]
        path = QPainterPath(points[0])
        for point in points[1:]:
            path.lineTo(point)
        fill = QPainterPath(path)
        fill.lineTo(points[-1].x(), rect.bottom())
        fill.lineTo(points[0].x(), rect.bottom())
        fill.closeSubpath()
        gradient = QLinearGradient(0, rect.top(), 0, rect.bottom())
        top = QColor(self._color)
        top.setAlpha(70)
        bottom = QColor(self._color)
        bottom.setAlpha(0)
        gradient.setColorAt(0.0, top)
        gradient.setColorAt(1.0, bottom)
        painter.fillPath(fill, gradient)
        painter.setPen(QPen(self._color, 1.8))
        painter.drawPath(path)
        painter.end()


def compact_date(timestamp: int) -> str:
    """Format a unix timestamp as a short day and month label."""
    return datetime.fromtimestamp(timestamp).strftime("%d.%m") if timestamp else "--"
