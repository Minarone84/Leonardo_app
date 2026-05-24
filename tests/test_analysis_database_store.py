from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from leonardo.data.historical.analysis_database_contracts import AnalysisDatabaseColumn, AnalysisFeatureSource
from leonardo.data.historical.analysis_database_naming import build_database_column_name, build_feature_source_id
from leonardo.data.historical.analysis_database_store import AnalysisDatabaseStore
from leonardo.data.historical.paths import HistoricalPaths
from leonardo.data.historical.store_csv import Candle, CsvOHLCVStore
from leonardo.data.naming import canonicalize


def _issues_for_status(status: str) -> tuple[tuple[str, str], ...]:
    if status == "error":
        return (("error", "test validation error"),)
    if status == "warning":
        return (("warning", "test validation warning"),)
    return ()


def _write_ohlcv(
    root: Path,
    market,
    *,
    validation_status: str = "ok",
    write_metadata: bool = True,
) -> Path:
    paths = HistoricalPaths(root=root)
    store = CsvOHLCVStore()
    path = store.file_path(paths.ensure_ohlcv_dir(market))
    candles = [
        Candle(1000, 1.0, 1.5, 0.5, 1.2, 10.0),
        Candle(2000, 2.0, 2.5, 1.5, 2.2, 20.0),
        Candle(3000, 3.0, 3.5, 2.5, 3.2, 30.0),
    ]
    store.write_atomic(path, candles, market=market, write_metadata=write_metadata)
    if write_metadata:
        store.record_validation_result(
            path,
            market=market,
            status=validation_status,
            row_count=len(candles),
            issues=_issues_for_status(validation_status),
            validator="HistoricalDatasetValidator",
        )
    return path


def _write_feature_artifact(root: Path, market, *, family: str, instance_key: str, column_name: str, values) -> Path:
    path = root / market.exchange / market.market_type / market.symbol / market.timeframe / family / f"{instance_key}.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame({"ts_ms": [1000, 2000, 3000], column_name: list(values)}).to_csv(path, index=False)
    return path


def _feature(*, family: str, tool_key: str, tool_title: str, instance_key: str, column_name: str):
    source_id = build_feature_source_id(family=family, tool_key=tool_key, instance_key=instance_key)
    source = AnalysisFeatureSource(
        source_id=source_id,
        family=family,  # type: ignore[arg-type]
        tool_key=tool_key,
        tool_title=tool_title,
        instance_key=instance_key,
        source_artifact_filename=f"{instance_key}.csv",
        source_artifact_relpath=f"{family}/{instance_key}.csv",
        params_status="inferred",
    )
    column = AnalysisDatabaseColumn(
        role="feature",
        selected=True,
        source_family=family,  # type: ignore[arg-type]
        source_id=source_id,
        source_column_name=column_name,
        db_column_name=build_database_column_name(
            source_family=family,
            tool_key=tool_key,
            instance_key=instance_key,
            source_column_name=column_name,
        ),
        dtype="float64",
        nullable=True,
        analysis_usable=True,
        renderable=True,
    )
    return source, column


def _draft(store: AnalysisDatabaseStore, market, *, display_name: str, feature):
    source, column = feature
    manifest = store.build_draft_manifest(
        market=market,
        display_name=display_name,
        user_description="store workflow test",
        feature_sources=(source,),
        feature_columns=(column,),
    )
    store.save_manifest(manifest, overwrite=False)
    return manifest


def test_analysis_database_display_name_validation(tmp_path: Path):
    market = canonicalize("bybit", "linear", "BTCUSDT", "30m")
    store = AnalysisDatabaseStore(historical_root=tmp_path)

    assert store.default_display_name_prefix(market=market) == "BTCUSDT_30m_"
    assert store.validate_database_display_name(" BTCUSDT_30m_pack ") == "BTCUSDT_30m_pack"

    with pytest.raises(ValueError, match="spaces|whitespace"):
        store.build_draft_manifest(market=market, display_name="BTC 30m pack")

    with pytest.raises(ValueError, match="path separators"):
        store.build_draft_manifest(market=market, display_name="BTCUSDT/30m_pack")


def test_analysis_database_rejects_duplicate_visible_name_per_market(tmp_path: Path):
    market = canonicalize("bybit", "linear", "BTCUSDT", "30m")
    other_market = canonicalize("bybit", "linear", "ETHUSDT", "30m")
    store = AnalysisDatabaseStore(historical_root=tmp_path)
    rsi = _feature(
        family="oscillators",
        tool_key="rsi",
        tool_title="RSI",
        instance_key="rsi__default__period-14",
        column_name="rsi_14",
    )
    sma = _feature(
        family="indicators",
        tool_key="sma",
        tool_title="SMA",
        instance_key="sma__default__length-9",
        column_name="sma_9",
    )

    _draft(store, market, display_name="BTCUSDT_30m_pack", feature=rsi)
    duplicate_recipe = store.build_draft_manifest(
        market=market,
        display_name="BTCUSDT_30m_pack",
        feature_sources=(sma[0],),
        feature_columns=(sma[1],),
    )
    with pytest.raises(FileExistsError, match="already exists"):
        store.save_manifest(duplicate_recipe, overwrite=False)

    same_visible_name_other_market = store.build_draft_manifest(
        market=other_market,
        display_name="BTCUSDT_30m_pack",
        feature_sources=(sma[0],),
        feature_columns=(sma[1],),
    )
    store.save_manifest(same_visible_name_other_market, overwrite=False)
    assert len(store.list_databases(market=other_market)) == 1


def test_materialize_database_rebuild_preserves_identity_recipe_and_updates_dataframe(tmp_path: Path):
    market = canonicalize("bybit", "linear", "BTCUSDT", "30m")
    _write_ohlcv(tmp_path, market)
    rsi_path = _write_feature_artifact(
        tmp_path,
        market,
        family="oscillators",
        instance_key="rsi__default__period-14",
        column_name="rsi_14",
        values=[45.0, 55.0, 65.0],
    )

    store = AnalysisDatabaseStore(historical_root=tmp_path)
    rsi = _feature(
        family="oscillators",
        tool_key="rsi",
        tool_title="RSI",
        instance_key="rsi__default__period-14",
        column_name="rsi_14",
    )
    draft = _draft(store, market, display_name="BTCUSDT_30m_rebuild_same_recipe", feature=rsi)

    first = store.materialize_database(market=market, database_id=draft.database_id)
    first_dataframe = store.load_dataframe(market=market, database_id=draft.database_id)
    assert first_dataframe["oscillator__rsi__rsi_default_period_14__rsi_14"].tolist() == [45.0, 55.0, 65.0]

    # Simulate updated source data or a damaged/outdated dataframe.csv. A rebuild
    # must reuse the saved manifest recipe and rewrite dataframe.csv for the
    # same database, not create another database or replace feature components.
    pd.DataFrame(
        {
            "ts_ms": [1000, 2000, 3000],
            "rsi_14": [40.0, 50.0, 60.0],
        }
    ).to_csv(rsi_path, index=False)

    rebuilt = store.materialize_database(market=market, database_id=draft.database_id, overwrite=True)
    rebuilt_dataframe = store.load_dataframe(market=market, database_id=draft.database_id)

    assert rebuilt.database_id == draft.database_id
    assert rebuilt.display_name == draft.display_name
    assert rebuilt.recipe_hash == first.recipe_hash
    assert rebuilt.feature_sources == first.feature_sources
    assert rebuilt.feature_columns == first.feature_columns
    assert rebuilt.materialization is not None
    assert first.materialization is not None
    assert rebuilt.materialization.created_at_ms == first.materialization.created_at_ms
    assert rebuilt.materialization.updated_at_ms >= first.materialization.updated_at_ms
    assert rebuilt_dataframe["oscillator__rsi__rsi_default_period_14__rsi_14"].tolist() == [40.0, 50.0, 60.0]


def test_materialize_database_allows_modified_ohlcv(tmp_path: Path) -> None:
    market = canonicalize("bybit", "linear", "BTCUSDT", "30m")
    _write_ohlcv(tmp_path, market, validation_status="modified")
    _write_feature_artifact(
        tmp_path,
        market,
        family="oscillators",
        instance_key="rsi__default__period-14",
        column_name="rsi_14",
        values=[45.0, 55.0, 65.0],
    )
    store = AnalysisDatabaseStore(historical_root=tmp_path)
    rsi = _feature(
        family="oscillators",
        tool_key="rsi",
        tool_title="RSI",
        instance_key="rsi__default__period-14",
        column_name="rsi_14",
    )
    draft = _draft(store, market, display_name="BTCUSDT_30m_modified", feature=rsi)

    materialized = store.materialize_database(market=market, database_id=draft.database_id)

    assert materialized.status == "materialized"


@pytest.mark.parametrize("status", ["unknown", "error", "warning"])
def test_materialize_database_blocks_unaccepted_ohlcv_statuses(
    tmp_path: Path,
    status: str,
) -> None:
    market = canonicalize("bybit", "linear", "BTCUSDT", "30m")
    _write_ohlcv(tmp_path, market, validation_status=status)
    _write_feature_artifact(
        tmp_path,
        market,
        family="oscillators",
        instance_key="rsi__default__period-14",
        column_name="rsi_14",
        values=[45.0, 55.0, 65.0],
    )
    store = AnalysisDatabaseStore(historical_root=tmp_path)
    rsi = _feature(
        family="oscillators",
        tool_key="rsi",
        tool_title="RSI",
        instance_key="rsi__default__period-14",
        column_name="rsi_14",
    )
    draft = _draft(store, market, display_name=f"BTCUSDT_30m_{status}", feature=rsi)

    with pytest.raises(PermissionError, match="OHLCV Maintenance"):
        store.materialize_database(market=market, database_id=draft.database_id)


def test_materialize_database_blocks_missing_ohlcv_metadata(tmp_path: Path) -> None:
    market = canonicalize("bybit", "linear", "BTCUSDT", "30m")
    _write_ohlcv(tmp_path, market, write_metadata=False)
    _write_feature_artifact(
        tmp_path,
        market,
        family="oscillators",
        instance_key="rsi__default__period-14",
        column_name="rsi_14",
        values=[45.0, 55.0, 65.0],
    )
    store = AnalysisDatabaseStore(historical_root=tmp_path)
    rsi = _feature(
        family="oscillators",
        tool_key="rsi",
        tool_title="RSI",
        instance_key="rsi__default__period-14",
        column_name="rsi_14",
    )
    draft = _draft(store, market, display_name="BTCUSDT_30m_missing_meta", feature=rsi)

    with pytest.raises(PermissionError, match="metadata sidecar"):
        store.materialize_database(market=market, database_id=draft.database_id)


def test_materialize_database_blocks_stale_ohlcv_validation_fingerprint(
    tmp_path: Path,
) -> None:
    market = canonicalize("bybit", "linear", "BTCUSDT", "30m")
    ohlcv_path = _write_ohlcv(tmp_path, market, validation_status="ok")
    ohlcv_path.write_text(
        ohlcv_path.read_text(encoding="utf-8") + "\n",
        encoding="utf-8",
    )
    _write_feature_artifact(
        tmp_path,
        market,
        family="oscillators",
        instance_key="rsi__default__period-14",
        column_name="rsi_14",
        values=[45.0, 55.0, 65.0],
    )
    store = AnalysisDatabaseStore(historical_root=tmp_path)
    rsi = _feature(
        family="oscillators",
        tool_key="rsi",
        tool_title="RSI",
        instance_key="rsi__default__period-14",
        column_name="rsi_14",
    )
    draft = _draft(store, market, display_name="BTCUSDT_30m_stale", feature=rsi)

    with pytest.raises(PermissionError, match="changed after validation|stale"):
        store.materialize_database(market=market, database_id=draft.database_id)


def test_analysis_database_rename_preserves_id_and_delete_removes_folder(tmp_path: Path):
    market = canonicalize("bybit", "linear", "BTCUSDT", "30m")
    store = AnalysisDatabaseStore(historical_root=tmp_path)
    rsi = _feature(
        family="oscillators",
        tool_key="rsi",
        tool_title="RSI",
        instance_key="rsi__default__period-14",
        column_name="rsi_14",
    )
    sma = _feature(
        family="indicators",
        tool_key="sma",
        tool_title="SMA",
        instance_key="sma__default__length-9",
        column_name="sma_9",
    )
    first = _draft(store, market, display_name="BTCUSDT_30m_first", feature=rsi)
    _draft(store, market, display_name="BTCUSDT_30m_taken", feature=sma)
    old_dir = store.database_dir(market=market, database_id=first.database_id)

    renamed = store.rename_database(
        market=market,
        database_id=first.database_id,
        new_display_name="BTCUSDT_30m_renamed",
    )

    assert renamed.database_id == first.database_id
    assert renamed.display_name == "BTCUSDT_30m_renamed"
    assert store.database_dir(market=market, database_id=first.database_id) == old_dir
    assert store.load_manifest(market=market, database_id=first.database_id).display_name == "BTCUSDT_30m_renamed"

    with pytest.raises(ValueError, match="spaces|whitespace"):
        store.rename_database(market=market, database_id=first.database_id, new_display_name="BTC 30m renamed")
    with pytest.raises(FileExistsError, match="already exists"):
        store.rename_database(market=market, database_id=first.database_id, new_display_name="BTCUSDT_30m_taken")

    store.delete_database(market=market, database_id=first.database_id)
    assert not old_dir.exists()
    assert first.database_id not in {summary.database_id for summary in store.list_databases(market=market)}


def test_rebuild_database_with_features_replaces_manifest_recipe_and_dataframe(tmp_path: Path):
    market = canonicalize("bybit", "linear", "BTCUSDT", "30m")
    _write_ohlcv(tmp_path, market)
    _write_feature_artifact(
        tmp_path,
        market,
        family="oscillators",
        instance_key="rsi__default__period-14",
        column_name="rsi_14",
        values=[45.0, 55.0, 65.0],
    )
    _write_feature_artifact(
        tmp_path,
        market,
        family="indicators",
        instance_key="sma__default__length-9",
        column_name="sma_9",
        values=[1.1, 2.1, 3.1],
    )

    store = AnalysisDatabaseStore(historical_root=tmp_path)
    rsi = _feature(
        family="oscillators",
        tool_key="rsi",
        tool_title="RSI",
        instance_key="rsi__default__period-14",
        column_name="rsi_14",
    )
    sma = _feature(
        family="indicators",
        tool_key="sma",
        tool_title="SMA",
        instance_key="sma__default__length-9",
        column_name="sma_9",
    )
    draft = _draft(store, market, display_name="BTCUSDT_30m_rebuild", feature=rsi)
    materialized = store.materialize_database(market=market, database_id=draft.database_id)
    before = store.load_dataframe(market=market, database_id=draft.database_id)
    assert "oscillator__rsi__rsi_default_period_14__rsi_14" in before.columns

    rebuilt = store.rebuild_database_with_features(
        market=market,
        database_id=draft.database_id,
        feature_sources=(sma[0],),
        feature_columns=(sma[1],),
    )
    after = store.load_dataframe(market=market, database_id=draft.database_id)

    assert rebuilt.database_id == draft.database_id
    assert rebuilt.recipe_hash != materialized.recipe_hash
    assert rebuilt.status == "materialized"
    assert "indicator__sma__sma_default_length_9__sma_9" in after.columns
    assert "oscillator__rsi__rsi_default_period_14__rsi_14" not in after.columns
    assert after["indicator__sma__sma_default_length_9__sma_9"].tolist() == [1.1, 2.1, 3.1]
