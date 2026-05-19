from __future__ import annotations

from typing import Any, Dict

import pandas as pd

from .common import coerce_positive_int, get_time_cols, resolve_volume_column
from .contracts import OscillatorLine, OscillatorResult


def _build_volume_signal_names(period: int) -> tuple[str, str]:
    return "volume", f"volume_mean_{period}"


def calculate_volume_result(dcd_df: pd.DataFrame, params: Dict[str, Any], context: Any = None) -> OscillatorResult:
    """
    Normalized Volume oscillator computation.

    This exposes canonical traded volume as an oscillator-family artifact and
    adds a configurable rolling mean line for volume context.
    """
    del context

    period = coerce_positive_int(params.get("period"), "period")
    vol_col = resolve_volume_column(dcd_df)
    volume = dcd_df[vol_col].astype(float)
    volume_mean = volume.rolling(window=period, min_periods=period).mean()

    time_col, timeframe_col = get_time_cols(dcd_df)
    volume_key, mean_key = _build_volume_signal_names(period)

    return OscillatorResult(
        name="volume",
        title=f"Volume({period})",
        kind="oscillator",
        lines=[
            OscillatorLine(
                key=volume_key,
                title="Volume",
                values=pd.Series(volume, index=dcd_df.index).astype("float32"),
            ),
            OscillatorLine(
                key=mean_key,
                title=f"Volume Mean({period})",
                values=pd.Series(volume_mean, index=dcd_df.index).astype("float32"),
            ),
        ],
        index=dcd_df.index,
        time=time_col,
        timeframe=timeframe_col,
        params={"period": period},
    )
