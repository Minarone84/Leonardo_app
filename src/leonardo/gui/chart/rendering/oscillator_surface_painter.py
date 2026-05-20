from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QPixmap, QBrush

from leonardo.gui.chart.model import Series


class OscillatorSurfacePaintMixin:
    def _series_render_mode(self, series: Series) -> str:
        style = getattr(series, "style", None)
        try:
            return str(getattr(style, "render_mode", "line") or "line").strip().lower()
        except Exception:
            return "line"

    def _candle_at_global(self, global_index: int):
        local = int(global_index) - int(getattr(self, "_resident_base_index", 0))
        candles = getattr(self, "_candles", []) or []
        try:
            if 0 <= local < len(candles):
                return candles[local]
        except Exception:
            return None
        return None

    def _volume_histogram_colors_for_global(self, global_index: int) -> tuple[QColor, QColor]:
        candle = self._candle_at_global(global_index)
        if candle is None:
            return QColor(80, 120, 220), QColor(80, 120, 220)

        try:
            is_up = float(candle.close) >= float(candle.open)
        except Exception:
            is_up = True

        if is_up:
            return QColor(14, 203, 129), QColor(38, 226, 160)
        return QColor(246, 70, 93), QColor(255, 110, 128)

    def _draw_histogram_series(
        self,
        p: QPainter,
        *,
        plot: QRectF,
        series: Series,
        values: list[float],
        start: int,
        end: int,
        x_positions: list[float],
        dx: float,
        y_to_px,
    ) -> None:
        baseline_y = y_to_px(0.0)
        bar_w = max(1.0, min(dx * 0.8, dx - 1.0 if dx > 2.0 else dx))

        for i, global_index in enumerate(range(start, end)):
            v = self._value_at_global_for_values(global_index, values)
            if v is None:
                continue

            x = x_positions[i]
            y = y_to_px(v)
            top = min(y, baseline_y)
            height = max(1.0, abs(baseline_y - y))
            fill_color, line_color = self._volume_histogram_colors_for_global(global_index)

            rect = QRectF(x - bar_w / 2.0, top, bar_w, height)
            p.setPen(QPen(line_color))
            p.setBrush(QBrush(fill_color))
            p.drawRect(rect)

    # ------------------------------------------------------------------
    # Static cache helpers
    # ------------------------------------------------------------------

    def _static_cache_key(self) -> tuple[object, ...]:
        # Refresh renderer-local mirrors from pane-owned state (y_offset).
        try:
            self._sync_view_state_from_owner()
        except Exception:
            pass

        y_range = None
        try:
            y_range = self._resolved_y_range_from_view_state()
        except Exception:
            y_range = None

        if y_range is None:
            y_key: object = None
        else:
            lo, hi = y_range
            y_key = (float(lo), float(hi))

        try:
            y_offset = float(getattr(self, "_y_offset", 0.0))
        except Exception:
            y_offset = 0.0

        return (
            int(self.width()),
            int(self.height()),
            int(getattr(self._viewport, "start", 0)),
            int(getattr(self._viewport, "end", 0)),
            int(getattr(self, "_resident_base_index", 0)),
            int(getattr(self, "_static_version", 0)),
            y_key,
            y_offset,
            len(getattr(self, "_candles", []) or []),
            int(id(getattr(self, "_candles", None))),
            len(getattr(self, "_series_list", []) or []),
        )

    def _ensure_static_pixmap(self) -> None:
        key = self._static_cache_key()
        if getattr(self, "_static_pixmap", None) is not None and getattr(self, "_static_pixmap_key", None) == key:
            return

        # First paint: build synchronously so the surface is not blank.
        if getattr(self, "_static_pixmap", None) is None:
            self._rebuild_static_pixmap(key)
            return

        # Subsequent invalidations: coalesce rebuilds so rapid multi-step updates
        # don't rebuild the static scene repeatedly inside paint.
        self._schedule_static_rebuild()

    def _schedule_static_rebuild(self) -> None:
        if bool(getattr(self, "_static_rebuild_scheduled", False)):
            return
        try:
            setattr(self, "_static_rebuild_scheduled", True)
        except Exception:
            return
        QTimer.singleShot(0, self._run_scheduled_static_rebuild)

    def _run_scheduled_static_rebuild(self) -> None:
        try:
            setattr(self, "_static_rebuild_scheduled", False)
        except Exception:
            pass
        key2 = self._static_cache_key()
        if getattr(self, "_static_pixmap", None) is not None and getattr(self, "_static_pixmap_key", None) == key2:
            return
        self._rebuild_static_pixmap(key2)
        try:
            self.update()
        except Exception:
            pass

    def _rebuild_static_pixmap(self, key: object) -> None:
        w = max(1, int(self.width()))
        h = max(1, int(self.height()))

        try:
            dpr = float(self.devicePixelRatioF())
        except Exception:
            dpr = 1.0

        pm = QPixmap(max(1, int(w * dpr)), max(1, int(h * dpr)))
        try:
            pm.setDevicePixelRatio(dpr)
        except Exception:
            pass

        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing, False)

        p.fillRect(0, 0, w, h, QColor(12, 12, 14))

        plot = self._plot_rect()
        axis = self._axis_rect(plot)

        p.setPen(QPen(QColor(70, 70, 82)))
        p.drawRect(plot)

        # Refresh renderer-local mirrors from pane-owned state before using the
        # current oscillator render contract.
        self._sync_view_state_from_owner()

        start, end = self._viewport.start, self._viewport.end
        n = max(0, int(end) - int(start))
        if n <= 0:
            p.end()
            self._static_pixmap = pm
            self._static_pixmap_key = key
            return

        resolved_range = self._resolved_y_range_from_view_state()
        if resolved_range is None:
            p.setPen(QPen(QColor(220, 220, 230)))
            p.setFont(QFont("Segoe UI", 11))
            p.drawText(plot, Qt.AlignCenter, "Missing y-range contract")
            p.end()
            self._static_pixmap = pm
            self._static_pixmap_key = key
            return

        ymin, ymax = resolved_range

        dx = plot.width() / max(1, (n - 1))
        pad = 0.1

        def y_to_px(v: float) -> float:
            t = (v - ymin) / (ymax - ymin)
            t = pad + t * (1.0 - 2.0 * pad)
            y = plot.bottom() - t * plot.height()
            return y + self._y_offset

        def series_is_visible(series: Series) -> bool:
            style = getattr(series, "style", None)
            if style is None:
                return True
            try:
                return bool(getattr(style, "visible", True))
            except Exception:
                return True

        # Early exit when nothing finite is visible.
        has_visible_data = False
        for series in self._series_list:
            if not series_is_visible(series):
                continue
            values = getattr(series, "values", None)
            if not isinstance(values, list) or not values:
                continue
            for global_index in range(start, end):
                if self._value_at_global_for_values(global_index, values) is not None:
                    has_visible_data = True
                    break
            if has_visible_data:
                break

        if not has_visible_data:
            p.end()
            self._static_pixmap = pm
            self._static_pixmap_key = key
            return

        # Precompute x coordinates once.
        x_positions = [plot.left() + i * dx for i in range(n)]

        p.save()
        p.setClipRect(plot)

        self._draw_policy_levels(
            p,
            plot=plot,
            y_to_px=y_to_px,
        )

        self._draw_policy_fills(
            p,
            plot=plot,
            start=start,
            end=end,
            dx=dx,
            y_to_px=y_to_px,
        )

        for series in self._series_list:
            if not series_is_visible(series):
                continue

            values = getattr(series, "values", None)
            if not isinstance(values, list) or not values:
                continue

            if self._series_render_mode(series) == "histogram":
                self._draw_histogram_series(
                    p,
                    plot=plot,
                    series=series,
                    values=values,
                    start=start,
                    end=end,
                    x_positions=x_positions,
                    dx=dx,
                    y_to_px=y_to_px,
                )
                continue

            prev_x: Optional[float] = None
            prev_y: Optional[float] = None
            prev_value: Optional[float] = None

            current_pen: Optional[QPen] = None
            path = QPainterPath()
            path_points = 0

            valid_points = 0
            last_point: Optional[tuple[float, float, float]] = None

            for i, global_index in enumerate(range(start, end)):
                v = self._value_at_global_for_values(global_index, values)
                if v is None:
                    if current_pen is not None and path_points >= 2:
                        p.setPen(current_pen)
                        p.drawPath(path)
                    current_pen = None
                    path = QPainterPath()
                    path_points = 0
                    prev_x = None
                    prev_y = None
                    prev_value = None
                    continue

                x = x_positions[i]
                y = y_to_px(v)
                valid_points += 1
                last_point = (x, y, v)

                pen = self._pen_for_series_value(series, v)

                if prev_x is None or prev_y is None or prev_value is None:
                    # First point in a new contiguous segment.
                    current_pen = pen
                    path = QPainterPath()
                    path.moveTo(x, y)
                    path_points = 1
                    prev_x, prev_y, prev_value = x, y, v
                    continue

                # Segment from previous point to current point is colored by the
                # pen resolved for the current value `v`.
                if current_pen is None or pen != current_pen:
                    if current_pen is not None and path_points >= 2:
                        p.setPen(current_pen)
                        p.drawPath(path)

                    current_pen = pen
                    path = QPainterPath()
                    path.moveTo(prev_x, prev_y)
                    path.lineTo(x, y)
                    path_points = 2
                else:
                    path.lineTo(x, y)
                    path_points += 1

                prev_x, prev_y, prev_value = x, y, v

            if current_pen is not None and path_points >= 2:
                p.setPen(current_pen)
                p.drawPath(path)

            if valid_points == 1 and last_point is not None:
                point_x, point_y, point_value = last_point
                p.setPen(self._pen_for_series_value(series, point_value))
                p.drawEllipse(QRectF(point_x - 2.0, point_y - 2.0, 4.0, 4.0))

        p.restore()

        # Axis labels (static).
        p.setPen(QPen(QColor(170, 170, 185)))
        p.setFont(QFont("Consolas", 9))

        ymax_text = f"{ymax:.2f}"
        ymid = (ymin + ymax) / 2.0
        ymid_text = f"{ymid:.2f}"
        ymin_text = f"{ymin:.2f}"

        p.drawText(int(plot.right() + 8), int(y_to_px(ymax)), ymax_text)
        p.drawText(int(plot.right() + 8), int(y_to_px(ymid)), ymid_text)
        p.drawText(int(plot.right() + 8), int(y_to_px(ymin)), ymin_text)

        p.end()

        self._static_pixmap = pm
        self._static_pixmap_key = key

    # ------------------------------------------------------------------
    # Paint
    # ------------------------------------------------------------------

    def paintEvent(self, event) -> None:
        # 1) Paint cached static scene.
        self._ensure_static_pixmap()

        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, False)

        pm = getattr(self, "_static_pixmap", None)
        if pm is not None:
            p.drawPixmap(0, 0, pm)

        # 2) Paint dynamic crosshair overlay.
        plot = self._plot_rect()
        start, end = self._viewport.start, self._viewport.end
        idx = self._crosshair.index

        resolved_range = self._resolved_y_range_from_view_state()
        if resolved_range is None:
            p.end()
            return

        ymin, ymax = resolved_range
        pad = 0.1

        def y_to_px(v: float) -> float:
            t = (v - ymin) / (ymax - ymin)
            t = pad + t * (1.0 - 2.0 * pad)
            y = plot.bottom() - t * plot.height()
            return y + self._y_offset

        p.save()
        p.setClipRect(plot)

        if self._crosshair.active and idx is not None:
            if start <= idx < end:
                x = self._viewport.x_from_index(plot, idx)
                p.setPen(QPen(QColor(120, 120, 140)))
                p.drawLine(int(x), int(plot.top()), int(x), int(plot.bottom()))

            primary = self._primary_series()
            if primary is not None:
                v_cross = self._value_at_global_for_values(idx, primary.values)
                if v_cross is not None:
                    y = y_to_px(v_cross)
                    p.setPen(QPen(QColor(120, 120, 140)))
                    p.drawLine(int(plot.left()), int(y), int(plot.right()), int(y))

        p.restore()
        p.end()

    def resizeEvent(self, event) -> None:
        # Drop cached pixmap so a resize does not stretch stale pixels.
        try:
            self._static_pixmap = None
            self._static_pixmap_key = None
        except Exception:
            pass
        super().resizeEvent(event)
