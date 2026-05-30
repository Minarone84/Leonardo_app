"""Bounded white-box rule candidate scanning for Analysis Suite.

The scanner builds a finite predicate vocabulary from AS9 genome paths supplied
through AS10 comparison cohorts, then evaluates each single-predicate candidate
through the AS10 white-box rule tester. It is read-only, performs no persistence,
does not regenerate upstream previews, and does not perform conjunction
expansion or unbounded rule discovery.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
import math
import re
from typing import Any, Mapping, Sequence

from leonardo.data.historical.analysis_suite_whitebox_rule_tester import (
    AnalysisSuiteComparisonSetDefinition,
    AnalysisSuiteRuleMetricSummary,
    AnalysisSuiteRulePredicate,
    AnalysisSuiteRuleTestReport,
    AnalysisSuiteWhiteBoxRuleDefinition,
    AnalysisSuiteWhiteBoxRuleTester,
)


ANALYSIS_SUITE_RULE_CANDIDATE_SCHEMA_VERSION = 1
DEFAULT_RULE_CANDIDATE_RETURN_LIMIT = 100
MAX_RULE_CANDIDATE_RETURN_LIMIT = 500
DEFAULT_MAX_DISTINCT_VALUES_PER_COMPONENT = 25
DEFAULT_ALLOWED_OPERATORS: tuple[str, ...] = ("equals",)
SUPPORTED_VOCABULARY_OPERATORS: tuple[str, ...] = (
    "equals",
    "not_equals",
    "is_null",
    "not_null",
)
SUPPORTED_NUMERIC_THRESHOLD_POLICIES: tuple[str, ...] = ("none",)

JsonValue = str | int | float | bool | None | list[Any] | dict[str, Any]


@dataclass(frozen=True)
class AnalysisSuitePredicateVocabularyItem:
    """One generated single-predicate rule candidate input.

    Vocabulary items are intentionally equivalent to AS10 rule predicates. The
    scanner stores lightweight provenance and observed support, then converts the
    item into an AS10 ``AnalysisSuiteRulePredicate`` for rule evaluation.
    """

    predicate_key: str
    component_key: str
    operator: str
    value: JsonValue = None
    values: tuple[JsonValue, ...] = ()
    path_offset: int = 0
    source: str = "observed_symbolic_value"
    support_observed: int | None = None
    metadata: Mapping[str, JsonValue] = field(default_factory=dict)
    schema_version: int = ANALYSIS_SUITE_RULE_CANDIDATE_SCHEMA_VERSION

    def to_rule_predicate(self) -> AnalysisSuiteRulePredicate:
        """Return the AS10 predicate represented by this vocabulary item."""

        return AnalysisSuiteRulePredicate(
            component_key=self.component_key,
            operator=self.operator,
            value=_json_safe_value(self.value),
            values=tuple(_json_safe_value(value) for value in self.values),
            path_offset=int(self.path_offset),
            label=self.predicate_key,
            required=True,
            metadata={
                "predicate_key": self.predicate_key,
                "source": self.source,
                "support_observed": self.support_observed,
                **_json_safe_mapping(self.metadata),
            },
        )

    def to_dict(self) -> dict[str, JsonValue]:
        """Return a JSON-safe dictionary representation."""

        return {
            "schema_version": self.schema_version,
            "predicate_key": self.predicate_key,
            "component_key": self.component_key,
            "operator": self.operator,
            "value": _json_safe_value(self.value),
            "values": [_json_safe_value(value) for value in self.values],
            "path_offset": int(self.path_offset),
            "source": self.source,
            "support_observed": self.support_observed,
            "metadata": _json_safe_mapping(self.metadata),
        }


@dataclass(frozen=True)
class AnalysisSuitePredicateVocabularyReport:
    """Report describing generated single-predicate vocabulary items."""

    status: str
    vocabulary_items: tuple[AnalysisSuitePredicateVocabularyItem, ...] = ()
    component_count: int = 0
    item_count: int = 0
    scanned_path_count: int = 0
    blockers: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()
    sample_limited: bool = False
    schema_version: int = ANALYSIS_SUITE_RULE_CANDIDATE_SCHEMA_VERSION

    def to_dict(self) -> dict[str, JsonValue]:
        """Return a JSON-safe dictionary representation."""

        return {
            "schema_version": self.schema_version,
            "status": self.status,
            "vocabulary_items": [item.to_dict() for item in self.vocabulary_items],
            "component_count": self.component_count,
            "item_count": self.item_count,
            "scanned_path_count": self.scanned_path_count,
            "blockers": list(self.blockers),
            "warnings": list(self.warnings),
            "errors": list(self.errors),
            "sample_limited": bool(self.sample_limited),
        }


@dataclass(frozen=True)
class AnalysisSuiteRuleCandidate:
    """One tested single-predicate rule candidate."""

    candidate_key: str
    rule_definition: AnalysisSuiteWhiteBoxRuleDefinition
    metrics: AnalysisSuiteRuleMetricSummary
    score: float | None = None
    rank: int | None = None
    blockers: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    metadata: Mapping[str, JsonValue] = field(default_factory=dict)
    schema_version: int = ANALYSIS_SUITE_RULE_CANDIDATE_SCHEMA_VERSION

    def to_dict(self) -> dict[str, JsonValue]:
        """Return a JSON-safe dictionary representation."""

        return {
            "schema_version": self.schema_version,
            "candidate_key": self.candidate_key,
            "rule_definition": self.rule_definition.to_dict(),
            "metrics": self.metrics.to_dict(),
            "score": self.score,
            "rank": self.rank,
            "blockers": list(self.blockers),
            "warnings": list(self.warnings),
            "metadata": _json_safe_mapping(self.metadata),
        }


@dataclass(frozen=True)
class AnalysisSuiteRuleCandidateScanConfig:
    """Configuration for bounded single-predicate candidate scans."""

    max_candidates_returned: int = DEFAULT_RULE_CANDIDATE_RETURN_LIMIT
    max_candidates_scanned: int | None = None
    min_total_support: int = 10
    min_positive_matches: int = 3
    min_precision: float | None = None
    min_lift: float | None = None
    allowed_component_keys: tuple[str, ...] = ()
    allowed_operators: tuple[str, ...] = ()
    allowed_path_offsets: tuple[int, ...] = (0,)
    include_negative_offsets: bool = False
    max_distinct_values_per_component: int = DEFAULT_MAX_DISTINCT_VALUES_PER_COMPONENT
    numeric_threshold_policy: str = "none"
    metadata: Mapping[str, JsonValue] = field(default_factory=dict)
    schema_version: int = ANALYSIS_SUITE_RULE_CANDIDATE_SCHEMA_VERSION

    def to_dict(self) -> dict[str, JsonValue]:
        """Return a JSON-safe dictionary representation."""

        return {
            "schema_version": self.schema_version,
            "max_candidates_returned": int(self.max_candidates_returned),
            "max_candidates_scanned": self.max_candidates_scanned,
            "min_total_support": int(self.min_total_support),
            "min_positive_matches": int(self.min_positive_matches),
            "min_precision": self.min_precision,
            "min_lift": self.min_lift,
            "allowed_component_keys": list(self.allowed_component_keys),
            "allowed_operators": list(self.allowed_operators),
            "allowed_path_offsets": [int(offset) for offset in self.allowed_path_offsets],
            "include_negative_offsets": bool(self.include_negative_offsets),
            "max_distinct_values_per_component": int(self.max_distinct_values_per_component),
            "numeric_threshold_policy": self.numeric_threshold_policy,
            "metadata": _json_safe_mapping(self.metadata),
        }


@dataclass(frozen=True)
class AnalysisSuiteRuleCandidateScanReport:
    """Report returned by bounded single-predicate candidate scans."""

    status: str
    comparison_key: str
    vocabulary_report: AnalysisSuitePredicateVocabularyReport
    candidates: tuple[AnalysisSuiteRuleCandidate, ...] = ()
    candidate_count_scanned: int = 0
    candidate_count_returned: int = 0
    candidate_count_filtered: int = 0
    blockers: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()
    sample_limited: bool = False
    metadata: Mapping[str, JsonValue] = field(default_factory=dict)
    schema_version: int = ANALYSIS_SUITE_RULE_CANDIDATE_SCHEMA_VERSION

    def to_dict(self) -> dict[str, JsonValue]:
        """Return a JSON-safe dictionary representation."""

        return {
            "schema_version": self.schema_version,
            "status": self.status,
            "comparison_key": self.comparison_key,
            "vocabulary_report": self.vocabulary_report.to_dict(),
            "candidates": [candidate.to_dict() for candidate in self.candidates],
            "candidate_count_scanned": self.candidate_count_scanned,
            "candidate_count_returned": self.candidate_count_returned,
            "candidate_count_filtered": self.candidate_count_filtered,
            "blockers": list(self.blockers),
            "warnings": list(self.warnings),
            "errors": list(self.errors),
            "sample_limited": bool(self.sample_limited),
            "metadata": _json_safe_mapping(self.metadata),
        }


class AnalysisSuiteRuleCandidateScanner:
    """Build and test bounded single-predicate white-box candidates.

    The scanner consumes explicit AS10 comparison sets. It derives a bounded
    predicate vocabulary from observed AS9 genome path component values and
    delegates rule evaluation to ``AnalysisSuiteWhiteBoxRuleTester`` so AS10
    remains the owner of rule matching and metric formulas.
    """

    def __init__(self, rule_tester: AnalysisSuiteWhiteBoxRuleTester | None = None) -> None:
        self._rule_tester = rule_tester or AnalysisSuiteWhiteBoxRuleTester()

    def build_predicate_vocabulary(
        self,
        comparison_set: AnalysisSuiteComparisonSetDefinition,
        config: AnalysisSuiteRuleCandidateScanConfig | None = None,
    ) -> AnalysisSuitePredicateVocabularyReport:
        """Build a finite predicate vocabulary from comparison cohort paths."""

        scan_config = config or AnalysisSuiteRuleCandidateScanConfig()
        blockers, warnings = _validate_config(scan_config)
        sample_limited = _comparison_set_sample_limited(comparison_set)
        paths = _comparison_paths(comparison_set)

        if sample_limited:
            warnings.append("input_cohorts_are_sample_limited")
        if not comparison_set.positive_cohort.paths:
            blockers.append("positive_cohort_empty")
        if not comparison_set.negative_cohort.paths:
            blockers.append("negative_cohort_empty")
        if not paths:
            blockers.append("comparison_set_has_no_paths")

        if blockers:
            return AnalysisSuitePredicateVocabularyReport(
                status=_status(warnings=warnings, blockers=blockers),
                blockers=tuple(blockers),
                warnings=tuple(warnings),
                scanned_path_count=len(paths),
                sample_limited=sample_limited,
            )

        allowed_offsets = _allowed_offsets_for_paths(paths, scan_config)
        observations: dict[tuple[str, int], dict[JsonValue, int]] = {}
        component_keys_seen: set[str] = set()
        numeric_components_skipped: set[tuple[str, int]] = set()
        unsupported_components_skipped: set[tuple[str, int]] = set()
        leakage_components_skipped: set[str] = set()

        allowed_components = set(scan_config.allowed_component_keys)
        for path in paths:
            for offset in allowed_offsets:
                snapshot = _snapshot_for_offset(path, offset)
                if snapshot is None:
                    continue
                components = _snapshot_components(snapshot)
                component_metadata = _snapshot_component_metadata(snapshot)
                for component_key, raw_value in components.items():
                    if allowed_components and component_key not in allowed_components:
                        continue
                    component_keys_seen.add(component_key)
                    metadata = component_metadata.get(component_key, {})
                    if _metadata_marks_leaky(metadata):
                        leakage_components_skipped.add(component_key)
                        continue
                    value = _json_safe_value(raw_value)
                    if _is_numeric_value(value):
                        numeric_components_skipped.add((component_key, offset))
                        continue
                    if _is_unsupported_value(value):
                        unsupported_components_skipped.add((component_key, offset))
                        continue
                    observation_key = (component_key, offset)
                    observations.setdefault(observation_key, {})
                    observations[observation_key][value] = observations[observation_key].get(value, 0) + 1

        for component_key, offset in sorted(numeric_components_skipped):
            warnings.append(
                f"numeric_component_skipped_without_threshold_policy: {component_key} offset={offset}"
            )
        for component_key, offset in sorted(unsupported_components_skipped):
            warnings.append(
                f"unsupported_component_value_skipped: {component_key} offset={offset}"
            )
        for component_key in sorted(leakage_components_skipped):
            warnings.append(f"component_skipped_due_to_leakage_metadata: {component_key}")

        vocabulary_items = _vocabulary_items_from_observations(observations, scan_config, warnings)
        if not vocabulary_items:
            blockers.append("predicate_vocabulary_empty")

        return AnalysisSuitePredicateVocabularyReport(
            status=_status(warnings=warnings, blockers=blockers),
            vocabulary_items=tuple(vocabulary_items),
            component_count=len(component_keys_seen),
            item_count=len(vocabulary_items),
            scanned_path_count=len(paths),
            blockers=tuple(blockers),
            warnings=tuple(warnings),
            sample_limited=sample_limited,
        )

    def scan_candidates(
        self,
        comparison_set: AnalysisSuiteComparisonSetDefinition,
        config: AnalysisSuiteRuleCandidateScanConfig | None = None,
        diagnostic_report: Any | None = None,
    ) -> AnalysisSuiteRuleCandidateScanReport:
        """Scan bounded single-predicate candidates and return ranked results."""

        scan_config = config or AnalysisSuiteRuleCandidateScanConfig()
        vocabulary_report = self.build_predicate_vocabulary(comparison_set, scan_config)
        blockers = list(vocabulary_report.blockers)
        warnings = list(vocabulary_report.warnings)
        errors = list(vocabulary_report.errors)
        sample_limited = vocabulary_report.sample_limited
        return_limit, limit_warnings = _candidate_return_limit(scan_config.max_candidates_returned)
        warnings.extend(limit_warnings)
        diagnostic_status = _report_status(diagnostic_report)
        if diagnostic_status in {"blocked", "error"}:
            blockers.append(f"diagnostic_report_not_acceptable: {diagnostic_status}")
        elif diagnostic_status == "warning":
            warnings.append("diagnostic_report_warning")

        if vocabulary_report.status in {"blocked", "error"} or blockers:
            return AnalysisSuiteRuleCandidateScanReport(
                status=_status(warnings=warnings, blockers=blockers, errors=errors),
                comparison_key=comparison_set.comparison_key,
                vocabulary_report=vocabulary_report,
                blockers=tuple(blockers),
                warnings=tuple(warnings),
                errors=tuple(errors),
                sample_limited=sample_limited,
                metadata={
                    "scan_config": scan_config.to_dict(),
                    "stability_status": "unknown",
                },
            )

        warnings.extend(
            (
                "multiple_testing_correction_not_applied",
                "temporal_stability_validation_not_performed",
            )
        )
        if sample_limited:
            warnings.append("candidate_metrics_are_based_on_bounded_preview_samples")

        max_scanned = scan_config.max_candidates_scanned
        vocabulary_items = vocabulary_report.vocabulary_items
        if max_scanned is not None and max_scanned < len(vocabulary_items):
            vocabulary_items = vocabulary_items[:max_scanned]
            warnings.append("candidate_scan_stopped_at_max_candidates_scanned")

        total_evaluated_paths = len(_comparison_paths(comparison_set))
        if len(vocabulary_items) > max(total_evaluated_paths, 1):
            warnings.append("candidate_count_high_relative_to_evaluated_sample_size")

        passed_candidates: list[AnalysisSuiteRuleCandidate] = []
        filter_reasons: dict[str, int] = {}
        candidate_count_scanned = 0
        for vocabulary_item in vocabulary_items:
            candidate_count_scanned += 1
            rule_definition = _rule_definition_for_vocabulary_item(
                vocabulary_item,
                comparison_set.comparison_key,
            )
            rule_report = self._rule_tester.test_rule(
                rule_definition,
                comparison_set,
                diagnostic_report=diagnostic_report,
            )
            candidate, reason = _candidate_from_rule_report(
                vocabulary_item,
                rule_definition,
                rule_report,
                scan_config,
                sample_limited,
            )
            if reason is not None:
                filter_reasons[reason] = filter_reasons.get(reason, 0) + 1
                continue
            passed_candidates.append(candidate)

        ranked_candidates = _rank_candidates(passed_candidates)
        returned_candidates = ranked_candidates[:return_limit]
        candidate_count_filtered = candidate_count_scanned - len(returned_candidates)
        if len(ranked_candidates) > return_limit:
            filter_reasons["return_limit"] = filter_reasons.get("return_limit", 0) + (
                len(ranked_candidates) - return_limit
            )
            warnings.append("candidate_return_limit_applied")

        status = _status(warnings=warnings, blockers=blockers, errors=errors)
        return AnalysisSuiteRuleCandidateScanReport(
            status=status,
            comparison_key=comparison_set.comparison_key,
            vocabulary_report=vocabulary_report,
            candidates=tuple(returned_candidates),
            candidate_count_scanned=candidate_count_scanned,
            candidate_count_returned=len(returned_candidates),
            candidate_count_filtered=candidate_count_filtered,
            blockers=tuple(blockers),
            warnings=tuple(warnings),
            errors=tuple(errors),
            sample_limited=sample_limited,
            metadata={
                "scan_config": scan_config.to_dict(),
                "filter_reasons": _json_safe_mapping(filter_reasons),
                "stability_status": "unknown",
                "total_evaluated_paths": total_evaluated_paths,
            },
        )


def _validate_config(config: AnalysisSuiteRuleCandidateScanConfig) -> tuple[list[str], list[str]]:
    blockers: list[str] = []
    warnings: list[str] = []
    if config.max_candidates_returned <= 0:
        warnings.append("max_candidates_returned_nonpositive_default_applied")
    if config.max_candidates_scanned is not None and config.max_candidates_scanned <= 0:
        blockers.append("max_candidates_scanned_must_be_positive")
    if config.min_total_support < 0:
        blockers.append("min_total_support_must_be_nonnegative")
    if config.min_positive_matches < 0:
        blockers.append("min_positive_matches_must_be_nonnegative")
    if config.min_precision is not None and not 0.0 <= config.min_precision <= 1.0:
        blockers.append("min_precision_must_be_between_zero_and_one")
    if config.min_lift is not None and config.min_lift < 0.0:
        blockers.append("min_lift_must_be_nonnegative")
    if config.max_distinct_values_per_component <= 0:
        blockers.append("max_distinct_values_per_component_must_be_positive")
    if config.numeric_threshold_policy not in SUPPORTED_NUMERIC_THRESHOLD_POLICIES:
        blockers.append(f"numeric_threshold_policy_not_supported: {config.numeric_threshold_policy}")

    allowed_operators = config.allowed_operators or DEFAULT_ALLOWED_OPERATORS
    unsupported_operators = sorted(set(allowed_operators) - set(SUPPORTED_VOCABULARY_OPERATORS))
    for operator in unsupported_operators:
        blockers.append(f"operator_not_supported_for_vocabulary_generation: {operator}")

    if not config.allowed_path_offsets:
        blockers.append("allowed_path_offsets_empty")
    for offset in config.allowed_path_offsets:
        if offset > 0:
            blockers.append(f"positive_path_offset_not_allowed: {offset}")

    if not config.include_negative_offsets:
        blocked_negative_offsets = [offset for offset in config.allowed_path_offsets if offset < 0]
        if blocked_negative_offsets:
            warnings.append("negative_path_offsets_ignored_when_include_negative_offsets_false")

    return blockers, warnings


def _candidate_return_limit(requested_limit: int) -> tuple[int, list[str]]:
    warnings: list[str] = []
    if requested_limit <= 0:
        warnings.append("max_candidates_returned_nonpositive_default_applied")
        return DEFAULT_RULE_CANDIDATE_RETURN_LIMIT, warnings
    if requested_limit > MAX_RULE_CANDIDATE_RETURN_LIMIT:
        warnings.append("max_candidates_returned_clamped_to_max")
        return MAX_RULE_CANDIDATE_RETURN_LIMIT, warnings
    return int(requested_limit), warnings


def _comparison_paths(comparison_set: AnalysisSuiteComparisonSetDefinition) -> tuple[Any, ...]:
    return tuple(comparison_set.positive_cohort.paths) + tuple(comparison_set.negative_cohort.paths)


def _comparison_set_sample_limited(comparison_set: AnalysisSuiteComparisonSetDefinition) -> bool:
    return _cohort_sample_limited(comparison_set.positive_cohort) or _cohort_sample_limited(
        comparison_set.negative_cohort
    )


def _cohort_sample_limited(cohort: Any) -> bool:
    metadata = getattr(cohort, "metadata", {}) or {}
    if not isinstance(metadata, Mapping):
        return False
    path_count = len(getattr(cohort, "paths", ()) or ())
    for key in ("input_path_count", "total_path_count", "path_count"):
        raw_count = metadata.get(key)
        if isinstance(raw_count, int | float) and raw_count > path_count:
            return True
    raw_limit = metadata.get("sample_limit")
    if isinstance(raw_limit, int | float) and path_count >= raw_limit:
        raw_input_count = metadata.get("input_path_count") or metadata.get("total_path_count")
        if isinstance(raw_input_count, int | float) and raw_input_count > raw_limit:
            return True
    return bool(metadata.get("sample_limited") or metadata.get("evaluated_sample_limited"))


def _allowed_offsets_for_paths(
    paths: Sequence[Any],
    config: AnalysisSuiteRuleCandidateScanConfig,
) -> tuple[int, ...]:
    offsets = [int(offset) for offset in config.allowed_path_offsets if offset <= 0]
    if not config.include_negative_offsets:
        offsets = [offset for offset in offsets if offset == 0]
    available_offsets: set[int] = set()
    for path in paths:
        snapshots = _path_snapshots(path)
        for offset in offsets:
            index = len(snapshots) - 1 + offset
            if 0 <= index < len(snapshots):
                available_offsets.add(offset)
    return tuple(sorted(available_offsets))


def _snapshot_for_offset(path: Any, offset: int) -> Any | None:
    snapshots = _path_snapshots(path)
    index = len(snapshots) - 1 + offset
    if index < 0 or index >= len(snapshots):
        return None
    return snapshots[index]


def _path_snapshots(path: Any) -> tuple[Any, ...]:
    if isinstance(path, Mapping):
        return tuple(path.get("snapshots", ()) or ())
    return tuple(getattr(path, "snapshots", ()) or ())


def _snapshot_components(snapshot: Any) -> Mapping[str, Any]:
    if isinstance(snapshot, Mapping):
        components = snapshot.get("components", {})
    else:
        components = getattr(snapshot, "components", {})
    if isinstance(components, Mapping):
        return components
    return {}


def _snapshot_component_metadata(snapshot: Any) -> Mapping[str, Mapping[str, Any]]:
    if isinstance(snapshot, Mapping):
        metadata = snapshot.get("component_metadata", {})
    else:
        metadata = getattr(snapshot, "component_metadata", {})
    if isinstance(metadata, Mapping):
        return {
            str(key): value
            for key, value in metadata.items()
            if isinstance(value, Mapping)
        }
    return {}


def _metadata_marks_leaky(metadata: Mapping[str, Any]) -> bool:
    if metadata.get("feature_eligible") is False:
        return True
    if metadata.get("future_derived") is True:
        return True
    if metadata.get("target_only") is True:
        return True
    leakage_role = metadata.get("leakage_role")
    if leakage_role in {"target_only", "future_derived"}:
        return True
    nested_metadata = metadata.get("metadata")
    if isinstance(nested_metadata, Mapping) and _metadata_marks_leaky(nested_metadata):
        return True
    column_metadata = metadata.get("column_metadata")
    if isinstance(column_metadata, Mapping) and _metadata_marks_leaky(column_metadata):
        return True
    return False


def _is_numeric_value(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def _is_unsupported_value(value: Any) -> bool:
    return isinstance(value, list | dict)


def _vocabulary_items_from_observations(
    observations: Mapping[tuple[str, int], Mapping[JsonValue, int]],
    config: AnalysisSuiteRuleCandidateScanConfig,
    warnings: list[str],
) -> list[AnalysisSuitePredicateVocabularyItem]:
    allowed_operators = config.allowed_operators or DEFAULT_ALLOWED_OPERATORS
    items: list[AnalysisSuitePredicateVocabularyItem] = []
    for component_key, offset in sorted(observations):
        value_counts = observations[(component_key, offset)]
        total_observed = sum(value_counts.values())
        ordered_values = sorted(value_counts, key=lambda value: _value_sort_key(value))
        if len(ordered_values) > config.max_distinct_values_per_component:
            warnings.append(
                "distinct_value_limit_applied: "
                f"{component_key} offset={offset} "
                f"limit={config.max_distinct_values_per_component}"
            )
            ordered_values = ordered_values[: config.max_distinct_values_per_component]
        for value in ordered_values:
            support_observed = value_counts[value]
            if value is None:
                if "is_null" in allowed_operators:
                    items.append(
                        _vocabulary_item(
                            component_key=component_key,
                            operator="is_null",
                            value=None,
                            path_offset=offset,
                            source="observed_null_value",
                            support_observed=support_observed,
                        )
                    )
                continue
            if "equals" in allowed_operators:
                items.append(
                    _vocabulary_item(
                        component_key=component_key,
                        operator="equals",
                        value=value,
                        path_offset=offset,
                        source="observed_symbolic_value",
                        support_observed=support_observed,
                    )
                )
            if "not_equals" in allowed_operators:
                items.append(
                    _vocabulary_item(
                        component_key=component_key,
                        operator="not_equals",
                        value=value,
                        path_offset=offset,
                        source="observed_symbolic_value",
                        support_observed=total_observed - support_observed,
                    )
                )
        if "not_null" in allowed_operators and any(value is not None for value in ordered_values):
            non_null_support = sum(count for value, count in value_counts.items() if value is not None)
            items.append(
                _vocabulary_item(
                    component_key=component_key,
                    operator="not_null",
                    value=None,
                    path_offset=offset,
                    source="observed_non_null_value",
                    support_observed=non_null_support,
                )
            )
    return items


def _vocabulary_item(
    *,
    component_key: str,
    operator: str,
    value: JsonValue,
    path_offset: int,
    source: str,
    support_observed: int,
) -> AnalysisSuitePredicateVocabularyItem:
    predicate_key = _predicate_key(
        component_key=component_key,
        operator=operator,
        value=value,
        path_offset=path_offset,
    )
    return AnalysisSuitePredicateVocabularyItem(
        predicate_key=predicate_key,
        component_key=component_key,
        operator=operator,
        value=value,
        path_offset=path_offset,
        source=source,
        support_observed=support_observed,
        metadata={"path_offset": path_offset},
    )


def _predicate_key(*, component_key: str, operator: str, value: JsonValue, path_offset: int) -> str:
    value_token = "null" if value is None else str(value)
    raw_key = f"{component_key}__offset_{path_offset}__{operator}__{value_token}"
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", raw_key).strip("_")


def _rule_definition_for_vocabulary_item(
    vocabulary_item: AnalysisSuitePredicateVocabularyItem,
    comparison_key: str,
) -> AnalysisSuiteWhiteBoxRuleDefinition:
    return AnalysisSuiteWhiteBoxRuleDefinition(
        rule_key=f"candidate__{vocabulary_item.predicate_key}",
        display_name=f"{vocabulary_item.component_key} {vocabulary_item.operator}",
        predicates=(vocabulary_item.to_rule_predicate(),),
        metadata={
            "comparison_key": comparison_key,
            "candidate_source": "single_predicate_scan",
            "predicate_key": vocabulary_item.predicate_key,
        },
    )


def _candidate_from_rule_report(
    vocabulary_item: AnalysisSuitePredicateVocabularyItem,
    rule_definition: AnalysisSuiteWhiteBoxRuleDefinition,
    rule_report: AnalysisSuiteRuleTestReport,
    config: AnalysisSuiteRuleCandidateScanConfig,
    sample_limited: bool,
) -> tuple[AnalysisSuiteRuleCandidate, str | None]:
    blockers = tuple(rule_report.blockers)
    warnings = list(rule_report.warnings)
    metrics = rule_report.metrics
    reason = _filter_reason(metrics, blockers, config)
    score = _candidate_score(metrics, config)
    if sample_limited:
        warnings.append("candidate_metric_inputs_sample_limited")
    if metrics.lift is not None and metrics.lift > 2.0 and metrics.support < config.min_total_support * 2:
        warnings.append("high_lift_with_low_support")
    warnings.append("temporal_stability_not_assessed")
    candidate = AnalysisSuiteRuleCandidate(
        candidate_key=f"candidate__{vocabulary_item.predicate_key}",
        rule_definition=rule_definition,
        metrics=metrics,
        score=score,
        blockers=blockers,
        warnings=tuple(dict.fromkeys(warnings)),
        metadata={
            "predicate_key": vocabulary_item.predicate_key,
            "rule_test_status": rule_report.status,
            "filter_reason": reason,
        },
    )
    return candidate, reason


def _filter_reason(
    metrics: AnalysisSuiteRuleMetricSummary,
    blockers: tuple[str, ...],
    config: AnalysisSuiteRuleCandidateScanConfig,
) -> str | None:
    if blockers or metrics.blockers:
        return "blockers"
    if metrics.support < config.min_total_support:
        return "min_total_support"
    if metrics.positive_matched < config.min_positive_matches:
        return "min_positive_matches"
    if config.min_precision is not None:
        if metrics.precision is None or metrics.precision < config.min_precision:
            return "min_precision"
    if config.min_lift is not None:
        if metrics.lift is None or metrics.lift < config.min_lift:
            return "min_lift"
    return None


def _candidate_score(
    metrics: AnalysisSuiteRuleMetricSummary,
    config: AnalysisSuiteRuleCandidateScanConfig,
) -> float:
    precision = metrics.precision or 0.0
    lift = metrics.lift or 0.0
    support_target = max(config.min_total_support, 1)
    support_weight = min(1.0, metrics.support / support_target)
    score = _finite_float(lift * precision * support_weight)
    return score if score is not None else 0.0


def _rank_candidates(
    candidates: Sequence[AnalysisSuiteRuleCandidate],
) -> tuple[AnalysisSuiteRuleCandidate, ...]:
    sorted_candidates = sorted(
        candidates,
        key=lambda candidate: (
            -(candidate.score or 0.0),
            -candidate.metrics.support,
            -(candidate.metrics.precision or 0.0),
            candidate.candidate_key,
        ),
    )
    return tuple(
        replace(candidate, rank=rank)
        for rank, candidate in enumerate(sorted_candidates, start=1)
    )


def _status(
    *,
    warnings: Sequence[str] = (),
    blockers: Sequence[str] = (),
    errors: Sequence[str] = (),
) -> str:
    if errors:
        return "error"
    if blockers:
        return "blocked"
    if warnings:
        return "warning"
    return "ready"


def _report_status(report: Any | None) -> str | None:
    if report is None:
        return None
    if isinstance(report, Mapping):
        status = report.get("status")
    else:
        status = getattr(report, "status", None)
    return str(status) if status is not None else None


def _value_sort_key(value: JsonValue) -> tuple[str, str]:
    return (type(value).__name__, str(value))


def _json_safe_mapping(values: Mapping[str, Any]) -> dict[str, JsonValue]:
    return {str(key): _json_safe_value(value) for key, value in values.items()}


def _json_safe_value(value: Any) -> JsonValue:
    if isinstance(value, Mapping):
        return {str(key): _json_safe_value(item) for key, item in value.items()}
    if isinstance(value, tuple | list):
        return [_json_safe_value(item) for item in value]
    if isinstance(value, bool) or value is None or isinstance(value, str):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return _finite_float(value)
    if hasattr(value, "item"):
        try:
            return _json_safe_value(value.item())
        except (TypeError, ValueError):
            return str(value)
    return str(value)


def _finite_float(value: float) -> float | None:
    return value if math.isfinite(value) else None
