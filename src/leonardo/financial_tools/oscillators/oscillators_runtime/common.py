from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


def get_time_cols(df: pd.DataFrame):
    """
    Return 'time' and 'timeframe' passthrough columns. If absent:
      - 'time' uses the index
      - 'timeframe' is a string-NA series aligned with the index
    """
    time_col = df["time"] if "time" in df.columns else pd.Series(df.index, index=df.index)
    if "timeframe" in df.columns:
        timeframe_col = df["timeframe"]
    else:
        timeframe_col = pd.Series(pd.NA, index=df.index, dtype="string")
    return time_col, timeframe_col


def require_dataframe(df: Any) -> pd.DataFrame:
    if not isinstance(df, pd.DataFrame):
        raise TypeError("Oscillator input 'dcd' must be a pandas.DataFrame.")
    return df


def require_column(df: pd.DataFrame, column_name: str) -> pd.Series:
    if column_name not in df.columns:
        raise KeyError(f"Required column '{column_name}' is missing from oscillator input.")
    return df[column_name]


def resolve_volume_column(df: pd.DataFrame) -> str:
    if "Volume" in df.columns:
        return "Volume"
    if "volume" in df.columns:
        return "volume"
    raise KeyError("Required volume column is missing from oscillator input. Expected 'Volume' or 'volume'.")


def coerce_positive_int(value: Any, param_name: str) -> int:
    try:
        out = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Parameter '{param_name}' must be an integer.") from exc

    if out <= 0:
        raise ValueError(f"Parameter '{param_name}' must be > 0.")
    return out


def coerce_positive_float(value: Any, param_name: str) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Parameter '{param_name}' must be a float.") from exc

    if out <= 0.0:
        raise ValueError(f"Parameter '{param_name}' must be > 0.")
    return out


def coerce_bool(value: Any, param_name: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, np.integer)):
        return bool(value)
    if isinstance(value, str):
        s = value.strip().lower()
        if s in {"true", "1", "yes", "y", "on"}:
            return True
        if s in {"false", "0", "no", "n", "off"}:
            return False
    raise ValueError(f"Parameter '{param_name}' must be a boolean.")


def rma_wilder(x: pd.Series, n: int) -> pd.Series:
    """
    Strict Wilder RMA with leading-NaN-aware SMA seeding.

    Why this exists
    ---------------
    Many oscillator inputs are built from `diff()`, so their first element is
    naturally NaN. Seeding the Wilder average at positional index `n - 1`
    would then use only `n - 1` actual observations and shift the entire
    oscillator one bar too early.

    This implementation instead:
    - finds the first `n` *valid* observations
    - seeds on the index of the nth valid observation
    - leaves all earlier rows as NaN

    That keeps Wilder-style oscillators aligned with the actual number of
    usable bars rather than with raw positional offsets.
    """
    x = pd.to_numeric(x, errors="coerce").astype(float)
    out = pd.Series(np.nan, index=x.index, dtype=float)

    valid_positions = np.flatnonzero(x.notna().to_numpy())
    if len(valid_positions) < n:
        return out

    seed_positions = valid_positions[:n]
    seed_end_pos = int(seed_positions[-1])
    seed = float(x.iloc[seed_positions].mean())
    out.iloc[seed_end_pos] = seed

    alpha = 1.0 / n
    prev = seed

    for i in range(seed_end_pos + 1, len(x)):
        value = x.iloc[i]
        if pd.isna(value):
            out.iloc[i] = np.nan
            continue

        prev = alpha * float(value) + (1.0 - alpha) * prev
        out.iloc[i] = prev

    return out


def rsi_from_avg_gain_loss(avg_gain: pd.Series, avg_loss: pd.Series) -> pd.Series:
    """
    Convert Wilder-smoothed gain/loss averages into canonical RSI values.

    Edge handling is explicit:
    - avg_gain > 0 and avg_loss == 0 -> 100
    - avg_gain == 0 and avg_loss > 0 -> 0
    - avg_gain == 0 and avg_loss == 0 -> 50
    - insufficient-history NaNs remain NaN
    """
    rs = avg_gain / avg_loss
    rsi = 100.0 - 100.0 / (1.0 + rs)

    zero_loss = avg_loss == 0
    zero_gain = avg_gain == 0
    both_zero = zero_loss & zero_gain

    rsi = rsi.mask(zero_loss & ~zero_gain, 100.0)
    rsi = rsi.mask(zero_gain & ~zero_loss, 0.0)
    rsi = rsi.mask(both_zero, 50.0)
    return rsi


def mfi_from_flow_sums(pos_sum: pd.Series, neg_sum: pd.Series) -> pd.Series:
    """
    Convert rolling positive/negative money-flow sums into canonical MFI.

    Edge handling is explicit:
    - pos_sum > 0 and neg_sum == 0 -> 100
    - pos_sum == 0 and neg_sum > 0 -> 0
    - pos_sum == 0 and neg_sum == 0 -> 50
    - insufficient-history NaNs remain NaN

    This avoids the old bug where `neg_sum == 0` collapsed to NaN and was
    later rewritten to a fake neutral 50.
    """
    mfr = pos_sum / neg_sum.replace(0.0, np.nan)
    mfi = 100.0 - 100.0 / (1.0 + mfr)

    neg_zero = neg_sum == 0
    pos_zero = pos_sum == 0
    both_zero = neg_zero & pos_zero

    mfi = mfi.mask(neg_zero & ~pos_zero, 100.0)
    mfi = mfi.mask(pos_zero & ~neg_zero, 0.0)
    mfi = mfi.mask(both_zero, 50.0)
    return mfi


def apply_smoother(x: pd.Series, n: int, mode: str) -> pd.Series:
    mode = str(mode).upper()
    if mode == "EMA":
        return x.ewm(span=n, adjust=False, min_periods=n).mean()
    if mode == "RMA":
        return rma_wilder(x, n)
    if mode == "SMA":
        return x.rolling(window=n, min_periods=n).mean()
    raise ValueError(f"Unsupported smoothing type: {mode}")
