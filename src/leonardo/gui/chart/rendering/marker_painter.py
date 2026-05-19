from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QBrush, QFont, QPainter, QPainterPath, QPen


class MarkerPainterMixin:
    def _marker_shape_for_series(self, series: object) -> str:
        style_obj = self._series_style(series)
        if style_obj is None:
            return ""
        return str(getattr(style_obj, "marker_shape", "") or "").strip().lower()

    def _marker_size_for_series(self, series: object) -> int:
        style_obj = self._series_style(series)
        if style_obj is None:
            return 0
        try:
            size = int(getattr(style_obj, "marker_size", 0) or 0)
        except Exception:
            size = 0
        return max(6, min(32, size)) if size > 0 else 0

    def _marker_text_for_series(self, series: object) -> str:
        style_obj = self._series_style(series)
        if style_obj is None:
            return ""
        return str(getattr(style_obj, "marker_text", "") or "")

    def _marker_text_color_for_series(self, series: object) -> QColor:
        style_obj = self._series_style(series)
        fallback = QColor(0, 0, 0)
        if style_obj is None:
            return fallback
        return self._coerce_color(getattr(style_obj, "marker_text_color", None), fallback)

    def _marker_offset_px_for_series(self, series: object) -> int:
        style_obj = self._series_style(series)
        if style_obj is None:
            return 0
        try:
            return int(getattr(style_obj, "marker_offset_px", 0) or 0)
        except Exception:
            return 0

    def _draw_overlay_marker(
        self,
        p: QPainter,
        *,
        x: float,
        y: float,
        color: QColor,
        shape: str,
        size: int,
        text: str,
        text_color: QColor,
        y_offset_px: int,
    ) -> None:
        resolved_shape = str(shape or "").strip().lower()
        resolved_size = max(6, min(32, int(size)))
        if resolved_shape not in {"triangle_up", "triangle_down"}:
            return

        half = resolved_size / 2.0
        center_y = float(y) + float(y_offset_px)

        path = QPainterPath()
        if resolved_shape == "triangle_up":
            path.moveTo(x, center_y - half)
            path.lineTo(x - half, center_y + half)
            path.lineTo(x + half, center_y + half)
        else:
            path.moveTo(x, center_y + half)
            path.lineTo(x - half, center_y - half)
            path.lineTo(x + half, center_y - half)
        path.closeSubpath()

        p.save()
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(color))
        p.drawPath(path)

        label = str(text or "").strip()
        if label:
            font = QFont(p.font())
            font.setPointSize(max(6, min(10, resolved_size - 4)))
            font.setBold(True)
            p.setFont(font)
            p.setPen(QPen(text_color))
            rect = QRectF(x - half, center_y - half, resolved_size, resolved_size)
            p.drawText(rect, Qt.AlignCenter, label)
        p.restore()
