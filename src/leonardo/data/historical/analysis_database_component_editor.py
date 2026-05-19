from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Literal

from leonardo.data.naming import MarketId

from .analysis_database_contracts import (
    AnalysisDatabaseColumn,
    AnalysisDatabaseManifest,
    AnalysisFeatureSource,
)
from .analysis_database_store import AnalysisDatabaseStore


AnalysisDatabaseComponentEditStatus = Literal["updated"]


@dataclass(frozen=True)
class AnalysisDatabaseComponentEditReport:
    """Report for an explicit Analysis Database component edit.

    Component edits intentionally change the saved Analysis Database recipe.
    They do not materialize ``dataframe.csv``. After a successful edit the
    database is reset to draft/unmaterialized state and must be rebuilt through
    ``AnalysisDatabaseStore.materialize_database(...)``.
    """

    market: MarketId
    database_id: str
    status: AnalysisDatabaseComponentEditStatus
    manifest: AnalysisDatabaseManifest
    previous_recipe_hash: str
    new_recipe_hash: str
    previous_feature_count: int
    new_feature_count: int
    dataframe_existed_before: bool
    dataframe_exists_after: bool

    @property
    def success(self) -> bool:
        return self.status == "updated"

    @property
    def recipe_changed(self) -> bool:
        return self.previous_recipe_hash != self.new_recipe_hash

    @property
    def materialization_reset(self) -> bool:
        return self.manifest.materialization is None and self.manifest.dataframe_filename is None

    @property
    def dataframe_removed(self) -> bool:
        return self.dataframe_existed_before and not self.dataframe_exists_after

    def to_dict(self) -> dict[str, object]:
        return {
            "market": {
                "exchange": self.market.exchange,
                "market_type": self.market.market_type,
                "symbol": self.market.symbol,
                "timeframe": self.market.timeframe,
            },
            "database_id": self.database_id,
            "status": self.status,
            "success": self.success,
            "recipe_changed": self.recipe_changed,
            "materialization_reset": self.materialization_reset,
            "dataframe_removed": self.dataframe_removed,
            "previous_recipe_hash": self.previous_recipe_hash,
            "new_recipe_hash": self.new_recipe_hash,
            "previous_feature_count": self.previous_feature_count,
            "new_feature_count": self.new_feature_count,
            "dataframe_existed_before": self.dataframe_existed_before,
            "dataframe_exists_after": self.dataframe_exists_after,
            "manifest": self.manifest.to_dict(),
        }


class AnalysisDatabaseComponentEditor:
    """Explicit editor for Analysis Database feature components.

    Ownership boundaries:
    - this class owns component-edit orchestration and validation only;
    - ``AnalysisDatabaseStore`` owns manifest persistence, dataframe paths, and
      materialization semantics;
    - this class must not build/materialize ``dataframe.csv``;
    - GUI code must map user selections into ``AnalysisFeatureSource`` and
      ``AnalysisDatabaseColumn`` objects before calling this service.

    This service is intentionally separate from Database Builder rebuild. A
    rebuild re-materializes the existing manifest recipe. A component edit
    deliberately changes that recipe and resets materialization.
    """

    def __init__(
        self,
        *,
        historical_root: Path,
        store: AnalysisDatabaseStore | None = None,
    ) -> None:
        self._historical_root = Path(historical_root)
        self._store = store or AnalysisDatabaseStore(historical_root=self._historical_root)

    def replace_components(
        self,
        *,
        market: MarketId,
        database_id: str,
        feature_sources: Iterable[AnalysisFeatureSource],
        feature_columns: Iterable[AnalysisDatabaseColumn],
    ) -> AnalysisDatabaseComponentEditReport:
        """Replace all feature components while preserving database identity.

        The existing ``database_id``, folder, display name, base columns, user
        description, and non-feature metadata are preserved by the store. The
        feature recipe is replaced, existing materialization metadata is reset,
        and any stale ``dataframe.csv`` is removed. The caller must rebuild the
        database explicitly after this edit.
        """

        before = self._store.load_manifest(market=market, database_id=database_id)
        sources, columns = self._validate_and_normalize_components(
            feature_sources=tuple(feature_sources),
            feature_columns=tuple(feature_columns),
        )
        return self._apply_component_replacement(
            before=before,
            feature_sources=sources,
            feature_columns=columns,
        )

    def add_components(
        self,
        *,
        market: MarketId,
        database_id: str,
        feature_sources: Iterable[AnalysisFeatureSource],
        feature_columns: Iterable[AnalysisDatabaseColumn],
    ) -> AnalysisDatabaseComponentEditReport:
        """Add feature components to an existing database recipe.

        Existing feature columns are preserved. New feature columns must not
        collide with existing database column names.
        """

        before = self._store.load_manifest(market=market, database_id=database_id)
        new_sources, new_columns = self._validate_and_normalize_components(
            feature_sources=tuple(feature_sources),
            feature_columns=tuple(feature_columns),
        )
        merged_sources_by_id: dict[str, AnalysisFeatureSource] = {
            source.source_id: source for source in before.feature_sources
        }
        for source in new_sources:
            merged_sources_by_id.setdefault(source.source_id, source)

        merged_columns = tuple(before.feature_columns) + tuple(new_columns)
        merged_sources = tuple(merged_sources_by_id.values())
        sources, columns = self._validate_and_normalize_components(
            feature_sources=merged_sources,
            feature_columns=merged_columns,
        )
        return self._apply_component_replacement(
            before=before,
            feature_sources=sources,
            feature_columns=columns,
        )

    def remove_components(
        self,
        *,
        market: MarketId,
        database_id: str,
        db_column_names: Iterable[str],
    ) -> AnalysisDatabaseComponentEditReport:
        """Remove feature components by database-column name.

        Source entries no longer referenced by any remaining feature column are
        pruned from the saved recipe.
        """

        before = self._store.load_manifest(market=market, database_id=database_id)
        names_to_remove = {str(name).strip() for name in db_column_names if str(name).strip()}
        if not names_to_remove:
            raise ValueError("At least one db_column_name is required for component removal.")

        unknown = names_to_remove - {column.db_column_name for column in before.feature_columns}
        if unknown:
            raise ValueError(f"Cannot remove unknown Analysis Database component column(s): {sorted(unknown)}")

        remaining_columns = tuple(
            column for column in before.feature_columns if column.db_column_name not in names_to_remove
        )
        remaining_source_ids = {
            column.source_id for column in remaining_columns if column.source_id
        }
        remaining_sources = tuple(
            source for source in before.feature_sources if source.source_id in remaining_source_ids
        )
        sources, columns = self._validate_and_normalize_components(
            feature_sources=remaining_sources,
            feature_columns=remaining_columns,
        )
        return self._apply_component_replacement(
            before=before,
            feature_sources=sources,
            feature_columns=columns,
        )

    def _apply_component_replacement(
        self,
        *,
        before: AnalysisDatabaseManifest,
        feature_sources: tuple[AnalysisFeatureSource, ...],
        feature_columns: tuple[AnalysisDatabaseColumn, ...],
    ) -> AnalysisDatabaseComponentEditReport:
        dataframe_path = self._store.dataframe_path(
            market=before.market,
            database_id=before.database_id,
        )
        dataframe_existed_before = dataframe_path.exists()
        updated = self._store.replace_database_features(
            market=before.market,
            database_id=before.database_id,
            feature_sources=feature_sources,
            feature_columns=feature_columns,
        )
        dataframe_exists_after = dataframe_path.exists()
        return AnalysisDatabaseComponentEditReport(
            market=updated.market,
            database_id=updated.database_id,
            status="updated",
            manifest=updated,
            previous_recipe_hash=before.recipe_hash,
            new_recipe_hash=updated.recipe_hash,
            previous_feature_count=len(before.feature_columns),
            new_feature_count=len(updated.feature_columns),
            dataframe_existed_before=dataframe_existed_before,
            dataframe_exists_after=dataframe_exists_after,
        )

    def _validate_and_normalize_components(
        self,
        *,
        feature_sources: tuple[AnalysisFeatureSource, ...],
        feature_columns: tuple[AnalysisDatabaseColumn, ...],
    ) -> tuple[tuple[AnalysisFeatureSource, ...], tuple[AnalysisDatabaseColumn, ...]]:
        source_by_id: dict[str, AnalysisFeatureSource] = {}
        for source in feature_sources:
            if not isinstance(source, AnalysisFeatureSource):
                raise TypeError("feature_sources must contain AnalysisFeatureSource instances")
            source_id = str(source.source_id or "").strip()
            if not source_id:
                raise ValueError("Analysis Database feature source is missing source_id.")
            if source_id in source_by_id:
                raise ValueError(f"Duplicate Analysis Database feature source_id: {source_id}")
            source_by_id[source_id] = source

        db_column_names: set[str] = set()
        referenced_source_ids: list[str] = []
        for column in feature_columns:
            if not isinstance(column, AnalysisDatabaseColumn):
                raise TypeError("feature_columns must contain AnalysisDatabaseColumn instances")
            if column.role != "feature":
                raise ValueError(
                    f"Analysis Database component columns must use role='feature'; got {column.role!r}"
                )
            source_id = str(column.source_id or "").strip()
            if not source_id:
                raise ValueError(f"Feature column {column.db_column_name!r} is missing source_id.")
            if source_id not in source_by_id:
                raise ValueError(
                    f"Feature column {column.db_column_name!r} references missing source_id: {source_id}"
                )
            db_column_name = str(column.db_column_name or "").strip()
            if not db_column_name:
                raise ValueError("Feature column is missing db_column_name.")
            if db_column_name in db_column_names:
                raise ValueError(f"Duplicate Analysis Database db_column_name: {db_column_name}")
            db_column_names.add(db_column_name)
            referenced_source_ids.append(source_id)

        referenced_source_id_set = set(referenced_source_ids)
        unused_sources = [source_id for source_id in source_by_id if source_id not in referenced_source_id_set]
        if unused_sources:
            raise ValueError(
                "Analysis Database feature source(s) are not referenced by any feature column: "
                f"{sorted(unused_sources)}"
            )

        ordered_sources: list[AnalysisFeatureSource] = []
        seen_sources: set[str] = set()
        for column in feature_columns:
            source_id = str(column.source_id or "").strip()
            if source_id in seen_sources:
                continue
            ordered_sources.append(source_by_id[source_id])
            seen_sources.add(source_id)

        return tuple(ordered_sources), tuple(feature_columns)
