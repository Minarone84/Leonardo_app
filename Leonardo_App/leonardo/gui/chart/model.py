from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

from PySide6.QtCore import QObject, Signal

from leonardo.gui.chart.dummy_data import Candle


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
    """
    changed = Signal()

    def __init__(self, candles: List[Candle], volume: List[float]) -> None:
        super().__init__()
        self._candles: List[Candle] = candles
        self._volume: List[float] = volume

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

    def set_candles(self, candles: List[Candle]) -> None:
        self._candles = candles
        self.changed.emit()

    def set_volume(self, volume: List[float]) -> None:
        self._volume = volume
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
