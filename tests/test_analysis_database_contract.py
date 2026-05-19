from __future__ import annotations

from leonardo.data.historical.analysis_database_contracts import (
    AnalysisDatabaseColumn,
    AnalysisFeatureSource,
    AnalysisMetadataEntry,
)
from leonardo.data.historical.analysis_database_naming import (
    build_database_column_name,
    build_feature_source_id,
)
from leonardo.data.historical.analysis_database_store import AnalysisDatabaseStore
from leonardo.data.naming import canonicalize


def test_analysis_database_draft_manifest_roundtrip(tmp_path):
    market = canonicalize("bybit", "linear", "BTC/USDT", "30m")
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
        metadata=(
            AnalysisMetadataEntry(
                namespace="analysis",
                key="feature_group",
                value="momentum",
                searchable=True,
            ),
        ),
    )

    store = AnalysisDatabaseStore(historical_root=tmp_path)
    manifest = store.build_draft_manifest(
        market=market,
        display_name="BTCUSDT_30m_trend_pack",
        user_description="Trend continuation test set.",
        feature_sources=(source,),
        feature_columns=(column,),
    )
    manifest_path = store.save_manifest(manifest)

    loaded = store.load_manifest(market=market, database_id=manifest.database_id)
    assert loaded.database_id == manifest.database_id
    assert loaded.display_name == "BTCUSDT_30m_trend_pack"
    assert loaded.status == "draft"
    assert loaded.description.user_text == "Trend continuation test set."
    assert loaded.feature_sources[0].params == {"period": 14}
    assert loaded.feature_columns[0].db_column_name == "oscillator__rsi__rsi_default_period_14__rsi_14"
    assert manifest_path.name == "manifest.json"

    summaries = store.list_databases(market=market)
    assert len(summaries) == 1
    assert summaries[0].database_id == manifest.database_id
    assert summaries[0].feature_count == 1