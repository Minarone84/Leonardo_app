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
from leonardo.data.historical.analysis_suite_feature_set_planner import (
    AnalysisSuiteFeatureSetPlanner,
)
from leonardo.data.historical.analysis_suite_genome_path_builder import (
    MAX_GENOME_PATH_SAMPLE_LIMIT,
    AnalysisSuiteGenomeComponentDefinition,
    AnalysisSuiteGenomeEncodingDefinition,
    AnalysisSuiteGenomePathBuilder,
    AnalysisSuiteStaticBinRule,
)
from leonardo.data.historical.analysis_suite_poi_family_planner import (
    AnalysisSuitePoiCondition,
    AnalysisSuitePoiDefinition,
    AnalysisSuitePoiFamilyDefinition,
    AnalysisSuitePoiFamilyPlanner,
)
from leonardo.data.naming import canonicalize


def _market():
    return canonicalize("bybit", "linear", "BTCUSDT", "30m")


def _metadata(key: str, value: object, *, namespace: str = "analysis_suite"):
    return AnalysisMetadataEntry(namespace=namespace, key=key, value=value)


def _source(*, family: str = "indicators", tool_key: str = "rsi") -> AnalysisFeatureSource:
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
    dtype: str | None = "float64",
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
        dtype=dtype,
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
        display_name="BTCUSDT_30m_genome_paths",
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


def _builder(root: Path, *, readiness: object) -> AnalysisSuiteGenomePathBuilder:
    return AnalysisSuiteGenomePathBuilder(
        historical_root=root,
        readiness_service=_FakeReadinessService(readiness),
    )


def _component(
    key: str,
    column: str,
    encoding: str,
    **kwargs,
) -> AnalysisSuiteGenomeComponentDefinition:
    return AnalysisSuiteGenomeComponentDefinition(
        component_key=key,
        source_column=column,
        encoding=encoding,
        **kwargs,
    )


def _encoding(
    components,
    *,
    path_length_bars: int = 1,
    anchor: str = "row",
) -> AnalysisSuiteGenomeEncodingDefinition:
    return AnalysisSuiteGenomeEncodingDefinition(
        encoding_key="genome_preview",
        display_name="Genome preview",
        components=tuple(components),
        path_length_bars=path_length_bars,
        anchor=anchor,
    )


def _feature_set_report(
    root: Path,
    manifest,
    *,
    selected_columns,
):
    return AnalysisSuiteFeatureSetPlanner(
        historical_root=root,
        readiness_service=_FakeReadinessService(
            SimpleNamespace(
                database_id=manifest.database_id,
                display_name=manifest.display_name,
                exchange=_market().exchange,
                market_type=_market().market_type,
                symbol=_market().symbol,
                timeframe=_market().timeframe,
                readiness_status="ready",
                strict_ready=True,
                can_preview=True,
                warnings=(),
                blockers=(),
                errors=(),
            )
        ),
    ).validate_selected_features(
        market=_market(),
        database_id=manifest.database_id,
        selected_columns=tuple(selected_columns),
    )


def test_identity_numeric_encoding_handles_nan_safely(tmp_path: Path) -> None:
    source = _source(tool_key="rsi")
    score = _feature_column(source, column_name="rsi_14")
    store, manifest = _save_manifest(
        tmp_path,
        feature_sources=(source,),
        feature_columns=(score,),
    )
    dataframe_path = store.dataframe_path(market=_market(), database_id=manifest.database_id)
    _write_dataframe(
        dataframe_path,
        4,
        **{score.db_column_name: [35.5, float("nan"), float("inf"), 42.0]},
    )

    report = _builder(
        tmp_path,
        readiness=_fake_readiness(
            database_id=manifest.database_id,
            dataframe_path=dataframe_path,
        ),
    ).preview_paths(
        market=_market(),
        database_id=manifest.database_id,
        encoding_definition=_encoding(
            (_component("rsi_value", score.db_column_name, "identity_numeric"),)
        ),
        anchor_rows=(0, 1, 2, 3),
    )

    values = [
        path.snapshots[0].components["rsi_value"] for path in report.sample_paths
    ]
    assert report.status == "warning"
    assert values == [35.5, "missing", "missing", 42.0]
    json.dumps(report.to_dict(), sort_keys=True)


def test_categorical_and_boolean_symbolic_encodings(tmp_path: Path) -> None:
    state_source = _source(tool_key="universal_trend_classifier")
    flag_source = _source(tool_key="braids")
    state = _feature_column(
        state_source,
        column_name="utc_state",
        dtype="object",
        renderable=False,
    )
    flag = _feature_column(flag_source, column_name="braid_compressed")
    store, manifest = _save_manifest(
        tmp_path,
        feature_sources=(state_source, flag_source),
        feature_columns=(state, flag),
    )
    dataframe_path = store.dataframe_path(market=_market(), database_id=manifest.database_id)
    _write_dataframe(
        dataframe_path,
        4,
        **{
            state.db_column_name: ["range", "bullish", None, "bearish"],
            flag.db_column_name: [False, 1, "yes", None],
        },
    )
    definition = _encoding(
        (
            _component("utc_state", state.db_column_name, "categorical"),
            _component("braid_flag", flag.db_column_name, "boolean_symbolic"),
        )
    )

    report = _builder(
        tmp_path,
        readiness=_fake_readiness(
            database_id=manifest.database_id,
            dataframe_path=dataframe_path,
        ),
    ).preview_paths(
        market=_market(),
        database_id=manifest.database_id,
        encoding_definition=definition,
        anchor_rows=(0, 1, 2, 3),
    )

    rows = [path.snapshots[0].components for path in report.sample_paths]
    assert rows[0] == {"utc_state": "range", "braid_flag": "false"}
    assert rows[1] == {"utc_state": "bullish", "braid_flag": "true"}
    assert rows[2] == {"utc_state": "missing", "braid_flag": "true"}
    assert rows[3] == {"utc_state": "bearish", "braid_flag": "missing"}


def test_static_bin_encoding_uses_explicit_bins_only(tmp_path: Path) -> None:
    source = _source(tool_key="rsi")
    score = _feature_column(source, column_name="rsi_14")
    store, manifest = _save_manifest(
        tmp_path,
        feature_sources=(source,),
        feature_columns=(score,),
    )
    dataframe_path = store.dataframe_path(market=_market(), database_id=manifest.database_id)
    _write_dataframe(dataframe_path, 5, **{score.db_column_name: [10, 35, 70, 101, None]})
    bins = (
        AnalysisSuiteStaticBinRule(label="low", upper=30),
        AnalysisSuiteStaticBinRule(label="middle", lower=30, upper=70),
        AnalysisSuiteStaticBinRule(label="high", lower=70, upper=100, include_upper=True),
    )

    report = _builder(
        tmp_path,
        readiness=_fake_readiness(
            database_id=manifest.database_id,
            dataframe_path=dataframe_path,
        ),
    ).preview_paths(
        market=_market(),
        database_id=manifest.database_id,
        encoding_definition=_encoding(
            (_component("rsi_bin", score.db_column_name, "static_bin", bins=bins),)
        ),
        anchor_rows=(0, 1, 2, 3, 4),
    )
    validation = _builder(
        tmp_path,
        readiness=_fake_readiness(
            database_id=manifest.database_id,
            dataframe_path=dataframe_path,
        ),
    ).validate_encoding_definition(
        market=_market(),
        database_id=manifest.database_id,
        encoding_definition=_encoding(
            (_component("bad_bin", score.db_column_name, "static_bin"),)
        ),
    )

    values = [path.snapshots[0].components["rsi_bin"] for path in report.sample_paths]
    assert values == ["low", "middle", "high", "out_of_range", "missing"]
    assert "component_static_bin_out_of_range: rsi_bin" in report.warnings
    assert validation["status"] == "blocked"
    assert "static_bin_requires_bins: bad_bin" in validation["blockers"]


def test_variation_direction_uses_current_and_past_rows_only(tmp_path: Path) -> None:
    source = _source(tool_key="delta")
    delta = _feature_column(source, column_name="close_ema50_delta")
    store, manifest = _save_manifest(
        tmp_path,
        feature_sources=(source,),
        feature_columns=(delta,),
    )
    dataframe_path = store.dataframe_path(market=_market(), database_id=manifest.database_id)
    _write_dataframe(dataframe_path, 5, **{delta.db_column_name: [10, 12, 12, 9, 100]})

    report = _builder(
        tmp_path,
        readiness=_fake_readiness(
            database_id=manifest.database_id,
            dataframe_path=dataframe_path,
        ),
    ).preview_paths(
        market=_market(),
        database_id=manifest.database_id,
        encoding_definition=_encoding(
            (
                _component(
                    "delta_variation",
                    delta.db_column_name,
                    "variation_direction",
                    lookback_bars=1,
                ),
            )
        ),
        anchor_rows=(0, 1, 2, 3),
    )

    values = [
        path.snapshots[0].components["delta_variation"]
        for path in report.sample_paths
    ]
    assert values == ["missing", "increasing", "flat", "decreasing"]
    assert "component_variation_lookback_unavailable: delta_variation" in report.warnings
    assert report.sample_paths[3].snapshots[0].component_metadata["delta_variation"]["delta"] == -3.0


def test_row_anchored_path_preview_preserves_order(tmp_path: Path) -> None:
    source = _source(tool_key="sma")
    sma = _feature_column(source, column_name="sma_3")
    store, manifest = _save_manifest(
        tmp_path,
        feature_sources=(source,),
        feature_columns=(sma,),
    )
    dataframe_path = store.dataframe_path(market=_market(), database_id=manifest.database_id)
    _write_dataframe(dataframe_path, 5, **{sma.db_column_name: [1, 2, 3, 4, 5]})

    report = _builder(
        tmp_path,
        readiness=_fake_readiness(
            database_id=manifest.database_id,
            dataframe_path=dataframe_path,
        ),
    ).preview_paths(
        market=_market(),
        database_id=manifest.database_id,
        encoding_definition=_encoding(
            (_component("sma_value", sma.db_column_name, "identity_numeric"),),
            path_length_bars=3,
        ),
        anchor_rows=(3,),
    )

    path = report.sample_paths[0]
    assert path.anchor_row_index == 3
    assert [snapshot.row_index for snapshot in path.snapshots] == [1, 2, 3]
    assert [snapshot.components["sma_value"] for snapshot in path.snapshots] == [2.0, 3.0, 4.0]


def test_poi_family_anchoring_uses_matched_as8_occurrences(tmp_path: Path) -> None:
    peaks = _source(tool_key="peaks_troughs")
    utc = _source(tool_key="universal_trend_classifier")
    trough = _feature_column(peaks, column_name="trough_fractal_7")
    state = _feature_column(utc, column_name="utc_state", dtype="object", renderable=False)
    store, manifest = _save_manifest(
        tmp_path,
        feature_sources=(peaks, utc),
        feature_columns=(trough, state),
    )
    dataframe_path = store.dataframe_path(market=_market(), database_id=manifest.database_id)
    _write_dataframe(
        dataframe_path,
        5,
        **{
            trough.db_column_name: [None, 1.0, 1.0, None, 1.0],
            state.db_column_name: ["range", "bullish", "bearish", "range", "bullish"],
        },
    )
    readiness = _fake_readiness(
        database_id=manifest.database_id,
        dataframe_path=dataframe_path,
    )
    family_report = AnalysisSuitePoiFamilyPlanner(
        historical_root=tmp_path,
        readiness_service=_FakeReadinessService(readiness),
    ).preview_family(
        market=_market(),
        database_id=manifest.database_id,
        family_definition=AnalysisSuitePoiFamilyDefinition(
            family_key="t7_bullish",
            display_name="T7 bullish",
            poi_definition=AnalysisSuitePoiDefinition(
                poi_key="t7_trough",
                poi_type="t7_trough",
                source_column=trough.db_column_name,
                event_kind="sparse_event",
            ),
            conditions=(
                AnalysisSuitePoiCondition(
                    column=state.db_column_name,
                    operator="equals",
                    value="bullish",
                ),
            ),
        ),
    )

    report = _builder(tmp_path, readiness=readiness).preview_paths_for_poi_family(
        market=_market(),
        database_id=manifest.database_id,
        encoding_definition=_encoding(
            (_component("utc_state", state.db_column_name, "categorical"),),
            path_length_bars=2,
            anchor="poi_occurrence",
        ),
        family_report=family_report,
    )

    assert family_report.matched_count == 2
    assert report.path_count == 2
    assert [path.anchor_row_index for path in report.sample_paths] == [1, 4]
    assert all(path.anchor_kind == "poi_occurrence" for path in report.sample_paths)


def test_readiness_and_diagnostic_gates(tmp_path: Path) -> None:
    source = _source(tool_key="sma")
    sma = _feature_column(source, column_name="sma_3")
    store, manifest = _save_manifest(
        tmp_path,
        feature_sources=(source,),
        feature_columns=(sma,),
    )
    dataframe_path = store.dataframe_path(market=_market(), database_id=manifest.database_id)
    _write_dataframe(dataframe_path, 3, **{sma.db_column_name: [1, 2, 3]})
    definition = _encoding((_component("sma_value", sma.db_column_name, "identity_numeric"),))

    blocked = _builder(
        tmp_path,
        readiness=_fake_readiness(
            database_id=manifest.database_id,
            dataframe_path=dataframe_path,
            can_preview=False,
            strict_ready=False,
            blockers=("database_not_ready",),
        ),
    ).preview_paths(
        market=_market(),
        database_id=manifest.database_id,
        encoding_definition=definition,
    )
    allowed = _builder(
        tmp_path,
        readiness=_fake_readiness(
            database_id=manifest.database_id,
            dataframe_path=dataframe_path,
            can_preview=True,
            strict_ready=False,
            warnings=("missing_topology: utc",),
            blockers=("source_drift: stale",),
        ),
    ).preview_paths(
        market=_market(),
        database_id=manifest.database_id,
        encoding_definition=definition,
    )
    diagnostic_blocked = AnalysisSuiteGenomePathBuilder(
        historical_root=tmp_path,
    ).preview_paths(
        market=_market(),
        database_id=manifest.database_id,
        encoding_definition=definition,
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
    assert allowed.path_count == 3
    assert "dataset_not_strict_ready" in allowed.warnings
    assert "source_drift: stale" in allowed.blockers
    assert diagnostic_blocked.status == "blocked"
    assert "diagnostic_report_not_acceptable: blocked" in diagnostic_blocked.blockers


def test_feature_set_context_and_leakage_metadata_reject_unsafe_components(
    tmp_path: Path,
) -> None:
    source = _source(tool_key="sma")
    safe = _feature_column(source, column_name="sma_3")
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
        feature_sources=(source,),
        feature_columns=(safe, target_only, future_derived, not_feature),
    )
    dataframe_path = store.dataframe_path(market=_market(), database_id=manifest.database_id)
    _write_dataframe(
        dataframe_path,
        3,
        **{
            safe.db_column_name: [1, 2, 3],
            target_only.db_column_name: [1, 2, 3],
            future_derived.db_column_name: [1, 2, 3],
            not_feature.db_column_name: [1, 2, 3],
        },
    )
    readiness = _fake_readiness(
        database_id=manifest.database_id,
        dataframe_path=dataframe_path,
    )
    feature_set = _feature_set_report(
        tmp_path,
        manifest,
        selected_columns=(safe.db_column_name,),
    )

    unselected = _builder(tmp_path, readiness=readiness).preview_paths(
        market=_market(),
        database_id=manifest.database_id,
        encoding_definition=_encoding(
            (_component("unsafe", target_only.db_column_name, "identity_numeric"),)
        ),
        feature_set_report=feature_set,
    )
    metadata_blocked = _builder(tmp_path, readiness=readiness).preview_paths(
        market=_market(),
        database_id=manifest.database_id,
        encoding_definition=_encoding(
            (
                _component("target_only", target_only.db_column_name, "identity_numeric"),
                _component("future", future_derived.db_column_name, "identity_numeric"),
                _component("not_feature", not_feature.db_column_name, "identity_numeric"),
            )
        ),
    )

    assert unselected.status == "blocked"
    assert (
        f"component_source_not_selected_by_feature_set: {target_only.db_column_name}"
        in unselected.blockers
    )
    assert metadata_blocked.status == "blocked"
    assert (
        f"component_target_only_column_forbidden: {target_only.db_column_name}"
        in metadata_blocked.blockers
    )
    assert (
        f"component_future_derived_column_forbidden: {future_derived.db_column_name}"
        in metadata_blocked.blockers
    )
    assert (
        f"component_feature_eligible_false: {not_feature.db_column_name}"
        in metadata_blocked.blockers
    )


def test_missing_source_column_blocks_after_physical_check(tmp_path: Path) -> None:
    source = _source(tool_key="sma")
    sma = _feature_column(source, column_name="sma_3")
    store, manifest = _save_manifest(
        tmp_path,
        feature_sources=(source,),
        feature_columns=(sma,),
    )
    dataframe_path = store.dataframe_path(market=_market(), database_id=manifest.database_id)
    _write_dataframe(dataframe_path, 3)

    report = _builder(
        tmp_path,
        readiness=_fake_readiness(
            database_id=manifest.database_id,
            dataframe_path=dataframe_path,
        ),
    ).preview_paths(
        market=_market(),
        database_id=manifest.database_id,
        encoding_definition=_encoding(
            (_component("sma_value", sma.db_column_name, "identity_numeric"),)
        ),
    )

    assert report.status == "blocked"
    assert f"dataframe_required_column_missing: {sma.db_column_name}" in report.blockers


def test_bounded_samples_preserve_total_path_count(tmp_path: Path) -> None:
    source = _source(tool_key="sma")
    sma = _feature_column(source, column_name="sma_3")
    store, manifest = _save_manifest(
        tmp_path,
        feature_sources=(source,),
        feature_columns=(sma,),
    )
    dataframe_path = store.dataframe_path(market=_market(), database_id=manifest.database_id)
    rows = 700
    _write_dataframe(dataframe_path, rows, **{sma.db_column_name: list(range(rows))})
    definition = _encoding(
        (_component("sma_value", sma.db_column_name, "identity_numeric"),),
        path_length_bars=2,
    )
    builder = _builder(
        tmp_path,
        readiness=_fake_readiness(
            database_id=manifest.database_id,
            dataframe_path=dataframe_path,
        ),
    )

    default_report = builder.preview_paths(
        market=_market(),
        database_id=manifest.database_id,
        encoding_definition=definition,
    )
    clamped_report = builder.preview_paths(
        market=_market(),
        database_id=manifest.database_id,
        encoding_definition=definition,
        sample_limit=999,
    )

    assert default_report.path_count == rows - 1
    assert len(default_report.sample_paths) == 100
    assert clamped_report.path_count == rows - 1
    assert clamped_report.sample_limit == MAX_GENOME_PATH_SAMPLE_LIMIT
    assert len(clamped_report.sample_paths) == MAX_GENOME_PATH_SAMPLE_LIMIT
    assert "sample_limit_clamped_to_max" in clamped_report.warnings


def test_report_to_dict_is_json_safe(tmp_path: Path) -> None:
    source = _source(tool_key="sma")
    sma = _feature_column(source, column_name="sma_3")
    store, manifest = _save_manifest(
        tmp_path,
        feature_sources=(source,),
        feature_columns=(sma,),
    )
    dataframe_path = store.dataframe_path(market=_market(), database_id=manifest.database_id)
    _write_dataframe(dataframe_path, 4, **{sma.db_column_name: [1.0, float("nan"), 2.0, 3.0]})

    report = _builder(
        tmp_path,
        readiness=_fake_readiness(
            database_id=manifest.database_id,
            dataframe_path=dataframe_path,
        ),
    ).preview_paths(
        market=_market(),
        database_id=manifest.database_id,
        encoding_definition=_encoding(
            (_component("sma_value", sma.db_column_name, "identity_numeric"),)
        ),
    )

    payload = report.to_dict()
    json.dumps(payload, sort_keys=True)
    assert payload["path_count"] == 4


def test_static_boundary_rules() -> None:
    source = Path(
        "src/leonardo/data/historical/analysis_suite_genome_path_builder.py"
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
        "rule discovery",
        "neural",
        "RL Decisor",
    )
    for term in forbidden_terms:
        assert term not in source
