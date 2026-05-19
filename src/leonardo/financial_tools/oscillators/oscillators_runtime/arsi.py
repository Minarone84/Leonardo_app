from __future__ import annotations

from typing import Any, Dict

import numpy as np
import pandas as pd

from .common import coerce_bool, coerce_positive_int, get_time_cols, require_column, rma_wilder
from .contracts import OscillatorLine, OscillatorResult


def _build_arsi_signal_name(period: int) -> str:
    return f"arsi_{period}"


def calculate_arsi_result(dcd_df: pd.DataFrame, params: Dict[str, Any], context: Any = None) -> OscillatorResult:
    """
    Normalized ARSI computation.

    Preserves original financial meaning:
      - single RMA smoother on signed and absolute deltas
      - optional breakout boost on fresh Donchian highs/lows
      - explicit flat-regime neutrality
      - preserved index

    Critical honesty rule
    ---------------------
    Warm-up NaNs must stay NaN. Only a *mathematically flat* regime is
    rewritten to 50. Missing history is not a market-neutral signal.
    """
    close = require_column(dcd_df, "close").astype(float)
    n = coerce_positive_int(params.get("period"), "period")
    boost = coerce_bool(params.get("boost_breakouts", True), "boost_breakouts")

    delta = close.diff()

    if boost:
        highest = close.rolling(n, min_periods=n).max()
        lowest = close.rolling(n, min_periods=n).min()
        rng = highest - lowest

        new_high = (highest > highest.shift(1)).fillna(False)
        new_low = (lowest < lowest.shift(1)).fillna(False)

        diff_p = delta.copy()
        diff_p[new_high] = rng[new_high]
        diff_p[new_low] = -rng[new_low]
    else:
        diff_p = delta

    num = rma_wilder(diff_p.fillna(0.0), n)
    den = rma_wilder(diff_p.abs().fillna(0.0), n)

    ratio = num / den.replace(0.0, np.nan)
    arsi = 50.0 + 50.0 * ratio

    zero_den = den == 0
    zero_num = num == 0
    both_zero = zero_den & zero_num

    arsi = arsi.mask(both_zero, 50.0)
    arsi = arsi.replace([np.inf, -np.inf], np.nan).clip(0.0, 100.0)

    line_key = _build_arsi_signal_name(n)
    line = OscillatorLine(
        key=line_key,
        title=line_key,
        values=pd.Series(arsi, index=dcd_df.index).astype("float32"),
    )

    time_col, timeframe_col = get_time_cols(dcd_df)

    return OscillatorResult(
        name="arsi",
        title=f"ARSI({n})",
        kind="oscillator",
        lines=[line],
        index=dcd_df.index,
        time=time_col,
        timeframe=timeframe_col,
        params={"period": n, "boost_breakouts": boost},
    )
