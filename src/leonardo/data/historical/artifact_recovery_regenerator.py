from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from leonardo.data.historical.artifact_recipe_collection_store import (
    ArtifactRecipeCollection,
    ArtifactRecipeCollectionStore,
)
from leonardo.data.historical.artifact_recipe_executor import (
    ArtifactRecipeExecutionReport,
    ArtifactRecipeExecutor,
)
from leonardo.data.historical.artifact_recovery_planner import (
    ArtifactRecoveryPlanner,
    ArtifactRecoveryReport,
)
from leonardo.data.naming import MarketId


@dataclass(frozen=True)
class ArtifactRecoveryRegenerationReport:
    """Structured report for a recovery-regeneration request.

    This report is orchestration-only. It records what the planner selected,
    what the executor attempted, and optionally what the planner saw after
    execution. It does not calculate artifacts, persist CSV files, repair
    metadata, or rebuild Analysis Databases.
    """

    market: MarketId
    collection_id: str
    requested_recipe_ids: tuple[str, ...]
    actionable_recipe_ids: tuple[str, ...]
    non_actionable_recipe_ids: tuple[str, ...]
    pre_recovery_report: ArtifactRecoveryReport
    execution_report: ArtifactRecipeExecutionReport | None = None
    post_recovery_report: ArtifactRecoveryReport | None = None

    @property
    def execution_attempted(self) -> bool:
        return self.execution_report is not None

    @property
    def attempted_count(self) -> int:
        if self.execution_report is None:
            return 0
        return self.execution_report.attempted_count

    @property
    def succeeded_count(self) -> int:
        if self.execution_report is None:
            return 0
        return self.execution_report.succeeded_count

    @property
    def failed_count(self) -> int:
        if self.execution_report is None:
            return 0
        return self.execution_report.failed_count

    @property
    def skipped_count(self) -> int:
        if self.execution_report is None:
            return 0
        return self.execution_report.skipped_count

    @property
    def execution_success(self) -> bool:
        if self.execution_report is None:
            return True
        return self.execution_report.success

    @property
    def success(self) -> bool:
        """Return True when the request completed cleanly.

        If no execution was needed, the pre-plan must already be fully clean.
        If execution was attempted, executor success is required. When a post
        plan is available, it is treated as the final recovery truth.
        """
        if not self.execution_success:
            return False
        if self.post_recovery_report is not None:
            return self.post_recovery_report.success
        if self.execution_report is None:
            return self.pre_recovery_report.success
        return True

    def to_dict(self) -> dict[str, object]:
        return {
            "market": {
                "exchange": self.market.exchange,
                "market_type": self.market.market_type,
                "symbol": self.market.symbol,
                "timeframe": self.market.timeframe,
            },
            "collection_id": self.collection_id,
            "requested_recipe_ids": list(self.requested_recipe_ids),
            "actionable_recipe_ids": list(self.actionable_recipe_ids),
            "non_actionable_recipe_ids": list(self.non_actionable_recipe_ids),
            "execution_attempted": self.execution_attempted,
            "attempted_count": self.attempted_count,
            "succeeded_count": self.succeeded_count,
            "failed_count": self.failed_count,
            "skipped_count": self.skipped_count,
            "execution_success": self.execution_success,
            "success": self.success,
            "pre_recovery_report": self.pre_recovery_report.to_dict(),
            "execution_report": (
                None if self.execution_report is None else self.execution_report.to_dict()
            ),
            "post_recovery_report": (
                None if self.post_recovery_report is None else self.post_recovery_report.to_dict()
            ),
        }


class ArtifactRecoveryRegenerator:
    """Regenerate actionable artifacts selected by a recovery planner report.

    Ownership boundaries:
    - ``ArtifactRecoveryPlanner`` owns read-only artifact/source status;
    - this class selects planner-actionable recipe ids and delegates execution;
    - ``ArtifactRecipeExecutor`` owns execution order and execution reports;
    - ``ArtifactCalculationService`` owns calculation and durable artifact saves;
    - Analysis Database rebuild/materialization remains out of scope.
    """

    def __init__(
        self,
        *,
        historical_root: Path,
        planner: ArtifactRecoveryPlanner | None = None,
        executor: ArtifactRecipeExecutor | None = None,
        collection_store: ArtifactRecipeCollectionStore | None = None,
    ) -> None:
        self._historical_root = Path(historical_root)
        self._planner = planner or ArtifactRecoveryPlanner(
            historical_root=self._historical_root
        )
        self._executor = executor or ArtifactRecipeExecutor(
            historical_root=self._historical_root
        )
        self._collection_store = collection_store or ArtifactRecipeCollectionStore(
            historical_root=self._historical_root
        )

    def regenerate_collection_by_id(
        self,
        *,
        market: MarketId,
        collection_id: str,
        selected_recipe_ids: Iterable[str] | None = None,
        continue_on_error: bool = False,
        replan_after: bool = True,
    ) -> ArtifactRecoveryRegenerationReport:
        collection = self._collection_store.load_collection(
            market=market,
            collection_id=collection_id,
        )
        return self.regenerate_collection(
            collection,
            selected_recipe_ids=selected_recipe_ids,
            continue_on_error=continue_on_error,
            replan_after=replan_after,
        )

    def regenerate_collection(
        self,
        collection: ArtifactRecipeCollection,
        *,
        selected_recipe_ids: Iterable[str] | None = None,
        continue_on_error: bool = False,
        replan_after: bool = True,
    ) -> ArtifactRecoveryRegenerationReport:
        if not isinstance(collection, ArtifactRecipeCollection):
            raise TypeError(
                "regenerate_collection() expects an ArtifactRecipeCollection instance"
            )

        pre_report = self._planner.plan_collection(
            collection,
            selected_recipe_ids=selected_recipe_ids,
        )
        return self.regenerate_from_report(
            collection=collection,
            recovery_report=pre_report,
            continue_on_error=continue_on_error,
            replan_after=replan_after,
        )

    def regenerate_from_report(
        self,
        *,
        collection: ArtifactRecipeCollection,
        recovery_report: ArtifactRecoveryReport,
        continue_on_error: bool = False,
        replan_after: bool = True,
    ) -> ArtifactRecoveryRegenerationReport:
        if not isinstance(collection, ArtifactRecipeCollection):
            raise TypeError(
                "regenerate_from_report() expects an ArtifactRecipeCollection instance"
            )
        if not isinstance(recovery_report, ArtifactRecoveryReport):
            raise TypeError(
                "regenerate_from_report() expects an ArtifactRecoveryReport instance"
            )
        if recovery_report.market != collection.market:
            raise ValueError("Recovery report market does not match collection market")
        if recovery_report.collection_id != collection.collection_id:
            raise ValueError(
                "Recovery report collection_id does not match collection collection_id"
            )

        actionable_recipe_ids = tuple(recovery_report.actionable_recipe_ids)
        actionable_set = set(actionable_recipe_ids)
        non_actionable_recipe_ids = tuple(
            recipe_id
            for recipe_id in recovery_report.requested_recipe_ids
            if recipe_id not in actionable_set
        )

        execution_report: ArtifactRecipeExecutionReport | None = None
        if actionable_recipe_ids:
            execution_report = self._executor.execute_collection(
                collection,
                selected_recipe_ids=actionable_recipe_ids,
                continue_on_error=continue_on_error,
            )

        post_report = None
        if replan_after:
            post_report = self._planner.plan_collection(
                collection,
                selected_recipe_ids=recovery_report.requested_recipe_ids,
            )

        return ArtifactRecoveryRegenerationReport(
            market=collection.market,
            collection_id=collection.collection_id,
            requested_recipe_ids=recovery_report.requested_recipe_ids,
            actionable_recipe_ids=actionable_recipe_ids,
            non_actionable_recipe_ids=non_actionable_recipe_ids,
            pre_recovery_report=recovery_report,
            execution_report=execution_report,
            post_recovery_report=post_report,
        )
