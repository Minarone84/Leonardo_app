from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

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
from leonardo.data.historical.analysis_suite_feature_set_planner import (
    AnalysisSuiteFeatureSetPlanner,
)
from leonardo.data.historical.analysis_suite_target_planner import (
    AnalysisSuiteTargetDefinition,
)
from leonardo.data.naming import canonicalize


def _market():
    return canonicalize("bybit", "linear", "BTCUSDT", "30m")


def _fake_readiness(
    *,
    database_id: str,
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


def _metadata(key: str, value: object, *, namespace: str = "analysis_suite"):
    return AnalysisMetadataEntry(namespace=namespace, key=key, value=value)


def _source(*, family: str, tool_key: str, metadata=()) -> AnalysisFeatureSource:
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
        metadata=tuple(metadata),
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


def _unknown_feature_column() -> AnalysisDatabaseColumn:
    return AnalysisDatabaseColumn(
        role="feature",
        selected=True,
        source_family="indicators",
        source_id="missing:source:id",
        source_column_name="mystery",
        db_column_name="indicator__missing__source__mystery",
        dtype="float64",
        nullable=True,
        analysis_usable=True,
        renderable=True,
    )


def _save_manifest(
    root: Path,
    *,
    include_volume: bool = True,
    feature_sources=(),
    feature_columns=(),
):
    market = _market()
    store = AnalysisDatabaseStore(historical_root=root)
    manifest = store.build_draft_manifest(
        market=market,
        display_name="BTCUSDT_30m_feature_set",
        include_volume=include_volume,
        feature_sources=tuple(feature_sources),
        feature_columns=tuple(feature_columns),
    )
    store.save_manifest(manifest, overwrite=False)
    return store, manifest


def _planner(root: Path, manifest, *, readiness: object | None = None):
    report = readiness or _fake_readiness(database_id=manifest.database_id)
    return AnalysisSuiteFeatureSetPlanner(
        historical_root=root,
        readiness_service=_FakeReadinessService(report),
    )


def _by_name(report):
    return {candidate.column_name: candidate for candidate in report.candidates}


def test_candidate_listing_groups_manifest_columns_and_allows_analysis_usable_non_renderable(
    tmp_path: Path,
) -> None:
    indicator = _source(family="indicators", tool_key="sma")
    volume = _source(family="oscillators", tool_key="volume")
    derivative = _source(family="constructs", tool_key="derivative")
    utc = _source(family="indicators", tool_key="universal_trend_classifier")
    sources = (indicator, volume, derivative, utc)
    columns = (
        _feature_column(indicator, column_name="sma_14"),
        _feature_column(volume, column_name="volume_signal"),
        _feature_column(derivative, column_name="slope", renderable=False),
        _feature_column(utc, column_name="trend_state", renderable=False),
    )
    _store, manifest = _save_manifest(
        tmp_path,
        include_volume=True,
        feature_sources=sources,
        feature_columns=columns,
    )

    report = _planner(tmp_path, manifest).list_feature_candidates(
        market=_market(),
        database_id=manifest.database_id,
    )

    candidates = _by_name(report)
    assert candidates["open"].group == "base_ohlc"
    assert candidates["open"].status == "eligible"
    assert candidates["volume"].group == "raw_volume"
    assert candidates["volume"].status == "warning"

    indicator_name = columns[0].db_column_name
    volume_name = columns[1].db_column_name
    derivative_name = columns[2].db_column_name
    utc_name = columns[3].db_column_name
    assert candidates[indicator_name].group == "indicators"
    assert candidates[volume_name].group == "volume"
    assert candidates[derivative_name].group == "construct_batch"
    assert candidates[derivative_name].status == "warning"
    assert candidates[derivative_name].feature_eligible is True
    assert candidates[utc_name].group == "topology"
    assert candidates[utc_name].feature_eligible is True
    assert report.group_summary["base_ohlc"]["eligible"] == 4


def test_ts_ms_is_reserved_alignment_key(tmp_path: Path) -> None:
    _store, manifest = _save_manifest(tmp_path, include_volume=True)

    report = _planner(tmp_path, manifest).list_feature_candidates(
        market=_market(),
        database_id=manifest.database_id,
    )

    ts_ms = _by_name(report)["ts_ms"]
    assert ts_ms.group == "alignment"
    assert ts_ms.status == "reserved"
    assert ts_ms.feature_eligible is False
    assert "alignment_key_reserved" in ts_ms.blockers


def test_leakage_metadata_and_target_output_are_rejected_but_current_close_stays_eligible(
    tmp_path: Path,
) -> None:
    source = _source(family="indicators", tool_key="sma")
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
    _store, manifest = _save_manifest(
        tmp_path,
        include_volume=True,
        feature_sources=(source,),
        feature_columns=(target_only, future_derived, not_feature),
    )
    target = AnalysisSuiteTargetDefinition.future_return(
        horizon_bars=2,
        output_column_name="target_future_return_2",
    )

    report = _planner(tmp_path, manifest).validate_selected_features(
        market=_market(),
        database_id=manifest.database_id,
        selected_columns=("close", "target_future_return_2"),
        target_definition=target,
    )

    candidates = _by_name(report)
    assert candidates["close"].status == "eligible"
    assert "close" in [candidate.column_name for candidate in report.selected_features]
    assert report.rejected_features[0].column_name == "target_future_return_2"
    assert "target_output_column_forbidden" in report.rejected_features[0].blockers
    assert candidates[target_only.db_column_name].status == "blocked"
    assert "target_only_column_forbidden" in candidates[target_only.db_column_name].blockers
    assert "future_derived_column_forbidden" in candidates[future_derived.db_column_name].blockers
    assert "feature_eligible_false" in candidates[not_feature.db_column_name].blockers
    assert report.status == "blocked"


def test_unknown_metadata_column_is_blocked(tmp_path: Path) -> None:
    unknown = _unknown_feature_column()
    _store, manifest = _save_manifest(
        tmp_path,
        include_volume=True,
        feature_sources=(),
        feature_columns=(unknown,),
    )

    report = _planner(tmp_path, manifest).list_feature_candidates(
        market=_market(),
        database_id=manifest.database_id,
    )

    candidate = _by_name(report)[unknown.db_column_name]
    assert candidate.group == "unknown"
    assert candidate.status == "unknown"
    assert "feature_metadata_unknown" in candidate.blockers
    assert "feature_source_missing" in candidate.blockers


def test_selectable_and_analysis_usable_rules_block_candidates(tmp_path: Path) -> None:
    source = _source(family="oscillators", tool_key="rsi")
    not_selectable = _feature_column(
        source,
        column_name="rsi_hidden",
        metadata=(_metadata("selectable", False),),
    )
    not_analysis_usable = _feature_column(
        source,
        column_name="rsi_utility",
        analysis_usable=False,
    )
    _store, manifest = _save_manifest(
        tmp_path,
        include_volume=True,
        feature_sources=(source,),
        feature_columns=(not_selectable, not_analysis_usable),
    )

    report = _planner(tmp_path, manifest).list_feature_candidates(
        market=_market(),
        database_id=manifest.database_id,
    )

    candidates = _by_name(report)
    assert "column_not_selectable" in candidates[not_selectable.db_column_name].blockers
    assert "column_not_analysis_usable" in candidates[not_analysis_usable.db_column_name].blockers
    assert candidates[not_selectable.db_column_name].feature_eligible is False
    assert candidates[not_analysis_usable.db_column_name].feature_eligible is False


def test_selected_feature_validation_preserves_order_and_rejects_invalid_choices(
    tmp_path: Path,
) -> None:
    _store, manifest = _save_manifest(tmp_path, include_volume=True)

    report = _planner(tmp_path, manifest).validate_selected_features(
        market=_market(),
        database_id=manifest.database_id,
        selected_columns=("close", "ts_ms", "open", "missing_feature"),
    )

    assert [candidate.column_name for candidate in report.selected_features] == [
        "close",
        "open",
    ]
    assert [candidate.column_name for candidate in report.rejected_features] == [
        "ts_ms",
        "missing_feature",
    ]
    assert report.selected_count == 4
    assert report.accepted_selected_count == 2
    assert report.rejected_selected_count == 2
    assert report.status == "blocked"


def test_non_strict_but_previewable_readiness_preserves_warnings_and_allows_planning(
    tmp_path: Path,
) -> None:
    _store, manifest = _save_manifest(tmp_path, include_volume=True)
    readiness = _fake_readiness(
        database_id=manifest.database_id,
        can_preview=True,
        strict_ready=False,
        warnings=("missing_topology: utc",),
        blockers=("source_ohlcv_drift: stale",),
    )

    report = _planner(tmp_path, manifest, readiness=readiness).list_feature_candidates(
        market=_market(),
        database_id=manifest.database_id,
    )

    assert report.status == "previewable"
    assert "dataset_not_strict_ready" in report.warnings
    assert "missing_topology: utc" in report.warnings
    assert "source_ohlcv_drift: stale" in report.blockers


def test_can_preview_false_blocks_before_manifest_is_required(tmp_path: Path) -> None:
    readiness = _fake_readiness(
        database_id="missing_database",
        can_preview=False,
        strict_ready=False,
        blockers=("database_not_materialized",),
    )
    planner = AnalysisSuiteFeatureSetPlanner(
        historical_root=tmp_path,
        readiness_service=_FakeReadinessService(readiness),
    )

    report = planner.list_feature_candidates(
        market=_market(),
        database_id="missing_database",
    )

    assert report.status == "blocked"
    assert "dataset_not_previewable" in report.blockers
    assert report.total_candidate_count == 0


def test_report_to_dict_is_json_safe(tmp_path: Path) -> None:
    _store, manifest = _save_manifest(tmp_path, include_volume=True)

    report = _planner(tmp_path, manifest).validate_selected_features(
        market=_market(),
        database_id=manifest.database_id,
        selected_columns=("open", "close"),
    )

    payload = report.to_dict()
    json.dumps(payload, sort_keys=True)
    assert payload["accepted_selected_count"] == 2
    assert payload["feature_set_definition"]["feature_count"] == 2


def test_static_boundary_rules() -> None:
    source = Path(
        "src/leonardo/data/historical/analysis_suite_feature_set_planner.py"
    ).read_text(encoding="utf-8")

    forbidden_terms = (
        "PySide",
        "QtWidgets",
        "AnalysisSuiteWindow",
        "FeatureSetStore",
        "AnalysisProjectStore",
        "AnalysisRunStore",
        "AnalysisReportStore",
        "ArtifactCalculationService",
        "ArtifactRecipeExecutor",
        "DataManagerUpdateService",
        "materialize_database",
        "save_manifest",
        "write_text",
        "write_bytes",
        "json.dump",
        ".to_csv",
    )
    for term in forbidden_terms:
        assert term not in source
