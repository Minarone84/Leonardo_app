from __future__ import annotations

import asyncio
import json
from typing import AsyncIterator, Optional, Sequence

import aiohttp
import websockets

from leonardo.common.market_types import BybitMarket, Candle, Timeframe
from leonardo.connection.exchange.base import BaseExchange


_BYBIT_REST_MAINNET = "https://api.bybit.com"
_BYBIT_REST_TESTNET = "https://api-testnet.bybit.com"

_BYBIT_WS_MAINNET = "wss://stream.bybit.com/v5/public"
_BYBIT_WS_TESTNET = "wss://stream-testnet.bybit.com/v5/public"


_TIMEFRAME_TO_BYBIT_INTERVAL: dict[Timeframe, str] = {
    "1m": "1",
    "3m": "3",
    "5m": "5",
    "15m": "15",
    "30m": "30",
    "1h": "60",
    "2h": "120",
    "4h": "240",
    "6h": "360",
    "12h": "720",
    "1d": "D",
    "1w": "W",
    # Bybit supports "M" too, but your Timeframe doesn't include it (fine).
}


class BybitExchange(BaseExchange):
    """
    Bybit V5 market data adapter.
    Market selection is via `market` (Bybit calls it `category`), e.g. spot/linear/inverse/option.
    """

    def __init__(self, *, testnet: bool = False) -> None:
        self._testnet = bool(testnet)
        self._session: Optional[aiohttp.ClientSession] = None

    @property
    def name(self) -> str:
        return "bybit"

    @property
    def _rest_base(self) -> str:
        return _BYBIT_REST_TESTNET if self._testnet else _BYBIT_REST_MAINNET

    @property
    def _ws_base(self) -> str:
        return _BYBIT_WS_TESTNET if self._testnet else _BYBIT_WS_MAINNET

    async def open(self) -> None:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()

    async def close(self) -> None:
        if self._session is not None and not self._session.closed:
            await self._session.close()

    async def get_metadata(self, *, market: str, force_refresh: bool = False) -> dict:
        # Phase 1: keep it minimal and cache later.
        m = self._normalize_market(market)
        return {
            "name": self.name,
            "market": m,
            "capabilities": {"rest_ohlcv": True, "websocket_ohlcv": True},
            "supported_timeframes": list(_TIMEFRAME_TO_BYBIT_INTERVAL.keys()),
        }

    async def fetch_ohlcv(
        self,
        *,
        market: str,
        symbol: str,
        timeframe: Timeframe,
        limit: int = 500,
        since_ms: Optional[int] = None,
    ) -> Sequence[Candle]:
        """
        GET /v5/market/kline
        - category defaults to linear if omitted (we always pass it)
        - list is sorted reverse by startTime
        """
        m = self._normalize_market(market)
        interval = _TIMEFRAME_TO_BYBIT_INTERVAL[timeframe]

        await self.open()
        assert self._session is not None

        params: dict[str, object] = {
            "category": m,
            "symbol": symbol.upper(),
            "interval": interval,
            "limit": int(limit),
        }
        if since_ms is not None:
            params["start"] = int(since_ms)

        url = f"{self._rest_base}/v5/market/kline"
        async with self._session.get(url, params=params) as resp:
            data = await resp.json()

        if data.get("retCode") != 0:
            raise RuntimeError(f"Bybit REST error: {data.get('retCode')} {data.get('retMsg')}")

        result = data.get("result") or {}
        rows = result.get("list") or []

        # rows are reverse sorted by startTime (newest first) -> we want chronological
        candles: list[Candle] = []
        for r in reversed(rows):
            # [startTime, open, high, low, close, volume, turnover]
            ts_ms = int(r[0])
            o = float(r[1])
            h = float(r[2])
            l = float(r[3])
            c = float(r[4])
            v = float(r[5])
            candles.append(Candle(ts_ms=ts_ms, open=o, high=h, low=l, close=c, volume=v, is_closed=True))

        return candles

    async def stream_ohlcv(
        self,
        *,
        market: str,
        symbol: str,
        timeframe: Timeframe,
    ) -> AsyncIterator[tuple[str, Candle]]:
        """
        Public WS kline stream:
          topic: kline.{interval}.{symbol}
          data[].confirm indicates candle closed or still updating
        """
        m = self._normalize_market(market)
        interval = _TIMEFRAME_TO_BYBIT_INTERVAL[timeframe]
        topic = f"kline.{interval}.{symbol.upper()}"
        ws_url = f"{self._ws_base}/{m}"

        sub_msg = {"op": "subscribe", "args": [topic]}
        ping_msg = {"op": "ping"}

        # Keep a small state so we emit "append" only when a candle closes
        last_closed_ts: Optional[int] = None

        try:
            async with websockets.connect(ws_url, ping_interval=None) as ws:
                await ws.send(json.dumps(sub_msg))

                async def _pinger() -> None:
                    while True:
                        await asyncio.sleep(20)
                        try:
                            await ws.send(json.dumps(ping_msg))
                        except Exception:
                            return

                pinger_task = asyncio.create_task(_pinger())

                try:
                    while True:
                        raw = await ws.recv()
                        msg = json.loads(raw)

                        # ignore subscribe acks / pongs etc
                        if isinstance(msg, dict) and msg.get("op") in ("pong", "subscribe"):
                            continue

                        if not isinstance(msg, dict):
                            continue

                        if msg.get("topic") != topic:
                            continue

                        data_arr = msg.get("data") or []
                        for item in data_arr:
                            # documented fields: start,end,interval,open,close,high,low,volume,turnover,confirm
                            ts_ms = int(item["start"])
                            candle = Candle(
                                ts_ms=ts_ms,
                                open=float(item["open"]),
                                high=float(item["high"]),
                                low=float(item["low"]),
                                close=float(item["close"]),
                                volume=float(item["volume"]),
                                is_closed=bool(item.get("confirm", False)),
                            )

                            if candle.is_closed:
                                # Candle closed -> append exactly once
                                if last_closed_ts != candle.ts_ms:
                                    last_closed_ts = candle.ts_ms
                                    yield ("append", candle)
                            else:
                                # Still forming -> update
                                yield ("update", candle)

                finally:
                    pinger_task.cancel()
        except asyncio.CancelledError:
            # Allow core to cancel streaming cleanly
            raise

    def _normalize_market(self, market: str) -> BybitMarket:
        m = market.strip().lower()
        if m not in ("spot", "linear", "inverse", "option"):
            raise ValueError(f"invalid bybit market={market!r} (expected spot|linear|inverse|option)")
        return m  # type: ignore[return-value]