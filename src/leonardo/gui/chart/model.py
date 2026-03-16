from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

from PySide6.QtCore import QObject, Signal

from leonardo.common.market_types import Candle


@dataclass(frozen=True)
class Series:
    key: str
    title: str
    values: List[float]


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
    Holds all series needed for rendering: price, volume, overlays, oscillators, trades.

    IMPORTANT:
    - Render surfaces may hold references to `candles` and `volume` lists.
      Therefore `set_candles`/`set_volume` must mutate lists IN PLACE (not rebind).
    """
    changed = Signal()

    def __init__(self, candles: List[Candle], volume: List[float]) -> None:
        super().__init__()
        self._candles: List[Candle] = candles
        self._volume: List[float] = volume

        self._resident_base_index: int = 0

        self._overlays: Dict[str, Series] = {}     # indicators drawn on price pane
        self._oscillators: Dict[str, Series] = {}  # panes below
        self._trades: List[TradeMarker] = []

    # ---- base series ----

    @property
    def candles(self) -> List[Candle]:
        return self._candles

    @property
    def volume(self) -> List[float]:
        return self._volume

    @property
    def resident_base_index(self) -> int:
        return self._resident_base_index

    def set_resident_base_index(self, base_index: int) -> None:
        base = max(0, int(base_index))
        if base == self._resident_base_index:
            return
        self._resident_base_index = base
        self.changed.emit()

    def global_to_local(self, global_index: int) -> Optional[int]:
        local = int(global_index) - self._resident_base_index
        if 0 <= local < len(self._candles):
            return local
        return None

    def local_to_global(self, local_index: int) -> int:
        return self._resident_base_index + int(local_index)

    def has_global_index(self, global_index: int) -> bool:
        return self.global_to_local(global_index) is not None

    def set_candles(self, candles: List[Candle]) -> None:
        # In-place update so any widget holding a reference keeps working.
        self._candles.clear()
        self._candles.extend(candles)
        self.changed.emit()

    def set_volume(self, volume: List[float]) -> None:
        # In-place update so any widget holding a reference keeps working.
        self._volume.clear()
        self._volume.extend(volume)
        self.changed.emit()

    def append_candle(self, candle: Candle, *, maxlen: int | None = None) -> None:
        self._candles.append(candle)
        self._volume.append(float(candle.volume))

        if maxlen is not None and len(self._candles) > maxlen:
            drop = len(self._candles) - maxlen
            del self._candles[:drop]
            del self._volume[:drop]
            self._resident_base_index += drop

        self.changed.emit()

    def update_last_candle(self, candle: Candle) -> None:
        if not self._candles:
            self.append_candle(candle)
            return

        self._candles[-1] = candle

        if self._volume:
            self._volume[-1] = float(candle.volume)
        else:
            self._volume.append(float(candle.volume))

        self.changed.emit()

    # ---- overlays (price indicators) ----

    def set_overlay(self, series: Series) -> None:
        self._overlays[series.key] = series
        self.changed.emit()

    def remove_overlay(self, key: str) -> None:
        if self._overlays.pop(key, None) is not None:
            self.changed.emit()

    def overlays(self) -> Dict[str, Series]:
        return dict(self._overlays)

    # ---- oscillators ----

    def set_oscillator(self, series: Series) -> None:
        self._oscillators[series.key] = series
        self.changed.emit()

    def remove_oscillator(self, key: str) -> None:
        if self._oscillators.pop(key, None) is not None:
            self.changed.emit()

    def oscillator(self, key: str) -> Optional[Series]:
        return self._oscillators.get(key)

    def oscillators(self) -> Dict[str, Series]:
        return dict(self._oscillators)

    # ---- trades (stub) ----

    def add_trade(self, t: TradeMarker) -> None:
        self._trades.append(t)
        self.changed.emit()

    def clear_trades(self) -> None:
        if self._trades:
            self._trades.clear()
            self.changed.emit()

    def trades(self) -> List[TradeMarker]:
        return list(self._trades)