from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from leonardo.data.historical.artifact_metadata_contracts import HistoricalCsvArtifactManifest
from leonardo.data.historical.artifact_metadata_naming import metadata_path_for_csv
from leonardo.data.historical.derived_store_csv import DerivedCsvStore
from leonardo.data.naming import canonicalize


def _load_manifest(csv_path: Path) -> HistoricalCsvArtifactManifest:
    with metadata_path_for_csv(csv_path).open("r", encoding="utf-8") as handle:
        return HistoricalCsvArtifactManifest.from_dict(json.load(handle))


def test_derived_store_writes_oscillator_metadata_sidecar_and_preserves_unique_id(tmp_path):
    market = canonicalize("bybit", "linear", "BTC/USDT", "30m")
    store = DerivedCsvStore(historical_root=tmp_path)
    df = pd.DataFrame(
        {
            "time": [1_609_459_200_000, 1_609_462_800_000, 1_609_466_400_000],
            "timeframe": ["30m", "30m", "30m"],
            "rsi_14": [50.0, 55.0, 60.0],
        }
    )

    csv_path = store.save_dataframe(
        market=market,
        kind="oscillators",
        tool_key="rsi",
        instance_key="rsi__default__period-14",
        df=df,
        params={"period": 14},
        params_status="explicit",
        bindings={"source": "close"},
        bindings_status="explicit",
    )
    meta_path = metadata_path_for_csv(csv_path)

    assert csv_path.exists()
    assert meta_path.exists()
    saved = pd.read_csv(csv_path)
    assert list(saved.columns) == ["ts_ms", "time", "timeframe", "rsi_14"]

    manifest = _load_manifest(csv_path)
    assert manifest.identity.artifact_family == "oscillator"
    assert manifest.identity.storage_family == "oscillators"
    assert manifest.identity.artifact_id == "oscillator__rsi__rsi_default_period_14"
    assert manifest.identity.artifact_uid == (
        "oscillator:bybit:linear:BTCUSDT:30m:oscillator__rsi__rsi_default_period_14"
    )
    assert manifest.time_range.first_ts_ms == 1_609_459_200_000
    assert manifest.time_range.first_ts_rome == "2021-01-01 01:00:00 Europe/Rome"
    assert manifest.shape.row_count == 3
    assert manifest.shape.column_count == 4
    assert manifest.tool is not None
    assert manifest.tool.tool_key == "rsi"
    assert manifest.tool.params == {"period": 14}
    assert manifest.tool.params_status == "explicit"
    assert manifest.tool.bindings == {"source": "close"}
    assert manifest.tool.oscillator_visual is not None
    assert {column.name: column.role for column in manifest.columns}["ts_ms"] == "primary_key"

    unique_id = manifest.identity.unique_id
    csv_path_2 = store.save_dataframe(
        market=market,
        kind="oscillators",
        tool_key="rsi",
        instance_key="rsi__default__period-14",
        df=df,
        params={"period": 14},
        params_status="explicit",
        bindings={"source": "close"},
        bindings_status="explicit",
    )
    manifest_2 = _load_manifest(csv_path_2)
    assert manifest_2.identity.unique_id == unique_id


def test_derived_store_sidecar_marks_hck_utility_output_from_contract(tmp_path):
    market = canonicalize("bybit", "linear", "BTCUSDT", "1h")
    store = DerivedCsvStore(historical_root=tmp_path)
    df = pd.DataFrame(
        {
            "ts_ms": [1_609_459_200_000, 1_609_462_800_000],
            "fast_vwap": [1.0, 2.0],
            "slow_vwap": [1.5, 1.6],
            "vwap_color": ["bull", "bear"],
        }
    )

    csv_path = store.save_dataframe(
        market=market,
        kind="indicators",
        tool_key="hck",
        instance_key="hck__default__fast_vwap_l-13__slow_vwap_l-48",
        df=df,
        params={"fast_vwap_l": 13, "slow_vwap_l": 48},
        params_status="explicit",
    )
    manifest = _load_manifest(csv_path)
    columns = {column.name: column for column in manifest.columns}

    assert manifest.identity.artifact_family == "indicator"
    assert manifest.tool is not None
    assert manifest.tool.tool_key == "hck"
    assert columns["fast_vwap"].role == "feature"
    assert columns["fast_vwap"].renderable is True
    assert columns["vwap_color"].role == "utility"
    assert columns["vwap_color"].renderable is False
    assert columns["vwap_color"].analysis_usable is False
    assert columns["vwap_color"].selectable is False


def test_derived_store_writes_construct_metadata_sidecar(tmp_path):
    market = canonicalize("bybit", "linear", "BTCUSDT", "1h")
    store = DerivedCsvStore(historical_root=tmp_path)
    df = pd.DataFrame(
        {
            "ts_ms": [1_609_459_200_000, 1_609_462_800_000],
            "ema_9_ema_21_delta_pct": [0.1, 0.2],
        }
    )

    csv_path = store.save_dataframe(
        market=market,
        kind="constructs",
        tool_key="delta",
        instance_key="delta__fast-ema_9_close__slow-ema_21_close__mode-pct__h123abcd",
        df=df,
        params={"fast": "ema_9_close", "slow": "ema_21_close", "mode": "pct"},
        params_status="explicit",
        bindings={"fast": "ema_9_close", "slow": "ema_21_close"},
        bindings_status="explicit",
    )
    manifest = _load_manifest(csv_path)

    assert manifest.identity.artifact_family == "construct"
    assert manifest.tool is not None
    assert manifest.tool.tool_key == "delta"
    assert manifest.tool.construct_io is not None
    assert manifest.tool.params["mode"] == "pct"
    assert manifest.tool.bindings == {"fast": "ema_9_close", "slow": "ema_21_close"}
    assert manifest.files.metadata_filename.endswith(".meta.json")


def test_derived_store_lists_construct_instances_from_metadata_not_filename(tmp_path):
    market = canonicalize("bybit", "linear", "BTCUSDT", "1h")
    store = DerivedCsvStore(historical_root=tmp_path)
    df = pd.DataFrame(
        {
            "ts_ms": [1_609_459_200_000, 1_609_462_800_000],
            "ema_9_ema_21_delta_pct": [0.1, 0.2],
        }
    )

    store.save_dataframe(
        market=market,
        kind="constructs",
        tool_key="delta",
        instance_key="delta__fast-ema_9_close__slow-ema_21_close__mode-pct__h123abcd",
        df=df,
        params={"fast": "ema_9_close", "slow": "ema_21_close", "mode": "pct"},
        params_status="explicit",
        bindings={"fast": "ema_9_close", "slow": "ema_21_close"},
        bindings_status="explicit",
    )

    all_refs = store.list_instances(market=market, kind="constructs")
    delta_refs = store.list_instances(market=market, kind="constructs", tool_key="delta")

    assert len(all_refs) == 1
    assert all_refs[0].tool_key == "delta"
    assert all_refs[0].instance_key == "delta__fast-ema_9_close__slow-ema_21_close__mode-pct__h123abcd"
    assert delta_refs == all_refs
