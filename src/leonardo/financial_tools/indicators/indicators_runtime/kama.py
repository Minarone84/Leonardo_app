from __future__ import annotations

from typing import Any, Dict

import numpy as np
import pandas as pd

from .common import coerce_positive_int, get_time_cols, require_column
from .contracts import IndicatorLine, IndicatorResult


def calculate_kama_result(dcd_df: pd.DataFrame, params: Dict[str, Any], context: Any = None) -> IndicatorResult:
    close = require_column(dcd_df, "close").astype(float)
    fast_period = coerce_positive_int(params.get("fast_period"), "fast_period")
    slow_period = coerce_positive_int(params.get("slow_period"), "slow_period")

    change = close.diff(periods=slow_period).abs()
    volatility = close.diff().abs().rolling(window=slow_period, min_periods=slow_period).sum()
    er = (change / (volatility + 1e-12)).clip(0.0, 1.0).fillna(0.0)

    fastest = 2.0 / (fast_period + 1.0)
    slowest = 2.0 / (slow_period + 1.0)
    sc = (er * (fastest - slowest) + slowest) ** 2

    sma_seed = close.rolling(slow_period, min_periods=slow_period).mean()
    kama = np.full(len(close), np.nan, dtype=float)
    start = slow_period - 1
    if start >= 0 and start < len(close) and not np.isnan(sma_seed.iloc[start]):
        kama[start] = float(sma_seed.iloc[start])
        for i in range(start + 1, len(close)):
            kama[i] = kama[i - 1] + sc.iloc[i] * (close.iloc[i] - kama[i - 1])

    time_col, timeframe_col = get_time_cols(dcd_df)

    line_key = f"kama_{fast_period}_{slow_period}"
    line = IndicatorLine(
        key=line_key,
        title=line_key,
        values=pd.Series(kama, index=dcd_df.index).astype("float32"),
    )

    return IndicatorResult(
        name="kama",
        title=f"KAMA({fast_period},{slow_period})",
        kind="overlay",
        lines=[line],
        index=dcd_df.index,
        time=time_col,
        timeframe=timeframe_col,
        params={"fast_period": fast_period, "slow_period": slow_period},
    )
