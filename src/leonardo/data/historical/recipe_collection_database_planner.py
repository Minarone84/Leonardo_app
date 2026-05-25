from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable, Mapping

from leonardo.data.historical.analysis_database_contracts import (
    AnalysisDatabaseColumn,
    AnalysisFeatureSource,
    AnalysisMetadataEntry,
)
from leonardo.data.historical.analysis_database_naming import (
    build_database_column_name,
    build_feature_source_id,
)
from leonardo.data.historical.analysis_dataset_geography import (
    AnalysisDatasetGeographyPolicy,
)
from leonardo.data.historical.artifact_metadata_contracts import (
    ArtifactColumnMetadata,
    HistoricalCsvArtifactManifest,
)
from leonardo.data.historical.artifact_recipe_collection_store import (
    ArtifactRecipeCollection,
    ArtifactRecipeCollectionStore,
)
from leonardo.data.historical.artifact_recipe_store import (
    ArtifactRecipe,
    market_to_dict,
)
from leonardo.data.historical.artifact_recovery_planner import (
    ArtifactRecoveryItemReport,
    ArtifactRecoveryPlanner,
)
from leonardo.data.historical.derived_store_csv import DerivedCsvStore
from leonardo.data.historical.paths import HistoricalPaths
from leonardo.data.naming import MarketId

_CURRENT_RECOVERY_STATUS = "up_to_date"
_NON_FEATURE_COLUMNS = {"ts_ms", "time", "timeframe"}


@dataclass(frozen=True)
class RecipeCollectionDatabaseWarning:
    """Non-blocking warning from recipe collection component planning."""

    code: str
    message: str
    metadata: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "metadata": _json_safe(self.metadata),
        }


@dataclass(frozen=True)
class RecipeCollectionDatabaseBlockedItem:
    """Recipe item that cannot become an Analysis Database component preview."""

    blocker_id: str
    recipe_index: int | None
    recipe_id: str | None
    tool_key: str | None
    status: str
    reason: str
    message: str
    metadata: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "blocker_id": self.blocker_id,
            "recipe_index": self.recipe_index,
            "recipe_id": self.recipe_id,
            "tool_key": self.tool_key,
            "status": self.status,
            "reason": self.reason,
            "message": self.message,
            "metadata": _json_safe(self.metadata),
        }


@dataclass(frozen=True)
class RecipeCollectionDatabaseComponentPreview:
    """Read-only Analysis Database component preview for one current artifact."""

    component_id: str
    recipe_index: int
    recipe_id: str | None
    recipe_hash: str | None
    tool_type: str
    tool_key: str
    storage_family: str
    instance_key: str
    artifact_relpath: str
    artifact_filename: str
    artifact_fingerprint: str | None
    source_preview: dict[str, Any]
    column_previews: tuple[dict[str, Any], ...]
    metadata: dict[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "source_preview",
            dict(self.source_preview),
        )
        object.__setattr__(
            self,
            "column_previews",
            tuple(dict(item) for item in self.column_previews),
        )
        object.__setattr__(self, "metadata", dict(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return {
            "component_id": self.component_id,
            "recipe_index": int(self.recipe_index),
            "recipe_id": self.recipe_id,
            "recipe_hash": self.recipe_hash,
            "tool_type": self.tool_type,
            "tool_key": self.tool_key,
            "storage_family": self.storage_family,
            "instance_key": self.instance_key,
            "artifact_relpath": self.artifact_relpath,
            "artifact_filename": self.artifact_filename,
            "artifact_fingerprint": self.artifact_fingerprint,
            "source_preview": _json_safe(self.source_preview),
            "column_previews": [_json_safe(item) for item in self.column_previews],
            "metadata": _json_safe(self.metadata),
        }


@dataclass(frozen=True)
class RecipeCollectionDatabasePlan:
    """Read-only component-resolution plan for one artifact recipe collection."""

    plan_id: str
    created_at_utc: str
    collection_id: str
    collection_display_name: str
    market: dict[str, str] | None
    source_database_id: str | None
    resolved_components: tuple[RecipeCollectionDatabaseComponentPreview, ...]
    blocked_items: tuple[RecipeCollectionDatabaseBlockedItem, ...]
    warnings: tuple[RecipeCollectionDatabaseWarning, ...]
    duplicate_columns: tuple[str, ...]
    geography_report: dict[str, Any] | None
    summary: dict[str, int]
    metadata: dict[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(self, "resolved_components", tuple(self.resolved_components))
        object.__setattr__(self, "blocked_items", tuple(self.blocked_items))
        object.__setattr__(self, "warnings", tuple(self.warnings))
        object.__setattr__(
            self,
            "duplicate_columns",
            tuple(str(item) for item in self.duplicate_columns),
        )
        object.__setattr__(self, "summary", dict(self.summary))
        object.__setattr__(self, "metadata", dict(self.metadata))
        if self.market is not None:
            object.__setattr__(self, "market", dict(self.market))

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "created_at_utc": self.created_at_utc,
            "collection_id": self.collection_id,
            "collection_display_name": self.collection_display_name,
            "market": None if self.market is None else dict(self.market),
            "source_database_id": self.source_database_id,
            "resolved_components": [
                component.to_dict() for component in self.resolved_components
            ],
            "blocked_items": [item.to_dict() for item in self.blocked_items],
            "warnings": [warning.to_dict() for warning in self.warnings],
            "duplicate_columns": list(self.duplicate_columns),
            "geography_report": _json_safe(self.geography_report),
            "summary": dict(self.summary),
            "metadata": _json_safe(self.metadata),
        }


class RecipeCollectionDatabasePlanner:
    """
    Resolve current recipe collection artifacts into database component previews.

    The planner consumes artifact recovery status and sidecar metadata. It
    returns typed preview data for future Analysis Database creation or
    extension flows. It does not edit manifests, run recipes, build artifacts,
    or coordinate user-interface behavior.
    """

    def __init__(
        self,
        *,
        historical_root: Path,
        recovery_planner: ArtifactRecoveryPlanner | None = None,
        collection_store: ArtifactRecipeCollectionStore | None = None,
        derived_store: DerivedCsvStore | None = None,
        geography_policy: AnalysisDatasetGeographyPolicy | None = None,
    ) -> None:
        self._historical_root = Path(historical_root)
        self._paths = HistoricalPaths(root=self._historical_root)
        self._collection_store = collection_store or ArtifactRecipeCollectionStore(
            historical_root=self._historical_root,
        )
        self._derived_store = derived_store or DerivedCsvStore(
            historical_root=self._historical_root,
        )
        self._recovery_planner = recovery_planner or ArtifactRecoveryPlanner(
            historical_root=self._historical_root,
            derived_store=self._derived_store,
            collection_store=self._collection_store,
        )
        self._geography_policy = geography_policy or AnalysisDatasetGeographyPolicy()

    def plan_collection_components_by_id(
        self,
        *,
        market: MarketId,
        collection_id: str,
        include_geography_report: bool = True,
    ) -> RecipeCollectionDatabasePlan:
        """
        Load a collection by id and build a read-only component preview plan.
        """

        collection = self._collection_store.load_collection(
            market=market,
            collection_id=collection_id,
        )
        return self.plan_collection_components(
            collection,
            include_geography_report=include_geography_report,
        )

    def plan_collection_components(
        self,
        collection: ArtifactRecipeCollection,
        *,
        include_geography_report: bool = True,
    ) -> RecipeCollectionDatabasePlan:
        """
        Resolve current collection artifacts into Analysis Database previews.

        Only recovery items whose status is ``up_to_date`` are converted into
        component previews. All other recovery statuses are reported as blocked
        because actionable recovery does not mean an artifact is safe to use as
        an Analysis Database feature.
        """

        if not isinstance(collection, ArtifactRecipeCollection):
            raise TypeError(
                "plan_collection_components() expects an ArtifactRecipeCollection instance"
            )

        recovery_report = self._recovery_planner.plan_collection(collection)
        recipe_by_id = {recipe.recipe_id: recipe for recipe in collection.recipe_snapshots}
        resolved: list[RecipeCollectionDatabaseComponentPreview] = []
        blocked: list[RecipeCollectionDatabaseBlockedItem] = []
        warnings: list[RecipeCollectionDatabaseWarning] = []
        source_objects: list[AnalysisFeatureSource] = []
        column_objects: list[AnalysisDatabaseColumn] = []

        if recovery_report.market != collection.market:
            blocked.append(
                self._collection_blocker(
                    reason="market_mismatch",
                    message="Recovery report market does not match the recipe collection market.",
                    metadata={
                        "collection_market": market_to_dict(collection.market),
                        "recovery_market": market_to_dict(recovery_report.market),
                    },
                )
            )

        for item in recovery_report.items:
            recipe = recipe_by_id.get(item.recipe_id)
            if recipe is None:
                blocked.append(self._missing_recipe_blocker(item))
                continue
            if recipe.market != collection.market:
                blocked.append(self._market_mismatch_blocker(item=item, recipe=recipe))
                continue
            if item.status != _CURRENT_RECOVERY_STATUS:
                blocked.append(self._recovery_status_blocker(item))
                continue

            component, component_source, component_columns, component_blockers, component_warnings = (
                self._component_preview(
                    collection=collection,
                    recipe=recipe,
                    item=item,
                )
            )
            blocked.extend(component_blockers)
            warnings.extend(component_warnings)
            if component is None:
                continue
            resolved.append(component)
            source_objects.append(component_source)
            column_objects.extend(component_columns)

        duplicate_columns = _duplicate_db_column_names(column_objects)
        if duplicate_columns:
            warnings.append(
                RecipeCollectionDatabaseWarning(
                    code="duplicate_planned_db_columns",
                    message=(
                        "Duplicate planned Analysis Database column names were "
                        "detected. Future database creation should resolve these "
                        "name collisions before editing a manifest."
                    ),
                    metadata={"duplicate_columns": duplicate_columns},
                )
            )

        geography_report = None
        if include_geography_report:
            geography_report = self._geography_policy.evaluate_components(
                base_columns=(),
                feature_sources=tuple(source_objects),
                feature_columns=tuple(column_objects),
                metadata={
                    "collection_id": collection.collection_id,
                    "collection_display_name": collection.display_name,
                    "source": "recipe_collection_database_planner",
                },
            ).to_dict()

        summary = {
            "total_recipes": len(collection.recipe_snapshots),
            "recovery_items": len(recovery_report.items),
            "resolved": len(resolved),
            "blocked": len(blocked),
            "warnings": len(warnings),
            "duplicate_columns": len(duplicate_columns),
        }
        return RecipeCollectionDatabasePlan(
            plan_id=_plan_id(collection=collection, recovery_item_count=len(recovery_report.items)),
            created_at_utc=_utc_now(),
            collection_id=collection.collection_id,
            collection_display_name=collection.display_name,
            market=market_to_dict(collection.market),
            source_database_id=collection.source_database_id,
            resolved_components=tuple(resolved),
            blocked_items=tuple(blocked),
            warnings=tuple(warnings),
            duplicate_columns=duplicate_columns,
            geography_report=geography_report,
            summary=summary,
            metadata={
                "collection_hash": collection.collection_hash,
                "collection_hash_short": collection.collection_hash_short,
                "recovery_report": recovery_report.to_dict(),
            },
        )

    def _component_preview(
        self,
        *,
        collection: ArtifactRecipeCollection,
        recipe: ArtifactRecipe,
        item: ArtifactRecoveryItemReport,
    ) -> tuple[
        RecipeCollectionDatabaseComponentPreview | None,
        AnalysisFeatureSource | None,
        tuple[AnalysisDatabaseColumn, ...],
        tuple[RecipeCollectionDatabaseBlockedItem, ...],
        tuple[RecipeCollectionDatabaseWarning, ...],
    ]:
        manifest = self._derived_store.load_metadata_manifest(item.expected_csv_path)
        if manifest is None:
            return (
                None,
                None,
                (),
                (
                    self._item_blocker(
                        item=item,
                        reason="metadata_unavailable",
                        message="Current artifact metadata sidecar could not be loaded.",
                        metadata={
                            "expected_metadata_path": item.expected_metadata_path,
                        },
                    ),
                ),
                (),
            )

        if manifest.market != collection.market:
            return (
                None,
                None,
                (),
                (
                    self._item_blocker(
                        item=item,
                        reason="market_mismatch",
                        message=(
                            "Resolved artifact metadata market does not match the "
                            "recipe collection market."
                        ),
                        metadata={
                            "collection_market": market_to_dict(collection.market),
                            "artifact_market": market_to_dict(manifest.market),
                        },
                    ),
                ),
                (),
            )

        source = self._analysis_source_from_artifact(
            collection=collection,
            recipe=recipe,
            item=item,
            manifest=manifest,
        )
        columns, blockers, warnings = self._analysis_columns_from_artifact(
            source=source,
            recipe=recipe,
            item=item,
            manifest=manifest,
        )
        if blockers:
            return None, None, (), blockers, warnings

        component = RecipeCollectionDatabaseComponentPreview(
            component_id=f"component:{recipe.recipe_id}",
            recipe_index=item.recipe_index,
            recipe_id=recipe.recipe_id,
            recipe_hash=recipe.recipe_hash,
            tool_type=recipe.tool_type,
            tool_key=recipe.tool_key,
            storage_family=item.expected_kind,
            instance_key=item.expected_instance_key,
            artifact_relpath=source.source_artifact_relpath,
            artifact_filename=source.source_artifact_filename,
            artifact_fingerprint=source.source_artifact_sha256,
            source_preview=source.to_dict(),
            column_previews=tuple(column.to_dict() for column in columns),
            metadata={
                "collection_id": collection.collection_id,
                "collection_hash": collection.collection_hash,
                "expected_metadata_path": item.expected_metadata_path,
                "artifact_uid": manifest.identity.artifact_uid,
                "metadata_relpath": manifest.files.metadata_relpath,
            },
        )
        return component, source, columns, (), warnings

    def _analysis_source_from_artifact(
        self,
        *,
        collection: ArtifactRecipeCollection,
        recipe: ArtifactRecipe,
        item: ArtifactRecoveryItemReport,
        manifest: HistoricalCsvArtifactManifest,
    ) -> AnalysisFeatureSource:
        source_id = build_feature_source_id(
            family=item.expected_kind,
            tool_key=recipe.tool_key,
            instance_key=item.expected_instance_key,
        )
        stat = _safe_stat(item.expected_csv_path)
        return AnalysisFeatureSource(
            source_id=source_id,
            family=item.expected_kind,
            tool_key=recipe.tool_key,
            tool_title=recipe.tool_title,
            instance_key=item.expected_instance_key,
            source_artifact_filename=item.expected_csv_path.name,
            source_artifact_relpath=self._source_relpath(
                market=collection.market,
                path=item.expected_csv_path,
            ),
            source_artifact_sha256=manifest.fingerprint.sha256,
            source_artifact_size_bytes=(
                int(stat.st_size)
                if stat is not None
                else manifest.fingerprint.size_bytes
            ),
            source_artifact_modified_at_ms=(
                int(stat.st_mtime * 1000)
                if stat is not None
                else manifest.fingerprint.modified_at_ms
            ),
            params=dict(recipe.params),
            params_status=_analysis_metadata_status(
                None if manifest.tool is None else manifest.tool.params_status
            ),
            bindings=dict(recipe.input_bindings),
            bindings_status=_analysis_metadata_status(
                None if manifest.tool is None else manifest.tool.bindings_status
            ),
            metadata=_source_metadata_entries(
                collection=collection,
                recipe=recipe,
                manifest=manifest,
                metadata_relpath=self._source_relpath(
                    market=collection.market,
                    path=item.expected_metadata_path,
                ),
            ),
        )

    def _analysis_columns_from_artifact(
        self,
        *,
        source: AnalysisFeatureSource,
        recipe: ArtifactRecipe,
        item: ArtifactRecoveryItemReport,
        manifest: HistoricalCsvArtifactManifest,
    ) -> tuple[
        tuple[AnalysisDatabaseColumn, ...],
        tuple[RecipeCollectionDatabaseBlockedItem, ...],
        tuple[RecipeCollectionDatabaseWarning, ...],
    ]:
        metadata_by_name = {column.name: column for column in manifest.columns}
        columns: list[AnalysisDatabaseColumn] = []
        blockers: list[RecipeCollectionDatabaseBlockedItem] = []
        warnings: list[RecipeCollectionDatabaseWarning] = []

        for output_name in item.expected_output_names:
            if output_name in _NON_FEATURE_COLUMNS:
                continue
            metadata_column = metadata_by_name.get(output_name)
            if metadata_column is None:
                warnings.append(
                    RecipeCollectionDatabaseWarning(
                        code="output_column_metadata_missing",
                        message=(
                            "Expected output column is present in artifact shape "
                            "but has no detailed column metadata."
                        ),
                        metadata={
                            "recipe_id": recipe.recipe_id,
                            "recipe_index": item.recipe_index,
                            "output_name": output_name,
                        },
                    )
                )
            elif not _column_is_analysis_selectable(metadata_column):
                blockers.append(
                    self._item_blocker(
                        item=item,
                        reason="output_column_not_analysis_usable",
                        message=(
                            f"Expected output column {output_name!r} is not "
                            "analysis-usable according to artifact metadata."
                        ),
                        metadata={
                            "output_name": output_name,
                            "column_metadata": metadata_column.to_dict(),
                        },
                    )
                )
                continue

            columns.append(
                AnalysisDatabaseColumn(
                    role="feature",
                    selected=True,
                    source_family=source.family,
                    source_id=source.source_id,
                    source_column_name=output_name,
                    db_column_name=build_database_column_name(
                        source_family=source.family,
                        tool_key=source.tool_key,
                        instance_key=source.instance_key,
                        source_column_name=output_name,
                    ),
                    dtype=None if metadata_column is None else metadata_column.dtype,
                    nullable=True,
                    analysis_usable=(
                        True
                        if metadata_column is None or metadata_column.analysis_usable is None
                        else bool(metadata_column.analysis_usable)
                    ),
                    renderable=(
                        None if metadata_column is None else metadata_column.renderable
                    ),
                    locked=False,
                    metadata=_column_metadata_entries(
                        recipe=recipe,
                        artifact_column=metadata_column,
                    ),
                )
            )

        if not columns and not blockers:
            blockers.append(
                self._item_blocker(
                    item=item,
                    reason="output_columns_unavailable",
                    message="No analysis-usable output columns were available for this artifact.",
                    metadata={"expected_output_names": item.expected_output_names},
                )
            )

        return tuple(columns), tuple(blockers), tuple(warnings)

    def _source_relpath(self, *, market: MarketId, path: Path) -> str:
        partition_dir = self._paths.partition_dir(market)
        try:
            return Path(path).resolve().relative_to(partition_dir.resolve()).as_posix()
        except Exception:
            return Path(path).name

    def _recovery_status_blocker(
        self,
        item: ArtifactRecoveryItemReport,
    ) -> RecipeCollectionDatabaseBlockedItem:
        reason = _blocked_reason_for_status(item)
        message = _blocked_message_for_status(item)
        return self._item_blocker(
            item=item,
            reason=reason,
            message=message,
            metadata={
                "status": item.status,
                "can_recalculate": item.can_recalculate,
                "actionable": item.actionable,
                "stale_reasons": item.stale_reasons,
                "blocked_reasons": item.blocked_reasons,
                "notes": item.notes,
                "expected_csv_path": item.expected_csv_path,
                "expected_metadata_path": item.expected_metadata_path,
            },
        )

    def _missing_recipe_blocker(
        self,
        item: ArtifactRecoveryItemReport,
    ) -> RecipeCollectionDatabaseBlockedItem:
        return self._item_blocker(
            item=item,
            reason="recipe_snapshot_missing",
            message="Recovery item did not match a recipe snapshot in the collection.",
            metadata={"recipe_id": item.recipe_id},
        )

    def _market_mismatch_blocker(
        self,
        *,
        item: ArtifactRecoveryItemReport,
        recipe: ArtifactRecipe,
    ) -> RecipeCollectionDatabaseBlockedItem:
        return self._item_blocker(
            item=item,
            reason="market_mismatch",
            message="Recipe market does not match the recipe collection market.",
            metadata={"recipe_market": market_to_dict(recipe.market)},
        )

    def _item_blocker(
        self,
        *,
        item: ArtifactRecoveryItemReport,
        reason: str,
        message: str,
        metadata: Mapping[str, Any] | None = None,
    ) -> RecipeCollectionDatabaseBlockedItem:
        return RecipeCollectionDatabaseBlockedItem(
            blocker_id=f"blocker:{item.recipe_index}:{_safe_token(reason)}",
            recipe_index=item.recipe_index,
            recipe_id=item.recipe_id,
            tool_key=item.tool_key,
            status=item.status,
            reason=reason,
            message=message,
            metadata=dict(metadata or {}),
        )

    def _collection_blocker(
        self,
        *,
        reason: str,
        message: str,
        metadata: Mapping[str, Any] | None = None,
    ) -> RecipeCollectionDatabaseBlockedItem:
        return RecipeCollectionDatabaseBlockedItem(
            blocker_id=f"blocker:collection:{_safe_token(reason)}",
            recipe_index=None,
            recipe_id=None,
            tool_key=None,
            status="blocked",
            reason=reason,
            message=message,
            metadata=dict(metadata or {}),
        )


def _source_metadata_entries(
    *,
    collection: ArtifactRecipeCollection,
    recipe: ArtifactRecipe,
    manifest: HistoricalCsvArtifactManifest,
    metadata_relpath: str,
) -> tuple[AnalysisMetadataEntry, ...]:
    return (
        AnalysisMetadataEntry(
            namespace="artifact",
            key="artifact_uid",
            value=manifest.identity.artifact_uid,
            value_type="string",
            label="Source artifact UID",
            searchable=True,
        ),
        AnalysisMetadataEntry(
            namespace="artifact",
            key="metadata_relpath",
            value=metadata_relpath,
            value_type="path",
            label="Source metadata sidecar relative path",
        ),
        AnalysisMetadataEntry(
            namespace="recipe_collection",
            key="collection_id",
            value=collection.collection_id,
            value_type="string",
            label="Source recipe collection ID",
            searchable=True,
        ),
        AnalysisMetadataEntry(
            namespace="artifact_recipe",
            key="recipe_id",
            value=recipe.recipe_id,
            value_type="string",
            label="Source artifact recipe ID",
            searchable=True,
        ),
    )


def _column_metadata_entries(
    *,
    recipe: ArtifactRecipe,
    artifact_column: ArtifactColumnMetadata | None,
) -> tuple[AnalysisMetadataEntry, ...]:
    entries = [
        AnalysisMetadataEntry(
            namespace="artifact_recipe",
            key="recipe_id",
            value=recipe.recipe_id,
            value_type="string",
            label="Source artifact recipe ID",
            searchable=True,
        )
    ]
    if artifact_column is not None:
        entries.append(
            AnalysisMetadataEntry(
                namespace="artifact",
                key="source_column_metadata",
                value=artifact_column.to_dict(),
                value_type="json",
                label="Source artifact column metadata",
            )
        )
    return tuple(entries)


def _column_is_analysis_selectable(column: ArtifactColumnMetadata) -> bool:
    if not bool(column.selectable):
        return False
    if column.analysis_usable is False:
        return False
    return True


def _duplicate_db_column_names(
    columns: Iterable[AnalysisDatabaseColumn],
) -> tuple[str, ...]:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for column in columns:
        name = str(column.db_column_name or "").strip()
        if not name:
            continue
        if name in seen:
            duplicates.add(name)
        seen.add(name)
    return tuple(sorted(duplicates))


def _blocked_reason_for_status(item: ArtifactRecoveryItemReport) -> str:
    if item.status == "missing":
        return "artifact_missing"
    if item.status == "stale":
        if any(_is_source_drift_reason(reason) for reason in item.stale_reasons):
            return "source_drift"
        return "artifact_stale"
    if item.status == "freshness_unknown":
        return "freshness_unknown"
    if item.status == "blocked":
        return "artifact_blocked"
    return "artifact_not_current"


def _blocked_message_for_status(item: ArtifactRecoveryItemReport) -> str:
    if item.status == "missing":
        return "Expected artifact is missing; run the update workflow before planning database components."
    if item.status == "stale":
        return "Expected artifact is stale; run the update workflow before planning database components."
    if item.status == "freshness_unknown":
        return "Expected artifact freshness is unknown; review or regenerate it before using it in a database plan."
    if item.status == "blocked":
        return "Expected artifact recovery is blocked; resolve blockers before using it in a database plan."
    return f"Expected artifact status is {item.status!r}, not current."


def _is_source_drift_reason(reason: str) -> bool:
    return "source_" in str(reason or "")


def _analysis_metadata_status(value: object) -> str:
    status = str(value or "unknown")
    return status if status in {"explicit", "inferred", "unknown", "not_applicable"} else "unknown"


def _plan_id(
    *,
    collection: ArtifactRecipeCollection,
    recovery_item_count: int,
) -> str:
    seed = "|".join(
        (
            collection.collection_id,
            collection.collection_hash,
            str(recovery_item_count),
            _utc_now(),
        )
    )
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:12]
    return f"rcdb_plan__{digest}"


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _safe_token(value: object) -> str:
    text = str(value or "").strip().lower()
    safe = "".join(char if char.isalnum() else "_" for char in text).strip("_")
    return safe or "item"


def _safe_stat(path: Path):
    try:
        return Path(path).stat()
    except OSError:
        return None


def _json_safe(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, Path):
        return value.as_posix()
    return value


__all__ = [
    "RecipeCollectionDatabaseBlockedItem",
    "RecipeCollectionDatabaseComponentPreview",
    "RecipeCollectionDatabasePlan",
    "RecipeCollectionDatabasePlanner",
    "RecipeCollectionDatabaseWarning",
]
