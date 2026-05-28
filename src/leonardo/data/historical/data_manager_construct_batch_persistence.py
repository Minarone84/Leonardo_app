from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Mapping, Sequence

from leonardo.data.historical.artifact_recipe_collection_store import (
    ArtifactRecipeCollection,
    ArtifactRecipeCollectionStore,
)
from leonardo.data.historical.artifact_recipe_store import (
    ArtifactRecipe,
    ArtifactRecipeStore,
)
from leonardo.data.historical.data_manager_construct_batch_planner import (
    SUPPORTED_DELTA_CONSTRUCT,
    SUPPORTED_UNARY_CONSTRUCTS,
    ConstructBatchPlan,
    ConstructBatchPlanItem,
)
from leonardo.data.naming import canonicalize

ConstructBatchPersistenceStatus = Literal[
    "saved",
    "reused_existing",
    "skipped",
    "blocked",
    "failed",
]


@dataclass(frozen=True)
class ConstructBatchPersistenceItemResult:
    """Persistence result for one selected construct batch plan item."""

    item_id: str
    status: ConstructBatchPersistenceStatus
    recipe_id: str | None
    recipe_hash: str | None
    display_name: str
    reason: str
    warnings: tuple[str, ...] = ()
    blockers: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "item_id": self.item_id,
            "status": self.status,
            "recipe_id": self.recipe_id,
            "recipe_hash": self.recipe_hash,
            "display_name": self.display_name,
            "reason": self.reason,
            "warnings": list(self.warnings),
            "blockers": list(self.blockers),
        }


@dataclass(frozen=True)
class ConstructBatchPersistenceCollectionResult:
    """Persistence result for an optional ordered recipe collection."""

    collection_saved: bool
    collection_id: str | None = None
    collection_name: str | None = None
    collection_hash: str | None = None
    collection_hash_short: str | None = None
    recipe_count: int = 0
    ordered_recipe_ids: tuple[str, ...] = ()
    ordered_recipe_hashes: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    blockers: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "collection_saved": bool(self.collection_saved),
            "collection_id": self.collection_id,
            "collection_name": self.collection_name,
            "collection_hash": self.collection_hash,
            "collection_hash_short": self.collection_hash_short,
            "recipe_count": int(self.recipe_count),
            "ordered_recipe_ids": list(self.ordered_recipe_ids),
            "ordered_recipe_hashes": list(self.ordered_recipe_hashes),
            "warnings": list(self.warnings),
            "blockers": list(self.blockers),
        }


@dataclass(frozen=True)
class ConstructBatchPersistenceReport:
    """JSON-safe report for construct batch recipe persistence."""

    batch_kind: str
    construct_key: str
    selected_count: int
    saved_recipe_count: int
    reused_recipe_count: int
    skipped_count: int
    blocked_count: int
    failed_count: int
    collection_saved: bool
    collection_id: str | None
    collection_name: str | None
    results: tuple[ConstructBatchPersistenceItemResult, ...]
    blockers: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    collection_result: ConstructBatchPersistenceCollectionResult | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "batch_kind": self.batch_kind,
            "construct_key": self.construct_key,
            "selected_count": int(self.selected_count),
            "saved_recipe_count": int(self.saved_recipe_count),
            "reused_recipe_count": int(self.reused_recipe_count),
            "skipped_count": int(self.skipped_count),
            "blocked_count": int(self.blocked_count),
            "failed_count": int(self.failed_count),
            "collection_saved": bool(self.collection_saved),
            "collection_id": self.collection_id,
            "collection_name": self.collection_name,
            "results": [result.to_dict() for result in self.results],
            "blockers": list(self.blockers),
            "warnings": list(self.warnings),
            "collection_result": (
                None
                if self.collection_result is None
                else self.collection_result.to_dict()
            ),
        }


class DataManagerConstructBatchPersistenceService:
    """
    Persist approved recipe candidates from construct batch planning.

    The service consumes DMCB2 plan output. It does not classify source state,
    inspect alignment, execute recipes, create artifacts, or mutate Analysis
    Databases. Persistence is delegated to the existing artifact recipe and
    recipe collection stores.
    """

    def __init__(
        self,
        *,
        historical_root: Path,
        recipe_store: ArtifactRecipeStore | None = None,
        collection_store: ArtifactRecipeCollectionStore | None = None,
    ) -> None:
        self._historical_root = Path(historical_root)
        self._recipe_store = recipe_store or ArtifactRecipeStore(
            historical_root=self._historical_root
        )
        self._collection_store = collection_store or ArtifactRecipeCollectionStore(
            historical_root=self._historical_root
        )

    def persist_selected_recipes(
        self,
        *,
        plan: ConstructBatchPlan,
        selected_item_ids: Sequence[str],
        include_existing_recipes: bool = True,
    ) -> ConstructBatchPersistenceReport:
        """Save/reuse selected construct recipes without creating a collection."""
        results, _recipes = self._persist_selected_items(
            plan=plan,
            selected_item_ids=selected_item_ids,
            include_existing_recipes=include_existing_recipes,
        )
        return self._build_report(
            plan=plan,
            selected_count=len(tuple(selected_item_ids)),
            results=results,
            collection_result=None,
        )

    def persist_selected_recipes_as_collection(
        self,
        *,
        plan: ConstructBatchPlan,
        selected_item_ids: Sequence[str],
        collection_name: str,
        collection_description: str = "",
        include_existing_recipes: bool = True,
        overwrite_collection: bool = True,
    ) -> ConstructBatchPersistenceReport:
        """
        Save/reuse selected construct recipes, then save an ordered collection.

        Collection persistence is all-or-blocked: if any selected item cannot
        produce a saved or reused recipe, no collection is written.
        """
        selected_ids = tuple(selected_item_ids)
        results, recipes = self._persist_selected_items(
            plan=plan,
            selected_item_ids=selected_ids,
            include_existing_recipes=include_existing_recipes,
        )
        collection_result = self._save_collection(
            plan=plan,
            selected_item_ids=selected_ids,
            recipes=recipes,
            results=results,
            collection_name=collection_name,
            collection_description=collection_description,
            overwrite_collection=overwrite_collection,
        )
        return self._build_report(
            plan=plan,
            selected_count=len(selected_ids),
            results=results,
            collection_result=collection_result,
        )

    def _persist_selected_items(
        self,
        *,
        plan: ConstructBatchPlan,
        selected_item_ids: Sequence[str],
        include_existing_recipes: bool,
    ) -> tuple[
        tuple[ConstructBatchPersistenceItemResult, ...],
        tuple[ArtifactRecipe, ...],
    ]:
        item_by_id = {item.item_id: item for item in plan.items}
        results: list[ConstructBatchPersistenceItemResult] = []
        recipes: list[ArtifactRecipe] = []

        for item_id in _unique_preserving_order(selected_item_ids):
            item = item_by_id.get(str(item_id))
            if item is None:
                results.append(
                    ConstructBatchPersistenceItemResult(
                        item_id=str(item_id),
                        status="blocked",
                        recipe_id=None,
                        recipe_hash=None,
                        display_name=str(item_id),
                        reason="Selected construct batch plan item was not found.",
                        blockers=("selected_item_missing",),
                    )
                )
                continue
            result, recipe = self._persist_item(
                plan=plan,
                item=item,
                include_existing_recipes=include_existing_recipes,
            )
            results.append(result)
            if recipe is not None:
                recipes.append(recipe)

        return tuple(results), tuple(recipes)

    def _persist_item(
        self,
        *,
        plan: ConstructBatchPlan,
        item: ConstructBatchPlanItem,
        include_existing_recipes: bool,
    ) -> tuple[ConstructBatchPersistenceItemResult, ArtifactRecipe | None]:
        if not _is_supported_construct(item.construct_key):
            return self._blocked_result(
                item=item,
                reason=f"Unsupported construct cannot be persisted: {item.construct_key}",
                blockers=("unsupported_construct",),
            ), None
        if item.status == "planned":
            return self._persist_planned_item(item)
        if item.status == "existing_recipe":
            if not include_existing_recipes:
                return (
                    ConstructBatchPersistenceItemResult(
                        item_id=item.item_id,
                        status="skipped",
                        recipe_id=item.existing_recipe_id,
                        recipe_hash=item.existing_recipe_hash,
                        display_name=item.display_name,
                        reason="Existing recipe reuse was disabled for this request.",
                    ),
                    None,
                )
            return self._reuse_existing_item(plan=plan, item=item)
        if item.status == "blocked":
            return self._blocked_result(
                item=item,
                reason="Blocked construct batch plan item was not persisted.",
                blockers=tuple(item.blockers or ("blocked_plan_item",)),
            ), None
        if item.status == "error":
            return self._blocked_result(
                item=item,
                reason="Errored construct batch plan item was not persisted.",
                blockers=tuple(item.blockers or ("errored_plan_item",)),
            ), None
        return self._blocked_result(
            item=item,
            reason=f"Unsupported construct batch plan item status: {item.status}",
            blockers=("unsupported_plan_item_status",),
        ), None

    def _persist_planned_item(
        self,
        item: ConstructBatchPlanItem,
    ) -> tuple[ConstructBatchPersistenceItemResult, ArtifactRecipe | None]:
        payload = item.expected_recipe_payload
        if not payload:
            return self._blocked_result(
                item=item,
                reason="Planned item has no expected recipe payload.",
                blockers=("missing_expected_recipe_payload",),
            ), None
        try:
            draft = self._recipe_store.build_recipe_from_payload(payload)
            existing = self._load_existing_recipe(draft)
            if existing is not None:
                if existing.recipe_hash != draft.recipe_hash:
                    return self._blocked_result(
                        item=item,
                        reason="Existing recipe id resolves to a different payload.",
                        blockers=("recipe_identity_conflict",),
                        recipe_id=draft.recipe_id,
                        recipe_hash=draft.recipe_hash,
                    ), None
                return (
                    ConstructBatchPersistenceItemResult(
                        item_id=item.item_id,
                        status="reused_existing",
                        recipe_id=existing.recipe_id,
                        recipe_hash=existing.recipe_hash,
                        display_name=existing.display_name,
                        reason="Equivalent artifact recipe already exists.",
                        warnings=tuple(item.warnings),
                    ),
                    existing,
                )
            saved = self._recipe_store.save_recipe(payload, overwrite=True)
            return (
                ConstructBatchPersistenceItemResult(
                    item_id=item.item_id,
                    status="saved",
                    recipe_id=saved.recipe_id,
                    recipe_hash=saved.recipe_hash,
                    display_name=saved.display_name,
                    reason="Artifact recipe saved.",
                    warnings=tuple(item.warnings),
                ),
                saved,
            )
        except Exception as exc:
            return (
                ConstructBatchPersistenceItemResult(
                    item_id=item.item_id,
                    status="failed",
                    recipe_id=item.expected_recipe_id,
                    recipe_hash=item.expected_recipe_hash,
                    display_name=item.display_name,
                    reason=f"Artifact recipe persistence failed: {exc!r}",
                    warnings=tuple(item.warnings),
                    blockers=("recipe_persistence_failed",),
                ),
                None,
            )

    def _reuse_existing_item(
        self,
        *,
        plan: ConstructBatchPlan,
        item: ConstructBatchPlanItem,
    ) -> tuple[ConstructBatchPersistenceItemResult, ArtifactRecipe | None]:
        recipe_id = str(item.existing_recipe_id or item.expected_recipe_id or "").strip()
        if not recipe_id:
            return self._blocked_result(
                item=item,
                reason="Existing recipe item does not include a recipe id.",
                blockers=("missing_existing_recipe_id",),
            ), None

        market = canonicalize(
            plan.exchange,
            plan.market_type,
            plan.symbol,
            plan.timeframe,
        )
        try:
            recipe = self._recipe_store.load_recipe(
                market=market,
                recipe_id=recipe_id,
            )
        except Exception as exc:
            return self._blocked_result(
                item=item,
                reason=f"Existing artifact recipe could not be loaded: {exc!r}",
                blockers=("existing_recipe_missing",),
                recipe_id=recipe_id,
                recipe_hash=item.existing_recipe_hash,
            ), None

        if item.existing_recipe_hash and recipe.recipe_hash != item.existing_recipe_hash:
            return self._blocked_result(
                item=item,
                reason="Existing artifact recipe hash does not match the plan.",
                blockers=("existing_recipe_hash_mismatch",),
                recipe_id=recipe.recipe_id,
                recipe_hash=recipe.recipe_hash,
            ), None

        return (
            ConstructBatchPersistenceItemResult(
                item_id=item.item_id,
                status="reused_existing",
                recipe_id=recipe.recipe_id,
                recipe_hash=recipe.recipe_hash,
                display_name=recipe.display_name,
                reason="Existing artifact recipe reused.",
                warnings=tuple(item.warnings),
            ),
            recipe,
        )

    def _save_collection(
        self,
        *,
        plan: ConstructBatchPlan,
        selected_item_ids: tuple[str, ...],
        recipes: tuple[ArtifactRecipe, ...],
        results: tuple[ConstructBatchPersistenceItemResult, ...],
        collection_name: str,
        collection_description: str,
        overwrite_collection: bool,
    ) -> ConstructBatchPersistenceCollectionResult:
        display_name = str(collection_name or "").strip()
        blockers: list[str] = []
        if not display_name:
            blockers.append("collection_name_required")
        if not recipes:
            blockers.append("no_persisted_recipes_for_collection")
        non_terminal = tuple(
            result
            for result in results
            if result.status not in {"saved", "reused_existing"}
        )
        if non_terminal:
            blockers.append("selected_item_persistence_not_complete")
        if blockers:
            return ConstructBatchPersistenceCollectionResult(
                collection_saved=False,
                collection_name=display_name or None,
                recipe_count=len(recipes),
                ordered_recipe_ids=tuple(recipe.recipe_id for recipe in recipes),
                ordered_recipe_hashes=tuple(recipe.recipe_hash for recipe in recipes),
                blockers=tuple(blockers),
            )

        try:
            collection = self._collection_store.build_collection(
                market=recipes[0].market,
                display_name=display_name,
                description=collection_description,
                recipes=recipes,
                metadata=self._collection_metadata(
                    plan=plan,
                    selected_item_ids=selected_item_ids,
                    recipes=recipes,
                ),
            )
            saved = self._collection_store.save_collection(
                collection,
                overwrite=overwrite_collection,
            )
            return self._collection_result(saved)
        except Exception as exc:
            return ConstructBatchPersistenceCollectionResult(
                collection_saved=False,
                collection_name=display_name,
                recipe_count=len(recipes),
                ordered_recipe_ids=tuple(recipe.recipe_id for recipe in recipes),
                ordered_recipe_hashes=tuple(recipe.recipe_hash for recipe in recipes),
                blockers=(f"collection_persistence_failed: {exc!r}",),
            )

    def _collection_metadata(
        self,
        *,
        plan: ConstructBatchPlan,
        selected_item_ids: tuple[str, ...],
        recipes: tuple[ArtifactRecipe, ...],
    ) -> dict[str, object]:
        return {
            "generated_by": "construct_batch_builder",
            "source_plan_id": plan.plan_id,
            "batch_kind": plan.batch_kind,
            "construct_key": plan.construct_key,
            "params": _json_safe(plan.params),
            "selected_item_ids": list(selected_item_ids),
            "recipe_ids": [recipe.recipe_id for recipe in recipes],
            "recipe_hashes": [recipe.recipe_hash for recipe in recipes],
        }

    def _collection_result(
        self,
        collection: ArtifactRecipeCollection,
    ) -> ConstructBatchPersistenceCollectionResult:
        return ConstructBatchPersistenceCollectionResult(
            collection_saved=True,
            collection_id=collection.collection_id,
            collection_name=collection.display_name,
            collection_hash=collection.collection_hash,
            collection_hash_short=collection.collection_hash_short,
            recipe_count=len(collection.recipe_snapshots),
            ordered_recipe_ids=tuple(
                recipe.recipe_id for recipe in collection.recipe_snapshots
            ),
            ordered_recipe_hashes=tuple(
                recipe.recipe_hash for recipe in collection.recipe_snapshots
            ),
        )

    def _build_report(
        self,
        *,
        plan: ConstructBatchPlan,
        selected_count: int,
        results: tuple[ConstructBatchPersistenceItemResult, ...],
        collection_result: ConstructBatchPersistenceCollectionResult | None,
    ) -> ConstructBatchPersistenceReport:
        blockers: list[str] = []
        warnings: list[str] = []
        if collection_result is not None:
            blockers.extend(collection_result.blockers)
            warnings.extend(collection_result.warnings)
        return ConstructBatchPersistenceReport(
            batch_kind=plan.batch_kind,
            construct_key=plan.construct_key,
            selected_count=int(selected_count),
            saved_recipe_count=sum(1 for item in results if item.status == "saved"),
            reused_recipe_count=sum(
                1 for item in results if item.status == "reused_existing"
            ),
            skipped_count=sum(1 for item in results if item.status == "skipped"),
            blocked_count=sum(1 for item in results if item.status == "blocked"),
            failed_count=sum(1 for item in results if item.status == "failed"),
            collection_saved=(
                False
                if collection_result is None
                else collection_result.collection_saved
            ),
            collection_id=(
                None if collection_result is None else collection_result.collection_id
            ),
            collection_name=(
                None if collection_result is None else collection_result.collection_name
            ),
            results=results,
            blockers=tuple(blockers),
            warnings=tuple(warnings),
            collection_result=collection_result,
        )

    def _load_existing_recipe(self, draft: ArtifactRecipe) -> ArtifactRecipe | None:
        path = self._recipe_store.recipe_path(
            market=draft.market,
            recipe_id=draft.recipe_id,
        )
        if not path.exists():
            return None
        return self._recipe_store.load_recipe(
            market=draft.market,
            recipe_id=draft.recipe_id,
        )

    def _blocked_result(
        self,
        *,
        item: ConstructBatchPlanItem,
        reason: str,
        blockers: tuple[str, ...],
        recipe_id: str | None = None,
        recipe_hash: str | None = None,
    ) -> ConstructBatchPersistenceItemResult:
        return ConstructBatchPersistenceItemResult(
            item_id=item.item_id,
            status="blocked",
            recipe_id=recipe_id or item.expected_recipe_id or item.existing_recipe_id,
            recipe_hash=recipe_hash or item.expected_recipe_hash or item.existing_recipe_hash,
            display_name=item.display_name,
            reason=reason,
            warnings=tuple(item.warnings),
            blockers=blockers,
        )


def _is_supported_construct(construct_key: str) -> bool:
    return construct_key in SUPPORTED_UNARY_CONSTRUCTS or construct_key == SUPPORTED_DELTA_CONSTRUCT


def _unique_preserving_order(values: Sequence[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        key = str(value)
        if key in seen:
            continue
        seen.add(key)
        out.append(key)
    return tuple(out)


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
