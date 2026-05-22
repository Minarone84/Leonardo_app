from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pandas as pd

from leonardo.data.historical.artifact_metadata_contracts import ArtifactColumnMetadata
from leonardo.data.historical.artifact_metadata_naming import metadata_path_for_csv
from leonardo.data.historical.derived_store_csv import DerivedCsvStore
from leonardo.data.naming import canonicalize
from leonardo.gui.windows.financial_tools_manager_window import FinancialToolsManagerWindow


def _manager_for_root(root: Path) -> FinancialToolsManagerWindow:
    manager = FinancialToolsManagerWindow.__new__(FinancialToolsManagerWindow)
    manager._exchange = "bybit"
    manager._market_type = "linear"
    manager._symbol = "BTCUSDT"
    manager._timeframe = "1h"
    manager._historical_root = root
    return manager


def _save_hc2_indicator_artifact(root: Path) -> Path:
    market = canonicalize("bybit", "linear", "BTCUSDT", "1h")
    store = DerivedCsvStore(historical_root=root)
    df = pd.DataFrame(
        {
            "ts_ms": [1_609_459_200_000, 1_609_462_800_000],
            "time": [1_609_459_200_000, 1_609_462_800_000],
            "timeframe": ["1h", "1h"],
            "alpha": [1.0, 2.0],
            "beta": [3.0, 4.0],
            "utility_state": [0, 1],
            "vwap_color": ["bull", "bear"],
        }
    )
    csv_path = store.save_dataframe(
        market=market,
        kind="indicators",
        tool_key="hck",
        instance_key="hck__hc2_saved_source_metadata",
        df=df,
        params={},
        params_status="explicit",
    )
    manifest = store.load_metadata_manifest(csv_path)
    assert manifest is not None
    updated_manifest = replace(
        manifest,
        columns=(
            ArtifactColumnMetadata(
                name="ts_ms",
                role="primary_key",
                selectable=False,
                analysis_usable=True,
                renderable=False,
                semantic_role="primary_key",
                value_type="int",
            ),
            ArtifactColumnMetadata(
                name="time",
                role="utility",
                selectable=False,
                analysis_usable=False,
                renderable=False,
                semantic_role="metadata",
                value_type="numeric",
            ),
            ArtifactColumnMetadata(
                name="timeframe",
                role="utility",
                selectable=False,
                analysis_usable=False,
                renderable=False,
                semantic_role="metadata",
                value_type="categorical",
            ),
            ArtifactColumnMetadata(
                name="alpha",
                role="feature",
                selectable=True,
                analysis_usable=True,
                renderable=False,
                label="Alpha source",
                semantic_role="primary",
                value_type="numeric",
            ),
            ArtifactColumnMetadata(
                name="beta",
                role="feature",
                selectable=False,
                analysis_usable=True,
                renderable=True,
                semantic_role="primary",
                value_type="numeric",
            ),
            ArtifactColumnMetadata(
                name="utility_state",
                role="utility",
                selectable=False,
                analysis_usable=False,
                renderable=False,
                semantic_role="state",
                value_type="categorical",
            ),
            ArtifactColumnMetadata(
                name="vwap_color",
                role="utility",
                selectable=True,
                analysis_usable=True,
                renderable=False,
                semantic_role="state",
                value_type="categorical",
            ),
        ),
    )
    metadata_path_for_csv(csv_path).write_text(
        json.dumps(updated_manifest.to_dict(), indent=2),
        encoding="utf-8",
    )
    return csv_path


def test_saved_source_selection_uses_sidecar_column_metadata(tmp_path: Path) -> None:
    _save_hc2_indicator_artifact(tmp_path)
    manager = _manager_for_root(tmp_path)

    options = manager._list_saved_source_options("indicator")
    by_column = {str(option["column_name"]): option for option in options}

    assert set(by_column) == {"alpha", "vwap_color"}
    assert by_column["alpha"]["renderable"] is False
    assert by_column["alpha"]["analysis_usable"] is True
    assert by_column["alpha"]["label"] == "Alpha source"
    assert by_column["vwap_color"]["selectable"] is True
    assert by_column["vwap_color"]["analysis_usable"] is True
    assert "beta" not in by_column
    assert "utility_state" not in by_column
    assert "ts_ms" not in by_column
    assert "time" not in by_column
    assert "timeframe" not in by_column


def test_saved_source_selection_falls_back_to_csv_header_without_sidecar(tmp_path: Path) -> None:
    csv_path = tmp_path / "legacy.csv"
    csv_path.write_text(
        "ts_ms,time,timeframe,alpha,vwap_color\n1,1,1h,10,bull\n",
        encoding="utf-8",
    )
    manager = _manager_for_root(tmp_path)
    store = DerivedCsvStore(historical_root=tmp_path)

    columns = manager._read_selectable_columns_from_artifact(csv_path, store=store)

    assert [column["column_name"] for column in columns] == ["alpha"]


def test_saved_source_selection_falls_back_for_malformed_sidecar(tmp_path: Path) -> None:
    csv_path = tmp_path / "legacy.csv"
    csv_path.write_text(
        "ts_ms,time,timeframe,alpha,vwap_color\n1,1,1h,10,bull\n",
        encoding="utf-8",
    )
    metadata_path_for_csv(csv_path).write_text("{not valid json", encoding="utf-8")
    manager = _manager_for_root(tmp_path)
    store = DerivedCsvStore(historical_root=tmp_path)

    columns = manager._read_selectable_columns_from_artifact(csv_path, store=store)

    assert [column["column_name"] for column in columns] == ["alpha"]


def test_saved_source_selection_falls_back_for_incomplete_sidecar(tmp_path: Path) -> None:
    csv_path = _save_hc2_indicator_artifact(tmp_path)
    store = DerivedCsvStore(historical_root=tmp_path)
    manifest = store.load_metadata_manifest(csv_path)
    assert manifest is not None
    metadata_path_for_csv(csv_path).write_text(
        json.dumps(replace(manifest, columns=()).to_dict(), indent=2),
        encoding="utf-8",
    )
    manager = _manager_for_root(tmp_path)

    columns = manager._read_selectable_columns_from_artifact(csv_path, store=store)

    assert [column["column_name"] for column in columns] == ["alpha", "beta", "utility_state"]
