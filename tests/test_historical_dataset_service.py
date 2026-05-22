from __future__ import annotations

import asyncio
from pathlib import Path

from leonardo.data.historical.dataset_service import DatasetId, HistoricalDatasetService, SliceRequest


def _write_dataset(data_root: Path, dataset_id: DatasetId, closes: list[float]) -> None:
    csv_path = (
        data_root
        / "historical"
        / dataset_id.exchange
        / dataset_id.market_type
        / dataset_id.symbol
        / dataset_id.timeframe
        / "ohlcv"
        / "candles.csv"
    )
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["ts_ms,open,high,low,close,volume"]
    for index, close in enumerate(closes):
        ts_ms = 60_000 * (index + 1)
        lines.append(f"{ts_ms},{close},{close},{close},{close},100")
    csv_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


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
