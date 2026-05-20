from __future__ import annotations

import numpy as np
import pandas as pd

from leonardo.financial_tools.ft_specs import (
    format_output_names,
    format_output_signals,
    get_oscillator_visual_spec,
    get_tool_spec,
)
from leonardo.financial_tools.naming_runtime.oscillators import get_oscillator_signal_names
from leonardo.financial_tools.oscillators.oscillators import Oscillators
from leonardo.financial_tools.oscillators.oscillators_runtime.contracts import OscillatorRequest
from leonardo.gui.chart.study_style_defaults import build_default_series_style


def _sample_ohlcv_frame() -> pd.DataFrame:
    idx = pd.RangeIndex(80)
    close = [
        100.0
        + idx_value * 0.25
        + np.sin(idx_value / 3.0) * 4.0
        + np.cos(idx_value / 7.0) * 2.0
        for idx_value in idx
    ]
    return pd.DataFrame(
        {
            "time": pd.date_range("2024-01-01", periods=len(idx), freq="h"),
            "timeframe": ["1h"] * len(idx),
            "close": close,
        },
        index=idx,
    )


def test_arsi_runtime_emits_main_and_signal_lines_with_default_params() -> None:
    df = _sample_ohlcv_frame()

    result = Oscillators.calculate(
        OscillatorRequest(
            name="arsi",
            data=df,
            params={},
        )
    )

    assert [line.key for line in result.lines] == [
        "arsi_14_rma",
        "arsi_signal_14_rma_14_ema",
    ]
    assert result.index.equals(df.index)
    assert result.time is not None
    assert result.timeframe is not None

    main = result.lines[0].values
    signal = result.lines[1].values
    assert main.index.equals(df.index)
    assert signal.index.equals(df.index)
    assert pd.api.types.is_float_dtype(main)
    assert pd.api.types.is_float_dtype(signal)

    finite_main = main.dropna()
    assert not finite_main.empty
    assert finite_main.between(0.0, 100.0).all()

    aligned = pd.concat([main, signal], axis=1).dropna()
    assert not aligned.empty
    assert not np.allclose(aligned.iloc[:, 0], aligned.iloc[:, 1])


def test_arsi_runtime_ignores_legacy_boost_breakouts_param() -> None:
    df = _sample_ohlcv_frame()

    result = Oscillators.calculate(
        OscillatorRequest(
            name="arsi",
            data=df,
            params={"boost_breakouts": True},
        )
    )

    assert [line.key for line in result.lines] == [
        "arsi_14_rma",
        "arsi_signal_14_rma_14_ema",
    ]


def test_arsi_naming_specs_visuals_and_gui_defaults_are_two_line_ultimate_rsi() -> None:
    params = {
        "period": 14,
        "method": "RMA",
        "signal_period": 14,
        "signal_method": "EMA",
    }
    expected_names = ("arsi_14_rma", "arsi_signal_14_rma_14_ema")

    assert get_oscillator_signal_names("arsi", **params) == expected_names

    spec = get_tool_spec("arsi")
    assert format_output_names(spec, params) == expected_names

    signals = format_output_signals(spec, params)
    assert tuple(signal.name for signal in signals) == expected_names
    assert all(signal.renderable for signal in signals)
    assert all(signal.analysis_usable for signal in signals)
    assert signals[0].semantic_role == "primary"
    assert signals[1].semantic_role == "signal"

    arsi_visual = get_oscillator_visual_spec("arsi")
    assert arsi_visual is not None
    assert arsi_visual.bounds == (0.0, 100.0)
    arsi_levels = {level.kind: level.value for level in arsi_visual.guide_levels}
    assert arsi_levels == {"overbought": 80.0, "center": 50.0, "oversold": 20.0}

    rsi_visual = get_oscillator_visual_spec("rsi")
    assert rsi_visual is not None
    rsi_levels = {level.kind: level.value for level in rsi_visual.guide_levels}
    assert rsi_levels == {"overbought": 70.0, "center": 50.0, "oversold": 30.0}

    main_style = build_default_series_style(
        study_key="arsi",
        signal_name="arsi_14_rma",
    )
    signal_style = build_default_series_style(
        study_key="arsi",
        signal_name="arsi_signal_14_rma_14_ema",
    )
    assert main_style.color == "#8B5CF6"
    assert signal_style.color == "#FF5D00"
    assert signal_style.render_mode == "line"
