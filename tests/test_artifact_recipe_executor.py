from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from leonardo.data.historical.artifact_recipe_collection_store import (
    ArtifactRecipeCollectionStore,
    ArtifactRecipeDependencyEdge,
)
from leonardo.data.historical.artifact_recipe_executor import ArtifactRecipeExecutor
from leonardo.data.historical.artifact_recipe_store import ArtifactRecipe, ArtifactRecipeStore
from leonardo.data.naming import canonicalize


@dataclass(frozen=True)
class FakeCalculationResult:
    recipe_id: str
    tool_key: str
    output_names: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "recipe_id": self.recipe_id,
            "tool_key": self.tool_key,
            "output_names": list(self.output_names),
        }


class FakeCalculationService:
    def __init__(self, *, fail_recipe_ids: set[str] | None = None) -> None:
        self.calls: list[dict[str, object]] = []
        self.fail_recipe_ids = set(fail_recipe_ids or set())

    def calculate_and_save(self, payload: dict[str, object]) -> FakeCalculationResult:
        self.calls.append(payload)
        recipe_id = str(payload.get("_test_recipe_id", ""))
        if recipe_id in self.fail_recipe_ids:
            raise RuntimeError(f"planned failure for {recipe_id}")
        output_names = tuple(str(item) for item in payload.get("output_names", ()) or ())  # type: ignore[arg-type]
        return FakeCalculationResult(
            recipe_id=recipe_id,
            tool_key=str(payload.get("tool_key", "")),
            output_names=output_names,
        )


def _payload(*, period: int = 14, symbol: str = "BTC/USDT") -> dict[str, object]:
    return {
        "tool_type": "oscillator",
        "tool_key": "rsi",
        "tool_title": "RSI",
        "exchange": "bybit",
        "market_type": "linear",
        "symbol": symbol,
        "timeframe": "30m",
        "params": {"period": period},
        "input_bindings": {},
        "input_binding_meta": {},
        "required_inputs": ["close"],
        "output_names": [f"rsi_{period}"],
        "output_signals": [
            {
                "name": f"rsi_{period}",
                "signal_type": "signal",
                "renderable": True,
                "analysis_usable": True,
                "default_visible": True,
                "label": f"RSI {period}",
                "description": "",
            }
        ],
    }


def _recipes(tmp_path: Path) -> tuple[ArtifactRecipe, ArtifactRecipe, ArtifactRecipe]:
    store = ArtifactRecipeStore(historical_root=tmp_path)
    first = store.save_recipe(_payload(period=14))
    second = store.save_recipe(_payload(period=21))
    third = store.save_recipe(_payload(period=28))
    return (
        _with_test_recipe_id(first),
        _with_test_recipe_id(second),
        _with_test_recipe_id(third),
    )


def _with_test_recipe_id(recipe: ArtifactRecipe) -> ArtifactRecipe:
    payload = recipe.to_payload()
    payload["_test_recipe_id"] = recipe.recipe_id
    # The executor must pass recipe.to_payload() through to the calculation service.
    # We patch this method on the instance for test observability only.
    object.__setattr__(recipe, "to_payload", lambda payload=payload: dict(payload))
    return recipe


def _collection(tmp_path: Path):
    first, second, third = _recipes(tmp_path)
    store = ArtifactRecipeCollectionStore(historical_root=tmp_path)
    collection = store.save_collection(
        store.build_collection(
            market=first.market,
            display_name="BTCUSDT_30m_rsi_pack",
            recipes=(first, second, third),
        )
    )
    return collection, first, second, third


def test_executor_runs_full_collection_in_collection_order(tmp_path: Path) -> None:
    collection, first, second, third = _collection(tmp_path)
    service = FakeCalculationService()
    executor = ArtifactRecipeExecutor(
        historical_root=tmp_path,
        calculation_service=service,
    )

    report = executor.execute_collection(collection)

    assert report.collection_id == collection.collection_id
    assert report.requested_recipe_ids == (first.recipe_id, second.recipe_id, third.recipe_id)
    assert report.succeeded_count == 3
    assert report.failed_count == 0
    assert report.skipped_count == 0
    assert report.success is True
    assert [call["_test_recipe_id"] for call in service.calls] == [
        first.recipe_id,
        second.recipe_id,
        third.recipe_id,
    ]
    assert [item.recipe_index for item in report.item_reports] == [0, 1, 2]


def test_executor_runs_selected_recipes_in_collection_order(tmp_path: Path) -> None:
    collection, first, second, third = _collection(tmp_path)
    service = FakeCalculationService()
    executor = ArtifactRecipeExecutor(
        historical_root=tmp_path,
        calculation_service=service,
    )

    report = executor.execute_collection(
        collection,
        selected_recipe_ids=(third.recipe_id, first.recipe_id),
    )

    assert report.requested_recipe_ids == (first.recipe_id, third.recipe_id)
    assert [call["_test_recipe_id"] for call in service.calls] == [
        first.recipe_id,
        third.recipe_id,
    ]
    assert [item.recipe_index for item in report.item_reports] == [0, 2]


def test_executor_unknown_selected_recipe_id_is_rejected(tmp_path: Path) -> None:
    collection, _first, _second, _third = _collection(tmp_path)
    executor = ArtifactRecipeExecutor(
        historical_root=tmp_path,
        calculation_service=FakeCalculationService(),
    )

    with pytest.raises(ValueError, match="not in collection"):
        executor.execute_collection(collection, selected_recipe_ids=("ar__missing",))


def test_executor_stops_after_failure_by_default_and_skips_remaining(tmp_path: Path) -> None:
    collection, first, second, third = _collection(tmp_path)
    service = FakeCalculationService(fail_recipe_ids={second.recipe_id})
    executor = ArtifactRecipeExecutor(
        historical_root=tmp_path,
        calculation_service=service,
    )

    report = executor.execute_collection(collection)

    assert [item.status for item in report.item_reports] == ["succeeded", "failed", "skipped"]
    assert report.succeeded_count == 1
    assert report.failed_count == 1
    assert report.skipped_count == 1
    assert report.success is False
    assert [call["_test_recipe_id"] for call in service.calls] == [
        first.recipe_id,
        second.recipe_id,
    ]
    assert third.recipe_id in report.item_reports[2].recipe_id
    assert "previous recipe failed" in report.item_reports[2].skipped_reason


def test_executor_can_continue_after_failure(tmp_path: Path) -> None:
    collection, first, second, third = _collection(tmp_path)
    service = FakeCalculationService(fail_recipe_ids={second.recipe_id})
    executor = ArtifactRecipeExecutor(
        historical_root=tmp_path,
        calculation_service=service,
    )

    report = executor.execute_collection(collection, continue_on_error=True)

    assert [item.status for item in report.item_reports] == ["succeeded", "failed", "succeeded"]
    assert report.succeeded_count == 2
    assert report.failed_count == 1
    assert report.skipped_count == 0
    assert [call["_test_recipe_id"] for call in service.calls] == [
        first.recipe_id,
        second.recipe_id,
        third.recipe_id,
    ]


def test_executor_loads_collection_by_id(tmp_path: Path) -> None:
    collection, first, second, third = _collection(tmp_path)
    service = FakeCalculationService()
    executor = ArtifactRecipeExecutor(
        historical_root=tmp_path,
        calculation_service=service,
    )

    report = executor.execute_collection_by_id(
        market=collection.market,
        collection_id=collection.collection_id,
    )

    assert report.collection_id == collection.collection_id
    assert [item.recipe_id for item in report.item_reports] == [
        first.recipe_id,
        second.recipe_id,
        third.recipe_id,
    ]


def test_executor_rejects_invalid_dependency_order_for_selected_recipes(tmp_path: Path) -> None:
    first, second, _third = _recipes(tmp_path)
    store = ArtifactRecipeCollectionStore(historical_root=tmp_path)
    collection = store.build_collection(
        market=first.market,
        display_name="Invalid Dependency Pack",
        recipes=(first, second),
        dependency_edges=(
            ArtifactRecipeDependencyEdge(
                from_recipe_id=second.recipe_id,
                to_recipe_id=first.recipe_id,
                reason="second must be produced before first",
            ),
        ),
    )
    executor = ArtifactRecipeExecutor(
        historical_root=tmp_path,
        calculation_service=FakeCalculationService(),
    )

    with pytest.raises(ValueError, match="dependency order is invalid"):
        executor.execute_collection(collection)


def test_executor_execute_single_recipe_report(tmp_path: Path) -> None:
    first, _second, _third = _recipes(tmp_path)
    service = FakeCalculationService()
    executor = ArtifactRecipeExecutor(
        historical_root=tmp_path,
        calculation_service=service,
    )

    report = executor.execute_recipe(first)

    assert report.collection_id is None
    assert report.requested_recipe_ids == (first.recipe_id,)
    assert report.succeeded_count == 1
    assert report.item_reports[0].recipe_index == 0
    assert report.to_dict()["succeeded_count"] == 1


def test_executor_does_not_auto_run_unselected_dependency(tmp_path: Path) -> None:
    first, second, _third = _recipes(tmp_path)
    store = ArtifactRecipeCollectionStore(historical_root=tmp_path)
    collection = store.build_collection(
        market=first.market,
        display_name="Selected Dependency Pack",
        recipes=(first, second),
        dependency_edges=(
            ArtifactRecipeDependencyEdge(
                from_recipe_id=first.recipe_id,
                to_recipe_id=second.recipe_id,
                reason="second may consume first if both are recalculated",
            ),
        ),
    )
    service = FakeCalculationService()
    executor = ArtifactRecipeExecutor(
        historical_root=tmp_path,
        calculation_service=service,
    )

    report = executor.execute_collection(
        collection,
        selected_recipe_ids=(second.recipe_id,),
    )

    assert report.requested_recipe_ids == (second.recipe_id,)
    assert [call["_test_recipe_id"] for call in service.calls] == [second.recipe_id]
