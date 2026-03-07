from __future__ import annotations

from typing import List, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget, QLabel, QVBoxLayout

from leonardo.common.market_types import Candle
from leonardo.gui.chart.viewport import ChartViewport
from leonardo.gui.chart.model import ChartModel

from leonardo.gui.chart.chart_render import ChartRenderSurface
from leonardo.gui.chart.series_render import VolumeRenderSurface, OscillatorRenderSurface
from leonardo.gui.chart.crosshair import Crosshair


class _PaneOverlay(QWidget):
    """
    Generic floating overlay: Title + (optional) lines.
    Always positioned top-left within its parent pane.
    """
    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)

        self._title = QLabel("", self)
        self._line1 = QLabel("", self)
        self._line2 = QLabel("", self)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(3)
        layout.addWidget(self._title)
        layout.addWidget(self._line1)
        layout.addWidget(self._line2)

        self.setStyleSheet(
            "QWidget { background: rgba(0, 0, 0, 90); border-radius: 6px; }"
            "QLabel { color: white; }"
        )

    def set_title(self, text: str) -> None:
        self._title.setText(text)

    def set_line1(self, text: str) -> None:
        self._line1.setText(text)

    def set_line2(self, text: str) -> None:
        self._line2.setText(text)

    def clear_line2(self) -> None:
        self._line2.setText("")


class PricePane(QWidget):
    """
    Price pane overlay:
    - Asset · TF (title)
    - OHLC at crosshair (line1)
    - Indicator values (line2)
    """
    def __init__(
        self,
        viewport: ChartViewport,
        model: ChartModel,
        crosshair: Crosshair,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)

        self._viewport = viewport
        self._model = model
        self._crosshair = crosshair

        self._surface = ChartRenderSurface(
            viewport=self._viewport,
            crosshair=self._crosshair,
            candles=self._model.candles,
            parent=self,
        )

        self._overlay = _PaneOverlay(self)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._surface)

        self._overlay.set_title("ASSET · TF")
        self._overlay.set_line1("")
        self._overlay.set_line2("")

        self._viewport.viewport_changed.connect(self._update_overlay)
        self._crosshair.changed.connect(self._update_overlay)
        self._crosshair.cleared.connect(self._update_overlay)

        # Ensure repaint + overlay refresh when model data changes (snapshot/stream updates)
        self._model.changed.connect(self._sync_surface_from_model)
        self._model.changed.connect(self._update_overlay)
        self._model.changed.connect(self._surface.update)

        self._sync_surface_from_model()
        self._update_overlay()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._overlay.move(12, 12)
        self._overlay.adjustSize()

    def set_asset_label(self, text: str) -> None:
        self._overlay.set_title(text)
        self._overlay.adjustSize()

    # kept for compatibility (not used anymore for values)
    def set_studies(self, indicators: List[str], oscillators: List[str]) -> None:
        self._update_overlay()

    def _sync_surface_from_model(self) -> None:
        if hasattr(self._surface, "set_candles"):
            try:
                self._surface.set_candles(self._model.candles)
            except Exception:
                pass
            
        if hasattr(self._surface, "set_resident_base_index"):
            try:
                self._surface.set_resident_base_index(self._model.resident_base_index)
            except Exception:
                pass

    def _global_to_local(self, global_index: int) -> Optional[int]:
        if hasattr(self._model, "global_to_local"):
            try:
                return self._model.global_to_local(global_index)
            except Exception:
                return None
        if 0 <= global_index < len(self._model.candles):
            return global_index
        return None

    def _overlay_index_local(self) -> Optional[int]:
        candles: List[Candle] = self._model.candles
        if not candles:
            return None

        idx = self._crosshair.index
        local = self._global_to_local(idx) if idx is not None else None
        if local is None:
            local = len(candles) - 1
        return local

    def _update_overlay(self) -> None:
        candles: List[Candle] = self._model.candles
        if not candles:
            self._overlay.set_line1("O: —  H: —  L: —  C: —")
            self._overlay.set_line2("")
            self._overlay.adjustSize()
            return

        local_idx = self._overlay_index_local()
        if local_idx is None or local_idx < 0 or local_idx >= len(candles):
            local_idx = len(candles) - 1

        c = candles[local_idx]
        self._overlay.set_line1(
            f"O: {c.open:.2f}  H: {c.high:.2f}  L: {c.low:.2f}  C: {c.close:.2f}"
        )

        # IMPORTANT: only show price OVERLAYS (indicators) here.
        parts: List[str] = []
        for s in self._model.overlays().values():
            if local_idx < len(s.values):
                parts.append(f"{s.title}: {s.values[local_idx]:.2f}")

        self._overlay.set_line2("  |  ".join(parts) if parts else "")
        self._overlay.adjustSize()


class VolumePane(QWidget):
    """
    Volume pane overlay:
    - "Volume" (title)
    - "Vol: <value>" at crosshair index (line1)
    """
    def __init__(
        self,
        viewport: ChartViewport,
        volume: List[float],
        crosshair: Crosshair,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)

        self._viewport = viewport
        self._volume = volume
        self._crosshair = crosshair
        self._resident_base_index = 0

        self._surface = VolumeRenderSurface(
            viewport=self._viewport,
            crosshair=self._crosshair,
            volume=self._volume,
            parent=self,
        )
        self._overlay = _PaneOverlay(self)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._surface)

        self._overlay.set_title("Volume")
        self._overlay.set_line1("")
        self._overlay.clear_line2()

        self._viewport.viewport_changed.connect(self._update_overlay)
        self._crosshair.changed.connect(self._update_overlay)
        self._crosshair.cleared.connect(self._update_overlay)

        self._sync_surface_state()
        self._update_overlay()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._overlay.move(12, 12)
        self._overlay.adjustSize()

    def set_volume(self, volume: List[float]) -> None:
        self._volume = volume
        self._sync_surface_state()
        self._update_overlay()

    def set_resident_base_index(self, base_index: int) -> None:
        self._resident_base_index = max(0, int(base_index))
        self._sync_surface_state()
        self._update_overlay()

    def _sync_surface_state(self) -> None:
        if hasattr(self._surface, "set_volume"):
            try:
                self._surface.set_volume(self._volume)
            except Exception:
                pass

        if hasattr(self._surface, "set_resident_base_index"):
            try:
                self._surface.set_resident_base_index(self._resident_base_index)
            except Exception:
                pass

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
            self._overlay.set_line1("Vol: —")
            self._overlay.adjustSize()
            return

        local_idx = self._overlay_index_local()
        if local_idx is None or local_idx < 0 or local_idx >= len(self._volume):
            local_idx = len(self._volume) - 1

        self._overlay.set_line1(f"Vol: {self._volume[local_idx]:.0f}")
        self._overlay.adjustSize()


class OscillatorPane(QWidget):
    """
    Oscillator pane overlay:
    - Oscillator title (title)
    - "<value>" at crosshair index (line1)
    """
    def __init__(
        self,
        title: str,
        viewport: ChartViewport,
        values: List[float],
        crosshair: Crosshair,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)

        self._title = title
        self._viewport = viewport
        self._crosshair = crosshair
        self._values = values
        self._resident_base_index = 0

        self._surface = OscillatorRenderSurface(
            title=title,
            viewport=self._viewport,
            crosshair=self._crosshair,
            values=self._values,
            parent=self,
        )
        self._overlay = _PaneOverlay(self)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._surface)

        self._overlay.set_title(self._title)
        self._overlay.set_line1("")
        self._overlay.clear_line2()

        self._viewport.viewport_changed.connect(self._update_overlay)
        self._crosshair.changed.connect(self._update_overlay)
        self._crosshair.cleared.connect(self._update_overlay)

        self._sync_surface_state()
        self._update_overlay()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._overlay.move(12, 12)
        self._overlay.adjustSize()

    def set_values(self, values: List[float]) -> None:
        self._values = values
        self._sync_surface_state()
        self._update_overlay()

    def set_resident_base_index(self, base_index: int) -> None:
        self._resident_base_index = max(0, int(base_index))
        self._sync_surface_state()
        self._update_overlay()

    def _sync_surface_state(self) -> None:
        if hasattr(self._surface, "set_values"):
            try:
                self._surface.set_values(self._values)
            except Exception:
                pass

        if hasattr(self._surface, "set_resident_base_index"):
            try:
                self._surface.set_resident_base_index(self._resident_base_index)
            except Exception:
                pass

    def _global_to_local(self, global_index: int) -> Optional[int]:
        local = int(global_index) - self._resident_base_index
        if 0 <= local < len(self._values):
            return local
        return None

    def _overlay_index_local(self) -> Optional[int]:
        if not self._values:
            return None

        idx = self._crosshair.index
        local = self._global_to_local(idx) if idx is not None else None
        if local is None:
            local = len(self._values) - 1
        return local

    def _update_overlay(self) -> None:
        if not self._values:
            self._overlay.set_line1("—")
            self._overlay.adjustSize()
            return

        local_idx = self._overlay_index_local()
        if local_idx is None or local_idx < 0 or local_idx >= len(self._values):
            local_idx = len(self._values) - 1

        self._overlay.set_line1(f"{self._values[local_idx]:.2f}")
        self._overlay.adjustSize()