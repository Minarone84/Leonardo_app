from __future__ import annotations

from typing import List, Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen

from leonardo.common.market_types import Candle
from leonardo.gui.chart.rendering.right_axis_tags import draw_right_axis_value_tag


class ChartSurfacePaintMixin:
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

        resolved_range = self._resolved_y_range_from_view_state()
        if resolved_range is None:
            self._draw_center_text(p, plot, "Missing y-range contract")
            return

        lo, hi = resolved_range
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
