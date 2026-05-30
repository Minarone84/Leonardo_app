"""Temporal validation support for Analysis Suite rule candidates.

The module implements the first Analysis Suite candidate validation layer. It
splits explicit AS10 comparison cohorts into chronological discovery and
validation segments, retests AS11 candidates through the AS10 rule tester, and
reports survival, degradation, and stability diagnostics.

The validator is read-only. It does not build genome paths, rescan candidate
vocabularies, persist reports, or interpret diagnostic metrics as trading
performance.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from math import ceil, isfinite
from typing import Any, Mapping, Sequence

from leonardo.data.historical.analysis_suite_rule_candidate_scanner import (
    AnalysisSuiteRuleCandidate,
    AnalysisSuiteRuleCandidateScanReport,
)
from leonardo.data.historical.analysis_suite_whitebox_rule_tester import (
    AnalysisSuiteComparisonCohort,
    AnalysisSuiteComparisonSetDefinition,
    AnalysisSuiteRuleMetricSummary,
    AnalysisSuiteRuleTestReport,
    AnalysisSuiteWhiteBoxRuleTester,
)

JsonValue = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]

ANALYSIS_SUITE_CANDIDATE_TEMPORAL_VALIDATION_SCHEMA_VERSION = 1
DEFAULT_CANDIDATES_VALIDATED_LIMIT = 100
MAX_CANDIDATES_VALIDATED_LIMIT = 500

SUPPORTED_SPLIT_METHODS = frozenset({"chronological_holdout"})


@dataclass(frozen=True)
class AnalysisSuiteTemporalValidationSegment:
    """Describe one chronological validation segment."""

    segment_key: str
    role: str
    start_ts_ms: int | None = None
    end_ts_ms: int | None = None
    metadata: Mapping[str, JsonValue] = field(default_factory=dict)
    schema_version: int = ANALYSIS_SUITE_CANDIDATE_TEMPORAL_VALIDATION_SCHEMA_VERSION

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "schema_version": self.schema_version,
            "segment_key": self.segment_key,
            "role": self.role,
            "start_ts_ms": self.start_ts_ms,
            "end_ts_ms": self.end_ts_ms,
            "metadata": _json_safe_mapping(self.metadata),
        }


@dataclass(frozen=True)
class AnalysisSuiteTemporalValidationConfig:
    """Configuration for candidate temporal validation."""

    split_method: str = "chronological_holdout"
    validation_fraction: float = 0.30
    min_segment_total: int = 30
    min_segment_positive: int = 10
    min_segment_negative: int = 10
    min_validation_support: int = 10
    min_validation_positive_matches: int = 3
    min_validation_precision: float | None = None
    min_validation_lift: float | None = None
    max_precision_degradation: float = 0.50
    max_lift_degradation: float = 0.50
    max_candidates_validated: int = DEFAULT_CANDIDATES_VALIDATED_LIMIT
    metadata: Mapping[str, JsonValue] = field(default_factory=dict)
    schema_version: int = ANALYSIS_SUITE_CANDIDATE_TEMPORAL_VALIDATION_SCHEMA_VERSION

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "schema_version": self.schema_version,
            "split_method": self.split_method,
            "validation_fraction": self.validation_fraction,
            "min_segment_total": self.min_segment_total,
            "min_segment_positive": self.min_segment_positive,
            "min_segment_negative": self.min_segment_negative,
            "min_validation_support": self.min_validation_support,
            "min_validation_positive_matches": self.min_validation_positive_matches,
            "min_validation_precision": self.min_validation_precision,
            "min_validation_lift": self.min_validation_lift,
            "max_precision_degradation": self.max_precision_degradation,
            "max_lift_degradation": self.max_lift_degradation,
            "max_candidates_validated": self.max_candidates_validated,
            "metadata": _json_safe_mapping(self.metadata),
        }


@dataclass(frozen=True)
class AnalysisSuiteCandidateSegmentValidation:
    """Store one candidate rule test result for one temporal segment."""

    candidate_key: str
    segment: AnalysisSuiteTemporalValidationSegment
    rule_test_report: AnalysisSuiteRuleTestReport
    status: str
    blockers: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    schema_version: int = ANALYSIS_SUITE_CANDIDATE_TEMPORAL_VALIDATION_SCHEMA_VERSION

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "schema_version": self.schema_version,
            "candidate_key": self.candidate_key,
            "segment": self.segment.to_dict(),
            "rule_test_report": self.rule_test_report.to_dict(),
            "status": self.status,
            "blockers": list(self.blockers),
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class AnalysisSuiteCandidateMetricDegradation:
    """Compare candidate metrics between discovery and validation segments."""

    precision_delta: float | None
    precision_degradation_ratio: float | None
    lift_delta: float | None
    lift_degradation_ratio: float | None
    recall_delta: float | None
    recall_degradation_ratio: float | None
    support_delta: int | None
    support_degradation_ratio: float | None
    false_positive_rate_delta: float | None
    warnings: tuple[str, ...] = ()
    blockers: tuple[str, ...] = ()
    schema_version: int = ANALYSIS_SUITE_CANDIDATE_TEMPORAL_VALIDATION_SCHEMA_VERSION

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "schema_version": self.schema_version,
            "precision_delta": self.precision_delta,
            "precision_degradation_ratio": self.precision_degradation_ratio,
            "lift_delta": self.lift_delta,
            "lift_degradation_ratio": self.lift_degradation_ratio,
            "recall_delta": self.recall_delta,
            "recall_degradation_ratio": self.recall_degradation_ratio,
            "support_delta": self.support_delta,
            "support_degradation_ratio": self.support_degradation_ratio,
            "false_positive_rate_delta": self.false_positive_rate_delta,
            "warnings": list(self.warnings),
            "blockers": list(self.blockers),
        }


@dataclass(frozen=True)
class AnalysisSuiteCandidateTemporalValidationResult:
    """Represent temporal validation diagnostics for one AS11 candidate."""

    candidate: AnalysisSuiteRuleCandidate
    discovery_segment_report: AnalysisSuiteCandidateSegmentValidation
    validation_segment_report: AnalysisSuiteCandidateSegmentValidation
    degradation: AnalysisSuiteCandidateMetricDegradation
    survival_status: str
    stability_score: float | None
    blockers: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    metadata: Mapping[str, JsonValue] = field(default_factory=dict)
    schema_version: int = ANALYSIS_SUITE_CANDIDATE_TEMPORAL_VALIDATION_SCHEMA_VERSION

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "schema_version": self.schema_version,
            "candidate": self.candidate.to_dict(),
            "discovery_segment_report": self.discovery_segment_report.to_dict(),
            "validation_segment_report": self.validation_segment_report.to_dict(),
            "degradation": self.degradation.to_dict(),
            "survival_status": self.survival_status,
            "stability_score": self.stability_score,
            "blockers": list(self.blockers),
            "warnings": list(self.warnings),
            "metadata": _json_safe_mapping(self.metadata),
        }


@dataclass(frozen=True)
class AnalysisSuiteCandidateTemporalValidationReport:
    """Top-level report for candidate temporal validation."""

    status: str
    split_method: str
    segments: tuple[AnalysisSuiteTemporalValidationSegment, ...] = ()
    candidate_results: tuple[AnalysisSuiteCandidateTemporalValidationResult, ...] = ()
    candidate_count_input: int = 0
    candidate_count_validated: int = 0
    candidate_count_survived: int = 0
    candidate_count_degraded: int = 0
    candidate_count_failed: int = 0
    candidate_count_insufficient_data: int = 0
    candidate_count_unknown: int = 0
    sample_limited: bool = False
    blockers: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()
    metadata: Mapping[str, JsonValue] = field(default_factory=dict)
    schema_version: int = ANALYSIS_SUITE_CANDIDATE_TEMPORAL_VALIDATION_SCHEMA_VERSION

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "schema_version": self.schema_version,
            "status": self.status,
            "split_method": self.split_method,
            "segments": [segment.to_dict() for segment in self.segments],
            "candidate_results": [result.to_dict() for result in self.candidate_results],
            "candidate_count_input": self.candidate_count_input,
            "candidate_count_validated": self.candidate_count_validated,
            "candidate_count_survived": self.candidate_count_survived,
            "candidate_count_degraded": self.candidate_count_degraded,
            "candidate_count_failed": self.candidate_count_failed,
            "candidate_count_insufficient_data": self.candidate_count_insufficient_data,
            "candidate_count_unknown": self.candidate_count_unknown,
            "sample_limited": self.sample_limited,
            "blockers": list(self.blockers),
            "warnings": list(self.warnings),
            "errors": list(self.errors),
            "metadata": _json_safe_mapping(self.metadata),
        }


@dataclass(frozen=True)
class _TimestampedPath:
    cohort_role: str
    path_index: int
    anchor_ts_ms: int
    path: Any


@dataclass(frozen=True)
class _SplitResult:
    discovery_segment: AnalysisSuiteTemporalValidationSegment
    validation_segment: AnalysisSuiteTemporalValidationSegment
    discovery_comparison_set: AnalysisSuiteComparisonSetDefinition
    validation_comparison_set: AnalysisSuiteComparisonSetDefinition
    warnings: tuple[str, ...] = ()
    blockers: tuple[str, ...] = ()


class AnalysisSuiteCandidateTemporalValidator:
    """Validate AS11 rule candidates across chronological AS10 cohort splits.

    The validator orchestrates temporal validation only. It consumes already
    prepared AS10 comparison sets and AS11 candidate scan reports, delegates all
    rule matching and metric calculation to ``AnalysisSuiteWhiteBoxRuleTester``,
    and reports diagnostic survival and degradation status.
    """

    def __init__(self, rule_tester: AnalysisSuiteWhiteBoxRuleTester | None = None) -> None:
        self._rule_tester = rule_tester or AnalysisSuiteWhiteBoxRuleTester()

    def validate_candidates(
        self,
        *,
        comparison_set: AnalysisSuiteComparisonSetDefinition,
        candidate_scan_report: AnalysisSuiteRuleCandidateScanReport,
        candidates: Sequence[AnalysisSuiteRuleCandidate] | None = None,
        diagnostic_report: Any | None = None,
        config: AnalysisSuiteTemporalValidationConfig | None = None,
    ) -> AnalysisSuiteCandidateTemporalValidationReport:
        """Validate AS11 candidates against chronological discovery and holdout segments."""

        validation_config = config or AnalysisSuiteTemporalValidationConfig()
        candidate_list = tuple(candidates) if candidates is not None else tuple(candidate_scan_report.candidates)
        candidate_count_input = len(candidate_list)

        blockers, warnings, errors = self._validate_inputs(
            comparison_set=comparison_set,
            candidate_scan_report=candidate_scan_report,
            diagnostic_report=diagnostic_report,
            config=validation_config,
            candidate_count_input=candidate_count_input,
        )
        sample_limited = _input_sample_limited(comparison_set, candidate_scan_report)
        if sample_limited:
            warnings.append("temporal_validation_inputs_are_sample_limited")
        warnings.extend(_scan_report_warnings(candidate_scan_report))
        warnings.append("temporal_validation_does_not_apply_multiple_testing_correction")

        candidate_limit = _candidate_limit(validation_config, warnings, blockers)
        skipped_by_limit = max(0, candidate_count_input - candidate_limit)
        if skipped_by_limit:
            warnings.append(f"candidate_validation_limit_applied: {candidate_limit}")

        if blockers or errors:
            return self._report(
                split_method=validation_config.split_method,
                candidate_count_input=candidate_count_input,
                sample_limited=sample_limited,
                blockers=blockers,
                warnings=warnings,
                errors=errors,
                metadata={
                    "config": validation_config.to_dict(),
                    "candidate_validation_limit": candidate_limit,
                    "candidate_count_skipped_by_limit": skipped_by_limit,
                },
            )

        split_result = self._build_chronological_holdout_split(comparison_set, validation_config)
        warnings.extend(split_result.warnings)
        if split_result.blockers:
            blockers.extend(split_result.blockers)
            return self._report(
                split_method=validation_config.split_method,
                segments=(split_result.discovery_segment, split_result.validation_segment),
                candidate_count_input=candidate_count_input,
                sample_limited=sample_limited,
                blockers=blockers,
                warnings=warnings,
                errors=errors,
                metadata={
                    "config": validation_config.to_dict(),
                    "candidate_validation_limit": candidate_limit,
                    "candidate_count_skipped_by_limit": skipped_by_limit,
                },
            )

        candidate_count_to_validate = min(candidate_count_input, candidate_limit)
        if candidate_count_to_validate and candidate_count_to_validate > _total_path_count(comparison_set) * 2:
            warnings.append("candidate_count_high_relative_to_temporal_validation_sample_size")

        candidate_results = tuple(
            self._validate_candidate(
                candidate=candidate,
                split_result=split_result,
                diagnostic_report=diagnostic_report,
                config=validation_config,
                sample_limited=sample_limited,
            )
            for candidate in candidate_list[:candidate_limit]
        )

        return self._report(
            split_method=validation_config.split_method,
            segments=(split_result.discovery_segment, split_result.validation_segment),
            candidate_results=candidate_results,
            candidate_count_input=candidate_count_input,
            sample_limited=sample_limited,
            blockers=blockers,
            warnings=warnings,
            errors=errors,
            metadata={
                "config": validation_config.to_dict(),
                "candidate_validation_limit": candidate_limit,
                "candidate_count_skipped_by_limit": skipped_by_limit,
            },
        )

    def _validate_inputs(
        self,
        *,
        comparison_set: AnalysisSuiteComparisonSetDefinition,
        candidate_scan_report: AnalysisSuiteRuleCandidateScanReport,
        diagnostic_report: Any | None,
        config: AnalysisSuiteTemporalValidationConfig,
        candidate_count_input: int,
    ) -> tuple[list[str], list[str], list[str]]:
        blockers: list[str] = []
        warnings: list[str] = []
        errors: list[str] = []

        if config.split_method not in SUPPORTED_SPLIT_METHODS:
            blockers.append(f"split_method_not_supported: {config.split_method}")
        if not (0.0 < config.validation_fraction < 1.0):
            blockers.append("validation_fraction_must_be_between_zero_and_one")

        for field_name in (
            "min_segment_total",
            "min_segment_positive",
            "min_segment_negative",
            "min_validation_support",
            "min_validation_positive_matches",
        ):
            if getattr(config, field_name) < 0:
                blockers.append(f"{field_name}_must_be_non_negative")

        if config.max_precision_degradation < 0:
            blockers.append("max_precision_degradation_must_be_non_negative")
        if config.max_lift_degradation < 0:
            blockers.append("max_lift_degradation_must_be_non_negative")

        if config.max_candidates_validated <= 0:
            blockers.append("max_candidates_validated_must_be_positive")

        if not comparison_set.positive_cohort.paths:
            blockers.append("positive_cohort_empty")
        if not comparison_set.negative_cohort.paths:
            blockers.append("negative_cohort_empty")

        scan_status = candidate_scan_report.status
        if scan_status in {"blocked", "error"}:
            blockers.append(f"candidate_scan_report_not_acceptable: {scan_status}")
        elif scan_status == "warning":
            warnings.append("candidate_scan_report_warning")

        if candidate_count_input == 0:
            blockers.append("candidate_scan_report_has_no_candidates")

        diagnostic_status = _report_status(diagnostic_report)
        if diagnostic_status in {"blocked", "error"}:
            blockers.append(f"diagnostic_report_not_acceptable: {diagnostic_status}")
        elif diagnostic_status == "warning":
            warnings.append("diagnostic_report_warning")

        return blockers, warnings, errors

    def _build_chronological_holdout_split(
        self,
        comparison_set: AnalysisSuiteComparisonSetDefinition,
        config: AnalysisSuiteTemporalValidationConfig,
    ) -> _SplitResult:
        entries, blockers = _timestamped_paths(comparison_set)
        if blockers:
            empty_discovery = AnalysisSuiteTemporalValidationSegment(
                segment_key="discovery",
                role="discovery",
                metadata={"split_method": config.split_method},
            )
            empty_validation = AnalysisSuiteTemporalValidationSegment(
                segment_key="validation",
                role="validation",
                metadata={"split_method": config.split_method},
            )
            return _SplitResult(
                discovery_segment=empty_discovery,
                validation_segment=empty_validation,
                discovery_comparison_set=_empty_segment_comparison_set(comparison_set, "discovery"),
                validation_comparison_set=_empty_segment_comparison_set(comparison_set, "validation"),
                blockers=tuple(blockers),
            )

        if len(entries) < 2:
            blocker = "not_enough_paths_for_chronological_holdout"
            empty_discovery = AnalysisSuiteTemporalValidationSegment(
                segment_key="discovery",
                role="discovery",
                metadata={"split_method": config.split_method, "path_count": len(entries)},
            )
            empty_validation = AnalysisSuiteTemporalValidationSegment(
                segment_key="validation",
                role="validation",
                metadata={"split_method": config.split_method, "path_count": 0},
            )
            return _SplitResult(
                discovery_segment=empty_discovery,
                validation_segment=empty_validation,
                discovery_comparison_set=_empty_segment_comparison_set(comparison_set, "discovery"),
                validation_comparison_set=_empty_segment_comparison_set(comparison_set, "validation"),
                blockers=(blocker,),
            )

        sorted_entries = sorted(entries, key=lambda item: (item.anchor_ts_ms, item.cohort_role, item.path_index))
        validation_count = max(1, min(len(sorted_entries) - 1, ceil(len(sorted_entries) * config.validation_fraction)))
        discovery_entries = tuple(sorted_entries[:-validation_count])
        validation_entries = tuple(sorted_entries[-validation_count:])

        discovery_segment = _segment_from_entries(
            segment_key="discovery",
            role="discovery",
            entries=discovery_entries,
            config=config,
        )
        validation_segment = _segment_from_entries(
            segment_key="validation",
            role="validation",
            entries=validation_entries,
            config=config,
        )

        return _SplitResult(
            discovery_segment=discovery_segment,
            validation_segment=validation_segment,
            discovery_comparison_set=_comparison_set_for_segment(
                comparison_set=comparison_set,
                segment=discovery_segment,
                entries=discovery_entries,
            ),
            validation_comparison_set=_comparison_set_for_segment(
                comparison_set=comparison_set,
                segment=validation_segment,
                entries=validation_entries,
            ),
        )

    def _validate_candidate(
        self,
        *,
        candidate: AnalysisSuiteRuleCandidate,
        split_result: _SplitResult,
        diagnostic_report: Any | None,
        config: AnalysisSuiteTemporalValidationConfig,
        sample_limited: bool,
    ) -> AnalysisSuiteCandidateTemporalValidationResult:
        discovery_rule_report = self._rule_tester.test_rule(
            rule_definition=candidate.rule_definition,
            comparison_set=split_result.discovery_comparison_set,
            diagnostic_report=diagnostic_report,
        )
        validation_rule_report = self._rule_tester.test_rule(
            rule_definition=candidate.rule_definition,
            comparison_set=split_result.validation_comparison_set,
            diagnostic_report=diagnostic_report,
        )

        discovery_segment_report = AnalysisSuiteCandidateSegmentValidation(
            candidate_key=candidate.candidate_key,
            segment=split_result.discovery_segment,
            rule_test_report=discovery_rule_report,
            status=discovery_rule_report.status,
            blockers=tuple(discovery_rule_report.blockers),
            warnings=tuple(discovery_rule_report.warnings),
        )
        validation_segment_report = AnalysisSuiteCandidateSegmentValidation(
            candidate_key=candidate.candidate_key,
            segment=split_result.validation_segment,
            rule_test_report=validation_rule_report,
            status=validation_rule_report.status,
            blockers=tuple(validation_rule_report.blockers),
            warnings=tuple(validation_rule_report.warnings),
        )

        degradation = _metric_degradation(discovery_rule_report.metrics, validation_rule_report.metrics)
        survival_status, status_warnings, status_blockers = _survival_status(
            discovery_rule_report=discovery_rule_report,
            validation_rule_report=validation_rule_report,
            degradation=degradation,
            config=config,
        )
        stability_score = _stability_score(
            survival_status=survival_status,
            validation_metrics=validation_rule_report.metrics,
            degradation=degradation,
            config=config,
            sample_limited=sample_limited,
        )

        warnings = _dedupe(
            tuple(candidate.warnings)
            + discovery_segment_report.warnings
            + validation_segment_report.warnings
            + degradation.warnings
            + tuple(status_warnings)
        )
        blockers = _dedupe(
            tuple(candidate.blockers)
            + discovery_segment_report.blockers
            + validation_segment_report.blockers
            + degradation.blockers
            + tuple(status_blockers)
        )

        return AnalysisSuiteCandidateTemporalValidationResult(
            candidate=candidate,
            discovery_segment_report=discovery_segment_report,
            validation_segment_report=validation_segment_report,
            degradation=degradation,
            survival_status=survival_status,
            stability_score=stability_score,
            blockers=blockers,
            warnings=warnings,
            metadata={
                "sample_limited": sample_limited,
                "stability_score_is_diagnostic": True,
            },
        )

    def _report(
        self,
        *,
        split_method: str,
        segments: tuple[AnalysisSuiteTemporalValidationSegment, ...] = (),
        candidate_results: tuple[AnalysisSuiteCandidateTemporalValidationResult, ...] = (),
        candidate_count_input: int = 0,
        sample_limited: bool = False,
        blockers: Sequence[str] = (),
        warnings: Sequence[str] = (),
        errors: Sequence[str] = (),
        metadata: Mapping[str, JsonValue] | None = None,
    ) -> AnalysisSuiteCandidateTemporalValidationReport:
        survived = sum(1 for result in candidate_results if result.survival_status == "survived")
        degraded = sum(1 for result in candidate_results if result.survival_status == "degraded")
        failed = sum(1 for result in candidate_results if result.survival_status == "failed")
        insufficient_data = sum(
            1 for result in candidate_results if result.survival_status == "insufficient_data"
        )
        unknown = sum(1 for result in candidate_results if result.survival_status == "unknown")

        return AnalysisSuiteCandidateTemporalValidationReport(
            status=_status(blockers=blockers, warnings=warnings, errors=errors),
            split_method=split_method,
            segments=segments,
            candidate_results=candidate_results,
            candidate_count_input=candidate_count_input,
            candidate_count_validated=len(candidate_results),
            candidate_count_survived=survived,
            candidate_count_degraded=degraded,
            candidate_count_failed=failed,
            candidate_count_insufficient_data=insufficient_data,
            candidate_count_unknown=unknown,
            sample_limited=sample_limited,
            blockers=_dedupe(blockers),
            warnings=_dedupe(warnings),
            errors=_dedupe(errors),
            metadata=_json_safe_mapping(metadata or {}),
        )


def _candidate_limit(
    config: AnalysisSuiteTemporalValidationConfig,
    warnings: list[str],
    blockers: list[str],
) -> int:
    if config.max_candidates_validated <= 0:
        blockers.append("max_candidates_validated_must_be_positive")
        return 0
    if config.max_candidates_validated > MAX_CANDIDATES_VALIDATED_LIMIT:
        warnings.append(f"max_candidates_validated_clamped_to_max: {MAX_CANDIDATES_VALIDATED_LIMIT}")
        return MAX_CANDIDATES_VALIDATED_LIMIT
    return config.max_candidates_validated


def _timestamped_paths(
    comparison_set: AnalysisSuiteComparisonSetDefinition,
) -> tuple[tuple[_TimestampedPath, ...], tuple[str, ...]]:
    entries: list[_TimestampedPath] = []
    blockers: list[str] = []

    for cohort_role, cohort in (
        ("positive", comparison_set.positive_cohort),
        ("negative", comparison_set.negative_cohort),
    ):
        for path_index, path in enumerate(cohort.paths):
            anchor_ts_ms = _path_anchor_ts_ms(path)
            if anchor_ts_ms is None:
                blockers.append(f"path_anchor_ts_ms_required_for_chronological_holdout: {cohort_role}:{path_index}")
                continue
            entries.append(
                _TimestampedPath(
                    cohort_role=cohort_role,
                    path_index=path_index,
                    anchor_ts_ms=anchor_ts_ms,
                    path=path,
                )
            )

    return tuple(entries), _dedupe(blockers)


def _path_anchor_ts_ms(path: Any) -> int | None:
    raw_value = _path_value(path, "anchor_ts_ms")
    if raw_value is None:
        raw_value = _path_value(path, "anchor_timestamp_ms")
    if raw_value is None:
        return None

    try:
        if hasattr(raw_value, "item"):
            raw_value = raw_value.item()
        if isinstance(raw_value, bool):
            return None
        if isinstance(raw_value, float) and not isfinite(raw_value):
            return None
        return int(raw_value)
    except (TypeError, ValueError, OverflowError):
        return None


def _path_value(path: Any, key: str) -> Any:
    if isinstance(path, Mapping):
        return path.get(key)
    return getattr(path, key, None)


def _segment_from_entries(
    *,
    segment_key: str,
    role: str,
    entries: Sequence[_TimestampedPath],
    config: AnalysisSuiteTemporalValidationConfig,
) -> AnalysisSuiteTemporalValidationSegment:
    start_ts_ms = min((entry.anchor_ts_ms for entry in entries), default=None)
    end_ts_ms = max((entry.anchor_ts_ms for entry in entries), default=None)
    positive_count = sum(1 for entry in entries if entry.cohort_role == "positive")
    negative_count = sum(1 for entry in entries if entry.cohort_role == "negative")

    return AnalysisSuiteTemporalValidationSegment(
        segment_key=segment_key,
        role=role,
        start_ts_ms=start_ts_ms,
        end_ts_ms=end_ts_ms,
        metadata={
            "split_method": config.split_method,
            "validation_fraction": config.validation_fraction,
            "path_count": len(entries),
            "positive_count": positive_count,
            "negative_count": negative_count,
        },
    )


def _comparison_set_for_segment(
    *,
    comparison_set: AnalysisSuiteComparisonSetDefinition,
    segment: AnalysisSuiteTemporalValidationSegment,
    entries: Sequence[_TimestampedPath],
) -> AnalysisSuiteComparisonSetDefinition:
    positive_paths = tuple(entry.path for entry in entries if entry.cohort_role == "positive")
    negative_paths = tuple(entry.path for entry in entries if entry.cohort_role == "negative")

    return AnalysisSuiteComparisonSetDefinition(
        comparison_key=f"{comparison_set.comparison_key}__{segment.segment_key}",
        display_name=f"{comparison_set.display_name} ({segment.segment_key})",
        positive_cohort=_cohort_for_segment(
            original=comparison_set.positive_cohort,
            paths=positive_paths,
            segment=segment,
        ),
        negative_cohort=_cohort_for_segment(
            original=comparison_set.negative_cohort,
            paths=negative_paths,
            segment=segment,
        ),
        comparison_kind=comparison_set.comparison_kind,
        metadata={
            **_json_safe_mapping(comparison_set.metadata),
            "time_split": True,
            "split_method": "chronological_holdout",
            "segment_key": segment.segment_key,
        },
    )


def _cohort_for_segment(
    *,
    original: AnalysisSuiteComparisonCohort,
    paths: tuple[Any, ...],
    segment: AnalysisSuiteTemporalValidationSegment,
) -> AnalysisSuiteComparisonCohort:
    return AnalysisSuiteComparisonCohort(
        cohort_key=f"{original.cohort_key}__{segment.segment_key}",
        label=f"{original.label} ({segment.segment_key})",
        paths=paths,
        role=original.role,
        metadata={
            **_json_safe_mapping(original.metadata),
            "time_split": True,
            "segment_key": segment.segment_key,
            "segment_role": segment.role,
            "start_ts_ms": segment.start_ts_ms,
            "end_ts_ms": segment.end_ts_ms,
            "path_count": len(paths),
            "input_path_count": len(paths),
        },
    )


def _empty_segment_comparison_set(
    comparison_set: AnalysisSuiteComparisonSetDefinition,
    segment_key: str,
) -> AnalysisSuiteComparisonSetDefinition:
    segment = AnalysisSuiteTemporalValidationSegment(
        segment_key=segment_key,
        role=segment_key,
        metadata={"split_method": "chronological_holdout", "path_count": 0},
    )
    return _comparison_set_for_segment(comparison_set=comparison_set, segment=segment, entries=())


def _survival_status(
    *,
    discovery_rule_report: AnalysisSuiteRuleTestReport,
    validation_rule_report: AnalysisSuiteRuleTestReport,
    degradation: AnalysisSuiteCandidateMetricDegradation,
    config: AnalysisSuiteTemporalValidationConfig,
) -> tuple[str, tuple[str, ...], tuple[str, ...]]:
    warnings: list[str] = []
    blockers: list[str] = []

    discovery_adequacy = _segment_sample_warnings("discovery", discovery_rule_report.metrics, config)
    validation_adequacy = _segment_sample_warnings("validation", validation_rule_report.metrics, config)
    warnings.extend(discovery_adequacy)
    warnings.extend(validation_adequacy)
    if discovery_adequacy or validation_adequacy:
        return "insufficient_data", _dedupe(warnings), tuple(blockers)

    if discovery_rule_report.status in {"blocked", "error"}:
        blockers.append(f"discovery_segment_rule_test_not_acceptable: {discovery_rule_report.status}")
        return "unknown", _dedupe(warnings), _dedupe(blockers)
    if validation_rule_report.status in {"blocked", "error"}:
        blockers.append(f"validation_segment_rule_test_not_acceptable: {validation_rule_report.status}")
        return "failed", _dedupe(warnings), _dedupe(blockers)

    validation_metrics = validation_rule_report.metrics
    if validation_metrics.support < config.min_validation_support:
        blockers.append(
            f"validation_support_below_minimum: {validation_metrics.support} < {config.min_validation_support}"
        )
        return "failed", _dedupe(warnings), _dedupe(blockers)
    if validation_metrics.positive_matched < config.min_validation_positive_matches:
        blockers.append(
            "validation_positive_matches_below_minimum: "
            f"{validation_metrics.positive_matched} < {config.min_validation_positive_matches}"
        )
        return "failed", _dedupe(warnings), _dedupe(blockers)
    if (
        config.min_validation_precision is not None
        and _metric_value(validation_metrics.precision) < config.min_validation_precision
    ):
        blockers.append(
            "validation_precision_below_minimum: "
            f"{_metric_value(validation_metrics.precision)} < {config.min_validation_precision}"
        )
        return "failed", _dedupe(warnings), _dedupe(blockers)
    if config.min_validation_lift is not None and _metric_value(validation_metrics.lift) < config.min_validation_lift:
        blockers.append(
            f"validation_lift_below_minimum: {_metric_value(validation_metrics.lift)} < {config.min_validation_lift}"
        )
        return "failed", _dedupe(warnings), _dedupe(blockers)

    if (
        degradation.precision_degradation_ratio is not None
        and degradation.precision_degradation_ratio > config.max_precision_degradation
    ):
        warnings.append(
            "precision_degradation_exceeds_maximum: "
            f"{degradation.precision_degradation_ratio} > {config.max_precision_degradation}"
        )
        return "degraded", _dedupe(warnings), _dedupe(blockers)
    if degradation.lift_degradation_ratio is not None and degradation.lift_degradation_ratio > config.max_lift_degradation:
        warnings.append(
            f"lift_degradation_exceeds_maximum: {degradation.lift_degradation_ratio} > {config.max_lift_degradation}"
        )
        return "degraded", _dedupe(warnings), _dedupe(blockers)

    return "survived", _dedupe(warnings), _dedupe(blockers)


def _segment_sample_warnings(
    segment_key: str,
    metrics: AnalysisSuiteRuleMetricSummary,
    config: AnalysisSuiteTemporalValidationConfig,
) -> tuple[str, ...]:
    total = metrics.positive_total + metrics.negative_total
    warnings: list[str] = []
    if total < config.min_segment_total:
        warnings.append(f"{segment_key}_segment_total_below_minimum: {total} < {config.min_segment_total}")
    if metrics.positive_total < config.min_segment_positive:
        warnings.append(
            f"{segment_key}_segment_positive_below_minimum: {metrics.positive_total} < {config.min_segment_positive}"
        )
    if metrics.negative_total < config.min_segment_negative:
        warnings.append(
            f"{segment_key}_segment_negative_below_minimum: {metrics.negative_total} < {config.min_segment_negative}"
        )
    return tuple(warnings)


def _metric_degradation(
    discovery_metrics: AnalysisSuiteRuleMetricSummary,
    validation_metrics: AnalysisSuiteRuleMetricSummary,
) -> AnalysisSuiteCandidateMetricDegradation:
    warnings: list[str] = []

    precision_delta, precision_ratio = _delta_and_degradation_ratio(
        "precision", discovery_metrics.precision, validation_metrics.precision, warnings
    )
    lift_delta, lift_ratio = _delta_and_degradation_ratio(
        "lift", discovery_metrics.lift, validation_metrics.lift, warnings
    )
    recall_delta, recall_ratio = _delta_and_degradation_ratio(
        "recall", discovery_metrics.recall, validation_metrics.recall, warnings
    )
    support_delta, support_ratio = _support_delta_and_ratio(
        discovery_metrics.support,
        validation_metrics.support,
        warnings,
    )

    false_positive_rate_delta = _safe_delta(
        discovery_metrics.false_positive_rate,
        validation_metrics.false_positive_rate,
    )

    return AnalysisSuiteCandidateMetricDegradation(
        precision_delta=precision_delta,
        precision_degradation_ratio=precision_ratio,
        lift_delta=lift_delta,
        lift_degradation_ratio=lift_ratio,
        recall_delta=recall_delta,
        recall_degradation_ratio=recall_ratio,
        support_delta=support_delta,
        support_degradation_ratio=support_ratio,
        false_positive_rate_delta=false_positive_rate_delta,
        warnings=_dedupe(warnings),
    )


def _delta_and_degradation_ratio(
    metric_name: str,
    discovery_value: float | None,
    validation_value: float | None,
    warnings: list[str],
) -> tuple[float | None, float | None]:
    discovery = _finite_optional_float(discovery_value)
    validation = _finite_optional_float(validation_value)
    if discovery is None or validation is None:
        warnings.append(f"{metric_name}_degradation_unavailable")
        return None, None

    delta = validation - discovery
    if discovery <= 0.0:
        warnings.append(f"{metric_name}_degradation_ratio_unavailable")
        return delta, None
    return delta, max(0.0, (discovery - validation) / discovery)


def _support_delta_and_ratio(
    discovery_support: int,
    validation_support: int,
    warnings: list[str],
) -> tuple[int | None, float | None]:
    delta = validation_support - discovery_support
    if discovery_support <= 0:
        warnings.append("support_degradation_ratio_unavailable")
        return delta, None
    return delta, max(0.0, (discovery_support - validation_support) / discovery_support)


def _safe_delta(discovery_value: float | None, validation_value: float | None) -> float | None:
    discovery = _finite_optional_float(discovery_value)
    validation = _finite_optional_float(validation_value)
    if discovery is None or validation is None:
        return None
    return validation - discovery


def _stability_score(
    *,
    survival_status: str,
    validation_metrics: AnalysisSuiteRuleMetricSummary,
    degradation: AnalysisSuiteCandidateMetricDegradation,
    config: AnalysisSuiteTemporalValidationConfig,
    sample_limited: bool,
) -> float | None:
    if survival_status in {"insufficient_data", "unknown"}:
        return None

    score = 1.0
    if degradation.precision_degradation_ratio is not None:
        score -= min(0.4, degradation.precision_degradation_ratio * 0.4)
    if degradation.lift_degradation_ratio is not None:
        score -= min(0.4, degradation.lift_degradation_ratio * 0.4)
    if validation_metrics.support < config.min_validation_support * 2:
        score -= 0.1
    if sample_limited:
        score -= 0.1
    if survival_status == "failed":
        score -= 0.2
    elif survival_status == "degraded":
        score -= 0.1

    return max(0.0, min(1.0, score))


def _input_sample_limited(
    comparison_set: AnalysisSuiteComparisonSetDefinition,
    candidate_scan_report: AnalysisSuiteRuleCandidateScanReport,
) -> bool:
    return (
        bool(candidate_scan_report.sample_limited)
        or _metadata_bool(candidate_scan_report.metadata, "sample_limited")
        or _metadata_bool(candidate_scan_report.metadata, "evaluated_sample_limited")
        or _cohort_sample_limited(comparison_set.positive_cohort)
        or _cohort_sample_limited(comparison_set.negative_cohort)
    )


def _cohort_sample_limited(cohort: AnalysisSuiteComparisonCohort) -> bool:
    if _metadata_bool(cohort.metadata, "sample_limited") or _metadata_bool(cohort.metadata, "evaluated_sample_limited"):
        return True
    input_path_count = _metadata_int(cohort.metadata, "input_path_count")
    total_path_count = _metadata_int(cohort.metadata, "total_path_count")
    path_count = len(cohort.paths)
    return (input_path_count is not None and input_path_count > path_count) or (
        total_path_count is not None and total_path_count > path_count
    )


def _metadata_bool(metadata: Mapping[str, Any], key: str) -> bool:
    value = metadata.get(key)
    return bool(value) if value is not None else False


def _metadata_int(metadata: Mapping[str, Any], key: str) -> int | None:
    value = metadata.get(key)
    try:
        if value is None or isinstance(value, bool):
            return None
        if hasattr(value, "item"):
            value = value.item()
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return None


def _scan_report_warnings(candidate_scan_report: AnalysisSuiteRuleCandidateScanReport) -> tuple[str, ...]:
    warnings = list(candidate_scan_report.warnings)
    vocabulary_report = candidate_scan_report.vocabulary_report
    warnings.extend(vocabulary_report.warnings)
    if candidate_scan_report.sample_limited or vocabulary_report.sample_limited:
        warnings.append("candidate_scan_report_sample_limited")
    return _dedupe(warnings)


def _report_status(report: Any | None) -> str | None:
    if report is None:
        return None
    if isinstance(report, Mapping):
        status = report.get("status")
    else:
        status = getattr(report, "status", None)
    return status if isinstance(status, str) else None


def _total_path_count(comparison_set: AnalysisSuiteComparisonSetDefinition) -> int:
    return len(comparison_set.positive_cohort.paths) + len(comparison_set.negative_cohort.paths)


def _status(
    *,
    blockers: Sequence[str],
    warnings: Sequence[str],
    errors: Sequence[str],
) -> str:
    if errors:
        return "error"
    if blockers:
        return "blocked"
    if warnings:
        return "warning"
    return "ready"


def _metric_value(value: float | None) -> float:
    finite_value = _finite_optional_float(value)
    return finite_value if finite_value is not None else 0.0


def _finite_optional_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        if hasattr(value, "item"):
            value = value.item()
        numeric_value = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return numeric_value if isfinite(numeric_value) else None


def _json_safe_mapping(mapping: Mapping[str, Any]) -> dict[str, JsonValue]:
    return {str(key): _json_safe_value(value) for key, value in mapping.items()}


def _json_safe_value(value: Any) -> JsonValue:
    if value is None or isinstance(value, bool | int | str):
        return value
    if isinstance(value, float):
        return value if isfinite(value) else None
    if hasattr(value, "item"):
        return _json_safe_value(value.item())
    if isinstance(value, Mapping):
        return {str(key): _json_safe_value(item) for key, item in value.items()}
    if isinstance(value, tuple | list | set):
        return [_json_safe_value(item) for item in value]
    return str(value)


def _dedupe(values: Sequence[str]) -> tuple[str, ...]:
    deduped: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return tuple(deduped)
