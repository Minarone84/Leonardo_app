from __future__ import annotations

from typing import Any, Dict

import numpy as np
import pandas as pd

from leonardo.financial_tools.ft_naming import build_source_token, build_unary_name

from .common import ConstructRuntimeCommon
from .contracts import ConstructResult


class _Runtime(ConstructRuntimeCommon):
    @classmethod
    def _calculate_angle_momentum_result(
        cls,
        *,
        data: pd.DataFrame,
        params: Dict[str, Any],
    ) -> ConstructResult:
        """
        Angle momentum construct.

        Ground truth emitted naming:
        - ``column_ang_mtm_{n}``

        Mathematical meaning
        --------------------
        This construct measures the signed change in angle over ``n`` bars.

        Core idea:
            angle_momentum_n = (angle_t - angle_{t-n}) / n

        This is intentionally *not* percent momentum. Angles are already bounded
        directional-intensity features, so expressing their change as a percent
        of a prior angle is unstable and analytically misleading near zero.

        The emitted value therefore represents average angle change per bar over
        the chosen lag window, in the same angular unit as the input columns.
        """
        angle_columns_param = params.get("angle_columns", params.get("source_columns"))
        angle_columns = cls._normalize_source_columns_param(
            angle_columns_param,
            context="angle_momentum.angle_columns",
        )
        cls._require_columns(data, angle_columns, context="angle_momentum input")

        n = int(params.get("n", 3))
        if n < 1:
            raise ValueError("angle_momentum.n must be >= 1")

        frame = cls._extract_numeric_source_frame(
            data=data,
            source_columns=angle_columns,
            context="angle_momentum input",
        )

        shifted = frame.shift(n)
        mtm = (frame - shifted) / float(n)
        mtm = mtm.replace([np.inf, -np.inf], np.nan)

        if len(mtm) > 0:
            mtm.iloc[:n, :] = np.nan

        line_specs = [
            (
                f"{build_source_token(column)}_ang_mtm_{n}",
                f"{build_source_token(column)}_ang_mtm_{n}",
                mtm[column],
            )
            for column in angle_columns
        ]

        effective_params = dict(params)
        effective_params["angle_columns"] = list(angle_columns)
        effective_params["n"] = n
        if "eps" in effective_params:
            effective_params.pop("eps")

        return cls._multi_line_result(
            name="angle_momentum",
            title="Angle Momentum",
            line_specs=line_specs,
            data=data,
            params=effective_params,
            metadata={
                "construct_mode": "oscillator-pane",
                "construct_kind": "angle_momentum",
                "angle_columns": list(angle_columns),
                "n": n,
                "definition": "(angle_t - angle_t_minus_n) / n",
                "unit_behavior": "same_as_input_angle_per_bar",
                "percent_based": False,
                "boundary_behavior": "nan",
                "gap_behavior": "nan-through-gaps",
            },
        )


def calculate(*, data: pd.DataFrame, params: Dict[str, Any], context: Any = None) -> ConstructResult:
    return _Runtime._calculate_angle_momentum_result(data=data, params=params)
