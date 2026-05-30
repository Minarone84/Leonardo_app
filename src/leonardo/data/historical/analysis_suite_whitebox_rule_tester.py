"""Read-only Analysis Suite white-box rule testing.

The module evaluates explicit human-readable rule predicates against supplied
genome path comparison cohorts. It consumes in-memory AS9-style genome paths or
JSON-like path dictionaries and returns bounded JSON-safe diagnostics. It does
not load Analysis Database files, infer comparison cohorts, persist rule
definitions, or generate trading actions.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Iterable, Literal, Mapping


ANALYSIS_SUITE_WHITEBOX_RULE_SCHEMA_VERSION = 1
DEFAULT_RULE_MATCH_SAMPLE_LIMIT = 100
MAX_RULE_MATCH_SAMPLE_LIMIT = 500
MIN_TOTAL_WARNING = 30
MIN_POSITIVE_WARNING = 10
MIN_NEGATIVE_WARNING = 10

AnalysisSuiteRulePredicateOperator = Literal[
    "equals",
    "not_equals",
    "gt",
    "gte",
    "lt",
    "lte",
    "in",
    "not_in",
    "is_null",
    "not_null",
]
AnalysisSuiteComparisonCohortRole = Literal["positive", "negative", "background"]
AnalysisSuiteComparisonKind = Literal[
    "family_vs_other",
    "success_vs_failure",
    "road_x_vs_road_y",
    "true_vs_false_signal",
    "custom",
]
AnalysisSuiteRuleTestStatus = Literal["ready", "warning", "blocked", "error"]

JsonValue = Any

_SUPPORTED_OPERATORS = frozenset(
    {
        "equals",
        "not_equals",
        "gt",
        "gte",
        "lt",
        "lte",
        "in",
        "not_in",
        "is_null",
        "not_null",
    }
)
_VALUE_OPERATORS = frozenset({"equals", "not_equals", "gt", "gte", "lt", "lte"})
_VALUES_OPERATORS = frozenset({"in", "not_in"})


@dataclass(frozen=True)
class AnalysisSuiteRulePredicate:
    """
    JSON-safe explicit condition over one genome path snapshot component.

    ``path_offset`` addresses snapshots relative to the anchor snapshot:
    ``0`` means ``G(t)``, negative values address earlier snapshots, and
    positive values are blocked by validation to avoid future-looking access.
    """

    component_key: str
    operator: AnalysisSuiteRulePredicateOperator | str
    value: JsonValue | None = None
    values: tuple[JsonValue, ...] = ()
    path_offset: int = 0
    label: str | None = None
    required: bool = True
    metadata: Mapping[str, JsonValue] = field(default_factory=dict)
    schema_version: int = ANALYSIS_SUITE_WHITEBOX_RULE_SCHEMA_VERSION
    path_offset_valid: bool = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "component_key", str(self.component_key))
        object.__setattr__(self, "operator", str(self.operator))
        object.__setattr__(self, "value", _json_safe_value(self.value))
        object.__setattr__(self, "values", tuple(_json_safe_value(item) for item in self.values))
        try:
            path_offset = int(self.path_offset)
            path_offset_valid = True
        except (TypeError, ValueError):
            path_offset = 0
            path_offset_valid = False
        object.__setattr__(self, "path_offset", path_offset)
        object.__setattr__(self, "path_offset_valid", path_offset_valid)
        if self.label is not None:
            object.__setattr__(self, "label", str(self.label))
        object.__setattr__(self, "required", bool(self.required))
        object.__setattr__(self, "metadata", dict(self.metadata))
        object.__setattr__(self, "schema_version", int(self.schema_version))

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "AnalysisSuiteRulePredicate":
        """Create a predicate from a JSON-like mapping."""

        raw_values = data.get("values", ()) or ()
        return cls(
            component_key=str(data.get("component_key", "")),
            operator=str(data.get("operator", "")),
            value=data.get("value"),
            values=tuple(raw_values),  # type: ignore[arg-type]
            path_offset=data.get("path_offset", 0),  # type: ignore[arg-type]
            label=_optional_str(data.get("label")),
            required=bool(data.get("required", True)),
            metadata=dict(data.get("metadata", {}) or {}),  # type: ignore[arg-type]
            schema_version=int(
                data.get(
                    "schema_version",
                    ANALYSIS_SUITE_WHITEBOX_RULE_SCHEMA_VERSION,
                )
            ),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": int(self.schema_version),
            "component_key": self.component_key,
            "operator": self.operator,
            "value": _json_safe_value(self.value),
            "values": [_json_safe_value(item) for item in self.values],
            "path_offset": int(self.path_offset),
            "label": self.label,
            "required": bool(self.required),
            "metadata": _json_safe_mapping(self.metadata),
        }


@dataclass(frozen=True)
class AnalysisSuiteWhiteBoxRuleDefinition:
    """
    JSON-safe explicit conjunction of rule predicates.

    The AS10 MVP uses AND semantics only. It does not evaluate arbitrary
    expressions, nested predicate trees, executable code, or regex policies.
    """

    rule_key: str
    display_name: str
    predicates: tuple[AnalysisSuiteRulePredicate, ...]
    target_label: str | None = None
    metadata: Mapping[str, JsonValue] = field(default_factory=dict)
    schema_version: int = ANALYSIS_SUITE_WHITEBOX_RULE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "rule_key", str(self.rule_key))
        object.__setattr__(self, "display_name", str(self.display_name))
        object.__setattr__(
            self,
            "predicates",
            tuple(_coerce_predicate(predicate) for predicate in self.predicates),
        )
        if self.target_label is not None:
            object.__setattr__(self, "target_label", str(self.target_label))
        object.__setattr__(self, "metadata", dict(self.metadata))
        object.__setattr__(self, "schema_version", int(self.schema_version))

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "AnalysisSuiteWhiteBoxRuleDefinition":
        """Create a rule definition from a JSON-like mapping."""

        return cls(
            rule_key=str(data.get("rule_key", "")),
            display_name=str(data.get("display_name", "")),
            predicates=tuple(
                _coerce_predicate(predicate)
                for predicate in data.get("predicates", ()) or ()  # type: ignore[union-attr]
            ),
            target_label=_optional_str(data.get("target_label")),
            metadata=dict(data.get("metadata", {}) or {}),  # type: ignore[arg-type]
            schema_version=int(
                data.get(
                    "schema_version",
                    ANALYSIS_SUITE_WHITEBOX_RULE_SCHEMA_VERSION,
                )
            ),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": int(self.schema_version),
            "rule_key": self.rule_key,
            "display_name": self.display_name,
            "predicates": [predicate.to_dict() for predicate in self.predicates],
            "target_label": self.target_label,
            "metadata": _json_safe_mapping(self.metadata),
        }


@dataclass(frozen=True)
class AnalysisSuiteComparisonCohort:
    """
    Explicit genome-path cohort used in a comparison set.

    Cohorts are caller-supplied. The tester does not infer negative examples or
    regenerate upstream AS8/AS9 reports.
    """

    cohort_key: str
    label: str
    paths: tuple[object, ...]
    role: AnalysisSuiteComparisonCohortRole | str
    metadata: Mapping[str, JsonValue] = field(default_factory=dict)
    schema_version: int = ANALYSIS_SUITE_WHITEBOX_RULE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "cohort_key", str(self.cohort_key))
        object.__setattr__(self, "label", str(self.label))
        object.__setattr__(self, "paths", tuple(self.paths))
        object.__setattr__(self, "role", str(self.role))
        object.__setattr__(self, "metadata", dict(self.metadata))
        object.__setattr__(self, "schema_version", int(self.schema_version))

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": int(self.schema_version),
            "cohort_key": self.cohort_key,
            "label": self.label,
            "role": self.role,
            "path_count": len(self.paths),
            "input_path_count": _cohort_input_path_count(self),
            "metadata": _json_safe_mapping(self.metadata),
        }


@dataclass(frozen=True)
class AnalysisSuiteComparisonSetDefinition:
    """JSON-safe explicit positive/negative comparison setup."""

    comparison_key: str
    display_name: str
    positive_cohort: AnalysisSuiteComparisonCohort
    negative_cohort: AnalysisSuiteComparisonCohort
    comparison_kind: AnalysisSuiteComparisonKind | str = "custom"
    metadata: Mapping[str, JsonValue] = field(default_factory=dict)
    schema_version: int = ANALYSIS_SUITE_WHITEBOX_RULE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "comparison_key", str(self.comparison_key))
        object.__setattr__(self, "display_name", str(self.display_name))
        object.__setattr__(self, "comparison_kind", str(self.comparison_kind))
        object.__setattr__(self, "metadata", dict(self.metadata))
        object.__setattr__(self, "schema_version", int(self.schema_version))

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": int(self.schema_version),
            "comparison_key": self.comparison_key,
            "display_name": self.display_name,
            "comparison_kind": self.comparison_kind,
            "positive_cohort": self.positive_cohort.to_dict(),
            "negative_cohort": self.negative_cohort.to_dict(),
            "metadata": _json_safe_mapping(self.metadata),
        }


@dataclass(frozen=True)
class AnalysisSuitePredicateResult:
    """JSON-safe evaluation result for one predicate against one path."""

    component_key: str
    operator: str
    path_offset: int
    matched: bool
    required: bool
    snapshot_index: int | None = None
    actual_value: JsonValue | None = None
    missing: bool = False
    blockers: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "component_key", str(self.component_key))
        object.__setattr__(self, "operator", str(self.operator))
        object.__setattr__(self, "path_offset", int(self.path_offset))
        object.__setattr__(self, "matched", bool(self.matched))
        object.__setattr__(self, "required", bool(self.required))
        if self.snapshot_index is not None:
            object.__setattr__(self, "snapshot_index", int(self.snapshot_index))
        object.__setattr__(self, "actual_value", _json_safe_value(self.actual_value))
        object.__setattr__(self, "missing", bool(self.missing))
        object.__setattr__(self, "blockers", tuple(str(item) for item in self.blockers))
        object.__setattr__(self, "warnings", tuple(str(item) for item in self.warnings))

    def to_dict(self) -> dict[str, object]:
        return {
            "component_key": self.component_key,
            "operator": self.operator,
            "path_offset": int(self.path_offset),
            "snapshot_index": self.snapshot_index,
            "actual_value": _json_safe_value(self.actual_value),
            "matched": bool(self.matched),
            "required": bool(self.required),
            "missing": bool(self.missing),
            "blockers": list(self.blockers),
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class AnalysisSuiteRuleMatch:
    """JSON-safe evaluation result for one rule against one genome path."""

    cohort_key: str
    path_index: int
    anchor_row_index: int | None
    anchor_ts_ms: int | None
    matched: bool
    predicate_results: tuple[AnalysisSuitePredicateResult, ...]
    blockers: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "cohort_key", str(self.cohort_key))
        object.__setattr__(self, "path_index", int(self.path_index))
        if self.anchor_row_index is not None:
            object.__setattr__(self, "anchor_row_index", int(self.anchor_row_index))
        if self.anchor_ts_ms is not None:
            object.__setattr__(self, "anchor_ts_ms", int(self.anchor_ts_ms))
        object.__setattr__(self, "matched", bool(self.matched))
        object.__setattr__(self, "predicate_results", tuple(self.predicate_results))
        object.__setattr__(self, "blockers", tuple(str(item) for item in self.blockers))
        object.__setattr__(self, "warnings", tuple(str(item) for item in self.warnings))

    def to_dict(self) -> dict[str, object]:
        return {
            "cohort_key": self.cohort_key,
            "path_index": int(self.path_index),
            "anchor_row_index": self.anchor_row_index,
            "anchor_ts_ms": self.anchor_ts_ms,
            "matched": bool(self.matched),
            "predicate_results": [result.to_dict() for result in self.predicate_results],
            "blockers": list(self.blockers),
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class AnalysisSuiteRuleMetricSummary:
    """JSON-safe diagnostic metric summary for one tested rule."""

    positive_total: int
    negative_total: int
    positive_matched: int
    negative_matched: int
    true_positive: int
    false_positive: int
    false_negative: int
    true_negative: int
    support: int
    coverage: float | None
    precision: float | None
    recall: float | None
    specificity: float | None
    false_positive_rate: float | None
    false_negative_rate: float | None
    lift: float | None
    baseline_positive_rate: float | None
    matched_positive_rate: float | None
    warnings: tuple[str, ...] = ()
    blockers: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name in (
            "positive_total",
            "negative_total",
            "positive_matched",
            "negative_matched",
            "true_positive",
            "false_positive",
            "false_negative",
            "true_negative",
            "support",
        ):
            object.__setattr__(self, name, int(getattr(self, name)))
        object.__setattr__(self, "warnings", tuple(str(item) for item in self.warnings))
        object.__setattr__(self, "blockers", tuple(str(item) for item in self.blockers))

    def to_dict(self) -> dict[str, object]:
        return {
            "positive_total": int(self.positive_total),
            "negative_total": int(self.negative_total),
            "positive_matched": int(self.positive_matched),
            "negative_matched": int(self.negative_matched),
            "true_positive": int(self.true_positive),
            "false_positive": int(self.false_positive),
            "false_negative": int(self.false_negative),
            "true_negative": int(self.true_negative),
            "support": int(self.support),
            "coverage": self.coverage,
            "precision": self.precision,
            "recall": self.recall,
            "specificity": self.specificity,
            "false_positive_rate": self.false_positive_rate,
            "false_negative_rate": self.false_negative_rate,
            "lift": self.lift,
            "baseline_positive_rate": self.baseline_positive_rate,
            "matched_positive_rate": self.matched_positive_rate,
            "warnings": list(self.warnings),
            "blockers": list(self.blockers),
        }


@dataclass(frozen=True)
class AnalysisSuiteRuleValidationReport:
    """JSON-safe validation report for one rule definition."""

    status: AnalysisSuiteRuleTestStatus
    rule_definition: AnalysisSuiteWhiteBoxRuleDefinition
    warnings: tuple[str, ...] = ()
    blockers: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "warnings", tuple(str(item) for item in self.warnings))
        object.__setattr__(self, "blockers", tuple(str(item) for item in self.blockers))
        object.__setattr__(self, "errors", tuple(str(item) for item in self.errors))

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "rule_definition": self.rule_definition.to_dict(),
            "warnings": list(self.warnings),
            "blockers": list(self.blockers),
            "errors": list(self.errors),
        }


@dataclass(frozen=True)
class AnalysisSuiteRuleTestReport:
    """JSON-safe bounded report for explicit white-box rule testing."""

    status: AnalysisSuiteRuleTestStatus
    rule_definition: AnalysisSuiteWhiteBoxRuleDefinition
    comparison_set: AnalysisSuiteComparisonSetDefinition
    metrics: AnalysisSuiteRuleMetricSummary
    positive_matches: tuple[AnalysisSuiteRuleMatch, ...]
    negative_matches: tuple[AnalysisSuiteRuleMatch, ...]
    warnings: tuple[str, ...] = ()
    blockers: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()
    evaluated_sample_limited: bool = False
    input_path_count: int = 0
    evaluated_path_count: int = 0
    requested_sample_limit: int = DEFAULT_RULE_MATCH_SAMPLE_LIMIT
    sample_limit: int = DEFAULT_RULE_MATCH_SAMPLE_LIMIT

    def __post_init__(self) -> None:
        object.__setattr__(self, "positive_matches", tuple(self.positive_matches))
        object.__setattr__(self, "negative_matches", tuple(self.negative_matches))
        object.__setattr__(self, "warnings", tuple(str(item) for item in self.warnings))
        object.__setattr__(self, "blockers", tuple(str(item) for item in self.blockers))
        object.__setattr__(self, "errors", tuple(str(item) for item in self.errors))
        object.__setattr__(self, "evaluated_sample_limited", bool(self.evaluated_sample_limited))
        object.__setattr__(self, "input_path_count", int(self.input_path_count))
        object.__setattr__(self, "evaluated_path_count", int(self.evaluated_path_count))
        object.__setattr__(self, "requested_sample_limit", int(self.requested_sample_limit))
        object.__setattr__(self, "sample_limit", int(self.sample_limit))

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "rule_definition": self.rule_definition.to_dict(),
            "comparison_set": self.comparison_set.to_dict(),
            "metrics": self.metrics.to_dict(),
            "positive_matches": [match.to_dict() for match in self.positive_matches],
            "negative_matches": [match.to_dict() for match in self.negative_matches],
            "warnings": list(self.warnings),
            "blockers": list(self.blockers),
            "errors": list(self.errors),
            "evaluated_sample_limited": bool(self.evaluated_sample_limited),
            "input_path_count": int(self.input_path_count),
            "evaluated_path_count": int(self.evaluated_path_count),
            "requested_sample_limit": int(self.requested_sample_limit),
            "sample_limit": int(self.sample_limit),
        }


class AnalysisSuiteWhiteBoxRuleTester:
    """
    Evaluate explicit white-box rules against supplied genome path cohorts.

    The tester owns AS10 rule diagnostics only. Upstream services remain
    responsible for diagnostic setup, POI/family previews, and genome path
    construction. Expected user/configuration issues are returned as structured
    blockers or warnings.
    """

    def validate_rule_definition(
        self,
        rule_definition: AnalysisSuiteWhiteBoxRuleDefinition | Mapping[str, object],
        *,
        genome_path_preview_report: object | None = None,
    ) -> AnalysisSuiteRuleValidationReport:
        """
        Validate rule structure and optional upstream genome report status.

        The validation is structural. It does not read files, inspect raw
        manifests, or infer component eligibility from column names.
        """

        definition = _coerce_rule_definition(rule_definition)
        warnings, blockers, errors = _validate_rule_definition(definition)
        warnings += _upstream_report_warnings(genome_path_preview_report)
        blockers += _upstream_report_blockers(genome_path_preview_report)
        return AnalysisSuiteRuleValidationReport(
            status=_status(warnings=warnings, blockers=blockers, errors=errors),
            rule_definition=definition,
            warnings=_dedupe(warnings),
            blockers=_dedupe(blockers),
            errors=_dedupe(errors),
        )

    def test_rule(
        self,
        rule_definition: AnalysisSuiteWhiteBoxRuleDefinition | Mapping[str, object],
        comparison_set: AnalysisSuiteComparisonSetDefinition,
        *,
        diagnostic_report: object | None = None,
        sample_limit: int | None = None,
    ) -> AnalysisSuiteRuleTestReport:
        """
        Test one explicit rule against explicit positive and negative cohorts.

        Returned metrics describe evidence quality for the supplied comparison
        set. They are not execution results.
        """

        definition = _coerce_rule_definition(rule_definition)
        requested_limit, effective_limit, limit_warnings = _sample_limit_state(sample_limit)
        warnings = tuple(limit_warnings)
        blockers: tuple[str, ...] = ()
        errors: tuple[str, ...] = ()

        validation = self.validate_rule_definition(definition)
        warnings += validation.warnings
        blockers += validation.blockers
        errors += validation.errors

        diagnostic_status = _report_status(diagnostic_report)
        if diagnostic_status in {"blocked", "error"}:
            blockers += (f"diagnostic_report_not_acceptable: {diagnostic_status}",)
        elif diagnostic_status == "warning":
            warnings += ("diagnostic_report_warning",)

        comparison_warnings, comparison_blockers = _validate_comparison_set(comparison_set)
        warnings += comparison_warnings
        blockers += comparison_blockers

        positive_matches = tuple(
            _evaluate_rule_on_path(
                definition=definition,
                path=path,
                cohort_key=comparison_set.positive_cohort.cohort_key,
                path_index=index,
            )
            for index, path in enumerate(comparison_set.positive_cohort.paths)
        )
        negative_matches = tuple(
            _evaluate_rule_on_path(
                definition=definition,
                path=path,
                cohort_key=comparison_set.negative_cohort.cohort_key,
                path_index=index,
            )
            for index, path in enumerate(comparison_set.negative_cohort.paths)
        )

        warnings += _match_warnings(positive_matches)
        warnings += _match_warnings(negative_matches)
        blockers += _match_blockers(positive_matches)
        blockers += _match_blockers(negative_matches)

        metrics = _metric_summary(
            positive_total=len(positive_matches),
            negative_total=len(negative_matches),
            positive_matched=sum(1 for match in positive_matches if match.matched),
            negative_matched=sum(1 for match in negative_matches if match.matched),
        )
        warnings += metrics.warnings
        blockers += metrics.blockers

        input_path_count = _comparison_input_path_count(comparison_set)
        evaluated_path_count = len(positive_matches) + len(negative_matches)
        evaluated_sample_limited = _comparison_sample_limited(
            comparison_set=comparison_set,
            input_path_count=input_path_count,
            evaluated_path_count=evaluated_path_count,
        )
        if evaluated_sample_limited:
            warnings += ("metrics_based_on_bounded_preview_samples",)

        sampled_positive_matches = tuple(
            match for match in positive_matches if match.matched
        )[:effective_limit]
        sampled_negative_matches = tuple(
            match for match in negative_matches if match.matched
        )[:effective_limit]

        return AnalysisSuiteRuleTestReport(
            status=_status(warnings=warnings, blockers=blockers, errors=errors),
            rule_definition=definition,
            comparison_set=comparison_set,
            metrics=metrics,
            positive_matches=sampled_positive_matches,
            negative_matches=sampled_negative_matches,
            warnings=_dedupe(warnings),
            blockers=_dedupe(blockers),
            errors=_dedupe(errors),
            evaluated_sample_limited=evaluated_sample_limited,
            input_path_count=input_path_count,
            evaluated_path_count=evaluated_path_count,
            requested_sample_limit=requested_limit,
            sample_limit=effective_limit,
        )

    def build_comparison_set_from_path_reports(
        self,
        *,
        positive_path_report: object,
        negative_path_report: object,
        comparison_key: str,
        display_name: str,
        comparison_kind: AnalysisSuiteComparisonKind | str = "custom",
    ) -> AnalysisSuiteComparisonSetDefinition:
        """
        Build an explicit comparison set from bounded AS9 path preview reports.

        The method copies supplied report samples only. It does not regenerate
        genome paths or infer unsampled examples from upstream datasets.
        """

        return AnalysisSuiteComparisonSetDefinition(
            comparison_key=comparison_key,
            display_name=display_name,
            comparison_kind=comparison_kind,
            positive_cohort=AnalysisSuiteComparisonCohort(
                cohort_key=f"{comparison_key}_positive",
                label="Positive",
                role="positive",
                paths=tuple(_report_sample_paths(positive_path_report)),
                metadata=_path_report_metadata(positive_path_report),
            ),
            negative_cohort=AnalysisSuiteComparisonCohort(
                cohort_key=f"{comparison_key}_negative",
                label="Negative",
                role="negative",
                paths=tuple(_report_sample_paths(negative_path_report)),
                metadata=_path_report_metadata(negative_path_report),
            ),
        )


def _validate_rule_definition(
    definition: AnalysisSuiteWhiteBoxRuleDefinition,
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    warnings: list[str] = []
    blockers: list[str] = []
    errors: list[str] = []

    if not definition.rule_key.strip():
        blockers.append("rule_key_required")
    if not definition.predicates:
        blockers.append("rule_predicates_required")
    for index, predicate in enumerate(definition.predicates):
        prefix = f"predicate[{index}]"
        if not predicate.component_key.strip():
            blockers.append(f"{prefix}_component_key_required")
        if predicate.operator not in _SUPPORTED_OPERATORS:
            blockers.append(f"{prefix}_unsupported_operator: {predicate.operator}")
        if not predicate.path_offset_valid:
            blockers.append(f"{prefix}_path_offset_must_be_int")
        elif predicate.path_offset > 0:
            blockers.append(f"{prefix}_positive_path_offset_forbidden: {predicate.path_offset}")
        if predicate.operator in _VALUE_OPERATORS and predicate.value is None:
            blockers.append(f"{prefix}_value_required_for_operator: {predicate.operator}")
        if predicate.operator in _VALUES_OPERATORS and not predicate.values:
            blockers.append(f"{prefix}_values_required_for_operator: {predicate.operator}")
        if predicate.operator in {"gt", "gte", "lt", "lte"} and predicate.value is not None:
            if _to_float(predicate.value) is None:
                blockers.append(f"{prefix}_numeric_value_required: {predicate.component_key}")
        if not predicate.required:
            warnings.append(f"{prefix}_optional_predicate")

    return _dedupe(warnings), _dedupe(blockers), _dedupe(errors)


def _validate_comparison_set(
    comparison_set: AnalysisSuiteComparisonSetDefinition,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    warnings: list[str] = []
    blockers: list[str] = []

    if not comparison_set.positive_cohort.paths:
        blockers.append("positive_cohort_empty")
    if not comparison_set.negative_cohort.paths:
        blockers.append("negative_cohort_empty")
    if comparison_set.positive_cohort.role != "positive":
        warnings.append(f"positive_cohort_role_unexpected: {comparison_set.positive_cohort.role}")
    if comparison_set.negative_cohort.role not in {"negative", "background"}:
        warnings.append(f"negative_cohort_role_unexpected: {comparison_set.negative_cohort.role}")

    positive_ids = {
        identity
        for identity in (
            _path_identity(path) for path in comparison_set.positive_cohort.paths
        )
        if identity is not None
    }
    negative_ids = {
        identity
        for identity in (
            _path_identity(path) for path in comparison_set.negative_cohort.paths
        )
        if identity is not None
    }
    if positive_ids.intersection(negative_ids):
        warnings.append("cohort_identity_overlap_detected")
    if not _has_time_split_metadata(comparison_set):
        warnings.append("time_split_not_assessed")

    total = len(comparison_set.positive_cohort.paths) + len(comparison_set.negative_cohort.paths)
    if total and total < MIN_TOTAL_WARNING:
        warnings.append(f"low_total_evaluated: {total}")
    if comparison_set.positive_cohort.paths and len(comparison_set.positive_cohort.paths) < MIN_POSITIVE_WARNING:
        warnings.append(f"low_positive_count: {len(comparison_set.positive_cohort.paths)}")
    if comparison_set.negative_cohort.paths and len(comparison_set.negative_cohort.paths) < MIN_NEGATIVE_WARNING:
        warnings.append(f"low_negative_count: {len(comparison_set.negative_cohort.paths)}")

    return _dedupe(warnings), _dedupe(blockers)


def _evaluate_rule_on_path(
    *,
    definition: AnalysisSuiteWhiteBoxRuleDefinition,
    path: object,
    cohort_key: str,
    path_index: int,
) -> AnalysisSuiteRuleMatch:
    predicate_results = tuple(
        _evaluate_predicate(predicate=predicate, path=path)
        for predicate in definition.predicates
    )
    blockers = _dedupe(
        blocker
        for result in predicate_results
        for blocker in result.blockers
        if result.required
    )
    warnings = _dedupe(
        warning
        for result in predicate_results
        for warning in result.warnings
    )
    matched = not blockers and all(
        result.matched for result in predicate_results if result.required
    )
    return AnalysisSuiteRuleMatch(
        cohort_key=cohort_key,
        path_index=path_index,
        anchor_row_index=_path_anchor_row_index(path),
        anchor_ts_ms=_path_anchor_ts_ms(path),
        matched=matched,
        predicate_results=predicate_results,
        blockers=blockers,
        warnings=warnings,
    )


def _evaluate_predicate(
    *,
    predicate: AnalysisSuiteRulePredicate,
    path: object,
) -> AnalysisSuitePredicateResult:
    if predicate.path_offset > 0:
        return AnalysisSuitePredicateResult(
            component_key=predicate.component_key,
            operator=predicate.operator,
            path_offset=predicate.path_offset,
            matched=False,
            required=predicate.required,
            blockers=(f"positive_path_offset_forbidden: {predicate.path_offset}",),
        )
    if predicate.operator not in _SUPPORTED_OPERATORS:
        return AnalysisSuitePredicateResult(
            component_key=predicate.component_key,
            operator=predicate.operator,
            path_offset=predicate.path_offset,
            matched=False,
            required=predicate.required,
            blockers=(f"unsupported_operator: {predicate.operator}",),
        )

    snapshot_index, snapshot = _snapshot_for_offset(path=path, offset=predicate.path_offset)
    if snapshot is None:
        matched = not predicate.required
        return AnalysisSuitePredicateResult(
            component_key=predicate.component_key,
            operator=predicate.operator,
            path_offset=predicate.path_offset,
            snapshot_index=snapshot_index,
            matched=matched,
            required=predicate.required,
            missing=True,
            warnings=(f"snapshot_offset_unavailable: {predicate.path_offset}",),
        )

    components = _snapshot_components(snapshot)
    if predicate.component_key not in components:
        matched = not predicate.required
        return AnalysisSuitePredicateResult(
            component_key=predicate.component_key,
            operator=predicate.operator,
            path_offset=predicate.path_offset,
            snapshot_index=snapshot_index,
            matched=matched,
            required=predicate.required,
            missing=True,
            warnings=(f"component_missing: {predicate.component_key}",),
        )

    actual = components[predicate.component_key]
    matched, warnings = _operator_matches(predicate=predicate, actual=actual)
    if not predicate.required:
        matched = True
    return AnalysisSuitePredicateResult(
        component_key=predicate.component_key,
        operator=predicate.operator,
        path_offset=predicate.path_offset,
        snapshot_index=snapshot_index,
        actual_value=actual,
        matched=matched,
        required=predicate.required,
        missing=_is_nullish(actual),
        warnings=warnings,
    )


def _operator_matches(
    *,
    predicate: AnalysisSuiteRulePredicate,
    actual: object,
) -> tuple[bool, tuple[str, ...]]:
    operator = predicate.operator
    if operator == "is_null":
        return _is_nullish(actual), ()
    if operator == "not_null":
        return not _is_nullish(actual), ()
    if operator == "equals":
        return _values_equal(actual, predicate.value), ()
    if operator == "not_equals":
        return not _values_equal(actual, predicate.value), ()
    if operator in {"in", "not_in"}:
        result = any(_values_equal(actual, expected) for expected in predicate.values)
        return (result if operator == "in" else not result), ()

    actual_number = _to_float(actual)
    expected_number = _to_float(predicate.value)
    if actual_number is None or expected_number is None:
        return False, (f"numeric_comparison_unavailable: {predicate.component_key}",)
    if operator == "gt":
        return actual_number > expected_number, ()
    if operator == "gte":
        return actual_number >= expected_number, ()
    if operator == "lt":
        return actual_number < expected_number, ()
    if operator == "lte":
        return actual_number <= expected_number, ()
    return False, (f"unsupported_operator: {operator}",)


def _metric_summary(
    *,
    positive_total: int,
    negative_total: int,
    positive_matched: int,
    negative_matched: int,
) -> AnalysisSuiteRuleMetricSummary:
    true_positive = positive_matched
    false_positive = negative_matched
    false_negative = positive_total - positive_matched
    true_negative = negative_total - negative_matched
    support = true_positive + false_positive
    total = positive_total + negative_total
    precision = _ratio(true_positive, true_positive + false_positive)
    baseline_positive_rate = _ratio(positive_total, total)
    warnings: list[str] = []
    blockers: list[str] = []

    if total < MIN_TOTAL_WARNING:
        warnings.append(f"low_total_evaluated: {total}")
    if positive_total < MIN_POSITIVE_WARNING:
        warnings.append(f"low_positive_count: {positive_total}")
    if negative_total < MIN_NEGATIVE_WARNING:
        warnings.append(f"low_negative_count: {negative_total}")
    if support and support < MIN_POSITIVE_WARNING:
        warnings.append(f"low_support: {support}")
    recall = _ratio(true_positive, positive_total)
    if precision is not None and recall is not None and precision >= 0.8 and recall < 0.2:
        warnings.append("high_precision_low_recall")
    if baseline_positive_rate is not None and (
        baseline_positive_rate < 0.1 or baseline_positive_rate > 0.9
    ):
        warnings.append(f"class_imbalance: {baseline_positive_rate}")

    lift = None
    if precision is not None and baseline_positive_rate not in {None, 0.0}:
        lift = precision / baseline_positive_rate

    return AnalysisSuiteRuleMetricSummary(
        positive_total=positive_total,
        negative_total=negative_total,
        positive_matched=positive_matched,
        negative_matched=negative_matched,
        true_positive=true_positive,
        false_positive=false_positive,
        false_negative=false_negative,
        true_negative=true_negative,
        support=support,
        coverage=_ratio(support, total),
        precision=precision,
        recall=recall,
        specificity=_ratio(true_negative, negative_total),
        false_positive_rate=_ratio(false_positive, negative_total),
        false_negative_rate=_ratio(false_negative, positive_total),
        lift=lift,
        baseline_positive_rate=baseline_positive_rate,
        matched_positive_rate=precision,
        warnings=_dedupe(warnings),
        blockers=_dedupe(blockers),
    )


def _sample_limit_state(limit: int | None) -> tuple[int, int, tuple[str, ...]]:
    if limit is None:
        return DEFAULT_RULE_MATCH_SAMPLE_LIMIT, DEFAULT_RULE_MATCH_SAMPLE_LIMIT, ()
    requested = int(limit)
    if requested <= 0:
        return requested, DEFAULT_RULE_MATCH_SAMPLE_LIMIT, ("sample_limit_defaulted",)
    if requested > MAX_RULE_MATCH_SAMPLE_LIMIT:
        return requested, MAX_RULE_MATCH_SAMPLE_LIMIT, (
            "sample_limit_clamped_to_max",
            f"sample_limit_effective: {MAX_RULE_MATCH_SAMPLE_LIMIT}",
        )
    return requested, requested, ()


def _status(
    *,
    warnings: Iterable[str],
    blockers: Iterable[str],
    errors: Iterable[str],
) -> AnalysisSuiteRuleTestStatus:
    if tuple(errors):
        return "error"
    if tuple(blockers):
        return "blocked"
    if tuple(warnings):
        return "warning"
    return "ready"


def _snapshot_for_offset(path: object, offset: int) -> tuple[int | None, object | None]:
    snapshots = _path_snapshots(path)
    index = len(snapshots) - 1 + offset
    if index < 0 or index >= len(snapshots):
        return index, None
    return index, snapshots[index]


def _path_snapshots(path: object) -> tuple[object, ...]:
    if isinstance(path, Mapping):
        return tuple(path.get("snapshots", ()) or ())
    return tuple(getattr(path, "snapshots", ()) or ())


def _snapshot_components(snapshot: object) -> Mapping[str, object]:
    if isinstance(snapshot, Mapping):
        components = snapshot.get("components", {}) or {}
    else:
        components = getattr(snapshot, "components", {}) or {}
    if isinstance(components, Mapping):
        return components
    return {}


def _path_anchor_row_index(path: object) -> int | None:
    value = path.get("anchor_row_index") if isinstance(path, Mapping) else getattr(path, "anchor_row_index", None)
    return _optional_int(value)


def _path_anchor_ts_ms(path: object) -> int | None:
    value = path.get("anchor_ts_ms") if isinstance(path, Mapping) else getattr(path, "anchor_ts_ms", None)
    return _optional_int(value)


def _path_identity(path: object) -> tuple[int | None, int | None] | None:
    row_index = _path_anchor_row_index(path)
    ts_ms = _path_anchor_ts_ms(path)
    if row_index is None and ts_ms is None:
        return None
    return row_index, ts_ms


def _match_warnings(matches: Iterable[AnalysisSuiteRuleMatch]) -> tuple[str, ...]:
    return _dedupe(warning for match in matches for warning in match.warnings)


def _match_blockers(matches: Iterable[AnalysisSuiteRuleMatch]) -> tuple[str, ...]:
    return _dedupe(blocker for match in matches for blocker in match.blockers)


def _comparison_input_path_count(comparison_set: AnalysisSuiteComparisonSetDefinition) -> int:
    return _cohort_input_path_count(comparison_set.positive_cohort) + _cohort_input_path_count(
        comparison_set.negative_cohort
    )


def _cohort_input_path_count(cohort: AnalysisSuiteComparisonCohort) -> int:
    for key in ("input_path_count", "path_count", "total_path_count"):
        count = _optional_int(cohort.metadata.get(key))
        if count is not None:
            return count
    return len(cohort.paths)


def _comparison_sample_limited(
    *,
    comparison_set: AnalysisSuiteComparisonSetDefinition,
    input_path_count: int,
    evaluated_path_count: int,
) -> bool:
    if input_path_count > evaluated_path_count:
        return True
    for cohort in (comparison_set.positive_cohort, comparison_set.negative_cohort):
        if bool(cohort.metadata.get("evaluated_sample_limited", False)):
            return True
        if bool(cohort.metadata.get("sample_limited", False)):
            return True
    return False


def _has_time_split_metadata(comparison_set: AnalysisSuiteComparisonSetDefinition) -> bool:
    for values in (
        comparison_set.metadata,
        comparison_set.positive_cohort.metadata,
        comparison_set.negative_cohort.metadata,
    ):
        if any(key in values for key in ("time_split", "split", "split_key", "split_role")):
            return True
    return False


def _upstream_report_warnings(report: object | None) -> tuple[str, ...]:
    if report is None:
        return ()
    warnings = tuple(str(item) for item in _report_sequence(report, "warnings"))
    status = _report_status(report)
    if status == "warning":
        warnings += ("genome_path_report_warning",)
    return _dedupe(warnings)


def _upstream_report_blockers(report: object | None) -> tuple[str, ...]:
    if report is None:
        return ()
    blockers = tuple(str(item) for item in _report_sequence(report, "blockers"))
    status = _report_status(report)
    if status in {"blocked", "error"}:
        blockers += (f"genome_path_report_not_acceptable: {status}",)
    return _dedupe(blockers)


def _report_status(report: object | None) -> str:
    if report is None:
        return ""
    if isinstance(report, Mapping):
        return str(report.get("status", ""))
    return str(getattr(report, "status", ""))


def _report_sequence(report: object, key: str) -> tuple[object, ...]:
    if isinstance(report, Mapping):
        value = report.get(key, ())
    else:
        value = getattr(report, key, ())
    return tuple(value or ())


def _report_sample_paths(report: object) -> tuple[object, ...]:
    if isinstance(report, Mapping):
        paths = report.get("sample_paths", ()) or ()
    else:
        paths = getattr(report, "sample_paths", ()) or ()
    return tuple(paths)


def _path_report_metadata(report: object) -> dict[str, object]:
    if isinstance(report, Mapping):
        path_count = report.get("path_count")
        sample_limit = report.get("sample_limit")
    else:
        path_count = getattr(report, "path_count", None)
        sample_limit = getattr(report, "sample_limit", None)
    sample_paths = _report_sample_paths(report)
    metadata: dict[str, object] = {
        "input_path_count": _optional_int(path_count) or len(sample_paths),
        "sample_limit": _optional_int(sample_limit),
    }
    metadata["evaluated_sample_limited"] = metadata["input_path_count"] > len(sample_paths)  # type: ignore[operator]
    return metadata


def _coerce_predicate(
    predicate: AnalysisSuiteRulePredicate | Mapping[str, object],
) -> AnalysisSuiteRulePredicate:
    if isinstance(predicate, AnalysisSuiteRulePredicate):
        return predicate
    return AnalysisSuiteRulePredicate.from_dict(predicate)


def _coerce_rule_definition(
    definition: AnalysisSuiteWhiteBoxRuleDefinition | Mapping[str, object],
) -> AnalysisSuiteWhiteBoxRuleDefinition:
    if isinstance(definition, AnalysisSuiteWhiteBoxRuleDefinition):
        return definition
    return AnalysisSuiteWhiteBoxRuleDefinition.from_dict(definition)


def _values_equal(left: object, right: object) -> bool:
    if _is_nullish(left) and _is_nullish(right):
        return True
    left_number = _to_float(left)
    right_number = _to_float(right)
    if left_number is not None and right_number is not None:
        return left_number == right_number
    return str(left) == str(right)


def _ratio(numerator: int, denominator: int) -> float | None:
    if denominator == 0:
        return None
    return numerator / denominator


def _is_nullish(value: object) -> bool:
    if value is None:
        return True
    if isinstance(value, float):
        return math.isnan(value)
    if hasattr(value, "item"):
        try:
            return _is_nullish(value.item())  # type: ignore[no-any-return]
        except (TypeError, ValueError):
            return False
    type_name = type(value).__name__
    return type_name in {"NAType", "NaTType"}


def _to_float(value: object) -> float | None:
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if _is_nullish(value):
        return None
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _optional_int(value: object) -> int | None:
    number = _to_float(value)
    if number is None:
        return None
    return int(number)


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text else None


def _json_safe_mapping(values: Mapping[str, object]) -> dict[str, object]:
    return {str(key): _json_safe_value(value) for key, value in values.items()}


def _json_safe_value(value: object) -> object:
    if isinstance(value, Mapping):
        return _json_safe_mapping(value)
    if isinstance(value, (list, tuple)):
        return [_json_safe_value(item) for item in value]
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, int):
        return int(value)
    if isinstance(value, float):
        return float(value) if math.isfinite(value) else None
    if _is_nullish(value):
        return None
    if hasattr(value, "item"):
        try:
            return _json_safe_value(value.item())  # type: ignore[no-any-return]
        except (TypeError, ValueError):
            return str(value)
    return str(value)


def _dedupe(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(str(item) for item in values))


__all__ = [
    "ANALYSIS_SUITE_WHITEBOX_RULE_SCHEMA_VERSION",
    "DEFAULT_RULE_MATCH_SAMPLE_LIMIT",
    "MAX_RULE_MATCH_SAMPLE_LIMIT",
    "MIN_NEGATIVE_WARNING",
    "MIN_POSITIVE_WARNING",
    "MIN_TOTAL_WARNING",
    "AnalysisSuiteComparisonCohort",
    "AnalysisSuiteComparisonCohortRole",
    "AnalysisSuiteComparisonKind",
    "AnalysisSuiteComparisonSetDefinition",
    "AnalysisSuitePredicateResult",
    "AnalysisSuiteRuleMatch",
    "AnalysisSuiteRuleMetricSummary",
    "AnalysisSuiteRulePredicate",
    "AnalysisSuiteRulePredicateOperator",
    "AnalysisSuiteRuleTestReport",
    "AnalysisSuiteRuleTestStatus",
    "AnalysisSuiteRuleValidationReport",
    "AnalysisSuiteWhiteBoxRuleDefinition",
    "AnalysisSuiteWhiteBoxRuleTester",
]
