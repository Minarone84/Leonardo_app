from __future__ import annotations

import json
import math
from pathlib import Path
from types import SimpleNamespace

from leonardo.data.historical.analysis_suite_genome_path_builder import (
    AnalysisSuiteGenomePath,
    AnalysisSuiteGenomeSnapshot,
)
from leonardo.data.historical.analysis_suite_rule_candidate_scanner import (
    MAX_RULE_CANDIDATE_RETURN_LIMIT,
    AnalysisSuiteRuleCandidateScanConfig,
    AnalysisSuiteRuleCandidateScanner,
)
from leonardo.data.historical.analysis_suite_whitebox_rule_tester import (
    AnalysisSuiteComparisonCohort,
    AnalysisSuiteComparisonSetDefinition,
    AnalysisSuiteWhiteBoxRuleTester,
)


def _snapshot(
    row_index: int,
    components: dict[str, object],
    component_metadata: dict[str, object] | None = None,
) -> AnalysisSuiteGenomeSnapshot:
    return AnalysisSuiteGenomeSnapshot(
        row_index=row_index,
        ts_ms=(row_index + 1) * 1000,
        components=components,
        component_metadata=component_metadata or {},
    )


def _path(
    *,
    anchor_row_index: int,
    anchor_components: dict[str, object],
    previous_components: dict[str, object] | None = None,
    component_metadata: dict[str, object] | None = None,
) -> AnalysisSuiteGenomePath:
    snapshots = []
    if previous_components is not None:
        snapshots.append(
            _snapshot(
                anchor_row_index - 1,
                previous_components,
                component_metadata=component_metadata,
            )
        )
    snapshots.append(
        _snapshot(
            anchor_row_index,
            anchor_components,
            component_metadata=component_metadata,
        )
    )
    return AnalysisSuiteGenomePath(
        anchor_row_index=anchor_row_index,
        anchor_ts_ms=(anchor_row_index + 1) * 1000,
        anchor_kind="row",
        snapshots=tuple(snapshots),
    )


def _comparison(
    *,
    positive_paths: tuple[object, ...],
    negative_paths: tuple[object, ...],
    positive_metadata: dict[str, object] | None = None,
    negative_metadata: dict[str, object] | None = None,
) -> AnalysisSuiteComparisonSetDefinition:
    return AnalysisSuiteComparisonSetDefinition(
        comparison_key="comparison",
        display_name="Comparison",
        comparison_kind="custom",
        metadata={"time_split": "provided"},
        positive_cohort=AnalysisSuiteComparisonCohort(
            cohort_key="positive",
            label="Positive",
            role="positive",
            paths=positive_paths,
            metadata=positive_metadata or {},
        ),
        negative_cohort=AnalysisSuiteComparisonCohort(
            cohort_key="negative",
            label="Negative",
            role="negative",
            paths=negative_paths,
            metadata=negative_metadata or {},
        ),
    )


def _metric_comparison() -> AnalysisSuiteComparisonSetDefinition:
    positives = tuple(
        _path(
            anchor_row_index=index,
            anchor_components={
                "state": "match" if index < 3 else "miss",
                "regime": "good" if index < 2 else "other",
            },
        )
        for index in range(4)
    )
    negatives = tuple(
        _path(
            anchor_row_index=index + 10,
            anchor_components={
                "state": "match" if index < 2 else "miss",
                "regime": "good" if index < 1 else "other",
            },
        )
        for index in range(6)
    )
    return _comparison(positive_paths=positives, negative_paths=negatives)


def test_predicate_vocabulary_generates_symbolic_boolean_and_null_predicates() -> None:
    comparison = _comparison(
        positive_paths=(
            _path(
                anchor_row_index=1,
                anchor_components={"state": "low", "flag": True, "bucket": None},
            ),
        ),
        negative_paths=(
            _path(
                anchor_row_index=2,
                anchor_components={"state": "high", "flag": False, "bucket": "known"},
            ),
        ),
    )
    config = AnalysisSuiteRuleCandidateScanConfig(
        allowed_operators=("equals", "is_null", "not_null"),
        min_total_support=1,
        min_positive_matches=1,
    )

    report = AnalysisSuiteRuleCandidateScanner().build_predicate_vocabulary(comparison, config)
    predicate_keys = {item.predicate_key for item in report.vocabulary_items}

    assert report.status == "ready"
    assert report.component_count == 3
    assert report.item_count == len(report.vocabulary_items)
    assert "state__offset_0__equals__low" in predicate_keys
    assert "flag__offset_0__equals__True" in predicate_keys
    assert "bucket__offset_0__is_null__null" in predicate_keys
    assert "bucket__offset_0__not_null__null" in predicate_keys


def test_numeric_values_are_skipped_when_threshold_policy_is_none() -> None:
    comparison = _comparison(
        positive_paths=(
            _path(anchor_row_index=1, anchor_components={"score": 1.5, "state": "low"}),
        ),
        negative_paths=(
            _path(anchor_row_index=2, anchor_components={"score": 2.5, "state": "high"}),
        ),
    )

    report = AnalysisSuiteRuleCandidateScanner().build_predicate_vocabulary(comparison)

    assert all(item.component_key != "score" for item in report.vocabulary_items)
    assert any("numeric_component_skipped_without_threshold_policy: score" in item for item in report.warnings)


def test_negative_path_offsets_can_use_previous_snapshots_when_enabled() -> None:
    comparison = _comparison(
        positive_paths=(
            _path(
                anchor_row_index=2,
                previous_components={"prior_state": "compression"},
                anchor_components={"prior_state": "release"},
            ),
        ),
        negative_paths=(
            _path(
                anchor_row_index=3,
                previous_components={"prior_state": "drift"},
                anchor_components={"prior_state": "release"},
            ),
        ),
    )
    config = AnalysisSuiteRuleCandidateScanConfig(
        allowed_path_offsets=(0, -1),
        include_negative_offsets=True,
        min_total_support=1,
        min_positive_matches=1,
    )

    report = AnalysisSuiteRuleCandidateScanner().scan_candidates(comparison, config)
    prior_candidate = next(
        candidate
        for candidate in report.candidates
        if candidate.rule_definition.predicates[0].path_offset == -1
        and candidate.rule_definition.predicates[0].value == "compression"
    )

    assert prior_candidate.metrics.positive_matched == 1
    assert prior_candidate.metrics.negative_matched == 0


def test_positive_path_offsets_block_vocabulary_generation() -> None:
    comparison = _comparison(
        positive_paths=(_path(anchor_row_index=1, anchor_components={"state": "low"}),),
        negative_paths=(_path(anchor_row_index=2, anchor_components={"state": "high"}),),
    )
    config = AnalysisSuiteRuleCandidateScanConfig(allowed_path_offsets=(1,))

    report = AnalysisSuiteRuleCandidateScanner().build_predicate_vocabulary(comparison, config)

    assert report.status == "blocked"
    assert "positive_path_offset_not_allowed: 1" in report.blockers


def test_empty_comparison_cohorts_block_scan() -> None:
    report = AnalysisSuiteRuleCandidateScanner().scan_candidates(
        _comparison(positive_paths=(), negative_paths=()),
    )

    assert report.status == "blocked"
    assert "positive_cohort_empty" in report.blockers
    assert "negative_cohort_empty" in report.blockers


def test_diagnostic_gating_blocks_or_warns_scan() -> None:
    config = AnalysisSuiteRuleCandidateScanConfig(
        min_total_support=1,
        min_positive_matches=1,
    )

    blocked_report = AnalysisSuiteRuleCandidateScanner().scan_candidates(
        _metric_comparison(),
        config,
        diagnostic_report=SimpleNamespace(status="blocked"),
    )
    warning_report = AnalysisSuiteRuleCandidateScanner().scan_candidates(
        _metric_comparison(),
        config,
        diagnostic_report=SimpleNamespace(status="warning"),
    )

    assert blocked_report.status == "blocked"
    assert blocked_report.candidate_count_scanned == 0
    assert "diagnostic_report_not_acceptable: blocked" in blocked_report.blockers
    assert warning_report.candidate_count_scanned > 0
    assert "diagnostic_report_warning" in warning_report.warnings


class _SpyRuleTester:
    def __init__(self) -> None:
        self.inner = AnalysisSuiteWhiteBoxRuleTester()
        self.rules: list[object] = []

    def test_rule(self, *args: object, **kwargs: object) -> object:
        self.rules.append(args[0])
        return self.inner.test_rule(*args, **kwargs)  # type: ignore[arg-type]


def test_candidate_scan_reuses_as10_rule_tester_metrics() -> None:
    spy = _SpyRuleTester()
    scanner = AnalysisSuiteRuleCandidateScanner(rule_tester=spy)  # type: ignore[arg-type]
    config = AnalysisSuiteRuleCandidateScanConfig(
        min_total_support=1,
        min_positive_matches=1,
    )

    report = scanner.scan_candidates(_metric_comparison(), config)
    state_candidate = next(
        candidate
        for candidate in report.candidates
        if candidate.rule_definition.predicates[0].component_key == "state"
        and candidate.rule_definition.predicates[0].value == "match"
    )
    metrics = state_candidate.metrics

    assert spy.rules
    assert all(len(rule.predicates) == 1 for rule in spy.rules)  # type: ignore[attr-defined]
    assert metrics.support == 5
    assert metrics.positive_matched == 3
    assert metrics.negative_matched == 2
    assert metrics.precision == 0.6
    assert metrics.recall == 0.75
    assert math.isclose(metrics.lift or 0.0, 1.5)


def test_candidate_filtering_reports_filtered_counts_and_reasons() -> None:
    config = AnalysisSuiteRuleCandidateScanConfig(
        min_total_support=99,
        min_positive_matches=1,
    )

    report = AnalysisSuiteRuleCandidateScanner().scan_candidates(_metric_comparison(), config)

    assert report.candidate_count_scanned > 0
    assert report.candidate_count_returned == 0
    assert report.candidate_count_filtered == report.candidate_count_scanned
    assert report.metadata["filter_reasons"]["min_total_support"] == report.candidate_count_scanned


def test_candidates_are_ranked_by_diagnostic_score() -> None:
    config = AnalysisSuiteRuleCandidateScanConfig(
        min_total_support=1,
        min_positive_matches=1,
    )

    report = AnalysisSuiteRuleCandidateScanner().scan_candidates(_metric_comparison(), config)
    scores = [candidate.score for candidate in report.candidates]
    ranks = [candidate.rank for candidate in report.candidates]

    assert scores == sorted(scores, reverse=True)
    assert ranks == list(range(1, len(report.candidates) + 1))
    assert all(candidate.score is not None for candidate in report.candidates)


def test_scan_reports_multiple_testing_sample_limit_and_stability_warnings() -> None:
    comparison = _comparison(
        positive_paths=tuple(
            _path(
                anchor_row_index=index,
                anchor_components={
                    f"component_{index}": "yes",
                    f"extra_component_{index}": "yes",
                },
            )
            for index in range(3)
        ),
        negative_paths=(
            _path(anchor_row_index=10, anchor_components={"component_10": "yes"}),
        ),
        positive_metadata={"input_path_count": 20},
    )
    config = AnalysisSuiteRuleCandidateScanConfig(
        min_total_support=1,
        min_positive_matches=0,
    )

    report = AnalysisSuiteRuleCandidateScanner().scan_candidates(comparison, config)

    assert report.sample_limited is True
    assert "input_cohorts_are_sample_limited" in report.vocabulary_report.warnings
    assert "candidate_metrics_are_based_on_bounded_preview_samples" in report.warnings
    assert "multiple_testing_correction_not_applied" in report.warnings
    assert "temporal_stability_validation_not_performed" in report.warnings
    assert "candidate_count_high_relative_to_evaluated_sample_size" in report.warnings
    assert report.metadata["stability_status"] == "unknown"


def test_returned_candidates_are_capped_and_counts_remain_accurate() -> None:
    positives = tuple(
        _path(
            anchor_row_index=index,
            anchor_components={f"component_{offset}": "yes" for offset in range(8)},
        )
        for index in range(3)
    )
    negatives = tuple(
        _path(
            anchor_row_index=index + 10,
            anchor_components={f"component_{offset}": "no" for offset in range(8)},
        )
        for index in range(3)
    )
    config = AnalysisSuiteRuleCandidateScanConfig(
        max_candidates_returned=2,
        min_total_support=1,
        min_positive_matches=0,
    )

    report = AnalysisSuiteRuleCandidateScanner().scan_candidates(
        _comparison(positive_paths=positives, negative_paths=negatives),
        config,
    )

    assert report.candidate_count_scanned > 2
    assert report.candidate_count_returned == 2
    assert report.candidate_count_filtered == report.candidate_count_scanned - 2
    assert report.metadata["filter_reasons"]["return_limit"] > 0
    assert "candidate_return_limit_applied" in report.warnings


def test_leaky_component_metadata_is_skipped() -> None:
    comparison = _comparison(
        positive_paths=(
            _path(
                anchor_row_index=1,
                anchor_components={"safe": "yes", "future": "yes"},
                component_metadata={"future": {"future_derived": True}},
            ),
        ),
        negative_paths=(
            _path(
                anchor_row_index=2,
                anchor_components={"safe": "no", "future": "no"},
                component_metadata={"future": {"future_derived": True}},
            ),
        ),
    )

    report = AnalysisSuiteRuleCandidateScanner().build_predicate_vocabulary(comparison)

    assert all(item.component_key != "future" for item in report.vocabulary_items)
    assert "component_skipped_due_to_leakage_metadata: future" in report.warnings


def test_scan_report_to_dict_is_json_safe() -> None:
    config = AnalysisSuiteRuleCandidateScanConfig(
        max_candidates_returned=MAX_RULE_CANDIDATE_RETURN_LIMIT + 1,
        min_total_support=1,
        min_positive_matches=1,
    )

    report = AnalysisSuiteRuleCandidateScanner().scan_candidates(_metric_comparison(), config)

    json.dumps(report.to_dict(), sort_keys=True)
    assert "max_candidates_returned_clamped_to_max" in report.warnings


def test_boundary_no_gui_or_mutation_imports() -> None:
    source = Path("src/leonardo/data/historical/analysis_suite_rule_candidate_scanner.py").read_text()

    forbidden_tokens = (
        "PySide",
        "QtWidgets",
        "QWidget",
        "QDialog",
        "QMainWindow",
        "AnalysisProjectStore",
        "AnalysisRunStore",
        "AnalysisReportStore",
        "read_csv",
        "save_manifest",
        "build_database",
        "execute_recipe",
        "ArtifactCalculationService",
    )
    for token in forbidden_tokens:
        assert token not in source
