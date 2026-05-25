from __future__ import annotations

import json

from leonardo.data.historical.analysis_database_contracts import (
    ANALYSIS_DATABASE_ARTIFACT_TYPE,
    ANALYSIS_DATABASE_SCHEMA_VERSION,
    AnalysisDatabaseAlignment,
    AnalysisDatabaseColumn,
    AnalysisDatabaseDescription,
    AnalysisDatabaseManifest,
    AnalysisFeatureSource,
    AnalysisMetadataEntry,
)
from leonardo.data.historical.analysis_dataset_geography import (
    GEOGRAPHY_KEY_BRAIDS,
    GEOGRAPHY_KEY_OHLC_BASE,
    GEOGRAPHY_KEY_PEAKS_TROUGHS,
    GEOGRAPHY_KEY_UTC,
    GEOGRAPHY_KEY_VOLUME_ARTIFACT,
    AnalysisDatasetGeographyPolicy,
)
from leonardo.data.historical.analysis_database_naming import (
    build_database_column_name,
    build_feature_source_id,
)
from leonardo.data.naming import canonicalize


def _base_column(
    name: str,
    *,
    selected: bool = True,
    role: str | None = None,
) -> AnalysisDatabaseColumn:
    return AnalysisDatabaseColumn(
        role="primary_key" if role is None and name == "ts_ms" else (role or "base"),
        selected=selected,
        source_family="ohlcv",
        source_id=None,
        source_column_name=name,
        db_column_name=build_database_column_name(
            source_family="ohlcv",
            tool_key=None,
            instance_key=None,
            source_column_name=name,
        ),
        dtype="int64" if name == "ts_ms" else "float64",
        nullable=False,
        analysis_usable=True,
        renderable=name != "ts_ms",
        locked=name != "volume",
    )


def _base_columns(
    *,
    include_volume: bool = False,
    missing: str | None = None,
    unselected: str | None = None,
) -> tuple[AnalysisDatabaseColumn, ...]:
    names = ["ts_ms", "open", "high", "low", "close"]
    if include_volume:
        names.append("volume")
    return tuple(
        _base_column(name, selected=name != unselected)
        for name in names
        if name != missing
    )


def _feature(
    *,
    family: str,
    tool_key: str,
    column_name: str,
    selected: bool = True,
    source_metadata: tuple[AnalysisMetadataEntry, ...] = (),
    column_metadata: tuple[AnalysisMetadataEntry, ...] = (),
) -> tuple[AnalysisFeatureSource, AnalysisDatabaseColumn]:
    instance_key = f"{tool_key}__default"
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
        metadata=source_metadata,
    )
    column = AnalysisDatabaseColumn(
        role="feature",
        selected=selected,
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
        metadata=column_metadata,
    )
    return source, column


def _role_entry(value: object) -> AnalysisMetadataEntry:
    return AnalysisMetadataEntry(
        namespace="study",
        key="dataset_role",
        value=value,
        value_type="string",
    )


def _report(
    *,
    base_columns: tuple[AnalysisDatabaseColumn, ...] | None = None,
    features: tuple[tuple[AnalysisFeatureSource, AnalysisDatabaseColumn], ...] = (),
):
    return AnalysisDatasetGeographyPolicy().evaluate_components(
        base_columns=_base_columns() if base_columns is None else base_columns,
        feature_sources=tuple(source for source, _column in features),
        feature_columns=tuple(column for _source, column in features),
    )


def test_detects_complete_ohlc_base_from_selected_base_columns() -> None:
    report = _report(base_columns=_base_columns())

    assert GEOGRAPHY_KEY_OHLC_BASE in report.present_keys
    assert GEOGRAPHY_KEY_OHLC_BASE not in report.missing_keys


def test_reports_missing_ohlc_base_when_required_column_is_unselected() -> None:
    report = _report(base_columns=_base_columns(unselected="close"))

    assert GEOGRAPHY_KEY_OHLC_BASE in report.missing_keys
    assert GEOGRAPHY_KEY_OHLC_BASE not in report.present_keys


def test_raw_ohlcv_volume_alone_does_not_satisfy_volume_artifact() -> None:
    report = _report(base_columns=_base_columns(include_volume=True))

    assert report.raw_volume_present is True
    assert report.volume_artifact_present is False
    assert GEOGRAPHY_KEY_VOLUME_ARTIFACT in report.missing_keys


def test_detects_volume_artifact_by_tool_identity() -> None:
    report = _report(
        features=(
            _feature(family="oscillators", tool_key="volume", column_name="volume"),
        )
    )

    assert report.volume_artifact_present is True
    assert GEOGRAPHY_KEY_VOLUME_ARTIFACT in report.present_keys


def test_detects_braids_by_tool_identity() -> None:
    report = _report(
        features=(
            _feature(family="constructs", tool_key="braids", column_name="braid_width"),
        )
    )

    assert GEOGRAPHY_KEY_BRAIDS in report.present_keys


def test_detects_peaks_troughs_by_tool_identity() -> None:
    report = _report(
        features=(
            _feature(
                family="indicators",
                tool_key="peaks_troughs",
                column_name="peak_fractal_5",
            ),
        )
    )

    assert GEOGRAPHY_KEY_PEAKS_TROUGHS in report.present_keys


def test_detects_utc_by_tool_identity() -> None:
    report = _report(
        features=(
            _feature(
                family="indicators",
                tool_key="universal_trend_classifier",
                column_name="trend_state",
            ),
        )
    )

    assert GEOGRAPHY_KEY_UTC in report.present_keys


def test_complete_requires_ohlc_base_and_all_required_artifacts() -> None:
    report = _report(
        base_columns=_base_columns(),
        features=(
            _feature(family="oscillators", tool_key="volume", column_name="volume"),
            _feature(family="constructs", tool_key="braids", column_name="braid_width"),
            _feature(
                family="indicators",
                tool_key="peaks_troughs",
                column_name="peak_fractal_5",
            ),
            _feature(
                family="indicators",
                tool_key="universal_trend_classifier",
                column_name="trend_state",
            ),
        ),
    )

    assert report.complete is True
    assert report.strict_ready is True
    assert report.missing_keys == ()


def test_missing_keys_include_missing_required_items() -> None:
    report = _report(base_columns=_base_columns())

    assert report.complete is False
    assert GEOGRAPHY_KEY_VOLUME_ARTIFACT in report.missing_keys
    assert GEOGRAPHY_KEY_BRAIDS in report.missing_keys
    assert GEOGRAPHY_KEY_PEAKS_TROUGHS in report.missing_keys
    assert GEOGRAPHY_KEY_UTC in report.missing_keys


def test_semantic_volume_duplication_warning_when_raw_and_artifact_volume_exist() -> None:
    report = _report(
        base_columns=_base_columns(include_volume=True),
        features=(
            _feature(family="oscillators", tool_key="volume", column_name="volume"),
        ),
    )

    assert report.semantic_volume_duplication is True
    assert any(warning.code == "semantic_volume_duplication" for warning in report.warnings)


def test_no_semantic_volume_duplication_warning_when_only_artifact_volume_exists() -> None:
    report = _report(
        base_columns=_base_columns(include_volume=False),
        features=(
            _feature(family="oscillators", tool_key="volume", column_name="volume"),
        ),
    )

    assert report.semantic_volume_duplication is False
    assert not any(warning.code == "semantic_volume_duplication" for warning in report.warnings)


def test_dataset_role_mismatch_produces_warning_when_metadata_is_present() -> None:
    report = _report(
        features=(
            _feature(
                family="oscillators",
                tool_key="rsi",
                column_name="rsi_14",
                source_metadata=(_role_entry("utc"),),
            ),
        )
    )

    assert any(warning.code == "dataset_role_utc_mismatch" for warning in report.warnings)


def test_dataset_role_alone_does_not_satisfy_geography() -> None:
    report = _report(
        features=(
            _feature(
                family="oscillators",
                tool_key="rsi",
                column_name="rsi_14",
                column_metadata=(_role_entry("utc"),),
            ),
        )
    )

    assert GEOGRAPHY_KEY_UTC in report.missing_keys
    assert any(warning.code == "dataset_role_utc_mismatch" for warning in report.warnings)


def test_legacy_manifest_with_raw_volume_remains_evaluable_and_unblocked() -> None:
    market = canonicalize("bybit", "linear", "BTCUSDT", "30m")
    manifest = AnalysisDatabaseManifest(
        schema_version=ANALYSIS_DATABASE_SCHEMA_VERSION,
        artifact_type=ANALYSIS_DATABASE_ARTIFACT_TYPE,
        database_id="adb__legacy__h12345678",
        display_name="BTCUSDT_30m_legacy",
        status="draft",
        description=AnalysisDatabaseDescription(user_text="Legacy manifest."),
        market=market,
        dataframe_filename=None,
        alignment=AnalysisDatabaseAlignment(),
        base_columns=_base_columns(include_volume=True),
        feature_sources=(),
        feature_columns=(),
        recipe_hash="1" * 64,
        recipe_hash_short="h11111111",
    )

    report = AnalysisDatasetGeographyPolicy().evaluate_manifest(manifest)

    assert report.blockers == ()
    assert report.raw_volume_present is True
    assert report.volume_artifact_present is False
    assert GEOGRAPHY_KEY_VOLUME_ARTIFACT in report.missing_keys
    assert report.metadata["database_id"] == manifest.database_id


def test_report_to_dict_is_json_safe() -> None:
    report = _report(
        base_columns=_base_columns(include_volume=True),
        features=(
            _feature(family="oscillators", tool_key="volume", column_name="volume"),
        ),
    )

    payload = report.to_dict()

    assert payload["raw_volume_present"] is True
    json.dumps(payload, sort_keys=True)
