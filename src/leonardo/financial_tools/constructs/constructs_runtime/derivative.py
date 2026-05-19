from __future__ import annotations

from typing import Any, Dict

import numpy as np
import pandas as pd

from leonardo.financial_tools.ft_naming import build_source_token, build_unary_name

from .common import ConstructRuntimeCommon
from .contracts import ConstructResult


class _Runtime(ConstructRuntimeCommon):
    @classmethod
    def _calculate_derivative_result(
        cls,
        *,
        data: pd.DataFrame,
        params: Dict[str, Any],
    ) -> ConstructResult:
        """
        Unary derivative construct.

        Mathematical meaning
        --------------------
        This construct computes a finite-difference approximation of the true
        derivative of a source series with respect to an explicit independent axis.

        Supported derivative orders:
        - order=1 -> first derivative
        - order=2 -> second derivative

        Supported axis modes:
        - axis="bar"  -> derivative with respect to bar/sample position
        - axis="time" -> derivative with respect to elapsed time

        Supported schemes:
        - scheme="central" (default)
        - scheme="forward" (first derivative only)

        Emits:
        - ``source__d1``
        - ``source__d2``
        """
        source_name = cls._resolve_single_source_name(
            params=params,
            context="derivative input",
        )
        source_series = cls._extract_numeric_source_series(
            data=data,
            source_column=source_name,
            context="derivative input",
        )

        order = int(params.get("order", 1))
        if order not in (1, 2):
            raise ValueError("derivative.order must be 1 or 2")

        scheme = str(params.get("scheme", "central")).strip().lower()
        if scheme not in {"central", "forward"}:
            raise ValueError("derivative.scheme must be 'central' or 'forward'")

        axis_params = dict(params)
        axis_params.setdefault("axis", "bar")

        axis_mode, axis_values, axis_unit, time_column = cls._resolve_derivative_axis(
            data=data,
            params=axis_params,
        )
        cls._validate_derivative_axis_monotonic(
            axis_values=axis_values,
            context="derivative axis",
        )

        if order == 1:
            derived = cls._finite_first_derivative(
                values=source_series,
                axis_values=axis_values,
                scheme=scheme,
            )
        else:
            derived = cls._finite_second_derivative(
                values=source_series,
                axis_values=axis_values,
                scheme=scheme,
            )

        effective_params = dict(params)
        effective_params["source"] = source_name
        effective_params["order"] = order
        effective_params["axis"] = axis_mode
        effective_params["scheme"] = scheme
        if axis_mode == "time" and time_column is not None:
            effective_params["time_column"] = time_column
            if "time_unit" in params:
                effective_params["time_unit"] = params["time_unit"]

        suffix = "d1" if order == 1 else "d2"
        line_key = build_unary_name(source_name, suffix)

        return cls._single_line_result(
            name="derivative",
            title="Derivatives",
            line_key=line_key,
            line_title=line_key,
            values=derived,
            data=data,
            params=effective_params,
            metadata={
                "construct_mode": "oscillator-pane",
                "construct_kind": "derivative",
                "source": source_name,
                "order": order,
                "axis": axis_mode,
                "axis_unit": axis_unit,
                "scheme": scheme,
                "time_column": time_column,
                "boundary_behavior": "nan",
                "gap_behavior": "nan-through-gaps",
            },
        )


def calculate(*, data: pd.DataFrame, params: Dict[str, Any], context: Any = None) -> ConstructResult:
    return _Runtime._calculate_derivative_result(data=data, params=params)
