from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Iterable

from leonardo.data.naming import MarketId

from .analysis_database_contracts import (
    AnalysisDatabaseAlignment,
    AnalysisDatabaseColumn,
    AnalysisFeatureSource,
    AnalysisMetadataEntry,
    ANALYSIS_DATABASE_SCHEMA_VERSION,
    market_to_dict,
)

_DATABASE_ID_PREFIX = "adb"
_SAFE_SEGMENT_RE = re.compile(r"[^a-zA-Z0-9_]+")
_UNDERSCORE_RE = re.compile(r"_+")


def slugify_database_name(display_name: str, *, fallback: str = "analysis_database", max_length: int = 72) -> str:
    """Return a lowercase filesystem-safe slug for a user-facing database name."""
    return _slugify_segment(display_name, fallback=fallback, max_length=max_length)


def slugify_column_segment(value: str, *, fallback: str = "column", max_length: int = 96) -> str:
    """Return a dataframe-column-safe segment.

    The final database column naming helper uses this for every derived
    component so artifact instance names cannot leak spaces, separators, or
    platform-sensitive characters into dataframe columns.
    """
    return _slugify_segment(value, fallback=fallback, max_length=max_length)


def build_recipe_hash(recipe_payload: dict[str, Any]) -> str:
    """Build a stable SHA-256 hash from a normalized recipe payload."""
    normalized = _normalize_for_hash(recipe_payload)
    encoded = json.dumps(normalized, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_recipe_hash_short(recipe_hash: str) -> str:
    raw = str(recipe_hash).strip().lower()
    if len(raw) < 8:
        raise ValueError("recipe_hash must contain at least 8 hexadecimal characters")
    return f"h{raw[:8]}"


def build_analysis_database_id(display_name: str, recipe_hash: str) -> str:
    """Build immutable database id: adb__{name_slug}__h{hash8}."""
    return f"{_DATABASE_ID_PREFIX}__{slugify_database_name(display_name)}__{build_recipe_hash_short(recipe_hash)}"


def build_feature_source_id(*, family: str, tool_key: str, instance_key: str) -> str:
    family_slug = _slugify_segment(family, fallback="source")
    tool_slug = _slugify_segment(tool_key, fallback="tool")
    instance_slug = _slugify_segment(instance_key, fallback="instance", max_length=128)
    return f"{family_slug}:{tool_slug}:{instance_slug}"


def build_database_column_name(
    *,
    source_family: str,
    tool_key: str | None,
    instance_key: str | None,
    source_column_name: str,
) -> str:
    """Build a stable database column name for a selected source column."""
    if source_family == "ohlcv":
        column = str(source_column_name).strip()
        if column not in {"ts_ms", "open", "high", "low", "close", "volume"}:
            raise ValueError(f"Unsupported OHLCV analysis database column: {source_column_name!r}")
        return column

    family_prefix = _singular_family(source_family)
    tool_slug = _slugify_segment(tool_key or "tool", fallback="tool")
    instance_slug = _slugify_segment(instance_key or "instance", fallback="instance", max_length=128)
    column_slug = _slugify_segment(source_column_name, fallback="column", max_length=96)
    return f"{family_prefix}__{tool_slug}__{instance_slug}__{column_slug}"


def build_analysis_database_recipe_payload(
    *,
    market: MarketId,
    alignment: AnalysisDatabaseAlignment,
    base_columns: Iterable[AnalysisDatabaseColumn],
    feature_sources: Iterable[AnalysisFeatureSource],
    feature_columns: Iterable[AnalysisDatabaseColumn],
    metadata: Iterable[AnalysisMetadataEntry] = (),
    description_metadata: Iterable[AnalysisMetadataEntry] = (),
) -> dict[str, Any]:
    """Build the identity recipe payload used for database hashing.

    User descriptions, display names, timestamps, local absolute paths, and
    non-identity metadata are intentionally excluded. Only metadata entries
    explicitly marked ``identity_affecting=True`` are included.
    """
    sources_payload = []
    for source in feature_sources:
        sources_payload.append(
            {
                "source_id": source.source_id,
                "family": source.family,
                "tool_key": source.tool_key,
                "instance_key": source.instance_key,
                "source_artifact_filename": source.source_artifact_filename,
                "params": _normalize_for_hash(source.params),
                "params_status": source.params_status,
                "bindings": _normalize_for_hash(source.bindings),
                "bindings_status": source.bindings_status,
                "metadata": _identity_metadata_payload(source.metadata),
            }
        )

    return {
        "schema_version": ANALYSIS_DATABASE_SCHEMA_VERSION,
        "artifact_type": "analysis_database",
        "market": market_to_dict(market),
        "alignment": alignment.to_dict(),
        "base_columns": [_column_recipe_payload(column) for column in base_columns],
        "feature_sources": sources_payload,
        "feature_columns": [_column_recipe_payload(column) for column in feature_columns],
        "metadata": _identity_metadata_payload(metadata),
        "description_metadata": _identity_metadata_payload(description_metadata),
    }


def _column_recipe_payload(column: AnalysisDatabaseColumn) -> dict[str, Any]:
    return {
        "role": column.role,
        "selected": bool(column.selected),
        "source_family": column.source_family,
        "source_id": column.source_id,
        "source_column_name": column.source_column_name,
        "db_column_name": column.db_column_name,
        "analysis_usable": column.analysis_usable,
        "renderable": column.renderable,
        "locked": bool(column.locked),
        "metadata": _identity_metadata_payload(column.metadata),
    }


def _identity_metadata_payload(metadata: Iterable[AnalysisMetadataEntry]) -> list[dict[str, Any]]:
    return [
        {
            "namespace": entry.namespace,
            "key": entry.key,
            "value": _normalize_for_hash(entry.value),
            "value_type": entry.value_type,
        }
        for entry in metadata
        if entry.identity_affecting
    ]


def _normalize_for_hash(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _normalize_for_hash(value[k]) for k in sorted(value.keys(), key=str)}
    if isinstance(value, (list, tuple)):
        return [_normalize_for_hash(v) for v in value]
    if isinstance(value, Path):
        return value.as_posix()
    return value


def _singular_family(source_family: str) -> str:
    if source_family == "indicators":
        return "indicator"
    if source_family == "oscillators":
        return "oscillator"
    if source_family == "constructs":
        return "construct"
    raise ValueError(f"Unsupported analysis database feature family: {source_family!r}")


def _slugify_segment(value: str, *, fallback: str, max_length: int = 96) -> str:
    raw = str(value or "").strip().lower()
    safe = _SAFE_SEGMENT_RE.sub("_", raw)
    safe = _UNDERSCORE_RE.sub("_", safe).strip("_")
    if not safe:
        safe = fallback
    if max_length > 0 and len(safe) > max_length:
        safe = safe[:max_length].rstrip("_") or fallback
    return safe
