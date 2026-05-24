from __future__ import annotations

import asyncio
import json
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
from leonardo.data.historical.artifact_metadata_contracts import HistoricalCsvArtifactManifest
from leonardo.data.historical.artifact_metadata_naming import metadata_path_for_csv
from leonardo.data.historical.paths import HistoricalPaths
from leonardo.data.historical.store_csv import CsvOHLCVStore
from leonardo.data.naming import canonicalize


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


def _custom_request(*, timeframe: str, start_ms: int, end_ms: int, limit: int) -> DownloadRequest:
    return DownloadRequest(
        exchange="bybit",
        market_type="linear",
        symbol="BTCUSDT",
        timeframe=timeframe,
        start_ms=start_ms,
        end_ms=end_ms,
        limit=limit,
    )


def _manifest_for(csv_path):
    return HistoricalCsvArtifactManifest.from_dict(
        json.loads(metadata_path_for_csv(csv_path).read_text(encoding="utf-8"))
    )


async def _download_validated_event(ctx: _Context):
    events = await ctx.audit.snapshot()
    for event in reversed(events):
        if event.message == "download validated":
            return event
    raise AssertionError("download validated event was not emitted")


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


def test_downloader_keeps_download_metadata_validation_unknown_after_preliminary_ok(tmp_path) -> None:
    probe = _DatasetServiceProbe()
    ctx = _Context(probe)
    exchange = _FakeExchange([
        [Candle(ts_ms=60_000, open=1.0, high=1.0, low=1.0, close=1.0, volume=100.0)]
    ])
    downloader = _Downloader(tmp_path / "historical", exchange)

    async def scenario() -> None:
        result = await downloader.run_with_job_id(ctx, _request(), "job-1")
        manifest = _manifest_for(result.file_path)
        assert manifest.validation.status == "unknown"
        assert manifest.quality.validation_status == "not_validated"

        event = await _download_validated_event(ctx)
        assert event.fields["status"] == "ok"
        assert event.fields["metadata_validation_status"] == "unknown"
        assert event.fields["timeframe_step_ms"] == 60_000
        assert event.fields["timeframe_continuity"] == "fixed"

    asyncio.run(scenario())


def test_downloader_reports_preliminary_validation_error_without_stamping_metadata_error(tmp_path) -> None:
    probe = _DatasetServiceProbe()
    ctx = _Context(probe)
    exchange = _FakeExchange([
        [Candle(ts_ms=60_000, open=10.0, high=5.0, low=1.0, close=2.0, volume=100.0)]
    ])
    downloader = _Downloader(tmp_path / "historical", exchange)

    async def scenario() -> None:
        result = await downloader.run_with_job_id(ctx, _request(), "job-1")
        manifest = _manifest_for(result.file_path)
        assert manifest.validation.status == "unknown"
        assert manifest.quality.validation_status == "not_validated"

        event = await _download_validated_event(ctx)
        assert event.severity == "error"
        assert event.fields["status"] == "error"
        assert event.fields["error_count"] >= 1
        assert any("open out of bounds" in issue for issue in event.fields["issues"])

    asyncio.run(scenario())


def test_downloader_reports_fixed_timeframe_gap_as_preliminary_warning(tmp_path) -> None:
    probe = _DatasetServiceProbe()
    ctx = _Context(probe)
    exchange = _FakeExchange([
        [
            Candle(ts_ms=60_000, open=1.0, high=1.0, low=1.0, close=1.0, volume=100.0),
            Candle(ts_ms=180_000, open=1.0, high=1.0, low=1.0, close=1.0, volume=100.0),
        ]
    ])
    downloader = _Downloader(tmp_path / "historical", exchange)

    async def scenario() -> None:
        await downloader.run_with_job_id(
            ctx,
            _custom_request(timeframe="1m", start_ms=60_000, end_ms=180_000, limit=2),
            "job-1",
        )
        event = await _download_validated_event(ctx)
        assert event.severity == "warning"
        assert event.fields["status"] == "warning"
        assert event.fields["warning_count"] >= 1
        assert any("timeframe gaps detected" in issue for issue in event.fields["issues"])

    asyncio.run(scenario())


def test_downloader_preliminary_validation_uses_variable_month_timeframe(tmp_path) -> None:
    probe = _DatasetServiceProbe()
    ctx = _Context(probe)
    exchange = _FakeExchange([
        [
            Candle(ts_ms=1_609_459_200_000, open=1.0, high=1.0, low=1.0, close=1.0, volume=100.0),
            Candle(ts_ms=1_612_137_600_000, open=1.0, high=1.0, low=1.0, close=1.0, volume=100.0),
        ]
    ])
    downloader = _Downloader(tmp_path / "historical", exchange)

    async def scenario() -> None:
        await downloader.run_with_job_id(
            ctx,
            _custom_request(
                timeframe="1M",
                start_ms=1_609_459_200_000,
                end_ms=1_612_137_600_000,
                limit=2,
            ),
            "job-1",
        )
        event = await _download_validated_event(ctx)
        assert event.fields["status"] == "warning"
        assert event.fields["timeframe_step_ms"] is None
        assert event.fields["timeframe_continuity"] == "variable"
        assert not any("timeframe gaps detected" in issue for issue in event.fields["issues"])

    asyncio.run(scenario())


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


def test_downloader_repair_range_replaces_existing_rows_inside_range(tmp_path) -> None:
    probe = _DatasetServiceProbe()
    ctx = _Context(probe)
    market = canonicalize("bybit", "linear", "BTCUSDT", "1m")
    paths = HistoricalPaths(root=tmp_path / "historical")
    store = CsvOHLCVStore()
    csv_path = store.file_path(paths.ensure_ohlcv_dir(market))
    store.write_atomic(
        csv_path,
        [
            Candle(ts_ms=0, open=1.0, high=1.0, low=1.0, close=1.0, volume=10.0),
            Candle(ts_ms=60_000, open=10.0, high=5.0, low=1.0, close=2.0, volume=11.0),
            Candle(ts_ms=120_000, open=3.0, high=3.0, low=3.0, close=3.0, volume=12.0),
            Candle(ts_ms=180_000, open=4.0, high=4.0, low=4.0, close=4.0, volume=13.0),
        ],
        market=market,
    )
    exchange = _FakeExchange([
        [
            Candle(ts_ms=60_000, open=2.0, high=5.0, low=1.0, close=2.5, volume=21.0),
            Candle(ts_ms=120_000, open=3.5, high=4.0, low=3.0, close=3.5, volume=22.0),
        ]
    ])
    downloader = _Downloader(tmp_path / "historical", exchange)
    request = DownloadRequest(
        exchange="bybit",
        market_type="linear",
        symbol="BTCUSDT",
        timeframe="1m",
        start_ms=60_000,
        end_ms=120_000,
        limit=2,
    )

    async def scenario() -> None:
        result = await downloader.run_repair_range_with_job_id(ctx, request, "job-1")
        assert result.total_rows == 4
        assert result.fetched_rows == 2
        assert result.downloaded_first_ts_ms == 60_000
        assert result.downloaded_last_ts_ms == 120_000

    asyncio.run(scenario())

    repaired = {candle.ts_ms: candle for candle in store.read(csv_path)}
    assert repaired[60_000].open == 2.0
    assert repaired[120_000].open == 3.5
    assert repaired[0].open == 1.0
    assert repaired[180_000].open == 4.0
    assert probe.invalidated == [DatasetId("bybit", "linear", "BTCUSDT", "1m")]
