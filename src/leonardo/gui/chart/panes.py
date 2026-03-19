from __future__ import annotations

from typing import List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget,
    QLabel,
    QVBoxLayout,
    QHBoxLayout,
    QToolButton,
)

from leonardo.common.market_types import Candle
from leonardo.gui.chart.viewport import ChartViewport
from leonardo.gui.chart.model import ChartModel

from leonardo.gui.chart.chart_render import ChartRenderSurface
from leonardo.gui.chart.series_render import VolumeRenderSurface, OscillatorRenderSurface
from leonardo.gui.chart.crosshair import Crosshair


class _PaneOverlay(QWidget):
    """
    Generic floating overlay container.
    """
    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(8, 8, 8, 8)
        self._layout.setSpacing(4)

        self.setStyleSheet(
            "QWidget { background: rgba(0, 0, 0, 90); border-radius: 6px; }"
            "QLabel { color: white; }"
            "QToolButton {"
            "  color: white;"
            "  background: rgba(255, 255, 255, 22);"
            "  border: 1px solid rgba(255, 255, 255, 40);"
            "  border-radius: 4px;"
            "  padding: 2px 6px;"
            "}"
            "QToolButton:hover {"
            "  background: rgba(255, 255, 255, 36);"
            "}"
        )

    @property
    def layout_box(self) -> QVBoxLayout:
        return self._layout


class _HeaderInfoBlock(QWidget):
    """
    Title + OHLC block used at the top of the price overlay card.
    """
    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)

        self._title = QLabel("", self)
        self._line1 = QLabel("", self)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(3)
        layout.addWidget(self._title)
        layout.addWidget(self._line1)

    def set_title(self, text: str) -> None:
        self._title.setText(text)

    def set_line1(self, text: str) -> None:
        self._line1.setText(text)


class _StudyRow(QWidget):
    edit_requested = Signal(str)
    remove_requested = Signal(str)

    def __init__(self, series_key: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._series_key = str(series_key)

        self._label = QLabel("", self)

        self._edit_btn = QToolButton(self)
        self._edit_btn.setText("Edit")
        self._edit_btn.clicked.connect(self._emit_edit)

        self._remove_btn = QToolButton(self)
        self._remove_btn.setText("X")
        self._remove_btn.setToolTip("Remove study from chart")
        self._remove_btn.clicked.connect(self._emit_remove)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        layout.addWidget(self._label, 1)
        layout.addWidget(self._edit_btn, 0)
        layout.addWidget(self._remove_btn, 0)

    @property
    def series_key(self) -> str:
        return self._series_key

    def set_text(self, text: str) -> None:
        self._label.setText(text)

    def _emit_edit(self) -> None:
        self.edit_requested.emit(self._series_key)

    def _emit_remove(self) -> None:
        self.remove_requested.emit(self._series_key)


class PricePane(QWidget):
    """
    Price pane overlay:
    - Asset · TF (title)
    - OHLC at crosshair
    - Interactive study rows for active overlays
    """

    study_edit_requested = Signal(str)
    study_remove_requested = Signal(str)

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
        self._header = _HeaderInfoBlock(self._overlay)
        self._overlay.layout_box.addWidget(self._header)

        self._study_rows_host = QWidget(self._overlay)
        self._study_rows_layout = QVBoxLayout(self._study_rows_host)
        self._study_rows_layout.setContentsMargins(0, 4, 0, 0)
        self._study_rows_layout.setSpacing(4)
        self._overlay.layout_box.addWidget(self._study_rows_host)

        self._study_rows: dict[str, _StudyRow] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._surface)

        self._header.set_title("ASSET · TF")
        self._header.set_line1("")

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
        self._header.set_title(text)
        self._overlay.adjustSize()

    # kept for compatibility
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

    def _ensure_study_row(self, series_key: str) -> _StudyRow:
        row = self._study_rows.get(series_key)
        if row is not None:
            return row

        row = _StudyRow(series_key, self._study_rows_host)
        row.edit_requested.connect(self.study_edit_requested)
        row.remove_requested.connect(self.study_remove_requested)
        self._study_rows_layout.addWidget(row)
        self._study_rows[series_key] = row
        return row

    def _clear_missing_study_rows(self, active_keys: set[str]) -> None:
        to_remove = [key for key in self._study_rows.keys() if key not in active_keys]
        for key in to_remove:
            row = self._study_rows.pop(key, None)
            if row is not None:
                self._study_rows_layout.removeWidget(row)
                row.setParent(None)
                row.deleteLater()

    def _update_overlay(self) -> None:
        candles: List[Candle] = self._model.candles
        if not candles:
            self._header.set_line1("O: —  H: —  L: —  C: —")
            self._clear_missing_study_rows(set())
            self._overlay.adjustSize()
            return

        local_idx = self._overlay_index_local()
        if local_idx is None or local_idx < 0 or local_idx >= len(candles):
            local_idx = len(candles) - 1

        c = candles[local_idx]
        self._header.set_line1(
            f"O: {c.open:.2f}  H: {c.high:.2f}  L: {c.low:.2f}  C: {c.close:.2f}"
        )

        active_keys: set[str] = set()

        for key, s in self._model.overlays().items():
            active_keys.add(key)
            row = self._ensure_study_row(key)

            value_text = "—"
            if local_idx < len(s.values):
                try:
                    value_text = f"{float(s.values[local_idx]):.2f}"
                except Exception:
                    value_text = "—"

            row.set_text(f"{s.title}: {value_text}")

        self._clear_missing_study_rows(active_keys)
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

        self._viewport.viewport_changed.connect(self._update_overlay)
        self._crosshair.changed.connect(self._update_overlay)
        self._crosshair.cleared.connect(self._update_overlay)

        self._sync_surface_state()
        self._update_overlay()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._overlay.move(12, 12)
        self._overlay.adjustSize()

    def set_candles(self, candles: List[Candle]) -> None:
        self._candles = candles
        self._sync_surface_state()
        self._update_overlay()

    def set_volume(self, volume: List[float]) -> None:
        self._volume = volume
        self._sync_surface_state()
        self._update_overlay()

    def set_resident_base_index(self, base_index: int) -> None:
        self._resident_base_index = max(0, int(base_index))
        self._sync_surface_state()
        self._update_overlay()

    def _sync_surface_state(self) -> None:
        if hasattr(self._surface, "set_candles"):
            try:
                self._surface.set_candles(self._candles)
            except Exception:
                pass

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
            self._line1.setText("Vol: —")
            self._overlay.adjustSize()
            return

        local_idx = self._overlay_index_local()
        if local_idx is None or local_idx < 0 or local_idx >= len(self._volume):
            local_idx = len(self._volume) - 1

        self._line1.setText(f"Vol: {self._volume[local_idx]:.0f}")
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

        self._title_text = title
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

        self._title = QLabel(self._title_text, self._overlay)
        self._line1 = QLabel("", self._overlay)

        overlay_layout = self._overlay.layout_box
        overlay_layout.addWidget(self._title)
        overlay_layout.addWidget(self._line1)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._surface)

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
            self._line1.setText("—")
            self._overlay.adjustSize()
            return

        local_idx = self._overlay_index_local()
        if local_idx is None or local_idx < 0 or local_idx >= len(self._values):
            local_idx = len(self._values) - 1

        self._line1.setText(f"{self._values[local_idx]:.2f}")
        self._overlay.adjustSize()