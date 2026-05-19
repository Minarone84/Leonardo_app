from __future__ import annotations

from typing import List, Optional

from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QBrush, QFont, QPainter, QPen, QWheelEvent, QPixmap

from leonardo.common.market_types import Candle
from leonardo.gui.chart.rendering.right_axis_tags import draw_right_axis_value_tag


class VolumeRenderInteractionMixin:
    def _global_to_local(self, global_index: int) -> Optional[int]:
        local = int(global_index) - self._resident_base_index
        if 0 <= local < len(self._volume):
            return local
        return None

    def _value_at_global(self, global_index: int) -> Optional[float]:
        local = self._global_to_local(global_index)
        if local is None:
            return None
        return float(self._volume[local])

    def _candle_at_global(self, global_index: int) -> Optional[Candle]:
        local = self._global_to_local(global_index)
        if local is None:
            return None
        if 0 <= local < len(self._candles):
            return self._candles[local]
        return None

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

    def mouseMoveEvent(self, e) -> None:
        plot = self._plot_rect()
        try:
            x = float(e.position().x())
            y = float(e.position().y())
        except Exception:
            x = float(e.x())
            y = float(e.y())

        if not plot.contains(x, y):
            self._crosshair.set_hover_on_price(False)
            return

        idx = self._viewport.index_from_x(plot, x)
        self._crosshair.set_index(idx)
        self._crosshair.set_hover_on_price(False)

    def wheelEvent(self, event: QWheelEvent) -> None:
        plot = self._plot_rect()

        try:
            mx = float(event.position().x())
            my = float(event.position().y())
        except Exception:
            mx = float(event.x())
            my = float(event.y())

        if not plot.contains(mx, my):
            event.ignore()
            return

        anchor_idx = self._viewport.index_from_x(plot, mx)
        anchor_rel = ((anchor_idx - self._viewport.start) + 0.5) / max(1, self._viewport.visible)

        dy = event.angleDelta().y()
        if dy > 0:
            self._viewport.zoom_in_at(anchor_idx, anchor_rel)
        elif dy < 0:
            self._viewport.zoom_out_at(anchor_idx, anchor_rel)

        event.accept()

    def leaveEvent(self, e) -> None:
        """Clear hover state when the pointer leaves the volume pane.

        VolumeRenderSurface is a self-contained auxiliary renderer. Unlike the
        price and oscillator render surfaces, it does not participate in any
        pane-owned vertical drag lifecycle or shared vertical view-state
        contract, so there is no drag state to end here.
        """
        self._crosshair.set_hover_on_price(False)
        super().leaveEvent(e)



class VolumeRenderPaintMixin:
    def _static_cache_key(self) -> tuple[object, ...]:
        try:
            dpr = float(self.devicePixelRatioF())
        except Exception:
            dpr = 1.0
        try:
            start = int(getattr(self._viewport, "start", 0))
            end = int(getattr(self._viewport, "end", 0))
        except Exception:
            start, end = 0, 0
        return (
            int(getattr(self, "_static_version", 0)),
            int(self.width()),
            int(self.height()),
            float(dpr),
            int(start),
            int(end),
            int(getattr(self, "_resident_base_index", 0)),
        )

    def _ensure_static_pixmap(self) -> None:
        key = self._static_cache_key()
        if getattr(self, "_static_pixmap", None) is not None and getattr(self, "_static_pixmap_key", None) == key:
            return

        if getattr(self, "_static_pixmap", None) is None:
            self._rebuild_static_pixmap(key)
            return

        # Coalesce rebuilds to avoid rebuilding the static volume scene inside
        # paint repeatedly during multi-step updates.
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
        key = self._static_cache_key()
        if getattr(self, "_static_pixmap", None) is not None and getattr(self, "_static_pixmap_key", None) == key:
            return
        self._rebuild_static_pixmap(key)
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

        start, end = self._viewport.start, self._viewport.end
        vis: List[Optional[float]] = [self._value_at_global(gi) for gi in range(start, end)]
        real_vis = [v for v in vis if v is not None]
        if not real_vis:
            try:
                self._static_vmax = None
                self._static_pixmap = pm
                self._static_pixmap_key = key
            except Exception:
                pass
            return

        vmax = max(real_vis)
        try:
            self._static_vmax = float(vmax)
        except Exception:
            self._static_vmax = None

        n = len(vis)
        if n <= 0:
            try:
                self._static_pixmap = pm
                self._static_pixmap_key = key
            except Exception:
                pass
            return

        bar_w = max(2.0, plot.width() / max(1, n))
        body_w = max(1.0, bar_w * 0.8)

        bull_fill = QColor(14, 203, 129)
        bull_line = QColor(38, 226, 160)
        bear_fill = QColor(246, 70, 93)
        bear_line = QColor(255, 110, 128)
        neutral_fill = QColor(80, 120, 220)
        neutral_line = QColor(80, 120, 220)

        p.save()
        p.setClipRect(plot)

        for i, v in enumerate(vis):
            if v is None:
                continue

            global_index = start + i
            candle = self._candle_at_global(global_index)

            if candle is not None:
                if candle.close >= candle.open:
                    fill_color = bull_fill
                    line_color = bull_line
                else:
                    fill_color = bear_fill
                    line_color = bear_line
            else:
                fill_color = neutral_fill
                line_color = neutral_line

            cx = plot.left() + (i + 0.5) * bar_w
            t = v / vmax if vmax > 0 else 0.0
            bar_h = t * plot.height()

            p.setPen(QPen(line_color))
            p.setBrush(QBrush(fill_color))
            p.drawRect(cx - body_w / 2, plot.bottom() - bar_h, body_w, bar_h)

        p.restore()

        if self._volume and vmax > 0:
            v_raw = float(self._volume[-1])
            v_clamped = v_raw
            if v_clamped < 0.0:
                v_clamped = 0.0
            elif v_clamped > vmax:
                v_clamped = vmax

            y_tag = plot.bottom() - (v_clamped / vmax) * plot.height()
            p.setFont(QFont("Consolas", 9))
            draw_right_axis_value_tag(p, axis, y_tag, f"{v_raw:.0f}")

        p.setPen(QPen(QColor(170, 170, 185)))
        p.setFont(QFont("Consolas", 9))
        p.drawText(int(plot.right() + 8), int(plot.top() + 12), "Vol")
        p.drawText(int(plot.right() + 8), int(plot.top() + 26), f"{vmax:0.0f}")

        try:
            self._static_pixmap = pm
            self._static_pixmap_key = key
        except Exception:
            pass

    def paintEvent(self, event) -> None:
        # 1) Paint cached static scene.
        self._ensure_static_pixmap()

        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, False)

        if getattr(self, "_static_pixmap", None) is not None:
            p.drawPixmap(0, 0, self._static_pixmap)

        # 2) Paint dynamic crosshair overlay.
        plot = self._plot_rect()
        start, end = self._viewport.start, self._viewport.end
        vmax = getattr(self, "_static_vmax", None)

        p.save()
        p.setClipRect(plot)

        if self._crosshair.active and self._crosshair.index is not None:
            idx = self._crosshair.index
            if start <= idx < end:
                x = self._viewport.x_from_index(plot, idx)
                p.setPen(QPen(QColor(120, 120, 140)))
                p.drawLine(int(x), int(plot.top()), int(x), int(plot.bottom()))

            if vmax is not None and vmax > 0:
                v_cross = self._value_at_global(idx)
                if v_cross is not None:
                    v = float(v_cross)
                    if v < 0.0:
                        v = 0.0
                    elif v > vmax:
                        v = vmax

                    t = v / vmax
                    y = plot.bottom() - t * plot.height()

                    p.setPen(QPen(QColor(120, 120, 140)))
                    p.drawLine(int(plot.left()), int(y), int(plot.right()), int(y))

        p.restore()
