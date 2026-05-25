from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from leonardo.data.historical.analysis_database_contracts import (
    AnalysisDatabaseColumn,
    AnalysisDatabaseManifest,
    AnalysisFeatureSource,
)

GEOGRAPHY_KEY_OHLC_BASE = "ohlc_base"
GEOGRAPHY_KEY_VOLUME_ARTIFACT = "volume_artifact"
GEOGRAPHY_KEY_BRAIDS = "braids"
GEOGRAPHY_KEY_PEAKS_TROUGHS = "peaks_troughs"
GEOGRAPHY_KEY_UTC = "utc"

REQUIRED_GEOGRAPHY_KEYS: tuple[str, ...] = (
    GEOGRAPHY_KEY_OHLC_BASE,
    GEOGRAPHY_KEY_VOLUME_ARTIFACT,
    GEOGRAPHY_KEY_BRAIDS,
    GEOGRAPHY_KEY_PEAKS_TROUGHS,
    GEOGRAPHY_KEY_UTC,
)

_GEOGRAPHY_LABELS: dict[str, str] = {
    GEOGRAPHY_KEY_OHLC_BASE: "OHLC base",
    GEOGRAPHY_KEY_VOLUME_ARTIFACT: "Volume artifact",
    GEOGRAPHY_KEY_BRAIDS: "Braids artifact",
    GEOGRAPHY_KEY_PEAKS_TROUGHS: "Peaks & Troughs artifact",
    GEOGRAPHY_KEY_UTC: "UTC artifact",
}

_REQUIRED_OHLC_BASE_COLUMNS = {"ts_ms", "open", "high", "low", "close"}

_REQUIRED_ARTIFACT_SPECS: dict[str, tuple[str, str]] = {
    GEOGRAPHY_KEY_VOLUME_ARTIFACT: ("oscillators", "volume"),
    GEOGRAPHY_KEY_BRAIDS: ("constructs", "braids"),
    GEOGRAPHY_KEY_PEAKS_TROUGHS: ("indicators", "peaks_troughs"),
    GEOGRAPHY_KEY_UTC: ("indicators", "universal_trend_classifier"),
}

_ROLE_TOOL_EXPECTATIONS: dict[str, str] = {
    "volume": "volume",
    "braid": "braids",
    "braids": "braids",
    "peaks_troughs": "peaks_troughs",
    "utc": "universal_trend_classifier",
}

_ROLE_WARNING_CODES: dict[str, str] = {
    "volume": "dataset_role_volume_mismatch",
    "braid": "dataset_role_braid_mismatch",
    "braids": "dataset_role_braid_mismatch",
    "peaks_troughs": "dataset_role_peaks_troughs_mismatch",
    "utc": "dataset_role_utc_mismatch",
}


@dataclass(frozen=True)
class AnalysisDatasetGeographyWarning:
    """Diagnostic warning produced by geography policy evaluation."""

    code: str
    message: str
    metadata: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "metadata": _json_safe(self.metadata),
        }


@dataclass(frozen=True)
class AnalysisDatasetGeographyBlocker:
    """Structural blocker that prevents reliable geography evaluation."""

    code: str
    message: str
    metadata: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "metadata": _json_safe(self.metadata),
        }


@dataclass(frozen=True)
class AnalysisDatasetGeographyItem:
    """Presence report for one required dataset geography item."""

    key: str
    label: str
    present: bool
    evidence: tuple[dict[str, Any], ...]
    required: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "evidence", tuple(dict(item) for item in self.evidence))

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "present": bool(self.present),
            "evidence": [_json_safe(item) for item in self.evidence],
            "required": bool(self.required),
        }


@dataclass(frozen=True)
class AnalysisDatasetGeographyReport:
    """Read-only diagnostic report for Analysis Database geography coverage."""

    complete: bool
    strict_ready: bool
    required_items: tuple[AnalysisDatasetGeographyItem, ...]
    present_keys: tuple[str, ...]
    missing_keys: tuple[str, ...]
    warnings: tuple[AnalysisDatasetGeographyWarning, ...]
    blockers: tuple[AnalysisDatasetGeographyBlocker, ...]
    raw_volume_present: bool
    volume_artifact_present: bool
    semantic_volume_duplication: bool
    metadata: dict[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(self, "required_items", tuple(self.required_items))
        object.__setattr__(self, "present_keys", tuple(str(item) for item in self.present_keys))
        object.__setattr__(self, "missing_keys", tuple(str(item) for item in self.missing_keys))
        object.__setattr__(self, "warnings", tuple(self.warnings))
        object.__setattr__(self, "blockers", tuple(self.blockers))
        object.__setattr__(self, "metadata", dict(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return {
            "complete": bool(self.complete),
            "strict_ready": bool(self.strict_ready),
            "required_items": [item.to_dict() for item in self.required_items],
            "present_keys": list(self.present_keys),
            "missing_keys": list(self.missing_keys),
            "warnings": [warning.to_dict() for warning in self.warnings],
            "blockers": [blocker.to_dict() for blocker in self.blockers],
            "raw_volume_present": bool(self.raw_volume_present),
            "volume_artifact_present": bool(self.volume_artifact_present),
            "semantic_volume_duplication": bool(self.semantic_volume_duplication),
            "metadata": _json_safe(self.metadata),
        }


class AnalysisDatasetGeographyPolicy:
    """
    Evaluate Analysis Database geography coverage from manifest components.

    The policy is diagnostic-only. It reads manifest component identity and
    metadata, reports missing or risky geography, and does not mutate manifests,
    create components, save files, or perform artifact calculation.
    """

    def evaluate_manifest(
        self,
        manifest: AnalysisDatabaseManifest,
    ) -> AnalysisDatasetGeographyReport:
        """
        Evaluate a persisted Analysis Database manifest.

        Parameters
        ----------
        manifest:
            Analysis Database manifest whose declared base and feature
            components should be inspected.

        Returns
        -------
        AnalysisDatasetGeographyReport
            JSON-safe diagnostic report describing required geography coverage.
        """

        return self.evaluate_components(
            base_columns=manifest.base_columns,
            feature_sources=manifest.feature_sources,
            feature_columns=manifest.feature_columns,
            metadata={
                "database_id": manifest.database_id,
                "display_name": manifest.display_name,
                "status": manifest.status,
            },
        )

    def evaluate_components(
        self,
        *,
        base_columns: Sequence[AnalysisDatabaseColumn],
        feature_sources: Sequence[AnalysisFeatureSource],
        feature_columns: Sequence[AnalysisDatabaseColumn],
        metadata: Mapping[str, Any] | None = None,
    ) -> AnalysisDatasetGeographyReport:
        """
        Evaluate a component set without requiring a saved manifest.

        This method supports future planning flows that assemble candidate base
        columns, feature sources, and feature columns before creating or editing
        an Analysis Database manifest.
        """

        selected_base_columns = _selected_columns(base_columns)
        selected_feature_columns = _selected_columns(feature_columns)
        feature_source_by_id = {
            str(source.source_id): source
            for source in feature_sources
            if str(source.source_id or "").strip()
        }
        selected_columns_by_source = _selected_feature_columns_by_source(
            selected_feature_columns
        )

        ohlc_evidence = _ohlc_base_evidence(selected_base_columns)
        raw_volume_evidence = _raw_volume_evidence(selected_base_columns)
        item_evidence: dict[str, tuple[dict[str, Any], ...]] = {
            GEOGRAPHY_KEY_OHLC_BASE: tuple(ohlc_evidence),
        }

        for key, (family, tool_key) in _REQUIRED_ARTIFACT_SPECS.items():
            item_evidence[key] = _artifact_evidence(
                feature_source_by_id=feature_source_by_id,
                selected_columns_by_source=selected_columns_by_source,
                family=family,
                tool_key=tool_key,
            )

        items = tuple(
            AnalysisDatasetGeographyItem(
                key=key,
                label=_GEOGRAPHY_LABELS[key],
                present=bool(item_evidence[key]),
                evidence=item_evidence[key],
            )
            for key in REQUIRED_GEOGRAPHY_KEYS
        )
        present_keys = tuple(item.key for item in items if item.present)
        missing_keys = tuple(item.key for item in items if not item.present)
        volume_artifact_present = GEOGRAPHY_KEY_VOLUME_ARTIFACT in present_keys
        raw_volume_present = bool(raw_volume_evidence)
        semantic_volume_duplication = raw_volume_present and volume_artifact_present

        warnings = list(
            _dataset_role_warnings(
                feature_sources=feature_sources,
                feature_columns=feature_columns,
            )
        )
        if semantic_volume_duplication:
            warnings.append(
                AnalysisDatasetGeographyWarning(
                    code="semantic_volume_duplication",
                    message=(
                        "Raw OHLCV volume and an explicit Volume artifact are "
                        "both present. Future geography-compliant datasets should "
                        "prefer OHLC base plus explicit Volume artifact while "
                        "legacy databases remain loadable."
                    ),
                    metadata={
                        "raw_volume_evidence": raw_volume_evidence,
                        "volume_artifact_evidence": item_evidence[
                            GEOGRAPHY_KEY_VOLUME_ARTIFACT
                        ],
                    },
                )
            )

        complete = len(missing_keys) == 0
        blockers: tuple[AnalysisDatasetGeographyBlocker, ...] = ()
        return AnalysisDatasetGeographyReport(
            complete=complete,
            strict_ready=complete and not blockers,
            required_items=items,
            present_keys=present_keys,
            missing_keys=missing_keys,
            warnings=tuple(warnings),
            blockers=blockers,
            raw_volume_present=raw_volume_present,
            volume_artifact_present=volume_artifact_present,
            semantic_volume_duplication=semantic_volume_duplication,
            metadata={
                "required_keys": REQUIRED_GEOGRAPHY_KEYS,
                "raw_volume_evidence": tuple(raw_volume_evidence),
                **dict(metadata or {}),
            },
        )


def _selected_columns(
    columns: Sequence[AnalysisDatabaseColumn],
) -> tuple[AnalysisDatabaseColumn, ...]:
    return tuple(column for column in columns if bool(column.selected))


def _ohlc_base_evidence(
    base_columns: Sequence[AnalysisDatabaseColumn],
) -> tuple[dict[str, Any], ...]:
    names_by_source_column: dict[str, AnalysisDatabaseColumn] = {}
    for column in base_columns:
        if column.source_family != "ohlcv" or column.role not in {"primary_key", "base"}:
            continue
        source_name = str(column.source_column_name or "").strip().lower()
        db_name = str(column.db_column_name or "").strip().lower()
        if source_name in _REQUIRED_OHLC_BASE_COLUMNS:
            names_by_source_column[source_name] = column
        elif db_name in _REQUIRED_OHLC_BASE_COLUMNS:
            names_by_source_column[db_name] = column

    if not _REQUIRED_OHLC_BASE_COLUMNS.issubset(names_by_source_column):
        return ()

    return tuple(
        _column_evidence(names_by_source_column[name])
        for name in ("ts_ms", "open", "high", "low", "close")
    )


def _raw_volume_evidence(
    base_columns: Sequence[AnalysisDatabaseColumn],
) -> tuple[dict[str, Any], ...]:
    return tuple(
        _column_evidence(column)
        for column in base_columns
        if (
            column.source_family == "ohlcv"
            and column.role in {"primary_key", "base"}
            and (
                str(column.source_column_name or "").strip().lower() == "volume"
                or str(column.db_column_name or "").strip().lower() == "volume"
            )
        )
    )


def _selected_feature_columns_by_source(
    feature_columns: Sequence[AnalysisDatabaseColumn],
) -> dict[str, tuple[AnalysisDatabaseColumn, ...]]:
    grouped: dict[str, list[AnalysisDatabaseColumn]] = {}
    for column in feature_columns:
        if column.role != "feature":
            continue
        source_id = str(column.source_id or "").strip()
        if not source_id:
            continue
        grouped.setdefault(source_id, []).append(column)
    return {source_id: tuple(columns) for source_id, columns in grouped.items()}


def _artifact_evidence(
    *,
    feature_source_by_id: Mapping[str, AnalysisFeatureSource],
    selected_columns_by_source: Mapping[str, tuple[AnalysisDatabaseColumn, ...]],
    family: str,
    tool_key: str,
) -> tuple[dict[str, Any], ...]:
    evidence: list[dict[str, Any]] = []
    for source_id, columns in selected_columns_by_source.items():
        source = feature_source_by_id.get(source_id)
        if source is None:
            continue
        if source.family != family or source.tool_key != tool_key:
            continue
        evidence.append(_source_evidence(source=source, columns=columns))
    return tuple(evidence)


def _source_evidence(
    *,
    source: AnalysisFeatureSource,
    columns: Sequence[AnalysisDatabaseColumn],
) -> dict[str, Any]:
    return {
        "source_id": source.source_id,
        "family": source.family,
        "tool_key": source.tool_key,
        "tool_title": source.tool_title,
        "instance_key": source.instance_key,
        "columns": [_column_evidence(column) for column in columns],
    }


def _column_evidence(column: AnalysisDatabaseColumn) -> dict[str, Any]:
    return {
        "role": column.role,
        "source_family": column.source_family,
        "source_id": column.source_id,
        "source_column_name": column.source_column_name,
        "db_column_name": column.db_column_name,
        "selected": bool(column.selected),
    }


def _dataset_role_warnings(
    *,
    feature_sources: Sequence[AnalysisFeatureSource],
    feature_columns: Sequence[AnalysisDatabaseColumn],
) -> tuple[AnalysisDatasetGeographyWarning, ...]:
    warnings: list[AnalysisDatasetGeographyWarning] = []
    source_by_id = {source.source_id: source for source in feature_sources}

    for source in feature_sources:
        warnings.extend(
            _warnings_for_roles(
                roles=_metadata_dataset_roles(source.metadata),
                source=source,
                column=None,
            )
        )

    for column in feature_columns:
        source_id = str(column.source_id or "").strip()
        source = source_by_id.get(source_id)
        if source is None:
            continue
        warnings.extend(
            _warnings_for_roles(
                roles=_metadata_dataset_roles(column.metadata),
                source=source,
                column=column,
            )
        )

    unique: dict[tuple[str, str, str | None], AnalysisDatasetGeographyWarning] = {}
    for warning in warnings:
        key = (
            warning.code,
            str(warning.metadata.get("source_id", "")),
            (
                None
                if warning.metadata.get("db_column_name") is None
                else str(warning.metadata.get("db_column_name"))
            ),
        )
        unique.setdefault(key, warning)
    return tuple(unique.values())


def _warnings_for_roles(
    *,
    roles: Sequence[str],
    source: AnalysisFeatureSource,
    column: AnalysisDatabaseColumn | None,
) -> tuple[AnalysisDatasetGeographyWarning, ...]:
    warnings: list[AnalysisDatasetGeographyWarning] = []
    for role in roles:
        expected_tool_key = _ROLE_TOOL_EXPECTATIONS.get(role)
        if expected_tool_key is not None and source.tool_key != expected_tool_key:
            warnings.append(
                AnalysisDatasetGeographyWarning(
                    code=_ROLE_WARNING_CODES[role],
                    message=(
                        f"dataset_role={role!r} does not match source tool_key "
                        f"{source.tool_key!r}."
                    ),
                    metadata={
                        "dataset_role": role,
                        "expected_tool_key": expected_tool_key,
                        "source_id": source.source_id,
                        "family": source.family,
                        "tool_key": source.tool_key,
                        "db_column_name": None if column is None else column.db_column_name,
                    },
                )
            )
        if role == "visual_only" and _source_satisfies_required_geography(source):
            warnings.append(
                AnalysisDatasetGeographyWarning(
                    code="dataset_role_visual_only_required_geography",
                    message=(
                        "dataset_role='visual_only' is attached to a source that "
                        "matches required geography identity."
                    ),
                    metadata={
                        "dataset_role": role,
                        "source_id": source.source_id,
                        "family": source.family,
                        "tool_key": source.tool_key,
                        "db_column_name": None if column is None else column.db_column_name,
                    },
                )
            )
    return tuple(warnings)


def _source_satisfies_required_geography(source: AnalysisFeatureSource) -> bool:
    for family, tool_key in _REQUIRED_ARTIFACT_SPECS.values():
        if source.family == family and source.tool_key == tool_key:
            return True
    return False


def _metadata_dataset_roles(metadata: Sequence[Any]) -> tuple[str, ...]:
    roles: list[str] = []
    for entry in metadata:
        key = str(getattr(entry, "key", "") or "").strip().lower()
        value = getattr(entry, "value", None)
        roles.extend(_dataset_roles_from_key_value(key=key, value=value))
    return tuple(role for role in roles if role)


def _dataset_roles_from_key_value(*, key: str, value: Any) -> tuple[str, ...]:
    if key == "dataset_role":
        role = _normalize_dataset_role(value)
        return (role,) if role else ()
    if isinstance(value, Mapping):
        roles: list[str] = []
        direct_role = _normalize_dataset_role(value.get("dataset_role"))
        if direct_role:
            roles.append(direct_role)
        for nested_key in ("user_metadata", "source_study_user_metadata"):
            nested = value.get(nested_key)
            if isinstance(nested, Mapping):
                nested_role = _normalize_dataset_role(nested.get("dataset_role"))
                if nested_role:
                    roles.append(nested_role)
        return tuple(roles)
    return ()


def _normalize_dataset_role(value: Any) -> str:
    text = str(value or "").strip().lower().replace(" ", "_").replace("-", "_")
    return text


def _json_safe(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, Path):
        return value.as_posix()
    return value


__all__ = [
    "GEOGRAPHY_KEY_BRAIDS",
    "GEOGRAPHY_KEY_OHLC_BASE",
    "GEOGRAPHY_KEY_PEAKS_TROUGHS",
    "GEOGRAPHY_KEY_UTC",
    "GEOGRAPHY_KEY_VOLUME_ARTIFACT",
    "REQUIRED_GEOGRAPHY_KEYS",
    "AnalysisDatasetGeographyBlocker",
    "AnalysisDatasetGeographyItem",
    "AnalysisDatasetGeographyPolicy",
    "AnalysisDatasetGeographyReport",
    "AnalysisDatasetGeographyWarning",
]
