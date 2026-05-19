from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from leonardo.data.historical.artifact_metadata_backfill import ArtifactMetadataBackfill
from leonardo.data.historical.artifact_metadata_contracts import HistoricalCsvArtifactManifest
from leonardo.data.historical.artifact_metadata_naming import metadata_path_for_csv
from leonardo.data.historical.store_csv import Candle, CsvOHLCVStore
from leonardo.data.naming import canonicalize


def _load_manifest(csv_path: Path) -> HistoricalCsvArtifactManifest:
    with metadata_path_for_csv(csv_path).open("r", encoding="utf-8") as handle:
        return HistoricalCsvArtifactManifest.from_dict(json.load(handle))


def test_backfill_restores_missing_ohlcv_metadata_without_touching_csv(tmp_path: Path):
    market = canonicalize("bybit", "linear", "BTC/USDT", "30m")
    csv_path = tmp_path / market.exchange / market.market_type / market.symbol / market.timeframe / "ohlcv" / "candles.csv"
    candles = [
        Candle(1_609_459_200_000, 1.0, 2.0, 0.5, 1.5, 10.0),
        Candle(1_609_460_000_000, 1.5, 2.5, 1.0, 2.0, 11.0),
    ]
    CsvOHLCVStore().write_atomic(csv_path, candles, market=market, write_metadata=False)
    before = csv_path.read_text(encoding="utf-8")

    report = ArtifactMetadataBackfill(historical_root=tmp_path).backfill_market(market)

    assert report.scanned_csv_count == 1
    assert report.created_count == 1
    assert report.failed_count == 0
    assert csv_path.read_text(encoding="utf-8") == before

    manifest = _load_manifest(csv_path)
    assert manifest.identity.artifact_family == "ohlcv"
    assert manifest.identity.artifact_id == "ohlcv__candles"
    assert manifest.files.csv_relpath == "ohlcv/candles.csv"
    assert manifest.time_range.first_ts_rome == "2021-01-01 01:00:00 Europe/Rome"
    assert manifest.shape.row_count == 2
    assert manifest.quality.timeline_status == "verified"
    assert any(entry.key == "metadata_restore_only" for entry in manifest.metadata)


def test_backfill_restores_missing_derived_metadata_with_cautious_statuses(tmp_path: Path):
    market = canonicalize("bybit", "linear", "BTCUSDT", "1h")
    csv_path = tmp_path / market.exchange / market.market_type / market.symbol / market.timeframe / "oscillators" / "rsi__default__period-14.csv"
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        {
            "ts_ms": [1_609_459_200_000, 1_609_462_800_000],
            "rsi_14": [50.0, 55.0],
        }
    ).to_csv(csv_path, index=False)

    report = ArtifactMetadataBackfill(historical_root=tmp_path).backfill_market(market)

    assert report.created_count == 1
    assert report.failed_count == 0
    manifest = _load_manifest(csv_path)
    assert manifest.identity.artifact_family == "oscillator"
    assert manifest.identity.storage_family == "oscillators"
    assert manifest.tool is not None
    assert manifest.tool.tool_key == "rsi"
    assert manifest.tool.tool_identity_status == "inferred"
    assert manifest.tool.params_status == "unknown"
    assert manifest.tool.bindings_status == "unknown"
    assert manifest.columns[1].name == "rsi_14"
    assert manifest.columns[1].selectable is True


def test_backfill_skips_valid_existing_metadata(tmp_path: Path):
    market = canonicalize("bybit", "linear", "ETHUSDT", "1h")
    csv_path = tmp_path / market.exchange / market.market_type / market.symbol / market.timeframe / "ohlcv" / "candles.csv"
    candles = [Candle(1_609_459_200_000, 1.0, 2.0, 0.5, 1.5, 10.0)]
    store = CsvOHLCVStore()
    store.write_atomic(csv_path, candles, market=market)
    unique_id = _load_manifest(csv_path).identity.unique_id

    report = ArtifactMetadataBackfill(historical_root=tmp_path).backfill_market(market)

    assert report.scanned_csv_count == 1
    assert report.skipped_existing_count == 1
    assert _load_manifest(csv_path).identity.unique_id == unique_id


def test_backfill_restores_unreadable_metadata_sidecar(tmp_path: Path):
    market = canonicalize("bybit", "linear", "BTCUSDT", "4h")
    csv_path = tmp_path / market.exchange / market.market_type / market.symbol / market.timeframe / "ohlcv" / "candles.csv"
    CsvOHLCVStore().write_atomic(
        csv_path,
        [Candle(1_609_459_200_000, 1.0, 2.0, 0.5, 1.5, 10.0)],
        market=market,
        write_metadata=False,
    )
    metadata_path_for_csv(csv_path).write_text("{bad json", encoding="utf-8")

    report = ArtifactMetadataBackfill(historical_root=tmp_path).backfill_market(market)

    assert report.restored_corrupt_count == 1
    assert _load_manifest(csv_path).identity.artifact_family == "ohlcv"


def test_backfill_reports_failure_when_ts_ms_is_missing_and_does_not_create_sidecar(tmp_path: Path):
    market = canonicalize("bybit", "linear", "BTCUSDT", "1h")
    csv_path = tmp_path / market.exchange / market.market_type / market.symbol / market.timeframe / "indicators" / "ema__default__period-14.csv"
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame({"time": ["2021-01-01"], "ema_14": [1.0]}).to_csv(csv_path, index=False)

    report = ArtifactMetadataBackfill(historical_root=tmp_path).backfill_market(market)

    assert report.failed_count == 1
    assert "ts_ms" in report.items[0].detail
    assert not metadata_path_for_csv(csv_path).exists()
