from __future__ import annotations

from typing import Any, Dict

import numpy as np
import pandas as pd

from leonardo.financial_tools.ft_naming import build_source_token, build_unary_name

from .common import ConstructRuntimeCommon
from .contracts import ConstructResult


class _Runtime(ConstructRuntimeCommon):
    @classmethod
    def _calculate_angle_result(
        cls,
        *,
        data: pd.DataFrame,
        params: Dict[str, Any],
    ) -> ConstructResult:
        """
        Unary angle construct.

        Mathematical meaning
        --------------------
        This construct computes a bounded angular transform of the canonical first
        derivative of a source series. The derivative is normalized into a local
        percent-relative change ratio over a declared reference interval, then
        mapped through arctan.

        Core idea:
            theta = arctan(100 * (dx/du * reference_interval) / max(abs(x), eps))

        Where:
        - ``dx/du`` is the canonical first derivative
        - ``reference_interval`` is 1 bar for bar-axis angle, or an explicit
          ``reference_seconds`` value for time-axis angle
        - ``max(abs(x), eps)`` protects normalization near zero source values

        Supported derivative schemes:
        - ``central`` (default)
        - ``forward``

        Supported output units:
        - ``deg`` (default)
        - ``rad``

        Emits:
        - ``source__ang``
        """
        source_name = cls._resolve_single_source_name(
            params=params,
            context="angle input",
        )
        source_series = cls._extract_numeric_source_series(
            data=data,
            source_column=source_name,
            context="angle input",
        )

        unit = str(params.get("unit", "deg")).strip().lower()
        if unit not in {"deg", "rad"}:
            raise ValueError("angle.unit must be 'deg' or 'rad'")

        scheme = str(params.get("scheme", "central")).strip().lower()
        if scheme not in {"central", "forward"}:
            raise ValueError("angle.scheme must be 'central' or 'forward'")

        eps = float(params.get("eps", 1e-12))
        if (not np.isfinite(eps)) or (eps <= 0.0):
            raise ValueError("angle.eps must be a finite value > 0")

        legacy_angle_type = params.get("angle_type")
        if legacy_angle_type is not None:
            legacy_angle_type = str(legacy_angle_type).strip().lower()
            if legacy_angle_type not in {"", "ang", "ang_pct"}:
                raise ValueError("angle.angle_type is deprecated; only legacy values 'ang' or 'ang_pct' are accepted")

        axis_params = dict(params)
        axis_params.setdefault("axis", "bar")

        axis_mode, axis_values, axis_unit, time_column = cls._resolve_derivative_axis(
            data=data,
            params=axis_params,
        )
        cls._validate_derivative_axis_monotonic(
            axis_values=axis_values,
            context="angle axis",
        )

        first_derivative = cls._finite_first_derivative(
            values=source_series,
            axis_values=axis_values,
            scheme=scheme,
        )

        reference_interval, reference_unit = cls._resolve_angle_reference_interval(
            axis_mode=axis_mode,
            params=params,
        )

        normalized_ratio = cls._normalized_angle_ratio(
            first_derivative=first_derivative,
            source_values=source_series,
            reference_interval=reference_interval,
            eps=eps,
        )

        angle_values = np.arctan(normalized_ratio)
        if unit == "deg":
            angle_values = np.degrees(angle_values)

        effective_params = dict(params)
        effective_params["source"] = source_name
        effective_params["unit"] = unit
        effective_params["scheme"] = scheme
        effective_params["axis"] = axis_mode
        effective_params["eps"] = eps
        if "angle_type" in effective_params:
            effective_params.pop("angle_type")
        if axis_mode == "time":
            effective_params["reference_seconds"] = reference_interval
            if time_column is not None:
                effective_params["time_column"] = time_column
                if "time_unit" in params:
                    effective_params["time_unit"] = params["time_unit"]

        line_key = build_unary_name(source_name, "ang")

        return cls._single_line_result(
            name="angle",
            title="Angles",
            line_key=line_key,
            line_title=line_key,
            values=pd.Series(angle_values, index=data.index, dtype="float64"),
            data=data,
            params=effective_params,
            metadata={
                "construct_mode": "oscillator-pane",
                "construct_kind": "angle",
                "source": source_name,
                "unit": unit,
                "axis": axis_mode,
                "axis_unit": axis_unit,
                "scheme": scheme,
                "time_column": time_column,
                "reference_interval": reference_interval,
                "reference_interval_unit": reference_unit,
                "normalization": "local-percent-relative",
                "normalization_formula": "100 * (dx/du * reference_interval) / max(abs(source), eps)",
                "eps": eps,
                "boundary_behavior": "nan",
                "gap_behavior": "nan-through-gaps",
            },
        )


def calculate(*, data: pd.DataFrame, params: Dict[str, Any], context: Any = None) -> ConstructResult:
    return _Runtime._calculate_angle_result(data=data, params=params)
