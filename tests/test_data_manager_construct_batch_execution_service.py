from __future__ import annotations

import json
from dataclasses import dataclass, replace
from pathlib import Path

from leonardo.data.historical.artifact_recipe_executor import (
    ArtifactRecipeExecutionItemReport,
    ArtifactRecipeExecutionReport,
)
from leonardo.data.historical.artifact_recipe_store import ArtifactRecipeStore
from leonardo.data.historical.data_manager_construct_batch_execution_service import (
    DataManagerConstructBatchExecutionService,
)
from leonardo.data.historical.data_manager_construct_batch_persistence import (
    ConstructBatchPersistenceItemResult,
    ConstructBatchPersistenceReport,
)
from leonardo.data.historical.data_manager_construct_batch_planner import (
    ConstructBatchSourceRef,
    ConstructDeltaBatchIntent,
    ConstructUnaryBatchIntent,
    DataManagerConstructBatchPlanner,
)


@dataclass(frozen=True)
class _FakeArtifactResult:
    saved_path: Path
    output_names: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "saved_path": str(self.saved_path),
            "output_names": list(self.output_names),
        }


class _FakeExecutor:
    def __init__(self, *, fail_recipe_ids: set[str] | None = None) -> None:
        self.calls: list[str] = []
        self.fail_recipe_ids = set(fail_recipe_ids or set())

    def execute_recipe(self, recipe):
        self.calls.append(recipe.recipe_id)
        if recipe.recipe_id in self.fail_recipe_ids:
            item = ArtifactRecipeExecutionItemReport(
                recipe_id=recipe.recipe_id,
                recipe_index=0,
                display_name=recipe.display_name,
                tool_type=recipe.tool_type,
                tool_key=recipe.tool_key,
                status="failed",
                error_text=f"planned failure for {recipe.recipe_id}",
            )
        else:
            item = ArtifactRecipeExecutionItemReport(
                recipe_id=recipe.recipe_id,
                recipe_index=0,
                display_name=recipe.display_name,
                tool_type=recipe.tool_type,
                tool_key=recipe.tool_key,
                status="succeeded",
                result=_FakeArtifactResult(
                    saved_path=Path(f"artifact_{recipe.recipe_id}.csv"),
                    output_names=recipe.output_names,
                ),
            )
        return ArtifactRecipeExecutionReport(
            market=recipe.market,
            collection_id=None,
            requested_recipe_ids=(recipe.recipe_id,),
            item_reports=(item,),
        )


class _FailingPersistenceService:
    def persist_selected_recipes(self, *, plan, selected_item_ids):
        item = plan.items[0]
        result = ConstructBatchPersistenceItemResult(
            item_id=item.item_id,
            status="failed",
            recipe_id=item.expected_recipe_id,
            recipe_hash=item.expected_recipe_hash,
            display_name=item.display_name,
            reason="persistence failed by test",
            blockers=("recipe_persistence_failed",),
        )
        return ConstructBatchPersistenceReport(
            batch_kind=plan.batch_kind,
            construct_key=plan.construct_key,
            selected_count=len(tuple(selected_item_ids)),
            saved_recipe_count=0,
            reused_recipe_count=0,
            skipped_count=0,
            blocked_count=0,
            failed_count=1,
            collection_saved=False,
            collection_id=None,
            collection_name=None,
            results=(result,),
        )


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


def test_execution_persists_planned_items_and_delegates_to_executor(
    tmp_path: Path,
) -> None:
    plan = _unary_plan(tmp_path, count=2)
    executor = _FakeExecutor()

    report = DataManagerConstructBatchExecutionService(
        historical_root=tmp_path,
        executor=executor,
    ).execute_selected_artifacts(
        plan=plan,
        selected_item_ids=[item.item_id for item in plan.items],
    )

    assert report.saved_recipe_count == 2
    assert report.reused_recipe_count == 0
    assert report.execution_attempted_count == 2
    assert report.completed_count == 2
    assert report.failed_count == 0
    assert [result.status for result in report.results] == ["completed", "completed"]
    assert executor.calls == [item.expected_recipe_id for item in plan.items]
    assert all(result.artifact_path for result in report.results)
    json.dumps(report.to_dict())


def test_execution_reuses_existing_recipe_and_delegates_once(
    tmp_path: Path,
) -> None:
    seed = _unary_plan(tmp_path, count=1)
    ArtifactRecipeStore(historical_root=tmp_path).save_recipe(
        seed.items[0].expected_recipe_payload
    )
    plan = _unary_plan(tmp_path, count=1)
    assert plan.items[0].status == "existing_recipe"
    executor = _FakeExecutor()

    report = DataManagerConstructBatchExecutionService(
        historical_root=tmp_path,
        executor=executor,
    ).execute_selected_artifacts(
        plan=plan,
        selected_item_ids=(plan.items[0].item_id,),
    )

    assert report.saved_recipe_count == 0
    assert report.reused_recipe_count == 1
    assert report.completed_count == 1
    assert executor.calls == [plan.items[0].existing_recipe_id]


def test_execution_blocks_blocked_error_and_unsupported_items(
    tmp_path: Path,
) -> None:
    plan = _unary_plan(tmp_path, count=1)
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
    unsupported = replace(
        plan.items[0],
        item_id=plan.items[0].item_id + "__unsupported",
        construct_key="braids",
    )
    modified_plan = replace(plan, items=(blocked, error, unsupported))
    executor = _FakeExecutor()

    report = DataManagerConstructBatchExecutionService(
        historical_root=tmp_path,
        executor=executor,
    ).execute_selected_artifacts(
        plan=modified_plan,
        selected_item_ids=[item.item_id for item in modified_plan.items],
    )

    assert [result.status for result in report.results] == [
        "blocked",
        "blocked",
        "blocked",
    ]
    assert report.execution_attempted_count == 0
    assert report.blocked_count == 3
    assert executor.calls == []


def test_persistence_failure_prevents_execution_attempt(
    tmp_path: Path,
) -> None:
    plan = _unary_plan(tmp_path, count=1)
    executor = _FakeExecutor()

    report = DataManagerConstructBatchExecutionService(
        historical_root=tmp_path,
        persistence_service=_FailingPersistenceService(),
        executor=executor,
    ).execute_selected_artifacts(
        plan=plan,
        selected_item_ids=(plan.items[0].item_id,),
    )

    assert report.failed_count == 1
    assert report.execution_attempted_count == 0
    assert report.results[0].status == "failed"
    assert "persistence failed" in report.results[0].reason
    assert executor.calls == []


def test_execution_partial_failure_continues_sequentially(
    tmp_path: Path,
) -> None:
    plan = _unary_plan(tmp_path, count=2)
    failing_recipe_id = plan.items[1].expected_recipe_id
    executor = _FakeExecutor(fail_recipe_ids={failing_recipe_id})

    report = DataManagerConstructBatchExecutionService(
        historical_root=tmp_path,
        executor=executor,
    ).execute_selected_artifacts(
        plan=plan,
        selected_item_ids=[item.item_id for item in plan.items],
    )

    assert [result.status for result in report.results] == ["completed", "failed"]
    assert report.completed_count == 1
    assert report.failed_count == 1
    assert report.execution_attempted_count == 2
    assert executor.calls == [item.expected_recipe_id for item in plan.items]


def test_execution_supports_delta_plan(tmp_path: Path) -> None:
    plan = _delta_plan(tmp_path)
    executor = _FakeExecutor()

    report = DataManagerConstructBatchExecutionService(
        historical_root=tmp_path,
        executor=executor,
    ).execute_selected_artifacts(
        plan=plan,
        selected_item_ids=(plan.items[0].item_id,),
    )

    assert report.construct_key == "delta"
    assert report.completed_count == 1
    assert executor.calls == [plan.items[0].expected_recipe_id]


def test_construct_batch_execution_service_static_boundaries() -> None:
    source = Path(
        "src/leonardo/data/historical/data_manager_construct_batch_execution_service.py"
    ).read_text(encoding="utf-8")

    forbidden = (
        "PySide",
        "leonardo.gui",
        "ArtifactCalculationService",
        "DataManagerSelectedUpdateService",
        "DataManagerUpdateService",
        "AnalysisDatabaseStore",
        "write_text",
        "write_bytes",
        "json.dump",
        "open(",
        ".to_csv(",
        "save_manifest",
        "materialize_database",
        "build_database",
        "rebuild_database",
        "extend_database",
    )
    for token in forbidden:
        assert token not in source

    assert "ArtifactRecipeExecutor" in source
    assert "execute_recipe(" in source
