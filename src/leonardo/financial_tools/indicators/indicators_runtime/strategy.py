from __future__ import annotations

from typing import Any, Dict, List

import pandas as pd

from leonardo.financial_tools.ft_naming import (
    STRATEGY_EMA_SLOT_COUNT,
    STRATEGY_SMA_SLOT_COUNT,
    build_strategy_bb_signal_names,
    build_strategy_ema_signal_name,
    build_strategy_hck_signal_names,
    build_strategy_sma_signal_name,
)

from .bb import calculate_bb_result
from .common import coerce_positive_float, coerce_positive_int, get_time_cols
from .contracts import IndicatorLine, IndicatorResult
from .ema import calculate_ema_result
from .hck import calculate_hck_result
from .sma import calculate_sma_result


def calculate_strategy_result(dcd_df: pd.DataFrame, params: Dict[str, Any], context: Any = None) -> IndicatorResult:
    """
    Composite strategy overlay.

    The strategy module intentionally composes the indicator runtime modules
    instead of duplicating their math. This keeps warm-up rules, output values,
    and future audits aligned with the standalone family implementations.
    """
    ema_periods: list[int] = []
    sma_periods: list[int] = []
    effective_params: Dict[str, Any] = {}

    for slot in range(1, STRATEGY_EMA_SLOT_COUNT + 1):
        param_name = f"ema_{slot}_period"
        period = coerce_positive_int(params.get(param_name), param_name)
        ema_periods.append(period)
        effective_params[param_name] = period

    for slot in range(1, STRATEGY_SMA_SLOT_COUNT + 1):
        param_name = f"sma_{slot}_period"
        period = coerce_positive_int(params.get(param_name), param_name)
        sma_periods.append(period)
        effective_params[param_name] = period

    bb_period = coerce_positive_int(params.get("bb_period"), "bb_period")
    bb_std = coerce_positive_float(params.get("bb_std"), "bb_std")
    hck_fast_l = coerce_positive_int(params.get("hck_fast_vwap_l"), "hck_fast_vwap_l")
    hck_slow_l = coerce_positive_int(params.get("hck_slow_vwap_l"), "hck_slow_vwap_l")

    effective_params.update(
        {
            "bb_period": bb_period,
            "bb_std": bb_std,
            "hck_fast_vwap_l": hck_fast_l,
            "hck_slow_vwap_l": hck_slow_l,
        }
    )

    time_col, timeframe_col = get_time_cols(dcd_df)
    lines: List[IndicatorLine] = []

    for slot, period in enumerate(ema_periods, start=1):
        signal_name = build_strategy_ema_signal_name(slot)
        ema_result = calculate_ema_result(dcd_df, {"period": period})
        lines.append(
            IndicatorLine(
                key=signal_name,
                title=signal_name,
                values=ema_result.lines[0].values,
            )
        )

    for slot, period in enumerate(sma_periods, start=1):
        signal_name = build_strategy_sma_signal_name(slot)
        sma_result = calculate_sma_result(dcd_df, {"period": period})
        lines.append(
            IndicatorLine(
                key=signal_name,
                title=signal_name,
                values=sma_result.lines[0].values,
            )
        )

    bb_result = calculate_bb_result(dcd_df, {"period": bb_period, "std": bb_std})
    st_bb_middle, st_bb_upper_band, st_bb_lower_band = build_strategy_bb_signal_names()
    bb_signal_names = (st_bb_middle, st_bb_upper_band, st_bb_lower_band)
    for line, signal_name in zip(bb_result.lines, bb_signal_names):
        lines.append(
            IndicatorLine(
                key=signal_name,
                title=signal_name,
                values=line.values,
            )
        )

    hck_result = calculate_hck_result(
        dcd_df,
        {"fast_vwap_l": hck_fast_l, "slow_vwap_l": hck_slow_l},
    )
    st_fast_vwap, st_slow_vwap, st_vwap_color = build_strategy_hck_signal_names()
    hck_signal_names = (st_fast_vwap, st_slow_vwap, st_vwap_color)
    for line, signal_name in zip(hck_result.lines, hck_signal_names):
        lines.append(
            IndicatorLine(
                key=signal_name,
                title=signal_name,
                values=line.values,
            )
        )

    return IndicatorResult(
        name="strategy",
        title="Strategy",
        kind="overlay",
        lines=lines,
        index=dcd_df.index,
        time=time_col,
        timeframe=timeframe_col,
        params=effective_params,
    )
