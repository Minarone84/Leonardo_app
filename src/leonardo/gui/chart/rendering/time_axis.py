from __future__ import annotations

from bisect import bisect_left
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone, tzinfo
from typing import List, Optional, Tuple
from zoneinfo import ZoneInfo

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPen

DAY_MS = 24 * 60 * 60 * 1000


@dataclass(frozen=True)
class TimeAxisTick:
    gi: int
    ts_ms: int
    x: float
    label: str
    priority: int  # 0=regular, 1=day, 2=month, 3=year


class ChartTimeAxisMixin:
    def _timezone_from_value(self, raw: object) -> Optional[tzinfo]:
        """Resolve one explicit display-timezone value when possible.

        The renderer must not hardcode a market/session timezone. It may only
        consume an explicit downstream display-timezone hint when one is
        provided through pane/workspace-owned state, otherwise it falls back to
        UTC as the neutral canonical display basis.
        """
        if raw is None:
            return None

        if isinstance(raw, tzinfo):
            return raw

        text = str(raw).strip()
        if not text:
            return None

        if text.upper() in {"UTC", "Z"}:
            return timezone.utc

        try:
            return ZoneInfo(text)
        except Exception:
            return None

    def _resolved_display_timezone(self) -> tzinfo:
        """Return the explicit downstream display timezone or UTC fallback."""
        for key in ("display_timezone", "timezone", "timezone_name", "time_zone", "tz"):
            resolved = self._timezone_from_value(self._view_state.get(key))
            if resolved is not None:
                return resolved
        return timezone.utc

    def _display_timezone_cache_key(self) -> str:
        tz = self._resolved_display_timezone()
        key = getattr(tz, "key", None)
        if isinstance(key, str) and key:
            return key
        return str(tz)

    def _time_axis_font_metrics(self) -> QFontMetricsF:
        cached = getattr(self, "_time_axis_font_metrics_cache", None)
        if cached is not None:
            return cached
        font = QFont("Consolas", 8)
        metrics = QFontMetricsF(font)
        self._time_axis_font_metrics_cache = metrics
        return metrics

    def _infer_tf_ms(self) -> Optional[int]:
        """Infer timeframe in ms from the last two real candles."""
        if len(self._candles) < 2:
            return None

        a = self._candles[-2].ts_ms
        b = self._candles[-1].ts_ms
        dt = int(b - a)

        if dt <= 0:
            return None

        return dt

    def _slot_ts_ms(self, gi: int) -> Optional[int]:
        """Timestamp for a global slot index gi.

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
        return dt_utc.astimezone(self._resolved_display_timezone())

    def _fmt_crosshair_time(self, ts_ms: int) -> str:
        dt_local = datetime.fromtimestamp(ts_ms / 1000.0, tz=timezone.utc).astimezone(
            self._resolved_display_timezone()
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
            epoch_day = datetime(1970, 1, 1, tzinfo=self._resolved_display_timezone())
            days_since_epoch = (midnight.date() - epoch_day.date()).days
            floored_days = (days_since_epoch // day_step) * day_step
            return epoch_day + timedelta(days=floored_days)

        month_step = max(1, interval_ms // (28 * DAY_MS))
        month_index = dt_local.year * 12 + (dt_local.month - 1)
        floored_month_index = (month_index // month_step) * month_step
        year = floored_month_index // 12
        month = (floored_month_index % 12) + 1
        return datetime(year, month, 1, tzinfo=self._resolved_display_timezone())

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
        *,
        ts_values: Optional[List[int]] = None,
    ) -> Optional[int]:
        if not visible_points:
            return None

        resolved_ts_values = ts_values if ts_values is not None else [ts for _, ts in visible_points]
        pos = bisect_left(resolved_ts_values, ts_ms)

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

        timezone_key = self._display_timezone_cache_key()
        rounded_w = int(round(plot.width()))

        # Fast-path cache check when the window edges are real candles.
        start_ts_candidate = self._slot_ts_ms(start_idx)
        end_ts_candidate = self._slot_ts_ms(start_idx + slots - 1)
        if start_ts_candidate is not None and end_ts_candidate is not None:
            cache_key = (
                rounded_w,
                start_idx,
                slots,
                base_tf_ms,
                int(start_ts_candidate),
                int(end_ts_candidate),
                timezone_key,
            )
            cached_key = getattr(self, "_time_axis_tick_cache_key", None)
            cached_ticks = getattr(self, "_time_axis_tick_cache", None)
            if cached_key == cache_key and isinstance(cached_ticks, list):
                return cached_ticks

        # Fallback: build visible point list (handles padding/partial coverage).
        visible_points = self._visible_slot_time_points(start_idx, slots)
        if len(visible_points) < 2:
            return []

        start_ts = visible_points[0][1]
        end_ts = visible_points[-1][1]
        visible_span_ms = max(base_tf_ms, end_ts - start_ts)

        cache_key = (
            rounded_w,
            start_idx,
            slots,
            base_tf_ms,
            int(start_ts),
            int(end_ts),
            timezone_key,
        )

        cached_key = getattr(self, "_time_axis_tick_cache_key", None)
        cached_ticks = getattr(self, "_time_axis_tick_cache", None)
        if cached_key == cache_key and isinstance(cached_ticks, list):
            return cached_ticks

        major_interval_ms = self._choose_major_interval_ms(
            base_tf_ms=base_tf_ms,
            visible_span_ms=visible_span_ms,
            plot_width=plot.width(),
        )

        display_timezone = self._resolved_display_timezone()
        first_dt = datetime.fromtimestamp(start_ts / 1000.0, tz=timezone.utc).astimezone(
            display_timezone
        )
        tick_dt = self._floor_local_time_to_interval(first_dt, major_interval_ms)

        if int(tick_dt.timestamp() * 1000) < start_ts:
            while int(tick_dt.timestamp() * 1000) < start_ts:
                tick_dt += timedelta(milliseconds=major_interval_ms)
            tick_dt -= timedelta(milliseconds=major_interval_ms)

        ticks: List[TimeAxisTick] = []
        prev_tick_dt: Optional[datetime] = None
        seen_gi: set[int] = set()
        visible_ts_values = [ts for _, ts in visible_points]

        last_limit_ts = end_ts + major_interval_ms

        while int(tick_dt.timestamp() * 1000) <= last_limit_ts:
            tick_ts = int(tick_dt.timestamp() * 1000)
            gi = self._nearest_visible_gi_for_ts(
                tick_ts,
                visible_points,
                ts_values=visible_ts_values,
            )

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

        fm = self._time_axis_font_metrics()

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

        self._time_axis_tick_cache_key = cache_key
        self._time_axis_tick_cache = filtered
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
        fm = self._time_axis_font_metrics()
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

        fm = self._time_axis_font_metrics()
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
