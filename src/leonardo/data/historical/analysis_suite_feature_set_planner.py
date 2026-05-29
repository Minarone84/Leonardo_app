from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Literal, Mapping, Protocol

from leonardo.data.historical.analysis_database_contracts import (
    BASE_OHLC_COLUMNS,
    AnalysisDatabaseColumn,
    AnalysisDatabaseManifest,
    AnalysisFeatureSource,
)
from leonardo.data.historical.analysis_database_store import AnalysisDatabaseStore
from leonardo.data.historical.analysis_suite_dataset_readiness import (
    AnalysisSuiteDatasetReadinessReport,
    AnalysisSuiteDatasetReadinessService,
    AnalysisSuiteDatasetReadinessStatus,
)
from leonardo.data.historical.analysis_suite_target_planner import (
    AnalysisSuiteTargetDefinition,
    AnalysisSuiteTargetPreviewReport,
)
from leonardo.data.naming import MarketId


ANALYSIS_SUITE_FEATURE_SET_SCHEMA_VERSION = 1
ANALYSIS_SUITE_LEAKAGE_POLICY_VERSION = 1

AnalysisSuiteFeatureCandidateStatus = Literal[
    "eligible",
    "blocked",
    "warning",
    "reserved",
    "unknown",
]
AnalysisSuiteFeatureSetPreviewStatus = Literal["previewable", "blocked", "error"]

JsonValue = Any

_BASE_OHLC = set(BASE_OHLC_COLUMNS)
_TOPOLOGY_TOOL_KEYS = frozenset(
    {"braids", "peaks_troughs", "universal_trend_classifier"}
)
_CONSTRUCT_BATCH_TOOL_KEYS = frozenset(
    {"delta", "angle", "derivative", "angle_momentum", "percent_span_angle"}
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
class AnalysisSuiteFeatureCandidate:
    """
    JSON-safe feature eligibility diagnostic for one Analysis Database column.

    A candidate is derived from Analysis Database manifest metadata. It reports
    whether the column can be selected as a future Analysis Suite feature and
    preserves the lineage and leakage metadata needed by later planners.
    """

    column_name: str
    display_name: str
    group: str
    status: AnalysisSuiteFeatureCandidateStatus
    selected: bool
    selectable: bool
    analysis_usable: bool | None
    renderable: bool | None
    feature_eligible: bool
    leakage_role: str
    future_derived: bool
    source_family: str
    source_id: str | None
    tool_key: str | None
    tool_title: str | None
    source_column_name: str
    dtype: str | None
    nullable: bool
    blockers: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    lineage_summary: Mapping[str, JsonValue] = field(default_factory=dict)
    metadata: Mapping[str, JsonValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "blockers", tuple(str(item) for item in self.blockers))
        object.__setattr__(self, "warnings", tuple(str(item) for item in self.warnings))
        object.__setattr__(self, "lineage_summary", dict(self.lineage_summary))
        object.__setattr__(self, "metadata", dict(self.metadata))

    def to_dict(self) -> dict[str, object]:
        return {
            "column_name": self.column_name,
            "display_name": self.display_name,
            "group": self.group,
            "status": self.status,
            "selected": bool(self.selected),
            "selectable": bool(self.selectable),
            "analysis_usable": self.analysis_usable,
            "renderable": self.renderable,
            "feature_eligible": bool(self.feature_eligible),
            "leakage_role": self.leakage_role,
            "future_derived": bool(self.future_derived),
            "source_family": self.source_family,
            "source_id": self.source_id,
            "tool_key": self.tool_key,
            "tool_title": self.tool_title,
            "source_column_name": self.source_column_name,
            "dtype": self.dtype,
            "nullable": bool(self.nullable),
            "blockers": list(self.blockers),
            "warnings": list(self.warnings),
            "lineage_summary": _json_safe_mapping(self.lineage_summary),
            "metadata": _json_safe_mapping(self.metadata),
        }


@dataclass(frozen=True)
class AnalysisSuiteFeatureSetDefinition:
    """
    JSON-safe in-memory definition for a previewed Analysis Suite feature set.

    AS6 does not persist this definition. It is returned as part of preview
    diagnostics so future callers can inspect selected columns, exclusions,
    target leakage context, and group counts without creating a store.
    """

    name: str
    database_id: str
    selected_columns: tuple[str, ...]
    excluded_columns: tuple[str, ...]
    target_summary: Mapping[str, JsonValue] = field(default_factory=dict)
    feature_count: int = 0
    group_summary: Mapping[str, JsonValue] = field(default_factory=dict)
    leakage_policy_version: int = ANALYSIS_SUITE_LEAKAGE_POLICY_VERSION
    warnings: tuple[str, ...] = ()
    blockers: tuple[str, ...] = ()
    schema_version: int = ANALYSIS_SUITE_FEATURE_SET_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "selected_columns",
            tuple(str(item) for item in self.selected_columns),
        )
        object.__setattr__(
            self,
            "excluded_columns",
            tuple(str(item) for item in self.excluded_columns),
        )
        object.__setattr__(self, "target_summary", dict(self.target_summary))
        object.__setattr__(self, "group_summary", dict(self.group_summary))
        object.__setattr__(self, "warnings", tuple(str(item) for item in self.warnings))
        object.__setattr__(self, "blockers", tuple(str(item) for item in self.blockers))

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": int(self.schema_version),
            "name": self.name,
            "database_id": self.database_id,
            "selected_columns": list(self.selected_columns),
            "excluded_columns": list(self.excluded_columns),
            "target_summary": _json_safe_mapping(self.target_summary),
            "feature_count": int(self.feature_count),
            "group_summary": _json_safe_mapping(self.group_summary),
            "leakage_policy_version": int(self.leakage_policy_version),
            "warnings": list(self.warnings),
            "blockers": list(self.blockers),
        }


@dataclass(frozen=True)
class AnalysisSuiteFeatureSetPreviewReport:
    """
    JSON-safe read-only feature-set preview report.

    The report combines readiness diagnostics, manifest-derived feature
    candidates, selected-column validation, leakage rejection reasons, and group
    summaries. It does not persist feature sets or modify Analysis Databases.
    """

    database_id: str
    display_name: str
    exchange: str
    market_type: str
    symbol: str
    timeframe: str
    readiness_status: AnalysisSuiteDatasetReadinessStatus | str
    strict_ready: bool
    can_preview: bool
    status: AnalysisSuiteFeatureSetPreviewStatus
    total_candidate_count: int
    eligible_count: int
    blocked_count: int
    warning_count: int
    selected_count: int
    accepted_selected_count: int
    rejected_selected_count: int
    candidates: tuple[AnalysisSuiteFeatureCandidate, ...]
    selected_features: tuple[AnalysisSuiteFeatureCandidate, ...]
    rejected_features: tuple[AnalysisSuiteFeatureCandidate, ...]
    group_summary: Mapping[str, JsonValue]
    leakage_summary: Mapping[str, JsonValue]
    feature_set_definition: AnalysisSuiteFeatureSetDefinition
    warnings: tuple[str, ...] = ()
    blockers: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "candidates", tuple(self.candidates))
        object.__setattr__(self, "selected_features", tuple(self.selected_features))
        object.__setattr__(self, "rejected_features", tuple(self.rejected_features))
        object.__setattr__(self, "group_summary", dict(self.group_summary))
        object.__setattr__(self, "leakage_summary", dict(self.leakage_summary))
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
            "readiness_status": self.readiness_status,
            "strict_ready": bool(self.strict_ready),
            "can_preview": bool(self.can_preview),
            "status": self.status,
            "total_candidate_count": int(self.total_candidate_count),
            "eligible_count": int(self.eligible_count),
            "blocked_count": int(self.blocked_count),
            "warning_count": int(self.warning_count),
            "selected_count": int(self.selected_count),
            "accepted_selected_count": int(self.accepted_selected_count),
            "rejected_selected_count": int(self.rejected_selected_count),
            "candidates": [candidate.to_dict() for candidate in self.candidates],
            "selected_features": [
                candidate.to_dict() for candidate in self.selected_features
            ],
            "rejected_features": [
                candidate.to_dict() for candidate in self.rejected_features
            ],
            "group_summary": _json_safe_mapping(self.group_summary),
            "leakage_summary": _json_safe_mapping(self.leakage_summary),
            "feature_set_definition": self.feature_set_definition.to_dict(),
            "warnings": list(self.warnings),
            "blockers": list(self.blockers),
            "errors": list(self.errors),
        }


class AnalysisSuiteFeatureSetPlanner:
    """
    Build read-only feature candidate and feature-set preview diagnostics.

    The planner gates work through AS1 readiness, reads Analysis Database
    manifest metadata, applies AS5 leakage metadata when provided, and validates
    selected columns without creating feature-set persistence or modifying
    database files.
    """

    def __init__(
        self,
        *,
        historical_root: Path,
        store: AnalysisDatabaseStore | None = None,
        readiness_service: _ReadinessService | None = None,
    ) -> None:
        self._historical_root = Path(historical_root)
        self._store = store or AnalysisDatabaseStore(
            historical_root=self._historical_root
        )
        self._readiness_service = readiness_service or AnalysisSuiteDatasetReadinessService(
            historical_root=self._historical_root,
            store=self._store,
        )

    def list_feature_candidates(
        self,
        *,
        market: MarketId,
        database_id: str,
        target_definition: AnalysisSuiteTargetDefinition | Mapping[str, object] | None = None,
        target_report: AnalysisSuiteTargetPreviewReport | Mapping[str, object] | None = None,
    ) -> AnalysisSuiteFeatureSetPreviewReport:
        """
        Return manifest-derived feature candidates for one Analysis Database.

        Candidate extraction uses AS1 readiness and manifest metadata. It does
        not inspect dataframe headers or create derived data.
        """

        return self.preview_feature_set(
            market=market,
            database_id=database_id,
            selected_columns=(),
            target_definition=target_definition,
            target_report=target_report,
        )

    def validate_selected_features(
        self,
        *,
        market: MarketId,
        database_id: str,
        selected_columns: Iterable[str],
        target_definition: AnalysisSuiteTargetDefinition | Mapping[str, object] | None = None,
        target_report: AnalysisSuiteTargetPreviewReport | Mapping[str, object] | None = None,
        name: str = "Feature set preview",
    ) -> AnalysisSuiteFeatureSetPreviewReport:
        """
        Validate selected feature columns against manifest and leakage policy.

        Selection order is preserved for accepted and rejected selections. The
        method returns diagnostics only and does not persist a feature set.
        """

        return self.preview_feature_set(
            market=market,
            database_id=database_id,
            selected_columns=selected_columns,
            target_definition=target_definition,
            target_report=target_report,
            name=name,
        )

    def preview_feature_set(
        self,
        *,
        market: MarketId,
        database_id: str,
        selected_columns: Iterable[str] = (),
        target_definition: AnalysisSuiteTargetDefinition | Mapping[str, object] | None = None,
        target_report: AnalysisSuiteTargetPreviewReport | Mapping[str, object] | None = None,
        name: str = "Feature set preview",
    ) -> AnalysisSuiteFeatureSetPreviewReport:
        """
        Build a read-only feature-set preview report.

        The preview blocks when AS1 reports that the selected Analysis Database
        is not previewable. Non-strict but previewable datasets are allowed and
        retain AS1 warnings and blockers in the returned report.
        """

        selected = tuple(str(column) for column in selected_columns)
        target_context = _target_context(
            target_definition=target_definition,
            target_report=target_report,
        )

        try:
            readiness = self._readiness_service.readiness_for_database(
                market=market,
                database_id=database_id,
            )
        except Exception as exc:
            return self._readiness_error_report(
                market=market,
                database_id=database_id,
                selected_columns=selected,
                target_context=target_context,
                name=name,
                exc=exc,
            )

        warnings = list(getattr(readiness, "warnings", ()))
        blockers = list(getattr(readiness, "blockers", ()))
        errors = list(getattr(readiness, "errors", ()))
        if not bool(getattr(readiness, "strict_ready", False)):
            warnings.append("dataset_not_strict_ready")

        if not bool(getattr(readiness, "can_preview", False)):
            return _report_from_readiness(
                readiness=readiness,
                status="blocked",
                candidates=(),
                selected_columns=selected,
                selected_features=(),
                rejected_features=(),
                target_context=target_context,
                name=name,
                warnings=tuple(warnings),
                blockers=tuple(blockers) + ("dataset_not_previewable",),
                errors=tuple(errors),
            )

        try:
            manifest = self._store.load_manifest(market=market, database_id=database_id)
            candidates = _candidates_from_manifest(
                manifest,
                target_context=target_context,
            )
        except Exception as exc:
            return _report_from_readiness(
                readiness=readiness,
                status="error",
                candidates=(),
                selected_columns=selected,
                selected_features=(),
                rejected_features=(),
                target_context=target_context,
                name=name,
                warnings=tuple(warnings),
                blockers=tuple(blockers) + ("manifest_feature_metadata_unavailable",),
                errors=tuple(errors) + (f"{type(exc).__name__}: {exc}",),
            )

        accepted, rejected = _validate_selected_columns(
            selected_columns=selected,
            candidates=candidates,
            target_context=target_context,
        )
        status: AnalysisSuiteFeatureSetPreviewStatus = "previewable"
        selection_blockers: tuple[str, ...] = ()
        if rejected:
            status = "blocked"
            selection_blockers = tuple(
                f"selected_feature_rejected: {candidate.column_name}: "
                f"{', '.join(candidate.blockers) if candidate.blockers else candidate.status}"
                for candidate in rejected
            )
        return _report_from_readiness(
            readiness=readiness,
            status=status,
            candidates=candidates,
            selected_columns=selected,
            selected_features=accepted,
            rejected_features=rejected,
            target_context=target_context,
            name=name,
            warnings=tuple(warnings),
            blockers=tuple(blockers) + selection_blockers,
            errors=tuple(errors),
        )

    def _readiness_error_report(
        self,
        *,
        market: MarketId,
        database_id: str,
        selected_columns: tuple[str, ...],
        target_context: "_TargetContext",
        name: str,
        exc: Exception,
    ) -> AnalysisSuiteFeatureSetPreviewReport:
        readiness = _SyntheticReadiness(
            database_id=str(database_id),
            display_name=str(database_id),
            exchange=market.exchange,
            market_type=market.market_type,
            symbol=market.symbol,
            timeframe=market.timeframe,
            readiness_status="error",
            strict_ready=False,
            can_preview=False,
            warnings=(),
            blockers=("readiness_check_failed",),
            errors=(f"{type(exc).__name__}: {exc}",),
        )
        return _report_from_readiness(
            readiness=readiness,
            status="error",
            candidates=(),
            selected_columns=selected_columns,
            selected_features=(),
            rejected_features=(),
            target_context=target_context,
            name=name,
            warnings=readiness.warnings,
            blockers=readiness.blockers,
            errors=readiness.errors,
        )


@dataclass(frozen=True)
class _SyntheticReadiness:
    database_id: str
    display_name: str
    exchange: str
    market_type: str
    symbol: str
    timeframe: str
    readiness_status: str
    strict_ready: bool
    can_preview: bool
    warnings: tuple[str, ...]
    blockers: tuple[str, ...]
    errors: tuple[str, ...]


@dataclass(frozen=True)
class _TargetContext:
    output_column_names: tuple[str, ...]
    target_summary: Mapping[str, JsonValue]
    leakage_summary: Mapping[str, JsonValue]


def _target_context(
    *,
    target_definition: AnalysisSuiteTargetDefinition | Mapping[str, object] | None,
    target_report: AnalysisSuiteTargetPreviewReport | Mapping[str, object] | None,
) -> _TargetContext:
    definition = _definition_from_inputs(
        target_definition=target_definition,
        target_report=target_report,
    )
    leakage = _leakage_from_report(target_report)
    if definition is not None:
        leakage = {
            **_leakage_from_definition(definition),
            **dict(leakage),
        }
    output_names = tuple(
        item
        for item in (
            _optional_str(leakage.get("output_column_name")),
            _optional_str(
                None
                if definition is None
                else getattr(definition, "output_column_name", None)
            ),
        )
        if item
    )
    return _TargetContext(
        output_column_names=tuple(dict.fromkeys(output_names)),
        target_summary=(
            {} if definition is None else _target_summary_from_definition(definition)
        ),
        leakage_summary=_json_safe_mapping(leakage),
    )


def _definition_from_inputs(
    *,
    target_definition: AnalysisSuiteTargetDefinition | Mapping[str, object] | None,
    target_report: AnalysisSuiteTargetPreviewReport | Mapping[str, object] | None,
) -> AnalysisSuiteTargetDefinition | None:
    if target_definition is not None:
        return _coerce_definition(target_definition)
    if target_report is None:
        return None
    if isinstance(target_report, Mapping):
        raw = target_report.get("target_definition")
    else:
        raw = getattr(target_report, "target_definition", None)
    if raw is None:
        return None
    if isinstance(raw, AnalysisSuiteTargetDefinition):
        return raw
    if isinstance(raw, Mapping):
        return AnalysisSuiteTargetDefinition.from_dict(raw)
    if hasattr(raw, "to_dict"):
        return AnalysisSuiteTargetDefinition.from_dict(raw.to_dict())
    return None


def _coerce_definition(
    definition: AnalysisSuiteTargetDefinition | Mapping[str, object],
) -> AnalysisSuiteTargetDefinition:
    if isinstance(definition, AnalysisSuiteTargetDefinition):
        return definition
    return AnalysisSuiteTargetDefinition.from_dict(definition)


def _leakage_from_report(
    target_report: AnalysisSuiteTargetPreviewReport | Mapping[str, object] | None,
) -> dict[str, object]:
    if target_report is None:
        return {}
    if isinstance(target_report, Mapping):
        raw = target_report.get("leakage_summary", {})
    else:
        raw = getattr(target_report, "leakage_summary", {})
    if isinstance(raw, Mapping):
        return dict(raw)
    return {}


def _leakage_from_definition(
    definition: AnalysisSuiteTargetDefinition,
) -> dict[str, object]:
    return {
        "leakage_role": definition.leakage_role,
        "future_derived": bool(definition.future_derived),
        "feature_eligible": bool(definition.feature_eligible),
        "source_columns": list(definition.source_columns),
        "horizon_bars": int(definition.horizon_bars),
        "output_column_name": definition.output_column_name,
        "future_rows_used": f"t+1 through t+{definition.horizon_bars}",
        "feature_selection_policy": "exclude_target_outputs",
        "leakage_policy_version": ANALYSIS_SUITE_LEAKAGE_POLICY_VERSION,
    }


def _target_summary_from_definition(
    definition: AnalysisSuiteTargetDefinition,
) -> dict[str, object]:
    return {
        "name": definition.name,
        "target_family": definition.target_family,
        "label_type": definition.label_type,
        "source_columns": list(definition.source_columns),
        "horizon_bars": int(definition.horizon_bars),
        "output_column_name": definition.output_column_name,
        "leakage_role": definition.leakage_role,
        "future_derived": bool(definition.future_derived),
        "feature_eligible": bool(definition.feature_eligible),
    }


def _candidates_from_manifest(
    manifest: AnalysisDatabaseManifest,
    *,
    target_context: _TargetContext,
) -> tuple[AnalysisSuiteFeatureCandidate, ...]:
    sources = {source.source_id: source for source in manifest.feature_sources}
    candidates: list[AnalysisSuiteFeatureCandidate] = []
    for column in tuple(manifest.base_columns) + tuple(manifest.feature_columns):
        source = None if column.source_id is None else sources.get(column.source_id)
        candidates.append(
            _candidate_from_column(
                column,
                source=source,
                target_context=target_context,
            )
        )
    return tuple(_with_duplicate_diagnostics(candidates))


def _candidate_from_column(
    column: AnalysisDatabaseColumn,
    *,
    source: AnalysisFeatureSource | None,
    target_context: _TargetContext,
) -> AnalysisSuiteFeatureCandidate:
    column_name = str(column.db_column_name)
    source_column_name = str(column.source_column_name)
    group = _candidate_group(column=column, source=source)
    metadata = _candidate_metadata(column=column, source=source)
    lineage = _lineage_summary(column=column, source=source)
    warnings: list[str] = []
    blockers: list[str] = []

    leakage_role = str(_metadata_value(column.metadata, "leakage_role") or "feature")
    future_derived = bool(_metadata_bool(column.metadata, "future_derived", False))
    explicit_feature_eligible = _metadata_bool(
        column.metadata,
        "feature_eligible",
        None,
    )
    selectable = bool(_metadata_bool(column.metadata, "selectable", column.selected))
    analysis_usable = column.analysis_usable

    if group == "alignment":
        blockers.append("alignment_key_reserved")
    if not bool(column.selected):
        blockers.append("column_not_selected_in_analysis_database")
    if not selectable:
        blockers.append("column_not_selectable")
    if analysis_usable is False:
        blockers.append("column_not_analysis_usable")
    if analysis_usable is None and group not in {"alignment", "base_ohlc", "raw_volume"}:
        blockers.append("analysis_usable_unknown")
    if group == "unknown":
        blockers.append("feature_metadata_unknown")
    if column.role == "feature" and source is None:
        blockers.append("feature_source_missing")
    if leakage_role == "target_only":
        blockers.append("target_only_column_forbidden")
    if future_derived:
        blockers.append("future_derived_column_forbidden")
    if explicit_feature_eligible is False:
        blockers.append("feature_eligible_false")
    if column_name in target_context.output_column_names:
        blockers.append("target_output_column_forbidden")
    if column.renderable is False and analysis_usable is True and group != "alignment":
        warnings.append("non_renderable_analysis_usable")

    if group == "alignment":
        status: AnalysisSuiteFeatureCandidateStatus = "reserved"
        feature_eligible = False
    elif group == "unknown":
        status = "unknown"
        feature_eligible = False
    elif blockers:
        status = "blocked"
        feature_eligible = False
    elif warnings:
        status = "warning"
        feature_eligible = True
    else:
        status = "eligible"
        feature_eligible = True

    if explicit_feature_eligible is True and not blockers and group != "alignment":
        feature_eligible = True

    return AnalysisSuiteFeatureCandidate(
        column_name=column_name,
        display_name=column_name,
        group=group,
        status=status,
        selected=bool(column.selected),
        selectable=selectable and status in {"eligible", "warning"},
        analysis_usable=analysis_usable,
        renderable=column.renderable,
        feature_eligible=feature_eligible,
        leakage_role=leakage_role,
        future_derived=future_derived,
        source_family=str(column.source_family),
        source_id=column.source_id,
        tool_key=None if source is None else source.tool_key,
        tool_title=None if source is None else source.tool_title,
        source_column_name=source_column_name,
        dtype=column.dtype,
        nullable=bool(column.nullable),
        blockers=tuple(dict.fromkeys(blockers)),
        warnings=tuple(dict.fromkeys(warnings)),
        lineage_summary=lineage,
        metadata=metadata,
    )


def _candidate_group(
    *,
    column: AnalysisDatabaseColumn,
    source: AnalysisFeatureSource | None,
) -> str:
    column_name = str(column.db_column_name)
    source_column_name = str(column.source_column_name)
    if column.role == "primary_key" or column_name == "ts_ms":
        return "alignment"
    if column.source_family == "ohlcv":
        if column_name in _BASE_OHLC or source_column_name in _BASE_OHLC:
            return "base_ohlc"
        if column_name == "volume" or source_column_name == "volume":
            return "raw_volume"
        return "unknown"
    if source is None:
        return "unknown"
    if source.family == "oscillators" and source.tool_key == "volume":
        return "volume"
    if source.tool_key in _TOPOLOGY_TOOL_KEYS:
        return "topology"
    if source.family == "constructs" and source.tool_key in _CONSTRUCT_BATCH_TOOL_KEYS:
        return "construct_batch"
    if source.family in {"indicators", "oscillators", "constructs"}:
        return source.family
    return "unknown"


def _with_duplicate_diagnostics(
    candidates: tuple[AnalysisSuiteFeatureCandidate, ...] | list[AnalysisSuiteFeatureCandidate],
) -> tuple[AnalysisSuiteFeatureCandidate, ...]:
    counts: dict[str, int] = {}
    for candidate in candidates:
        counts[candidate.column_name] = counts.get(candidate.column_name, 0) + 1
    out: list[AnalysisSuiteFeatureCandidate] = []
    for candidate in candidates:
        if counts.get(candidate.column_name, 0) <= 1:
            out.append(candidate)
            continue
        blockers = tuple(dict.fromkeys(candidate.blockers + ("duplicate_column_name",)))
        out.append(
            AnalysisSuiteFeatureCandidate(
                column_name=candidate.column_name,
                display_name=candidate.display_name,
                group=candidate.group,
                status="blocked",
                selected=candidate.selected,
                selectable=False,
                analysis_usable=candidate.analysis_usable,
                renderable=candidate.renderable,
                feature_eligible=False,
                leakage_role=candidate.leakage_role,
                future_derived=candidate.future_derived,
                source_family=candidate.source_family,
                source_id=candidate.source_id,
                tool_key=candidate.tool_key,
                tool_title=candidate.tool_title,
                source_column_name=candidate.source_column_name,
                dtype=candidate.dtype,
                nullable=candidate.nullable,
                blockers=blockers,
                warnings=candidate.warnings,
                lineage_summary=candidate.lineage_summary,
                metadata=candidate.metadata,
            )
        )
    return tuple(out)


def _validate_selected_columns(
    *,
    selected_columns: tuple[str, ...],
    candidates: tuple[AnalysisSuiteFeatureCandidate, ...],
    target_context: _TargetContext,
) -> tuple[tuple[AnalysisSuiteFeatureCandidate, ...], tuple[AnalysisSuiteFeatureCandidate, ...]]:
    candidates_by_name = {candidate.column_name: candidate for candidate in candidates}
    accepted: list[AnalysisSuiteFeatureCandidate] = []
    rejected: list[AnalysisSuiteFeatureCandidate] = []
    for column_name in selected_columns:
        candidate = candidates_by_name.get(column_name)
        if candidate is None:
            rejected.append(_missing_selected_candidate(column_name, target_context))
            continue
        if candidate.status in {"eligible", "warning"} and candidate.feature_eligible:
            accepted.append(candidate)
        else:
            rejected.append(candidate)
    return tuple(accepted), tuple(rejected)


def _missing_selected_candidate(
    column_name: str,
    target_context: _TargetContext,
) -> AnalysisSuiteFeatureCandidate:
    blockers = ["selected_column_not_found"]
    if column_name in target_context.output_column_names:
        blockers.append("target_output_column_forbidden")
    return AnalysisSuiteFeatureCandidate(
        column_name=column_name,
        display_name=column_name,
        group="unknown",
        status="blocked",
        selected=False,
        selectable=False,
        analysis_usable=None,
        renderable=None,
        feature_eligible=False,
        leakage_role="unknown",
        future_derived=False,
        source_family="unknown",
        source_id=None,
        tool_key=None,
        tool_title=None,
        source_column_name=column_name,
        dtype=None,
        nullable=True,
        blockers=tuple(blockers),
        warnings=(),
        lineage_summary={},
        metadata={},
    )


def _report_from_readiness(
    *,
    readiness: object,
    status: AnalysisSuiteFeatureSetPreviewStatus,
    candidates: tuple[AnalysisSuiteFeatureCandidate, ...],
    selected_columns: tuple[str, ...],
    selected_features: tuple[AnalysisSuiteFeatureCandidate, ...],
    rejected_features: tuple[AnalysisSuiteFeatureCandidate, ...],
    target_context: _TargetContext,
    name: str,
    warnings: Iterable[str],
    blockers: Iterable[str],
    errors: Iterable[str],
) -> AnalysisSuiteFeatureSetPreviewReport:
    group_summary = _group_summary(candidates, selected_features=selected_features)
    definition = AnalysisSuiteFeatureSetDefinition(
        name=name,
        database_id=str(getattr(readiness, "database_id", "")),
        selected_columns=tuple(candidate.column_name for candidate in selected_features),
        excluded_columns=tuple(
            candidate.column_name
            for candidate in candidates
            if candidate.column_name not in {item.column_name for item in selected_features}
        ),
        target_summary=target_context.target_summary,
        feature_count=len(selected_features),
        group_summary=group_summary,
        warnings=tuple(warnings),
        blockers=tuple(blockers),
    )
    return AnalysisSuiteFeatureSetPreviewReport(
        database_id=str(getattr(readiness, "database_id", "")),
        display_name=str(getattr(readiness, "display_name", "")),
        exchange=str(getattr(readiness, "exchange", "")),
        market_type=str(getattr(readiness, "market_type", "")),
        symbol=str(getattr(readiness, "symbol", "")),
        timeframe=str(getattr(readiness, "timeframe", "")),
        readiness_status=str(getattr(readiness, "readiness_status", "error")),
        strict_ready=bool(getattr(readiness, "strict_ready", False)),
        can_preview=bool(getattr(readiness, "can_preview", False)),
        status=status,
        total_candidate_count=len(candidates),
        eligible_count=sum(
            1 for candidate in candidates if candidate.status in {"eligible", "warning"}
        ),
        blocked_count=sum(
            1
            for candidate in candidates
            if candidate.status in {"blocked", "reserved", "unknown"}
        ),
        warning_count=sum(1 for candidate in candidates if candidate.status == "warning"),
        selected_count=len(selected_columns),
        accepted_selected_count=len(selected_features),
        rejected_selected_count=len(rejected_features),
        candidates=candidates,
        selected_features=selected_features,
        rejected_features=rejected_features,
        group_summary=group_summary,
        leakage_summary=target_context.leakage_summary,
        feature_set_definition=definition,
        warnings=tuple(str(item) for item in warnings),
        blockers=tuple(str(item) for item in blockers),
        errors=tuple(str(item) for item in errors),
    )


def _group_summary(
    candidates: tuple[AnalysisSuiteFeatureCandidate, ...],
    *,
    selected_features: tuple[AnalysisSuiteFeatureCandidate, ...],
) -> dict[str, object]:
    selected_names = {candidate.column_name for candidate in selected_features}
    summary: dict[str, dict[str, int]] = {}
    for candidate in candidates:
        group = candidate.group
        bucket = summary.setdefault(
            group,
            {
                "total": 0,
                "eligible": 0,
                "blocked": 0,
                "warning": 0,
                "reserved": 0,
                "unknown": 0,
                "selected": 0,
            },
        )
        bucket["total"] += 1
        bucket[candidate.status] += 1
        if candidate.column_name in selected_names:
            bucket["selected"] += 1
    return summary


def _candidate_metadata(
    *,
    column: AnalysisDatabaseColumn,
    source: AnalysisFeatureSource | None,
) -> dict[str, object]:
    return {
        "column_metadata": [entry.to_dict() for entry in column.metadata],
        "source_metadata": [] if source is None else [entry.to_dict() for entry in source.metadata],
        "semantic_role": _metadata_value(column.metadata, "semantic_role"),
        "value_type": _metadata_value(column.metadata, "value_type"),
        "signal_type": _metadata_value(column.metadata, "signal_type"),
    }


def _lineage_summary(
    *,
    column: AnalysisDatabaseColumn,
    source: AnalysisFeatureSource | None,
) -> dict[str, object]:
    if source is None:
        return {
            "source_family": column.source_family,
            "source_id": column.source_id,
            "source_column_name": column.source_column_name,
            "db_column_name": column.db_column_name,
        }
    return {
        "source_family": source.family,
        "source_id": source.source_id,
        "tool_key": source.tool_key,
        "tool_title": source.tool_title,
        "instance_key": source.instance_key,
        "source_artifact_filename": source.source_artifact_filename,
        "source_artifact_relpath": source.source_artifact_relpath,
        "source_artifact_sha256": source.source_artifact_sha256,
        "source_artifact_size_bytes": source.source_artifact_size_bytes,
        "source_artifact_modified_at_ms": source.source_artifact_modified_at_ms,
        "source_column_name": column.source_column_name,
        "db_column_name": column.db_column_name,
        "params_status": source.params_status,
        "bindings_status": source.bindings_status,
        "recipe_id": _metadata_value(source.metadata, "recipe_id"),
        "recipe_hash": _metadata_value(source.metadata, "recipe_hash"),
    }


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
    return str(value)


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text else None


__all__ = [
    "ANALYSIS_SUITE_FEATURE_SET_SCHEMA_VERSION",
    "ANALYSIS_SUITE_LEAKAGE_POLICY_VERSION",
    "AnalysisSuiteFeatureCandidate",
    "AnalysisSuiteFeatureCandidateStatus",
    "AnalysisSuiteFeatureSetDefinition",
    "AnalysisSuiteFeatureSetPlanner",
    "AnalysisSuiteFeatureSetPreviewReport",
    "AnalysisSuiteFeatureSetPreviewStatus",
]
