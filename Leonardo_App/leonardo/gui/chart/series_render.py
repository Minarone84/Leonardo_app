from __future__ import annotations

from typing import List, Optional

from PySide6.QtCore import QRectF
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QBrush, QWheelEvent
from PySide6.QtWidgets import QWidget

from leonardo.gui.chart.viewport import ChartViewport
from leonardo.gui.chart.crosshair import Crosshair


class VolumeRenderSurface(QWidget):
    def __init__(
        self,
        viewport: ChartViewport,
        crosshair: Crosshair,
        volume: List[float],
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._viewport = viewport
        self._volume = volume
        self._crosshair = crosshair

        self.setMouseTracking(True)

        self._viewport.viewport_changed.connect(self.update)
        self._crosshair.changed.connect(self.update)
        self._crosshair.cleared.connect(self.update)

        self._pad_left = 8
        self._pad_top = 6
        self._pad_right = 64
        self._pad_bottom = 14

    def _plot_rect(self) -> QRectF:
        w = self.width()
        h = self.height()
        return QRectF(
            self._pad_left,
            self._pad_top,
            max(1, w - self._pad_left - self._pad_right),
            max(1, h - self._pad_top - self._pad_bottom),
        )

    def mouseMoveEvent(self, e) -> None:
        plot = self._plot_rect()
        try:
            x = float(e.position().x())
            y = float(e.position().y())
        except Exception:
            x = float(e.x())
            y = float(e.y())

        if not plot.contains(x, y):
            return

        idx = self._viewport.index_from_x(plot, x)
        self._crosshair.set_index(idx)
        # ensure price pane doesn't draw its horizontal line while hovering lower panes
        self._crosshair.set_hover_on_price(False)

    def wheelEvent(self, event: QWheelEvent) -> None:
        plot = self._plot_rect()

        try:
            mx = float(event.position().x())
            my = float(event.position().y())
        except Exception:
            mx = float(event.x())
            my = float(event.y())

        if not plot.contains(mx, my):
            event.ignore()
            return

        anchor_idx = self._viewport.index_from_x(plot, mx)
        anchor_rel = (mx - plot.left()) / max(1.0, plot.width())

        dy = event.angleDelta().y()
        if dy > 0:
            self._viewport.zoom_in_at(anchor_idx, anchor_rel)
        elif dy < 0:
            self._viewport.zoom_out_at(anchor_idx, anchor_rel)

        event.accept()

    def leaveEvent(self, e) -> None:
        # Do NOT clear shared index here; it would flicker when moving between panes.
        # Workspace-level clearing (optional) can be added later.
        return

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, False)

        w = self.width()
        h = self.height()
        p.fillRect(0, 0, w, h, QColor(12, 12, 14))

        plot = self._plot_rect()

        # border
        p.setPen(QPen(QColor(70, 70, 82)))
        p.drawRect(plot)

        start, end = self._viewport.start, self._viewport.end
        vis = self._volume[start:end]
        if not vis:
            return

        vmax = max(vis)
        n = len(vis)
        if n <= 0:
            return

        bar_w = max(2.0, plot.width() / max(1, n))
        body_w = max(1.0, bar_w * 0.8)

        brush = QBrush(QColor(80, 120, 220))
        p.setPen(QPen(QColor(80, 120, 220)))
        p.setBrush(brush)

        for i, v in enumerate(vis):
            cx = plot.left() + (i + 0.5) * bar_w
            t = v / vmax if vmax > 0 else 0.0
            bar_h = t * plot.height()
            p.drawRect(cx - body_w / 2, plot.bottom() - bar_h, body_w, bar_h)

        # ---- shared vertical + value-based horizontal (at volume[idx]) ----
        if self._crosshair.active and self._crosshair.index is not None:
            idx = self._crosshair.index

            # vertical (only if within visible slice)
            if start <= idx < end:
                x = self._viewport.x_from_index(plot, idx)
                p.setPen(QPen(QColor(120, 120, 140)))
                p.drawLine(int(x), int(plot.top()), int(x), int(plot.bottom()))

            # horizontal at value:
            # IMPORTANT: use the SAME scale as visible bars (vmax from vis),
            # but clamp series value to that scale to avoid off-plot y when idx is outside vis.
            if 0 <= idx < len(self._volume) and vmax > 0:
                v = self._volume[idx]
                if v < 0.0:
                    v = 0.0
                elif v > vmax:
                    v = vmax  # clamp to visible scale

                t = v / vmax
                y = plot.bottom() - t * plot.height()

                p.setPen(QPen(QColor(120, 120, 140)))
                p.drawLine(int(plot.left()), int(y), int(plot.right()), int(y))

        # right-side label
        p.setPen(QPen(QColor(170, 170, 185)))
        p.setFont(QFont("Consolas", 9))
        p.drawText(int(plot.right() + 8), int(plot.top() + 12), "Vol")
        p.drawText(int(plot.right() + 8), int(plot.top() + 26), f"{vmax:0.0f}")


class OscillatorRenderSurface(QWidget):
    def __init__(
        self,
        title: str,
        viewport: ChartViewport,
        crosshair: Crosshair,
        values: List[float],
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._title = title
        self._viewport = viewport
        self._crosshair = crosshair
        self._values = values

        self.setMouseTracking(True)

        self._viewport.viewport_changed.connect(self.update)
        self._crosshair.changed.connect(self.update)
        self._crosshair.cleared.connect(self.update)

        self._pad_left = 8
        self._pad_top = 6
        self._pad_right = 64
        self._pad_bottom = 14

    def _plot_rect(self) -> QRectF:
        w = self.width()
        h = self.height()
        return QRectF(
            self._pad_left,
            self._pad_top,
            max(1, w - self._pad_left - self._pad_right),
            max(1, h - self._pad_top - self._pad_bottom),
        )

    def mouseMoveEvent(self, e) -> None:
        plot = self._plot_rect()
        try:
            x = float(e.position().x())
            y = float(e.position().y())
        except Exception:
            x = float(e.x())
            y = float(e.y())

        if not plot.contains(x, y):
            return

        idx = self._viewport.index_from_x(plot, x)
        self._crosshair.set_index(idx)
        self._crosshair.set_hover_on_price(False)

    def wheelEvent(self, event: QWheelEvent) -> None:
        plot = self._plot_rect()

        try:
            mx = float(event.position().x())
            my = float(event.position().y())
        except Exception:
            mx = float(event.x())
            my = float(event.y())

        if not plot.contains(mx, my):
            event.ignore()
            return

        anchor_idx = self._viewport.index_from_x(plot, mx)
        anchor_rel = (mx - plot.left()) / max(1.0, plot.width())

        dy = event.angleDelta().y()
        if dy > 0:
            self._viewport.zoom_in_at(anchor_idx, anchor_rel)
        elif dy < 0:
            self._viewport.zoom_out_at(anchor_idx, anchor_rel)

        event.accept()

    def leaveEvent(self, e) -> None:
        return

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, False)

        w = self.width()
        h = self.height()
        p.fillRect(0, 0, w, h, QColor(12, 12, 14))

        plot = self._plot_rect()

        # border
        p.setPen(QPen(QColor(70, 70, 82)))
        p.drawRect(plot)

        start, end = self._viewport.start, self._viewport.end
        vis = self._values[start:end]
        if len(vis) < 2:
            return

        ymin = min(vis)
        ymax = max(vis)
        if ymax <= ymin:
            ymax = ymin + 1.0

        n = len(vis)
        dx = plot.width() / max(1, (n - 1))

        pen = QPen(QColor(0, 200, 255))
        pen.setWidth(1)
        p.setPen(pen)

        def y_to_px(v: float) -> float:
            t = (v - ymin) / (ymax - ymin)
            return plot.bottom() - t * plot.height()

        prev_x = plot.left()
        prev_y = y_to_px(vis[0])
        for i in range(1, n):
            x = plot.left() + i * dx
            y = y_to_px(vis[i])
            p.drawLine(int(prev_x), int(prev_y), int(x), int(y))
            prev_x, prev_y = x, y

        # ---- shared vertical + value-based horizontal (at values[idx]) ----
        if self._crosshair.active and self._crosshair.index is not None:
            idx = self._crosshair.index

            # vertical (only if within visible slice)
            if start <= idx < end:
                x = self._viewport.x_from_index(plot, idx)
                p.setPen(QPen(QColor(120, 120, 140)))
                p.drawLine(int(x), int(plot.top()), int(x), int(plot.bottom()))

            # horizontal at value (clamp safely)
            if 0 <= idx < len(self._values):
                v = self._values[idx]
                y = y_to_px(v)
                p.setPen(QPen(QColor(120, 120, 140)))
                p.drawLine(int(plot.left()), int(y), int(plot.right()), int(y))

        # right-side title
        p.setPen(QPen(QColor(170, 170, 185)))
        p.setFont(QFont("Consolas", 9))
        p.drawText(int(plot.right() + 8), int(plot.top() + 12), self._title)