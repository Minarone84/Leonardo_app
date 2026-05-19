from __future__ import annotations

from dataclasses import replace
from typing import Callable, Dict

import pandas as pd

from leonardo.financial_tools.execution_context import (
    ToolExecutionContext,
    ensure_environment_supported,
)
from leonardo.financial_tools.tool_contracts.registry import get_contract

from .oscillators_runtime.common import require_dataframe
from .oscillators_runtime.contracts import (
    OscillatorLine,
    OscillatorRequest,
    OscillatorResult,
)
from .oscillators_runtime.arsi import calculate_arsi_result
from .oscillators_runtime.mfi import calculate_mfi_result
from .oscillators_runtime.obv import calculate_obv_result
from .oscillators_runtime.rsi import calculate_rsi_result
from .oscillators_runtime.smi import calculate_smi_result
from .oscillators_runtime.tdirsi import calculate_tdirsi_result
from .oscillators_runtime.volume import calculate_volume_result


OscillatorCalculator = Callable[[pd.DataFrame, Dict[str, object], ToolExecutionContext], OscillatorResult]


class Oscillators:
    """
    Bridge/facade for the oscillator family.

    Responsibilities kept here:
      - public legacy API surface
      - normalized request dispatch
      - explicit registry ownership
      - legacy dataframe adaptation

    Responsibilities moved into ``oscillators_runtime``:
      - oscillator-specific computation
      - shared validation/math helpers
      - per-oscillator runtime behavior
    """

    @classmethod
    def _registry(cls) -> Dict[str, OscillatorCalculator]:
        return {
            "rsi": calculate_rsi_result,
            "arsi": calculate_arsi_result,
            "tdirsi": calculate_tdirsi_result,
            "smi": calculate_smi_result,
            "mfi": calculate_mfi_result,
            "obv": calculate_obv_result,
            "volume": calculate_volume_result,
        }

    @classmethod
    def calculate(cls, request: OscillatorRequest) -> OscillatorResult:
        """
        Public normalized computation entry point.
        """
        if not isinstance(request, OscillatorRequest):
            raise TypeError("calculate() expects an OscillatorRequest instance.")

        raw_name = str(request.name).strip().lower()
        try:
            contract = get_contract(raw_name)
        except KeyError as exc:
            raise NotImplementedError(
                f"Oscillator '{request.name}' is not registered in the normalized framework."
            ) from exc
        if contract.family != "oscillator":
            raise ValueError(f"Financial tool {request.name!r} is not an oscillator.")

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
                f"Oscillator '{request.name}' is not registered in the normalized framework."
            )

        df = require_dataframe(request.data)
        result = registry[name](df, dict(request.params), context)
        return replace(
            result,
            metadata={**dict(result.metadata or {}), "environment": context.environment},
        )

    @staticmethod
    def _result_to_legacy_frame(result: OscillatorResult) -> pd.DataFrame:
        """
        Convert a normalized OscillatorResult back into the legacy dataframe contract.

        This preserves the existing public API while allowing normalized internal computation.
        """
        out = pd.DataFrame(index=result.index)

        if result.time is not None:
            out["time"] = result.time
        if result.timeframe is not None:
            out["timeframe"] = result.timeframe

        for line in result.lines:
            series = line.values.reindex(result.index)
            if pd.api.types.is_numeric_dtype(series):
                out[line.key] = series.astype("float32")
            else:
                out[line.key] = series

        return out

    @staticmethod
    def _legacy_compute(*, name: str, dcd_df: pd.DataFrame, params: Dict[str, object]) -> pd.DataFrame:
        request = OscillatorRequest(
            name=name,
            data=dcd_df,
            params=params,
        )
        result = Oscillators.calculate(request)
        return Oscillators._result_to_legacy_frame(result)

    # ---------- Wilder RSI ----------
    @staticmethod
    def rsi(data_dict):
        """
        Compute **Wilder's RSI** (Relative Strength Index), strictly SMA-seeded.

        Returns a single column named f"rsi_{period}", indexed exactly like dcd.
        Legacy API preserved.
        """
        return Oscillators._legacy_compute(
            name="rsi",
            dcd_df=data_dict["dcd"],
            params={"period": data_dict["period"]},
        )

    # ---------- Augmented RSI (ARSI) ----------
    @staticmethod
    def arsi(data_dict):
        """
        Compute **ARSI (Augmented RSI)** using a single RMA smoother on signed
        and absolute deltas, with optional **breakout boost** on fresh Donchian
        highs/lows over `period`.

        Legacy API preserved.
        """
        return Oscillators._legacy_compute(
            name="arsi",
            dcd_df=data_dict["dcd"],
            params={
                "period": data_dict["period"],
                "boost_breakouts": data_dict.get("boost_breakouts", True),
            },
        )

    # ---------- TDI (RSI-based) ----------
    @staticmethod
    def tdirsi(data_dict):
        """
        Traders Dynamic Index (TDI) built on top of **Wilder RSI**.

        Legacy API preserved.
        """
        return Oscillators._legacy_compute(
            name="tdirsi",
            dcd_df=data_dict["dcd"],
            params={
                "period": data_dict["period"],
                "band_length": data_dict["band_length"],
                "band_mult": data_dict.get("band_mult", 1.6185),
                "fast_len": data_dict.get("fast_len", 2),
                "slow_len": data_dict.get("slow_len", 7),
                "fast_smo": data_dict.get("fast_smo", "EMA"),
                "slow_smo": data_dict.get("slow_smo", "RMA"),
            },
        )

    # ---------- SMI ----------
    @staticmethod
    def smi(data_dict):
        """
        Stochastic Momentum Index (SMI), double-smoothed.

        Legacy API preserved.
        """
        return Oscillators._legacy_compute(
            name="smi",
            dcd_df=data_dict["dcd"],
            params={
                "k_length": data_dict["k_length"],
                "d_length": data_dict["d_length"],
            },
        )

    # ---------- MFI (canonical) ----------
    @staticmethod
    def mfi(data_dict):
        """
        Money Flow Index (MFI), canonical definition.

        Legacy API preserved.
        """
        return Oscillators._legacy_compute(
            name="mfi",
            dcd_df=data_dict["dcd"],
            params={"period": data_dict["period"]},
        )

    # ---------- OBV ----------
    @staticmethod
    def obv(data_dict):
        """
        On-Balance Volume (OBV).

        Legacy API preserved.
        """
        return Oscillators._legacy_compute(
            name="obv",
            dcd_df=data_dict["dcd"],
            params={},
        )

    # ---------- Volume ----------
    @staticmethod
    def volume(data_dict):
        """
        Raw Volume with configurable rolling mean.

        Legacy API preserved.
        """
        return Oscillators._legacy_compute(
            name="volume",
            dcd_df=data_dict["dcd"],
            params={"period": data_dict.get("period", 20)},
        )
