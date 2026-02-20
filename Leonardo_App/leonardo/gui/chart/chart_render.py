from __future__ import annotations

from typing import List, Optional, Tuple

from PySide6.QtCore import Qt, QPoint, QRectF
from PySide6.QtGui import QColor, QFont, QMouseEvent, QPainter, QPen, QBrush, QWheelEvent
from PySide6.QtWidgets import QWidget

from leonardo.gui.chart.dummy_data import Candle
from leonardo.gui.chart.viewport import ChartViewport
from leonardo.gui.chart.crosshair import Crosshair


class ChartRenderSurface(QWidget):
    def __init__(
        self,
        viewport: ChartViewport,
        crosshair: Crosshair,
        candles: List[Candle],
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setMouseTracking(True)

        self._viewport = viewport
        self._candles = candles
        self._crosshair = crosshair

        self._viewport.viewport_changed.connect(self.update)
        self._crosshair.changed.connect(self.update)
        self._crosshair.cleared.connect(self.update)

        self._pad_left = 8
        self._pad_top = 8
        self._pad_right = 64
        self._pad_bottom = 18

        self._grid_v = 10
        self._grid_h = 8

        self._dragging = False
        self._last_drag_x: int | None = None

        # local mouse point for PRICE horizontal line (only when hovering price plot)
        self._mouse_pt: Optional[QPoint] = None

        # ---- Non-anchored Y-scale state (price pane only) ----
        self._y_lo: Optional[float] = None
        self._y_hi: Optional[float] = None

        # Right-axis drag state (zoom/pan)
        self._y_dragging = False
        self._y_drag_mode: str | None = None  # "zoom" | "pan"
        self._y_drag_start_y: float = 0.0
        self._y_drag_start_lo: float = 0.0
        self._y_drag_start_hi: float = 0.0

    def set_candles(self, candles: List[Candle]) -> None:
        self._candles = candles
        self._viewport.set_total(len(candles))
        # Reset non-anchored scale baseline to avoid stale ranges
        self._y_lo = None
        self._y_hi = None
        self.update()

    # ---------------- Mouse ----------------

    def mousePressEvent(self, event: QMouseEvent) -> None:
        plot = self._plot_rect()

        # Axis drag (LEFT button) takes precedence over horizontal panning.
        # Only meaningful when anchor is OFF.
        if event.button() == Qt.LeftButton and self._axis_rect(plot).contains(event.position()):
            if not self._is_anchor_enabled():
                lo, hi = self._current_y_range_for_drag()
                self._y_dragging = True
                self._y_drag_mode = "pan" if (event.modifiers() & Qt.ShiftModifier) else "zoom"
                self._y_drag_start_y = float(event.position().y())
                self._y_drag_start_lo = lo
                self._y_drag_start_hi = hi
                event.accept()
                return

            # anchor is ON and user clicked axis: do NOT start horizontal pan
            event.accept()
            return

        # Normal horizontal pan (LEFT button ONLY inside plot)
        if event.button() == Qt.LeftButton and plot.contains(event.position()):
            self._dragging = True
            self._last_drag_x = int(event.position().x())
            event.accept()
            return

        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.LeftButton and self._y_dragging:
            self._y_dragging = False
            self._y_drag_mode = None
            event.accept()
            return

        if event.button() == Qt.LeftButton:
            self._dragging = False
            self._last_drag_x = None
            event.accept()
            return

        super().mouseReleaseEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        pt = event.position().toPoint()
        plot = self._plot_rect()

        # Handle axis drag (vertical zoom/pan) when active
        if self._y_dragging and not self._is_anchor_enabled():
            dy = float(event.position().y()) - self._y_drag_start_y
            self._apply_y_axis_drag(plot, dy)
            self.update()
            event.accept()
            return

        if plot.contains(pt):
            # --- UPDATED: new Crosshair API (shared vertical index + price hover flag) ---
            idx = self._viewport.index_from_x(plot, float(pt.x()))
            self._crosshair.set_index(idx)
            self._crosshair.set_hover_on_price(True)

            # local price horizontal line position (only for price pane)
            self._mouse_pt = pt
        else:
            # Leaving plot: stop price horizontal line, but KEEP shared index.
            self._crosshair.set_hover_on_price(False)
            self._mouse_pt = None

        # Pan if dragging (left button) - only when inside plot
        if self._dragging and self._last_drag_x is not None and plot.contains(pt):
            dx = pt.x() - self._last_drag_x
            if dx != 0:
                self._pan_by_pixels(plot, dx)
                self._last_drag_x = pt.x()

        self.update()

    def leaveEvent(self, event) -> None:
        # --- UPDATED: do NOT clear shared index; only stop price horizontal line ---
        self._crosshair.set_hover_on_price(False)
        self._mouse_pt = None

        # If pointer leaves while axis-dragging, end it cleanly
        self._y_dragging = False
        self._y_drag_mode = None

        self.update()
        super().leaveEvent(event)

    # ---------------- Paint ----------------

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, False)

        w = self.width()
        h = self.height()
        p.fillRect(0, 0, w, h, QColor(12, 12, 14))

        plot = self._plot_rect()
        self._draw_grid(p, plot)

        start, end = self._viewport.start, self._viewport.end
        vis = self._candles[start:end]
        if not vis:
            self._draw_center_text(p, plot, "No data")
            return

        # Determine Y range
        if self._is_anchor_enabled():
            lo, hi = self._visible_minmax(vis)
            # keep a fresh baseline for when user disables anchor
            self._y_lo, self._y_hi = lo, hi
        else:
            lo, hi = self._ensure_non_anchored_range(vis)

        if hi <= lo:
            self._draw_center_text(p, plot, "Bad scale")
            return

        self._draw_price_axis(p, plot, lo, hi)
        self._draw_candles(p, plot, vis, lo, hi)

        # ---- Shared vertical line (always when we have an index in range) ----
        idx = self._crosshair.index
        if idx is not None and start <= idx < end:
            x = self._viewport.x_from_index(plot, idx)
            p.setPen(QPen(QColor(120, 120, 140)))
            p.drawLine(int(x), int(plot.top()), int(x), int(plot.bottom()))

        # ---- Price horizontal line ONLY when hovering price plot ----
        # --- UPDATED: use crosshair.hover_on_price as source of truth ---
        if self._crosshair.hover_on_price and self._mouse_pt is not None and plot.contains(self._mouse_pt):
            y = self._mouse_pt.y()
            p.setPen(QPen(QColor(120, 120, 140)))
            p.drawLine(int(plot.left()), int(y), int(plot.right()), int(y))

    # ---------------- Geometry helpers ----------------

    def _plot_rect(self) -> QRectF:
        return QRectF(
            self._pad_left,
            self._pad_top,
            max(1, self.width() - self._pad_left - self._pad_right),
            max(1, self.height() - self._pad_top - self._pad_bottom),
        )

    def _axis_rect(self, plot: QRectF) -> QRectF:
        # The right “price bar” region where labels are drawn
        return QRectF(plot.right(), plot.top(), float(self._pad_right), plot.height())

    # ---------------- Y-scale logic ----------------

    def _is_anchor_enabled(self) -> bool:
        return bool(getattr(self._viewport, "anchor_zoom_enabled", True))

    def _visible_minmax(self, candles: List[Candle]) -> Tuple[float, float]:
        lo = min(c.l for c in candles)
        hi = max(c.h for c in candles)
        span = max(1e-6, hi - lo)
        return (lo - 0.03 * span, hi + 0.03 * span)

    def _ensure_non_anchored_range(self, vis: List[Candle]) -> Tuple[float, float]:
        if self._y_lo is None or self._y_hi is None or self._y_hi <= self._y_lo:
            lo, hi = self._visible_minmax(vis)
            self._y_lo, self._y_hi = lo, hi
            return lo, hi
        return self._y_lo, self._y_hi

    def _current_y_range_for_drag(self) -> Tuple[float, float]:
        start, end = self._viewport.start, self._viewport.end
        vis = self._candles[start:end]
        if not vis:
            return (0.0, 1.0)
        return self._ensure_non_anchored_range(vis)

    def _apply_y_axis_drag(self, plot: QRectF, dy_pixels: float) -> None:
        lo0 = self._y_drag_start_lo
        hi0 = self._y_drag_start_hi
        rng0 = max(1e-9, hi0 - lo0)
        h = max(1.0, plot.height())

        if self._y_drag_mode == "zoom":
            # drag down -> zoom out (bigger range); drag up -> zoom in
            s = 1.0 + (dy_pixels / 180.0)
            s = max(0.15, min(8.0, s))
            new_rng = rng0 * s
            mid = (lo0 + hi0) * 0.5
            self._y_lo = mid - new_rng * 0.5
            self._y_hi = mid + new_rng * 0.5
            return

        if self._y_drag_mode == "pan":
            # shift+drag: move window up/down without changing range
            delta = (dy_pixels / h) * rng0
            self._y_lo = lo0 - delta
            self._y_hi = hi0 - delta
            return

    def _y_for_price(self, plot: QRectF, price: float, lo: float, hi: float) -> float:
        t = (price - lo) / (hi - lo)
        return plot.bottom() - t * plot.height()

    # ---------------- Drawing ----------------

    def _draw_grid(self, p: QPainter, plot: QRectF) -> None:
        grid_pen = QPen(QColor(40, 40, 48))
        grid_pen.setWidth(1)
        p.setPen(grid_pen)

        for i in range(1, self._grid_v):
            x = plot.left() + (i / self._grid_v) * plot.width()
            p.drawLine(int(x), int(plot.top()), int(x), int(plot.bottom()))

        for i in range(1, self._grid_h):
            y = plot.top() + (i / self._grid_h) * plot.height()
            p.drawLine(int(plot.left()), int(y), int(plot.right()), int(y))

        border_pen = QPen(QColor(70, 70, 82))
        border_pen.setWidth(1)
        p.setPen(border_pen)
        p.drawRect(plot)

    def _draw_candles(self, p: QPainter, plot: QRectF, candles: List[Candle], lo: float, hi: float) -> None:
        n = len(candles)
        candle_w = max(3.0, plot.width() / max(1, n))
        body_w = max(1.0, candle_w * 0.65)

        up_brush = QBrush(QColor(0, 170, 120))
        dn_brush = QBrush(QColor(210, 70, 70))
        wick_pen = QPen(QColor(200, 200, 210))
        wick_pen.setWidth(1)

        p.setPen(wick_pen)

        for i, c in enumerate(candles):
            cx = plot.left() + (i + 0.5) * candle_w

            y_o = self._y_for_price(plot, c.o, lo, hi)
            y_c = self._y_for_price(plot, c.c, lo, hi)
            y_h = self._y_for_price(plot, c.h, lo, hi)
            y_l = self._y_for_price(plot, c.l, lo, hi)

            p.drawLine(int(cx), int(y_h), int(cx), int(y_l))

            top = min(y_o, y_c)
            bot = max(y_o, y_c)
            body_h = max(1.0, bot - top)
            rect = QRectF(cx - body_w / 2, top, body_w, body_h)

            if c.c >= c.o:
                p.fillRect(rect, up_brush)
                p.setPen(QPen(QColor(0, 220, 160)))
                p.drawRect(rect)
            else:
                p.fillRect(rect, dn_brush)
                p.setPen(QPen(QColor(240, 110, 110)))
                p.drawRect(rect)

            p.setPen(wick_pen)

    def _draw_price_axis(self, p: QPainter, plot: QRectF, lo: float, hi: float) -> None:
        p.setPen(QPen(QColor(170, 170, 185)))
        p.setFont(QFont("Consolas", 9))

        steps = 5
        for i in range(steps + 1):
            t = i / steps
            price = hi - t * (hi - lo)
            y = plot.top() + t * plot.height()
            label = f"{price:0.2f}"
            p.drawLine(int(plot.right()), int(y), int(plot.right() + 6), int(y))
            p.drawText(int(plot.right() + 8), int(y + 4), label)

    def _draw_center_text(self, p: QPainter, plot: QRectF, text: str) -> None:
        p.setPen(QPen(QColor(220, 220, 230)))
        p.setFont(QFont("Segoe UI", 11))
        p.drawText(plot, Qt.AlignCenter, text)

    # ---------------- Horizontal pan/zoom ----------------

    def _pan_by_pixels(self, plot: QRectF, dx_pixels: int) -> None:
        if dx_pixels == 0:
            return
        step = int(abs(dx_pixels) / max(1.0, plot.width()) * self._viewport.visible)
        step = max(1, step)

        if dx_pixels > 0:
            self._viewport.pan_left(step)
        else:
            self._viewport.pan_right(step)

    def wheelEvent(self, event: QWheelEvent) -> None:
        plot = self._plot_rect()

        # only zoom when mouse is over plot area
        try:
            mx = float(event.position().x())
        except Exception:
            mx = float(event.x())

        if not plot.contains(mx, plot.center().y()):
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