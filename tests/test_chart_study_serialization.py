from __future__ import annotations

from dataclasses import fields
import json
from pathlib import Path

import pytest

from leonardo.gui.chart.studies import (
    ChartStudyInstance,
    ChartStudyRuntimeState,
    PANE_TARGET_PRICE,
    STUDY_DATASET_ROLE_UNSPECIFIED,
    STUDY_FAMILY_INDICATOR,
    STUDY_RUNTIME_ERROR,
    StudyComputationConfig,
    StudyDisplayStyle,
    StudyFillStyle,
    StudySignalStyle,
    StudyStyleModuleState,
    StudyUserMetadata,
    normalize_study_dataset_role,
)
from leonardo.gui.chart.study_serialization import (
    deserialize_chart_study_payload,
    serialize_chart_study,
    validate_serialized_chart_study,
)


REPO_ROOT = Path(__file__).resolve().parents[1]


def _source(relative_path: str) -> str:
    return (REPO_ROOT / relative_path).read_text(encoding="utf-8")


def _sample_study() -> ChartStudyInstance:
    return ChartStudyInstance(
        instance_id="runtime-instance-id",
        dataset_id="binance_spot_btcusdt_1h",
        pane_target=PANE_TARGET_PRICE,
        display_name="SMA 20",
        computation=StudyComputationConfig(
            family=STUDY_FAMILY_INDICATOR,
            tool_key="sma",
            params={"period": 20, "source_columns": ("close", "volume")},
            source_kind="temporary",
            input_bindings={"source": "close"},
            input_binding_meta={
                "source": {
                    "source_kind": "default",
                    "column_name": "close",
                }
            },
            required_inputs=("source",),
            saved_artifact_ref={"path": Path("data/historical/example.csv")},
        ),
        style=StudyDisplayStyle(
            color="#FFFFFF",
            line_width=2,
            line_style="solid",
            visible=True,
            show_label=True,
            show_value=False,
            signal_styles={
                "sma_20": StudySignalStyle(
                    color="#22C55E",
                    line_width=2,
                    show_value=False,
                )
            },
            fill_styles={
                "sma_fill": StudyFillStyle(
                    fill_id="sma_fill",
                    signal_a="close",
                    signal_b="sma_20",
                    color="#22C55E",
                    opacity=0.2,
                    visible=False,
                )
            },
            style_modules=[
                StudyStyleModuleState(
                    module_key="conditional_line_color",
                    enabled=True,
                    config={"levels": {1, 2}},
                )
            ],
        ),
        runtime=ChartStudyRuntimeState(
            last_value=123.45,
            selected=True,
            status=STUDY_RUNTIME_ERROR,
            error_text="runtime-only",
            render_keys=["runtime|render|sma_20"],
        ),
        user_metadata=StudyUserMetadata(
            important=True,
            description="Main short-term trend study.",
            dataset_role="supporting_indicator",
        ),
    )


def test_study_computation_config_exposes_durable_binding_fields() -> None:
    field_names = {field.name for field in fields(StudyComputationConfig)}

    assert "input_bindings" in field_names
    assert "input_binding_meta" in field_names
    assert "required_inputs" in field_names
    assert "saved_artifact_ref" in field_names


def test_study_user_metadata_defaults_and_role_normalization() -> None:
    metadata = StudyUserMetadata()

    assert metadata.important is False
    assert metadata.description == ""
    assert metadata.dataset_role == STUDY_DATASET_ROLE_UNSPECIFIED
    assert normalize_study_dataset_role("UTC") == "utc"
    assert normalize_study_dataset_role("not-a-role") == STUDY_DATASET_ROLE_UNSPECIFIED
    assert StudyUserMetadata(important="false", dataset_role="visual only").important is False
    assert StudyUserMetadata(important="true", dataset_role="visual only").dataset_role == "visual_only"


def test_chart_study_instance_has_default_user_metadata() -> None:
    study = ChartStudyInstance(
        instance_id="study_1",
        dataset_id="binance_spot_btcusdt_1h",
        pane_target=PANE_TARGET_PRICE,
        display_name="SMA 20",
        computation=StudyComputationConfig(
            family=STUDY_FAMILY_INDICATOR,
            tool_key="sma",
        ),
    )

    assert study.user_metadata == StudyUserMetadata()


def test_chart_apply_registration_preserves_payload_binding_fields() -> None:
    study_apply_source = _source(
        "src/leonardo/gui/windows/_historical_chart_panel/historical_chart_panel_study_apply.py"
    )
    projection_source = _source("src/leonardo/gui/historical_chart/projection.py")
    tool_execution_source = _source("src/leonardo/gui/historical_chart/tool_execution.py")

    assert "input_bindings=dict(input_bindings or {})" in study_apply_source
    assert "input_binding_meta=dict(input_binding_meta or {})" in study_apply_source
    assert "required_inputs=tuple(required_inputs or ())" in study_apply_source
    assert "saved_artifact_ref=dict(saved_artifact_ref)" in study_apply_source
    assert "source_kind=source_kind" in study_apply_source

    assert 'source_payload.get("input_bindings"' in projection_source
    assert '"input_bindings": input_bindings' in projection_source
    assert '"input_binding_meta": input_binding_meta' in projection_source
    assert '"required_inputs": required_inputs' in projection_source
    assert '"source_kind": source_kind' in projection_source

    assert "source_payload=payload" in tool_execution_source


def test_serialize_chart_study_excludes_runtime_only_fields() -> None:
    payload = serialize_chart_study(_sample_study())
    payload_text = json.dumps(payload)

    assert "runtime" not in payload
    assert "instance_id" not in payload
    assert "dataset_id" not in payload
    assert "render_keys" not in payload_text
    assert "runtime|render|sma_20" not in payload_text
    assert "last_value" not in payload_text
    assert "selected" not in payload_text
    assert "error_text" not in payload_text


def test_serialize_chart_study_includes_durable_intent_style_and_bindings() -> None:
    payload = serialize_chart_study(_sample_study())

    assert payload["family"] == "indicator"
    assert payload["tool_key"] == "sma"
    assert payload["display_name"] == "SMA 20"
    assert payload["pane_target"] == PANE_TARGET_PRICE
    assert payload["params"] == {"period": 20, "source_columns": ["close", "volume"]}
    assert payload["source_kind"] == "temporary"
    assert payload["input_bindings"] == {"source": "close"}
    assert payload["input_binding_meta"]["source"]["source_kind"] == "default"
    assert payload["required_inputs"] == ["source"]
    assert payload["saved_artifact_ref"] == {"path": "data/historical/example.csv"}

    style = payload["style"]
    assert style["signal_styles"]["sma_20"]["color"] == "#22C55E"
    assert style["fill_styles"]["sma_fill"]["signal_b"] == "sma_20"
    assert style["style_modules"][0]["module_key"] == "conditional_line_color"
    assert style["style_modules"][0]["config"]["levels"] == [1, 2]

    assert payload["user_metadata"] == {
        "important": True,
        "description": "Main short-term trend study.",
        "dataset_role": "supporting_indicator",
    }


def test_serialized_chart_study_is_json_safe() -> None:
    payload = serialize_chart_study(_sample_study())

    json.dumps(payload)


def test_deserialize_chart_study_payload_validates_required_shape() -> None:
    bad_payload = {
        "schema_version": 1,
        "params": [],
        "style": {"signal_styles": []},
    }

    errors = validate_serialized_chart_study(bad_payload)
    assert "family is required." in errors
    assert "tool_key is required." in errors
    assert "params must be a mapping." in errors
    assert "style.signal_styles must be a mapping." in errors

    with pytest.raises(ValueError, match="Invalid serialized chart study"):
        deserialize_chart_study_payload(bad_payload)


def test_deserialize_chart_study_payload_normalizes_json_safe_structure() -> None:
    payload = serialize_chart_study(_sample_study())

    errors = validate_serialized_chart_study(payload)
    assert errors == []

    normalized = deserialize_chart_study_payload(payload)

    assert normalized["schema_version"] == 1
    assert normalized["family"] == "indicator"
    assert normalized["tool_key"] == "sma"
    assert normalized["required_inputs"] == ["source"]
    assert normalized["style"]["signal_styles"]["sma_20"]["color"] == "#22C55E"
    assert normalized["user_metadata"] == {
        "important": True,
        "description": "Main short-term trend study.",
        "dataset_role": "supporting_indicator",
    }
    json.dumps(normalized)


def test_deserialize_chart_study_payload_defaults_missing_user_metadata() -> None:
    payload = serialize_chart_study(_sample_study())
    payload.pop("user_metadata")

    normalized = deserialize_chart_study_payload(payload)

    assert normalized["user_metadata"] == {
        "important": False,
        "description": "",
        "dataset_role": STUDY_DATASET_ROLE_UNSPECIFIED,
    }


def test_deserialize_chart_study_payload_normalizes_partial_user_metadata() -> None:
    payload = serialize_chart_study(_sample_study())
    payload["user_metadata"] = {
        "important": "false",
        "dataset_role": "unknown-role",
    }

    normalized = deserialize_chart_study_payload(payload)

    assert normalized["user_metadata"] == {
        "important": False,
        "description": "",
        "dataset_role": STUDY_DATASET_ROLE_UNSPECIFIED,
    }


def test_user_metadata_does_not_change_computation_or_style_payload() -> None:
    study = _sample_study()
    changed = study.with_user_metadata(
        StudyUserMetadata(
            important=False,
            description="Different semantic note.",
            dataset_role="experimental",
        )
    )

    original_payload = serialize_chart_study(study)
    changed_payload = serialize_chart_study(changed)

    assert changed_payload["params"] == original_payload["params"]
    assert changed_payload["input_bindings"] == original_payload["input_bindings"]
    assert changed_payload["style"] == original_payload["style"]
    assert changed_payload["user_metadata"]["dataset_role"] == "experimental"
