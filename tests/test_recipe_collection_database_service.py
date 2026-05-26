from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pandas as pd

from leonardo.data.historical.analysis_database_contracts import (
    AnalysisDatabaseMaterialization,
)
from leonardo.data.historical.analysis_database_store import AnalysisDatabaseStore
from leonardo.data.historical.artifact_metadata_contracts import ArtifactMetadataEntry
from leonardo.data.historical.artifact_recipe_collection_store import (
    ArtifactRecipeCollectionStore,
)
from leonardo.data.historical.artifact_recipe_store import ArtifactRecipe, ArtifactRecipeStore
from leonardo.data.historical.artifact_recovery_planner import ArtifactRecoveryPlanner
from leonardo.data.historical.derived_store_csv import DerivedCsvStore
from leonardo.data.historical.paths import HistoricalPaths
from leonardo.data.historical.recipe_collection_database_planner import (
    RecipeCollectionDatabasePlanner,
    RecipeCollectionDatabasePlan,
)
from leonardo.data.historical.recipe_collection_database_service import (
    RecipeCollectionDatabaseService,
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


def _kind_for_recipe(recipe: ArtifactRecipe) -> str:
    if recipe.tool_type == "indicator":
        return "indicators"
    if recipe.tool_type == "oscillator":
        return "oscillators"
    if recipe.tool_type == "construct":
        return "constructs"
    raise AssertionError(f"Unsupported test recipe tool type: {recipe.tool_type}")


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


def _save_artifact(root: Path, recipe: ArtifactRecipe) -> Path:
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
        params=dict(recipe.params),
        params_status="explicit",
        bindings=dict(recipe.input_bindings),
        bindings_status="unknown",
        metadata=_source_snapshot_entry(root, recipe.market),
    )


def _plan(root: Path, *recipes: ArtifactRecipe) -> RecipeCollectionDatabasePlan:
    collection = _collection(root, *recipes)
    return RecipeCollectionDatabasePlanner(
        historical_root=root
    ).plan_collection_components(collection)


def _ready_recipe(
    root: Path,
    market,
    *,
    tool_key: str = "rsi",
    tool_title: str = "RSI",
    tool_type: str = "oscillator",
    params: dict[str, object] | None = None,
    output_names: tuple[str, ...] = ("rsi_14",),
) -> ArtifactRecipe:
    recipe = _recipe(
        root,
        _payload(
            market,
            tool_type=tool_type,
            tool_key=tool_key,
            tool_title=tool_title,
            params=params,
            output_names=output_names,
        ),
    )
    _save_artifact(root, recipe)
    return recipe


def _create_report(tmp_path: Path, plan: RecipeCollectionDatabasePlan, **kwargs):
    return RecipeCollectionDatabaseService(
        historical_root=tmp_path
    ).create_database_from_plan(
        plan,
        display_name=kwargs.pop("display_name", "BTCUSDT_30m_from_collection"),
        **kwargs,
    )


def test_create_database_from_resolved_plan_saves_draft_without_dataframe(tmp_path: Path) -> None:
    market, _ohlcv = _write_ohlcv(tmp_path)
    recipe = _ready_recipe(tmp_path, market)
    plan = _plan(tmp_path, recipe)

    report = _create_report(tmp_path, plan, description="Created from collection.")

    store = AnalysisDatabaseStore(historical_root=tmp_path)
    manifest = store.load_manifest(market=market, database_id=report.database_id)
    assert report.status == "created"
    assert manifest.status == "draft"
    assert manifest.materialization is None
    assert manifest.dataframe_filename is None
    assert not store.dataframe_path(market=market, database_id=manifest.database_id).exists()
    assert [column.db_column_name for column in manifest.feature_columns] == [
        plan.resolved_components[0].column_previews[0]["db_column_name"]
    ]


def test_create_blocks_when_plan_has_no_resolved_components(tmp_path: Path) -> None:
    market, _ohlcv = _write_ohlcv(tmp_path)
    recipe = _recipe(tmp_path, _payload(market))
    plan = _plan(tmp_path, recipe)

    report = _create_report(tmp_path, plan)

    assert report.status == "blocked"
    assert any(blocker.code == "no_resolved_components" for blocker in report.blockers)


def test_create_blocks_on_duplicate_planned_columns(tmp_path: Path) -> None:
    market, _ohlcv = _write_ohlcv(tmp_path)
    recipe = _ready_recipe(
        tmp_path,
        market,
        output_names=("duplicate-column", "duplicate_column"),
    )
    plan = _plan(tmp_path, recipe)

    report = _create_report(tmp_path, plan)

    assert report.status == "blocked"
    assert any(blocker.code == "duplicate_planned_columns" for blocker in report.blockers)


def test_create_uses_ohlc_only_base_when_volume_artifact_present_by_default(
    tmp_path: Path,
) -> None:
    market, _ohlcv = _write_ohlcv(tmp_path)
    recipe = _ready_recipe(
        tmp_path,
        market,
        tool_key="volume",
        tool_title="Volume",
        params={"period": 20},
        output_names=("volume", "volume_mean_20"),
    )
    plan = _plan(tmp_path, recipe)

    report = _create_report(tmp_path, plan)

    manifest = AnalysisDatabaseStore(historical_root=tmp_path).load_manifest(
        market=market,
        database_id=report.database_id,
    )
    raw_volume = next(column for column in manifest.base_columns if column.source_column_name == "volume")
    assert raw_volume.selected is False
    assert any(
        warning.code == "raw_volume_omitted_due_to_volume_artifact"
        for warning in report.warnings
    )


def test_create_includes_raw_volume_when_explicitly_requested(tmp_path: Path) -> None:
    market, _ohlcv = _write_ohlcv(tmp_path)
    recipe = _ready_recipe(
        tmp_path,
        market,
        tool_key="volume",
        tool_title="Volume",
        params={"period": 20},
        output_names=("volume", "volume_mean_20"),
    )
    plan = _plan(tmp_path, recipe)

    report = _create_report(tmp_path, plan, include_raw_volume=True)

    manifest = AnalysisDatabaseStore(historical_root=tmp_path).load_manifest(
        market=market,
        database_id=report.database_id,
    )
    raw_volume = next(column for column in manifest.base_columns if column.source_column_name == "volume")
    assert raw_volume.selected is True
    assert report.geography_report["semantic_volume_duplication"] is True


def test_create_report_includes_geography_report(tmp_path: Path) -> None:
    market, _ohlcv = _write_ohlcv(tmp_path)
    recipe = _ready_recipe(tmp_path, market)
    plan = _plan(tmp_path, recipe)

    report = _create_report(tmp_path, plan)

    assert report.geography_report is not None
    assert "ohlc_base" in report.geography_report["present_keys"]


def test_create_skips_blocked_plan_items(tmp_path: Path) -> None:
    market, _ohlcv = _write_ohlcv(tmp_path)
    ready = _ready_recipe(tmp_path, market)
    missing = _recipe(
        tmp_path,
        _payload(market, params={"period": 21}, output_names=("rsi_21",)),
    )
    plan = _plan(tmp_path, ready, missing)

    report = _create_report(tmp_path, plan)

    manifest = AnalysisDatabaseStore(historical_root=tmp_path).load_manifest(
        market=market,
        database_id=report.database_id,
    )
    assert report.status == "created"
    assert report.skipped_component_count == 1
    assert len(manifest.feature_columns) == 1
    assert any(warning.code == "blocked_plan_items_skipped" for warning in report.warnings)


def test_create_preserves_resolved_component_order(tmp_path: Path) -> None:
    market, _ohlcv = _write_ohlcv(tmp_path)
    first = _ready_recipe(
        tmp_path,
        market,
        params={"period": 14},
        output_names=("rsi_14",),
    )
    second = _ready_recipe(
        tmp_path,
        market,
        params={"period": 21},
        output_names=("rsi_21",),
    )
    plan = _plan(tmp_path, second, first)

    report = _create_report(tmp_path, plan)

    manifest = AnalysisDatabaseStore(historical_root=tmp_path).load_manifest(
        market=market,
        database_id=report.database_id,
    )
    assert [column.source_column_name for column in manifest.feature_columns] == [
        "rsi_21",
        "rsi_14",
    ]


def test_extend_appends_components_and_preserves_existing_components(tmp_path: Path) -> None:
    market, _ohlcv = _write_ohlcv(tmp_path)
    first = _ready_recipe(tmp_path, market, output_names=("rsi_14",))
    first_plan = _plan(tmp_path, first)
    create_report = _create_report(tmp_path, first_plan)
    second = _ready_recipe(
        tmp_path,
        market,
        params={"period": 21},
        output_names=("rsi_21",),
    )
    second_plan = _plan(tmp_path, second)

    report = RecipeCollectionDatabaseService(
        historical_root=tmp_path
    ).extend_database_from_plan(
        second_plan,
        database_id=create_report.database_id,
    )

    manifest = AnalysisDatabaseStore(historical_root=tmp_path).load_manifest(
        market=market,
        database_id=create_report.database_id,
    )
    assert report.status == "extended"
    assert [column.source_column_name for column in manifest.feature_columns] == [
        "rsi_14",
        "rsi_21",
    ]


def test_extend_resets_materialization_state_through_editor(tmp_path: Path) -> None:
    market, _ohlcv = _write_ohlcv(tmp_path)
    first = _ready_recipe(tmp_path, market, output_names=("rsi_14",))
    create_report = _create_report(tmp_path, _plan(tmp_path, first))
    store = AnalysisDatabaseStore(historical_root=tmp_path)
    manifest = store.load_manifest(market=market, database_id=create_report.database_id)
    materialized_like = replace(
        manifest,
        status="materialized",
        dataframe_filename="dataframe.csv",
        materialization=AnalysisDatabaseMaterialization(
            row_count=2,
            column_count=6,
            first_ts_ms=1_700_000_000_000,
            last_ts_ms=1_700_001_800_000,
            dataframe_sha256="abc123",
            created_at_ms=1,
            updated_at_ms=1,
        ),
    )
    store.save_manifest(materialized_like)
    second = _ready_recipe(
        tmp_path,
        market,
        params={"period": 21},
        output_names=("rsi_21",),
    )

    report = RecipeCollectionDatabaseService(
        historical_root=tmp_path
    ).extend_database_from_plan(
        _plan(tmp_path, second),
        database_id=create_report.database_id,
    )

    updated = store.load_manifest(market=market, database_id=create_report.database_id)
    assert report.status == "extended"
    assert updated.status == "draft"
    assert updated.materialization is None
    assert updated.dataframe_filename is None


def test_extend_blocks_on_market_mismatch(tmp_path: Path) -> None:
    market, _ohlcv = _write_ohlcv(tmp_path)
    other_market, _other_ohlcv = _write_ohlcv(tmp_path, market=_market("ETHUSDT"))
    first = _ready_recipe(tmp_path, market)
    create_report = _create_report(tmp_path, _plan(tmp_path, first))
    other_recipe = _ready_recipe(tmp_path, other_market)
    other_plan = _plan(tmp_path, other_recipe)

    report = RecipeCollectionDatabaseService(
        historical_root=tmp_path
    ).extend_database_from_plan(
        other_plan,
        database_id=create_report.database_id,
    )

    assert report.status == "blocked"
    assert any(blocker.code == "market_mismatch" for blocker in report.blockers)


def test_extend_blocks_duplicate_existing_database_column(tmp_path: Path) -> None:
    market, _ohlcv = _write_ohlcv(tmp_path)
    recipe = _ready_recipe(tmp_path, market)
    plan = _plan(tmp_path, recipe)
    create_report = _create_report(tmp_path, plan)

    report = RecipeCollectionDatabaseService(
        historical_root=tmp_path
    ).extend_database_from_plan(
        plan,
        database_id=create_report.database_id,
    )

    assert report.status == "blocked"
    assert any(
        blocker.code == "duplicate_existing_db_columns" for blocker in report.blockers
    )


def test_require_geography_complete_blocks_before_create_save(tmp_path: Path) -> None:
    market, _ohlcv = _write_ohlcv(tmp_path)
    recipe = _ready_recipe(tmp_path, market)
    plan = _plan(tmp_path, recipe)

    report = _create_report(tmp_path, plan, require_geography_complete=True)

    assert report.status == "blocked"
    assert any(blocker.code == "geography_incomplete" for blocker in report.blockers)
    assert AnalysisDatabaseStore(historical_root=tmp_path).list_databases(market=market) == []


def test_report_to_dict_is_json_safe(tmp_path: Path) -> None:
    market, _ohlcv = _write_ohlcv(tmp_path)
    recipe = _ready_recipe(tmp_path, market)
    plan = _plan(tmp_path, recipe)

    report = _create_report(tmp_path, plan)
    payload = report.to_dict()

    assert payload["status"] == "created"
    json.dumps(payload, sort_keys=True)
