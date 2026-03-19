from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class OHLCVCandle:
    """
    Canonical OHLCV candle used across exchange adapters.

    - ts_ms: candle open timestamp (ms epoch UTC)
    - open/high/low/close/volume: floats
    """
    ts_ms: int
    open: float
    high: float
    low: float
    close: float
    volume: float