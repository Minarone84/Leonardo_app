from __future__ import annotations

import math
from typing import Any, List, Mapping, Optional

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QBrush, QPainter, QPainterPath, QPen

from leonardo.gui.chart.model import Series


class OscillatorPolicyPainterMixin:
    def _primary_series(self) -> Optional[Series]:
        if not self._series_list:
            return None
        return self._series_list[0]

    def _line_key_from_series_key(self, series_key: str) -> str:
        text = str(series_key).strip()
        if not text:
            return ""
        return text.rsplit("|", 1)[-1].strip().lower()

    def _series_by_signal_name(self) -> dict[str, Series]:
        by_signal: dict[str, Series] = {}
        for series in self._series_list:
            signal_name = self._line_key_from_series_key(series.key)
            if signal_name and signal_name not in by_signal:
                by_signal[signal_name] = series
        return by_signal

    def _global_to_local(self, global_index: int, values: List[float]) -> Optional[int]:
        local = int(global_index) - self._resident_base_index
        if 0 <= local < len(values):
            return local
        return None

    def _value_at_global_for_values(self, global_index: int, values: List[float]) -> Optional[float]:
        local = self._global_to_local(global_index, values)
        if local is None:
            return None
        try:
            numeric = float(values[local])
        except Exception:
            return None
        if not math.isfinite(numeric):
            return None
        return numeric

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

    def _pen_for_series(self, series: Series) -> QPen:
        color_text = ""
        line_width = 1
        line_style = "solid"

        if getattr(series, "style", None) is not None:
            color_text = str(getattr(series.style, "color", "") or "").strip()
            try:
                line_width = max(1, int(getattr(series.style, "line_width", 1)))
            except Exception:
                line_width = 1
            line_style = str(getattr(series.style, "line_style", "solid") or "solid").strip().lower()

        color = QColor(color_text) if color_text else QColor(170, 170, 185)
        if not color.isValid():
            color = QColor(170, 170, 185)

        pen = QPen(color)
        pen.setWidth(line_width)

        if line_style == "dotted":
            pen.setStyle(Qt.DotLine)
        elif line_style == "dashed":
            pen.setStyle(Qt.DashLine)
        elif line_style == "dash_dot":
            pen.setStyle(Qt.DashDotLine)
        else:
            pen.setStyle(Qt.SolidLine)

        return pen

    def _pen_from_policy_line(
        self,
        *,
        color_text: str,
        line_width: int,
        line_style: str,
    ) -> QPen:
        color = QColor(str(color_text or "").strip()) if str(color_text or "").strip() else QColor(120, 120, 140)
        if not color.isValid():
            color = QColor(120, 120, 140)

        pen = QPen(color)
        pen.setWidth(max(1, int(line_width)))

        normalized_style = str(line_style or "solid").strip().lower()
        if normalized_style == "dotted":
            pen.setStyle(Qt.DotLine)
        elif normalized_style == "dashed":
            pen.setStyle(Qt.DashLine)
        elif normalized_style == "dash_dot":
            pen.setStyle(Qt.DashDotLine)
        else:
            pen.setStyle(Qt.SolidLine)

        return pen

    def _brush_from_policy_fill(self, *, color_text: str) -> QBrush:
        color = QColor(str(color_text or "").strip()) if str(color_text or "").strip() else QColor(96, 165, 250)
        if not color.isValid():
            color = QColor(96, 165, 250)
        return QBrush(color)

    def _threshold_line_color_policy(self) -> Optional[Mapping[str, Any]]:
        policy = self._visual_policy.get("threshold_line_color")
        if isinstance(policy, Mapping):
            return policy
        return None

    def _series_matches_threshold_target(self, series: Series, target_signal: str) -> bool:
        normalized_target = str(target_signal or "").strip().lower()
        if not normalized_target:
            return False
        if normalized_target == "__primary__":
            return series is self._primary_series()
        return self._line_key_from_series_key(series.key) == normalized_target

    def _pen_for_series_value(self, series: Series, value: float) -> QPen:
        threshold_policy = self._threshold_line_color_policy()
        if threshold_policy is None:
            return self._pen_for_series(series)

        target_signal = str(threshold_policy.get("target_signal", "") or "").strip().lower()
        if not self._series_matches_threshold_target(series, target_signal):
            return self._pen_for_series(series)

        try:
            lower_value = float(threshold_policy.get("lower_value"))
            upper_value = float(threshold_policy.get("upper_value"))
        except Exception:
            return self._pen_for_series(series)

        if lower_value != lower_value or upper_value != upper_value or upper_value <= lower_value:
            return self._pen_for_series(series)

        base_pen = self._pen_for_series(series)

        if value <= lower_value:
            color_text = str(threshold_policy.get("oversold_color", "") or "").strip()
        elif value >= upper_value:
            color_text = str(threshold_policy.get("overbought_color", "") or "").strip()
        else:
            color_text = str(threshold_policy.get("neutral_color", "") or "").strip()

        color = QColor(color_text) if color_text else base_pen.color()
        if not color.isValid():
            color = base_pen.color()

        base_pen.setColor(color)
        return base_pen

    def _draw_policy_levels(
        self,
        p: QPainter,
        *,
        plot: QRectF,
        y_to_px,
    ) -> None:
        raw_levels = self._visual_policy.get("levels", []) or []
        if not isinstance(raw_levels, list):
            return

        for level in raw_levels:
            if not isinstance(level, Mapping):
                continue
            if not bool(level.get("visible", True)):
                continue

            try:
                value = float(level.get("value"))
            except Exception:
                continue

            if value != value:
                continue

            pen = self._pen_from_policy_line(
                color_text=str(level.get("color", "") or ""),
                line_width=int(level.get("line_width", 1) or 1),
                line_style=str(level.get("line_style", "dashed") or "dashed"),
            )

            y = y_to_px(value)

            p.save()
            p.setPen(pen)
            p.drawLine(int(plot.left()), int(y), int(plot.right()), int(y))
            p.restore()

    def _draw_policy_fills(
        self,
        p: QPainter,
        *,
        plot: QRectF,
        start: int,
        end: int,
        dx: float,
        y_to_px,
    ) -> None:
        raw_fills = self._visual_policy.get("fills", []) or []
        if not isinstance(raw_fills, list):
            return

        by_signal = self._series_by_signal_name()
        if not by_signal:
            return

        for fill_spec in raw_fills:
            if not isinstance(fill_spec, Mapping):
                continue
            if not bool(fill_spec.get("visible", True)):
                continue

            signal_a = str(fill_spec.get("series_a", "") or "").strip().lower()
            signal_b = str(fill_spec.get("series_b", "") or "").strip().lower()
            if not signal_a or not signal_b:
                continue

            series_a = by_signal.get(signal_a)
            series_b = by_signal.get(signal_b)
            if series_a is None or series_b is None:
                continue

            brush = self._brush_from_policy_fill(
                color_text=str(fill_spec.get("color", "") or "")
            )

            try:
                opacity = float(fill_spec.get("opacity", 0.10))
            except Exception:
                opacity = 0.10
            opacity = max(0.0, min(1.0, opacity))

            upper_points: List[tuple[float, float]] = []
            lower_points: List[tuple[float, float]] = []

            def flush_segment() -> None:
                if len(upper_points) < 2 or len(lower_points) < 2:
                    upper_points.clear()
                    lower_points.clear()
                    return

                path = QPainterPath()
                first_x, first_y = upper_points[0]
                path.moveTo(first_x, first_y)

                for x_pt, y_pt in upper_points[1:]:
                    path.lineTo(x_pt, y_pt)

                for x_pt, y_pt in reversed(lower_points):
                    path.lineTo(x_pt, y_pt)

                path.closeSubpath()

                p.save()
                p.setPen(Qt.NoPen)
                p.setBrush(brush)
                p.setOpacity(opacity)
                p.drawPath(path)
                p.restore()

                upper_points.clear()
                lower_points.clear()

            for i, gi in enumerate(range(start, end)):
                va = self._value_at_global_for_values(gi, series_a.values)
                vb = self._value_at_global_for_values(gi, series_b.values)

                if va is None or vb is None:
                    flush_segment()
                    continue

                x = plot.left() + i * dx
                upper_points.append((x, y_to_px(va)))
                lower_points.append((x, y_to_px(vb)))

            flush_segment()
