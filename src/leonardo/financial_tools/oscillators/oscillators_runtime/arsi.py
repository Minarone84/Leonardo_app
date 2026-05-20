from __future__ import annotations

from typing import Any, Dict

import numpy as np
import pandas as pd

from leonardo.financial_tools.naming_runtime.oscillators import build_arsi_signal_names

from .common import apply_smoother, coerce_positive_int, get_time_cols, require_column
from .contracts import OscillatorLine, OscillatorResult


SUPPORTED_ARSI_SMOOTHERS = {"EMA", "SMA", "RMA", "TMA"}


def _coerce_arsi_smoother(value: Any, param_name: str, default: str) -> str:
    text = str(default if value is None else value).strip().upper()
    if text not in SUPPORTED_ARSI_SMOOTHERS:
        supported = ", ".join(sorted(SUPPORTED_ARSI_SMOOTHERS))
        raise ValueError(f"Parameter '{param_name}' must be one of: {supported}.")
    return text


def calculate_arsi_result(dcd_df: pd.DataFrame, params: Dict[str, Any], context: Any = None) -> OscillatorResult:
    """
    Normalized Ultimate RSI-style ARSI computation.

    The runtime emits the primary ARSI line and a configurable signal/mean line.
    Warm-up NaNs remain NaN. Only a mathematically flat regime where the
    numerator and denominator are both zero is rewritten to 50.
    """
    close = require_column(dcd_df, "close").astype(float)
    period = coerce_positive_int(params.get("period", 14), "period")
    method = _coerce_arsi_smoother(params.get("method", "RMA"), "method", "RMA")
    signal_period = coerce_positive_int(params.get("signal_period", 14), "signal_period")
    signal_method = _coerce_arsi_smoother(
        params.get("signal_method", "EMA"),
        "signal_method",
        "EMA",
    )

    upper = close.rolling(window=period, min_periods=period).max()
    lower = close.rolling(window=period, min_periods=period).min()
    price_range = upper - lower
    delta = close.diff()

    upper_break = upper > upper.shift(1)
    lower_break = lower < lower.shift(1)
    diff = delta.copy()
    diff = diff.mask(upper_break, price_range)
    diff = diff.mask(~upper_break & lower_break, -price_range)

    num = apply_smoother(diff, period, method)
    den = apply_smoother(diff.abs(), period, method)

    ratio = num / den.replace(0.0, np.nan)
    arsi = 50.0 + 50.0 * ratio

    zero_den = den == 0
    zero_num = num == 0
    both_zero = zero_den & zero_num

    arsi = arsi.mask(both_zero, 50.0)
    arsi = arsi.replace([np.inf, -np.inf], np.nan).clip(0.0, 100.0)
    signal = apply_smoother(arsi, signal_period, signal_method)

    arsi_key, signal_key = build_arsi_signal_names(
        period,
        method,
        signal_period,
        signal_method,
    )
    lines = [
        OscillatorLine(
            key=arsi_key,
            title=arsi_key,
            values=pd.Series(arsi, index=dcd_df.index).astype("float32"),
        ),
        OscillatorLine(
            key=signal_key,
            title=signal_key,
            values=pd.Series(signal, index=dcd_df.index).astype("float32"),
        ),
    ]

    time_col, timeframe_col = get_time_cols(dcd_df)

    return OscillatorResult(
        name="arsi",
        title=f"ARSI({period},{method})",
        kind="oscillator",
        lines=lines,
        index=dcd_df.index,
        time=time_col,
        timeframe=timeframe_col,
        params={
            "period": period,
            "method": method,
            "signal_period": signal_period,
            "signal_method": signal_method,
        },
    )
