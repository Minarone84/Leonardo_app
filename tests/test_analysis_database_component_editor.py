from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from leonardo.data.historical.analysis_database_component_editor import (
    AnalysisDatabaseComponentEditor,
)
from leonardo.data.historical.analysis_database_contracts import (
    AnalysisDatabaseColumn,
    AnalysisFeatureSource,
)
from leonardo.data.historical.analysis_database_naming import (
    build_database_column_name,
    build_feature_source_id,
)
from leonardo.data.historical.analysis_database_store import AnalysisDatabaseStore
from leonardo.data.naming import canonicalize


def _market():
    return canonicalize("bybit", "linear", "BTCUSDT", "30m")


def _write_ohlcv(root: Path) -> None:
    market = _market()
    path = root / market.exchange / market.market_type / market.symbol / market.timeframe / "ohlcv" / "candles.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        {
            "ts_ms": [1000, 2000, 3000],
            "open": [1.0, 2.0, 3.0],
            "high": [1.5, 2.5, 3.5],
            "low": [0.5, 1.5, 2.5],
            "close": [1.2, 2.2, 3.2],
            "volume": [10.0, 20.0, 30.0],
        }
    ).to_csv(path, index=False)


def _write_feature_artifact(
    root: Path,
    *,
    family: str,
    instance_key: str,
    column_name: str,
    values,
) -> Path:
    market = _market()
    path = root / market.exchange / market.market_type / market.symbol / market.timeframe / family / f"{instance_key}.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame({"ts_ms": [1000, 2000, 3000], column_name: list(values)}).to_csv(path, index=False)
    return path


def _feature(*, family: str, tool_key: str, tool_title: str, instance_key: str, column_name: str):
    source_id = build_feature_source_id(
        family=family,
        tool_key=tool_key,
        instance_key=instance_key,
    )
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


def _draft(store: AnalysisDatabaseStore, *, feature):
    source, column = feature
    manifest = store.build_draft_manifest(
        market=_market(),
        display_name="BTCUSDT_30m_component_editor",
        user_description="Component editor test database.",
        feature_sources=(source,),
        feature_columns=(column,),
    )
    store.save_manifest(manifest, overwrite=False)
    return manifest


def _seed_rsi_sma(tmp_path: Path):
    _write_ohlcv(tmp_path)
    _write_feature_artifact(
        tmp_path,
        family="oscillators",
        instance_key="rsi__default__period-14",
        column_name="rsi_14",
        values=[45.0, 55.0, 65.0],
    )
    _write_feature_artifact(
        tmp_path,
        family="indicators",
        instance_key="sma__default__length-9",
        column_name="sma_9",
        values=[1.1, 2.1, 3.1],
    )
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
    return rsi, sma


def test_component_editor_replace_components_preserves_identity_and_resets_materialization(tmp_path: Path) -> None:
    rsi, sma = _seed_rsi_sma(tmp_path)
    store = AnalysisDatabaseStore(historical_root=tmp_path)
    draft = _draft(store, feature=rsi)
    materialized = store.materialize_database(market=_market(), database_id=draft.database_id)
    dataframe_path = store.dataframe_path(market=_market(), database_id=draft.database_id)
    assert dataframe_path.exists()

    report = AnalysisDatabaseComponentEditor(historical_root=tmp_path).replace_components(
        market=_market(),
        database_id=draft.database_id,
        feature_sources=(sma[0],),
        feature_columns=(sma[1],),
    )
    updated = report.manifest

    assert report.success is True
    assert report.recipe_changed is True
    assert report.materialization_reset is True
    assert report.dataframe_removed is True
    assert updated.database_id == draft.database_id
    assert updated.display_name == draft.display_name
    assert updated.description.user_text == draft.description.user_text
    assert updated.status == "draft"
    assert updated.materialization is None
    assert updated.dataframe_filename is None
    assert updated.recipe_hash != materialized.recipe_hash
    assert tuple(source.source_id for source in updated.feature_sources) == (sma[0].source_id,)
    assert tuple(column.db_column_name for column in updated.feature_columns) == (sma[1].db_column_name,)
    assert not dataframe_path.exists()

    rebuilt = store.materialize_database(market=_market(), database_id=draft.database_id)
    dataframe = store.load_dataframe(market=_market(), database_id=draft.database_id)
    assert rebuilt.status == "materialized"
    assert sma[1].db_column_name in dataframe.columns
    assert rsi[1].db_column_name not in dataframe.columns


def test_component_editor_add_components_preserves_existing_components(tmp_path: Path) -> None:
    rsi, sma = _seed_rsi_sma(tmp_path)
    store = AnalysisDatabaseStore(historical_root=tmp_path)
    draft = _draft(store, feature=rsi)
    store.materialize_database(market=_market(), database_id=draft.database_id)

    report = AnalysisDatabaseComponentEditor(historical_root=tmp_path).add_components(
        market=_market(),
        database_id=draft.database_id,
        feature_sources=(sma[0],),
        feature_columns=(sma[1],),
    )
    updated = report.manifest

    assert updated.database_id == draft.database_id
    assert updated.status == "draft"
    assert updated.materialization is None
    assert tuple(column.db_column_name for column in updated.feature_columns) == (
        rsi[1].db_column_name,
        sma[1].db_column_name,
    )
    assert tuple(source.source_id for source in updated.feature_sources) == (
        rsi[0].source_id,
        sma[0].source_id,
    )


def test_component_editor_remove_components_prunes_unused_sources(tmp_path: Path) -> None:
    rsi, sma = _seed_rsi_sma(tmp_path)
    store = AnalysisDatabaseStore(historical_root=tmp_path)
    draft = _draft(store, feature=rsi)
    editor = AnalysisDatabaseComponentEditor(historical_root=tmp_path)
    editor.add_components(
        market=_market(),
        database_id=draft.database_id,
        feature_sources=(sma[0],),
        feature_columns=(sma[1],),
    )
    store.materialize_database(market=_market(), database_id=draft.database_id)

    report = editor.remove_components(
        market=_market(),
        database_id=draft.database_id,
        db_column_names=(rsi[1].db_column_name,),
    )
    updated = report.manifest

    assert updated.status == "draft"
    assert tuple(column.db_column_name for column in updated.feature_columns) == (sma[1].db_column_name,)
    assert tuple(source.source_id for source in updated.feature_sources) == (sma[0].source_id,)
    assert report.dataframe_removed is True


def test_component_editor_rejects_duplicate_database_column_names(tmp_path: Path) -> None:
    _seed_rsi_sma(tmp_path)
    store = AnalysisDatabaseStore(historical_root=tmp_path)
    rsi = _feature(
        family="oscillators",
        tool_key="rsi",
        tool_title="RSI",
        instance_key="rsi__default__period-14",
        column_name="rsi_14",
    )
    draft = _draft(store, feature=rsi)

    with pytest.raises(ValueError, match="Duplicate Analysis Database db_column_name"):
        AnalysisDatabaseComponentEditor(historical_root=tmp_path).replace_components(
            market=_market(),
            database_id=draft.database_id,
            feature_sources=(rsi[0],),
            feature_columns=(rsi[1], rsi[1]),
        )


def test_component_editor_rejects_missing_source_reference(tmp_path: Path) -> None:
    rsi, sma = _seed_rsi_sma(tmp_path)
    store = AnalysisDatabaseStore(historical_root=tmp_path)
    draft = _draft(store, feature=rsi)

    with pytest.raises(ValueError, match="references missing source_id"):
        AnalysisDatabaseComponentEditor(historical_root=tmp_path).replace_components(
            market=_market(),
            database_id=draft.database_id,
            feature_sources=(rsi[0],),
            feature_columns=(sma[1],),
        )
