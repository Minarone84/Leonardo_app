from __future__ import annotations

import abc
from typing import AsyncIterator, Optional, Sequence

from leonardo.common.market_types import Candle, Timeframe


class BaseExchange(abc.ABC):
    """
    Exchange adapter contract (async, GUI-free).
    """

    @property
    @abc.abstractmethod
    def name(self) -> str: ...

    async def open(self) -> None:
        return None

    async def close(self) -> None:
        return None

    @abc.abstractmethod
    async def get_metadata(self, *, market: str, force_refresh: bool = False) -> dict:
        raise NotImplementedError

    @abc.abstractmethod
    async def fetch_ohlcv(
        self,
        *,
        market: str,
        symbol: str,
        timeframe: Timeframe,
        limit: int = 500,
        since_ms: Optional[int] = None,
    ) -> Sequence[Candle]:
        raise NotImplementedError

    @abc.abstractmethod
    async def stream_ohlcv(
        self,
        *,
        market: str,
        symbol: str,
        timeframe: Timeframe,
    ) -> AsyncIterator[tuple[str, Candle]]:
        """
        Yields (op, candle) where op is "update" or "append".
        """
        raise NotImplementedError