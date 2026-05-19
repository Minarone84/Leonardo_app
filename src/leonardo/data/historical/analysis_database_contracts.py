from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from leonardo.data.naming import MarketId, canonicalize

ANALYSIS_DATABASE_SCHEMA_VERSION = 1
ANALYSIS_DATABASE_ARTIFACT_TYPE = "analysis_database"
ANALYSIS_DATABASE_DATASET_TYPE = "analysis_databases"
ANALYSIS_DATABASE_MANIFEST_FILENAME = "manifest.json"
ANALYSIS_DATABASE_DATAFRAME_FILENAME = "dataframe.csv"

BASE_OHLC_COLUMNS: tuple[str, str, str, str] = ("open", "high", "low", "close")
BASE_OHLCV_COLUMNS: tuple[str, str, str, str, str, str] = (
    "ts_ms",
    "open",
    "high",
    "low",
    "close",
    "volume",
)

AnalysisDatabaseStatus = Literal["draft", "materialized", "stale", "missing_source", "error"]
AnalysisSourceFamily = Literal["ohlcv", "indicators", "oscillators", "constructs"]
AnalysisDerivedFamily = Literal["indicators", "oscillators", "constructs"]
AnalysisColumnRole = Literal["primary_key", "base", "feature"]
AnalysisMetadataStatus = Literal["explicit", "inferred", "unknown", "not_applicable"]

_IDENTIFIER_RE = re.compile(r"^[a-z][a-z0-9_]*$")

# JSON values are intentionally typed as Any at runtime so Python's normal
# json encoder remains the validation authority.
JsonValue = Any


def market_to_dict(market: MarketId) -> dict[str, str]:
    return {
        "exchange": market.exchange,
        "market_type": market.market_type,
        "symbol": market.symbol,
        "timeframe": market.timeframe,
    }


def market_from_dict(data: dict[str, object]) -> MarketId:
    return canonicalize(
        str(data.get("exchange", "")),
        str(data.get("market_type", "")),
        str(data.get("symbol", "")),
        str(data.get("timeframe", "")),
    )


def _require_identifier(value: str, *, field_name: str) -> None:
    if not _IDENTIFIER_RE.fullmatch(value):
        raise ValueError(f"{field_name} must be lowercase snake_case; got {value!r}")


def _require_json_serializable(value: JsonValue, *, field_name: str) -> None:
    try:
        json.dumps(value, sort_keys=True, separators=(",", ":"))
    except TypeError as exc:
        raise TypeError(f"{field_name} must be JSON-serializable") from exc


def _metadata_tuple(values: tuple["AnalysisMetadataEntry", ...] | list["AnalysisMetadataEntry"] | None) -> tuple["AnalysisMetadataEntry", ...]:
    if values is None:
        return ()
    return tuple(values)


@dataclass(frozen=True)
class AnalysisMetadataEntry:
    """Extensible namespaced metadata entry for analysis database artifacts.

    Metadata is not identity-affecting by default. Only entries explicitly
    marked ``identity_affecting=True`` may participate in recipe hashing.
    """

    namespace: str
    key: str
    value: JsonValue
    value_type: str = "json"
    label: str = ""
    description: str = ""
    tags: tuple[str, ...] = ()
    searchable: bool = False
    identity_affecting: bool = False

    def __post_init__(self) -> None:
        _require_identifier(str(self.namespace), field_name="metadata.namespace")
        _require_identifier(str(self.key), field_name="metadata.key")
        _require_json_serializable(self.value, field_name=f"metadata.{self.namespace}.{self.key}")
        object.__setattr__(self, "tags", tuple(str(tag) for tag in self.tags))

    def to_dict(self) -> dict[str, object]:
        return {
            "namespace": self.namespace,
            "key": self.key,
            "value": self.value,
            "value_type": self.value_type,
            "label": self.label,
            "description": self.description,
            "tags": list(self.tags),
            "searchable": bool(self.searchable),
            "identity_affecting": bool(self.identity_affecting),
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "AnalysisMetadataEntry":
        return cls(
            namespace=str(data.get("namespace", "")),
            key=str(data.get("key", "")),
            value=data.get("value"),
            value_type=str(data.get("value_type", "json")),
            label=str(data.get("label", "")),
            description=str(data.get("description", "")),
            tags=tuple(str(tag) for tag in data.get("tags", ()) or ()),  # type: ignore[arg-type]
            searchable=bool(data.get("searchable", False)),
            identity_affecting=bool(data.get("identity_affecting", False)),
        )


@dataclass(frozen=True)
class AnalysisDatabaseDescription:
    user_text: str = ""
    generated_summary: str = ""
    studies_used_summary: str = ""
    notes: str = ""
    metadata: tuple[AnalysisMetadataEntry, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "metadata", _metadata_tuple(self.metadata))

    def to_dict(self) -> dict[str, object]:
        return {
            "user_text": self.user_text,
            "generated_summary": self.generated_summary,
            "studies_used_summary": self.studies_used_summary,
            "notes": self.notes,
            "metadata": [entry.to_dict() for entry in self.metadata],
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "AnalysisDatabaseDescription":
        return cls(
            user_text=str(data.get("user_text", "")),
            generated_summary=str(data.get("generated_summary", "")),
            studies_used_summary=str(data.get("studies_used_summary", "")),
            notes=str(data.get("notes", "")),
            metadata=tuple(AnalysisMetadataEntry.from_dict(dict(item)) for item in data.get("metadata", ()) or ()),  # type: ignore[arg-type]
        )


@dataclass(frozen=True)
class AnalysisDatabaseAlignment:
    primary_key: Literal["ts_ms"] = "ts_ms"
    join_type: Literal["left_on_ohlcv"] = "left_on_ohlcv"
    duplicate_policy: Literal["reject"] = "reject"
    missing_policy: Literal["preserve_nan"] = "preserve_nan"
    position_only_alignment_allowed: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "primary_key": self.primary_key,
            "join_type": self.join_type,
            "duplicate_policy": self.duplicate_policy,
            "missing_policy": self.missing_policy,
            "position_only_alignment_allowed": bool(self.position_only_alignment_allowed),
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "AnalysisDatabaseAlignment":
        return cls(
            primary_key="ts_ms",
            join_type="left_on_ohlcv",
            duplicate_policy="reject",
            missing_policy="preserve_nan",
            position_only_alignment_allowed=bool(data.get("position_only_alignment_allowed", False)),
        )


@dataclass(frozen=True)
class AnalysisFeatureSource:
    source_id: str
    family: AnalysisDerivedFamily
    tool_key: str
    tool_title: str
    instance_key: str
    source_artifact_filename: str
    source_artifact_relpath: str
    source_artifact_sha256: str | None = None
    source_artifact_size_bytes: int | None = None
    source_artifact_modified_at_ms: int | None = None
    params: dict[str, JsonValue] = field(default_factory=dict)
    params_status: Literal["explicit", "inferred", "unknown"] = "unknown"
    bindings: dict[str, JsonValue] = field(default_factory=dict)
    bindings_status: AnalysisMetadataStatus = "unknown"
    metadata: tuple[AnalysisMetadataEntry, ...] = ()

    def __post_init__(self) -> None:
        if self.family not in {"indicators", "oscillators", "constructs"}:
            raise ValueError(f"Unsupported analysis feature source family: {self.family!r}")
        _require_json_serializable(self.params, field_name="feature_source.params")
        _require_json_serializable(self.bindings, field_name="feature_source.bindings")
        object.__setattr__(self, "params", dict(self.params))
        object.__setattr__(self, "bindings", dict(self.bindings))
        object.__setattr__(self, "metadata", _metadata_tuple(self.metadata))

    def to_dict(self) -> dict[str, object]:
        return {
            "source_id": self.source_id,
            "family": self.family,
            "tool_key": self.tool_key,
            "tool_title": self.tool_title,
            "instance_key": self.instance_key,
            "source_artifact_filename": self.source_artifact_filename,
            "source_artifact_relpath": self.source_artifact_relpath,
            "source_artifact_sha256": self.source_artifact_sha256,
            "source_artifact_size_bytes": self.source_artifact_size_bytes,
            "source_artifact_modified_at_ms": self.source_artifact_modified_at_ms,
            "params": dict(self.params),
            "params_status": self.params_status,
            "bindings": dict(self.bindings),
            "bindings_status": self.bindings_status,
            "metadata": [entry.to_dict() for entry in self.metadata],
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "AnalysisFeatureSource":
        return cls(
            source_id=str(data.get("source_id", "")),
            family=str(data.get("family", "indicators")),  # type: ignore[arg-type]
            tool_key=str(data.get("tool_key", "")),
            tool_title=str(data.get("tool_title", "")),
            instance_key=str(data.get("instance_key", "")),
            source_artifact_filename=str(data.get("source_artifact_filename", "")),
            source_artifact_relpath=str(data.get("source_artifact_relpath", "")),
            source_artifact_sha256=(None if data.get("source_artifact_sha256") is None else str(data.get("source_artifact_sha256"))),
            source_artifact_size_bytes=(None if data.get("source_artifact_size_bytes") is None else int(data.get("source_artifact_size_bytes"))),
            source_artifact_modified_at_ms=(None if data.get("source_artifact_modified_at_ms") is None else int(data.get("source_artifact_modified_at_ms"))),
            params=dict(data.get("params", {}) or {}),  # type: ignore[arg-type]
            params_status=str(data.get("params_status", "unknown")),  # type: ignore[arg-type]
            bindings=dict(data.get("bindings", {}) or {}),  # type: ignore[arg-type]
            bindings_status=str(data.get("bindings_status", "unknown")),  # type: ignore[arg-type]
            metadata=tuple(AnalysisMetadataEntry.from_dict(dict(item)) for item in data.get("metadata", ()) or ()),  # type: ignore[arg-type]
        )


@dataclass(frozen=True)
class AnalysisDatabaseColumn:
    role: AnalysisColumnRole
    selected: bool
    source_family: AnalysisSourceFamily
    source_id: str | None
    source_column_name: str
    db_column_name: str
    dtype: str | None = None
    nullable: bool = True
    analysis_usable: bool | None = None
    renderable: bool | None = None
    locked: bool = False
    metadata: tuple[AnalysisMetadataEntry, ...] = ()

    def __post_init__(self) -> None:
        if self.role not in {"primary_key", "base", "feature"}:
            raise ValueError(f"Unsupported analysis database column role: {self.role!r}")
        if self.source_family not in {"ohlcv", "indicators", "oscillators", "constructs"}:
            raise ValueError(f"Unsupported analysis database source family: {self.source_family!r}")
        object.__setattr__(self, "metadata", _metadata_tuple(self.metadata))

    def to_dict(self) -> dict[str, object]:
        return {
            "role": self.role,
            "selected": bool(self.selected),
            "source_family": self.source_family,
            "source_id": self.source_id,
            "source_column_name": self.source_column_name,
            "db_column_name": self.db_column_name,
            "dtype": self.dtype,
            "nullable": bool(self.nullable),
            "analysis_usable": self.analysis_usable,
            "renderable": self.renderable,
            "locked": bool(self.locked),
            "metadata": [entry.to_dict() for entry in self.metadata],
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "AnalysisDatabaseColumn":
        return cls(
            role=str(data.get("role", "feature")),  # type: ignore[arg-type]
            selected=bool(data.get("selected", True)),
            source_family=str(data.get("source_family", "ohlcv")),  # type: ignore[arg-type]
            source_id=(None if data.get("source_id") is None else str(data.get("source_id"))),
            source_column_name=str(data.get("source_column_name", "")),
            db_column_name=str(data.get("db_column_name", "")),
            dtype=(None if data.get("dtype") is None else str(data.get("dtype"))),
            nullable=bool(data.get("nullable", True)),
            analysis_usable=(None if data.get("analysis_usable") is None else bool(data.get("analysis_usable"))),
            renderable=(None if data.get("renderable") is None else bool(data.get("renderable"))),
            locked=bool(data.get("locked", False)),
            metadata=tuple(AnalysisMetadataEntry.from_dict(dict(item)) for item in data.get("metadata", ()) or ()),  # type: ignore[arg-type]
        )


@dataclass(frozen=True)
class AnalysisDatabaseMaterialization:
    row_count: int
    column_count: int
    first_ts_ms: int | None
    last_ts_ms: int | None
    dataframe_sha256: str | None
    created_at_ms: int
    updated_at_ms: int
    metadata: tuple[AnalysisMetadataEntry, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "metadata", _metadata_tuple(self.metadata))

    def to_dict(self) -> dict[str, object]:
        return {
            "row_count": int(self.row_count),
            "column_count": int(self.column_count),
            "first_ts_ms": self.first_ts_ms,
            "last_ts_ms": self.last_ts_ms,
            "dataframe_sha256": self.dataframe_sha256,
            "created_at_ms": int(self.created_at_ms),
            "updated_at_ms": int(self.updated_at_ms),
            "metadata": [entry.to_dict() for entry in self.metadata],
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "AnalysisDatabaseMaterialization":
        return cls(
            row_count=int(data.get("row_count", 0)),
            column_count=int(data.get("column_count", 0)),
            first_ts_ms=(None if data.get("first_ts_ms") is None else int(data.get("first_ts_ms"))),
            last_ts_ms=(None if data.get("last_ts_ms") is None else int(data.get("last_ts_ms"))),
            dataframe_sha256=(None if data.get("dataframe_sha256") is None else str(data.get("dataframe_sha256"))),
            created_at_ms=int(data.get("created_at_ms", 0)),
            updated_at_ms=int(data.get("updated_at_ms", 0)),
            metadata=tuple(AnalysisMetadataEntry.from_dict(dict(item)) for item in data.get("metadata", ()) or ()),  # type: ignore[arg-type]
        )


@dataclass(frozen=True)
class AnalysisDatabaseManifest:
    schema_version: int
    artifact_type: Literal["analysis_database"]
    database_id: str
    display_name: str
    status: AnalysisDatabaseStatus
    description: AnalysisDatabaseDescription
    market: MarketId
    dataframe_filename: str | None
    alignment: AnalysisDatabaseAlignment
    base_columns: tuple[AnalysisDatabaseColumn, ...]
    feature_sources: tuple[AnalysisFeatureSource, ...]
    feature_columns: tuple[AnalysisDatabaseColumn, ...]
    recipe_hash: str
    recipe_hash_short: str
    materialization: AnalysisDatabaseMaterialization | None = None
    metadata: tuple[AnalysisMetadataEntry, ...] = ()

    def __post_init__(self) -> None:
        if self.schema_version != ANALYSIS_DATABASE_SCHEMA_VERSION:
            raise ValueError(f"Unsupported analysis database schema_version: {self.schema_version}")
        if self.artifact_type != ANALYSIS_DATABASE_ARTIFACT_TYPE:
            raise ValueError(f"Unsupported analysis database artifact_type: {self.artifact_type!r}")
        object.__setattr__(self, "base_columns", tuple(self.base_columns))
        object.__setattr__(self, "feature_sources", tuple(self.feature_sources))
        object.__setattr__(self, "feature_columns", tuple(self.feature_columns))
        object.__setattr__(self, "metadata", _metadata_tuple(self.metadata))

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "artifact_type": self.artifact_type,
            "database_id": self.database_id,
            "display_name": self.display_name,
            "status": self.status,
            "description": self.description.to_dict(),
            "market": market_to_dict(self.market),
            "files": {
                "manifest_filename": ANALYSIS_DATABASE_MANIFEST_FILENAME,
                "dataframe_filename": self.dataframe_filename,
            },
            "dataframe_filename": self.dataframe_filename,
            "alignment": self.alignment.to_dict(),
            "base_columns": [column.to_dict() for column in self.base_columns],
            "feature_sources": [source.to_dict() for source in self.feature_sources],
            "feature_columns": [column.to_dict() for column in self.feature_columns],
            "recipe": {
                "recipe_hash": self.recipe_hash,
                "recipe_hash_short": self.recipe_hash_short,
            },
            "recipe_hash": self.recipe_hash,
            "recipe_hash_short": self.recipe_hash_short,
            "materialization": None if self.materialization is None else self.materialization.to_dict(),
            "metadata": [entry.to_dict() for entry in self.metadata],
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "AnalysisDatabaseManifest":
        recipe = dict(data.get("recipe", {}) or {})  # type: ignore[arg-type]
        files = dict(data.get("files", {}) or {})  # type: ignore[arg-type]
        materialization_raw = data.get("materialization")
        return cls(
            schema_version=int(data.get("schema_version", 0)),
            artifact_type=str(data.get("artifact_type", "")),  # type: ignore[arg-type]
            database_id=str(data.get("database_id", "")),
            display_name=str(data.get("display_name", "")),
            status=str(data.get("status", "draft")),  # type: ignore[arg-type]
            description=AnalysisDatabaseDescription.from_dict(dict(data.get("description", {}) or {})),  # type: ignore[arg-type]
            market=market_from_dict(dict(data.get("market", {}) or {})),  # type: ignore[arg-type]
            dataframe_filename=(
                None
                if (data.get("dataframe_filename") is None and files.get("dataframe_filename") is None)
                else str(data.get("dataframe_filename", files.get("dataframe_filename")))
            ),
            alignment=AnalysisDatabaseAlignment.from_dict(dict(data.get("alignment", {}) or {})),  # type: ignore[arg-type]
            base_columns=tuple(AnalysisDatabaseColumn.from_dict(dict(item)) for item in data.get("base_columns", ()) or ()),  # type: ignore[arg-type]
            feature_sources=tuple(AnalysisFeatureSource.from_dict(dict(item)) for item in data.get("feature_sources", ()) or ()),  # type: ignore[arg-type]
            feature_columns=tuple(AnalysisDatabaseColumn.from_dict(dict(item)) for item in data.get("feature_columns", ()) or ()),  # type: ignore[arg-type]
            recipe_hash=str(data.get("recipe_hash", recipe.get("recipe_hash", ""))),
            recipe_hash_short=str(data.get("recipe_hash_short", recipe.get("recipe_hash_short", ""))),
            materialization=(None if materialization_raw is None else AnalysisDatabaseMaterialization.from_dict(dict(materialization_raw))),  # type: ignore[arg-type]
            metadata=tuple(AnalysisMetadataEntry.from_dict(dict(item)) for item in data.get("metadata", ()) or ()),  # type: ignore[arg-type]
        )


@dataclass(frozen=True)
class AnalysisDatabaseSummary:
    database_id: str
    display_name: str
    status: AnalysisDatabaseStatus
    market: MarketId
    user_description: str
    generated_summary: str
    studies_used_summary: str
    row_count: int | None
    column_count: int | None
    feature_count: int
    created_at_ms: int | None
    updated_at_ms: int | None
    manifest_path: Path
    metadata: tuple[AnalysisMetadataEntry, ...] = ()

    @classmethod
    def from_manifest(cls, manifest: AnalysisDatabaseManifest, *, manifest_path: Path) -> "AnalysisDatabaseSummary":
        materialization = manifest.materialization
        return cls(
            database_id=manifest.database_id,
            display_name=manifest.display_name,
            status=manifest.status,
            market=manifest.market,
            user_description=manifest.description.user_text,
            generated_summary=manifest.description.generated_summary,
            studies_used_summary=manifest.description.studies_used_summary,
            row_count=None if materialization is None else materialization.row_count,
            column_count=None if materialization is None else materialization.column_count,
            feature_count=len(manifest.feature_columns),
            created_at_ms=None if materialization is None else materialization.created_at_ms,
            updated_at_ms=None if materialization is None else materialization.updated_at_ms,
            manifest_path=manifest_path,
            metadata=manifest.metadata,
        )
