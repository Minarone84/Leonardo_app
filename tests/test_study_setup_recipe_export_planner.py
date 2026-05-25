from __future__ import annotations

import json

from leonardo.data.chart_presets.study_setup_store import (
    CHART_STUDY_SETUP_OBJECT_TYPE,
    CHART_STUDY_SETUP_SCHEMA_VERSION,
    ChartStudySetup,
)
from leonardo.data.historical.study_setup_recipe_export_planner import (
    STUDY_EXPORT_STATUS_BLOCKED,
    STUDY_EXPORT_STATUS_CONDITIONAL,
    STUDY_EXPORT_STATUS_EXPORTABLE,
    STUDY_EXPORT_STATUS_SKIPPED,
    StudySetupRecipeExportPlanner,
)


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
        description="Saved study setup",
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
