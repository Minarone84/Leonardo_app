from __future__ import annotations

from collections.abc import Sequence
import math
from typing import Iterable, List, Optional, Tuple

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen


class OverlayPainterMixin:
    def _overlay_series(self) -> List[object]:
        """Return the explicit pane-owned overlay render payload.

        Final point-C contract: overlay membership is resolved upstream and
        passed into the renderer explicitly. The renderer does not inspect
        parent widgets or models to discover what it should draw.

        NOTE: this returns the renderer-owned payload list directly. Callers
        must treat it as read-only.
        """
        return self._explicit_overlay_series

    def _overlay_fills(self) -> List[object]:
        """Return the explicit pane-owned overlay fill payload.

        Final point-C contract: fill descriptors are visualization payloads
        supplied by the pane/workspace layer. The renderer consumes only that
        explicit payload.

        NOTE: this returns the renderer-owned payload list directly. Callers
        must treat it as read-only.
        """
        return self._explicit_overlay_fills

    def _series_key(self, series: object) -> str:
        return str(getattr(series, "key", "") or "").strip()

    def _series_title(self, series: object) -> str:
        return str(getattr(series, "title", "") or "").strip()

    def _series_values(self, series: object) -> Optional[Sequence[object]]:
        values = getattr(series, "values", None)
        try:
            len(values)  # Check if it's a sequence-like object
        except Exception:
            return None
        return values

    def _series_style(self, series: object) -> object | None:
        return getattr(series, "style", None)

    def _series_visible(self, series: object) -> bool:
        style_obj = self._series_style(series)
        if style_obj is None:
            return True

        try:
            return bool(getattr(style_obj, "visible", True))
        except Exception:
            return True

    def _iter_visible_overlay_series(self) -> List[object]:
        return [series for series in self._overlay_series() if self._series_visible(series)]

    def _iter_finite_overlay_values_in_view(self, start: int, end: int) -> Iterable[float]:
        for series in self._iter_visible_overlay_series():
            values = self._series_values(series)
            if values is None:
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
        style_obj = self._series_style(series)
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
        style_obj = self._series_style(series)
        if style_obj is None:
            return 2

        try:
            width = int(getattr(style_obj, "line_width", 2))
        except Exception:
            width = 2

        return max(1, min(8, width))

    def _pen_color_for_series(self, series: object, series_index: int) -> QColor:
        fallback = self._overlay_palette[series_index % len(self._overlay_palette)]
        style_obj = self._series_style(series)
        if style_obj is None:
            return fallback

        return self._coerce_color(getattr(style_obj, "color", None), fallback)

    def _series_render_mode(self, series: object) -> str:
        style_obj = self._series_style(series)
        if style_obj is None:
            return "line"
        return str(getattr(style_obj, "render_mode", "line") or "line").strip().lower()

    def _draw_overlays(
        self,
        p: QPainter,
        plot: QRectF,
        start_idx: int,
        end_idx: int,
        lo: float,
        hi: float,
    ) -> None:
        overlays = self._iter_visible_overlay_series()
        if not overlays:
            return

        n = max(0, int(end_idx) - int(start_idx))
        if n <= 0 or plot.width() <= 1.0:
            return

        # Precompute global->local mapping and x positions once per paint.
        # This avoids repeating viewport/index mapping per series.
        local_indices: List[Optional[int]] = [
            self._global_to_local(int(start_idx) + i) for i in range(n)
        ]

        # Match ChartViewport.x_from_index() mapping: center-of-cell positions.
        cell_w = plot.width() / max(1, n)
        x_positions = [plot.left() + (i + 0.5) * cell_w for i in range(n)]

        # Density-aware antialiasing.
        dx = abs(x_positions[1] - x_positions[0]) if n >= 2 else float(plot.width())
        dense = dx < 1.25

        p.save()
        p.setRenderHint(QPainter.Antialiasing, not dense)

        self._draw_overlay_fills(
            p,
            plot,
            start_idx,
            end_idx,
            lo,
            hi,
            local_indices=local_indices,
            x_positions=x_positions,
        )

        for series_index, series in enumerate(overlays):
            values = self._series_values(series)
            if values is None or not values:
                continue

            render_mode = self._series_render_mode(series)
            base_color = self._pen_color_for_series(series, series_index)

            if render_mode == "marker":
                marker_shape = self._marker_shape_for_series(series)
                marker_size = self._marker_size_for_series(series)
                marker_text = self._marker_text_for_series(series)
                marker_text_color = self._marker_text_color_for_series(series)
                marker_offset_px = self._marker_offset_px_for_series(series)
                if not marker_shape or marker_size <= 0:
                    continue

                for i in range(n):
                    local = local_indices[i]
                    if local is None or local >= len(values):
                        continue

                    raw = values[local]
                    try:
                        val = float(raw)
                    except Exception:
                        continue

                    if not math.isfinite(val):
                        continue

                    x = x_positions[i]
                    y = self._y_for_price(plot, val, lo, hi)
                    self._draw_overlay_marker(
                        p,
                        x=x,
                        y=y,
                        color=base_color,
                        shape=marker_shape,
                        size=marker_size,
                        text=marker_text,
                        text_color=marker_text_color,
                        y_offset_px=marker_offset_px,
                    )
                continue

            base_pen = QPen(base_color)
            base_pen.setWidth(self._pen_width_for_series(series))
            base_pen.setStyle(self._qt_pen_style_for_series(series))
            p.setPen(base_pen)

            # When the chart is dense, drawing full-resolution paths for every
            # overlay is expensive. Use a pixel-bucket min/max strategy so the
            # cost scales with screen pixels rather than series length.
            if dense and dx < 1.0:
                last_px: Optional[int] = None
                min_y: Optional[float] = None
                max_y: Optional[float] = None

                def flush_bucket() -> None:
                    nonlocal last_px, min_y, max_y
                    if last_px is None or min_y is None or max_y is None:
                        last_px = None
                        min_y = None
                        max_y = None
                        return
                    p.drawLine(int(last_px), int(min_y), int(last_px), int(max_y))
                    last_px = None
                    min_y = None
                    max_y = None

                for i in range(n):
                    local = local_indices[i]
                    if local is None or local >= len(values):
                        flush_bucket()
                        continue

                    raw = values[local]
                    try:
                        val = float(raw)
                    except Exception:
                        flush_bucket()
                        continue

                    if not math.isfinite(val):
                        flush_bucket()
                        continue

                    x = x_positions[i]
                    y = self._y_for_price(plot, val, lo, hi)
                    px = int(x)

                    if last_px is None:
                        last_px = px
                        min_y = y
                        max_y = y
                        continue

                    if px != last_px:
                        flush_bucket()
                        last_px = px
                        min_y = y
                        max_y = y
                        continue

                    if min_y is None or y < min_y:
                        min_y = y
                    if max_y is None or y > max_y:
                        max_y = y

                flush_bucket()
                continue

            # Build and draw one path per contiguous finite segment.
            path = QPainterPath()
            path_points = 0

            for i in range(n):
                local = local_indices[i]
                if local is None or local >= len(values):
                    if path_points >= 2:
                        p.drawPath(path)
                    path = QPainterPath()
                    path_points = 0
                    continue

                raw = values[local]
                try:
                    val = float(raw)
                except Exception:
                    if path_points >= 2:
                        p.drawPath(path)
                    path = QPainterPath()
                    path_points = 0
                    continue

                if not math.isfinite(val):
                    if path_points >= 2:
                        p.drawPath(path)
                    path = QPainterPath()
                    path_points = 0
                    continue

                x = x_positions[i]
                y = self._y_for_price(plot, val, lo, hi)

                if path_points == 0:
                    path.moveTo(x, y)
                    path_points = 1
                else:
                    path.lineTo(x, y)
                    path_points += 1

            if path_points >= 2:
                p.drawPath(path)

        p.restore()