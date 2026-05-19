from __future__ import annotations

from pathlib import Path

from leonardo.data.historical.artifact_metadata_naming import (
    artifact_family_for_storage_family,
    build_artifact_id,
    build_artifact_uid,
    csv_path_for_metadata,
    format_ts_ms_rome,
    format_ts_ms_utc,
    metadata_path_for_csv,
    new_unique_id,
    slugify_artifact_segment,
    storage_family_for_artifact_family,
)
from leonardo.data.naming import canonicalize


def test_csv_metadata_sidecar_path_roundtrip():
    csv = Path("oscillators") / "rsi__default__period-14.csv"
    meta = metadata_path_for_csv(csv)
    assert meta == Path("oscillators") / "rsi__default__period-14.meta.json"
    assert csv_path_for_metadata(meta) == csv


def test_artifact_family_storage_family_mapping():
    assert storage_family_for_artifact_family("indicator") == "indicators"
    assert storage_family_for_artifact_family("analysis_database") == "analysis_databases"
    assert artifact_family_for_storage_family("constructs") == "construct"


def test_artifact_id_and_uid_policy():
    market = canonicalize("bybit", "linear", "BTC/USDT", "30m")
    artifact_id = build_artifact_id(
        artifact_family="oscillator",
        tool_key="rsi",
        instance_key="rsi__default__period-14",
    )
    assert artifact_id == "oscillator__rsi__rsi_default_period_14"
    assert build_artifact_uid(market=market, artifact_family="oscillator", artifact_id=artifact_id) == (
        "oscillator:bybit:linear:BTCUSDT:30m:oscillator__rsi__rsi_default_period_14"
    )
    assert build_artifact_id(artifact_family="ohlcv") == "ohlcv__candles"
    assert build_artifact_id(artifact_family="analysis_database", database_id="adb__btc_pack__h123abcd") == (
        "database__adb_btc_pack_h123abcd"
    )


def test_timestamp_formatting_utc_and_rome():
    ts_ms = 1_609_459_200_000  # 2021-01-01 00:00:00 UTC
    assert format_ts_ms_utc(ts_ms) == "2021-01-01 00:00:00 UTC"
    assert format_ts_ms_rome(ts_ms) == "2021-01-01 01:00:00 Europe/Rome"
    assert format_ts_ms_utc(None) == "(n/a)"
    assert format_ts_ms_rome("not-a-ts") == "(n/a)"


def test_slug_and_unique_id():
    assert slugify_artifact_segment("RSI__Default__Period-14") == "rsi_default_period_14"
    unique_id = new_unique_id()
    assert len(unique_id) == 32
    assert unique_id.isalnum()
