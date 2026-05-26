from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from leonardo.data.chart_presets.study_setup_store import ChartStudySetup
from leonardo.data.chart_presets.workspace_snapshot_store import (
    HistoricalWorkspaceSnapshot,
    validate_historical_workspace_snapshot_payload,
)
from leonardo.financial_tools.ft_specs import ToolSpec, get_tool_spec
from leonardo.gui.chart.study_serialization import validate_serialized_chart_study


PRESET_STATUS_READY = "ready"
PRESET_STATUS_WARNING = "warning"
PRESET_STATUS_BROKEN = "broken"

PRESET_ISSUE_WARNING = "warning"
PRESET_ISSUE_BROKEN = "broken"

_KNOWN_FAMILIES = {"indicator", "oscillator", "construct"}
_STUDY_LOAD_MODES = {"append", "replace"}
_WORKSPACE_LOAD_MODES = {"replace", "load_into_current"}
_DATASET_KEYS = ("exchange", "market_type", "symbol", "timeframe")
_SAVED_SOURCE_KINDS = {"saved", "saved-loaded", "saved-linked", "linked"}
_ARTIFACT_PATH_KEYS = ("path", "file_path", "artifact_path", "csv_path")


@dataclass(frozen=True)
class PresetCompatibilityIssue:
    """One compatibility finding for a preset load preflight."""

    severity: str
    code: str
    message: str
    context: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-safe representation suitable for UI summaries."""
        return {
            "severity": self.severity,
            "code": self.code,
            "message": self.message,
            "context": dict(self.context),
        }


@dataclass(frozen=True)
class PresetCompatibilityReport:
    """Aggregated Ready/Warning/Broken compatibility result."""

    status: str
    issues: tuple[PresetCompatibilityIssue, ...] = ()

    @property
    def can_load(self) -> bool:
        """Return whether the load workflow may proceed."""
        return self.status != PRESET_STATUS_BROKEN

    @property
    def summary(self) -> str:
        """Return a compact user-facing status summary."""
        if self.status == PRESET_STATUS_READY:
            return "Ready"
        warning_count = sum(
            1 for issue in self.issues if issue.severity == PRESET_ISSUE_WARNING
        )
        broken_count = sum(
            1 for issue in self.issues if issue.severity == PRESET_ISSUE_BROKEN
        )
        if self.status == PRESET_STATUS_BROKEN:
            return f"Broken ({broken_count} blocking issue(s))"
        return f"Warning ({warning_count} caveat(s))"

    def messages(self, *, severity: str | None = None) -> list[str]:
        """Return issue messages, optionally filtered by severity."""
        return [
            issue.message
            for issue in self.issues
            if severity is None or issue.severity == severity
        ]


def ready_report() -> PresetCompatibilityReport:
    """Return a ready compatibility report with no issues."""
    return PresetCompatibilityReport(status=PRESET_STATUS_READY)


def build_compatibility_report(
    issues: Sequence[PresetCompatibilityIssue],
) -> PresetCompatibilityReport:
    """Build the aggregate report status from individual findings."""
    normalized = tuple(issues)
    if any(issue.severity == PRESET_ISSUE_BROKEN for issue in normalized):
        return PresetCompatibilityReport(
            status=PRESET_STATUS_BROKEN,
            issues=normalized,
        )
    if any(issue.severity == PRESET_ISSUE_WARNING for issue in normalized):
        return PresetCompatibilityReport(
            status=PRESET_STATUS_WARNING,
            issues=normalized,
        )
    return ready_report()


def format_compatibility_report(report: PresetCompatibilityReport) -> str:
    """Return a compact multiline report for dialogs and message boxes."""
    lines = [f"Status: {report.summary}"]
    if not report.issues:
        lines.append("No compatibility issues were detected.")
        return "\n".join(lines)
    lines.append("")
    for issue in report.issues:
        label = "Broken" if issue.severity == PRESET_ISSUE_BROKEN else "Warning"
        lines.append(f"{label}: {issue.message}")
    return "\n".join(lines)


def evaluate_study_setup_compatibility(
    setup: ChartStudySetup,
    *,
    target_panel: Any | None,
    load_mode: str,
) -> PresetCompatibilityReport:
    """Evaluate whether a saved chart study environment can load onto a target chart."""
    issues: list[PresetCompatibilityIssue] = []

    normalized_mode = str(load_mode or "").strip().lower()
    if normalized_mode not in _STUDY_LOAD_MODES:
        issues.append(
            _broken(
                "invalid_load_mode",
                f"Unsupported study environment load mode: {load_mode!r}.",
                {"load_mode": load_mode},
            )
        )

    if target_panel is None:
        issues.append(
            _broken(
                "missing_target_chart",
                "Selected target chart is no longer available.",
                {},
            )
        )
    else:
        target_dataset = _panel_dataset_descriptor(target_panel)
        if not _has_dataset_identity(target_dataset):
            issues.append(
                _broken(
                    "missing_target_dataset",
                    "Selected target chart does not expose a complete dataset identity.",
                    {"dataset": target_dataset},
                )
            )
        elif _has_dataset_identity(setup.created_from) and _dataset_differs(
            setup.created_from,
            target_dataset,
        ):
            issues.append(
                _warning(
                    "different_target_dataset",
                    "Setup was created from a different dataset; portable studies may still load.",
                    {
                        "created_from": dict(setup.created_from),
                        "target_dataset": target_dataset,
                    },
                )
            )

    if not setup.studies:
        issues.append(
            _broken(
                "empty_setup",
                "Study setup does not contain any studies.",
                {"setup_id": setup.setup_id},
            )
        )

    issues.extend(_study_payload_compatibility_issues(setup.studies, "Study"))

    if normalized_mode == "replace":
        issues.append(
            _warning(
                "non_transactional_study_restore",
                "Replace mode is preflighted, but study application is not transactionally rolled back if a later apply fails.",
                {"load_mode": normalized_mode},
            )
        )

    if _contains_oscillator_study(setup.studies):
        issues.append(
            _warning(
                "oscillator_visual_policy_deferred",
                "Exact oscillator visual policy persistence is deferred; chart-local line styles are restored.",
                {},
            )
        )

    return build_compatibility_report(issues)


def evaluate_workspace_snapshot_compatibility(
    snapshot: HistoricalWorkspaceSnapshot,
    *,
    workspace: Any | None,
    core_bridge: Any | None,
    load_mode: str,
    notebook_store: Any | None = None,
) -> PresetCompatibilityReport:
    """Evaluate whether a workspace snapshot can load into the current workspace."""
    issues: list[PresetCompatibilityIssue] = []

    normalized_mode = str(load_mode or "").strip().lower()
    if normalized_mode not in _WORKSPACE_LOAD_MODES:
        issues.append(
            _broken(
                "invalid_load_mode",
                f"Unsupported workspace snapshot load mode: {load_mode!r}.",
                {"load_mode": load_mode},
            )
        )

    structural_errors = validate_historical_workspace_snapshot_payload(snapshot.to_dict())
    for error in structural_errors:
        issues.append(
            _broken(
                "invalid_snapshot_structure",
                f"Snapshot structure is invalid: {error}",
                {"snapshot_id": snapshot.snapshot_id},
            )
        )

    charts = [dict(chart) for chart in snapshot.charts]
    if not charts:
        issues.append(
            _broken(
                "empty_snapshot",
                "Workspace snapshot does not contain any charts.",
                {"snapshot_id": snapshot.snapshot_id},
            )
        )

    if workspace is None:
        issues.append(
            _broken(
                "missing_workspace",
                "Historical workspace is not available.",
                {},
            )
        )
    else:
        detached_count = _call_int(workspace, "detached_reserved_slot_count")
        if normalized_mode == "replace" and detached_count > 0:
            issues.append(
                _broken(
                    "detached_reservations_block_replace",
                    "Replace mode is blocked while detached charts reserve dock-back slots.",
                    {"detached_reserved_slot_count": detached_count},
                )
            )

        if normalized_mode == "load_into_current":
            current_count = _call_int(workspace, "chart_count")
            available_count = _call_int(workspace, "available_embedded_slot_count")
            required_count = current_count + len(charts)
            if required_count > available_count:
                issues.append(
                    _broken(
                        "insufficient_non_reserved_slots",
                        "Not enough non-reserved chart slots are available for this snapshot.",
                        {
                            "current_chart_count": current_count,
                            "snapshot_chart_count": len(charts),
                            "available_slot_count": available_count,
                        },
                    )
                )
            if detached_count > 0:
                issues.append(
                    _warning(
                        "detached_slots_protected",
                        "Detached dock-back reservations are protected and skipped during placement.",
                        {"detached_reserved_slot_count": detached_count},
                    )
                )

    for index, chart in enumerate(charts, start=1):
        dataset = chart.get("dataset", {})
        if not isinstance(dataset, Mapping) or not _has_dataset_identity(dataset):
            issues.append(
                _broken(
                    "missing_dataset_identity",
                    f"Chart {index} does not contain a complete dataset identity.",
                    {"chart_index": index, "dataset": dataset if isinstance(dataset, Mapping) else {}},
                )
            )
        elif core_bridge is None:
            issues.append(
                _broken(
                    "dataset_service_unavailable",
                    f"Chart {index} dataset cannot be preflighted because CoreBridge is unavailable.",
                    {"chart_index": index, "dataset": dict(dataset)},
                )
            )
        else:
            _append_dataset_existence_issue(issues, core_bridge, index, dataset)

        studies = chart.get("studies", []) or []
        if not isinstance(studies, Sequence) or isinstance(studies, (str, bytes)):
            issues.append(
                _broken(
                    "invalid_chart_studies",
                    f"Chart {index} studies must be a list.",
                    {"chart_index": index},
                )
            )
            continue
        issues.extend(
            _study_payload_compatibility_issues(
                studies,
                f"Chart {index}, study",
            )
        )

    issues.append(
        _warning(
            "non_transactional_workspace_restore",
            "Workspace loading is preflighted, but async chart/study restore is not transactionally rolled back if a later apply fails.",
            {"load_mode": normalized_mode},
        )
    )

    if _charts_contain_oscillator_studies(charts):
        issues.append(
            _warning(
                "oscillator_visual_policy_deferred",
                "Exact oscillator visual policy persistence is deferred; chart-local line styles are restored.",
                {},
            )
        )

    notebook_ref = getattr(snapshot, "notebook_ref", None)
    if isinstance(notebook_ref, Mapping):
        notebook_id = str(notebook_ref.get("notebook_id", "") or "").strip()
        if not notebook_id:
            issues.append(
                _warning(
                    "invalid_notebook_ref",
                    "Workspace snapshot has a notebook reference without a notebook_id.",
                    {},
                )
            )
        elif notebook_store is None:
            issues.append(
                _warning(
                    "notebook_ref_unverified",
                    "Assigned notebook reference could not be preflighted.",
                    {"notebook_id": notebook_id},
                )
            )
        else:
            try:
                notebook_store.load_notebook(notebook_id)
            except Exception as exc:
                issues.append(
                    _warning(
                        "assigned_notebook_unavailable",
                        f"Assigned notebook could not be loaded: {exc!r}.",
                        {"notebook_id": notebook_id},
                    )
                )

    return build_compatibility_report(issues)


def _study_payload_compatibility_issues(
    studies: Sequence[Any],
    label_prefix: str,
) -> list[PresetCompatibilityIssue]:
    issues: list[PresetCompatibilityIssue] = []
    for index, raw_study in enumerate(studies, start=1):
        label = f"{label_prefix} {index}"
        if not isinstance(raw_study, Mapping):
            issues.append(
                _broken(
                    "invalid_study_payload",
                    f"{label} must be a mapping.",
                    {"index": index},
                )
            )
            continue
        study = dict(raw_study)
        for error in validate_serialized_chart_study(study):
            issues.append(
                _broken(
                    "invalid_study_payload",
                    f"{label}: {error}",
                    {"index": index},
                )
            )

        family = str(study.get("family", "") or "").strip().lower()
        tool_key = str(study.get("tool_key", "") or "").strip().lower()
        if family not in _KNOWN_FAMILIES:
            issues.append(
                _broken(
                    "unknown_tool_family",
                    f"{label}: unknown tool family {family!r}.",
                    {"family": family, "tool_key": tool_key},
                )
            )
            continue

        spec = _tool_spec_for_study(tool_key)
        if spec is None:
            issues.append(
                _broken(
                    "unknown_tool_key",
                    f"{label}: unknown tool key {tool_key!r}.",
                    {"family": family, "tool_key": tool_key},
                )
            )
            continue

        if spec.kind != family:
            issues.append(
                _broken(
                    "tool_family_mismatch",
                    f"{label}: tool key {tool_key!r} belongs to {spec.kind!r}, not {family!r}.",
                    {"family": family, "tool_key": tool_key, "spec_kind": spec.kind},
                )
            )

        issues.extend(_param_compatibility_issues(label, spec, study.get("params", {})))
        issues.extend(_source_binding_compatibility_issues(label, spec, study))
    return issues


def _param_compatibility_issues(
    label: str,
    spec: ToolSpec,
    raw_params: Any,
) -> list[PresetCompatibilityIssue]:
    if not isinstance(raw_params, Mapping):
        return [
            _broken(
                "invalid_params",
                f"{label}: params must be a mapping.",
                {"tool_key": spec.key},
            )
        ]

    issues: list[PresetCompatibilityIssue] = []
    params = dict(raw_params)
    specs_by_name = {param.name: param for param in spec.params}
    for key, value in params.items():
        param_spec = specs_by_name.get(str(key))
        if param_spec is None:
            issues.append(
                _warning(
                    "unknown_param",
                    f"{label}: parameter {key!r} is not declared by the current tool spec.",
                    {"tool_key": spec.key, "param": str(key)},
                )
            )
            continue

        parsed_value = _coerced_param_value(value, param_spec.dtype)
        if parsed_value is None:
            issues.append(
                _broken(
                    "invalid_param_type",
                    f"{label}: parameter {key!r} cannot be interpreted as {param_spec.dtype}.",
                    {"tool_key": spec.key, "param": str(key), "value": value},
                )
            )
            continue

        if param_spec.choices and parsed_value not in param_spec.choices:
            issues.append(
                _broken(
                    "invalid_param_choice",
                    f"{label}: parameter {key!r} must be one of {tuple(param_spec.choices)!r}.",
                    {"tool_key": spec.key, "param": str(key), "value": parsed_value},
                )
            )
            continue

        if param_spec.minimum is not None and parsed_value < param_spec.minimum:
            issues.append(
                _broken(
                    "param_below_minimum",
                    f"{label}: parameter {key!r} is below the minimum {param_spec.minimum}.",
                    {"tool_key": spec.key, "param": str(key), "value": parsed_value},
                )
            )
        if param_spec.maximum is not None and parsed_value > param_spec.maximum:
            issues.append(
                _broken(
                    "param_above_maximum",
                    f"{label}: parameter {key!r} is above the maximum {param_spec.maximum}.",
                    {"tool_key": spec.key, "param": str(key), "value": parsed_value},
                )
            )

    missing_required = [
        param.name
        for param in spec.params
        if param.required and param.name not in params and param.default is None
    ]
    if missing_required:
        issues.append(
            _warning(
                "missing_required_params",
                f"{label}: required parameters are missing and may fall back incorrectly: {', '.join(missing_required)}.",
                {"tool_key": spec.key, "missing": missing_required},
            )
        )
    return issues


def _source_binding_compatibility_issues(
    label: str,
    spec: ToolSpec,
    study: Mapping[str, Any],
) -> list[PresetCompatibilityIssue]:
    issues: list[PresetCompatibilityIssue] = []

    input_bindings = study.get("input_bindings", {})
    if input_bindings is not None and not isinstance(input_bindings, Mapping):
        issues.append(
            _broken(
                "invalid_input_bindings",
                f"{label}: input_bindings must be a mapping.",
                {"tool_key": spec.key},
            )
        )

    input_binding_meta = study.get("input_binding_meta", {})
    if input_binding_meta is not None and not isinstance(input_binding_meta, Mapping):
        issues.append(
            _broken(
                "invalid_input_binding_meta",
                f"{label}: input_binding_meta must be a mapping.",
                {"tool_key": spec.key},
            )
        )

    required_inputs = study.get("required_inputs", [])
    if required_inputs is not None and (
        not isinstance(required_inputs, Sequence) or isinstance(required_inputs, (str, bytes))
    ):
        issues.append(
            _broken(
                "invalid_required_inputs",
                f"{label}: required_inputs must be a sequence.",
                {"tool_key": spec.key},
            )
        )

    saved_artifact_ref = study.get("saved_artifact_ref")
    if saved_artifact_ref is not None and not isinstance(saved_artifact_ref, Mapping):
        issues.append(
            _broken(
                "invalid_saved_artifact_ref",
                f"{label}: saved_artifact_ref must be a mapping or null.",
                {"tool_key": spec.key},
            )
        )
    elif isinstance(saved_artifact_ref, Mapping):
        path_value = _artifact_path_value(saved_artifact_ref)
        if path_value:
            if not Path(path_value).exists():
                issues.append(
                    _broken(
                        "missing_saved_artifact",
                        f"{label}: saved artifact reference does not exist: {path_value}.",
                        {"tool_key": spec.key, "path": path_value},
                    )
                )
        else:
            issues.append(
                _warning(
                    "unverified_saved_artifact_ref",
                    f"{label}: saved artifact reference is present but cannot be verified in this preflight.",
                    {"tool_key": spec.key},
                )
            )

    source_kind = str(study.get("source_kind", "") or "").strip().lower()
    if source_kind in _SAVED_SOURCE_KINDS and not isinstance(saved_artifact_ref, Mapping):
        issues.append(
            _broken(
                "missing_saved_artifact_ref",
                f"{label}: saved source kind requires a saved artifact reference.",
                {"tool_key": spec.key, "source_kind": source_kind},
            )
        )

    if spec.kind == "construct" and spec.construct_io is not None:
        has_bindings = isinstance(input_bindings, Mapping) and bool(input_bindings)
        has_required_inputs = (
            isinstance(required_inputs, Sequence)
            and not isinstance(required_inputs, (str, bytes))
            and bool(required_inputs)
        )
        if not has_bindings and not has_required_inputs:
            issues.append(
                _broken(
                    "unresolved_construct_inputs",
                    f"{label}: construct inputs are not serialized and cannot be resolved safely.",
                    {"tool_key": spec.key},
                )
            )
        if source_kind == "temporary":
            issues.append(
                _warning(
                    "temporary_construct_chain",
                    f"{label}: temporary construct-source restoration depends on serialized apply order.",
                    {"tool_key": spec.key},
                )
            )
    return issues


def _append_dataset_existence_issue(
    issues: list[PresetCompatibilityIssue],
    core_bridge: Any,
    chart_index: int,
    dataset: Mapping[str, Any],
) -> None:
    loadability_fn = getattr(core_bridge, "historical_dataset_loadability", None)
    if callable(loadability_fn):
        try:
            loadability = loadability_fn(
                exchange=str(dataset.get("exchange", "") or ""),
                market_type=str(dataset.get("market_type", "") or ""),
                symbol=str(dataset.get("symbol", "") or ""),
                timeframe=str(dataset.get("timeframe", "") or ""),
            )
        except Exception as exc:
            issues.append(
                _broken(
                    "dataset_preflight_failed",
                    f"Chart {chart_index} dataset could not be validated: {exc!r}.",
                    {"chart_index": chart_index, "dataset": dict(dataset)},
                )
            )
            return

        loadable = bool(
            loadability.get("loadable")
            if isinstance(loadability, Mapping)
            else getattr(loadability, "loadable", False)
        )
        if not loadable:
            reason = (
                loadability.get("reason", "")
                if isinstance(loadability, Mapping)
                else getattr(loadability, "reason", "")
            )
            message = str(reason or "dataset is not accepted for chart loading").strip()
            issues.append(
                _broken(
                    "blocked_ohlcv_dataset",
                    f"Chart {chart_index} dataset is not loadable: {_dataset_text(dataset)}. {message}",
                    {"chart_index": chart_index, "dataset": dict(dataset)},
                )
            )
        return

    exists_fn = getattr(core_bridge, "historical_dataset_exists", None)
    if not callable(exists_fn):
        issues.append(
            _broken(
                "dataset_service_unavailable",
                f"Chart {chart_index} dataset cannot be preflighted because dataset existence checking is unavailable.",
                {"chart_index": chart_index, "dataset": dict(dataset)},
            )
        )
        return

    try:
        exists = bool(
            exists_fn(
                exchange=str(dataset.get("exchange", "") or ""),
                market_type=str(dataset.get("market_type", "") or ""),
                symbol=str(dataset.get("symbol", "") or ""),
                timeframe=str(dataset.get("timeframe", "") or ""),
            )
        )
    except Exception as exc:
        issues.append(
            _broken(
                "dataset_preflight_failed",
                f"Chart {chart_index} dataset could not be validated: {exc!r}.",
                {"chart_index": chart_index, "dataset": dict(dataset)},
            )
        )
        return

    if not exists:
        issues.append(
            _broken(
                "missing_dataset",
                f"Chart {chart_index} dataset is not available: {_dataset_text(dataset)}.",
                {"chart_index": chart_index, "dataset": dict(dataset)},
            )
        )


def _tool_spec_for_study(tool_key: str) -> ToolSpec | None:
    try:
        return get_tool_spec(tool_key)
    except KeyError:
        return None


def _panel_dataset_descriptor(panel: Any) -> dict[str, str]:
    descriptor = getattr(panel, "dataset_descriptor", None)
    if not callable(descriptor):
        return {}
    raw = descriptor()
    if not isinstance(raw, Mapping):
        return {}
    return {key: str(raw.get(key, "") or "") for key in _DATASET_KEYS}


def _has_dataset_identity(dataset: Mapping[str, Any]) -> bool:
    return all(str(dataset.get(key, "") or "").strip() for key in _DATASET_KEYS)


def _dataset_differs(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
    return any(
        str(left.get(key, "") or "").strip().lower()
        != str(right.get(key, "") or "").strip().lower()
        for key in _DATASET_KEYS
    )


def _dataset_text(dataset: Mapping[str, Any]) -> str:
    return " / ".join(str(dataset.get(key, "") or "").strip() for key in _DATASET_KEYS)


def _call_int(owner: Any, method_name: str) -> int:
    method = getattr(owner, method_name, None)
    if not callable(method):
        return 0
    try:
        return int(method())
    except (TypeError, ValueError):
        return 0


def _contains_oscillator_study(studies: Sequence[Any]) -> bool:
    for study in studies:
        if isinstance(study, Mapping) and str(study.get("family", "") or "").strip().lower() == "oscillator":
            return True
    return False


def _charts_contain_oscillator_studies(charts: Sequence[Mapping[str, Any]]) -> bool:
    for chart in charts:
        studies = chart.get("studies", []) or []
        if isinstance(studies, Sequence) and _contains_oscillator_study(studies):
            return True
    return False


def _artifact_path_value(saved_artifact_ref: Mapping[str, Any]) -> str:
    for key in _ARTIFACT_PATH_KEYS:
        value = saved_artifact_ref.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _coerced_param_value(value: Any, dtype: str) -> Any:
    try:
        if dtype == "bool":
            if isinstance(value, bool):
                return value
            if isinstance(value, str):
                normalized = value.strip().lower()
                if normalized in {"true", "1", "yes", "on"}:
                    return True
                if normalized in {"false", "0", "no", "off"}:
                    return False
            return None
        if dtype == "int":
            if isinstance(value, bool):
                return None
            return int(value)
        if dtype == "float":
            if isinstance(value, bool):
                return None
            return float(value)
        if dtype == "str":
            return str(value)
    except (TypeError, ValueError):
        return None
    return value


def _warning(
    code: str,
    message: str,
    context: Mapping[str, Any],
) -> PresetCompatibilityIssue:
    return PresetCompatibilityIssue(
        severity=PRESET_ISSUE_WARNING,
        code=code,
        message=message,
        context=dict(context),
    )


def _broken(
    code: str,
    message: str,
    context: Mapping[str, Any],
) -> PresetCompatibilityIssue:
    return PresetCompatibilityIssue(
        severity=PRESET_ISSUE_BROKEN,
        code=code,
        message=message,
        context=dict(context),
    )


__all__ = [
    "PRESET_STATUS_BROKEN",
    "PRESET_STATUS_READY",
    "PRESET_STATUS_WARNING",
    "PresetCompatibilityIssue",
    "PresetCompatibilityReport",
    "build_compatibility_report",
    "evaluate_study_setup_compatibility",
    "evaluate_workspace_snapshot_compatibility",
    "format_compatibility_report",
    "ready_report",
]
