from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Mapping

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class IndicatorRequest:
    """
    Normalized request contract for indicator computation.

    Attributes:
        name: Indicator name, e.g. 'sma'
        data: Input dataframe
        params: Indicator parameters
    """
    name: str
    data: pd.DataFrame
    params: Mapping[str, Any]


@dataclass(frozen=True)
class IndicatorLine:
    """
    One plot-ready output line from an indicator.
    """
    key: str
    title: str
    values: pd.Series


@dataclass(frozen=True)
class IndicatorResult:
    """
    Normalized result contract for indicator computation.

    Attributes:
        name: Internal indicator name, e.g. 'sma'
        title: Human-readable title
        kind: Overlay classification
        lines: Output line(s)
        index: Output index, preserved from input
        time: Output time column
        timeframe: Output timeframe column
        params: Effective validated params
    """
    name: str
    title: str
    kind: str
    lines: List[IndicatorLine]
    index: pd.Index
    time: pd.Series | None
    timeframe: pd.Series | None
    params: Dict[str, Any]


class Indicators:
    """
    A class to calculate various financial indicators.

    Assumptions (validated elsewhere, plus local defensive checks here):
      - data_dict['dcd'] is a pandas.DataFrame with a monotonic increasing timestamp index (oldest at 0).
      - Required columns exist and are floats: 'open','high','low','close', and either 'Volume' or 'volume'.
      - Optional columns 'time' and/or 'timeframe' may be present and aligned with the index.

    Contract (this class enforces):
      - Output preserves the input index.
      - Output always includes 'time' and 'timeframe' columns for the legacy API.
      - Indicator columns use unbiased warm-ups internally where appropriate.
      - Numeric outputs are cast to float32 (except the categorical/string 'vwap_color').
      - Public legacy names and output column names are unchanged.

    Migration policy:
      - The normalized framework is now the internal computation path.
      - Legacy public APIs remain available as thin wrappers.
    """

    # ---------- helpers ----------
    @staticmethod
    def _get_time_cols(df: pd.DataFrame):
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

    @staticmethod
    def _require_dataframe(df: Any) -> pd.DataFrame:
        if not isinstance(df, pd.DataFrame):
            raise TypeError("Indicator input 'dcd' must be a pandas.DataFrame.")
        return df

    @staticmethod
    def _require_column(df: pd.DataFrame, column_name: str) -> pd.Series:
        if column_name not in df.columns:
            raise KeyError(f"Required column '{column_name}' is missing from indicator input.")
        return df[column_name]

    @staticmethod
    def _resolve_volume_column(df: pd.DataFrame) -> str:
        if "Volume" in df.columns:
            return "Volume"
        if "volume" in df.columns:
            return "volume"
        raise KeyError("Required volume column is missing from indicator input. Expected 'Volume' or 'volume'.")

    @staticmethod
    def _coerce_positive_int(value: Any, param_name: str) -> int:
        try:
            out = int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Parameter '{param_name}' must be an integer.") from exc

        if out <= 0:
            raise ValueError(f"Parameter '{param_name}' must be > 0.")
        return out

    @staticmethod
    def _coerce_positive_float(value: Any, param_name: str) -> float:
        try:
            out = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Parameter '{param_name}' must be a float.") from exc

        if out <= 0.0:
            raise ValueError(f"Parameter '{param_name}' must be > 0.")
        return out

    @staticmethod
    def _wma(series: pd.Series, window: int) -> pd.Series:
        window = max(1, int(window))
        weights = np.arange(1, window + 1, dtype=float)
        return series.rolling(window=window, min_periods=window).apply(
            lambda x: np.dot(x, weights) / weights.sum(),
            raw=True,
        )

    @classmethod
    def _registry(cls):
        return {
            "sma": cls._calculate_sma_result,
            "ema": cls._calculate_ema_result,
            "tema": cls._calculate_tema_result,
            "hma": cls._calculate_hma_result,
            "kama": cls._calculate_kama_result,
            "bb": cls._calculate_bb_result,
            "hck": cls._calculate_hck_result,
        }

    @classmethod
    def calculate(cls, request: IndicatorRequest) -> IndicatorResult:
        """
        Public normalized computation entry point.
        """
        if not isinstance(request, IndicatorRequest):
            raise TypeError("calculate() expects an IndicatorRequest instance.")

        name = str(request.name).strip().lower()
        registry = cls._registry()

        if name not in registry:
            raise NotImplementedError(
                f"Indicator '{request.name}' is not registered in the normalized framework."
            )

        df = cls._require_dataframe(request.data)
        return registry[name](df, dict(request.params))

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
            if pd.api.types.is_numeric_dtype(series):
                out[line.key] = series.astype("float32")
            else:
                out[line.key] = series

        return out

    # ---------- normalized SMA implementation ----------
    @classmethod
    def _calculate_sma_result(cls, dcd_df: pd.DataFrame, params: Dict[str, Any]) -> IndicatorResult:
        close = cls._require_column(dcd_df, "close").astype(float)
        period = cls._coerce_positive_int(params.get("period"), "period")

        sma = close.rolling(window=period, min_periods=period).mean()
        time_col, timeframe_col = cls._get_time_cols(dcd_df)

        line_key = f"SMA_{period}"
        line = IndicatorLine(
            key=line_key,
            title=line_key,
            values=pd.Series(sma, index=dcd_df.index).astype("float32"),
        )

        return IndicatorResult(
            name="sma",
            title=f"SMA({period})",
            kind="overlay",
            lines=[line],
            index=dcd_df.index,
            time=time_col,
            timeframe=timeframe_col,
            params={"period": period},
        )

    # ---------- normalized EMA implementation ----------
    @classmethod
    def _calculate_ema_result(cls, dcd_df: pd.DataFrame, params: Dict[str, Any]) -> IndicatorResult:
        close = cls._require_column(dcd_df, "close").astype(float)
        period = cls._coerce_positive_int(params.get("period"), "period")

        ema = close.ewm(span=period, adjust=False, min_periods=period).mean()
        time_col, timeframe_col = cls._get_time_cols(dcd_df)

        line_key = f"EMA_{period}"
        line = IndicatorLine(
            key=line_key,
            title=line_key,
            values=pd.Series(ema, index=dcd_df.index).astype("float32"),
        )

        return IndicatorResult(
            name="ema",
            title=f"EMA({period})",
            kind="overlay",
            lines=[line],
            index=dcd_df.index,
            time=time_col,
            timeframe=timeframe_col,
            params={"period": period},
        )

    # ---------- normalized TEMA implementation ----------
    @classmethod
    def _calculate_tema_result(cls, dcd_df: pd.DataFrame, params: Dict[str, Any]) -> IndicatorResult:
        close = cls._require_column(dcd_df, "close").astype(float)
        period = cls._coerce_positive_int(params.get("period"), "period")

        ema1 = close.ewm(span=period, adjust=False, min_periods=period).mean()
        ema2 = ema1.ewm(span=period, adjust=False, min_periods=1).mean()
        ema3 = ema2.ewm(span=period, adjust=False, min_periods=1).mean()
        tema = 3 * ema1 - 3 * ema2 + ema3

        tema[ema1.isna()] = np.nan

        time_col, timeframe_col = cls._get_time_cols(dcd_df)

        line_key = f"TEMA_{period}"
        line = IndicatorLine(
            key=line_key,
            title=line_key,
            values=pd.Series(tema, index=dcd_df.index).astype("float32"),
        )

        return IndicatorResult(
            name="tema",
            title=f"TEMA({period})",
            kind="overlay",
            lines=[line],
            index=dcd_df.index,
            time=time_col,
            timeframe=timeframe_col,
            params={"period": period},
        )

    # ---------- normalized HMA implementation ----------
    @classmethod
    def _calculate_hma_result(cls, dcd_df: pd.DataFrame, params: Dict[str, Any]) -> IndicatorResult:
        close = cls._require_column(dcd_df, "close").astype(float)
        period = cls._coerce_positive_int(params.get("period"), "period")

        n2 = max(1, int(period / 2))
        ns = max(1, int(np.sqrt(period)))

        wma_half = cls._wma(close, n2)
        wma_full = cls._wma(close, period)
        h = 2 * wma_half - wma_full
        hma = cls._wma(h, ns)

        time_col, timeframe_col = cls._get_time_cols(dcd_df)

        line_key = f"HMA_{period}"
        line = IndicatorLine(
            key=line_key,
            title=line_key,
            values=pd.Series(hma, index=dcd_df.index).astype("float32"),
        )

        return IndicatorResult(
            name="hma",
            title=f"HMA({period})",
            kind="overlay",
            lines=[line],
            index=dcd_df.index,
            time=time_col,
            timeframe=timeframe_col,
            params={"period": period},
        )

    # ---------- normalized KAMA implementation ----------
    @classmethod
    def _calculate_kama_result(cls, dcd_df: pd.DataFrame, params: Dict[str, Any]) -> IndicatorResult:
        close = cls._require_column(dcd_df, "close").astype(float)
        fast_period = cls._coerce_positive_int(params.get("fast_period"), "fast_period")
        slow_period = cls._coerce_positive_int(params.get("slow_period"), "slow_period")

        change = close.diff(periods=slow_period).abs()
        volatility = close.diff().abs().rolling(window=slow_period, min_periods=slow_period).sum()
        er = (change / (volatility + 1e-12)).clip(0.0, 1.0).fillna(0.0)

        fastest = 2.0 / (fast_period + 1.0)
        slowest = 2.0 / (slow_period + 1.0)
        sc = (er * (fastest - slowest) + slowest) ** 2

        sma_seed = close.rolling(slow_period, min_periods=slow_period).mean()
        kama = np.full(len(close), np.nan, dtype=float)
        start = slow_period - 1
        if start >= 0 and start < len(close) and not np.isnan(sma_seed.iloc[start]):
            kama[start] = float(sma_seed.iloc[start])
            for i in range(start + 1, len(close)):
                kama[i] = kama[i - 1] + sc.iloc[i] * (close.iloc[i] - kama[i - 1])

        time_col, timeframe_col = cls._get_time_cols(dcd_df)

        line_key = f"KAMA_{fast_period}_{slow_period}"
        line = IndicatorLine(
            key=line_key,
            title=line_key,
            values=pd.Series(kama, index=dcd_df.index).astype("float32"),
        )

        return IndicatorResult(
            name="kama",
            title=f"KAMA({fast_period},{slow_period})",
            kind="overlay",
            lines=[line],
            index=dcd_df.index,
            time=time_col,
            timeframe=timeframe_col,
            params={"fast_period": fast_period, "slow_period": slow_period},
        )

    # ---------- normalized Bollinger Bands implementation ----------
    @classmethod
    def _calculate_bb_result(cls, dcd_df: pd.DataFrame, params: Dict[str, Any]) -> IndicatorResult:
        close = cls._require_column(dcd_df, "close").astype(float)
        period = cls._coerce_positive_int(params.get("period"), "period")
        std_mult = cls._coerce_positive_float(params.get("std"), "std")

        mid = close.rolling(window=period, min_periods=period).mean()
        sd = close.rolling(window=period, min_periods=period).std(ddof=0)
        up = mid + std_mult * sd
        dn = mid - std_mult * sd

        time_col, timeframe_col = cls._get_time_cols(dcd_df)

        lines = [
            IndicatorLine("bb_middle", "bb_middle", pd.Series(mid, index=dcd_df.index).astype("float32")),
            IndicatorLine("bb_upper_band", "bb_upper_band", pd.Series(up, index=dcd_df.index).astype("float32")),
            IndicatorLine("bb_lower_band", "bb_lower_band", pd.Series(dn, index=dcd_df.index).astype("float32")),
        ]

        return IndicatorResult(
            name="bb",
            title=f"BB({period},{std_mult})",
            kind="overlay",
            lines=lines,
            index=dcd_df.index,
            time=time_col,
            timeframe=timeframe_col,
            params={"period": period, "std": std_mult},
        )

    # ---------- normalized Hancock implementation ----------
    @classmethod
    def _calculate_hck_result(cls, dcd_df: pd.DataFrame, params: Dict[str, Any]) -> IndicatorResult:
        high = cls._require_column(dcd_df, "high").astype(float)
        low = cls._require_column(dcd_df, "low").astype(float)
        close = cls._require_column(dcd_df, "close").astype(float)
        vol_col = cls._resolve_volume_column(dcd_df)
        vol = dcd_df[vol_col].astype(float)

        fast_l = cls._coerce_positive_int(params.get("fast_vwap_l"), "fast_vwap_l")
        slow_l = cls._coerce_positive_int(params.get("slow_vwap_l"), "slow_vwap_l")

        hlc3 = (high + low + close) / 3.0

        def ew_vwap(x_price: pd.Series, v: pd.Series, L: int) -> pd.Series:
            den = v.ewm(alpha=1.0 / L, adjust=False, min_periods=L).mean()
            num = (x_price * v).ewm(alpha=1.0 / L, adjust=False, min_periods=L).mean()
            out = num / den
            out[den == 0] = np.nan
            return out

        fast_vwap = ew_vwap(hlc3, vol, fast_l)
        slow_vwap = ew_vwap(hlc3, vol, slow_l)

        vwap_color = pd.Series(
            pd.Categorical(["silver"] * len(dcd_df), categories=["red", "silver", "green"]),
            index=dcd_df.index,
        )
        vwap_color = vwap_color.mask(fast_vwap > slow_vwap, "green")
        vwap_color = vwap_color.mask(fast_vwap < slow_vwap, "red")

        time_col, timeframe_col = cls._get_time_cols(dcd_df)

        lines = [
            IndicatorLine("fast_vwap", "fast_vwap", pd.Series(fast_vwap, index=dcd_df.index).astype("float32")),
            IndicatorLine("slow_vwap", "slow_vwap", pd.Series(slow_vwap, index=dcd_df.index).astype("float32")),
            IndicatorLine("vwap_color", "vwap_color", pd.Series(vwap_color, index=dcd_df.index)),
        ]

        return IndicatorResult(
            name="hck",
            title=f"HCK({fast_l},{slow_l})",
            kind="overlay",
            lines=lines,
            index=dcd_df.index,
            time=time_col,
            timeframe=timeframe_col,
            params={"fast_vwap_l": fast_l, "slow_vwap_l": slow_l},
        )

    # ---------- SMA ----------
    @staticmethod
    def sma(data_dict):
        """
        Simple Moving Average (SMA) with unbiased warm-up.

        Legacy public API preserved.
        """
        dcd_df = data_dict["dcd"]
        request = IndicatorRequest(
            name="sma",
            data=dcd_df,
            params={"period": data_dict["period"]},
        )
        result = Indicators.calculate(request)
        return Indicators._result_to_legacy_frame(result)

    # ---------- EMA ----------
    @staticmethod
    def ema(data_dict):
        """
        Exponential Moving Average (EMA).

        Legacy public API preserved.
        """
        dcd_df = data_dict["dcd"]
        request = IndicatorRequest(
            name="ema",
            data=dcd_df,
            params={"period": data_dict["period"]},
        )
        result = Indicators.calculate(request)
        return Indicators._result_to_legacy_frame(result)

    # ---------- TEMA ----------
    @staticmethod
    def tema(data_dict):
        """
        Triple Exponential Moving Average (TEMA).

        Legacy public API preserved.
        """
        dcd_df = data_dict["dcd"]
        request = IndicatorRequest(
            name="tema",
            data=dcd_df,
            params={"period": data_dict["period"]},
        )
        result = Indicators.calculate(request)
        return Indicators._result_to_legacy_frame(result)

    # ---------- HMA ----------
    @staticmethod
    def hma(data_dict):
        """
        Hull Moving Average (HMA).

        Legacy public API preserved.
        """
        dcd_df = data_dict["dcd"]
        request = IndicatorRequest(
            name="hma",
            data=dcd_df,
            params={"period": data_dict["period"]},
        )
        result = Indicators.calculate(request)
        return Indicators._result_to_legacy_frame(result)

    # ---------- KAMA ----------
    @staticmethod
    def kama(data_dict):
        """
        Kaufman's Adaptive Moving Average (KAMA).

        Legacy public API preserved.
        """
        dcd_df = data_dict["dcd"]
        request = IndicatorRequest(
            name="kama",
            data=dcd_df,
            params={
                "fast_period": data_dict["fast_period"],
                "slow_period": data_dict["slow_period"],
            },
        )
        result = Indicators.calculate(request)
        return Indicators._result_to_legacy_frame(result)

    # ---------- Bollinger Bands ----------
    @staticmethod
    def bb(data_dict):
        """
        Bollinger Bands on close.

        Legacy public API preserved.
        """
        dcd_df = data_dict["dcd"]
        request = IndicatorRequest(
            name="bb",
            data=dcd_df,
            params={
                "period": data_dict["period"],
                "std": data_dict["std"],
            },
        )
        result = Indicators.calculate(request)
        return Indicators._result_to_legacy_frame(result)

    # ---------- Hancock (EW-VWAPs) ----------
    @staticmethod
    def hck(data_dict):
        """
        Hancock fast/slow EW-VWAPs.

        Legacy public API preserved.
        """
        dcd_df = data_dict["dcd"]
        request = IndicatorRequest(
            name="hck",
            data=dcd_df,
            params={
                "fast_vwap_l": data_dict["fast_vwap_l"],
                "slow_vwap_l": data_dict["slow_vwap_l"],
            },
        )
        result = Indicators.calculate(request)
        return Indicators._result_to_legacy_frame(result)