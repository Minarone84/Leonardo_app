from __future__ import annotations

from pathlib import Path
from typing import Sequence

from leonardo.data.historical.analysis_database_contracts import (
    AnalysisDatabaseColumn,
    AnalysisMetadataEntry,
    AnalysisFeatureSource,
)
from leonardo.data.historical.analysis_database_naming import (
    build_database_column_name,
    build_feature_source_id,
)
from leonardo.data.naming import MarketId
from leonardo.gui.windows._data_manager.saved_artifact_columns import SavedArtifactColumn


def build_manifest_features_from_saved_columns(
    *,
    historical_root: Path,
    market: MarketId,
    selected_columns: Sequence[SavedArtifactColumn],
) -> tuple[tuple[AnalysisFeatureSource, ...], tuple[AnalysisDatabaseColumn, ...]]:
    """Build Analysis Database feature recipe objects from checked saved-artifact columns.

    This helper is GUI-owned because it consumes ``SavedArtifactColumn`` from
    the Data Manager saved-artifact selector. It creates typed Analysis
    Database contract objects for callers that intentionally create or edit a
    database recipe. It must not be imported by Database Builder's build/rebuild
    path, where rebuild means materialize the selected database from its own
    existing manifest recipe.
    """
    sources_by_id: dict[str, AnalysisFeatureSource] = {}
    feature_columns: list[AnalysisDatabaseColumn] = []

    for selected in selected_columns:
        source_id = build_feature_source_id(
            family=selected.family,
            tool_key=selected.tool_key,
            instance_key=selected.instance_key,
        )
        if source_id not in sources_by_id:
            sources_by_id[source_id] = _build_feature_source(
                historical_root=historical_root,
                market=market,
                source_id=source_id,
                selected=selected,
            )

        feature_columns.append(
            AnalysisDatabaseColumn(
                role="feature",
                selected=True,
                source_family=selected.family,  # type: ignore[arg-type]
                source_id=source_id,
                source_column_name=selected.column_name,
                db_column_name=build_database_column_name(
                    source_family=selected.family,
                    tool_key=selected.tool_key,
                    instance_key=selected.instance_key,
                    source_column_name=selected.column_name,
                ),
                dtype=selected.dtype,
                nullable=True,
                analysis_usable=True if selected.analysis_usable is None else bool(selected.analysis_usable),
                renderable=selected.renderable,
                locked=False,
            )
        )

    return tuple(sources_by_id.values()), tuple(feature_columns)


def _build_feature_source(
    *,
    historical_root: Path,
    market: MarketId,
    source_id: str,
    selected: SavedArtifactColumn,
) -> AnalysisFeatureSource:
    path = Path(selected.path)
    stat = None
    try:
        stat = path.stat()
    except OSError:
        stat = None

    return AnalysisFeatureSource(
        source_id=source_id,
        family=selected.family,  # type: ignore[arg-type]
        tool_key=selected.tool_key,
        tool_title=selected.tool_title,
        instance_key=selected.instance_key,
        source_artifact_filename=path.name,
        source_artifact_relpath=_source_relpath(historical_root=historical_root, market=market, path=path),
        source_artifact_sha256=selected.source_artifact_sha256,
        source_artifact_size_bytes=None if stat is None else int(stat.st_size),
        source_artifact_modified_at_ms=None if stat is None else int(stat.st_mtime * 1000),
        params=dict(selected.params),
        params_status=_analysis_params_status(selected.params_status),
        bindings=dict(selected.bindings),
        bindings_status=_analysis_metadata_status(selected.bindings_status),
        metadata=_source_metadata_entries(historical_root=historical_root, market=market, selected=selected),
    )


def _source_relpath(*, historical_root: Path, market: MarketId, path: Path) -> str:
    partition_dir = Path(historical_root) / market.exchange / market.market_type / market.symbol / market.timeframe
    try:
        return Path(path).resolve().relative_to(partition_dir.resolve()).as_posix()
    except Exception:
        return Path(path).name


def _analysis_params_status(value: str) -> str:
    status = str(value or "unknown")
    return status if status in {"explicit", "inferred", "unknown"} else "unknown"


def _analysis_metadata_status(value: str) -> str:
    status = str(value or "unknown")
    return status if status in {"explicit", "inferred", "unknown", "not_applicable"} else "unknown"


def _source_metadata_entries(
    *,
    historical_root: Path,
    market: MarketId,
    selected: SavedArtifactColumn,
) -> tuple[AnalysisMetadataEntry, ...]:
    entries: list[AnalysisMetadataEntry] = []
    if selected.artifact_uid:
        entries.append(
            AnalysisMetadataEntry(
                namespace="artifact",
                key="artifact_uid",
                value=selected.artifact_uid,
                value_type="string",
                label="Source artifact UID",
                searchable=True,
            )
        )
    if selected.metadata_path is not None:
        entries.append(
            AnalysisMetadataEntry(
                namespace="artifact",
                key="metadata_relpath",
                value=_source_relpath(historical_root=historical_root, market=market, path=selected.metadata_path),
                value_type="path",
                label="Source metadata sidecar relative path",
                searchable=False,
            )
        )
    return tuple(entries)
