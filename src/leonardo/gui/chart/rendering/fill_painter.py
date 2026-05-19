from __future__ import annotations

import math
from typing import List, Optional, Sequence

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QBrush, QPainter, QPainterPath


class FillPainterMixin:
    def _fill_attr(self, fill_desc: object, *names: str, default: object = None) -> object:
        if isinstance(fill_desc, dict):
            for name in names:
                if name in fill_desc:
                    return fill_desc[name]
            return default

        for name in names:
            if hasattr(fill_desc, name):
                return getattr(fill_desc, name)
        return default

    def _resolve_fill_series_key(self, fill_desc: object, side: str) -> str:
        if side == "a":
            raw = self._fill_attr(fill_desc, "signal_a", "series_a", "key_a", "a", default="")
        else:
            raw = self._fill_attr(fill_desc, "signal_b", "series_b", "key_b", "b", default="")
        return str(raw or "").strip()

    def _fill_visible(self, fill_desc: object) -> bool:
        try:
            return bool(self._fill_attr(fill_desc, "visible", default=True))
        except Exception:
            return True

    def _fill_opacity(self, fill_desc: object) -> float:
        try:
            opacity = float(self._fill_attr(fill_desc, "opacity", default=0.15))
        except Exception:
            opacity = 0.15
        return max(0.0, min(1.0, opacity))

    def _fill_color(self, fill_desc: object, fallback: QColor) -> QColor:
        raw = self._fill_attr(fill_desc, "color", default=None)
        return self._coerce_color(raw, fallback)

    def _visible_overlay_series_by_key(self) -> dict[str, object]:
        by_key: dict[str, object] = {}
        for series in self._iter_visible_overlay_series():
            key = self._series_key(series)
            if key:
                by_key[key] = series
        return by_key

    def _finite_series_point(self, values: List[object], gi: int) -> Optional[float]:
        local = self._global_to_local(gi)
        if local is None or local >= len(values):
            return None
        return self._finite_series_point_local(values, local)

    def _finite_series_point_local(self, values: List[object], local: int) -> Optional[float]:
        if local < 0 or local >= len(values):
            return None
        raw = values[local]
        try:
            value = float(raw)
        except Exception:
            return None
        if not math.isfinite(value):
            return None
        return value

    def _draw_fill_between_series(
        self,
        p: QPainter,
        plot: QRectF,
        *,
        series_a: object,
        series_b: object,
        color: QColor,
        opacity: float,
        start_idx: int,
        end_idx: int,
        lo: float,
        hi: float,
        local_indices: Optional[Sequence[Optional[int]]] = None,
        x_positions: Optional[Sequence[float]] = None,
    ) -> None:
        values_a = self._series_values(series_a)
        values_b = self._series_values(series_b)
        if values_a is None or values_b is None:
            return

        path_upper = QPainterPath()
        path_lower_points: list[tuple[float, float]] = []
        segment_open = False

        def flush_segment() -> None:
            nonlocal path_upper, path_lower_points, segment_open
            if not segment_open or len(path_lower_points) < 2:
                path_upper = QPainterPath()
                path_lower_points = []
                segment_open = False
                return

            fill_path = QPainterPath(path_upper)
            for x, y in reversed(path_lower_points):
                fill_path.lineTo(x, y)
            fill_path.closeSubpath()

            p.save()
            p.setPen(Qt.NoPen)
            p.setOpacity(opacity)
            p.setBrush(QBrush(color))
            p.drawPath(fill_path)
            p.restore()

            path_upper = QPainterPath()
            path_lower_points = []
            segment_open = False

        # Fast path: reuse overlay precompute (global->local + x positions) when supplied.
        n = max(0, int(end_idx) - int(start_idx))
        use_precompute = (
            local_indices is not None
            and x_positions is not None
            and len(local_indices) >= n
            and len(x_positions) >= n
        )

        if use_precompute:
            for i in range(n):
                local = local_indices[i]
                if local is None:
                    flush_segment()
                    continue

                val_a = self._finite_series_point_local(values_a, int(local))
                val_b = self._finite_series_point_local(values_b, int(local))
                if val_a is None or val_b is None:
                    flush_segment()
                    continue

                x = float(x_positions[i])
                y_a = self._y_for_price(plot, val_a, lo, hi)
                y_b = self._y_for_price(plot, val_b, lo, hi)

                if not segment_open:
                    path_upper.moveTo(x, y_a)
                    path_lower_points = [(x, y_b)]
                    segment_open = True
                    continue

                path_upper.lineTo(x, y_a)
                path_lower_points.append((x, y_b))

            flush_segment()
            return

        # Fallback: compute mapping per point.
        for gi in range(start_idx, end_idx):
            val_a = self._finite_series_point(values_a, gi)
            val_b = self._finite_series_point(values_b, gi)

            if val_a is None or val_b is None:
                flush_segment()
                continue

            x = self._viewport.x_from_index(plot, gi)
            y_a = self._y_for_price(plot, val_a, lo, hi)
            y_b = self._y_for_price(plot, val_b, lo, hi)

            if not segment_open:
                path_upper.moveTo(x, y_a)
                path_lower_points = [(x, y_b)]
                segment_open = True
                continue

            path_upper.lineTo(x, y_a)
            path_lower_points.append((x, y_b))

        flush_segment()

    def _draw_overlay_fills(
        self,
        p: QPainter,
        plot: QRectF,
        start_idx: int,
        end_idx: int,
        lo: float,
        hi: float,
        *,
        local_indices: Optional[Sequence[Optional[int]]] = None,
        x_positions: Optional[Sequence[float]] = None,
    ) -> None:
        fills = self._overlay_fills()
        if not fills:
            return

        series_by_key = self._visible_overlay_series_by_key()
        if not series_by_key:
            return

        for fill_desc in fills:
            if not self._fill_visible(fill_desc):
                continue

            key_a = self._resolve_fill_series_key(fill_desc, "a")
            key_b = self._resolve_fill_series_key(fill_desc, "b")
            if not key_a or not key_b:
                continue

            series_a = series_by_key.get(key_a)
            series_b = series_by_key.get(key_b)
            if series_a is None or series_b is None:
                continue

            fallback = QColor(59, 130, 246)
            color = self._fill_color(fill_desc, fallback)
            opacity = self._fill_opacity(fill_desc)
            if opacity <= 0.0:
                continue

            self._draw_fill_between_series(
                p,
                plot,
                series_a=series_a,
                series_b=series_b,
                color=color,
                opacity=opacity,
                start_idx=start_idx,
                end_idx=end_idx,
                lo=lo,
                hi=hi,
                local_indices=local_indices,
                x_positions=x_positions,
            )
