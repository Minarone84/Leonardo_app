import json
from types import SimpleNamespace

from leonardo.data.historical.analysis_suite_candidate_temporal_validator import (
    AnalysisSuiteCandidateTemporalValidator,
    AnalysisSuiteTemporalValidationConfig,
)
from leonardo.data.historical.analysis_suite_genome_path_builder import (
    AnalysisSuiteGenomePath,
    AnalysisSuiteGenomeSnapshot,
)
from leonardo.data.historical.analysis_suite_rule_candidate_scanner import (
    AnalysisSuitePredicateVocabularyReport,
    AnalysisSuiteRuleCandidate,
    AnalysisSuiteRuleCandidateScanReport,
)
from leonardo.data.historical.analysis_suite_whitebox_rule_tester import (
    AnalysisSuiteComparisonCohort,
    AnalysisSuiteComparisonSetDefinition,
    AnalysisSuiteRulePredicate,
    AnalysisSuiteWhiteBoxRuleDefinition,
    AnalysisSuiteWhiteBoxRuleTester,
)


def _snapshot(row_index: int, components: dict[str, object]) -> AnalysisSuiteGenomeSnapshot:
    return AnalysisSuiteGenomeSnapshot(
        row_index=row_index,
        ts_ms=1_700_000_000_000 + row_index,
        components=components,
        component_metadata={},
    )


def _path(row_index: int, ts_ms: int | None, components: dict[str, object]) -> AnalysisSuiteGenomePath:
    return AnalysisSuiteGenomePath(
        anchor_row_index=row_index,
        anchor_ts_ms=ts_ms,
        anchor_kind="row",
        snapshots=(_snapshot(row_index, components),),
    )


def _comparison(
    positive_paths: tuple[AnalysisSuiteGenomePath, ...],
    negative_paths: tuple[AnalysisSuiteGenomePath, ...],
    *,
    positive_metadata: dict[str, object] | None = None,
    negative_metadata: dict[str, object] | None = None,
) -> AnalysisSuiteComparisonSetDefinition:
    return AnalysisSuiteComparisonSetDefinition(
        comparison_key="family_a_vs_family_b",
        display_name="Family A vs Family B",
        positive_cohort=AnalysisSuiteComparisonCohort(
            cohort_key="positive",
            label="Positive",
            paths=positive_paths,
            role="positive",
            metadata=positive_metadata or {},
        ),
        negative_cohort=AnalysisSuiteComparisonCohort(
            cohort_key="negative",
            label="Negative",
            paths=negative_paths,
            role="negative",
            metadata=negative_metadata or {},
        ),
        comparison_kind="custom",
        metadata={},
    )


def _rule(component_key: str = "state", value: object = "match", rule_key: str = "state_match"):
    return AnalysisSuiteWhiteBoxRuleDefinition(
        rule_key=rule_key,
        display_name=rule_key,
        predicates=(
            AnalysisSuiteRulePredicate(
                component_key=component_key,
                operator="equals",
                value=value,
            ),
        ),
    )


def _candidate(
    comparison_set: AnalysisSuiteComparisonSetDefinition,
    *,
    rule: AnalysisSuiteWhiteBoxRuleDefinition | None = None,
    candidate_key: str = "candidate_1",
) -> AnalysisSuiteRuleCandidate:
    rule_definition = rule or _rule()
    metrics = AnalysisSuiteWhiteBoxRuleTester().test_rule(
        rule_definition=rule_definition,
        comparison_set=comparison_set,
    ).metrics
    return AnalysisSuiteRuleCandidate(
        candidate_key=candidate_key,
        rule_definition=rule_definition,
        metrics=metrics,
        score=1.0,
        rank=1,
        warnings=(),
        metadata={},
    )


def _scan_report(
    candidates: tuple[AnalysisSuiteRuleCandidate, ...],
    *,
    status: str = "warning",
    warnings: tuple[str, ...] = ("multiple_testing_correction_not_applied",),
    sample_limited: bool = False,
) -> AnalysisSuiteRuleCandidateScanReport:
    return AnalysisSuiteRuleCandidateScanReport(
        status=status,
        comparison_key="family_a_vs_family_b",
        vocabulary_report=AnalysisSuitePredicateVocabularyReport(
            status="ready",
            sample_limited=sample_limited,
            warnings=("vocabulary_sample_limited",) if sample_limited else (),
        ),
        candidates=candidates,
        candidate_count_scanned=len(candidates),
        candidate_count_returned=len(candidates),
        candidate_count_filtered=0,
        warnings=warnings,
        sample_limited=sample_limited,
        metadata={"sample_limited": sample_limited},
    )


def _stable_comparison() -> AnalysisSuiteComparisonSetDefinition:
    return _comparison(
        (
            _path(1, 1_000, {"state": "match"}),
            _path(3, 3_000, {"state": "match"}),
        ),
        (
            _path(2, 2_000, {"state": "miss"}),
            _path(4, 4_000, {"state": "miss"}),
        ),
    )


def _config(**overrides) -> AnalysisSuiteTemporalValidationConfig:
    values = {
        "validation_fraction": 0.5,
        "min_segment_total": 2,
        "min_segment_positive": 1,
        "min_segment_negative": 1,
        "min_validation_support": 1,
        "min_validation_positive_matches": 1,
        "max_candidates_validated": 100,
    }
    values.update(overrides)
    return AnalysisSuiteTemporalValidationConfig(**values)


def test_config_validation_blocks_invalid_values():
    comparison_set = _stable_comparison()
    candidate = _candidate(comparison_set)
    scan_report = _scan_report((candidate,))

    invalid_fraction = AnalysisSuiteCandidateTemporalValidator().validate_candidates(
        comparison_set=comparison_set,
        candidate_scan_report=scan_report,
        config=_config(validation_fraction=1.0),
    )
    assert invalid_fraction.status == "blocked"
    assert "validation_fraction_must_be_between_zero_and_one" in invalid_fraction.blockers

    invalid_limit = AnalysisSuiteCandidateTemporalValidator().validate_candidates(
        comparison_set=comparison_set,
        candidate_scan_report=scan_report,
        config=_config(max_candidates_validated=0),
    )
    assert invalid_limit.status == "blocked"
    assert "max_candidates_validated_must_be_positive" in invalid_limit.blockers


def test_chronological_holdout_split_preserves_order_and_cohorts():
    comparison_set = _comparison(
        (
            _path(1, 1_000, {"state": "match"}),
            _path(2, 2_000, {"state": "match"}),
            _path(5, 9_000, {"state": "match"}),
        ),
        (
            _path(3, 3_000, {"state": "miss"}),
            _path(4, 4_000, {"state": "miss"}),
            _path(6, 10_000, {"state": "miss"}),
        ),
    )
    candidate = _candidate(comparison_set)
    report = AnalysisSuiteCandidateTemporalValidator().validate_candidates(
        comparison_set=comparison_set,
        candidate_scan_report=_scan_report((candidate,)),
        config=_config(validation_fraction=0.30),
    )

    discovery, validation = report.segments
    assert discovery.start_ts_ms == 1_000
    assert discovery.end_ts_ms == 4_000
    assert discovery.metadata["positive_count"] == 2
    assert discovery.metadata["negative_count"] == 2
    assert validation.start_ts_ms == 9_000
    assert validation.end_ts_ms == 10_000
    assert validation.metadata["positive_count"] == 1
    assert validation.metadata["negative_count"] == 1

    result = report.candidate_results[0]
    assert result.discovery_segment_report.rule_test_report.comparison_set.comparison_key.endswith(
        "__discovery"
    )
    assert result.validation_segment_report.rule_test_report.comparison_set.comparison_key.endswith(
        "__validation"
    )


def test_missing_anchor_timestamps_block_chronological_holdout():
    comparison_set = _comparison(
        (_path(1, None, {"state": "match"}),),
        (_path(2, 2_000, {"state": "miss"}),),
    )
    candidate = _candidate(_stable_comparison())
    report = AnalysisSuiteCandidateTemporalValidator().validate_candidates(
        comparison_set=comparison_set,
        candidate_scan_report=_scan_report((candidate,)),
        config=_config(min_segment_total=1, min_segment_positive=0, min_segment_negative=0),
    )

    assert report.status == "blocked"
    assert any("path_anchor_ts_ms_required_for_chronological_holdout" in item for item in report.blockers)


class _SpyRuleTester:
    def __init__(self):
        self.calls: list[str] = []
        self._delegate = AnalysisSuiteWhiteBoxRuleTester()

    def test_rule(self, *, rule_definition, comparison_set, diagnostic_report=None, sample_limit=None):
        self.calls.append(comparison_set.comparison_key)
        return self._delegate.test_rule(
            rule_definition=rule_definition,
            comparison_set=comparison_set,
            diagnostic_report=diagnostic_report,
            sample_limit=sample_limit,
        )


def test_segment_validation_reuses_injected_as10_rule_tester():
    comparison_set = _stable_comparison()
    candidate = _candidate(comparison_set)
    spy = _SpyRuleTester()

    report = AnalysisSuiteCandidateTemporalValidator(rule_tester=spy).validate_candidates(
        comparison_set=comparison_set,
        candidate_scan_report=_scan_report((candidate,)),
        config=_config(),
    )

    assert spy.calls == ["family_a_vs_family_b__discovery", "family_a_vs_family_b__validation"]
    assert report.candidate_results[0].validation_segment_report.rule_test_report.metrics.support == 1


def test_survival_status_survived_when_validation_metrics_hold():
    comparison_set = _stable_comparison()
    candidate = _candidate(comparison_set)

    report = AnalysisSuiteCandidateTemporalValidator().validate_candidates(
        comparison_set=comparison_set,
        candidate_scan_report=_scan_report((candidate,)),
        config=_config(),
    )

    result = report.candidate_results[0]
    assert result.survival_status == "survived"
    assert result.stability_score is not None
    assert 0.0 <= result.stability_score <= 1.0


def test_survival_status_degraded_when_precision_degrades():
    comparison_set = _comparison(
        (_path(1, 1_000, {"state": "match"}), _path(3, 3_000, {"state": "match"})),
        (_path(2, 2_000, {"state": "miss"}), _path(4, 4_000, {"state": "match"})),
    )
    candidate = _candidate(comparison_set)

    report = AnalysisSuiteCandidateTemporalValidator().validate_candidates(
        comparison_set=comparison_set,
        candidate_scan_report=_scan_report((candidate,)),
        config=_config(max_precision_degradation=0.25, max_lift_degradation=0.25),
    )

    result = report.candidate_results[0]
    assert result.survival_status == "degraded"
    assert result.degradation.precision_degradation_ratio == 0.5
    assert result.stability_score is not None
    assert result.stability_score < 1.0


def test_survival_status_failed_when_validation_support_below_minimum():
    comparison_set = _comparison(
        (_path(1, 1_000, {"state": "match"}), _path(3, 3_000, {"state": "miss"})),
        (_path(2, 2_000, {"state": "miss"}), _path(4, 4_000, {"state": "miss"})),
    )
    candidate = _candidate(comparison_set)

    report = AnalysisSuiteCandidateTemporalValidator().validate_candidates(
        comparison_set=comparison_set,
        candidate_scan_report=_scan_report((candidate,)),
        config=_config(min_validation_support=1, min_validation_positive_matches=0),
    )

    result = report.candidate_results[0]
    assert result.survival_status == "failed"
    assert any("validation_support_below_minimum" in item for item in result.blockers)


def test_survival_status_insufficient_data_when_segments_are_too_small():
    comparison_set = _stable_comparison()
    candidate = _candidate(comparison_set)

    report = AnalysisSuiteCandidateTemporalValidator().validate_candidates(
        comparison_set=comparison_set,
        candidate_scan_report=_scan_report((candidate,)),
        config=AnalysisSuiteTemporalValidationConfig(validation_fraction=0.5),
    )

    result = report.candidate_results[0]
    assert result.survival_status == "insufficient_data"
    assert result.stability_score is None
    assert any("segment_total_below_minimum" in warning for warning in result.warnings)


def test_metric_degradation_handles_zero_denominator_safely():
    comparison_set = _comparison(
        (_path(1, 1_000, {"state": "miss"}), _path(3, 3_000, {"state": "miss"})),
        (_path(2, 2_000, {"state": "miss"}), _path(4, 4_000, {"state": "miss"})),
    )
    candidate = _candidate(comparison_set)

    report = AnalysisSuiteCandidateTemporalValidator().validate_candidates(
        comparison_set=comparison_set,
        candidate_scan_report=_scan_report((candidate,)),
        config=_config(min_validation_support=0, min_validation_positive_matches=0),
    )

    degradation = report.candidate_results[0].degradation
    assert degradation.support_delta == 0
    assert degradation.support_degradation_ratio is None
    assert "support_degradation_ratio_unavailable" in degradation.warnings


def test_warning_propagation_and_sample_limited_reporting():
    comparison_set = _comparison(
        (_path(1, 1_000, {"state": "match"}), _path(3, 3_000, {"state": "match"})),
        (_path(2, 2_000, {"state": "miss"}), _path(4, 4_000, {"state": "miss"})),
        positive_metadata={"input_path_count": 20},
    )
    candidate = _candidate(comparison_set)

    report = AnalysisSuiteCandidateTemporalValidator().validate_candidates(
        comparison_set=comparison_set,
        candidate_scan_report=_scan_report((candidate,), sample_limited=True),
        config=_config(),
    )

    assert report.sample_limited is True
    assert "multiple_testing_correction_not_applied" in report.warnings
    assert "candidate_scan_report_sample_limited" in report.warnings
    assert "temporal_validation_inputs_are_sample_limited" in report.warnings
    assert "temporal_validation_does_not_apply_multiple_testing_correction" in report.warnings


def test_gating_blocks_or_warns_from_diagnostic_and_scan_reports():
    comparison_set = _stable_comparison()
    candidate = _candidate(comparison_set)

    blocked_diagnostic = AnalysisSuiteCandidateTemporalValidator().validate_candidates(
        comparison_set=comparison_set,
        candidate_scan_report=_scan_report((candidate,)),
        diagnostic_report=SimpleNamespace(status="blocked"),
        config=_config(),
    )
    assert blocked_diagnostic.status == "blocked"
    assert "diagnostic_report_not_acceptable: blocked" in blocked_diagnostic.blockers

    warning_diagnostic = AnalysisSuiteCandidateTemporalValidator().validate_candidates(
        comparison_set=comparison_set,
        candidate_scan_report=_scan_report((candidate,)),
        diagnostic_report=SimpleNamespace(status="warning"),
        config=_config(),
    )
    assert warning_diagnostic.status == "warning"
    assert "diagnostic_report_warning" in warning_diagnostic.warnings

    blocked_scan = AnalysisSuiteCandidateTemporalValidator().validate_candidates(
        comparison_set=comparison_set,
        candidate_scan_report=_scan_report((candidate,), status="blocked"),
        config=_config(),
    )
    assert blocked_scan.status == "blocked"
    assert "candidate_scan_report_not_acceptable: blocked" in blocked_scan.blockers

    empty_scan = AnalysisSuiteCandidateTemporalValidator().validate_candidates(
        comparison_set=comparison_set,
        candidate_scan_report=_scan_report(()),
        config=_config(),
    )
    assert empty_scan.status == "blocked"
    assert "candidate_scan_report_has_no_candidates" in empty_scan.blockers


def test_bounded_output_caps_candidates_and_preserves_counts():
    comparison_set = _stable_comparison()
    candidates = tuple(
        _candidate(comparison_set, rule=_rule(rule_key=f"candidate_rule_{index}"), candidate_key=f"candidate_{index}")
        for index in range(3)
    )

    report = AnalysisSuiteCandidateTemporalValidator().validate_candidates(
        comparison_set=comparison_set,
        candidate_scan_report=_scan_report(candidates),
        config=_config(max_candidates_validated=2),
    )

    assert report.candidate_count_input == 3
    assert report.candidate_count_validated == 2
    assert report.metadata["candidate_count_skipped_by_limit"] == 1
    assert "candidate_validation_limit_applied: 2" in report.warnings


def test_report_to_dict_is_json_safe():
    comparison_set = _stable_comparison()
    candidate = _candidate(comparison_set)

    report = AnalysisSuiteCandidateTemporalValidator().validate_candidates(
        comparison_set=comparison_set,
        candidate_scan_report=_scan_report((candidate,)),
        config=_config(max_candidates_validated=600),
    )

    payload = report.to_dict()
    assert payload["metadata"]["candidate_validation_limit"] == 500
    json.dumps(payload, sort_keys=True)


def test_boundary_source_has_no_forbidden_layer_dependencies():
    source = (
        __import__("pathlib")
        .Path("src/leonardo/data/historical/analysis_suite_candidate_temporal_validator.py")
        .read_text(encoding="utf-8")
    )
    forbidden_tokens = (
        "PySide",
        "QtWidgets",
        "QWidget",
        "QDialog",
        "QMainWindow",
        "AnalysisProject" + "Store",
        "AnalysisRun" + "Store",
        "AnalysisReport" + "Store",
        "read" + "_csv",
        "save" + "_manifest",
        "build" + "_database",
        "execute" + "_recipe",
        "Artifact" + "CalculationService",
    )

    for token in forbidden_tokens:
        assert token not in source
