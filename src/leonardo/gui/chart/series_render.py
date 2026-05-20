from __future__ import annotations

from typing import Any, List, Mapping, Optional

from PySide6.QtWidgets import QWidget

from leonardo.common.market_types import Candle
from leonardo.gui.chart.viewport import ChartViewport
from leonardo.gui.chart.crosshair import Crosshair
from leonardo.gui.chart.model import Series
from leonardo.gui.chart.rendering.right_axis_tags import draw_right_axis_value_tag
from leonardo.gui.chart.rendering.volume_surface import (
    VolumeRenderInteractionMixin,
    VolumeRenderPaintMixin,
)
from leonardo.gui.chart.rendering.y_axis_interaction import OscillatorYAxisInteractionMixin
from leonardo.gui.chart.rendering.oscillator_policy_painter import OscillatorPolicyPainterMixin
from leonardo.gui.chart.rendering.oscillator_surface_painter import OscillatorSurfacePaintMixin


class VolumeRenderSurface(
    VolumeRenderPaintMixin,
    VolumeRenderInteractionMixin,
    QWidget,
):
    def __init__(
        self,
        viewport: ChartViewport,
        crosshair: Crosshair,
        candles: List[Candle],
        volume: List[float],
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._viewport = viewport
        self._candles = candles
        self._volume = volume
        self._crosshair = crosshair

        self._resident_base_index = 0

        # ------------------------------------------------------------------
        # Static cache
        #
        # Crosshair movement should not force a full volume-bar repaint.
        # Cache the static scene and paint only the dynamic crosshair overlay
        # on top for mouse-move updates.
        # ------------------------------------------------------------------
        self._static_pixmap = None
        self._static_pixmap_key = None
        self._static_version = 0
        self._static_rebuild_scheduled = False
        self._static_vmax: float | None = None

        self.setMouseTracking(True)

        # Workspace owns viewport-driven refresh coordination.
        #
        # Volume is an auxiliary pane and still consumes the shared horizontal
        # camera, but the surface must not become a second refresh owner by
        # listening directly to viewport signals. Workspace triggers volume
        # repaints explicitly on camera changes (mirroring price/oscillator).
        self._crosshair.changed.connect(self.update)
        self._crosshair.cleared.connect(self.update)

        self._pad_left = 8
        self._pad_top = 6
        self._pad_right = 64
        self._pad_bottom = 14


    def _bump_static_version(self) -> None:
        try:
            self._static_version = int(getattr(self, "_static_version", 0)) + 1
            self._static_pixmap_key = None
        except Exception:
            pass

    def apply_contract(
        self,
        *,
        candles: List[Candle],
        volume: List[float],
        resident_base_index: int,
    ) -> None:
        """Apply the full workspace-owned volume render contract in one update."""
        self._candles = candles
        self._volume = volume
        self._resident_base_index = max(0, int(resident_base_index))
        self._bump_static_version()
        self.update()


class OscillatorRenderSurface(
    OscillatorYAxisInteractionMixin,
    OscillatorSurfacePaintMixin,
    OscillatorPolicyPainterMixin,
    QWidget,
):
    def __init__(
        self,
        title: str,
        viewport: ChartViewport,
        crosshair: Crosshair,
        values: List[float],
        parent: Optional[QWidget] = None,
        *,
        visual_policy: Optional[Mapping[str, Any]] = None,
        candles: Optional[List[Candle]] = None,
    ) -> None:
        super().__init__(parent)
        self._title = str(title).strip() or "Oscillator"
        self._viewport = viewport
        self._crosshair = crosshair
        self._values = values if isinstance(values, list) else list(values)
        self._candles: List[Candle] = candles if isinstance(candles, list) else list(candles or [])

        self._series_list: List[Series] = [
            Series(
                key="__oscillator__",
                title=self._title,
                values=self._values,
            )
        ]

        self._resident_base_index = 0
        self._visual_policy: dict[str, Any] = dict(visual_policy or {})

        # Pane-owned view state is supplied by OscillatorPane/Workspace.
        # Final point-C contract for the oscillator renderer mirrors the price
        # renderer contract:
        # - workspace/pane own the explicit vertical range contract
        # - workspace/pane own the durable interaction state
        # - the renderer consumes that state and may only write back direct
        #   gesture updates into the same pane-owned mapping
        #
        # Required keys for painting:
        # - ``y_lo`` / ``y_hi``: current resolved oscillator range
        #
        # Additional pane-owned keys consumed in this phase:
        # - ``y_offset``: vertical pixel offset applied after value->pixel mapping
        #
        # Transient gesture keys owned in the same pane/workspace mapping:
        # - ``y_drag_active``
        # - ``y_drag_last_mouse_y``
        self._view_state: dict[str, Any] = {}
        self._y_offset = 0.0

        self.setMouseTracking(True)

        # Workspace owns viewport-driven oscillator-pane contract refresh.
        # The renderer repaints when the pane pushes a refreshed contract or
        # when crosshair interaction changes the current overlay state.
        self._crosshair.changed.connect(self.update)
        self._crosshair.cleared.connect(self.update)

        self._pad_left = 8
        self._pad_top = 6
        self._pad_right = 64
        self._pad_bottom = 14

        # ------------------------------------------------------------------
        # Static render caching
        #
        # Oscillator panes can contain multiple series and policy layers. Mouse
        # crosshair motion should not force a full redraw of that entire scene.
        # We therefore cache the static scene into a pixmap and paint only the
        # dynamic crosshair overlay on top.
        # ------------------------------------------------------------------
        self._static_pixmap = None
        self._static_pixmap_key = None
        self._static_version = 0




    def _bump_static_version(self) -> None:
        """Mark the cached static oscillator scene as dirty."""
        try:
            self._static_version = int(getattr(self, "_static_version", 0)) + 1
            self._static_pixmap_key = None
        except Exception:
            pass

    def apply_contract(
        self,
        *,
        title: str,
        series_list: List[Series],
        visual_policy: Optional[Mapping[str, Any]],
        view_state: Optional[Mapping[str, Any]],
        resident_base_index: int,
        candles: Optional[List[Candle]] = None,
    ) -> None:
        """Apply the full pane-owned oscillator render contract in one update."""
        self._title = str(title).strip() or "Oscillator"
        self._series_list = series_list if isinstance(series_list, list) else list(series_list)
        primary = self._primary_series()
        self._values = primary.values if primary is not None else []
        self._visual_policy = dict(visual_policy or {})
        if candles is not None:
            self._candles = candles if isinstance(candles, list) else list(candles)
        if isinstance(view_state, dict):
            self._view_state = view_state
        else:
            self._view_state = dict(view_state or {})
        self._resident_base_index = max(0, int(resident_base_index))
        self._sync_view_state_from_owner()
        self._bump_static_version()
        self.update()
