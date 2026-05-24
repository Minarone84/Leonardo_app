from __future__ import annotations

import asyncio
import json
from pathlib import Path

from leonardo.data.historical.artifact_metadata_contracts import HistoricalCsvArtifactManifest
from leonardo.data.historical.artifact_metadata_naming import metadata_path_for_csv
from leonardo.data.historical.dataset_service import DatasetId, HistoricalDatasetService
from leonardo.data.historical.paths import (
    HistoricalPaths,
    storage_segment_to_timeframe,
    timeframe_to_storage_segment,
)
from leonardo.data.historical.store_csv import Candle, CsvOHLCVStore
from leonardo.data.naming import canonicalize


def _candles() -> list[Candle]:
    return [
        Candle(1_609_459_200_000, 1.0, 2.0, 0.5, 1.5, 10.0),
        Candle(1_609_462_800_000, 1.5, 2.5, 1.0, 2.0, 11.0),
    ]


def test_timeframe_storage_segments_keep_minute_and_month_paths_distinct(tmp_path: Path) -> None:
    paths = HistoricalPaths(root=tmp_path)
    minute = canonicalize("bybit", "linear", "LINKUSDT", "1m")
    month = canonicalize("bybit", "linear", "LINKUSDT", "1M")

    assert timeframe_to_storage_segment("1m") == "1m"
    assert timeframe_to_storage_segment("1M") == "1mo"
    assert storage_segment_to_timeframe("1mo") == "1M"

    minute_partition = paths.partition_dir(minute)
    month_partition = paths.partition_dir(month)

    assert minute_partition.name == "1m"
    assert month_partition.name == "1mo"
    assert minute_partition != month_partition
    assert minute_partition.name.casefold() != month_partition.name.casefold()


def test_dataset_service_resolves_month_storage_segment_to_canonical_timeframe(tmp_path: Path) -> None:
    historical_root = tmp_path / "historical"
    paths = HistoricalPaths(root=historical_root)
    store = CsvOHLCVStore()
    minute = canonicalize("bybit", "linear", "LINKUSDT", "1m")
    month = canonicalize("bybit", "linear", "LINKUSDT", "1M")

    store.write_atomic(store.file_path(paths.ensure_ohlcv_dir(minute)), _candles(), market=minute)
    store.write_atomic(store.file_path(paths.ensure_ohlcv_dir(month)), _candles(), market=month)
    store.record_validation_result(
        store.file_path(paths.ensure_ohlcv_dir(minute)),
        market=minute,
        status="ok",
        row_count=len(_candles()),
        issues=(),
        validator="HistoricalDatasetValidator",
    )
    store.record_validation_result(
        store.file_path(paths.ensure_ohlcv_dir(month)),
        market=month,
        status="ok",
        row_count=len(_candles()),
        issues=(),
        validator="HistoricalDatasetValidator",
    )

    partition_names = {
        child.name
        for child in (historical_root / "bybit" / "linear" / "LINKUSDT").iterdir()
        if child.is_dir()
    }
    assert partition_names == {"1m", "1mo"}

    service = HistoricalDatasetService(tmp_path)
    assert service.list_dataset_timeframes("bybit", "linear", "LINKUSDT") == ["1m", "1M"]
    assert service.has_dataset(DatasetId("bybit", "linear", "LINKUSDT", "1m"))
    assert service.has_dataset(DatasetId("bybit", "linear", "LINKUSDT", "1M"))

    async def open_month() -> None:
        meta = await service.open_dataset(DatasetId("bybit", "linear", "LINKUSDT", "1M"))
        assert Path(meta.path).parent.parent.name == "1mo"

    asyncio.run(open_month())


def test_ohlcv_metadata_infers_canonical_month_from_storage_segment(tmp_path: Path) -> None:
    paths = HistoricalPaths(root=tmp_path)
    month = canonicalize("bybit", "linear", "LINKUSDT", "1M")
    csv_path = CsvOHLCVStore().file_path(paths.ensure_ohlcv_dir(month))

    CsvOHLCVStore().write_atomic(csv_path, _candles())

    manifest = HistoricalCsvArtifactManifest.from_dict(
        json.loads(metadata_path_for_csv(csv_path).read_text(encoding="utf-8"))
    )
    assert csv_path.parent.parent.name == "1mo"
    assert manifest.market.timeframe == "1M"
