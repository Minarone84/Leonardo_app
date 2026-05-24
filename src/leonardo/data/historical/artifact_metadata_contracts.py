from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from leonardo.data.naming import MarketId, canonicalize

from .artifact_metadata_naming import (
    CSV_METADATA_SUFFIX,
    ROME_TIMEZONE,
    build_artifact_uid,
    format_ts_ms_rome,
    format_ts_ms_utc,
    metadata_path_for_csv,
    storage_family_for_artifact_family,
)

ARTIFACT_METADATA_SCHEMA_VERSION = 1
HISTORICAL_CSV_ARTIFACT_TYPE = "historical_csv_artifact"
ARTIFACT_METADATA_FILENAME_SUFFIX = CSV_METADATA_SUFFIX
ARTIFACT_METADATA_TIMEZONE = ROME_TIMEZONE

ArtifactFamily = Literal["ohlcv", "indicator", "oscillator", "construct", "analysis_database"]
ArtifactStorageFamily = Literal["ohlcv", "indicators", "oscillators", "constructs", "analysis_databases"]
ArtifactToolFamily = Literal["indicator", "oscillator", "construct"]
ArtifactColumnRole = Literal["primary_key", "base", "feature", "utility"]
ArtifactMetadataStatus = Literal["explicit", "inferred", "unknown", "not_applicable"]
ArtifactToolIdentityStatus = Literal["explicit", "inferred", "unknown"]
ArtifactSha256Status = Literal["computed", "not_computed", "unknown", "error"]
ArtifactTimelineStatus = Literal["verified", "assumed_sorted", "unverified", "error"]
ArtifactValidationStatus = Literal["not_validated", "ok", "modified", "warning", "error"]
ArtifactValidationResultStatus = Literal["unknown", "ok", "modified", "warning", "error"]
JsonValue = Any

_IDENTIFIER_RE = re.compile(r"^[a-z][a-z0-9_]*$")


def market_to_dict(market: MarketId) -> dict[str, str]:
    return {"exchange": market.exchange, "market_type": market.market_type, "symbol": market.symbol, "timeframe": market.timeframe}


def market_from_dict(data: dict[str, object]) -> MarketId:
    return canonicalize(str(data.get("exchange", "")), str(data.get("market_type", "")), str(data.get("symbol", "")), str(data.get("timeframe", "")))


def _require_identifier(value: str, *, field_name: str) -> None:
    if not _IDENTIFIER_RE.fullmatch(str(value)):
        raise ValueError(f"{field_name} must be lowercase snake_case; got {value!r}")


def _require_json_serializable(value: JsonValue, *, field_name: str) -> None:
    try:
        json.dumps(value, sort_keys=True, separators=(",", ":"))
    except TypeError as exc:
        raise TypeError(f"{field_name} must be JSON-serializable") from exc


def _metadata_tuple(values) -> tuple["ArtifactMetadataEntry", ...]:
    return tuple(values or ())


def _str_tuple(values: object) -> tuple[str, ...]:
    return tuple(str(item) for item in (values or ()))  # type: ignore[arg-type]


def _dict_or_empty(value: object) -> dict[str, JsonValue]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise TypeError(f"Expected JSON object; got {type(value).__name__}")
    return dict(value)


@dataclass(frozen=True)
class ArtifactMetadataEntry:
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
        _require_identifier(self.namespace, field_name="metadata.namespace")
        _require_identifier(self.key, field_name="metadata.key")
        _require_json_serializable(self.value, field_name=f"metadata.{self.namespace}.{self.key}")
        object.__setattr__(self, "tags", tuple(str(tag) for tag in self.tags))

    def to_dict(self) -> dict[str, object]:
        return {"namespace": self.namespace, "key": self.key, "value": self.value, "value_type": self.value_type, "label": self.label, "description": self.description, "tags": list(self.tags), "searchable": bool(self.searchable), "identity_affecting": bool(self.identity_affecting)}

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "ArtifactMetadataEntry":
        return cls(namespace=str(data.get("namespace", "")), key=str(data.get("key", "")), value=data.get("value"), value_type=str(data.get("value_type", "json")), label=str(data.get("label", "")), description=str(data.get("description", "")), tags=tuple(str(tag) for tag in data.get("tags", ()) or ()), searchable=bool(data.get("searchable", False)), identity_affecting=bool(data.get("identity_affecting", False)))  # type: ignore[arg-type]


@dataclass(frozen=True)
class ArtifactIdentity:
    unique_id: str
    artifact_family: ArtifactFamily
    storage_family: ArtifactStorageFamily
    artifact_id: str
    artifact_uid: str
    artifact_version: int = 1

    def __post_init__(self) -> None:
        expected = storage_family_for_artifact_family(self.artifact_family)
        if self.storage_family != expected:
            raise ValueError(f"storage_family {self.storage_family!r} does not match artifact_family {self.artifact_family!r}; expected {expected!r}")
        if not self.unique_id or not self.artifact_id or not self.artifact_uid:
            raise ValueError("unique_id, artifact_id, and artifact_uid are required")
        if int(self.artifact_version) < 1:
            raise ValueError("artifact_version must be >= 1")

    def to_dict(self) -> dict[str, object]:
        return {"unique_id": self.unique_id, "artifact_family": self.artifact_family, "storage_family": self.storage_family, "artifact_id": self.artifact_id, "artifact_uid": self.artifact_uid, "artifact_version": int(self.artifact_version)}

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "ArtifactIdentity":
        return cls(unique_id=str(data.get("unique_id", "")), artifact_family=str(data.get("artifact_family", "ohlcv")), storage_family=str(data.get("storage_family", "ohlcv")), artifact_id=str(data.get("artifact_id", "")), artifact_uid=str(data.get("artifact_uid", "")), artifact_version=int(data.get("artifact_version", 1)))  # type: ignore[arg-type]


@dataclass(frozen=True)
class ArtifactFiles:
    csv_filename: str
    csv_relpath: str
    metadata_filename: str
    metadata_relpath: str
    data_format: Literal["csv"] = "csv"

    def __post_init__(self) -> None:
        if self.data_format != "csv":
            raise ValueError("Only csv data_format is supported")
        if not self.csv_filename.endswith(".csv"):
            raise ValueError("files.csv_filename must end with .csv")
        if not self.metadata_filename.endswith(ARTIFACT_METADATA_FILENAME_SUFFIX):
            raise ValueError(f"files.metadata_filename must end with {ARTIFACT_METADATA_FILENAME_SUFFIX!r}")
        if not self.csv_relpath or not self.metadata_relpath:
            raise ValueError("csv_relpath and metadata_relpath are required")

    def to_dict(self) -> dict[str, object]:
        return {"data_format": self.data_format, "csv_filename": self.csv_filename, "csv_relpath": self.csv_relpath, "metadata_filename": self.metadata_filename, "metadata_relpath": self.metadata_relpath}

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "ArtifactFiles":
        return cls(csv_filename=str(data.get("csv_filename", "")), csv_relpath=str(data.get("csv_relpath", "")), metadata_filename=str(data.get("metadata_filename", "")), metadata_relpath=str(data.get("metadata_relpath", "")), data_format="csv")


@dataclass(frozen=True)
class ArtifactTimeRange:
    first_ts_ms: int | None
    last_ts_ms: int | None
    first_ts_utc: str = ""
    first_ts_rome: str = ""
    last_ts_utc: str = ""
    last_ts_rome: str = ""
    timezone: Literal["Europe/Rome"] = "Europe/Rome"

    def __post_init__(self) -> None:
        object.__setattr__(self, "first_ts_utc", self.first_ts_utc or format_ts_ms_utc(self.first_ts_ms))
        object.__setattr__(self, "first_ts_rome", self.first_ts_rome or format_ts_ms_rome(self.first_ts_ms))
        object.__setattr__(self, "last_ts_utc", self.last_ts_utc or format_ts_ms_utc(self.last_ts_ms))
        object.__setattr__(self, "last_ts_rome", self.last_ts_rome or format_ts_ms_rome(self.last_ts_ms))

    @classmethod
    def from_ts_ms(cls, *, first_ts_ms: int | None, last_ts_ms: int | None) -> "ArtifactTimeRange":
        return cls(first_ts_ms=first_ts_ms, last_ts_ms=last_ts_ms)

    def to_dict(self) -> dict[str, object]:
        return {"first_ts_ms": self.first_ts_ms, "first_ts_utc": self.first_ts_utc, "first_ts_rome": self.first_ts_rome, "last_ts_ms": self.last_ts_ms, "last_ts_utc": self.last_ts_utc, "last_ts_rome": self.last_ts_rome, "timezone": self.timezone}

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "ArtifactTimeRange":
        return cls(first_ts_ms=None if data.get("first_ts_ms") is None else int(data.get("first_ts_ms")), first_ts_utc=str(data.get("first_ts_utc", "")), first_ts_rome=str(data.get("first_ts_rome", "")), last_ts_ms=None if data.get("last_ts_ms") is None else int(data.get("last_ts_ms")), last_ts_utc=str(data.get("last_ts_utc", "")), last_ts_rome=str(data.get("last_ts_rome", "")), timezone="Europe/Rome")


@dataclass(frozen=True)
class ArtifactShape:
    row_count: int | None
    column_count: int
    columns: tuple[str, ...]
    primary_key: Literal["ts_ms"] = "ts_ms"

    def __post_init__(self) -> None:
        cols = tuple(str(column) for column in self.columns)
        object.__setattr__(self, "columns", cols)
        if self.primary_key not in cols:
            raise ValueError("Artifact shape must include primary_key 'ts_ms' in columns")
        if int(self.column_count) != len(cols):
            raise ValueError("shape.column_count must match len(shape.columns)")
        if self.row_count is not None and int(self.row_count) < 0:
            raise ValueError("shape.row_count cannot be negative")

    def to_dict(self) -> dict[str, object]:
        return {"row_count": self.row_count, "column_count": int(self.column_count), "columns": list(self.columns), "primary_key": self.primary_key}

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "ArtifactShape":
        columns = tuple(str(column) for column in data.get("columns", ()) or ())  # type: ignore[arg-type]
        return cls(row_count=None if data.get("row_count") is None else int(data.get("row_count")), column_count=int(data.get("column_count", len(columns))), columns=columns, primary_key="ts_ms")


@dataclass(frozen=True)
class ArtifactColumnMetadata:
    name: str
    role: ArtifactColumnRole
    dtype: str | None = None
    selectable: bool = True
    analysis_usable: bool | None = None
    renderable: bool | None = None
    label: str = ""
    description: str = ""
    semantic_role: str = "primary"
    value_type: str = "numeric"
    signal_type: str | None = None
    default_visible: bool | None = None
    can_drive_style_rules: bool | None = None
    metadata: tuple[ArtifactMetadataEntry, ...] = ()

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("column.name is required")
        if self.role not in {"primary_key", "base", "feature", "utility"}:
            raise ValueError(f"Unsupported artifact column role: {self.role!r}")
        object.__setattr__(self, "metadata", _metadata_tuple(self.metadata))

    def to_dict(self) -> dict[str, object]:
        return {"name": self.name, "role": self.role, "dtype": self.dtype, "selectable": bool(self.selectable), "analysis_usable": self.analysis_usable, "renderable": self.renderable, "label": self.label, "description": self.description, "semantic_role": self.semantic_role, "value_type": self.value_type, "signal_type": self.signal_type, "default_visible": self.default_visible, "can_drive_style_rules": self.can_drive_style_rules, "metadata": [entry.to_dict() for entry in self.metadata]}

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "ArtifactColumnMetadata":
        return cls(name=str(data.get("name", "")), role=str(data.get("role", "feature")), dtype=None if data.get("dtype") is None else str(data.get("dtype")), selectable=bool(data.get("selectable", True)), analysis_usable=None if data.get("analysis_usable") is None else bool(data.get("analysis_usable")), renderable=None if data.get("renderable") is None else bool(data.get("renderable")), label=str(data.get("label", "")), description=str(data.get("description", "")), semantic_role=str(data.get("semantic_role", "primary")), value_type=str(data.get("value_type", "numeric")), signal_type=None if data.get("signal_type") is None else str(data.get("signal_type")), default_visible=None if data.get("default_visible") is None else bool(data.get("default_visible")), can_drive_style_rules=None if data.get("can_drive_style_rules") is None else bool(data.get("can_drive_style_rules")), metadata=tuple(ArtifactMetadataEntry.from_dict(dict(item)) for item in data.get("metadata", ()) or ()))  # type: ignore[arg-type]


@dataclass(frozen=True)
class ArtifactDataInputMetadata:
    name: str
    dtype: str
    required: bool = True
    label: str = ""
    description: str = ""

    def to_dict(self) -> dict[str, object]:
        return {"name": self.name, "dtype": self.dtype, "required": bool(self.required), "label": self.label, "description": self.description}

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "ArtifactDataInputMetadata":
        return cls(name=str(data.get("name", "")), dtype=str(data.get("dtype", "")), required=bool(data.get("required", True)), label=str(data.get("label", "")), description=str(data.get("description", "")))

    @classmethod
    def from_contract(cls, contract: object) -> "ArtifactDataInputMetadata":
        return cls(name=str(getattr(contract, "name", "")), dtype=str(getattr(contract, "dtype", "")), required=bool(getattr(contract, "required", True)), label=str(getattr(contract, "label", "")), description=str(getattr(contract, "description", "")))


@dataclass(frozen=True)
class ArtifactParamContractMetadata:
    name: str
    dtype: str
    value: JsonValue = None
    default: JsonValue = None
    required: bool = True
    label: str = ""
    description: str = ""
    minimum: float | int | None = None
    maximum: float | int | None = None
    choices: tuple[JsonValue, ...] = ()

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("param.name is required")
        _require_json_serializable(self.value, field_name=f"param.{self.name}.value")
        _require_json_serializable(self.default, field_name=f"param.{self.name}.default")
        object.__setattr__(self, "choices", tuple(self.choices))

    def to_dict(self) -> dict[str, object]:
        return {"name": self.name, "dtype": self.dtype, "value": self.value, "default": self.default, "required": bool(self.required), "label": self.label, "description": self.description, "minimum": self.minimum, "maximum": self.maximum, "choices": list(self.choices)}

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "ArtifactParamContractMetadata":
        return cls(name=str(data.get("name", "")), dtype=str(data.get("dtype", "str")), value=data.get("value"), default=data.get("default"), required=bool(data.get("required", True)), label=str(data.get("label", "")), description=str(data.get("description", "")), minimum=data.get("minimum"), maximum=data.get("maximum"), choices=tuple(data.get("choices", ()) or ()))  # type: ignore[arg-type]

    @classmethod
    def from_contract(cls, contract: object, *, value: JsonValue = None) -> "ArtifactParamContractMetadata":
        return cls(name=str(getattr(contract, "name", "")), dtype=str(getattr(contract, "dtype", "str")), value=value, default=getattr(contract, "default", None), required=bool(getattr(contract, "required", True)), label=str(getattr(contract, "label", "")), description=str(getattr(contract, "description", "")), minimum=getattr(contract, "minimum", None), maximum=getattr(contract, "maximum", None), choices=tuple(getattr(contract, "choices", ()) or ()))


# Short alias used by some callers.
ArtifactParamMetadata = ArtifactParamContractMetadata


@dataclass(frozen=True)
class ArtifactOutputSignalMetadata:
    signal_type: str = "signal"
    renderable: bool = True
    analysis_usable: bool = True
    default_visible: bool = True
    label: str = ""
    description: str = ""
    semantic_role: str = "primary"
    value_type: str = "numeric"
    can_drive_style_rules: bool = False

    def to_dict(self) -> dict[str, object]:
        return {"signal_type": self.signal_type, "renderable": bool(self.renderable), "analysis_usable": bool(self.analysis_usable), "default_visible": bool(self.default_visible), "label": self.label, "description": self.description, "semantic_role": self.semantic_role, "value_type": self.value_type, "can_drive_style_rules": bool(self.can_drive_style_rules)}

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "ArtifactOutputSignalMetadata":
        return cls(signal_type=str(data.get("signal_type", "signal")), renderable=bool(data.get("renderable", True)), analysis_usable=bool(data.get("analysis_usable", True)), default_visible=bool(data.get("default_visible", True)), label=str(data.get("label", "")), description=str(data.get("description", "")), semantic_role=str(data.get("semantic_role", "primary")), value_type=str(data.get("value_type", "numeric")), can_drive_style_rules=bool(data.get("can_drive_style_rules", False)))

    @classmethod
    def from_contract(cls, contract: object) -> "ArtifactOutputSignalMetadata":
        return cls(signal_type=str(getattr(contract, "signal_type", "signal")), renderable=bool(getattr(contract, "renderable", True)), analysis_usable=bool(getattr(contract, "analysis_usable", True)), default_visible=bool(getattr(contract, "default_visible", True)), label=str(getattr(contract, "label", "")), description=str(getattr(contract, "description", "")), semantic_role=str(getattr(contract, "semantic_role", "primary")), value_type=str(getattr(contract, "value_type", "numeric")), can_drive_style_rules=bool(getattr(contract, "can_drive_style_rules", False)))


@dataclass(frozen=True)
class ArtifactOutputMetadata:
    structure: str
    naming_resolver: str
    signals: tuple[ArtifactOutputSignalMetadata, ...] = ()
    dynamic_signals: bool = False
    accepts_empty_render_output: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "signals", tuple(self.signals))

    def to_dict(self) -> dict[str, object]:
        return {"structure": self.structure, "naming_resolver": self.naming_resolver, "signals": [signal.to_dict() for signal in self.signals], "dynamic_signals": bool(self.dynamic_signals), "accepts_empty_render_output": bool(self.accepts_empty_render_output)}

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "ArtifactOutputMetadata":
        return cls(structure=str(data.get("structure", "")), naming_resolver=str(data.get("naming_resolver", "")), signals=tuple(ArtifactOutputSignalMetadata.from_dict(dict(item)) for item in data.get("signals", ()) or ()), dynamic_signals=bool(data.get("dynamic_signals", False)), accepts_empty_render_output=bool(data.get("accepts_empty_render_output", False)))  # type: ignore[arg-type]

    @classmethod
    def from_contract(cls, contract: object | None) -> "ArtifactOutputMetadata | None":
        if contract is None:
            return None
        return cls(structure=str(getattr(contract, "structure", "")), naming_resolver=str(getattr(contract, "naming_resolver", "")), signals=tuple(ArtifactOutputSignalMetadata.from_contract(signal) for signal in getattr(contract, "signals", ()) or ()), dynamic_signals=bool(getattr(contract, "dynamic_signals", False)), accepts_empty_render_output=bool(getattr(contract, "accepts_empty_render_output", False)))


@dataclass(frozen=True)
class ArtifactBehaviorMetadata:
    output_mode: str
    chart_renderable: bool = True
    supports_style: bool = True
    supports_pane_layout: bool = False
    supports_last_value: bool = True
    supported_environments: tuple[str, ...] = ("historical",)
    default_environment: str = "historical"

    def __post_init__(self) -> None:
        object.__setattr__(self, "supported_environments", tuple(str(item) for item in self.supported_environments))

    def to_dict(self) -> dict[str, object]:
        return {"output_mode": self.output_mode, "chart_renderable": bool(self.chart_renderable), "supports_style": bool(self.supports_style), "supports_pane_layout": bool(self.supports_pane_layout), "supports_last_value": bool(self.supports_last_value), "supported_environments": list(self.supported_environments), "default_environment": self.default_environment}

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "ArtifactBehaviorMetadata":
        return cls(output_mode=str(data.get("output_mode", "")), chart_renderable=bool(data.get("chart_renderable", True)), supports_style=bool(data.get("supports_style", True)), supports_pane_layout=bool(data.get("supports_pane_layout", False)), supports_last_value=bool(data.get("supports_last_value", True)), supported_environments=_str_tuple(data.get("supported_environments", ("historical",))), default_environment=str(data.get("default_environment", "historical")))

    @classmethod
    def from_contract(cls, contract: object | None) -> "ArtifactBehaviorMetadata | None":
        if contract is None:
            return None
        return cls(output_mode=str(getattr(contract, "output_mode", "")), chart_renderable=bool(getattr(contract, "chart_renderable", True)), supports_style=bool(getattr(contract, "supports_style", True)), supports_pane_layout=bool(getattr(contract, "supports_pane_layout", False)), supports_last_value=bool(getattr(contract, "supports_last_value", True)), supported_environments=tuple(str(item) for item in getattr(contract, "supported_environments", ("historical",)) or ()), default_environment=str(getattr(contract, "default_environment", "historical")))


@dataclass(frozen=True)
class ArtifactConstructIOMetadata:
    input_binding: str
    allowed_source_families: tuple[str, ...]
    source_compatibility: str = "mixed_numeric"
    output_cardinality: str = "single"
    output_role: str = "plotted_line"

    def __post_init__(self) -> None:
        object.__setattr__(self, "allowed_source_families", tuple(str(item) for item in self.allowed_source_families))

    def to_dict(self) -> dict[str, object]:
        return {"input_binding": self.input_binding, "allowed_source_families": list(self.allowed_source_families), "source_compatibility": self.source_compatibility, "output_cardinality": self.output_cardinality, "output_role": self.output_role}

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "ArtifactConstructIOMetadata":
        return cls(input_binding=str(data.get("input_binding", "")), allowed_source_families=_str_tuple(data.get("allowed_source_families", ())), source_compatibility=str(data.get("source_compatibility", "mixed_numeric")), output_cardinality=str(data.get("output_cardinality", "single")), output_role=str(data.get("output_role", "plotted_line")))

    @classmethod
    def from_contract(cls, contract: object | None) -> "ArtifactConstructIOMetadata | None":
        if contract is None:
            return None
        return cls(input_binding=str(getattr(contract, "input_binding", "")), allowed_source_families=tuple(str(item) for item in getattr(contract, "allowed_source_families", ()) or ()), source_compatibility=str(getattr(contract, "source_compatibility", "mixed_numeric")), output_cardinality=str(getattr(contract, "output_cardinality", "single")), output_role=str(getattr(contract, "output_role", "plotted_line")))


@dataclass(frozen=True)
class ArtifactOscillatorGuideLevelMetadata:
    kind: str
    value: float
    visible: bool = True
    label: str = ""
    description: str = ""

    def to_dict(self) -> dict[str, object]:
        return {"kind": self.kind, "value": float(self.value), "visible": bool(self.visible), "label": self.label, "description": self.description}

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "ArtifactOscillatorGuideLevelMetadata":
        return cls(str(data.get("kind", "")), float(data.get("value", 0.0)), bool(data.get("visible", True)), str(data.get("label", "")), str(data.get("description", "")))

    @classmethod
    def from_contract(cls, contract: object) -> "ArtifactOscillatorGuideLevelMetadata":
        return cls(str(getattr(contract, "kind", "")), float(getattr(contract, "value", 0.0)), bool(getattr(contract, "visible", True)), str(getattr(contract, "label", "")), str(getattr(contract, "description", "")))


@dataclass(frozen=True)
class ArtifactOscillatorVisualMetadata:
    range_mode: str = "auto"
    bounds: tuple[float, float] | None = None
    guide_levels: tuple[ArtifactOscillatorGuideLevelMetadata, ...] = ()

    def __post_init__(self) -> None:
        if self.bounds is not None:
            object.__setattr__(self, "bounds", (float(self.bounds[0]), float(self.bounds[1])))
        object.__setattr__(self, "guide_levels", tuple(self.guide_levels))

    def to_dict(self) -> dict[str, object]:
        return {"range_mode": self.range_mode, "bounds": None if self.bounds is None else [float(self.bounds[0]), float(self.bounds[1])], "guide_levels": [level.to_dict() for level in self.guide_levels]}

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "ArtifactOscillatorVisualMetadata":
        bounds_raw = data.get("bounds")
        bounds = None
        if isinstance(bounds_raw, (list, tuple)) and len(bounds_raw) == 2:
            bounds = (float(bounds_raw[0]), float(bounds_raw[1]))
        return cls(range_mode=str(data.get("range_mode", "auto")), bounds=bounds, guide_levels=tuple(ArtifactOscillatorGuideLevelMetadata.from_dict(dict(item)) for item in data.get("guide_levels", ()) or ()))  # type: ignore[arg-type]

    @classmethod
    def from_contract(cls, contract: object | None) -> "ArtifactOscillatorVisualMetadata | None":
        if contract is None:
            return None
        return cls(range_mode=str(getattr(contract, "range_mode", "auto")), bounds=getattr(contract, "bounds", None), guide_levels=tuple(ArtifactOscillatorGuideLevelMetadata.from_contract(level) for level in getattr(contract, "guide_levels", ()) or ()))


@dataclass(frozen=True)
class ArtifactToolMetadata:
    family: ArtifactToolFamily
    tool_key: str
    tool_title: str
    description: str = ""
    instance_key: str = ""
    tool_identity_status: ArtifactToolIdentityStatus = "explicit"
    params: dict[str, JsonValue] = field(default_factory=dict)
    params_status: ArtifactMetadataStatus = "unknown"
    param_contracts: tuple[ArtifactParamContractMetadata, ...] = ()
    bindings: dict[str, JsonValue] = field(default_factory=dict)
    bindings_status: ArtifactMetadataStatus = "unknown"
    data_inputs: tuple[dict[str, JsonValue], ...] = ()
    output: ArtifactOutputMetadata | dict[str, JsonValue] | None = None
    output_signals: tuple[ArtifactColumnMetadata, ...] = ()
    behavior: ArtifactBehaviorMetadata | dict[str, JsonValue] | None = None
    construct_io: ArtifactConstructIOMetadata | dict[str, JsonValue] | None = None
    oscillator_visual: ArtifactOscillatorVisualMetadata | dict[str, JsonValue] | None = None
    contract_version: str = ""
    form_variant: str = ""
    metadata: tuple[ArtifactMetadataEntry, ...] = ()

    def __post_init__(self) -> None:
        if self.family not in {"indicator", "oscillator", "construct"}:
            raise ValueError(f"Unsupported artifact tool family: {self.family!r}")
        _require_json_serializable(self.params, field_name="tool.params")
        _require_json_serializable(self.bindings, field_name="tool.bindings")
        object.__setattr__(self, "params", dict(self.params))
        object.__setattr__(self, "bindings", dict(self.bindings))
        object.__setattr__(self, "param_contracts", tuple(self.param_contracts))
        object.__setattr__(self, "output_signals", tuple(self.output_signals))
        object.__setattr__(self, "metadata", _metadata_tuple(self.metadata))
        object.__setattr__(self, "data_inputs", tuple(dict(item) for item in self.data_inputs))

    @classmethod
    def from_tool_contract(
        cls,
        *,
        contract: object,
        instance_key: str,
        params: dict[str, JsonValue] | None = None,
        params_status: ArtifactMetadataStatus = "explicit",
        bindings: dict[str, JsonValue] | None = None,
        bindings_status: ArtifactMetadataStatus = "explicit",
    ) -> "ArtifactToolMetadata":
        return cls.from_contract(
            contract,
            instance_key=instance_key,
            params=params,
            params_status=params_status,
            bindings=bindings,
            bindings_status=bindings_status,
        )

    @classmethod
    def from_contract(
        cls,
        contract: object,
        *,
        instance_key: str,
        params: dict[str, JsonValue] | None = None,
        params_status: ArtifactMetadataStatus = "explicit",
        bindings: dict[str, JsonValue] | None = None,
        bindings_status: ArtifactMetadataStatus = "explicit",
    ) -> "ArtifactToolMetadata":
        param_values = dict(params or {})
        return cls(
            family=str(getattr(contract, "family", "indicator")),  # type: ignore[arg-type]
            tool_key=str(getattr(contract, "key", "")),
            tool_title=str(getattr(contract, "title", "")),
            description=str(getattr(contract, "description", "")),
            instance_key=instance_key,
            tool_identity_status="explicit",
            params=param_values,
            params_status=params_status,
            param_contracts=tuple(
                ArtifactParamContractMetadata.from_contract(param, value=param_values.get(str(getattr(param, "name", ""))))
                for param in getattr(contract, "params", ()) or ()
            ),
            bindings=dict(bindings or {}),
            bindings_status=bindings_status,
            data_inputs=tuple(ArtifactDataInputMetadata.from_contract(item).to_dict() for item in getattr(contract, "data_inputs", ()) or ()),
            output=ArtifactOutputMetadata.from_contract(getattr(contract, "output", None)),
            behavior=ArtifactBehaviorMetadata.from_contract(getattr(contract, "behavior", None)),
            construct_io=ArtifactConstructIOMetadata.from_contract(getattr(contract, "construct_io", None)),
            oscillator_visual=ArtifactOscillatorVisualMetadata.from_contract(getattr(contract, "oscillator_visual", None)),
            contract_version=str(getattr(contract, "contract_version", "")),
            form_variant=str(getattr(contract, "form_variant", "")),
            metadata=(),
        )

    def _object_or_dict_to_dict(self, value: object) -> object:
        if value is None:
            return None
        if hasattr(value, "to_dict"):
            return value.to_dict()  # type: ignore[no-any-return]
        if isinstance(value, dict):
            return dict(value)
        raise TypeError(f"Unsupported tool metadata value: {type(value).__name__}")

    def to_dict(self) -> dict[str, object]:
        return {
            "family": self.family,
            "tool_key": self.tool_key,
            "tool_title": self.tool_title,
            "description": self.description,
            "instance_key": self.instance_key,
            "tool_identity_status": self.tool_identity_status,
            "params": dict(self.params),
            "params_status": self.params_status,
            "param_contracts": [param.to_dict() for param in self.param_contracts],
            "bindings": dict(self.bindings),
            "bindings_status": self.bindings_status,
            "data_inputs": [dict(item) for item in self.data_inputs],
            "output": self._object_or_dict_to_dict(self.output),
            "output_signals": [signal.to_dict() for signal in self.output_signals],
            "behavior": self._object_or_dict_to_dict(self.behavior),
            "construct_io": self._object_or_dict_to_dict(self.construct_io),
            "oscillator_visual": self._object_or_dict_to_dict(self.oscillator_visual),
            "contract_version": self.contract_version,
            "form_variant": self.form_variant,
            "metadata": [entry.to_dict() for entry in self.metadata],
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "ArtifactToolMetadata":
        return cls(
            family=str(data.get("family", "indicator")),  # type: ignore[arg-type]
            tool_key=str(data.get("tool_key", "")),
            tool_title=str(data.get("tool_title", "")),
            description=str(data.get("description", "")),
            instance_key=str(data.get("instance_key", "")),
            tool_identity_status=str(data.get("tool_identity_status", "explicit")),  # type: ignore[arg-type]
            params=_dict_or_empty(data.get("params")),
            params_status=str(data.get("params_status", "unknown")),  # type: ignore[arg-type]
            param_contracts=tuple(ArtifactParamContractMetadata.from_dict(dict(item)) for item in data.get("param_contracts", ()) or ()),  # type: ignore[arg-type]
            bindings=_dict_or_empty(data.get("bindings")),
            bindings_status=str(data.get("bindings_status", "unknown")),  # type: ignore[arg-type]
            data_inputs=tuple(dict(item) for item in data.get("data_inputs", ()) or ()),  # type: ignore[arg-type]
            output=None if data.get("output") is None else ArtifactOutputMetadata.from_dict(dict(data.get("output", {}))),  # type: ignore[arg-type]
            output_signals=tuple(ArtifactColumnMetadata.from_dict(dict(item)) for item in data.get("output_signals", ()) or ()),  # type: ignore[arg-type]
            behavior=None if data.get("behavior") is None else ArtifactBehaviorMetadata.from_dict(dict(data.get("behavior", {}))),  # type: ignore[arg-type]
            construct_io=None if data.get("construct_io") is None else ArtifactConstructIOMetadata.from_dict(dict(data.get("construct_io", {}))),  # type: ignore[arg-type]
            oscillator_visual=None if data.get("oscillator_visual") is None else ArtifactOscillatorVisualMetadata.from_dict(dict(data.get("oscillator_visual", {}))),  # type: ignore[arg-type]
            contract_version=str(data.get("contract_version", "")),
            form_variant=str(data.get("form_variant", "")),
            metadata=tuple(ArtifactMetadataEntry.from_dict(dict(item)) for item in data.get("metadata", ()) or ()),  # type: ignore[arg-type]
        )


@dataclass(frozen=True)
class ArtifactLineage:
    created_at_ms: int | None = None
    created_at_utc: str = ""
    created_at_rome: str = ""
    updated_at_ms: int | None = None
    updated_at_utc: str = ""
    updated_at_rome: str = ""
    created_by: str = "leonardo"
    source_artifacts: tuple[JsonValue, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "created_at_utc", self.created_at_utc or format_ts_ms_utc(self.created_at_ms))
        object.__setattr__(self, "created_at_rome", self.created_at_rome or format_ts_ms_rome(self.created_at_ms))
        object.__setattr__(self, "updated_at_utc", self.updated_at_utc or format_ts_ms_utc(self.updated_at_ms))
        object.__setattr__(self, "updated_at_rome", self.updated_at_rome or format_ts_ms_rome(self.updated_at_ms))
        _require_json_serializable(list(self.source_artifacts), field_name="lineage.source_artifacts")

    @classmethod
    def from_timestamps(cls, *, created_at_ms: int | None, updated_at_ms: int | None = None, created_by: str = "leonardo", source_artifacts: tuple[JsonValue, ...] = ()) -> "ArtifactLineage":
        return cls(created_at_ms=created_at_ms, updated_at_ms=created_at_ms if updated_at_ms is None else updated_at_ms, created_by=created_by, source_artifacts=source_artifacts)

    def to_dict(self) -> dict[str, object]:
        return {"created_at_ms": self.created_at_ms, "created_at_utc": self.created_at_utc, "created_at_rome": self.created_at_rome, "updated_at_ms": self.updated_at_ms, "updated_at_utc": self.updated_at_utc, "updated_at_rome": self.updated_at_rome, "created_by": self.created_by, "source_artifacts": list(self.source_artifacts)}

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "ArtifactLineage":
        return cls(created_at_ms=None if data.get("created_at_ms") is None else int(data.get("created_at_ms")), created_at_utc=str(data.get("created_at_utc", "")), created_at_rome=str(data.get("created_at_rome", "")), updated_at_ms=None if data.get("updated_at_ms") is None else int(data.get("updated_at_ms")), updated_at_utc=str(data.get("updated_at_utc", "")), updated_at_rome=str(data.get("updated_at_rome", "")), created_by=str(data.get("created_by", "leonardo")), source_artifacts=tuple(data.get("source_artifacts", ()) or ()))  # type: ignore[arg-type]


@dataclass(frozen=True)
class ArtifactFingerprint:
    size_bytes: int | None = None
    modified_at_ms: int | None = None
    modified_at_utc: str = ""
    modified_at_rome: str = ""
    sha256: str | None = None
    sha256_status: ArtifactSha256Status = "not_computed"

    def __post_init__(self) -> None:
        object.__setattr__(self, "modified_at_utc", self.modified_at_utc or format_ts_ms_utc(self.modified_at_ms))
        object.__setattr__(self, "modified_at_rome", self.modified_at_rome or format_ts_ms_rome(self.modified_at_ms))

    @classmethod
    def from_file_stat(cls, *, size_bytes: int | None, modified_at_ms: int | None, sha256: str | None = None, sha256_status: ArtifactSha256Status | None = None) -> "ArtifactFingerprint":
        return cls(size_bytes=size_bytes, modified_at_ms=modified_at_ms, sha256=sha256, sha256_status=sha256_status or ("computed" if sha256 else "not_computed"))

    def to_dict(self) -> dict[str, object]:
        return {"size_bytes": self.size_bytes, "modified_at_ms": self.modified_at_ms, "modified_at_utc": self.modified_at_utc, "modified_at_rome": self.modified_at_rome, "sha256": self.sha256, "sha256_status": self.sha256_status}

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "ArtifactFingerprint":
        return cls(size_bytes=None if data.get("size_bytes") is None else int(data.get("size_bytes")), modified_at_ms=None if data.get("modified_at_ms") is None else int(data.get("modified_at_ms")), modified_at_utc=str(data.get("modified_at_utc", "")), modified_at_rome=str(data.get("modified_at_rome", "")), sha256=None if data.get("sha256") is None else str(data.get("sha256")), sha256_status=str(data.get("sha256_status", "not_computed")))  # type: ignore[arg-type]


@dataclass(frozen=True)
class ArtifactQuality:
    timeline_status: ArtifactTimelineStatus = "unverified"
    monotonic_ts_ms: bool | None = None
    duplicate_ts_ms: bool | None = None
    alignment_key: Literal["ts_ms"] = "ts_ms"
    validation_status: ArtifactValidationStatus = "not_validated"
    validation_notes: tuple[str, ...] = ()
    metadata: tuple[ArtifactMetadataEntry, ...] = ()

    def __post_init__(self) -> None:
        if self.alignment_key != "ts_ms":
            raise ValueError("Artifact alignment_key must be ts_ms")
        object.__setattr__(self, "validation_notes", tuple(str(note) for note in self.validation_notes))
        object.__setattr__(self, "metadata", _metadata_tuple(self.metadata))

    def to_dict(self) -> dict[str, object]:
        return {"timeline_status": self.timeline_status, "monotonic_ts_ms": self.monotonic_ts_ms, "duplicate_ts_ms": self.duplicate_ts_ms, "alignment_key": self.alignment_key, "validation_status": self.validation_status, "validation_notes": list(self.validation_notes), "metadata": [entry.to_dict() for entry in self.metadata]}

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "ArtifactQuality":
        return cls(timeline_status=str(data.get("timeline_status", "unverified")), monotonic_ts_ms=None if data.get("monotonic_ts_ms") is None else bool(data.get("monotonic_ts_ms")), duplicate_ts_ms=None if data.get("duplicate_ts_ms") is None else bool(data.get("duplicate_ts_ms")), alignment_key="ts_ms", validation_status=str(data.get("validation_status", "not_validated")), validation_notes=tuple(str(note) for note in data.get("validation_notes", ()) or ()), metadata=tuple(ArtifactMetadataEntry.from_dict(dict(item)) for item in data.get("metadata", ()) or ()))  # type: ignore[arg-type]


@dataclass(frozen=True)
class ArtifactValidationMetadata:
    status: ArtifactValidationResultStatus = "unknown"
    validated_at_ms: int | None = None
    validated_at: str = ""
    validated_at_rome: str = ""
    validator: str = ""
    row_count: int | None = None
    issue_count: int = 0
    warning_count: int = 0
    error_count: int = 0
    csv_fingerprint: ArtifactFingerprint = field(default_factory=ArtifactFingerprint)
    message: str = ""

    def __post_init__(self) -> None:
        if self.status not in {"unknown", "ok", "modified", "warning", "error"}:
            raise ValueError(f"Unsupported validation status: {self.status!r}")
        object.__setattr__(self, "validated_at", self.validated_at or format_ts_ms_utc(self.validated_at_ms))
        object.__setattr__(self, "validated_at_rome", self.validated_at_rome or format_ts_ms_rome(self.validated_at_ms))

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "validated_at_ms": self.validated_at_ms,
            "validated_at": self.validated_at,
            "validated_at_rome": self.validated_at_rome,
            "validator": self.validator,
            "row_count": self.row_count,
            "issue_count": int(self.issue_count),
            "warning_count": int(self.warning_count),
            "error_count": int(self.error_count),
            "csv_fingerprint": self.csv_fingerprint.to_dict(),
            "message": self.message,
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "ArtifactValidationMetadata":
        fingerprint_raw = data.get("csv_fingerprint", {}) or {}
        return cls(
            status=str(data.get("status", "unknown")),  # type: ignore[arg-type]
            validated_at_ms=None if data.get("validated_at_ms") is None else int(data.get("validated_at_ms")),
            validated_at=str(data.get("validated_at", "")),
            validated_at_rome=str(data.get("validated_at_rome", "")),
            validator=str(data.get("validator", "")),
            row_count=None if data.get("row_count") is None else int(data.get("row_count")),
            issue_count=int(data.get("issue_count", 0)),
            warning_count=int(data.get("warning_count", 0)),
            error_count=int(data.get("error_count", 0)),
            csv_fingerprint=ArtifactFingerprint.from_dict(dict(fingerprint_raw)),
            message=str(data.get("message", "")),
        )


@dataclass(frozen=True)
class HistoricalCsvArtifactManifest:
    schema_version: int
    artifact_type: Literal["historical_csv_artifact"]
    identity: ArtifactIdentity
    market: MarketId
    files: ArtifactFiles
    time_range: ArtifactTimeRange
    shape: ArtifactShape
    columns: tuple[ArtifactColumnMetadata, ...]
    tool: ArtifactToolMetadata | None = None
    lineage: ArtifactLineage = field(default_factory=ArtifactLineage)
    fingerprint: ArtifactFingerprint = field(default_factory=ArtifactFingerprint)
    quality: ArtifactQuality = field(default_factory=ArtifactQuality)
    validation: ArtifactValidationMetadata = field(default_factory=ArtifactValidationMetadata)
    metadata: tuple[ArtifactMetadataEntry, ...] = ()

    def __post_init__(self) -> None:
        if self.schema_version != ARTIFACT_METADATA_SCHEMA_VERSION:
            raise ValueError(f"Unsupported artifact metadata schema_version: {self.schema_version}")
        if self.artifact_type != HISTORICAL_CSV_ARTIFACT_TYPE:
            raise ValueError(f"Unsupported artifact_type: {self.artifact_type!r}")
        expected_uid = build_artifact_uid(market=self.market, artifact_family=self.identity.artifact_family, artifact_id=self.identity.artifact_id)
        if self.identity.artifact_uid != expected_uid:
            raise ValueError(f"identity.artifact_uid mismatch: expected {expected_uid!r}")
        object.__setattr__(self, "columns", tuple(self.columns))
        object.__setattr__(self, "metadata", _metadata_tuple(self.metadata))
        column_names = tuple(column.name for column in self.columns)
        if any(name not in self.shape.columns for name in column_names):
            raise ValueError("manifest column metadata must be a subset of shape.columns")
        if self.identity.artifact_family in {"indicator", "oscillator", "construct"} and self.tool is None:
            raise ValueError("tool metadata is required for indicator, oscillator, and construct artifacts")
        if self.identity.artifact_family == "ohlcv" and self.tool is not None:
            raise ValueError("OHLCV artifacts must not carry tool metadata")
        if self.identity.artifact_family == "analysis_database":
            raise ValueError("Analysis databases use manifest.json, not HistoricalCsvArtifactManifest")

    def to_dict(self) -> dict[str, object]:
        return {"schema_version": self.schema_version, "artifact_type": self.artifact_type, "identity": self.identity.to_dict(), "market": market_to_dict(self.market), "files": self.files.to_dict(), "time_range": self.time_range.to_dict(), "shape": self.shape.to_dict(), "columns": [column.to_dict() for column in self.columns], "tool": None if self.tool is None else self.tool.to_dict(), "lineage": self.lineage.to_dict(), "fingerprint": self.fingerprint.to_dict(), "quality": self.quality.to_dict(), "validation": self.validation.to_dict(), "metadata": [entry.to_dict() for entry in self.metadata]}

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "HistoricalCsvArtifactManifest":
        tool_raw = data.get("tool")
        return cls(schema_version=int(data.get("schema_version", 0)), artifact_type=str(data.get("artifact_type", "")), identity=ArtifactIdentity.from_dict(dict(data.get("identity", {}) or {})), market=market_from_dict(dict(data.get("market", {}) or {})), files=ArtifactFiles.from_dict(dict(data.get("files", {}) or {})), time_range=ArtifactTimeRange.from_dict(dict(data.get("time_range", {}) or {})), shape=ArtifactShape.from_dict(dict(data.get("shape", {}) or {})), columns=tuple(ArtifactColumnMetadata.from_dict(dict(item)) for item in data.get("columns", ()) or ()), tool=None if tool_raw is None else ArtifactToolMetadata.from_dict(dict(tool_raw)), lineage=ArtifactLineage.from_dict(dict(data.get("lineage", {}) or {})), fingerprint=ArtifactFingerprint.from_dict(dict(data.get("fingerprint", {}) or {})), quality=ArtifactQuality.from_dict(dict(data.get("quality", {}) or {})), validation=ArtifactValidationMetadata.from_dict(dict(data.get("validation", {}) or {})), metadata=tuple(ArtifactMetadataEntry.from_dict(dict(item)) for item in data.get("metadata", ()) or ()))  # type: ignore[arg-type]


@dataclass(frozen=True)
class HistoricalArtifactSummary:
    unique_id: str
    artifact_family: ArtifactFamily
    storage_family: ArtifactStorageFamily
    artifact_id: str
    artifact_uid: str
    market: MarketId
    csv_relpath: str
    metadata_relpath: str
    first_ts_ms: int | None
    last_ts_ms: int | None
    first_ts_rome: str
    last_ts_rome: str
    row_count: int | None
    column_count: int
    columns: tuple[str, ...]
    tool_key: str | None
    tool_title: str | None
    instance_key: str | None
    timeline_status: ArtifactTimelineStatus
    metadata_path: Path | None = None

    @classmethod
    def from_manifest(cls, manifest: HistoricalCsvArtifactManifest, *, metadata_path: Path | None = None) -> "HistoricalArtifactSummary":
        return cls(unique_id=manifest.identity.unique_id, artifact_family=manifest.identity.artifact_family, storage_family=manifest.identity.storage_family, artifact_id=manifest.identity.artifact_id, artifact_uid=manifest.identity.artifact_uid, market=manifest.market, csv_relpath=manifest.files.csv_relpath, metadata_relpath=manifest.files.metadata_relpath, first_ts_ms=manifest.time_range.first_ts_ms, last_ts_ms=manifest.time_range.last_ts_ms, first_ts_rome=manifest.time_range.first_ts_rome, last_ts_rome=manifest.time_range.last_ts_rome, row_count=manifest.shape.row_count, column_count=manifest.shape.column_count, columns=manifest.shape.columns, tool_key=None if manifest.tool is None else manifest.tool.tool_key, tool_title=None if manifest.tool is None else manifest.tool.tool_title, instance_key=None if manifest.tool is None else manifest.tool.instance_key, timeline_status=manifest.quality.timeline_status, metadata_path=metadata_path)


def metadata_files_from_csv(*, csv_path: Path, partition_dir: Path) -> ArtifactFiles:
    csv = Path(csv_path)
    metadata = metadata_path_for_csv(csv)
    try:
        csv_relpath = csv.resolve().relative_to(Path(partition_dir).resolve()).as_posix()
    except Exception:
        csv_relpath = csv.name
    try:
        metadata_relpath = metadata.resolve().relative_to(Path(partition_dir).resolve()).as_posix()
    except Exception:
        metadata_relpath = metadata.name
    return ArtifactFiles(csv_filename=csv.name, csv_relpath=csv_relpath, metadata_filename=metadata.name, metadata_relpath=metadata_relpath)




def _artifact_column_metadata_from_output_signal(cls, *, name: str, signal: object) -> "ArtifactColumnMetadata":
    signal_type = str(getattr(signal, "signal_type", "signal"))
    return cls(
        name=str(name),
        role="utility" if signal_type == "utility" else "feature",
        selectable=bool(getattr(signal, "analysis_usable", True)),
        analysis_usable=bool(getattr(signal, "analysis_usable", True)),
        renderable=bool(getattr(signal, "renderable", True)),
        label=str(getattr(signal, "label", "")),
        description=str(getattr(signal, "description", "")),
        semantic_role=str(getattr(signal, "semantic_role", "primary")),
        value_type=str(getattr(signal, "value_type", "numeric")),
        signal_type=signal_type,
        default_visible=bool(getattr(signal, "default_visible", True)),
        can_drive_style_rules=bool(getattr(signal, "can_drive_style_rules", False)),
    )


ArtifactColumnMetadata.from_output_signal = classmethod(_artifact_column_metadata_from_output_signal)  # type: ignore[attr-defined]
