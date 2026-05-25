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
from leonardo.data.historical.artifact_recipe_collection_store import (
    ArtifactRecipeCollectionStore,
)
from leonardo.data.historical.artifact_recipe_store import ArtifactRecipe, ArtifactRecipeStore
from leonardo.data.historical.data_manager_update_service import DataManagerUpdateService
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
                "label": f"RSI {period}",
                "description": "",
            }
        ],
    }


def _recipe(root: Path, *, period: int = 14) -> ArtifactRecipe:
    return ArtifactRecipeStore(historical_root=root).save_recipe(_rsi_payload(period=period))


def _save_rsi_artifact(
    root: Path,
    recipe: ArtifactRecipe,
    *,
    include_source_snapshot: bool = True,
) -> Path:
    metadata = ()
    if include_source_snapshot:
        metadata = (
            ArtifactMetadataEntry(
                namespace=SOURCE_OHLCV_PROVENANCE_NAMESPACE,
                key=SOURCE_OHLCV_PROVENANCE_KEY,
                value=build_source_ohlcv_provenance_snapshot(
                    historical_root=root,
                    market=recipe.market,
                ),
            ),
        )
    return DerivedCsvStore(historical_root=root).save_dataframe(
        market=recipe.market,
        kind="oscillators",
        tool_key="rsi",
        instance_key="rsi__default__period-14",
        df=pd.DataFrame({"ts_ms": [1000, 2000, 3000], "rsi_14": [45.0, 55.0, 65.0]}),
        params=dict(recipe.params),
        params_status="explicit",
        bindings={},
        bindings_status="unknown",
        metadata=metadata,
    )


def _feature_for_rsi():
    source_id = build_feature_source_id(
        family="oscillators",
        tool_key="rsi",
        instance_key="rsi__default__period-14",
    )
    source = AnalysisFeatureSource(
        source_id=source_id,
        family="oscillators",
        tool_key="rsi",
        tool_title="RSI",
        instance_key="rsi__default__period-14",
        source_artifact_filename="rsi__default__period-14.csv",
        source_artifact_relpath="oscillators/rsi__default__period-14.csv",
        params={"period": 14},
        params_status="explicit",
    )
    column = AnalysisDatabaseColumn(
        role="feature",
        selected=True,
        source_family="oscillators",
        source_id=source_id,
        source_column_name="rsi_14",
        db_column_name=build_database_column_name(
            source_family="oscillators",
            tool_key="rsi",
            instance_key="rsi__default__period-14",
            source_column_name="rsi_14",
        ),
        dtype="float64",
        nullable=True,
        analysis_usable=True,
        renderable=True,
    )
    return source, column


def _materialized_database(root: Path, recipe: ArtifactRecipe):
    store = AnalysisDatabaseStore(historical_root=root)
    source, column = _feature_for_rsi()
    draft = store.build_draft_manifest(
        market=recipe.market,
        display_name="BTCUSDT_30m_update_plan",
        user_description="Update planning test.",
        feature_sources=(source,),
        feature_columns=(column,),
    )
    store.save_manifest(draft)
    return store.materialize_database(market=recipe.market, database_id=draft.database_id)


def _draft_database(root: Path, recipe: ArtifactRecipe):
    store = AnalysisDatabaseStore(historical_root=root)
    source, column = _feature_for_rsi()
    draft = store.build_draft_manifest(
        market=recipe.market,
        display_name="BTCUSDT_30m_update_plan_draft",
        user_description="Update planning draft test.",
        feature_sources=(source,),
        feature_columns=(column,),
    )
    store.save_manifest(draft)
    return draft


def _collection(
    root: Path,
    recipe: ArtifactRecipe,
    *,
    source_database_id: str | None = None,
    extra_recipes: tuple[ArtifactRecipe, ...] = (),
):
    store = ArtifactRecipeCollectionStore(historical_root=root)
    return store.save_collection(
        store.build_collection(
            market=recipe.market,
            display_name="Update Plan Pack",
            recipes=(recipe, *extra_recipes),
            source_database_id=source_database_id,
        )
    )


def _service(
    root: Path,
    *,
    regenerator: object | None = None,
    rebuilder: object | None = None,
) -> DataManagerUpdateService:
    return DataManagerUpdateService(
        historical_root=root,
        recovery_regenerator=regenerator,
        database_rebuilder=rebuilder,
    )


def _item(plan, item_type: str):
    return next(item for item in plan.items if item.item_type == item_type)


def _actions(plan, action_type: str):
    return [action for action in plan.actions if action.action_type == action_type]


def _result(report, action_id: str):
    return next(result for result in report.results if result.action_id == action_id)


class _FakeRegenerationReport:
    def __init__(
        self,
        *,
        execution_attempted: bool = True,
        execution_success: bool = True,
        blocked_count: int = 0,
        error_text: str = "",
    ) -> None:
        self.execution_attempted = execution_attempted
        self.execution_success = execution_success
        self.pre_recovery_report = SimpleNamespace(blocked_count=blocked_count)
        self.execution_report = (
            SimpleNamespace(
                item_reports=(
                    SimpleNamespace(error_text=error_text, skipped_reason=""),
                )
            )
            if execution_attempted
            else None
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "execution_attempted": self.execution_attempted,
            "execution_success": self.execution_success,
            "blocked_count": self.pre_recovery_report.blocked_count,
        }


class _FakeRegenerator:
    def __init__(
        self,
        *,
        failed_recipe_ids: tuple[str, ...] = (),
        raised_recipe_ids: tuple[str, ...] = (),
        order: list[str] | None = None,
    ) -> None:
        self.calls: list[tuple[str, tuple[str, ...], bool, bool]] = []
        self.failed_recipe_ids = set(failed_recipe_ids)
        self.raised_recipe_ids = set(raised_recipe_ids)
        self.order = order

    def regenerate_collection(
        self,
        collection,
        *,
        selected_recipe_ids,
        continue_on_error: bool = False,
        replan_after: bool = True,
    ):
        recipe_ids = tuple(selected_recipe_ids)
        recipe_id = recipe_ids[0]
        self.calls.append(
            (collection.collection_id, recipe_ids, continue_on_error, replan_after)
        )
        if self.order is not None:
            self.order.append(f"regenerate:{recipe_id}")
        if recipe_id in self.raised_recipe_ids:
            raise RuntimeError(f"regeneration failed for {recipe_id}")
        if recipe_id in self.failed_recipe_ids:
            return _FakeRegenerationReport(
                execution_success=False,
                error_text=f"failed recipe {recipe_id}",
            )
        return _FakeRegenerationReport()


class _FakeRebuildReport:
    def __init__(
        self,
        *,
        status: str = "rebuilt",
        blocked_reasons: tuple[str, ...] = (),
        error_text: str = "",
        skipped_reason: str = "",
    ) -> None:
        self.status = status
        self.blocked_reasons = blocked_reasons
        self.error_text = error_text
        self.skipped_reason = skipped_reason

    @property
    def rebuilt(self) -> bool:
        return self.status == "rebuilt"

    @property
    def blocked(self) -> bool:
        return self.status == "blocked"

    @property
    def skipped(self) -> bool:
        return self.status == "skipped"

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "blocked_reasons": list(self.blocked_reasons),
            "error_text": self.error_text,
            "skipped_reason": self.skipped_reason,
        }


class _FakeRebuilder:
    def __init__(
        self,
        *,
        report: _FakeRebuildReport | None = None,
        order: list[str] | None = None,
    ) -> None:
        self.report = report or _FakeRebuildReport()
        self.calls: list[tuple[str, bool, bool]] = []
        self.order = order

    def rebuild_for_collection(
        self,
        collection,
        *,
        require_clean_recovery: bool = True,
        overwrite: bool = True,
    ):
        self.calls.append((collection.collection_id, require_clean_recovery, overwrite))
        if self.order is not None:
            self.order.append(f"rebuild:{collection.source_database_id}")
        return self.report


def test_update_plan_reports_current_collection_without_actions(tmp_path: Path) -> None:
    _write_ohlcv(tmp_path)
    recipe = _recipe(tmp_path)
    _save_rsi_artifact(tmp_path, recipe)
    database = _materialized_database(tmp_path, recipe)
    collection = _collection(tmp_path, recipe, source_database_id=database.database_id)

    plan = _service(tmp_path).plan_recipe_collection_update(collection)

    assert plan.summary["current"] == 3
    assert plan.actions == ()
    assert plan.blockers == ()
    assert _item(plan, "recipe_collection").status == "current"
    assert _item(plan, "artifact").status == "current"
    assert _item(plan, "analysis_database").status == "current"


def test_update_plan_marks_missing_artifact_actionable(tmp_path: Path) -> None:
    _write_ohlcv(tmp_path)
    recipe = _recipe(tmp_path)
    collection = _collection(tmp_path, recipe)

    plan = _service(tmp_path).plan_recipe_collection_update(collection)

    artifact = _item(plan, "artifact")
    assert artifact.status == "missing"
    assert artifact.actionability == "actionable"
    actions = _actions(plan, "regenerate_artifact")
    assert len(actions) == 1
    assert actions[0].target_item_id == artifact.item_id
    assert actions[0].blocked is False


def test_update_plan_marks_source_drifted_artifact_stale_and_actionable(
    tmp_path: Path,
) -> None:
    _write_ohlcv(tmp_path)
    recipe = _recipe(tmp_path)
    _save_rsi_artifact(tmp_path, recipe)
    _write_ohlcv(tmp_path, validation_status="ok", price_offset=1_000_000.0)
    collection = _collection(tmp_path, recipe)

    plan = _service(tmp_path).plan_recipe_collection_update(collection)

    artifact = _item(plan, "artifact")
    assert artifact.status == "stale"
    assert artifact.actionability == "actionable"
    assert artifact.metadata["source_drift"] is True
    assert any("source_csv_fingerprint_changed" in reason for reason in artifact.reasons)
    assert len(_actions(plan, "regenerate_artifact")) == 1


def test_update_plan_keeps_legacy_missing_snapshot_as_review_not_blocker(
    tmp_path: Path,
) -> None:
    _write_ohlcv(tmp_path)
    recipe = _recipe(tmp_path)
    _save_rsi_artifact(tmp_path, recipe, include_source_snapshot=False)
    collection = _collection(tmp_path, recipe)

    plan = _service(tmp_path).plan_recipe_collection_update(collection)

    artifact = _item(plan, "artifact")
    assert artifact.status == "freshness_unknown"
    assert artifact.actionability == "requires_review"
    assert any("missing_recorded_source_ohlcv_snapshot" in reason for reason in artifact.reasons)
    assert len(_actions(plan, "review")) == 1
    assert plan.blockers == ()


def test_update_plan_blocks_artifact_when_current_ohlcv_is_not_loadable(
    tmp_path: Path,
) -> None:
    _write_ohlcv(tmp_path, validation_status="unknown")
    recipe = _recipe(tmp_path)
    collection = _collection(tmp_path, recipe)

    plan = _service(tmp_path).plan_recipe_collection_update(collection)

    artifact = _item(plan, "artifact")
    assert artifact.status == "blocked"
    assert artifact.actionability == "blocked"
    assert _actions(plan, "regenerate_artifact") == []
    assert any("not loadable" in blocker.message for blocker in plan.blockers)


def test_update_plan_marks_linked_database_source_drift_as_rebuild_after_artifacts(
    tmp_path: Path,
) -> None:
    _write_ohlcv(tmp_path)
    recipe = _recipe(tmp_path)
    _save_rsi_artifact(tmp_path, recipe)
    database = _materialized_database(tmp_path, recipe)
    collection = _collection(tmp_path, recipe, source_database_id=database.database_id)
    _write_ohlcv(tmp_path, validation_status="ok", price_offset=1_000_000.0)

    plan = _service(tmp_path).plan_recipe_collection_update(collection)

    database_item = _item(plan, "analysis_database")
    assert database_item.status == "needs_rebuild"
    rebuild_actions = _actions(plan, "rebuild_analysis_database")
    regenerate_actions = _actions(plan, "regenerate_artifact")
    assert len(rebuild_actions) == 1
    assert rebuild_actions[0].depends_on_actions == tuple(
        action.action_id for action in regenerate_actions
    )


def test_update_plan_blocks_linked_database_when_current_ohlcv_is_not_loadable(
    tmp_path: Path,
) -> None:
    _write_ohlcv(tmp_path)
    recipe = _recipe(tmp_path)
    _save_rsi_artifact(tmp_path, recipe)
    database = _materialized_database(tmp_path, recipe)
    collection = _collection(tmp_path, recipe, source_database_id=database.database_id)
    _write_ohlcv(tmp_path, validation_status="unknown", price_offset=1_000_000.0)

    plan = _service(tmp_path).plan_recipe_collection_update(collection)

    database_item = _item(plan, "analysis_database")
    assert database_item.status == "blocked"
    assert _actions(plan, "rebuild_analysis_database") == []
    assert any(blocker.item_id == database_item.item_id for blocker in plan.blockers)


def test_update_plan_to_dict_is_json_safe(tmp_path: Path) -> None:
    _write_ohlcv(tmp_path)
    recipe = _recipe(tmp_path)
    collection = _collection(tmp_path, recipe)

    plan = _service(tmp_path).plan_recipe_collection_update(collection)

    json.dumps(plan.to_dict(), sort_keys=True)


def test_update_plan_by_id_is_read_only(tmp_path: Path) -> None:
    _write_ohlcv(tmp_path)
    recipe = _recipe(tmp_path)
    artifact_path = _save_rsi_artifact(tmp_path, recipe)
    database = _materialized_database(tmp_path, recipe)
    collection = _collection(tmp_path, recipe, source_database_id=database.database_id)
    collection_path = ArtifactRecipeCollectionStore(historical_root=tmp_path).collection_path(
        market=collection.market,
        collection_id=collection.collection_id,
    )
    database_store = AnalysisDatabaseStore(historical_root=tmp_path)
    paths = [
        artifact_path,
        artifact_path.with_name(f"{artifact_path.stem}.meta.json"),
        database_store.manifest_path(market=collection.market, database_id=database.database_id),
        database_store.dataframe_path(market=collection.market, database_id=database.database_id),
        collection_path,
    ]
    before = {path: path.read_bytes() for path in paths}

    plan = _service(tmp_path).plan_recipe_collection_update_by_id(
        market=collection.market,
        collection_id=collection.collection_id,
    )

    assert plan.summary["current"] == 3
    after = {path: path.read_bytes() for path in paths}
    assert after == before


def test_execute_update_plan_with_empty_selection_runs_no_actions(tmp_path: Path) -> None:
    _write_ohlcv(tmp_path)
    recipe = _recipe(tmp_path)
    collection = _collection(tmp_path, recipe)
    regenerator = _FakeRegenerator()
    service = _service(tmp_path, regenerator=regenerator)
    plan = service.plan_recipe_collection_update(collection)

    report = service.execute_update_plan(plan, selected_action_ids=())

    assert report.requested_action_ids == ()
    assert report.results == ()
    assert report.summary["completed"] == 0
    assert regenerator.calls == []


def test_execute_update_plan_delegates_selected_artifact_regeneration(
    tmp_path: Path,
) -> None:
    _write_ohlcv(tmp_path)
    recipe = _recipe(tmp_path)
    collection = _collection(tmp_path, recipe)
    regenerator = _FakeRegenerator()
    service = _service(tmp_path, regenerator=regenerator)
    plan = service.plan_recipe_collection_update(collection)
    action = _actions(plan, "regenerate_artifact")[0]

    report = service.execute_update_plan(plan, selected_action_ids=(action.action_id,))

    assert report.completed_action_ids == (action.action_id,)
    assert report.summary["regenerated_artifacts"] == 1
    assert regenerator.calls == [
        (collection.collection_id, (recipe.recipe_id,), False, True)
    ]
    json.dumps(report.to_dict(), sort_keys=True)


def test_execute_update_plan_delegates_selected_database_rebuild(
    tmp_path: Path,
) -> None:
    _write_ohlcv(tmp_path)
    recipe = _recipe(tmp_path)
    _save_rsi_artifact(tmp_path, recipe)
    database = _draft_database(tmp_path, recipe)
    collection = _collection(tmp_path, recipe, source_database_id=database.database_id)
    regenerator = _FakeRegenerator()
    rebuilder = _FakeRebuilder()
    service = _service(tmp_path, regenerator=regenerator, rebuilder=rebuilder)
    plan = service.plan_recipe_collection_update(collection)
    action = _actions(plan, "rebuild_analysis_database")[0]

    report = service.execute_update_plan(plan, selected_action_ids=(action.action_id,))

    assert report.completed_action_ids == (action.action_id,)
    assert report.summary["rebuilt_databases"] == 1
    assert regenerator.calls == []
    assert rebuilder.calls == [(collection.collection_id, True, True)]


def test_execute_update_plan_blocks_blocked_action_without_delegation(
    tmp_path: Path,
) -> None:
    _write_ohlcv(tmp_path)
    recipe = _recipe(tmp_path)
    collection = _collection(tmp_path, recipe)
    regenerator = _FakeRegenerator()
    service = _service(tmp_path, regenerator=regenerator)
    plan = service.plan_recipe_collection_update(collection)
    action = replace(
        _actions(plan, "regenerate_artifact")[0],
        blocked=True,
        blocker_reasons=("blocked for test",),
    )
    blocked_plan = replace(plan, actions=(action,), blockers=())

    report = service.execute_update_plan(
        blocked_plan,
        selected_action_ids=(action.action_id,),
    )

    result = _result(report, action.action_id)
    assert result.status == "blocked"
    assert report.blocked_action_ids == (action.action_id,)
    assert regenerator.calls == []
    assert any(blocker.reason == "blocked_for_test" for blocker in report.blockers)


def test_execute_update_plan_skips_review_action_without_delegation(
    tmp_path: Path,
) -> None:
    _write_ohlcv(tmp_path)
    recipe = _recipe(tmp_path)
    _save_rsi_artifact(tmp_path, recipe, include_source_snapshot=False)
    collection = _collection(tmp_path, recipe)
    regenerator = _FakeRegenerator()
    service = _service(tmp_path, regenerator=regenerator)
    plan = service.plan_recipe_collection_update(collection)
    action = _actions(plan, "review")[0]

    report = service.execute_update_plan(plan, selected_action_ids=(action.action_id,))

    result = _result(report, action.action_id)
    assert result.status == "skipped"
    assert result.metadata["reason"] == "review_action_not_executable"
    assert regenerator.calls == []


def test_execute_update_plan_reports_unknown_selected_action_id(
    tmp_path: Path,
) -> None:
    _write_ohlcv(tmp_path)
    recipe = _recipe(tmp_path)
    collection = _collection(tmp_path, recipe)
    regenerator = _FakeRegenerator()
    service = _service(tmp_path, regenerator=regenerator)
    plan = service.plan_recipe_collection_update(collection)

    report = service.execute_update_plan(
        plan,
        selected_action_ids=("regenerate_artifact:missing",),
    )

    result = _result(report, "regenerate_artifact:missing")
    assert result.status == "failed"
    assert result.error == "unknown_action_id"
    assert regenerator.calls == []


def test_execute_update_plan_respects_dependency_success(tmp_path: Path) -> None:
    _write_ohlcv(tmp_path)
    recipe = _recipe(tmp_path)
    _save_rsi_artifact(tmp_path, recipe)
    database = _materialized_database(tmp_path, recipe)
    collection = _collection(tmp_path, recipe, source_database_id=database.database_id)
    _write_ohlcv(tmp_path, validation_status="ok", price_offset=1_000_000.0)
    order: list[str] = []
    regenerator = _FakeRegenerator(order=order)
    rebuilder = _FakeRebuilder(order=order)
    service = _service(tmp_path, regenerator=regenerator, rebuilder=rebuilder)
    plan = service.plan_recipe_collection_update(collection)

    report = service.execute_update_plan(plan)

    regenerate_action = _actions(plan, "regenerate_artifact")[0]
    rebuild_action = _actions(plan, "rebuild_analysis_database")[0]
    assert report.completed_action_ids == (
        regenerate_action.action_id,
        rebuild_action.action_id,
    )
    assert order == [
        f"regenerate:{recipe.recipe_id}",
        f"rebuild:{database.database_id}",
    ]


def test_execute_update_plan_skips_dependent_action_after_dependency_failure(
    tmp_path: Path,
) -> None:
    _write_ohlcv(tmp_path)
    recipe = _recipe(tmp_path)
    _save_rsi_artifact(tmp_path, recipe)
    database = _materialized_database(tmp_path, recipe)
    collection = _collection(tmp_path, recipe, source_database_id=database.database_id)
    _write_ohlcv(tmp_path, validation_status="ok", price_offset=1_000_000.0)
    regenerator = _FakeRegenerator(failed_recipe_ids=(recipe.recipe_id,))
    rebuilder = _FakeRebuilder()
    service = _service(tmp_path, regenerator=regenerator, rebuilder=rebuilder)
    plan = service.plan_recipe_collection_update(collection)

    report = service.execute_update_plan(plan)

    regenerate_action = _actions(plan, "regenerate_artifact")[0]
    rebuild_action = _actions(plan, "rebuild_analysis_database")[0]
    assert _result(report, regenerate_action.action_id).status == "failed"
    rebuild_result = _result(report, rebuild_action.action_id)
    assert rebuild_result.status == "skipped"
    assert rebuild_result.metadata["reason"] == "dependency_not_completed"
    assert rebuilder.calls == []


def test_execute_update_plan_skips_dependent_action_when_dependency_not_selected(
    tmp_path: Path,
) -> None:
    _write_ohlcv(tmp_path)
    recipe = _recipe(tmp_path)
    _save_rsi_artifact(tmp_path, recipe)
    database = _materialized_database(tmp_path, recipe)
    collection = _collection(tmp_path, recipe, source_database_id=database.database_id)
    _write_ohlcv(tmp_path, validation_status="ok", price_offset=1_000_000.0)
    rebuilder = _FakeRebuilder()
    service = _service(tmp_path, regenerator=_FakeRegenerator(), rebuilder=rebuilder)
    plan = service.plan_recipe_collection_update(collection)
    rebuild_action = _actions(plan, "rebuild_analysis_database")[0]

    report = service.execute_update_plan(
        plan,
        selected_action_ids=(rebuild_action.action_id,),
    )

    rebuild_result = _result(report, rebuild_action.action_id)
    assert rebuild_result.status == "skipped"
    assert rebuild_result.metadata["reason"] == "dependency_not_selected"
    assert rebuilder.calls == []


def test_execute_update_plan_continues_independent_actions_after_failure(
    tmp_path: Path,
) -> None:
    _write_ohlcv(tmp_path)
    first = _recipe(tmp_path, period=14)
    second = _recipe(tmp_path, period=21)
    collection = _collection(tmp_path, first, extra_recipes=(second,))
    regenerator = _FakeRegenerator(failed_recipe_ids=(first.recipe_id,))
    service = _service(tmp_path, regenerator=regenerator)
    plan = service.plan_recipe_collection_update(collection)
    actions = _actions(plan, "regenerate_artifact")

    report = service.execute_update_plan(plan)

    assert [action.depends_on_actions for action in actions] == [(), ()]
    assert _result(report, actions[0].action_id).status == "failed"
    assert _result(report, actions[1].action_id).status == "completed"
    assert [call[1] for call in regenerator.calls] == [
        (first.recipe_id,),
        (second.recipe_id,),
    ]
