from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from leonardo.data.historical.dataset_service import (
    DatasetId,
    HistoricalDatasetService,
    SliceRequest,
    evaluate_ohlcv_dataset_loadability,
    require_ohlcv_dataset_loadable,
)
from leonardo.data.historical.artifact_metadata_naming import metadata_path_for_csv
from leonardo.data.historical.paths import timeframe_to_storage_segment
from leonardo.data.historical.store_csv import Candle, CsvOHLCVStore
from leonardo.data.naming import canonicalize


def _write_dataset(
    data_root: Path,
    dataset_id: DatasetId,
    closes: list[float],
    *,
    validation_status: str = "ok",
    write_metadata: bool = True,
    record_validation: bool = True,
) -> Path:
    csv_path = (
        data_root
        / "historical"
        / dataset_id.exchange
        / dataset_id.market_type
        / dataset_id.symbol
        / timeframe_to_storage_segment(dataset_id.timeframe)
        / "ohlcv"
        / "candles.csv"
    )
    market = canonicalize(
        dataset_id.exchange,
        dataset_id.market_type,
        dataset_id.symbol,
        dataset_id.timeframe,
    )
    candles = [
        Candle(
            ts_ms=60_000 * (index + 1),
            open=float(close),
            high=float(close),
            low=float(close),
            close=float(close),
            volume=100.0,
        )
        for index, close in enumerate(closes)
    ]
    store = CsvOHLCVStore()
    store.write_atomic(csv_path, candles, market=market, write_metadata=write_metadata)
    if write_metadata and record_validation:
        store.record_validation_result(
            csv_path,
            market=market,
            status=validation_status,
            row_count=len(candles),
            issues=(),
            validator="HistoricalDatasetValidator",
        )
    return csv_path


def _slice_request(dataset_id: DatasetId, request_id: str) -> SliceRequest:
    return SliceRequest(
        tab_id="tab",
        request_id=request_id,
        dataset_id=dataset_id,
        center_ts_ms=120_000,
        visible_max=3,
        buffer_left=0,
        buffer_right=0,
    )


def test_dataset_service_loadability_accepts_ok_and_modified_metadata(tmp_path) -> None:
    ok_dataset = DatasetId("bybit", "linear", "BTCUSDT", "1m")
    modified_dataset = DatasetId("bybit", "linear", "ETHUSDT", "1m")
    _write_dataset(tmp_path, ok_dataset, [1.0, 2.0], validation_status="ok")
    _write_dataset(tmp_path, modified_dataset, [3.0, 4.0], validation_status="modified")
    service = HistoricalDatasetService(tmp_path)

    ok_report = service.dataset_loadability(ok_dataset)
    modified_report = service.dataset_loadability(modified_dataset)

    assert ok_report.loadable is True
    assert ok_report.validation_status == "ok"
    assert modified_report.loadable is True
    assert modified_report.validation_status == "modified"
    assert "documented source correction" in modified_report.reason
    assert service.list_loadable_dataset_symbols("bybit", "linear") == ["BTCUSDT", "ETHUSDT"]


@pytest.mark.parametrize("status", ["unknown", "error", "warning"])
def test_dataset_service_loadability_blocks_unaccepted_validation_statuses(tmp_path, status: str) -> None:
    dataset = DatasetId("bybit", "linear", f"{status.upper()}USDT", "1m")
    _write_dataset(tmp_path, dataset, [1.0, 2.0], validation_status=status)
    service = HistoricalDatasetService(tmp_path)

    report = service.dataset_loadability(dataset)

    assert report.loadable is False
    assert report.validation_status == status
    assert service.has_dataset(dataset) is True
    assert service.list_loadable_dataset_symbols("bybit", "linear") == []
    with pytest.raises(PermissionError, match="not accepted for chart loading"):
        asyncio.run(service.open_dataset(dataset))


def test_dataset_service_blocks_downloaded_not_validated_metadata(tmp_path) -> None:
    dataset = DatasetId("bybit", "linear", "BTCUSDT", "1m")
    _write_dataset(tmp_path, dataset, [1.0, 2.0], write_metadata=True, record_validation=False)
    service = HistoricalDatasetService(tmp_path)

    report = service.dataset_loadability(dataset)

    assert report.loadable is False
    assert report.validation_status == "unknown"
    assert "not been manually validated" in report.reason
    assert service.list_dataset_exchanges() == ["bybit"]
    assert service.list_loadable_dataset_exchanges() == []


def test_dataset_service_blocks_missing_metadata_sidecar(tmp_path) -> None:
    dataset = DatasetId("bybit", "linear", "BTCUSDT", "1m")
    _write_dataset(tmp_path, dataset, [1.0, 2.0], write_metadata=False)
    service = HistoricalDatasetService(tmp_path)

    report = service.dataset_loadability(dataset)

    assert report.loadable is False
    assert report.validation_status == "unknown"
    assert "metadata sidecar" in report.reason


def test_dataset_service_blocks_missing_validation_block(tmp_path) -> None:
    dataset = DatasetId("bybit", "linear", "BTCUSDT", "1m")
    csv_path = _write_dataset(tmp_path, dataset, [1.0, 2.0], validation_status="ok")
    metadata_path = metadata_path_for_csv(csv_path)
    payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    payload.pop("validation", None)
    metadata_path.write_text(json.dumps(payload), encoding="utf-8")
    service = HistoricalDatasetService(tmp_path)

    report = service.dataset_loadability(dataset)

    assert report.loadable is False
    assert report.validation_status == "unknown"


def test_dataset_service_blocks_unreadable_metadata_sidecar(tmp_path) -> None:
    dataset = DatasetId("bybit", "linear", "BTCUSDT", "1m")
    csv_path = _write_dataset(tmp_path, dataset, [1.0, 2.0], validation_status="ok")
    metadata_path_for_csv(csv_path).write_text("{", encoding="utf-8")
    service = HistoricalDatasetService(tmp_path)

    report = service.dataset_loadability(dataset)

    assert report.loadable is False
    assert report.validation_status == "unknown"
    assert "unreadable" in report.reason or "invalid" in report.reason


def test_dataset_service_blocks_stale_validation_fingerprint(tmp_path) -> None:
    dataset = DatasetId("bybit", "linear", "BTCUSDT", "1m")
    csv_path = _write_dataset(tmp_path, dataset, [1.0, 2.0], validation_status="ok")
    csv_path.write_text(
        csv_path.read_text(encoding="utf-8") + "180000,3,3,3,3,100\n",
        encoding="utf-8",
    )
    service = HistoricalDatasetService(tmp_path)

    report = service.dataset_loadability(dataset)

    assert report.loadable is False
    assert report.validation_status == "unknown"
    assert "changed after validation" in report.reason or "stale" in report.reason


def test_dataset_service_loadability_preserves_month_storage_segment(tmp_path) -> None:
    dataset = DatasetId("bybit", "linear", "LINKUSDT", "1M")
    _write_dataset(tmp_path, dataset, [1.0, 2.0], validation_status="ok")
    service = HistoricalDatasetService(tmp_path)

    assert service.list_loadable_dataset_timeframes("bybit", "linear", "LINKUSDT") == ["1M"]
    assert service.dataset_loadability(dataset).loadable is True


def test_shared_ohlcv_loadability_helper_uses_historical_root_and_month_segment(tmp_path) -> None:
    dataset = DatasetId("bybit", "linear", "LINKUSDT", "1M")
    csv_path = _write_dataset(tmp_path, dataset, [1.0, 2.0], validation_status="modified")
    market = canonicalize("bybit", "linear", "LINKUSDT", "1M")

    report = evaluate_ohlcv_dataset_loadability(
        historical_root=tmp_path / "historical",
        market=market,
    )

    assert report.loadable is True
    assert report.validation_status == "modified"
    assert report.csv_path == str(csv_path)
    assert require_ohlcv_dataset_loadable(
        historical_root=tmp_path / "historical",
        market=market,
        context="test",
    ).loadable is True


def test_invalidate_dataset_cache_removes_only_matching_loaded_and_slice_entries(tmp_path) -> None:
    dataset_a = DatasetId("bybit", "linear", "BTCUSDT", "1m")
    dataset_b = DatasetId("bybit", "linear", "ETHUSDT", "1m")
    _write_dataset(tmp_path, dataset_a, [1.0, 2.0, 3.0])
    _write_dataset(tmp_path, dataset_b, [4.0, 5.0, 6.0])
    service = HistoricalDatasetService(tmp_path, slice_cache_entries=10)

    async def scenario() -> None:
        first_a = await service.get_slice(_slice_request(dataset_a, "a-1"))
        first_b = await service.get_slice(_slice_request(dataset_b, "b-1"))
        assert first_a.close == [1.0, 2.0, 3.0]
        assert first_b.close == [4.0, 5.0, 6.0]

        _write_dataset(tmp_path, dataset_a, [10.0, 20.0, 30.0])
        _write_dataset(tmp_path, dataset_b, [40.0, 50.0, 60.0])

        assert service.invalidate_dataset_cache(dataset_a) is True

        reloaded_a = await service.get_slice(_slice_request(dataset_a, "a-2"))
        cached_b = await service.get_slice(_slice_request(dataset_b, "b-2"))
        assert reloaded_a.close == [10.0, 20.0, 30.0]
        assert cached_b.close == [4.0, 5.0, 6.0]
        assert cached_b.request_id == "b-2"

    asyncio.run(scenario())


def test_invalidate_all_dataset_caches_clears_loaded_and_slice_entries(tmp_path) -> None:
    dataset_a = DatasetId("bybit", "linear", "BTCUSDT", "1m")
    dataset_b = DatasetId("bybit", "linear", "ETHUSDT", "1m")
    _write_dataset(tmp_path, dataset_a, [1.0, 2.0, 3.0])
    _write_dataset(tmp_path, dataset_b, [4.0, 5.0, 6.0])
    service = HistoricalDatasetService(tmp_path, slice_cache_entries=10)

    async def scenario() -> None:
        await service.get_slice(_slice_request(dataset_a, "a-1"))
        await service.get_slice(_slice_request(dataset_b, "b-1"))

        _write_dataset(tmp_path, dataset_a, [10.0, 20.0, 30.0])
        _write_dataset(tmp_path, dataset_b, [40.0, 50.0, 60.0])

        assert service.invalidate_all_dataset_caches() >= 2

        reloaded_a = await service.get_slice(_slice_request(dataset_a, "a-2"))
        reloaded_b = await service.get_slice(_slice_request(dataset_b, "b-2"))
        assert reloaded_a.close == [10.0, 20.0, 30.0]
        assert reloaded_b.close == [40.0, 50.0, 60.0]

    asyncio.run(scenario())
