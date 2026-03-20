from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, Mapping

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class ConstructRequest:
    name: str
    data: pd.DataFrame
    params: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ConstructLine:
    key: str
    title: str
    values: pd.Series


@dataclass(frozen=True)
class ConstructResult:
    name: str
    title: str
    index: pd.Index
    time: pd.Series
    timeframe: pd.Series
    params: Dict[str, Any]
    lines: tuple[ConstructLine, ...] = ()
    metadata: Dict[str, Any] = field(default_factory=dict)


class Constructs:
    """
    Leonardo construct family.

    Constructs are analysis-oriented tools that are intentionally distinct from:
    - indicators
    - oscillators

    A construct may be:
    - overlay-like
    - oscillator-like
    - non-visual

    This family module mirrors the architectural style of indicators.py and
    oscillators.py so it can scale cleanly as larger constructs arrive.

    Current scope in this phase:
    - dummy_overlay
    - dummy_oscillator
    - dummy_non_visual

    Legacy transform utilities preserved for later promotion:
    - derivative
    - slope
    - angle
    """

    _REGISTRY: Dict[str, str] = {
        "dummy_overlay": "_calculate_dummy_overlay_result",
        "dummy_oscillator": "_calculate_dummy_oscillator_result",
        "dummy_non_visual": "_calculate_dummy_non_visual_result",
    }

    # ------------------------------------------------------------------
    # Public family entrypoint
    # ------------------------------------------------------------------

    @classmethod
    def calculate(cls, request: ConstructRequest) -> ConstructResult:
        name = str(request.name).strip().lower()
        if not name:
            raise ValueError("ConstructRequest.name must not be empty.")

        method_name = cls._REGISTRY.get(name)
        if method_name is None:
            available = ", ".join(sorted(cls._REGISTRY.keys()))
            raise ValueError(f"Unknown construct '{name}'. Available constructs: {available}")

        data = cls._normalize_input_dataframe(request.data)
        params = dict(request.params or {})

        method = getattr(cls, method_name)
        return method(data=data, params=params)

    # ------------------------------------------------------------------
    # Core normalization helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize_input_dataframe(data: pd.DataFrame) -> pd.DataFrame:
        if not isinstance(data, pd.DataFrame):
            raise TypeError("ConstructRequest.data must be a pandas DataFrame.")

        if data.empty:
            raise ValueError("Construct input dataframe is empty.")

        df = data.copy()

        required = ["close"]
        missing = [col for col in required if col not in df.columns]
        if missing:
            raise ValueError(f"Construct input is missing required columns: {missing}")

        if "time" not in df.columns:
            if "ts_ms" in df.columns:
                df["time"] = df["ts_ms"]
            else:
                df["time"] = pd.Series(df.index, index=df.index)

        if "timeframe" not in df.columns:
            df["timeframe"] = pd.Series(pd.NA, index=df.index, dtype="string")

        return df

    @staticmethod
    def _time_series(df: pd.DataFrame) -> pd.Series:
        return pd.Series(df["time"], index=df.index, name="time")

    @staticmethod
    def _timeframe_series(df: pd.DataFrame) -> pd.Series:
        return pd.Series(df["timeframe"], index=df.index, name="timeframe")

    @staticmethod
    def _float_series(values: pd.Series, *, index: pd.Index) -> pd.Series:
        series = values.reindex(index)
        if not pd.api.types.is_numeric_dtype(series):
            series = pd.to_numeric(series, errors="coerce")
        return series.astype("float32")

    @classmethod
    def _single_line_result(
        cls,
        *,
        name: str,
        title: str,
        line_key: str,
        line_title: str,
        values: pd.Series,
        data: pd.DataFrame,
        params: Dict[str, Any],
        metadata: Dict[str, Any] | None = None,
    ) -> ConstructResult:
        index = data.index
        line = ConstructLine(
            key=line_key,
            title=line_title,
            values=cls._float_series(values, index=index),
        )
        return ConstructResult(
            name=name,
            title=title,
            index=index,
            time=cls._time_series(data),
            timeframe=cls._timeframe_series(data),
            params=dict(params),
            lines=(line,),
            metadata=dict(metadata or {}),
        )

    @classmethod
    def _empty_result(
        cls,
        *,
        name: str,
        title: str,
        data: pd.DataFrame,
        params: Dict[str, Any],
        metadata: Dict[str, Any] | None = None,
    ) -> ConstructResult:
        return ConstructResult(
            name=name,
            title=title,
            index=data.index,
            time=cls._time_series(data),
            timeframe=cls._timeframe_series(data),
            params=dict(params),
            lines=(),
            metadata=dict(metadata or {}),
        )

    # ------------------------------------------------------------------
    # Dummy constructs for architecture testing
    # ------------------------------------------------------------------

    @classmethod
    def _calculate_dummy_overlay_result(
        cls,
        *,
        data: pd.DataFrame,
        params: Dict[str, Any],
    ) -> ConstructResult:
        """
        Overlay-like dummy construct.

        Produces a single EMA-style line over close prices so we can validate
        that construct behavior can render in the price pane without pretending
        to be an indicator family tool.
        """
        period = int(params.get("period", 14))
        if period < 1:
            raise ValueError("dummy_overlay.period must be >= 1")

        close = pd.to_numeric(data["close"], errors="coerce")
        ema_like = close.ewm(span=period, adjust=False).mean()

        effective_params = dict(params)
        effective_params["period"] = period

        return cls._single_line_result(
            name="dummy_overlay",
            title="Dummy Overlay Construct",
            line_key="dummy_overlay",
            line_title=f"Dummy Overlay ({period})",
            values=ema_like,
            data=data,
            params=effective_params,
            metadata={
                "construct_mode": "overlay",
                "dummy": True,
            },
        )

    @classmethod
    def _calculate_dummy_oscillator_result(
        cls,
        *,
        data: pd.DataFrame,
        params: Dict[str, Any],
    ) -> ConstructResult:
        """
        Oscillator-like dummy construct.

        Produces a simple RSI-style line in the 0-100 range so we can validate
        lower-pane construct rendering and pane-managed lifecycle.
        """
        period = int(params.get("period", 14))
        if period < 1:
            raise ValueError("dummy_oscillator.period must be >= 1")

        close = pd.to_numeric(data["close"], errors="coerce")
        delta = close.diff()

        gain = delta.clip(lower=0.0)
        loss = -delta.clip(upper=0.0)

        avg_gain = gain.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
        avg_loss = loss.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()

        rs = avg_gain / avg_loss.replace(0.0, np.nan)
        rsi_like = 100.0 - (100.0 / (1.0 + rs))
        rsi_like = rsi_like.fillna(50.0)

        effective_params = dict(params)
        effective_params["period"] = period

        return cls._single_line_result(
            name="dummy_oscillator",
            title="Dummy Oscillator Construct",
            line_key="dummy_oscillator",
            line_title=f"Dummy Oscillator ({period})",
            values=rsi_like,
            data=data,
            params=effective_params,
            metadata={
                "construct_mode": "oscillator-pane",
                "dummy": True,
            },
        )

    @classmethod
    def _calculate_dummy_non_visual_result(
        cls,
        *,
        data: pd.DataFrame,
        params: Dict[str, Any],
    ) -> ConstructResult:
        """
        Non-visual dummy construct.

        Produces no chart lines on purpose. It exists to validate that the
        construct family can create a legitimate analysis-only study result
        that participates in session lifecycle without rendering.
        """
        window = int(params.get("window", 10))
        if window < 1:
            raise ValueError("dummy_non_visual.window must be >= 1")

        close = pd.to_numeric(data["close"], errors="coerce")
        rolling_mean = close.rolling(window=window, min_periods=1).mean()
        rolling_std = close.rolling(window=window, min_periods=1).std(ddof=0)

        latest_mean = float(rolling_mean.iloc[-1]) if len(rolling_mean) else float("nan")
        latest_std = float(rolling_std.iloc[-1]) if len(rolling_std) else float("nan")

        effective_params = dict(params)
        effective_params["window"] = window

        return cls._empty_result(
            name="dummy_non_visual",
            title="Dummy Non-Visual Construct",
            data=data,
            params=effective_params,
            metadata={
                "construct_mode": "non-visual",
                "dummy": True,
                "latest_mean_close": latest_mean,
                "latest_std_close": latest_std,
                "row_count": int(len(data)),
            },
        )

    # ------------------------------------------------------------------
    # Legacy / future analytical transform utilities
    # ------------------------------------------------------------------

    @staticmethod
    def _get_time_cols(df: pd.DataFrame) -> tuple[pd.Series | pd.Index, pd.Series]:
        time_col = df["time"] if "time" in df.columns else df.index
        if "timeframe" in df.columns:
            timeframe_col = df["timeframe"]
        else:
            timeframe_col = pd.Series(pd.NA, index=df.index, dtype="string")
        return time_col, timeframe_col

    @staticmethod
    def _select_numeric_feature_cols(df: pd.DataFrame) -> list[str]:
        """
        Select feature columns in order, excluding meta/categorical ones.
        """
        skip = {"time", "timeframe", "vwap_color"}
        return [c for c in df.columns if c not in skip]

    @staticmethod
    def derivative(data_dict: Mapping[str, Any]) -> pd.DataFrame:
        """
        First difference for each numeric feature column (Δx).

        Naming:
          - If ALL selected input feature names end with '_d1', outputs are
            labeled as second derivatives with suffix '_d2'.
          - Otherwise, outputs get suffix '_d1'.

        Also recomputes 'vwap_color' (if present in input) using:
          - 'fast_vwap_d1' vs 'slow_vwap_d1', or
          - 'fast_vwap_d2' vs 'slow_vwap_d2' (when upgrading).
        """
        data_df = data_dict["data_df"]

        time_col, timeframe_col = Constructs._get_time_cols(data_df)
        feat_cols = Constructs._select_numeric_feature_cols(data_df)

        derivatives = [data_df[c].astype(float).diff() for c in feat_cols]
        deriv_df = pd.concat(derivatives, axis=1)
        deriv_df.columns = feat_cols

        all_d1_inputs = all(c.endswith("_d1") for c in feat_cols)
        if all_d1_inputs:
            out_names = [c[:-3] + "_d2" for c in feat_cols]
        else:
            out_names = [f"{c}_d1" for c in feat_cols]

        deriv_df.columns = out_names

        out = pd.concat(
            [
                pd.Series(time_col, index=data_df.index, name="time"),
                pd.Series(timeframe_col, index=data_df.index, name="timeframe"),
                deriv_df,
            ],
            axis=1,
        )

        if "vwap_color" in data_df.columns:
            out["vwap_color"] = "silver"
            if {"fast_vwap_d2", "slow_vwap_d2"}.issubset(set(out.columns)):
                out.loc[out["fast_vwap_d2"] > out["slow_vwap_d2"], "vwap_color"] = "green"
                out.loc[out["fast_vwap_d2"] < out["slow_vwap_d2"], "vwap_color"] = "red"
            elif {"fast_vwap_d1", "slow_vwap_d1"}.issubset(set(out.columns)):
                out.loc[out["fast_vwap_d1"] > out["slow_vwap_d1"], "vwap_color"] = "green"
                out.loc[out["fast_vwap_d1"] < out["slow_vwap_d1"], "vwap_color"] = "red"

        for c in out.columns:
            if c not in ("time", "timeframe", "vwap_color"):
                out[c] = out[c].astype("float32")

        return out

    @staticmethod
    def slope(data_dict: Mapping[str, Any]) -> pd.DataFrame:
        """
        Per-second slope for each numeric column:
            slope = Δx / Δt_seconds
        where Δt_seconds = index.diff().total_seconds().

        Returns:
          time, timeframe, all *_slope columns, and vwap_color (if present),
          with 'fast_vwap_slope' vs 'slow_vwap_slope' determining color.
        """
        data_df = data_dict["data_df"]

        time_col, timeframe_col = Constructs._get_time_cols(data_df)
        feat_cols = Constructs._select_numeric_feature_cols(data_df)

        dt_seconds = data_df.index.to_series().diff().dt.total_seconds()

        slopes = []
        for c in feat_cols:
            x = data_df[c].astype(float)
            s = x.diff() / dt_seconds
            slopes.append(s)

        slopes_df = pd.concat(slopes, axis=1)
        slopes_df.columns = [f"{c}_slope" for c in feat_cols]

        out = pd.concat(
            [
                pd.Series(time_col, index=data_df.index, name="time"),
                pd.Series(timeframe_col, index=data_df.index, name="timeframe"),
                slopes_df,
            ],
            axis=1,
        )

        if "vwap_color" in data_df.columns:
            out["vwap_color"] = "silver"
            if {"fast_vwap_slope", "slow_vwap_slope"}.issubset(set(out.columns)):
                out.loc[out["fast_vwap_slope"] > out["slow_vwap_slope"], "vwap_color"] = "green"
                out.loc[out["fast_vwap_slope"] < out["slow_vwap_slope"], "vwap_color"] = "red"

        for c in out.columns:
            if c not in ("time", "timeframe", "vwap_color"):
                out[c] = out[c].astype("float32")

        return out

    @staticmethod
    def angle(data_dict: Mapping[str, Any]) -> pd.DataFrame:
        """
        Angle of each slope series:
            angle = arctan(slope)   (radians)

        Input:
          data_dict['data_df'] is expected to contain *_slope columns
          (and optionally 'time','timeframe','vwap_color').

        Output:
          time, timeframe, *_angle columns (converted from the matching *_slope
          names by replacing suffix), and vwap_color recomputed from
          'fast_vwap_angle' vs 'slow_vwap_angle' if available.
        """
        slopes_df = data_dict["data_df"]

        time_col, timeframe_col = Constructs._get_time_cols(slopes_df)

        feat_cols = Constructs._select_numeric_feature_cols(slopes_df)
        slope_cols = [c for c in feat_cols if c.endswith("_slope")]

        angles = [np.arctan(slopes_df[c].astype(float)) for c in slope_cols]
        angles_df = pd.concat(angles, axis=1)

        angle_cols = [c[:-6] + "_angle" for c in slope_cols]
        angles_df.columns = angle_cols

        out = pd.concat(
            [
                pd.Series(time_col, index=slopes_df.index, name="time"),
                pd.Series(timeframe_col, index=slopes_df.index, name="timeframe"),
                angles_df,
            ],
            axis=1,
        )

        if "vwap_color" in slopes_df.columns:
            out["vwap_color"] = "silver"
            if {"fast_vwap_angle", "slow_vwap_angle"}.issubset(set(out.columns)):
                out.loc[out["fast_vwap_angle"] > out["slow_vwap_angle"], "vwap_color"] = "green"
                out.loc[out["fast_vwap_angle"] < out["slow_vwap_angle"], "vwap_color"] = "red"

        for c in out.columns:
            if c not in ("time", "timeframe", "vwap_color"):
                out[c] = out[c].astype("float32")

        return out