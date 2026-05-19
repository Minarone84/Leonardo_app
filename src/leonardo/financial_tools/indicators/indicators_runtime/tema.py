from __future__ import annotations

from typing import Any, Dict

import numpy as np
import pandas as pd

from .common import coerce_positive_int, ema_strict, get_time_cols, require_column
from .contracts import IndicatorLine, IndicatorResult


def calculate_tema_result(dcd_df: pd.DataFrame, params: Dict[str, Any], context: Any = None) -> IndicatorResult:
    """
    Compute TEMA with full-chain warm-up enforcement.

    Why this matters:
    - TEMA is defined from a three-stage EMA chain
    - if ema2/ema3 are allowed to start with ``min_periods=1``, the output
      becomes numerically populated before the chain is honestly mature
    - that creates early values which look valid but are still under-warmed

    Contract enforced here:
    - ema1, ema2, and ema3 all use the same strict EMA warm-up policy
    - the final TEMA line is considered renderable only where the full chain
      has matured
    """
    close = require_column(dcd_df, "close").astype(float)
    period = coerce_positive_int(params.get("period"), "period")

    ema1 = ema_strict(close, period)
    ema2 = ema_strict(ema1, period)
    ema3 = ema_strict(ema2, period)
    tema = 3.0 * ema1 - 3.0 * ema2 + ema3

    # The final line is valid only when the deepest EMA stage is valid.
    tema = tema.where(ema3.notna(), np.nan)

    time_col, timeframe_col = get_time_cols(dcd_df)

    line_key = f"tema_{period}"
    line = IndicatorLine(
        key=line_key,
        title=line_key,
        values=pd.Series(tema, index=dcd_df.index).astype("float32"),
    )

    return IndicatorResult(
        name="tema",
        title=f"TEMA({period})",
        kind="overlay",
        lines=[line],
        index=dcd_df.index,
        time=time_col,
        timeframe=timeframe_col,
        params={"period": period},
    )
