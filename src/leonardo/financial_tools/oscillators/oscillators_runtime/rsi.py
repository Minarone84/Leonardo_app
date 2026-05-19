from __future__ import annotations

from typing import Any, Dict

import pandas as pd

from .common import (
    coerce_positive_int,
    get_time_cols,
    require_column,
    rma_wilder,
    rsi_from_avg_gain_loss,
)
from .contracts import OscillatorLine, OscillatorResult


def _build_rsi_signal_name(period: int) -> str:
    return f"rsi_{period}"


def calculate_rsi_result(dcd_df: pd.DataFrame, params: Dict[str, Any], context: Any = None) -> OscillatorResult:
    """
    Normalized Wilder RSI computation, strictly SMA-seeded.

    Preserves original financial meaning:
      - delta from close.diff()
      - gain/loss split
      - strict Wilder RMA
      - explicit edge handling
      - preserved index
    """
    close = require_column(dcd_df, "close").astype(float)
    n = coerce_positive_int(params.get("period"), "period")

    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)

    avg_gain = rma_wilder(gain, n)
    avg_loss = rma_wilder(loss, n)

    rsi = rsi_from_avg_gain_loss(avg_gain, avg_loss)

    line_key = _build_rsi_signal_name(n)
    line = OscillatorLine(
        key=line_key,
        title=line_key,
        values=pd.Series(rsi, index=dcd_df.index).astype("float32"),
    )

    time_col, timeframe_col = get_time_cols(dcd_df)

    return OscillatorResult(
        name="rsi",
        title=f"RSI({n})",
        kind="oscillator",
        lines=[line],
        index=dcd_df.index,
        time=time_col,
        timeframe=timeframe_col,
        params={"period": n},
    )
