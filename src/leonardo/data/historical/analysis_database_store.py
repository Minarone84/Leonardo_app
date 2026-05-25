from __future__ import annotations

from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import shutil
from tempfile import NamedTemporaryFile
import time
from typing import Iterable

import pandas as pd

from leonardo.data.historical.dataset_service import require_ohlcv_dataset_loadable
from leonardo.data.historical.paths import HistoricalPaths
from leonardo.data.historical.source_ohlcv_provenance import (
    SOURCE_OHLCV_PROVENANCE_KEY,
    SOURCE_OHLCV_PROVENANCE_NAMESPACE,
    SourceOhlcvDriftReport,
    build_source_ohlcv_drift_report,
    build_source_ohlcv_provenance_snapshot,
    extract_source_ohlcv_snapshot,
)
from leonardo.data.naming import MarketId, canonicalize

from .analysis_database_contracts import (
    ANALYSIS_DATABASE_ARTIFACT_TYPE,
    ANALYSIS_DATABASE_DATAFRAME_FILENAME,
    ANALYSIS_DATABASE_DATASET_TYPE,
    ANALYSIS_DATABASE_MANIFEST_FILENAME,
    ANALYSIS_DATABASE_SCHEMA_VERSION,
    BASE_OHLC_COLUMNS,
    AnalysisDatabaseAlignment,
    AnalysisDatabaseColumn,
    AnalysisDatabaseDescription,
    AnalysisDatabaseManifest,
    AnalysisDatabaseMaterialization,
    AnalysisDatabaseSummary,
    AnalysisFeatureSource,
    AnalysisMetadataEntry,
)
from .analysis_database_naming import (
    build_analysis_database_id,
    build_analysis_database_recipe_payload,
    build_database_column_name,
    build_recipe_hash,
    build_recipe_hash_short,
)


class AnalysisDatabaseStore:
    """Store for Analysis Database manifests and materialized dataframes.

    The store owns manifest persistence, database pathing, and timestamp-safe
    materialization of OHLCV plus selected derived artifact columns. GUI code
    should collect user choices only; it should not improvise merge or
    persistence semantics.
    """

    def __init__(self, *, historical_root: Path) -> None:
        self._historical_root = Path(historical_root)
        self._paths = HistoricalPaths(root=self._historical_root)

    # ------------------------------------------------------------------
    # Display-name policy
    # ------------------------------------------------------------------

    def default_display_name_prefix(self, *, market: MarketId) -> str:
        return f"{market.symbol}_{market.timeframe}_"

    def validate_database_display_name(self, display_name: str) -> str:
        name = str(display_name or "").strip()
        if not name:
            raise ValueError("Analysis database name is required.")
        if any(char.isspace() for char in name):
            raise ValueError("Analysis database name cannot contain spaces or other whitespace.")
        if "/" in name or "\\" in name or name in {".", ".."}:
            raise ValueError("Analysis database name cannot contain path separators.")
        return name

    def display_name_exists(
        self,
        *,
        market: MarketId,
        display_name: str,
        exclude_database_id: str | None = None,
    ) -> bool:
        candidate = self._display_name_key(display_name)
        excluded = None if exclude_database_id is None else self._safe_database_id(exclude_database_id)
        for summary in self.list_databases(market=market):
            if excluded is not None and summary.database_id == excluded:
                continue
            try:
                existing = self._display_name_key(summary.display_name)
            except ValueError:
                existing = str(summary.display_name or "").strip().casefold()
            if existing == candidate:
                return True
        return False

    # ------------------------------------------------------------------
    # Paths
    # ------------------------------------------------------------------

    def analysis_databases_dir(self, *, market: MarketId, ensure: bool = False) -> Path:
        if ensure:
            return self._paths.ensure_dataset_dir(market, ANALYSIS_DATABASE_DATASET_TYPE)
        return self._paths.dataset_dir(market, ANALYSIS_DATABASE_DATASET_TYPE)

    def database_dir(self, *, market: MarketId, database_id: str, ensure: bool = False) -> Path:
        parent = self.analysis_databases_dir(market=market, ensure=ensure)
        path = parent / self._safe_database_id(database_id)
        if ensure:
            path.mkdir(parents=True, exist_ok=True)
        return path

    def manifest_path(self, *, market: MarketId, database_id: str) -> Path:
        return self.database_dir(market=market, database_id=database_id) / ANALYSIS_DATABASE_MANIFEST_FILENAME

    def dataframe_path(self, *, market: MarketId, database_id: str) -> Path:
        return self.database_dir(market=market, database_id=database_id) / ANALYSIS_DATABASE_DATAFRAME_FILENAME

    # ------------------------------------------------------------------
    # Draft construction
    # ------------------------------------------------------------------

    def build_draft_manifest(
        self,
        *,
        market: MarketId,
        display_name: str,
        user_description: str = "",
        include_volume: bool = True,
        feature_sources: Iterable[AnalysisFeatureSource] = (),
        feature_columns: Iterable[AnalysisDatabaseColumn] = (),
        metadata: Iterable[AnalysisMetadataEntry] = (),
        description_metadata: Iterable[AnalysisMetadataEntry] = (),
    ) -> AnalysisDatabaseManifest:
        """Build a draft Analysis Database manifest without materializing CSV data."""
        display_name = self.validate_database_display_name(display_name)
        feature_sources_tuple = tuple(feature_sources)
        feature_columns_tuple = tuple(feature_columns)
        metadata_tuple = tuple(metadata)
        description_metadata_tuple = tuple(description_metadata)
        alignment = AnalysisDatabaseAlignment()
        base_columns = self._default_base_columns(include_volume=include_volume)

        generated_summary = self._build_generated_summary(
            market=market,
            base_columns=base_columns,
            feature_columns=feature_columns_tuple,
            feature_sources=feature_sources_tuple,
            materialization=None,
        )
        studies_used_summary = self._build_studies_used_summary(feature_sources_tuple)
        description = AnalysisDatabaseDescription(
            user_text=user_description,
            generated_summary=generated_summary,
            studies_used_summary=studies_used_summary,
            metadata=description_metadata_tuple,
        )

        recipe_payload = build_analysis_database_recipe_payload(
            market=market,
            alignment=alignment,
            base_columns=base_columns,
            feature_sources=feature_sources_tuple,
            feature_columns=feature_columns_tuple,
            metadata=metadata_tuple,
            description_metadata=description_metadata_tuple,
        )
        recipe_hash = build_recipe_hash(recipe_payload)
        database_id = build_analysis_database_id(display_name, recipe_hash)

        return AnalysisDatabaseManifest(
            schema_version=ANALYSIS_DATABASE_SCHEMA_VERSION,
            artifact_type=ANALYSIS_DATABASE_ARTIFACT_TYPE,
            database_id=database_id,
            display_name=display_name,
            status="draft",
            description=description,
            market=market,
            dataframe_filename=None,
            alignment=alignment,
            base_columns=base_columns,
            feature_sources=feature_sources_tuple,
            feature_columns=feature_columns_tuple,
            recipe_hash=recipe_hash,
            recipe_hash_short=build_recipe_hash_short(recipe_hash),
            materialization=None,
            metadata=metadata_tuple,
        )

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save_manifest(self, manifest: AnalysisDatabaseManifest, *, overwrite: bool = True) -> Path:
        """Save a draft/new manifest with visible-name conflict protection.

        This public path is used for database creation and remains strict about
        duplicate display names inside a market/timeframe partition. Existing
        database repair/materialization paths must use ``_save_existing_manifest``
        so rebuilding one database by ``database_id`` is not blocked by visible
        name checks intended for create/rename workflows.
        """
        manifest = self._normalized_manifest_display_name(manifest)

        target = self.manifest_path(market=manifest.market, database_id=manifest.database_id)
        if target.exists() and not overwrite:
            raise FileExistsError(f"Analysis database manifest already exists: {target}")
        self._assert_display_name_available(
            market=manifest.market,
            display_name=manifest.display_name,
            exclude_database_id=manifest.database_id,
        )
        self._atomic_write_json(manifest.to_dict(), target)
        return target

    def _save_existing_manifest(self, manifest: AnalysisDatabaseManifest) -> Path:
        """Update an existing database manifest by immutable database_id.

        This is the repair/materialization path. It intentionally does not run
        duplicate visible-name validation because it is not creating a database
        and it is not renaming one; it is updating the selected existing
        database's own ``manifest.json`` after rebuilding ``dataframe.csv`` or
        otherwise preserving the same database identity.
        """
        manifest = self._normalized_manifest_display_name(manifest)
        target = self.manifest_path(market=manifest.market, database_id=manifest.database_id)
        if not target.exists():
            raise FileNotFoundError(f"Analysis database manifest not found: {target}")
        self._atomic_write_json(manifest.to_dict(), target)
        return target

    def _normalized_manifest_display_name(
        self,
        manifest: AnalysisDatabaseManifest,
    ) -> AnalysisDatabaseManifest:
        display_name = self.validate_database_display_name(manifest.display_name)
        if display_name != manifest.display_name:
            return replace(manifest, display_name=display_name)
        return manifest

    def load_manifest(self, *, market: MarketId, database_id: str) -> AnalysisDatabaseManifest:
        path = self.manifest_path(market=market, database_id=database_id)
        if not path.exists():
            raise FileNotFoundError(f"Analysis database manifest not found: {path}")
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        return AnalysisDatabaseManifest.from_dict(data)

    def list_databases(self, *, market: MarketId | None = None) -> list[AnalysisDatabaseSummary]:
        manifests = self._manifest_paths_for_market(market) if market is not None else self._all_manifest_paths()
        summaries: list[AnalysisDatabaseSummary] = []
        for path in manifests:
            try:
                with path.open("r", encoding="utf-8") as handle:
                    manifest = AnalysisDatabaseManifest.from_dict(json.load(handle))
                summaries.append(AnalysisDatabaseSummary.from_manifest(manifest, manifest_path=path))
            except Exception:
                continue
        summaries.sort(key=lambda item: (item.market.exchange, item.market.market_type, item.market.symbol, item.market.timeframe, item.display_name.lower()))
        return summaries

    def load_dataframe(self, *, market: MarketId, database_id: str) -> pd.DataFrame:
        path = self.dataframe_path(market=market, database_id=database_id)
        if not path.exists():
            raise FileNotFoundError(f"Analysis database dataframe not found: {path}")
        return pd.read_csv(path)

    def materialization_source_ohlcv_drift_report(
        self,
        *,
        market: MarketId,
        database_id: str,
    ) -> SourceOhlcvDriftReport:
        """
        Compare materialized source OHLCV provenance with current OHLCV truth.

        The method is read-only. It does not rebuild the dataframe, repair the
        manifest, or backfill missing legacy source provenance.
        """
        manifest = self.load_manifest(market=market, database_id=database_id)
        if manifest.materialization is None:
            return SourceOhlcvDriftReport(
                matches=False,
                status="unknown",
                reasons=("missing_recorded_source_ohlcv_snapshot",),
                actionable=True,
            )
        recorded_snapshot = extract_source_ohlcv_snapshot(manifest.materialization.metadata)
        return build_source_ohlcv_drift_report(
            historical_root=self._historical_root,
            market=manifest.market,
            recorded_snapshot=recorded_snapshot,
        )

    def rename_database(self, *, market: MarketId, database_id: str, new_display_name: str) -> AnalysisDatabaseManifest:
        """Rename a database by mutating display_name only.

        ``database_id`` and the folder path are immutable persistence identity;
        a user-facing rename must not move the folder or recompute the id.
        """
        display_name = self.validate_database_display_name(new_display_name)
        manifest = self.load_manifest(market=market, database_id=database_id)
        self._assert_display_name_available(
            market=manifest.market,
            display_name=display_name,
            exclude_database_id=manifest.database_id,
        )
        updated = replace(manifest, display_name=display_name)
        self.save_manifest(updated, overwrite=True)
        return updated

    def delete_database(self, *, market: MarketId, database_id: str) -> None:
        """Delete one folder-backed Analysis Database artifact."""
        path = self.database_dir(market=market, database_id=database_id)
        if not path.exists():
            raise FileNotFoundError(f"Analysis database folder not found: {path}")
        if not path.is_dir():
            raise NotADirectoryError(f"Analysis database path is not a folder: {path}")
        shutil.rmtree(path)

    def replace_database_features(
        self,
        *,
        market: MarketId,
        database_id: str,
        feature_sources: Iterable[AnalysisFeatureSource],
        feature_columns: Iterable[AnalysisDatabaseColumn],
    ) -> AnalysisDatabaseManifest:
        """Replace selected feature recipe while preserving database identity."""
        manifest = self.load_manifest(market=market, database_id=database_id)
        feature_sources_tuple = tuple(feature_sources)
        feature_columns_tuple = tuple(feature_columns)
        recipe_hash = self._recipe_hash_for_manifest_features(
            manifest=manifest,
            feature_sources=feature_sources_tuple,
            feature_columns=feature_columns_tuple,
        )
        description = replace(
            manifest.description,
            generated_summary=self._build_generated_summary(
                market=manifest.market,
                base_columns=manifest.base_columns,
                feature_columns=feature_columns_tuple,
                feature_sources=feature_sources_tuple,
                materialization=None,
            ),
            studies_used_summary=self._build_studies_used_summary(feature_sources_tuple),
        )
        updated = replace(
            manifest,
            status="draft",
            dataframe_filename=None,
            description=description,
            feature_sources=feature_sources_tuple,
            feature_columns=feature_columns_tuple,
            recipe_hash=recipe_hash,
            recipe_hash_short=build_recipe_hash_short(recipe_hash),
            materialization=None,
        )
        self._save_existing_manifest(updated)
        dataframe_path = self.dataframe_path(market=market, database_id=database_id)
        if dataframe_path.exists():
            dataframe_path.unlink()
        return updated

    def rebuild_database_with_features(
        self,
        *,
        market: MarketId,
        database_id: str,
        feature_sources: Iterable[AnalysisFeatureSource],
        feature_columns: Iterable[AnalysisDatabaseColumn],
        overwrite: bool = True,
    ) -> AnalysisDatabaseManifest:
        """Replace selected features and materialize the updated recipe."""
        updated = self.replace_database_features(
            market=market,
            database_id=database_id,
            feature_sources=feature_sources,
            feature_columns=feature_columns,
        )
        return self.materialize_database(market=updated.market, database_id=updated.database_id, overwrite=overwrite)

    # ------------------------------------------------------------------
    # Materialization
    # ------------------------------------------------------------------

    def materialize_database(
        self,
        *,
        market: MarketId,
        database_id: str,
        overwrite: bool = True,
    ) -> AnalysisDatabaseManifest:
        """Materialize a saved draft manifest into dataframe.csv.

        Materialization is manifest-driven. It does not depend on current GUI
        selection state. Alignment is strict: OHLCV ``ts_ms`` is the master
        timeline, every source artifact must expose ``ts_ms`` or ``time``,
        duplicate timestamps are rejected, and feature columns are left-joined
        onto OHLCV by timestamp.
        """
        manifest = self.load_manifest(market=market, database_id=database_id)
        target = self.dataframe_path(market=market, database_id=database_id)
        if target.exists() and not overwrite:
            raise FileExistsError(f"Analysis database dataframe already exists: {target}")

        dataframe = self._build_materialized_dataframe(manifest)
        source_ohlcv_snapshot = build_source_ohlcv_provenance_snapshot(
            historical_root=self._historical_root,
            market=manifest.market,
        )
        self._atomic_write_dataframe(dataframe, target)
        dataframe_sha256 = self._sha256_file(target)

        now_ms = int(time.time() * 1000)
        existing_materialization = manifest.materialization
        created_at_ms = now_ms if existing_materialization is None else existing_materialization.created_at_ms
        first_ts_ms = None if dataframe.empty else int(dataframe["ts_ms"].iloc[0])
        last_ts_ms = None if dataframe.empty else int(dataframe["ts_ms"].iloc[-1])
        materialization = AnalysisDatabaseMaterialization(
            row_count=int(len(dataframe)),
            column_count=int(len(dataframe.columns)),
            first_ts_ms=first_ts_ms,
            last_ts_ms=last_ts_ms,
            dataframe_sha256=dataframe_sha256,
            created_at_ms=created_at_ms,
            updated_at_ms=now_ms,
            metadata=self._materialization_metadata_with_source_ohlcv(
                existing=() if existing_materialization is None else existing_materialization.metadata,
                snapshot=source_ohlcv_snapshot,
            ),
        )

        description = replace(
            manifest.description,
            generated_summary=self._build_generated_summary(
                market=manifest.market,
                base_columns=manifest.base_columns,
                feature_columns=manifest.feature_columns,
                feature_sources=manifest.feature_sources,
                materialization=materialization,
            ),
        )
        updated = replace(
            manifest,
            status="materialized",
            dataframe_filename=ANALYSIS_DATABASE_DATAFRAME_FILENAME,
            description=description,
            materialization=materialization,
        )
        self._save_existing_manifest(updated)
        return updated

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _default_base_columns(self, *, include_volume: bool) -> tuple[AnalysisDatabaseColumn, ...]:
        columns: list[AnalysisDatabaseColumn] = [
            AnalysisDatabaseColumn(
                role="primary_key",
                selected=True,
                source_family="ohlcv",
                source_id=None,
                source_column_name="ts_ms",
                db_column_name="ts_ms",
                dtype="int64",
                nullable=False,
                analysis_usable=True,
                renderable=False,
                locked=True,
            )
        ]
        for column_name in BASE_OHLC_COLUMNS:
            columns.append(
                AnalysisDatabaseColumn(
                    role="base",
                    selected=True,
                    source_family="ohlcv",
                    source_id=None,
                    source_column_name=column_name,
                    db_column_name=build_database_column_name(
                        source_family="ohlcv",
                        tool_key=None,
                        instance_key=None,
                        source_column_name=column_name,
                    ),
                    dtype="float64",
                    nullable=False,
                    analysis_usable=True,
                    renderable=True,
                    locked=True,
                )
            )
        columns.append(
            AnalysisDatabaseColumn(
                role="base",
                selected=bool(include_volume),
                source_family="ohlcv",
                source_id=None,
                source_column_name="volume",
                db_column_name="volume",
                dtype="float64",
                nullable=False,
                analysis_usable=True,
                renderable=False,
                locked=False,
            )
        )
        return tuple(columns)

    def _materialization_metadata_with_source_ohlcv(
        self,
        *,
        existing: Iterable[AnalysisMetadataEntry],
        snapshot: dict[str, object],
    ) -> tuple[AnalysisMetadataEntry, ...]:
        retained = tuple(
            entry
            for entry in existing
            if not (
                entry.namespace == SOURCE_OHLCV_PROVENANCE_NAMESPACE
                and entry.key == SOURCE_OHLCV_PROVENANCE_KEY
            )
        )
        return retained + (
            AnalysisMetadataEntry(
                namespace=SOURCE_OHLCV_PROVENANCE_NAMESPACE,
                key=SOURCE_OHLCV_PROVENANCE_KEY,
                value=snapshot,
                label="Source OHLCV provenance",
                description="Accepted OHLCV source snapshot used for this materialization.",
                tags=("source_ohlcv", "lineage"),
                searchable=False,
                identity_affecting=False,
            ),
        )

    def _build_materialized_dataframe(self, manifest: AnalysisDatabaseManifest) -> pd.DataFrame:
        result = self._load_selected_ohlcv_dataframe(manifest)
        selected_feature_columns = [column for column in manifest.feature_columns if column.selected]
        if not selected_feature_columns:
            return result

        source_by_id = {source.source_id: source for source in manifest.feature_sources}
        columns_by_source: dict[str, list[AnalysisDatabaseColumn]] = {}
        for column in selected_feature_columns:
            if not column.source_id:
                raise ValueError(f"Feature column {column.db_column_name!r} is missing source_id.")
            columns_by_source.setdefault(column.source_id, []).append(column)

        for source_id, columns in columns_by_source.items():
            source = source_by_id.get(source_id)
            if source is None:
                raise ValueError(f"Manifest feature column references missing source_id: {source_id}")
            artifact = self._load_source_artifact_dataframe(manifest=manifest, source=source)
            source_column_names = [column.source_column_name for column in columns]
            missing = [name for name in source_column_names if name not in artifact.columns]
            if missing:
                raise ValueError(
                    f"Source artifact {source.source_artifact_relpath!r} is missing selected column(s): {missing}"
                )

            selected = artifact[["ts_ms", *source_column_names]].copy()
            rename_map = {column.source_column_name: column.db_column_name for column in columns}
            selected = selected.rename(columns=rename_map)
            duplicate_db_columns = [name for name in selected.columns if name != "ts_ms" and name in result.columns]
            if duplicate_db_columns:
                raise ValueError(f"Analysis database column name collision: {duplicate_db_columns}")

            result = result.merge(selected, on="ts_ms", how="left", validate="one_to_one")

        return result

    def _load_selected_ohlcv_dataframe(self, manifest: AnalysisDatabaseManifest) -> pd.DataFrame:
        path = self._paths.ohlcv_dir(manifest.market) / "candles.csv"
        require_ohlcv_dataset_loadable(
            historical_root=self._historical_root,
            market=manifest.market,
            context="Data Manager Analysis Database materialization",
        )
        if not path.exists():
            raise FileNotFoundError(f"OHLCV candles.csv not found: {path}")

        dataframe = pd.read_csv(path)
        self._require_columns(dataframe, ["ts_ms"], context=str(path))
        dataframe = self._with_ts_ms(dataframe, context=str(path))
        self._validate_ts_ms(dataframe, context=str(path))

        selected_columns = [column for column in manifest.base_columns if column.selected]
        if not any(column.source_column_name == "ts_ms" for column in selected_columns):
            raise ValueError("Analysis database base column contract must include selected ts_ms.")

        source_names = [column.source_column_name for column in selected_columns]
        self._require_columns(dataframe, source_names, context=str(path))
        result = dataframe[source_names].copy()
        rename_map = {
            column.source_column_name: column.db_column_name
            for column in selected_columns
            if column.source_column_name != column.db_column_name
        }
        if rename_map:
            result = result.rename(columns=rename_map)
        if "ts_ms" not in result.columns:
            raise ValueError("Materialized analysis database must contain ts_ms.")
        if result.columns.duplicated().any():
            duplicates = list(result.columns[result.columns.duplicated()])
            raise ValueError(f"Duplicate base database column names: {duplicates}")
        return result

    def _load_source_artifact_dataframe(
        self,
        *,
        manifest: AnalysisDatabaseManifest,
        source: AnalysisFeatureSource,
    ) -> pd.DataFrame:
        path = self._source_artifact_path(market=manifest.market, source=source)
        if not path.exists():
            raise FileNotFoundError(f"Source artifact not found: {path}")
        dataframe = pd.read_csv(path)
        dataframe = self._with_ts_ms(dataframe, context=str(path))
        self._validate_ts_ms(dataframe, context=str(path))
        return dataframe

    def _source_artifact_path(self, *, market: MarketId, source: AnalysisFeatureSource) -> Path:
        partition_dir = self._paths.partition_dir(market)
        candidate = partition_dir / source.source_artifact_relpath
        if candidate.exists():
            return candidate

        fallback = partition_dir / source.family / source.source_artifact_filename
        if fallback.exists():
            return fallback

        return candidate

    def _with_ts_ms(self, dataframe: pd.DataFrame, *, context: str) -> pd.DataFrame:
        if "ts_ms" in dataframe.columns:
            out = dataframe.copy()
            out["ts_ms"] = pd.to_numeric(out["ts_ms"], errors="raise").astype("int64")
            return out

        if "time" not in dataframe.columns:
            raise ValueError(f"{context} must contain either 'ts_ms' or 'time' for timestamp alignment.")

        out = dataframe.copy()
        numeric = pd.to_numeric(out["time"], errors="coerce")
        if numeric.notna().all():
            max_abs = float(numeric.abs().max()) if len(numeric) else 0.0
            if max_abs < 10_000_000_000:
                numeric = (numeric * 1000.0).round()
            out["ts_ms"] = numeric.astype("int64")
            return out

        parsed = pd.to_datetime(out["time"], utc=True, errors="raise")
        out["ts_ms"] = (parsed.astype("int64") // 1_000_000).astype("int64")
        return out

    def _validate_ts_ms(self, dataframe: pd.DataFrame, *, context: str) -> None:
        if dataframe["ts_ms"].isna().any():
            raise ValueError(f"{context} contains null ts_ms values.")
        if dataframe["ts_ms"].duplicated().any():
            raise ValueError(f"{context} contains duplicate ts_ms values; duplicate_policy=reject.")
        if not dataframe["ts_ms"].is_monotonic_increasing:
            raise ValueError(f"{context} ts_ms values must be monotonically increasing.")

    def _require_columns(self, dataframe: pd.DataFrame, columns: Iterable[str], *, context: str) -> None:
        missing = [name for name in columns if name not in dataframe.columns]
        if missing:
            raise ValueError(f"{context} is missing required column(s): {missing}")

    def _build_generated_summary(
        self,
        *,
        market: MarketId,
        base_columns: tuple[AnalysisDatabaseColumn, ...],
        feature_columns: tuple[AnalysisDatabaseColumn, ...],
        feature_sources: tuple[AnalysisFeatureSource, ...],
        materialization: AnalysisDatabaseMaterialization | None,
    ) -> str:
        selected_base_count = sum(1 for column in base_columns if column.selected)
        prefix = "Analysis database" if materialization is not None else "Analysis database draft"
        summary = (
            f"{prefix} for "
            f"{market.exchange} / {market.market_type} / {market.symbol} / {market.timeframe}. "
            f"Includes {selected_base_count} selected OHLCV column(s) and "
            f"{len(feature_columns)} selected feature column(s) from "
            f"{len(feature_sources)} saved tool artifact(s)."
        )
        if materialization is not None:
            summary += f" Materialized with {materialization.row_count} row(s) and {materialization.column_count} column(s)."
        return summary

    def _build_studies_used_summary(self, sources: tuple[AnalysisFeatureSource, ...]) -> str:
        if not sources:
            return "No indicator, oscillator, or construct sources selected."

        family_titles = {
            "indicators": "Indicators",
            "oscillators": "Oscillators",
            "constructs": "Constructs",
        }
        lines: list[str] = []
        for family in ("indicators", "oscillators", "constructs"):
            family_sources = [source for source in sources if source.family == family]
            if not family_sources:
                continue
            lines.append(f"{family_titles[family]}:")
            for source in family_sources:
                params = self._format_params(source.params, source.params_status)
                bindings = self._format_params(source.bindings, source.bindings_status)
                detail = f"- {source.tool_title} ({source.tool_key}) · {source.instance_key}"
                if params:
                    detail += f" · params: {params}"
                if bindings:
                    detail += f" · bindings: {bindings}"
                lines.append(detail)
        return "\n".join(lines)

    def _format_params(self, values: dict[str, object], status: str) -> str:
        if not values:
            return "" if status in {"unknown", "not_applicable"} else f"{status}: none"
        joined = ", ".join(f"{key}={values[key]!r}" for key in sorted(values.keys()))
        return f"{joined} ({status})"

    def _recipe_hash_for_manifest_features(
        self,
        *,
        manifest: AnalysisDatabaseManifest,
        feature_sources: tuple[AnalysisFeatureSource, ...],
        feature_columns: tuple[AnalysisDatabaseColumn, ...],
    ) -> str:
        recipe_payload = build_analysis_database_recipe_payload(
            market=manifest.market,
            alignment=manifest.alignment,
            base_columns=manifest.base_columns,
            feature_sources=feature_sources,
            feature_columns=feature_columns,
            metadata=manifest.metadata,
            description_metadata=manifest.description.metadata,
        )
        return build_recipe_hash(recipe_payload)

    def _display_name_key(self, display_name: str) -> str:
        return self.validate_database_display_name(display_name).casefold()

    def _assert_display_name_available(
        self,
        *,
        market: MarketId,
        display_name: str,
        exclude_database_id: str | None = None,
    ) -> None:
        if self.display_name_exists(
            market=market,
            display_name=display_name,
            exclude_database_id=exclude_database_id,
        ):
            raise FileExistsError(
                "An analysis database with this name already exists for "
                f"{market.exchange} / {market.market_type} / {market.symbol} / {market.timeframe}: {display_name}"
            )

    def _manifest_paths_for_market(self, market: MarketId) -> list[Path]:
        base = self.analysis_databases_dir(market=market, ensure=False)
        if not base.exists():
            return []
        return sorted(base.glob(f"*/{ANALYSIS_DATABASE_MANIFEST_FILENAME}"))

    def _all_manifest_paths(self) -> list[Path]:
        if not self._historical_root.exists():
            return []
        return sorted(self._historical_root.glob(f"*/*/*/*/{ANALYSIS_DATABASE_DATASET_TYPE}/*/{ANALYSIS_DATABASE_MANIFEST_FILENAME}"))

    def _safe_database_id(self, database_id: str) -> str:
        value = str(database_id).strip()
        if not value or "/" in value or "\\" in value or value in {".", ".."}:
            raise ValueError(f"Invalid analysis database id: {database_id!r}")
        return value

    def _atomic_write_json(self, data: dict[str, object], target_path: Path) -> None:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="",
            suffix=".tmp",
            prefix="analysis_database_",
            dir=str(target_path.parent),
            delete=False,
        ) as tmp:
            tmp_path = Path(tmp.name)
            try:
                json.dump(data, tmp, indent=2, sort_keys=True)
                tmp.write("\n")
            except Exception:
                try:
                    tmp_path.unlink(missing_ok=True)
                except Exception:
                    pass
                raise
        os.replace(tmp_path, target_path)


    def _atomic_write_dataframe(self, dataframe: pd.DataFrame, target_path: Path) -> None:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="",
            suffix=".tmp",
            prefix="analysis_dataframe_",
            dir=str(target_path.parent),
            delete=False,
        ) as tmp:
            tmp_path = Path(tmp.name)
            try:
                dataframe.to_csv(tmp, index=False)
            except Exception:
                try:
                    tmp_path.unlink(missing_ok=True)
                except Exception:
                    pass
                raise
        os.replace(tmp_path, target_path)

    def _sha256_file(self, path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()


def infer_market_from_manifest_path(*, historical_root: Path, manifest_path: Path) -> MarketId:
    """Infer MarketId from .../{exchange}/{market_type}/{symbol}/{timeframe}/analysis_databases/{id}/manifest.json."""
    rel = Path(manifest_path).resolve().relative_to(Path(historical_root).resolve())
    parts = rel.parts
    if len(parts) < 7:
        raise ValueError(f"Manifest path is not inside a historical market analysis database partition: {manifest_path}")
    exchange, market_type, symbol, timeframe = parts[0], parts[1], parts[2], parts[3]
    return canonicalize(exchange, market_type, symbol, timeframe)
