from __future__ import annotations

from typing import Any, Dict, List

import pandas as pd

from .common import build_peaks_troughs_line_key, fractal_extrema_series, get_time_cols, require_column
from .contracts import IndicatorLine, IndicatorResult


def calculate_peaks_troughs_result(
    dcd_df: pd.DataFrame,
    params: Dict[str, Any],
    context: Any = None,
) -> IndicatorResult:
    """
    Compute confirmed peak/trough events from strict symmetric fractals.

    Design notes:
    - peaks are confirmed from ``high``
    - troughs are confirmed from ``low``
    - only confirmed fractals are emitted, so the latest bars remain empty
      until enough right-side bars exist
    - outputs are sparse numeric event series: the event price on the center
      bar, NaN elsewhere
    """
    del params  # Fixed-runtime family in this phase: 3/5/7/9/11-bar fractals.

    high = require_column(dcd_df, "high").astype(float)
    low = require_column(dcd_df, "low").astype(float)
    time_col, timeframe_col = get_time_cols(dcd_df)

    fractal_lengths = (3, 5, 7, 9, 11)
    lines: List[IndicatorLine] = []

    for fractal_length in fractal_lengths:
        peak_key = build_peaks_troughs_line_key("peak", fractal_length)
        trough_key = build_peaks_troughs_line_key("trough", fractal_length)

        peak_values = fractal_extrema_series(
            high,
            window=fractal_length,
            mode="peak",
        )
        trough_values = fractal_extrema_series(
            low,
            window=fractal_length,
            mode="trough",
        )

        lines.append(
            IndicatorLine(
                key=peak_key,
                title=peak_key,
                values=pd.Series(peak_values, index=dcd_df.index).astype("float32"),
            )
        )
        lines.append(
            IndicatorLine(
                key=trough_key,
                title=trough_key,
                values=pd.Series(trough_values, index=dcd_df.index).astype("float32"),
            )
        )

    return IndicatorResult(
        name="peaks_troughs",
        title="Peaks & Troughs",
        kind="overlay",
        lines=lines,
        index=dcd_df.index,
        time=time_col,
        timeframe=timeframe_col,
        params={},
    )
