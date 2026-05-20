from __future__ import annotations

from dataclasses import fields
import json
from pathlib import Path

import pytest

from leonardo.gui.chart.studies import (
    ChartStudyInstance,
    ChartStudyRuntimeState,
    PANE_TARGET_PRICE,
    STUDY_FAMILY_INDICATOR,
    STUDY_RUNTIME_ERROR,
    StudyComputationConfig,
    StudyDisplayStyle,
    StudyFillStyle,
    StudySignalStyle,
    StudyStyleModuleState,
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
    )


def test_study_computation_config_exposes_durable_binding_fields() -> None:
    field_names = {field.name for field in fields(StudyComputationConfig)}

    assert "input_bindings" in field_names
    assert "input_binding_meta" in field_names
    assert "required_inputs" in field_names
    assert "saved_artifact_ref" in field_names


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
    json.dumps(normalized)
