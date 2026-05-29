"""Read-only Analysis Suite pre-analysis diagnostic reporting.

The module composes existing AS1 readiness, AS5 target preview, and AS6
feature-set preview reports into a JSON-safe diagnostic report. It owns only
cross-report coherence checks and selected-feature physical consistency
inspection. It does not persist reports, mutate Analysis Databases, calculate
artifacts, train models, generate signals, or provide GUI behavior.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Mapping

import pandas as pd

from leonardo.data.historical.analysis_suite_dataset_readiness import (
    AnalysisSuiteDatasetReadinessReport,
    AnalysisSuiteDatasetReadinessStatus,
)
from leonardo.data.historical.analysis_suite_feature_set_planner import (
    AnalysisSuiteFeatureCandidate,
    AnalysisSuiteFeatureSetPreviewReport,
)
from leonardo.data.historical.analysis_suite_target_planner import (
    AnalysisSuiteTargetPreviewReport,
)


AnalysisSuiteDiagnosticStatus = Literal["ready", "warning", "blocked", "error"]
JsonValue = Any

LOW_LABEL_COUNT_WARNING_THRESHOLD = 100
LOW_LABEL_AVAILABILITY_RATIO = 0.50
HIGH_FEATURE_NULL_RATIO = 0.50
ALL_NULL_FEATURE_RATIO = 1.0
MIN_FEATURE_COUNT_WARNING_THRESHOLD = 3
CLASSIFICATION_IMBALANCE_RATIO = 0.90


@dataclass(frozen=True)
class AnalysisSuiteFeatureColumnDiagnostic:
    """
    JSON-safe physical consistency diagnostic for one accepted feature column.

    The diagnostic is derived from dataframe values only after AS6 has accepted
    the feature candidate. It is not used to decide feature eligibility, and it
    does not treat raw dataframe headers as feature-set truth.
    """

    column_name: str
    declared_dtype: str | None
    dtype: str | None
    row_count: int | None
    non_null_count: int | None
    null_count: int | None
    null_ratio: float | None
    finite_count: int | None
    non_finite_count: int | None
    blockers: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "blockers", tuple(str(item) for item in self.blockers))
        object.__setattr__(self, "warnings", tuple(str(item) for item in self.warnings))

    def to_dict(self) -> dict[str, object]:
        return {
            "column_name": self.column_name,
            "declared_dtype": self.declared_dtype,
            "dtype": self.dtype,
            "row_count": self.row_count,
            "non_null_count": self.non_null_count,
            "null_count": self.null_count,
            "null_ratio": self.null_ratio,
            "finite_count": self.finite_count,
            "non_finite_count": self.non_finite_count,
            "blockers": list(self.blockers),
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class AnalysisSuiteDiagnosticReport:
    """
    JSON-safe pre-analysis coherence report for Analysis Suite.

    The report composes AS1 readiness, AS5 target preview, and AS6 feature-set
    preview diagnostics. It is read-only and does not persist projects, runs,
    reports, targets, labels, feature sets, manifests, dataframes, or artifacts.
    """

    database_id: str
    display_name: str
    exchange: str
    market_type: str
    symbol: str
    timeframe: str
    manifest_path: str | None
    dataframe_path: str | None
    status: AnalysisSuiteDiagnosticStatus
    readiness_status: AnalysisSuiteDatasetReadinessStatus | str
    strict_ready: bool
    can_preview: bool
    row_count: int | None
    column_count: int | None
    first_ts_ms: int | None
    last_ts_ms: int | None
    source_ohlcv_drift_status: str | None
    geography_status: str | None
    missing_topology: tuple[str, ...]
    target_family: str
    label_type: str
    target_output_column: str
    horizon_bars: int | None
    target_row_count: int | None
    available_label_count: int
    unavailable_label_count: int
    label_availability_ratio: float | None
    first_available_label_ts_ms: int | None
    last_available_label_ts_ms: int | None
    regression_stats: Mapping[str, JsonValue] = field(default_factory=dict)
    class_distribution: Mapping[str, JsonValue] = field(default_factory=dict)
    selected_feature_count: int = 0
    accepted_feature_count: int = 0
    rejected_feature_count: int = 0
    selected_features: tuple[str, ...] = ()
    rejected_features: tuple[str, ...] = ()
    group_summary: Mapping[str, JsonValue] = field(default_factory=dict)
    has_leakage_blockers: bool = False
    selected_target_output_columns: tuple[str, ...] = ()
    selected_future_derived_columns: tuple[str, ...] = ()
    selected_target_only_columns: tuple[str, ...] = ()
    selected_feature_eligible_false_columns: tuple[str, ...] = ()
    selected_alignment_key_columns: tuple[str, ...] = ()
    leakage_summary: Mapping[str, JsonValue] = field(default_factory=dict)
    feature_column_diagnostics: tuple[AnalysisSuiteFeatureColumnDiagnostic, ...] = ()
    dataset_warnings: tuple[str, ...] = ()
    dataset_blockers: tuple[str, ...] = ()
    dataset_errors: tuple[str, ...] = ()
    target_warnings: tuple[str, ...] = ()
    target_blockers: tuple[str, ...] = ()
    target_errors: tuple[str, ...] = ()
    feature_set_warnings: tuple[str, ...] = ()
    feature_set_blockers: tuple[str, ...] = ()
    feature_set_errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    blockers: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name in (
            "missing_topology",
            "selected_features",
            "rejected_features",
            "selected_target_output_columns",
            "selected_future_derived_columns",
            "selected_target_only_columns",
            "selected_feature_eligible_false_columns",
            "selected_alignment_key_columns",
            "feature_column_diagnostics",
            "dataset_warnings",
            "dataset_blockers",
            "dataset_errors",
            "target_warnings",
            "target_blockers",
            "target_errors",
            "feature_set_warnings",
            "feature_set_blockers",
            "feature_set_errors",
            "warnings",
            "blockers",
            "errors",
        ):
            object.__setattr__(self, name, tuple(getattr(self, name)))
        object.__setattr__(self, "regression_stats", dict(self.regression_stats))
        object.__setattr__(self, "class_distribution", dict(self.class_distribution))
        object.__setattr__(self, "group_summary", dict(self.group_summary))
        object.__setattr__(self, "leakage_summary", dict(self.leakage_summary))

    def to_dict(self) -> dict[str, object]:
        return {
            "database_id": self.database_id,
            "display_name": self.display_name,
            "exchange": self.exchange,
            "market_type": self.market_type,
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "manifest_path": self.manifest_path,
            "dataframe_path": self.dataframe_path,
            "status": self.status,
            "readiness_status": self.readiness_status,
            "strict_ready": bool(self.strict_ready),
            "can_preview": bool(self.can_preview),
            "row_count": self.row_count,
            "column_count": self.column_count,
            "first_ts_ms": self.first_ts_ms,
            "last_ts_ms": self.last_ts_ms,
            "source_ohlcv_drift_status": self.source_ohlcv_drift_status,
            "geography_status": self.geography_status,
            "missing_topology": list(self.missing_topology),
            "target_family": self.target_family,
            "label_type": self.label_type,
            "target_output_column": self.target_output_column,
            "horizon_bars": self.horizon_bars,
            "target_row_count": self.target_row_count,
            "available_label_count": int(self.available_label_count),
            "unavailable_label_count": int(self.unavailable_label_count),
            "label_availability_ratio": self.label_availability_ratio,
            "first_available_label_ts_ms": self.first_available_label_ts_ms,
            "last_available_label_ts_ms": self.last_available_label_ts_ms,
            "regression_stats": _json_safe_mapping(self.regression_stats),
            "class_distribution": _json_safe_mapping(self.class_distribution),
            "selected_feature_count": int(self.selected_feature_count),
            "accepted_feature_count": int(self.accepted_feature_count),
            "rejected_feature_count": int(self.rejected_feature_count),
            "selected_features": list(self.selected_features),
            "rejected_features": list(self.rejected_features),
            "group_summary": _json_safe_mapping(self.group_summary),
            "has_leakage_blockers": bool(self.has_leakage_blockers),
            "selected_target_output_columns": list(self.selected_target_output_columns),
            "selected_future_derived_columns": list(self.selected_future_derived_columns),
            "selected_target_only_columns": list(self.selected_target_only_columns),
            "selected_feature_eligible_false_columns": list(
                self.selected_feature_eligible_false_columns
            ),
            "selected_alignment_key_columns": list(self.selected_alignment_key_columns),
            "leakage_summary": _json_safe_mapping(self.leakage_summary),
            "feature_column_diagnostics": [
                diagnostic.to_dict() for diagnostic in self.feature_column_diagnostics
            ],
            "dataset_warnings": list(self.dataset_warnings),
            "dataset_blockers": list(self.dataset_blockers),
            "dataset_errors": list(self.dataset_errors),
            "target_warnings": list(self.target_warnings),
            "target_blockers": list(self.target_blockers),
            "target_errors": list(self.target_errors),
            "feature_set_warnings": list(self.feature_set_warnings),
            "feature_set_blockers": list(self.feature_set_blockers),
            "feature_set_errors": list(self.feature_set_errors),
            "warnings": list(self.warnings),
            "blockers": list(self.blockers),
            "errors": list(self.errors),
        }


class AnalysisSuiteDiagnosticReportService:
    """
    Compose AS1, AS5, and AS6 diagnostics into one pre-analysis report.

    The service owns cross-report coherence checks and selected-feature
    physical consistency diagnostics. It does not own dataset readiness policy,
    target generation, feature eligibility, persistence, GUI behavior, model
    training, signal generation, artifact calculation, or database mutation.
    """

    def build_report(
        self,
        *,
        readiness_report: AnalysisSuiteDatasetReadinessReport,
        target_report: AnalysisSuiteTargetPreviewReport,
        feature_set_report: AnalysisSuiteFeatureSetPreviewReport,
    ) -> AnalysisSuiteDiagnosticReport:
        """Build a read-only diagnostic report from existing AS reports."""

        try:
            return _build_report(
                readiness_report=readiness_report,
                target_report=target_report,
                feature_set_report=feature_set_report,
            )
        except Exception as exc:
            return _error_report(
                readiness_report=readiness_report,
                target_report=target_report,
                feature_set_report=feature_set_report,
                exc=exc,
            )

    def diagnose(
        self,
        *,
        readiness_report: AnalysisSuiteDatasetReadinessReport,
        target_report: AnalysisSuiteTargetPreviewReport,
        feature_set_report: AnalysisSuiteFeatureSetPreviewReport,
    ) -> AnalysisSuiteDiagnosticReport:
        """Alias for ``build_report``."""

        return self.build_report(
            readiness_report=readiness_report,
            target_report=target_report,
            feature_set_report=feature_set_report,
        )


def _build_report(
    *,
    readiness_report: AnalysisSuiteDatasetReadinessReport,
    target_report: AnalysisSuiteTargetPreviewReport,
    feature_set_report: AnalysisSuiteFeatureSetPreviewReport,
) -> AnalysisSuiteDiagnosticReport:
    warnings = _prefixed("dataset", _tuple_attr(readiness_report, "warnings"))
    blockers = _prefixed("dataset", _tuple_attr(readiness_report, "blockers"))
    errors = _prefixed("dataset", _tuple_attr(readiness_report, "errors"))
    warnings += _prefixed("target", _tuple_attr(target_report, "warnings"))
    blockers += _prefixed("target", _tuple_attr(target_report, "blockers"))
    errors += _prefixed("target", _tuple_attr(target_report, "errors"))
    warnings += _prefixed("feature_set", _tuple_attr(feature_set_report, "warnings"))
    blockers += _prefixed("feature_set", _tuple_attr(feature_set_report, "blockers"))
    errors += _prefixed("feature_set", _tuple_attr(feature_set_report, "errors"))

    if errors:
        blockers += ("upstream_errors_present",)

    can_preview = bool(getattr(readiness_report, "can_preview", False))
    strict_ready = bool(getattr(readiness_report, "strict_ready", False))
    if not can_preview:
        blockers += ("dataset_not_previewable",)
    elif not strict_ready:
        warnings += ("dataset_not_strict_ready",)

    if str(getattr(target_report, "status", "")) != "previewable":
        blockers += (f"target_report_not_previewable: {getattr(target_report, 'status', '')}",)
    if str(getattr(feature_set_report, "status", "")) != "previewable":
        blockers += (f"feature_set_report_not_previewable: {getattr(feature_set_report, 'status', '')}",)

    blockers += _identity_blockers(
        readiness_report=readiness_report,
        target_report=target_report,
        feature_set_report=feature_set_report,
    )

    target_definition = getattr(target_report, "target_definition", None)
    target_family = str(getattr(target_definition, "target_family", ""))
    label_type = str(getattr(target_definition, "label_type", ""))
    target_output_column = str(getattr(target_definition, "output_column_name", ""))
    horizon_bars = _int_or_none(getattr(target_definition, "horizon_bars", None))
    available_label_count = _int_attr(target_report, "available_label_count", default=0)
    unavailable_label_count = _int_attr(target_report, "unavailable_label_count", default=0)
    target_row_count = _int_or_none(getattr(target_report, "row_count", None))
    label_ratio = _label_availability_ratio(
        available_label_count=available_label_count,
        unavailable_label_count=unavailable_label_count,
        row_count=target_row_count,
    )

    if available_label_count <= 0:
        blockers += ("no_available_labels",)
    elif available_label_count < LOW_LABEL_COUNT_WARNING_THRESHOLD:
        warnings += (f"low_available_label_count: {available_label_count}",)
    if label_ratio is not None and 0.0 < label_ratio < LOW_LABEL_AVAILABILITY_RATIO:
        warnings += (f"low_label_availability_ratio: {label_ratio:.4f}",)

    class_distribution = _mapping_attr(target_report, "class_distribution")
    if label_type == "classification":
        class_blockers, class_warnings = _classification_diagnostics(
            class_distribution=class_distribution,
        )
        blockers += class_blockers
        warnings += class_warnings

    selected_candidates = tuple(getattr(feature_set_report, "selected_features", ()))
    rejected_candidates = tuple(getattr(feature_set_report, "rejected_features", ()))
    selected_features = _candidate_names(selected_candidates)
    rejected_features = _candidate_names(rejected_candidates)
    accepted_feature_count = _int_attr(
        feature_set_report,
        "accepted_selected_count",
        default=len(selected_features),
    )
    rejected_feature_count = _int_attr(
        feature_set_report,
        "rejected_selected_count",
        default=len(rejected_features),
    )
    selected_feature_count = _int_attr(
        feature_set_report,
        "selected_count",
        default=accepted_feature_count + rejected_feature_count,
    )

    if accepted_feature_count <= 0:
        blockers += ("no_accepted_features",)
    elif accepted_feature_count < MIN_FEATURE_COUNT_WARNING_THRESHOLD:
        warnings += (f"small_feature_set: {accepted_feature_count}",)

    leakage = _leakage_diagnostics(
        rejected_candidates=rejected_candidates,
        target_output_column=target_output_column,
        leakage_summary=_mapping_attr(feature_set_report, "leakage_summary"),
    )
    if leakage["has_leakage_blockers"]:
        blockers += ("leakage_blockers_present",)

    feature_column_diagnostics: tuple[AnalysisSuiteFeatureColumnDiagnostic, ...] = ()
    if can_preview and selected_candidates:
        dataframe_path = _first_text_attr(
            "dataframe_path",
            readiness_report,
            target_report,
        )
        if dataframe_path:
            feature_column_diagnostics, physical_blockers, physical_warnings, physical_errors = (
                _feature_column_diagnostics(
                    dataframe_path=Path(dataframe_path),
                    candidates=selected_candidates,
                )
            )
            blockers += physical_blockers
            warnings += physical_warnings
            errors += physical_errors
        else:
            blockers += ("dataframe_path_missing_for_feature_diagnostics",)

    status = _diagnostic_status(warnings=warnings, blockers=blockers, errors=errors)

    return AnalysisSuiteDiagnosticReport(
        database_id=_first_text_attr(
            "database_id",
            readiness_report,
            target_report,
            feature_set_report,
        )
        or "",
        display_name=_first_text_attr(
            "display_name",
            readiness_report,
            target_report,
            feature_set_report,
        )
        or "",
        exchange=_first_text_attr("exchange", readiness_report, target_report, feature_set_report)
        or "",
        market_type=_first_text_attr(
            "market_type",
            readiness_report,
            target_report,
            feature_set_report,
        )
        or "",
        symbol=_first_text_attr("symbol", readiness_report, target_report, feature_set_report)
        or "",
        timeframe=_first_text_attr(
            "timeframe",
            readiness_report,
            target_report,
            feature_set_report,
        )
        or "",
        manifest_path=_first_text_attr("manifest_path", readiness_report, target_report),
        dataframe_path=_first_text_attr("dataframe_path", readiness_report, target_report),
        status=status,
        readiness_status=str(getattr(readiness_report, "readiness_status", "")),
        strict_ready=strict_ready,
        can_preview=can_preview,
        row_count=_int_or_none(getattr(readiness_report, "row_count", None)),
        column_count=_int_or_none(getattr(readiness_report, "column_count", None)),
        first_ts_ms=_int_or_none(getattr(readiness_report, "first_ts_ms", None)),
        last_ts_ms=_int_or_none(getattr(readiness_report, "last_ts_ms", None)),
        source_ohlcv_drift_status=_optional_str(
            getattr(readiness_report, "source_ohlcv_drift_status", None)
        ),
        geography_status=_optional_str(getattr(readiness_report, "geography_status", None)),
        missing_topology=_tuple_attr(readiness_report, "missing_topology"),
        target_family=target_family,
        label_type=label_type,
        target_output_column=target_output_column,
        horizon_bars=horizon_bars,
        target_row_count=target_row_count,
        available_label_count=available_label_count,
        unavailable_label_count=unavailable_label_count,
        label_availability_ratio=label_ratio,
        first_available_label_ts_ms=_int_or_none(
            getattr(target_report, "first_available_ts_ms", None)
        ),
        last_available_label_ts_ms=_int_or_none(
            getattr(target_report, "last_available_ts_ms", None)
        ),
        regression_stats=_mapping_attr(target_report, "regression_stats"),
        class_distribution=class_distribution,
        selected_feature_count=selected_feature_count,
        accepted_feature_count=accepted_feature_count,
        rejected_feature_count=rejected_feature_count,
        selected_features=selected_features,
        rejected_features=rejected_features,
        group_summary=_mapping_attr(feature_set_report, "group_summary"),
        has_leakage_blockers=bool(leakage["has_leakage_blockers"]),
        selected_target_output_columns=tuple(leakage["selected_target_output_columns"]),
        selected_future_derived_columns=tuple(leakage["selected_future_derived_columns"]),
        selected_target_only_columns=tuple(leakage["selected_target_only_columns"]),
        selected_feature_eligible_false_columns=tuple(
            leakage["selected_feature_eligible_false_columns"]
        ),
        selected_alignment_key_columns=tuple(leakage["selected_alignment_key_columns"]),
        leakage_summary=leakage["leakage_summary"],
        feature_column_diagnostics=feature_column_diagnostics,
        dataset_warnings=_tuple_attr(readiness_report, "warnings"),
        dataset_blockers=_tuple_attr(readiness_report, "blockers"),
        dataset_errors=_tuple_attr(readiness_report, "errors"),
        target_warnings=_tuple_attr(target_report, "warnings"),
        target_blockers=_tuple_attr(target_report, "blockers"),
        target_errors=_tuple_attr(target_report, "errors"),
        feature_set_warnings=_tuple_attr(feature_set_report, "warnings"),
        feature_set_blockers=_tuple_attr(feature_set_report, "blockers"),
        feature_set_errors=_tuple_attr(feature_set_report, "errors"),
        warnings=_dedupe(warnings),
        blockers=_dedupe(blockers),
        errors=_dedupe(errors),
    )


def _feature_column_diagnostics(
    *,
    dataframe_path: Path,
    candidates: tuple[AnalysisSuiteFeatureCandidate, ...],
) -> tuple[
    tuple[AnalysisSuiteFeatureColumnDiagnostic, ...],
    tuple[str, ...],
    tuple[str, ...],
    tuple[str, ...],
]:
    if not dataframe_path.exists():
        return (), (f"dataframe_missing_for_feature_diagnostics: {dataframe_path}",), (), ()

    try:
        header = tuple(str(column) for column in pd.read_csv(dataframe_path, nrows=0).columns)
    except Exception as exc:
        return (), (), (), (f"dataframe_header_read_failed: {type(exc).__name__}: {exc}",)

    candidate_by_name = {str(candidate.column_name): candidate for candidate in candidates}
    selected_columns = tuple(candidate_by_name)
    missing = tuple(column for column in selected_columns if column not in header)
    present = tuple(column for column in selected_columns if column in header)

    diagnostics: list[AnalysisSuiteFeatureColumnDiagnostic] = []
    blockers: list[str] = []
    warnings: list[str] = []
    errors: list[str] = []

    for column in missing:
        candidate = candidate_by_name[column]
        diagnostics.append(
            AnalysisSuiteFeatureColumnDiagnostic(
                column_name=column,
                declared_dtype=_optional_str(getattr(candidate, "dtype", None)),
                dtype=None,
                row_count=None,
                non_null_count=None,
                null_count=None,
                null_ratio=None,
                finite_count=None,
                non_finite_count=None,
                blockers=("feature_missing_from_dataframe",),
            )
        )
        blockers.append(f"feature_missing_from_dataframe: {column}")

    if not present:
        return tuple(diagnostics), tuple(blockers), tuple(warnings), tuple(errors)

    states = {column: _FeatureColumnState(column_name=column) for column in present}
    try:
        for chunk in pd.read_csv(dataframe_path, usecols=list(present), chunksize=50_000):
            for column in present:
                states[column].consume(chunk[column])
    except Exception as exc:
        return (
            tuple(diagnostics),
            tuple(blockers),
            tuple(warnings),
            tuple(errors) + (f"feature_diagnostics_read_failed: {type(exc).__name__}: {exc}",),
        )

    for column in present:
        diagnostic = states[column].to_diagnostic(
            declared_dtype=_optional_str(getattr(candidate_by_name[column], "dtype", None))
        )
        diagnostics.append(diagnostic)
        for blocker in diagnostic.blockers:
            blockers.append(f"{blocker}: {column}")
        for warning in diagnostic.warnings:
            warnings.append(f"{warning}: {column}")

    return tuple(diagnostics), tuple(blockers), tuple(warnings), tuple(errors)


@dataclass
class _FeatureColumnState:
    column_name: str
    row_count: int = 0
    non_null_count: int = 0
    finite_count: int | None = 0
    all_numeric: bool = True
    dtype_names: set[str] = field(default_factory=set)

    def consume(self, series: pd.Series) -> None:
        self.row_count += int(len(series))
        non_null = series.notna()
        self.non_null_count += int(non_null.sum())
        self.dtype_names.add(str(series.dtype))
        if not pd.api.types.is_numeric_dtype(series):
            self.all_numeric = False
            self.finite_count = None
            return
        if self.finite_count is None:
            return
        numeric = pd.to_numeric(series, errors="coerce")
        self.finite_count += sum(
            1
            for value in numeric[non_null]
            if value is not None and pd.notna(value) and math.isfinite(float(value))
        )

    def to_diagnostic(self, *, declared_dtype: str | None) -> AnalysisSuiteFeatureColumnDiagnostic:
        null_count = self.row_count - self.non_null_count
        null_ratio = _ratio(null_count, self.row_count)
        blockers: list[str] = []
        warnings: list[str] = []
        if null_ratio is not None and null_ratio >= ALL_NULL_FEATURE_RATIO:
            blockers.append("feature_all_null")
        elif null_ratio is not None and null_ratio >= HIGH_FEATURE_NULL_RATIO:
            warnings.append(f"feature_high_missingness: {null_ratio:.4f}")
        finite_count = self.finite_count if self.all_numeric else None
        non_finite_count = (
            None
            if finite_count is None
            else max(0, self.non_null_count - int(finite_count))
        )
        return AnalysisSuiteFeatureColumnDiagnostic(
            column_name=self.column_name,
            declared_dtype=declared_dtype,
            dtype=_dtype_name(self.dtype_names),
            row_count=self.row_count,
            non_null_count=self.non_null_count,
            null_count=null_count,
            null_ratio=null_ratio,
            finite_count=finite_count,
            non_finite_count=non_finite_count,
            blockers=tuple(blockers),
            warnings=tuple(warnings),
        )


def _classification_diagnostics(
    *,
    class_distribution: Mapping[str, object],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    observed = {
        str(label): int(count)
        for label, count in class_distribution.items()
        if str(label) != "unavailable" and _int_or_none(count) and int(count) > 0
    }
    if not observed:
        return ("classification_target_has_no_observed_classes",), ()
    if len(observed) < 2:
        return ("classification_target_has_fewer_than_two_observed_classes",), ()
    total = sum(observed.values())
    dominant = max(observed.values())
    if total > 0 and dominant / total >= CLASSIFICATION_IMBALANCE_RATIO:
        return (), (f"classification_target_imbalanced: {dominant / total:.4f}",)
    return (), ()


def _leakage_diagnostics(
    *,
    rejected_candidates: tuple[AnalysisSuiteFeatureCandidate, ...],
    target_output_column: str,
    leakage_summary: Mapping[str, object],
) -> dict[str, object]:
    selected_target_output_columns: list[str] = []
    selected_future_derived_columns: list[str] = []
    selected_target_only_columns: list[str] = []
    selected_feature_eligible_false_columns: list[str] = []
    selected_alignment_key_columns: list[str] = []

    for candidate in rejected_candidates:
        column = str(getattr(candidate, "column_name", ""))
        if target_output_column and column == target_output_column:
            selected_target_output_columns.append(column)
        if bool(getattr(candidate, "future_derived", False)):
            selected_future_derived_columns.append(column)
        if str(getattr(candidate, "leakage_role", "")) == "target_only":
            selected_target_only_columns.append(column)
        if not bool(getattr(candidate, "feature_eligible", True)):
            selected_feature_eligible_false_columns.append(column)
        if column == "ts_ms" or str(getattr(candidate, "group", "")) == "alignment":
            selected_alignment_key_columns.append(column)

    has_leakage_blockers = any(
        (
            selected_target_output_columns,
            selected_future_derived_columns,
            selected_target_only_columns,
            selected_feature_eligible_false_columns,
            selected_alignment_key_columns,
        )
    )
    summary = dict(leakage_summary)
    summary.update(
        {
            "selected_target_output_columns": tuple(selected_target_output_columns),
            "selected_future_derived_columns": tuple(selected_future_derived_columns),
            "selected_target_only_columns": tuple(selected_target_only_columns),
            "selected_feature_eligible_false_columns": tuple(
                selected_feature_eligible_false_columns
            ),
            "selected_alignment_key_columns": tuple(selected_alignment_key_columns),
        }
    )
    return {
        "has_leakage_blockers": has_leakage_blockers,
        "selected_target_output_columns": tuple(selected_target_output_columns),
        "selected_future_derived_columns": tuple(selected_future_derived_columns),
        "selected_target_only_columns": tuple(selected_target_only_columns),
        "selected_feature_eligible_false_columns": tuple(
            selected_feature_eligible_false_columns
        ),
        "selected_alignment_key_columns": tuple(selected_alignment_key_columns),
        "leakage_summary": summary,
    }


def _identity_blockers(
    *,
    readiness_report: object,
    target_report: object,
    feature_set_report: object,
) -> tuple[str, ...]:
    blockers: list[str] = []
    for attr in ("database_id", "exchange", "market_type", "symbol", "timeframe"):
        values = {
            str(value)
            for value in (
                getattr(readiness_report, attr, None),
                getattr(target_report, attr, None),
                getattr(feature_set_report, attr, None),
            )
            if value not in (None, "")
        }
        if len(values) > 1:
            blockers.append(f"report_identity_mismatch: {attr}")
    return tuple(blockers)


def _error_report(
    *,
    readiness_report: AnalysisSuiteDatasetReadinessReport,
    target_report: AnalysisSuiteTargetPreviewReport,
    feature_set_report: AnalysisSuiteFeatureSetPreviewReport,
    exc: Exception,
) -> AnalysisSuiteDiagnosticReport:
    return AnalysisSuiteDiagnosticReport(
        database_id=_first_text_attr("database_id", readiness_report, target_report, feature_set_report)
        or "",
        display_name=_first_text_attr(
            "display_name",
            readiness_report,
            target_report,
            feature_set_report,
        )
        or "",
        exchange=_first_text_attr("exchange", readiness_report, target_report, feature_set_report)
        or "",
        market_type=_first_text_attr(
            "market_type",
            readiness_report,
            target_report,
            feature_set_report,
        )
        or "",
        symbol=_first_text_attr("symbol", readiness_report, target_report, feature_set_report)
        or "",
        timeframe=_first_text_attr("timeframe", readiness_report, target_report, feature_set_report)
        or "",
        manifest_path=_first_text_attr("manifest_path", readiness_report, target_report),
        dataframe_path=_first_text_attr("dataframe_path", readiness_report, target_report),
        status="error",
        readiness_status=str(getattr(readiness_report, "readiness_status", "")),
        strict_ready=bool(getattr(readiness_report, "strict_ready", False)),
        can_preview=bool(getattr(readiness_report, "can_preview", False)),
        row_count=_int_or_none(getattr(readiness_report, "row_count", None)),
        column_count=_int_or_none(getattr(readiness_report, "column_count", None)),
        first_ts_ms=_int_or_none(getattr(readiness_report, "first_ts_ms", None)),
        last_ts_ms=_int_or_none(getattr(readiness_report, "last_ts_ms", None)),
        source_ohlcv_drift_status=_optional_str(
            getattr(readiness_report, "source_ohlcv_drift_status", None)
        ),
        geography_status=_optional_str(getattr(readiness_report, "geography_status", None)),
        missing_topology=_tuple_attr(readiness_report, "missing_topology"),
        target_family=str(getattr(getattr(target_report, "target_definition", None), "target_family", "")),
        label_type=str(getattr(getattr(target_report, "target_definition", None), "label_type", "")),
        target_output_column=str(
            getattr(getattr(target_report, "target_definition", None), "output_column_name", "")
        ),
        horizon_bars=_int_or_none(
            getattr(getattr(target_report, "target_definition", None), "horizon_bars", None)
        ),
        target_row_count=_int_or_none(getattr(target_report, "row_count", None)),
        available_label_count=_int_attr(target_report, "available_label_count", default=0),
        unavailable_label_count=_int_attr(target_report, "unavailable_label_count", default=0),
        label_availability_ratio=None,
        first_available_label_ts_ms=_int_or_none(
            getattr(target_report, "first_available_ts_ms", None)
        ),
        last_available_label_ts_ms=_int_or_none(
            getattr(target_report, "last_available_ts_ms", None)
        ),
        regression_stats=_mapping_attr(target_report, "regression_stats"),
        class_distribution=_mapping_attr(target_report, "class_distribution"),
        selected_feature_count=_int_attr(feature_set_report, "selected_count", default=0),
        accepted_feature_count=_int_attr(
            feature_set_report,
            "accepted_selected_count",
            default=0,
        ),
        rejected_feature_count=_int_attr(
            feature_set_report,
            "rejected_selected_count",
            default=0,
        ),
        selected_features=_candidate_names(tuple(getattr(feature_set_report, "selected_features", ()))),
        rejected_features=_candidate_names(tuple(getattr(feature_set_report, "rejected_features", ()))),
        group_summary=_mapping_attr(feature_set_report, "group_summary"),
        leakage_summary=_mapping_attr(feature_set_report, "leakage_summary"),
        dataset_warnings=_tuple_attr(readiness_report, "warnings"),
        dataset_blockers=_tuple_attr(readiness_report, "blockers"),
        dataset_errors=_tuple_attr(readiness_report, "errors"),
        target_warnings=_tuple_attr(target_report, "warnings"),
        target_blockers=_tuple_attr(target_report, "blockers"),
        target_errors=_tuple_attr(target_report, "errors"),
        feature_set_warnings=_tuple_attr(feature_set_report, "warnings"),
        feature_set_blockers=_tuple_attr(feature_set_report, "blockers"),
        feature_set_errors=_tuple_attr(feature_set_report, "errors"),
        errors=(f"diagnostic_report_failed: {type(exc).__name__}: {exc}",),
    )


def _diagnostic_status(
    *,
    warnings: tuple[str, ...],
    blockers: tuple[str, ...],
    errors: tuple[str, ...],
) -> AnalysisSuiteDiagnosticStatus:
    if errors:
        return "error"
    if blockers:
        return "blocked"
    if warnings:
        return "warning"
    return "ready"


def _label_availability_ratio(
    *,
    available_label_count: int,
    unavailable_label_count: int,
    row_count: int | None,
) -> float | None:
    denominator = row_count if row_count and row_count > 0 else available_label_count + unavailable_label_count
    return _ratio(available_label_count, denominator)


def _ratio(numerator: int, denominator: int | None) -> float | None:
    if denominator is None or denominator <= 0:
        return None
    return float(numerator) / float(denominator)


def _candidate_names(candidates: tuple[object, ...]) -> tuple[str, ...]:
    return tuple(
        str(getattr(candidate, "column_name", ""))
        for candidate in candidates
        if str(getattr(candidate, "column_name", "")).strip()
    )


def _first_text_attr(attr: str, *objects: object) -> str | None:
    for obj in objects:
        value = _optional_str(getattr(obj, attr, None))
        if value:
            return value
    return None


def _tuple_attr(obj: object, attr: str) -> tuple[str, ...]:
    value = getattr(obj, attr, ())
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    return tuple(str(item) for item in value)


def _mapping_attr(obj: object, attr: str) -> dict[str, object]:
    value = getattr(obj, attr, {})
    if isinstance(value, Mapping):
        return _json_safe_mapping(value)
    return {}


def _int_attr(obj: object, attr: str, *, default: int) -> int:
    value = _int_or_none(getattr(obj, attr, None))
    return default if value is None else value


def _prefixed(prefix: str, values: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(f"{prefix}: {value}" for value in values)


def _dedupe(values: tuple[str, ...]) -> tuple[str, ...]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        out.append(value)
    return tuple(out)


def _dtype_name(dtype_names: set[str]) -> str | None:
    if not dtype_names:
        return None
    if len(dtype_names) == 1:
        return next(iter(dtype_names))
    return "mixed:" + ",".join(sorted(dtype_names))


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _int_or_none(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _json_safe_mapping(values: Mapping[str, object]) -> dict[str, object]:
    return {str(key): _json_safe_value(value) for key, value in values.items()}


def _json_safe_value(value: object) -> object:
    if isinstance(value, Mapping):
        return _json_safe_mapping(value)
    if isinstance(value, tuple | list):
        return [_json_safe_value(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, Path):
        return str(value)
    if value is None or isinstance(value, bool | int | float | str):
        return value
    return str(value)


__all__ = [
    "AnalysisSuiteDiagnosticReport",
    "AnalysisSuiteDiagnosticReportService",
    "AnalysisSuiteDiagnosticStatus",
    "AnalysisSuiteFeatureColumnDiagnostic",
]
