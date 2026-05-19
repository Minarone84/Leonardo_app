from __future__ import annotations

import math
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

from leonardo.data.naming import MarketId

CSV_METADATA_SUFFIX = ".meta.json"
ARTIFACT_METADATA_SUFFIX = CSV_METADATA_SUFFIX
ROME_TIMEZONE = "Europe/Rome"
ARTIFACT_METADATA_TIMEZONE = ROME_TIMEZONE

ArtifactFamily = Literal["ohlcv", "indicator", "oscillator", "construct", "analysis_database"]
StorageFamily = Literal["ohlcv", "indicators", "oscillators", "constructs", "analysis_databases"]

_STORAGE_TO_ARTIFACT_FAMILY = {
    "ohlcv": "ohlcv",
    "indicators": "indicator",
    "oscillators": "oscillator",
    "constructs": "construct",
    "analysis_databases": "analysis_database",
}
_ARTIFACT_TO_STORAGE_FAMILY = {value: key for key, value in _STORAGE_TO_ARTIFACT_FAMILY.items()}
_SAFE_SEGMENT_RE = re.compile(r"[^a-zA-Z0-9_]+")
_UNDERSCORE_RE = re.compile(r"_+")


def new_unique_id() -> str:
    """Return a new opaque immutable id for one saved artifact object."""
    return uuid.uuid4().hex


def metadata_path_for_csv(csv_path: Path) -> Path:
    """Return adjacent metadata sidecar path: ``<stem>.csv`` -> ``<stem>.meta.json``."""
    path = Path(csv_path)
    if path.suffix.lower() != ".csv":
        raise ValueError(f"CSV artifact path must end with .csv: {csv_path!r}")
    return path.with_name(f"{path.stem}{CSV_METADATA_SUFFIX}")


def csv_path_for_metadata(metadata_path: Path) -> Path:
    """Return CSV path paired with an adjacent ``.meta.json`` sidecar."""
    path = Path(metadata_path)
    if not path.name.endswith(CSV_METADATA_SUFFIX):
        raise ValueError(f"Metadata sidecar must end with {CSV_METADATA_SUFFIX!r}: {metadata_path!r}")
    stem = path.name[: -len(CSV_METADATA_SUFFIX)]
    if not stem:
        raise ValueError(f"Metadata sidecar is missing an artifact stem: {metadata_path!r}")
    return path.with_name(f"{stem}.csv")


def metadata_filename_for_csv_filename(csv_filename: str) -> str:
    return metadata_path_for_csv(Path(str(csv_filename))).name


def csv_filename_for_metadata_filename(metadata_filename: str) -> str:
    return csv_path_for_metadata(Path(str(metadata_filename))).name


def storage_family_for_artifact_family(artifact_family: str) -> str:
    family = str(artifact_family).strip().lower()
    try:
        return _ARTIFACT_TO_STORAGE_FAMILY[family]
    except KeyError as exc:
        raise ValueError(f"Unsupported artifact family: {artifact_family!r}") from exc


def artifact_family_for_storage_family(storage_family: str) -> str:
    storage = str(storage_family).strip().lower()
    try:
        return _STORAGE_TO_ARTIFACT_FAMILY[storage]
    except KeyError as exc:
        raise ValueError(f"Unsupported storage family: {storage_family!r}") from exc


# Alternate wording kept for callers that use "from" rather than "for".
def artifact_family_from_storage_family(storage_family: str) -> str:
    return artifact_family_for_storage_family(storage_family)


def slugify_artifact_segment(value: object, *, fallback: str = "artifact", max_length: int = 128) -> str:
    raw = str(value or "").strip().lower()
    safe = _SAFE_SEGMENT_RE.sub("_", raw)
    safe = _UNDERSCORE_RE.sub("_", safe).strip("_")
    if not safe:
        safe = fallback
    if max_length > 0 and len(safe) > max_length:
        safe = safe[:max_length].rstrip("_") or fallback
    return safe


def build_artifact_id(
    *,
    artifact_family: ArtifactFamily | str,
    tool_key: str | None = None,
    instance_key: str | None = None,
    database_id: str | None = None,
) -> str:
    """Build deterministic local artifact id inside one market/timeframe partition."""
    family = str(artifact_family).strip().lower()
    if family == "ohlcv":
        return "ohlcv__candles"
    if family == "analysis_database":
        if not database_id:
            raise ValueError("database_id is required for analysis_database artifacts")
        return f"database__{slugify_artifact_segment(database_id, fallback='database', max_length=160)}"
    if family in {"indicator", "oscillator", "construct"}:
        if not tool_key:
            raise ValueError(f"tool_key is required for {family} artifacts")
        if not instance_key:
            raise ValueError(f"instance_key is required for {family} artifacts")
        tool_slug = slugify_artifact_segment(tool_key, fallback="tool", max_length=96)
        instance_slug = slugify_artifact_segment(instance_key, fallback="instance", max_length=180)
        return f"{family}__{tool_slug}__{instance_slug}"
    raise ValueError(f"Unsupported artifact family: {artifact_family!r}")


def build_artifact_uid(*, market: MarketId, artifact_family: ArtifactFamily | str, artifact_id: str) -> str:
    """Build globally scoped deterministic artifact uid."""
    family = str(artifact_family).strip().lower()
    if family not in _ARTIFACT_TO_STORAGE_FAMILY:
        raise ValueError(f"Unsupported artifact family: {artifact_family!r}")
    local_id = str(artifact_id).strip()
    if not local_id:
        raise ValueError("artifact_id is required")
    return ":".join((family, market.exchange, market.market_type, market.symbol, market.timeframe, local_id))


def format_ts_ms_utc(ts_ms: object) -> str:
    return _format_ts_ms(ts_ms, tz=timezone.utc, suffix="UTC")


def format_ts_ms_rome(ts_ms: object) -> str:
    return _format_ts_ms(ts_ms, tz=ZoneInfo(ROME_TIMEZONE), suffix=ROME_TIMEZONE)


def _format_ts_ms(ts_ms: object, *, tz: timezone | ZoneInfo, suffix: str) -> str:
    try:
        if ts_ms is None:
            return "(n/a)"
        if isinstance(ts_ms, float) and not math.isfinite(ts_ms):
            return "(n/a)"
        value = int(ts_ms)
    except Exception:
        return "(n/a)"
    try:
        dt = datetime.fromtimestamp(value / 1000.0, tz=tz)
    except Exception:
        return "(n/a)"
    return f"{dt:%Y-%m-%d %H:%M:%S} {suffix}"
