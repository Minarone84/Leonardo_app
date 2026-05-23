# leonardo/connection/exchange/adapters/bybit.py
from __future__ import annotations

import asyncio
import json
import time
from typing import Any, AsyncIterator, Literal, Mapping, Optional, Sequence, Set

import aiohttp
import websockets

from leonardo.common.market_types import Candle
from leonardo.connection.exchange.base import BaseExchange

BybitMarket = Literal["spot", "linear", "inverse", "option"]

Bybit_Timeframe = Literal[
    "1m", "3m", "5m", "15m", "30m",
    "1h", "2h", "4h", "6h", "12h",
    "1d", "1w", "1M",
]

BYBIT_MARKETS: tuple[BybitMarket, ...] = ("spot", "linear", "inverse", "option")
BYBIT_CANONICAL_MARKETS: tuple[str, ...] = ("spot", "linear", "inverse", "options")
BYBIT_MARKET_ALIASES: dict[str, BybitMarket] = {"options": "option"}

BYBIT_TIMEFRAMES: tuple[Bybit_Timeframe, ...] = (
    "1m", "3m", "5m", "15m", "30m",
    "1h", "2h", "4h", "6h", "12h",
    "1d", "1w", "1M",
)

BYBIT_TIMEFRAME_ALIASES: dict[str, Bybit_Timeframe] = {
    "60m": "1h",
}

_BYBIT_REST_MAINNET = "https://api.bybit.com"
_BYBIT_REST_TESTNET = "https://api-testnet.bybit.com"

_BYBIT_WS_MAINNET = "wss://stream.bybit.com/v5/public"
_BYBIT_WS_TESTNET = "wss://stream-testnet.bybit.com/v5/public"

_BYBIT_MAX_KLINE_LIMIT = 1000
_BYBIT_MONTH_DISCOVERY_STEP_MS = 31 * 86_400_000
_BYBIT_RATE_LIMIT_RETCODE = 10006
_BYBIT_REST_MAX_ATTEMPTS = 4
_BYBIT_REST_MIN_INTERVAL_SECONDS = 0.20
_BYBIT_REST_RATE_LIMIT_FALLBACK_SLEEP_SECONDS = 1.0
_BYBIT_REST_MAX_RATE_LIMIT_SLEEP_SECONDS = 10.0
_BYBIT_REST_RESET_CUSHION_SECONDS = 0.05

_TIMEFRAME_TO_BYBIT_INTERVAL: dict[Bybit_Timeframe, str] = {
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

_BYBIT_OPTIONA_TO_TIMEFRAME: dict[str, Bybit_Timeframe] = {
    **{timeframe: timeframe for timeframe in BYBIT_TIMEFRAMES},
    **BYBIT_TIMEFRAME_ALIASES,
}


class BybitExchange(BaseExchange):
    def __init__(self, *, testnet: bool = False) -> None:
        self._testnet = bool(testnet)
        self._session: Optional[aiohttp.ClientSession] = None
        self._rest_lock = asyncio.Lock()
        self._next_rest_request_at = 0.0

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

    async def _public_get_json(
        self,
        path: str,
        *,
        params: Optional[Mapping[str, object]] = None,
    ) -> dict[str, Any]:
        await self.open()
        assert self._session is not None

        url = f"{self._rest_base}{path}"
        last_rate_limit: tuple[int, str] | None = None

        async with self._rest_lock:
            for attempt in range(1, _BYBIT_REST_MAX_ATTEMPTS + 1):
                await self._pace_rest_request_locked()

                async with self._session.get(url, params=dict(params or {})) as resp:
                    status = int(getattr(resp, "status", 200) or 200)
                    headers = getattr(resp, "headers", {}) or {}
                    try:
                        data = await resp.json()
                    except Exception as e:
                        if status == 429:
                            data = {}
                        else:
                            raise RuntimeError(f"Bybit REST response JSON decode failed for {path}: {e}") from e

                if not isinstance(data, dict):
                    raise RuntimeError(f"Bybit REST response was not a JSON object for {path}: {data!r}")

                if self._is_rate_limit_response(status, data):
                    last_rate_limit = (status, str(data.get("retMsg") or "rate limit"))
                    if attempt >= _BYBIT_REST_MAX_ATTEMPTS:
                        break
                    await asyncio.sleep(self._rate_limit_sleep_seconds(headers, attempt=attempt))
                    continue

                self._update_pacing_from_headers(headers)
                ret_code = self._ret_code(data)
                if status >= 400:
                    raise RuntimeError(f"Bybit HTTP error: {status} {data!r}")
                if ret_code not in (None, 0):
                    raise RuntimeError(f"Bybit REST error: {data.get('retCode')} {data.get('retMsg')}")
                return data

        status, message = last_rate_limit or (0, "rate limit")
        raise RuntimeError(
            f"Bybit REST rate limit exceeded after {_BYBIT_REST_MAX_ATTEMPTS} attempts: {status} {message}"
        )

    async def _pace_rest_request_locked(self) -> None:
        now = time.monotonic()
        delay = self._next_rest_request_at - now
        if delay > 0:
            await asyncio.sleep(delay)
        self._next_rest_request_at = time.monotonic() + _BYBIT_REST_MIN_INTERVAL_SECONDS

    def _update_pacing_from_headers(self, headers: object) -> None:
        remaining = self._header_int(headers, "X-Bapi-Limit-Status")
        if remaining is None or remaining > 0:
            return

        reset_delay = self._rate_limit_reset_delay_seconds(headers)
        if reset_delay is not None:
            self._next_rest_request_at = max(
                self._next_rest_request_at,
                time.monotonic() + reset_delay,
            )

    def _rate_limit_sleep_seconds(self, headers: object, *, attempt: int) -> float:
        reset_delay = self._rate_limit_reset_delay_seconds(headers)
        if reset_delay is not None:
            return reset_delay
        return min(
            _BYBIT_REST_RATE_LIMIT_FALLBACK_SLEEP_SECONDS * max(1, int(attempt)),
            _BYBIT_REST_MAX_RATE_LIMIT_SLEEP_SECONDS,
        )

    def _rate_limit_reset_delay_seconds(self, headers: object) -> Optional[float]:
        reset_ms = self._header_int(headers, "X-Bapi-Limit-Reset-Timestamp")
        if reset_ms is None:
            return None
        delay = (reset_ms / 1000.0) - time.time() + _BYBIT_REST_RESET_CUSHION_SECONDS
        if delay <= 0:
            return None
        return min(delay, _BYBIT_REST_MAX_RATE_LIMIT_SLEEP_SECONDS)

    @staticmethod
    def _is_rate_limit_response(status: int, data: Mapping[str, Any]) -> bool:
        return int(status) == 429 or BybitExchange._ret_code(data) == _BYBIT_RATE_LIMIT_RETCODE

    @staticmethod
    def _ret_code(data: Mapping[str, Any]) -> Optional[int]:
        value = data.get("retCode")
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _header_int(headers: object, name: str) -> Optional[int]:
        raw = BybitExchange._header_value(headers, name)
        if raw is None:
            return None
        try:
            return int(str(raw))
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _header_value(headers: object, name: str) -> Optional[object]:
        getter = getattr(headers, "get", None)
        if callable(getter):
            value = getter(name)
            if value is not None:
                return value

        items = getattr(headers, "items", None)
        if callable(items):
            wanted = name.lower()
            for key, value in items():
                if str(key).lower() == wanted:
                    return value
        return None

    async def get_server_time_ms(self) -> int:
        """
        GET /v5/market/time
        Returns server time in ms.
        """
        data = await self._public_get_json("/v5/market/time")
        # Typical shape: {"retCode":0,...,"result":{},"time":1672025956592}
        t = data.get("time")
        if t is None:
            raise RuntimeError(f"Bybit server time missing in response: {data!r}")
        return int(t)

    def supported_markets(self) -> Set[str]:
        return {str(market) for market in BYBIT_CANONICAL_MARKETS}

    def supported_timeframes(self, market: str) -> Set[str]:
        _ = self._normalize_market(market)
        return {str(timeframe) for timeframe in BYBIT_TIMEFRAMES}

    def max_historical_ohlcv_limit(self, market: str) -> Optional[int]:
        _ = self._normalize_market(market)
        return _BYBIT_MAX_KLINE_LIMIT

    async def get_metadata(self, *, market: str, force_refresh: bool = False) -> dict:
        m = self._normalize_market(market)
        return {
            "name": self.name,
            "market": m,
            "capabilities": {"rest_ohlcv": True, "websocket_ohlcv": True, "rest_historical": True},
            "supported_markets": list(BYBIT_CANONICAL_MARKETS),
            "supported_timeframes": list(BYBIT_TIMEFRAMES),
            "max_historical_ohlcv_limit": _BYBIT_MAX_KLINE_LIMIT,
        }

    async def fetch_ohlcv(
        self,
        *,
        market: str,
        symbol: str,
        timeframe: Bybit_Timeframe,
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
        timeframe: Bybit_Timeframe,
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

    async def oldest_historical_ohlcv_ts_ms(
        self,
        *,
        market: str,
        symbol: str,
        timeframe: str,
        limit: Optional[int] = None,
    ) -> Optional[int]:
        """
        Discover the oldest available Bybit OHLCV candle for this market.

        Bybit's kline endpoint does not expose a direct "oldest candle" field,
        so this uses bounded existence probes over [0, server_time] and then
        fetches the smallest discovered window to return the actual candle
        timestamp. This is read-only and does not write downloader state.
        """
        m = self._normalize_market(market)
        tf_obj = self._normalize_timeframe(timeframe)

        step_ms = self._tf_duration_ms(tf_obj)
        if step_ms is None:
            # Month candles are variable length. Use a conservative probe step
            # only for discovery-window narrowing; the final timestamp still
            # comes from the exchange candle open time.
            step_ms = _BYBIT_MONTH_DISCOVERY_STEP_MS

        server_time_ms = await self.get_server_time_ms()
        if server_time_ms <= 0:
            return None

        async def _has_candle_through(end_ms: int) -> bool:
            candles = await self.fetch_ohlcv_historical(
                market=m,
                symbol=symbol,
                timeframe=tf_obj,
                start_ms=0,
                end_ms=max(0, int(end_ms)),
                limit=1,
            )
            return bool(candles)

        if not await _has_candle_through(server_time_ms):
            return None

        low = 0
        high = int(server_time_ms)
        while high - low > step_ms:
            mid = low + ((high - low) // 2)
            if await _has_candle_through(mid):
                high = mid
            else:
                low = mid + 1

        final_start = max(0, high - step_ms)
        final_end = min(int(server_time_ms), high + step_ms)
        final_limit = self.max_historical_ohlcv_limit(m) or _BYBIT_MAX_KLINE_LIMIT
        if limit is not None:
            requested_limit = max(1, int(limit))
            final_limit = min(final_limit, requested_limit)

        candles = await self.fetch_ohlcv_historical(
            market=m,
            symbol=symbol,
            timeframe=tf_obj,
            start_ms=final_start,
            end_ms=final_end,
            limit=final_limit,
        )
        if not candles:
            return None
        return min(candle.ts_ms for candle in candles)

    def _normalize_timeframe(self, timeframe: str) -> Bybit_Timeframe:
        tf_in = (timeframe or "").strip()
        if not tf_in:
            raise ValueError("timeframe required")

        # Keep "1M" distinct from "1m".
        tf_key = "1M" if tf_in == "1M" else tf_in.lower()

        tf_obj = _BYBIT_OPTIONA_TO_TIMEFRAME.get(tf_key)
        if tf_obj is None:
            supported = self.supported_timeframes("linear")
            raise ValueError(f"invalid bybit timeframe={timeframe!r} (supported: {sorted(supported)})")
        return tf_obj

    def _tf_duration_ms(self, tf: Bybit_Timeframe) -> Optional[int]:
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

        tf_obj = self._normalize_timeframe(timeframe)
        interval = _TIMEFRAME_TO_BYBIT_INTERVAL[tf_obj]

        lim = int(limit) if limit is not None else 200
        if lim < 1:
            lim = 1
        if lim > _BYBIT_MAX_KLINE_LIMIT:
            lim = _BYBIT_MAX_KLINE_LIMIT

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

        data = await self._public_get_json("/v5/market/kline", params=params)
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
        m = BYBIT_MARKET_ALIASES.get(m, m)
        if m not in BYBIT_MARKETS:
            raise ValueError(f"invalid bybit market={market!r} (expected spot|linear|inverse|options)")
        return m  # type: ignore[return-value]
