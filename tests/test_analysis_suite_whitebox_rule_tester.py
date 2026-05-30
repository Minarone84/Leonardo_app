from __future__ import annotations

import json
import math
from pathlib import Path
from types import SimpleNamespace

from leonardo.data.historical.analysis_suite_genome_path_builder import (
    AnalysisSuiteGenomePath,
    AnalysisSuiteGenomeSnapshot,
)
from leonardo.data.historical.analysis_suite_whitebox_rule_tester import (
    DEFAULT_RULE_MATCH_SAMPLE_LIMIT,
    MAX_RULE_MATCH_SAMPLE_LIMIT,
    AnalysisSuiteComparisonCohort,
    AnalysisSuiteComparisonSetDefinition,
    AnalysisSuiteRulePredicate,
    AnalysisSuiteWhiteBoxRuleDefinition,
    AnalysisSuiteWhiteBoxRuleTester,
)


def _snapshot(row_index: int, components: dict[str, object]) -> AnalysisSuiteGenomeSnapshot:
    return AnalysisSuiteGenomeSnapshot(
        row_index=row_index,
        ts_ms=(row_index + 1) * 1000,
        components=components,
        component_metadata={},
    )


def _path(
    *,
    anchor_row_index: int,
    anchor_components: dict[str, object],
    previous_components: dict[str, object] | None = None,
) -> AnalysisSuiteGenomePath:
    snapshots = []
    if previous_components is not None:
        snapshots.append(_snapshot(anchor_row_index - 1, previous_components))
    snapshots.append(_snapshot(anchor_row_index, anchor_components))
    return AnalysisSuiteGenomePath(
        anchor_row_index=anchor_row_index,
        anchor_ts_ms=(anchor_row_index + 1) * 1000,
        anchor_kind="row",
        snapshots=tuple(snapshots),
    )


def _rule(
    *predicates: AnalysisSuiteRulePredicate,
    rule_key: str = "rule_under_test",
) -> AnalysisSuiteWhiteBoxRuleDefinition:
    return AnalysisSuiteWhiteBoxRuleDefinition(
        rule_key=rule_key,
        display_name="Rule under test",
        predicates=tuple(predicates),
    )


def _comparison(
    *,
    positive_paths: tuple[object, ...],
    negative_paths: tuple[object, ...],
    metadata: dict[str, object] | None = None,
    positive_metadata: dict[str, object] | None = None,
    negative_metadata: dict[str, object] | None = None,
) -> AnalysisSuiteComparisonSetDefinition:
    return AnalysisSuiteComparisonSetDefinition(
        comparison_key="comparison",
        display_name="Comparison",
        comparison_kind="custom",
        metadata=metadata if metadata is not None else {"time_split": "provided"},
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


def _tester() -> AnalysisSuiteWhiteBoxRuleTester:
    return AnalysisSuiteWhiteBoxRuleTester()


def test_predicate_operators_are_evaluated() -> None:
    cases = (
        AnalysisSuiteRulePredicate("state", "equals", value="low"),
        AnalysisSuiteRulePredicate("state", "not_equals", value="high"),
        AnalysisSuiteRulePredicate("score", "gt", value=9),
        AnalysisSuiteRulePredicate("score", "gte", value=10),
        AnalysisSuiteRulePredicate("score", "lt", value=11),
        AnalysisSuiteRulePredicate("score", "lte", value=10),
        AnalysisSuiteRulePredicate("state", "in", values=("low", "mid")),
        AnalysisSuiteRulePredicate("state", "not_in", values=("high", "mid")),
        AnalysisSuiteRulePredicate("empty", "is_null"),
        AnalysisSuiteRulePredicate("score", "not_null"),
    )
    positive = (_path(anchor_row_index=1, anchor_components={"state": "low", "score": 10, "empty": None}),)
    negative = (_path(anchor_row_index=2, anchor_components={"state": "high", "score": None, "empty": 1}),)

    for predicate in cases:
        report = _tester().test_rule(
            _rule(predicate),
            _comparison(positive_paths=positive, negative_paths=negative),
        )

        assert report.metrics.positive_matched == 1
        assert report.metrics.negative_matched == 0
        assert report.positive_matches[0].predicate_results[0].matched is True


def test_required_and_optional_missing_component_behavior() -> None:
    path = _path(anchor_row_index=1, anchor_components={"state": "low"})
    comparison = _comparison(
        positive_paths=(path,),
        negative_paths=(_path(anchor_row_index=2, anchor_components={"state": "high"}),),
    )

    required_report = _tester().test_rule(
        _rule(AnalysisSuiteRulePredicate("missing", "equals", value="x")),
        comparison,
    )
    optional_report = _tester().test_rule(
        _rule(
            AnalysisSuiteRulePredicate("state", "equals", value="low"),
            AnalysisSuiteRulePredicate("missing", "equals", value="x", required=False),
        ),
        comparison,
    )

    assert required_report.metrics.positive_matched == 0
    assert "component_missing: missing" in required_report.warnings
    assert optional_report.metrics.positive_matched == 1
    assert optional_report.positive_matches[0].predicate_results[1].missing is True


def test_path_offsets_use_anchor_and_previous_snapshots() -> None:
    path = _path(
        anchor_row_index=3,
        previous_components={"trend": "down"},
        anchor_components={"trend": "up"},
    )
    comparison = _comparison(
        positive_paths=(path,),
        negative_paths=(
            _path(
                anchor_row_index=4,
                previous_components={"trend": "up"},
                anchor_components={"trend": "down"},
            ),
        ),
    )

    report = _tester().test_rule(
        _rule(
            AnalysisSuiteRulePredicate("trend", "equals", value="up", path_offset=0),
            AnalysisSuiteRulePredicate("trend", "equals", value="down", path_offset=-1),
        ),
        comparison,
    )
    unavailable_report = _tester().test_rule(
        _rule(AnalysisSuiteRulePredicate("trend", "equals", value="x", path_offset=-2)),
        comparison,
    )
    future_report = _tester().test_rule(
        _rule(AnalysisSuiteRulePredicate("trend", "equals", value="x", path_offset=1)),
        comparison,
    )

    assert report.metrics.positive_matched == 1
    assert unavailable_report.metrics.positive_matched == 0
    assert "snapshot_offset_unavailable: -2" in unavailable_report.warnings
    assert future_report.status == "blocked"
    assert any("positive_path_offset_forbidden" in item for item in future_report.blockers)


def test_rule_predicates_use_and_semantics() -> None:
    positive = (_path(anchor_row_index=1, anchor_components={"state": "low", "volume": "normal"}),)
    negative = (_path(anchor_row_index=2, anchor_components={"state": "high", "volume": "normal"}),)

    report = _tester().test_rule(
        _rule(
            AnalysisSuiteRulePredicate("state", "equals", value="low"),
            AnalysisSuiteRulePredicate("volume", "equals", value="elevated"),
        ),
        _comparison(positive_paths=positive, negative_paths=negative),
    )

    assert report.metrics.positive_matched == 0
    assert report.metrics.false_negative == 1


def test_metric_summary_counts_and_rates() -> None:
    positives = tuple(
        _path(anchor_row_index=index, anchor_components={"state": "match" if index < 3 else "miss"})
        for index in range(4)
    )
    negatives = tuple(
        _path(anchor_row_index=index + 10, anchor_components={"state": "match" if index < 2 else "miss"})
        for index in range(6)
    )

    report = _tester().test_rule(
        _rule(AnalysisSuiteRulePredicate("state", "equals", value="match")),
        _comparison(positive_paths=positives, negative_paths=negatives),
    )
    metrics = report.metrics

    assert metrics.positive_total == 4
    assert metrics.negative_total == 6
    assert metrics.positive_matched == 3
    assert metrics.negative_matched == 2
    assert metrics.true_positive == 3
    assert metrics.false_positive == 2
    assert metrics.false_negative == 1
    assert metrics.true_negative == 4
    assert metrics.support == 5
    assert metrics.coverage == 0.5
    assert metrics.precision == 0.6
    assert metrics.recall == 0.75
    assert metrics.specificity == 4 / 6
    assert metrics.false_positive_rate == 2 / 6
    assert metrics.false_negative_rate == 0.25
    assert metrics.baseline_positive_rate == 0.4
    assert metrics.matched_positive_rate == 0.6
    assert math.isclose(metrics.lift or 0.0, 1.5)


def test_zero_denominators_are_safe() -> None:
    report = _tester().test_rule(
        _rule(AnalysisSuiteRulePredicate("state", "equals", value="match")),
        _comparison(positive_paths=(), negative_paths=()),
    )

    assert report.status == "blocked"
    assert report.metrics.coverage is None
    assert report.metrics.precision is None
    assert report.metrics.recall is None
    assert report.metrics.specificity is None
    assert report.metrics.lift is None


def test_small_sample_and_missing_time_split_warnings() -> None:
    report = _tester().test_rule(
        _rule(AnalysisSuiteRulePredicate("state", "equals", value="match")),
        _comparison(
            positive_paths=(_path(anchor_row_index=1, anchor_components={"state": "match"}),),
            negative_paths=(_path(anchor_row_index=2, anchor_components={"state": "miss"}),),
            metadata={},
        ),
    )

    assert report.status == "warning"
    assert "time_split_not_assessed" in report.warnings
    assert "low_total_evaluated: 2" in report.warnings
    assert "low_positive_count: 1" in report.warnings
    assert "low_negative_count: 1" in report.warnings


def test_comparison_set_and_rule_blockers() -> None:
    empty_rule_report = _tester().test_rule(
        _rule(),
        _comparison(
            positive_paths=(_path(anchor_row_index=1, anchor_components={"state": "match"}),),
            negative_paths=(_path(anchor_row_index=2, anchor_components={"state": "miss"}),),
        ),
    )
    empty_cohort_report = _tester().test_rule(
        _rule(AnalysisSuiteRulePredicate("state", "equals", value="match")),
        _comparison(positive_paths=(), negative_paths=()),
    )
    invalid_offset_report = _tester().test_rule(
        _rule(
            AnalysisSuiteRulePredicate(
                "state",
                "equals",
                value="match",
                path_offset="invalid",  # type: ignore[arg-type]
            )
        ),
        _comparison(
            positive_paths=(_path(anchor_row_index=1, anchor_components={"state": "match"}),),
            negative_paths=(_path(anchor_row_index=2, anchor_components={"state": "miss"}),),
        ),
    )

    assert empty_rule_report.status == "blocked"
    assert "rule_predicates_required" in empty_rule_report.blockers
    assert empty_cohort_report.status == "blocked"
    assert "positive_cohort_empty" in empty_cohort_report.blockers
    assert "negative_cohort_empty" in empty_cohort_report.blockers
    assert invalid_offset_report.status == "blocked"
    assert "predicate[0]_path_offset_must_be_int" in invalid_offset_report.blockers


def test_diagnostic_gating_blocks_or_warns() -> None:
    positives = tuple(
        _path(anchor_row_index=index, anchor_components={"state": "match"})
        for index in range(15)
    )
    negatives = tuple(
        _path(anchor_row_index=index + 20, anchor_components={"state": "miss"})
        for index in range(15)
    )
    comparison = _comparison(positive_paths=positives, negative_paths=negatives)
    rule = _rule(AnalysisSuiteRulePredicate("state", "equals", value="match"))

    blocked_report = _tester().test_rule(
        rule,
        comparison,
        diagnostic_report=SimpleNamespace(status="blocked"),
    )
    warning_report = _tester().test_rule(
        rule,
        comparison,
        diagnostic_report=SimpleNamespace(status="warning"),
    )
    ready_report = _tester().test_rule(
        rule,
        comparison,
        diagnostic_report=SimpleNamespace(status="ready"),
    )

    assert blocked_report.status == "blocked"
    assert "diagnostic_report_not_acceptable: blocked" in blocked_report.blockers
    assert warning_report.status == "warning"
    assert "diagnostic_report_warning" in warning_report.warnings
    assert ready_report.status == "ready"


def test_match_samples_are_bounded_but_metrics_remain_complete() -> None:
    positives = tuple(
        _path(anchor_row_index=index, anchor_components={"state": "match"})
        for index in range(120)
    )
    negatives = tuple(
        _path(anchor_row_index=index + 200, anchor_components={"state": "match"})
        for index in range(120)
    )

    report = _tester().test_rule(
        _rule(AnalysisSuiteRulePredicate("state", "equals", value="match")),
        _comparison(positive_paths=positives, negative_paths=negatives),
        sample_limit=3,
    )
    clamped_report = _tester().test_rule(
        _rule(AnalysisSuiteRulePredicate("state", "equals", value="match")),
        _comparison(positive_paths=positives, negative_paths=negatives),
        sample_limit=MAX_RULE_MATCH_SAMPLE_LIMIT + 1,
    )

    assert len(report.positive_matches) == 3
    assert len(report.negative_matches) == 3
    assert report.metrics.positive_matched == 120
    assert report.metrics.negative_matched == 120
    assert clamped_report.requested_sample_limit == MAX_RULE_MATCH_SAMPLE_LIMIT + 1
    assert clamped_report.sample_limit == MAX_RULE_MATCH_SAMPLE_LIMIT


def test_default_sample_limit_constant_is_reported() -> None:
    report = _tester().test_rule(
        _rule(AnalysisSuiteRulePredicate("state", "equals", value="match")),
        _comparison(
            positive_paths=(_path(anchor_row_index=1, anchor_components={"state": "match"}),),
            negative_paths=(_path(anchor_row_index=2, anchor_components={"state": "miss"}),),
        ),
    )

    assert report.requested_sample_limit == DEFAULT_RULE_MATCH_SAMPLE_LIMIT
    assert report.sample_limit == DEFAULT_RULE_MATCH_SAMPLE_LIMIT


def test_bounded_upstream_path_report_metadata_is_reported() -> None:
    positive_report = SimpleNamespace(
        status="ready",
        path_count=20,
        sample_limit=2,
        sample_paths=(
            _path(anchor_row_index=1, anchor_components={"state": "match"}),
            _path(anchor_row_index=2, anchor_components={"state": "match"}),
        ),
    )
    negative_report = {
        "status": "ready",
        "path_count": 20,
        "sample_limit": 2,
        "sample_paths": (
            _path(anchor_row_index=3, anchor_components={"state": "miss"}),
            _path(anchor_row_index=4, anchor_components={"state": "miss"}),
        ),
    }
    comparison = _tester().build_comparison_set_from_path_reports(
        positive_path_report=positive_report,
        negative_path_report=negative_report,
        comparison_key="bounded",
        display_name="Bounded",
    )

    report = _tester().test_rule(
        _rule(AnalysisSuiteRulePredicate("state", "equals", value="match")),
        comparison,
    )

    assert report.evaluated_sample_limited is True
    assert report.input_path_count == 40
    assert report.evaluated_path_count == 4
    assert "metrics_based_on_bounded_preview_samples" in report.warnings


def test_json_safe_output_handles_non_finite_values() -> None:
    report = _tester().test_rule(
        _rule(AnalysisSuiteRulePredicate("score", "not_null")),
        _comparison(
            positive_paths=(
                _path(anchor_row_index=1, anchor_components={"score": float("inf")}),
            ),
            negative_paths=(
                _path(anchor_row_index=2, anchor_components={"score": float("nan")}),
            ),
        ),
    )

    payload = report.to_dict()
    json.dumps(payload, allow_nan=False, sort_keys=True)
    assert payload["positive_matches"][0]["predicate_results"][0]["actual_value"] is None


def test_dict_like_paths_are_supported() -> None:
    positive_path = {
        "anchor_row_index": 1,
        "anchor_ts_ms": 1000,
        "snapshots": [{"components": {"state": "match"}}],
    }
    negative_path = {
        "anchor_row_index": 2,
        "anchor_ts_ms": 2000,
        "snapshots": [{"components": {"state": "miss"}}],
    }

    report = _tester().test_rule(
        _rule(AnalysisSuiteRulePredicate("state", "equals", value="match")),
        _comparison(positive_paths=(positive_path,), negative_paths=(negative_path,)),
    )

    assert report.metrics.positive_matched == 1
    assert report.positive_matches[0].anchor_row_index == 1
    assert report.positive_matches[0].anchor_ts_ms == 1000


def test_validate_rule_definition_uses_upstream_genome_report_status() -> None:
    blocked = _tester().validate_rule_definition(
        _rule(AnalysisSuiteRulePredicate("state", "equals", value="match")),
        genome_path_preview_report=SimpleNamespace(status="blocked", blockers=("bad_paths",)),
    )
    warning = _tester().validate_rule_definition(
        _rule(AnalysisSuiteRulePredicate("state", "equals", value="match")),
        genome_path_preview_report=SimpleNamespace(status="warning", warnings=("review",)),
    )

    assert blocked.status == "blocked"
    assert "genome_path_report_not_acceptable: blocked" in blocked.blockers
    assert "bad_paths" in blocked.blockers
    assert warning.status == "warning"
    assert "genome_path_report_warning" in warning.warnings
    assert "review" in warning.warnings


def test_module_does_not_import_gui_or_file_policy_layers() -> None:
    module_path = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "leonardo"
        / "data"
        / "historical"
        / "analysis_suite_whitebox_rule_tester.py"
    )
    source = module_path.read_text(encoding="utf-8")

    forbidden = (
        "PySide",
        "QtWidgets",
        "QWidget",
        "QDialog",
        "QMainWindow",
        "AnalysisProjectStore",
        "AnalysisRunStore",
        "AnalysisReportStore",
        "read_csv",
        "dataframe.csv",
        "manifest.json",
        "save_manifest",
        "execute_recipe",
        "ArtifactCalculationService",
        "AnalysisDatabaseStore",
    )
    for token in forbidden:
        assert token not in source

    assert "AnalysisSuiteRuleCandidateScanReport" not in source
    assert "scan_single_predicate_candidates" not in source
