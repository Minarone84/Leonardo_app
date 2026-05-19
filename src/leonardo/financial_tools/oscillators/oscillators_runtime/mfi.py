from __future__ import annotations

from typing import Any, Dict

import pandas as pd

from .common import (
    coerce_positive_int,
    get_time_cols,
    mfi_from_flow_sums,
    require_column,
    resolve_volume_column,
)
from .contracts import OscillatorLine, OscillatorResult


def _build_mfi_signal_name(period: int) -> str:
    return f"mfi_{period}"


def calculate_mfi_result(dcd_df: pd.DataFrame, params: Dict[str, Any], context: Any = None) -> OscillatorResult:
    """
    Normalized canonical MFI computation.

    Critical edge handling
    ----------------------
    MFI must distinguish between:
    - all-positive flow   -> 100
    - all-negative flow   -> 0
    - no flow at all      -> 50
    - insufficient history -> NaN

    The old global `fillna(50.0)` behavior incorrectly turned the
    `pos_sum > 0, neg_sum == 0` case into a fake neutral reading.
    """
    high = require_column(dcd_df, "high").astype(float)
    low = require_column(dcd_df, "low").astype(float)
    close = require_column(dcd_df, "close").astype(float)
    vol_col = resolve_volume_column(dcd_df)
    volume = dcd_df[vol_col].astype(float)

    period = coerce_positive_int(params.get("period"), "period")

    tp = (high + low + close) / 3.0
    dtp = tp.diff()

    pos_flow = (tp * volume).where(dtp > 0, 0.0)
    neg_flow = (tp * volume).where(dtp < 0, 0.0)

    pos_sum = pos_flow.rolling(window=period, min_periods=period).sum()
    neg_sum = neg_flow.rolling(window=period, min_periods=period).sum()

    mfi = mfi_from_flow_sums(pos_sum, neg_sum)

    time_col, timeframe_col = get_time_cols(dcd_df)
    line_key = _build_mfi_signal_name(period)

    line = OscillatorLine(
        key=line_key,
        title=line_key,
        values=pd.Series(mfi, index=dcd_df.index).astype("float32"),
    )

    return OscillatorResult(
        name="mfi",
        title=f"MFI({period})",
        kind="oscillator",
        lines=[line],
        index=dcd_df.index,
        time=time_col,
        timeframe=timeframe_col,
        params={"period": period},
    )
