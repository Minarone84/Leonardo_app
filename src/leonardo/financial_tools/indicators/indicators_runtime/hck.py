from __future__ import annotations

from typing import Any, Dict

import pandas as pd

from .common import coerce_positive_int, ew_vwap, get_time_cols, require_column, resolve_volume_column
from .contracts import IndicatorLine, IndicatorResult


def calculate_hck_result(dcd_df: pd.DataFrame, params: Dict[str, Any], context: Any = None) -> IndicatorResult:
    high = require_column(dcd_df, "high").astype(float)
    low = require_column(dcd_df, "low").astype(float)
    close = require_column(dcd_df, "close").astype(float)
    vol_col = resolve_volume_column(dcd_df)
    vol = dcd_df[vol_col].astype(float)

    fast_l = coerce_positive_int(params.get("fast_vwap_l"), "fast_vwap_l")
    slow_l = coerce_positive_int(params.get("slow_vwap_l"), "slow_vwap_l")

    hlc3 = (high + low + close) / 3.0
    fast_vwap = ew_vwap(hlc3, vol, fast_l)
    slow_vwap = ew_vwap(hlc3, vol, slow_l)

    vwap_color = pd.Series(
        pd.Categorical(["silver"] * len(dcd_df), categories=["red", "silver", "green"]),
        index=dcd_df.index,
    )
    vwap_color = vwap_color.mask(fast_vwap > slow_vwap, "green")
    vwap_color = vwap_color.mask(fast_vwap < slow_vwap, "red")

    time_col, timeframe_col = get_time_cols(dcd_df)

    lines = [
        IndicatorLine("fast_vwap", "fast_vwap", pd.Series(fast_vwap, index=dcd_df.index).astype("float32")),
        IndicatorLine("slow_vwap", "slow_vwap", pd.Series(slow_vwap, index=dcd_df.index).astype("float32")),
        IndicatorLine("vwap_color", "vwap_color", pd.Series(vwap_color, index=dcd_df.index)),
    ]

    return IndicatorResult(
        name="hck",
        title=f"HCK({fast_l},{slow_l})",
        kind="overlay",
        lines=lines,
        index=dcd_df.index,
        time=time_col,
        timeframe=timeframe_col,
        params={"fast_vwap_l": fast_l, "slow_vwap_l": slow_l},
    )
