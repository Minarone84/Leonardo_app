from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from leonardo.data.historical.analysis_suite_dataset_readiness import (
    AnalysisSuiteDatasetReadinessReport,
)
from leonardo.data.historical.analysis_suite_diagnostic_report import (
    AnalysisSuiteDiagnosticReportService,
)
from leonardo.data.historical.analysis_suite_feature_set_planner import (
    AnalysisSuiteFeatureCandidate,
    AnalysisSuiteFeatureSetDefinition,
    AnalysisSuiteFeatureSetPreviewReport,
)
from leonardo.data.historical.analysis_suite_target_planner import (
    AnalysisSuiteTargetDefinition,
    AnalysisSuiteTargetPreviewReport,
)


def _write_dataframe(path: Path, rows: int, **columns: list[object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data: dict[str, list[object]] = {
        "ts_ms": [1000 * index for index in range(1, rows + 1)],
        "close": [100.0 + index for index in range(rows)],
    }
    data.update(columns)
    pd.DataFrame(data).to_csv(path, index=False)


def _readiness(
    dataframe_path: Path,
    *,
    row_count: int,
    strict_ready: bool = True,
    can_preview: bool = True,
    blockers: tuple[str, ...] = (),
    warnings: tuple[str, ...] = (),
    errors: tuple[str, ...] = (),
) -> AnalysisSuiteDatasetReadinessReport:
    return AnalysisSuiteDatasetReadinessReport(
        database_id="adb_ready",
        display_name="BTCUSDT_30m_ready",
        exchange="bybit",
        market_type="linear",
        symbol="BTCUSDT",
        timeframe="30m",
        manifest_status="materialized",
        materialization_status="present",
        dataframe_status="available" if can_preview else "missing",
        dataframe_path=str(dataframe_path),
        manifest_path=str(dataframe_path.parent / "manifest.json"),
        readiness_status="ready" if strict_ready else "incomplete_topology",
        strict_ready=strict_ready,
        can_preview=can_preview,
        row_count=row_count,
        column_count=6,
        first_ts_ms=1000,
        last_ts_ms=1000 * row_count,
        source_ohlcv_drift_status="current",
        geography_status="complete" if strict_ready else "incomplete",
        missing_topology=() if strict_ready else ("utc",),
        warnings=warnings,
        blockers=blockers,
        errors=errors,
    )


def _target_report(
    *,
    definition: AnalysisSuiteTargetDefinition,
    status: str = "previewable",
    row_count: int = 120,
    available: int = 110,
    unavailable: int = 10,
    class_distribution: dict[str, int] | None = None,
    blockers: tuple[str, ...] = (),
    warnings: tuple[str, ...] = (),
    errors: tuple[str, ...] = (),
) -> AnalysisSuiteTargetPreviewReport:
    return AnalysisSuiteTargetPreviewReport(
        database_id="adb_ready",
        display_name="BTCUSDT_30m_ready",
        exchange="bybit",
        market_type="linear",
        symbol="BTCUSDT",
        timeframe="30m",
        dataframe_path=None,
        manifest_path=None,
        readiness_status="ready",
        strict_ready=True,
        can_preview=True,
        target_definition=definition,
        status=status,  # type: ignore[arg-type]
        row_count=row_count,
        available_label_count=available,
        unavailable_label_count=unavailable,
        first_available_ts_ms=1000 if available else None,
        last_available_ts_ms=available * 1000 if available else None,
        preview_limit=100,
        sample_rows=(),
        regression_stats=(
            {}
            if definition.label_type == "classification"
            else {"count": available, "min": -0.05, "max": 0.07, "mean": 0.01}
        ),
        class_distribution=class_distribution or {},
        leakage_summary={
            "leakage_role": definition.leakage_role,
            "future_derived": definition.future_derived,
            "feature_eligible": definition.feature_eligible,
            "output_column_name": definition.output_column_name,
        },
        warnings=warnings,
        blockers=blockers,
        errors=errors,
    )


def _candidate(
    column: str,
    *,
    group: str = "indicators",
    status: str = "eligible",
    feature_eligible: bool = True,
    leakage_role: str = "feature",
    future_derived: bool = False,
    dtype: str | None = "float64",
    blockers: tuple[str, ...] = (),
    warnings: tuple[str, ...] = (),
) -> AnalysisSuiteFeatureCandidate:
    return AnalysisSuiteFeatureCandidate(
        column_name=column,
        display_name=column,
        group=group,
        status=status,  # type: ignore[arg-type]
        selected=True,
        selectable=feature_eligible,
        analysis_usable=True,
        renderable=True,
        feature_eligible=feature_eligible,
        leakage_role=leakage_role,
        future_derived=future_derived,
        source_family="ohlcv" if column in {"open", "high", "low", "close"} else "indicators",
        source_id=None if column in {"open", "high", "low", "close"} else "source_1",
        tool_key=None if column in {"open", "high", "low", "close"} else "sma",
        tool_title=None if column in {"open", "high", "low", "close"} else "SMA",
        source_column_name=column,
        dtype=dtype,
        nullable=True,
        blockers=blockers,
        warnings=warnings,
    )


def _feature_report(
    *,
    selected: tuple[AnalysisSuiteFeatureCandidate, ...],
    rejected: tuple[AnalysisSuiteFeatureCandidate, ...] = (),
    status: str = "previewable",
    blockers: tuple[str, ...] = (),
    warnings: tuple[str, ...] = (),
    errors: tuple[str, ...] = (),
) -> AnalysisSuiteFeatureSetPreviewReport:
    selected_columns = tuple(candidate.column_name for candidate in selected)
    rejected_columns = tuple(candidate.column_name for candidate in rejected)
    group_summary = {
        "base_ohlc": {"selected": sum(1 for item in selected if item.group == "base_ohlc")},
        "indicators": {"selected": sum(1 for item in selected if item.group == "indicators")},
    }
    return AnalysisSuiteFeatureSetPreviewReport(
        database_id="adb_ready",
        display_name="BTCUSDT_30m_ready",
        exchange="bybit",
        market_type="linear",
        symbol="BTCUSDT",
        timeframe="30m",
        readiness_status="ready",
        strict_ready=True,
        can_preview=True,
        status=status,  # type: ignore[arg-type]
        total_candidate_count=len(selected) + len(rejected),
        eligible_count=len(selected),
        blocked_count=len(rejected),
        warning_count=0,
        selected_count=len(selected) + len(rejected),
        accepted_selected_count=len(selected),
        rejected_selected_count=len(rejected),
        candidates=selected + rejected,
        selected_features=selected,
        rejected_features=rejected,
        group_summary=group_summary,
        leakage_summary={},
        feature_set_definition=AnalysisSuiteFeatureSetDefinition(
            name="Feature set preview",
            database_id="adb_ready",
            selected_columns=selected_columns,
            excluded_columns=rejected_columns,
            feature_count=len(selected),
            group_summary=group_summary,
            blockers=blockers,
            warnings=warnings,
        ),
        warnings=warnings,
        blockers=blockers,
        errors=errors,
    )


def test_ready_diagnostic_composes_dataset_target_and_feature_reports(tmp_path: Path) -> None:
    dataframe_path = tmp_path / "dataframe.csv"
    rows = 120
    _write_dataframe(
        dataframe_path,
        rows,
        open=[100.0 + index for index in range(rows)],
        feature_a=[float(index) for index in range(rows)],
        feature_b=[float(index) * 2.0 for index in range(rows)],
    )
    target_definition = AnalysisSuiteTargetDefinition.future_return(horizon_bars=10)

    report = AnalysisSuiteDiagnosticReportService().build_report(
        readiness_report=_readiness(dataframe_path, row_count=rows),
        target_report=_target_report(
            definition=target_definition,
            row_count=rows,
            available=110,
            unavailable=10,
        ),
        feature_set_report=_feature_report(
            selected=(
                _candidate("close", group="base_ohlc"),
                _candidate("feature_a"),
                _candidate("feature_b"),
            ),
        ),
    )

    assert report.status == "ready"
    assert report.database_id == "adb_ready"
    assert report.available_label_count == 110
    assert report.label_availability_ratio == 110 / 120
    assert report.accepted_feature_count == 3
    assert report.has_leakage_blockers is False
    assert [item.column_name for item in report.feature_column_diagnostics] == [
        "close",
        "feature_a",
        "feature_b",
    ]
    assert report.feature_column_diagnostics[0].non_null_count == rows
    json.dumps(report.to_dict())


def test_leakage_and_feature_set_blockers_are_exposed(tmp_path: Path) -> None:
    dataframe_path = tmp_path / "dataframe.csv"
    _write_dataframe(dataframe_path, 120)
    target_definition = AnalysisSuiteTargetDefinition.future_return(horizon_bars=2)
    rejected = (
        _candidate(
            target_definition.output_column_name,
            status="blocked",
            feature_eligible=False,
            leakage_role="target_only",
            future_derived=True,
            blockers=("target_output_column_forbidden",),
        ),
        _candidate(
            "future_signal",
            status="blocked",
            feature_eligible=False,
            future_derived=True,
            blockers=("future_derived_column_forbidden",),
        ),
        _candidate(
            "not_feature",
            status="blocked",
            feature_eligible=False,
            blockers=("feature_eligible_false",),
        ),
        _candidate(
            "ts_ms",
            group="alignment",
            status="reserved",
            feature_eligible=False,
            blockers=("alignment_key_reserved",),
        ),
    )

    report = AnalysisSuiteDiagnosticReportService().build_report(
        readiness_report=_readiness(dataframe_path, row_count=120),
        target_report=_target_report(definition=target_definition, row_count=120),
        feature_set_report=_feature_report(
            selected=(_candidate("close", group="base_ohlc"),),
            rejected=rejected,
            status="blocked",
            blockers=("selected_feature_rejected",),
        ),
    )

    assert report.status == "blocked"
    assert report.has_leakage_blockers is True
    assert target_definition.output_column_name in report.selected_target_output_columns
    assert "future_signal" in report.selected_future_derived_columns
    assert target_definition.output_column_name in report.selected_target_only_columns
    assert "not_feature" in report.selected_feature_eligible_false_columns
    assert "ts_ms" in report.selected_alignment_key_columns
    assert "leakage_blockers_present" in report.blockers


def test_no_available_labels_blocks_analysis(tmp_path: Path) -> None:
    dataframe_path = tmp_path / "dataframe.csv"
    _write_dataframe(dataframe_path, 20, feature_a=[1.0] * 20, feature_b=[2.0] * 20)
    target_definition = AnalysisSuiteTargetDefinition.future_return(horizon_bars=50)

    report = AnalysisSuiteDiagnosticReportService().build_report(
        readiness_report=_readiness(dataframe_path, row_count=20),
        target_report=_target_report(
            definition=target_definition,
            row_count=20,
            available=0,
            unavailable=20,
        ),
        feature_set_report=_feature_report(
            selected=(
                _candidate("close", group="base_ohlc"),
                _candidate("feature_a"),
                _candidate("feature_b"),
            ),
        ),
    )

    assert report.status == "blocked"
    assert "no_available_labels" in report.blockers
    assert report.label_availability_ratio == 0.0


def test_feature_missingness_dtype_and_missing_dataframe_column_diagnostics(
    tmp_path: Path,
) -> None:
    dataframe_path = tmp_path / "dataframe.csv"
    _write_dataframe(
        dataframe_path,
        4,
        feature_ok=[1.0, None, 3.0, 4.0],
        all_null=[None, None, None, None],
    )
    target_definition = AnalysisSuiteTargetDefinition.future_return(horizon_bars=1)

    report = AnalysisSuiteDiagnosticReportService().build_report(
        readiness_report=_readiness(dataframe_path, row_count=4),
        target_report=_target_report(
            definition=target_definition,
            row_count=4,
            available=3,
            unavailable=1,
        ),
        feature_set_report=_feature_report(
            selected=(
                _candidate("feature_ok"),
                _candidate("all_null"),
                _candidate("missing_feature"),
            ),
        ),
    )

    diagnostics = {item.column_name: item for item in report.feature_column_diagnostics}
    assert diagnostics["feature_ok"].dtype == "float64"
    assert diagnostics["feature_ok"].null_count == 1
    assert diagnostics["feature_ok"].null_ratio == 0.25
    assert diagnostics["all_null"].null_ratio == 1.0
    assert "feature_all_null" in diagnostics["all_null"].blockers
    assert "feature_missing_from_dataframe" in diagnostics["missing_feature"].blockers
    assert "feature_missing_from_dataframe: missing_feature" in report.blockers
    assert "feature_all_null: all_null" in report.blockers
    assert report.status == "blocked"


def test_classification_distribution_passes_with_two_classes_and_blocks_one_class(
    tmp_path: Path,
) -> None:
    dataframe_path = tmp_path / "dataframe.csv"
    rows = 120
    _write_dataframe(
        dataframe_path,
        rows,
        open=[100.0 + index for index in range(rows)],
        feature_a=[float(index) for index in range(rows)],
        feature_b=[float(index) * 2.0 for index in range(rows)],
    )
    target_definition = AnalysisSuiteTargetDefinition.future_direction(
        horizon_bars=5,
        up_threshold=0.01,
    )
    readiness = _readiness(dataframe_path, row_count=rows)
    features = _feature_report(
        selected=(
            _candidate("close", group="base_ohlc"),
            _candidate("feature_a"),
            _candidate("feature_b"),
        ),
    )

    valid = AnalysisSuiteDiagnosticReportService().build_report(
        readiness_report=readiness,
        target_report=_target_report(
            definition=target_definition,
            row_count=rows,
            available=110,
            unavailable=10,
            class_distribution={"up": 55, "down": 35, "flat": 20, "unavailable": 10},
        ),
        feature_set_report=features,
    )
    blocked = AnalysisSuiteDiagnosticReportService().build_report(
        readiness_report=readiness,
        target_report=_target_report(
            definition=target_definition,
            row_count=rows,
            available=110,
            unavailable=10,
            class_distribution={"up": 110, "down": 0, "flat": 0, "unavailable": 10},
        ),
        feature_set_report=features,
    )

    assert valid.status == "ready"
    assert blocked.status == "blocked"
    assert "classification_target_has_fewer_than_two_observed_classes" in blocked.blockers


def test_diagnostic_service_boundary_static_checks() -> None:
    source = Path(
        "src/leonardo/data/historical/analysis_suite_diagnostic_report.py"
    ).read_text(encoding="utf-8")

    forbidden = (
        "PySide",
        "leonardo.gui",
        "AnalysisProjectStore",
        "AnalysisRunStore",
        "AnalysisReportStore",
        "FeatureSetStore",
        "materialize_database",
        "ArtifactCalculationService",
        "ArtifactRecipeExecutor",
        "DataManagerUpdateService",
        "write_text",
        "write_bytes",
        "json.dump",
        ".to_csv",
        "save_manifest",
    )
    for token in forbidden:
        assert token not in source
