from __future__ import annotations

import json
from dataclasses import replace

from leonardo.data.chart_presets.study_setup_store import (
    CHART_STUDY_SETUP_OBJECT_TYPE,
    CHART_STUDY_SETUP_SCHEMA_VERSION,
    ChartStudySetup,
)
from leonardo.data.historical.artifact_recipe_collection_store import (
    ArtifactRecipeCollectionStore,
)
from leonardo.data.historical.artifact_recipe_store import ArtifactRecipeStore
from leonardo.data.historical.study_setup_recipe_export_planner import (
    STUDY_EXPORT_SAVE_STATUS_BLOCKED,
    STUDY_EXPORT_SAVE_STATUS_FAILED,
    STUDY_EXPORT_SAVE_STATUS_SAVED,
    STUDY_EXPORT_SAVE_STATUS_SKIPPED,
    STUDY_EXPORT_STATUS_BLOCKED,
    STUDY_EXPORT_STATUS_CONDITIONAL,
    STUDY_EXPORT_STATUS_EXPORTABLE,
    STUDY_EXPORT_STATUS_SKIPPED,
    StudyRecipeCollectionDraft,
    StudySetupRecipeExportPersistenceService,
    StudySetupRecipeExportPlanner,
)
from leonardo.data.naming import canonicalize


def _study_payload(
    *,
    family: str = "indicator",
    tool_key: str = "ema",
    display_name: str = "EMA 20",
    params: dict[str, object] | None = None,
    important: bool = True,
    dataset_role: str = "supporting_indicator",
    description: str = "Main trend study.",
    source_kind: str = "temporary",
    input_bindings: dict[str, object] | None = None,
    input_binding_meta: dict[str, object] | None = None,
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "family": family,
        "tool_key": tool_key,
        "display_name": display_name,
        "pane_target": "price",
        "params": dict(params or {"period": 20}),
        "source_kind": source_kind,
        "input_bindings": dict(input_bindings or {"source": "close"}),
        "input_binding_meta": dict(
            input_binding_meta
            or {"source": {"source_kind": "default", "family": "default", "column_name": "close"}}
        ),
        "required_inputs": ["source"],
        "saved_artifact_ref": None,
        "user_metadata": {
            "important": important,
            "description": description,
            "dataset_role": dataset_role,
        },
        "style": {
            "color": "#22C55E",
            "signal_styles": {},
            "fill_styles": {},
            "style_modules": [],
        },
        "runtime": {"render_key": "chart-only"},
    }


def _setup(
    *,
    studies: list[dict[str, object]] | None = None,
    created_from: dict[str, object] | None = None,
) -> ChartStudySetup:
    return ChartStudySetup(
        schema_version=CHART_STUDY_SETUP_SCHEMA_VERSION,
        object_type=CHART_STUDY_SETUP_OBJECT_TYPE,
        setup_id="setup_export",
        content_hash="",
        display_name="Export Setup",
        description="Saved study environment",
        created_at_ms=1000,
        updated_at_ms=1000,
        created_from=created_from
        if created_from is not None
        else {
            "exchange": "bybit",
            "market_type": "linear",
            "symbol": "BTCUSDT",
            "timeframe": "1h",
        },
        studies=tuple(studies or [_study_payload()]),
    )


def _market():
    return canonicalize("bybit", "linear", "BTCUSDT", "1h")


def test_direct_ohlcv_study_plans_exportable_recipe_payload(tmp_path) -> None:
    planner = StudySetupRecipeExportPlanner(historical_root=tmp_path)

    plan = planner.plan_study_setup_export(_setup())

    assert plan.summary[STUDY_EXPORT_STATUS_EXPORTABLE] == 1
    candidate = plan.candidates[0]
    assert candidate.status == STUDY_EXPORT_STATUS_EXPORTABLE
    assert candidate.recipe_payload is not None
    assert candidate.recipe_payload["tool_type"] == "indicator"
    assert candidate.recipe_payload["tool_key"] == "ema"
    assert candidate.recipe_payload["params"] == {"period": 20}
    assert candidate.recipe_payload["required_inputs"] == ["close"]
    assert candidate.recipe_payload["output_names"] == ["ema_20"]
    assert candidate.recipe_payload["input_bindings"] == {}
    assert candidate.recipe_payload["input_binding_meta"] == {}


def test_important_only_skips_non_important_studies(tmp_path) -> None:
    setup = _setup(
        studies=[
            _study_payload(tool_key="ema", display_name="EMA 20", important=False),
            _study_payload(
                family="oscillator",
                tool_key="rsi",
                display_name="RSI 14",
                params={"period": 14},
                important=True,
            ),
        ]
    )
    planner = StudySetupRecipeExportPlanner(historical_root=tmp_path)

    plan = planner.plan_study_setup_export(setup, important_only=True)

    assert [candidate.status for candidate in plan.candidates] == [
        STUDY_EXPORT_STATUS_SKIPPED,
        STUDY_EXPORT_STATUS_EXPORTABLE,
    ]
    assert plan.candidates[0].reasons == ("not_marked_important",)
    assert plan.collection_draft is not None
    assert [payload["tool_key"] for payload in plan.collection_draft.recipe_payloads] == [
        "rsi"
    ]


def test_metadata_is_reported_without_entering_recipe_payload(tmp_path) -> None:
    setup = _setup(
        studies=[
            _study_payload(
                description="Use this as a future core indicator.",
                dataset_role="core_geography",
            )
        ]
    )
    planner = StudySetupRecipeExportPlanner(historical_root=tmp_path)

    candidate = planner.plan_study_setup_export(setup).candidates[0]

    assert candidate.description == "Use this as a future core indicator."
    assert candidate.dataset_role == "core_geography"
    assert candidate.metadata["source_study_user_metadata"] == {
        "important": True,
        "description": "Use this as a future core indicator.",
        "dataset_role": "core_geography",
    }
    assert candidate.recipe_payload is not None
    assert "user_metadata" not in candidate.recipe_payload
    assert "description" not in candidate.recipe_payload
    assert "dataset_role" not in candidate.recipe_payload


def test_old_study_payload_without_user_metadata_uses_defaults(tmp_path) -> None:
    study = _study_payload()
    study.pop("user_metadata")
    planner = StudySetupRecipeExportPlanner(historical_root=tmp_path)

    candidate = planner.plan_study_setup_export(_setup(studies=[study])).candidates[0]

    assert candidate.status == STUDY_EXPORT_STATUS_EXPORTABLE
    assert candidate.important is False
    assert candidate.description == ""
    assert candidate.dataset_role == "unspecified"


def test_style_runtime_and_pane_target_do_not_leak_into_recipe_payload(tmp_path) -> None:
    planner = StudySetupRecipeExportPlanner(historical_root=tmp_path)

    candidate = planner.plan_study_setup_export(_setup()).candidates[0]

    assert candidate.recipe_payload is not None
    assert "style" not in candidate.recipe_payload
    assert "runtime" not in candidate.recipe_payload
    assert "pane_target" not in candidate.recipe_payload
    assert "render_key" not in json.dumps(candidate.recipe_payload)


def test_missing_market_identity_blocks_recipe_payload(tmp_path) -> None:
    planner = StudySetupRecipeExportPlanner(historical_root=tmp_path)

    plan = planner.plan_study_setup_export(_setup(created_from={}))

    assert plan.source_market is None
    assert plan.summary[STUDY_EXPORT_STATUS_BLOCKED] == 1
    assert plan.candidates[0].recipe_payload is None
    assert "missing_market_identity" in plan.candidates[0].reasons
    assert any(blocker.reason == "missing_market_identity" for blocker in plan.blockers)


def test_target_market_allows_incomplete_setup_created_from(tmp_path) -> None:
    planner = StudySetupRecipeExportPlanner(historical_root=tmp_path)

    plan = planner.plan_study_setup_export(
        _setup(created_from={}),
        target_market={
            "exchange": "bybit",
            "market_type": "linear",
            "symbol": "BTC/USDT",
            "timeframe": "60",
        },
    )

    assert plan.source_market == {
        "exchange": "bybit",
        "market_type": "linear",
        "symbol": "BTCUSDT",
        "timeframe": "60m",
    }
    assert plan.candidates[0].status == STUDY_EXPORT_STATUS_EXPORTABLE


def test_construct_temporary_source_is_blocked(tmp_path) -> None:
    setup = _setup(
        studies=[
            _study_payload(
                family="construct",
                tool_key="derivative",
                display_name="Derivative",
                params={"order": 1},
                input_bindings={"source": "ema_20"},
                input_binding_meta={
                    "source": {
                        "source_kind": "temporary",
                        "family": "indicator",
                        "tool_key": "ema",
                        "column_name": "ema_20",
                    }
                },
            )
        ]
    )
    planner = StudySetupRecipeExportPlanner(historical_root=tmp_path)

    candidate = planner.plan_study_setup_export(setup).candidates[0]

    assert candidate.status == STUDY_EXPORT_STATUS_BLOCKED
    assert candidate.reasons == ("temporary_source_not_exportable",)
    assert candidate.recipe_payload is None


def test_missing_tool_spec_is_blocked(tmp_path) -> None:
    setup = _setup(
        studies=[
            _study_payload(
                family="indicator",
                tool_key="missing_tool",
                display_name="Missing Tool",
            )
        ]
    )
    planner = StudySetupRecipeExportPlanner(historical_root=tmp_path)

    candidate = planner.plan_study_setup_export(setup).candidates[0]

    assert candidate.status == STUDY_EXPORT_STATUS_BLOCKED
    assert candidate.reasons == ("missing_tool_spec",)


def test_utc_dependency_is_reported_as_conditional(tmp_path) -> None:
    setup = _setup(
        studies=[
            _study_payload(
                family="indicator",
                tool_key="peaks_troughs",
                display_name="Peaks & Troughs",
                params={},
                important=False,
                dataset_role="peaks_troughs",
            ),
            _study_payload(
                family="indicator",
                tool_key="universal_trend_classifier",
                display_name="UTC",
                params={},
                important=True,
                dataset_role="utc",
            ),
        ]
    )
    planner = StudySetupRecipeExportPlanner(historical_root=tmp_path)

    plan = planner.plan_study_setup_export(setup, important_only=True)

    assert plan.candidates[0].status == STUDY_EXPORT_STATUS_SKIPPED
    utc_candidate = plan.candidates[1]
    assert utc_candidate.status == STUDY_EXPORT_STATUS_CONDITIONAL
    assert utc_candidate.reasons == ("required_dependency_not_selected",)
    assert "Peaks & Troughs" in utc_candidate.dependency_notes[0]


def test_collection_draft_preserves_exportable_study_order(tmp_path) -> None:
    setup = _setup(
        studies=[
            _study_payload(
                family="oscillator",
                tool_key="rsi",
                display_name="RSI 14",
                params={"period": 14},
            ),
            _study_payload(
                family="indicator",
                tool_key="ema",
                display_name="EMA 20",
                params={"period": 20},
            ),
        ]
    )
    planner = StudySetupRecipeExportPlanner(historical_root=tmp_path)

    plan = planner.plan_study_setup_export(setup)

    assert plan.collection_draft is not None
    assert [payload["tool_key"] for payload in plan.collection_draft.recipe_payloads] == [
        "rsi",
        "ema",
    ]


def test_plan_to_dict_is_json_safe(tmp_path) -> None:
    planner = StudySetupRecipeExportPlanner(historical_root=tmp_path)

    plan_dict = planner.plan_study_setup_export(_setup()).to_dict()

    encoded = json.dumps(plan_dict, sort_keys=True)
    assert "Export Setup" in encoded


def test_persistence_saves_all_exportable_candidates_by_default(tmp_path) -> None:
    setup = _setup(
        studies=[
            _study_payload(tool_key="ema", params={"period": 20}),
            _study_payload(
                family="oscillator",
                tool_key="rsi",
                display_name="RSI 14",
                params={"period": 14},
            ),
        ]
    )
    planner = StudySetupRecipeExportPlanner(historical_root=tmp_path)
    persister = StudySetupRecipeExportPersistenceService(historical_root=tmp_path)

    report = persister.persist_export_plan(planner.plan_study_setup_export(setup))

    assert report.summary[STUDY_EXPORT_SAVE_STATUS_SAVED] == 2
    assert len(report.saved_recipe_ids) == 2
    summaries = ArtifactRecipeStore(historical_root=tmp_path).list_recipes(
        market=_market()
    )
    assert {summary.recipe_id for summary in summaries} == set(report.saved_recipe_ids)
    assert report.saved_collection_id is None


def test_persistence_saves_selected_candidates_only(tmp_path) -> None:
    setup = _setup(
        studies=[
            _study_payload(tool_key="ema", params={"period": 20}),
            _study_payload(
                family="oscillator",
                tool_key="rsi",
                display_name="RSI 14",
                params={"period": 14},
            ),
        ]
    )
    plan = StudySetupRecipeExportPlanner(historical_root=tmp_path).plan_study_setup_export(
        setup
    )
    selected_candidate_id = plan.candidates[1].candidate_id
    persister = StudySetupRecipeExportPersistenceService(historical_root=tmp_path)

    report = persister.persist_export_plan(
        plan,
        selected_candidate_ids=(selected_candidate_id,),
    )

    assert report.requested_candidate_ids == (selected_candidate_id,)
    assert len(report.saved_recipe_ids) == 1
    recipe = ArtifactRecipeStore(historical_root=tmp_path).load_recipe(
        market=_market(),
        recipe_id=report.saved_recipe_ids[0],
    )
    assert recipe.tool_key == "rsi"


def test_persistence_reports_unknown_selected_candidate_id(tmp_path) -> None:
    plan = StudySetupRecipeExportPlanner(historical_root=tmp_path).plan_study_setup_export(
        _setup()
    )
    persister = StudySetupRecipeExportPersistenceService(historical_root=tmp_path)

    report = persister.persist_export_plan(
        plan,
        selected_candidate_ids=("missing_candidate",),
    )

    assert report.saved_recipe_ids == ()
    assert report.skipped_candidate_ids == ()
    assert report.summary[STUDY_EXPORT_SAVE_STATUS_BLOCKED] == 1
    assert report.results[0].status == STUDY_EXPORT_SAVE_STATUS_BLOCKED
    assert report.blockers[0].reason == "unknown_candidate_id"


def test_persistence_does_not_save_blocked_conditional_or_skipped_candidates(
    tmp_path,
) -> None:
    setup = _setup(
        studies=[
            _study_payload(tool_key="ema", important=False),
            _study_payload(
                family="indicator",
                tool_key="universal_trend_classifier",
                display_name="UTC",
                params={},
                important=True,
                dataset_role="utc",
            ),
            _study_payload(
                family="indicator",
                tool_key="missing_tool",
                display_name="Missing Tool",
                important=True,
            ),
        ]
    )
    plan = StudySetupRecipeExportPlanner(historical_root=tmp_path).plan_study_setup_export(
        setup,
        important_only=True,
    )
    persister = StudySetupRecipeExportPersistenceService(historical_root=tmp_path)

    report = persister.persist_export_plan(
        plan,
        selected_candidate_ids=tuple(candidate.candidate_id for candidate in plan.candidates),
    )

    assert report.saved_recipe_ids == ()
    assert [result.status for result in report.results] == [
        STUDY_EXPORT_SAVE_STATUS_SKIPPED,
        STUDY_EXPORT_SAVE_STATUS_BLOCKED,
        STUDY_EXPORT_SAVE_STATUS_BLOCKED,
    ]
    assert {blocker.reason for blocker in report.blockers} == {
        "candidate_skipped",
        "conditional_not_persisted",
        "candidate_not_exportable",
    }


def test_persistence_blocks_missing_recipe_payload(tmp_path) -> None:
    plan = StudySetupRecipeExportPlanner(historical_root=tmp_path).plan_study_setup_export(
        _setup()
    )
    candidate = replace(plan.candidates[0], recipe_payload=None)
    plan = replace(plan, candidates=(candidate,), collection_draft=None)
    persister = StudySetupRecipeExportPersistenceService(historical_root=tmp_path)

    report = persister.persist_export_plan(
        plan,
        selected_candidate_ids=(candidate.candidate_id,),
    )

    assert report.saved_recipe_ids == ()
    assert report.results[0].status == STUDY_EXPORT_SAVE_STATUS_BLOCKED
    assert report.blockers[0].reason == "missing_recipe_payload"


def test_persistence_continues_after_recipe_save_failure(tmp_path) -> None:
    setup = _setup(
        studies=[
            _study_payload(tool_key="ema", params={"period": 20}),
            _study_payload(tool_key="ema", display_name="EMA 30", params={"period": 30}),
        ]
    )
    plan = StudySetupRecipeExportPlanner(historical_root=tmp_path).plan_study_setup_export(
        setup
    )
    assert plan.candidates[0].recipe_payload is not None
    ArtifactRecipeStore(historical_root=tmp_path).save_recipe(
        plan.candidates[0].recipe_payload
    )
    persister = StudySetupRecipeExportPersistenceService(historical_root=tmp_path)

    report = persister.persist_export_plan(
        plan,
        overwrite_recipes=False,
    )

    assert len(report.saved_recipe_ids) == 1
    assert len(report.failed_candidate_ids) == 1
    assert {result.status for result in report.results} == {
        STUDY_EXPORT_SAVE_STATUS_SAVED,
        STUDY_EXPORT_SAVE_STATUS_FAILED,
    }


def test_persistence_can_save_collection_with_study_order(tmp_path) -> None:
    setup = _setup(
        studies=[
            _study_payload(
                family="oscillator",
                tool_key="rsi",
                display_name="RSI 14",
                params={"period": 14},
            ),
            _study_payload(tool_key="ema", params={"period": 20}),
        ]
    )
    plan = StudySetupRecipeExportPlanner(historical_root=tmp_path).plan_study_setup_export(
        setup
    )
    persister = StudySetupRecipeExportPersistenceService(historical_root=tmp_path)

    report = persister.persist_export_plan(plan, save_collection=True)

    assert report.saved_collection_id is not None
    collection = ArtifactRecipeCollectionStore(historical_root=tmp_path).load_collection(
        market=_market(),
        collection_id=report.saved_collection_id,
    )
    assert [recipe.tool_key for recipe in collection.recipe_snapshots] == ["rsi", "ema"]
    assert collection.metadata["source_plan_id"] == plan.plan_id


def test_persistence_save_collection_false_saves_recipes_only(tmp_path) -> None:
    plan = StudySetupRecipeExportPlanner(historical_root=tmp_path).plan_study_setup_export(
        _setup()
    )
    persister = StudySetupRecipeExportPersistenceService(historical_root=tmp_path)

    report = persister.persist_export_plan(plan, save_collection=False)

    assert len(report.saved_recipe_ids) == 1
    assert report.saved_collection_id is None
    assert ArtifactRecipeCollectionStore(historical_root=tmp_path).list_collections(
        market=_market()
    ) == []


def test_persistence_save_collection_requires_saved_recipes(tmp_path) -> None:
    setup = _setup(
        studies=[
            _study_payload(
                family="indicator",
                tool_key="universal_trend_classifier",
                display_name="UTC",
                params={},
                dataset_role="utc",
            )
        ]
    )
    plan = StudySetupRecipeExportPlanner(historical_root=tmp_path).plan_study_setup_export(
        setup
    )
    persister = StudySetupRecipeExportPersistenceService(historical_root=tmp_path)

    report = persister.persist_export_plan(plan, save_collection=True)

    assert report.saved_recipe_ids == ()
    assert report.saved_collection_id is None
    assert report.blockers[0].reason == "no_saved_recipes_for_collection"


def test_persistence_collection_uses_only_successfully_saved_selected_candidates(
    tmp_path,
) -> None:
    setup = _setup(
        studies=[
            _study_payload(tool_key="ema", params={"period": 20}),
            _study_payload(tool_key="ema", display_name="EMA 30", params={"period": 30}),
            _study_payload(
                family="indicator",
                tool_key="missing_tool",
                display_name="Missing Tool",
            ),
        ]
    )
    plan = StudySetupRecipeExportPlanner(historical_root=tmp_path).plan_study_setup_export(
        setup
    )
    assert plan.candidates[0].recipe_payload is not None
    ArtifactRecipeStore(historical_root=tmp_path).save_recipe(
        plan.candidates[0].recipe_payload
    )
    persister = StudySetupRecipeExportPersistenceService(historical_root=tmp_path)

    report = persister.persist_export_plan(
        plan,
        selected_candidate_ids=(
            plan.candidates[0].candidate_id,
            plan.candidates[1].candidate_id,
            plan.candidates[2].candidate_id,
        ),
        save_collection=True,
        overwrite_recipes=False,
    )

    assert len(report.saved_recipe_ids) == 1
    assert len(report.failed_candidate_ids) == 1
    assert report.saved_collection_id is not None
    collection = ArtifactRecipeCollectionStore(historical_root=tmp_path).load_collection(
        market=_market(),
        collection_id=report.saved_collection_id,
    )
    assert [recipe.output_names for recipe in collection.recipe_snapshots] == [
        ("ema_30",)
    ]


def test_persistence_collection_drops_edges_for_excluded_recipes(tmp_path) -> None:
    setup = _setup(
        studies=[
            _study_payload(tool_key="ema", params={"period": 20}),
            _study_payload(tool_key="ema", display_name="EMA 30", params={"period": 30}),
        ]
    )
    plan = StudySetupRecipeExportPlanner(historical_root=tmp_path).plan_study_setup_export(
        setup
    )
    assert plan.collection_draft is not None
    source_recipe_id = plan.candidates[0].metadata["recipe_id"]
    draft = StudyRecipeCollectionDraft(
        display_name=plan.collection_draft.display_name,
        source_market=plan.collection_draft.source_market,
        recipe_payloads=plan.collection_draft.recipe_payloads,
        dependency_edges=(
            {
                "from_recipe_id": source_recipe_id,
                "to_recipe_id": "ar__indicator__missing__h00000000",
                "reason": "missing downstream recipe",
            },
        ),
        warnings=plan.collection_draft.warnings,
        metadata=plan.collection_draft.metadata,
    )
    plan = replace(plan, collection_draft=draft)
    persister = StudySetupRecipeExportPersistenceService(historical_root=tmp_path)

    report = persister.persist_export_plan(plan, save_collection=True)

    assert "dropped_dependency_edge_for_excluded_recipe" in report.warnings
    assert report.saved_collection_id is not None
    collection = ArtifactRecipeCollectionStore(historical_root=tmp_path).load_collection(
        market=_market(),
        collection_id=report.saved_collection_id,
    )
    assert collection.dependency_edges == ()


def test_persistence_passes_collection_overwrite_flag(tmp_path) -> None:
    plan = StudySetupRecipeExportPlanner(historical_root=tmp_path).plan_study_setup_export(
        _setup()
    )
    persister = StudySetupRecipeExportPersistenceService(historical_root=tmp_path)

    first_report = persister.persist_export_plan(
        plan,
        save_collection=True,
        overwrite_recipes=True,
        overwrite_collection=True,
    )
    second_report = persister.persist_export_plan(
        plan,
        save_collection=True,
        overwrite_recipes=True,
        overwrite_collection=False,
    )

    assert first_report.saved_collection_id is not None
    assert second_report.saved_collection_id is None
    assert any(
        blocker.reason == "collection_save_failed"
        for blocker in second_report.blockers
    )


def test_persistence_report_to_dict_is_json_safe(tmp_path) -> None:
    plan = StudySetupRecipeExportPlanner(historical_root=tmp_path).plan_study_setup_export(
        _setup()
    )
    persister = StudySetupRecipeExportPersistenceService(historical_root=tmp_path)

    report_dict = persister.persist_export_plan(plan).to_dict()

    encoded = json.dumps(report_dict, sort_keys=True)
    assert "study_recipe_export_persistence" in encoded
