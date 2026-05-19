from __future__ import annotations

from typing import Any, Dict

import pandas as pd

from .common import apply_smoother, coerce_positive_float, coerce_positive_int, get_time_cols, require_column
from .contracts import OscillatorLine, OscillatorResult
from .rsi import calculate_rsi_result


def _build_tdirsi_signal_names(
    period: int,
    band_length: int,
    fast_len: int,
    slow_len: int,
    fast_smo: str,
    slow_smo: str,
) -> tuple[str, str, str, str, str]:
    fast_smo_norm = str(fast_smo).strip().lower()
    slow_smo_norm = str(slow_smo).strip().lower()
    suffix = f"{period}_{band_length}_{fast_len}_{slow_len}_{fast_smo_norm}_{slow_smo_norm}"
    return (
        f"tdirsi_fast_ma_{suffix}",
        f"tdirsi_slow_ma_{suffix}",
        f"tdirsi_up_{suffix}",
        f"tdirsi_dn_{suffix}",
        f"tdirsi_mid_{suffix}",
    )


def calculate_tdirsi_result(dcd_df: pd.DataFrame, params: Dict[str, Any], context: Any = None) -> OscillatorResult:
    """
    Normalized TDI computation based on Wilder RSI.
    """
    require_column(dcd_df, "close")

    period = coerce_positive_int(params.get("period"), "period")
    band_length = coerce_positive_int(params.get("band_length"), "band_length")
    band_mult = coerce_positive_float(params.get("band_mult", 1.6185), "band_mult")

    fast_len = coerce_positive_int(params.get("fast_len", 2), "fast_len")
    slow_len = coerce_positive_int(params.get("slow_len", 7), "slow_len")
    fast_smo = str(params.get("fast_smo", "EMA")).upper()
    slow_smo = str(params.get("slow_smo", "RMA")).upper()

    rsi_result = calculate_rsi_result(dcd_df, {"period": period})
    r = rsi_result.lines[0].values.astype(float)

    ma = r.rolling(window=band_length, min_periods=band_length).mean()
    std = r.rolling(window=band_length, min_periods=band_length).std(ddof=0)
    offs = band_mult * std
    up = ma + offs
    dn = ma - offs
    mid = (up + dn) / 2.0

    fast_ma = apply_smoother(r, fast_len, fast_smo)
    slow_ma = apply_smoother(r, slow_len, slow_smo)

    time_col, timeframe_col = get_time_cols(dcd_df)

    fast_ma_key, slow_ma_key, up_key, dn_key, mid_key = _build_tdirsi_signal_names(
        period=period,
        band_length=band_length,
        fast_len=fast_len,
        slow_len=slow_len,
        fast_smo=fast_smo,
        slow_smo=slow_smo,
    )

    lines = [
        OscillatorLine(
            key=fast_ma_key,
            title=fast_ma_key,
            values=pd.Series(fast_ma, index=dcd_df.index).astype("float32"),
        ),
        OscillatorLine(
            key=slow_ma_key,
            title=slow_ma_key,
            values=pd.Series(slow_ma, index=dcd_df.index).astype("float32"),
        ),
        OscillatorLine(
            key=up_key,
            title=up_key,
            values=pd.Series(up, index=dcd_df.index).astype("float32"),
        ),
        OscillatorLine(
            key=dn_key,
            title=dn_key,
            values=pd.Series(dn, index=dcd_df.index).astype("float32"),
        ),
        OscillatorLine(
            key=mid_key,
            title=mid_key,
            values=pd.Series(mid, index=dcd_df.index).astype("float32"),
        ),
    ]

    return OscillatorResult(
        name="tdirsi",
        title=f"TDI RSI({period})",
        kind="oscillator",
        lines=lines,
        index=dcd_df.index,
        time=time_col,
        timeframe=timeframe_col,
        params={
            "period": period,
            "band_length": band_length,
            "band_mult": band_mult,
            "fast_len": fast_len,
            "slow_len": slow_len,
            "fast_smo": fast_smo,
            "slow_smo": slow_smo,
        },
    )
