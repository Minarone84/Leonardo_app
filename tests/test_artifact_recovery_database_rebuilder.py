from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

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
from leonardo.data.historical.artifact_recipe_collection_store import (
    ArtifactRecipeCollectionStore,
)
from leonardo.data.historical.artifact_recipe_store import ArtifactRecipe, ArtifactRecipeStore
from leonardo.data.historical.artifact_recovery_planner import ArtifactRecoveryPlanner
from leonardo.data.historical.artifact_recovery_database_rebuilder import (
    ArtifactRecoveryDatabaseRebuilder,
)
from leonardo.data.historical.artifact_recovery_regenerator import (
    ArtifactRecoveryRegenerationReport,
)
from leonardo.data.historical.artifact_metadata_contracts import ArtifactMetadataEntry
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


def _write_ohlcv(root: Path) -> None:
    market = _market()
    paths = HistoricalPaths(root=root)
    csv_path = CsvOHLCVStore().file_path(paths.ensure_ohlcv_dir(market))
    candles = [
        Candle(1000, 1.0, 1.5, 0.5, 1.2, 10.0),
        Candle(2000, 2.0, 2.5, 1.5, 2.2, 20.0),
        Candle(3000, 3.0, 3.5, 2.5, 3.2, 30.0),
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


def _save_rsi_artifact(root: Path, recipe: ArtifactRecipe) -> Path:
    instance_key = "rsi__default__period-14"
    return DerivedCsvStore(historical_root=root).save_dataframe(
        market=recipe.market,
        kind="oscillators",
        tool_key="rsi",
        instance_key=instance_key,
        df=pd.DataFrame({"ts_ms": [1000, 2000, 3000], "rsi_14": [45.0, 55.0, 65.0]}),
        params=dict(recipe.params),
        params_status="explicit",
        bindings={},
        bindings_status="unknown",
        metadata=(
            ArtifactMetadataEntry(
                namespace=SOURCE_OHLCV_PROVENANCE_NAMESPACE,
                key=SOURCE_OHLCV_PROVENANCE_KEY,
                value=build_source_ohlcv_provenance_snapshot(
                    historical_root=root,
                    market=recipe.market,
                ),
            ),
        ),
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


def _analysis_database(root: Path, recipe: ArtifactRecipe):
    store = AnalysisDatabaseStore(historical_root=root)
    source, column = _feature_for_rsi()
    manifest = store.build_draft_manifest(
        market=recipe.market,
        display_name="BTCUSDT_30m_recovery_rebuild",
        user_description="Recovery rebuild test.",
        feature_sources=(source,),
        feature_columns=(column,),
    )
    store.save_manifest(manifest)
    return manifest


def _collection(root: Path, recipe: ArtifactRecipe, *, source_database_id: str | None):
    store = ArtifactRecipeCollectionStore(historical_root=root)
    return store.save_collection(
        store.build_collection(
            market=recipe.market,
            display_name="Recovery DB Pack",
            recipes=(recipe,),
            source_database_id=source_database_id,
        )
    )


def test_database_rebuilder_materializes_linked_database_when_recovery_is_clean(tmp_path: Path) -> None:
    _write_ohlcv(tmp_path)
    recipe = _recipe(tmp_path)
    _save_rsi_artifact(tmp_path, recipe)
    database = _analysis_database(tmp_path, recipe)
    collection = _collection(tmp_path, recipe, source_database_id=database.database_id)

    report = ArtifactRecoveryDatabaseRebuilder(historical_root=tmp_path).rebuild_for_collection(collection)

    assert report.status == "rebuilt"
    assert report.success is True
    assert report.manifest is not None
    assert report.manifest.status == "materialized"

    dataframe = AnalysisDatabaseStore(historical_root=tmp_path).load_dataframe(
        market=recipe.market,
        database_id=database.database_id,
    )
    assert "oscillator__rsi__rsi_default_period_14__rsi_14" in dataframe.columns
    assert dataframe["oscillator__rsi__rsi_default_period_14__rsi_14"].tolist() == [45.0, 55.0, 65.0]


def test_database_rebuilder_skips_collection_without_source_database_id(tmp_path: Path) -> None:
    _write_ohlcv(tmp_path)
    recipe = _recipe(tmp_path)
    collection = _collection(tmp_path, recipe, source_database_id=None)

    report = ArtifactRecoveryDatabaseRebuilder(historical_root=tmp_path).rebuild_for_collection(collection)

    assert report.status == "skipped"
    assert report.skipped is True
    assert "not linked" in report.skipped_reason


def test_database_rebuilder_blocks_when_recovery_report_is_not_clean(tmp_path: Path) -> None:
    _write_ohlcv(tmp_path)
    recipe = _recipe(tmp_path)
    database = _analysis_database(tmp_path, recipe)
    collection = _collection(tmp_path, recipe, source_database_id=database.database_id)

    report = ArtifactRecoveryDatabaseRebuilder(historical_root=tmp_path).rebuild_for_collection(collection)

    assert report.status == "blocked"
    assert report.blocked is True
    assert any("Recovery report is not clean" in reason for reason in report.blocked_reasons)
    assert not AnalysisDatabaseStore(historical_root=tmp_path).dataframe_path(
        market=recipe.market,
        database_id=database.database_id,
    ).exists()


def test_database_rebuilder_fails_without_owning_manifest_repair(tmp_path: Path) -> None:
    _write_ohlcv(tmp_path)
    recipe = _recipe(tmp_path)
    _save_rsi_artifact(tmp_path, recipe)
    collection = _collection(tmp_path, recipe, source_database_id="adb__missing")

    report = ArtifactRecoveryDatabaseRebuilder(historical_root=tmp_path).rebuild_for_collection(collection)

    assert report.status == "failed"
    assert report.failed is True
    assert "FileNotFoundError" in report.error_text


@dataclass(frozen=True)
class _FakeRegenerationReport:
    market: object
    collection_id: str


def test_database_rebuilder_uses_post_recovery_report_from_regeneration(tmp_path: Path) -> None:
    _write_ohlcv(tmp_path)
    recipe = _recipe(tmp_path)
    _save_rsi_artifact(tmp_path, recipe)
    database = _analysis_database(tmp_path, recipe)
    collection = _collection(tmp_path, recipe, source_database_id=database.database_id)
    rebuilder = ArtifactRecoveryDatabaseRebuilder(historical_root=tmp_path)
    clean_report = ArtifactRecoveryPlanner(historical_root=tmp_path).plan_collection(collection)
    regeneration_report = ArtifactRecoveryRegenerationReport(
        market=collection.market,
        collection_id=collection.collection_id,
        requested_recipe_ids=clean_report.requested_recipe_ids,
        actionable_recipe_ids=(),
        non_actionable_recipe_ids=clean_report.requested_recipe_ids,
        pre_recovery_report=clean_report,
        execution_report=None,
        post_recovery_report=clean_report,
    )

    report = rebuilder.rebuild_for_collection(
        collection,
        regeneration_report=regeneration_report,
    )

    assert report.status == "rebuilt"
    assert report.recovery_report is clean_report


def test_database_rebuilder_can_force_materialization_without_clean_recovery_check(tmp_path: Path) -> None:
    _write_ohlcv(tmp_path)
    recipe = _recipe(tmp_path)
    _save_rsi_artifact(tmp_path, recipe)
    database = _analysis_database(tmp_path, recipe)
    collection = _collection(tmp_path, recipe, source_database_id=database.database_id)

    report = ArtifactRecoveryDatabaseRebuilder(historical_root=tmp_path).rebuild_for_collection(
        collection,
        require_clean_recovery=False,
    )

    assert report.status == "rebuilt"
    assert report.recovery_report is None
