from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

from leonardo.data.historical.analysis_database_contracts import (
    AnalysisDatabaseColumn,
    AnalysisFeatureSource,
    AnalysisMetadataEntry,
)
from leonardo.data.historical.analysis_database_naming import (
    build_database_column_name,
    build_feature_source_id,
)
from leonardo.data.historical.analysis_database_store import AnalysisDatabaseStore
from leonardo.data.historical.analysis_suite_poi_family_planner import (
    AnalysisSuitePoiCondition,
    AnalysisSuitePoiDefinition,
    AnalysisSuitePoiFamilyDefinition,
    AnalysisSuitePoiFamilyPlanner,
    MAX_POI_SAMPLE_LIMIT,
)
from leonardo.data.naming import canonicalize


def _market():
    return canonicalize("bybit", "linear", "BTCUSDT", "30m")


def _metadata(key: str, value: object, *, namespace: str = "analysis_suite"):
    return AnalysisMetadataEntry(namespace=namespace, key=key, value=value)


def _source(*, family: str = "indicators", tool_key: str = "peaks_troughs") -> AnalysisFeatureSource:
    instance_key = f"{tool_key}__default"
    source_id = build_feature_source_id(
        family=family,
        tool_key=tool_key,
        instance_key=instance_key,
    )
    return AnalysisFeatureSource(
        source_id=source_id,
        family=family,  # type: ignore[arg-type]
        tool_key=tool_key,
        tool_title=tool_key.replace("_", " ").title(),
        instance_key=instance_key,
        source_artifact_filename=f"{instance_key}.csv",
        source_artifact_relpath=f"{family}/{instance_key}.csv",
        source_artifact_sha256="abc123",
        params_status="explicit",
        bindings_status="explicit",
    )


def _feature_column(
    source: AnalysisFeatureSource,
    *,
    column_name: str,
    analysis_usable: bool | None = True,
    renderable: bool | None = True,
    metadata=(),
) -> AnalysisDatabaseColumn:
    return AnalysisDatabaseColumn(
        role="feature",
        selected=True,
        source_family=source.family,  # type: ignore[arg-type]
        source_id=source.source_id,
        source_column_name=column_name,
        db_column_name=build_database_column_name(
            source_family=source.family,
            tool_key=source.tool_key,
            instance_key=source.instance_key,
            source_column_name=column_name,
        ),
        dtype="float64",
        nullable=True,
        analysis_usable=analysis_usable,
        renderable=renderable,
        metadata=tuple(metadata),
    )


def _save_manifest(
    root: Path,
    *,
    feature_sources=(),
    feature_columns=(),
):
    market = _market()
    store = AnalysisDatabaseStore(historical_root=root)
    manifest = store.build_draft_manifest(
        market=market,
        display_name="BTCUSDT_30m_poi_family",
        include_volume=True,
        feature_sources=tuple(feature_sources),
        feature_columns=tuple(feature_columns),
    )
    store.save_manifest(manifest, overwrite=False)
    return store, manifest


def _write_dataframe(path: Path, rows: int, **columns: list[object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data: dict[str, list[object]] = {
        "ts_ms": [1000 * index for index in range(1, rows + 1)],
        "open": [100.0 + index for index in range(rows)],
        "high": [101.0 + index for index in range(rows)],
        "low": [99.0 + index for index in range(rows)],
        "close": [100.5 + index for index in range(rows)],
        "volume": [1000.0 + index for index in range(rows)],
    }
    data.update(columns)
    pd.DataFrame(data).to_csv(path, index=False)


def _fake_readiness(
    *,
    database_id: str,
    dataframe_path: Path,
    can_preview: bool = True,
    strict_ready: bool = True,
    warnings=(),
    blockers=(),
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
        readiness_status="ready" if strict_ready else "incomplete_topology",
        strict_ready=strict_ready,
        can_preview=can_preview,
        warnings=tuple(warnings),
        blockers=tuple(blockers),
        errors=tuple(errors),
    )


class _FakeReadinessService:
    def __init__(self, report: object) -> None:
        self.report = report
        self.calls = 0

    def readiness_for_database(self, *, market, database_id: str):
        self.calls += 1
        return self.report


def _planner(root: Path, *, readiness: object) -> AnalysisSuitePoiFamilyPlanner:
    return AnalysisSuitePoiFamilyPlanner(
        historical_root=root,
        readiness_service=_FakeReadinessService(readiness),
    )


def _poi(source_column: str, *, event_kind: str = "sparse_event", event_value=None):
    return AnalysisSuitePoiDefinition(
        poi_key="t7_trough",
        poi_type="t7_trough",
        source_column=source_column,
        event_kind=event_kind,
        event_value=event_value,
        display_name="T7 trough",
    )


def test_sparse_event_poi_occurrence_detection(tmp_path: Path) -> None:
    source = _source(tool_key="peaks_troughs")
    trough = _feature_column(source, column_name="trough_fractal_7")
    store, manifest = _save_manifest(
        tmp_path,
        feature_sources=(source,),
        feature_columns=(trough,),
    )
    dataframe_path = store.dataframe_path(market=_market(), database_id=manifest.database_id)
    _write_dataframe(
        dataframe_path,
        6,
        **{trough.db_column_name: [None, 101.25, None, 99.5, 0.0, None]},
    )

    report = _planner(
        tmp_path,
        readiness=_fake_readiness(
            database_id=manifest.database_id,
            dataframe_path=dataframe_path,
        ),
    ).preview_poi_occurrences(
        market=_market(),
        database_id=manifest.database_id,
        poi_definition=_poi(trough.db_column_name),
    )

    assert report.status == "ready"
    assert report.row_count == 6
    assert report.occurrence_count == 2
    assert [item.ts_ms for item in report.sample_occurrences] == [2000, 4000]
    assert report.sample_occurrences[0].source_value == 101.25
    assert report.first_occurrence_ts_ms == 2000
    assert report.last_occurrence_ts_ms == 4000


def test_boolean_true_poi_occurrence_detection(tmp_path: Path) -> None:
    source = _source(tool_key="braids")
    event = _feature_column(source, column_name="braid_compressed")
    store, manifest = _save_manifest(
        tmp_path,
        feature_sources=(source,),
        feature_columns=(event,),
    )
    dataframe_path = store.dataframe_path(market=_market(), database_id=manifest.database_id)
    _write_dataframe(
        dataframe_path,
        5,
        **{event.db_column_name: [False, 1, 0, True, "yes"]},
    )

    report = _planner(
        tmp_path,
        readiness=_fake_readiness(
            database_id=manifest.database_id,
            dataframe_path=dataframe_path,
        ),
    ).preview_poi_occurrences(
        market=_market(),
        database_id=manifest.database_id,
        poi_definition=_poi(event.db_column_name, event_kind="boolean_true"),
    )

    assert report.occurrence_count == 3
    assert [item.ts_ms for item in report.sample_occurrences] == [2000, 4000, 5000]


def test_value_equals_poi_occurrence_detection(tmp_path: Path) -> None:
    source = _source(tool_key="universal_trend_classifier")
    state = _feature_column(source, column_name="utc_state", renderable=False)
    store, manifest = _save_manifest(
        tmp_path,
        feature_sources=(source,),
        feature_columns=(state,),
    )
    dataframe_path = store.dataframe_path(market=_market(), database_id=manifest.database_id)
    _write_dataframe(
        dataframe_path,
        5,
        **{state.db_column_name: ["range", "bullish", "bearish", "bullish", None]},
    )

    report = _planner(
        tmp_path,
        readiness=_fake_readiness(
            database_id=manifest.database_id,
            dataframe_path=dataframe_path,
        ),
    ).preview_poi_occurrences(
        market=_market(),
        database_id=manifest.database_id,
        poi_definition=_poi(
            state.db_column_name,
            event_kind="value_equals",
            event_value="bullish",
        ),
    )

    assert report.status == "ready"
    assert report.occurrence_count == 2
    assert [item.ts_ms for item in report.sample_occurrences] == [2000, 4000]


def test_transition_poi_occurrence_detection_tracks_previous_value(tmp_path: Path) -> None:
    source = _source(tool_key="universal_trend_classifier")
    state = _feature_column(source, column_name="utc_state", renderable=False)
    store, manifest = _save_manifest(
        tmp_path,
        feature_sources=(source,),
        feature_columns=(state,),
    )
    dataframe_path = store.dataframe_path(market=_market(), database_id=manifest.database_id)
    _write_dataframe(
        dataframe_path,
        6,
        **{state.db_column_name: ["bullish", "bearish", "bullish", "bullish", "range", "bullish"]},
    )

    report = _planner(
        tmp_path,
        readiness=_fake_readiness(
            database_id=manifest.database_id,
            dataframe_path=dataframe_path,
        ),
    ).preview_poi_occurrences(
        market=_market(),
        database_id=manifest.database_id,
        poi_definition=_poi(
            state.db_column_name,
            event_kind="transition",
            event_value="bullish",
        ),
    )

    assert report.occurrence_count == 2
    assert [item.ts_ms for item in report.sample_occurrences] == [3000, 6000]
    assert report.sample_occurrences[0].metadata["previous_value"] == "bearish"
    assert report.sample_occurrences[0].metadata["current_value"] == "bullish"


def test_family_condition_matching_same_row(tmp_path: Path) -> None:
    peaks = _source(tool_key="peaks_troughs")
    utc = _source(tool_key="universal_trend_classifier")
    trough = _feature_column(peaks, column_name="trough_fractal_7")
    utc_state = _feature_column(utc, column_name="utc_state", renderable=False)
    store, manifest = _save_manifest(
        tmp_path,
        feature_sources=(peaks, utc),
        feature_columns=(trough, utc_state),
    )
    dataframe_path = store.dataframe_path(market=_market(), database_id=manifest.database_id)
    _write_dataframe(
        dataframe_path,
        5,
        **{
            trough.db_column_name: [None, 101.0, 102.0, 103.0, None],
            utc_state.db_column_name: ["range", "bullish", "bearish", "bullish", "range"],
        },
    )
    family = AnalysisSuitePoiFamilyDefinition(
        family_key="t7_trough_bullish",
        display_name="T7 trough inside bullish UTC",
        poi_definition=_poi(trough.db_column_name),
        conditions=(
            AnalysisSuitePoiCondition(
                column=utc_state.db_column_name,
                operator="equals",
                value="bullish",
            ),
        ),
    )

    report = _planner(
        tmp_path,
        readiness=_fake_readiness(
            database_id=manifest.database_id,
            dataframe_path=dataframe_path,
        ),
    ).preview_family(
        market=_market(),
        database_id=manifest.database_id,
        family_definition=family,
    )

    assert report.status == "ready"
    assert report.occurrence_count == 3
    assert report.matched_count == 2
    assert report.unmatched_count == 1
    assert [item.matched for item in report.sample_memberships] == [True, False, True]
    assert report.sample_memberships[0].condition_results[0]["matched"] is True


def test_lookback_condition_matching_handles_early_rows(tmp_path: Path) -> None:
    peaks = _source(tool_key="peaks_troughs")
    setup_source = _source(tool_key="rsi")
    trough = _feature_column(peaks, column_name="trough_fractal_7")
    setup = _feature_column(setup_source, column_name="setup_score")
    store, manifest = _save_manifest(
        tmp_path,
        feature_sources=(peaks, setup_source),
        feature_columns=(trough, setup),
    )
    dataframe_path = store.dataframe_path(market=_market(), database_id=manifest.database_id)
    _write_dataframe(
        dataframe_path,
        5,
        **{
            trough.db_column_name: [101.0, 102.0, None, 103.0, None],
            setup.db_column_name: [5.0, 20.0, 22.0, 4.0, 30.0],
        },
    )
    family = AnalysisSuitePoiFamilyDefinition(
        family_key="t7_trough_prior_setup",
        display_name="T7 trough after prior setup",
        poi_definition=_poi(trough.db_column_name),
        conditions=(
            AnalysisSuitePoiCondition(
                column=setup.db_column_name,
                operator="gte",
                value=10.0,
                lookback_bars=1,
            ),
        ),
    )

    report = _planner(
        tmp_path,
        readiness=_fake_readiness(
            database_id=manifest.database_id,
            dataframe_path=dataframe_path,
        ),
    ).preview_family(
        market=_market(),
        database_id=manifest.database_id,
        family_definition=family,
    )

    assert report.occurrence_count == 3
    assert report.matched_count == 1
    assert "membership_condition_blockers_present" in report.warnings
    assert "condition_lookback_unavailable" in report.sample_memberships[0].blockers[0]
    assert report.sample_memberships[2].matched is True
    assert report.sample_memberships[2].condition_results[0]["row_index"] == 2


def test_missing_source_and_condition_columns_block_safely(tmp_path: Path) -> None:
    source = _source(tool_key="peaks_troughs")
    trough = _feature_column(source, column_name="trough_fractal_7")
    store, manifest = _save_manifest(
        tmp_path,
        feature_sources=(source,),
        feature_columns=(trough,),
    )
    dataframe_path = store.dataframe_path(market=_market(), database_id=manifest.database_id)
    _write_dataframe(dataframe_path, 3, **{trough.db_column_name: [None, 1.0, None]})
    planner = _planner(
        tmp_path,
        readiness=_fake_readiness(
            database_id=manifest.database_id,
            dataframe_path=dataframe_path,
        ),
    )

    missing_source = planner.preview_poi_occurrences(
        market=_market(),
        database_id=manifest.database_id,
        poi_definition=_poi("missing_poi_source"),
    )
    missing_condition = planner.preview_family(
        market=_market(),
        database_id=manifest.database_id,
        family_definition=AnalysisSuitePoiFamilyDefinition(
            family_key="missing_condition",
            display_name="Missing condition",
            poi_definition=_poi(trough.db_column_name),
            conditions=(
                AnalysisSuitePoiCondition(
                    column="missing_condition_column",
                    operator="equals",
                    value="x",
                ),
            ),
        ),
    )

    assert missing_source.status == "blocked"
    assert "poi_source_column_missing_from_manifest: missing_poi_source" in missing_source.blockers
    assert missing_condition.status == "blocked"
    assert (
        "condition_column_missing_from_manifest: missing_condition_column"
        in missing_condition.blockers
    )


def test_leakage_metadata_columns_are_rejected_for_poi_and_family_inputs(
    tmp_path: Path,
) -> None:
    source = _source(tool_key="sma")
    peaks = _source(tool_key="peaks_troughs")
    event = _feature_column(peaks, column_name="trough_fractal_7")
    target_only = _feature_column(
        source,
        column_name="target_like",
        metadata=(_metadata("leakage_role", "target_only"),),
    )
    future_derived = _feature_column(
        source,
        column_name="future_like",
        metadata=(_metadata("future_derived", True),),
    )
    not_feature = _feature_column(
        source,
        column_name="not_feature",
        metadata=(_metadata("feature_eligible", False),),
    )
    store, manifest = _save_manifest(
        tmp_path,
        feature_sources=(source, peaks),
        feature_columns=(event, target_only, future_derived, not_feature),
    )
    dataframe_path = store.dataframe_path(market=_market(), database_id=manifest.database_id)
    _write_dataframe(
        dataframe_path,
        3,
        **{
            event.db_column_name: [None, 1.0, None],
            target_only.db_column_name: [None, 1.0, None],
            future_derived.db_column_name: [1.0, 2.0, 3.0],
            not_feature.db_column_name: [1.0, 2.0, 3.0],
        },
    )
    planner = _planner(
        tmp_path,
        readiness=_fake_readiness(
            database_id=manifest.database_id,
            dataframe_path=dataframe_path,
        ),
    )

    poi_report = planner.preview_poi_occurrences(
        market=_market(),
        database_id=manifest.database_id,
        poi_definition=_poi(target_only.db_column_name),
    )
    family_report = planner.preview_family(
        market=_market(),
        database_id=manifest.database_id,
        family_definition=AnalysisSuitePoiFamilyDefinition(
            family_key="leakage_inputs",
            display_name="Leakage inputs",
            poi_definition=_poi(event.db_column_name),
            conditions=(
                AnalysisSuitePoiCondition(
                    column=future_derived.db_column_name,
                    operator="gte",
                    value=0,
                ),
                AnalysisSuitePoiCondition(
                    column=not_feature.db_column_name,
                    operator="gte",
                    value=0,
                ),
            ),
        ),
    )

    assert poi_report.status == "blocked"
    assert (
        f"poi_source_target_only_column_forbidden: {target_only.db_column_name}"
        in poi_report.blockers
    )
    assert family_report.status == "blocked"
    assert (
        f"condition_future_derived_column_forbidden: {future_derived.db_column_name}"
        in family_report.blockers
    )
    assert (
        f"condition_feature_eligible_false: {not_feature.db_column_name}"
        in family_report.blockers
    )


def test_readiness_and_diagnostic_gating(tmp_path: Path) -> None:
    source = _source(tool_key="peaks_troughs")
    trough = _feature_column(source, column_name="trough_fractal_7")
    store, manifest = _save_manifest(
        tmp_path,
        feature_sources=(source,),
        feature_columns=(trough,),
    )
    dataframe_path = store.dataframe_path(market=_market(), database_id=manifest.database_id)
    _write_dataframe(dataframe_path, 3, **{trough.db_column_name: [None, 1.0, None]})

    blocked = _planner(
        tmp_path,
        readiness=_fake_readiness(
            database_id=manifest.database_id,
            dataframe_path=dataframe_path,
            can_preview=False,
            strict_ready=False,
            blockers=("database_not_materialized",),
        ),
    ).preview_poi_occurrences(
        market=_market(),
        database_id=manifest.database_id,
        poi_definition=_poi(trough.db_column_name),
    )
    allowed = _planner(
        tmp_path,
        readiness=_fake_readiness(
            database_id=manifest.database_id,
            dataframe_path=dataframe_path,
            can_preview=True,
            strict_ready=False,
            warnings=("missing_topology: utc",),
            blockers=("source_ohlcv_drift: stale",),
        ),
    ).preview_poi_occurrences(
        market=_market(),
        database_id=manifest.database_id,
        poi_definition=_poi(trough.db_column_name),
    )
    diagnostic_blocked = AnalysisSuitePoiFamilyPlanner(
        historical_root=tmp_path,
    ).preview_poi_occurrences(
        market=_market(),
        database_id=manifest.database_id,
        poi_definition=_poi(trough.db_column_name),
        diagnostic_report=SimpleNamespace(
            database_id=manifest.database_id,
            display_name=manifest.display_name,
            exchange=_market().exchange,
            market_type=_market().market_type,
            symbol=_market().symbol,
            timeframe=_market().timeframe,
            dataframe_path=str(dataframe_path),
            manifest_path=str(store.manifest_path(market=_market(), database_id=manifest.database_id)),
            readiness_status="ready",
            strict_ready=True,
            can_preview=True,
            status="blocked",
            has_leakage_blockers=False,
            warnings=(),
            blockers=("upstream_blocker",),
            errors=(),
        ),  # type: ignore[arg-type]
    )

    assert blocked.status == "blocked"
    assert "dataset_not_previewable" in blocked.blockers
    assert allowed.status == "warning"
    assert allowed.occurrence_count == 1
    assert "dataset_not_strict_ready" in allowed.warnings
    assert "source_ohlcv_drift: stale" in allowed.blockers
    assert diagnostic_blocked.status == "blocked"
    assert "diagnostic_report_not_acceptable: blocked" in diagnostic_blocked.blockers


def test_bounded_samples_preserve_total_counts(tmp_path: Path) -> None:
    source = _source(tool_key="peaks_troughs")
    event = _feature_column(source, column_name="peak_fractal_7")
    store, manifest = _save_manifest(
        tmp_path,
        feature_sources=(source,),
        feature_columns=(event,),
    )
    dataframe_path = store.dataframe_path(market=_market(), database_id=manifest.database_id)
    rows = 700
    _write_dataframe(dataframe_path, rows, **{event.db_column_name: [1.0] * rows})
    planner = _planner(
        tmp_path,
        readiness=_fake_readiness(
            database_id=manifest.database_id,
            dataframe_path=dataframe_path,
        ),
    )

    default_report = planner.preview_poi_occurrences(
        market=_market(),
        database_id=manifest.database_id,
        poi_definition=_poi(event.db_column_name),
    )
    clamped_report = planner.preview_poi_occurrences(
        market=_market(),
        database_id=manifest.database_id,
        poi_definition=_poi(event.db_column_name),
        sample_limit=999,
    )

    assert default_report.occurrence_count == rows
    assert len(default_report.sample_occurrences) == 100
    assert clamped_report.occurrence_count == rows
    assert clamped_report.sample_limit == MAX_POI_SAMPLE_LIMIT
    assert len(clamped_report.sample_occurrences) == MAX_POI_SAMPLE_LIMIT
    assert "sample_limit_clamped_to_max" in clamped_report.warnings


def test_report_to_dict_is_json_safe(tmp_path: Path) -> None:
    source = _source(tool_key="peaks_troughs")
    event = _feature_column(source, column_name="peak_fractal_7")
    store, manifest = _save_manifest(
        tmp_path,
        feature_sources=(source,),
        feature_columns=(event,),
    )
    dataframe_path = store.dataframe_path(market=_market(), database_id=manifest.database_id)
    _write_dataframe(dataframe_path, 4, **{event.db_column_name: [None, 1.0, float("nan"), 2.0]})

    report = _planner(
        tmp_path,
        readiness=_fake_readiness(
            database_id=manifest.database_id,
            dataframe_path=dataframe_path,
        ),
    ).preview_family(
        market=_market(),
        database_id=manifest.database_id,
        family_definition=AnalysisSuitePoiFamilyDefinition(
            family_key="json_safe",
            display_name="JSON safe",
            poi_definition=_poi(event.db_column_name),
            conditions=(),
        ),
    )

    payload = report.to_dict()
    json.dumps(payload, sort_keys=True)
    assert payload["occurrence_count"] == 2
    assert payload["matched_count"] == 2


def test_static_boundary_rules() -> None:
    source = Path(
        "src/leonardo/data/historical/analysis_suite_poi_family_planner.py"
    ).read_text(encoding="utf-8")

    forbidden_terms = (
        "PySide",
        "QtWidgets",
        "QWidget",
        "QDialog",
        "QMainWindow",
        "leonardo.gui",
        "AnalysisProjectStore",
        "AnalysisRunStore",
        "AnalysisReportStore",
        "FeatureSetStore",
        "ArtifactCalculationService",
        "ArtifactRecipeExecutor",
        "DataManagerUpdateService",
        "DataManagerSelectedUpdateService",
        "DataManagerConstructBatchExecutionService",
        "materialize_database",
        "build_database",
        "rebuild",
        "execute_recipe",
        "save_manifest",
        "write_text",
        "write_bytes",
        "json.dump",
        ".to_csv",
        "backtest",
        "white-box",
        "neural",
        "RL Decisor",
    )
    for term in forbidden_terms:
        assert term not in source
