from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

import leonardo.data.historical.utc_dependency_sources as utc_dependency_sources
from leonardo.data.historical.derived_store_csv import DerivedCsvStore
from leonardo.data.historical.utc_dependency_sources import (
    prepare_utc_peak_trough_dependencies,
    utc_dependency_role_name,
    utc_peak_trough_columns,
    utc_peak_trough_columns_for_purpose,
)
from leonardo.data.naming import canonicalize


def _market():
    return canonicalize("bybit", "linear", "BTCUSDT", "1h")


def _save_peaks_troughs(root: Path, df: pd.DataFrame, *, instance_key: str = "peaks_troughs") -> None:
    DerivedCsvStore(historical_root=root).save_dataframe(
        market=_market(),
        kind="indicators",
        tool_key="peaks_troughs",
        instance_key=instance_key,
        df=df,
        params={},
        params_status="explicit",
    )


def test_default_utc_dependency_columns() -> None:
    assert utc_peak_trough_columns({"trend_fractal_window": 5, "range_fractal_window": 3}) == (
        "peak_fractal_5",
        "trough_fractal_5",
        "peak_fractal_3",
        "trough_fractal_3",
    )


def test_legacy_fractal_window_fallback_for_trend() -> None:
    assert utc_peak_trough_columns({"fractal_window": 7}) == (
        "peak_fractal_7",
        "trough_fractal_7",
        "peak_fractal_3",
        "trough_fractal_3",
    )


def test_same_trend_and_range_windows_deduplicate_loaded_columns() -> None:
    params = {"trend_fractal_window": 5, "range_fractal_window": 5}

    assert utc_peak_trough_columns(params) == ("peak_fractal_5", "trough_fractal_5")
    assert utc_dependency_role_name(params=params, column_name="peak_fractal_5") == (
        "universal_trend_classifier.trend_range.peak_fractal_5"
    )


def test_explicit_trend_and_range_overrides_are_independent() -> None:
    params = {
        "trend_fractal_window": 5,
        "range_fractal_window": 3,
        "trend_peak_column": "trend_peak",
        "trend_trough_column": "trend_trough",
        "range_peak_column": "range_peak",
        "range_trough_column": "range_trough",
    }

    assert utc_peak_trough_columns_for_purpose(params, purpose="trend") == (
        "trend_peak",
        "trend_trough",
    )
    assert utc_peak_trough_columns_for_purpose(params, purpose="range") == (
        "range_peak",
        "range_trough",
    )
    assert utc_peak_trough_columns(params) == (
        "trend_peak",
        "trend_trough",
        "range_peak",
        "range_trough",
    )


def test_prepare_utc_dependencies_aligns_by_timestamp_not_position(tmp_path: Path) -> None:
    root = tmp_path / "historical"
    _save_peaks_troughs(
        root,
        pd.DataFrame(
            {
                "ts_ms": [1000, 2000, 3000],
                "peak_fractal_5": [10.0, 20.0, 30.0],
                "trough_fractal_5": [11.0, 21.0, 31.0],
                "peak_fractal_3": [12.0, 22.0, 32.0],
                "trough_fractal_3": [13.0, 23.0, 33.0],
            }
        ),
    )
    full_df = pd.DataFrame({"ts_ms": [2000, 1000, 3000], "close": [2.0, 1.0, 3.0]})

    out = prepare_utc_peak_trough_dependencies(
        df=full_df,
        historical_root=root,
        market=_market(),
        params={"trend_fractal_window": 5, "range_fractal_window": 3},
        expected_instance_key="peaks_troughs",
    )

    assert out["peak_fractal_5"].tolist() == [20.0, 10.0, 30.0]
    assert out["trough_fractal_3"].tolist() == [23.0, 13.0, 33.0]
    assert out["close"].tolist() == [2.0, 1.0, 3.0]


def test_prepare_utc_dependencies_rejects_duplicate_source_join_keys(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "duplicate_peaks.csv"
    pd.DataFrame(
        {
            "ts_ms": [1000, 1000],
            "peak_fractal_5": [1.0, 2.0],
            "trough_fractal_5": [3.0, 4.0],
        }
    ).to_csv(path, index=False)

    class _FakeStore:
        def __init__(self, *, historical_root: Path) -> None:
            self.historical_root = historical_root

        def list_instances(self, **_kwargs):
            return [SimpleNamespace(instance_key="peaks_troughs", path=path)]

    monkeypatch.setattr(utc_dependency_sources, "DerivedCsvStore", _FakeStore)

    with pytest.raises(ValueError, match="duplicate join-key values"):
        prepare_utc_peak_trough_dependencies(
            df=pd.DataFrame({"ts_ms": [1000], "close": [1.0]}),
            historical_root=tmp_path / "historical",
            market=_market(),
            params={"trend_fractal_window": 5, "range_fractal_window": 5},
            expected_instance_key="peaks_troughs",
        )


def test_prepare_utc_dependencies_reports_missing_artifact(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="requires a saved Peaks & Troughs indicator"):
        prepare_utc_peak_trough_dependencies(
            df=pd.DataFrame({"ts_ms": [1000], "close": [1.0]}),
            historical_root=tmp_path / "historical",
            market=_market(),
            params={"trend_fractal_window": 5, "range_fractal_window": 3},
        )


def test_prepare_utc_dependencies_reports_missing_required_columns(tmp_path: Path) -> None:
    root = tmp_path / "historical"
    _save_peaks_troughs(
        root,
        pd.DataFrame(
            {
                "ts_ms": [1000],
                "peak_fractal_5": [1.0],
                "trough_fractal_5": [2.0],
            }
        ),
    )

    with pytest.raises(ValueError, match="does not contain the columns required by UTC"):
        prepare_utc_peak_trough_dependencies(
            df=pd.DataFrame({"ts_ms": [1000], "close": [1.0]}),
            historical_root=root,
            market=_market(),
            params={"trend_fractal_window": 5, "range_fractal_window": 3},
            expected_instance_key="peaks_troughs",
        )


def test_chart_and_data_paths_use_shared_utc_dependency_helper() -> None:
    root = Path(__file__).resolve().parents[1]
    chart_source = (root / "src" / "leonardo" / "gui" / "historical_chart" / "tool_execution.py").read_text(
        encoding="utf-8"
    )
    service_source = (
        root / "src" / "leonardo" / "data" / "historical" / "artifact_calculation_service.py"
    ).read_text(encoding="utf-8")
    helper_source = (
        root / "src" / "leonardo" / "data" / "historical" / "utc_dependency_sources.py"
    ).read_text(encoding="utf-8")

    assert "prepare_utc_peak_trough_dependencies" in chart_source
    assert "prepare_utc_peak_trough_dependencies" in service_source
    assert "indicators_runtime.universal_trend_classifier" not in helper_source
