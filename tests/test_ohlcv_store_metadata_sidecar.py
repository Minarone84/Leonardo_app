from __future__ import annotations

import json
from pathlib import Path

from leonardo.data.historical.artifact_metadata_contracts import HistoricalCsvArtifactManifest
from leonardo.data.historical.artifact_metadata_naming import metadata_path_for_csv
from leonardo.data.historical.store_csv import Candle, CsvOHLCVStore
from leonardo.data.naming import canonicalize


def _candles() -> list[Candle]:
    return [
        Candle(1_609_459_200_000, 1.0, 2.0, 0.5, 1.5, 10.0),
        Candle(1_609_462_800_000, 1.5, 2.5, 1.0, 2.0, 11.0),
    ]


def test_ohlcv_write_atomic_creates_metadata_sidecar(tmp_path: Path):
    market = canonicalize("bybit", "linear", "BTC/USDT", "1h")
    csv_path = tmp_path / market.exchange / market.market_type / market.symbol / market.timeframe / "ohlcv" / "candles.csv"

    store = CsvOHLCVStore()
    store.write_atomic(csv_path, _candles(), market=market)

    metadata_path = metadata_path_for_csv(csv_path)
    assert metadata_path.exists()

    with metadata_path.open("r", encoding="utf-8") as handle:
        manifest = HistoricalCsvArtifactManifest.from_dict(json.load(handle))

    assert manifest.identity.unique_id
    assert manifest.identity.artifact_family == "ohlcv"
    assert manifest.identity.storage_family == "ohlcv"
    assert manifest.identity.artifact_id == "ohlcv__candles"
    assert manifest.identity.artifact_uid == "ohlcv:bybit:linear:BTCUSDT:1h:ohlcv__candles"
    assert manifest.market == market
    assert manifest.files.csv_filename == "candles.csv"
    assert manifest.files.csv_relpath == "ohlcv/candles.csv"
    assert manifest.files.metadata_filename == "candles.meta.json"
    assert manifest.files.metadata_relpath == "ohlcv/candles.meta.json"
    assert manifest.time_range.first_ts_ms == 1_609_459_200_000
    assert manifest.time_range.first_ts_rome == "2021-01-01 01:00:00 Europe/Rome"
    assert manifest.time_range.last_ts_ms == 1_609_462_800_000
    assert manifest.shape.row_count == 2
    assert manifest.shape.column_count == 6
    assert manifest.shape.columns == ("ts_ms", "open", "high", "low", "close", "volume")
    assert manifest.tool is None
    assert manifest.quality.timeline_status == "verified"
    assert manifest.quality.monotonic_ts_ms is True
    assert manifest.quality.duplicate_ts_ms is False
    assert [column.name for column in manifest.columns] == list(CsvOHLCVStore.HEADER)


def test_ohlcv_sidecar_preserves_unique_id_on_overwrite(tmp_path: Path):
    market = canonicalize("bybit", "linear", "ETHUSDT", "1h")
    csv_path = tmp_path / market.exchange / market.market_type / market.symbol / market.timeframe / "ohlcv" / "candles.csv"
    store = CsvOHLCVStore()

    store.write_atomic(csv_path, _candles(), market=market)
    metadata_path = metadata_path_for_csv(csv_path)
    first_payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    first_unique_id = first_payload["identity"]["unique_id"]

    updated_candles = _candles() + [Candle(1_609_466_400_000, 2.0, 3.0, 1.5, 2.5, 12.0)]
    store.write_atomic(csv_path, updated_candles, market=market)
    second_manifest = HistoricalCsvArtifactManifest.from_dict(json.loads(metadata_path.read_text(encoding="utf-8")))

    assert second_manifest.identity.unique_id == first_unique_id
    assert second_manifest.shape.row_count == 3
    assert second_manifest.time_range.last_ts_ms == 1_609_466_400_000
    assert second_manifest.lineage.created_at_ms == first_payload["lineage"]["created_at_ms"]
    assert second_manifest.lineage.updated_at_ms >= second_manifest.lineage.created_at_ms


def test_ohlcv_metadata_is_skipped_for_nonstandard_paths(tmp_path: Path):
    csv_path = tmp_path / "candles.csv"
    CsvOHLCVStore().write_atomic(csv_path, _candles())
    assert csv_path.exists()
    assert not metadata_path_for_csv(csv_path).exists()


def test_ohlcv_rebuild_metadata_sidecar_does_not_rewrite_csv(tmp_path: Path):
    market = canonicalize("bybit", "linear", "LINKUSDT", "1M")
    csv_path = tmp_path / market.exchange / market.market_type / market.symbol / "1mo" / "ohlcv" / "candles.csv"
    store = CsvOHLCVStore()
    store.write_atomic(csv_path, _candles(), market=market, write_metadata=False)
    before = csv_path.read_text(encoding="utf-8")

    state = store.rebuild_metadata_sidecar(csv_path, market=market)

    assert state.metadata_valid is True
    assert state.row_count == 2
    assert csv_path.read_text(encoding="utf-8") == before
    manifest = HistoricalCsvArtifactManifest.from_dict(
        json.loads(metadata_path_for_csv(csv_path).read_text(encoding="utf-8"))
    )
    assert manifest.market.timeframe == "1M"
    assert manifest.identity.artifact_uid == "ohlcv:bybit:linear:LINKUSDT:1M:ohlcv__candles"
