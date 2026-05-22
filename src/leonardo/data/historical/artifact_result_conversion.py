from __future__ import annotations

from typing import Any

import pandas as pd


def result_to_save_dataframe(
    result: Any,
    *,
    default_timeframe: Any | None = None,
) -> pd.DataFrame:
    """
    Convert a financial-tool runtime result into a full artifact dataframe.

    The conversion is shared by chart-save and save-only data workflows. It
    does not calculate tools, trim to chart resident slices, filter by
    renderability, or persist files. Persistence and sidecar metadata remain
    owned by ``DerivedCsvStore``.
    """
    if getattr(result, "lines", None):
        return _line_result_to_save_dataframe(result, default_timeframe=default_timeframe)

    metadata = dict(getattr(result, "metadata", {}) or {})
    labeled_rows = metadata.get("labeled_rows")
    if labeled_rows:
        result_df = pd.DataFrame(labeled_rows)
        if result_df.empty:
            raise ValueError("Construct labeled_rows is empty.")
        return result_df

    raise ValueError("Financial tool produced no saveable output rows.")


def _line_result_to_save_dataframe(
    result: Any,
    *,
    default_timeframe: Any | None,
) -> pd.DataFrame:
    df = pd.DataFrame(index=result.index)

    if getattr(result, "time", None) is not None:
        df["time"] = result.time
    if getattr(result, "timeframe", None) is not None:
        df["timeframe"] = result.timeframe

    for line in result.lines:
        series = line.values.reindex(result.index)
        df[line.key] = _coerce_save_series(series)

    if "time" not in df.columns:
        if "ts_ms" in df.columns:
            df["time"] = df["ts_ms"]
        else:
            df["time"] = list(range(len(df)))

    if "timeframe" not in df.columns and default_timeframe is not None:
        df["timeframe"] = default_timeframe

    return df.reset_index(drop=True)


def _coerce_save_series(series: pd.Series) -> pd.Series:
    if pd.api.types.is_bool_dtype(series):
        return series.astype("bool")
    if pd.api.types.is_numeric_dtype(series):
        return series.astype("float32")
    return series
