from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QSplitter, QWidget, QVBoxLayout

from leonardo.common.market_types import ChartPatch, ChartSnapshot, Candle
from leonardo.gui.chart.viewport import ChartViewport
from leonardo.gui.chart.model import ChartModel, Series
from leonardo.gui.chart.panes import PricePane, VolumePane, OscillatorPane
from leonardo.gui.chart.crosshair import Crosshair


@dataclass(frozen=True)
class OscillatorSpec:
    key: str    # unique id, e.g. "rsi_14"
    title: str  # e.g. "RSI(14)"


class ChartWorkspaceWidget(QWidget):
    """
    Central chart workspace: price pane + optional volume + optional oscillator panes.
    Shared viewport + shared data owned here (via ChartModel).

    apply_snapshot/apply_patch are GUI-thread entry points for core market data updates.
    """

    request_start_feed = Signal()
    request_stop_feed = Signal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)

        self._crosshair = Crosshair()

        # ---- Shared data (owned by the model) ----
        self._model = ChartModel(candles=[], volume=[])

        # ---- Shared viewport ----
        self._viewport = ChartViewport(total_count=0, visible_count=1)

        # ---- Layout ----
        self._splitter = QSplitter(Qt.Vertical, self)
        self._splitter.setChildrenCollapsible(False)

        self._price = PricePane(
            viewport=self._viewport,
            model=self._model,
            crosshair=self._crosshair,
            parent=self,
        )
        self._splitter.addWidget(self._price)

        # Optional panes (not shown by default)
        self._volume: Optional[VolumePane] = None
        self._oscillators: Dict[str, OscillatorPane] = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(self._splitter)

        self._apply_default_sizes()

    # -------- Public API (MainWindow / controller calls these) --------

    def set_asset_label(self, text: str) -> None:
        self._price.set_asset_label(text)

    def set_studies_labels(self, indicators: List[str], oscillators: List[str]) -> None:
        self._price.set_studies(indicators=indicators, oscillators=oscillators)
        self._refresh_price_pane()

    def set_anchor_zoom_enabled(self, enabled: bool) -> None:
        enabled = bool(enabled)

        self._viewport.set_anchor_zoom_enabled(enabled)
        self._viewport.set_future_padding(0 if enabled else 50)
        self._refresh_price_pane()

    def set_volume_enabled(self, enabled: bool) -> None:
        if enabled and self._volume is None:
            self._volume = VolumePane(
                viewport=self._viewport,
                crosshair=self._crosshair,
                candles=self._model.candles,
                volume=self._model.volume,
                parent=self,
            )
            self._splitter.addWidget(self._volume)
            self._refresh_aux_pane_bindings()
            self._apply_default_sizes()
        elif not enabled and self._volume is not None:
            self._remove_widget(self._volume)
            self._volume.deleteLater()
            self._volume = None
            self._apply_default_sizes()

    def add_oscillator(self, spec: OscillatorSpec) -> None:
        """
        Create a pane for an already-existing oscillator series in the model.

        This method no longer creates dummy data. A real oscillator series must
        already exist in the model before a pane is added.
        """
        if spec.key in self._oscillators:
            return

        series = self._model.oscillator(spec.key)
        if series is None:
            return

        pane = OscillatorPane(
            title=series.title,
            viewport=self._viewport,
            crosshair=self._crosshair,
            values=series.values,
            parent=self,
        )
        self._oscillators[spec.key] = pane
        self._splitter.addWidget(pane)
        self._refresh_aux_pane_bindings()
        self._apply_default_sizes()

    def remove_oscillator(self, key: str) -> None:
        pane = self._oscillators.pop(key, None)
        if pane is None:
            return
        self._remove_widget(pane)
        pane.deleteLater()
        self._model.remove_oscillator(key)
        self._apply_default_sizes()

    def clear_oscillators(self) -> None:
        for key in list(self._oscillators.keys()):
            pane = self._oscillators.pop(key, None)
            if pane is not None:
                self._remove_widget(pane)
                pane.deleteLater()
        for key in list(self._model.oscillators().keys()):
            self._model.remove_oscillator(key)
        self._apply_default_sizes()

    def clear_overlays(self) -> None:
        for key in list(self._model.overlays().keys()):
            self._model.remove_overlay(key)
        self._refresh_aux_pane_bindings()
        self._refresh_studies_labels()
        self._refresh_price_pane()

    def clear_financial_tools(self) -> None:
        self.clear_overlays()
        self.clear_oscillators()

    def apply_overlay_series(self, series: Series) -> None:
        """
        Apply or replace a price overlay series in the chart model.
        """
        self._model.set_overlay(series)
        self._refresh_aux_pane_bindings()
        self._refresh_studies_labels()
        self._refresh_price_pane()

    def remove_overlay_series(self, key: str) -> None:
        """
        Remove a price overlay series from the chart model.
        """
        self._model.remove_overlay(key)
        self._refresh_aux_pane_bindings()
        self._refresh_studies_labels()
        self._refresh_price_pane()

    def apply_oscillator_series(self, series: Series) -> None:
        """
        Apply or replace an oscillator series and ensure its pane exists.
        """
        self._model.set_oscillator(series)

        if series.key in self._oscillators:
            pane = self._oscillators[series.key]
            if hasattr(pane, "set_values"):
                try:
                    pane.set_values(series.values)
                except Exception:
                    pass
        else:
            pane = OscillatorPane(
                title=series.title,
                viewport=self._viewport,
                crosshair=self._crosshair,
                values=series.values,
                parent=self,
            )
            self._oscillators[series.key] = pane
            self._splitter.addWidget(pane)

        self._refresh_aux_pane_bindings()
        self._refresh_studies_labels()
        self._apply_default_sizes()

    def remove_oscillator_series(self, key: str) -> None:
        """
        Remove an oscillator series and its pane.
        """
        self.remove_oscillator(key)
        self._refresh_aux_pane_bindings()
        self._refresh_studies_labels()

    @property
    def viewport(self) -> ChartViewport:
        return self._viewport

    @property
    def model(self) -> ChartModel:
        return self._model

    # -------- core → GUI chart update API --------

    def apply_snapshot(self, snapshot: ChartSnapshot) -> None:
        candles = list(snapshot.candles)

        self.set_asset_label(f"{snapshot.symbol} · {snapshot.timeframe}")

        if not candles:
            self._model.set_candles([])
            self._model.set_volume([])
            if hasattr(self._model, "set_resident_base_index"):
                try:
                    self._model.set_resident_base_index(0)  # type: ignore[attr-defined]
                except Exception:
                    pass
            elif hasattr(self._model, "resident_base_index"):
                try:
                    setattr(self._model, "resident_base_index", 0)
                except Exception:
                    pass

            self._refresh_aux_pane_bindings()
            self._refresh_studies_labels()
            self._refresh_price_pane()
            if hasattr(self._viewport, "set_total_count"):
                self._viewport.set_total_count(0)  # type: ignore[attr-defined]
            return

        self._model.set_candles(candles)
        self._model.set_volume([float(c.volume) for c in candles])

        if hasattr(self._model, "set_resident_base_index"):
            try:
                self._model.set_resident_base_index(0)  # type: ignore[attr-defined]
            except Exception:
                pass
        elif hasattr(self._model, "resident_base_index"):
            try:
                setattr(self._model, "resident_base_index", 0)
            except Exception:
                pass

        self._refresh_aux_pane_bindings()
        self._refresh_studies_labels()
        self._refresh_price_pane()

        n = len(candles)
        if hasattr(self._viewport, "set_total_count"):
            self._viewport.set_total_count(n)  # type: ignore[attr-defined]

    def apply_historical_slice(
        self,
        *,
        symbol: str,
        timeframe: str,
        candles: List[Candle],
        resident_base_index: int,
        dataset_total: int,
    ) -> None:
        """
        Historical-mode apply path.

        Unlike apply_snapshot(), the viewport total represents the full dataset
        size, while the model stores only the currently resident slice.
        """
        self.set_asset_label(f"{symbol} · {timeframe}")

        if not candles:
            self._model.set_candles([])
            self._model.set_volume([])
            if hasattr(self._model, "set_resident_base_index"):
                try:
                    self._model.set_resident_base_index(int(resident_base_index))  # type: ignore[attr-defined]
                except Exception:
                    pass
            elif hasattr(self._model, "resident_base_index"):
                try:
                    setattr(self._model, "resident_base_index", int(resident_base_index))
                except Exception:
                    pass

            if hasattr(self._viewport, "set_total_count_preserve_position"):
                self._viewport.set_total_count_preserve_position(max(0, int(dataset_total)))  # type: ignore[attr-defined]
            elif hasattr(self._viewport, "set_total_count"):
                self._viewport.set_total_count(max(0, int(dataset_total)))  # type: ignore[attr-defined]

            self._refresh_aux_pane_bindings()
            self._refresh_studies_labels()
            self._refresh_price_pane()
            return

        self._model.set_candles(candles)
        self._model.set_volume([float(c.volume) for c in candles])

        if hasattr(self._model, "set_resident_base_index"):
            try:
                self._model.set_resident_base_index(int(resident_base_index))  # type: ignore[attr-defined]
            except Exception:
                pass
        elif hasattr(self._model, "resident_base_index"):
            try:
                setattr(self._model, "resident_base_index", int(resident_base_index))
            except Exception:
                pass

        if hasattr(self._viewport, "set_total_count_preserve_position"):
            self._viewport.set_total_count_preserve_position(max(0, int(dataset_total)))  # type: ignore[attr-defined]
        elif hasattr(self._viewport, "set_total_count"):
            self._viewport.set_total_count(max(0, int(dataset_total)))  # type: ignore[attr-defined]

        self._refresh_aux_pane_bindings()
        self._refresh_studies_labels()
        self._refresh_price_pane()

    def apply_patch(self, patch: ChartPatch) -> None:
        self.set_asset_label(f"{patch.symbol} · {patch.timeframe}")

        if patch.op == "append":
            self._model.append_candle(patch.candle, maxlen=200)

            if hasattr(self._model, "set_resident_base_index"):
                try:
                    self._model.set_resident_base_index(0)  # type: ignore[attr-defined]
                except Exception:
                    pass
            elif hasattr(self._model, "resident_base_index"):
                try:
                    setattr(self._model, "resident_base_index", 0)
                except Exception:
                    pass

            if hasattr(self._viewport, "set_total_count"):
                self._viewport.set_total_count(len(self._model.candles))  # type: ignore[attr-defined]

            self._refresh_aux_pane_bindings()
            self._refresh_studies_labels()
            self._refresh_price_pane()
        else:
            self._model.update_last_candle(patch.candle)

            if hasattr(self._model, "set_resident_base_index"):
                try:
                    self._model.set_resident_base_index(0)  # type: ignore[attr-defined]
                except Exception:
                    pass
            elif hasattr(self._model, "resident_base_index"):
                try:
                    setattr(self._model, "resident_base_index", 0)
                except Exception:
                    pass

            self._refresh_aux_pane_bindings()
            self._refresh_studies_labels()
            self._refresh_price_pane()

    # -------- Internal helpers --------

    def _apply_default_sizes(self) -> None:
        sizes = [800]
        if self._volume:
            sizes.append(200)
        for _ in range(len(self._oscillators)):
            sizes.append(220)

        if len(sizes) == 1:
            sizes = [1000]

        self._splitter.setSizes(sizes)

    def _remove_widget(self, w: QWidget) -> None:
        w.setParent(None)
        w.hide()

    def _refresh_studies_labels(self) -> None:
        overlay_titles = [s.title for s in self._model.overlays().values()]
        oscillator_titles = [s.title for s in self._model.oscillators().values()]
        self.set_studies_labels(overlay_titles, oscillator_titles)

    def _refresh_price_pane(self) -> None:
        """
        Force the price pane to repaint after candle/overlay/study changes.

        This is intentionally explicit because overlay series can be present in
        the model and in the study labels while still not becoming visible until
        the pane is repainted.
        """
        if hasattr(self._price, "update"):
            try:
                self._price.update()  # type: ignore[attr-defined]
            except Exception:
                pass

        if hasattr(self._price, "repaint"):
            try:
                self._price.repaint()  # type: ignore[attr-defined]
            except Exception:
                pass

    def _refresh_aux_pane_bindings(self) -> None:
        """
        Keep auxiliary panes bound to the model's current series objects and
        resident base index.
        """
        resident_base_index = 0
        if hasattr(self._model, "resident_base_index"):
            try:
                resident_base_index = int(self._model.resident_base_index)
            except Exception:
                resident_base_index = 0

        if self._volume is not None:
            if hasattr(self._volume, "set_candles"):
                try:
                    self._volume.set_candles(self._model.candles)  # type: ignore[attr-defined]
                except Exception:
                    pass

            if hasattr(self._volume, "set_volume"):
                try:
                    self._volume.set_volume(self._model.volume)  # type: ignore[attr-defined]
                except Exception:
                    pass

            if hasattr(self._volume, "set_resident_base_index"):
                try:
                    self._volume.set_resident_base_index(resident_base_index)  # type: ignore[attr-defined]
                except Exception:
                    pass

        for key, pane in self._oscillators.items():
            series = self._model.oscillator(key)
            if series is not None:
                if hasattr(pane, "set_values"):
                    try:
                        pane.set_values(series.values)  # type: ignore[attr-defined]
                    except Exception:
                        pass

            if hasattr(pane, "set_resident_base_index"):
                try:
                    pane.set_resident_base_index(resident_base_index)  # type: ignore[attr-defined]
                except Exception:
                    pass