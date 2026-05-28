from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

from leonardo.data.historical.analysis_database_contracts import (
    AnalysisDatabaseColumn,
    AnalysisFeatureSource,
)
from leonardo.data.historical.analysis_database_naming import (
    build_database_column_name,
    build_feature_source_id,
)
from leonardo.data.historical.analysis_database_store import AnalysisDatabaseStore
from leonardo.data.historical.artifact_metadata_contracts import ArtifactMetadataEntry
from leonardo.data.historical.artifact_recipe_store import (
    ArtifactRecipe,
    ArtifactRecipeStore,
    artifact_recipe_metadata_entries,
)
from leonardo.data.historical.data_manager_selected_update_service import (
    DataManagerSelectedUpdateService,
    SelectedAnalysisDatabaseUpdateRef,
    SelectedArtifactUpdateRef,
    SelectedUpdateAction,
)
from leonardo.data.historical.derived_store_csv import DerivedCsvStore
from leonardo.data.historical.paths import HistoricalPaths
from leonardo.data.historical.source_ohlcv_provenance import (
    SOURCE_OHLCV_PROVENANCE_KEY,
    SOURCE_OHLCV_PROVENANCE_NAMESPACE,
    build_source_ohlcv_provenance_snapshot,
)
from leonardo.data.historical.store_csv import Candle, CsvOHLCVStore
from leonardo.data.naming import canonicalize


def _market():
    return canonicalize("bybit", "linear", "BTCUSDT", "30m")


def _issues_for_status(status: str) -> tuple[tuple[str, str], ...]:
    if status == "error":
        return (("error", "test validation error"),)
    if status == "warning":
        return (("warning", "test validation warning"),)
    return ()


def _write_ohlcv(
    root: Path,
    *,
    validation_status: str = "ok",
    price_offset: float = 0.0,
) -> Path:
    market = _market()
    paths = HistoricalPaths(root=root)
    store = CsvOHLCVStore()
    path = store.file_path(paths.ensure_ohlcv_dir(market))
    candles = [
        Candle(1000, 1.0 + price_offset, 1.5 + price_offset, 0.5 + price_offset, 1.2 + price_offset, 10.0),
        Candle(2000, 2.0 + price_offset, 2.5 + price_offset, 1.5 + price_offset, 2.2 + price_offset, 20.0),
        Candle(3000, 3.0 + price_offset, 3.5 + price_offset, 2.5 + price_offset, 3.2 + price_offset, 30.0),
    ]
    store.write_atomic(path, candles, market=market)
    store.record_validation_result(
        path,
        market=market,
        status=validation_status,
        row_count=len(candles),
        issues=_issues_for_status(validation_status),
        validator="HistoricalDatasetValidator",
    )
    return path


def _rsi_payload(*, period: int = 14) -> dict[str, object]:
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
            }
        ],
    }


def _recipe(root: Path, *, period: int = 14) -> ArtifactRecipe:
    return ArtifactRecipeStore(historical_root=root).save_recipe(
        _rsi_payload(period=period),
    )


def _source_ohlcv_metadata(root: Path, recipe: ArtifactRecipe) -> tuple[ArtifactMetadataEntry, ...]:
    return (
        ArtifactMetadataEntry(
            namespace=SOURCE_OHLCV_PROVENANCE_NAMESPACE,
            key=SOURCE_OHLCV_PROVENANCE_KEY,
            value=build_source_ohlcv_provenance_snapshot(
                historical_root=root,
                market=recipe.market,
            ),
        ),
    )


def _save_rsi_artifact(
    root: Path,
    recipe: ArtifactRecipe,
    *,
    include_recipe_metadata: bool = True,
    include_source_snapshot: bool = True,
) -> Path:
    period = int(recipe.params["period"])
    metadata: tuple[ArtifactMetadataEntry, ...] = ()
    if include_recipe_metadata:
        metadata += artifact_recipe_metadata_entries(recipe)
    if include_source_snapshot:
        metadata += _source_ohlcv_metadata(root, recipe)
    return DerivedCsvStore(historical_root=root).save_dataframe(
        market=recipe.market,
        kind="oscillators",
        tool_key="rsi",
        instance_key=f"rsi__default__period-{period}",
        df=pd.DataFrame(
            {
                "ts_ms": [1000, 2000, 3000],
                f"rsi_{period}": [45.0, 55.0, 65.0],
            }
        ),
        params=dict(recipe.params),
        params_status="explicit",
        bindings={},
        bindings_status="unknown",
        metadata=metadata,
    )


def _artifact_ref(recipe: ArtifactRecipe, path: Path) -> SelectedArtifactUpdateRef:
    return SelectedArtifactUpdateRef(
        family="oscillator",
        exchange=recipe.market.exchange,
        market_type=recipe.market.market_type,
        symbol=recipe.market.symbol,
        timeframe=recipe.market.timeframe,
        artifact_path=path,
        tool_key=recipe.tool_key,
        instance_key=f"rsi__default__period-{recipe.params['period']}",
        display_name=recipe.display_name,
    )


def _feature_for_rsi(recipe: ArtifactRecipe):
    period = int(recipe.params["period"])
    instance_key = f"rsi__default__period-{period}"
    source_id = build_feature_source_id(
        family="oscillators",
        tool_key="rsi",
        instance_key=instance_key,
    )
    source = AnalysisFeatureSource(
        source_id=source_id,
        family="oscillators",
        tool_key="rsi",
        tool_title="RSI",
        instance_key=instance_key,
        source_artifact_filename=f"{instance_key}.csv",
        source_artifact_relpath=f"oscillators/{instance_key}.csv",
        params=dict(recipe.params),
        params_status="explicit",
    )
    column = AnalysisDatabaseColumn(
        role="feature",
        selected=True,
        source_family="oscillators",
        source_id=source_id,
        source_column_name=f"rsi_{period}",
        db_column_name=build_database_column_name(
            source_family="oscillators",
            tool_key="rsi",
            instance_key=instance_key,
            source_column_name=f"rsi_{period}",
        ),
        dtype="float64",
        nullable=True,
        analysis_usable=True,
        renderable=True,
    )
    return source, column


def _materialized_database(
    root: Path,
    recipe: ArtifactRecipe,
    *,
    display_name: str = "BTCUSDT_30m_selected_update",
    include_feature: bool = True,
):
    store = AnalysisDatabaseStore(historical_root=root)
    feature_sources = ()
    feature_columns = ()
    if include_feature:
        source, column = _feature_for_rsi(recipe)
        feature_sources = (source,)
        feature_columns = (column,)
    draft = store.build_draft_manifest(
        market=recipe.market,
        display_name=display_name,
        user_description="selected update test",
        feature_sources=feature_sources,
        feature_columns=feature_columns,
    )
    store.save_manifest(draft)
    return store.materialize_database(
        market=recipe.market,
        database_id=draft.database_id,
    )


def _draft_database(root: Path, recipe: ArtifactRecipe):
    store = AnalysisDatabaseStore(historical_root=root)
    draft = store.build_draft_manifest(
        market=recipe.market,
        display_name="BTCUSDT_30m_selected_update_draft",
        user_description="selected update draft test",
    )
    store.save_manifest(draft)
    return draft


def _database_ref(database) -> SelectedAnalysisDatabaseUpdateRef:
    return SelectedAnalysisDatabaseUpdateRef(
        exchange=database.market.exchange,
        market_type=database.market.market_type,
        symbol=database.market.symbol,
        timeframe=database.market.timeframe,
        database_id=database.database_id,
        display_name=database.display_name,
    )


class _FakeRegenerationReport:
    def __init__(self, *, success: bool = True, error_text: str = "") -> None:
        self.execution_attempted = True
        self.execution_success = success
        self.execution_report = SimpleNamespace(
            item_reports=(SimpleNamespace(error_text=error_text, skipped_reason=""),)
            if error_text
            else (),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "execution_attempted": self.execution_attempted,
            "execution_success": self.execution_success,
        }


class _FakeRegenerator:
    def __init__(self, *, fail_recipe_ids: set[str] | None = None) -> None:
        self.fail_recipe_ids = set(fail_recipe_ids or set())
        self.calls: list[tuple[tuple[str, ...], bool, bool]] = []

    def regenerate_collection(
        self,
        collection,
        *,
        selected_recipe_ids,
        continue_on_error: bool = False,
        replan_after: bool = True,
    ):
        recipe_ids = tuple(selected_recipe_ids)
        self.calls.append((recipe_ids, continue_on_error, replan_after))
        recipe_id = recipe_ids[0]
        if recipe_id in self.fail_recipe_ids:
            return _FakeRegenerationReport(
                success=False,
                error_text=f"failed recipe {recipe_id}",
            )
        return _FakeRegenerationReport()


def _item(plan):
    assert len(plan.items) == 1
    return plan.items[0]


def test_selected_artifact_plan_marks_current_artifact_current(tmp_path: Path) -> None:
    _write_ohlcv(tmp_path)
    recipe = _recipe(tmp_path)
    artifact_path = _save_rsi_artifact(tmp_path, recipe)

    plan = DataManagerSelectedUpdateService(
        historical_root=tmp_path,
    ).plan_artifact_updates((_artifact_ref(recipe, artifact_path),))

    item = _item(plan)
    assert item.status == "current"
    assert item.actionable is False
    assert plan.actions == ()
    json.dumps(plan.to_dict(), sort_keys=True)


def test_selected_artifact_plan_marks_source_drift_old_actionable(tmp_path: Path) -> None:
    _write_ohlcv(tmp_path)
    recipe = _recipe(tmp_path)
    artifact_path = _save_rsi_artifact(tmp_path, recipe)
    _write_ohlcv(tmp_path, price_offset=1_000_000.0)

    plan = DataManagerSelectedUpdateService(
        historical_root=tmp_path,
    ).plan_artifact_updates((_artifact_ref(recipe, artifact_path),))

    item = _item(plan)
    assert item.status == "old"
    assert item.actionable is True
    assert plan.actions[0].action_type == "regenerate_artifact"
    assert plan.actions[0].metadata["recipe_id"] == recipe.recipe_id


def test_selected_artifact_missing_recipe_metadata_is_unknown_not_old(
    tmp_path: Path,
) -> None:
    _write_ohlcv(tmp_path)
    recipe = _recipe(tmp_path)
    artifact_path = _save_rsi_artifact(
        tmp_path,
        recipe,
        include_recipe_metadata=False,
    )

    plan = DataManagerSelectedUpdateService(
        historical_root=tmp_path,
    ).plan_artifact_updates((_artifact_ref(recipe, artifact_path),))

    item = _item(plan)
    assert item.status == "unknown"
    assert item.actionable is False
    assert plan.actions == ()


def test_selected_artifact_missing_recipe_file_is_blocked(tmp_path: Path) -> None:
    _write_ohlcv(tmp_path)
    recipe = _recipe(tmp_path)
    artifact_path = _save_rsi_artifact(tmp_path, recipe)
    recipe_store = ArtifactRecipeStore(historical_root=tmp_path)
    recipe_store.delete_recipe(market=recipe.market, recipe_id=recipe.recipe_id)

    plan = DataManagerSelectedUpdateService(
        historical_root=tmp_path,
    ).plan_artifact_updates((_artifact_ref(recipe, artifact_path),))

    item = _item(plan)
    assert item.status == "blocked"
    assert item.actionable is False
    assert "could not be loaded" in item.reason


def test_selected_artifact_missing_source_snapshot_is_unknown_not_old(
    tmp_path: Path,
) -> None:
    _write_ohlcv(tmp_path)
    recipe = _recipe(tmp_path)
    artifact_path = _save_rsi_artifact(
        tmp_path,
        recipe,
        include_source_snapshot=False,
    )

    plan = DataManagerSelectedUpdateService(
        historical_root=tmp_path,
    ).plan_artifact_updates((_artifact_ref(recipe, artifact_path),))

    item = _item(plan)
    assert item.status == "unknown"
    assert item.actionable is False
    assert any("missing_recorded_source_ohlcv_snapshot" in warning for warning in item.warnings)


def test_selected_artifact_execution_delegates_only_old_actions(
    tmp_path: Path,
) -> None:
    _write_ohlcv(tmp_path)
    recipe = _recipe(tmp_path)
    artifact_path = _save_rsi_artifact(tmp_path, recipe)
    _write_ohlcv(tmp_path, price_offset=1_000_000.0)
    regenerator = _FakeRegenerator()
    service = DataManagerSelectedUpdateService(
        historical_root=tmp_path,
        recovery_regenerator=regenerator,  # type: ignore[arg-type]
    )
    plan = service.plan_artifact_updates((_artifact_ref(recipe, artifact_path),))

    report = service.execute_artifact_update_plan(plan)

    assert report.completed_action_ids == (plan.actions[0].action_id,)
    assert regenerator.calls == [((recipe.recipe_id,), False, True)]
    json.dumps(report.to_dict(), sort_keys=True)


def test_selected_artifact_execution_skips_non_actionable_items(
    tmp_path: Path,
) -> None:
    _write_ohlcv(tmp_path)
    recipe = _recipe(tmp_path)
    artifact_path = _save_rsi_artifact(tmp_path, recipe)
    regenerator = _FakeRegenerator()
    service = DataManagerSelectedUpdateService(
        historical_root=tmp_path,
        recovery_regenerator=regenerator,  # type: ignore[arg-type]
    )
    plan = service.plan_artifact_updates((_artifact_ref(recipe, artifact_path),))
    forced_action = SelectedUpdateAction(
        action_id=f"regenerate_artifact:{recipe.recipe_id}",
        action_type="regenerate_artifact",
        item_id=plan.items[0].item_id,
        item_type="artifact",
        label="Regenerate",
        reason="forced test action",
        metadata={
            "market": {
                "exchange": recipe.market.exchange,
                "market_type": recipe.market.market_type,
                "symbol": recipe.market.symbol,
                "timeframe": recipe.market.timeframe,
            },
            "recipe_id": recipe.recipe_id,
        },
    )
    forced_plan = replace(plan, actions=(forced_action,))

    report = service.execute_artifact_update_plan(forced_plan)

    assert report.skipped_action_ids == (forced_action.action_id,)
    assert regenerator.calls == []


def test_selected_artifact_execution_reports_partial_failure(tmp_path: Path) -> None:
    _write_ohlcv(tmp_path)
    first = _recipe(tmp_path, period=14)
    second = _recipe(tmp_path, period=21)
    first_path = _save_rsi_artifact(tmp_path, first)
    second_path = _save_rsi_artifact(tmp_path, second)
    _write_ohlcv(tmp_path, price_offset=1_000_000.0)
    regenerator = _FakeRegenerator(fail_recipe_ids={first.recipe_id})
    service = DataManagerSelectedUpdateService(
        historical_root=tmp_path,
        recovery_regenerator=regenerator,  # type: ignore[arg-type]
    )
    plan = service.plan_artifact_updates(
        (_artifact_ref(first, first_path), _artifact_ref(second, second_path)),
    )

    report = service.execute_artifact_update_plan(plan)

    assert len(report.failed_action_ids) == 1
    assert len(report.completed_action_ids) == 1
    assert [call[0] for call in regenerator.calls] == [
        (first.recipe_id,),
        (second.recipe_id,),
    ]


def test_selected_database_plan_marks_current_materialized_database_current(
    tmp_path: Path,
) -> None:
    _write_ohlcv(tmp_path)
    recipe = _recipe(tmp_path)
    _save_rsi_artifact(tmp_path, recipe)
    database = _materialized_database(tmp_path, recipe)

    plan = DataManagerSelectedUpdateService(
        historical_root=tmp_path,
    ).plan_database_updates((_database_ref(database),))

    item = _item(plan)
    assert item.status == "current"
    assert item.actionable is False
    assert plan.actions == ()


def test_selected_database_plan_marks_ohlcv_only_source_drift_old(
    tmp_path: Path,
) -> None:
    _write_ohlcv(tmp_path)
    recipe = _recipe(tmp_path)
    database = _materialized_database(
        tmp_path,
        recipe,
        display_name="BTCUSDT_30m_selected_update_ohlcv_only",
        include_feature=False,
    )
    _write_ohlcv(tmp_path, price_offset=1_000_000.0)

    plan = DataManagerSelectedUpdateService(
        historical_root=tmp_path,
    ).plan_database_updates((_database_ref(database),))

    item = _item(plan)
    assert item.status == "old"
    assert item.actionable is True
    assert plan.actions[0].action_type == "rebuild_analysis_database"


def test_selected_database_plan_keeps_draft_as_draft(tmp_path: Path) -> None:
    _write_ohlcv(tmp_path)
    recipe = _recipe(tmp_path)
    database = _draft_database(tmp_path, recipe)

    plan = DataManagerSelectedUpdateService(
        historical_root=tmp_path,
    ).plan_database_updates((_database_ref(database),))

    item = _item(plan)
    assert item.status == "draft"
    assert item.actionable is False
    assert plan.actions == ()


def test_selected_database_plan_blocks_unloadable_current_ohlcv(
    tmp_path: Path,
) -> None:
    _write_ohlcv(tmp_path)
    recipe = _recipe(tmp_path)
    database = _materialized_database(
        tmp_path,
        recipe,
        display_name="BTCUSDT_30m_selected_update_blocked",
        include_feature=False,
    )
    _write_ohlcv(tmp_path, validation_status="unknown", price_offset=1_000_000.0)

    plan = DataManagerSelectedUpdateService(
        historical_root=tmp_path,
    ).plan_database_updates((_database_ref(database),))

    item = _item(plan)
    assert item.status == "blocked"
    assert item.actionable is False
    assert plan.actions == ()


def test_selected_database_plan_blocks_stale_source_artifacts(
    tmp_path: Path,
) -> None:
    _write_ohlcv(tmp_path)
    recipe = _recipe(tmp_path)
    _save_rsi_artifact(tmp_path, recipe)
    database = _materialized_database(
        tmp_path,
        recipe,
        display_name="BTCUSDT_30m_selected_update_stale_source",
    )
    _write_ohlcv(tmp_path, price_offset=1_000_000.0)

    plan = DataManagerSelectedUpdateService(
        historical_root=tmp_path,
    ).plan_database_updates((_database_ref(database),))

    item = _item(plan)
    assert item.status == "blocked"
    assert item.actionable is False
    assert any("Source artifact is stale" in blocker for blocker in item.blockers)


def test_selected_database_execution_rebuilds_only_old_databases(
    tmp_path: Path,
) -> None:
    _write_ohlcv(tmp_path)
    recipe = _recipe(tmp_path)
    database = _materialized_database(
        tmp_path,
        recipe,
        display_name="BTCUSDT_30m_selected_update_execute",
        include_feature=False,
    )
    before_id = database.database_id
    before_name = database.display_name
    _write_ohlcv(tmp_path, price_offset=1_000_000.0)
    service = DataManagerSelectedUpdateService(historical_root=tmp_path)
    plan = service.plan_database_updates((_database_ref(database),))

    report = service.execute_database_update_plan(plan)

    assert report.completed_action_ids == (plan.actions[0].action_id,)
    rebuilt = AnalysisDatabaseStore(historical_root=tmp_path).load_manifest(
        market=database.market,
        database_id=database.database_id,
    )
    assert rebuilt.database_id == before_id
    assert rebuilt.display_name == before_name
    assert rebuilt.feature_sources == database.feature_sources
    assert rebuilt.feature_columns == database.feature_columns


def test_selected_database_execution_skips_non_actionable_databases(
    tmp_path: Path,
) -> None:
    _write_ohlcv(tmp_path)
    recipe = _recipe(tmp_path)
    database = _materialized_database(
        tmp_path,
        recipe,
        display_name="BTCUSDT_30m_selected_update_skip",
        include_feature=False,
    )
    service = DataManagerSelectedUpdateService(historical_root=tmp_path)
    plan = service.plan_database_updates((_database_ref(database),))
    forced_action = SelectedUpdateAction(
        action_id=f"rebuild_analysis_database:{database.database_id}",
        action_type="rebuild_analysis_database",
        item_id=plan.items[0].item_id,
        item_type="analysis_database",
        label="Rebuild",
        reason="forced test action",
        metadata={
            "market": {
                "exchange": database.market.exchange,
                "market_type": database.market.market_type,
                "symbol": database.market.symbol,
                "timeframe": database.market.timeframe,
            },
            "database_id": database.database_id,
        },
    )
    forced_plan = replace(plan, actions=(forced_action,))

    report = service.execute_database_update_plan(forced_plan)

    assert report.skipped_action_ids == (forced_action.action_id,)


def test_selected_update_service_static_boundaries() -> None:
    source = Path(
        "src/leonardo/data/historical/data_manager_selected_update_service.py"
    ).read_text(encoding="utf-8")

    assert "from leonardo.gui" not in source
    assert "import leonardo.gui" not in source
    forbidden_direct_writes = (
        "write_text",
        "json.dump",
        ".to_csv(",
        "save_manifest(",
        "execute_update_plan",
        "shutil.rmtree",
        "Path.write_bytes",
    )
    for forbidden in forbidden_direct_writes:
        assert forbidden not in source
