from __future__ import annotations

from typing import Any, Dict

import numpy as np
import pandas as pd

from leonardo.financial_tools.ft_naming import build_source_token, build_unary_name

from .common import ConstructRuntimeCommon
from .contracts import ConstructResult


class _Runtime(ConstructRuntimeCommon):
    @classmethod
    def _calculate_percent_span_angle_result(
        cls,
        *,
        data: pd.DataFrame,
        params: Dict[str, Any],
    ) -> ConstructResult:
        """
        Windowed percent-span angle construct.

        Purpose and final semantic contract
        -----------------------------------
        This construct computes the angular transform of a *contiguous percent span*
        over a fixed bar window.

        It is intentionally distinct from the unary ``angle`` construct:

        - unary ``angle`` is a local, derivative-based feature
        - ``percent_span_angle`` is a windowed, span-based feature

        In other words, this construct answers:

            "Over the last w bars, what is the orientation of the total percent
            movement of this source?"

        It does NOT answer:

            "What is the local derivative-based angle right now?"

        Core calculation
        ----------------
        For a source ``x`` and window ``w``:

            dx = w - 1
            pct_span_t = ((x_t / x_{t-dx}) - 1) * 100
            theta_t = atan2(pct_span_t, dx)

        The final output unit is:
        - degrees if ``unit='deg'``
        - radians if ``unit='rad'``

        Why this is finalized as a span construct
        -----------------------------------------
        Earlier versions compressed the timeline with ``dropna()`` before
        computing percent change. That was operationally convenient but
        semantically sloppy because it could bridge across warm-up gaps or
        internal missing regions as though they were contiguous bars.

        This finalized version stays on the original timeline and computes a
        value only when the full trailing window is valid.

        Window validity policy
        ----------------------
        A value is emitted at bar ``t`` only if:

        - ``x_t`` is valid
        - ``x_{t-dx}`` is valid
        - and *every* observation in the full trailing window of size ``w``
          is valid

        If any value inside the effective window is missing, the output remains
        NaN.

        This means:
        - indicator warm-up regions remain honestly undefined
        - internal NaN gaps are not silently skipped
        - the feature always refers to a true contiguous bar span

        Typical interpretation
        ----------------------
        - strongly positive values: sustained upward percent movement over the span
        - strongly negative values: sustained downward percent movement over the span
        - values near zero: flat or weak net percent movement over the span

        Emitted naming
        --------------
        Ground-truth emitted line naming is:

            ``source_ang_pct_span_{window}``

        Examples:
        - ``ema_50_ang_pct_span_5``
        - ``bb_upper_ang_pct_span_8``

        Backward compatibility
        ----------------------
        The older construct name ``percent_angle`` remains supported as an alias,
        but the canonical runtime identity is now ``percent_span_angle``.

        Notes for pipeline usage
        ------------------------
        This construct is well suited for:
        - windowed trend-orientation features
        - smoothed directional descriptors
        - regime characterization over a fixed horizon

        It should not be confused with local derivative/angle features.
        """
        source_windows = cls._resolve_percent_span_angle_windows(data=data, params=params)

        unit = str(params.get("unit", "deg")).strip().lower()
        if unit not in {"deg", "rad"}:
            raise ValueError("percent_span_angle.unit must be 'deg' or 'rad'")

        factor = 180.0 / np.pi if unit == "deg" else 1.0
        line_specs: list[tuple[str, str, pd.Series]] = []

        for source_name, window in source_windows.items():
            source_series = cls._extract_numeric_source_series(
                data=data,
                source_column=source_name,
                context=f"percent_span_angle input ({source_name})",
            ).astype("float64")

            dx = window - 1

            # Build an explicit contiguous-window validity mask. A value can be
            # emitted only when every observation in the full trailing window is
            # present. This preserves the original timeline and avoids silently
            # jumping across warm-up NaNs or internal gaps.
            valid = source_series.notna().astype("int64")
            full_window_valid = valid.rolling(window=window, min_periods=window).sum().eq(window)

            # Percent span from t-dx to t on the original timeline. We disable
            # fill behavior explicitly so pandas does not pad through gaps behind
            # our backs like a sneaky little goblin.
            pct_span = source_series.pct_change(periods=dx, fill_method=None).mul(100.0)

            # Angle of average percent-per-bar orientation across the span.
            theta = np.arctan2(pct_span, float(dx)) * factor

            aligned = pd.Series(np.nan, index=data.index, dtype="float64")
            aligned.loc[full_window_valid] = theta.loc[full_window_valid].astype("float64")

            line_key = f"{build_source_token(source_name)}_ang_pct_span_{window}"
            line_specs.append((line_key, line_key, aligned))

        effective_params = dict(params)
        effective_params["source_windows"] = dict(source_windows)
        effective_params["unit"] = unit

        return cls._multi_line_result(
            name="percent_span_angle",
            title="Percent Span Angles",
            line_specs=line_specs,
            data=data,
            params=effective_params,
            metadata={
                "construct_mode": "oscillator-pane",
                "construct_kind": "percent_span_angle",
                "source_windows": dict(source_windows),
                "unit": unit,
                "percent_based": True,
                "calculation_basis": "percent-span",
                "window_policy": "full-contiguous-valid-window-required",
                "line_naming": "source_ang_pct_span_window",
            },
        )


def calculate(*, data: pd.DataFrame, params: Dict[str, Any], context: Any = None) -> ConstructResult:
    return _Runtime._calculate_percent_span_angle_result(data=data, params=params)
