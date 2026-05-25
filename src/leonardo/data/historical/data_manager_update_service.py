from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import time
from typing import Any, Iterable, Literal, Mapping

from leonardo.data.historical.analysis_database_store import AnalysisDatabaseStore
from leonardo.data.historical.artifact_metadata_naming import format_ts_ms_utc
from leonardo.data.historical.artifact_recipe_collection_store import (
    ArtifactRecipeCollection,
    ArtifactRecipeCollectionStore,
)
from leonardo.data.historical.artifact_recipe_store import market_from_dict, market_to_dict
from leonardo.data.historical.artifact_recovery_planner import (
    ArtifactRecoveryItemReport,
    ArtifactRecoveryPlanner,
    ArtifactRecoveryReport,
)
from leonardo.data.historical.artifact_recovery_database_rebuilder import (
    ArtifactRecoveryDatabaseRebuildReport,
    ArtifactRecoveryDatabaseRebuilder,
)
from leonardo.data.historical.artifact_recovery_regenerator import (
    ArtifactRecoveryRegenerationReport,
    ArtifactRecoveryRegenerator,
)
from leonardo.data.historical.source_ohlcv_provenance import SourceOhlcvDriftReport
from leonardo.data.naming import MarketId


DataManagerUpdateItemType = Literal[
    "artifact",
    "analysis_database",
    "recipe_collection",
]
DataManagerUpdateItemStatus = Literal[
    "current",
    "missing",
    "stale",
    "freshness_unknown",
    "blocked",
    "needs_rebuild",
]
DataManagerUpdateActionability = Literal[
    "none",
    "actionable",
    "optional",
    "blocked",
    "requires_review",
]
DataManagerUpdateActionType = Literal[
    "regenerate_artifact",
    "rebuild_analysis_database",
    "review",
    "none",
]
DataManagerUpdateActionResultStatus = Literal[
    "completed",
    "skipped",
    "failed",
    "blocked",
]


@dataclass(frozen=True)
class DataManagerUpdateBlocker:
    """One read-only blocker that prevents a planned Data Manager update action."""

    blocker_id: str
    item_id: str | None
    reason: str
    message: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return {
            "blocker_id": self.blocker_id,
            "item_id": self.item_id,
            "reason": self.reason,
            "message": self.message,
            "metadata": _json_safe(self.metadata),
        }


@dataclass(frozen=True)
class DataManagerUpdateAction:
    """One action that a future explicit update workflow may execute."""

    action_id: str
    action_type: DataManagerUpdateActionType
    target_item_id: str
    label: str
    reason: str
    blocked: bool = False
    blocker_reasons: tuple[str, ...] = ()
    depends_on_actions: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return {
            "action_id": self.action_id,
            "action_type": self.action_type,
            "target_item_id": self.target_item_id,
            "label": self.label,
            "reason": self.reason,
            "blocked": bool(self.blocked),
            "blocker_reasons": list(self.blocker_reasons),
            "depends_on_actions": list(self.depends_on_actions),
            "metadata": _json_safe(self.metadata),
        }


@dataclass(frozen=True)
class DataManagerUpdatePlanItem:
    """One artifact, collection, or Analysis Database entry in an update plan."""

    item_id: str
    item_type: DataManagerUpdateItemType
    identity: dict[str, Any]
    display_name: str
    status: DataManagerUpdateItemStatus
    reasons: tuple[str, ...] = ()
    actionability: DataManagerUpdateActionability = "none"
    depends_on: tuple[str, ...] = ()
    affected_databases: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return {
            "item_id": self.item_id,
            "item_type": self.item_type,
            "identity": _json_safe(self.identity),
            "display_name": self.display_name,
            "status": self.status,
            "reasons": list(self.reasons),
            "actionability": self.actionability,
            "depends_on": list(self.depends_on),
            "affected_databases": list(self.affected_databases),
            "metadata": _json_safe(self.metadata),
        }


@dataclass(frozen=True)
class DataManagerUpdatePlan:
    """Read-only Data Manager update plan for a recipe collection target."""

    plan_id: str
    created_at_utc: str
    target_type: str
    target_id: str
    target_display_name: str | None
    market: dict[str, str]
    source_database_id: str | None
    items: tuple[DataManagerUpdatePlanItem, ...]
    actions: tuple[DataManagerUpdateAction, ...]
    blockers: tuple[DataManagerUpdateBlocker, ...]
    warnings: tuple[str, ...]
    summary: dict[str, int]

    def to_dict(self) -> dict[str, object]:
        return {
            "plan_id": self.plan_id,
            "created_at_utc": self.created_at_utc,
            "target_type": self.target_type,
            "target_id": self.target_id,
            "target_display_name": self.target_display_name,
            "market": dict(self.market),
            "source_database_id": self.source_database_id,
            "items": [item.to_dict() for item in self.items],
            "actions": [action.to_dict() for action in self.actions],
            "blockers": [blocker.to_dict() for blocker in self.blockers],
            "warnings": list(self.warnings),
            "summary": dict(self.summary),
        }


@dataclass(frozen=True)
class DataManagerUpdateActionResult:
    """Execution outcome for one confirmed update-plan action."""

    action_id: str
    action_type: str
    target_item_id: str
    status: DataManagerUpdateActionResultStatus
    message: str
    started_at_utc: str | None = None
    finished_at_utc: str | None = None
    dependency_action_ids: tuple[str, ...] = ()
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return {
            "action_id": self.action_id,
            "action_type": self.action_type,
            "target_item_id": self.target_item_id,
            "status": self.status,
            "message": self.message,
            "started_at_utc": self.started_at_utc,
            "finished_at_utc": self.finished_at_utc,
            "dependency_action_ids": list(self.dependency_action_ids),
            "error": self.error,
            "metadata": _json_safe(self.metadata),
        }


@dataclass(frozen=True)
class DataManagerUpdateExecutionReport:
    """Structured report for confirmed Data Manager update-plan execution."""

    report_id: str
    plan_id: str
    started_at_utc: str
    finished_at_utc: str | None
    requested_action_ids: tuple[str, ...]
    completed_action_ids: tuple[str, ...]
    skipped_action_ids: tuple[str, ...]
    failed_action_ids: tuple[str, ...]
    blocked_action_ids: tuple[str, ...]
    results: tuple[DataManagerUpdateActionResult, ...]
    blockers: tuple[DataManagerUpdateBlocker, ...]
    warnings: tuple[str, ...]
    summary: dict[str, int]
    metadata: dict[str, Any] = field(default_factory=dict)

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
            "blockers": [blocker.to_dict() for blocker in self.blockers],
            "warnings": list(self.warnings),
            "summary": dict(self.summary),
            "metadata": _json_safe(self.metadata),
        }


class DataManagerUpdateService:
    """
    Build Data Manager update plans and execute confirmed plan actions.

    Planning consumes ``ArtifactRecoveryPlanner`` and Analysis Database
    materialization drift reports without mutating storage. Execution methods
    only orchestrate confirmed plan actions through the existing recovery
    regenerator and database rebuilder boundaries.
    """

    def __init__(
        self,
        *,
        historical_root: Path,
        recovery_planner: ArtifactRecoveryPlanner | None = None,
        collection_store: ArtifactRecipeCollectionStore | None = None,
        analysis_store: AnalysisDatabaseStore | None = None,
        recovery_regenerator: ArtifactRecoveryRegenerator | None = None,
        database_rebuilder: ArtifactRecoveryDatabaseRebuilder | None = None,
    ) -> None:
        self._historical_root = Path(historical_root)
        self._collection_store = collection_store or ArtifactRecipeCollectionStore(
            historical_root=self._historical_root
        )
        self._recovery_planner = recovery_planner or ArtifactRecoveryPlanner(
            historical_root=self._historical_root,
            collection_store=self._collection_store,
        )
        self._analysis_store = analysis_store or AnalysisDatabaseStore(
            historical_root=self._historical_root,
        )
        self._recovery_regenerator = recovery_regenerator or ArtifactRecoveryRegenerator(
            historical_root=self._historical_root,
            planner=self._recovery_planner,
            collection_store=self._collection_store,
        )
        self._database_rebuilder = database_rebuilder or ArtifactRecoveryDatabaseRebuilder(
            historical_root=self._historical_root,
            analysis_store=self._analysis_store,
            planner=self._recovery_planner,
            collection_store=self._collection_store,
        )

    def plan_recipe_collection_update_by_id(
        self,
        *,
        market: MarketId,
        collection_id: str,
        selected_recipe_ids: Iterable[str] | None = None,
    ) -> DataManagerUpdatePlan:
        """Load a recipe collection and build its read-only update plan."""
        collection = self._collection_store.load_collection(
            market=market,
            collection_id=collection_id,
        )
        return self.plan_recipe_collection_update(
            collection,
            selected_recipe_ids=selected_recipe_ids,
        )

    def plan_recipe_collection_update(
        self,
        collection: ArtifactRecipeCollection,
        *,
        selected_recipe_ids: Iterable[str] | None = None,
    ) -> DataManagerUpdatePlan:
        """Build a read-only update plan for one recipe collection."""
        if not isinstance(collection, ArtifactRecipeCollection):
            raise TypeError(
                "plan_recipe_collection_update() expects an ArtifactRecipeCollection instance"
            )

        recovery_report = self._recovery_planner.plan_collection(
            collection,
            selected_recipe_ids=selected_recipe_ids,
        )
        items: list[DataManagerUpdatePlanItem] = []
        actions: list[DataManagerUpdateAction] = []
        blockers: list[DataManagerUpdateBlocker] = []
        warnings: list[str] = []
        artifact_regenerate_actions: list[str] = []

        for recovery_item in recovery_report.items:
            item, item_action, item_blockers, item_warnings = self._artifact_plan_entry(
                recovery_item=recovery_item,
                source_database_id=collection.source_database_id,
            )
            items.append(item)
            blockers.extend(item_blockers)
            warnings.extend(item_warnings)
            if item_action is not None:
                actions.append(item_action)
                if item_action.action_type == "regenerate_artifact" and not item_action.blocked:
                    artifact_regenerate_actions.append(item_action.action_id)

        database_item, database_action, database_blockers, database_warnings = (
            self._linked_database_plan_entry(
                collection=collection,
                recovery_report=recovery_report,
                artifact_regenerate_actions=tuple(artifact_regenerate_actions),
            )
        )
        if database_item is not None:
            items.append(database_item)
        if database_action is not None:
            actions.append(database_action)
        blockers.extend(database_blockers)
        warnings.extend(database_warnings)

        collection_item = self._collection_plan_item(
            collection=collection,
            recovery_report=recovery_report,
            planned_items=tuple(items),
        )
        items.insert(0, collection_item)

        now_ms = int(time.time() * 1000)
        plan = DataManagerUpdatePlan(
            plan_id=f"dmup__{collection.collection_id}__{now_ms}",
            created_at_utc=format_ts_ms_utc(now_ms),
            target_type="recipe_collection",
            target_id=collection.collection_id,
            target_display_name=collection.display_name,
            market=market_to_dict(collection.market),
            source_database_id=collection.source_database_id,
            items=tuple(items),
            actions=tuple(actions),
            blockers=tuple(blockers),
            warnings=tuple(warnings),
            summary=_plan_summary(
                items=items,
                actions=actions,
                blockers=blockers,
            ),
        )
        return plan

    def execute_update_plan(
        self,
        plan: DataManagerUpdatePlan,
        selected_action_ids: Iterable[str] | None = None,
    ) -> DataManagerUpdateExecutionReport:
        """Execute selected confirmed actions from a Data Manager update plan."""
        if not isinstance(plan, DataManagerUpdatePlan):
            raise TypeError("execute_update_plan() expects a DataManagerUpdatePlan instance")

        started_ms = int(time.time() * 1000)
        requested_action_ids = _requested_action_ids(
            plan=plan,
            selected_action_ids=selected_action_ids,
        )
        requested_set = set(requested_action_ids)
        plan_actions_by_id = {action.action_id: action for action in plan.actions}
        terminal_statuses: dict[str, DataManagerUpdateActionResultStatus] = {}
        results: list[DataManagerUpdateActionResult] = []
        blockers: list[DataManagerUpdateBlocker] = list(plan.blockers)

        for action in plan.actions:
            if action.action_id not in requested_set:
                continue
            result, action_blockers = self._execute_plan_action(
                plan=plan,
                action=action,
                requested_action_ids=requested_set,
                plan_actions_by_id=plan_actions_by_id,
                terminal_statuses=terminal_statuses,
            )
            results.append(result)
            blockers.extend(action_blockers)
            terminal_statuses[action.action_id] = result.status

        for action_id in requested_action_ids:
            if action_id in plan_actions_by_id:
                continue
            result = self._unknown_action_result(action_id=action_id)
            results.append(result)
            terminal_statuses[action_id] = result.status

        finished_ms = int(time.time() * 1000)
        result_tuple = tuple(results)
        return DataManagerUpdateExecutionReport(
            report_id=f"dmur__{plan.plan_id}__{started_ms}",
            plan_id=plan.plan_id,
            started_at_utc=format_ts_ms_utc(started_ms),
            finished_at_utc=format_ts_ms_utc(finished_ms),
            requested_action_ids=requested_action_ids,
            completed_action_ids=_action_ids_by_result_status(result_tuple, "completed"),
            skipped_action_ids=_action_ids_by_result_status(result_tuple, "skipped"),
            failed_action_ids=_action_ids_by_result_status(result_tuple, "failed"),
            blocked_action_ids=_action_ids_by_result_status(result_tuple, "blocked"),
            results=result_tuple,
            blockers=tuple(blockers),
            warnings=plan.warnings,
            summary=_execution_summary(
                requested_action_ids=requested_action_ids,
                results=result_tuple,
                blockers=blockers,
                warnings=plan.warnings,
            ),
            metadata={
                "target_type": plan.target_type,
                "target_id": plan.target_id,
                "source_database_id": plan.source_database_id,
            },
        )

    def _execute_plan_action(
        self,
        *,
        plan: DataManagerUpdatePlan,
        action: DataManagerUpdateAction,
        requested_action_ids: set[str],
        plan_actions_by_id: Mapping[str, DataManagerUpdateAction],
        terminal_statuses: Mapping[str, DataManagerUpdateActionResultStatus],
    ) -> tuple[DataManagerUpdateActionResult, tuple[DataManagerUpdateBlocker, ...]]:
        if action.blocked:
            result, blockers = self._blocked_action_result(action=action)
            return result, blockers

        if action.action_type == "review":
            return (
                self._skipped_action_result(
                    action=action,
                    message="Review actions are not executable by the update service.",
                    reason="review_action_not_executable",
                ),
                (),
            )

        if action.action_type == "none":
            return (
                self._skipped_action_result(
                    action=action,
                    message="No execution is defined for this plan action.",
                    reason="none_action_not_executable",
                ),
                (),
            )

        dependency_result = self._dependency_skip_result(
            action=action,
            requested_action_ids=requested_action_ids,
            plan_actions_by_id=plan_actions_by_id,
            terminal_statuses=terminal_statuses,
        )
        if dependency_result is not None:
            return dependency_result, ()

        if action.action_type == "regenerate_artifact":
            return self._execute_regenerate_artifact_action(plan=plan, action=action), ()

        if action.action_type == "rebuild_analysis_database":
            return self._execute_rebuild_database_action(plan=plan, action=action), ()

        return (
            self._failed_action_result(
                action=action,
                message=f"Unsupported update action type: {action.action_type}",
                reason="unsupported_action_type",
            ),
            (),
        )

    def _execute_regenerate_artifact_action(
        self,
        *,
        plan: DataManagerUpdatePlan,
        action: DataManagerUpdateAction,
    ) -> DataManagerUpdateActionResult:
        started_at = _utc_now()
        recipe_id = str(action.metadata.get("recipe_id") or "").strip()
        if not recipe_id:
            return DataManagerUpdateActionResult(
                action_id=action.action_id,
                action_type=action.action_type,
                target_item_id=action.target_item_id,
                status="failed",
                message="Regenerate action is missing recipe_id metadata.",
                started_at_utc=started_at,
                finished_at_utc=_utc_now(),
                dependency_action_ids=action.depends_on_actions,
                error="missing_recipe_id",
                metadata={"reason": "missing_recipe_id"},
            )

        try:
            collection = self._load_plan_collection(plan)
            report = self._recovery_regenerator.regenerate_collection(
                collection,
                selected_recipe_ids=(recipe_id,),
                continue_on_error=False,
                replan_after=True,
            )
        except Exception as exc:
            return DataManagerUpdateActionResult(
                action_id=action.action_id,
                action_type=action.action_type,
                target_item_id=action.target_item_id,
                status="failed",
                message=f"Artifact regeneration failed: {type(exc).__name__}: {exc}",
                started_at_utc=started_at,
                finished_at_utc=_utc_now(),
                dependency_action_ids=action.depends_on_actions,
                error=f"{type(exc).__name__}: {exc}",
                metadata={"recipe_id": recipe_id},
            )

        status, message, error = _regeneration_action_status(report)
        return DataManagerUpdateActionResult(
            action_id=action.action_id,
            action_type=action.action_type,
            target_item_id=action.target_item_id,
            status=status,
            message=message,
            started_at_utc=started_at,
            finished_at_utc=_utc_now(),
            dependency_action_ids=action.depends_on_actions,
            error=error,
            metadata={
                "recipe_id": recipe_id,
                "regeneration_report": _report_to_dict(report),
            },
        )

    def _execute_rebuild_database_action(
        self,
        *,
        plan: DataManagerUpdatePlan,
        action: DataManagerUpdateAction,
    ) -> DataManagerUpdateActionResult:
        started_at = _utc_now()
        database_id = str(
            action.metadata.get("database_id") or plan.source_database_id or ""
        ).strip()
        if not database_id:
            return DataManagerUpdateActionResult(
                action_id=action.action_id,
                action_type=action.action_type,
                target_item_id=action.target_item_id,
                status="failed",
                message="Rebuild action is missing database_id metadata.",
                started_at_utc=started_at,
                finished_at_utc=_utc_now(),
                dependency_action_ids=action.depends_on_actions,
                error="missing_database_id",
                metadata={"reason": "missing_database_id"},
            )

        try:
            collection = self._load_plan_collection(plan)
            report = self._database_rebuilder.rebuild_for_collection(
                collection,
                require_clean_recovery=True,
                overwrite=True,
            )
        except Exception as exc:
            return DataManagerUpdateActionResult(
                action_id=action.action_id,
                action_type=action.action_type,
                target_item_id=action.target_item_id,
                status="failed",
                message=f"Analysis Database rebuild failed: {type(exc).__name__}: {exc}",
                started_at_utc=started_at,
                finished_at_utc=_utc_now(),
                dependency_action_ids=action.depends_on_actions,
                error=f"{type(exc).__name__}: {exc}",
                metadata={"database_id": database_id},
            )

        status, message, error = _database_rebuild_action_status(report)
        return DataManagerUpdateActionResult(
            action_id=action.action_id,
            action_type=action.action_type,
            target_item_id=action.target_item_id,
            status=status,
            message=message,
            started_at_utc=started_at,
            finished_at_utc=_utc_now(),
            dependency_action_ids=action.depends_on_actions,
            error=error,
            metadata={
                "database_id": database_id,
                "database_rebuild_report": _report_to_dict(report),
            },
        )

    def _load_plan_collection(
        self,
        plan: DataManagerUpdatePlan,
    ) -> ArtifactRecipeCollection:
        return self._collection_store.load_collection(
            market=market_from_dict(dict(plan.market)),
            collection_id=plan.target_id,
        )

    def _blocked_action_result(
        self,
        *,
        action: DataManagerUpdateAction,
    ) -> tuple[DataManagerUpdateActionResult, tuple[DataManagerUpdateBlocker, ...]]:
        reasons = action.blocker_reasons or (action.reason or "Action is blocked.",)
        blockers = tuple(
            DataManagerUpdateBlocker(
                blocker_id=f"blocker:action:{action.action_id}:{index}",
                item_id=action.target_item_id,
                reason=_reason_code(reason),
                message=reason,
                metadata={"action_id": action.action_id, "action_type": action.action_type},
            )
            for index, reason in enumerate(reasons)
        )
        now = _utc_now()
        result = DataManagerUpdateActionResult(
            action_id=action.action_id,
            action_type=action.action_type,
            target_item_id=action.target_item_id,
            status="blocked",
            message=_first_reason_or_default(reasons, default="Action is blocked."),
            started_at_utc=now,
            finished_at_utc=now,
            dependency_action_ids=action.depends_on_actions,
            error=None,
            metadata={
                "blocker_reasons": list(reasons),
                "reason": "action_blocked",
            },
        )
        return result, blockers

    def _dependency_skip_result(
        self,
        *,
        action: DataManagerUpdateAction,
        requested_action_ids: set[str],
        plan_actions_by_id: Mapping[str, DataManagerUpdateAction],
        terminal_statuses: Mapping[str, DataManagerUpdateActionResultStatus],
    ) -> DataManagerUpdateActionResult | None:
        for dependency_id in action.depends_on_actions:
            if dependency_id not in plan_actions_by_id:
                return self._skipped_action_result(
                    action=action,
                    message=f"Dependency action is not in the plan: {dependency_id}",
                    reason="dependency_not_found",
                    metadata={"dependency_action_id": dependency_id},
                )
            if dependency_id not in requested_action_ids:
                return self._skipped_action_result(
                    action=action,
                    message=f"Dependency action was not selected: {dependency_id}",
                    reason="dependency_not_selected",
                    metadata={"dependency_action_id": dependency_id},
                )
            if terminal_statuses.get(dependency_id) != "completed":
                return self._skipped_action_result(
                    action=action,
                    message=f"Dependency action did not complete: {dependency_id}",
                    reason="dependency_not_completed",
                    metadata={"dependency_action_id": dependency_id},
                )
        return None

    def _skipped_action_result(
        self,
        *,
        action: DataManagerUpdateAction,
        message: str,
        reason: str,
        metadata: Mapping[str, Any] | None = None,
    ) -> DataManagerUpdateActionResult:
        now = _utc_now()
        result_metadata = {"reason": reason}
        result_metadata.update(dict(metadata or {}))
        return DataManagerUpdateActionResult(
            action_id=action.action_id,
            action_type=action.action_type,
            target_item_id=action.target_item_id,
            status="skipped",
            message=message,
            started_at_utc=now,
            finished_at_utc=now,
            dependency_action_ids=action.depends_on_actions,
            metadata=result_metadata,
        )

    def _failed_action_result(
        self,
        *,
        action: DataManagerUpdateAction,
        message: str,
        reason: str,
    ) -> DataManagerUpdateActionResult:
        now = _utc_now()
        return DataManagerUpdateActionResult(
            action_id=action.action_id,
            action_type=action.action_type,
            target_item_id=action.target_item_id,
            status="failed",
            message=message,
            started_at_utc=now,
            finished_at_utc=now,
            dependency_action_ids=action.depends_on_actions,
            error=reason,
            metadata={"reason": reason},
        )

    def _unknown_action_result(self, *, action_id: str) -> DataManagerUpdateActionResult:
        now = _utc_now()
        return DataManagerUpdateActionResult(
            action_id=action_id,
            action_type="unknown",
            target_item_id="",
            status="failed",
            message=f"Selected action id is not present in the update plan: {action_id}",
            started_at_utc=now,
            finished_at_utc=now,
            error="unknown_action_id",
            metadata={"reason": "unknown_action_id"},
        )

    def _artifact_plan_entry(
        self,
        *,
        recovery_item: ArtifactRecoveryItemReport,
        source_database_id: str | None,
    ) -> tuple[
        DataManagerUpdatePlanItem,
        DataManagerUpdateAction | None,
        tuple[DataManagerUpdateBlocker, ...],
        tuple[str, ...],
    ]:
        item_id = f"artifact:{recovery_item.recipe_id}"
        reasons = _recovery_item_reasons(recovery_item)
        status = _artifact_plan_status(recovery_item.status)
        source_drift = any(_is_source_drift_reason(reason) for reason in reasons)
        actionability: DataManagerUpdateActionability = "none"
        action: DataManagerUpdateAction | None = None
        blockers: list[DataManagerUpdateBlocker] = []
        warnings: list[str] = []

        if recovery_item.status in {"missing", "stale"} and recovery_item.actionable:
            actionability = "actionable"
            action_id = f"regenerate_artifact:{recovery_item.recipe_id}"
            action = DataManagerUpdateAction(
                action_id=action_id,
                action_type="regenerate_artifact",
                target_item_id=item_id,
                label=f"Regenerate {recovery_item.display_name}",
                reason=_first_reason_or_default(
                    reasons,
                    default=f"Artifact status is {recovery_item.status}.",
                ),
                metadata={
                    "recipe_id": recovery_item.recipe_id,
                    "recipe_index": recovery_item.recipe_index,
                    "source_drift": source_drift,
                },
            )
        elif recovery_item.status == "freshness_unknown":
            actionability = "requires_review"
            warnings.append(
                f"{recovery_item.display_name}: artifact freshness requires review."
            )
            action = DataManagerUpdateAction(
                action_id=f"review_artifact:{recovery_item.recipe_id}",
                action_type="review",
                target_item_id=item_id,
                label=f"Review {recovery_item.display_name}",
                reason=_first_reason_or_default(
                    reasons,
                    default="Artifact freshness is unknown.",
                ),
                metadata={
                    "recipe_id": recovery_item.recipe_id,
                    "recipe_index": recovery_item.recipe_index,
                },
            )
        elif recovery_item.status == "blocked":
            actionability = "blocked"
            for index, reason in enumerate(reasons or ("Artifact update is blocked.",)):
                blockers.append(
                    DataManagerUpdateBlocker(
                        blocker_id=f"blocker:artifact:{recovery_item.recipe_id}:{index}",
                        item_id=item_id,
                        reason=_reason_code(reason),
                        message=reason,
                        metadata={
                            "recipe_id": recovery_item.recipe_id,
                            "recipe_index": recovery_item.recipe_index,
                        },
                    )
                )

        item = DataManagerUpdatePlanItem(
            item_id=item_id,
            item_type="artifact",
            identity={
                "recipe_id": recovery_item.recipe_id,
                "recipe_index": recovery_item.recipe_index,
                "tool_type": recovery_item.tool_type,
                "tool_key": recovery_item.tool_key,
                "expected_kind": recovery_item.expected_kind,
                "expected_instance_key": recovery_item.expected_instance_key,
                "expected_csv_path": str(recovery_item.expected_csv_path),
                "expected_metadata_path": str(recovery_item.expected_metadata_path),
                "expected_output_names": list(recovery_item.expected_output_names),
            },
            display_name=recovery_item.display_name,
            status=status,
            reasons=reasons,
            actionability=actionability,
            affected_databases=(
                () if source_database_id is None else (source_database_id,)
            ),
            metadata={
                "recovery_status": recovery_item.status,
                "can_recalculate": recovery_item.can_recalculate,
                "actionable": recovery_item.actionable,
                "existing_csv": recovery_item.existing_csv,
                "existing_metadata": recovery_item.existing_metadata,
                "source_drift": source_drift,
            },
        )
        return item, action, tuple(blockers), tuple(warnings)

    def _linked_database_plan_entry(
        self,
        *,
        collection: ArtifactRecipeCollection,
        recovery_report: ArtifactRecoveryReport,
        artifact_regenerate_actions: tuple[str, ...],
    ) -> tuple[
        DataManagerUpdatePlanItem | None,
        DataManagerUpdateAction | None,
        tuple[DataManagerUpdateBlocker, ...],
        tuple[str, ...],
    ]:
        source_database_id = collection.source_database_id
        if not source_database_id:
            return None, None, (), ()

        item_id = f"analysis_database:{source_database_id}"
        blockers: list[DataManagerUpdateBlocker] = []
        warnings: list[str] = []
        depends_on_items = tuple(f"artifact:{recipe_id}" for recipe_id in recovery_report.requested_recipe_ids)

        try:
            manifest = self._analysis_store.load_manifest(
                market=collection.market,
                database_id=source_database_id,
            )
        except Exception as exc:
            reason = "analysis_database_manifest_unavailable"
            message = f"Linked Analysis Database manifest could not be loaded: {type(exc).__name__}: {exc}"
            blocker = DataManagerUpdateBlocker(
                blocker_id=f"blocker:analysis_database:{source_database_id}:manifest",
                item_id=item_id,
                reason=reason,
                message=message,
                metadata={"database_id": source_database_id},
            )
            item = DataManagerUpdatePlanItem(
                item_id=item_id,
                item_type="analysis_database",
                identity={"database_id": source_database_id},
                display_name=source_database_id,
                status="blocked",
                reasons=(message,),
                actionability="blocked",
                depends_on=depends_on_items,
                metadata={"error": message},
            )
            return item, None, (blocker,), ()

        if recovery_report.blocked_count:
            reason = "artifact_recovery_blocked"
            message = (
                "Linked Analysis Database rebuild is blocked until artifact recovery blockers are resolved."
            )
            blocker = DataManagerUpdateBlocker(
                blocker_id=f"blocker:analysis_database:{source_database_id}:artifacts",
                item_id=item_id,
                reason=reason,
                message=message,
                metadata={
                    "database_id": source_database_id,
                    "blocked_artifact_count": recovery_report.blocked_count,
                },
            )
            item = self._analysis_database_item(
                item_id=item_id,
                manifest=manifest,
                status="blocked",
                reasons=(message,),
                actionability="blocked",
                depends_on=depends_on_items,
                drift_report=None,
                metadata={"blocked_artifact_count": recovery_report.blocked_count},
            )
            return item, None, (blocker,), ()

        if manifest.materialization is None or not self._analysis_dataframe_exists(
            market=collection.market,
            database_id=source_database_id,
        ):
            reasons = ("Analysis Database is not materialized.",)
            action = self._database_rebuild_action(
                database_id=source_database_id,
                item_id=item_id,
                reason=reasons[0],
                depends_on_actions=artifact_regenerate_actions,
            )
            item = self._analysis_database_item(
                item_id=item_id,
                manifest=manifest,
                status="needs_rebuild",
                reasons=reasons,
                actionability="actionable",
                depends_on=depends_on_items,
                drift_report=None,
                metadata={"materialized": False},
            )
            return item, action, (), ()

        drift_report = self._analysis_store.materialization_source_ohlcv_drift_report(
            market=collection.market,
            database_id=source_database_id,
        )
        return self._analysis_database_drift_entry(
            item_id=item_id,
            manifest=manifest,
            drift_report=drift_report,
            artifact_regenerate_actions=artifact_regenerate_actions,
            depends_on_items=depends_on_items,
        )

    def _analysis_database_drift_entry(
        self,
        *,
        item_id: str,
        manifest: Any,
        drift_report: SourceOhlcvDriftReport,
        artifact_regenerate_actions: tuple[str, ...],
        depends_on_items: tuple[str, ...],
    ) -> tuple[
        DataManagerUpdatePlanItem,
        DataManagerUpdateAction | None,
        tuple[DataManagerUpdateBlocker, ...],
        tuple[str, ...],
    ]:
        database_id = str(manifest.database_id)
        reasons = tuple(drift_report.reasons)
        if drift_report.status == "blocked":
            message = _first_reason_or_default(
                reasons,
                default="Current source OHLCV is not loadable for Analysis Database rebuild.",
            )
            blocker = DataManagerUpdateBlocker(
                blocker_id=f"blocker:analysis_database:{database_id}:source_ohlcv",
                item_id=item_id,
                reason=_reason_code(message),
                message=message,
                metadata=drift_report.to_dict(),
            )
            item = self._analysis_database_item(
                item_id=item_id,
                manifest=manifest,
                status="blocked",
                reasons=reasons,
                actionability="blocked",
                depends_on=depends_on_items,
                drift_report=drift_report,
            )
            return item, None, (blocker,), ()

        if drift_report.status == "source_drift":
            action = self._database_rebuild_action(
                database_id=database_id,
                item_id=item_id,
                reason=_first_reason_or_default(
                    reasons,
                    default="Analysis Database source OHLCV drift was detected.",
                ),
                depends_on_actions=artifact_regenerate_actions,
            )
            item = self._analysis_database_item(
                item_id=item_id,
                manifest=manifest,
                status="needs_rebuild",
                reasons=reasons,
                actionability="actionable",
                depends_on=depends_on_items,
                drift_report=drift_report,
            )
            return item, action, (), ()

        if drift_report.status == "unknown":
            warning = f"{manifest.display_name}: materialization source lineage requires review."
            action = DataManagerUpdateAction(
                action_id=f"review_analysis_database:{database_id}",
                action_type="review",
                target_item_id=item_id,
                label=f"Review Analysis Database {manifest.display_name}",
                reason=_first_reason_or_default(
                    reasons,
                    default="Analysis Database materialization source freshness is unknown.",
                ),
                metadata=drift_report.to_dict(),
            )
            item = self._analysis_database_item(
                item_id=item_id,
                manifest=manifest,
                status="freshness_unknown",
                reasons=reasons,
                actionability="requires_review",
                depends_on=depends_on_items,
                drift_report=drift_report,
            )
            return item, action, (), (warning,)

        if artifact_regenerate_actions:
            reason = "artifact_updates_planned"
            action = self._database_rebuild_action(
                database_id=database_id,
                item_id=item_id,
                reason="Artifact updates are planned for this linked Analysis Database.",
                depends_on_actions=artifact_regenerate_actions,
            )
            item = self._analysis_database_item(
                item_id=item_id,
                manifest=manifest,
                status="needs_rebuild",
                reasons=(reason,),
                actionability="actionable",
                depends_on=depends_on_items,
                drift_report=drift_report,
                metadata={"artifact_updates_planned": True},
            )
            return item, action, (), ()

        item = self._analysis_database_item(
            item_id=item_id,
            manifest=manifest,
            status="current",
            reasons=(),
            actionability="none",
            depends_on=depends_on_items,
            drift_report=drift_report,
        )
        return item, None, (), ()

    def _database_rebuild_action(
        self,
        *,
        database_id: str,
        item_id: str,
        reason: str,
        depends_on_actions: tuple[str, ...],
    ) -> DataManagerUpdateAction:
        return DataManagerUpdateAction(
            action_id=f"rebuild_analysis_database:{database_id}",
            action_type="rebuild_analysis_database",
            target_item_id=item_id,
            label=f"Rebuild Analysis Database {database_id}",
            reason=reason,
            depends_on_actions=depends_on_actions,
            metadata={"database_id": database_id},
        )

    def _analysis_database_item(
        self,
        *,
        item_id: str,
        manifest: Any,
        status: DataManagerUpdateItemStatus,
        reasons: tuple[str, ...],
        actionability: DataManagerUpdateActionability,
        depends_on: tuple[str, ...],
        drift_report: SourceOhlcvDriftReport | None,
        metadata: Mapping[str, Any] | None = None,
    ) -> DataManagerUpdatePlanItem:
        item_metadata: dict[str, Any] = {
            "status": getattr(manifest, "status", ""),
            "dataframe_filename": getattr(manifest, "dataframe_filename", None),
            "drift_report": None if drift_report is None else drift_report.to_dict(),
        }
        item_metadata.update(dict(metadata or {}))
        return DataManagerUpdatePlanItem(
            item_id=item_id,
            item_type="analysis_database",
            identity={
                "database_id": manifest.database_id,
                "recipe_hash": manifest.recipe_hash,
                "recipe_hash_short": manifest.recipe_hash_short,
            },
            display_name=manifest.display_name,
            status=status,
            reasons=reasons,
            actionability=actionability,
            depends_on=depends_on,
            metadata=item_metadata,
        )

    def _analysis_dataframe_exists(self, *, market: MarketId, database_id: str) -> bool:
        return self._analysis_store.dataframe_path(
            market=market,
            database_id=database_id,
        ).exists()

    def _collection_plan_item(
        self,
        *,
        collection: ArtifactRecipeCollection,
        recovery_report: ArtifactRecoveryReport,
        planned_items: tuple[DataManagerUpdatePlanItem, ...],
    ) -> DataManagerUpdatePlanItem:
        if any(item.status == "blocked" for item in planned_items):
            status: DataManagerUpdateItemStatus = "blocked"
            actionability: DataManagerUpdateActionability = "blocked"
        elif any(item.status in {"missing", "stale", "needs_rebuild"} for item in planned_items):
            status = "stale"
            actionability = "actionable"
        elif any(item.status == "freshness_unknown" for item in planned_items):
            status = "freshness_unknown"
            actionability = "requires_review"
        else:
            status = "current"
            actionability = "none"

        return DataManagerUpdatePlanItem(
            item_id=f"recipe_collection:{collection.collection_id}",
            item_type="recipe_collection",
            identity={
                "collection_id": collection.collection_id,
                "collection_hash": collection.collection_hash,
                "collection_hash_short": collection.collection_hash_short,
                "requested_recipe_ids": list(recovery_report.requested_recipe_ids),
            },
            display_name=collection.display_name,
            status=status,
            reasons=(),
            actionability=actionability,
            depends_on=tuple(item.item_id for item in planned_items),
            affected_databases=(
                ()
                if collection.source_database_id is None
                else (collection.source_database_id,)
            ),
            metadata={
                "recovery_report": recovery_report.to_dict(),
                "source_database_id": collection.source_database_id,
            },
        )


def _artifact_plan_status(recovery_status: str) -> DataManagerUpdateItemStatus:
    if recovery_status == "up_to_date":
        return "current"
    if recovery_status in {"missing", "stale", "freshness_unknown", "blocked"}:
        return recovery_status  # type: ignore[return-value]
    return "freshness_unknown"


def _recovery_item_reasons(item: ArtifactRecoveryItemReport) -> tuple[str, ...]:
    return tuple(item.stale_reasons) + tuple(item.blocked_reasons) + tuple(item.notes)


def _is_source_drift_reason(reason: str) -> bool:
    value = str(reason or "")
    if value.startswith("missing_recorded_source_ohlcv_snapshot"):
        return False
    if value.startswith("invalid_recorded_source_ohlcv_snapshot"):
        return False
    return value.startswith("source_") or value.startswith("current_source_ohlcv")


def _first_reason_or_default(reasons: Iterable[str], *, default: str) -> str:
    for reason in reasons:
        value = str(reason or "").strip()
        if value:
            return value
    return default


def _reason_code(reason: str) -> str:
    value = str(reason or "").strip()
    if ":" in value:
        value = value.split(":", 1)[0]
    value = value.strip().lower().replace(" ", "_")
    return value or "blocked"


def _plan_summary(
    *,
    items: Iterable[DataManagerUpdatePlanItem],
    actions: Iterable[DataManagerUpdateAction],
    blockers: Iterable[DataManagerUpdateBlocker],
) -> dict[str, int]:
    item_list = list(items)
    action_list = list(actions)
    blocker_list = list(blockers)
    return {
        "total_items": len(item_list),
        "current": sum(1 for item in item_list if item.status == "current"),
        "missing": sum(1 for item in item_list if item.status == "missing"),
        "stale": sum(1 for item in item_list if item.status == "stale"),
        "freshness_unknown": sum(
            1 for item in item_list if item.status == "freshness_unknown"
        ),
        "blocked": sum(1 for item in item_list if item.status == "blocked"),
        "needs_rebuild": sum(1 for item in item_list if item.status == "needs_rebuild"),
        "actions": len(action_list),
        "actionable_actions": sum(1 for action in action_list if not action.blocked),
        "blocked_actions": sum(1 for action in action_list if action.blocked),
        "blockers": len(blocker_list),
    }


def _requested_action_ids(
    *,
    plan: DataManagerUpdatePlan,
    selected_action_ids: Iterable[str] | None,
) -> tuple[str, ...]:
    raw_ids: Iterable[str]
    if selected_action_ids is None:
        raw_ids = (action.action_id for action in plan.actions if not action.blocked)
    else:
        raw_ids = selected_action_ids

    requested: list[str] = []
    for raw_action_id in raw_ids:
        action_id = str(raw_action_id or "").strip()
        if action_id not in requested:
            requested.append(action_id)
    return tuple(requested)


def _action_ids_by_result_status(
    results: Iterable[DataManagerUpdateActionResult],
    status: DataManagerUpdateActionResultStatus,
) -> tuple[str, ...]:
    return tuple(result.action_id for result in results if result.status == status)


def _execution_summary(
    *,
    requested_action_ids: Iterable[str],
    results: Iterable[DataManagerUpdateActionResult],
    blockers: Iterable[DataManagerUpdateBlocker],
    warnings: Iterable[str],
) -> dict[str, int]:
    result_list = list(results)
    return {
        "requested": len(tuple(requested_action_ids)),
        "completed": sum(1 for result in result_list if result.status == "completed"),
        "skipped": sum(1 for result in result_list if result.status == "skipped"),
        "failed": sum(1 for result in result_list if result.status == "failed"),
        "blocked": sum(1 for result in result_list if result.status == "blocked"),
        "warnings": len(tuple(warnings)),
        "blockers": len(tuple(blockers)),
        "regenerated_artifacts": sum(
            1
            for result in result_list
            if result.status == "completed" and result.action_type == "regenerate_artifact"
        ),
        "rebuilt_databases": sum(
            1
            for result in result_list
            if result.status == "completed"
            and result.action_type == "rebuild_analysis_database"
        ),
    }


def _regeneration_action_status(
    report: ArtifactRecoveryRegenerationReport,
) -> tuple[DataManagerUpdateActionResultStatus, str, str | None]:
    if getattr(report, "execution_attempted", False):
        if getattr(report, "execution_success", False):
            return "completed", "Artifact regeneration completed.", None
        error = _first_execution_error(getattr(report, "execution_report", None))
        return (
            "failed",
            "Artifact regeneration completed with failures.",
            error or "artifact_regeneration_failed",
        )

    pre_report = getattr(report, "pre_recovery_report", None)
    if int(getattr(pre_report, "blocked_count", 0) or 0) > 0:
        return (
            "blocked",
            "Artifact regeneration is blocked by the current recovery plan.",
            "artifact_regeneration_blocked",
        )
    return (
        "skipped",
        "No planner-actionable artifact regeneration was attempted.",
        None,
    )


def _database_rebuild_action_status(
    report: ArtifactRecoveryDatabaseRebuildReport,
) -> tuple[DataManagerUpdateActionResultStatus, str, str | None]:
    if getattr(report, "rebuilt", False):
        return "completed", "Analysis Database rebuild completed.", None
    if getattr(report, "blocked", False):
        reasons = tuple(getattr(report, "blocked_reasons", ()) or ())
        message = _first_reason_or_default(
            reasons,
            default="Analysis Database rebuild is blocked.",
        )
        return "blocked", message, "analysis_database_rebuild_blocked"
    if getattr(report, "skipped", False):
        message = str(getattr(report, "skipped_reason", "") or "").strip()
        return (
            "skipped",
            message or "Analysis Database rebuild was skipped.",
            None,
        )
    error_text = str(getattr(report, "error_text", "") or "").strip()
    return (
        "failed",
        error_text or "Analysis Database rebuild failed.",
        error_text or "analysis_database_rebuild_failed",
    )


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
