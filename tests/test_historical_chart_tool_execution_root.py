from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pandas as pd

import leonardo.data.historical.utc_dependency_sources as utc_dependency_sources
from leonardo.data.historical.derived_store_csv import DerivedCsvStore
from leonardo.data.naming import canonicalize
from leonardo.gui.historical_chart.tool_execution import HistoricalChartToolExecutionMixin


class _ChartToolExecutionHarness(HistoricalChartToolExecutionMixin):
    def __init__(self, *, data_dir: Path) -> None:
        self._core = SimpleNamespace(
            context=SimpleNamespace(
                config=SimpleNamespace(
                    runtime=SimpleNamespace(data_dir=str(data_dir)),
                ),
            ),
        )
        self._exchange = "bybit"
        self._market_type = "linear"
        self._symbol = "BTCUSDT"
        self._timeframe = "1h"

    def _build_instance_key(self, tool_key: str, params: dict[str, object]) -> str:
        return str(tool_key)


def test_historical_chart_tool_execution_uses_configured_historical_root(tmp_path: Path) -> None:
    data_dir = tmp_path / "configured_data"
    harness = _ChartToolExecutionHarness(data_dir=data_dir)

    assert harness._historical_root() == data_dir / "historical"


def test_historical_chart_tool_execution_does_not_use_default_root_for_non_default_config(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "configured_data"
    harness = _ChartToolExecutionHarness(data_dir=data_dir)

    assert harness._historical_root() != Path("data") / "historical"


def test_peaks_troughs_dependency_lookup_uses_configured_historical_root(
    tmp_path: Path,
    monkeypatch,
) -> None:
    data_dir = tmp_path / "configured_data"
    configured_root = data_dir / "historical"
    market = canonicalize("bybit", "linear", "BTCUSDT", "1h")
    saved_df = pd.DataFrame(
        {
            "ts_ms": [1_700_000_000_000, 1_700_003_600_000],
            "peak_fractal_5": [0.0, 1.0],
            "trough_fractal_5": [1.0, 0.0],
        }
    )
    DerivedCsvStore(historical_root=configured_root).save_dataframe(
        market=market,
        kind="indicators",
        tool_key="peaks_troughs",
        instance_key="peaks_troughs",
        df=saved_df,
        params={},
        params_status="explicit",
    )

    observed_roots: list[Path] = []
    real_store = DerivedCsvStore

    class _SpyDerivedCsvStore(real_store):
        def __init__(self, *, historical_root: Path) -> None:
            observed_roots.append(Path(historical_root))
            super().__init__(historical_root=historical_root)

    monkeypatch.setattr(utc_dependency_sources, "DerivedCsvStore", _SpyDerivedCsvStore)

    loaded = _ChartToolExecutionHarness(data_dir=data_dir)._load_saved_peaks_troughs_dataframe()

    assert observed_roots == [configured_root]
    assert "peak_fractal_5" in loaded.columns
    assert loaded["peak_fractal_5"].tolist() == [0.0, 1.0]
