from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import pytest

from leonardo.data.historical.artifact_recipe_collection_store import ArtifactRecipeCollectionStore
from leonardo.data.historical.artifact_recipe_executor import ArtifactRecipeExecutor
from leonardo.data.historical.artifact_recipe_store import ArtifactRecipe, ArtifactRecipeStore
from leonardo.data.historical.artifact_recovery_planner import ArtifactRecoveryPlanner
from leonardo.data.historical.artifact_recovery_regenerator import ArtifactRecoveryRegenerator
from leonardo.data.historical.derived_store_csv import DerivedCsvStore
from leonardo.data.historical.paths import HistoricalPaths
from leonardo.data.historical.store_csv import Candle, CsvOHLCVStore
from leonardo.data.naming import canonicalize


@dataclass(frozen=True)
class FakeCalculationResult:
    recipe_id: str
    tool_key: str

    def to_dict(self) -> dict[str, object]:
        return {"recipe_id": self.recipe_id, "tool_key": self.tool_key}


class FakeCalculationService:
    def __init__(self, *, fail_recipe_ids: set[str] | None = None) -> None:
        self.calls: list[dict[str, object]] = []
        self.fail_recipe_ids = set(fail_recipe_ids or set())

    def calculate_and_save(self, payload: dict[str, object]) -> FakeCalculationResult:
        self.calls.append(payload)
        recipe_id = str(payload.get("_test_recipe_id", ""))
        if recipe_id in self.fail_recipe_ids:
            raise RuntimeError(f"planned failure for {recipe_id}")
        return FakeCalculationResult(
            recipe_id=recipe_id,
            tool_key=str(payload.get("tool_key", "")),
        )


def _market():
    return canonicalize("bybit", "linear", "BTCUSDT", "30m")


def _write_ohlcv(root: Path, *, rows: int = 20):
    market = _market()
    paths = HistoricalPaths(root=root)
    csv_path = CsvOHLCVStore().file_path(paths.ensure_ohlcv_dir(market))
    start = 1_700_000_000_000
    candles = [
        Candle(
            ts_ms=start + idx * 1_800_000,
            open=100.0 + idx,
            high=101.0 + idx,
            low=99.0 + idx,
            close=100.5 + idx,
            volume=10.0 + idx,
        )
        for idx in range(rows)
    ]
    CsvOHLCVStore().write_atomic(csv_path, candles, market=market)
    return market, csv_path


def _payload(*, period: int = 14) -> dict[str, object]:
    market = _market()
    return {
        "tool_type": "oscillator",
        "tool_key": "rsi",
        "tool_title": "RSI",
        "exchange": market.exchange,
        "market_type": market.market_type,
        "symbol": market.symbol,
        "timeframe": market.timeframe,
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


def _recipe(root: Path, *, period: int) -> ArtifactRecipe:
    recipe = ArtifactRecipeStore(historical_root=root).save_recipe(_payload(period=period))
    return _with_test_recipe_id(recipe)


def _with_test_recipe_id(recipe: ArtifactRecipe) -> ArtifactRecipe:
    payload = recipe.to_payload()
    payload["_test_recipe_id"] = recipe.recipe_id
    object.__setattr__(recipe, "to_payload", lambda payload=payload: dict(payload))
    return recipe


def _collection(root: Path, *recipes: ArtifactRecipe):
    store = ArtifactRecipeCollectionStore(historical_root=root)
    return store.save_collection(
        store.build_collection(
            market=recipes[0].market,
            display_name="Recovery Regeneration Pack",
            recipes=recipes,
        )
    )


def _save_artifact(root: Path, recipe: ArtifactRecipe):
    planner = ArtifactRecoveryPlanner(historical_root=root)
    instance_key = planner.expected_instance_key(recipe)
    period = int(recipe.params["period"])
    return DerivedCsvStore(historical_root=root).save_dataframe(
        market=recipe.market,
        kind="oscillators",
        tool_key="rsi",
        instance_key=instance_key,
        df=pd.DataFrame(
            {
                "ts_ms": [1_700_000_000_000, 1_700_001_800_000],
                f"rsi_{period}": [50.0, 55.0],
            }
        ),
        params=dict(recipe.params),
        params_status="explicit",
        bindings={},
        bindings_status="unknown",
    )


def _regenerator(root: Path, service: FakeCalculationService) -> ArtifactRecoveryRegenerator:
    executor = ArtifactRecipeExecutor(
        historical_root=root,
        calculation_service=service,
    )
    return ArtifactRecoveryRegenerator(
        historical_root=root,
        executor=executor,
    )


def test_regenerator_executes_only_planner_actionable_recipes(tmp_path: Path) -> None:
    _write_ohlcv(tmp_path)
    up_to_date = _recipe(tmp_path, period=14)
    missing = _recipe(tmp_path, period=21)
    _save_artifact(tmp_path, up_to_date)
    collection = _collection(tmp_path, up_to_date, missing)
    service = FakeCalculationService()

    report = _regenerator(tmp_path, service).regenerate_collection(
        collection,
        replan_after=False,
    )

    assert report.requested_recipe_ids == (up_to_date.recipe_id, missing.recipe_id)
    assert report.actionable_recipe_ids == (missing.recipe_id,)
    assert report.non_actionable_recipe_ids == (up_to_date.recipe_id,)
    assert report.execution_attempted is True
    assert report.execution_success is True
    assert report.success is True
    assert report.execution_report is not None
    assert report.execution_report.requested_recipe_ids == (missing.recipe_id,)
    assert [call["_test_recipe_id"] for call in service.calls] == [missing.recipe_id]


def test_regenerator_noops_when_collection_is_already_up_to_date(tmp_path: Path) -> None:
    _write_ohlcv(tmp_path)
    recipe = _recipe(tmp_path, period=14)
    _save_artifact(tmp_path, recipe)
    collection = _collection(tmp_path, recipe)
    service = FakeCalculationService()

    report = _regenerator(tmp_path, service).regenerate_collection(collection)

    assert report.actionable_recipe_ids == ()
    assert report.non_actionable_recipe_ids == (recipe.recipe_id,)
    assert report.execution_attempted is False
    assert report.execution_report is None
    assert report.post_recovery_report is not None
    assert report.success is True
    assert service.calls == []


def test_regenerator_does_not_execute_blocked_items(tmp_path: Path) -> None:
    recipe = _recipe(tmp_path, period=14)
    collection = _collection(tmp_path, recipe)
    service = FakeCalculationService()

    report = _regenerator(tmp_path, service).regenerate_collection(collection)

    assert report.pre_recovery_report.blocked_count == 1
    assert report.actionable_recipe_ids == ()
    assert report.non_actionable_recipe_ids == (recipe.recipe_id,)
    assert report.execution_attempted is False
    assert report.success is False
    assert service.calls == []


def test_regenerator_preserves_executor_failure_and_skip_semantics(tmp_path: Path) -> None:
    _write_ohlcv(tmp_path)
    first = _recipe(tmp_path, period=14)
    second = _recipe(tmp_path, period=21)
    third = _recipe(tmp_path, period=28)
    collection = _collection(tmp_path, first, second, third)
    service = FakeCalculationService(fail_recipe_ids={second.recipe_id})

    report = _regenerator(tmp_path, service).regenerate_collection(
        collection,
        replan_after=False,
    )

    assert report.actionable_recipe_ids == (first.recipe_id, second.recipe_id, third.recipe_id)
    assert report.execution_report is not None
    assert [item.status for item in report.execution_report.item_reports] == [
        "succeeded",
        "failed",
        "skipped",
    ]
    assert report.succeeded_count == 1
    assert report.failed_count == 1
    assert report.skipped_count == 1
    assert report.execution_success is False
    assert report.success is False
    assert [call["_test_recipe_id"] for call in service.calls] == [
        first.recipe_id,
        second.recipe_id,
    ]


def test_regenerator_continue_on_error_delegates_to_executor(tmp_path: Path) -> None:
    _write_ohlcv(tmp_path)
    first = _recipe(tmp_path, period=14)
    second = _recipe(tmp_path, period=21)
    third = _recipe(tmp_path, period=28)
    collection = _collection(tmp_path, first, second, third)
    service = FakeCalculationService(fail_recipe_ids={second.recipe_id})

    report = _regenerator(tmp_path, service).regenerate_collection(
        collection,
        continue_on_error=True,
        replan_after=False,
    )

    assert report.execution_report is not None
    assert [item.status for item in report.execution_report.item_reports] == [
        "succeeded",
        "failed",
        "succeeded",
    ]
    assert report.succeeded_count == 2
    assert report.failed_count == 1
    assert report.skipped_count == 0
    assert [call["_test_recipe_id"] for call in service.calls] == [
        first.recipe_id,
        second.recipe_id,
        third.recipe_id,
    ]


def test_regenerator_selected_recipe_ids_keep_collection_order(tmp_path: Path) -> None:
    _write_ohlcv(tmp_path)
    first = _recipe(tmp_path, period=14)
    second = _recipe(tmp_path, period=21)
    third = _recipe(tmp_path, period=28)
    collection = _collection(tmp_path, first, second, third)
    service = FakeCalculationService()

    report = _regenerator(tmp_path, service).regenerate_collection(
        collection,
        selected_recipe_ids=(third.recipe_id, first.recipe_id),
        replan_after=False,
    )

    assert report.requested_recipe_ids == (first.recipe_id, third.recipe_id)
    assert report.actionable_recipe_ids == (first.recipe_id, third.recipe_id)
    assert report.execution_report is not None
    assert report.execution_report.requested_recipe_ids == (first.recipe_id, third.recipe_id)
    assert [call["_test_recipe_id"] for call in service.calls] == [
        first.recipe_id,
        third.recipe_id,
    ]


def test_regenerator_can_use_existing_planner_report(tmp_path: Path) -> None:
    _write_ohlcv(tmp_path)
    first = _recipe(tmp_path, period=14)
    second = _recipe(tmp_path, period=21)
    collection = _collection(tmp_path, first, second)
    service = FakeCalculationService()
    regenerator = _regenerator(tmp_path, service)
    recovery_report = ArtifactRecoveryPlanner(historical_root=tmp_path).plan_collection(
        collection,
        selected_recipe_ids=(second.recipe_id,),
    )

    report = regenerator.regenerate_from_report(
        collection=collection,
        recovery_report=recovery_report,
        replan_after=False,
    )

    assert report.requested_recipe_ids == (second.recipe_id,)
    assert report.actionable_recipe_ids == (second.recipe_id,)
    assert [call["_test_recipe_id"] for call in service.calls] == [second.recipe_id]


def test_regenerator_loads_collection_by_id(tmp_path: Path) -> None:
    _write_ohlcv(tmp_path)
    recipe = _recipe(tmp_path, period=14)
    collection = _collection(tmp_path, recipe)
    service = FakeCalculationService()

    report = _regenerator(tmp_path, service).regenerate_collection_by_id(
        market=collection.market,
        collection_id=collection.collection_id,
        replan_after=False,
    )

    assert report.collection_id == collection.collection_id
    assert report.actionable_recipe_ids == (recipe.recipe_id,)
    assert len(service.calls) == 1
    assert service.calls[0]["tool_key"] == "rsi"
    assert service.calls[0]["params"] == {"period": 14}


def test_regenerator_rejects_mismatched_existing_report(tmp_path: Path) -> None:
    _write_ohlcv(tmp_path)
    first = _recipe(tmp_path, period=14)
    second = _recipe(tmp_path, period=21)
    first_collection = _collection(tmp_path, first)
    second_collection = _collection(tmp_path, second)
    recovery_report = ArtifactRecoveryPlanner(historical_root=tmp_path).plan_collection(
        first_collection
    )

    with pytest.raises(ValueError, match="collection_id"):
        _regenerator(tmp_path, FakeCalculationService()).regenerate_from_report(
            collection=second_collection,
            recovery_report=recovery_report,
        )
