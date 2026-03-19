from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Mapping

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class OscillatorRequest:
    """
    Normalized request contract for oscillator computation.

    Attributes:
        name: Oscillator name, e.g. 'rsi'
        data: Input dataframe
        params: Oscillator parameters
    """
    name: str
    data: pd.DataFrame
    params: Mapping[str, Any]


@dataclass(frozen=True)
class OscillatorLine:
    """
    One plot-ready output line from an oscillator.
    """
    key: str
    title: str
    values: pd.Series


@dataclass(frozen=True)
class OscillatorResult:
    """
    Normalized result contract for oscillator computation.

    Attributes:
        name: Internal oscillator name
        title: Human-readable title
        kind: Oscillator classification
        lines: Output line(s)
        index: Output index, preserved from input
        time: Output time column
        timeframe: Output timeframe column
        params: Effective validated params
    """
    name: str
    title: str
    kind: str
    lines: List[OscillatorLine]
    index: pd.Index
    time: pd.Series | None
    timeframe: pd.Series | None
    params: Dict[str, Any]


class Oscillators:
    """
    A class to calculate various financial oscillators.

    Project assumptions (validated elsewhere):
      - data_dict['dcd'] is a DataFrame with a monotonic increasing timestamp index (oldest at 0).
      - Required columns for each oscillator exist and are float-like.
      - Optional 'time'/'timeframe' may be present and aligned.

    Contract (enforced here):
      - Output preserves the input index exactly.
      - Column names and method names remain exactly as specified below.
      - Numeric outputs are cast to float32 (strings/categoricals left as-is).
      - Warm-ups are handled in a numerically unbiased way (first rows may be NaN),
        which is fine since you slice/drop NaNs downstream.

    Migration policy:
      - The normalized framework is now the internal computation path.
      - Legacy public APIs remain available as thin wrappers.
    """

    # ---------- helper: time/timeframe passthrough ----------
    @staticmethod
    def _get_time_cols(df: pd.DataFrame):
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

    @staticmethod
    def _require_dataframe(df: Any) -> pd.DataFrame:
        if not isinstance(df, pd.DataFrame):
            raise TypeError("Oscillator input 'dcd' must be a pandas.DataFrame.")
        return df

    @staticmethod
    def _require_column(df: pd.DataFrame, column_name: str) -> pd.Series:
        if column_name not in df.columns:
            raise KeyError(f"Required column '{column_name}' is missing from oscillator input.")
        return df[column_name]

    @staticmethod
    def _resolve_volume_column(df: pd.DataFrame) -> str:
        if "Volume" in df.columns:
            return "Volume"
        if "volume" in df.columns:
            return "volume"
        raise KeyError("Required volume column is missing from oscillator input. Expected 'Volume' or 'volume'.")

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
    def _coerce_bool(value: Any, param_name: str) -> bool:
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

    @staticmethod
    def _rma_wilder(x: pd.Series, n: int) -> pd.Series:
        """
        Strict Wilder RMA with SMA seed at index n-1; earlier = NaN.
        """
        x = x.astype(float)
        out = pd.Series(np.nan, index=x.index, dtype=float)
        if len(x) < n:
            return out
        seed = x.iloc[:n].mean()
        out.iloc[n - 1] = seed
        alpha = 1.0 / n
        for i in range(n, len(x)):
            out.iloc[i] = alpha * x.iloc[i] + (1 - alpha) * out.iloc[i - 1]
        return out

    @classmethod
    def _apply_smoother(cls, x: pd.Series, n: int, mode: str) -> pd.Series:
        mode = str(mode).upper()
        if mode == "EMA":
            return x.ewm(span=n, adjust=False, min_periods=n).mean()
        if mode == "RMA":
            return cls._rma_wilder(x, n)
        if mode == "SMA":
            return x.rolling(window=n, min_periods=n).mean()
        raise ValueError(f"Unsupported smoothing type: {mode}")

    @classmethod
    def _registry(cls):
        return {
            "rsi": cls._calculate_rsi_result,
            "arsi": cls._calculate_arsi_result,
            "tdirsi": cls._calculate_tdirsi_result,
            "smi": cls._calculate_smi_result,
            "mfi": cls._calculate_mfi_result,
            "obv": cls._calculate_obv_result,
        }

    @classmethod
    def calculate(cls, request: OscillatorRequest) -> OscillatorResult:
        """
        Public normalized computation entry point.
        """
        if not isinstance(request, OscillatorRequest):
            raise TypeError("calculate() expects an OscillatorRequest instance.")

        name = str(request.name).strip().lower()
        registry = cls._registry()

        if name not in registry:
            raise NotImplementedError(
                f"Oscillator '{request.name}' is not registered in the normalized framework."
            )

        df = cls._require_dataframe(request.data)
        return registry[name](df, dict(request.params))

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

    # ---------- normalized RSI implementation ----------
    @classmethod
    def _calculate_rsi_result(cls, dcd_df: pd.DataFrame, params: Dict[str, Any]) -> OscillatorResult:
        """
        Normalized Wilder RSI computation, strictly SMA-seeded.

        Preserves original financial meaning:
          - delta from close.diff()
          - gain/loss split
          - strict Wilder RMA
          - explicit edge handling
          - preserved index
        """
        close = cls._require_column(dcd_df, "close").astype(float)
        n = cls._coerce_positive_int(params.get("period"), "period")

        delta = close.diff()
        gain = delta.clip(lower=0.0)
        loss = (-delta).clip(lower=0.0)

        avg_gain = cls._rma_wilder(gain, n)
        avg_loss = cls._rma_wilder(loss, n)

        rs = avg_gain / avg_loss
        rsi = 100.0 - 100.0 / (1.0 + rs)

        zero_loss = avg_loss == 0
        zero_gain = avg_gain == 0
        both_zero = zero_loss & zero_gain
        rsi = rsi.mask(zero_loss, 100.0)
        rsi = rsi.mask(zero_gain, 0.0)
        rsi = rsi.mask(both_zero, 50.0)

        line_key = f"rsi_{n}"
        line = OscillatorLine(
            key=line_key,
            title=f"RSI({n})",
            values=pd.Series(rsi, index=dcd_df.index).astype("float32"),
        )

        return OscillatorResult(
            name="rsi",
            title=f"RSI({n})",
            kind="oscillator",
            lines=[line],
            index=dcd_df.index,
            time=None,
            timeframe=None,
            params={"period": n},
        )

    # ---------- normalized ARSI implementation ----------
    @classmethod
    def _calculate_arsi_result(cls, dcd_df: pd.DataFrame, params: Dict[str, Any]) -> OscillatorResult:
        """
        Normalized ARSI computation.

        Preserves original financial meaning:
          - single RMA smoother on signed and absolute deltas
          - optional breakout boost on fresh Donchian highs/lows
          - neutral fill/clamp behavior
          - preserved index
        """
        close = cls._require_column(dcd_df, "close").astype(float)
        n = cls._coerce_positive_int(params.get("period"), "period")
        boost = cls._coerce_bool(params.get("boost_breakouts", True), "boost_breakouts")

        delta = close.diff()

        if boost:
            highest = close.rolling(n, min_periods=n).max()
            lowest = close.rolling(n, min_periods=n).min()
            rng = highest - lowest

            new_high = (highest > highest.shift(1)).fillna(False)
            new_low = (lowest < lowest.shift(1)).fillna(False)

            diff_p = delta.copy()
            diff_p[new_high] = rng[new_high]
            diff_p[new_low] = -rng[new_low]
        else:
            diff_p = delta

        num = cls._rma_wilder(diff_p.fillna(0.0), n)
        den = cls._rma_wilder(diff_p.abs().fillna(0.0), n)

        ratio = num / den.replace(0.0, np.nan)
        arsi = 50.0 + 50.0 * ratio
        arsi = arsi.replace([np.inf, -np.inf], np.nan).fillna(50.0).clip(0.0, 100.0)

        line_key = f"arsi_{n}"
        line = OscillatorLine(
            key=line_key,
            title=f"ARSI({n})",
            values=pd.Series(arsi, index=dcd_df.index).astype("float32"),
        )

        return OscillatorResult(
            name="arsi",
            title=f"ARSI({n})",
            kind="oscillator",
            lines=[line],
            index=dcd_df.index,
            time=None,
            timeframe=None,
            params={"period": n, "boost_breakouts": boost},
        )

    # ---------- normalized TDI RSI implementation ----------
    @classmethod
    def _calculate_tdirsi_result(cls, dcd_df: pd.DataFrame, params: Dict[str, Any]) -> OscillatorResult:
        """
        Normalized TDI computation based on Wilder RSI.
        """
        cls._require_column(dcd_df, "close")

        period = cls._coerce_positive_int(params.get("period"), "period")
        band_length = cls._coerce_positive_int(params.get("band_length"), "band_length")
        band_mult = cls._coerce_positive_float(params.get("band_mult", 1.6185), "band_mult")

        fast_len = cls._coerce_positive_int(params.get("fast_len", 2), "fast_len")
        slow_len = cls._coerce_positive_int(params.get("slow_len", 7), "slow_len")
        fast_smo = str(params.get("fast_smo", "EMA")).upper()
        slow_smo = str(params.get("slow_smo", "RMA")).upper()

        rsi_result = cls._calculate_rsi_result(dcd_df, {"period": period})
        r = rsi_result.lines[0].values.astype(float)

        ma = r.rolling(window=band_length, min_periods=band_length).mean()
        std = r.rolling(window=band_length, min_periods=band_length).std(ddof=0)
        offs = band_mult * std
        up = ma + offs
        dn = ma - offs
        mid = (up + dn) / 2.0

        fast_ma = cls._apply_smoother(r, fast_len, fast_smo)
        slow_ma = cls._apply_smoother(r, slow_len, slow_smo)

        time_col, timeframe_col = cls._get_time_cols(dcd_df)

        lines = [
            OscillatorLine("fast_ma", "fast_ma", pd.Series(fast_ma, index=dcd_df.index).astype("float32")),
            OscillatorLine("slow_ma", "slow_ma", pd.Series(slow_ma, index=dcd_df.index).astype("float32")),
            OscillatorLine("up", "up", pd.Series(up, index=dcd_df.index).astype("float32")),
            OscillatorLine("dn", "dn", pd.Series(dn, index=dcd_df.index).astype("float32")),
            OscillatorLine("mid", "mid", pd.Series(mid, index=dcd_df.index).astype("float32")),
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

    # ---------- normalized SMI implementation ----------
    @classmethod
    def _calculate_smi_result(cls, dcd_df: pd.DataFrame, params: Dict[str, Any]) -> OscillatorResult:
        """
        Normalized SMI computation, double-smoothed.
        """
        high = cls._require_column(dcd_df, "high").astype(float)
        low = cls._require_column(dcd_df, "low").astype(float)
        close = cls._require_column(dcd_df, "close").astype(float)

        k_length = cls._coerce_positive_int(params.get("k_length"), "k_length")
        d_length = cls._coerce_positive_int(params.get("d_length"), "d_length")

        ll = low.rolling(window=k_length, min_periods=k_length).min()
        hh = high.rolling(window=k_length, min_periods=k_length).max()

        diff = hh - ll
        rdiff = close - (hh + ll) / 2.0

        avgrel = (
            rdiff.ewm(span=d_length, adjust=False, min_periods=d_length).mean()
            .ewm(span=d_length, adjust=False, min_periods=d_length).mean()
        )
        avgdiff = (
            diff.ewm(span=d_length, adjust=False, min_periods=d_length).mean()
            .ewm(span=d_length, adjust=False, min_periods=d_length).mean()
        )

        smi_val = (avgrel / (avgdiff / 2.0)) * 100.0
        smi_val = smi_val.where(avgdiff != 0, 0.0)

        smi_sig = smi_val.ewm(span=d_length, adjust=False, min_periods=d_length).mean()

        time_col, timeframe_col = cls._get_time_cols(dcd_df)

        lines = [
            OscillatorLine("SMI", "SMI", pd.Series(smi_val, index=dcd_df.index).astype("float32")),
            OscillatorLine("SMIsignal", "SMIsignal", pd.Series(smi_sig, index=dcd_df.index).astype("float32")),
        ]

        return OscillatorResult(
            name="smi",
            title=f"SMI({k_length},{d_length})",
            kind="oscillator",
            lines=lines,
            index=dcd_df.index,
            time=time_col,
            timeframe=timeframe_col,
            params={"k_length": k_length, "d_length": d_length},
        )

    # ---------- normalized MFI implementation ----------
    @classmethod
    def _calculate_mfi_result(cls, dcd_df: pd.DataFrame, params: Dict[str, Any]) -> OscillatorResult:
        """
        Normalized canonical MFI computation.
        """
        high = cls._require_column(dcd_df, "high").astype(float)
        low = cls._require_column(dcd_df, "low").astype(float)
        close = cls._require_column(dcd_df, "close").astype(float)
        vol_col = cls._resolve_volume_column(dcd_df)
        volume = dcd_df[vol_col].astype(float)

        period = cls._coerce_positive_int(params.get("period"), "period")

        tp = (high + low + close) / 3.0
        dtp = tp.diff()

        pos_flow = (tp * volume).where(dtp > 0, 0.0)
        neg_flow = (tp * volume).where(dtp < 0, 0.0)

        pos_sum = pos_flow.rolling(window=period, min_periods=period).sum()
        neg_sum = neg_flow.rolling(window=period, min_periods=period).sum()

        mfr = pos_sum / neg_sum.replace(0.0, np.nan)
        mfi = 100.0 - 100.0 / (1.0 + mfr)
        mfi = mfi.fillna(50.0)

        time_col, timeframe_col = cls._get_time_cols(dcd_df)

        line = OscillatorLine(
            key="mfi",
            title="mfi",
            values=pd.Series(mfi, index=dcd_df.index).astype("float32"),
        )

        return OscillatorResult(
            name="mfi",
            title=f"MFI({period})",
            kind="oscillator",
            lines=[line],
            index=dcd_df.index,
            time=time_col,
            timeframe=timeframe_col,
            params={"period": period},
        )

    # ---------- normalized OBV implementation ----------
    @classmethod
    def _calculate_obv_result(cls, dcd_df: pd.DataFrame, params: Dict[str, Any]) -> OscillatorResult:
        """
        Normalized OBV computation.
        """
        close = cls._require_column(dcd_df, "close").astype(float)
        vol_col = cls._resolve_volume_column(dcd_df)
        vol = dcd_df[vol_col].astype(float)

        up = close.diff() > 0
        down = close.diff() < 0
        step = np.where(up, vol, np.where(down, -vol, 0.0))
        obv_vector = pd.Series(step, index=dcd_df.index).cumsum()

        time_col, timeframe_col = cls._get_time_cols(dcd_df)

        line = OscillatorLine(
            key="obv",
            title="obv",
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

    # ---------- Wilder RSI ----------
    @staticmethod
    def rsi(data_dict):
        """
        Compute **Wilder's RSI** (Relative Strength Index), strictly SMA-seeded.

        Returns a single column named f"rsi_{period}", indexed exactly like dcd.
        Legacy API preserved.
        """
        dcd_df = data_dict["dcd"]
        request = OscillatorRequest(
            name="rsi",
            data=dcd_df,
            params={"period": data_dict["period"]},
        )
        result = Oscillators.calculate(request)
        return Oscillators._result_to_legacy_frame(result)

    # ---------- Augmented RSI (ARSI) ----------
    @staticmethod
    def arsi(data_dict):
        """
        Compute **ARSI (Augmented RSI)** using a single RMA smoother on signed
        and absolute deltas, with optional **breakout boost** on fresh Donchian
        highs/lows over `period`.

        Legacy API preserved.
        """
        dcd_df = data_dict["dcd"]
        request = OscillatorRequest(
            name="arsi",
            data=dcd_df,
            params={
                "period": data_dict["period"],
                "boost_breakouts": data_dict.get("boost_breakouts", True),
            },
        )
        result = Oscillators.calculate(request)
        return Oscillators._result_to_legacy_frame(result)

    # ---------- TDI (RSI-based) ----------
    @staticmethod
    def tdirsi(data_dict):
        """
        Traders Dynamic Index (TDI) built on top of **Wilder RSI**.

        Legacy API preserved.
        """
        dcd_df = data_dict["dcd"]
        request = OscillatorRequest(
            name="tdirsi",
            data=dcd_df,
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
        result = Oscillators.calculate(request)
        return Oscillators._result_to_legacy_frame(result)

    # ---------- SMI ----------
    @staticmethod
    def smi(data_dict):
        """
        Stochastic Momentum Index (SMI), double-smoothed.

        Legacy API preserved.
        """
        dcd_df = data_dict["dcd"]
        request = OscillatorRequest(
            name="smi",
            data=dcd_df,
            params={
                "k_length": data_dict["k_length"],
                "d_length": data_dict["d_length"],
            },
        )
        result = Oscillators.calculate(request)
        return Oscillators._result_to_legacy_frame(result)

    # ---------- MFI (canonical) ----------
    @staticmethod
    def mfi(data_dict):
        """
        Money Flow Index (MFI), canonical definition.

        Legacy API preserved.
        """
        dcd_df = data_dict["dcd"]
        request = OscillatorRequest(
            name="mfi",
            data=dcd_df,
            params={"period": data_dict["period"]},
        )
        result = Oscillators.calculate(request)
        return Oscillators._result_to_legacy_frame(result)

    # ---------- OBV ----------
    @staticmethod
    def obv(data_dict):
        """
        On-Balance Volume (OBV).

        Legacy API preserved.
        """
        dcd_df = data_dict["dcd"]
        request = OscillatorRequest(
            name="obv",
            data=dcd_df,
            params={},
        )
        result = Oscillators.calculate(request)
        return Oscillators._result_to_legacy_frame(result)