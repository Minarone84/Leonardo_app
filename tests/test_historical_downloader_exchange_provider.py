from __future__ import annotations

import asyncio

import pytest

from leonardo.common.market_types import Candle
from leonardo.connection.exchange.registry import ExchangeRegistry
from leonardo.core.audit import InMemoryAuditSink
from leonardo.core.registry_keys import SVC_EXCHANGE_REGISTRY, SVC_HISTORICAL_DATASET
from leonardo.data.historical.dataset_service import DatasetId, HistoricalDatasetService
from leonardo.data.historical.downloader import DownloadRequest, HistoricalDownloader


class _DatasetServiceProbe:
    def __init__(self) -> None:
        self.invalidated: list[DatasetId] = []

    def invalidate_dataset_cache(self, dataset_id: DatasetId) -> bool:
        self.invalidated.append(dataset_id)
        return True


class _Context:
    def __init__(self, registry: ExchangeRegistry, dataset_service: _DatasetServiceProbe | None = None) -> None:
        self.audit = InMemoryAuditSink()
        self.registry = registry
        self.dataset_service = dataset_service or _DatasetServiceProbe()

    def get_service(self, name: str, t: type[object]) -> object:
        if name == SVC_EXCHANGE_REGISTRY:
            assert t is ExchangeRegistry
            return self.registry
        if name == SVC_HISTORICAL_DATASET:
            assert t is HistoricalDatasetService
            return self.dataset_service
        raise KeyError(name)


class _FakeExchange:
    def __init__(self) -> None:
        self.open_count = 0
        self.close_count = 0
        self.fetch_count = 0

    async def open(self) -> None:
        self.open_count += 1

    async def close(self) -> None:
        self.close_count += 1

    def max_historical_ohlcv_limit(self, market: str) -> int:
        _ = market
        return 10

    async def fetch_ohlcv_historical(self, **kwargs) -> list[Candle]:
        _ = kwargs
        self.fetch_count += 1
        if self.fetch_count == 1:
            return [Candle(ts_ms=60_000, open=1.0, high=2.0, low=0.5, close=1.5, volume=100.0)]
        return []


def _request(exchange: str = "bybit") -> DownloadRequest:
    return DownloadRequest(
        exchange=exchange,
        market_type="linear",
        symbol="BTCUSDT",
        timeframe="1m",
        start_ms=60_000,
        end_ms=60_000,
        limit=1,
    )


def test_downloader_obtains_adapter_from_registered_exchange_registry(tmp_path) -> None:
    exchange = _FakeExchange()
    registry = ExchangeRegistry()
    registry.register("bybit", lambda: exchange)
    dataset_service = _DatasetServiceProbe()
    ctx = _Context(registry, dataset_service)
    downloader = HistoricalDownloader(root=tmp_path / "historical")

    async def scenario() -> None:
        result = await downloader.run_with_job_id(ctx, _request(), "job-1")
        assert result.total_rows == 1

    asyncio.run(scenario())

    assert exchange.open_count == 1
    assert exchange.close_count == 1
    assert exchange.fetch_count == 1
    assert dataset_service.invalidated == [DatasetId("bybit", "linear", "BTCUSDT", "1m")]


def test_downloader_unsupported_exchange_fails_clearly(tmp_path) -> None:
    ctx = _Context(ExchangeRegistry())
    downloader = HistoricalDownloader(root=tmp_path / "historical")

    async def scenario() -> None:
        with pytest.raises(ValueError, match="unsupported exchange"):
            await downloader.run_with_job_id(ctx, _request(exchange="kraken"), "job-1")

    asyncio.run(scenario())
