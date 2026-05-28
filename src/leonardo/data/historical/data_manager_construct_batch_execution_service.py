from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Mapping, Sequence

from leonardo.data.historical.artifact_recipe_executor import (
    ArtifactRecipeExecutionReport,
    ArtifactRecipeExecutor,
)
from leonardo.data.historical.artifact_recipe_store import ArtifactRecipeStore
from leonardo.data.historical.data_manager_construct_batch_persistence import (
    ConstructBatchPersistenceItemResult,
    ConstructBatchPersistenceReport,
    DataManagerConstructBatchPersistenceService,
)
from leonardo.data.historical.data_manager_construct_batch_planner import (
    SUPPORTED_DELTA_CONSTRUCT,
    SUPPORTED_UNARY_CONSTRUCTS,
    ConstructBatchPlan,
    ConstructBatchPlanItem,
)
from leonardo.data.naming import canonicalize


ConstructBatchExecutionStatus = Literal[
    "completed",
    "skipped",
    "blocked",
    "failed",
    "cancelled",
]


@dataclass(frozen=True)
class ConstructBatchExecutionItemResult:
    """Execution result for one selected construct batch plan item."""

    item_id: str
    status: ConstructBatchExecutionStatus
    display_name: str
    recipe_id: str | None
    recipe_hash: str | None
    reason: str
    artifact_path: str | None = None
    output_summary: Mapping[str, object] | None = None
    execution_attempted: bool = False
    warnings: tuple[str, ...] = ()
    blockers: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "item_id": self.item_id,
            "status": self.status,
            "display_name": self.display_name,
            "recipe_id": self.recipe_id,
            "recipe_hash": self.recipe_hash,
            "reason": self.reason,
            "artifact_path": self.artifact_path,
            "output_summary": _json_safe(self.output_summary),
            "execution_attempted": bool(self.execution_attempted),
            "warnings": list(self.warnings),
            "blockers": list(self.blockers),
        }


@dataclass(frozen=True)
class ConstructBatchExecutionReport:
    """JSON-safe report for construct batch artifact calculation."""

    report_id: str
    plan_id: str
    batch_kind: str
    construct_key: str
    started_at_utc: str
    finished_at_utc: str
    selected_count: int
    saved_recipe_count: int
    reused_recipe_count: int
    persisted_recipe_count: int
    execution_attempted_count: int
    completed_count: int
    skipped_count: int
    blocked_count: int
    failed_count: int
    cancelled: bool
    results: tuple[ConstructBatchExecutionItemResult, ...]
    persistence_report: ConstructBatchPersistenceReport
    warnings: tuple[str, ...] = ()
    blockers: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "report_id": self.report_id,
            "plan_id": self.plan_id,
            "batch_kind": self.batch_kind,
            "construct_key": self.construct_key,
            "started_at_utc": self.started_at_utc,
            "finished_at_utc": self.finished_at_utc,
            "selected_count": int(self.selected_count),
            "saved_recipe_count": int(self.saved_recipe_count),
            "reused_recipe_count": int(self.reused_recipe_count),
            "persisted_recipe_count": int(self.persisted_recipe_count),
            "execution_attempted_count": int(self.execution_attempted_count),
            "completed_count": int(self.completed_count),
            "skipped_count": int(self.skipped_count),
            "blocked_count": int(self.blocked_count),
            "failed_count": int(self.failed_count),
            "cancelled": bool(self.cancelled),
            "results": [result.to_dict() for result in self.results],
            "persistence_report": self.persistence_report.to_dict(),
            "warnings": list(self.warnings),
            "blockers": list(self.blockers),
        }


class DataManagerConstructBatchExecutionService:
    """
    Execute approved construct batch plan items through existing recipe execution.

    The service consumes DMCB2 plan output, delegates recipe persistence and
    existing-recipe reuse to the DMCB3 persistence service, and then delegates
    artifact calculation to ``ArtifactRecipeExecutor``. It does not write
    artifact CSV files or sidecars directly, create recipe collections, or
    mutate Analysis Databases.
    """

    def __init__(
        self,
        *,
        historical_root: Path,
        persistence_service: DataManagerConstructBatchPersistenceService | None = None,
        recipe_store: ArtifactRecipeStore | None = None,
        executor: object | None = None,
    ) -> None:
        self._historical_root = Path(historical_root)
        self._persistence_service = (
            persistence_service
            or DataManagerConstructBatchPersistenceService(
                historical_root=self._historical_root
            )
        )
        self._recipe_store = recipe_store or ArtifactRecipeStore(
            historical_root=self._historical_root
        )
        self._executor = executor or ArtifactRecipeExecutor(
            historical_root=self._historical_root
        )

    def execute_selected_artifacts(
        self,
        *,
        plan: ConstructBatchPlan,
        selected_item_ids: Sequence[str],
    ) -> ConstructBatchExecutionReport:
        """Save/reuse selected recipes, then calculate their artifacts."""
        selected_ids = _unique_preserving_order(selected_item_ids)
        started_ms = int(time.time() * 1000)
        started_at = _format_ts_ms_utc(started_ms)

        persistence_report = self._persistence_service.persist_selected_recipes(
            plan=plan,
            selected_item_ids=selected_ids,
        )
        persistence_by_item_id = {
            result.item_id: result for result in persistence_report.results
        }
        item_by_id = {item.item_id: item for item in plan.items}
        results: list[ConstructBatchExecutionItemResult] = []

        for item_id in selected_ids:
            item = item_by_id.get(item_id)
            persistence_result = persistence_by_item_id.get(item_id)
            results.append(
                self._execute_item(
                    plan=plan,
                    item_id=item_id,
                    item=item,
                    persistence_result=persistence_result,
                )
            )

        finished_ms = int(time.time() * 1000)
        return self._build_report(
            plan=plan,
            selected_count=len(selected_ids),
            started_ms=started_ms,
            started_at=started_at,
            finished_at=_format_ts_ms_utc(finished_ms),
            persistence_report=persistence_report,
            results=tuple(results),
        )

    def _execute_item(
        self,
        *,
        plan: ConstructBatchPlan,
        item_id: str,
        item: ConstructBatchPlanItem | None,
        persistence_result: ConstructBatchPersistenceItemResult | None,
    ) -> ConstructBatchExecutionItemResult:
        if item is None:
            return ConstructBatchExecutionItemResult(
                item_id=item_id,
                status="blocked",
                display_name=item_id,
                recipe_id=None,
                recipe_hash=None,
                reason="Selected construct batch plan item was not found.",
                blockers=("selected_item_missing",),
            )

        if not _is_supported_construct(item.construct_key):
            return ConstructBatchExecutionItemResult(
                item_id=item.item_id,
                status="blocked",
                display_name=item.display_name,
                recipe_id=item.expected_recipe_id or item.existing_recipe_id,
                recipe_hash=item.expected_recipe_hash or item.existing_recipe_hash,
                reason=f"Unsupported construct cannot be executed: {item.construct_key}",
                warnings=tuple(item.warnings),
                blockers=("unsupported_construct",),
            )

        if persistence_result is None:
            return ConstructBatchExecutionItemResult(
                item_id=item.item_id,
                status="blocked",
                display_name=item.display_name,
                recipe_id=item.expected_recipe_id or item.existing_recipe_id,
                recipe_hash=item.expected_recipe_hash or item.existing_recipe_hash,
                reason="Selected item did not produce a recipe persistence result.",
                warnings=tuple(item.warnings),
                blockers=("missing_persistence_result",),
            )

        if persistence_result.status not in {"saved", "reused_existing"}:
            return _non_executed_result(
                item=item,
                persistence_result=persistence_result,
            )

        recipe_id = str(persistence_result.recipe_id or "").strip()
        if not recipe_id:
            return ConstructBatchExecutionItemResult(
                item_id=item.item_id,
                status="blocked",
                display_name=item.display_name,
                recipe_id=None,
                recipe_hash=persistence_result.recipe_hash,
                reason="Recipe persistence did not return a recipe id.",
                warnings=tuple(item.warnings) + tuple(persistence_result.warnings),
                blockers=("missing_recipe_id",),
            )

        try:
            recipe = self._recipe_store.load_recipe(
                market=canonicalize(
                    plan.exchange,
                    plan.market_type,
                    plan.symbol,
                    plan.timeframe,
                ),
                recipe_id=recipe_id,
            )
        except Exception as exc:
            return ConstructBatchExecutionItemResult(
                item_id=item.item_id,
                status="failed",
                display_name=item.display_name,
                recipe_id=recipe_id,
                recipe_hash=persistence_result.recipe_hash,
                reason=f"Persisted recipe could not be loaded: {type(exc).__name__}: {exc}",
                warnings=tuple(item.warnings) + tuple(persistence_result.warnings),
                blockers=("persisted_recipe_load_failed",),
            )

        try:
            report = self._executor.execute_recipe(recipe)
        except Exception as exc:
            return ConstructBatchExecutionItemResult(
                item_id=item.item_id,
                status="failed",
                display_name=recipe.display_name,
                recipe_id=recipe.recipe_id,
                recipe_hash=recipe.recipe_hash,
                reason=f"Artifact recipe execution failed: {type(exc).__name__}: {exc}",
                execution_attempted=True,
                warnings=tuple(item.warnings) + tuple(persistence_result.warnings),
                blockers=("artifact_recipe_execution_failed",),
            )

        return _execution_result(
            item=item,
            persistence_result=persistence_result,
            execution_report=report,
        )

    def _build_report(
        self,
        *,
        plan: ConstructBatchPlan,
        selected_count: int,
        started_ms: int,
        started_at: str,
        finished_at: str,
        persistence_report: ConstructBatchPersistenceReport,
        results: tuple[ConstructBatchExecutionItemResult, ...],
    ) -> ConstructBatchExecutionReport:
        completed_count = sum(1 for item in results if item.status == "completed")
        skipped_count = sum(1 for item in results if item.status == "skipped")
        blocked_count = sum(1 for item in results if item.status == "blocked")
        failed_count = sum(1 for item in results if item.status == "failed")
        cancelled = any(item.status == "cancelled" for item in results)
        execution_attempted_count = sum(
            1 for item in results if item.execution_attempted
        )
        return ConstructBatchExecutionReport(
            report_id=f"dmcb_exec__{plan.plan_id}__{started_ms}",
            plan_id=plan.plan_id,
            batch_kind=plan.batch_kind,
            construct_key=plan.construct_key,
            started_at_utc=started_at,
            finished_at_utc=finished_at,
            selected_count=selected_count,
            saved_recipe_count=persistence_report.saved_recipe_count,
            reused_recipe_count=persistence_report.reused_recipe_count,
            persisted_recipe_count=(
                persistence_report.saved_recipe_count
                + persistence_report.reused_recipe_count
            ),
            execution_attempted_count=execution_attempted_count,
            completed_count=completed_count,
            skipped_count=skipped_count,
            blocked_count=blocked_count,
            failed_count=failed_count,
            cancelled=cancelled,
            results=results,
            persistence_report=persistence_report,
            warnings=tuple(persistence_report.warnings),
            blockers=tuple(persistence_report.blockers),
        )


def _execution_result(
    *,
    item: ConstructBatchPlanItem,
    persistence_result: ConstructBatchPersistenceItemResult,
    execution_report: ArtifactRecipeExecutionReport,
) -> ConstructBatchExecutionItemResult:
    if not execution_report.item_reports:
        return ConstructBatchExecutionItemResult(
            item_id=item.item_id,
            status="failed",
            display_name=item.display_name,
            recipe_id=persistence_result.recipe_id,
            recipe_hash=persistence_result.recipe_hash,
            reason="Artifact recipe execution returned no item report.",
            execution_attempted=True,
            warnings=tuple(item.warnings) + tuple(persistence_result.warnings),
            blockers=("missing_execution_item_report",),
        )

    execution_item = execution_report.item_reports[0]
    warnings = tuple(item.warnings) + tuple(persistence_result.warnings)
    if execution_item.succeeded:
        output_summary = _result_to_dict(execution_item.result)
        return ConstructBatchExecutionItemResult(
            item_id=item.item_id,
            status="completed",
            display_name=execution_item.display_name,
            recipe_id=execution_item.recipe_id,
            recipe_hash=persistence_result.recipe_hash,
            reason="Artifact recipe executed.",
            artifact_path=_artifact_path(execution_item.result),
            output_summary=output_summary,
            execution_attempted=True,
            warnings=warnings,
        )
    if execution_item.skipped:
        return ConstructBatchExecutionItemResult(
            item_id=item.item_id,
            status="skipped",
            display_name=execution_item.display_name,
            recipe_id=execution_item.recipe_id,
            recipe_hash=persistence_result.recipe_hash,
            reason=execution_item.skipped_reason or "Artifact recipe execution skipped.",
            execution_attempted=True,
            warnings=warnings,
            blockers=("artifact_recipe_execution_skipped",),
        )
    return ConstructBatchExecutionItemResult(
        item_id=item.item_id,
        status="failed",
        display_name=execution_item.display_name,
        recipe_id=execution_item.recipe_id,
        recipe_hash=persistence_result.recipe_hash,
        reason=execution_item.error_text or "Artifact recipe execution failed.",
        execution_attempted=True,
        warnings=warnings,
        blockers=("artifact_recipe_execution_failed",),
    )


def _non_executed_result(
    *,
    item: ConstructBatchPlanItem,
    persistence_result: ConstructBatchPersistenceItemResult,
) -> ConstructBatchExecutionItemResult:
    if persistence_result.status == "skipped":
        status: ConstructBatchExecutionStatus = "skipped"
    elif persistence_result.status == "failed":
        status = "failed"
    else:
        status = "blocked"
    return ConstructBatchExecutionItemResult(
        item_id=item.item_id,
        status=status,
        display_name=item.display_name,
        recipe_id=persistence_result.recipe_id,
        recipe_hash=persistence_result.recipe_hash,
        reason=persistence_result.reason,
        warnings=tuple(item.warnings) + tuple(persistence_result.warnings),
        blockers=tuple(item.blockers) + tuple(persistence_result.blockers),
    )


def _is_supported_construct(construct_key: str) -> bool:
    return (
        construct_key in SUPPORTED_UNARY_CONSTRUCTS
        or construct_key == SUPPORTED_DELTA_CONSTRUCT
    )


def _unique_preserving_order(values: Sequence[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        item = str(value)
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
    return tuple(out)


def _format_ts_ms_utc(ts_ms: int) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts_ms / 1000))


def _artifact_path(result: object | None) -> str | None:
    if result is None:
        return None
    value = getattr(result, "saved_path", None)
    if value is None and isinstance(result, Mapping):
        value = result.get("saved_path")
    return str(value) if value else None


def _result_to_dict(result: object | None) -> Mapping[str, object] | None:
    if result is None:
        return None
    to_dict = getattr(result, "to_dict", None)
    if callable(to_dict):
        raw = to_dict()
        return raw if isinstance(raw, Mapping) else {"result": str(raw)}
    if isinstance(result, Mapping):
        return dict(result)
    return {"result": str(result)}


def _json_safe(value: object) -> object:
    if value is None:
        return None
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, Path):
        return value.as_posix()
    if isinstance(value, (str, int, float, bool)):
        return value
    return str(value)
