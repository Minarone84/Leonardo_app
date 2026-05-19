from __future__ import annotations

from typing import List, Optional

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QBrush, QFont, QPainter, QPen

from leonardo.common.market_types import Candle
from leonardo.gui.chart.rendering.time_axis import TimeAxisTick


class CandlePainterMixin:
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
