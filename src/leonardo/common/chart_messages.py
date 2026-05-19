# leonardo/common/chart_messages.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Sequence

from leonardo.common.market_types import Candle


PatchOp = Literal["append", "update"]


@dataclass(frozen=True, slots=True)
class ChartSnapshot:
    symbol: str
    timeframe: str
    candles: Sequence[Candle]


@dataclass(frozen=True, slots=True)
class ChartPatch:
    symbol: str
    timeframe: str
    op: PatchOp
    candle: Candle
