from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Literal, Mapping, Sequence, TYPE_CHECKING

from leonardo.data.historical.artifact_recipe_collection_store import (
    ArtifactRecipeCollection,
    ArtifactRecipeCollectionStore,
)
from leonardo.data.historical.artifact_recipe_store import ArtifactRecipe
from leonardo.data.naming import MarketId

if TYPE_CHECKING:  # pragma: no cover - typing only; keeps runtime import lazy.
    from leonardo.data.historical.artifact_calculation_service import ArtifactCalculationResult


ArtifactRecipeExecutionStatus = Literal["succeeded", "failed", "skipped"]


@dataclass(frozen=True)
class ArtifactRecipeExecutionItemReport:
    """Execution outcome for one recipe in a collection.

    This is reporting only. It does not persist artifacts by itself and does not
    own calculation semantics. Calculation remains delegated to
    ``ArtifactCalculationService``.
    """

    recipe_id: str
    recipe_index: int
    display_name: str
    tool_type: str
    tool_key: str
    status: ArtifactRecipeExecutionStatus
    result: Any | None = None
    error_text: str = ""
    skipped_reason: str = ""

    @property
    def succeeded(self) -> bool:
        return self.status == "succeeded"

    @property
    def failed(self) -> bool:
        return self.status == "failed"

    @property
    def skipped(self) -> bool:
        return self.status == "skipped"

    def to_dict(self) -> dict[str, object]:
        return {
            "recipe_id": self.recipe_id,
            "recipe_index": int(self.recipe_index),
            "display_name": self.display_name,
            "tool_type": self.tool_type,
            "tool_key": self.tool_key,
            "status": self.status,
            "result": _result_to_dict(self.result),
            "error_text": self.error_text,
            "skipped_reason": self.skipped_reason,
        }


@dataclass(frozen=True)
class ArtifactRecipeExecutionReport:
    """Structured report for a recipe or collection execution request."""

    market: MarketId
    collection_id: str | None
    requested_recipe_ids: tuple[str, ...]
    item_reports: tuple[ArtifactRecipeExecutionItemReport, ...]

    @property
    def succeeded_count(self) -> int:
        return sum(1 for item in self.item_reports if item.succeeded)

    @property
    def failed_count(self) -> int:
        return sum(1 for item in self.item_reports if item.failed)

    @property
    def skipped_count(self) -> int:
        return sum(1 for item in self.item_reports if item.skipped)

    @property
    def attempted_count(self) -> int:
        return self.succeeded_count + self.failed_count

    @property
    def success(self) -> bool:
        return self.failed_count == 0 and self.skipped_count == 0

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
            "succeeded_count": self.succeeded_count,
            "failed_count": self.failed_count,
            "skipped_count": self.skipped_count,
            "attempted_count": self.attempted_count,
            "success": self.success,
            "item_reports": [item.to_dict() for item in self.item_reports],
        }


class ArtifactRecipeExecutor:
    """Execute artifact recipes through the save-only calculation service.

    The executor is intentionally small and orchestration-only:

    - recipe persistence remains owned by ``ArtifactRecipeStore``;
    - collection persistence remains owned by ``ArtifactRecipeCollectionStore``;
    - financial-tool computation and durable artifact CSV/sidecar writes remain
      owned by ``ArtifactCalculationService``;
    - no GUI, chart-session, pane, or renderer state is created here.
    """

    def __init__(
        self,
        *,
        historical_root: Path,
        calculation_service: object | None = None,
        collection_store: ArtifactRecipeCollectionStore | None = None,
    ) -> None:
        self._historical_root = Path(historical_root)
        self._calculation_service = calculation_service
        self._collection_store = collection_store or ArtifactRecipeCollectionStore(
            historical_root=self._historical_root
        )

    def execute_recipe(self, recipe: ArtifactRecipe) -> ArtifactRecipeExecutionReport:
        """Calculate a single recipe and return a one-item report."""
        if not isinstance(recipe, ArtifactRecipe):
            raise TypeError("execute_recipe() expects an ArtifactRecipe instance")

        item = self._execute_one_recipe(recipe=recipe, recipe_index=0)
        return ArtifactRecipeExecutionReport(
            market=recipe.market,
            collection_id=None,
            requested_recipe_ids=(recipe.recipe_id,),
            item_reports=(item,),
        )

    def execute_collection_by_id(
        self,
        *,
        market: MarketId,
        collection_id: str,
        selected_recipe_ids: Iterable[str] | None = None,
        continue_on_error: bool = False,
    ) -> ArtifactRecipeExecutionReport:
        collection = self._collection_store.load_collection(
            market=market,
            collection_id=collection_id,
        )
        return self.execute_collection(
            collection,
            selected_recipe_ids=selected_recipe_ids,
            continue_on_error=continue_on_error,
        )

    def execute_collection(
        self,
        collection: ArtifactRecipeCollection,
        *,
        selected_recipe_ids: Iterable[str] | None = None,
        continue_on_error: bool = False,
    ) -> ArtifactRecipeExecutionReport:
        """Execute all or selected recipes in their collection order.

        ``selected_recipe_ids`` filters which recipes are executed but does not
        reorder them. The collection's stored recipe order remains the execution
        order so persisted packs stay deterministic.
        """
        if not isinstance(collection, ArtifactRecipeCollection):
            raise TypeError("execute_collection() expects an ArtifactRecipeCollection instance")

        selected_ids = self._normalize_selected_recipe_ids(
            collection=collection,
            selected_recipe_ids=selected_recipe_ids,
        )
        selected_set = set(selected_ids)
        self._validate_dependency_order(collection=collection, selected_recipe_ids=selected_set)

        item_reports: list[ArtifactRecipeExecutionItemReport] = []
        failure_seen = False

        for recipe_index, recipe in enumerate(collection.recipe_snapshots):
            if recipe.recipe_id not in selected_set:
                continue

            if failure_seen and not continue_on_error:
                item_reports.append(
                    ArtifactRecipeExecutionItemReport(
                        recipe_id=recipe.recipe_id,
                        recipe_index=recipe_index,
                        display_name=recipe.display_name,
                        tool_type=recipe.tool_type,
                        tool_key=recipe.tool_key,
                        status="skipped",
                        skipped_reason="Skipped because a previous recipe failed and continue_on_error=False.",
                    )
                )
                continue

            item = self._execute_one_recipe(recipe=recipe, recipe_index=recipe_index)
            item_reports.append(item)
            if item.failed:
                failure_seen = True

        return ArtifactRecipeExecutionReport(
            market=collection.market,
            collection_id=collection.collection_id,
            requested_recipe_ids=selected_ids,
            item_reports=tuple(item_reports),
        )

    def _execute_one_recipe(
        self,
        *,
        recipe: ArtifactRecipe,
        recipe_index: int,
    ) -> ArtifactRecipeExecutionItemReport:
        try:
            result = self._service().calculate_and_save(recipe.to_payload())
        except Exception as exc:
            return ArtifactRecipeExecutionItemReport(
                recipe_id=recipe.recipe_id,
                recipe_index=recipe_index,
                display_name=recipe.display_name,
                tool_type=recipe.tool_type,
                tool_key=recipe.tool_key,
                status="failed",
                error_text=f"{type(exc).__name__}: {exc}",
            )

        return ArtifactRecipeExecutionItemReport(
            recipe_id=recipe.recipe_id,
            recipe_index=recipe_index,
            display_name=recipe.display_name,
            tool_type=recipe.tool_type,
            tool_key=recipe.tool_key,
            status="succeeded",
            result=result,
        )

    def _service(self) -> object:
        if self._calculation_service is None:
            # Lazy import so executor tests and persistence-only workflows do not
            # import financial-tool runtime modules unless calculation is needed.
            from leonardo.data.historical.artifact_calculation_service import (  # noqa: PLC0415
                ArtifactCalculationService,
            )

            self._calculation_service = ArtifactCalculationService(
                historical_root=self._historical_root
            )
        return self._calculation_service

    def _normalize_selected_recipe_ids(
        self,
        *,
        collection: ArtifactRecipeCollection,
        selected_recipe_ids: Iterable[str] | None,
    ) -> tuple[str, ...]:
        collection_ids = tuple(recipe.recipe_id for recipe in collection.recipe_snapshots)
        collection_id_set = set(collection_ids)

        if selected_recipe_ids is None:
            return collection_ids

        requested: list[str] = []
        for raw_recipe_id in selected_recipe_ids:
            recipe_id = str(raw_recipe_id or "").strip()
            if not recipe_id:
                raise ValueError("selected_recipe_ids must not contain empty recipe ids")
            if recipe_id not in collection_id_set:
                raise ValueError(f"Selected recipe id is not in collection: {recipe_id}")
            if recipe_id not in requested:
                requested.append(recipe_id)

        if not requested:
            raise ValueError("selected_recipe_ids must include at least one recipe id")

        requested_set = set(requested)
        return tuple(recipe_id for recipe_id in collection_ids if recipe_id in requested_set)

    def _validate_dependency_order(
        self,
        *,
        collection: ArtifactRecipeCollection,
        selected_recipe_ids: set[str],
    ) -> None:
        index_by_recipe_id = {
            recipe.recipe_id: index
            for index, recipe in enumerate(collection.recipe_snapshots)
        }

        for edge in collection.dependency_edges:
            if edge.from_recipe_id not in selected_recipe_ids:
                continue
            if edge.to_recipe_id not in selected_recipe_ids:
                continue
            from_index = index_by_recipe_id[edge.from_recipe_id]
            to_index = index_by_recipe_id[edge.to_recipe_id]
            if from_index > to_index:
                raise ValueError(
                    "Artifact recipe collection dependency order is invalid: "
                    f"{edge.from_recipe_id} must execute before {edge.to_recipe_id}."
                )


def _result_to_dict(result: Any | None) -> object | None:
    if result is None:
        return None
    to_dict = getattr(result, "to_dict", None)
    if callable(to_dict):
        return to_dict()
    if isinstance(result, Mapping):
        return dict(result)
    return str(result)
