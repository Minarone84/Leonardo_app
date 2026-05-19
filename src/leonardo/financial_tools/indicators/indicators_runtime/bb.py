from __future__ import annotations

from typing import Any, Dict

import pandas as pd

from .common import coerce_positive_float, coerce_positive_int, get_time_cols, require_column
from .contracts import IndicatorLine, IndicatorResult


def calculate_bb_result(dcd_df: pd.DataFrame, params: Dict[str, Any], context: Any = None) -> IndicatorResult:
    close = require_column(dcd_df, "close").astype(float)
    period = coerce_positive_int(params.get("period"), "period")
    std_mult = coerce_positive_float(params.get("std"), "std")

    mid = close.rolling(window=period, min_periods=period).mean()
    sd = close.rolling(window=period, min_periods=period).std(ddof=0)
    up = mid + std_mult * sd
    dn = mid - std_mult * sd

    time_col, timeframe_col = get_time_cols(dcd_df)

    lines = [
        IndicatorLine("bb_middle", "bb_middle", pd.Series(mid, index=dcd_df.index).astype("float32")),
        IndicatorLine("bb_upper_band", "bb_upper_band", pd.Series(up, index=dcd_df.index).astype("float32")),
        IndicatorLine("bb_lower_band", "bb_lower_band", pd.Series(dn, index=dcd_df.index).astype("float32")),
    ]

    return IndicatorResult(
        name="bb",
        title=f"BB({period},{std_mult})",
        kind="overlay",
        lines=lines,
        index=dcd_df.index,
        time=time_col,
        timeframe=timeframe_col,
        params={"period": period, "std": std_mult},
    )
