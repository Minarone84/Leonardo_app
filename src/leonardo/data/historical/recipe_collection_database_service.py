from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable, Literal, Mapping

from leonardo.data.naming import MarketId

from .analysis_database_component_editor import AnalysisDatabaseComponentEditor
from .analysis_database_contracts import (
    AnalysisDatabaseColumn,
    AnalysisDatabaseManifest,
    AnalysisFeatureSource,
    AnalysisMetadataEntry,
    market_from_dict,
    market_to_dict,
)
from .analysis_database_store import AnalysisDatabaseStore
from .analysis_dataset_geography import AnalysisDatasetGeographyPolicy
from .recipe_collection_database_planner import (
    RecipeCollectionDatabasePlan,
)

RecipeCollectionDatabaseApplyOperation = Literal["create", "extend"]
RecipeCollectionDatabaseApplyStatus = Literal["created", "extended", "blocked", "failed"]


@dataclass(frozen=True)
class RecipeCollectionDatabaseApplyWarning:
    """Non-blocking warning from recipe collection database application."""

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
class RecipeCollectionDatabaseApplyBlocker:
    """Blocking condition that prevented create or extend application."""

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
class RecipeCollectionDatabaseApplyReport:
    """JSON-safe result for recipe collection database create or extend."""

    report_id: str
    created_at_utc: str
    operation: RecipeCollectionDatabaseApplyOperation
    source_plan_id: str
    database_id: str | None
    display_name: str | None
    status: RecipeCollectionDatabaseApplyStatus
    added_source_count: int
    added_column_count: int
    skipped_component_count: int
    blockers: tuple[RecipeCollectionDatabaseApplyBlocker, ...]
    warnings: tuple[RecipeCollectionDatabaseApplyWarning, ...]
    geography_report: dict[str, Any] | None
    metadata: dict[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(self, "blockers", tuple(self.blockers))
        object.__setattr__(self, "warnings", tuple(self.warnings))
        object.__setattr__(self, "metadata", dict(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return {
            "report_id": self.report_id,
            "created_at_utc": self.created_at_utc,
            "operation": self.operation,
            "source_plan_id": self.source_plan_id,
            "database_id": self.database_id,
            "display_name": self.display_name,
            "status": self.status,
            "added_source_count": int(self.added_source_count),
            "added_column_count": int(self.added_column_count),
            "skipped_component_count": int(self.skipped_component_count),
            "blockers": [blocker.to_dict() for blocker in self.blockers],
            "warnings": [warning.to_dict() for warning in self.warnings],
            "geography_report": _json_safe(self.geography_report),
            "metadata": _json_safe(self.metadata),
        }


class RecipeCollectionDatabaseService:
    """
    Create or extend Analysis Database manifests from resolved collection plans.

    The service consumes read-only component plans produced by
    ``RecipeCollectionDatabasePlanner``. It persists Analysis Database
    manifests through ``AnalysisDatabaseStore`` and appends to existing
    manifests through ``AnalysisDatabaseComponentEditor``. It does not run
    artifact recovery, recipe execution, artifact calculation, dataframe
    materialization, or GUI workflows.
    """

    def __init__(
        self,
        *,
        historical_root: Path,
        store: AnalysisDatabaseStore | None = None,
        component_editor: AnalysisDatabaseComponentEditor | None = None,
        geography_policy: AnalysisDatasetGeographyPolicy | None = None,
    ) -> None:
        self._historical_root = Path(historical_root)
        self._store = store or AnalysisDatabaseStore(historical_root=self._historical_root)
        self._component_editor = component_editor or AnalysisDatabaseComponentEditor(
            historical_root=self._historical_root,
            store=self._store,
        )
        self._geography_policy = geography_policy or AnalysisDatasetGeographyPolicy()

    def create_database_from_plan(
        self,
        plan: RecipeCollectionDatabasePlan,
        *,
        display_name: str,
        description: str = "",
        include_raw_volume: bool | None = None,
        require_geography_complete: bool = False,
        overwrite: bool = False,
    ) -> RecipeCollectionDatabaseApplyReport:
        """
        Create a saved draft Analysis Database manifest from a resolved plan.

        Only resolved/current C2 component previews are converted into manifest
        feature components. Blocked C2 items are reported as skipped warnings and
        are never included in the saved manifest.
        """

        prepared = self._prepare_plan_components(plan)
        warnings = list(prepared.warnings)
        blockers = list(prepared.blockers)
        manifest: AnalysisDatabaseManifest | None = None
        geography_report: dict[str, Any] | None = None

        if prepared.market is not None and not blockers:
            include_volume = self._resolve_include_raw_volume(
                plan=plan,
                include_raw_volume=include_raw_volume,
                warnings=warnings,
            )
            try:
                manifest = self._store.build_draft_manifest(
                    market=prepared.market,
                    display_name=display_name,
                    user_description=description,
                    include_volume=include_volume,
                    feature_sources=prepared.sources,
                    feature_columns=prepared.columns,
                    metadata=_source_metadata_entries(plan),
                )
                geography_report = self._geography_policy.evaluate_manifest(manifest).to_dict()
                if require_geography_complete and not bool(
                    geography_report.get("complete")
                ):
                    blockers.append(
                        RecipeCollectionDatabaseApplyBlocker(
                            code="geography_incomplete",
                            message="Analysis Database geography is incomplete.",
                            metadata={
                                "missing_keys": geography_report.get("missing_keys", ()),
                            },
                        )
                    )
            except (TypeError, ValueError, FileExistsError) as exc:
                blockers.append(
                    RecipeCollectionDatabaseApplyBlocker(
                        code="manifest_build_failed",
                        message=str(exc),
                        metadata={"exception_type": type(exc).__name__},
                    )
                )

        if blockers:
            return self._report(
                operation="create",
                plan=plan,
                status="blocked",
                database_id=None if manifest is None else manifest.database_id,
                display_name=display_name,
                added_source_count=0,
                added_column_count=0,
                skipped_component_count=self._skipped_component_count(plan),
                blockers=blockers,
                warnings=warnings,
                geography_report=geography_report,
                metadata={"saved": False},
            )

        assert manifest is not None
        try:
            self._store.save_manifest(manifest, overwrite=overwrite)
        except (FileExistsError, ValueError) as exc:
            return self._report(
                operation="create",
                plan=plan,
                status="blocked",
                database_id=manifest.database_id,
                display_name=manifest.display_name,
                added_source_count=0,
                added_column_count=0,
                skipped_component_count=self._skipped_component_count(plan),
                blockers=(
                    RecipeCollectionDatabaseApplyBlocker(
                        code="manifest_save_blocked",
                        message=str(exc),
                        metadata={"exception_type": type(exc).__name__},
                    ),
                ),
                warnings=warnings,
                geography_report=geography_report,
                metadata={"saved": False},
            )

        return self._report(
            operation="create",
            plan=plan,
            status="created",
            database_id=manifest.database_id,
            display_name=manifest.display_name,
            added_source_count=len(prepared.sources),
            added_column_count=len(prepared.columns),
            skipped_component_count=self._skipped_component_count(plan),
            blockers=(),
            warnings=warnings,
            geography_report=geography_report,
            metadata={
                "saved": True,
                "manifest": manifest.to_dict(),
            },
        )

    def extend_database_from_plan(
        self,
        plan: RecipeCollectionDatabasePlan,
        *,
        database_id: str,
        require_geography_complete: bool = False,
    ) -> RecipeCollectionDatabaseApplyReport:
        """
        Append resolved plan components to an existing Analysis Database manifest.

        Existing feature components are preserved. The append is delegated to
        ``AnalysisDatabaseComponentEditor.add_components(...)`` so draft reset
        and stale dataframe removal remain owned by the component editor/store
        layer.
        """

        prepared = self._prepare_plan_components(plan)
        warnings = list(prepared.warnings)
        blockers = list(prepared.blockers)
        before: AnalysisDatabaseManifest | None = None
        geography_report: dict[str, Any] | None = None
        new_source_count = len(prepared.sources)

        if prepared.market is not None and not blockers:
            try:
                before = self._store.load_manifest(
                    market=prepared.market,
                    database_id=database_id,
                )
            except (FileNotFoundError, ValueError) as exc:
                other_market = self._market_for_database_id(database_id)
                if other_market is not None and other_market != prepared.market:
                    blockers.append(
                        RecipeCollectionDatabaseApplyBlocker(
                            code="market_mismatch",
                            message=(
                                "Existing database market does not match the "
                                "recipe collection plan market."
                            ),
                            metadata={
                                "database_id": database_id,
                                "database_market": market_to_dict(other_market),
                                "plan_market": market_to_dict(prepared.market),
                            },
                        )
                    )
                else:
                    blockers.append(
                        RecipeCollectionDatabaseApplyBlocker(
                            code="database_load_failed",
                            message=str(exc),
                            metadata={
                                "database_id": database_id,
                                "exception_type": type(exc).__name__,
                            },
                        )
                    )

        if before is not None and prepared.market is not None and not blockers:
            if before.market != prepared.market:
                blockers.append(
                    RecipeCollectionDatabaseApplyBlocker(
                        code="market_mismatch",
                        message="Existing database market does not match the recipe collection plan market.",
                        metadata={
                            "database_market": market_to_dict(before.market),
                            "plan_market": market_to_dict(prepared.market),
                        },
                    )
                )
            else:
                duplicate_existing = _duplicate_existing_column_names(
                    existing=before.feature_columns,
                    incoming=prepared.columns,
                )
                if duplicate_existing:
                    blockers.append(
                        RecipeCollectionDatabaseApplyBlocker(
                            code="duplicate_existing_db_columns",
                            message="Plan components would duplicate existing Analysis Database columns.",
                            metadata={"duplicate_columns": duplicate_existing},
                        )
                    )

        if before is not None and prepared.market is not None and not blockers:
            projected_sources = _merged_sources(
                existing=before.feature_sources,
                incoming=prepared.sources,
            )
            projected_columns = tuple(before.feature_columns) + tuple(prepared.columns)
            geography_report = self._geography_policy.evaluate_components(
                base_columns=before.base_columns,
                feature_sources=projected_sources,
                feature_columns=projected_columns,
                metadata={
                    "database_id": before.database_id,
                    "display_name": before.display_name,
                    "source_plan_id": plan.plan_id,
                },
            ).to_dict()
            if require_geography_complete and not bool(geography_report.get("complete")):
                blockers.append(
                    RecipeCollectionDatabaseApplyBlocker(
                        code="geography_incomplete",
                        message="Projected Analysis Database geography is incomplete.",
                        metadata={"missing_keys": geography_report.get("missing_keys", ())},
                    )
                )

        if blockers:
            return self._report(
                operation="extend",
                plan=plan,
                status="blocked",
                database_id=database_id,
                display_name=None if before is None else before.display_name,
                added_source_count=0,
                added_column_count=0,
                skipped_component_count=self._skipped_component_count(plan),
                blockers=blockers,
                warnings=warnings,
                geography_report=geography_report,
                metadata={"saved": False},
            )

        assert prepared.market is not None
        assert before is not None
        try:
            edit_report = self._component_editor.add_components(
                market=prepared.market,
                database_id=database_id,
                feature_sources=prepared.sources,
                feature_columns=prepared.columns,
            )
        except (TypeError, ValueError, FileNotFoundError) as exc:
            return self._report(
                operation="extend",
                plan=plan,
                status="blocked",
                database_id=database_id,
                display_name=before.display_name,
                added_source_count=0,
                added_column_count=0,
                skipped_component_count=self._skipped_component_count(plan),
                blockers=(
                    RecipeCollectionDatabaseApplyBlocker(
                        code="component_append_blocked",
                        message=str(exc),
                        metadata={"exception_type": type(exc).__name__},
                    ),
                ),
                warnings=warnings,
                geography_report=geography_report,
                metadata={"saved": False},
            )

        updated = edit_report.manifest
        geography_report = self._geography_policy.evaluate_manifest(updated).to_dict()
        existing_source_ids = {source.source_id for source in before.feature_sources}
        new_source_count = sum(
            1 for source in prepared.sources if source.source_id not in existing_source_ids
        )
        return self._report(
            operation="extend",
            plan=plan,
            status="extended",
            database_id=updated.database_id,
            display_name=updated.display_name,
            added_source_count=new_source_count,
            added_column_count=len(prepared.columns),
            skipped_component_count=self._skipped_component_count(plan),
            blockers=(),
            warnings=warnings,
            geography_report=geography_report,
            metadata={
                "saved": True,
                "component_edit_report": edit_report.to_dict(),
            },
        )

    def _prepare_plan_components(
        self,
        plan: RecipeCollectionDatabasePlan,
    ) -> "_PreparedPlanComponents":
        if not isinstance(plan, RecipeCollectionDatabasePlan):
            raise TypeError(
                "RecipeCollectionDatabaseService expects a RecipeCollectionDatabasePlan"
            )

        blockers: list[RecipeCollectionDatabaseApplyBlocker] = []
        warnings: list[RecipeCollectionDatabaseApplyWarning] = []
        market = _market_from_plan(plan)
        if market is None:
            blockers.append(
                RecipeCollectionDatabaseApplyBlocker(
                    code="missing_plan_market",
                    message="Recipe collection database plan is missing market identity.",
                    metadata={"plan_id": plan.plan_id},
                )
            )

        if plan.duplicate_columns:
            blockers.append(
                RecipeCollectionDatabaseApplyBlocker(
                    code="duplicate_planned_columns",
                    message="Recipe collection plan contains duplicate planned database columns.",
                    metadata={"duplicate_columns": plan.duplicate_columns},
                )
            )

        if not plan.resolved_components:
            blockers.append(
                RecipeCollectionDatabaseApplyBlocker(
                    code="no_resolved_components",
                    message="Recipe collection plan has no resolved current artifacts to apply.",
                    metadata={
                        "blocked_item_count": len(plan.blocked_items),
                        "warning_count": len(plan.warnings),
                    },
                )
            )

        if plan.blocked_items:
            warnings.append(
                RecipeCollectionDatabaseApplyWarning(
                    code="blocked_plan_items_skipped",
                    message="Blocked recipe collection plan items were skipped.",
                    metadata={
                        "blocked_item_count": len(plan.blocked_items),
                        "blocked_items": [item.to_dict() for item in plan.blocked_items],
                    },
                )
            )

        sources: list[AnalysisFeatureSource] = []
        columns: list[AnalysisDatabaseColumn] = []
        source_ids_seen: set[str] = set()
        for component in plan.resolved_components:
            try:
                source = AnalysisFeatureSource.from_dict(dict(component.source_preview))
                component_columns = tuple(
                    AnalysisDatabaseColumn.from_dict(dict(column))
                    for column in component.column_previews
                )
            except (TypeError, ValueError) as exc:
                blockers.append(
                    RecipeCollectionDatabaseApplyBlocker(
                        code="component_preview_invalid",
                        message=str(exc),
                        metadata={
                            "component_id": component.component_id,
                            "recipe_id": component.recipe_id,
                            "exception_type": type(exc).__name__,
                        },
                    )
                )
                continue

            if not component_columns:
                blockers.append(
                    RecipeCollectionDatabaseApplyBlocker(
                        code="component_columns_missing",
                        message="Resolved component has no column previews.",
                        metadata={"component_id": component.component_id},
                    )
                )
                continue

            if source.source_id not in source_ids_seen:
                sources.append(source)
                source_ids_seen.add(source.source_id)
            columns.extend(component_columns)

        duplicate_converted = _duplicate_column_names(columns)
        if duplicate_converted:
            blockers.append(
                RecipeCollectionDatabaseApplyBlocker(
                    code="duplicate_converted_columns",
                    message="Converted component previews contain duplicate database columns.",
                    metadata={"duplicate_columns": duplicate_converted},
                )
            )

        return _PreparedPlanComponents(
            market=market,
            sources=tuple(sources),
            columns=tuple(columns),
            blockers=tuple(blockers),
            warnings=tuple(warnings),
        )

    def _resolve_include_raw_volume(
        self,
        *,
        plan: RecipeCollectionDatabasePlan,
        include_raw_volume: bool | None,
        warnings: list[RecipeCollectionDatabaseApplyWarning],
    ) -> bool:
        volume_artifact_present = _plan_has_volume_artifact(plan)
        if include_raw_volume is None:
            if volume_artifact_present:
                warnings.append(
                    RecipeCollectionDatabaseApplyWarning(
                        code="raw_volume_omitted_due_to_volume_artifact",
                        message=(
                            "Raw OHLCV volume was omitted because the plan "
                            "contains an explicit Volume artifact."
                        ),
                        metadata={"volume_artifact_present": True},
                    )
                )
                return False
            warnings.append(
                RecipeCollectionDatabaseApplyWarning(
                    code="raw_volume_included_without_volume_artifact",
                    message=(
                        "Raw OHLCV volume was included because the plan does "
                        "not contain an explicit Volume artifact."
                    ),
                    metadata={"volume_artifact_present": False},
                )
            )
            return True
        if bool(include_raw_volume) and volume_artifact_present:
            warnings.append(
                RecipeCollectionDatabaseApplyWarning(
                    code="raw_volume_requested_with_volume_artifact",
                    message=(
                        "Raw OHLCV volume was explicitly requested while the "
                        "plan contains an explicit Volume artifact."
                    ),
                    metadata={"volume_artifact_present": True},
                )
            )
        return bool(include_raw_volume)

    def _skipped_component_count(self, plan: RecipeCollectionDatabasePlan) -> int:
        return len(plan.blocked_items)

    def _market_for_database_id(self, database_id: str) -> MarketId | None:
        for summary in self._store.list_databases():
            if summary.database_id == database_id:
                return summary.market
        return None

    def _report(
        self,
        *,
        operation: RecipeCollectionDatabaseApplyOperation,
        plan: RecipeCollectionDatabasePlan,
        status: RecipeCollectionDatabaseApplyStatus,
        database_id: str | None,
        display_name: str | None,
        added_source_count: int,
        added_column_count: int,
        skipped_component_count: int,
        blockers: Iterable[RecipeCollectionDatabaseApplyBlocker],
        warnings: Iterable[RecipeCollectionDatabaseApplyWarning],
        geography_report: dict[str, Any] | None,
        metadata: Mapping[str, Any] | None = None,
    ) -> RecipeCollectionDatabaseApplyReport:
        return RecipeCollectionDatabaseApplyReport(
            report_id=_report_id(operation=operation, plan_id=plan.plan_id),
            created_at_utc=_utc_now(),
            operation=operation,
            source_plan_id=plan.plan_id,
            database_id=database_id,
            display_name=display_name,
            status=status,
            added_source_count=added_source_count,
            added_column_count=added_column_count,
            skipped_component_count=skipped_component_count,
            blockers=tuple(blockers),
            warnings=tuple(warnings),
            geography_report=geography_report,
            metadata={
                "collection_id": plan.collection_id,
                "collection_display_name": plan.collection_display_name,
                "source_database_id": plan.source_database_id,
                **dict(metadata or {}),
            },
        )


@dataclass(frozen=True)
class _PreparedPlanComponents:
    market: MarketId | None
    sources: tuple[AnalysisFeatureSource, ...]
    columns: tuple[AnalysisDatabaseColumn, ...]
    blockers: tuple[RecipeCollectionDatabaseApplyBlocker, ...]
    warnings: tuple[RecipeCollectionDatabaseApplyWarning, ...]


def _source_metadata_entries(
    plan: RecipeCollectionDatabasePlan,
) -> tuple[AnalysisMetadataEntry, ...]:
    collection_hash = str(plan.metadata.get("collection_hash", "") or "")
    collection_hash_short = str(plan.metadata.get("collection_hash_short", "") or "")
    entries: list[AnalysisMetadataEntry] = [
        AnalysisMetadataEntry(
            namespace="recipe_collection_database",
            key="source_plan_id",
            value=plan.plan_id,
            value_type="string",
            label="Source recipe collection database plan ID",
            searchable=True,
        ),
        AnalysisMetadataEntry(
            namespace="recipe_collection",
            key="collection_id",
            value=plan.collection_id,
            value_type="string",
            label="Source recipe collection ID",
            searchable=True,
        ),
        AnalysisMetadataEntry(
            namespace="recipe_collection",
            key="collection_display_name",
            value=plan.collection_display_name,
            value_type="string",
            label="Source recipe collection display name",
        ),
    ]
    if collection_hash:
        entries.append(
            AnalysisMetadataEntry(
                namespace="recipe_collection",
                key="collection_hash",
                value=collection_hash,
                value_type="string",
                label="Source recipe collection hash",
            )
        )
    if collection_hash_short:
        entries.append(
            AnalysisMetadataEntry(
                namespace="recipe_collection",
                key="collection_hash_short",
                value=collection_hash_short,
                value_type="string",
                label="Source recipe collection hash short",
            )
        )
    if plan.source_database_id:
        entries.append(
            AnalysisMetadataEntry(
                namespace="recipe_collection",
                key="source_database_id",
                value=plan.source_database_id,
                value_type="string",
                label="Source database ID linked by collection",
                searchable=True,
            )
        )
    return tuple(entries)


def _market_from_plan(plan: RecipeCollectionDatabasePlan) -> MarketId | None:
    if plan.market is None:
        return None
    try:
        return market_from_dict(dict(plan.market))
    except Exception:
        return None


def _plan_has_volume_artifact(plan: RecipeCollectionDatabasePlan) -> bool:
    geography_report = plan.geography_report or {}
    if bool(geography_report.get("volume_artifact_present")):
        return True
    present_keys = {
        str(key)
        for key in geography_report.get("present_keys", ()) or ()
    }
    if "volume_artifact" in present_keys:
        return True
    return any(
        component.tool_key == "volume" and component.storage_family == "oscillators"
        for component in plan.resolved_components
    )


def _duplicate_existing_column_names(
    *,
    existing: Iterable[AnalysisDatabaseColumn],
    incoming: Iterable[AnalysisDatabaseColumn],
) -> tuple[str, ...]:
    existing_names = {
        str(column.db_column_name or "").strip()
        for column in existing
        if str(column.db_column_name or "").strip()
    }
    duplicates = sorted(
        {
            str(column.db_column_name or "").strip()
            for column in incoming
            if str(column.db_column_name or "").strip() in existing_names
        }
    )
    return tuple(duplicates)


def _duplicate_column_names(
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


def _merged_sources(
    *,
    existing: Iterable[AnalysisFeatureSource],
    incoming: Iterable[AnalysisFeatureSource],
) -> tuple[AnalysisFeatureSource, ...]:
    sources: dict[str, AnalysisFeatureSource] = {}
    for source in existing:
        sources[source.source_id] = source
    for source in incoming:
        sources.setdefault(source.source_id, source)
    return tuple(sources.values())


def _report_id(*, operation: str, plan_id: str) -> str:
    seed = f"{operation}|{plan_id}|{_utc_now()}"
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:12]
    return f"rcdb_apply__{digest}"


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _json_safe(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, Path):
        return value.as_posix()
    return value


__all__ = [
    "RecipeCollectionDatabaseApplyBlocker",
    "RecipeCollectionDatabaseApplyReport",
    "RecipeCollectionDatabaseApplyWarning",
    "RecipeCollectionDatabaseService",
]
