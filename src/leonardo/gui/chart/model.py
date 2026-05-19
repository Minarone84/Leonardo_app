from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Dict, Iterator, List, Optional, Mapping, Sequence

from PySide6.QtCore import QObject, Signal

from leonardo.common.market_types import Candle


@dataclass(frozen=True)
class SeriesStyle:
    """
    Chart-local display style for a renderable series.

    This is intentionally separate from computation parameters.
    """
    color: Optional[str] = None
    line_width: int = 1
    line_style: str = "solid"  # solid | dotted | dashed | dash_dot
    visible: bool = True
    render_mode: str = "line"  # line | marker
    marker_shape: Optional[str] = None  # triangle_up | triangle_down
    marker_size: int = 0
    marker_text: str = ""
    marker_text_color: Optional[str] = None
    marker_offset_px: int = 0


@dataclass(frozen=True)
class Series:
    key: str
    title: str
    values: Sequence[float]
    style: SeriesStyle = field(default_factory=SeriesStyle)


@dataclass(frozen=True)
class OverlayFill:
    """
    Chart-local static fill descriptor between two overlay series.

    This is renderer-facing metadata owned by the chart model so the price
    renderer can consume fill information without needing to understand study
    internals directly.

    Important:
    - this is display-only state
    - this does not alter computation
    - this is intended for static fill configuration in the current phase
    """
    fill_id: str
    series_a: str
    series_b: str
    color: Optional[str] = None
    opacity: float = 0.15
    visible: bool = True


@dataclass(frozen=True)
class TradeMarker:
    # Stub for now; will expand in step (3)
    index: int
    price: float
    side: str  # "buy" | "sell"
    label: str = ""


class ChartModel(QObject):
    """
    GUI-side chart data container.

    Canonical chart contract:
    - OHLC bars are the base chart layer and the foundation for all rendering.
    - Volume is an auxiliary base layer. It is not part of the canonical price
      foundation and must not redefine chart truth.
    - Overlays, oscillators, and trades are derived or auxiliary render state.
      They are never the base chart layer.

    Important implementation note:
    - Render surfaces may hold references to the base OHLC and base volume
      lists. Therefore base-layer updates must mutate lists IN PLACE rather than
      rebinding them.
    """

    changed = Signal()

    def __init__(self, candles: List[Candle], volume: List[float]) -> None:
        super().__init__()

        # Base chart layers
        self._candles: List[Candle] = candles
        self._volume: List[float] = volume

        # Resident base index maps resident/local bar positions to the global
        # chart-session x-axis. It is a visualization alignment helper only.
        self._resident_base_index: int = 0

        # Derived / auxiliary render state
        self._overlays: Dict[str, Series] = {}
        self._overlay_fills: Dict[str, OverlayFill] = {}
        self._oscillators: Dict[str, Series] = {}
        self._trades: List[TradeMarker] = []

        # Workspace owns when chart-state mutations should be grouped into one
        # coherent pane refresh. The model therefore supports batched change
        # emission so large resident-slice or multi-study updates do not fan
        # out into a repaint storm.
        self._change_batch_depth: int = 0
        self._change_pending: bool = False

    # ------------------------------------------------------------------
    # Change batching
    # ------------------------------------------------------------------

    def begin_change_batch(self) -> None:
        self._change_batch_depth += 1

    def end_change_batch(self) -> None:
        if self._change_batch_depth <= 0:
            raise RuntimeError("ChartModel change batch ended without a matching begin.")

        self._change_batch_depth -= 1
        if self._change_batch_depth == 0 and self._change_pending:
            self._change_pending = False
            self.changed.emit()

    @contextmanager
    def change_batch(self) -> Iterator["ChartModel"]:
        self.begin_change_batch()
        try:
            yield self
        finally:
            self.end_change_batch()

    def _emit_changed(self) -> None:
        if self._change_batch_depth > 0:
            self._change_pending = True
            return
        self.changed.emit()

    # ------------------------------------------------------------------
    # Base chart layer
    # ------------------------------------------------------------------

    @property
    def candles(self) -> List[Candle]:
        """
        Backward-compatible access to the canonical base OHLC layer.
        """
        return self._candles

    @property
    def base_price_bars(self) -> List[Candle]:
        """
        Canonical base OHLC chart layer.

        This is the solid chart foundation for both historical and real-time
        environments.
        """
        return self._candles

    @property
    def volume(self) -> List[float]:
        """
        Backward-compatible access to the auxiliary base volume layer.
        """
        return self._volume

    @property
    def base_volume(self) -> List[float]:
        """
        Auxiliary base volume layer.

        Volume is chart-local supporting data. It is not the canonical price
        foundation.
        """
        return self._volume

    @property
    def resident_base_index(self) -> int:
        return self._resident_base_index

    def has_base_price_layer(self) -> bool:
        return bool(self._candles)

    def set_resident_base_index(self, base_index: int) -> None:
        """
        Set the resident base offset for viewport/local-index alignment.

        This is a visualization concern only. It must not redefine the base
        chart truth.
        """
        base = max(0, int(base_index))
        if base == self._resident_base_index:
            return
        self._resident_base_index = base
        self._emit_changed()

    def global_to_local(self, global_index: int) -> Optional[int]:
        local = int(global_index) - self._resident_base_index
        if 0 <= local < len(self._candles):
            return local
        return None

    def local_to_global(self, local_index: int) -> int:
        return self._resident_base_index + int(local_index)

    def has_global_index(self, global_index: int) -> bool:
        return self.global_to_local(global_index) is not None

    def set_base_price_bars(self, candles: List[Candle]) -> None:
        """
        Replace the canonical base OHLC layer in place.

        This must preserve the list object so any bound render surface continues
        to observe the same list reference.
        """
        self._candles.clear()
        self._candles.extend(candles)
        self._emit_changed()

    def clear_base_price_bars(self) -> None:
        if not self._candles:
            return
        self._candles.clear()
        self._emit_changed()

    def set_candles(self, candles: List[Candle]) -> None:
        """
        Backward-compatible wrapper for setting the canonical base OHLC layer.
        """
        self.set_base_price_bars(candles)

    def set_base_volume(self, volume: List[float]) -> None:
        """
        Replace the auxiliary base volume layer in place.
        """
        self._volume.clear()
        self._volume.extend(volume)
        self._emit_changed()

    def clear_base_volume(self) -> None:
        if not self._volume:
            return
        self._volume.clear()
        self._emit_changed()

    def set_volume(self, volume: List[float]) -> None:
        """
        Backward-compatible wrapper for setting the auxiliary base volume layer.
        """
        self.set_base_volume(volume)

    def append_candle(self, candle: Candle, *, maxlen: int | None = None) -> None:
        """
        Append one OHLC bar to the canonical base layer.

        In real-time environments this extends the current chart-session base
        truth. If a resident max length is enforced, the resident base index is
        advanced accordingly so local/global alignment remains coherent.
        """
        self._candles.append(candle)
        self._volume.append(float(candle.volume))

        if maxlen is not None and len(self._candles) > maxlen:
            drop = len(self._candles) - maxlen
            del self._candles[:drop]
            del self._volume[:drop]
            self._resident_base_index += drop

        self._emit_changed()

    def update_last_candle(self, candle: Candle) -> None:
        """
        Replace the latest OHLC bar in the canonical base layer.
        """
        if not self._candles:
            self.append_candle(candle)
            return

        self._candles[-1] = candle

        if self._volume:
            self._volume[-1] = float(candle.volume)
        else:
            self._volume.append(float(candle.volume))

        self._emit_changed()

    # ------------------------------------------------------------------
    # Overlay studies (derived price-pane render state)
    # ------------------------------------------------------------------

    def set_overlay(self, series: Series) -> None:
        self._overlays[series.key] = series
        self._emit_changed()

    def remove_overlay(self, key: str) -> None:
        normalized_key = str(key).strip()
        if not normalized_key:
            return

        changed = False

        if self._overlays.pop(normalized_key, None) is not None:
            changed = True

        fill_ids_to_remove = [
            fill_id
            for fill_id, fill in self._overlay_fills.items()
            if fill.series_a == normalized_key or fill.series_b == normalized_key
        ]
        for fill_id in fill_ids_to_remove:
            self._overlay_fills.pop(fill_id, None)
            changed = True

        if changed:
            self._emit_changed()


    def overlay(self, key: str) -> Optional[Series]:
        """Return one overlay series by key."""
        return self._overlays.get(str(key).strip())

    def overlays_view(self) -> Mapping[str, Series]:
        """Return a read-only view of current overlay render state.

        This exposes the canonical model-owned mapping without allocating a hot-path
        copy for every pane/render query. Callers must treat the returned mapping
        as read-only.
        """
        return self._overlays

    def overlays(self) -> Dict[str, Series]:
        return dict(self._overlays)

    def set_overlay_fill(self, fill: OverlayFill) -> None:
        fill_id = str(fill.fill_id).strip()
        if not fill_id:
            raise ValueError("OverlayFill.fill_id must not be empty.")

        self._overlay_fills[fill_id] = fill
        self._emit_changed()

    def remove_overlay_fill(self, fill_id: str) -> None:
        normalized_fill_id = str(fill_id).strip()
        if not normalized_fill_id:
            return

        if self._overlay_fills.pop(normalized_fill_id, None) is not None:
            self._emit_changed()

    def clear_overlay_fills(self) -> None:
        if not self._overlay_fills:
            return
        self._overlay_fills.clear()
        self._emit_changed()

    def overlay_fill(self, fill_id: str) -> Optional[OverlayFill]:
        return self._overlay_fills.get(str(fill_id).strip())

    def overlay_fills_view(self) -> Mapping[str, OverlayFill]:
        """Return a read-only view of current overlay fill descriptors."""
        return self._overlay_fills

    def overlay_fills(self) -> List[OverlayFill]:
        return list(self._overlay_fills.values())

    # ------------------------------------------------------------------
    # Oscillator studies (derived auxiliary-pane render state)
    # ------------------------------------------------------------------

    def set_oscillator(self, series: Series) -> None:
        self._oscillators[series.key] = series
        self._emit_changed()

    def remove_oscillator(self, key: str) -> None:
        normalized_key = str(key).strip()
        if not normalized_key:
            return
        if self._oscillators.pop(normalized_key, None) is not None:
            self._emit_changed()

    def oscillator(self, key: str) -> Optional[Series]:
        return self._oscillators.get(str(key).strip())

    def oscillators_view(self) -> Mapping[str, Series]:
        """Return a read-only view of current oscillator render state."""
        return self._oscillators

    def oscillators(self) -> Dict[str, Series]:
        return dict(self._oscillators)

    # ------------------------------------------------------------------
    # Trades (auxiliary annotations)
    # ------------------------------------------------------------------

    def add_trade(self, t: TradeMarker) -> None:
        self._trades.append(t)
        self._emit_changed()

    def clear_trades(self) -> None:
        if self._trades:
            self._trades.clear()
            self._emit_changed()

    def trades(self) -> List[TradeMarker]:
        return list(self._trades)