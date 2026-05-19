from __future__ import annotations

import pandas as pd
import pytest

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


def _write_ohlcv(root, market):
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


def _write_rsi(root, market):
    path = root / market.exchange / market.market_type / market.symbol / market.timeframe / "oscillators" / "rsi__default__period-14.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        {
            "ts_ms": [1000, 2000, 3000],
            "rsi_14": [45.0, 55.0, 65.0],
        }
    ).to_csv(path, index=False)
    return path


def _build_rsi_manifest(store, market):
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
        params_status="inferred",
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
    manifest = store.build_draft_manifest(
        market=market,
        display_name="BTCUSDT_30m_rsi_database",
        user_description="RSI materialization smoke test.",
        include_volume=True,
        feature_sources=(source,),
        feature_columns=(column,),
    )
    store.save_manifest(manifest)
    return manifest


def test_analysis_database_materializes_dataframe_csv(tmp_path):
    market = canonicalize("bybit", "linear", "BTCUSDT", "30m")
    _write_ohlcv(tmp_path, market)
    _write_rsi(tmp_path, market)

    store = AnalysisDatabaseStore(historical_root=tmp_path)
    draft = _build_rsi_manifest(store, market)

    materialized = store.materialize_database(market=market, database_id=draft.database_id)
    dataframe_path = store.dataframe_path(market=market, database_id=draft.database_id)
    dataframe = store.load_dataframe(market=market, database_id=draft.database_id)

    assert dataframe_path.exists()
    assert materialized.status == "materialized"
    assert materialized.dataframe_filename == "dataframe.csv"
    assert materialized.materialization is not None
    assert materialized.materialization.row_count == 3
    assert materialized.materialization.column_count == 7
    assert materialized.materialization.first_ts_ms == 1000
    assert materialized.materialization.last_ts_ms == 3000
    assert materialized.materialization.dataframe_sha256
    assert "oscillator__rsi__rsi_default_period_14__rsi_14" in dataframe.columns
    assert dataframe["oscillator__rsi__rsi_default_period_14__rsi_14"].tolist() == [45.0, 55.0, 65.0]


def test_analysis_database_rejects_duplicate_artifact_timestamps(tmp_path):
    market = canonicalize("bybit", "linear", "BTCUSDT", "30m")
    _write_ohlcv(tmp_path, market)
    rsi_path = _write_rsi(tmp_path, market)
    pd.DataFrame({"ts_ms": [1000, 1000], "rsi_14": [45.0, 46.0]}).to_csv(rsi_path, index=False)

    store = AnalysisDatabaseStore(historical_root=tmp_path)
    draft = _build_rsi_manifest(store, market)

    with pytest.raises(ValueError, match="duplicate ts_ms"):
        store.materialize_database(market=market, database_id=draft.database_id)