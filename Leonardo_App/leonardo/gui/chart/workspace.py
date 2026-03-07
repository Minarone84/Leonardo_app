from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QSplitter, QWidget, QVBoxLayout

from leonardo.common.market_types import ChartPatch, ChartSnapshot, Candle
from leonardo.gui.chart.viewport import ChartViewport
from leonardo.gui.chart.dummy_data import make_dummy_oscillator
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

        # NOTE: Indicators/oscillators are out of scope for the exchange phase.
        # We do NOT pre-populate dummy oscillator series here.

        # ---- Shared viewport ----
        # Start empty: no data yet
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

    # -------- Public API (MainWindow calls these) --------

    def set_asset_label(self, text: str) -> None:
        self._price.set_asset_label(text)

    def set_studies_labels(self, indicators: List[str], oscillators: List[str]) -> None:
        self._price.set_studies(indicators=indicators, oscillators=oscillators)

    def set_anchor_zoom_enabled(self, enabled: bool) -> None:
        enabled = bool(enabled)

        # allow future space only when anchor is OFF
        self._viewport.set_future_padding(0 if enabled else 50)  # tweak as desired

        self._viewport.set_anchor_zoom_enabled(enabled)

    def set_volume_enabled(self, enabled: bool) -> None:
        if enabled and self._volume is None:
            self._volume = VolumePane(
                viewport=self._viewport,
                crosshair=self._crosshair,
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
        # Still supported for GUI testing, but values are dummy until indicators return.
        if spec.key in self._oscillators:
            return

        series = self._model.oscillator(spec.key)
        if series is None:
            n = max(1, len(self._model.candles))
            series = Series(
                key=spec.key,
                title=spec.title,
                values=make_dummy_oscillator(n=n, seed=99),
            )
            self._model.set_oscillator(series)

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
        self._apply_default_sizes()

    def clear_oscillators(self) -> None:
        for key in list(self._oscillators.keys()):
            self.remove_oscillator(key)

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
            if hasattr(self._viewport, "set_total_count"):
                self._viewport.set_total_count(0)  # type: ignore[attr-defined]
            return

        self._model.set_candles(candles)
        self._model.set_volume([float(c.volume) for c in candles])

        # Realtime/local snapshot semantics: viewport indices remain local.
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

            self._refresh_aux_pane_bindings()

            if hasattr(self._viewport, "set_total_count_preserve_position"):
                self._viewport.set_total_count_preserve_position(max(0, int(dataset_total)))  # type: ignore[attr-defined]
            elif hasattr(self._viewport, "set_total_count"):
                self._viewport.set_total_count(max(0, int(dataset_total)))  # type: ignore[attr-defined]
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

        self._refresh_aux_pane_bindings()

        if hasattr(self._viewport, "set_total_count_preserve_position"):
            self._viewport.set_total_count_preserve_position(max(0, int(dataset_total)))  # type: ignore[attr-defined]
        elif hasattr(self._viewport, "set_total_count"):
            self._viewport.set_total_count(max(0, int(dataset_total)))  # type: ignore[attr-defined]

    def apply_patch(self, patch: ChartPatch) -> None:
        self.set_asset_label(f"{patch.symbol} · {patch.timeframe}")

        if patch.op == "append":
            # cap realtime window
            self._model.append_candle(patch.candle, maxlen=200)

            # Realtime/local patch semantics: viewport indices remain local.
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

            # update viewport to new (possibly trimmed) length
            if hasattr(self._viewport, "set_total_count"):
                self._viewport.set_total_count(len(self._model.candles))  # type: ignore[attr-defined]

            self._refresh_aux_pane_bindings()
        else:
            # "update" of the currently forming candle
            self._model.update_last_candle(patch.candle)

            # Realtime/local patch semantics: viewport indices remain local.
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
            if series is not None and hasattr(pane, "set_values"):
                try:
                    pane.set_values(series.values)  # type: ignore[attr-defined]
                except Exception:
                    pass

            if hasattr(pane, "set_resident_base_index"):
                try:
                    pane.set_resident_base_index(resident_base_index)  # type: ignore[attr-defined]
                except Exception:
                    pass