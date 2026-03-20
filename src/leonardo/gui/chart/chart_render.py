from __future__ import annotations

import math
from bisect import bisect_left
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable, List, Optional, Tuple
from zoneinfo import ZoneInfo

from PySide6.QtCore import QPoint, QRectF, Qt
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QFontMetricsF,
    QMouseEvent,
    QPainter,
    QPen,
    QWheelEvent,
)
from PySide6.QtWidgets import QWidget

from leonardo.common.market_types import Candle
from leonardo.gui.chart.crosshair import Crosshair
from leonardo.gui.chart.viewport import ChartViewport


DAY_MS = 24 * 60 * 60 * 1000


@dataclass(frozen=True)
class TimeAxisTick:
    gi: int
    ts_ms: int
    x: float
    label: str
    priority: int  # 0=regular, 1=day, 2=month, 3=year


def draw_right_axis_value_tag(
    p: QPainter,
    axis: QRectF,
    y: float,
    text: str,
) -> None:
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
    p.setBrush(QColor(255, 165, 0))
    p.setOpacity(0.5)
    p.drawRoundedRect(r, 6.0, 6.0)
    p.setOpacity(1.0)
    p.setPen(QColor(0, 0, 0))
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

        self._grid_h = 8

        self._dragging = False
        self._last_drag_x: int | None = None
        self._last_drag_y: int | None = None

        self._mouse_pt: Optional[QPoint] = None

        self._y_lo: Optional[float] = None
        self._y_hi: Optional[float] = None
        self._last_anchor_enabled: bool = bool(
            getattr(self._viewport, "anchor_zoom_enabled", True)
        )

        self._y_dragging = False
        self._y_drag_mode: str | None = None  # "zoom" | "pan"
        self._y_drag_start_y: float = 0.0
        self._y_drag_start_lo: float = 0.0
        self._y_drag_start_hi: float = 0.0

        self._overlay_palette: Tuple[QColor, ...] = (
            QColor(255, 165, 0),   # orange
            QColor(0, 200, 255),   # cyan
            QColor(186, 104, 200), # purple
            QColor(255, 214, 102), # amber
            QColor(76, 175, 80),   # green
            QColor(239, 83, 80),   # red
        )

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

    def _overlay_series(self) -> List[object]:
        """
        Compatibility bridge for the current architecture.

        PricePane owns ChartModel and creates this render surface as its child.
        We read overlays from the parent pane's model so we can render them
        without changing pane construction in this step.
        """
        parent = self.parent()
        if parent is None:
            return []

        model = getattr(parent, "_model", None)
        if model is None:
            return []

        overlays_fn = getattr(model, "overlays", None)
        if not callable(overlays_fn):
            return []

        try:
            overlays = overlays_fn()
        except Exception:
            return []

        if isinstance(overlays, dict):
            return list(overlays.values())

        return []

    def _iter_finite_overlay_values_in_view(self, start: int, end: int) -> Iterable[float]:
        for series in self._overlay_series():
            values = getattr(series, "values", None)
            if not isinstance(values, list):
                continue

            for gi in range(start, end):
                local = self._global_to_local(gi)
                if local is None or local >= len(values):
                    continue

                raw = values[local]
                try:
                    val = float(raw)
                except Exception:
                    continue

                if math.isfinite(val):
                    yield val

    def _coerce_color(self, value: object, fallback: QColor) -> QColor:
        if isinstance(value, QColor):
            return value

        if value is None:
            return fallback

        text = str(value).strip()
        if not text:
            return fallback

        candidate = QColor(text)
        if candidate.isValid():
            return candidate

        return fallback

    def _qt_pen_style_for_series(self, series: object) -> Qt.PenStyle:
        style_obj = getattr(series, "style", None)
        if style_obj is None:
            return Qt.SolidLine

        line_style = str(getattr(style_obj, "line_style", "solid") or "solid").strip().lower()

        if line_style == "dotted":
            return Qt.DotLine
        if line_style == "dashed":
            return Qt.DashLine
        if line_style == "dash_dot":
            return Qt.DashDotLine
        return Qt.SolidLine

    def _pen_width_for_series(self, series: object) -> int:
        style_obj = getattr(series, "style", None)
        if style_obj is None:
            return 2

        try:
            width = int(getattr(style_obj, "line_width", 2))
        except Exception:
            width = 2

        return max(1, min(8, width))

    def _pen_color_for_series(self, series: object, series_index: int) -> QColor:
        fallback = self._overlay_palette[series_index % len(self._overlay_palette)]
        style_obj = getattr(series, "style", None)
        if style_obj is None:
            return fallback

        return self._coerce_color(getattr(style_obj, "color", None), fallback)

    # ---------------- Mouse ----------------

    def mousePressEvent(self, event: QMouseEvent) -> None:
        plot = self._plot_rect()

        if event.button() == Qt.LeftButton and self._axis_rect(plot).contains(
            event.position()
        ):
            if not self._is_anchor_enabled():
                lo, hi = self._current_y_range_for_drag()
                self._y_dragging = True
                self._y_drag_mode = (
                    "pan" if (event.modifiers() & Qt.ShiftModifier) else "zoom"
                )
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
            self._last_drag_y = int(event.position().y())
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
            self._last_drag_y = None
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

        if self._dragging and self._last_drag_x is not None and plot.contains(pt):
            self._crosshair.set_hover_on_price(False)
            self._mouse_pt = None

            dx = pt.x() - self._last_drag_x
            if dx != 0:
                self._pan_by_pixels(plot, dx)
                self._last_drag_x = pt.x()

            if not self._is_anchor_enabled() and self._last_drag_y is not None:
                dy = pt.y() - self._last_drag_y
                if dy != 0:
                    self._pan_y_by_pixels(plot, dy)
                    self._last_drag_y = pt.y()

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

        time_ticks = self._build_time_axis_ticks(plot, start, slots)
        self._draw_grid(p, plot, time_ticks)

        if not self._candles:
            self._draw_center_text(p, plot, "No data")
            return

        vis: List[Optional[Candle]] = []
        for gi in range(start, end):
            vis.append(self._candle_at_global(gi))

        real_vis = [c for c in vis if c is not None]
        anchor_enabled = self._is_anchor_enabled()

        if real_vis:
            if anchor_enabled:
                lo, hi = self._visible_minmax(real_vis)
                overlay_vals = list(self._iter_finite_overlay_values_in_view(start, end))
                if overlay_vals:
                    lo = min(lo, min(overlay_vals))
                    hi = max(hi, max(overlay_vals))
                    span = max(1e-6, hi - lo)
                    lo -= 0.03 * span
                    hi += 0.03 * span
                self._y_lo, self._y_hi = lo, hi
            else:
                if self._last_anchor_enabled:
                    lo, hi = self._visible_minmax(real_vis)
                    overlay_vals = list(self._iter_finite_overlay_values_in_view(start, end))
                    if overlay_vals:
                        lo = min(lo, min(overlay_vals))
                        hi = max(hi, max(overlay_vals))
                        span = max(1e-6, hi - lo)
                        lo -= 0.03 * span
                        hi += 0.03 * span
                    lo, hi = self._clamp_non_anchored_range(lo, hi)
                    self._y_lo, self._y_hi = lo, hi
                else:
                    lo, hi = self._ensure_non_anchored_range(real_vis)
        else:
            if anchor_enabled:
                lo, hi = self._resident_minmax()
                self._y_lo, self._y_hi = lo, hi
            else:
                lo, hi = self._ensure_non_anchored_range([])

        self._last_anchor_enabled = anchor_enabled

        if hi <= lo:
            self._draw_center_text(p, plot, "Bad scale")
            return

        self._draw_price_axis(p, plot, lo, hi)

        p.save()
        p.setClipRect(plot)

        self._draw_candles(p, plot, start, vis, lo, hi)
        self._draw_overlays(p, plot, start, end, lo, hi)

        idx2 = self._crosshair.index
        if idx2 is not None and start <= idx2 < end:
            x = self._viewport.x_from_index(plot, idx2)
            p.setPen(QPen(QColor(120, 120, 140)))
            p.drawLine(int(x), int(plot.top()), int(x), int(plot.bottom()))

        if (
            self._crosshair.hover_on_price
            and self._mouse_pt is not None
            and plot.contains(self._mouse_pt)
        ):
            y = self._mouse_pt.y()
            p.setPen(QPen(QColor(120, 120, 140)))
            p.drawLine(int(plot.left()), int(y), int(plot.right()), int(y))

        p.restore()

        if start < 0:
            self._draw_left_gap_message(p, plot, start, slots, "No older data")

        self._draw_time_axis(p, plot, time_ticks)

        if idx2 is not None and start <= idx2 < end:
            self._draw_crosshair_time_tag(p, plot, idx2)

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

    def _slot_dt_local(self, gi: int) -> Optional[datetime]:
        ts = self._slot_ts_ms(gi)
        if ts is None:
            return None

        dt_utc = datetime.fromtimestamp(ts / 1000.0, tz=timezone.utc)
        return dt_utc.astimezone(self._tz)

    def _fmt_crosshair_time(self, ts_ms: int) -> str:
        dt_local = datetime.fromtimestamp(ts_ms / 1000.0, tz=timezone.utc).astimezone(
            self._tz
        )
        return dt_local.strftime("%d %b %Y %H:%M")

    def _time_tick_priority(self, prev_dt: Optional[datetime], cur_dt: datetime) -> int:
        if prev_dt is None:
            return 3
        if cur_dt.year != prev_dt.year:
            return 3
        if cur_dt.month != prev_dt.month:
            return 2
        if cur_dt.date() != prev_dt.date():
            return 1
        return 0

    def _regular_label_for_interval(self, dt: datetime, interval_ms: int) -> str:
        if interval_ms >= 365 * DAY_MS:
            return dt.strftime("%Y")
        if interval_ms >= 28 * DAY_MS:
            return dt.strftime("%b %Y")
        if interval_ms >= DAY_MS:
            return dt.strftime("%d %b")
        return dt.strftime("%H:%M")

    def _format_tick_label(
        self,
        prev_dt: Optional[datetime],
        cur_dt: datetime,
        interval_ms: int,
    ) -> Tuple[str, int]:
        priority = self._time_tick_priority(prev_dt, cur_dt)

        if priority >= 3:
            return cur_dt.strftime("%Y %b"), 3
        if priority == 2:
            return cur_dt.strftime("%b %d"), 2
        if priority == 1:
            return cur_dt.strftime("%d %H:%M"), 1

        return self._regular_label_for_interval(cur_dt, interval_ms), 0

    def _nice_interval_multipliers(self) -> Tuple[int, ...]:
        return (
            1,
            2,
            3,
            5,
            10,
            15,
            20,
            30,
            60,
            120,
            180,
            240,
            360,
            480,
            720,
            1440,
            2880,
            4320,
            10080,
            20160,
            43200,
            86400,
            172800,
            259200,
            518400,
        )

    def _choose_major_interval_ms(
        self,
        base_tf_ms: int,
        visible_span_ms: int,
        plot_width: float,
    ) -> int:
        target_px = 120.0
        desired_tick_count = max(2.0, plot_width / target_px)
        target_interval_ms = max(
            base_tf_ms,
            int(visible_span_ms / max(1.0, desired_tick_count)),
        )

        for mult in self._nice_interval_multipliers():
            interval_ms = max(base_tf_ms, base_tf_ms * mult)
            if interval_ms >= target_interval_ms:
                return interval_ms

        return max(base_tf_ms, base_tf_ms * self._nice_interval_multipliers()[-1])

    def _floor_local_time_to_interval(
        self,
        dt_local: datetime,
        interval_ms: int,
    ) -> datetime:
        if interval_ms < DAY_MS:
            midnight = dt_local.replace(hour=0, minute=0, second=0, microsecond=0)
            elapsed_ms = int((dt_local - midnight).total_seconds() * 1000.0)
            floored_ms = (elapsed_ms // interval_ms) * interval_ms
            return midnight + timedelta(milliseconds=floored_ms)

        if interval_ms < 28 * DAY_MS:
            midnight = dt_local.replace(hour=0, minute=0, second=0, microsecond=0)
            day_step = max(1, interval_ms // DAY_MS)
            epoch_day = datetime(1970, 1, 1, tzinfo=self._tz)
            days_since_epoch = (midnight.date() - epoch_day.date()).days
            floored_days = (days_since_epoch // day_step) * day_step
            return epoch_day + timedelta(days=floored_days)

        month_step = max(1, interval_ms // (28 * DAY_MS))
        month_index = dt_local.year * 12 + (dt_local.month - 1)
        floored_month_index = (month_index // month_step) * month_step
        year = floored_month_index // 12
        month = (floored_month_index % 12) + 1
        return datetime(year, month, 1, tzinfo=self._tz)

    def _visible_slot_time_points(
        self,
        start_idx: int,
        slots: int,
    ) -> List[Tuple[int, int]]:
        points: List[Tuple[int, int]] = []
        for gi in range(start_idx, start_idx + slots):
            ts = self._slot_ts_ms(gi)
            if ts is None:
                continue
            points.append((gi, ts))
        return points

    def _nearest_visible_gi_for_ts(
        self,
        ts_ms: int,
        visible_points: List[Tuple[int, int]],
    ) -> Optional[int]:
        if not visible_points:
            return None

        ts_values = [ts for _, ts in visible_points]
        pos = bisect_left(ts_values, ts_ms)

        candidates: List[Tuple[int, int]] = []
        if pos < len(visible_points):
            candidates.append(visible_points[pos])
        if pos > 0:
            candidates.append(visible_points[pos - 1])

        if not candidates:
            return None

        gi, nearest_ts = min(candidates, key=lambda item: abs(item[1] - ts_ms))
        tolerance_ms = max(1, self._infer_tf_ms() or 1)
        return gi if abs(nearest_ts - ts_ms) <= tolerance_ms else None

    def _build_time_axis_ticks(
        self,
        plot: QRectF,
        start_idx: int,
        slots: int,
    ) -> List[TimeAxisTick]:
        if slots <= 0 or plot.width() <= 1.0:
            return []

        base_tf_ms = self._infer_tf_ms()
        if base_tf_ms is None or base_tf_ms <= 0:
            return []

        visible_points = self._visible_slot_time_points(start_idx, slots)
        if len(visible_points) < 2:
            return []

        start_ts = visible_points[0][1]
        end_ts = visible_points[-1][1]
        visible_span_ms = max(base_tf_ms, end_ts - start_ts)

        major_interval_ms = self._choose_major_interval_ms(
            base_tf_ms=base_tf_ms,
            visible_span_ms=visible_span_ms,
            plot_width=plot.width(),
        )

        first_dt = datetime.fromtimestamp(start_ts / 1000.0, tz=timezone.utc).astimezone(
            self._tz
        )
        tick_dt = self._floor_local_time_to_interval(first_dt, major_interval_ms)

        if int(tick_dt.timestamp() * 1000) < start_ts:
            while int(tick_dt.timestamp() * 1000) < start_ts:
                tick_dt += timedelta(milliseconds=major_interval_ms)
            tick_dt -= timedelta(milliseconds=major_interval_ms)

        ticks: List[TimeAxisTick] = []
        prev_tick_dt: Optional[datetime] = None
        seen_gi: set[int] = set()

        last_limit_ts = end_ts + major_interval_ms

        while int(tick_dt.timestamp() * 1000) <= last_limit_ts:
            tick_ts = int(tick_dt.timestamp() * 1000)
            gi = self._nearest_visible_gi_for_ts(tick_ts, visible_points)

            if gi is not None and start_idx <= gi < (start_idx + slots) and gi not in seen_gi:
                actual_dt = self._slot_dt_local(gi)
                if actual_dt is not None:
                    label, priority = self._format_tick_label(
                        prev_dt=prev_tick_dt,
                        cur_dt=actual_dt,
                        interval_ms=major_interval_ms,
                    )
                    x = self._viewport.x_from_index(plot, gi)

                    ticks.append(
                        TimeAxisTick(
                            gi=gi,
                            ts_ms=tick_ts,
                            x=x,
                            label=label,
                            priority=priority,
                        )
                    )
                    seen_gi.add(gi)
                    prev_tick_dt = actual_dt

            tick_dt += timedelta(milliseconds=major_interval_ms)

        font = QFont("Consolas", 8)
        fm = QFontMetricsF(font)

        filtered: List[TimeAxisTick] = []
        last_right = float("-inf")
        min_sep = 10.0

        for tick in ticks:
            text_w = fm.horizontalAdvance(tick.label)
            left = tick.x - (text_w / 2.0)
            right = tick.x + (text_w / 2.0)

            if left >= (last_right + min_sep):
                filtered.append(tick)
                last_right = right
                continue

            if filtered and tick.priority > filtered[-1].priority:
                prev = filtered[-1]
                prev_w = fm.horizontalAdvance(prev.label)
                prev_left = prev.x - (prev_w / 2.0)
                if left >= prev_left:
                    filtered[-1] = tick
                    last_right = right

        return filtered

    def _draw_time_axis(
        self,
        p: QPainter,
        plot: QRectF,
        ticks: List[TimeAxisTick],
    ) -> None:
        if not ticks:
            return

        p.save()
        p.setFont(QFont("Consolas", 8))
        fm = QFontMetricsF(p.font())
        y = int(plot.bottom() + 14)

        for tick in ticks:
            p.setPen(QPen(QColor(70, 70, 82)))
            p.drawLine(
                int(tick.x),
                int(plot.bottom()),
                int(tick.x),
                int(plot.bottom() + 4),
            )

            if tick.priority >= 2:
                p.setPen(QPen(QColor(205, 205, 220)))
            elif tick.priority == 1:
                p.setPen(QPen(QColor(185, 185, 205)))
            else:
                p.setPen(QPen(QColor(170, 170, 185)))

            tw = fm.horizontalAdvance(tick.label)
            p.drawText(int(tick.x - tw / 2), y, tick.label)

        p.restore()

    def _draw_crosshair_time_tag(
        self,
        p: QPainter,
        plot: QRectF,
        gi: int,
    ) -> None:
        ts = self._slot_ts_ms(gi)
        if ts is None:
            return

        text = self._fmt_crosshair_time(ts)
        x = self._viewport.x_from_index(plot, gi)

        p.save()
        p.setFont(QFont("Consolas", 8))

        fm = QFontMetricsF(p.font())
        pad_x = 7.0
        pad_y = 3.0

        text_w = fm.horizontalAdvance(text)
        text_h = fm.height()

        tag_w = text_w + 2 * pad_x
        tag_h = text_h + 2 * pad_y

        x_left = x - (tag_w / 2.0)
        x_left = max(plot.left(), min(plot.right() - tag_w, x_left))

        y_top = plot.bottom() + 2.0
        r = QRectF(x_left, y_top, tag_w, tag_h)

        p.setPen(Qt.NoPen)
        p.setBrush(QColor(225, 225, 225))
        p.drawRoundedRect(r, 4.0, 4.0)

        p.setPen(QColor(0, 0, 0))
        p.drawText(r, Qt.AlignCenter, text)
        p.restore()

    # ---------------- Y-scale logic ----------------

    def _is_anchor_enabled(self) -> bool:
        return bool(getattr(self._viewport, "anchor_zoom_enabled", True))

    def _visible_minmax(self, candles: List[Candle]) -> Tuple[float, float]:
        lo = min(c.low for c in candles)
        hi = max(c.high for c in candles)
        span = max(1e-6, hi - lo)
        return (lo - 0.03 * span, hi + 0.03 * span)

    def _resident_minmax(self) -> Tuple[float, float]:
        if not self._candles:
            return (0.0, 1.0)

        lo = min(c.low for c in self._candles)
        hi = max(c.high for c in self._candles)
        span = max(1e-6, hi - lo)
        return (lo - 0.03 * span, hi + 0.03 * span)

    def _clamp_non_anchored_range(self, lo: float, hi: float) -> Tuple[float, float]:
        """
        In non-anchored mode, vertical navigation is manual and should not be
        clamped back into the resident candle envelope.

        This helper now only guarantees a valid, non-degenerate range.
        """
        if hi <= lo:
            return self._resident_minmax()
        return (lo, hi)

    def _ensure_non_anchored_range(self, vis: List[Candle]) -> Tuple[float, float]:
        if self._y_lo is None or self._y_hi is None or self._y_hi <= self._y_lo:
            if vis:
                lo, hi = self._visible_minmax(vis)
                lo, hi = self._clamp_non_anchored_range(lo, hi)
            else:
                lo, hi = self._resident_minmax()

            self._y_lo, self._y_hi = lo, hi
            return lo, hi

        lo, hi = self._clamp_non_anchored_range(self._y_lo, self._y_hi)
        self._y_lo, self._y_hi = lo, hi
        return lo, hi

    def _current_y_range_for_drag(self) -> Tuple[float, float]:
        start, end = self._viewport.start, self._viewport.end
        real = [
            c
            for gi in range(start, end)
            if (c := self._candle_at_global(gi)) is not None
        ]
        if not real:
            return self._ensure_non_anchored_range([])
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
            lo = mid - new_rng * 0.5
            hi = mid + new_rng * 0.5
            self._y_lo, self._y_hi = self._clamp_non_anchored_range(lo, hi)
            return

        if self._y_drag_mode == "pan":
            delta = (dy_pixels / h) * rng0
            lo = lo0 + delta
            hi = hi0 + delta
            self._y_lo, self._y_hi = self._clamp_non_anchored_range(lo, hi)
            return

    def _pan_y_by_pixels(self, plot: QRectF, dy_pixels: int) -> None:
        lo, hi = self._current_y_range_for_drag()
        rng = max(1e-9, hi - lo)
        h = max(1.0, plot.height())

        delta = (float(dy_pixels) / h) * rng
        new_lo = lo + delta
        new_hi = hi + delta
        self._y_lo, self._y_hi = self._clamp_non_anchored_range(new_lo, new_hi)

    def _y_for_price(self, plot: QRectF, price: float, lo: float, hi: float) -> float:
        t = (price - lo) / (hi - lo)
        return plot.bottom() - t * plot.height()

    # ---------------- Drawing ----------------

    def _draw_grid(
        self,
        p: QPainter,
        plot: QRectF,
        time_ticks: List[TimeAxisTick],
    ) -> None:
        grid_pen = QPen(QColor(40, 40, 48))
        grid_pen.setWidth(1)
        p.setPen(grid_pen)

        for tick in time_ticks:
            p.drawLine(int(tick.x), int(plot.top()), int(tick.x), int(plot.bottom()))

        for i in range(1, self._grid_h):
            y = plot.top() + (i / self._grid_h) * plot.height()
            p.drawLine(int(plot.left()), int(y), int(plot.right()), int(y))

        border_pen = QPen(QColor(70, 70, 82))
        border_pen.setWidth(1)
        p.setPen(border_pen)
        p.drawRect(plot)

    def _draw_compressed_candle(
        self,
        p: QPainter,
        x_px: int,
        open_price: float,
        high_price: float,
        low_price: float,
        close_price: float,
        lo: float,
        hi: float,
        plot: QRectF,
    ) -> None:
        y_o = self._y_for_price(plot, open_price, lo, hi)
        y_c = self._y_for_price(plot, close_price, lo, hi)
        y_h = self._y_for_price(plot, high_price, lo, hi)
        y_l = self._y_for_price(plot, low_price, lo, hi)

        wick_pen = QPen(QColor(200, 200, 210))
        wick_pen.setWidth(1)
        p.setPen(wick_pen)
        p.drawLine(x_px, int(y_h), x_px, int(y_l))

        top = min(y_o, y_c)
        bot = max(y_o, y_c)
        body_h = max(1.0, bot - top)
        rect = QRectF(float(x_px), top, 1.0, body_h)

        if close_price >= open_price:
            p.fillRect(rect, QBrush(QColor(0, 170, 120)))
            p.setPen(QPen(QColor(0, 220, 160)))
            p.drawRect(rect)
        else:
            p.fillRect(rect, QBrush(QColor(210, 70, 70)))
            p.setPen(QPen(QColor(240, 110, 110)))
            p.drawRect(rect)

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

        if cell_w < 2.0:
            agg_x: Optional[int] = None
            agg_open: Optional[float] = None
            agg_high: Optional[float] = None
            agg_low: Optional[float] = None
            agg_close: Optional[float] = None

            def flush_bucket() -> None:
                if (
                    agg_x is None
                    or agg_open is None
                    or agg_high is None
                    or agg_low is None
                    or agg_close is None
                ):
                    return

                self._draw_compressed_candle(
                    p=p,
                    x_px=agg_x,
                    open_price=agg_open,
                    high_price=agg_high,
                    low_price=agg_low,
                    close_price=agg_close,
                    lo=lo,
                    hi=hi,
                    plot=plot,
                )

            for i, c in enumerate(candles):
                gi = start_idx + i
                if c is None:
                    continue

                cx = self._viewport.x_from_index(plot, gi)
                x_px = int(cx)

                if agg_x is None:
                    agg_x = x_px
                    agg_open = c.open
                    agg_high = c.high
                    agg_low = c.low
                    agg_close = c.close
                    continue

                if x_px != agg_x:
                    flush_bucket()
                    agg_x = x_px
                    agg_open = c.open
                    agg_high = c.high
                    agg_low = c.low
                    agg_close = c.close
                    continue

                agg_high = max(float(agg_high), c.high)
                agg_low = min(float(agg_low), c.low)
                agg_close = c.close

            flush_bucket()
            return

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

    def _draw_overlay_segment_points(
        self,
        p: QPainter,
        points: List[Tuple[float, float]],
    ) -> None:
        if len(points) < 2:
            return

        for i in range(1, len(points)):
            x1, y1 = points[i - 1]
            x2, y2 = points[i]
            p.drawLine(int(x1), int(y1), int(x2), int(y2))

    def _draw_overlays(
        self,
        p: QPainter,
        plot: QRectF,
        start_idx: int,
        end_idx: int,
        lo: float,
        hi: float,
    ) -> None:
        overlays = self._overlay_series()
        if not overlays:
            return

        p.save()
        p.setRenderHint(QPainter.Antialiasing, True)

        for series_index, series in enumerate(overlays):
            values = getattr(series, "values", None)
            if not isinstance(values, list) or not values:
                continue

            color = self._pen_color_for_series(series, series_index)
            pen = QPen(color)
            pen.setWidth(self._pen_width_for_series(series))
            pen.setStyle(self._qt_pen_style_for_series(series))
            p.setPen(pen)

            segment_points: List[Tuple[float, float]] = []

            for gi in range(start_idx, end_idx):
                local = self._global_to_local(gi)
                if local is None or local >= len(values):
                    self._draw_overlay_segment_points(p, segment_points)
                    segment_points = []
                    continue

                raw = values[local]
                try:
                    val = float(raw)
                except Exception:
                    self._draw_overlay_segment_points(p, segment_points)
                    segment_points = []
                    continue

                if not math.isfinite(val):
                    self._draw_overlay_segment_points(p, segment_points)
                    segment_points = []
                    continue

                x = self._viewport.x_from_index(plot, gi)
                y = self._y_for_price(plot, val, lo, hi)
                segment_points.append((x, y))

            self._draw_overlay_segment_points(p, segment_points)

        p.restore()

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

    def _draw_left_gap_message(
        self,
        p: QPainter,
        plot: QRectF,
        start_idx: int,
        slots: int,
        text: str,
    ) -> None:
        left_gap_slots = min(max(0, -start_idx), slots)
        if left_gap_slots <= 0:
            return

        cell_w = plot.width() / max(1, slots)
        gap_w = left_gap_slots * cell_w
        msg_rect = QRectF(plot.left(), plot.top(), gap_w, plot.height())

        p.save()
        p.setPen(QPen(QColor(150, 150, 165)))
        p.setFont(QFont("Segoe UI", 10))
        p.drawText(msg_rect, Qt.AlignCenter, text)
        p.restore()

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
        anchor_rel = ((anchor_idx - self._viewport.start) + 0.5) / max(
            1, self._viewport.visible
        )

        dy = event.angleDelta().y()
        if dy > 0:
            self._viewport.zoom_in_at(anchor_idx, anchor_rel)
        elif dy < 0:
            self._viewport.zoom_out_at(anchor_idx, anchor_rel)

        event.accept()