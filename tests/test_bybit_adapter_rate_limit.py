from __future__ import annotations

import asyncio
import sys
import time
import types
from typing import Any

import pytest

sys.modules.setdefault("websockets", types.SimpleNamespace(connect=None))

from leonardo.connection.exchange.adapters import bybit
from leonardo.connection.exchange.adapters.bybit import BybitExchange


class _FakeResponse:
    def __init__(
        self,
        payload: dict[str, Any],
        *,
        status: int = 200,
        headers: dict[str, object] | None = None,
    ) -> None:
        self._payload = payload
        self.status = status
        self.headers = headers or {}

    async def __aenter__(self) -> "_FakeResponse":
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        return None

    async def json(self) -> dict[str, Any]:
        return self._payload


class _FakeSession:
    closed = False

    def __init__(self, responses: list[_FakeResponse]) -> None:
        self._responses = list(responses)
        self.requests: list[tuple[str, dict[str, object]]] = []

    def get(self, url: str, *, params: dict[str, object] | None = None) -> _FakeResponse:
        self.requests.append((url, dict(params or {})))
        if not self._responses:
            raise AssertionError("unexpected Bybit REST request")
        return self._responses.pop(0)


def _exchange_with_session(responses: list[_FakeResponse]) -> tuple[BybitExchange, _FakeSession]:
    exchange = BybitExchange()
    session = _FakeSession(responses)
    exchange._session = session
    return exchange, session


def test_bybit_public_rest_success_returns_server_time(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(bybit, "_BYBIT_REST_MIN_INTERVAL_SECONDS", 0.0)
    exchange, session = _exchange_with_session([
        _FakeResponse({"retCode": 0, "retMsg": "OK", "time": 1234567890})
    ])

    result = asyncio.run(exchange.get_server_time_ms())

    assert result == 1234567890
    assert session.requests == [("https://api.bybit.com/v5/market/time", {})]


def test_bybit_retcode_10006_retries_with_reset_header(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(bybit, "_BYBIT_REST_MIN_INTERVAL_SECONDS", 0.0)
    sleeps: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    monkeypatch.setattr(bybit.asyncio, "sleep", fake_sleep)
    reset_ms = int(time.time() * 1000) + 250
    exchange, session = _exchange_with_session([
        _FakeResponse(
            {"retCode": 10006, "retMsg": "Too many visits. Exceeded the API Rate Limit."},
            headers={"X-Bapi-Limit-Reset-Timestamp": str(reset_ms)},
        ),
        _FakeResponse({"retCode": 0, "retMsg": "OK", "time": 1000, "result": {"list": []}}),
    ])

    result = asyncio.run(
        exchange.fetch_ohlcv_historical(
            market="linear",
            symbol="BTCUSDT",
            timeframe="1m",
            limit=1,
        )
    )

    assert result == []
    assert len(session.requests) == 2
    assert sleeps
    assert sleeps[0] > 0


def test_bybit_http_429_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(bybit, "_BYBIT_REST_MIN_INTERVAL_SECONDS", 0.0)
    sleeps: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    monkeypatch.setattr(bybit.asyncio, "sleep", fake_sleep)
    exchange, session = _exchange_with_session([
        _FakeResponse({"retCode": 0, "retMsg": "OK"}, status=429),
        _FakeResponse({"retCode": 0, "retMsg": "OK", "time": 2222}),
    ])

    result = asyncio.run(exchange.get_server_time_ms())

    assert result == 2222
    assert len(session.requests) == 2
    assert sleeps == [bybit._BYBIT_REST_RATE_LIMIT_FALLBACK_SLEEP_SECONDS]


def test_bybit_rate_limit_retries_are_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(bybit, "_BYBIT_REST_MIN_INTERVAL_SECONDS", 0.0)
    monkeypatch.setattr(bybit, "_BYBIT_REST_MAX_ATTEMPTS", 3)

    async def fake_sleep(delay: float) -> None:
        _ = delay

    monkeypatch.setattr(bybit.asyncio, "sleep", fake_sleep)
    exchange, session = _exchange_with_session([
        _FakeResponse({"retCode": 10006, "retMsg": "Too many visits."}),
        _FakeResponse({"retCode": 10006, "retMsg": "Too many visits."}),
        _FakeResponse({"retCode": 10006, "retMsg": "Too many visits."}),
    ])

    with pytest.raises(RuntimeError, match="rate limit exceeded after 3 attempts"):
        asyncio.run(exchange.get_server_time_ms())

    assert len(session.requests) == 3


def test_bybit_adapter_paces_successive_public_rest_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(bybit, "_BYBIT_REST_MIN_INTERVAL_SECONDS", 0.5)
    clock = {"now": 100.0}
    sleeps: list[float] = []

    def fake_monotonic() -> float:
        return clock["now"]

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)
        clock["now"] += delay

    monkeypatch.setattr(bybit.time, "monotonic", fake_monotonic)
    monkeypatch.setattr(bybit.asyncio, "sleep", fake_sleep)
    exchange, _session = _exchange_with_session([
        _FakeResponse({"retCode": 0, "retMsg": "OK", "time": 1}),
        _FakeResponse({"retCode": 0, "retMsg": "OK", "time": 2}),
    ])

    async def scenario() -> None:
        assert await exchange.get_server_time_ms() == 1
        assert await exchange.get_server_time_ms() == 2

    asyncio.run(scenario())

    assert sleeps == [0.5]
