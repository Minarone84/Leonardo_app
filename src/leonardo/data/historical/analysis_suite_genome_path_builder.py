"""Read-only Analysis Suite genome path preview building.

The module defines genome component and encoding definitions for Analysis
Suite and builds bounded in-memory path previews from prepared Analysis
Database columns. It uses AS1 readiness or AS7 diagnostic context for gating,
uses AS6 feature-set reports or manifest metadata for semantic checks, and
reads dataframe values only for bounded value extraction.
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
from leonardo.data.historical.analysis_suite_feature_set_planner import (
    AnalysisSuiteFeatureCandidate,
    AnalysisSuiteFeatureSetPreviewReport,
)
from leonardo.data.historical.analysis_suite_poi_family_planner import (
    AnalysisSuitePoiFamilyPreviewReport,
)
from leonardo.data.naming import MarketId


ANALYSIS_SUITE_GENOME_PATH_SCHEMA_VERSION = 1
DEFAULT_GENOME_PATH_SAMPLE_LIMIT = 100
MAX_GENOME_PATH_SAMPLE_LIMIT = 500

AnalysisSuiteGenomeEncodingMethod = Literal[
    "identity_numeric",
    "categorical",
    "boolean_symbolic",
    "static_bin",
    "variation_direction",
]
AnalysisSuiteGenomeAnchorKind = Literal["row", "poi_occurrence"]
AnalysisSuiteGenomePathStatus = Literal["ready", "warning", "blocked", "error"]

JsonValue = Any

_SUPPORTED_ENCODINGS = frozenset(
    {
        "identity_numeric",
        "categorical",
        "boolean_symbolic",
        "static_bin",
        "variation_direction",
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
class AnalysisSuiteStaticBinRule:
    """JSON-safe explicit static bin rule for AS9 genome components."""

    label: str
    lower: float | None = None
    upper: float | None = None
    include_lower: bool = True
    include_upper: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "label", str(self.label))
        object.__setattr__(self, "include_lower", bool(self.include_lower))
        object.__setattr__(self, "include_upper", bool(self.include_upper))

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "AnalysisSuiteStaticBinRule":
        """Create a static bin rule from a JSON-like mapping."""

        return cls(
            label=str(data.get("label", "")),
            lower=_optional_float(data.get("lower")),
            upper=_optional_float(data.get("upper")),
            include_lower=bool(data.get("include_lower", True)),
            include_upper=bool(data.get("include_upper", False)),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "label": self.label,
            "lower": self.lower,
            "upper": self.upper,
            "include_lower": bool(self.include_lower),
            "include_upper": bool(self.include_upper),
        }


@dataclass(frozen=True)
class AnalysisSuiteGenomeComponentDefinition:
    """
    JSON-safe definition for one genome component.

    A component definition names a source column and the deterministic encoding
    used to represent that column in genome snapshots. AS9 supports only
    current-row or past-lookback encodings and does not persist definitions.
    """

    component_key: str
    source_column: str
    encoding: AnalysisSuiteGenomeEncodingMethod | str
    display_name: str | None = None
    bins: tuple[AnalysisSuiteStaticBinRule, ...] = ()
    categories: tuple[str, ...] = ()
    lookback_bars: int = 0
    missing_token: str = "missing"
    out_of_range_token: str = "out_of_range"
    metadata: Mapping[str, JsonValue] = field(default_factory=dict)
    schema_version: int = ANALYSIS_SUITE_GENOME_PATH_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "component_key", str(self.component_key))
        object.__setattr__(self, "source_column", str(self.source_column))
        object.__setattr__(self, "encoding", str(self.encoding))
        object.__setattr__(
            self,
            "bins",
            tuple(_coerce_static_bin_rule(rule) for rule in self.bins),
        )
        object.__setattr__(
            self,
            "categories",
            tuple(str(category) for category in self.categories),
        )
        object.__setattr__(self, "lookback_bars", int(self.lookback_bars))
        object.__setattr__(self, "missing_token", str(self.missing_token))
        object.__setattr__(self, "out_of_range_token", str(self.out_of_range_token))
        object.__setattr__(self, "metadata", dict(self.metadata))

    @classmethod
    def from_dict(
        cls,
        data: Mapping[str, object],
    ) -> "AnalysisSuiteGenomeComponentDefinition":
        """Create a component definition from a JSON-like mapping."""

        return cls(
            component_key=str(data.get("component_key", "")),
            source_column=str(data.get("source_column", "")),
            encoding=str(data.get("encoding", "")),
            display_name=_optional_str(data.get("display_name")),
            bins=tuple(
                _coerce_static_bin_rule(rule)
                for rule in data.get("bins", ()) or ()  # type: ignore[union-attr]
            ),
            categories=tuple(str(item) for item in data.get("categories", ()) or ()),  # type: ignore[arg-type]
            lookback_bars=int(data.get("lookback_bars", 0)),
            missing_token=str(data.get("missing_token", "missing")),
            out_of_range_token=str(data.get("out_of_range_token", "out_of_range")),
            metadata=dict(data.get("metadata", {}) or {}),  # type: ignore[arg-type]
            schema_version=int(
                data.get(
                    "schema_version",
                    ANALYSIS_SUITE_GENOME_PATH_SCHEMA_VERSION,
                )
            ),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": int(self.schema_version),
            "component_key": self.component_key,
            "source_column": self.source_column,
            "encoding": self.encoding,
            "display_name": self.display_name,
            "bins": [rule.to_dict() for rule in self.bins],
            "categories": list(self.categories),
            "lookback_bars": int(self.lookback_bars),
            "missing_token": self.missing_token,
            "out_of_range_token": self.out_of_range_token,
            "metadata": _json_safe_mapping(self.metadata),
        }


@dataclass(frozen=True)
class AnalysisSuiteGenomeEncodingDefinition:
    """JSON-safe definition for one bounded genome path preview."""

    encoding_key: str
    display_name: str
    components: tuple[AnalysisSuiteGenomeComponentDefinition, ...]
    path_length_bars: int
    anchor: AnalysisSuiteGenomeAnchorKind | str = "row"
    metadata: Mapping[str, JsonValue] = field(default_factory=dict)
    schema_version: int = ANALYSIS_SUITE_GENOME_PATH_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "encoding_key", str(self.encoding_key))
        object.__setattr__(self, "display_name", str(self.display_name))
        object.__setattr__(
            self,
            "components",
            tuple(_coerce_component_definition(component) for component in self.components),
        )
        object.__setattr__(self, "path_length_bars", int(self.path_length_bars))
        object.__setattr__(self, "anchor", str(self.anchor))
        object.__setattr__(self, "metadata", dict(self.metadata))

    @classmethod
    def from_dict(
        cls,
        data: Mapping[str, object],
    ) -> "AnalysisSuiteGenomeEncodingDefinition":
        """Create an encoding definition from a JSON-like mapping."""

        return cls(
            encoding_key=str(data.get("encoding_key", "")),
            display_name=str(data.get("display_name", "")),
            components=tuple(
                _coerce_component_definition(component)
                for component in data.get("components", ()) or ()  # type: ignore[union-attr]
            ),
            path_length_bars=int(data.get("path_length_bars", 0)),
            anchor=str(data.get("anchor", "row")),
            metadata=dict(data.get("metadata", {}) or {}),  # type: ignore[arg-type]
            schema_version=int(
                data.get(
                    "schema_version",
                    ANALYSIS_SUITE_GENOME_PATH_SCHEMA_VERSION,
                )
            ),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": int(self.schema_version),
            "encoding_key": self.encoding_key,
            "display_name": self.display_name,
            "components": [component.to_dict() for component in self.components],
            "path_length_bars": int(self.path_length_bars),
            "anchor": self.anchor,
            "metadata": _json_safe_mapping(self.metadata),
        }


@dataclass(frozen=True)
class AnalysisSuiteGenomeSnapshot:
    """JSON-safe encoded genome at one dataframe row."""

    row_index: int
    ts_ms: int | None
    components: Mapping[str, JsonValue]
    component_metadata: Mapping[str, JsonValue]
    blockers: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "row_index", int(self.row_index))
        object.__setattr__(self, "components", dict(self.components))
        object.__setattr__(self, "component_metadata", dict(self.component_metadata))
        object.__setattr__(self, "blockers", tuple(str(item) for item in self.blockers))
        object.__setattr__(self, "warnings", tuple(str(item) for item in self.warnings))

    def to_dict(self) -> dict[str, object]:
        return {
            "row_index": int(self.row_index),
            "ts_ms": self.ts_ms,
            "components": _json_safe_mapping(self.components),
            "component_metadata": _json_safe_mapping(self.component_metadata),
            "blockers": list(self.blockers),
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class AnalysisSuiteGenomePath:
    """JSON-safe ordered genome snapshot path."""

    anchor_row_index: int
    anchor_ts_ms: int | None
    anchor_kind: AnalysisSuiteGenomeAnchorKind | str
    snapshots: tuple[AnalysisSuiteGenomeSnapshot, ...]
    blockers: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "anchor_row_index", int(self.anchor_row_index))
        object.__setattr__(self, "anchor_kind", str(self.anchor_kind))
        object.__setattr__(self, "snapshots", tuple(self.snapshots))
        object.__setattr__(self, "blockers", tuple(str(item) for item in self.blockers))
        object.__setattr__(self, "warnings", tuple(str(item) for item in self.warnings))

    def to_dict(self) -> dict[str, object]:
        return {
            "anchor_row_index": int(self.anchor_row_index),
            "anchor_ts_ms": self.anchor_ts_ms,
            "anchor_kind": self.anchor_kind,
            "snapshots": [snapshot.to_dict() for snapshot in self.snapshots],
            "blockers": list(self.blockers),
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class AnalysisSuiteGenomePathPreviewReport:
    """JSON-safe bounded preview report for genome paths."""

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
    status: AnalysisSuiteGenomePathStatus
    encoding_definition: AnalysisSuiteGenomeEncodingDefinition
    row_count: int | None
    path_count: int
    requested_sample_limit: int
    sample_limit: int
    sample_paths: tuple[AnalysisSuiteGenomePath, ...]
    warnings: tuple[str, ...] = ()
    blockers: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "sample_paths", tuple(self.sample_paths))
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
            "encoding_definition": self.encoding_definition.to_dict(),
            "row_count": self.row_count,
            "path_count": int(self.path_count),
            "requested_sample_limit": int(self.requested_sample_limit),
            "sample_limit": int(self.sample_limit),
            "sample_paths": [path.to_dict() for path in self.sample_paths],
            "warnings": list(self.warnings),
            "blockers": list(self.blockers),
            "errors": list(self.errors),
        }


class AnalysisSuiteGenomePathBuilder:
    """
    Build bounded read-only genome snapshot and path previews.

    The builder validates component source columns through AS6 feature-set
    reports or Analysis Database manifest metadata when available, gates
    dataframe access through AS1 or AS7 context, and encodes only current-row or
    past-lookback component values.
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

    def validate_encoding_definition(
        self,
        *,
        market: MarketId,
        database_id: str,
        encoding_definition: AnalysisSuiteGenomeEncodingDefinition | Mapping[str, object],
        readiness_report: AnalysisSuiteDatasetReadinessReport | None = None,
        diagnostic_report: AnalysisSuiteDiagnosticReport | None = None,
        feature_set_report: AnalysisSuiteFeatureSetPreviewReport | None = None,
    ) -> dict[str, object]:
        """
        Validate a genome encoding definition without reading dataframe values.

        The method reads manifest metadata when available. It returns
        structured diagnostics and does not persist validation output.
        """

        definition = _coerce_encoding_definition(encoding_definition)
        try:
            context = self._context(
                market=market,
                database_id=database_id,
                readiness_report=readiness_report,
                diagnostic_report=diagnostic_report,
                limit_warnings=(),
            )
            manifest = self._store.load_manifest(market=market, database_id=database_id)
            blockers, warnings = _validate_encoding_definition(
                definition,
                manifest=manifest,
                feature_set_report=feature_set_report,
            )
            context = context.with_added(warnings=warnings, blockers=blockers)
            return {
                "status": _context_status(context) if not blockers else "blocked",
                "blockers": list(context.blockers),
                "warnings": list(context.warnings),
                "errors": list(context.errors),
            }
        except Exception as exc:
            return {
                "status": "error",
                "blockers": ["genome_encoding_validation_failed"],
                "warnings": [],
                "errors": [f"{type(exc).__name__}: {exc}"],
            }

    def preview_paths(
        self,
        *,
        market: MarketId,
        database_id: str,
        encoding_definition: AnalysisSuiteGenomeEncodingDefinition | Mapping[str, object],
        sample_limit: int | None = None,
        anchor_rows: Sequence[int] | None = None,
        readiness_report: AnalysisSuiteDatasetReadinessReport | None = None,
        diagnostic_report: AnalysisSuiteDiagnosticReport | None = None,
        feature_set_report: AnalysisSuiteFeatureSetPreviewReport | None = None,
    ) -> AnalysisSuiteGenomePathPreviewReport:
        """Return bounded row-anchored genome path previews."""

        return self._preview_paths(
            market=market,
            database_id=database_id,
            encoding_definition=encoding_definition,
            sample_limit=sample_limit,
            anchor_rows=anchor_rows,
            anchor_kind="row",
            readiness_report=readiness_report,
            diagnostic_report=diagnostic_report,
            feature_set_report=feature_set_report,
        )

    def preview_paths_for_poi_family(
        self,
        *,
        market: MarketId,
        database_id: str,
        encoding_definition: AnalysisSuiteGenomeEncodingDefinition | Mapping[str, object],
        family_report: AnalysisSuitePoiFamilyPreviewReport,
        sample_limit: int | None = None,
        readiness_report: AnalysisSuiteDatasetReadinessReport | None = None,
        diagnostic_report: AnalysisSuiteDiagnosticReport | None = None,
        feature_set_report: AnalysisSuiteFeatureSetPreviewReport | None = None,
    ) -> AnalysisSuiteGenomePathPreviewReport:
        """Return bounded genome paths anchored to matched AS8 family samples."""

        anchors = _matched_family_anchor_rows(family_report)
        return self._preview_paths(
            market=market,
            database_id=database_id,
            encoding_definition=encoding_definition,
            sample_limit=sample_limit,
            anchor_rows=anchors,
            anchor_kind="poi_occurrence",
            readiness_report=readiness_report,
            diagnostic_report=diagnostic_report,
            feature_set_report=feature_set_report,
            pre_warnings=_family_anchor_warnings(family_report, anchors),
            pre_blockers=_family_anchor_blockers(family_report),
        )

    def _preview_paths(
        self,
        *,
        market: MarketId,
        database_id: str,
        encoding_definition: AnalysisSuiteGenomeEncodingDefinition | Mapping[str, object],
        sample_limit: int | None,
        anchor_rows: Sequence[int] | None,
        anchor_kind: AnalysisSuiteGenomeAnchorKind | str,
        readiness_report: AnalysisSuiteDatasetReadinessReport | None,
        diagnostic_report: AnalysisSuiteDiagnosticReport | None,
        feature_set_report: AnalysisSuiteFeatureSetPreviewReport | None,
        pre_warnings: Iterable[str] = (),
        pre_blockers: Iterable[str] = (),
    ) -> AnalysisSuiteGenomePathPreviewReport:
        definition = _coerce_encoding_definition(encoding_definition)
        requested_limit, effective_limit, limit_warnings = _sample_limit_state(sample_limit)

        try:
            context = self._context(
                market=market,
                database_id=database_id,
                readiness_report=readiness_report,
                diagnostic_report=diagnostic_report,
                limit_warnings=limit_warnings + tuple(pre_warnings),
            )
            context = context.with_added(blockers=pre_blockers)
        except Exception as exc:
            context = _synthetic_context(
                market=market,
                database_id=database_id,
                store=self._store,
                errors=(f"{type(exc).__name__}: {exc}",),
                blockers=("readiness_check_failed",),
            )
            return _path_report(
                context=context,
                status="error",
                definition=definition,
                row_count=None,
                path_count=0,
                paths=(),
                requested_sample_limit=requested_limit,
                sample_limit=effective_limit,
            )

        if _context_blocks_preview(context):
            return _path_report(
                context=context,
                status=_context_status(context),
                definition=definition,
                row_count=None,
                path_count=0,
                paths=(),
                requested_sample_limit=requested_limit,
                sample_limit=effective_limit,
            )

        try:
            manifest = self._store.load_manifest(market=market, database_id=database_id)
            blockers, warnings = _validate_encoding_definition(
                definition,
                manifest=manifest,
                feature_set_report=feature_set_report,
            )
            context = context.with_added(warnings=warnings, blockers=blockers)
            if blockers:
                return _path_report(
                    context=context,
                    status="blocked",
                    definition=definition,
                    row_count=None,
                    path_count=0,
                    paths=(),
                    requested_sample_limit=requested_limit,
                    sample_limit=effective_limit,
                )

            required_columns = ("ts_ms",) + tuple(
                component.source_column for component in definition.components
            )
            frame, physical_warnings, physical_blockers = _read_genome_dataframe(
                dataframe_path=Path(context.dataframe_path or ""),
                required_columns=required_columns,
            )
            context = context.with_added(
                warnings=physical_warnings,
                blockers=physical_blockers,
            )
            if physical_blockers:
                return _path_report(
                    context=context,
                    status="blocked",
                    definition=definition,
                    row_count=None,
                    path_count=0,
                    paths=(),
                    requested_sample_limit=requested_limit,
                    sample_limit=effective_limit,
                )

            anchors = _anchor_rows(
                row_count=len(frame),
                path_length=definition.path_length_bars,
                anchor_rows=anchor_rows,
            )
            path_count = len(anchors)
            if not anchors:
                context = context.with_added(blockers=("no_genome_path_anchors_available",))
                return _path_report(
                    context=context,
                    status="blocked",
                    definition=definition,
                    row_count=len(frame),
                    path_count=0,
                    paths=(),
                    requested_sample_limit=requested_limit,
                    sample_limit=effective_limit,
                )

            source_metadata = _component_source_metadata(
                definition=definition,
                manifest=manifest,
                feature_set_report=feature_set_report,
            )
            paths = tuple(
                _build_path(
                    frame=frame,
                    definition=definition,
                    anchor_row=row,
                    anchor_kind=anchor_kind,
                    source_metadata=source_metadata,
                )
                for row in anchors[:effective_limit]
            )
            path_warnings = _path_warnings(paths)
            path_blockers = _path_blockers(paths)
            if path_blockers and any(path.snapshots for path in paths):
                context = context.with_added(
                    warnings=("genome_path_blockers_present",) + path_warnings
                )
            elif path_blockers:
                context = context.with_added(blockers=path_blockers)
            else:
                context = context.with_added(warnings=path_warnings)

            return _path_report(
                context=context,
                status=_context_status(context),
                definition=definition,
                row_count=len(frame),
                path_count=path_count,
                paths=paths,
                requested_sample_limit=requested_limit,
                sample_limit=effective_limit,
            )
        except Exception as exc:
            context = context.with_added(errors=(f"{type(exc).__name__}: {exc}",))
            return _path_report(
                context=context,
                status="error",
                definition=definition,
                row_count=None,
                path_count=0,
                paths=(),
                requested_sample_limit=requested_limit,
                sample_limit=effective_limit,
            )

    def _context(
        self,
        *,
        market: MarketId,
        database_id: str,
        readiness_report: AnalysisSuiteDatasetReadinessReport | None,
        diagnostic_report: AnalysisSuiteDiagnosticReport | None,
        limit_warnings: tuple[str, ...],
    ) -> "_BuilderContext":
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
class _BuilderContext:
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
    ) -> "_BuilderContext":
        return _BuilderContext(
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


def _context_from_readiness(readiness: AnalysisSuiteDatasetReadinessReport) -> _BuilderContext:
    warnings = tuple(str(item) for item in getattr(readiness, "warnings", ()))
    blockers = tuple(str(item) for item in getattr(readiness, "blockers", ()))
    errors = tuple(str(item) for item in getattr(readiness, "errors", ()))
    if not bool(getattr(readiness, "strict_ready", False)):
        warnings += ("dataset_not_strict_ready",)
    if not bool(getattr(readiness, "can_preview", False)):
        blockers += ("dataset_not_previewable",)
    return _BuilderContext(
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


def _context_from_diagnostic(report: AnalysisSuiteDiagnosticReport) -> _BuilderContext:
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
    return _BuilderContext(
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
) -> _BuilderContext:
    return _BuilderContext(
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


def _validate_encoding_definition(
    definition: AnalysisSuiteGenomeEncodingDefinition,
    *,
    manifest: AnalysisDatabaseManifest,
    feature_set_report: AnalysisSuiteFeatureSetPreviewReport | None,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    blockers: list[str] = []
    warnings: list[str] = []
    if definition.schema_version != ANALYSIS_SUITE_GENOME_PATH_SCHEMA_VERSION:
        blockers.append("unsupported_genome_encoding_schema")
    if not definition.encoding_key:
        blockers.append("genome_encoding_key_required")
    if not definition.display_name:
        warnings.append("genome_encoding_display_name_missing")
    if definition.path_length_bars <= 0:
        blockers.append("path_length_bars_must_be_positive")
    if definition.anchor not in {"row", "poi_occurrence"}:
        blockers.append(f"unsupported_genome_anchor: {definition.anchor}")
    if not definition.components:
        blockers.append("genome_components_required")
    if feature_set_report is not None:
        feature_set_status = str(getattr(feature_set_report, "status", ""))
        if feature_set_status in {"blocked", "error"}:
            blockers.append(f"feature_set_report_not_acceptable: {feature_set_status}")
        warnings.extend(
            f"feature_set_warning: {item}"
            for item in getattr(feature_set_report, "warnings", ())
        )
        blockers.extend(
            f"feature_set_blocker: {item}"
            for item in getattr(feature_set_report, "blockers", ())
        )
        if tuple(getattr(feature_set_report, "errors", ())):
            blockers.append("feature_set_errors_present")

    component_keys: set[str] = set()
    columns = _manifest_columns(manifest)
    feature_candidates = _feature_candidate_context(feature_set_report)
    for component in definition.components:
        blockers.extend(_validate_component_definition(component))
        if component.component_key in component_keys:
            blockers.append(f"duplicate_component_key: {component.component_key}")
        component_keys.add(component.component_key)
        candidate = feature_candidates.selected.get(component.source_column)
        rejected_candidate = feature_candidates.rejected.get(component.source_column)
        manifest_column = columns.get(component.source_column)
        if feature_set_report is not None:
            if candidate is not None:
                blockers.extend(_candidate_blockers(candidate, component=component))
                warnings.extend(_candidate_warnings(candidate, component=component))
            elif rejected_candidate is not None:
                blockers.append(
                    f"component_source_rejected_by_feature_set: {component.source_column}"
                )
            else:
                blockers.append(
                    f"component_source_not_selected_by_feature_set: {component.source_column}"
                )
        elif manifest_column is not None:
            blockers.extend(_column_input_blockers(manifest_column, component=component))
            warnings.extend(_column_input_warnings(manifest_column, component=component))
        elif component.source_column:
            warnings.append(
                f"component_semantic_eligibility_unknown: {component.source_column}"
            )
    return _dedupe(blockers), _dedupe(warnings)


def _validate_component_definition(
    component: AnalysisSuiteGenomeComponentDefinition,
) -> tuple[str, ...]:
    blockers: list[str] = []
    if component.schema_version != ANALYSIS_SUITE_GENOME_PATH_SCHEMA_VERSION:
        blockers.append(f"unsupported_component_schema: {component.component_key}")
    if not component.component_key:
        blockers.append("component_key_required")
    if not component.source_column:
        blockers.append(f"component_source_column_required: {component.component_key}")
    if component.source_column == "ts_ms":
        blockers.append(f"component_cannot_use_alignment_key: {component.component_key}")
    if component.encoding not in _SUPPORTED_ENCODINGS:
        blockers.append(
            f"unsupported_component_encoding: {component.component_key}:{component.encoding}"
        )
    if component.encoding == "static_bin":
        if not component.bins:
            blockers.append(f"static_bin_requires_bins: {component.component_key}")
        for rule in component.bins:
            if not rule.label:
                blockers.append(f"static_bin_rule_label_required: {component.component_key}")
            if rule.lower is None and rule.upper is None:
                blockers.append(f"static_bin_rule_bound_required: {component.component_key}")
    if component.encoding == "variation_direction" and component.lookback_bars <= 0:
        blockers.append(f"variation_direction_requires_positive_lookback: {component.component_key}")
    return tuple(blockers)


def _manifest_columns(
    manifest: AnalysisDatabaseManifest,
) -> dict[str, AnalysisDatabaseColumn]:
    columns = tuple(manifest.base_columns) + tuple(manifest.feature_columns)
    return {str(column.db_column_name): column for column in columns}


@dataclass(frozen=True)
class _FeatureCandidateContext:
    selected: Mapping[str, AnalysisSuiteFeatureCandidate]
    rejected: Mapping[str, AnalysisSuiteFeatureCandidate]


def _feature_candidate_context(
    report: AnalysisSuiteFeatureSetPreviewReport | None,
) -> _FeatureCandidateContext:
    if report is None:
        return _FeatureCandidateContext(selected={}, rejected={})
    selected = {
        str(candidate.column_name): candidate
        for candidate in getattr(report, "selected_features", ())
    }
    rejected = {
        str(candidate.column_name): candidate
        for candidate in getattr(report, "rejected_features", ())
    }
    return _FeatureCandidateContext(selected=selected, rejected=rejected)


def _candidate_blockers(
    candidate: AnalysisSuiteFeatureCandidate,
    *,
    component: AnalysisSuiteGenomeComponentDefinition,
) -> tuple[str, ...]:
    blockers: list[str] = []
    column_name = str(candidate.column_name)
    if column_name == "ts_ms":
        blockers.append(f"component_cannot_use_alignment_key: {component.component_key}")
    if str(getattr(candidate, "leakage_role", "")) == "target_only":
        blockers.append(f"component_target_only_column_forbidden: {column_name}")
    if bool(getattr(candidate, "future_derived", False)):
        blockers.append(f"component_future_derived_column_forbidden: {column_name}")
    if bool(getattr(candidate, "feature_eligible", True)) is False:
        blockers.append(f"component_feature_eligible_false: {column_name}")
    if bool(getattr(candidate, "selectable", True)) is False:
        blockers.append(f"component_not_selectable: {column_name}")
    if getattr(candidate, "analysis_usable", True) is False:
        blockers.append(f"component_not_analysis_usable: {column_name}")
    if getattr(candidate, "status", "") == "blocked":
        blockers.append(f"component_candidate_blocked: {column_name}")
    return tuple(blockers)


def _candidate_warnings(
    candidate: AnalysisSuiteFeatureCandidate,
    *,
    component: AnalysisSuiteGenomeComponentDefinition,
) -> tuple[str, ...]:
    warnings: list[str] = []
    if getattr(candidate, "status", "") == "warning":
        warnings.append(f"component_candidate_warning: {component.component_key}")
    warnings.extend(
        f"component_candidate_warning:{component.component_key}:{item}"
        for item in getattr(candidate, "warnings", ())
    )
    return tuple(warnings)


def _column_input_blockers(
    column: AnalysisDatabaseColumn,
    *,
    component: AnalysisSuiteGenomeComponentDefinition,
) -> tuple[str, ...]:
    column_name = str(column.db_column_name)
    blockers: list[str] = []
    if column_name == "ts_ms":
        blockers.append(f"component_cannot_use_alignment_key: {component.component_key}")
    if _metadata_value(column.metadata, "leakage_role") == "target_only":
        blockers.append(f"component_target_only_column_forbidden: {column_name}")
    if _metadata_bool(column.metadata, "future_derived", False):
        blockers.append(f"component_future_derived_column_forbidden: {column_name}")
    if _metadata_bool(column.metadata, "feature_eligible", None) is False:
        blockers.append(f"component_feature_eligible_false: {column_name}")
    if column.analysis_usable is False:
        blockers.append(f"component_column_not_analysis_usable: {column_name}")
    if column.role == "feature" and not column.source_id:
        blockers.append(f"component_feature_source_missing: {column_name}")
    return tuple(blockers)


def _column_input_warnings(
    column: AnalysisDatabaseColumn,
    *,
    component: AnalysisSuiteGenomeComponentDefinition,
) -> tuple[str, ...]:
    if column.role == "feature" and column.analysis_usable is None:
        return (
            f"component_semantic_eligibility_not_confirmed: {component.component_key}",
        )
    return ()


def _read_genome_dataframe(
    *,
    dataframe_path: Path,
    required_columns: Sequence[str],
) -> tuple[pd.DataFrame, tuple[str, ...], tuple[str, ...]]:
    if not dataframe_path.exists():
        return pd.DataFrame(), (), (f"dataframe_missing: {dataframe_path}",)
    header = tuple(str(column) for column in pd.read_csv(dataframe_path, nrows=0).columns)
    header_set = set(header)
    required = tuple(dict.fromkeys(str(column) for column in required_columns))
    missing_required = tuple(column for column in required if column not in header_set)
    blockers = tuple(
        f"dataframe_required_column_missing: {column}" for column in missing_required
    )
    if blockers:
        return pd.DataFrame(), (), blockers
    frame = pd.read_csv(dataframe_path, usecols=list(required))
    return frame, (), ()


def _anchor_rows(
    *,
    row_count: int,
    path_length: int,
    anchor_rows: Sequence[int] | None,
) -> tuple[int, ...]:
    if anchor_rows is not None:
        return tuple(int(row) for row in anchor_rows)
    if path_length <= 0 or row_count < path_length:
        return ()
    return tuple(range(path_length - 1, row_count))


def _build_path(
    *,
    frame: pd.DataFrame,
    definition: AnalysisSuiteGenomeEncodingDefinition,
    anchor_row: int,
    anchor_kind: AnalysisSuiteGenomeAnchorKind | str,
    source_metadata: Mapping[str, JsonValue],
) -> AnalysisSuiteGenomePath:
    if anchor_row < 0 or anchor_row >= len(frame):
        return AnalysisSuiteGenomePath(
            anchor_row_index=anchor_row,
            anchor_ts_ms=None,
            anchor_kind=anchor_kind,
            snapshots=(),
            blockers=(f"anchor_row_out_of_range: {anchor_row}",),
        )
    start_row = anchor_row - definition.path_length_bars + 1
    anchor_ts = _row_ts_ms(frame, anchor_row)
    if start_row < 0:
        return AnalysisSuiteGenomePath(
            anchor_row_index=anchor_row,
            anchor_ts_ms=anchor_ts,
            anchor_kind=anchor_kind,
            snapshots=(),
            blockers=(f"insufficient_history_for_anchor: {anchor_row}",),
        )
    snapshots = tuple(
        _build_snapshot(
            frame=frame,
            row_index=row_index,
            definition=definition,
            source_metadata=source_metadata,
        )
        for row_index in range(start_row, anchor_row + 1)
    )
    warnings = _dedupe(
        warning
        for snapshot in snapshots
        for warning in snapshot.warnings
    )
    blockers = _dedupe(
        blocker
        for snapshot in snapshots
        for blocker in snapshot.blockers
    )
    return AnalysisSuiteGenomePath(
        anchor_row_index=anchor_row,
        anchor_ts_ms=anchor_ts,
        anchor_kind=anchor_kind,
        snapshots=snapshots,
        blockers=blockers,
        warnings=warnings,
    )


def _build_snapshot(
    *,
    frame: pd.DataFrame,
    row_index: int,
    definition: AnalysisSuiteGenomeEncodingDefinition,
    source_metadata: Mapping[str, JsonValue],
) -> AnalysisSuiteGenomeSnapshot:
    components: dict[str, object] = {}
    metadata: dict[str, object] = {}
    warnings: list[str] = []
    blockers: list[str] = []
    for component in definition.components:
        value, value_metadata, value_warnings, value_blockers = _encode_component(
            frame=frame,
            row_index=row_index,
            component=component,
        )
        components[component.component_key] = value
        metadata[component.component_key] = {
            "source_column": component.source_column,
            "encoding": component.encoding,
            "row_index": int(row_index),
            "ts_ms": _row_ts_ms(frame, row_index),
            "source_metadata": source_metadata.get(component.component_key, {}),
            **value_metadata,
        }
        warnings.extend(value_warnings)
        blockers.extend(value_blockers)
    return AnalysisSuiteGenomeSnapshot(
        row_index=row_index,
        ts_ms=_row_ts_ms(frame, row_index),
        components=components,
        component_metadata=metadata,
        blockers=_dedupe(blockers),
        warnings=_dedupe(warnings),
    )


def _encode_component(
    *,
    frame: pd.DataFrame,
    row_index: int,
    component: AnalysisSuiteGenomeComponentDefinition,
) -> tuple[object, dict[str, object], tuple[str, ...], tuple[str, ...]]:
    if component.source_column not in frame.columns:
        return (
            component.missing_token,
            {},
            (),
            (f"component_source_missing_from_dataframe: {component.source_column}",),
        )
    if component.encoding == "identity_numeric":
        return _encode_identity_numeric(frame, row_index, component)
    if component.encoding == "categorical":
        return _encode_categorical(frame, row_index, component)
    if component.encoding == "boolean_symbolic":
        return _encode_boolean_symbolic(frame, row_index, component)
    if component.encoding == "static_bin":
        return _encode_static_bin(frame, row_index, component)
    if component.encoding == "variation_direction":
        return _encode_variation_direction(frame, row_index, component)
    return (
        component.missing_token,
        {},
        (),
        (f"unsupported_component_encoding: {component.component_key}:{component.encoding}",),
    )


def _encode_identity_numeric(
    frame: pd.DataFrame,
    row_index: int,
    component: AnalysisSuiteGenomeComponentDefinition,
) -> tuple[object, dict[str, object], tuple[str, ...], tuple[str, ...]]:
    value = frame.iloc[row_index][component.source_column]
    number = _to_float(value)
    if number is None:
        return (
            component.missing_token,
            {"source_value": _json_safe_value(value)},
            (f"component_numeric_value_missing: {component.component_key}",),
            (),
        )
    return (
        _json_safe_value(number),
        {"source_value": _json_safe_value(value)},
        (),
        (),
    )


def _encode_categorical(
    frame: pd.DataFrame,
    row_index: int,
    component: AnalysisSuiteGenomeComponentDefinition,
) -> tuple[object, dict[str, object], tuple[str, ...], tuple[str, ...]]:
    value = frame.iloc[row_index][component.source_column]
    if _is_nullish(value):
        return (
            component.missing_token,
            {"source_value": None},
            (f"component_categorical_value_missing: {component.component_key}",),
            (),
        )
    token = str(value).strip()
    warnings: tuple[str, ...] = ()
    if component.categories and token not in component.categories:
        warnings = (f"component_category_not_declared: {component.component_key}:{token}",)
    return token, {"source_value": _json_safe_value(value)}, warnings, ()


def _encode_boolean_symbolic(
    frame: pd.DataFrame,
    row_index: int,
    component: AnalysisSuiteGenomeComponentDefinition,
) -> tuple[object, dict[str, object], tuple[str, ...], tuple[str, ...]]:
    value = frame.iloc[row_index][component.source_column]
    if _is_nullish(value):
        return (
            component.missing_token,
            {"source_value": None},
            (f"component_boolean_value_missing: {component.component_key}",),
            (),
        )
    bool_value = _bool_value(value)
    if bool_value is None:
        return (
            component.missing_token,
            {"source_value": _json_safe_value(value)},
            (f"component_boolean_value_unrecognized: {component.component_key}",),
            (),
        )
    return (
        "true" if bool_value else "false",
        {"source_value": _json_safe_value(value)},
        (),
        (),
    )


def _encode_static_bin(
    frame: pd.DataFrame,
    row_index: int,
    component: AnalysisSuiteGenomeComponentDefinition,
) -> tuple[object, dict[str, object], tuple[str, ...], tuple[str, ...]]:
    value = frame.iloc[row_index][component.source_column]
    number = _to_float(value)
    if number is None:
        return (
            component.missing_token,
            {"source_value": _json_safe_value(value)},
            (f"component_static_bin_value_missing: {component.component_key}",),
            (),
        )
    for rule in component.bins:
        if _static_bin_matches(rule, number):
            return (
                rule.label,
                {"source_value": _json_safe_value(value), "matched_bin": rule.to_dict()},
                (),
                (),
            )
    return (
        component.out_of_range_token,
        {"source_value": _json_safe_value(value)},
        (f"component_static_bin_out_of_range: {component.component_key}",),
        (),
    )


def _encode_variation_direction(
    frame: pd.DataFrame,
    row_index: int,
    component: AnalysisSuiteGenomeComponentDefinition,
) -> tuple[object, dict[str, object], tuple[str, ...], tuple[str, ...]]:
    previous_index = row_index - component.lookback_bars
    if previous_index < 0:
        return (
            component.missing_token,
            {"lookback_bars": int(component.lookback_bars)},
            (f"component_variation_lookback_unavailable: {component.component_key}",),
            (),
        )
    current = _to_float(frame.iloc[row_index][component.source_column])
    previous = _to_float(frame.iloc[previous_index][component.source_column])
    if current is None or previous is None:
        return (
            component.missing_token,
            {
                "lookback_bars": int(component.lookback_bars),
                "previous_row_index": int(previous_index),
                "previous_ts_ms": _row_ts_ms(frame, previous_index),
            },
            (f"component_variation_value_missing: {component.component_key}",),
            (),
        )
    delta = current - previous
    if delta > 0:
        descriptor = "increasing"
    elif delta < 0:
        descriptor = "decreasing"
    else:
        descriptor = "flat"
    return (
        descriptor,
        {
            "lookback_bars": int(component.lookback_bars),
            "previous_row_index": int(previous_index),
            "previous_ts_ms": _row_ts_ms(frame, previous_index),
            "delta": _json_safe_value(delta),
        },
        (),
        (),
    )


def _static_bin_matches(rule: AnalysisSuiteStaticBinRule, value: float) -> bool:
    lower_ok = True
    upper_ok = True
    if rule.lower is not None:
        lower_ok = value >= rule.lower if rule.include_lower else value > rule.lower
    if rule.upper is not None:
        upper_ok = value <= rule.upper if rule.include_upper else value < rule.upper
    return lower_ok and upper_ok


def _component_source_metadata(
    *,
    definition: AnalysisSuiteGenomeEncodingDefinition,
    manifest: AnalysisDatabaseManifest,
    feature_set_report: AnalysisSuiteFeatureSetPreviewReport | None,
) -> dict[str, object]:
    columns = _manifest_columns(manifest)
    candidates = _feature_candidate_context(feature_set_report)
    metadata: dict[str, object] = {}
    for component in definition.components:
        candidate = candidates.selected.get(component.source_column)
        column = columns.get(component.source_column)
        metadata[component.component_key] = _source_metadata(
            candidate=candidate,
            column=column,
        )
    return metadata


def _source_metadata(
    *,
    candidate: AnalysisSuiteFeatureCandidate | None,
    column: AnalysisDatabaseColumn | None,
) -> dict[str, object]:
    if candidate is not None:
        return {
            "semantic_source": "feature_set",
            "column_name": candidate.column_name,
            "group": candidate.group,
            "status": candidate.status,
            "source_family": candidate.source_family,
            "source_id": candidate.source_id,
            "tool_key": candidate.tool_key,
            "tool_title": candidate.tool_title,
            "feature_eligible": bool(candidate.feature_eligible),
            "leakage_role": candidate.leakage_role,
            "future_derived": bool(candidate.future_derived),
            "metadata": _json_safe_mapping(candidate.metadata),
        }
    if column is not None:
        return {
            "semantic_source": "manifest",
            "role": column.role,
            "source_family": column.source_family,
            "source_id": column.source_id,
            "source_column_name": column.source_column_name,
            "db_column_name": column.db_column_name,
            "dtype": column.dtype,
            "analysis_usable": column.analysis_usable,
            "renderable": column.renderable,
            "column_metadata": [entry.to_dict() for entry in column.metadata],
        }
    return {"semantic_source": "unknown"}


def _matched_family_anchor_rows(
    report: AnalysisSuitePoiFamilyPreviewReport,
) -> tuple[int, ...]:
    anchors: list[int] = []
    for membership in getattr(report, "sample_memberships", ()):
        if not bool(getattr(membership, "matched", False)):
            continue
        occurrence = getattr(membership, "occurrence", None)
        if occurrence is not None:
            anchors.append(int(getattr(occurrence, "row_index")))
    if anchors:
        return tuple(anchors)
    return tuple(
        int(getattr(occurrence, "row_index"))
        for occurrence in getattr(report, "sample_occurrences", ())
    )


def _family_anchor_warnings(
    report: AnalysisSuitePoiFamilyPreviewReport,
    anchors: tuple[int, ...],
) -> tuple[str, ...]:
    warnings: list[str] = []
    matched_count = int(getattr(report, "matched_count", len(anchors)) or 0)
    if matched_count > len(anchors):
        warnings.append("poi_family_anchor_uses_bounded_samples")
    if not anchors:
        warnings.append("poi_family_anchor_rows_unavailable")
    return tuple(warnings)


def _family_anchor_blockers(
    report: AnalysisSuitePoiFamilyPreviewReport,
) -> tuple[str, ...]:
    status = str(getattr(report, "status", ""))
    if status in {"blocked", "error"}:
        return (f"poi_family_report_not_acceptable: {status}",)
    return ()


def _path_report(
    *,
    context: _BuilderContext,
    status: AnalysisSuiteGenomePathStatus,
    definition: AnalysisSuiteGenomeEncodingDefinition,
    row_count: int | None,
    path_count: int,
    paths: tuple[AnalysisSuiteGenomePath, ...],
    requested_sample_limit: int,
    sample_limit: int,
) -> AnalysisSuiteGenomePathPreviewReport:
    return AnalysisSuiteGenomePathPreviewReport(
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
        encoding_definition=definition,
        row_count=row_count,
        path_count=path_count,
        requested_sample_limit=requested_sample_limit,
        sample_limit=sample_limit,
        sample_paths=tuple(paths[:sample_limit]),
        warnings=context.warnings,
        blockers=context.blockers,
        errors=context.errors,
    )


def _sample_limit_state(limit: int | None) -> tuple[int, int, tuple[str, ...]]:
    if limit is None:
        return DEFAULT_GENOME_PATH_SAMPLE_LIMIT, DEFAULT_GENOME_PATH_SAMPLE_LIMIT, ()
    requested = int(limit)
    if requested <= 0:
        return requested, DEFAULT_GENOME_PATH_SAMPLE_LIMIT, ("sample_limit_defaulted",)
    if requested > MAX_GENOME_PATH_SAMPLE_LIMIT:
        return requested, MAX_GENOME_PATH_SAMPLE_LIMIT, (
            "sample_limit_clamped_to_max",
            f"sample_limit_effective: {MAX_GENOME_PATH_SAMPLE_LIMIT}",
        )
    return requested, requested, ()


def _context_status(context: _BuilderContext) -> AnalysisSuiteGenomePathStatus:
    if context.errors:
        return "error"
    if _context_blocks_preview(context):
        return "blocked"
    if context.warnings or context.blockers:
        return "warning"
    return "ready"


def _context_blocks_preview(context: _BuilderContext) -> bool:
    if context.errors:
        return True
    fatal_exact = {
        "dataset_not_previewable",
        "diagnostic_leakage_blockers_present",
        "no_genome_path_anchors_available",
    }
    for blocker in context.blockers:
        if blocker in fatal_exact:
            return True
        if blocker.startswith("diagnostic_report_not_acceptable:"):
            return True
        if blocker.startswith("poi_family_report_not_acceptable:"):
            return True
    return False


def _path_warnings(paths: tuple[AnalysisSuiteGenomePath, ...]) -> tuple[str, ...]:
    return _dedupe(warning for path in paths for warning in path.warnings)


def _path_blockers(paths: tuple[AnalysisSuiteGenomePath, ...]) -> tuple[str, ...]:
    return _dedupe(blocker for path in paths for blocker in path.blockers)


def _row_ts_ms(frame: pd.DataFrame, row_index: int) -> int | None:
    if "ts_ms" not in frame.columns or row_index < 0 or row_index >= len(frame):
        return None
    return _optional_int(frame.iloc[row_index]["ts_ms"])


def _coerce_static_bin_rule(
    rule: AnalysisSuiteStaticBinRule | Mapping[str, object],
) -> AnalysisSuiteStaticBinRule:
    if isinstance(rule, AnalysisSuiteStaticBinRule):
        return rule
    return AnalysisSuiteStaticBinRule.from_dict(rule)


def _coerce_component_definition(
    component: AnalysisSuiteGenomeComponentDefinition | Mapping[str, object],
) -> AnalysisSuiteGenomeComponentDefinition:
    if isinstance(component, AnalysisSuiteGenomeComponentDefinition):
        return component
    return AnalysisSuiteGenomeComponentDefinition.from_dict(component)


def _coerce_encoding_definition(
    definition: AnalysisSuiteGenomeEncodingDefinition | Mapping[str, object],
) -> AnalysisSuiteGenomeEncodingDefinition:
    if isinstance(definition, AnalysisSuiteGenomeEncodingDefinition):
        return definition
    return AnalysisSuiteGenomeEncodingDefinition.from_dict(definition)


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


def _bool_value(value: object) -> bool | None:
    if isinstance(value, bool):
        return value
    numeric = _to_float(value)
    if numeric is not None:
        if numeric == 1.0:
            return True
        if numeric == 0.0:
            return False
    text = str(value).strip().casefold()
    if text in {"true", "yes", "y", "1"}:
        return True
    if text in {"false", "no", "n", "0"}:
        return False
    return None


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


def _optional_float(value: object) -> float | None:
    if value is None or _is_nullish(value):
        return None
    return _to_float(value)


def _optional_int(value: object) -> int | None:
    if _is_nullish(value):
        return None
    number = _to_float(value)
    if number is None:
        return None
    return int(number)


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
    "ANALYSIS_SUITE_GENOME_PATH_SCHEMA_VERSION",
    "DEFAULT_GENOME_PATH_SAMPLE_LIMIT",
    "MAX_GENOME_PATH_SAMPLE_LIMIT",
    "AnalysisSuiteGenomeAnchorKind",
    "AnalysisSuiteGenomeComponentDefinition",
    "AnalysisSuiteGenomeEncodingDefinition",
    "AnalysisSuiteGenomeEncodingMethod",
    "AnalysisSuiteGenomePath",
    "AnalysisSuiteGenomePathBuilder",
    "AnalysisSuiteGenomePathPreviewReport",
    "AnalysisSuiteGenomePathStatus",
    "AnalysisSuiteGenomeSnapshot",
    "AnalysisSuiteStaticBinRule",
]
