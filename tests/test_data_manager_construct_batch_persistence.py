from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from leonardo.data.historical.artifact_recipe_collection_store import (
    ArtifactRecipeCollectionStore,
)
from leonardo.data.historical.artifact_recipe_store import ArtifactRecipeStore
from leonardo.data.historical.data_manager_construct_batch_persistence import (
    DataManagerConstructBatchPersistenceService,
)
from leonardo.data.historical.data_manager_construct_batch_planner import (
    ConstructBatchSourceRef,
    ConstructDeltaBatchIntent,
    ConstructUnaryBatchIntent,
    DataManagerConstructBatchPlanner,
)
from leonardo.data.naming import canonicalize


def _write_csv(path: Path, timestamps: tuple[int, ...], column_name: str) -> Path:
    lines = ["ts_ms," + column_name]
    lines.extend(f"{ts},{idx + 1}.0" for idx, ts in enumerate(timestamps))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _source(
    root: Path,
    *,
    source_id: str,
    family: str = "indicator",
    column_name: str | None = None,
    write_file: bool = True,
    timestamps: tuple[int, ...] = (1000, 2000, 3000),
) -> ConstructBatchSourceRef:
    column = column_name or source_id
    csv_path = None
    if write_file:
        csv_path = _write_csv(root / f"{source_id}.csv", timestamps, column)
    return ConstructBatchSourceRef(
        source_id=source_id,
        display_name=source_id,
        source_family=family,
        exchange="bybit",
        market_type="linear",
        symbol="BTCUSDT",
        timeframe="30m",
        column_name=column,
        source_token=column,
        csv_path=csv_path,
        timestamp_key=None if write_file else "ts_ms",
        timestamp_values=None if write_file else timestamps,
    )


def _unary_plan(root: Path, *, count: int = 2):
    sources = tuple(
        _source(root, source_id=f"rsi_{idx}", column_name=f"rsi_{idx}")
        for idx in range(count)
    )
    return DataManagerConstructBatchPlanner(historical_root=root).plan_unary_batch(
        ConstructUnaryBatchIntent(
            construct_key="derivative",
            exchange="bybit",
            market_type="linear",
            symbol="BTCUSDT",
            timeframe="30m",
            sources=sources,
            params={"order": 1},
        )
    )


def _delta_plan(root: Path):
    fixed = _source(
        root,
        source_id="close",
        family="ohlc",
        column_name="close",
        write_file=False,
    )
    variable = _source(
        root,
        source_id="rsi_delta",
        column_name="rsi_delta",
        write_file=False,
    )
    return DataManagerConstructBatchPlanner(historical_root=root).plan_delta_batch(
        ConstructDeltaBatchIntent(
            exchange="bybit",
            market_type="linear",
            symbol="BTCUSDT",
            timeframe="30m",
            fixed_source=fixed,
            fixed_role="minuend",
            variable_sources=(variable,),
            params={"mode": "abs"},
        )
    )


def _service(root: Path) -> DataManagerConstructBatchPersistenceService:
    return DataManagerConstructBatchPersistenceService(historical_root=root)


def test_persistence_saves_selected_planned_unary_recipes(tmp_path: Path) -> None:
    plan = _unary_plan(tmp_path, count=2)

    report = _service(tmp_path).persist_selected_recipes(
        plan=plan,
        selected_item_ids=[item.item_id for item in plan.items],
    )

    assert report.saved_recipe_count == 2
    assert report.reused_recipe_count == 0
    assert report.blocked_count == 0
    assert [result.status for result in report.results] == ["saved", "saved"]
    assert [
        result.recipe_id for result in report.results
    ] == [item.expected_recipe_id for item in plan.items]
    recipes = ArtifactRecipeStore(historical_root=tmp_path).list_recipes(
        market=_market_from_plan(plan)
    )
    assert len(recipes) == 2
    json.dumps(report.to_dict())


def test_persistence_saves_selected_planned_delta_recipe(tmp_path: Path) -> None:
    plan = _delta_plan(tmp_path)
    item = plan.items[0]

    report = _service(tmp_path).persist_selected_recipes(
        plan=plan,
        selected_item_ids=(item.item_id,),
    )

    assert report.saved_recipe_count == 1
    assert report.results[0].status == "saved"
    assert report.results[0].recipe_id == item.expected_recipe_id


def test_persistence_reuses_existing_recipe_without_duplicate(
    tmp_path: Path,
) -> None:
    first_plan = _unary_plan(tmp_path, count=1)
    ArtifactRecipeStore(historical_root=tmp_path).save_recipe(
        first_plan.items[0].expected_recipe_payload
    )
    existing_plan = _unary_plan(tmp_path, count=1)
    assert existing_plan.items[0].status == "existing_recipe"

    report = _service(tmp_path).persist_selected_recipes(
        plan=existing_plan,
        selected_item_ids=(existing_plan.items[0].item_id,),
    )

    assert report.saved_recipe_count == 0
    assert report.reused_recipe_count == 1
    assert report.results[0].status == "reused_existing"
    store = ArtifactRecipeStore(historical_root=tmp_path)
    recipe = store.load_recipe(
        market=_market_from_plan(existing_plan),
        recipe_id=existing_plan.items[0].existing_recipe_id,
    )
    assert recipe.recipe_hash == existing_plan.items[0].existing_recipe_hash
    assert len(store.list_recipes(market=recipe.market)) == 1


def test_persistence_blocks_blocked_error_and_malformed_items(
    tmp_path: Path,
) -> None:
    plan = _unary_plan(tmp_path, count=1)
    unsupported = replace(plan.items[0], construct_key="braids")
    malformed = replace(
        plan.items[0],
        item_id=plan.items[0].item_id + "__malformed",
        expected_recipe_payload={"tool_type": "construct"},
    )
    blocked = replace(
        plan.items[0],
        item_id=plan.items[0].item_id + "__blocked",
        status="blocked",
        blockers=("blocked_by_test",),
    )
    error = replace(
        plan.items[0],
        item_id=plan.items[0].item_id + "__error",
        status="error",
        blockers=("error_by_test",),
    )
    missing_payload = replace(
        plan.items[0],
        item_id=plan.items[0].item_id + "__missing_payload",
        expected_recipe_payload=None,
    )
    modified_plan = replace(
        plan,
        items=(unsupported, malformed, blocked, error, missing_payload),
    )

    report = _service(tmp_path).persist_selected_recipes(
        plan=modified_plan,
        selected_item_ids=[item.item_id for item in modified_plan.items],
    )

    assert [result.status for result in report.results] == [
        "blocked",
        "failed",
        "blocked",
        "blocked",
        "blocked",
    ]
    assert report.saved_recipe_count == 0
    assert report.blocked_count == 4
    assert report.failed_count == 1


def test_collection_persistence_saves_ordered_collection(tmp_path: Path) -> None:
    plan = _unary_plan(tmp_path, count=2)
    selected_ids = tuple(item.item_id for item in reversed(plan.items))

    report = _service(tmp_path).persist_selected_recipes_as_collection(
        plan=plan,
        selected_item_ids=selected_ids,
        collection_name="Construct Batch Pack",
        collection_description="selected construct batch recipes",
    )

    assert report.collection_saved is True
    assert report.saved_recipe_count == 2
    assert report.collection_id
    collection = ArtifactRecipeCollectionStore(historical_root=tmp_path).load_collection(
        market=_market_from_plan(plan),
        collection_id=report.collection_id,
    )
    assert collection.display_name == "Construct Batch Pack"
    assert [recipe.recipe_id for recipe in collection.recipe_snapshots] == [
        result.recipe_id for result in report.results
    ]
    assert [result.item_id for result in report.results] == list(selected_ids)
    assert collection.metadata["generated_by"] == "construct_batch_builder"
    assert collection.metadata["selected_item_ids"] == list(selected_ids)


def test_collection_includes_reused_existing_recipe_snapshots(
    tmp_path: Path,
) -> None:
    existing_seed = _unary_plan(tmp_path, count=1)
    ArtifactRecipeStore(historical_root=tmp_path).save_recipe(
        existing_seed.items[0].expected_recipe_payload
    )
    existing_plan = _unary_plan(tmp_path, count=1)
    new_plan = _delta_plan(tmp_path)
    combined_plan = replace(
        existing_plan,
        batch_kind="unary",
        items=(existing_plan.items[0], new_plan.items[0]),
    )

    report = _service(tmp_path).persist_selected_recipes_as_collection(
        plan=combined_plan,
        selected_item_ids=(combined_plan.items[0].item_id, combined_plan.items[1].item_id),
        collection_name="Mixed Construct Batch Pack",
    )

    assert report.collection_saved is True
    assert [result.status for result in report.results] == ["reused_existing", "saved"]
    collection = ArtifactRecipeCollectionStore(historical_root=tmp_path).load_collection(
        market=_market_from_plan(combined_plan),
        collection_id=report.collection_id,
    )
    assert [recipe.recipe_id for recipe in collection.recipe_snapshots] == [
        result.recipe_id for result in report.results
    ]


def test_collection_is_blocked_when_name_blank_or_item_failed(
    tmp_path: Path,
) -> None:
    plan = _unary_plan(tmp_path, count=1)
    blank_report = _service(tmp_path).persist_selected_recipes_as_collection(
        plan=plan,
        selected_item_ids=(plan.items[0].item_id,),
        collection_name=" ",
    )
    assert blank_report.collection_saved is False
    assert "collection_name_required" in blank_report.collection_result.blockers

    blocked_item = replace(
        plan.items[0],
        item_id=plan.items[0].item_id + "__blocked",
        status="blocked",
        blockers=("blocked_by_test",),
    )
    blocked_plan = replace(plan, items=(plan.items[0], blocked_item))
    partial_report = _service(tmp_path).persist_selected_recipes_as_collection(
        plan=blocked_plan,
        selected_item_ids=(plan.items[0].item_id, blocked_item.item_id),
        collection_name="Partial Pack",
    )
    assert partial_report.saved_recipe_count + partial_report.reused_recipe_count == 1
    assert partial_report.blocked_count == 1
    assert partial_report.collection_saved is False
    assert "selected_item_persistence_not_complete" in partial_report.collection_result.blockers


def test_construct_batch_persistence_static_boundaries() -> None:
    source = Path(
        "src/leonardo/data/historical/data_manager_construct_batch_persistence.py"
    ).read_text(encoding="utf-8")

    forbidden = (
        "PySide",
        "leonardo.gui",
        "ArtifactCalculationService",
        "ArtifactRecipeExecutor",
        "ArtifactRecoveryRegenerator",
        "DataManagerSelectedUpdateService",
        "DataManagerUpdateService",
        "AnalysisDatabaseStore",
        "write_text",
        "write_bytes",
        "json.dump",
        "open(",
        ".to_csv(",
        "materialize_database",
        "build_database",
        "rebuild_database",
        "extend_database",
    )
    for token in forbidden:
        assert token not in source


def _market_from_plan(plan):
    return canonicalize(
        plan.exchange,
        plan.market_type,
        plan.symbol,
        plan.timeframe,
    )
