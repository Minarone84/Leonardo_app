from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


def get_time_cols(df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    """
    Return 'time' and 'timeframe' columns, preserving input when present.
    If 'timeframe' is absent, create a string-NA Series to avoid float-NaN dtype drift.
    """
    time_col = df["time"] if "time" in df.columns else pd.Series(df.index, index=df.index)
    if "timeframe" in df.columns:
        timeframe_col = df["timeframe"]
    else:
        timeframe_col = pd.Series(pd.NA, index=df.index, dtype="string")
    return time_col, timeframe_col


def require_dataframe(df: Any) -> pd.DataFrame:
    if not isinstance(df, pd.DataFrame):
        raise TypeError("Indicator input 'dcd' must be a pandas.DataFrame.")
    return df


def require_column(df: pd.DataFrame, column_name: str) -> pd.Series:
    if column_name not in df.columns:
        raise KeyError(f"Required column '{column_name}' is missing from indicator input.")
    return df[column_name]


def resolve_volume_column(df: pd.DataFrame) -> str:
    if "Volume" in df.columns:
        return "Volume"
    if "volume" in df.columns:
        return "volume"
    raise KeyError("Required volume column is missing from indicator input. Expected 'Volume' or 'volume'.")


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


def ema_strict(series: pd.Series, period: int) -> pd.Series:
    """
    Compute an EMA with explicit warm-up discipline.

    This helper is the single source of truth for EMA-chain warm-up behavior
    inside the indicator family. It exists primarily so chained indicators
    such as TEMA do not accidentally become numerically defined before every
    EMA stage in the chain has matured.

    Rule:
    - a stage becomes valid only after it has seen ``period`` non-null input
      observations of its own input series
    """
    return series.astype(float).ewm(
        span=period,
        adjust=False,
        min_periods=period,
    ).mean()


def wma(series: pd.Series, window: int) -> pd.Series:
    validated_window = max(1, int(window))
    weights = np.arange(1, validated_window + 1, dtype=float)
    return series.rolling(window=validated_window, min_periods=validated_window).apply(
        lambda x: np.dot(x, weights) / weights.sum(),
        raw=True,
    )


def ew_vwap(price: pd.Series, volume: pd.Series, length: int) -> pd.Series:
    validated_length = coerce_positive_int(length, "length")
    den = volume.ewm(alpha=1.0 / validated_length, adjust=False, min_periods=validated_length).mean()
    num = (price * volume).ewm(alpha=1.0 / validated_length, adjust=False, min_periods=validated_length).mean()
    out = num / den
    out[den == 0] = np.nan
    return out


def coerce_odd_int_at_least_three(value: Any, param_name: str) -> int:
    out = coerce_positive_int(value, param_name)
    if out < 3 or out % 2 == 0:
        raise ValueError(f"Parameter '{param_name}' must be an odd integer >= 3.")
    return out


def fractal_extrema_series(
    series: pd.Series,
    *,
    window: int,
    mode: str,
) -> pd.Series:
    """
    Return a sparse confirmed fractal extrema series.

    The returned series keeps the original price level only on the center
    bar of a confirmed fractal and is NaN everywhere else.

    Confirmation rule:
    - the center bar must be a strict extreme versus ``half_window`` bars on
      both the left and right side
    - missing future bars naturally suppress unconfirmed realtime points
    """
    validated_window = coerce_odd_int_at_least_three(window, "window")
    half_window = validated_window // 2
    values = series.astype(float)

    if mode not in {"peak", "trough"}:
        raise ValueError("mode must be either 'peak' or 'trough'.")

    mask = pd.Series(True, index=values.index, dtype=bool)
    for offset in range(1, half_window + 1):
        if mode == "peak":
            mask &= values.gt(values.shift(offset))
            mask &= values.gt(values.shift(-offset))
        else:
            mask &= values.lt(values.shift(offset))
            mask &= values.lt(values.shift(-offset))

    return values.where(mask, np.nan)


def build_peaks_troughs_line_key(kind: str, fractal_length: int) -> str:
    normalized_kind = str(kind).strip().lower()
    if normalized_kind not in {"peak", "trough"}:
        raise ValueError("kind must be either 'peak' or 'trough'.")
    return f"{normalized_kind}_fractal_{int(fractal_length)}"
