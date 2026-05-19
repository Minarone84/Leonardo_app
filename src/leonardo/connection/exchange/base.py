from __future__ import annotations

import abc
from typing import AsyncIterator, Optional, Sequence, Set

from leonardo.common.market_types import Candle


class BaseExchange(abc.ABC):
    """
    Exchange adapter contract (async, GUI-free).

    Design constraints:
    - Do not break existing realtime chart feed (fetch_ohlcv/stream_ohlcv).
    - Add separate historical REST helpers for the historical downloader.
    - Option A naming policy is enforced at the boundary of fetch_ohlcv_historical():
        - market is a canonical string (spot|linear|inverse|options)
        - symbol is canonicalized (uppercase, separators removed, dot preserved)
        - timeframe is canonical string "<int><unit>" where unit in {m,h,d,w,M}
        - no auto conversion in naming layer
    """

    # -----------------------------
    # Identity / lifecycle
    # -----------------------------

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

    def supported_markets(self) -> Set[str]:
        """
        Optional convenience for GUI and validation layers.
        Default: unknown (empty set).
        Typical: {"spot", "linear", "inverse", "options"} (subset).
        """
        return set()

    # -----------------------------
    # Existing contract (keep as-is)
    # -----------------------------

    @abc.abstractmethod
    async def fetch_ohlcv(
        self,
        *,
        market: str,
        symbol: str,
        timeframe: str,
        limit: int = 500,
        since_ms: Optional[int] = None,
    ) -> Sequence[Candle]:
        """
        Existing REST OHLCV fetch used by the realtime chart bootstrap path.

        - timeframe is a canonical exchange-specific string
        - since_ms is the start bound
        - returns candles typically sorted by timestamp ascending (recommended)
        """
        raise NotImplementedError

    @abc.abstractmethod
    async def stream_ohlcv(
        self,
        *,
        market: str,
        symbol: str,
        timeframe: str,
    ) -> AsyncIterator[tuple[str, Candle]]:
        """
        Yields (op, candle) where op is "update" or "append".

        - "append": a new candle was added (next timestamp)
        - "update": the latest candle was updated (same timestamp)
        """
        raise NotImplementedError

    # -----------------------------------------
    # New historical contract (Option A boundary)
    # -----------------------------------------

    def supported_timeframes(self, market: str) -> Set[str]:
        """
        Return canonical Option A timeframes supported by this exchange adapter for a given market.

        Canonical timeframe format (Option A):
          - "<int><unit>" where unit in {m,h,d,w,M}
          - no auto-conversion (60m stays "60m" unless the adapter chooses otherwise)

        Default: unknown (empty set). Adapters should override when possible.
        """
        return set()

    def max_historical_ohlcv_limit(self, market: str) -> Optional[int]:
        """
        Return the adapter's maximum candle count for one historical OHLCV REST page.

        Default: unknown. Historical downloaders may keep their own conservative
        default when an adapter does not publish a venue-specific limit.
        """
        _ = market
        return None

    async def oldest_historical_ohlcv_ts_ms(
        self,
        *,
        market: str,
        symbol: str,
        timeframe: str,
        limit: Optional[int] = None,
    ) -> Optional[int]:
        """
        Return the oldest known historical OHLCV candle open timestamp in ms.

        This optional capability lets Core build a determinate full-history
        download plan before writing data. Adapters that cannot discover the
        venue's oldest candle should leave the default unsupported path intact.
        """
        _ = (market, symbol, timeframe, limit)
        raise NotImplementedError(
            f"{self.__class__.__name__}.oldest_historical_ohlcv_ts_ms not implemented"
        )

    async def fetch_ohlcv_historical(
        self,
        *,
        market: str,
        symbol: str,
        timeframe: str,
        start_ms: Optional[int] = None,
        end_ms: Optional[int] = None,
        limit: Optional[int] = None,
    ) -> Sequence[Candle]:
        """
        Fetch historical OHLCV via REST for the historical downloader.

        This method is intentionally NOT abstract, to avoid breaking existing adapters.
        Adapters that support historical downloading should override it.

        Inputs (expected canonicalized by caller, Option A):
          - market: "spot" | "linear" | "inverse" | "options"
          - symbol: uppercase, separators removed, dot preserved
          - timeframe: "<int><unit>" (m/h/d/w), no auto conversion
          - start_ms/end_ms: ms epoch UTC (open time bounds; end optional best-effort)
          - limit: optional; adapter clamps to venue max

        Output contract:
          - Sequence[Candle] sorted ascending by candle open timestamp (ms)
          - Candle must expose candle open timestamp as `ts_ms` (recommended invariant)
          - Overlaps are acceptable; caller will dedupe by ts_ms
        """
        raise NotImplementedError(
            f"{self.__class__.__name__}.fetch_ohlcv_historical not implemented"
        )