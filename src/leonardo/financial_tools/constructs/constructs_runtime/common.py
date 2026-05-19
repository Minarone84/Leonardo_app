from __future__ import annotations

from typing import Any, Dict, Iterable

import numpy as np
import pandas as pd

from leonardo.financial_tools.ft_naming import build_source_token

from .contracts import ConstructLine, ConstructResult


class ConstructRuntimeCommon:
    _BRAID_ORDER_TO_STATE: Dict[tuple[str, str, str], int] = {
            ("slow", "mid", "fast"): 1,
            ("slow", "fast", "mid"): 2,
            ("fast", "slow", "mid"): 3,
            ("fast", "mid", "slow"): 4,
            ("mid", "fast", "slow"): 5,
            ("mid", "slow", "fast"): 6,
        }

    @classmethod
    def _normalize_input_dataframe(cls, data: pd.DataFrame) -> pd.DataFrame:
        """
        Normalize the construct input dataframe at the family level.

        Guarantees provided here:
        - input is a pandas DataFrame
        - input is not empty
        - explicit timeline columns are lightly validated for strict ordering
        - ``time`` exists, or is synthesized from ``ts_ms`` or index
        - ``timeframe`` exists, or is synthesized as an NA string series

        Important rule
        --------------
        This method does not sort or mutate source order beyond adding the
        required passthrough columns. If the caller provides an explicit
        timeline that is out of order, we reject it instead of silently
        reordering rows behind the caller's back.
        """
        if not isinstance(data, pd.DataFrame):
            raise TypeError("ConstructRequest.data must be a pandas DataFrame.")

        if data.empty:
            raise ValueError("Construct input dataframe is empty.")

        df = data.copy()
        cls._validate_input_order(df)

        if "time" not in df.columns:
            if "ts_ms" in df.columns:
                df["time"] = df["ts_ms"]
            else:
                df["time"] = pd.Series(df.index, index=df.index)

        if "timeframe" not in df.columns:
            df["timeframe"] = pd.Series(pd.NA, index=df.index, dtype="string")

        return df

    @staticmethod
    def _require_strictly_increasing_numeric_series(values: pd.Series, *, context: str) -> None:
        """
        Validate that a numeric series is strictly increasing on all valid rows.
        """
        valid = values.dropna()
        if valid.empty:
            return

        diffs = valid.diff().dropna()
        if diffs.empty:
            return

        if bool((diffs <= 0).any()):
            raise ValueError(f"{context} must be strictly increasing.")

    @classmethod
    def _validate_input_order(cls, df: pd.DataFrame) -> None:
        """
        Perform light family-level order validation when an explicit timeline exists.

        Why this exists
        ---------------
        Constructs such as derivatives, trap_area, percent_span_angle, and
        angle_momentum are row-order sensitive. Accepting shuffled inputs would
        still produce deterministic output, but it would be deterministic
        nonsense.

        This helper is intentionally conservative:
        - if ``ts_ms`` exists, it must be fully numeric and strictly increasing
        - otherwise, if ``time`` exists and is fully numeric or fully datetime-like,
          it must be strictly increasing
        - otherwise, if the index is a DatetimeIndex, it must be strictly increasing

        If no explicit timeline is available, we do not guess.
        """
        if "ts_ms" in df.columns:
            ts_ms = pd.to_numeric(df["ts_ms"], errors="coerce")
            if bool(ts_ms.isna().any()):
                raise ValueError("Construct input column 'ts_ms' contains non-numeric values.")
            cls._require_strictly_increasing_numeric_series(
                ts_ms.astype("float64"),
                context="construct input ts_ms",
            )
            return

        if "time" in df.columns:
            raw_time = df["time"]

            if bool(raw_time.notna().any()):
                numeric_time = pd.to_numeric(raw_time, errors="coerce")
                if int(numeric_time.notna().sum()) == int(raw_time.notna().sum()):
                    cls._require_strictly_increasing_numeric_series(
                        numeric_time.astype("float64"),
                        context="construct input time",
                    )
                    return

                datetime_time = pd.to_datetime(raw_time, errors="coerce")
                if int(datetime_time.notna().sum()) == int(raw_time.notna().sum()):
                    cls._require_strictly_increasing_numeric_series(
                        datetime_time.astype("int64").astype("float64"),
                        context="construct input time",
                    )
                    return

        if isinstance(df.index, pd.DatetimeIndex):
            if (not df.index.is_monotonic_increasing) or bool(df.index.has_duplicates):
                raise ValueError("Construct input DatetimeIndex must be strictly increasing.")

    @staticmethod
    def _require_columns(data: pd.DataFrame, required: Iterable[str], *, context: str) -> None:
        required_list = list(required)
        missing = [col for col in required_list if col not in data.columns]
        if missing:
            raise ValueError(f"{context} is missing required columns: {missing}")

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

    @staticmethod
    def _normalize_source_columns_param(source_columns: Any, *, context: str) -> list[str]:
        """
        Normalize a generic source column parameter into a non-empty list[str].

        Accepted shapes:
        - single string containing one or more comma-separated column names
        - iterable of values convertible to stripped strings
        """
        if isinstance(source_columns, str):
            normalized = [part.strip() for part in source_columns.split(",")]
        else:
            try:
                normalized = [str(value).strip() for value in source_columns]
            except TypeError as exc:
                raise ValueError(f"{context} must be a string or an iterable of strings") from exc

        normalized = [name for name in normalized if name]
        if not normalized:
            raise ValueError(f"{context} must not be empty")

        duplicates = sorted({name for name in normalized if normalized.count(name) > 1})
        if duplicates:
            raise ValueError(f"{context} contains duplicates: {duplicates}")

        return normalized

    @staticmethod
    def _normalize_single_source_param(source: Any, *, context: str) -> str:
        normalized = str(source or "").strip()
        if not normalized:
            raise ValueError(f"{context} requires a non-empty source column selection")
        return normalized

    @classmethod
    def _resolve_single_source_name(cls, *, params: Dict[str, Any], context: str) -> str:
        source = params.get("source", params.get("source_column"))
        return cls._normalize_single_source_param(source, context=context)

    @classmethod
    def _resolve_fast_mid_slow_sources(
        cls,
        *,
        params: Dict[str, Any],
        context: str,
    ) -> dict[str, str]:
        fast = cls._normalize_single_source_param(params.get("fast"), context=f"{context}.fast")
        slow = cls._normalize_single_source_param(params.get("slow"), context=f"{context}.slow")
        mid_raw = params.get("mid")
        mid = str(mid_raw).strip() if mid_raw is not None else ""
        if mid:
            return {"fast": fast, "mid": mid, "slow": slow}
        return {"fast": fast, "slow": slow}

    @classmethod
    def _extract_numeric_source_frame(
        cls,
        *,
        data: pd.DataFrame,
        source_columns: list[str],
        context: str,
    ) -> pd.DataFrame:
        cls._require_columns(data, source_columns, context=context)

        frame = pd.DataFrame(index=data.index)
        for column in source_columns:
            frame[column] = pd.to_numeric(data[column], errors="coerce").astype(float)

        if frame.dropna(how="all").empty:
            raise ValueError(
                f"{context} produced no usable numeric data after coercion for source_columns={source_columns}"
            )

        return frame

    @classmethod
    def _extract_numeric_source_series(
        cls,
        *,
        data: pd.DataFrame,
        source_column: str,
        context: str,
    ) -> pd.Series:
        cls._require_columns(data, [source_column], context=context)
        series = pd.to_numeric(data[source_column], errors="coerce").astype(float)

        if series.dropna().empty:
            raise ValueError(
                f"{context} produced no usable numeric data after coercion for source={source_column}"
            )

        return series

    @classmethod
    def _extract_numeric_role_frame(
        cls,
        *,
        data: pd.DataFrame,
        role_sources: dict[str, str],
        context: str,
    ) -> pd.DataFrame:
        source_columns = list(role_sources.values())
        cls._require_columns(data, source_columns, context=context)

        frame = pd.DataFrame(index=data.index)
        for role, source_name in role_sources.items():
            frame[role] = pd.to_numeric(data[source_name], errors="coerce").astype(float)

        if frame.dropna(how="all").empty:
            raise ValueError(f"{context} produced no usable numeric data after coercion")

        return frame

    @classmethod
    def _raw_braid_state_from_role_values(
        cls,
        *,
        fast: Any,
        mid: Any,
        slow: Any,
    ) -> float:
        """
        Resolve one raw braid ambient state from explicit fast/mid/slow values.

        Rules:
        - any NaN in the triplet -> NaN
        - any tie in the triplet -> NaN
        - otherwise map strict ordering to the canonical braid state integer
        """
        if pd.isna(fast) or pd.isna(mid) or pd.isna(slow):
            return np.nan

        values = {
            "fast": float(fast),
            "mid": float(mid),
            "slow": float(slow),
        }

        if len(set(values.values())) < 3:
            return np.nan

        ordered = tuple(sorted(values, key=values.get, reverse=True))
        return float(cls._BRAID_ORDER_TO_STATE[ordered])

    @classmethod
    def _raw_braid_state_series(cls, frame: pd.DataFrame) -> pd.Series:
        """
        Compute the raw braid ambient state series from a role-normalized frame.

        Centralizing this logic keeps:
        - braids ambient-state output
        - braid_instability state-change logic

        on one shared source of truth instead of duplicating ordering code in
        two separate construct implementations.
        """
        cls._require_columns(frame, ["fast", "mid", "slow"], context="raw braid state")
        return frame.apply(
            lambda row: cls._raw_braid_state_from_role_values(
                fast=row["fast"],
                mid=row["mid"],
                slow=row["slow"],
            ),
            axis=1,
        ).astype("float64")

    @classmethod
    def _resolve_delta_pairs(
        cls,
        *,
        params: Dict[str, Any],
        context: str,
    ) -> list[dict[str, str]]:
        """
        Resolve delta pair definitions.

        Supported parameter shapes
        --------------------------
        1. Single pair:
           - ``fast`` + ``slow``

        2. Multiple pairs:
           - ``pairs=[{"fast": "a", "slow": "b"}, ...]``

        Design note
        -----------
        Delta is intentionally directional in Leonardo:
        it always means ``fast - slow``.

        This gives the construct a fixed semantic pole:
        - positive delta  -> fast above slow
        - negative delta  -> fast below slow
        """
        pairs_raw = params.get("pairs")
        if pairs_raw is not None:
            if not isinstance(pairs_raw, (list, tuple)) or not pairs_raw:
                raise ValueError(f"{context}.pairs must be a non-empty list of pair definitions")

            resolved: list[dict[str, str]] = []
            seen: set[tuple[str, str]] = set()

            for i, pair in enumerate(pairs_raw):
                if not isinstance(pair, dict):
                    raise ValueError(f"{context}.pairs[{i}] must be a dict with 'fast' and 'slow'")

                fast = cls._normalize_single_source_param(pair.get("fast"), context=f"{context}.pairs[{i}].fast")
                slow = cls._normalize_single_source_param(pair.get("slow"), context=f"{context}.pairs[{i}].slow")

                key = (fast, slow)
                if key in seen:
                    raise ValueError(f"{context}.pairs contains duplicate pair ({fast}, {slow})")
                seen.add(key)

                resolved.append({"fast": fast, "slow": slow})

            return resolved

        fast = cls._normalize_single_source_param(params.get("fast"), context=f"{context}.fast")
        slow = cls._normalize_single_source_param(params.get("slow"), context=f"{context}.slow")
        return [{"fast": fast, "slow": slow}]

    @classmethod
    def _resolve_derivative_axis(
        cls,
        *,
        data: pd.DataFrame,
        params: Dict[str, Any],
    ) -> tuple[str, pd.Series, str, str | None]:
        """
        Resolve the explicit independent axis used by the derivative construct.

        Supported modes:
        - axis="bar"  -> derivative with respect to bar/sample position
        - axis="time" -> derivative with respect to elapsed time in seconds

        Important:
        - the axis must be explicit
        - time-axis derivative never guesses from synthesized fallback columns
        """
        axis = str(params.get("axis", "")).strip().lower()
        if axis not in {"bar", "time"}:
            raise ValueError("derivative.axis must be explicitly set to 'bar' or 'time'")

        if axis == "bar":
            axis_values = pd.Series(
                np.arange(len(data), dtype="float64"),
                index=data.index,
                name="bar_index",
            )
            return axis, axis_values, "bars", None

        time_column_raw = params.get("time_column")
        if time_column_raw is None or str(time_column_raw).strip() == "":
            if isinstance(data.index, pd.DatetimeIndex):
                axis_values = (
                    data.index.to_series(index=data.index).astype("int64").astype("float64") / 1_000_000_000.0
                )
                return "time", axis_values, "seconds", None
            raise ValueError(
                "derivative with axis='time' requires either a DatetimeIndex or an explicit time_column"
            )

        time_column = str(time_column_raw).strip()
        cls._require_columns(data, [time_column], context="derivative time axis")

        raw = data[time_column]
        numeric = pd.to_numeric(raw, errors="coerce")

        if numeric.notna().any():
            time_unit = str(params.get("time_unit", "")).strip().lower()
            if time_unit not in {"s", "sec", "second", "seconds", "ms", "millisecond", "milliseconds"}:
                raise ValueError(
                    "derivative.time_unit must be explicitly set to 's' or 'ms' when time_column is numeric"
                )

            scale = 1.0 if time_unit in {"s", "sec", "second", "seconds"} else 1_000.0
            axis_values = (numeric.astype("float64") / scale).rename(time_column)
            return "time", axis_values, "seconds", time_column

        dt = pd.to_datetime(raw, errors="coerce")
        if dt.notna().any():
            axis_values = (dt.astype("int64").astype("float64") / 1_000_000_000.0).rename(time_column)
            return "time", axis_values, "seconds", time_column

        raise ValueError(
            f"derivative time_column '{time_column}' could not be interpreted as numeric time or datetime values"
        )

    @staticmethod
    def _validate_derivative_axis_monotonic(
        *,
        axis_values: pd.Series,
        context: str,
    ) -> None:
        valid_axis = axis_values.dropna()
        if valid_axis.empty:
            raise ValueError(f"{context} produced no usable axis values")

        diffs = valid_axis.diff().dropna()
        if diffs.empty:
            return

        if (diffs <= 0).any():
            raise ValueError(f"{context} must be strictly increasing on valid observations")

    @staticmethod
    def _finite_first_derivative(
        *,
        values: pd.Series,
        axis_values: pd.Series,
        scheme: str,
    ) -> pd.Series:
        result = pd.Series(np.nan, index=values.index, dtype="float64")
        valid = values.notna() & axis_values.notna()

        if scheme == "central":
            x_prev = values.shift(1)
            x_curr = values
            x_next = values.shift(-1)

            u_prev = axis_values.shift(1)
            u_curr = axis_values
            u_next = axis_values.shift(-1)

            h_prev = u_curr - u_prev
            h_next = u_next - u_curr

            ok = (
                valid
                & valid.shift(1, fill_value=False)
                & valid.shift(-1, fill_value=False)
                & h_prev.notna()
                & h_next.notna()
                & (h_prev > 0)
                & (h_next > 0)
            )

            numerator = (
                (h_prev ** 2) * x_next
                + ((h_next ** 2) - (h_prev ** 2)) * x_curr
                - (h_next ** 2) * x_prev
            )
            denominator = h_prev * h_next * (h_prev + h_next)
            result.loc[ok] = (numerator / denominator).loc[ok]
            return result

        if scheme == "forward":
            x_next = values.shift(-1)
            u_next = axis_values.shift(-1)
            denom = u_next - axis_values
            ok = (
                valid
                & valid.shift(-1, fill_value=False)
                & denom.notna()
                & (denom > 0)
            )
            result.loc[ok] = ((x_next - values) / denom).loc[ok]
            return result

        raise ValueError("derivative.scheme must be 'central' or 'forward'")

    @staticmethod
    def _finite_second_derivative(
        *,
        values: pd.Series,
        axis_values: pd.Series,
        scheme: str,
    ) -> pd.Series:
        if scheme != "central":
            raise ValueError("second derivative currently supports only scheme='central'")

        result = pd.Series(np.nan, index=values.index, dtype="float64")
        valid = values.notna() & axis_values.notna()

        x_prev = values.shift(1)
        x_curr = values
        x_next = values.shift(-1)

        u_prev = axis_values.shift(1)
        u_curr = axis_values
        u_next = axis_values.shift(-1)

        h_prev = u_curr - u_prev
        h_next = u_next - u_curr

        ok = (
            valid
            & valid.shift(1, fill_value=False)
            & valid.shift(-1, fill_value=False)
            & h_prev.notna()
            & h_next.notna()
            & (h_prev > 0)
            & (h_next > 0)
        )

        numerator = 2.0 * (
            (h_prev * x_next) - ((h_prev + h_next) * x_curr) + (h_next * x_prev)
        )
        denominator = h_prev * h_next * (h_prev + h_next)

        result.loc[ok] = (numerator / denominator).loc[ok]
        return result

    @staticmethod
    def _resolve_angle_reference_interval(
        *,
        axis_mode: str,
        params: Dict[str, Any],
    ) -> tuple[float, str]:
        """
        Resolve the reference interval used to make the angle input dimensionless.

        Angle is defined as a bounded transform of a normalized first derivative:

            theta = arctan((dx/du * reference_interval) / scale)

        For bar-axis derivatives, one bar is the natural reference interval.
        For time-axis derivatives, the caller must explicitly declare the reference
        interval in seconds to avoid hidden assumptions.
        """
        if axis_mode == "bar":
            return 1.0, "bars"

        reference_seconds_raw = params.get("reference_seconds")
        if reference_seconds_raw is None:
            raise ValueError(
                "angle with axis='time' requires an explicit positive reference_seconds parameter"
            )

        reference_seconds = float(reference_seconds_raw)
        if (not np.isfinite(reference_seconds)) or (reference_seconds <= 0.0):
            raise ValueError("angle.reference_seconds must be a finite value > 0")

        return reference_seconds, "seconds"

    @staticmethod
    def _normalized_angle_ratio(
        *,
        first_derivative: pd.Series,
        source_values: pd.Series,
        reference_interval: float,
        eps: float,
    ) -> pd.Series:
        """
        Build the dimensionless input fed to arctan for the unary angle construct.

        The unary angle construct is defined as the angular transform of the
        local percent-relative change over the chosen reference interval:

            ratio = ((dx/du) * reference_interval) / max(abs(x), eps)

        This keeps the angle grounded in a single, explicit meaning:
        bounded local relative movement intensity of the source itself.
        """
        denom = source_values.abs().clip(lower=eps)
        ratio = ((first_derivative * reference_interval) / denom) * 100.0
        ratio = ratio.replace([np.inf, -np.inf], np.nan)
        return ratio.astype("float64")

    @staticmethod
    def _json_ready_value(value: Any) -> Any:
        if isinstance(value, dict):
            return {str(k): ConstructRuntimeCommon._json_ready_value(v) for k, v in value.items()}
        if isinstance(value, list):
            return [ConstructRuntimeCommon._json_ready_value(v) for v in value]
        if isinstance(value, tuple):
            return [ConstructRuntimeCommon._json_ready_value(v) for v in value]
        if isinstance(value, pd.Timestamp):
            return value.isoformat()
        if isinstance(value, pd.Timedelta):
            return str(value)
        if isinstance(value, np.generic):
            return value.item()
        if pd.isna(value):
            return None
        return value

    @staticmethod
    def _records_from_dataframe(df: pd.DataFrame) -> list[dict[str, Any]]:
        safe_df = df.copy()
        return [
            {str(column): ConstructRuntimeCommon._json_ready_value(value) for column, value in record.items()}
            for record in safe_df.to_dict(orient="records")
        ]

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
        return cls._multi_line_result(
            name=name,
            title=title,
            line_specs=((line_key, line_title, values),),
            data=data,
            params=params,
            metadata=metadata,
        )

    @classmethod
    def _multi_line_result(
        cls,
        *,
        name: str,
        title: str,
        line_specs: Iterable[tuple[str, str, pd.Series]],
        data: pd.DataFrame,
        params: Dict[str, Any],
        metadata: Dict[str, Any] | None = None,
    ) -> ConstructResult:
        index = data.index
        lines = tuple(
            ConstructLine(
                key=line_key,
                title=line_title,
                values=cls._float_series(values, index=index),
            )
            for line_key, line_title, values in line_specs
        )
        return ConstructResult(
            name=name,
            title=title,
            index=index,
            time=cls._time_series(data),
            timeframe=cls._timeframe_series(data),
            params=dict(params),
            lines=lines,
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

    @staticmethod
    def _trap_segments_from(diff: pd.Series, *, zero_eps: float = 0.0) -> pd.Series:
        """
        Build segment IDs for a difference series. Segments split on:
        - sign change,
        - near-zero,
        - NaN gaps.
        """
        s = diff.astype(float)

        if zero_eps > 0:
            s = s.mask(s.abs() <= zero_eps, 0.0)

        sign = np.sign(s)
        sign_shift = sign.shift(1)

        boundary = sign.ne(sign_shift)
        boundary |= s.eq(0) | s.shift(1).eq(0)
        boundary |= s.isna() | s.shift(1).isna()

        if len(boundary) > 0:
            boundary.iloc[0] = True

        return boundary.fillna(False).cumsum()

    @staticmethod
    def _cum_trap_by_segment(diff: pd.Series, seg_id: pd.Series) -> pd.Series:
        """
        Cumulative trapezoid per segment for a difference series.

        Gap honesty rule
        ----------------
        Rows where ``diff`` itself is NaN must remain NaN in the output.

        Only valid segment starts receive a ``0.0`` seed. This preserves the
        original meaning of segment initialization without silently converting
        NaN gap rows into fake neutral trap-area values.
        """
        d = diff.astype(float)
        g = seg_id

        prev = d.shift(1)
        same_seg = g.eq(g.shift(1))

        inc = pd.Series(np.nan, index=d.index, dtype="float64")

        # Ongoing valid segment rows accumulate the trapezoid increment.
        ongoing_mask = same_seg & d.notna() & prev.notna()
        inc.loc[ongoing_mask] = (0.5 * (d + prev)).loc[ongoing_mask]

        # First valid row of a segment contributes 0.0 by construction.
        segment_start_mask = (~same_seg) & d.notna()
        inc.loc[segment_start_mask] = 0.0

        return inc.groupby(g, dropna=True).cumsum()

    @classmethod
    def _build_trap_area_pairs(
        cls,
        *,
        role_sources: dict[str, str],
    ) -> list[tuple[str, str, str]]:
        """
        Build ordered trap-area pairs using faster-minus-slower convention.

        Supported shapes:
        - fast + slow
        - fast + mid + slow
        """
        roles = set(role_sources.keys())

        if roles == {"fast", "slow"}:
            fast_token = build_source_token(role_sources["fast"])
            slow_token = build_source_token(role_sources["slow"])
            return [("fast", "slow", f"{fast_token}_{slow_token}_trapA")]

        if roles == {"fast", "mid", "slow"}:
            fast_token = build_source_token(role_sources["fast"])
            mid_token = build_source_token(role_sources["mid"])
            slow_token = build_source_token(role_sources["slow"])
            return [
                ("fast", "mid", f"{fast_token}_{mid_token}_trapA"),
                ("fast", "slow", f"{fast_token}_{slow_token}_trapA"),
                ("mid", "slow", f"{mid_token}_{slow_token}_trapA"),
            ]

        raise ValueError("trap_area requires either fast+slow or fast+mid+slow")

    @classmethod
    def _resolve_percent_span_angle_windows(
        cls,
        *,
        data: pd.DataFrame,
        params: Dict[str, Any],
    ) -> dict[str, int]:
        """
        Resolve percent-span-angle source/window configuration.

        Supported parameter shapes:
        - ``source_windows``: {"col_a": 5, "col_b": 8}
        - ``source`` + ``window``
        - ``source_column`` + ``window``
        - ``source_columns`` + ``window`` (same window broadcast to all sources)

        Finalized semantic meaning
        --------------------------
        This construct is explicitly a *windowed percent-span angle* feature.
        It is not the local percent version of the unary ``angle`` construct.

        Each source/window pair defines a contiguous bar-span requirement:
        - window size = ``w`` bars
        - effective percent span = from t-(w-1) to t

        Therefore the source/window mapping resolved here becomes part of the
        feature identity and later metadata.
        """
        source_windows = params.get("source_windows")
        if source_windows is not None:
            if not isinstance(source_windows, dict) or not source_windows:
                raise ValueError("percent_span_angle.source_windows must be a non-empty dict")
            resolved: dict[str, int] = {}
            for key, value in source_windows.items():
                name = cls._normalize_single_source_param(
                    key,
                    context="percent_span_angle.source_windows key",
                )
                window = int(value)
                if window < 2:
                    raise ValueError(f"percent_span_angle window for '{name}' must be >= 2")
                resolved[name] = window
            cls._require_columns(data, resolved.keys(), context="percent_span_angle input")
            return resolved

        explicit_single = params.get("source", params.get("source_column"))
        if explicit_single is not None:
            name = cls._normalize_single_source_param(explicit_single, context="percent_span_angle.source")
            window = int(params.get("window", 2))
            if window < 2:
                raise ValueError("percent_span_angle.window must be >= 2")
            cls._require_columns(data, [name], context="percent_span_angle input")
            return {name: window}

        explicit_many = params.get("source_columns")
        if explicit_many is None:
            raise ValueError(
                "percent_span_angle requires one of: source_windows, source, source_column, or source_columns"
            )

        names = cls._normalize_source_columns_param(
            explicit_many,
            context="percent_span_angle.source_columns",
        )
        window = int(params.get("window", 2))
        if window < 2:
            raise ValueError("percent_span_angle.window must be >= 2")
        cls._require_columns(data, names, context="percent_span_angle input")
        return {name: window for name in names}
