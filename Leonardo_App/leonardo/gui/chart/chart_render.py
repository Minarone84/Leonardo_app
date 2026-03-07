from __future__ import annotations

from typing import List, Optional, Tuple
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from PySide6.QtCore import Qt, QPoint, QRectF
from PySide6.QtGui import (
    QColor,
    QFont,
    QMouseEvent,
    QPainter,
    QPen,
    QBrush,
    QWheelEvent,
    QFontMetricsF,
)
from PySide6.QtWidgets import QWidget

from leonardo.common.market_types import Candle
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

        self._tz = ZoneInfo("Europe/Rome")

        self._viewport = viewport
        self._candles = candles
        self._crosshair = crosshair

        self._resident_base_index = 0

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

        self._mouse_pt: Optional[QPoint] = None

        self._y_lo: Optional[float] = None
        self._y_hi: Optional[float] = None

        self._y_dragging = False
        self._y_drag_mode: str | None = None  # "zoom" | "pan"
        self._y_drag_start_y: float = 0.0
        self._y_drag_start_lo: float = 0.0
        self._y_drag_start_hi: float = 0.0

    def set_candles(self, candles: List[Candle]) -> None:
        self._candles = candles
        self._y_lo = None
        self._y_hi = None
        self.update()

    def set_resident_base_index(self, base_index: int) -> None:
        self._resident_base_index = max(0, int(base_index))
        self.update()

    def _global_to_local(self, global_index: int) -> Optional[int]:
        local = int(global_index) - self._resident_base_index
        if 0 <= local < len(self._candles):
            return local
        return None

    def _local_to_global(self, local_index: int) -> int:
        return self._resident_base_index + int(local_index)

    def _candle_at_global(self, global_index: int) -> Optional[Candle]:
        local = self._global_to_local(global_index)
        if local is None:
            return None
        return self._candles[local]

    # ---------------- Mouse ----------------

    def mousePressEvent(self, event: QMouseEvent) -> None:
        plot = self._plot_rect()

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

            event.accept()
            return

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
    
        if self._y_dragging and not self._is_anchor_enabled():
            dy = float(event.position().y()) - self._y_drag_start_y
            self._apply_y_axis_drag(plot, dy)
            self.update()
            event.accept()
            return
    
        # During horizontal pan-drag, prioritize panning over hover/crosshair updates.
        # This avoids crosshair jitter and overlay churn while the viewport is moving.
        if self._dragging and self._last_drag_x is not None and plot.contains(pt):
            self._crosshair.set_hover_on_price(False)
            self._mouse_pt = None
    
            dx = pt.x() - self._last_drag_x
            if dx != 0:
                self._pan_by_pixels(plot, dx)
                self._last_drag_x = pt.x()
    
            self.update()
            event.accept()
            return
    
        if plot.contains(pt):
            idx = self._viewport.index_from_x(plot, float(pt.x()))
            self._crosshair.set_index(idx)
            self._crosshair.set_hover_on_price(True)
            self._mouse_pt = pt
        else:
            self._crosshair.set_hover_on_price(False)
            self._mouse_pt = None
    
        self.update()

    def leaveEvent(self, event) -> None:
        self._crosshair.set_hover_on_price(False)
        self._mouse_pt = None
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
        axis = self._axis_rect(plot)

        start, end = self._viewport.start, self._viewport.end
        slots = max(1, end - start)

        # Discrete-grid vertical lines must align to slots
        self._draw_grid(p, plot, start, slots)

        # Build visible candle list *by global slots* (future/non-resident slots -> None)
        vis: List[Optional[Candle]] = []
        for gi in range(start, end):
            vis.append(self._candle_at_global(gi))

        # Determine Y range from real candles only
        real_vis = [c for c in vis if c is not None]
        if not real_vis:
            self._draw_center_text(p, plot, "No data")
            return

        if self._is_anchor_enabled():
            lo, hi = self._visible_minmax(real_vis)
            self._y_lo, self._y_hi = lo, hi
        else:
            lo, hi = self._ensure_non_anchored_range(real_vis)

        if hi <= lo:
            self._draw_center_text(p, plot, "Bad scale")
            return

        self._draw_price_axis(p, plot, lo, hi)

        # ---- NEW: clip all plot drawing to prevent overlap into x-label gutter ----
        p.save()
        p.setClipRect(plot)

        self._draw_candles(p, plot, start, vis, lo, hi)

        # shared vertical (clipped)
        idx2 = self._crosshair.index
        if idx2 is not None and start <= idx2 < end:
            x = self._viewport.x_from_index(plot, idx2)
            p.setPen(QPen(QColor(120, 120, 140)))
            p.drawLine(int(x), int(plot.top()), int(x), int(plot.bottom()))

        # price horizontal only while hovering (clipped)
        if self._crosshair.hover_on_price and self._mouse_pt is not None and plot.contains(self._mouse_pt):
            y = self._mouse_pt.y()
            p.setPen(QPen(QColor(120, 120, 140)))
            p.drawLine(int(plot.left()), int(y), int(plot.right()), int(y))

        p.restore()
        # ---- end clip ----

        # X axis time labels (first, every 5, every 10, ..., last)
        self._draw_time_axis(p, plot, start, vis)

        # ALWAYS latest price tag (latest resident value)
        last = self._candles[-1]
        y_price = self._y_for_price(plot, last.close, lo, hi)
        p.setFont(QFont("Consolas", 9))
        draw_right_axis_value_tag(p, axis, y_price, f"{last.close:.2f}")

    # ---------------- Geometry helpers ----------------

    def _plot_rect(self) -> QRectF:
        return QRectF(
            self._pad_left,
            self._pad_top,
            max(1, self.width() - self._pad_left - self._pad_right),
            max(1, self.height() - self._pad_top - self._pad_bottom),
        )

    def _axis_rect(self, plot: QRectF) -> QRectF:
        return QRectF(plot.right(), plot.top(), float(self._pad_right), plot.height())

    # ---------------- Time axis ----------------

    def _fmt_time_hhmm(self, ts_ms: int) -> str:
        dt_utc = datetime.fromtimestamp(ts_ms / 1000.0, tz=timezone.utc)
        dt_local = dt_utc.astimezone(self._tz)
        return dt_local.strftime("%H:%M")

    def _infer_tf_ms(self) -> Optional[int]:
        """
        Infer timeframe in ms from the last two real candles.
        Returns None if we can't infer reliably.
        """
        if len(self._candles) < 2:
            return None
        a = self._candles[-2].ts_ms
        b = self._candles[-1].ts_ms
        dt = int(b - a)
        if dt <= 0:
            return None
        return dt

    def _slot_ts_ms(self, gi: int) -> Optional[int]:
        """
        Timestamp for a global slot index gi.
        - If gi is a real candle -> candle.ts_ms
        - If gi is future -> infer from last resident candle + timeframe
        """
        c = self._candle_at_global(gi)
        if c is not None:
            return int(c.ts_ms)

        tf = self._infer_tf_ms()
        if tf is None or not self._candles:
            return None

        last_local_idx = len(self._candles) - 1
        last_global_idx = self._local_to_global(last_local_idx)
        last_ts = int(self._candles[last_local_idx].ts_ms)
        steps = gi - last_global_idx
        if steps <= 0:
            return None
        return last_ts + steps * tf

    def _draw_time_axis(self, p: QPainter, plot: QRectF, start_idx: int, vis: List[Optional[Candle]]) -> None:
        n = len(vis)
        if n <= 0:
            return

        # indices: first, 5, 10, 15, ..., last (relative to the visible window)
        label_rel: List[int] = [0]
        step = 5
        for r in range(step, max(0, n - 1), step):
            label_rel.append(r)
        if (n - 1) not in label_rel:
            label_rel.append(n - 1)

        p.save()
        p.setFont(QFont("Consolas", 8))

        fm = QFontMetricsF(p.font())
        y = int(plot.bottom() + 14)

        for r in label_rel:
            gi = start_idx + r

            ts = self._slot_ts_ms(gi)
            if ts is None:
                continue

            x = self._viewport.x_from_index(plot, gi)

            # tick
            p.setPen(QPen(QColor(70, 70, 82)))
            p.drawLine(int(x), int(plot.bottom()), int(x), int(plot.bottom() + 4))

            # label
            p.setPen(QPen(QColor(170, 170, 185)))
            t = self._fmt_time_hhmm(ts)
            tw = fm.horizontalAdvance(t)
            p.drawText(int(x - tw / 2), y, t)

        p.restore()

    # ---------------- Y-scale logic ----------------

    def _is_anchor_enabled(self) -> bool:
        return bool(getattr(self._viewport, "anchor_zoom_enabled", True))

    def _visible_minmax(self, candles: List[Candle]) -> Tuple[float, float]:
        lo = min(c.low for c in candles)
        hi = max(c.high for c in candles)
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
        real = [c for gi in range(start, end) if (c := self._candle_at_global(gi)) is not None]
        if not real:
            return (0.0, 1.0)
        return self._ensure_non_anchored_range(real)

    def _apply_y_axis_drag(self, plot: QRectF, dy_pixels: float) -> None:
        lo0 = self._y_drag_start_lo
        hi0 = self._y_drag_start_hi
        rng0 = max(1e-9, hi0 - lo0)
        h = max(1.0, plot.height())

        if self._y_drag_mode == "zoom":
            s = 1.0 + (dy_pixels / 180.0)
            s = max(0.15, min(8.0, s))
            new_rng = rng0 * s
            mid = (lo0 + hi0) * 0.5
            self._y_lo = mid - new_rng * 0.5
            self._y_hi = mid + new_rng * 0.5
            return

        if self._y_drag_mode == "pan":
            delta = (dy_pixels / h) * rng0
            self._y_lo = lo0 - delta
            self._y_hi = hi0 - delta
            return

    def _y_for_price(self, plot: QRectF, price: float, lo: float, hi: float) -> float:
        t = (price - lo) / (hi - lo)
        return plot.bottom() - t * plot.height()

    # ---------------- Drawing ----------------

    def _draw_grid(self, p: QPainter, plot: QRectF, start_idx: int, slots: int) -> None:
        """
        Vertical grid is DISCRETE and aligned to candle slots.
        Horizontal grid stays proportional (unchanged).
        """
        # --- vertical grid (slot aligned) ---
        grid_pen = QPen(QColor(40, 40, 48))
        grid_pen.setWidth(1)
        p.setPen(grid_pen)

        # Aim for ~10 vertical lines, but aligned to discrete slots
        step = max(1, int(round(slots / max(1, self._grid_v))))
        for r in range(0, slots + 1, step):
            gi = start_idx + r
            # boundary line: left edge of slot r (for r==slots it's right edge)
            if r == slots:
                x = plot.right()
            else:
                # boundary is at center - 0.5 cell; we can reconstruct via x_from_index
                cx = self._viewport.x_from_index(plot, gi)
                cell_w = plot.width() / max(1, slots)
                x = cx - 0.5 * cell_w
            p.drawLine(int(x), int(plot.top()), int(x), int(plot.bottom()))

        # --- horizontal grid (as before) ---
        for i in range(1, self._grid_h):
            y = plot.top() + (i / self._grid_h) * plot.height()
            p.drawLine(int(plot.left()), int(y), int(plot.right()), int(y))

        # border
        border_pen = QPen(QColor(70, 70, 82))
        border_pen.setWidth(1)
        p.setPen(border_pen)
        p.drawRect(plot)

    def _draw_candles(
        self,
        p: QPainter,
        plot: QRectF,
        start_idx: int,
        candles: List[Optional[Candle]],
        lo: float,
        hi: float,
    ) -> None:
        slots = max(1, len(candles))
        cell_w = plot.width() / slots
        body_w = max(1.0, max(3.0, cell_w) * 0.65)

        up_brush = QBrush(QColor(0, 170, 120))
        dn_brush = QBrush(QColor(210, 70, 70))
        wick_pen = QPen(QColor(200, 200, 210))
        wick_pen.setWidth(1)

        p.setPen(wick_pen)

        for i, c in enumerate(candles):
            gi = start_idx + i
            if c is None:
                continue

            cx = self._viewport.x_from_index(plot, gi)

            y_o = self._y_for_price(plot, c.open, lo, hi)
            y_c = self._y_for_price(plot, c.close, lo, hi)
            y_h = self._y_for_price(plot, c.high, lo, hi)
            y_l = self._y_for_price(plot, c.low, lo, hi)

            p.drawLine(int(cx), int(y_h), int(cx), int(y_l))

            top = min(y_o, y_c)
            bot = max(y_o, y_c)
            body_h = max(1.0, bot - top)
            rect = QRectF(cx - body_w / 2, top, body_w, body_h)

            if c.close >= c.open:
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

        try:
            mx = float(event.position().x())
        except Exception:
            mx = float(event.x())

        if not plot.contains(mx, plot.center().y()):
            event.ignore()
            return

        anchor_idx = self._viewport.index_from_x(plot, mx)
        # slot-centered anchor_rel (NOT continuous mouse-based)
        anchor_rel = (((anchor_idx - self._viewport.start) + 0.5) / max(1, self._viewport.visible))

        dy = event.angleDelta().y()
        if dy > 0:
            self._viewport.zoom_in_at(anchor_idx, anchor_rel)
        elif dy < 0:
            self._viewport.zoom_out_at(anchor_idx, anchor_rel)

        event.accept()