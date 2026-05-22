from __future__ import annotations

import asyncio
import sys
import types

import pytest

from leonardo.common.market_types import Candle
from leonardo.core.audit import InMemoryAuditSink
from leonardo.core.registry_keys import SVC_HISTORICAL_DATASET
from leonardo.data.historical.dataset_service import DatasetId, HistoricalDatasetService

bybit_module = types.ModuleType("leonardo.connection.exchange.adapters.bybit")


class _BybitExchange:
    pass


bybit_module.BybitExchange = _BybitExchange
sys.modules.setdefault("leonardo.connection.exchange.adapters.bybit", bybit_module)

from leonardo.data.historical.downloader import DownloadRequest, HistoricalDownloader


class _DatasetServiceProbe:
    def __init__(self) -> None:
        self.invalidated: list[DatasetId] = []

    def invalidate_dataset_cache(self, dataset_id: DatasetId) -> bool:
        self.invalidated.append(dataset_id)
        return True


class _Context:
    def __init__(self, dataset_service: _DatasetServiceProbe) -> None:
        self.audit = InMemoryAuditSink()
        self.dataset_service = dataset_service

    def get_service(self, name: str, t: type[HistoricalDatasetService]) -> _DatasetServiceProbe:
        assert name == SVC_HISTORICAL_DATASET
        assert t is HistoricalDatasetService
        return self.dataset_service


class _FakeExchange:
    def __init__(self, batches: list[list[Candle]]) -> None:
        self._batches = list(batches)
        self.closed = False

    def max_historical_ohlcv_limit(self, market: str) -> int:
        _ = market
        return 10

    async def fetch_ohlcv_historical(self, **kwargs) -> list[Candle]:
        _ = kwargs
        if self._batches:
            return self._batches.pop(0)
        return []

    async def close(self) -> None:
        self.closed = True


class _Downloader(HistoricalDownloader):
    def __init__(self, root, exchange: _FakeExchange) -> None:
        super().__init__(root=root)
        self.exchange = exchange

    async def _get_exchange(self, ctx, exchange_name: str) -> _FakeExchange:
        _ = (ctx, exchange_name)
        return self.exchange


def _request() -> DownloadRequest:
    return DownloadRequest(
        exchange="bybit",
        market_type="linear",
        symbol="BTCUSDT",
        timeframe="1m",
        start_ms=60_000,
        end_ms=60_000,
        limit=1,
    )


def test_downloader_invalidates_dataset_service_cache_after_successful_write(tmp_path) -> None:
    probe = _DatasetServiceProbe()
    ctx = _Context(probe)
    exchange = _FakeExchange([
        [Candle(ts_ms=60_000, open=1.0, high=1.0, low=1.0, close=1.0, volume=100.0)]
    ])
    downloader = _Downloader(tmp_path / "historical", exchange)

    async def scenario() -> None:
        result = await downloader.run_with_job_id(ctx, _request(), "job-1")
        assert result.total_rows == 1

    asyncio.run(scenario())

    assert probe.invalidated == [DatasetId("bybit", "linear", "BTCUSDT", "1m")]
    assert exchange.closed is True


def test_downloader_does_not_invalidate_dataset_cache_when_write_fails(tmp_path, monkeypatch) -> None:
    probe = _DatasetServiceProbe()
    ctx = _Context(probe)
    exchange = _FakeExchange([
        [Candle(ts_ms=60_000, open=1.0, high=1.0, low=1.0, close=1.0, volume=100.0)]
    ])
    downloader = _Downloader(tmp_path / "historical", exchange)

    def fail_write(*args, **kwargs) -> None:
        _ = (args, kwargs)
        raise OSError("write failed")

    monkeypatch.setattr(downloader._store, "write_atomic", fail_write)

    async def scenario() -> None:
        with pytest.raises(OSError, match="write failed"):
            await downloader.run_with_job_id(ctx, _request(), "job-1")

    asyncio.run(scenario())

    assert probe.invalidated == []
    assert exchange.closed is True
