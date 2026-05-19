from __future__ import annotations

from typing import Any, Dict

import pandas as pd

from .common import coerce_positive_int, ema_strict, get_time_cols, require_column
from .contracts import IndicatorLine, IndicatorResult


def calculate_ema_result(dcd_df: pd.DataFrame, params: Dict[str, Any], context: Any = None) -> IndicatorResult:
    close = require_column(dcd_df, "close").astype(float)
    period = coerce_positive_int(params.get("period"), "period")

    ema = ema_strict(close, period)
    time_col, timeframe_col = get_time_cols(dcd_df)

    line_key = f"ema_{period}"
    line = IndicatorLine(
        key=line_key,
        title=line_key,
        values=pd.Series(ema, index=dcd_df.index).astype("float32"),
    )

    return IndicatorResult(
        name="ema",
        title=f"EMA({period})",
        kind="overlay",
        lines=[line],
        index=dcd_df.index,
        time=time_col,
        timeframe=timeframe_col,
        params={"period": period},
    )
