from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from leonardo.data.historical.analysis_database_contracts import (
    AnalysisDatabaseColumn,
    AnalysisFeatureSource,
)
from leonardo.data.historical.analysis_database_naming import (
    build_database_column_name,
    build_feature_source_id,
)
from leonardo.data.historical.analysis_database_store import AnalysisDatabaseStore
from leonardo.data.historical.analysis_dataset_geography import (
    GEOGRAPHY_KEY_BRAIDS,
    GEOGRAPHY_KEY_PEAKS_TROUGHS,
    GEOGRAPHY_KEY_UTC,
    GEOGRAPHY_KEY_VOLUME_ARTIFACT,
)
from leonardo.data.historical.analysis_suite_dataset_readiness import (
    AnalysisSuiteDatasetReadinessService,
)
from leonardo.data.historical.paths import HistoricalPaths
from leonardo.data.historical.store_csv import Candle, CsvOHLCVStore
from leonardo.data.naming import canonicalize


def _market():
    return canonicalize("bybit", "linear", "BTCUSDT", "30m")


def _write_ohlcv(root: Path, market, *, price_offset: float = 0.0) -> None:
    store = CsvOHLCVStore()
    path = store.file_path(HistoricalPaths(root=root).ensure_ohlcv_dir(market))
    candles = [
        Candle(1000, 1.0 + price_offset, 1.5 + price_offset, 0.5, 1.2, 10.0),
        Candle(2000, 2.0 + price_offset, 2.5 + price_offset, 1.5, 2.2, 20.0),
        Candle(3000, 3.0 + price_offset, 3.5 + price_offset, 2.5, 3.2, 30.0),
    ]
    store.write_atomic(path, candles, market=market)
    store.record_validation_result(
        path,
        market=market,
        status="ok",
        row_count=len(candles),
        issues=(),
        validator="HistoricalDatasetValidator",
    )


def _feature(
    root: Path,
    market,
    *,
    family: str,
    tool_key: str,
    column_name: str,
) -> tuple[AnalysisFeatureSource, AnalysisDatabaseColumn]:
    instance_key = f"{tool_key}__default"
    artifact_path = (
        root
        / market.exchange
        / market.market_type
        / market.symbol
        / market.timeframe
        / family
        / f"{instance_key}.csv"
    )
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        {
            "ts_ms": [1000, 2000, 3000],
            column_name: [1.0, 2.0, 3.0],
        }
    ).to_csv(artifact_path, index=False)

    source_id = build_feature_source_id(
        family=family,
        tool_key=tool_key,
        instance_key=instance_key,
    )
    source = AnalysisFeatureSource(
        source_id=source_id,
        family=family,  # type: ignore[arg-type]
        tool_key=tool_key,
        tool_title=tool_key.replace("_", " ").title(),
        instance_key=instance_key,
        source_artifact_filename=f"{instance_key}.csv",
        source_artifact_relpath=f"{family}/{instance_key}.csv",
        params_status="inferred",
    )
    column = AnalysisDatabaseColumn(
        role="feature",
        selected=True,
        source_family=family,  # type: ignore[arg-type]
        source_id=source_id,
        source_column_name=column_name,
        db_column_name=build_database_column_name(
            source_family=family,
            tool_key=tool_key,
            instance_key=instance_key,
            source_column_name=column_name,
        ),
        dtype="float64",
        nullable=True,
        analysis_usable=True,
        renderable=True,
    )
    return source, column


def _complete_features(root: Path, market):
    return (
        _feature(
            root,
            market,
            family="oscillators",
            tool_key="volume",
            column_name="volume_signal",
        ),
        _feature(
            root,
            market,
            family="constructs",
            tool_key="braids",
            column_name="braid_width",
        ),
        _feature(
            root,
            market,
            family="indicators",
            tool_key="peaks_troughs",
            column_name="peak_fractal_5",
        ),
        _feature(
            root,
            market,
            family="indicators",
            tool_key="universal_trend_classifier",
            column_name="trend_state",
        ),
    )


def _save_database(
    root: Path,
    *,
    display_name: str,
    features=(),
    materialize: bool = True,
):
    market = _market()
    store = AnalysisDatabaseStore(historical_root=root)
    sources = tuple(source for source, _column in features)
    columns = tuple(column for _source, column in features)
    manifest = store.build_draft_manifest(
        market=market,
        display_name=display_name,
        include_volume=False,
        feature_sources=sources,
        feature_columns=columns,
    )
    store.save_manifest(manifest, overwrite=False)
    if materialize:
        return store.materialize_database(
            market=market,
            database_id=manifest.database_id,
        )
    return manifest


def test_ready_materialized_analysis_database_reports_strict_ready(tmp_path: Path) -> None:
    market = _market()
    _write_ohlcv(tmp_path, market)
    manifest = _save_database(
        tmp_path,
        display_name="BTCUSDT_30m_as_ready",
        features=_complete_features(tmp_path, market),
    )

    service = AnalysisSuiteDatasetReadinessService(historical_root=tmp_path)
    report = service.readiness_for_database(
        market=market,
        database_id=manifest.database_id,
    )
    catalog = service.list_analysis_datasets(market=market)

    assert report.readiness_status == "ready"
    assert report.strict_ready is True
    assert report.can_preview is True
    assert report.row_count == 3
    assert report.column_count == 9
    assert report.first_ts_ms == 1000
    assert report.last_ts_ms == 3000
    assert report.source_ohlcv_drift_status == "current"
    assert report.geography_status == "complete"
    assert report.missing_topology == ()
    assert catalog.total_count == 1
    assert catalog.ready_count == 1
    json.dumps(report.to_dict(), sort_keys=True)
    json.dumps(catalog.to_dict(), sort_keys=True)


def test_draft_database_is_reported_without_materializing(tmp_path: Path) -> None:
    market = _market()
    _write_ohlcv(tmp_path, market)
    manifest = _save_database(
        tmp_path,
        display_name="BTCUSDT_30m_as_draft",
        features=_complete_features(tmp_path, market),
        materialize=False,
    )

    service = AnalysisSuiteDatasetReadinessService(historical_root=tmp_path)
    report = service.readiness_for_database(
        market=market,
        database_id=manifest.database_id,
    )
    dataframe_path = AnalysisDatabaseStore(historical_root=tmp_path).dataframe_path(
        market=market,
        database_id=manifest.database_id,
    )

    assert report.readiness_status == "draft"
    assert report.strict_ready is False
    assert report.can_preview is False
    assert report.dataframe_status == "not_materialized"
    assert report.source_ohlcv_drift_status == "not_checked"
    assert not dataframe_path.exists()


def test_missing_topology_is_not_strict_ready(tmp_path: Path) -> None:
    market = _market()
    _write_ohlcv(tmp_path, market)
    manifest = _save_database(
        tmp_path,
        display_name="BTCUSDT_30m_as_incomplete",
        features=(),
    )

    report = AnalysisSuiteDatasetReadinessService(
        historical_root=tmp_path
    ).readiness_for_database(market=market, database_id=manifest.database_id)

    assert report.readiness_status == "incomplete_topology"
    assert report.strict_ready is False
    assert report.can_preview is True
    assert GEOGRAPHY_KEY_VOLUME_ARTIFACT in report.missing_topology
    assert GEOGRAPHY_KEY_BRAIDS in report.missing_topology
    assert GEOGRAPHY_KEY_PEAKS_TROUGHS in report.missing_topology
    assert GEOGRAPHY_KEY_UTC in report.missing_topology


def test_source_ohlcv_drift_is_reported_as_stale(tmp_path: Path) -> None:
    market = _market()
    _write_ohlcv(tmp_path, market)
    manifest = _save_database(
        tmp_path,
        display_name="BTCUSDT_30m_as_stale",
        features=_complete_features(tmp_path, market),
    )
    _write_ohlcv(tmp_path, market, price_offset=1_000_000.0)

    report = AnalysisSuiteDatasetReadinessService(
        historical_root=tmp_path
    ).readiness_for_database(market=market, database_id=manifest.database_id)

    assert report.readiness_status == "stale_source"
    assert report.strict_ready is False
    assert report.source_ohlcv_drift_status == "source_drift"
    assert any("source_ohlcv_drift" in blocker for blocker in report.blockers)


def test_corrupt_manifest_is_exposed_in_catalog(tmp_path: Path) -> None:
    market = _market()
    manifest_path = (
        tmp_path
        / market.exchange
        / market.market_type
        / market.symbol
        / market.timeframe
        / "analysis_databases"
        / "adb__bad_manifest"
        / "manifest.json"
    )
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text("{not-json", encoding="utf-8")

    catalog = AnalysisSuiteDatasetReadinessService(
        historical_root=tmp_path
    ).list_analysis_datasets(market=market)

    assert catalog.total_count == 1
    assert catalog.error_count == 1
    assert catalog.items[0].readiness_status == "corrupt_manifest"
    assert catalog.items[0].database_id == "adb__bad_manifest"
    assert catalog.items[0].strict_ready is False


def test_missing_dataframe_is_blocked(tmp_path: Path) -> None:
    market = _market()
    _write_ohlcv(tmp_path, market)
    manifest = _save_database(
        tmp_path,
        display_name="BTCUSDT_30m_as_missing_dataframe",
        features=_complete_features(tmp_path, market),
    )
    dataframe_path = AnalysisDatabaseStore(historical_root=tmp_path).dataframe_path(
        market=market,
        database_id=manifest.database_id,
    )
    dataframe_path.unlink()

    report = AnalysisSuiteDatasetReadinessService(
        historical_root=tmp_path
    ).readiness_for_database(market=market, database_id=manifest.database_id)

    assert report.readiness_status == "missing_dataframe"
    assert report.strict_ready is False
    assert report.can_preview is False
    assert report.dataframe_status == "missing"


def test_dataframe_hash_mismatch_is_corrupt_dataframe(tmp_path: Path) -> None:
    market = _market()
    _write_ohlcv(tmp_path, market)
    manifest = _save_database(
        tmp_path,
        display_name="BTCUSDT_30m_as_corrupt_dataframe",
        features=_complete_features(tmp_path, market),
    )
    dataframe_path = AnalysisDatabaseStore(historical_root=tmp_path).dataframe_path(
        market=market,
        database_id=manifest.database_id,
    )
    dataframe_path.write_text(
        dataframe_path.read_text(encoding="utf-8") + "\n",
        encoding="utf-8",
    )

    report = AnalysisSuiteDatasetReadinessService(
        historical_root=tmp_path
    ).readiness_for_database(market=market, database_id=manifest.database_id)

    assert report.readiness_status == "corrupt_dataframe"
    assert report.strict_ready is False
    assert report.can_preview is False
    assert "dataframe_hash_mismatch" in report.blockers


def test_service_boundary_is_read_only_and_non_gui() -> None:
    source = Path(
        "src/leonardo/data/historical/analysis_suite_dataset_readiness.py"
    ).read_text(encoding="utf-8")

    forbidden = (
        "PySide",
        "leonardo.gui",
        "ArtifactCalculationService",
        "ArtifactRecipeExecutor",
        "write_text",
        "write_bytes",
        "json.dump",
        ".to_csv(",
        "materialize_database(",
        "rebuild_database_with_features",
        "replace_database_features",
        "save_manifest(",
        "CoreBridge",
        "AnalysisProjectStore",
        "AnalysisRunStore",
        "AnalysisReportStore",
    )
    for pattern in forbidden:
        assert pattern not in source
    assert '.open("w' not in source
    assert ".open('w" not in source
