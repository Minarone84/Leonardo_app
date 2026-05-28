from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import time
from typing import Any, Iterable, Literal, Mapping

import pandas as pd

from leonardo.data.historical.analysis_database_contracts import (
    AnalysisDatabaseManifest,
    market_from_dict as analysis_market_from_dict,
    market_to_dict as analysis_market_to_dict,
)
from leonardo.data.historical.analysis_database_store import AnalysisDatabaseStore
from leonardo.data.historical.artifact_metadata_contracts import (
    HistoricalCsvArtifactManifest,
)
from leonardo.data.historical.artifact_metadata_naming import (
    format_ts_ms_utc,
    metadata_path_for_csv,
)
from leonardo.data.historical.artifact_recipe_collection_store import (
    ArtifactRecipeCollection,
    ArtifactRecipeCollectionStore,
)
from leonardo.data.historical.artifact_recipe_store import (
    ARTIFACT_RECIPE_METADATA_NAMESPACE,
    ArtifactRecipe,
    ArtifactRecipeStore,
    market_to_dict as recipe_market_to_dict,
)
from leonardo.data.historical.artifact_recovery_planner import (
    ArtifactRecoveryItemReport,
    ArtifactRecoveryPlanner,
)
from leonardo.data.historical.artifact_recovery_regenerator import (
    ArtifactRecoveryRegenerator,
)
from leonardo.data.historical.derived_store_csv import DerivedCsvStore
from leonardo.data.historical.paths import HistoricalPaths
from leonardo.data.historical.source_ohlcv_provenance import (
    SourceOhlcvDriftReport,
    build_source_ohlcv_drift_report,
    extract_source_ohlcv_snapshot,
)
from leonardo.data.naming import MarketId, canonicalize


SelectedArtifactStatus = Literal["current", "old", "unknown", "blocked", "error"]
SelectedDatabaseStatus = Literal[
    "current",
    "old",
    "draft",
    "unknown",
    "blocked",
    "error",
]
SelectedUpdateItemType = Literal["artifact", "analysis_database"]
SelectedUpdateActionType = Literal["regenerate_artifact", "rebuild_analysis_database"]
SelectedUpdateResultStatus = Literal["completed", "skipped", "failed", "blocked"]


@dataclass(frozen=True)
class SelectedArtifactUpdateRef:
    """Reference to one saved derived artifact selected for update planning."""

    family: str
    exchange: str
    market_type: str
    symbol: str
    timeframe: str
    artifact_path: str | Path | None = None
    tool_key: str | None = None
    instance_key: str | None = None
    recipe_id: str | None = None
    display_name: str | None = None

    @property
    def market(self) -> MarketId:
        return canonicalize(
            self.exchange,
            self.market_type,
            self.symbol,
            self.timeframe,
        )


@dataclass(frozen=True)
class SelectedAnalysisDatabaseUpdateRef:
    """Reference to one existing Analysis Database selected for update planning."""

    exchange: str
    market_type: str
    symbol: str
    timeframe: str
    database_id: str
    display_name: str | None = None

    @property
    def market(self) -> MarketId:
        return canonicalize(
            self.exchange,
            self.market_type,
            self.symbol,
            self.timeframe,
        )


@dataclass(frozen=True)
class SelectedUpdateAction:
    """Executable action emitted by a selected-item update plan."""

    action_id: str
    action_type: SelectedUpdateActionType
    item_id: str
    item_type: SelectedUpdateItemType
    label: str
    reason: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return {
            "action_id": self.action_id,
            "action_type": self.action_type,
            "item_id": self.item_id,
            "item_type": self.item_type,
            "label": self.label,
            "reason": self.reason,
            "metadata": _json_safe(self.metadata),
        }


@dataclass(frozen=True)
class SelectedArtifactUpdatePlanItem:
    """Read-only update status for one selected saved artifact."""

    item_id: str
    family: str
    display_name: str
    status: SelectedArtifactStatus
    actionable: bool
    reason: str
    warnings: tuple[str, ...] = ()
    blockers: tuple[str, ...] = ()
    recipe_id: str | None = None
    recipe_hash: str | None = None
    recipe_hash_short: str | None = None
    expected_action_label: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return {
            "item_id": self.item_id,
            "family": self.family,
            "display_name": self.display_name,
            "status": self.status,
            "actionable": bool(self.actionable),
            "reason": self.reason,
            "warnings": list(self.warnings),
            "blockers": list(self.blockers),
            "recipe_id": self.recipe_id,
            "recipe_hash": self.recipe_hash,
            "recipe_hash_short": self.recipe_hash_short,
            "expected_action_label": self.expected_action_label,
            "metadata": _json_safe(self.metadata),
        }


@dataclass(frozen=True)
class SelectedDatabaseUpdatePlanItem:
    """Read-only update status for one selected Analysis Database."""

    item_id: str
    database_id: str
    display_name: str
    status: SelectedDatabaseStatus
    actionable: bool
    reason: str
    warnings: tuple[str, ...] = ()
    blockers: tuple[str, ...] = ()
    materialized: bool = False
    expected_action_label: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return {
            "item_id": self.item_id,
            "database_id": self.database_id,
            "display_name": self.display_name,
            "status": self.status,
            "actionable": bool(self.actionable),
            "reason": self.reason,
            "warnings": list(self.warnings),
            "blockers": list(self.blockers),
            "materialized": bool(self.materialized),
            "expected_action_label": self.expected_action_label,
            "metadata": _json_safe(self.metadata),
        }


@dataclass(frozen=True)
class SelectedArtifactUpdatePlan:
    """Read-only update plan for selected saved artifacts."""

    plan_id: str
    created_at_utc: str
    items: tuple[SelectedArtifactUpdatePlanItem, ...]
    actions: tuple[SelectedUpdateAction, ...]
    warnings: tuple[str, ...]
    blockers: tuple[str, ...]
    summary: dict[str, int]

    def to_dict(self) -> dict[str, object]:
        return {
            "plan_id": self.plan_id,
            "created_at_utc": self.created_at_utc,
            "items": [item.to_dict() for item in self.items],
            "actions": [action.to_dict() for action in self.actions],
            "warnings": list(self.warnings),
            "blockers": list(self.blockers),
            "summary": dict(self.summary),
        }


@dataclass(frozen=True)
class SelectedDatabaseUpdatePlan:
    """Read-only update plan for selected Analysis Databases."""

    plan_id: str
    created_at_utc: str
    items: tuple[SelectedDatabaseUpdatePlanItem, ...]
    actions: tuple[SelectedUpdateAction, ...]
    warnings: tuple[str, ...]
    blockers: tuple[str, ...]
    summary: dict[str, int]

    def to_dict(self) -> dict[str, object]:
        return {
            "plan_id": self.plan_id,
            "created_at_utc": self.created_at_utc,
            "items": [item.to_dict() for item in self.items],
            "actions": [action.to_dict() for action in self.actions],
            "warnings": list(self.warnings),
            "blockers": list(self.blockers),
            "summary": dict(self.summary),
        }


@dataclass(frozen=True)
class SelectedUpdateExecutionItemResult:
    """Execution outcome for one selected update action."""

    action_id: str
    action_type: str
    item_id: str
    status: SelectedUpdateResultStatus
    message: str
    started_at_utc: str
    finished_at_utc: str
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return {
            "action_id": self.action_id,
            "action_type": self.action_type,
            "item_id": self.item_id,
            "status": self.status,
            "message": self.message,
            "started_at_utc": self.started_at_utc,
            "finished_at_utc": self.finished_at_utc,
            "error": self.error,
            "metadata": _json_safe(self.metadata),
        }


@dataclass(frozen=True)
class SelectedUpdateExecutionReport:
    """Structured report for selected-item update execution."""

    report_id: str
    plan_id: str
    started_at_utc: str
    finished_at_utc: str
    requested_action_ids: tuple[str, ...]
    completed_action_ids: tuple[str, ...]
    skipped_action_ids: tuple[str, ...]
    failed_action_ids: tuple[str, ...]
    blocked_action_ids: tuple[str, ...]
    results: tuple[SelectedUpdateExecutionItemResult, ...]
    summary: dict[str, int]

    def to_dict(self) -> dict[str, object]:
        return {
            "report_id": self.report_id,
            "plan_id": self.plan_id,
            "started_at_utc": self.started_at_utc,
            "finished_at_utc": self.finished_at_utc,
            "requested_action_ids": list(self.requested_action_ids),
            "completed_action_ids": list(self.completed_action_ids),
            "skipped_action_ids": list(self.skipped_action_ids),
            "failed_action_ids": list(self.failed_action_ids),
            "blocked_action_ids": list(self.blocked_action_ids),
            "results": [result.to_dict() for result in self.results],
            "summary": dict(self.summary),
        }


class DataManagerSelectedUpdateService:
    """
    Plan and execute Data Manager updates for explicitly selected items.

    The service is data-layer orchestration only. Artifact status delegates to
    ``ArtifactRecoveryPlanner`` and artifact execution delegates to
    ``ArtifactRecoveryRegenerator``. Analysis Database rebuilds delegate to
    ``AnalysisDatabaseStore.materialize_database``. The service does not own GUI
    state, raw OHLCV repair, recipe-collection workflows, or low-level CSV/JSON
    writes.
    """

    def __init__(
        self,
        *,
        historical_root: Path,
        recipe_store: ArtifactRecipeStore | None = None,
        collection_store: ArtifactRecipeCollectionStore | None = None,
        recovery_planner: ArtifactRecoveryPlanner | None = None,
        recovery_regenerator: ArtifactRecoveryRegenerator | None = None,
        analysis_store: AnalysisDatabaseStore | None = None,
    ) -> None:
        self._historical_root = Path(historical_root)
        self._paths = HistoricalPaths(root=self._historical_root)
        self._recipe_store = recipe_store or ArtifactRecipeStore(
            historical_root=self._historical_root,
        )
        self._collection_store = collection_store or ArtifactRecipeCollectionStore(
            historical_root=self._historical_root,
        )
        self._recovery_planner = recovery_planner or ArtifactRecoveryPlanner(
            historical_root=self._historical_root,
            collection_store=self._collection_store,
        )
        self._recovery_regenerator = (
            recovery_regenerator
            or ArtifactRecoveryRegenerator(
                historical_root=self._historical_root,
                planner=self._recovery_planner,
                collection_store=self._collection_store,
            )
        )
        self._analysis_store = analysis_store or AnalysisDatabaseStore(
            historical_root=self._historical_root,
        )
        self._derived_store = DerivedCsvStore(historical_root=self._historical_root)

    def plan_artifact_updates(
        self,
        refs: Iterable[SelectedArtifactUpdateRef],
    ) -> SelectedArtifactUpdatePlan:
        """Build a read-only update plan for selected saved artifacts."""
        items: list[SelectedArtifactUpdatePlanItem] = []
        actions: list[SelectedUpdateAction] = []
        warnings: list[str] = []
        blockers: list[str] = []

        for index, ref in enumerate(refs):
            item, action = self._plan_one_artifact(ref=ref, index=index)
            items.append(item)
            warnings.extend(item.warnings)
            blockers.extend(item.blockers)
            if action is not None:
                actions.append(action)

        plan_id = f"selected_artifacts:{int(time.time() * 1000)}"
        return SelectedArtifactUpdatePlan(
            plan_id=plan_id,
            created_at_utc=_utc_now(),
            items=tuple(items),
            actions=tuple(actions),
            warnings=tuple(warnings),
            blockers=tuple(blockers),
            summary=_artifact_summary(items=items, actions=actions),
        )

    def execute_artifact_update_plan(
        self,
        plan: SelectedArtifactUpdatePlan,
        *,
        selected_action_ids: Iterable[str] | None = None,
    ) -> SelectedUpdateExecutionReport:
        """Execute selected actionable stale-artifact actions sequentially."""
        requested = _requested_action_ids(
            actions=plan.actions,
            selected_action_ids=selected_action_ids,
        )
        action_by_id = {action.action_id: action for action in plan.actions}
        item_by_id = {item.item_id: item for item in plan.items}
        started = _utc_now()
        results: list[SelectedUpdateExecutionItemResult] = []

        for action_id in requested:
            action = action_by_id.get(action_id)
            if action is None:
                results.append(_unknown_action_result(action_id=action_id))
                continue
            item = item_by_id.get(action.item_id)
            if item is None:
                results.append(
                    _skipped_result(
                        action=action,
                        message="Action target item is not present in the plan.",
                        reason="missing_plan_item",
                    )
                )
                continue
            if item.status != "old" or not item.actionable:
                results.append(
                    _skipped_result(
                        action=action,
                        message="Selected artifact is not an actionable old item.",
                        reason="not_actionable_old_artifact",
                    )
                )
                continue
            results.append(self._execute_artifact_action(action=action))

        finished = _utc_now()
        return _execution_report(
            plan_id=plan.plan_id,
            started_at_utc=started,
            finished_at_utc=finished,
            requested_action_ids=requested,
            results=results,
        )

    def plan_database_updates(
        self,
        refs: Iterable[SelectedAnalysisDatabaseUpdateRef],
    ) -> SelectedDatabaseUpdatePlan:
        """Build a read-only update plan for selected Analysis Databases."""
        items: list[SelectedDatabaseUpdatePlanItem] = []
        actions: list[SelectedUpdateAction] = []
        warnings: list[str] = []
        blockers: list[str] = []

        for index, ref in enumerate(refs):
            item, action = self._plan_one_database(ref=ref, index=index)
            items.append(item)
            warnings.extend(item.warnings)
            blockers.extend(item.blockers)
            if action is not None:
                actions.append(action)

        plan_id = f"selected_databases:{int(time.time() * 1000)}"
        return SelectedDatabaseUpdatePlan(
            plan_id=plan_id,
            created_at_utc=_utc_now(),
            items=tuple(items),
            actions=tuple(actions),
            warnings=tuple(warnings),
            blockers=tuple(blockers),
            summary=_database_summary(items=items, actions=actions),
        )

    def execute_database_update_plan(
        self,
        plan: SelectedDatabaseUpdatePlan,
        *,
        selected_action_ids: Iterable[str] | None = None,
    ) -> SelectedUpdateExecutionReport:
        """Execute selected actionable stale-database rebuilds sequentially."""
        requested = _requested_action_ids(
            actions=plan.actions,
            selected_action_ids=selected_action_ids,
        )
        action_by_id = {action.action_id: action for action in plan.actions}
        item_by_id = {item.item_id: item for item in plan.items}
        started = _utc_now()
        results: list[SelectedUpdateExecutionItemResult] = []

        for action_id in requested:
            action = action_by_id.get(action_id)
            if action is None:
                results.append(_unknown_action_result(action_id=action_id))
                continue
            item = item_by_id.get(action.item_id)
            if item is None:
                results.append(
                    _skipped_result(
                        action=action,
                        message="Action target item is not present in the plan.",
                        reason="missing_plan_item",
                    )
                )
                continue
            if item.status != "old" or not item.actionable:
                results.append(
                    _skipped_result(
                        action=action,
                        message="Selected Analysis Database is not an actionable old item.",
                        reason="not_actionable_old_database",
                    )
                )
                continue
            results.append(self._execute_database_action(action=action))

        finished = _utc_now()
        return _execution_report(
            plan_id=plan.plan_id,
            started_at_utc=started,
            finished_at_utc=finished,
            requested_action_ids=requested,
            results=results,
        )

    def _plan_one_artifact(
        self,
        *,
        ref: SelectedArtifactUpdateRef,
        index: int,
    ) -> tuple[SelectedArtifactUpdatePlanItem, SelectedUpdateAction | None]:
        try:
            return self._plan_one_artifact_inner(ref=ref, index=index)
        except Exception as exc:
            item_id = _artifact_item_id(ref=ref, index=index)
            item = SelectedArtifactUpdatePlanItem(
                item_id=item_id,
                family=str(ref.family or ""),
                display_name=_artifact_display_name(ref=ref, item_id=item_id),
                status="error",
                actionable=False,
                reason=f"Artifact update planning failed: {type(exc).__name__}: {exc}",
                metadata={"error": f"{type(exc).__name__}: {exc}"},
            )
            return item, None

    def _plan_one_artifact_inner(
        self,
        *,
        ref: SelectedArtifactUpdateRef,
        index: int,
    ) -> tuple[SelectedArtifactUpdatePlanItem, SelectedUpdateAction | None]:
        market = ref.market
        kind = _artifact_kind(ref.family)
        item_id = _artifact_item_id(ref=ref, index=index)
        artifact_path = self._resolve_artifact_path(ref=ref, kind=kind, market=market)
        metadata_path = None if artifact_path is None else metadata_path_for_csv(artifact_path)
        display_name = _artifact_display_name(ref=ref, item_id=item_id)

        if artifact_path is None:
            item = SelectedArtifactUpdatePlanItem(
                item_id=item_id,
                family=kind,
                display_name=display_name,
                status="unknown",
                actionable=False,
                reason="Selected artifact reference does not include an artifact path or instance key.",
                warnings=("Artifact path could not be resolved from the selected reference.",),
            )
            return item, None

        if not artifact_path.exists():
            item = SelectedArtifactUpdatePlanItem(
                item_id=item_id,
                family=kind,
                display_name=display_name,
                status="blocked",
                actionable=False,
                reason="Selected artifact CSV is missing.",
                blockers=(f"Selected artifact CSV was not found: {artifact_path}",),
                metadata={"artifact_path": artifact_path},
            )
            return item, None

        manifest = self._derived_store.load_metadata_manifest(artifact_path)
        recipe_id = _metadata_value(
            manifest,
            namespace=ARTIFACT_RECIPE_METADATA_NAMESPACE,
            key="recipe_id",
        ) or _clean_optional(ref.recipe_id)
        recipe_hash = _metadata_value(
            manifest,
            namespace=ARTIFACT_RECIPE_METADATA_NAMESPACE,
            key="recipe_hash",
        )
        recipe_hash_short = _metadata_value(
            manifest,
            namespace=ARTIFACT_RECIPE_METADATA_NAMESPACE,
            key="recipe_hash_short",
        )

        if recipe_id is None:
            item = SelectedArtifactUpdatePlanItem(
                item_id=item_id,
                family=kind,
                display_name=display_name,
                status="unknown",
                actionable=False,
                reason="Selected artifact does not record reusable recipe metadata.",
                warnings=("Missing artifact_recipe.recipe_id metadata.",),
                metadata={
                    "artifact_path": artifact_path,
                    "metadata_path": metadata_path,
                    "metadata_present": manifest is not None,
                },
            )
            return item, None

        try:
            recipe = self._recipe_store.load_recipe(market=market, recipe_id=recipe_id)
        except Exception as exc:
            item = SelectedArtifactUpdatePlanItem(
                item_id=item_id,
                family=kind,
                display_name=display_name,
                status="blocked",
                actionable=False,
                reason="Reusable recipe for selected artifact could not be loaded.",
                blockers=(
                    f"Artifact recipe {recipe_id!r} could not be loaded: {type(exc).__name__}: {exc}",
                ),
                recipe_id=recipe_id,
                recipe_hash=recipe_hash,
                recipe_hash_short=recipe_hash_short,
                metadata={
                    "artifact_path": artifact_path,
                    "metadata_path": metadata_path,
                },
            )
            return item, None

        mismatch_blockers = self._artifact_identity_blockers(
            ref=ref,
            kind=kind,
            manifest=manifest,
            recipe=recipe,
            recipe_hash=recipe_hash,
            artifact_path=artifact_path,
        )
        if mismatch_blockers:
            item = SelectedArtifactUpdatePlanItem(
                item_id=item_id,
                family=kind,
                display_name=display_name,
                status="blocked",
                actionable=False,
                reason="Selected artifact identity does not match its reusable recipe.",
                blockers=mismatch_blockers,
                recipe_id=recipe.recipe_id,
                recipe_hash=recipe_hash or recipe.recipe_hash,
                recipe_hash_short=recipe_hash_short or recipe.recipe_hash_short,
                metadata={
                    "artifact_path": artifact_path,
                    "metadata_path": metadata_path,
                },
            )
            return item, None

        collection = self._collection_for_recipes(market=market, recipes=(recipe,))
        recovery_report = self._recovery_planner.plan_collection(collection)
        recovery_item = recovery_report.items[0]
        expected_path = Path(recovery_item.expected_csv_path)
        if not _same_path(artifact_path, expected_path):
            blocker = (
                "Selected artifact path does not match the reusable recipe's expected output path: "
                f"selected={artifact_path}; expected={expected_path}"
            )
            item = SelectedArtifactUpdatePlanItem(
                item_id=item_id,
                family=kind,
                display_name=display_name,
                status="blocked",
                actionable=False,
                reason="Selected artifact path does not match recipe output.",
                blockers=(blocker,),
                recipe_id=recipe.recipe_id,
                recipe_hash=recipe.recipe_hash,
                recipe_hash_short=recipe.recipe_hash_short,
                metadata=_recovery_metadata(
                    recovery_item=recovery_item,
                    artifact_path=artifact_path,
                    metadata_path=metadata_path,
                    recovery_report=recovery_report.to_dict(),
                ),
            )
            return item, None

        status, actionable, reason, warnings, blockers = _artifact_status_from_recovery(
            recovery_item,
        )
        item = SelectedArtifactUpdatePlanItem(
            item_id=item_id,
            family=kind,
            display_name=display_name or recovery_item.display_name,
            status=status,
            actionable=actionable,
            reason=reason,
            warnings=warnings,
            blockers=blockers,
            recipe_id=recipe.recipe_id,
            recipe_hash=recipe.recipe_hash,
            recipe_hash_short=recipe.recipe_hash_short,
            expected_action_label=(
                f"Regenerate {recovery_item.display_name}" if actionable else None
            ),
            metadata=_recovery_metadata(
                recovery_item=recovery_item,
                artifact_path=artifact_path,
                metadata_path=metadata_path,
                recovery_report=recovery_report.to_dict(),
            ),
        )
        action = None
        if item.status == "old" and item.actionable:
            action = SelectedUpdateAction(
                action_id=f"regenerate_artifact:{recipe.recipe_id}",
                action_type="regenerate_artifact",
                item_id=item.item_id,
                item_type="artifact",
                label=f"Regenerate {recovery_item.display_name}",
                reason=reason,
                metadata={
                    "market": recipe_market_to_dict(market),
                    "recipe_id": recipe.recipe_id,
                    "recipe_hash": recipe.recipe_hash,
                    "recipe_hash_short": recipe.recipe_hash_short,
                    "tool_type": recipe.tool_type,
                    "tool_key": recipe.tool_key,
                },
            )
        return item, action

    def _plan_one_database(
        self,
        *,
        ref: SelectedAnalysisDatabaseUpdateRef,
        index: int,
    ) -> tuple[SelectedDatabaseUpdatePlanItem, SelectedUpdateAction | None]:
        try:
            return self._plan_one_database_inner(ref=ref, index=index)
        except Exception as exc:
            item_id = _database_item_id(ref=ref, index=index)
            database_id = str(ref.database_id or "").strip()
            item = SelectedDatabaseUpdatePlanItem(
                item_id=item_id,
                database_id=database_id,
                display_name=str(ref.display_name or database_id or item_id),
                status="error",
                actionable=False,
                reason=f"Analysis Database update planning failed: {type(exc).__name__}: {exc}",
                metadata={"error": f"{type(exc).__name__}: {exc}"},
            )
            return item, None

    def _plan_one_database_inner(
        self,
        *,
        ref: SelectedAnalysisDatabaseUpdateRef,
        index: int,
    ) -> tuple[SelectedDatabaseUpdatePlanItem, SelectedUpdateAction | None]:
        market = ref.market
        database_id = str(ref.database_id or "").strip()
        item_id = _database_item_id(ref=ref, index=index)
        if not database_id:
            item = SelectedDatabaseUpdatePlanItem(
                item_id=item_id,
                database_id="",
                display_name=str(ref.display_name or item_id),
                status="blocked",
                actionable=False,
                reason="Selected Analysis Database reference is missing database_id.",
                blockers=("Missing database_id.",),
            )
            return item, None

        try:
            manifest = self._analysis_store.load_manifest(
                market=market,
                database_id=database_id,
            )
        except Exception as exc:
            item = SelectedDatabaseUpdatePlanItem(
                item_id=item_id,
                database_id=database_id,
                display_name=str(ref.display_name or database_id),
                status="blocked",
                actionable=False,
                reason="Selected Analysis Database manifest could not be loaded.",
                blockers=(
                    f"Analysis Database manifest could not be loaded: {type(exc).__name__}: {exc}",
                ),
                metadata={"market": analysis_market_to_dict(market)},
            )
            return item, None

        if manifest.materialization is None or manifest.status == "draft":
            item = self._database_item(
                item_id=item_id,
                manifest=manifest,
                status="draft",
                actionable=False,
                reason="Analysis Database is a draft and has no materialized dataframe.",
                warnings=(),
                blockers=(),
                drift_report=None,
                materialized=False,
            )
            return item, None

        dataframe_path = self._analysis_store.dataframe_path(
            market=market,
            database_id=database_id,
        )
        if not dataframe_path.exists():
            item = self._database_item(
                item_id=item_id,
                manifest=manifest,
                status="blocked",
                actionable=False,
                reason="Analysis Database manifest is materialized but dataframe.csv is missing.",
                warnings=(),
                blockers=(f"Analysis Database dataframe was not found: {dataframe_path}",),
                drift_report=None,
                materialized=False,
            )
            return item, None

        dependency_status, dependency_reasons, dependency_metadata = (
            self._database_source_artifact_status(manifest)
        )
        drift_report = self._analysis_store.materialization_source_ohlcv_drift_report(
            market=market,
            database_id=database_id,
        )
        if dependency_status == "blocked":
            item = self._database_item(
                item_id=item_id,
                manifest=manifest,
                status="blocked",
                actionable=False,
                reason="Analysis Database rebuild is blocked by source artifact state.",
                warnings=(),
                blockers=dependency_reasons,
                drift_report=drift_report,
                materialized=True,
                metadata={"source_artifacts": dependency_metadata},
            )
            return item, None
        if dependency_status == "unknown":
            item = self._database_item(
                item_id=item_id,
                manifest=manifest,
                status="unknown",
                actionable=False,
                reason="Analysis Database source artifact freshness cannot be proven safely.",
                warnings=dependency_reasons,
                blockers=(),
                drift_report=drift_report,
                materialized=True,
                metadata={"source_artifacts": dependency_metadata},
            )
            return item, None

        if drift_report.status == "blocked":
            reason = _first_reason(
                drift_report.reasons,
                default="Current source OHLCV is not loadable for Analysis Database rebuild.",
            )
            item = self._database_item(
                item_id=item_id,
                manifest=manifest,
                status="blocked",
                actionable=False,
                reason=reason,
                warnings=(),
                blockers=tuple(drift_report.reasons) or (reason,),
                drift_report=drift_report,
                materialized=True,
            )
            return item, None
        if drift_report.status == "unknown":
            reason = _first_reason(
                drift_report.reasons,
                default="Analysis Database materialization freshness is unknown.",
            )
            item = self._database_item(
                item_id=item_id,
                manifest=manifest,
                status="unknown",
                actionable=False,
                reason=reason,
                warnings=tuple(drift_report.reasons) or (reason,),
                blockers=(),
                drift_report=drift_report,
                materialized=True,
            )
            return item, None
        if drift_report.status == "source_drift" and drift_report.actionable:
            reason = _first_reason(
                drift_report.reasons,
                default="Analysis Database source OHLCV drift was detected.",
            )
            item = self._database_item(
                item_id=item_id,
                manifest=manifest,
                status="old",
                actionable=True,
                reason=reason,
                warnings=(),
                blockers=(),
                drift_report=drift_report,
                materialized=True,
                expected_action_label=f"Rebuild Analysis Database {manifest.display_name}",
            )
            action = SelectedUpdateAction(
                action_id=f"rebuild_analysis_database:{manifest.database_id}",
                action_type="rebuild_analysis_database",
                item_id=item.item_id,
                item_type="analysis_database",
                label=f"Rebuild Analysis Database {manifest.display_name}",
                reason=reason,
                metadata={
                    "market": analysis_market_to_dict(market),
                    "database_id": manifest.database_id,
                    "display_name": manifest.display_name,
                    "recipe_hash": manifest.recipe_hash,
                    "recipe_hash_short": manifest.recipe_hash_short,
                },
            )
            return item, action

        item = self._database_item(
            item_id=item_id,
            manifest=manifest,
            status="current",
            actionable=False,
            reason="Analysis Database materialization is current.",
            warnings=(),
            blockers=(),
            drift_report=drift_report,
            materialized=True,
        )
        return item, None

    def _execute_artifact_action(
        self,
        *,
        action: SelectedUpdateAction,
    ) -> SelectedUpdateExecutionItemResult:
        started = _utc_now()
        recipe_id = str(action.metadata.get("recipe_id") or "").strip()
        market_raw = action.metadata.get("market")
        if not recipe_id or not isinstance(market_raw, Mapping):
            return _failed_result(
                action=action,
                started_at_utc=started,
                message="Artifact action is missing recipe or market metadata.",
                error="missing_action_metadata",
            )
        try:
            market = analysis_market_from_dict(dict(market_raw))
            recipe = self._recipe_store.load_recipe(market=market, recipe_id=recipe_id)
            collection = self._collection_for_recipes(market=market, recipes=(recipe,))
            report = self._recovery_regenerator.regenerate_collection(
                collection,
                selected_recipe_ids=(recipe_id,),
                continue_on_error=False,
                replan_after=True,
            )
        except Exception as exc:
            return _failed_result(
                action=action,
                started_at_utc=started,
                message=f"Artifact regeneration failed: {type(exc).__name__}: {exc}",
                error=f"{type(exc).__name__}: {exc}",
            )

        finished = _utc_now()
        if getattr(report, "execution_attempted", False) and getattr(
            report,
            "execution_success",
            False,
        ):
            return SelectedUpdateExecutionItemResult(
                action_id=action.action_id,
                action_type=action.action_type,
                item_id=action.item_id,
                status="completed",
                message="Artifact regeneration completed.",
                started_at_utc=started,
                finished_at_utc=finished,
                metadata={"regeneration_report": _report_to_dict(report)},
            )
        error = _first_execution_error(getattr(report, "execution_report", None))
        return SelectedUpdateExecutionItemResult(
            action_id=action.action_id,
            action_type=action.action_type,
            item_id=action.item_id,
            status="failed",
            message="Artifact regeneration did not complete successfully.",
            started_at_utc=started,
            finished_at_utc=finished,
            error=error or "artifact_regeneration_failed",
            metadata={"regeneration_report": _report_to_dict(report)},
        )

    def _execute_database_action(
        self,
        *,
        action: SelectedUpdateAction,
    ) -> SelectedUpdateExecutionItemResult:
        started = _utc_now()
        database_id = str(action.metadata.get("database_id") or "").strip()
        market_raw = action.metadata.get("market")
        if not database_id or not isinstance(market_raw, Mapping):
            return _failed_result(
                action=action,
                started_at_utc=started,
                message="Analysis Database action is missing database or market metadata.",
                error="missing_action_metadata",
            )
        try:
            market = analysis_market_from_dict(dict(market_raw))
            manifest = self._analysis_store.materialize_database(
                market=market,
                database_id=database_id,
                overwrite=True,
            )
        except Exception as exc:
            return _failed_result(
                action=action,
                started_at_utc=started,
                message=f"Analysis Database rebuild failed: {type(exc).__name__}: {exc}",
                error=f"{type(exc).__name__}: {exc}",
            )

        return SelectedUpdateExecutionItemResult(
            action_id=action.action_id,
            action_type=action.action_type,
            item_id=action.item_id,
            status="completed",
            message="Analysis Database rebuild completed.",
            started_at_utc=started,
            finished_at_utc=_utc_now(),
            metadata={
                "database_id": manifest.database_id,
                "display_name": manifest.display_name,
                "status": manifest.status,
                "dataframe_filename": manifest.dataframe_filename,
            },
        )

    def _database_source_artifact_status(
        self,
        manifest: AnalysisDatabaseManifest,
    ) -> tuple[Literal["current", "unknown", "blocked"], tuple[str, ...], list[dict[str, object]]]:
        selected_source_ids = {
            str(column.source_id)
            for column in manifest.feature_columns
            if column.selected and column.source_id
        }
        source_by_id = {
            source.source_id: source
            for source in manifest.feature_sources
            if source.source_id in selected_source_ids
        }
        if not source_by_id:
            return "current", (), []

        blockers: list[str] = []
        warnings: list[str] = []
        metadata: list[dict[str, object]] = []
        partition_dir = self._paths.partition_dir(manifest.market)
        columns_by_source: dict[str, list[str]] = {}
        for column in manifest.feature_columns:
            if column.selected and column.source_id:
                columns_by_source.setdefault(column.source_id, []).append(
                    column.source_column_name,
                )

        for source_id, source in source_by_id.items():
            path = _source_artifact_path(partition_dir=partition_dir, source=source)
            source_metadata: dict[str, object] = {
                "source_id": source_id,
                "family": source.family,
                "tool_key": source.tool_key,
                "instance_key": source.instance_key,
                "path": str(path),
            }
            if not path.exists():
                blockers.append(f"Source artifact was not found: {path}")
                metadata.append(source_metadata)
                continue

            columns, csv_error = _read_csv_columns(path)
            if csv_error:
                blockers.append(csv_error)
                metadata.append(source_metadata)
                continue
            required_columns = tuple(columns_by_source.get(source_id, ()))
            missing_columns = tuple(name for name in required_columns if name not in columns)
            if missing_columns:
                blockers.append(
                    f"Source artifact {path} is missing selected column(s): {list(missing_columns)}"
                )
            join_key = "ts_ms" if "ts_ms" in columns else "time" if "time" in columns else ""
            if not join_key:
                blockers.append(
                    f"Source artifact cannot be aligned safely; 'ts_ms' or 'time' is required: {path}"
                )
            elif _csv_join_key_has_duplicates(path=path, join_key=join_key):
                blockers.append(
                    f"Source artifact contains duplicate {join_key!r} values: {path}"
                )

            artifact_manifest = self._derived_store.load_metadata_manifest(path)
            if artifact_manifest is None:
                warnings.append(
                    f"Source artifact freshness cannot be proven because metadata is missing or unreadable: {path}"
                )
                metadata.append(source_metadata)
                continue

            drift_report = build_source_ohlcv_drift_report(
                historical_root=self._historical_root,
                market=manifest.market,
                recorded_snapshot=extract_source_ohlcv_snapshot(
                    artifact_manifest.metadata,
                ),
            )
            source_metadata["source_drift_report"] = drift_report.to_dict()
            if drift_report.status == "blocked":
                blockers.extend(tuple(drift_report.reasons))
            elif drift_report.status == "source_drift":
                blockers.append(
                    f"Source artifact is stale and must be updated before database rebuild: {path}"
                )
                blockers.extend(tuple(drift_report.reasons))
            elif drift_report.status == "unknown":
                warnings.extend(tuple(drift_report.reasons))
            metadata.append(source_metadata)

        if blockers:
            return "blocked", tuple(blockers), metadata
        if warnings:
            return "unknown", tuple(warnings), metadata
        return "current", (), metadata

    def _database_item(
        self,
        *,
        item_id: str,
        manifest: AnalysisDatabaseManifest,
        status: SelectedDatabaseStatus,
        actionable: bool,
        reason: str,
        warnings: tuple[str, ...],
        blockers: tuple[str, ...],
        drift_report: SourceOhlcvDriftReport | None,
        materialized: bool,
        expected_action_label: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> SelectedDatabaseUpdatePlanItem:
        dataframe_path = self._analysis_store.dataframe_path(
            market=manifest.market,
            database_id=manifest.database_id,
        )
        item_metadata: dict[str, Any] = {
            "market": analysis_market_to_dict(manifest.market),
            "manifest_status": manifest.status,
            "recipe_hash": manifest.recipe_hash,
            "recipe_hash_short": manifest.recipe_hash_short,
            "dataframe_filename": manifest.dataframe_filename,
            "dataframe_path": dataframe_path,
            "dataframe_exists": dataframe_path.exists(),
            "materialization": (
                None
                if manifest.materialization is None
                else manifest.materialization.to_dict()
            ),
            "drift_report": None if drift_report is None else drift_report.to_dict(),
        }
        item_metadata.update(dict(metadata or {}))
        return SelectedDatabaseUpdatePlanItem(
            item_id=item_id,
            database_id=manifest.database_id,
            display_name=manifest.display_name,
            status=status,
            actionable=actionable,
            reason=reason,
            warnings=warnings,
            blockers=blockers,
            materialized=materialized,
            expected_action_label=expected_action_label,
            metadata=item_metadata,
        )

    def _resolve_artifact_path(
        self,
        *,
        ref: SelectedArtifactUpdateRef,
        kind: str,
        market: MarketId,
    ) -> Path | None:
        if ref.artifact_path is not None:
            candidate = Path(ref.artifact_path).expanduser()
            if candidate.is_absolute():
                return candidate
            return self._paths.partition_dir(market) / candidate
        instance_key = _clean_optional(ref.instance_key)
        if instance_key is None:
            return None
        return self._paths.dataset_dir(market, kind) / f"{instance_key}.csv"

    def _artifact_identity_blockers(
        self,
        *,
        ref: SelectedArtifactUpdateRef,
        kind: str,
        manifest: HistoricalCsvArtifactManifest | None,
        recipe: ArtifactRecipe,
        recipe_hash: str | None,
        artifact_path: Path,
    ) -> tuple[str, ...]:
        blockers: list[str] = []
        expected_tool_type = _tool_type_for_kind(kind)
        if recipe.tool_type != expected_tool_type:
            blockers.append(
                f"Recipe tool_type {recipe.tool_type!r} does not match selected artifact family {kind!r}."
            )
        if _clean_optional(ref.tool_key) is not None and _clean_optional(ref.tool_key) != recipe.tool_key:
            blockers.append(
                f"Selected artifact tool_key {ref.tool_key!r} does not match recipe tool_key {recipe.tool_key!r}."
            )
        if recipe_hash is not None and recipe_hash != recipe.recipe_hash:
            blockers.append(
                "Artifact sidecar recipe_hash does not match the current saved recipe hash."
            )
        if manifest is None:
            return tuple(blockers)
        if manifest.market != recipe.market:
            blockers.append("Artifact sidecar market does not match the saved recipe market.")
        if manifest.identity.storage_family != kind:
            blockers.append(
                f"Artifact sidecar storage_family {manifest.identity.storage_family!r} does not match selected family {kind!r}."
            )
        if manifest.tool is not None and manifest.tool.tool_key != recipe.tool_key:
            blockers.append(
                f"Artifact sidecar tool_key {manifest.tool.tool_key!r} does not match recipe tool_key {recipe.tool_key!r}."
            )
        if Path(manifest.files.csv_filename).name != artifact_path.name:
            blockers.append(
                f"Artifact sidecar csv_filename {manifest.files.csv_filename!r} does not match selected file {artifact_path.name!r}."
            )
        return tuple(blockers)

    def _collection_for_recipes(
        self,
        *,
        market: MarketId,
        recipes: tuple[ArtifactRecipe, ...],
    ) -> ArtifactRecipeCollection:
        return self._collection_store.build_collection(
            market=market,
            display_name="Selected Data Manager update items",
            recipes=recipes,
            description="Transient collection for selected-item update planning.",
            metadata={"scope": "selected_item_update"},
        )


def _artifact_status_from_recovery(
    recovery_item: ArtifactRecoveryItemReport,
) -> tuple[SelectedArtifactStatus, bool, str, tuple[str, ...], tuple[str, ...]]:
    reasons = _recovery_reasons(recovery_item)
    reason = _first_reason(
        reasons,
        default=f"Artifact recovery status is {recovery_item.status}.",
    )
    if recovery_item.status == "up_to_date":
        return "current", False, "Selected artifact is current.", (), ()
    if recovery_item.status == "stale" and recovery_item.actionable:
        return "old", True, reason, (), ()
    if recovery_item.status == "freshness_unknown":
        return "unknown", False, reason, reasons or (reason,), ()
    if recovery_item.status in {"missing", "blocked"}:
        blockers = reasons or (reason,)
        return "blocked", False, reason, (), blockers
    if recovery_item.status == "stale":
        blockers = reasons or ("Selected artifact is stale but not actionable.",)
        return "blocked", False, reason, (), blockers
    return "unknown", False, reason, reasons or (reason,), ()


def _recovery_metadata(
    *,
    recovery_item: ArtifactRecoveryItemReport,
    artifact_path: Path,
    metadata_path: Path | None,
    recovery_report: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "artifact_path": artifact_path,
        "metadata_path": metadata_path,
        "recovery_status": recovery_item.status,
        "can_recalculate": recovery_item.can_recalculate,
        "actionable": recovery_item.actionable,
        "source_drift": any(
            _is_source_drift_reason(reason) for reason in _recovery_reasons(recovery_item)
        ),
        "expected_kind": recovery_item.expected_kind,
        "expected_instance_key": recovery_item.expected_instance_key,
        "expected_csv_path": recovery_item.expected_csv_path,
        "expected_metadata_path": recovery_item.expected_metadata_path,
        "expected_output_names": list(recovery_item.expected_output_names),
        "recovery_report": recovery_report,
    }


def _metadata_value(
    manifest: HistoricalCsvArtifactManifest | None,
    *,
    namespace: str,
    key: str,
) -> str | None:
    if manifest is None:
        return None
    for entry in manifest.metadata:
        if entry.namespace == namespace and entry.key == key:
            value = str(entry.value or "").strip()
            return value or None
    return None


def _source_artifact_path(*, partition_dir: Path, source: object) -> Path:
    relpath = Path(str(getattr(source, "source_artifact_relpath", "") or ""))
    candidate = partition_dir / relpath
    if candidate.exists():
        return candidate
    return (
        partition_dir
        / str(getattr(source, "family", "") or "")
        / str(getattr(source, "source_artifact_filename", "") or "")
    )


def _read_csv_columns(path: Path) -> tuple[tuple[str, ...], str]:
    try:
        dataframe = pd.read_csv(path, nrows=0)
    except Exception as exc:
        return (), f"Could not read CSV header from {path}: {type(exc).__name__}: {exc}"
    return tuple(str(column) for column in dataframe.columns), ""


def _csv_join_key_has_duplicates(*, path: Path, join_key: str) -> bool:
    try:
        values = pd.read_csv(path, usecols=[join_key])[join_key]
    except Exception:
        return False
    return bool(values.duplicated(keep=False).any())


def _requested_action_ids(
    *,
    actions: Iterable[SelectedUpdateAction],
    selected_action_ids: Iterable[str] | None,
) -> tuple[str, ...]:
    raw_ids: Iterable[str]
    if selected_action_ids is None:
        raw_ids = (action.action_id for action in actions)
    else:
        raw_ids = selected_action_ids
    requested: list[str] = []
    for raw in raw_ids:
        action_id = str(raw or "").strip()
        if action_id and action_id not in requested:
            requested.append(action_id)
    return tuple(requested)


def _execution_report(
    *,
    plan_id: str,
    started_at_utc: str,
    finished_at_utc: str,
    requested_action_ids: tuple[str, ...],
    results: list[SelectedUpdateExecutionItemResult],
) -> SelectedUpdateExecutionReport:
    completed = tuple(result.action_id for result in results if result.status == "completed")
    skipped = tuple(result.action_id for result in results if result.status == "skipped")
    failed = tuple(result.action_id for result in results if result.status == "failed")
    blocked = tuple(result.action_id for result in results if result.status == "blocked")
    return SelectedUpdateExecutionReport(
        report_id=f"selected_update_execution:{int(time.time() * 1000)}",
        plan_id=plan_id,
        started_at_utc=started_at_utc,
        finished_at_utc=finished_at_utc,
        requested_action_ids=requested_action_ids,
        completed_action_ids=completed,
        skipped_action_ids=skipped,
        failed_action_ids=failed,
        blocked_action_ids=blocked,
        results=tuple(results),
        summary={
            "requested": len(requested_action_ids),
            "completed": len(completed),
            "skipped": len(skipped),
            "failed": len(failed),
            "blocked": len(blocked),
        },
    )


def _unknown_action_result(*, action_id: str) -> SelectedUpdateExecutionItemResult:
    now = _utc_now()
    return SelectedUpdateExecutionItemResult(
        action_id=action_id,
        action_type="unknown",
        item_id="",
        status="failed",
        message=f"Selected action id is not present in the update plan: {action_id}",
        started_at_utc=now,
        finished_at_utc=now,
        error="unknown_action_id",
        metadata={"reason": "unknown_action_id"},
    )


def _skipped_result(
    *,
    action: SelectedUpdateAction,
    message: str,
    reason: str,
) -> SelectedUpdateExecutionItemResult:
    now = _utc_now()
    return SelectedUpdateExecutionItemResult(
        action_id=action.action_id,
        action_type=action.action_type,
        item_id=action.item_id,
        status="skipped",
        message=message,
        started_at_utc=now,
        finished_at_utc=now,
        metadata={"reason": reason},
    )


def _failed_result(
    *,
    action: SelectedUpdateAction,
    started_at_utc: str,
    message: str,
    error: str,
) -> SelectedUpdateExecutionItemResult:
    return SelectedUpdateExecutionItemResult(
        action_id=action.action_id,
        action_type=action.action_type,
        item_id=action.item_id,
        status="failed",
        message=message,
        started_at_utc=started_at_utc,
        finished_at_utc=_utc_now(),
        error=error,
        metadata={"reason": error},
    )


def _artifact_summary(
    *,
    items: Iterable[SelectedArtifactUpdatePlanItem],
    actions: Iterable[SelectedUpdateAction],
) -> dict[str, int]:
    item_list = list(items)
    return {
        "total_items": len(item_list),
        "current": sum(1 for item in item_list if item.status == "current"),
        "old": sum(1 for item in item_list if item.status == "old"),
        "unknown": sum(1 for item in item_list if item.status == "unknown"),
        "blocked": sum(1 for item in item_list if item.status == "blocked"),
        "error": sum(1 for item in item_list if item.status == "error"),
        "actions": len(tuple(actions)),
    }


def _database_summary(
    *,
    items: Iterable[SelectedDatabaseUpdatePlanItem],
    actions: Iterable[SelectedUpdateAction],
) -> dict[str, int]:
    item_list = list(items)
    return {
        "total_items": len(item_list),
        "current": sum(1 for item in item_list if item.status == "current"),
        "old": sum(1 for item in item_list if item.status == "old"),
        "draft": sum(1 for item in item_list if item.status == "draft"),
        "unknown": sum(1 for item in item_list if item.status == "unknown"),
        "blocked": sum(1 for item in item_list if item.status == "blocked"),
        "error": sum(1 for item in item_list if item.status == "error"),
        "actions": len(tuple(actions)),
    }


def _artifact_kind(family: str) -> str:
    value = str(family or "").strip().lower()
    if value in {"indicator", "indicators"}:
        return "indicators"
    if value in {"oscillator", "oscillators"}:
        return "oscillators"
    if value in {"construct", "constructs"}:
        return "constructs"
    raise ValueError(f"Unsupported selected artifact family: {family!r}")


def _tool_type_for_kind(kind: str) -> str:
    if kind == "indicators":
        return "indicator"
    if kind == "oscillators":
        return "oscillator"
    if kind == "constructs":
        return "construct"
    raise ValueError(f"Unsupported selected artifact kind: {kind!r}")


def _artifact_item_id(*, ref: SelectedArtifactUpdateRef, index: int) -> str:
    identity = (
        _clean_optional(ref.recipe_id)
        or _clean_optional(ref.instance_key)
        or (Path(ref.artifact_path).stem if ref.artifact_path is not None else "")
        or f"artifact_{index}"
    )
    return f"artifact:{_safe_id(identity)}"


def _database_item_id(*, ref: SelectedAnalysisDatabaseUpdateRef, index: int) -> str:
    identity = str(ref.database_id or "").strip() or f"database_{index}"
    return f"analysis_database:{_safe_id(identity)}"


def _artifact_display_name(*, ref: SelectedArtifactUpdateRef, item_id: str) -> str:
    if _clean_optional(ref.display_name) is not None:
        return str(ref.display_name).strip()
    if _clean_optional(ref.instance_key) is not None:
        return str(ref.instance_key).strip()
    if ref.artifact_path is not None:
        return Path(ref.artifact_path).name
    return item_id


def _safe_id(value: str) -> str:
    out = []
    for char in str(value).strip().lower():
        out.append(char if char.isalnum() or char in {"_", "-", ":"} else "_")
    cleaned = "".join(out).strip("_")
    return cleaned or "item"


def _clean_optional(value: object) -> str | None:
    cleaned = str(value or "").strip()
    return cleaned or None


def _same_path(left: Path, right: Path) -> bool:
    try:
        return left.resolve() == right.resolve()
    except Exception:
        return left == right


def _recovery_reasons(item: ArtifactRecoveryItemReport) -> tuple[str, ...]:
    return tuple(item.stale_reasons) + tuple(item.blocked_reasons) + tuple(item.notes)


def _is_source_drift_reason(reason: str) -> bool:
    value = str(reason or "")
    if value.startswith("missing_recorded_source_ohlcv_snapshot"):
        return False
    if value.startswith("invalid_recorded_source_ohlcv_snapshot"):
        return False
    return value.startswith("source_") or value.startswith("current_source_ohlcv")


def _first_reason(reasons: Iterable[str], *, default: str) -> str:
    for reason in reasons:
        value = str(reason or "").strip()
        if value:
            return value
    return default


def _first_execution_error(execution_report: object | None) -> str:
    for item in getattr(execution_report, "item_reports", ()) or ():
        error_text = str(getattr(item, "error_text", "") or "").strip()
        if error_text:
            return error_text
        skipped_reason = str(getattr(item, "skipped_reason", "") or "").strip()
        if skipped_reason:
            return skipped_reason
    return ""


def _report_to_dict(report: object) -> object:
    to_dict = getattr(report, "to_dict", None)
    if callable(to_dict):
        return to_dict()
    return _json_safe(report)


def _utc_now() -> str:
    return format_ts_ms_utc(int(time.time() * 1000))


def _json_safe(value: object) -> object:
    if isinstance(value, Mapping):
        return {
            str(key): _json_safe(item)
            for key, item in sorted(value.items(), key=lambda item: str(item[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, Path):
        return value.as_posix()
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)
