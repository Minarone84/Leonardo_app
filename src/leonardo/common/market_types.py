# leonardo/common/market_types.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Sequence

Timeframe = Literal[
    "1m", "3m", "5m", "15m", "30m",
    "1h", "2h", "4h", "6h", "12h",
    "1d", "1w",
]

BybitMarket = Literal["spot", "linear", "inverse", "option"]

@dataclass(frozen=True, slots=True)
class Candle:
    """
    Shared normalized OHLCV candle (no Qt deps).
    ts_ms: candle open time in UTC milliseconds since epoch.
    """
    ts_ms: int
    open: float
    high: float
    low: float
    close: float
    volume: float
    is_closed: bool = True


@dataclass(frozen=True, slots=True)
class ChartSnapshot:
    symbol: str
    timeframe: Timeframe
    candles: Sequence[Candle]


PatchOp = Literal["append", "update"]


@dataclass(frozen=True, slots=True)
class ChartPatch:
    symbol: str
    timeframe: Timeframe
    op: PatchOp
    candle: Candle