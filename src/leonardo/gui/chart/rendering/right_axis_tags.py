from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFontMetricsF, QPainter


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
