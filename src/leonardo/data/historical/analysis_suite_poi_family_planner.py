"""Read-only Analysis Suite POI and family preview planning.

The module defines typed POI and family definitions for Analysis Suite and
builds bounded in-memory preview reports from already-prepared Analysis
Databases. It consumes AS1 readiness or AS7 diagnostic context for gating,
uses Analysis Database manifest metadata as semantic input truth, and reads
dataframe values only for physical occurrence and condition evaluation.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Literal, Mapping, Protocol, Sequence

import pandas as pd

from leonardo.data.historical.analysis_database_contracts import (
    AnalysisDatabaseColumn,
    AnalysisDatabaseManifest,
)
from leonardo.data.historical.analysis_database_store import AnalysisDatabaseStore
from leonardo.data.historical.analysis_suite_dataset_readiness import (
    AnalysisSuiteDatasetReadinessReport,
    AnalysisSuiteDatasetReadinessService,
    AnalysisSuiteDatasetReadinessStatus,
)
from leonardo.data.historical.analysis_suite_diagnostic_report import (
    AnalysisSuiteDiagnosticReport,
)
from leonardo.data.naming import MarketId


ANALYSIS_SUITE_POI_FAMILY_SCHEMA_VERSION = 1
DEFAULT_POI_SAMPLE_LIMIT = 100
MAX_POI_SAMPLE_LIMIT = 500

AnalysisSuitePoiEventKind = Literal[
    "sparse_event",
    "boolean_true",
    "value_equals",
    "transition",
]
AnalysisSuitePoiConditionOperator = Literal[
    "equals",
    "not_equals",
    "gt",
    "gte",
    "lt",
    "lte",
    "in",
    "not_in",
    "is_null",
    "not_null",
]
AnalysisSuitePoiPreviewStatus = Literal["ready", "warning", "blocked", "error"]

JsonValue = Any

_SUPPORTED_EVENT_KINDS = frozenset(
    {"sparse_event", "boolean_true", "value_equals", "transition"}
)
_SUPPORTED_OPERATORS = frozenset(
    {
        "equals",
        "not_equals",
        "gt",
        "gte",
        "lt",
        "lte",
        "in",
        "not_in",
        "is_null",
        "not_null",
    }
)


class _ReadinessService(Protocol):
    def readiness_for_database(
        self,
        *,
        market: MarketId,
        database_id: str,
    ) -> AnalysisSuiteDatasetReadinessReport:
        ...


@dataclass(frozen=True)
class AnalysisSuitePoiDefinition:
    """
    JSON-safe definition for one Analysis Suite point-of-interest event.

    A POI definition identifies an event column from an Analysis Database and
    the rule used to interpret rows as occurrences. The definition is evaluated
    in memory and is not persisted by AS8.
    """

    poi_key: str
    poi_type: str
    source_column: str
    event_kind: AnalysisSuitePoiEventKind | str
    event_value: JsonValue | None = None
    previous_value: JsonValue | None = None
    threshold: float | None = None
    direction: str | None = None
    display_name: str | None = None
    metadata: Mapping[str, JsonValue] = field(default_factory=dict)
    schema_version: int = ANALYSIS_SUITE_POI_FAMILY_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "poi_key", str(self.poi_key))
        object.__setattr__(self, "poi_type", str(self.poi_type))
        object.__setattr__(self, "source_column", str(self.source_column))
        object.__setattr__(self, "event_kind", str(self.event_kind))
        object.__setattr__(self, "metadata", dict(self.metadata))

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "AnalysisSuitePoiDefinition":
        """Create a POI definition from a JSON-like mapping."""

        return cls(
            poi_key=str(data.get("poi_key", "")),
            poi_type=str(data.get("poi_type", "")),
            source_column=str(data.get("source_column", "")),
            event_kind=str(data.get("event_kind", "")),
            event_value=data.get("event_value"),
            previous_value=data.get("previous_value"),
            threshold=(
                None if data.get("threshold") is None else float(data.get("threshold"))
            ),
            direction=_optional_str(data.get("direction")),
            display_name=_optional_str(data.get("display_name")),
            metadata=dict(data.get("metadata", {}) or {}),  # type: ignore[arg-type]
            schema_version=int(data.get("schema_version", ANALYSIS_SUITE_POI_FAMILY_SCHEMA_VERSION)),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": int(self.schema_version),
            "poi_key": self.poi_key,
            "poi_type": self.poi_type,
            "source_column": self.source_column,
            "event_kind": self.event_kind,
            "event_value": _json_safe_value(self.event_value),
            "previous_value": _json_safe_value(self.previous_value),
            "threshold": self.threshold,
            "direction": self.direction,
            "display_name": self.display_name,
            "metadata": _json_safe_mapping(self.metadata),
        }


@dataclass(frozen=True)
class AnalysisSuitePoiCondition:
    """
    JSON-safe context condition used by POI family membership previews.

    Conditions are evaluated as fixed row checks. ``lookback_bars`` addresses
    rows before the event row only; AS8 does not inspect future rows for family
    membership.
    """

    column: str
    operator: AnalysisSuitePoiConditionOperator | str
    value: JsonValue | None = None
    values: tuple[JsonValue, ...] = ()
    lookback_bars: int = 0
    required: bool = True
    label: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "column", str(self.column))
        object.__setattr__(self, "operator", str(self.operator))
        object.__setattr__(self, "values", tuple(self.values))
        object.__setattr__(self, "lookback_bars", int(self.lookback_bars))
        object.__setattr__(self, "required", bool(self.required))

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "AnalysisSuitePoiCondition":
        """Create a condition from a JSON-like mapping."""

        return cls(
            column=str(data.get("column", "")),
            operator=str(data.get("operator", "")),
            value=data.get("value"),
            values=tuple(data.get("values", ()) or ()),  # type: ignore[arg-type]
            lookback_bars=int(data.get("lookback_bars", 0)),
            required=bool(data.get("required", True)),
            label=_optional_str(data.get("label")),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "column": self.column,
            "operator": self.operator,
            "value": _json_safe_value(self.value),
            "values": [_json_safe_value(item) for item in self.values],
            "lookback_bars": int(self.lookback_bars),
            "required": bool(self.required),
            "label": self.label,
        }


@dataclass(frozen=True)
class AnalysisSuitePoiFamilyDefinition:
    """
    JSON-safe definition for one POI family preview.

    A family definition combines one base POI definition with same-row or
    fixed-lookback context conditions. It is evaluated in memory and is not
    persisted by AS8.
    """

    family_key: str
    display_name: str
    poi_definition: AnalysisSuitePoiDefinition
    conditions: tuple[AnalysisSuitePoiCondition, ...] = ()
    pre_event_window_bars: int = 0
    post_event_window_bars: int = 0
    metadata: Mapping[str, JsonValue] = field(default_factory=dict)
    schema_version: int = ANALYSIS_SUITE_POI_FAMILY_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "family_key", str(self.family_key))
        object.__setattr__(self, "display_name", str(self.display_name))
        object.__setattr__(self, "conditions", tuple(self.conditions))
        object.__setattr__(self, "pre_event_window_bars", int(self.pre_event_window_bars))
        object.__setattr__(self, "post_event_window_bars", int(self.post_event_window_bars))
        object.__setattr__(self, "metadata", dict(self.metadata))

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "AnalysisSuitePoiFamilyDefinition":
        """Create a family definition from a JSON-like mapping."""

        raw_poi = data.get("poi_definition")
        if isinstance(raw_poi, AnalysisSuitePoiDefinition):
            poi_definition = raw_poi
        elif isinstance(raw_poi, Mapping):
            poi_definition = AnalysisSuitePoiDefinition.from_dict(raw_poi)
        else:
            poi_definition = AnalysisSuitePoiDefinition(
                poi_key="",
                poi_type="",
                source_column="",
                event_kind="",
            )
        raw_conditions = data.get("conditions", ()) or ()
        conditions = tuple(
            condition
            if isinstance(condition, AnalysisSuitePoiCondition)
            else AnalysisSuitePoiCondition.from_dict(condition)
            for condition in raw_conditions  # type: ignore[union-attr]
        )
        return cls(
            family_key=str(data.get("family_key", "")),
            display_name=str(data.get("display_name", "")),
            poi_definition=poi_definition,
            conditions=conditions,
            pre_event_window_bars=int(data.get("pre_event_window_bars", 0)),
            post_event_window_bars=int(data.get("post_event_window_bars", 0)),
            metadata=dict(data.get("metadata", {}) or {}),  # type: ignore[arg-type]
            schema_version=int(data.get("schema_version", ANALYSIS_SUITE_POI_FAMILY_SCHEMA_VERSION)),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": int(self.schema_version),
            "family_key": self.family_key,
            "display_name": self.display_name,
            "poi_definition": self.poi_definition.to_dict(),
            "conditions": [condition.to_dict() for condition in self.conditions],
            "pre_event_window_bars": int(self.pre_event_window_bars),
            "post_event_window_bars": int(self.post_event_window_bars),
            "metadata": _json_safe_mapping(self.metadata),
        }


@dataclass(frozen=True)
class AnalysisSuitePoiOccurrence:
    """JSON-safe occurrence of one POI definition in an Analysis Database."""

    row_index: int
    ts_ms: int | None
    anchor_ts_ms: int | None
    event_ts_ms: int | None
    knowable_at_ts_ms: int | None
    poi_key: str
    poi_type: str
    source_column: str
    source_value: JsonValue
    metadata: Mapping[str, JsonValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "row_index", int(self.row_index))
        object.__setattr__(self, "metadata", dict(self.metadata))

    def to_dict(self) -> dict[str, object]:
        return {
            "row_index": int(self.row_index),
            "ts_ms": self.ts_ms,
            "anchor_ts_ms": self.anchor_ts_ms,
            "event_ts_ms": self.event_ts_ms,
            "knowable_at_ts_ms": self.knowable_at_ts_ms,
            "poi_key": self.poi_key,
            "poi_type": self.poi_type,
            "source_column": self.source_column,
            "source_value": _json_safe_value(self.source_value),
            "metadata": _json_safe_mapping(self.metadata),
        }


@dataclass(frozen=True)
class AnalysisSuitePoiFamilyMembership:
    """
    JSON-safe membership evaluation for one POI occurrence.

    ``matched`` means all required conditions matched. Optional condition
    results are reported without preventing membership.
    """

    occurrence: AnalysisSuitePoiOccurrence
    matched: bool
    condition_results: tuple[Mapping[str, JsonValue], ...] = ()
    blockers: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "condition_results", tuple(self.condition_results))
        object.__setattr__(self, "blockers", tuple(str(item) for item in self.blockers))
        object.__setattr__(self, "warnings", tuple(str(item) for item in self.warnings))

    def to_dict(self) -> dict[str, object]:
        return {
            "occurrence": self.occurrence.to_dict(),
            "matched": bool(self.matched),
            "condition_results": [
                _json_safe_mapping(result) for result in self.condition_results
            ],
            "blockers": list(self.blockers),
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class AnalysisSuitePoiOccurrencePreviewReport:
    """JSON-safe bounded preview report for POI occurrences."""

    database_id: str
    display_name: str
    exchange: str
    market_type: str
    symbol: str
    timeframe: str
    dataframe_path: str | None
    manifest_path: str | None
    readiness_status: AnalysisSuiteDatasetReadinessStatus | str
    strict_ready: bool
    can_preview: bool
    status: AnalysisSuitePoiPreviewStatus
    poi_definition: AnalysisSuitePoiDefinition
    row_count: int | None
    occurrence_count: int
    first_occurrence_ts_ms: int | None
    last_occurrence_ts_ms: int | None
    requested_sample_limit: int
    sample_limit: int
    sample_occurrences: tuple[AnalysisSuitePoiOccurrence, ...]
    warnings: tuple[str, ...] = ()
    blockers: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "sample_occurrences", tuple(self.sample_occurrences))
        object.__setattr__(self, "warnings", tuple(str(item) for item in self.warnings))
        object.__setattr__(self, "blockers", tuple(str(item) for item in self.blockers))
        object.__setattr__(self, "errors", tuple(str(item) for item in self.errors))

    def to_dict(self) -> dict[str, object]:
        return {
            "database_id": self.database_id,
            "display_name": self.display_name,
            "exchange": self.exchange,
            "market_type": self.market_type,
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "dataframe_path": self.dataframe_path,
            "manifest_path": self.manifest_path,
            "readiness_status": self.readiness_status,
            "strict_ready": bool(self.strict_ready),
            "can_preview": bool(self.can_preview),
            "status": self.status,
            "poi_definition": self.poi_definition.to_dict(),
            "row_count": self.row_count,
            "occurrence_count": int(self.occurrence_count),
            "first_occurrence_ts_ms": self.first_occurrence_ts_ms,
            "last_occurrence_ts_ms": self.last_occurrence_ts_ms,
            "requested_sample_limit": int(self.requested_sample_limit),
            "sample_limit": int(self.sample_limit),
            "sample_occurrences": [
                occurrence.to_dict() for occurrence in self.sample_occurrences
            ],
            "warnings": list(self.warnings),
            "blockers": list(self.blockers),
            "errors": list(self.errors),
        }


@dataclass(frozen=True)
class AnalysisSuitePoiFamilyPreviewReport:
    """JSON-safe bounded preview report for POI family membership."""

    database_id: str
    display_name: str
    exchange: str
    market_type: str
    symbol: str
    timeframe: str
    dataframe_path: str | None
    manifest_path: str | None
    readiness_status: AnalysisSuiteDatasetReadinessStatus | str
    strict_ready: bool
    can_preview: bool
    status: AnalysisSuitePoiPreviewStatus
    family_definition: AnalysisSuitePoiFamilyDefinition
    row_count: int | None
    occurrence_count: int
    matched_count: int
    unmatched_count: int
    first_occurrence_ts_ms: int | None
    last_occurrence_ts_ms: int | None
    requested_sample_limit: int
    sample_limit: int
    sample_occurrences: tuple[AnalysisSuitePoiOccurrence, ...]
    sample_memberships: tuple[AnalysisSuitePoiFamilyMembership, ...]
    warnings: tuple[str, ...] = ()
    blockers: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "sample_occurrences", tuple(self.sample_occurrences))
        object.__setattr__(self, "sample_memberships", tuple(self.sample_memberships))
        object.__setattr__(self, "warnings", tuple(str(item) for item in self.warnings))
        object.__setattr__(self, "blockers", tuple(str(item) for item in self.blockers))
        object.__setattr__(self, "errors", tuple(str(item) for item in self.errors))

    def to_dict(self) -> dict[str, object]:
        return {
            "database_id": self.database_id,
            "display_name": self.display_name,
            "exchange": self.exchange,
            "market_type": self.market_type,
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "dataframe_path": self.dataframe_path,
            "manifest_path": self.manifest_path,
            "readiness_status": self.readiness_status,
            "strict_ready": bool(self.strict_ready),
            "can_preview": bool(self.can_preview),
            "status": self.status,
            "family_definition": self.family_definition.to_dict(),
            "row_count": self.row_count,
            "occurrence_count": int(self.occurrence_count),
            "matched_count": int(self.matched_count),
            "unmatched_count": int(self.unmatched_count),
            "first_occurrence_ts_ms": self.first_occurrence_ts_ms,
            "last_occurrence_ts_ms": self.last_occurrence_ts_ms,
            "requested_sample_limit": int(self.requested_sample_limit),
            "sample_limit": int(self.sample_limit),
            "sample_occurrences": [
                occurrence.to_dict() for occurrence in self.sample_occurrences
            ],
            "sample_memberships": [
                membership.to_dict() for membership in self.sample_memberships
            ],
            "warnings": list(self.warnings),
            "blockers": list(self.blockers),
            "errors": list(self.errors),
        }


class AnalysisSuitePoiFamilyPlanner:
    """
    Build read-only POI occurrence and family membership previews.

    The planner gates access through AS1 readiness or AS7 diagnostic reports,
    validates POI and family definitions against Analysis Database manifest
    metadata, and reads only required dataframe columns for bounded reports.
    It does not create stores, persist definitions, or mutate Analysis Database
    files.
    """

    def __init__(
        self,
        *,
        historical_root: Path,
        store: AnalysisDatabaseStore | None = None,
        readiness_service: _ReadinessService | None = None,
    ) -> None:
        self._historical_root = Path(historical_root)
        self._store = store or AnalysisDatabaseStore(historical_root=self._historical_root)
        self._readiness_service = readiness_service or AnalysisSuiteDatasetReadinessService(
            historical_root=self._historical_root,
            store=self._store,
        )

    def preview_poi_occurrences(
        self,
        *,
        market: MarketId,
        database_id: str,
        poi_definition: AnalysisSuitePoiDefinition | Mapping[str, object],
        sample_limit: int | None = None,
        readiness_report: AnalysisSuiteDatasetReadinessReport | None = None,
        diagnostic_report: AnalysisSuiteDiagnosticReport | None = None,
    ) -> AnalysisSuitePoiOccurrencePreviewReport:
        """Return a bounded read-only preview for one POI definition."""

        definition = _coerce_poi_definition(poi_definition)
        requested_limit, effective_limit, limit_warnings = _sample_limit_state(sample_limit)

        try:
            context = self._context(
                market=market,
                database_id=database_id,
                readiness_report=readiness_report,
                diagnostic_report=diagnostic_report,
                limit_warnings=limit_warnings,
            )
        except Exception as exc:
            context = _synthetic_context(
                market=market,
                database_id=database_id,
                store=self._store,
                errors=(f"{type(exc).__name__}: {exc}",),
                blockers=("readiness_check_failed",),
            )
            return _occurrence_report(
                context=context,
                status="error",
                definition=definition,
                row_count=None,
                occurrences=(),
                requested_sample_limit=requested_limit,
                sample_limit=effective_limit,
            )

        if _context_blocks_preview(context):
            return _occurrence_report(
                context=context,
                status=_context_status(context),
                definition=definition,
                row_count=None,
                occurrences=(),
                requested_sample_limit=requested_limit,
                sample_limit=effective_limit,
            )

        try:
            manifest = self._store.load_manifest(market=market, database_id=database_id)
            blockers, warnings = _validate_poi_definition(
                definition,
                manifest=manifest,
            )
            context = context.with_added(warnings=warnings, blockers=blockers)
            if blockers:
                return _occurrence_report(
                    context=context,
                    status="blocked",
                    definition=definition,
                    row_count=None,
                    occurrences=(),
                    requested_sample_limit=requested_limit,
                    sample_limit=effective_limit,
                )

            frame, physical_warnings, physical_blockers = _read_event_dataframe(
                dataframe_path=Path(context.dataframe_path or ""),
                required_columns=("ts_ms", definition.source_column),
                optional_columns=(),
            )
            context = context.with_added(
                warnings=physical_warnings,
                blockers=physical_blockers,
            )
            if physical_blockers:
                return _occurrence_report(
                    context=context,
                    status="blocked",
                    definition=definition,
                    row_count=None,
                    occurrences=(),
                    requested_sample_limit=requested_limit,
                    sample_limit=effective_limit,
                )

            occurrences, occurrence_warnings = _detect_occurrences(
                frame=frame,
                definition=definition,
                manifest=manifest,
            )
            context = context.with_added(warnings=occurrence_warnings)
            if not occurrences:
                context = context.with_added(warnings=("no_poi_occurrences",))
            return _occurrence_report(
                context=context,
                status=_context_status(context),
                definition=definition,
                row_count=len(frame),
                occurrences=occurrences,
                requested_sample_limit=requested_limit,
                sample_limit=effective_limit,
            )
        except Exception as exc:
            context = context.with_added(errors=(f"{type(exc).__name__}: {exc}",))
            return _occurrence_report(
                context=context,
                status="error",
                definition=definition,
                row_count=None,
                occurrences=(),
                requested_sample_limit=requested_limit,
                sample_limit=effective_limit,
            )

    def preview_family(
        self,
        *,
        market: MarketId,
        database_id: str,
        family_definition: AnalysisSuitePoiFamilyDefinition | Mapping[str, object],
        sample_limit: int | None = None,
        readiness_report: AnalysisSuiteDatasetReadinessReport | None = None,
        diagnostic_report: AnalysisSuiteDiagnosticReport | None = None,
    ) -> AnalysisSuitePoiFamilyPreviewReport:
        """Return a bounded read-only preview for one POI family definition."""

        definition = _coerce_family_definition(family_definition)
        requested_limit, effective_limit, limit_warnings = _sample_limit_state(sample_limit)

        try:
            context = self._context(
                market=market,
                database_id=database_id,
                readiness_report=readiness_report,
                diagnostic_report=diagnostic_report,
                limit_warnings=limit_warnings,
            )
        except Exception as exc:
            context = _synthetic_context(
                market=market,
                database_id=database_id,
                store=self._store,
                errors=(f"{type(exc).__name__}: {exc}",),
                blockers=("readiness_check_failed",),
            )
            return _family_report(
                context=context,
                status="error",
                definition=definition,
                row_count=None,
                occurrences=(),
                memberships=(),
                requested_sample_limit=requested_limit,
                sample_limit=effective_limit,
            )

        if _context_blocks_preview(context):
            return _family_report(
                context=context,
                status=_context_status(context),
                definition=definition,
                row_count=None,
                occurrences=(),
                memberships=(),
                requested_sample_limit=requested_limit,
                sample_limit=effective_limit,
            )

        try:
            manifest = self._store.load_manifest(market=market, database_id=database_id)
            blockers, warnings = _validate_family_definition(
                definition,
                manifest=manifest,
            )
            context = context.with_added(warnings=warnings, blockers=blockers)
            if blockers:
                return _family_report(
                    context=context,
                    status="blocked",
                    definition=definition,
                    row_count=None,
                    occurrences=(),
                    memberships=(),
                    requested_sample_limit=requested_limit,
                    sample_limit=effective_limit,
                )

            required_columns = ("ts_ms", definition.poi_definition.source_column) + tuple(
                condition.column for condition in definition.conditions if condition.required
            )
            optional_columns = tuple(
                condition.column for condition in definition.conditions if not condition.required
            )
            frame, physical_warnings, physical_blockers = _read_event_dataframe(
                dataframe_path=Path(context.dataframe_path or ""),
                required_columns=required_columns,
                optional_columns=optional_columns,
            )
            context = context.with_added(
                warnings=physical_warnings,
                blockers=physical_blockers,
            )
            if physical_blockers:
                return _family_report(
                    context=context,
                    status="blocked",
                    definition=definition,
                    row_count=None,
                    occurrences=(),
                    memberships=(),
                    requested_sample_limit=requested_limit,
                    sample_limit=effective_limit,
                )

            occurrences, occurrence_warnings = _detect_occurrences(
                frame=frame,
                definition=definition.poi_definition,
                manifest=manifest,
            )
            memberships = _evaluate_memberships(
                frame=frame,
                occurrences=occurrences,
                family_definition=definition,
            )
            context = context.with_added(warnings=occurrence_warnings)
            if not occurrences:
                context = context.with_added(warnings=("no_poi_occurrences",))
            if occurrences and not any(membership.matched for membership in memberships):
                context = context.with_added(warnings=("no_family_memberships",))
            if any(membership.blockers for membership in memberships):
                context = context.with_added(warnings=("membership_condition_blockers_present",))
            return _family_report(
                context=context,
                status=_context_status(context),
                definition=definition,
                row_count=len(frame),
                occurrences=occurrences,
                memberships=memberships,
                requested_sample_limit=requested_limit,
                sample_limit=effective_limit,
            )
        except Exception as exc:
            context = context.with_added(errors=(f"{type(exc).__name__}: {exc}",))
            return _family_report(
                context=context,
                status="error",
                definition=definition,
                row_count=None,
                occurrences=(),
                memberships=(),
                requested_sample_limit=requested_limit,
                sample_limit=effective_limit,
            )

    def validate_family_definition(
        self,
        *,
        market: MarketId,
        database_id: str,
        family_definition: AnalysisSuitePoiFamilyDefinition | Mapping[str, object],
    ) -> dict[str, object]:
        """
        Validate a POI family definition against Analysis Database metadata.

        The method reads the manifest only. It does not read dataframe values or
        persist validation output.
        """

        definition = _coerce_family_definition(family_definition)
        try:
            manifest = self._store.load_manifest(market=market, database_id=database_id)
            blockers, warnings = _validate_family_definition(definition, manifest=manifest)
            return {
                "status": _status(warnings, blockers, ()),
                "blockers": list(blockers),
                "warnings": list(warnings),
                "errors": [],
            }
        except Exception as exc:
            return {
                "status": "error",
                "blockers": ["manifest_metadata_unavailable"],
                "warnings": [],
                "errors": [f"{type(exc).__name__}: {exc}"],
            }

    def _context(
        self,
        *,
        market: MarketId,
        database_id: str,
        readiness_report: AnalysisSuiteDatasetReadinessReport | None,
        diagnostic_report: AnalysisSuiteDiagnosticReport | None,
        limit_warnings: tuple[str, ...],
    ) -> "_PlannerContext":
        if diagnostic_report is not None:
            context = _context_from_diagnostic(diagnostic_report)
        elif readiness_report is not None:
            context = _context_from_readiness(readiness_report)
        else:
            context = _context_from_readiness(
                self._readiness_service.readiness_for_database(
                    market=market,
                    database_id=database_id,
                )
            )
        if not context.dataframe_path:
            context = context.with_added(
                dataframe_path=str(
                    self._store.dataframe_path(market=market, database_id=database_id)
                )
            )
        if not context.manifest_path:
            context = context.with_added(
                manifest_path=str(
                    self._store.manifest_path(market=market, database_id=database_id)
                )
            )
        return context.with_added(warnings=limit_warnings)


@dataclass(frozen=True)
class _PlannerContext:
    database_id: str
    display_name: str
    exchange: str
    market_type: str
    symbol: str
    timeframe: str
    dataframe_path: str | None
    manifest_path: str | None
    readiness_status: str
    strict_ready: bool
    can_preview: bool
    warnings: tuple[str, ...]
    blockers: tuple[str, ...]
    errors: tuple[str, ...]

    def with_added(
        self,
        *,
        warnings: Iterable[str] = (),
        blockers: Iterable[str] = (),
        errors: Iterable[str] = (),
        dataframe_path: str | None = None,
        manifest_path: str | None = None,
    ) -> "_PlannerContext":
        return _PlannerContext(
            database_id=self.database_id,
            display_name=self.display_name,
            exchange=self.exchange,
            market_type=self.market_type,
            symbol=self.symbol,
            timeframe=self.timeframe,
            dataframe_path=self.dataframe_path if dataframe_path is None else dataframe_path,
            manifest_path=self.manifest_path if manifest_path is None else manifest_path,
            readiness_status=self.readiness_status,
            strict_ready=self.strict_ready,
            can_preview=self.can_preview,
            warnings=_dedupe(self.warnings + tuple(str(item) for item in warnings)),
            blockers=_dedupe(self.blockers + tuple(str(item) for item in blockers)),
            errors=_dedupe(self.errors + tuple(str(item) for item in errors)),
        )


def _context_from_readiness(readiness: AnalysisSuiteDatasetReadinessReport) -> _PlannerContext:
    warnings = tuple(str(item) for item in getattr(readiness, "warnings", ()))
    blockers = tuple(str(item) for item in getattr(readiness, "blockers", ()))
    errors = tuple(str(item) for item in getattr(readiness, "errors", ()))
    if not bool(getattr(readiness, "strict_ready", False)):
        warnings += ("dataset_not_strict_ready",)
    if not bool(getattr(readiness, "can_preview", False)):
        blockers += ("dataset_not_previewable",)
    return _PlannerContext(
        database_id=str(getattr(readiness, "database_id", "")),
        display_name=str(getattr(readiness, "display_name", "")),
        exchange=str(getattr(readiness, "exchange", "")),
        market_type=str(getattr(readiness, "market_type", "")),
        symbol=str(getattr(readiness, "symbol", "")),
        timeframe=str(getattr(readiness, "timeframe", "")),
        dataframe_path=_optional_str(getattr(readiness, "dataframe_path", None)),
        manifest_path=_optional_str(getattr(readiness, "manifest_path", None)),
        readiness_status=str(getattr(readiness, "readiness_status", "")),
        strict_ready=bool(getattr(readiness, "strict_ready", False)),
        can_preview=bool(getattr(readiness, "can_preview", False)),
        warnings=_dedupe(warnings),
        blockers=_dedupe(blockers),
        errors=_dedupe(errors),
    )


def _context_from_diagnostic(report: AnalysisSuiteDiagnosticReport) -> _PlannerContext:
    warnings = tuple(str(item) for item in getattr(report, "warnings", ()))
    blockers = tuple(str(item) for item in getattr(report, "blockers", ()))
    errors = tuple(str(item) for item in getattr(report, "errors", ()))
    status = str(getattr(report, "status", ""))
    if status in {"blocked", "error"}:
        blockers += (f"diagnostic_report_not_acceptable: {status}",)
    elif status == "warning":
        warnings += ("diagnostic_report_warning",)
    if bool(getattr(report, "has_leakage_blockers", False)):
        blockers += ("diagnostic_leakage_blockers_present",)
    if not bool(getattr(report, "can_preview", False)):
        blockers += ("dataset_not_previewable",)
    if not bool(getattr(report, "strict_ready", False)):
        warnings += ("dataset_not_strict_ready",)
    return _PlannerContext(
        database_id=str(getattr(report, "database_id", "")),
        display_name=str(getattr(report, "display_name", "")),
        exchange=str(getattr(report, "exchange", "")),
        market_type=str(getattr(report, "market_type", "")),
        symbol=str(getattr(report, "symbol", "")),
        timeframe=str(getattr(report, "timeframe", "")),
        dataframe_path=_optional_str(getattr(report, "dataframe_path", None)),
        manifest_path=_optional_str(getattr(report, "manifest_path", None)),
        readiness_status=str(getattr(report, "readiness_status", "")),
        strict_ready=bool(getattr(report, "strict_ready", False)),
        can_preview=bool(getattr(report, "can_preview", False)),
        warnings=_dedupe(warnings),
        blockers=_dedupe(blockers),
        errors=_dedupe(errors),
    )


def _synthetic_context(
    *,
    market: MarketId,
    database_id: str,
    store: AnalysisDatabaseStore,
    errors: Iterable[str],
    blockers: Iterable[str],
) -> _PlannerContext:
    return _PlannerContext(
        database_id=str(database_id),
        display_name=str(database_id),
        exchange=market.exchange,
        market_type=market.market_type,
        symbol=market.symbol,
        timeframe=market.timeframe,
        dataframe_path=str(store.dataframe_path(market=market, database_id=database_id)),
        manifest_path=str(store.manifest_path(market=market, database_id=database_id)),
        readiness_status="error",
        strict_ready=False,
        can_preview=False,
        warnings=(),
        blockers=tuple(str(item) for item in blockers),
        errors=tuple(str(item) for item in errors),
    )


def _coerce_poi_definition(
    definition: AnalysisSuitePoiDefinition | Mapping[str, object],
) -> AnalysisSuitePoiDefinition:
    if isinstance(definition, AnalysisSuitePoiDefinition):
        return definition
    return AnalysisSuitePoiDefinition.from_dict(definition)


def _coerce_family_definition(
    definition: AnalysisSuitePoiFamilyDefinition | Mapping[str, object],
) -> AnalysisSuitePoiFamilyDefinition:
    if isinstance(definition, AnalysisSuitePoiFamilyDefinition):
        return definition
    return AnalysisSuitePoiFamilyDefinition.from_dict(definition)


def _validate_poi_definition(
    definition: AnalysisSuitePoiDefinition,
    *,
    manifest: AnalysisDatabaseManifest,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    blockers: list[str] = []
    warnings: list[str] = []
    if definition.schema_version != ANALYSIS_SUITE_POI_FAMILY_SCHEMA_VERSION:
        blockers.append("unsupported_poi_definition_schema")
    if not definition.poi_key:
        blockers.append("poi_key_required")
    if not definition.poi_type:
        blockers.append("poi_type_required")
    if not definition.source_column:
        blockers.append("poi_source_column_required")
    if definition.event_kind not in _SUPPORTED_EVENT_KINDS:
        blockers.append(f"unsupported_poi_event_kind: {definition.event_kind}")
    if definition.event_kind in {"value_equals", "transition"} and definition.event_value is None:
        blockers.append(f"{definition.event_kind}_requires_event_value")
    columns = _manifest_columns(manifest)
    source_column = columns.get(definition.source_column)
    if definition.source_column and source_column is None:
        blockers.append(f"poi_source_column_missing_from_manifest: {definition.source_column}")
    elif source_column is not None:
        blockers.extend(
            _column_input_blockers(
                source_column,
                purpose="poi_source",
            )
        )
        warnings.extend(_column_input_warnings(source_column, purpose="poi_source"))
    return _dedupe(blockers), _dedupe(warnings)


def _validate_family_definition(
    definition: AnalysisSuitePoiFamilyDefinition,
    *,
    manifest: AnalysisDatabaseManifest,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    blockers: list[str] = []
    warnings: list[str] = []
    if definition.schema_version != ANALYSIS_SUITE_POI_FAMILY_SCHEMA_VERSION:
        blockers.append("unsupported_family_definition_schema")
    if not definition.family_key:
        blockers.append("family_key_required")
    if not definition.display_name:
        warnings.append("family_display_name_missing")
    if definition.pre_event_window_bars < 0:
        blockers.append("pre_event_window_bars_must_be_non_negative")
    if definition.post_event_window_bars < 0:
        blockers.append("post_event_window_bars_must_be_non_negative")

    poi_blockers, poi_warnings = _validate_poi_definition(
        definition.poi_definition,
        manifest=manifest,
    )
    blockers.extend(poi_blockers)
    warnings.extend(poi_warnings)

    columns = _manifest_columns(manifest)
    for condition in definition.conditions:
        if condition.operator not in _SUPPORTED_OPERATORS:
            blockers.append(f"unsupported_condition_operator: {condition.operator}")
        if not condition.column:
            blockers.append("condition_column_required")
        if condition.lookback_bars < 0:
            blockers.append(f"condition_lookback_must_be_non_negative: {condition.column}")
        if condition.operator in {"in", "not_in"} and not condition.values:
            blockers.append(f"{condition.operator}_requires_values: {condition.column}")
        column = columns.get(condition.column)
        if condition.column and column is None:
            reason = f"condition_column_missing_from_manifest: {condition.column}"
            if condition.required:
                blockers.append(reason)
            else:
                warnings.append(reason)
            continue
        if column is not None:
            semantic_blockers = _column_input_blockers(column, purpose="condition")
            semantic_warnings = _column_input_warnings(column, purpose="condition")
            if condition.required:
                blockers.extend(semantic_blockers)
            else:
                warnings.extend(semantic_blockers)
            warnings.extend(semantic_warnings)
    return _dedupe(blockers), _dedupe(warnings)


def _manifest_columns(
    manifest: AnalysisDatabaseManifest,
) -> dict[str, AnalysisDatabaseColumn]:
    columns = tuple(manifest.base_columns) + tuple(manifest.feature_columns)
    return {str(column.db_column_name): column for column in columns}


def _column_input_blockers(
    column: AnalysisDatabaseColumn,
    *,
    purpose: str,
) -> tuple[str, ...]:
    column_name = str(column.db_column_name)
    blockers: list[str] = []
    if column_name == "ts_ms":
        blockers.append(f"{purpose}_cannot_use_alignment_key")
    if _metadata_value(column.metadata, "leakage_role") == "target_only":
        blockers.append(f"{purpose}_target_only_column_forbidden: {column_name}")
    if _metadata_bool(column.metadata, "future_derived", False):
        blockers.append(f"{purpose}_future_derived_column_forbidden: {column_name}")
    if _metadata_bool(column.metadata, "feature_eligible", None) is False:
        blockers.append(f"{purpose}_feature_eligible_false: {column_name}")
    if column.analysis_usable is False:
        blockers.append(f"{purpose}_column_not_analysis_usable: {column_name}")
    if column.role == "feature" and not column.source_id:
        blockers.append(f"{purpose}_feature_source_missing: {column_name}")
    return tuple(blockers)


def _column_input_warnings(
    column: AnalysisDatabaseColumn,
    *,
    purpose: str,
) -> tuple[str, ...]:
    if column.role == "feature" and column.analysis_usable is None:
        return (f"{purpose}_semantic_eligibility_not_confirmed: {column.db_column_name}",)
    return ()


def _read_event_dataframe(
    *,
    dataframe_path: Path,
    required_columns: Sequence[str],
    optional_columns: Sequence[str],
) -> tuple[pd.DataFrame, tuple[str, ...], tuple[str, ...]]:
    if not dataframe_path.exists():
        return pd.DataFrame(), (), (f"dataframe_missing: {dataframe_path}",)
    header = tuple(str(column) for column in pd.read_csv(dataframe_path, nrows=0).columns)
    header_set = set(header)
    required = tuple(dict.fromkeys(str(column) for column in required_columns))
    optional = tuple(dict.fromkeys(str(column) for column in optional_columns))
    missing_required = tuple(column for column in required if column not in header_set)
    missing_optional = tuple(column for column in optional if column not in header_set)
    blockers = tuple(f"dataframe_required_column_missing: {column}" for column in missing_required)
    warnings = tuple(f"dataframe_optional_column_missing: {column}" for column in missing_optional)
    if blockers:
        return pd.DataFrame(), warnings, blockers
    usecols = tuple(column for column in required + optional if column in header_set)
    frame = pd.read_csv(dataframe_path, usecols=list(dict.fromkeys(usecols)))
    return frame, warnings, ()


def _detect_occurrences(
    *,
    frame: pd.DataFrame,
    definition: AnalysisSuitePoiDefinition,
    manifest: AnalysisDatabaseManifest,
) -> tuple[tuple[AnalysisSuitePoiOccurrence, ...], tuple[str, ...]]:
    occurrences: list[AnalysisSuitePoiOccurrence] = []
    warnings: list[str] = []
    ts_values = tuple(frame["ts_ms"].tolist()) if "ts_ms" in frame.columns else ()
    values = tuple(frame[definition.source_column].tolist())
    source_column = _manifest_columns(manifest).get(definition.source_column)
    source_metadata = _source_metadata_for_occurrence(source_column)
    confirmation_offset = _optional_int(definition.metadata.get("confirmation_offset_bars"))
    for row_index, value in enumerate(values):
        previous = None if row_index == 0 else values[row_index - 1]
        if not _event_matches(definition, value=value, previous=previous):
            continue
        ts_ms = _optional_int(ts_values[row_index]) if row_index < len(ts_values) else None
        knowable_at_ts_ms = _knowable_ts_ms(
            ts_values=ts_values,
            row_index=row_index,
            confirmation_offset=confirmation_offset,
        )
        if confirmation_offset is not None and knowable_at_ts_ms is None:
            warnings.append("confirmation_offset_exceeds_dataframe")
        metadata = {
            **source_metadata,
            "event_kind": definition.event_kind,
            "current_value": _json_safe_value(value),
            "previous_value": _json_safe_value(previous),
        }
        occurrences.append(
            AnalysisSuitePoiOccurrence(
                row_index=row_index,
                ts_ms=ts_ms,
                anchor_ts_ms=ts_ms,
                event_ts_ms=ts_ms,
                knowable_at_ts_ms=knowable_at_ts_ms,
                poi_key=definition.poi_key,
                poi_type=definition.poi_type,
                source_column=definition.source_column,
                source_value=_json_safe_value(value),
                metadata=metadata,
            )
        )
    return tuple(occurrences), _dedupe(warnings)


def _event_matches(
    definition: AnalysisSuitePoiDefinition,
    *,
    value: object,
    previous: object,
) -> bool:
    if definition.event_kind == "sparse_event":
        return _truthy_event_value(value)
    if definition.event_kind == "boolean_true":
        return _bool_true(value)
    if definition.event_kind == "value_equals":
        return _values_equal(value, definition.event_value)
    if definition.event_kind == "transition":
        if previous is None or _is_nullish(previous):
            return False
        current_matches = _values_equal(value, definition.event_value)
        if not current_matches:
            return False
        if definition.previous_value is not None:
            return _values_equal(previous, definition.previous_value)
        return not _values_equal(previous, definition.event_value)
    return False


def _evaluate_memberships(
    *,
    frame: pd.DataFrame,
    occurrences: tuple[AnalysisSuitePoiOccurrence, ...],
    family_definition: AnalysisSuitePoiFamilyDefinition,
) -> tuple[AnalysisSuitePoiFamilyMembership, ...]:
    memberships: list[AnalysisSuitePoiFamilyMembership] = []
    for occurrence in occurrences:
        results: list[dict[str, object]] = []
        blockers: list[str] = []
        warnings: list[str] = []
        required_matches: list[bool] = []
        for condition in family_definition.conditions:
            result = _evaluate_condition(
                frame=frame,
                occurrence=occurrence,
                condition=condition,
            )
            results.append(result)
            if condition.required:
                required_matches.append(bool(result["matched"]))
                blockers.extend(str(item) for item in result.get("blockers", ()))  # type: ignore[arg-type]
            warnings.extend(str(item) for item in result.get("warnings", ()))  # type: ignore[arg-type]
        matched = all(required_matches) if required_matches else True
        if blockers:
            matched = False
        memberships.append(
            AnalysisSuitePoiFamilyMembership(
                occurrence=occurrence,
                matched=matched,
                condition_results=tuple(results),
                blockers=tuple(dict.fromkeys(blockers)),
                warnings=tuple(dict.fromkeys(warnings)),
            )
        )
    return tuple(memberships)


def _evaluate_condition(
    *,
    frame: pd.DataFrame,
    occurrence: AnalysisSuitePoiOccurrence,
    condition: AnalysisSuitePoiCondition,
) -> dict[str, object]:
    condition_index = occurrence.row_index - condition.lookback_bars
    blockers: list[str] = []
    warnings: list[str] = []
    if condition_index < 0:
        reason = f"condition_lookback_unavailable: {condition.column}"
        if condition.required:
            blockers.append(reason)
        else:
            warnings.append(reason)
        return _condition_result(
            condition=condition,
            row_index=condition_index,
            ts_ms=None,
            actual_value=None,
            matched=False,
            blockers=blockers,
            warnings=warnings,
        )
    if condition.column not in frame.columns:
        reason = f"condition_column_missing_from_dataframe: {condition.column}"
        if condition.required:
            blockers.append(reason)
        else:
            warnings.append(reason)
        return _condition_result(
            condition=condition,
            row_index=condition_index,
            ts_ms=None,
            actual_value=None,
            matched=False,
            blockers=blockers,
            warnings=warnings,
        )
    actual_value = frame.iloc[condition_index][condition.column]
    ts_ms = _optional_int(frame.iloc[condition_index]["ts_ms"]) if "ts_ms" in frame.columns else None
    matched = _condition_matches(condition, actual_value)
    return _condition_result(
        condition=condition,
        row_index=condition_index,
        ts_ms=ts_ms,
        actual_value=actual_value,
        matched=matched,
        blockers=blockers,
        warnings=warnings,
    )


def _condition_result(
    *,
    condition: AnalysisSuitePoiCondition,
    row_index: int,
    ts_ms: int | None,
    actual_value: object,
    matched: bool,
    blockers: Sequence[str],
    warnings: Sequence[str],
) -> dict[str, object]:
    return {
        "column": condition.column,
        "operator": condition.operator,
        "value": _json_safe_value(condition.value),
        "values": [_json_safe_value(item) for item in condition.values],
        "lookback_bars": int(condition.lookback_bars),
        "required": bool(condition.required),
        "label": condition.label,
        "row_index": int(row_index),
        "ts_ms": ts_ms,
        "actual_value": _json_safe_value(actual_value),
        "matched": bool(matched),
        "blockers": list(blockers),
        "warnings": list(warnings),
    }


def _condition_matches(condition: AnalysisSuitePoiCondition, actual_value: object) -> bool:
    operator = condition.operator
    if operator == "is_null":
        return _is_nullish(actual_value)
    if operator == "not_null":
        return not _is_nullish(actual_value)
    if operator == "equals":
        return _values_equal(actual_value, condition.value)
    if operator == "not_equals":
        return not _values_equal(actual_value, condition.value)
    if operator == "in":
        return any(_values_equal(actual_value, expected) for expected in condition.values)
    if operator == "not_in":
        return not any(_values_equal(actual_value, expected) for expected in condition.values)
    left = _to_float(actual_value)
    right = _to_float(condition.value)
    if left is None or right is None:
        return False
    if operator == "gt":
        return left > right
    if operator == "gte":
        return left >= right
    if operator == "lt":
        return left < right
    if operator == "lte":
        return left <= right
    return False


def _occurrence_report(
    *,
    context: _PlannerContext,
    status: AnalysisSuitePoiPreviewStatus,
    definition: AnalysisSuitePoiDefinition,
    row_count: int | None,
    occurrences: tuple[AnalysisSuitePoiOccurrence, ...],
    requested_sample_limit: int,
    sample_limit: int,
) -> AnalysisSuitePoiOccurrencePreviewReport:
    return AnalysisSuitePoiOccurrencePreviewReport(
        database_id=context.database_id,
        display_name=context.display_name,
        exchange=context.exchange,
        market_type=context.market_type,
        symbol=context.symbol,
        timeframe=context.timeframe,
        dataframe_path=context.dataframe_path,
        manifest_path=context.manifest_path,
        readiness_status=context.readiness_status,
        strict_ready=context.strict_ready,
        can_preview=context.can_preview,
        status=status,
        poi_definition=definition,
        row_count=row_count,
        occurrence_count=len(occurrences),
        first_occurrence_ts_ms=_first_ts(occurrences),
        last_occurrence_ts_ms=_last_ts(occurrences),
        requested_sample_limit=requested_sample_limit,
        sample_limit=sample_limit,
        sample_occurrences=tuple(occurrences[:sample_limit]),
        warnings=context.warnings,
        blockers=context.blockers,
        errors=context.errors,
    )


def _family_report(
    *,
    context: _PlannerContext,
    status: AnalysisSuitePoiPreviewStatus,
    definition: AnalysisSuitePoiFamilyDefinition,
    row_count: int | None,
    occurrences: tuple[AnalysisSuitePoiOccurrence, ...],
    memberships: tuple[AnalysisSuitePoiFamilyMembership, ...],
    requested_sample_limit: int,
    sample_limit: int,
) -> AnalysisSuitePoiFamilyPreviewReport:
    matched_count = sum(1 for membership in memberships if membership.matched)
    return AnalysisSuitePoiFamilyPreviewReport(
        database_id=context.database_id,
        display_name=context.display_name,
        exchange=context.exchange,
        market_type=context.market_type,
        symbol=context.symbol,
        timeframe=context.timeframe,
        dataframe_path=context.dataframe_path,
        manifest_path=context.manifest_path,
        readiness_status=context.readiness_status,
        strict_ready=context.strict_ready,
        can_preview=context.can_preview,
        status=status,
        family_definition=definition,
        row_count=row_count,
        occurrence_count=len(occurrences),
        matched_count=matched_count,
        unmatched_count=max(0, len(occurrences) - matched_count),
        first_occurrence_ts_ms=_first_ts(occurrences),
        last_occurrence_ts_ms=_last_ts(occurrences),
        requested_sample_limit=requested_sample_limit,
        sample_limit=sample_limit,
        sample_occurrences=tuple(occurrences[:sample_limit]),
        sample_memberships=tuple(memberships[:sample_limit]),
        warnings=context.warnings,
        blockers=context.blockers,
        errors=context.errors,
    )


def _sample_limit_state(limit: int | None) -> tuple[int, int, tuple[str, ...]]:
    if limit is None:
        return DEFAULT_POI_SAMPLE_LIMIT, DEFAULT_POI_SAMPLE_LIMIT, ()
    requested = int(limit)
    if requested <= 0:
        return requested, DEFAULT_POI_SAMPLE_LIMIT, ("sample_limit_defaulted",)
    if requested > MAX_POI_SAMPLE_LIMIT:
        return requested, MAX_POI_SAMPLE_LIMIT, (
            "sample_limit_clamped_to_max",
            f"sample_limit_effective: {MAX_POI_SAMPLE_LIMIT}",
        )
    return requested, requested, ()


def _status(
    warnings: Iterable[str],
    blockers: Iterable[str],
    errors: Iterable[str],
) -> AnalysisSuitePoiPreviewStatus:
    if tuple(errors):
        return "error"
    if tuple(blockers):
        return "blocked"
    if tuple(warnings):
        return "warning"
    return "ready"


def _context_status(context: _PlannerContext) -> AnalysisSuitePoiPreviewStatus:
    if context.errors:
        return "error"
    if _context_blocks_preview(context):
        return "blocked"
    if context.warnings or context.blockers:
        return "warning"
    return "ready"


def _context_blocks_preview(context: _PlannerContext) -> bool:
    if context.errors:
        return True
    fatal_exact = {
        "dataset_not_previewable",
        "diagnostic_leakage_blockers_present",
    }
    for blocker in context.blockers:
        if blocker in fatal_exact:
            return True
        if blocker.startswith("diagnostic_report_not_acceptable:"):
            return True
    return False


def _source_metadata_for_occurrence(
    column: AnalysisDatabaseColumn | None,
) -> dict[str, object]:
    if column is None:
        return {}
    return {
        "source_family": column.source_family,
        "source_id": column.source_id,
        "source_column_name": column.source_column_name,
        "db_column_name": column.db_column_name,
        "analysis_usable": column.analysis_usable,
        "renderable": column.renderable,
        "column_metadata": [entry.to_dict() for entry in column.metadata],
    }


def _knowable_ts_ms(
    *,
    ts_values: Sequence[object],
    row_index: int,
    confirmation_offset: int | None,
) -> int | None:
    if confirmation_offset is None or confirmation_offset <= 0:
        return _optional_int(ts_values[row_index]) if row_index < len(ts_values) else None
    confirmation_index = row_index + confirmation_offset
    if confirmation_index >= len(ts_values):
        return None
    return _optional_int(ts_values[confirmation_index])


def _first_ts(occurrences: tuple[AnalysisSuitePoiOccurrence, ...]) -> int | None:
    for occurrence in occurrences:
        if occurrence.ts_ms is not None:
            return occurrence.ts_ms
    return None


def _last_ts(occurrences: tuple[AnalysisSuitePoiOccurrence, ...]) -> int | None:
    for occurrence in reversed(occurrences):
        if occurrence.ts_ms is not None:
            return occurrence.ts_ms
    return None


def _truthy_event_value(value: object) -> bool:
    if _is_nullish(value):
        return False
    if isinstance(value, bool):
        return value
    numeric = _to_float(value)
    if numeric is not None:
        return numeric != 0.0
    text = str(value).strip().casefold()
    return text not in {"", "0", "false", "no", "none", "null", "nan"}


def _bool_true(value: object) -> bool:
    if isinstance(value, bool):
        return value
    numeric = _to_float(value)
    if numeric is not None:
        return numeric == 1.0
    return str(value).strip().casefold() in {"true", "yes", "y", "1"}


def _values_equal(left: object, right: object) -> bool:
    if _is_nullish(left) and _is_nullish(right):
        return True
    left_number = _to_float(left)
    right_number = _to_float(right)
    if left_number is not None and right_number is not None:
        return left_number == right_number
    return str(left) == str(right)


def _is_nullish(value: object) -> bool:
    if value is None:
        return True
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def _to_float(value: object) -> float | None:
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _optional_int(value: object) -> int | None:
    if _is_nullish(value):
        return None
    number = _to_float(value)
    if number is None:
        return None
    return int(number)


def _metadata_value(metadata: Iterable[object], key: str) -> object | None:
    key_text = str(key)
    for entry in metadata:
        if str(getattr(entry, "key", "")) == key_text:
            return getattr(entry, "value", None)
    return None


def _metadata_bool(
    metadata: Iterable[object],
    key: str,
    default: bool | None,
) -> bool | None:
    value = _metadata_value(metadata, key)
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().casefold()
    if text in {"1", "true", "yes", "y"}:
        return True
    if text in {"0", "false", "no", "n"}:
        return False
    return default


def _json_safe_mapping(values: Mapping[str, object]) -> dict[str, object]:
    return {str(key): _json_safe_value(value) for key, value in values.items()}


def _json_safe_value(value: object) -> object:
    if isinstance(value, Mapping):
        return _json_safe_mapping(value)
    if isinstance(value, (list, tuple)):
        return [_json_safe_value(item) for item in value]
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, int):
        return int(value)
    if isinstance(value, float):
        return float(value) if math.isfinite(value) else None
    if _is_nullish(value):
        return None
    if hasattr(value, "item"):
        try:
            return _json_safe_value(value.item())  # type: ignore[no-any-return]
        except (TypeError, ValueError):
            return str(value)
    return str(value)


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text else None


def _dedupe(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(str(item) for item in values))


__all__ = [
    "ANALYSIS_SUITE_POI_FAMILY_SCHEMA_VERSION",
    "DEFAULT_POI_SAMPLE_LIMIT",
    "MAX_POI_SAMPLE_LIMIT",
    "AnalysisSuitePoiCondition",
    "AnalysisSuitePoiConditionOperator",
    "AnalysisSuitePoiDefinition",
    "AnalysisSuitePoiEventKind",
    "AnalysisSuitePoiFamilyDefinition",
    "AnalysisSuitePoiFamilyMembership",
    "AnalysisSuitePoiFamilyPlanner",
    "AnalysisSuitePoiFamilyPreviewReport",
    "AnalysisSuitePoiOccurrence",
    "AnalysisSuitePoiOccurrencePreviewReport",
    "AnalysisSuitePoiPreviewStatus",
]
