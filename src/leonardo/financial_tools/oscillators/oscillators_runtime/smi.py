from __future__ import annotations

from typing import Any, Dict

import pandas as pd

from .common import coerce_positive_int, get_time_cols, require_column
from .contracts import OscillatorLine, OscillatorResult


def _build_smi_signal_names(k_length: int, d_length: int) -> tuple[str, str]:
    return (
        f"smi_{k_length}_{d_length}",
        f"smi_signal_{k_length}_{d_length}",
    )


def calculate_smi_result(dcd_df: pd.DataFrame, params: Dict[str, Any], context: Any = None) -> OscillatorResult:
    """
    Normalized SMI computation, double-smoothed.
    """
    high = require_column(dcd_df, "high").astype(float)
    low = require_column(dcd_df, "low").astype(float)
    close = require_column(dcd_df, "close").astype(float)

    k_length = coerce_positive_int(params.get("k_length"), "k_length")
    d_length = coerce_positive_int(params.get("d_length"), "d_length")

    ll = low.rolling(window=k_length, min_periods=k_length).min()
    hh = high.rolling(window=k_length, min_periods=k_length).max()

    diff = hh - ll
    rdiff = close - (hh + ll) / 2.0

    avgrel = (
        rdiff.ewm(span=d_length, adjust=False, min_periods=d_length).mean()
        .ewm(span=d_length, adjust=False, min_periods=d_length).mean()
    )
    avgdiff = (
        diff.ewm(span=d_length, adjust=False, min_periods=d_length).mean()
        .ewm(span=d_length, adjust=False, min_periods=d_length).mean()
    )

    smi_val = (avgrel / (avgdiff / 2.0)) * 100.0
    smi_val = smi_val.where(avgdiff != 0, 0.0)

    smi_sig = smi_val.ewm(span=d_length, adjust=False, min_periods=d_length).mean()

    time_col, timeframe_col = get_time_cols(dcd_df)
    smi_key, smi_signal_key = _build_smi_signal_names(k_length, d_length)

    lines = [
        OscillatorLine(
            key=smi_key,
            title=smi_key,
            values=pd.Series(smi_val, index=dcd_df.index).astype("float32"),
        ),
        OscillatorLine(
            key=smi_signal_key,
            title=smi_signal_key,
            values=pd.Series(smi_sig, index=dcd_df.index).astype("float32"),
        ),
    ]

    return OscillatorResult(
        name="smi",
        title=f"SMI({k_length},{d_length})",
        kind="oscillator",
        lines=lines,
        index=dcd_df.index,
        time=time_col,
        timeframe=timeframe_col,
        params={"k_length": k_length, "d_length": d_length},
    )
