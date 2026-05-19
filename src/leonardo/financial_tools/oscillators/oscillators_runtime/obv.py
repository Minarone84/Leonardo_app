from __future__ import annotations

from typing import Any, Dict

import numpy as np
import pandas as pd

from .common import get_time_cols, require_column, resolve_volume_column
from .contracts import OscillatorLine, OscillatorResult


def _build_obv_signal_name() -> str:
    return "obv"


def calculate_obv_result(dcd_df: pd.DataFrame, params: Dict[str, Any], context: Any = None) -> OscillatorResult:
    """
    Normalized OBV computation.
    """
    del params

    close = require_column(dcd_df, "close").astype(float)
    vol_col = resolve_volume_column(dcd_df)
    vol = dcd_df[vol_col].astype(float)

    up = close.diff() > 0
    down = close.diff() < 0
    step = np.where(up, vol, np.where(down, -vol, 0.0))
    obv_vector = pd.Series(step, index=dcd_df.index).cumsum()

    time_col, timeframe_col = get_time_cols(dcd_df)
    line_key = _build_obv_signal_name()

    line = OscillatorLine(
        key=line_key,
        title=line_key,
        values=pd.Series(obv_vector, index=dcd_df.index).astype("float32"),
    )

    return OscillatorResult(
        name="obv",
        title="OBV",
        kind="oscillator",
        lines=[line],
        index=dcd_df.index,
        time=time_col,
        timeframe=timeframe_col,
        params={},
    )
