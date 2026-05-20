from __future__ import annotations

from typing import List, Mapping, Optional, Tuple

from PySide6.QtCore import QPoint, QRectF, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QWidget

from leonardo.common.market_types import Candle
from leonardo.gui.chart.crosshair import Crosshair
from leonardo.gui.chart.viewport import ChartViewport
from leonardo.gui.chart.rendering.time_axis import DAY_MS, TimeAxisTick, ChartTimeAxisMixin
from leonardo.gui.chart.rendering.right_axis_tags import draw_right_axis_value_tag
from leonardo.gui.chart.rendering.y_axis_interaction import PriceYAxisInteractionMixin
from leonardo.gui.chart.rendering.candle_painter import CandlePainterMixin
from leonardo.gui.chart.rendering.fill_painter import FillPainterMixin
from leonardo.gui.chart.rendering.marker_painter import MarkerPainterMixin
from leonardo.gui.chart.rendering.overlay_painter import OverlayPainterMixin
from leonardo.gui.chart.rendering.surface_painter import ChartSurfacePaintMixin


class ChartRenderSurface(
    PriceYAxisInteractionMixin,
    ChartSurfacePaintMixin,
    CandlePainterMixin,
    OverlayPainterMixin,
    FillPainterMixin,
    MarkerPainterMixin,
    ChartTimeAxisMixin,
    QWidget,
):
    def __init__(
        self,
        viewport: ChartViewport,
        crosshair: Crosshair,
        candles: List[Candle],
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setMouseTracking(True)

        self._viewport = viewport
        self._candles = candles
        self._crosshair = crosshair

        self._resident_base_index = 0

        # Pane/workspace own the full vertical contract for the price pane.
        # This shared mutable mapping carries both the explicit y-range
        # contract and the transient drag lifecycle used during immediate
        # interaction. The renderer must consume and write back through this
        # same mapping instead of maintaining a second durable vertical-state
        # store of its own.
        self._view_state: dict[str, object] = {}
        self._explicit_overlay_series: List[object] = []
        self._explicit_overlay_fills: List[object] = []
        self._explicit_background_regions: List[object] = []

        # Workspace owns viewport-driven contract refresh. This surface repaints
        # when it receives explicit contract/view_state updates from the pane,
        # plus crosshair repaint for interaction feedback.

        self._crosshair.changed.connect(self.update)
        self._crosshair.cleared.connect(self.update)

        self._pad_left = 2
        self._pad_top = 4
        self._pad_right = 56
        self._pad_bottom = 18

        self._grid_h = 8

        self._dragging = False
        self._last_drag_x: int | None = None
        self._last_drag_y: int | None = None

        self._mouse_pt: Optional[QPoint] = None

        # Vertical axis drag lifecycle is owned in pane/workspace view state.
        # The renderer reads and updates those transient keys through the shared
        # mapping instead of holding a second private source of truth.

        self._overlay_palette: Tuple[QColor, ...] = (
            QColor(255, 165, 0),   # orange
            QColor(0, 200, 255),   # cyan
            QColor(186, 104, 200), # purple
            QColor(255, 214, 102), # amber
            QColor(76, 175, 80),   # green
            QColor(239, 83, 80),   # red
        )

        # ------------------------------------------------------------------
        # Static render caching
        #
        # The price surface is expensive to paint (candles + overlays + fills +
        # markers + axes). Crosshair motion should not force a full recompute
        # of that entire scene. We therefore render the "static" scene into a
        # cached pixmap and then paint only the dynamic crosshair overlay on
        # top for mouse-move updates.
        # ------------------------------------------------------------------
        self._static_pixmap: QPixmap | None = None
        self._static_pixmap_key: object | None = None
        self._static_version: int = 0
        self._static_rebuild_scheduled: bool = False

    def apply_contract(
        self,
        *,
        candles: List[Candle],
        resident_base_index: int,
        view_state: Optional[Mapping[str, object]],
        overlay_series_payload: Optional[List[object]],
        overlay_fill_payload: Optional[List[object]],
        overlay_background_regions_payload: Optional[List[object]] = None,
    ) -> None:
        """Apply the full pane-owned render contract in one update.

        PricePane hands the surface one coherent contract here so a historical
        slice refresh or study reapply does not fan out into many intermediate
        renderer updates. The renderer still owns only execution; it simply
        swaps to the new explicit inputs and schedules one repaint.
        """
        self._candles = candles
        self._resident_base_index = max(0, int(resident_base_index))
        if isinstance(view_state, dict):
            self._view_state = view_state
        else:
            self._view_state = dict(view_state or {})
        payload_series = overlay_series_payload or []
        self._explicit_overlay_series = payload_series if isinstance(payload_series, list) else list(payload_series)
        payload_fills = overlay_fill_payload or []
        self._explicit_overlay_fills = payload_fills if isinstance(payload_fills, list) else list(payload_fills)
        payload_background_regions = overlay_background_regions_payload or []
        self._explicit_background_regions = (
            payload_background_regions
            if isinstance(payload_background_regions, list)
            else list(payload_background_regions)
        )
        self._bump_static_version()
        self.update()

    def _global_to_local(self, global_index: int) -> Optional[int]:
        local = int(global_index) - self._resident_base_index
        if 0 <= local < len(self._candles):
            return local
        return None

    def _local_to_global(self, local_index: int) -> int:
        return self._resident_base_index + int(local_index)

    def _candle_at_global(self, global_index: int) -> Optional[Candle]:
        local = self._global_to_local(global_index)
        if local is None:
            return None
        return self._candles[local]

    def _plot_rect(self) -> QRectF:
        return QRectF(
            self._pad_left,
            self._pad_top,
            max(1, self.width() - self._pad_left - self._pad_right),
            max(1, self.height() - self._pad_top - self._pad_bottom),
        )

    def _axis_rect(self, plot: QRectF) -> QRectF:
        return QRectF(plot.right(), plot.top(), float(self._pad_right), plot.height())


    # ------------------------------------------------------------------
    # Background-region drawing
    # ------------------------------------------------------------------

    def _draw_background_regions(self, p: QPainter, plot: QRectF, start: int, end: int) -> None:
        """Draw explicit full-height background x-spans behind the price layer."""
        if not self._explicit_background_regions:
            return

        slots = max(1, int(end) - int(start))
        slot_width = float(plot.width()) / float(slots)

        for region in self._explicit_background_regions:
            if not bool(getattr(region, "visible", True)):
                continue

            try:
                local_start = int(getattr(region, "start_index"))
                local_end = int(getattr(region, "end_index"))
            except Exception:
                continue

            if local_end < local_start:
                continue

            global_start = self._resident_base_index + local_start
            global_end = self._resident_base_index + local_end
            if global_end < start or global_start >= end:
                continue

            color_text = str(getattr(region, "color", "") or "").strip()
            if not color_text:
                continue

            color = QColor(color_text)
            if not color.isValid():
                continue

            try:
                opacity = float(getattr(region, "opacity", 0.08))
            except Exception:
                opacity = 0.08
            opacity = max(0.0, min(1.0, opacity))
            if opacity <= 0.0:
                continue

            color.setAlpha(int(round(opacity * 255)))

            if global_start <= start:
                left = float(plot.left())
            else:
                left = float(self._viewport.x_from_index(plot, global_start)) - (slot_width / 2.0)

            if global_end >= end - 1:
                right = float(plot.right())
            else:
                right = float(self._viewport.x_from_index(plot, global_end)) + (slot_width / 2.0)

            left = max(float(plot.left()), left)
            right = min(float(plot.right()), right)
            if right <= left:
                continue

            p.fillRect(QRectF(left, plot.top(), right - left, plot.height()), color)

    # ------------------------------------------------------------------
    # Static cache helpers
    # ------------------------------------------------------------------

    def _bump_static_version(self) -> None:
        """Mark the static scene as changed.

        This is used for payload changes (candles/overlays/fills/base-index) so
        crosshair-only interaction does not force a full rebuild.
        """
        self._static_version += 1
        self._static_pixmap_key = None

    def _static_cache_key(self) -> tuple[object, ...]:
        y_range = self._resolved_y_range_from_view_state()
        if y_range is None:
            y_key: object = None
        else:
            lo, hi = y_range
            y_key = (float(lo), float(hi))

        # Time-axis display depends on the chosen timezone hint in view_state.
        tz_key: object
        try:
            tz_key = self._display_timezone_cache_key()
        except Exception:
            tz_key = "UTC"

        return (
            int(self.width()),
            int(self.height()),
            int(self._viewport.start),
            int(self._viewport.end),
            int(self._resident_base_index),
            int(self._static_version),
            len(self._candles),
            tz_key,
            y_key,
        )

    def _ensure_static_pixmap(self) -> None:
        key = self._static_cache_key()
        if self._static_pixmap is not None and self._static_pixmap_key == key:
            return

        # First paint: build synchronously so the surface is not blank.
        if self._static_pixmap is None:
            self._rebuild_static_pixmap(key)
            return

        # Subsequent invalidations: coalesce rebuilds so rapid multi-step updates
        # (e.g., multi-study apply across multiple charts) don't rebuild the
        # static scene repeatedly inside paint.
        self._schedule_static_rebuild()

    def _schedule_static_rebuild(self) -> None:
        if self._static_rebuild_scheduled:
            return
        self._static_rebuild_scheduled = True
        QTimer.singleShot(0, self._run_scheduled_static_rebuild)

    def _run_scheduled_static_rebuild(self) -> None:
        self._static_rebuild_scheduled = False
        key = self._static_cache_key()
        if self._static_pixmap is not None and self._static_pixmap_key == key:
            return
        self._rebuild_static_pixmap(key)
        self.update()

    def _rebuild_static_pixmap(self, key: object) -> None:
        w = max(1, int(self.width()))
        h = max(1, int(self.height()))

        # HiDPI-friendly pixmap sizing.
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

        start, end = self._viewport.start, self._viewport.end
        slots = max(1, end - start)

        time_ticks = self._build_time_axis_ticks(plot, start, slots)

        p.save()
        p.setClipRect(plot)
        self._draw_background_regions(p, plot, start, end)
        p.restore()

        self._draw_grid(p, plot, time_ticks)

        if not self._candles:
            self._draw_center_text(p, plot, "No data")
            p.end()
            self._static_pixmap = pm
            self._static_pixmap_key = key
            return

        vis: List[Optional[Candle]] = []
        for gi in range(start, end):
            vis.append(self._candle_at_global(gi))

        resolved_range = self._resolved_y_range_from_view_state()
        if resolved_range is None:
            self._draw_center_text(p, plot, "Missing y-range contract")
            p.end()
            self._static_pixmap = pm
            self._static_pixmap_key = key
            return

        lo, hi = resolved_range
        if hi <= lo:
            self._draw_center_text(p, plot, "Bad scale")
            p.end()
            self._static_pixmap = pm
            self._static_pixmap_key = key
            return

        self._draw_price_axis(p, plot, lo, hi)

        p.save()
        p.setClipRect(plot)

        self._draw_candles(p, plot, start, vis, lo, hi)
        self._draw_overlays(p, plot, start, end, lo, hi)

        p.restore()

        if start < 0:
            self._draw_left_gap_message(p, plot, start, slots, "No older data")

        self._draw_time_axis(p, plot, time_ticks)

        # Right-axis tag: last price.
        last = self._candles[-1]
        y_price = self._y_for_price(plot, last.close, lo, hi)
        p.setFont(QFont("Consolas", 9))
        draw_right_axis_value_tag(p, axis, y_price, f"{last.close:.2f}")

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

        if self._static_pixmap is not None:
            p.drawPixmap(0, 0, self._static_pixmap)

        # 2) Paint dynamic crosshair overlay.
        plot = self._plot_rect()
        start, end = self._viewport.start, self._viewport.end
        idx2 = self._crosshair.index

        p.save()
        p.setClipRect(plot)

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

        if idx2 is not None and start <= idx2 < end:
            self._draw_crosshair_time_tag(p, plot, idx2)

        p.end()

    def resizeEvent(self, event) -> None:
        # Drop cached pixmap so a resize does not stretch stale pixels.
        self._static_pixmap = None
        self._static_pixmap_key = None
        super().resizeEvent(event)
