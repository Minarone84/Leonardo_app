from __future__ import annotations

from dataclasses import replace
from typing import Any, Callable, Dict

import pandas as pd

from leonardo.financial_tools.execution_context import (
    ToolExecutionContext,
    ensure_environment_supported,
)
from leonardo.financial_tools.tool_contracts.registry import get_contract
from leonardo.financial_tools.ft_naming import (
    STRATEGY_EMA_SLOT_COUNT,
    STRATEGY_SMA_SLOT_COUNT,
)
from .indicators_runtime.common import require_dataframe
from .indicators_runtime.contracts import (
    IndicatorLine,
    IndicatorRequest,
    IndicatorResult,
)
from .indicators_runtime.bb import calculate_bb_result
from .indicators_runtime.ema import calculate_ema_result
from .indicators_runtime.hck import calculate_hck_result
from .indicators_runtime.hma import calculate_hma_result
from .indicators_runtime.kama import calculate_kama_result
from .indicators_runtime.peaks_troughs import (
    calculate_peaks_troughs_result,
)
from .indicators_runtime.sma import calculate_sma_result
from .indicators_runtime.strategy import calculate_strategy_result
from .indicators_runtime.tema import calculate_tema_result
from .indicators_runtime.universal_trend_classifier import (
    calculate_universal_trend_classifier_result,
)


IndicatorCalculator = Callable[[pd.DataFrame, Dict[str, Any], ToolExecutionContext], IndicatorResult]


class Indicators:
    """
    Bridge/facade for the indicator family.

    Responsibilities kept here:
      - public legacy API surface
      - normalized request dispatch
      - explicit registry ownership
      - legacy dataframe adaptation

    Responsibilities moved into ``indicators_runtime``:
      - indicator-specific computation
      - shared validation/math helpers
      - per-indicator runtime behavior
    """

    @classmethod
    def _registry(cls) -> Dict[str, IndicatorCalculator]:
        return {
            "sma": calculate_sma_result,
            "ema": calculate_ema_result,
            "tema": calculate_tema_result,
            "hma": calculate_hma_result,
            "kama": calculate_kama_result,
            "bb": calculate_bb_result,
            "hck": calculate_hck_result,
            "strategy": calculate_strategy_result,
            "peaks_troughs": calculate_peaks_troughs_result,
            "universal_trend_classifier": calculate_universal_trend_classifier_result,
        }

    @classmethod
    def calculate(cls, request: IndicatorRequest) -> IndicatorResult:
        """
        Public normalized computation entry point.
        """
        if not isinstance(request, IndicatorRequest):
            raise TypeError("calculate() expects an IndicatorRequest instance.")

        raw_name = str(request.name).strip().lower()
        try:
            contract = get_contract(raw_name)
        except KeyError as exc:
            raise NotImplementedError(
                f"Indicator '{request.name}' is not registered in the normalized framework."
            ) from exc
        if contract.family != "indicator":
            raise ValueError(f"Financial tool {request.name!r} is not an indicator.")

        context = request.context if request.context is not None else ToolExecutionContext()
        ensure_environment_supported(
            tool_key=contract.key,
            environment=context.environment,
            supported_environments=contract.behavior.supported_environments,
        )

        name = contract.key
        registry = cls._registry()

        if name not in registry:
            raise NotImplementedError(
                f"Indicator '{request.name}' is not registered in the normalized framework."
            )

        df = require_dataframe(request.data)
        result = registry[name](df, dict(request.params), context)
        return replace(
            result,
            metadata={**dict(result.metadata or {}), "environment": context.environment},
        )

    @staticmethod
    def _result_to_legacy_frame(result: IndicatorResult) -> pd.DataFrame:
        """
        Convert a normalized IndicatorResult back into the legacy dataframe contract.

        This preserves the existing public API while allowing normalized internal computation.
        """
        out = pd.DataFrame(index=result.index)

        if result.time is not None:
            out["time"] = result.time
        if result.timeframe is not None:
            out["timeframe"] = result.timeframe

        for line in result.lines:
            series = line.values.reindex(result.index)
            if pd.api.types.is_bool_dtype(series):
                out[line.key] = series.astype("bool")
            elif pd.api.types.is_numeric_dtype(series):
                out[line.key] = series.astype("float32")
            else:
                out[line.key] = series

        return out

    @staticmethod
    def _legacy_compute(*, name: str, dcd_df: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
        request = IndicatorRequest(
            name=name,
            data=dcd_df,
            params=params,
        )
        result = Indicators.calculate(request)
        return Indicators._result_to_legacy_frame(result)

    # ---------- SMA ----------
    @staticmethod
    def sma(data_dict):
        """
        Simple Moving Average (SMA) with unbiased warm-up.

        Legacy public API preserved.
        """
        return Indicators._legacy_compute(
            name="sma",
            dcd_df=data_dict["dcd"],
            params={"period": data_dict["period"]},
        )

    # ---------- EMA ----------
    @staticmethod
    def ema(data_dict):
        """
        Exponential Moving Average (EMA).

        Legacy public API preserved.
        """
        return Indicators._legacy_compute(
            name="ema",
            dcd_df=data_dict["dcd"],
            params={"period": data_dict["period"]},
        )

    # ---------- TEMA ----------
    @staticmethod
    def tema(data_dict):
        """
        Triple Exponential Moving Average (TEMA).

        Legacy public API preserved.
        """
        return Indicators._legacy_compute(
            name="tema",
            dcd_df=data_dict["dcd"],
            params={"period": data_dict["period"]},
        )

    # ---------- HMA ----------
    @staticmethod
    def hma(data_dict):
        """
        Hull Moving Average (HMA).

        Legacy public API preserved.
        """
        return Indicators._legacy_compute(
            name="hma",
            dcd_df=data_dict["dcd"],
            params={"period": data_dict["period"]},
        )

    # ---------- KAMA ----------
    @staticmethod
    def kama(data_dict):
        """
        Kaufman's Adaptive Moving Average (KAMA).

        Legacy public API preserved.
        """
        return Indicators._legacy_compute(
            name="kama",
            dcd_df=data_dict["dcd"],
            params={
                "fast_period": data_dict["fast_period"],
                "slow_period": data_dict["slow_period"],
            },
        )

    # ---------- Bollinger Bands ----------
    @staticmethod
    def bb(data_dict):
        """
        Bollinger Bands on close.

        Legacy public API preserved.
        """
        return Indicators._legacy_compute(
            name="bb",
            dcd_df=data_dict["dcd"],
            params={
                "period": data_dict["period"],
                "std": data_dict["std"],
            },
        )

    # ---------- Hancock (EW-VWAPs) ----------
    @staticmethod
    def hck(data_dict):
        """
        Hancock fast/slow EW-VWAPs.

        Legacy public API preserved.
        """
        return Indicators._legacy_compute(
            name="hck",
            dcd_df=data_dict["dcd"],
            params={
                "fast_vwap_l": data_dict["fast_vwap_l"],
                "slow_vwap_l": data_dict["slow_vwap_l"],
            },
        )

    # ---------- Peaks & Troughs ----------
    @staticmethod
    def peaks_troughs(data_dict):
        """
        Confirmed strict symmetric fractal peak/trough events.

        Legacy public API preserved.
        """
        return Indicators._legacy_compute(
            name="peaks_troughs",
            dcd_df=data_dict["dcd"],
            params={},
        )

    # ---------- Universal Trend Classifier ----------
    @staticmethod
    def universal_trend_classifier(data_dict):
        """
        Universal Trend Classifier overlay and event/state outputs.

        Legacy public API preserved.
        """
        params: Dict[str, Any] = {
            "source": data_dict.get("source", data_dict.get("col", "close")),
            "fractal_window": data_dict.get("fractal_window", 5),
            "min_hr_band_perc": data_dict.get("min_hr_band_perc", 0.005),
            "hr_trend_length": data_dict.get("hr_trend_length", 20),
            "hr_trend_atr_mult": data_dict.get("hr_trend_atr_mult", 1.0),
            "hr_trend_atr_len": data_dict.get("hr_trend_atr_len", 500),
            "hr_trend_tol_mult": data_dict.get("hr_trend_tol_mult", 0.3),
            "hr_trend_max_gap": data_dict.get("hr_trend_max_gap", 20),
            "hr_min_inside_ratio": data_dict.get("hr_min_inside_ratio", 0.8),
            "min_range_swings": data_dict.get("min_range_swings", 4),
        }
        if "peak_column" in data_dict:
            params["peak_column"] = data_dict.get("peak_column")
        if "trough_column" in data_dict:
            params["trough_column"] = data_dict.get("trough_column")
        return Indicators._legacy_compute(
            name="universal_trend_classifier",
            dcd_df=data_dict["dcd"],
            params=params,
        )

    # ---------- Strategy composite overlay ----------
    @staticmethod
    def strategy(data_dict):
        """
        Composite Strategy overlay containing six EMAs, six SMAs, Bollinger Bands,
        and a Hancock fast/slow EW-VWAP pair.

        Legacy public API preserved.
        """
        params: Dict[str, Any] = {}

        for slot in range(1, STRATEGY_EMA_SLOT_COUNT + 1):
            params[f"ema_{slot}_period"] = data_dict[f"ema_{slot}_period"]

        for slot in range(1, STRATEGY_SMA_SLOT_COUNT + 1):
            params[f"sma_{slot}_period"] = data_dict[f"sma_{slot}_period"]

        params["bb_period"] = data_dict["bb_period"]
        params["bb_std"] = data_dict["bb_std"]
        params["hck_fast_vwap_l"] = data_dict["hck_fast_vwap_l"]
        params["hck_slow_vwap_l"] = data_dict["hck_slow_vwap_l"]

        return Indicators._legacy_compute(
            name="strategy",
            dcd_df=data_dict["dcd"],
            params=params,
        )


__all__ = [
    "IndicatorLine",
    "IndicatorRequest",
    "IndicatorResult",
    "Indicators",
]
