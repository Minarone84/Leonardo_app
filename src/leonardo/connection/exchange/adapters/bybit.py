# leonardo/connection/exchange/adapters/bybit.py
from __future__ import annotations

import asyncio
import json
from typing import AsyncIterator, Optional, Sequence, Set

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
    "1M": "M",
}

_BYBIT_OPTIONA_TO_TIMEFRAME: dict[str, Timeframe] = {
    "1m": "1m",
    "3m": "3m",
    "5m": "5m",
    "15m": "15m",
    "30m": "30m",
    "60m": "1h",
    "1h": "1h",
    "2h": "2h",
    "4h": "4h",
    "6h": "6h",
    "12h": "12h",
    "1d": "1d",
    "1w": "1w",
    "1M": "1M",
    "1m".upper(): "1m",
    "1h".upper(): "1h",
    "1d".upper(): "1d",
    "1w".upper(): "1w",
    "1M".upper(): "1M",
}


class BybitExchange(BaseExchange):
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
            timeout = aiohttp.ClientTimeout(total=20)
            self._session = aiohttp.ClientSession(timeout=timeout)

    async def close(self) -> None:
        if self._session is not None and not self._session.closed:
            await self._session.close()

    async def get_server_time_ms(self) -> int:
        """
        GET /v5/market/time
        Returns server time in ms.
        """
        await self.open()
        assert self._session is not None

        url = f"{self._rest_base}/v5/market/time"
        async with self._session.get(url) as resp:
            data = await resp.json()

        # Typical shape: {"retCode":0,...,"result":{},"time":1672025956592}
        t = data.get("time")
        if t is None:
            raise RuntimeError(f"Bybit server time missing in response: {data!r}")
        return int(t)

    def supported_timeframes(self, market: str) -> Set[str]:
        _ = self._normalize_market(market)
        out: set[str] = {str(tf) for tf in _TIMEFRAME_TO_BYBIT_INTERVAL.keys()}
        out.add("60m")
        return out

    async def get_metadata(self, *, market: str, force_refresh: bool = False) -> dict:
        m = self._normalize_market(market)
        return {
            "name": self.name,
            "market": m,
            "capabilities": {"rest_ohlcv": True, "websocket_ohlcv": True, "rest_historical": True},
            "supported_timeframes": sorted(self.supported_timeframes(m)),
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
        Required by BaseExchange.

        For now, delegate to fetch_ohlcv_historical(), since it's the same REST endpoint.
        """
        return await self.fetch_ohlcv_historical(
            market=market,
            symbol=symbol,
            timeframe=timeframe,
            start_ms=since_ms,
            end_ms=None,
            limit=limit,
        )

    async def stream_ohlcv(
        self,
        *,
        market: str,
        symbol: str,
        timeframe: Timeframe,
    ) -> AsyncIterator[tuple[str, Candle]]:
        """
        Required by BaseExchange.

        Bybit v5 public WS kline stream:
          topic: kline.{interval}.{symbol}
          data[].confirm indicates candle closed (True) or still updating (False).
        """
        m = self._normalize_market(market)
        interval = _TIMEFRAME_TO_BYBIT_INTERVAL[timeframe]
        topic = f"kline.{interval}.{symbol.upper()}"
        ws_url = f"{self._ws_base}/{m}"

        sub_msg = {"op": "subscribe", "args": [topic]}
        ping_msg = {"op": "ping"}

        last_closed_ts: Optional[int] = None

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
                            if last_closed_ts != candle.ts_ms:
                                last_closed_ts = candle.ts_ms
                                yield ("append", candle)
                        else:
                            yield ("update", candle)
            finally:
                pinger_task.cancel()
                
    def _tf_duration_ms(self, tf: Timeframe) -> Optional[int]:
        # Month is variable; we do not try to compute it here
        if tf == "1M":
            return None
        if tf.endswith("m"):
            return int(tf[:-1]) * 60_000
        if tf.endswith("h"):
            return int(tf[:-1]) * 3_600_000
        if tf.endswith("d"):
            return int(tf[:-1]) * 86_400_000
        if tf.endswith("w"):
            return int(tf[:-1]) * 7 * 86_400_000
        return None

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
        GET /v5/market/kline with paging controls.

        Docs:
        - category defaults to linear if omitted (we always pass it)
        - list is reverse-sorted by startTime
        - closePrice is last traded price when candle not closed
        """
        m = self._normalize_market(market)

        tf_in = (timeframe or "").strip()
        if not tf_in:
            raise ValueError("timeframe required")

        # Keep "1M" distinct from "1m"
        tf_key = "1M" if tf_in == "1M" else tf_in.lower()

        supported = self.supported_timeframes(m)
        if supported and tf_key not in supported:
            raise ValueError(f"invalid bybit timeframe={timeframe!r} (supported: {sorted(supported)})")

        tf_obj = _BYBIT_OPTIONA_TO_TIMEFRAME.get(tf_key)
        if tf_obj is None:
            raise ValueError(f"cannot map timeframe {timeframe!r} to internal Timeframe for Bybit")

        interval = _TIMEFRAME_TO_BYBIT_INTERVAL[tf_obj]

        lim = int(limit) if limit is not None else 200
        if lim < 1:
            lim = 1
        if lim > 1000:
            lim = 1000

        await self.open()
        assert self._session is not None

        params: dict[str, object] = {
            "category": m,
            "symbol": symbol.upper(),
            "interval": interval,
            "limit": lim,
        }
        if start_ms is not None:
            params["start"] = int(start_ms)
        if end_ms is not None:
            params["end"] = int(end_ms)

        url = f"{self._rest_base}/v5/market/kline"
        async with self._session.get(url, params=params) as resp:
            data = await resp.json()

        if data.get("retCode") != 0:
            raise RuntimeError(f"Bybit REST error: {data.get('retCode')} {data.get('retMsg')}")

        result = data.get("result") or {}
        rows = result.get("list") or []

        # rows are reverse sorted by startTime (newest first) -> convert to chronological
        candles: list[Candle] = []
        for r in reversed(rows):
            ts_ms = int(r[0])
            o = float(r[1])
            h = float(r[2])
            l = float(r[3])
            c = float(r[4])
            v = float(r[5])
            candles.append(Candle(ts_ms=ts_ms, open=o, high=h, low=l, close=c, volume=v, is_closed=True))

        candles.sort(key=lambda c: c.ts_ms)

        # Best-effort detect "still forming" newest candle using server time included in response
        server_time_ms = int(data.get("time") or 0)
        dur_ms = self._tf_duration_ms(tf_obj)
        if server_time_ms and dur_ms and candles:
            newest = candles[-1]
            # If candle end > server time, it's still forming
            if newest.ts_ms + dur_ms > server_time_ms:
                candles[-1] = Candle(
                    ts_ms=newest.ts_ms,
                    open=newest.open,
                    high=newest.high,
                    low=newest.low,
                    close=newest.close,
                    volume=newest.volume,
                    is_closed=False,
                )

        # Keep end_ms as an extra defensive filter (Bybit behavior is consistent, but no harm)
        if end_ms is not None:
            candles = [c for c in candles if c.ts_ms <= end_ms]

        return candles

    # stream_ohlcv unchanged ...

    def _normalize_market(self, market: str) -> BybitMarket:
        m = market.strip().lower()
        if m not in ("spot", "linear", "inverse", "option"):
            raise ValueError(f"invalid bybit market={market!r} (expected spot|linear|inverse|option)")
        return m  # type: ignore[return-value]