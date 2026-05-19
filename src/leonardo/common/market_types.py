# leonardo/common/market_types.py
from __future__ import annotations

from dataclasses import dataclass


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
