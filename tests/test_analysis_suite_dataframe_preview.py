from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

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
from leonardo.data.historical.analysis_suite_dataframe_preview import (
    DEFAULT_PREVIEW_ROW_LIMIT,
    MAX_PREVIEW_ROW_LIMIT,
    AnalysisSuiteDataframePreviewService,
)
from leonardo.data.historical.paths import HistoricalPaths
from leonardo.data.historical.store_csv import Candle, CsvOHLCVStore
from leonardo.data.naming import canonicalize


def _market():
    return canonicalize("bybit", "linear", "BTCUSDT", "30m")


def _write_ohlcv(root: Path, market, *, row_count: int = 5, price_offset: float = 0.0) -> None:
    store = CsvOHLCVStore()
    path = store.file_path(HistoricalPaths(root=root).ensure_ohlcv_dir(market))
    candles = tuple(
        Candle(
            1000 * index,
            float(index) + price_offset,
            float(index) + 0.5 + price_offset,
            float(index) - 0.5 + price_offset,
            float(index) + 0.25 + price_offset,
            float(index) * 10.0,
        )
        for index in range(1, row_count + 1)
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
    row_count: int = 5,
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


def _complete_features(root: Path, market, *, row_count: int = 5):
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
        manifest_path=str(dataframe_path.parent / "manifest.json"),
        dataframe_path=str(dataframe_path),
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


def test_ready_dataset_head_preview_returns_bounded_json_safe_rows(tmp_path: Path) -> None:
    market = _market()
    _write_ohlcv(tmp_path, market, row_count=5)
    manifest = _save_database(
        tmp_path,
        display_name="BTCUSDT_30m_preview_head",
        features=_complete_features(tmp_path, market, row_count=5),
    )

    report = AnalysisSuiteDataframePreviewService(
        historical_root=tmp_path
    ).preview_dataframe(
        market=market,
        database_id=manifest.database_id,
        mode="head",
        row_limit=2,
    )

    assert report.status == "previewable"
    assert report.mode == "head"
    assert report.requested_limit == 2
    assert report.effective_limit == 2
    assert report.returned_row_count == 2
    assert report.total_row_count == 5
    assert report.preview_first_ts_ms == 1000
    assert report.preview_last_ts_ms == 2000
    assert report.dataset_first_ts_ms == 1000
    assert report.dataset_last_ts_ms == 5000
    assert report.columns[:3] == ("ts_ms", "ts_utc", "ts_rome")
    assert report.rows[0]["ts_ms"] == 1000
    assert "UTC" in str(report.rows[0]["ts_utc"])
    assert "Europe/Rome" in str(report.rows[0]["ts_rome"])
    json.dumps(report.to_dict(), sort_keys=True)


def test_ready_dataset_tail_preview_returns_last_rows_without_full_dataframe_load(tmp_path: Path) -> None:
    market = _market()
    _write_ohlcv(tmp_path, market, row_count=5)
    manifest = _save_database(
        tmp_path,
        display_name="BTCUSDT_30m_preview_tail",
        features=_complete_features(tmp_path, market, row_count=5),
    )

    report = AnalysisSuiteDataframePreviewService(
        historical_root=tmp_path
    ).preview_for_database(
        market=market,
        database_id=manifest.database_id,
        mode="tail",
        row_limit=2,
    )

    assert report.status == "previewable"
    assert report.mode == "tail"
    assert [row["ts_ms"] for row in report.rows] == [4000, 5000]
    assert report.total_row_count == 5
    assert report.preview_first_ts_ms == 4000
    assert report.preview_last_ts_ms == 5000


def test_row_limit_policy_clamps_and_defaults(tmp_path: Path) -> None:
    market = _market()
    _write_ohlcv(tmp_path, market, row_count=5)
    manifest = _save_database(
        tmp_path,
        display_name="BTCUSDT_30m_preview_limits",
        features=_complete_features(tmp_path, market, row_count=5),
    )
    service = AnalysisSuiteDataframePreviewService(historical_root=tmp_path)

    clamped = service.preview_dataframe(
        market=market,
        database_id=manifest.database_id,
        row_limit=999,
    )
    defaulted = service.preview_dataframe(
        market=market,
        database_id=manifest.database_id,
        row_limit=0,
    )

    assert clamped.requested_limit == 999
    assert clamped.effective_limit == MAX_PREVIEW_ROW_LIMIT
    assert "row_limit_clamped_to_max" in clamped.warnings
    assert defaulted.requested_limit == 0
    assert defaulted.effective_limit == DEFAULT_PREVIEW_ROW_LIMIT
    assert "row_limit_defaulted" in defaulted.warnings


def test_non_strict_but_previewable_dataset_preserves_readiness_diagnostics(tmp_path: Path) -> None:
    market = _market()
    _write_ohlcv(tmp_path, market, row_count=5)
    manifest = _save_database(
        tmp_path,
        display_name="BTCUSDT_30m_preview_incomplete",
        features=(),
    )

    report = AnalysisSuiteDataframePreviewService(
        historical_root=tmp_path
    ).preview_dataframe(
        market=market,
        database_id=manifest.database_id,
        row_limit=1,
    )

    assert report.status == "previewable"
    assert report.strict_ready is False
    assert report.can_preview is True
    assert report.readiness_status == "incomplete_topology"
    assert any("missing_topology" in blocker for blocker in report.blockers)


def test_blocked_preview_does_not_read_dataframe_when_as1_disallows_preview(tmp_path: Path) -> None:
    market = _market()
    database_id = "adb_blocked"
    store = AnalysisDatabaseStore(historical_root=tmp_path)
    dataframe_path = store.dataframe_path(market=market, database_id=database_id)
    readiness = _fake_report(
        database_id=database_id,
        dataframe_path=dataframe_path,
        can_preview=False,
        strict_ready=False,
        readiness_status="draft",
        blockers=("database_not_materialized",),
    )

    report = AnalysisSuiteDataframePreviewService(
        historical_root=tmp_path,
        readiness_service=_FakeReadinessService(readiness),
    ).preview_dataframe(
        market=market,
        database_id=database_id,
    )

    assert report.status == "blocked"
    assert report.returned_row_count == 0
    assert "database_not_materialized" in report.blockers
    assert "dataset_not_previewable" in report.blockers
    assert not dataframe_path.exists()


def test_unsupported_mode_returns_blocked_report(tmp_path: Path) -> None:
    market = _market()
    database_id = "adb_unsupported_mode"
    store = AnalysisDatabaseStore(historical_root=tmp_path)
    dataframe_path = store.dataframe_path(market=market, database_id=database_id)
    readiness = _fake_report(
        database_id=database_id,
        dataframe_path=dataframe_path,
        can_preview=True,
        strict_ready=True,
    )

    report = AnalysisSuiteDataframePreviewService(
        historical_root=tmp_path,
        readiness_service=_FakeReadinessService(readiness),
    ).preview_dataframe(
        market=market,
        database_id=database_id,
        mode="sample",
    )

    assert report.status == "blocked"
    assert report.mode == "sample"
    assert "unsupported_preview_mode" in report.blockers


def test_timestamp_formatting_and_absent_ts_ms_handling(tmp_path: Path) -> None:
    market = _market()
    database_id = "adb_no_ts"
    store = AnalysisDatabaseStore(historical_root=tmp_path)
    dataframe_path = store.dataframe_path(market=market, database_id=database_id)
    dataframe_path.parent.mkdir(parents=True, exist_ok=True)
    dataframe_path.write_text("feature,note\n1.0,alpha\n2.0,beta\n", encoding="utf-8")
    readiness = _fake_report(
        database_id=database_id,
        dataframe_path=dataframe_path,
        can_preview=True,
        strict_ready=True,
    )

    report = AnalysisSuiteDataframePreviewService(
        historical_root=tmp_path,
        readiness_service=_FakeReadinessService(readiness),
    ).preview_dataframe(
        market=market,
        database_id=database_id,
        row_limit=1,
    )

    assert report.status == "previewable"
    assert report.columns == ("feature", "note")
    assert report.preview_first_ts_ms is None
    assert report.preview_last_ts_ms is None
    assert "ts_utc" not in report.rows[0]
    assert "ts_rome" not in report.rows[0]


def test_json_safety_converts_empty_and_nan_cells_to_none(tmp_path: Path) -> None:
    market = _market()
    database_id = "adb_json_safe"
    store = AnalysisDatabaseStore(historical_root=tmp_path)
    dataframe_path = store.dataframe_path(market=market, database_id=database_id)
    dataframe_path.parent.mkdir(parents=True, exist_ok=True)
    dataframe_path.write_text("ts_ms,value,note\n1000,,NaN\n", encoding="utf-8")
    readiness = _fake_report(
        database_id=database_id,
        dataframe_path=dataframe_path,
        can_preview=True,
        strict_ready=True,
    )

    report = AnalysisSuiteDataframePreviewService(
        historical_root=tmp_path,
        readiness_service=_FakeReadinessService(readiness),
    ).preview_dataframe(
        market=market,
        database_id=database_id,
    )

    assert report.rows[0]["value"] is None
    assert report.rows[0]["note"] is None
    json.dumps(report.to_dict(), sort_keys=True)


def test_preview_service_static_boundaries() -> None:
    source = Path(
        "src/leonardo/data/historical/analysis_suite_dataframe_preview.py"
    ).read_text(encoding="utf-8")

    forbidden = (
        "PySide",
        "leonardo.gui",
        "ArtifactCalculationService",
        "ArtifactRecipeExecutor",
        "ArtifactRecoveryRegenerator",
        "DataManagerUpdateService",
        "DataManagerSelectedUpdateService",
        "DataManagerConstructBatchExecutionService",
        "AnalysisProjectStore",
        "AnalysisRunStore",
        "AnalysisReportStore",
        "materialize_database",
        "rebuild_database",
        "replace_database_features",
        "save_manifest",
        "write_text",
        "write_bytes",
        "json.dump",
        ".to_csv(",
        "load_dataframe(",
    )
    for pattern in forbidden:
        assert pattern not in source
    assert '.open("w' not in source
    assert ".open('w" not in source
