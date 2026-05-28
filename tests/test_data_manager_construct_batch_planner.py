from __future__ import annotations

import json
from pathlib import Path

from leonardo.data.historical.artifact_recipe_store import ArtifactRecipeStore
from leonardo.data.historical.data_manager_construct_batch_planner import (
    ConstructBatchSourceRef,
    ConstructDeltaBatchIntent,
    ConstructUnaryBatchIntent,
    DataManagerConstructBatchPlanner,
)


def _planner(root: Path) -> DataManagerConstructBatchPlanner:
    return DataManagerConstructBatchPlanner(historical_root=root)


def _write_csv(path: Path, timestamps: tuple[int, ...], column_name: str) -> Path:
    lines = ["ts_ms," + column_name]
    lines.extend(f"{ts},{idx + 1}.0" for idx, ts in enumerate(timestamps))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _source(
    root: Path,
    *,
    source_id: str = "rsi_14",
    display_name: str | None = None,
    family: str = "indicator",
    column_name: str | None = None,
    source_token: str | None = None,
    timestamps: tuple[int, ...] = (1000, 2000, 3000),
    exchange: str = "bybit",
    market_type: str = "linear",
    symbol: str = "BTCUSDT",
    timeframe: str = "30m",
    selectable: bool = True,
    analysis_usable: bool = True,
    renderable: bool = True,
    write_file: bool = True,
    row_count: int | None = None,
) -> ConstructBatchSourceRef:
    column = column_name or source_id
    csv_path = None
    if write_file:
        csv_path = _write_csv(root / f"{source_id}.csv", timestamps, column)
    return ConstructBatchSourceRef(
        source_id=source_id,
        display_name=display_name or source_id,
        source_family=family,
        exchange=exchange,
        market_type=market_type,
        symbol=symbol,
        timeframe=timeframe,
        column_name=column,
        source_token=source_token or column,
        csv_path=csv_path,
        selectable=selectable,
        analysis_usable=analysis_usable,
        renderable=renderable,
        timestamp_key=None if write_file else "ts_ms",
        timestamp_values=None if write_file else timestamps,
        row_count=row_count,
    )


def _row_count_only_source(root: Path) -> ConstructBatchSourceRef:
    return ConstructBatchSourceRef(
        source_id="legacy",
        display_name="Legacy Source",
        source_family="indicator",
        exchange="bybit",
        market_type="linear",
        symbol="BTCUSDT",
        timeframe="30m",
        column_name="legacy",
        source_token="legacy",
        row_count=3,
    )


def test_unary_derivative_plans_three_sources_with_json_safe_report(
    tmp_path: Path,
) -> None:
    sources = tuple(
        _source(tmp_path, source_id=f"rsi_{idx}", column_name=f"rsi_{idx}")
        for idx in range(3)
    )

    plan = _planner(tmp_path).plan_unary_batch(
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

    assert plan.total_candidate_count == 3
    assert plan.planned_count == 3
    assert plan.blocked_count == 0
    assert {item.status for item in plan.items} == {"planned"}
    assert all(item.actionable for item in plan.items)
    assert all(item.expected_outputs for item in plan.items)
    json.dumps(plan.to_dict())


def test_unary_construct_params_are_reflected_in_recipe_preview(
    tmp_path: Path,
) -> None:
    source = _source(tmp_path, source_id="angle_src", column_name="angle_src")

    angle_plan = _planner(tmp_path).plan_unary_batch(
        ConstructUnaryBatchIntent(
            construct_key="angle",
            exchange="bybit",
            market_type="linear",
            symbol="BTCUSDT",
            timeframe="30m",
            sources=(source,),
            params={"unit": "rad"},
        )
    )
    assert angle_plan.items[0].expected_recipe_payload["params"]["source"] == "angle_src"
    assert angle_plan.items[0].expected_recipe_payload["params"]["unit"] == "rad"

    percent_plan = _planner(tmp_path).plan_unary_batch(
        ConstructUnaryBatchIntent(
            construct_key="percent_span_angle",
            exchange="bybit",
            market_type="linear",
            symbol="BTCUSDT",
            timeframe="30m",
            sources=(source,),
            params={"window": 21},
        )
    )
    percent_params = percent_plan.items[0].expected_recipe_payload["params"]
    assert percent_params["source_columns"] == ["angle_src"]
    assert percent_params["window"] == 21

    momentum_plan = _planner(tmp_path).plan_unary_batch(
        ConstructUnaryBatchIntent(
            construct_key="angle_momentum",
            exchange="bybit",
            market_type="linear",
            symbol="BTCUSDT",
            timeframe="30m",
            sources=(source,),
            params={"n": 5},
        )
    )
    momentum_params = momentum_plan.items[0].expected_recipe_payload["params"]
    assert momentum_params["source_columns"] == ["angle_src"]
    assert momentum_params["n"] == 5


def test_unary_blocks_unsupported_or_ineligible_sources(tmp_path: Path) -> None:
    valid = _source(tmp_path, source_id="valid")
    not_selectable = _source(
        tmp_path,
        source_id="hidden",
        selectable=False,
    )
    not_usable = _source(
        tmp_path,
        source_id="utility",
        analysis_usable=False,
    )
    not_renderable = _source(
        tmp_path,
        source_id="analysis_ok",
        renderable=False,
    )

    unsupported = _planner(tmp_path).plan_unary_batch(
        ConstructUnaryBatchIntent(
            construct_key="braids",
            exchange="bybit",
            market_type="linear",
            symbol="BTCUSDT",
            timeframe="30m",
            sources=(valid,),
        )
    )
    assert unsupported.items[0].status == "blocked"
    assert "Unsupported construct" in unsupported.items[0].blockers[0]

    plan = _planner(tmp_path).plan_unary_batch(
        ConstructUnaryBatchIntent(
            construct_key="derivative",
            exchange="bybit",
            market_type="linear",
            symbol="BTCUSDT",
            timeframe="30m",
            sources=(not_selectable, not_usable, not_renderable),
        )
    )

    by_id = {item.source_refs[0]["source_id"]: item for item in plan.items}
    assert by_id["hidden"].status == "blocked"
    assert by_id["utility"].status == "blocked"
    assert by_id["analysis_ok"].status == "planned"
    assert by_id["analysis_ok"].warnings


def test_unary_detects_existing_equivalent_recipe(tmp_path: Path) -> None:
    source = _source(tmp_path, source_id="rsi_existing")
    intent = ConstructUnaryBatchIntent(
        construct_key="derivative",
        exchange="bybit",
        market_type="linear",
        symbol="BTCUSDT",
        timeframe="30m",
        sources=(source,),
        params={"order": 1},
    )
    first_plan = _planner(tmp_path).plan_unary_batch(intent)
    ArtifactRecipeStore(historical_root=tmp_path).save_recipe(
        first_plan.items[0].expected_recipe_payload
    )

    second_plan = _planner(tmp_path).plan_unary_batch(intent)

    assert second_plan.existing_recipe_count == 1
    assert second_plan.items[0].status == "existing_recipe"
    assert second_plan.items[0].existing_recipe_id == second_plan.items[0].expected_recipe_id
    assert not second_plan.items[0].actionable


def test_delta_plans_minuend_and_subtrahend_directions(tmp_path: Path) -> None:
    fixed = _source(
        tmp_path,
        source_id="close",
        family="ohlc",
        column_name="close",
        write_file=False,
        timestamps=(1000, 2000, 3000),
    )
    variables = tuple(
        _source(
            tmp_path,
            source_id=f"rsi_{idx}",
            column_name=f"rsi_{idx}",
            write_file=False,
            timestamps=(1000, 2000, 3000),
        )
        for idx in range(3)
    )

    minuend_plan = _planner(tmp_path).plan_delta_batch(
        ConstructDeltaBatchIntent(
            exchange="bybit",
            market_type="linear",
            symbol="BTCUSDT",
            timeframe="30m",
            fixed_source=fixed,
            fixed_role="minuend",
            variable_sources=variables,
            params={"mode": "abs"},
        )
    )
    assert minuend_plan.planned_count == 3
    assert all(item.direction == "delta = minuend - subtrahend" for item in minuend_plan.items)
    assert minuend_plan.items[0].role_bindings["minuend"] == "close"
    assert minuend_plan.items[0].role_bindings["fast"] == "close"

    subtrahend_plan = _planner(tmp_path).plan_delta_batch(
        ConstructDeltaBatchIntent(
            exchange="bybit",
            market_type="linear",
            symbol="BTCUSDT",
            timeframe="30m",
            fixed_source=fixed,
            fixed_role="subtrahend",
            variable_sources=variables,
            params={"mode": "pct"},
        )
    )
    assert subtrahend_plan.planned_count == 3
    assert subtrahend_plan.items[0].role_bindings["subtrahend"] == "close"
    assert subtrahend_plan.items[0].role_bindings["slow"] == "close"
    assert subtrahend_plan.items[0].expected_outputs


def test_delta_blocks_same_source_cross_market_and_missing_alignment(
    tmp_path: Path,
) -> None:
    fixed = _source(
        tmp_path,
        source_id="close",
        family="ohlc",
        column_name="close",
        write_file=False,
        timestamps=(1000, 2000, 3000),
    )
    same = fixed
    cross_market = _source(
        tmp_path,
        source_id="eth_rsi",
        symbol="ETHUSDT",
        write_file=False,
        timestamps=(1000, 2000, 3000),
    )
    row_count_only = _row_count_only_source(tmp_path)
    no_overlap = _source(
        tmp_path,
        source_id="late_rsi",
        write_file=False,
        timestamps=(4000, 5000, 6000),
    )
    duplicate_ts = _source(
        tmp_path,
        source_id="dupe_rsi",
        write_file=False,
        timestamps=(1000, 1000, 2000),
    )

    plan = _planner(tmp_path).plan_delta_batch(
        ConstructDeltaBatchIntent(
            exchange="bybit",
            market_type="linear",
            symbol="BTCUSDT",
            timeframe="30m",
            fixed_source=fixed,
            fixed_role="minuend",
            variable_sources=(same, cross_market, row_count_only, no_overlap, duplicate_ts),
        )
    )

    by_id = {item.source_refs[1]["source_id"]: item for item in plan.items}
    assert by_id["close"].status == "blocked"
    assert any("itself" in blocker for blocker in by_id["close"].blockers)
    assert by_id["eth_rsi"].status == "blocked"
    assert any("market identity" in blocker for blocker in by_id["eth_rsi"].blockers)
    assert by_id["legacy"].status == "blocked"
    assert any("Row count alone" in blocker for blocker in by_id["legacy"].blockers)
    assert by_id["late_rsi"].status == "blocked"
    assert any("no common timestamp range" in blocker for blocker in by_id["late_rsi"].blockers)
    assert by_id["dupe_rsi"].status == "blocked"
    assert any("duplicate timestamp" in blocker.lower() for blocker in by_id["dupe_rsi"].blockers)


def test_delta_computes_common_range_and_detects_existing_recipe(tmp_path: Path) -> None:
    fixed = _source(
        tmp_path,
        source_id="close_existing",
        family="ohlc",
        column_name="close",
        write_file=False,
        timestamps=(1000, 2000, 3000, 4000),
    )
    variable = _source(
        tmp_path,
        source_id="rsi_existing_delta",
        write_file=False,
        timestamps=(2000, 3000, 4000, 5000),
    )
    intent = ConstructDeltaBatchIntent(
        exchange="bybit",
        market_type="linear",
        symbol="BTCUSDT",
        timeframe="30m",
        fixed_source=fixed,
        fixed_role="minuend",
        variable_sources=(variable,),
        params={"mode": "abs"},
    )
    first_plan = _planner(tmp_path).plan_delta_batch(intent)
    item = first_plan.items[0]
    assert item.status == "planned"
    assert item.alignment_summary.common_first_ts_ms == 2000
    assert item.alignment_summary.common_last_ts_ms == 4000
    assert item.alignment_summary.aligned_row_count == 3

    ArtifactRecipeStore(historical_root=tmp_path).save_recipe(
        item.expected_recipe_payload
    )
    second_plan = _planner(tmp_path).plan_delta_batch(intent)

    assert second_plan.items[0].status == "existing_recipe"
    assert second_plan.items[0].existing_recipe_id == item.expected_recipe_id


def test_construct_batch_planner_static_boundaries() -> None:
    source = Path(
        "src/leonardo/data/historical/data_manager_construct_batch_planner.py"
    ).read_text(encoding="utf-8")

    forbidden = (
        "PySide",
        "leonardo.gui",
        "write_text",
        "write_bytes",
        "json.dump",
        ".to_csv(",
        "save_recipe(",
        "save_collection(",
        "calculate",
        "materialize_database(",
        "execute_update_plan",
        "DataManagerSelectedUpdateService",
        "DataManagerUpdateService",
    )
    for token in forbidden:
        assert token not in source
