from __future__ import annotations

from typing import List, Optional

from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from leonardo.common.market_types import Candle
from leonardo.gui.chart.crosshair import Crosshair
from leonardo.gui.chart.series_render import VolumeRenderSurface
from leonardo.gui.chart.viewport import ChartViewport

from .header_widgets import _PaneOverlay

class VolumePane(QWidget):
    """
    Auxiliary base volume pane.

    Volume is rendered relative to the same chart-session x-axis as the base
    OHLC layer, but it is not the canonical price foundation.
    """

    def __init__(
        self,
        viewport: ChartViewport,
        candles: List[Candle],
        volume: List[float],
        crosshair: Crosshair,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)

        self._viewport = viewport
        self._candles = candles
        self._volume = volume
        self._crosshair = crosshair
        self._resident_base_index = 0
        self._last_overlay_text = ""

        self._surface = VolumeRenderSurface(
            viewport=self._viewport,
            crosshair=self._crosshair,
            candles=self._candles,
            volume=self._volume,
            parent=self,
        )
        self._overlay = _PaneOverlay(self)

        self._title = QLabel("Volume", self._overlay)
        self._line1 = QLabel("", self._overlay)

        overlay_layout = self._overlay.layout_box
        overlay_layout.addWidget(self._title)
        overlay_layout.addWidget(self._line1)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._surface)

        self._crosshair.changed.connect(self._update_overlay)
        self._crosshair.cleared.connect(self._update_overlay)

        self._sync_surface_state()
        self._update_overlay()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._overlay.anchor_top_left()

    def apply_contract(
        self,
        *,
        candles: List[Candle],
        volume: List[float],
        resident_base_index: int,
    ) -> None:
        """Apply the full workspace-owned volume-pane contract in one step."""
        self._candles = candles
        self._volume = volume
        self._resident_base_index = max(0, int(resident_base_index))
        self._sync_surface_state()
        self._update_overlay()


    def refresh_viewport(self) -> None:
        """Repaint the volume surface after viewport camera changes.

        VolumePane consumes the shared horizontal camera, but it does not own
        viewport refresh triggers. Workspace calls this method explicitly when
        the viewport changes so VolumeRenderSurface does not need to subscribe
        directly to viewport signals.
        """
        try:
            self._surface.update()
        except Exception:
            self.update()

    def _sync_surface_state(self) -> None:
        # Contract-first handoff. VolumeRenderSurface consumes one coherent payload
        # instead of a fragmented setter cascade.
        self._surface.apply_contract(
            candles=self._candles,
            volume=self._volume,
            resident_base_index=self._resident_base_index,
        )

    def _global_to_local(self, global_index: int) -> Optional[int]:
        local = int(global_index) - self._resident_base_index
        if 0 <= local < len(self._volume):
            return local
        return None

    def _overlay_index_local(self) -> Optional[int]:
        if not self._volume:
            return None

        idx = self._crosshair.index
        local = self._global_to_local(idx) if idx is not None else None
        if local is None:
            local = len(self._volume) - 1
        return local

    def _update_overlay(self) -> None:
        if not self._volume:
            if self._last_overlay_text != "Vol: —":
                self._line1.setText("Vol: —")
                self._last_overlay_text = "Vol: —"
            return

        local_idx = self._overlay_index_local()
        if local_idx is None or local_idx < 0 or local_idx >= len(self._volume):
            local_idx = len(self._volume) - 1

        text = f"Vol: {self._volume[local_idx]:.0f}"
        if text != self._last_overlay_text:
            self._line1.setText(text)
            self._last_overlay_text = text
