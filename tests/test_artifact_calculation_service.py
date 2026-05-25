from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from leonardo.data.historical.artifact_calculation_service import ArtifactCalculationService
from leonardo.data.historical.artifact_metadata_contracts import HistoricalCsvArtifactManifest
from leonardo.data.historical.artifact_metadata_naming import metadata_path_for_csv
from leonardo.data.historical.paths import HistoricalPaths
from leonardo.data.historical.source_ohlcv_provenance import (
    SOURCE_OHLCV_PROVENANCE_KEY,
    SOURCE_OHLCV_PROVENANCE_NAMESPACE,
)
from leonardo.data.historical.store_csv import Candle, CsvOHLCVStore
from leonardo.data.naming import canonicalize


def _issues_for_status(status: str) -> tuple[tuple[str, str], ...]:
    if status == "error":
        return (("error", "test validation error"),)
    if status == "warning":
        return (("warning", "test validation warning"),)
    return ()


def _write_ohlcv(
    root: Path,
    *,
    rows: int = 40,
    validation_status: str = "ok",
    write_metadata: bool = True,
):
    market = canonicalize("bybit", "linear", "BTCUSDT", "30m")
    paths = HistoricalPaths(root=root)
    ohlcv_path = CsvOHLCVStore().file_path(paths.ensure_ohlcv_dir(market))
    start = 1_700_000_000_000
    candles = [
        Candle(
            ts_ms=start + idx * 1_800_000,
            open=100.0 + idx,
            high=101.0 + idx,
            low=99.0 + idx,
            close=100.5 + idx,
            volume=10.0 + idx,
        )
        for idx in range(rows)
    ]
    store = CsvOHLCVStore()
    store.write_atomic(ohlcv_path, candles, market=market, write_metadata=write_metadata)
    if write_metadata:
        store.record_validation_result(
            ohlcv_path,
            market=market,
            status=validation_status,
            row_count=len(candles),
            issues=_issues_for_status(validation_status),
            validator="HistoricalDatasetValidator",
        )
    return market, ohlcv_path


def _payload(market, *, tool_key: str = "rsi", tool_type: str = "oscillator") -> dict[str, object]:
    return {
        "tool_type": tool_type,
        "tool_key": tool_key,
        "tool_title": tool_key.upper(),
        "exchange": market.exchange,
        "market_type": market.market_type,
        "symbol": market.symbol,
        "timeframe": market.timeframe,
        "params": {"period": 14},
        "input_bindings": {},
        "input_binding_meta": {},
    }


def _load_manifest(csv_path: Path) -> HistoricalCsvArtifactManifest:
    with metadata_path_for_csv(csv_path).open("r", encoding="utf-8") as handle:
        return HistoricalCsvArtifactManifest.from_dict(json.load(handle))


def _source_ohlcv_snapshot(manifest: HistoricalCsvArtifactManifest) -> dict[str, object]:
    for entry in manifest.metadata:
        if (
            entry.namespace == SOURCE_OHLCV_PROVENANCE_NAMESPACE
            and entry.key == SOURCE_OHLCV_PROVENANCE_KEY
        ):
            assert isinstance(entry.value, dict)
            return entry.value
    raise AssertionError("source OHLCV provenance snapshot metadata entry was not written")


def _record_source_correction(path: Path, market) -> None:
    store = CsvOHLCVStore()
    fingerprint = store.file_fingerprint(path).to_dict()
    store.record_source_corrections(
        path,
        market=market,
        records=(
            {
                "ts_ms": 1_700_000_000_000,
                "row_index": 0,
                "issue_code": "open_out_of_bounds",
                "issue_message": "open out of bounds at row 0",
                "action": "correct_open",
                "method": "test_context",
                "confidence": "high",
                "needs_source_recheck": True,
                "original": {"open": 105.0, "high": 101.0, "low": 99.0, "close": 100.5},
                "corrected": {"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5},
                "context": {"previous_close": None, "next_open": 101.0},
                "source": "test",
                "corrected_at_ms": 1_700_000_060_000,
                "corrected_at": "2023-11-14T22:14:20Z",
                "source_csv_fingerprint": fingerprint,
                "corrected_csv_fingerprint": fingerprint,
            },
        ),
    )


def test_artifact_calculation_service_saves_single_oscillator_with_metadata(tmp_path):
    market, _ohlcv_path = _write_ohlcv(tmp_path)
    service = ArtifactCalculationService(historical_root=tmp_path)

    result = service.calculate_and_save(
        {
            "tool_type": "oscillator",
            "tool_key": "rsi",
            "tool_title": "RSI",
            "exchange": market.exchange,
            "market_type": market.market_type,
            "symbol": market.symbol,
            "timeframe": market.timeframe,
            "params": {"period": 14},
            "input_bindings": {},
            "input_binding_meta": {},
        }
    )

    assert result.saved_path.exists()
    assert result.metadata_path.exists()
    assert result.saved_path.is_relative_to(tmp_path)
    assert result.instance_key == "rsi__default__period-14"

    saved = pd.read_csv(result.saved_path)
    assert list(saved.columns) == ["ts_ms", "time", "timeframe", "rsi_14"]
    assert len(saved) == 40

    manifest = _load_manifest(result.saved_path)
    assert manifest.identity.artifact_family == "oscillator"
    assert manifest.identity.storage_family == "oscillators"
    assert manifest.tool is not None
    assert manifest.tool.tool_key == "rsi"
    assert manifest.tool.params == {"period": 14}
    assert manifest.tool.params_status == "explicit"
    assert manifest.tool.bindings_status == "unknown"
    snapshot = _source_ohlcv_snapshot(manifest)
    assert snapshot["kind"] == "source_ohlcv_provenance"
    assert snapshot["dataset"] == {
        "exchange": market.exchange,
        "market_type": market.market_type,
        "symbol": market.symbol,
        "timeframe": market.timeframe,
    }
    assert snapshot["validation"]["status"] == "ok"  # type: ignore[index]
    assert snapshot["validation"]["fingerprint_fresh"] is True  # type: ignore[index]
    assert snapshot["validation"]["csv_fingerprint"]["size_bytes"] is not None  # type: ignore[index]
    assert snapshot["fingerprint"]["size_bytes"] is not None  # type: ignore[index]
    assert snapshot["source_correction"]["is_modified"] is False  # type: ignore[index]
    assert snapshot["source_correction"]["record_count"] == 0  # type: ignore[index]


def test_artifact_calculation_service_saves_volume_oscillator_with_configurable_mean_metadata(tmp_path):
    market, _ohlcv_path = _write_ohlcv(tmp_path)
    service = ArtifactCalculationService(historical_root=tmp_path)

    result = service.calculate_and_save(
        {
            "tool_type": "oscillator",
            "tool_key": "volume",
            "tool_title": "Volume",
            "exchange": market.exchange,
            "market_type": market.market_type,
            "symbol": market.symbol,
            "timeframe": market.timeframe,
            "params": {"period": 20},
            "input_bindings": {},
            "input_binding_meta": {},
        }
    )

    assert result.saved_path.exists()
    assert result.metadata_path.exists()
    assert result.saved_path.is_relative_to(tmp_path)
    assert result.instance_key == "volume__default__period-20"

    saved = pd.read_csv(result.saved_path)
    assert list(saved.columns) == ["ts_ms", "time", "timeframe", "volume", "volume_mean_20"]
    assert len(saved) == 40
    assert saved["volume"].tolist() == pytest.approx([10.0 + idx for idx in range(40)])
    assert saved["volume_mean_20"].iloc[:19].isna().all()
    assert saved["volume_mean_20"].iloc[19] == pytest.approx(sum(10.0 + idx for idx in range(20)) / 20.0)

    manifest = _load_manifest(result.saved_path)
    assert manifest.identity.artifact_family == "oscillator"
    assert manifest.identity.storage_family == "oscillators"
    assert manifest.tool is not None
    assert manifest.tool.tool_key == "volume"
    assert manifest.tool.params == {"period": 20}
    assert manifest.tool.params_status == "explicit"
    assert manifest.tool.bindings_status == "unknown"

    columns = {column.name: column for column in manifest.columns}
    assert columns["volume"].renderable is True
    assert columns["volume"].analysis_usable is True
    assert columns["volume_mean_20"].renderable is True
    assert columns["volume_mean_20"].analysis_usable is True


def test_artifact_calculation_service_requires_existing_ohlcv(tmp_path):
    service = ArtifactCalculationService(historical_root=tmp_path)

    with pytest.raises(PermissionError, match="not loadable"):
        service.calculate_and_save(
            {
                "tool_type": "indicator",
                "tool_key": "sma",
                "tool_title": "SMA",
                "exchange": "bybit",
                "market_type": "linear",
                "symbol": "BTCUSDT",
                "timeframe": "30m",
                "params": {"period": 5},
            }
        )


def test_artifact_calculation_service_allows_modified_ohlcv(tmp_path: Path) -> None:
    market, ohlcv_path = _write_ohlcv(tmp_path, validation_status="modified")
    _record_source_correction(ohlcv_path, market)
    service = ArtifactCalculationService(historical_root=tmp_path)

    result = service.calculate_and_save(_payload(market))

    assert result.saved_path.exists()
    manifest = _load_manifest(result.saved_path)
    snapshot = _source_ohlcv_snapshot(manifest)
    assert snapshot["validation"]["status"] == "modified"  # type: ignore[index]
    assert snapshot["source_correction"]["is_modified"] is True  # type: ignore[index]
    assert snapshot["source_correction"]["needs_source_recheck"] is True  # type: ignore[index]
    assert snapshot["source_correction"]["record_count"] == 1  # type: ignore[index]
    records = snapshot["source_correction"]["records"]  # type: ignore[index]
    assert records[0]["ts_ms"] == 1_700_000_000_000  # type: ignore[index]


@pytest.mark.parametrize("status", ["unknown", "error", "warning"])
def test_artifact_calculation_service_blocks_unaccepted_ohlcv_statuses(
    tmp_path: Path,
    status: str,
) -> None:
    market, _ohlcv_path = _write_ohlcv(tmp_path, validation_status=status)
    service = ArtifactCalculationService(historical_root=tmp_path)

    with pytest.raises(PermissionError, match="OHLCV Maintenance"):
        service.calculate_and_save(_payload(market))


def test_artifact_calculation_service_blocks_missing_ohlcv_metadata(tmp_path: Path) -> None:
    market, _ohlcv_path = _write_ohlcv(tmp_path, write_metadata=False)
    service = ArtifactCalculationService(historical_root=tmp_path)

    with pytest.raises(PermissionError, match="metadata sidecar"):
        service.calculate_and_save(_payload(market))


def test_artifact_calculation_service_blocks_stale_ohlcv_validation_fingerprint(
    tmp_path: Path,
) -> None:
    market, ohlcv_path = _write_ohlcv(tmp_path, validation_status="ok")
    ohlcv_path.write_text(
        ohlcv_path.read_text(encoding="utf-8") + "\n",
        encoding="utf-8",
    )
    service = ArtifactCalculationService(historical_root=tmp_path)

    with pytest.raises(PermissionError, match="changed after validation|stale"):
        service.calculate_and_save(_payload(market))
