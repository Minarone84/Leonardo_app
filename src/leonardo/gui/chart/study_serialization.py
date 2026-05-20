from __future__ import annotations

from dataclasses import asdict, is_dataclass
import math
from pathlib import Path
from collections.abc import Mapping
from typing import Any

from leonardo.gui.chart.studies import (
    ChartStudyInstance,
    StudyDisplayStyle,
    StudyFillStyle,
    StudySignalStyle,
    StudyStyleModuleState,
)


CHART_STUDY_SERIALIZATION_SCHEMA_VERSION = 1


def serialize_chart_study(study: ChartStudyInstance) -> dict[str, Any]:
    """Return durable, JSON-safe chart-study intent and style data.

    The serialized payload intentionally excludes runtime projection state such
    as render keys, last values, selection state, error text, and computed
    resident-local values. Future restore code must recompute studies through
    the normal chart/controller apply path and then apply serialized
    chart-local styles.
    """

    computation = study.computation
    return {
        "schema_version": CHART_STUDY_SERIALIZATION_SCHEMA_VERSION,
        "family": str(computation.family).strip().lower(),
        "tool_key": str(computation.tool_key).strip().lower(),
        "display_name": str(study.display_name).strip(),
        "pane_target": study.pane_target,
        "params": _json_safe(computation.params),
        "source_kind": str(computation.source_kind).strip().lower(),
        "input_bindings": _json_safe(computation.input_bindings),
        "input_binding_meta": _json_safe(computation.input_binding_meta),
        "required_inputs": _json_safe(list(computation.required_inputs)),
        "saved_artifact_ref": (
            _json_safe(computation.saved_artifact_ref)
            if computation.saved_artifact_ref is not None
            else None
        ),
        "style": serialize_study_style(study.style),
    }


def serialize_study_style(style: StudyDisplayStyle) -> dict[str, Any]:
    """Return JSON-safe chart-local style state for one study."""

    return {
        "color": _json_safe(style.color),
        "line_width": _json_safe(style.line_width),
        "line_style": _json_safe(style.line_style),
        "visible": _json_safe(style.visible),
        "show_label": _json_safe(style.show_label),
        "show_value": _json_safe(style.show_value),
        "signal_styles": {
            str(signal_name): _json_safe(asdict(signal_style))
            for signal_name, signal_style in style.signal_styles.items()
        },
        "fill_styles": {
            str(fill_id): _json_safe(asdict(fill_style))
            for fill_id, fill_style in style.fill_styles.items()
        },
        "style_modules": [
            _json_safe(asdict(module_state))
            for module_state in style.style_modules
        ],
    }


def deserialize_study_style_payload(payload: Mapping[str, Any]) -> StudyDisplayStyle:
    """Normalize serialized style data into a StudyDisplayStyle instance."""

    data = _mapping_or_empty(payload)
    signal_styles: dict[str, StudySignalStyle] = {}
    for signal_name, raw_style in _mapping_or_empty(data.get("signal_styles")).items():
        signal_key = str(signal_name).strip()
        if signal_key and isinstance(raw_style, Mapping):
            signal_styles[signal_key] = _deserialize_signal_style(raw_style)

    fill_styles: dict[str, StudyFillStyle] = {}
    for fill_id, raw_style in _mapping_or_empty(data.get("fill_styles")).items():
        fill_key = str(fill_id).strip()
        if fill_key and isinstance(raw_style, Mapping):
            fill_styles[fill_key] = _deserialize_fill_style(fill_key, raw_style)

    style_modules: list[StudyStyleModuleState] = []
    raw_modules = data.get("style_modules", []) or []
    if isinstance(raw_modules, (list, tuple)):
        for raw_module in raw_modules:
            if not isinstance(raw_module, Mapping):
                continue
            module_key = str(raw_module.get("module_key", "") or "").strip()
            if not module_key:
                continue
            style_modules.append(
                StudyStyleModuleState(
                    module_key=module_key,
                    enabled=_bool_value(raw_module.get("enabled"), True),
                    config=_mapping_or_empty(raw_module.get("config")),
                )
            )

    return StudyDisplayStyle(
        color=str(data.get("color", "") or ""),
        line_width=_int_value(data.get("line_width"), 1),
        line_style=str(data.get("line_style", "solid") or "solid"),
        visible=_bool_value(data.get("visible"), True),
        show_label=_bool_value(data.get("show_label"), True),
        show_value=_bool_value(data.get("show_value"), True),
        signal_styles=signal_styles,
        fill_styles=fill_styles,
        style_modules=style_modules,
    )


def validate_serialized_chart_study(payload: Mapping[str, Any]) -> list[str]:
    """Return structural validation errors for a serialized chart study."""

    errors: list[str] = []
    if not isinstance(payload, Mapping):
        return ["payload must be a mapping."]

    schema_version = _int_value(
        payload.get("schema_version"),
        CHART_STUDY_SERIALIZATION_SCHEMA_VERSION,
    )
    if schema_version != CHART_STUDY_SERIALIZATION_SCHEMA_VERSION:
        errors.append(f"unsupported schema_version: {schema_version}")

    if not str(payload.get("family", "") or "").strip():
        errors.append("family is required.")
    if not str(payload.get("tool_key", "") or "").strip():
        errors.append("tool_key is required.")

    for field_name in ("params", "input_bindings", "input_binding_meta", "style"):
        value = payload.get(field_name, {})
        if value is not None and not isinstance(value, Mapping):
            errors.append(f"{field_name} must be a mapping.")

    required_inputs = payload.get("required_inputs", [])
    if required_inputs is not None and not isinstance(required_inputs, (list, tuple)):
        errors.append("required_inputs must be a sequence.")

    saved_artifact_ref = payload.get("saved_artifact_ref")
    if saved_artifact_ref is not None and not isinstance(saved_artifact_ref, Mapping):
        errors.append("saved_artifact_ref must be a mapping or null.")

    style = payload.get("style", {})
    if isinstance(style, Mapping):
        signal_styles = style.get("signal_styles", {})
        if signal_styles is not None and not isinstance(signal_styles, Mapping):
            errors.append("style.signal_styles must be a mapping.")
        fill_styles = style.get("fill_styles", {})
        if fill_styles is not None and not isinstance(fill_styles, Mapping):
            errors.append("style.fill_styles must be a mapping.")
        style_modules = style.get("style_modules", [])
        if style_modules is not None and not isinstance(style_modules, (list, tuple)):
            errors.append("style.style_modules must be a sequence.")

    return errors


def deserialize_chart_study_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and normalize a serialized chart-study payload.

    This phase does not reconstruct a live ChartStudyInstance or reapply a
    study to a chart. The returned structure is JSON-safe durable intent data
    for future setup/snapshot loaders.
    """

    errors = validate_serialized_chart_study(payload)
    if errors:
        raise ValueError("Invalid serialized chart study: " + "; ".join(errors))

    style = deserialize_study_style_payload(_mapping_or_empty(payload.get("style")))
    family = str(payload.get("family", "") or "").strip().lower()
    tool_key = str(payload.get("tool_key", "") or "").strip().lower()
    display_name = str(payload.get("display_name", "") or "").strip() or tool_key
    pane_target = payload.get("pane_target")
    saved_artifact_ref = payload.get("saved_artifact_ref")

    return {
        "schema_version": CHART_STUDY_SERIALIZATION_SCHEMA_VERSION,
        "family": family,
        "tool_key": tool_key,
        "display_name": display_name,
        "pane_target": None if pane_target is None else str(pane_target).strip() or None,
        "params": _json_safe(_mapping_or_empty(payload.get("params"))),
        "source_kind": str(payload.get("source_kind", "temporary") or "temporary").strip().lower(),
        "input_bindings": _json_safe(_mapping_or_empty(payload.get("input_bindings"))),
        "input_binding_meta": _json_safe(_mapping_or_empty(payload.get("input_binding_meta"))),
        "required_inputs": _json_safe(list(payload.get("required_inputs", []) or [])),
        "saved_artifact_ref": (
            _json_safe(saved_artifact_ref)
            if isinstance(saved_artifact_ref, Mapping)
            else None
        ),
        "style": serialize_study_style(style),
    }


def _deserialize_signal_style(payload: Mapping[str, Any]) -> StudySignalStyle:
    data = _mapping_or_empty(payload)
    return StudySignalStyle(
        color=str(data.get("color", "") or ""),
        line_width=_int_value(data.get("line_width"), 1),
        line_style=str(data.get("line_style", "solid") or "solid"),
        visible=_bool_value(data.get("visible"), True),
        show_label=_bool_value(data.get("show_label"), True),
        show_value=_bool_value(data.get("show_value"), True),
        render_mode=str(data.get("render_mode", "line") or "line"),
        marker_shape=str(data.get("marker_shape", "") or ""),
        marker_size=_int_value(data.get("marker_size"), 0),
        marker_text=str(data.get("marker_text", "") or ""),
        marker_text_color=str(data.get("marker_text_color", "") or ""),
        marker_offset_px=_int_value(data.get("marker_offset_px"), 0),
    )


def _deserialize_fill_style(fill_id: str, payload: Mapping[str, Any]) -> StudyFillStyle:
    data = _mapping_or_empty(payload)
    return StudyFillStyle(
        fill_id=str(data.get("fill_id", "") or "").strip() or fill_id,
        signal_a=str(data.get("signal_a", "") or ""),
        signal_b=str(data.get("signal_b", "") or ""),
        color=str(data.get("color", "") or ""),
        opacity=_float_value(data.get("opacity"), 0.15),
        visible=_bool_value(data.get("visible"), True),
    )


def _mapping_or_empty(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _bool_value(value: Any, default: bool) -> bool:
    if value is None:
        return bool(default)
    if isinstance(value, bool):
        return value
    return bool(value)


def _int_value(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def _float_value(value: Any, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return float(default)
    if math.isfinite(parsed):
        return parsed
    return float(default)


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, Path):
        return value.as_posix()
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if is_dataclass(value):
        return _json_safe(asdict(value))
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, set):
        return [_json_safe(item) for item in sorted(value, key=str)]
    return str(value)


__all__ = [
    "CHART_STUDY_SERIALIZATION_SCHEMA_VERSION",
    "deserialize_chart_study_payload",
    "deserialize_study_style_payload",
    "serialize_chart_study",
    "serialize_study_style",
    "validate_serialized_chart_study",
]
