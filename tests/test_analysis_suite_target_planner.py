from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from leonardo.data.historical.analysis_database_contracts import (
    AnalysisDatabaseColumn,
    AnalysisFeatureSource,
)
from leonardo.data.historical.analysis_database_naming import (
    build_database_column_name,
    build_feature_source_id,
)
from leonardo.data.historical.analysis_database_store import AnalysisDatabaseStore
from leonardo.data.historical.analysis_suite_target_planner import (
    AnalysisSuiteTargetDefinition,
    AnalysisSuiteTargetPlanner,
)
from leonardo.data.historical.paths import HistoricalPaths
from leonardo.data.historical.store_csv import Candle, CsvOHLCVStore
from leonardo.data.naming import canonicalize


def _market():
    return canonicalize("bybit", "linear", "BTCUSDT", "30m")


def _write_ohlcv(root: Path, market, closes: tuple[float, ...]) -> None:
    store = CsvOHLCVStore()
    path = store.file_path(HistoricalPaths(root=root).ensure_ohlcv_dir(market))
    candles = tuple(
        Candle(
            1000 * index,
            max(close - 0.25, 0.0),
            close + 1.0,
            max(close - 1.0, 0.0),
            close,
            float(index) * 10.0,
        )
        for index, close in enumerate(closes, start=1)
    )
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
    row_count: int,
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
            "ts_ms": [1000 * index for index in range(1, row_count + 1)],
            column_name: [float(index) for index in range(1, row_count + 1)],
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


def _complete_features(root: Path, market, *, row_count: int):
    return (
        _feature(
            root,
            market,
            family="oscillators",
            tool_key="volume",
            column_name="volume_signal",
            row_count=row_count,
        ),
        _feature(
            root,
            market,
            family="constructs",
            tool_key="braids",
            column_name="braid_width",
            row_count=row_count,
        ),
        _feature(
            root,
            market,
            family="indicators",
            tool_key="peaks_troughs",
            column_name="peak_fractal_5",
            row_count=row_count,
        ),
        _feature(
            root,
            market,
            family="indicators",
            tool_key="universal_trend_classifier",
            column_name="trend_state",
            row_count=row_count,
        ),
    )


def _save_database(
    root: Path,
    *,
    closes: tuple[float, ...],
    display_name: str,
    complete_topology: bool = True,
):
    market = _market()
    _write_ohlcv(root, market, closes)
    features = _complete_features(root, market, row_count=len(closes)) if complete_topology else ()
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
    return store.materialize_database(market=market, database_id=manifest.database_id)


class _FakeReadinessService:
    def __init__(self, report: object) -> None:
        self.report = report
        self.calls = 0

    def readiness_for_database(self, *, market, database_id: str):
        self.calls += 1
        return self.report


def _fake_report(
    *,
    database_id: str,
    dataframe_path: Path,
    can_preview: bool,
    strict_ready: bool,
    readiness_status: str = "ready",
    blockers=(),
    warnings=(),
    errors=(),
):
    market = _market()
    return SimpleNamespace(
        database_id=database_id,
        display_name=database_id,
        exchange=market.exchange,
        market_type=market.market_type,
        symbol=market.symbol,
        timeframe=market.timeframe,
        dataframe_path=str(dataframe_path),
        manifest_path=str(dataframe_path.parent / "manifest.json"),
        readiness_status=readiness_status,
        strict_ready=strict_ready,
        can_preview=can_preview,
        row_count=None,
        column_count=None,
        first_ts_ms=None,
        last_ts_ms=None,
        warnings=tuple(warnings),
        blockers=tuple(blockers),
        errors=tuple(errors),
    )


def test_future_return_regression_aligns_labels_to_current_timestamp(tmp_path: Path) -> None:
    market = _market()
    manifest = _save_database(
        tmp_path,
        closes=(100.0, 110.0, 121.0, 100.0, 90.0),
        display_name="BTCUSDT_30m_target_return",
    )

    report = AnalysisSuiteTargetPlanner(historical_root=tmp_path).preview_future_return(
        market=market,
        database_id=manifest.database_id,
        horizon_bars=2,
        preview_limit=10,
    )

    assert report.status == "previewable"
    assert report.row_count == 5
    assert report.available_label_count == 3
    assert report.unavailable_label_count == 2
    assert report.first_available_ts_ms == 1000
    assert report.last_available_ts_ms == 3000
    assert report.target_definition.output_column_name == "target_future_return_2"

    rows = report.sample_rows
    assert [row["ts_ms"] for row in rows] == [1000, 2000, 3000, 4000, 5000]
    assert [row["label_ts_ms"] for row in rows] == [1000, 2000, 3000, 4000, 5000]
    assert [row["label_end_ts_ms"] for row in rows] == [3000, 4000, 5000, None, None]
    assert rows[0]["target_future_return_2"] == pytest.approx(0.21)
    assert rows[1]["target_future_return_2"] == pytest.approx(-10.0 / 110.0)
    assert rows[2]["target_future_return_2"] == pytest.approx(-31.0 / 121.0)
    assert rows[3]["label_available"] is False
    assert rows[3]["target_future_return_2"] is None
    assert report.regression_stats["count"] == 3
    assert report.regression_stats["max"] == pytest.approx(0.21)
    assert report.regression_stats["min"] == pytest.approx(-31.0 / 121.0)
    assert report.regression_stats["mean"] == pytest.approx(
        (0.21 + (-10.0 / 110.0) + (-31.0 / 121.0)) / 3.0
    )
    json.dumps(report.to_dict(), sort_keys=True)


def test_future_direction_classification_thresholds_and_distribution(tmp_path: Path) -> None:
    market = _market()
    manifest = _save_database(
        tmp_path,
        closes=(100.0, 110.0, 100.0, 100.0, 120.0),
        display_name="BTCUSDT_30m_target_direction",
    )

    report = AnalysisSuiteTargetPlanner(historical_root=tmp_path).preview_future_direction(
        market=market,
        database_id=manifest.database_id,
        horizon_bars=1,
        up_threshold=0.05,
        down_threshold=0.05,
        preview_limit=10,
    )

    assert report.status == "previewable"
    assert [
        row["target_future_direction_1"] for row in report.sample_rows
    ] == ["up", "down", "flat", "up", "unavailable"]
    assert [row["label_available"] for row in report.sample_rows] == [
        True,
        True,
        True,
        True,
        False,
    ]
    assert report.class_distribution == {
        "up": 2,
        "down": 1,
        "flat": 1,
        "unavailable": 1,
    }
    json.dumps(report.to_dict(), sort_keys=True)


def test_horizon_validation_blocks_invalid_and_useless_definitions(tmp_path: Path) -> None:
    market = _market()
    manifest = _save_database(
        tmp_path,
        closes=(100.0, 101.0),
        display_name="BTCUSDT_30m_target_horizon",
    )
    planner = AnalysisSuiteTargetPlanner(historical_root=tmp_path)

    invalid = planner.preview_future_return(
        market=market,
        database_id=manifest.database_id,
        horizon_bars=0,
    )
    too_long = planner.preview_future_return(
        market=market,
        database_id=manifest.database_id,
        horizon_bars=2,
    )

    assert invalid.status == "blocked"
    assert "horizon_bars_must_be_positive" in invalid.blockers
    assert too_long.status == "blocked"
    assert "insufficient_rows_for_horizon" in too_long.blockers


def test_missing_required_columns_block_target_preview(tmp_path: Path) -> None:
    market = _market()
    store = AnalysisDatabaseStore(historical_root=tmp_path)
    missing_close_path = store.dataframe_path(market=market, database_id="missing_close")
    missing_close_path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame({"ts_ms": [1000, 2000]}).to_csv(missing_close_path, index=False)
    missing_ts_path = store.dataframe_path(market=market, database_id="missing_ts")
    missing_ts_path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame({"close": [100.0, 101.0]}).to_csv(missing_ts_path, index=False)

    close_report = _fake_report(
        database_id="missing_close",
        dataframe_path=missing_close_path,
        can_preview=True,
        strict_ready=True,
    )
    ts_report = _fake_report(
        database_id="missing_ts",
        dataframe_path=missing_ts_path,
        can_preview=True,
        strict_ready=True,
    )

    close_result = AnalysisSuiteTargetPlanner(
        historical_root=tmp_path,
        readiness_service=_FakeReadinessService(close_report),
    ).preview_future_return(
        market=market,
        database_id="missing_close",
        horizon_bars=1,
    )
    ts_result = AnalysisSuiteTargetPlanner(
        historical_root=tmp_path,
        readiness_service=_FakeReadinessService(ts_report),
    ).preview_future_return(
        market=market,
        database_id="missing_ts",
        horizon_bars=1,
    )

    assert close_result.status == "blocked"
    assert "missing_required_target_column: close" in close_result.blockers
    assert ts_result.status == "blocked"
    assert "missing_required_target_column: ts_ms" in ts_result.blockers


def test_invalid_close_denominator_marks_affected_labels_unavailable(tmp_path: Path) -> None:
    market = _market()
    manifest = _save_database(
        tmp_path,
        closes=(100.0, 0.0, 120.0, 130.0),
        display_name="BTCUSDT_30m_target_zero_close",
    )

    report = AnalysisSuiteTargetPlanner(historical_root=tmp_path).preview_future_return(
        market=market,
        database_id=manifest.database_id,
        horizon_bars=1,
        preview_limit=10,
    )

    assert report.status == "previewable"
    assert report.available_label_count == 2
    assert report.unavailable_label_count == 2
    assert "invalid_close_denominator_count: 1" in report.warnings
    assert report.sample_rows[1]["ts_ms"] == 2000
    assert report.sample_rows[1]["label_available"] is False
    assert report.sample_rows[1]["target_future_return_1"] is None


def test_readiness_gating_blocks_non_previewable_and_preserves_non_strict_diagnostics(tmp_path: Path) -> None:
    market = _market()
    store = AnalysisDatabaseStore(historical_root=tmp_path)
    blocked_path = store.dataframe_path(market=market, database_id="blocked_db")
    previewable_path = store.dataframe_path(market=market, database_id="previewable_db")
    previewable_path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame({"ts_ms": [1000, 2000, 3000], "close": [100.0, 101.0, 102.0]}).to_csv(
        previewable_path,
        index=False,
    )

    blocked_report = _fake_report(
        database_id="blocked_db",
        dataframe_path=blocked_path,
        can_preview=False,
        strict_ready=False,
        readiness_status="draft",
        blockers=("database_not_materialized",),
    )
    blocked = AnalysisSuiteTargetPlanner(
        historical_root=tmp_path,
        readiness_service=_FakeReadinessService(blocked_report),
    ).preview_future_return(
        market=market,
        database_id="blocked_db",
        horizon_bars=1,
    )

    previewable_report = _fake_report(
        database_id="previewable_db",
        dataframe_path=previewable_path,
        can_preview=True,
        strict_ready=False,
        readiness_status="incomplete_topology",
        blockers=("missing_topology: utc",),
        warnings=("source_warning",),
    )
    previewable = AnalysisSuiteTargetPlanner(
        historical_root=tmp_path,
        readiness_service=_FakeReadinessService(previewable_report),
    ).preview_future_return(
        market=market,
        database_id="previewable_db",
        horizon_bars=1,
    )

    assert blocked.status == "blocked"
    assert "dataset_not_previewable" in blocked.blockers
    assert "database_not_materialized" in blocked.blockers
    assert previewable.status == "previewable"
    assert previewable.strict_ready is False
    assert "source_warning" in previewable.warnings
    assert "dataset_not_strict_ready" in previewable.warnings
    assert "missing_topology: utc" in previewable.blockers


def test_leakage_metadata_marks_target_outputs_as_not_feature_eligible(tmp_path: Path) -> None:
    market = _market()
    manifest = _save_database(
        tmp_path,
        closes=(100.0, 110.0, 120.0),
        display_name="BTCUSDT_30m_target_leakage",
    )

    report = AnalysisSuiteTargetPlanner(historical_root=tmp_path).preview_future_return(
        market=market,
        database_id=manifest.database_id,
        horizon_bars=1,
    )

    assert report.leakage_summary["leakage_role"] == "target_only"
    assert report.leakage_summary["future_derived"] is True
    assert report.leakage_summary["feature_eligible"] is False
    assert report.leakage_summary["source_columns"] == ["ts_ms", "close"]
    assert report.leakage_summary["horizon_bars"] == 1
    assert report.target_definition.leakage_role == "target_only"
    assert report.target_definition.future_derived is True
    assert report.target_definition.feature_eligible is False


def test_direction_defaults_down_threshold_with_report_warning(tmp_path: Path) -> None:
    market = _market()
    manifest = _save_database(
        tmp_path,
        closes=(100.0, 110.0, 100.0),
        display_name="BTCUSDT_30m_target_threshold_default",
    )

    report = AnalysisSuiteTargetPlanner(historical_root=tmp_path).preview_future_direction(
        market=market,
        database_id=manifest.database_id,
        horizon_bars=1,
        up_threshold=0.05,
    )

    assert report.status == "previewable"
    assert "down_threshold_defaulted_to_up_threshold" in report.warnings
    assert report.sample_rows[0]["target_future_direction_1"] == "up"
    assert report.sample_rows[1]["target_future_direction_1"] == "down"


def test_target_preview_boundary_static_checks() -> None:
    source = Path("src/leonardo/data/historical/analysis_suite_target_planner.py").read_text(
        encoding="utf-8"
    )

    forbidden = (
        "PySide",
        "leonardo.gui",
        "write_text",
        "write_bytes",
        "json.dump",
        "open(",
        "to_csv",
        "save_manifest",
        "materialize_database",
        "ArtifactCalculationService",
        "ArtifactRecipeExecutor",
        "DataManagerUpdateService",
        "AnalysisProjectStore",
        "AnalysisRunStore",
        "AnalysisReportStore",
    )
    for pattern in forbidden:
        assert pattern not in source
