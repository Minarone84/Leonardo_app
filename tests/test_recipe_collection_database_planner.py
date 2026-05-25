from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

from leonardo.data.historical.artifact_metadata_contracts import ArtifactMetadataEntry
from leonardo.data.historical.artifact_recipe_collection_store import (
    ArtifactRecipeCollectionStore,
)
from leonardo.data.historical.artifact_recipe_store import ArtifactRecipe, ArtifactRecipeStore
from leonardo.data.historical.artifact_recovery_planner import (
    ArtifactRecoveryItemReport,
    ArtifactRecoveryPlanner,
    ArtifactRecoveryReport,
)
from leonardo.data.historical.derived_store_csv import DerivedCsvStore
from leonardo.data.historical.paths import HistoricalPaths
from leonardo.data.historical.recipe_collection_database_planner import (
    RecipeCollectionDatabasePlanner,
)
from leonardo.data.historical.source_ohlcv_provenance import (
    SOURCE_OHLCV_PROVENANCE_KEY,
    SOURCE_OHLCV_PROVENANCE_NAMESPACE,
    build_source_ohlcv_provenance_snapshot,
)
from leonardo.data.historical.store_csv import Candle, CsvOHLCVStore
from leonardo.data.naming import canonicalize


def _market(symbol: str = "BTCUSDT"):
    return canonicalize("bybit", "linear", symbol, "30m")


def _write_ohlcv(root: Path, *, market=None, rows: int = 20):
    market = _market() if market is None else market
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
    store = CsvOHLCVStore()
    store.write_atomic(csv_path, candles, market=market)
    store.record_validation_result(
        csv_path,
        market=market,
        status="ok",
        row_count=len(candles),
        issues=(),
        validator="HistoricalDatasetValidator",
    )
    return market, csv_path


def _payload(
    market,
    *,
    tool_type: str = "oscillator",
    tool_key: str = "rsi",
    tool_title: str = "RSI",
    params: dict[str, object] | None = None,
    output_names: tuple[str, ...] = ("rsi_14",),
) -> dict[str, object]:
    params = {"period": 14} if params is None else dict(params)
    return {
        "tool_type": tool_type,
        "tool_key": tool_key,
        "tool_title": tool_title,
        "exchange": market.exchange,
        "market_type": market.market_type,
        "symbol": market.symbol,
        "timeframe": market.timeframe,
        "params": params,
        "input_bindings": {},
        "input_binding_meta": {},
        "required_inputs": ["close"],
        "output_names": list(output_names),
        "output_signals": [
            {
                "name": name,
                "signal_type": "signal",
                "renderable": True,
                "analysis_usable": True,
                "default_visible": True,
            }
            for name in output_names
        ],
    }


def _recipe(root: Path, payload: dict[str, object]) -> ArtifactRecipe:
    return ArtifactRecipeStore(historical_root=root).save_recipe(payload)


def _collection(root: Path, *recipes: ArtifactRecipe):
    store = ArtifactRecipeCollectionStore(historical_root=root)
    return store.save_collection(
        store.build_collection(
            market=recipes[0].market,
            display_name="Database Component Pack",
            recipes=recipes,
            source_database_id="adb__source__h12345678",
        )
    )


def _source_snapshot_entry(root: Path, market) -> tuple[ArtifactMetadataEntry, ...]:
    return (
        ArtifactMetadataEntry(
            namespace=SOURCE_OHLCV_PROVENANCE_NAMESPACE,
            key=SOURCE_OHLCV_PROVENANCE_KEY,
            value=build_source_ohlcv_provenance_snapshot(
                historical_root=root,
                market=market,
            ),
        ),
    )


def _kind_for_recipe(recipe: ArtifactRecipe) -> str:
    if recipe.tool_type == "indicator":
        return "indicators"
    if recipe.tool_type == "oscillator":
        return "oscillators"
    if recipe.tool_type == "construct":
        return "constructs"
    raise AssertionError(f"Unsupported test recipe tool type: {recipe.tool_type}")


def _save_artifact(
    root: Path,
    recipe: ArtifactRecipe,
    *,
    params: dict[str, object] | None = None,
    include_source_snapshot: bool = True,
) -> Path:
    planner = ArtifactRecoveryPlanner(historical_root=root)
    instance_key = planner.expected_instance_key(recipe)
    rows: dict[str, object] = {"ts_ms": [1_700_000_000_000, 1_700_001_800_000]}
    for index, name in enumerate(recipe.output_names):
        rows[name] = [float(index + 1), float(index + 2)]
    return DerivedCsvStore(historical_root=root).save_dataframe(
        market=recipe.market,
        kind=_kind_for_recipe(recipe),  # type: ignore[arg-type]
        tool_key=recipe.tool_key,
        instance_key=instance_key,
        df=pd.DataFrame(rows),
        params=dict(recipe.params) if params is None else dict(params),
        params_status="explicit",
        bindings=dict(recipe.input_bindings),
        bindings_status="unknown",
        metadata=(
            _source_snapshot_entry(root, recipe.market) if include_source_snapshot else ()
        ),
    )


def test_up_to_date_recipe_artifact_resolves_to_component_preview(tmp_path: Path) -> None:
    market, _ohlcv_path = _write_ohlcv(tmp_path)
    recipe = _recipe(tmp_path, _payload(market))
    _save_artifact(tmp_path, recipe)
    collection = _collection(tmp_path, recipe)

    plan = RecipeCollectionDatabasePlanner(
        historical_root=tmp_path
    ).plan_collection_components(collection)

    assert plan.summary["resolved"] == 1
    assert plan.blocked_items == ()
    component = plan.resolved_components[0]
    assert component.recipe_id == recipe.recipe_id
    assert component.tool_key == "rsi"
    assert component.storage_family == "oscillators"
    assert component.source_preview["tool_key"] == "rsi"
    assert component.source_preview["instance_key"] == component.instance_key
    assert component.artifact_relpath.startswith("oscillators/")
    assert component.column_previews[0]["source_column_name"] == "rsi_14"
    assert component.column_previews[0]["db_column_name"].endswith("__rsi_14")


def test_missing_artifact_is_blocked_without_preview(tmp_path: Path) -> None:
    market, _ohlcv_path = _write_ohlcv(tmp_path)
    recipe = _recipe(tmp_path, _payload(market))
    collection = _collection(tmp_path, recipe)

    plan = RecipeCollectionDatabasePlanner(
        historical_root=tmp_path
    ).plan_collection_components(collection)

    assert plan.resolved_components == ()
    assert plan.blocked_items[0].reason == "artifact_missing"
    assert plan.blocked_items[0].metadata["actionable"] is True


def test_stale_artifact_is_blocked_without_preview(tmp_path: Path) -> None:
    market, _ohlcv_path = _write_ohlcv(tmp_path)
    recipe = _recipe(tmp_path, _payload(market))
    _save_artifact(tmp_path, recipe, params={"period": 21})
    collection = _collection(tmp_path, recipe)

    plan = RecipeCollectionDatabasePlanner(
        historical_root=tmp_path
    ).plan_collection_components(collection)

    assert plan.resolved_components == ()
    assert plan.blocked_items[0].reason == "artifact_stale"


def test_freshness_unknown_artifact_is_blocked_without_preview(tmp_path: Path) -> None:
    market, _ohlcv_path = _write_ohlcv(tmp_path)
    recipe = _recipe(tmp_path, _payload(market))
    _save_artifact(tmp_path, recipe, include_source_snapshot=False)
    collection = _collection(tmp_path, recipe)

    plan = RecipeCollectionDatabasePlanner(
        historical_root=tmp_path
    ).plan_collection_components(collection)

    assert plan.resolved_components == ()
    assert plan.blocked_items[0].reason == "freshness_unknown"


def test_blocked_current_ohlcv_artifact_is_blocked_without_preview(tmp_path: Path) -> None:
    market = _market()
    recipe = _recipe(tmp_path, _payload(market))
    collection = _collection(tmp_path, recipe)

    plan = RecipeCollectionDatabasePlanner(
        historical_root=tmp_path
    ).plan_collection_components(collection)

    assert plan.resolved_components == ()
    assert plan.blocked_items[0].reason == "artifact_blocked"
    assert plan.blocked_items[0].status == "blocked"


def test_collection_order_is_preserved_in_resolved_components(tmp_path: Path) -> None:
    market, _ohlcv_path = _write_ohlcv(tmp_path)
    first = _recipe(
        tmp_path,
        _payload(market, params={"period": 14}, output_names=("rsi_14",)),
    )
    second = _recipe(
        tmp_path,
        _payload(market, params={"period": 21}, output_names=("rsi_21",)),
    )
    _save_artifact(tmp_path, first)
    _save_artifact(tmp_path, second)
    collection = _collection(tmp_path, second, first)

    plan = RecipeCollectionDatabasePlanner(
        historical_root=tmp_path
    ).plan_collection_components(collection)

    assert [component.recipe_id for component in plan.resolved_components] == [
        second.recipe_id,
        first.recipe_id,
    ]


def test_duplicate_planned_database_columns_are_reported(tmp_path: Path) -> None:
    market, _ohlcv_path = _write_ohlcv(tmp_path)
    recipe = _recipe(
        tmp_path,
        _payload(
            market,
            output_names=("duplicate-column", "duplicate_column"),
        ),
    )
    _save_artifact(tmp_path, recipe)
    collection = _collection(tmp_path, recipe)

    plan = RecipeCollectionDatabasePlanner(
        historical_root=tmp_path
    ).plan_collection_components(collection)

    assert len(plan.resolved_components) == 1
    assert plan.duplicate_columns == (
        "oscillator__rsi__rsi_default_period_14__duplicate_column",
    )
    assert any(warning.code == "duplicate_planned_db_columns" for warning in plan.warnings)


def test_cross_market_mismatch_is_blocked(tmp_path: Path) -> None:
    market, _ohlcv_path = _write_ohlcv(tmp_path)
    other_market, _other_ohlcv_path = _write_ohlcv(tmp_path, market=_market("ETHUSDT"))
    recipe = _recipe(tmp_path, _payload(market))
    other_recipe = _recipe(tmp_path, _payload(other_market))
    other_path = _save_artifact(tmp_path, other_recipe)
    collection = _collection(tmp_path, recipe)
    item = ArtifactRecoveryItemReport(
        recipe_id=recipe.recipe_id,
        recipe_index=0,
        display_name=recipe.display_name,
        tool_type=recipe.tool_type,
        tool_key=recipe.tool_key,
        expected_kind="oscillators",
        expected_instance_key=ArtifactRecoveryPlanner(
            historical_root=tmp_path
        ).expected_instance_key(recipe),
        expected_csv_path=other_path,
        expected_metadata_path=DerivedCsvStore(
            historical_root=tmp_path
        ).resolve_metadata_path(
            market=other_market,
            kind="oscillators",
            tool_key=other_recipe.tool_key,
            instance_key=ArtifactRecoveryPlanner(
                historical_root=tmp_path
            ).expected_instance_key(other_recipe),
        ),
        expected_output_names=recipe.output_names,
        status="up_to_date",
        can_recalculate=True,
        existing_csv=True,
        existing_metadata=True,
    )
    fake_recovery = SimpleNamespace(
        plan_collection=lambda _collection: ArtifactRecoveryReport(
            market=market,
            collection_id=collection.collection_id,
            collection_display_name=collection.display_name,
            requested_recipe_ids=(recipe.recipe_id,),
            items=(item,),
        )
    )

    plan = RecipeCollectionDatabasePlanner(
        historical_root=tmp_path,
        recovery_planner=fake_recovery,  # type: ignore[arg-type]
    ).plan_collection_components(collection)

    assert plan.resolved_components == ()
    assert plan.blocked_items[0].reason == "market_mismatch"


def test_actionable_not_current_artifact_does_not_generate_preview(tmp_path: Path) -> None:
    market, _ohlcv_path = _write_ohlcv(tmp_path)
    recipe = _recipe(tmp_path, _payload(market))
    collection = _collection(tmp_path, recipe)

    plan = RecipeCollectionDatabasePlanner(
        historical_root=tmp_path
    ).plan_collection_components(collection)

    assert plan.blocked_items[0].metadata["actionable"] is True
    assert plan.resolved_components == ()


def test_geography_report_is_included_for_planned_components(tmp_path: Path) -> None:
    market, _ohlcv_path = _write_ohlcv(tmp_path)
    recipe = _recipe(
        tmp_path,
        _payload(
            market,
            tool_key="volume",
            tool_title="Volume",
            params={"period": 20},
            output_names=("volume", "volume_mean_20"),
        ),
    )
    _save_artifact(tmp_path, recipe)
    collection = _collection(tmp_path, recipe)

    plan = RecipeCollectionDatabasePlanner(
        historical_root=tmp_path
    ).plan_collection_components(collection)

    assert plan.geography_report is not None
    assert "volume_artifact" in plan.geography_report["present_keys"]
    assert "ohlc_base" in plan.geography_report["missing_keys"]


def test_plan_to_dict_is_json_safe(tmp_path: Path) -> None:
    market, _ohlcv_path = _write_ohlcv(tmp_path)
    recipe = _recipe(tmp_path, _payload(market))
    _save_artifact(tmp_path, recipe)
    collection = _collection(tmp_path, recipe)

    plan = RecipeCollectionDatabasePlanner(
        historical_root=tmp_path
    ).plan_collection_components(collection)
    payload = plan.to_dict()

    assert payload["summary"]["resolved"] == 1
    json.dumps(payload, sort_keys=True)
