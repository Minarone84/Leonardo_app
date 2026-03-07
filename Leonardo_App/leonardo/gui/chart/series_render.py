from __future__ import annotations

from typing import List, Optional

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QPainter,
    QPen,
    QBrush,
    QWheelEvent,
    QFontMetricsF,
)
from PySide6.QtWidgets import QWidget

from leonardo.gui.chart.viewport import ChartViewport
from leonardo.gui.chart.crosshair import Crosshair


def draw_right_axis_value_tag(p: QPainter, axis: QRectF, y: float, text: str) -> None:
    """
    Draw a right-side floating label INSIDE the axis/legend gutter at vertical position y.
    Style: orange box, 50% opacity, black text.
    """
    fm = QFontMetricsF(p.font())
    pad_x = 7.0
    pad_y = 3.0

    text_w = fm.horizontalAdvance(text)
    text_h = fm.height()

    w = min(axis.width() - 8.0, text_w + 2 * pad_x)
    h = text_h + 2 * pad_y

    y_top = y - h / 2.0
    y_top = max(axis.top(), min(axis.bottom() - h, y_top))

    x_left = axis.right() - w - 4.0
    r = QRectF(x_left, y_top, w, h)

    p.save()
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(255, 165, 0))  # orange
    p.setOpacity(0.5)
    p.drawRoundedRect(r, 6.0, 6.0)
    p.setOpacity(1.0)
    p.setPen(QColor(0, 0, 0))        # black text
    p.drawText(r, Qt.AlignCenter, text)
    p.restore()


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

        self._resident_base_index = 0

        self.setMouseTracking(True)

        self._viewport.viewport_changed.connect(self.update)
        self._crosshair.changed.connect(self.update)
        self._crosshair.cleared.connect(self.update)

        self._pad_left = 8
        self._pad_top = 6
        self._pad_right = 64
        self._pad_bottom = 14

    def set_volume(self, volume: List[float]) -> None:
        self._volume = volume
        self.update()

    def set_resident_base_index(self, base_index: int) -> None:
        self._resident_base_index = max(0, int(base_index))
        self.update()

    def _global_to_local(self, global_index: int) -> Optional[int]:
        local = int(global_index) - self._resident_base_index
        if 0 <= local < len(self._volume):
            return local
        return None

    def _value_at_global(self, global_index: int) -> Optional[float]:
        local = self._global_to_local(global_index)
        if local is None:
            return None
        return float(self._volume[local])

    def _plot_rect(self) -> QRectF:
        w = self.width()
        h = self.height()
        return QRectF(
            self._pad_left,
            self._pad_top,
            max(1, w - self._pad_left - self._pad_right),
            max(1, h - self._pad_top - self._pad_bottom),
        )

    def _axis_rect(self, plot: QRectF) -> QRectF:
        return QRectF(plot.right(), plot.top(), float(self._pad_right), plot.height())

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
        # slot-centered anchor_rel (NOT continuous mouse-based)
        anchor_rel = ((anchor_idx - self._viewport.start) + 0.5) / max(1, self._viewport.visible)

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
        axis = self._axis_rect(plot)

        p.setPen(QPen(QColor(70, 70, 82)))
        p.drawRect(plot)

        start, end = self._viewport.start, self._viewport.end
        vis: List[Optional[float]] = [self._value_at_global(gi) for gi in range(start, end)]
        real_vis = [v for v in vis if v is not None]
        if not real_vis:
            return

        vmax = max(real_vis)
        n = len(vis)
        if n <= 0:
            return

        bar_w = max(2.0, plot.width() / max(1, n))
        body_w = max(1.0, bar_w * 0.8)

        brush = QBrush(QColor(80, 120, 220))
        p.setPen(QPen(QColor(80, 120, 220)))
        p.setBrush(brush)

        # NEW: clip plot drawing so bars/crosshair can't bleed into x-label gutter (or outside plot)
        p.save()
        p.setClipRect(plot)

        for i, v in enumerate(vis):
            if v is None:
                continue
            cx = plot.left() + (i + 0.5) * bar_w
            t = v / vmax if vmax > 0 else 0.0
            bar_h = t * plot.height()
            p.drawRect(cx - body_w / 2, plot.bottom() - bar_h, body_w, bar_h)

        # crosshair lines (keep as-is) (clipped)
        if self._crosshair.active and self._crosshair.index is not None:
            idx = self._crosshair.index

            if start <= idx < end:
                x = self._viewport.x_from_index(plot, idx)
                p.setPen(QPen(QColor(120, 120, 140)))
                p.drawLine(int(x), int(plot.top()), int(x), int(plot.bottom()))

            v_cross = self._value_at_global(idx)
            if v_cross is not None and vmax > 0:
                v = v_cross
                if v < 0.0:
                    v = 0.0
                elif v > vmax:
                    v = vmax

                t = v / vmax
                y = plot.bottom() - t * plot.height()

                p.setPen(QPen(QColor(120, 120, 140)))
                p.drawLine(int(plot.left()), int(y), int(plot.right()), int(y))

        p.restore()
        # ---- end clip ----

        # ---- ALWAYS: latest volume value tag (NOT crosshair-based) ----
        if self._volume and vmax > 0:
            v_raw = float(self._volume[-1])
            v_clamped = v_raw
            if v_clamped < 0.0:
                v_clamped = 0.0
            elif v_clamped > vmax:
                v_clamped = vmax

            y_tag = plot.bottom() - (v_clamped / vmax) * plot.height()
            p.setFont(QFont("Consolas", 9))
            draw_right_axis_value_tag(p, axis, y_tag, f"{v_raw:.0f}")

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

        self._resident_base_index = 0

        self.setMouseTracking(True)

        self._viewport.viewport_changed.connect(self.update)
        self._crosshair.changed.connect(self.update)
        self._crosshair.cleared.connect(self.update)

        self._pad_left = 8
        self._pad_top = 6
        self._pad_right = 64
        self._pad_bottom = 14

    def set_values(self, values: List[float]) -> None:
        self._values = values
        self.update()

    def set_resident_base_index(self, base_index: int) -> None:
        self._resident_base_index = max(0, int(base_index))
        self.update()

    def _global_to_local(self, global_index: int) -> Optional[int]:
        local = int(global_index) - self._resident_base_index
        if 0 <= local < len(self._values):
            return local
        return None

    def _value_at_global(self, global_index: int) -> Optional[float]:
        local = self._global_to_local(global_index)
        if local is None:
            return None
        return float(self._values[local])

    def _plot_rect(self) -> QRectF:
        w = self.width()
        h = self.height()
        return QRectF(
            self._pad_left,
            self._pad_top,
            max(1, w - self._pad_left - self._pad_right),
            max(1, h - self._pad_top - self._pad_bottom),
        )

    def _axis_rect(self, plot: QRectF) -> QRectF:
        return QRectF(plot.right(), plot.top(), float(self._pad_right), plot.height())

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
        # slot-centered anchor_rel (NOT continuous mouse-based)
        anchor_rel = ((anchor_idx - self._viewport.start) + 0.5) / max(1, self._viewport.visible)

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
        axis = self._axis_rect(plot)

        p.setPen(QPen(QColor(70, 70, 82)))
        p.drawRect(plot)

        start, end = self._viewport.start, self._viewport.end
        vis: List[Optional[float]] = [self._value_at_global(gi) for gi in range(start, end)]
        real_vis = [v for v in vis if v is not None]
        if len(real_vis) < 2:
            return

        ymin = min(real_vis)
        ymax = max(real_vis)
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

        # NEW: clip plot drawing so line/crosshair can't bleed into x-label gutter (or outside plot)
        p.save()
        p.setClipRect(plot)

        prev_x: float | None = None
        prev_y: float | None = None
        for i, v in enumerate(vis):
            if v is None:
                prev_x = None
                prev_y = None
                continue

            x = plot.left() + i * dx
            y = y_to_px(v)

            if prev_x is not None and prev_y is not None:
                p.drawLine(int(prev_x), int(prev_y), int(x), int(y))

            prev_x, prev_y = x, y

        if self._crosshair.active and self._crosshair.index is not None:
            idx = self._crosshair.index

            if start <= idx < end:
                x = self._viewport.x_from_index(plot, idx)
                p.setPen(QPen(QColor(120, 120, 140)))
                p.drawLine(int(x), int(plot.top()), int(x), int(plot.bottom()))

            v_cross = self._value_at_global(idx)
            if v_cross is not None:
                y = y_to_px(v_cross)
                p.setPen(QPen(QColor(120, 120, 140)))
                p.drawLine(int(plot.left()), int(y), int(plot.right()), int(y))

        p.restore()
        # ---- end clip ----

        # ---- ALWAYS: latest oscillator value tag (NOT crosshair-based) ----
        if self._values:
            v_last = float(self._values[-1])
            y_tag = y_to_px(v_last)
            p.setFont(QFont("Consolas", 9))
            draw_right_axis_value_tag(p, axis, y_tag, f"{v_last:.2f}")

        p.setPen(QPen(QColor(170, 170, 185)))
        p.setFont(QFont("Consolas", 9))
        p.drawText(int(plot.right() + 8), int(plot.top() + 12), self._title)