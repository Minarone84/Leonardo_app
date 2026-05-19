from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from leonardo.data.historical.derived_store_csv import DerivedCsvStore
from leonardo.data.naming import MarketId
from leonardo.financial_tools.ft_specs import get_construct_specs, get_indicator_specs, get_oscillator_specs


NON_SELECTABLE_COLUMNS = {"time", "timeframe", "ts_ms"}


@dataclass(frozen=True)
class SavedArtifactColumn:
    family: str
    tool_key: str
    tool_title: str
    instance_key: str
    column_name: str
    path: Path
    dtype: Optional[str] = None
    analysis_usable: Optional[bool] = None
    renderable: Optional[bool] = None
    artifact_uid: str = ""
    metadata_path: Optional[Path] = None
    source_artifact_sha256: Optional[str] = None
    params: dict[str, object] = field(default_factory=dict)
    params_status: str = "unknown"
    bindings: dict[str, object] = field(default_factory=dict)
    bindings_status: str = "unknown"


def load_saved_artifact_columns(
    *,
    historical_root: Path,
    market: MarketId,
) -> list[SavedArtifactColumn]:
    """Load analysis-usable saved artifact columns for a market partition.

    This helper is GUI-owned discovery code shared by Data Manager widgets and
    dialogs. It reads saved indicator/oscillator/construct metadata and returns
    ``SavedArtifactColumn`` transport objects. It does not create Analysis
    Database manifests, materialize dataframes, or mutate saved artifacts.
    """
    store = DerivedCsvStore(historical_root=Path(historical_root))
    specs_by_kind = {
        "indicators": get_indicator_specs(),
        "oscillators": get_oscillator_specs(),
        "constructs": get_construct_specs(),
    }

    columns: list[SavedArtifactColumn] = []
    seen: set[tuple[str, str]] = set()

    for kind in ("indicators", "oscillators", "constructs"):
        refs = []
        try:
            refs = store.list_instances(market=market, kind=kind)  # type: ignore[arg-type]
        except Exception:
            refs = []

        spec_map = specs_by_kind[kind]
        for ref in refs:
            manifest = store.load_metadata_manifest(Path(ref.path))
            tool_key = str(getattr(getattr(manifest, "tool", None), "tool_key", ref.tool_key) or ref.tool_key)
            instance_key = str(
                getattr(getattr(manifest, "tool", None), "instance_key", ref.instance_key) or ref.instance_key
            )
            tool_title = str(getattr(getattr(manifest, "tool", None), "tool_title", "") or "")
            if not tool_title:
                tool_title = spec_map.get(tool_key).title if tool_key in spec_map else tool_key

            for column in _read_artifact_columns(path=Path(ref.path), manifest=manifest):
                dedupe_key = (str(ref.path), column.column_name)
                if dedupe_key in seen:
                    continue
                seen.add(dedupe_key)
                columns.append(
                    SavedArtifactColumn(
                        family=kind,
                        tool_key=tool_key,
                        tool_title=tool_title,
                        instance_key=instance_key,
                        column_name=column.column_name,
                        path=Path(ref.path),
                        dtype=column.dtype,
                        analysis_usable=column.analysis_usable,
                        renderable=column.renderable,
                        artifact_uid=column.artifact_uid,
                        metadata_path=column.metadata_path,
                        source_artifact_sha256=column.source_artifact_sha256,
                        params=column.params,
                        params_status=column.params_status,
                        bindings=column.bindings,
                        bindings_status=column.bindings_status,
                    )
                )

    columns.sort(key=lambda c: (c.family, c.tool_title.lower(), c.instance_key.lower(), c.column_name.lower()))
    return columns


def _read_artifact_columns(*, path: Path, manifest: object | None) -> list[SavedArtifactColumn]:
    metadata_columns = _read_artifact_columns_from_metadata(path=path, manifest=manifest)
    if metadata_columns:
        return metadata_columns
    return _read_artifact_columns_from_csv_header(path)


def _read_artifact_columns_from_metadata(*, path: Path, manifest: object | None) -> list[SavedArtifactColumn]:
    tool = getattr(manifest, "tool", None)
    if manifest is None or tool is None:
        return []

    family = str(getattr(getattr(manifest, "identity", None), "storage_family", "") or "")
    tool_key = str(getattr(tool, "tool_key", "") or "")
    tool_title = str(getattr(tool, "tool_title", "") or tool_key)
    instance_key = str(getattr(tool, "instance_key", "") or Path(path).stem)
    artifact_uid = str(getattr(getattr(manifest, "identity", None), "artifact_uid", "") or "")
    metadata_path = getattr(manifest, "metadata_path", None)
    if metadata_path is None:
        metadata_filename = str(getattr(getattr(manifest, "files", None), "metadata_filename", "") or "")
        metadata_path = path.with_name(metadata_filename) if metadata_filename else None
    fingerprint = getattr(manifest, "fingerprint", None)

    columns: list[SavedArtifactColumn] = []
    for column in getattr(manifest, "columns", ()) or ():
        column_name = str(getattr(column, "name", "") or "")
        if not column_name or column_name in NON_SELECTABLE_COLUMNS:
            continue
        if not bool(getattr(column, "selectable", True)):
            continue
        analysis_usable = getattr(column, "analysis_usable", None)
        if analysis_usable is False:
            continue
        columns.append(
            SavedArtifactColumn(
                family=family,
                tool_key=tool_key,
                tool_title=tool_title,
                instance_key=instance_key,
                column_name=column_name,
                path=path,
                dtype=getattr(column, "dtype", None),
                analysis_usable=None if analysis_usable is None else bool(analysis_usable),
                renderable=getattr(column, "renderable", None),
                artifact_uid=artifact_uid,
                metadata_path=Path(metadata_path) if metadata_path else None,
                source_artifact_sha256=getattr(fingerprint, "sha256", None),
                params=dict(getattr(tool, "params", {}) or {}),
                params_status=str(getattr(tool, "params_status", "unknown") or "unknown"),
                bindings=dict(getattr(tool, "bindings", {}) or {}),
                bindings_status=str(getattr(tool, "bindings_status", "unknown") or "unknown"),
            )
        )
    return columns


def _read_artifact_columns_from_csv_header(path: Path) -> list[SavedArtifactColumn]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            header = handle.readline().strip()
    except Exception:
        return []

    if not header:
        return []

    return [
        SavedArtifactColumn(
            family="",
            tool_key="",
            tool_title="",
            instance_key=Path(path).stem,
            column_name=col.strip(),
            path=path,
            analysis_usable=True,
        )
        for col in header.split(",")
        if col.strip() and col.strip() not in NON_SELECTABLE_COLUMNS
    ]
