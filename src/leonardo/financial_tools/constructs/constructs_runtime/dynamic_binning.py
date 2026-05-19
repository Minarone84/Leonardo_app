from __future__ import annotations

from typing import Any, Dict

import numpy as np
import pandas as pd

from leonardo.financial_tools.ft_naming import build_source_token, build_unary_name

from .common import ConstructRuntimeCommon
from .contracts import ConstructResult
from ..DynamicBinner import DynamicBinner
from ..VariationAnalyzer import VariationAnalyzer


class _Runtime(ConstructRuntimeCommon):
    @classmethod
    def _calculate_dynamic_binning_result(
        cls,
        *,
        data: pd.DataFrame,
        params: Dict[str, Any],
    ) -> ConstructResult:
        """
        Non-visual dynamic binning construct.

        This remains the one construct that intentionally orchestrates the
        external VariationAnalyzer + DynamicBinner pair.
        """
        source_columns = cls._normalize_source_columns_param(
            params.get("source_columns"),
            context="dynamic_binning.source_columns",
        )
        source_frame = cls._extract_numeric_source_frame(
            data=data,
            source_columns=source_columns,
            context="dynamic_binning input",
        )

        window = int(params.get("window", 50))
        multiplier = float(params.get("multiplier", 1.0))
        floor_quantile = float(params.get("floor_quantile", 0.05))
        per_series_min = params.get("per_series_min")
        per_series_max = params.get("per_series_max")
        global_min_step = float(params.get("global_min_step", 1e-12))
        quantile_method = str(params.get("quantile_method", "nearest"))

        analyzer = VariationAnalyzer(
            source_frame,
            window=window,
            multiplier=multiplier,
            floor_quantile=floor_quantile,
            per_series_min=per_series_min,
            per_series_max=per_series_max,
            global_min_step=global_min_step,
            quantile_method=quantile_method,
        ).fit()

        n_bins = int(params.get("n_bins", 15))
        boundary_eps = float(params.get("boundary_eps", DynamicBinner._DEFAULT_BOUNDARY_EPS))

        binner = DynamicBinner(
            source_frame,
            min_steps=dict(analyzer.steps or {}),
            n_bins=n_bins,
            boundary_eps=boundary_eps,
        ).fit()

        labeled_df = binner.transform(source_frame)

        effective_params = {
            "source_columns": list(source_columns),
            "window": window,
            "multiplier": multiplier,
            "floor_quantile": floor_quantile,
            "per_series_min": dict(per_series_min or {}),
            "per_series_max": dict(per_series_max or {}),
            "global_min_step": global_min_step,
            "quantile_method": quantile_method,
            "n_bins": n_bins,
            "boundary_eps": boundary_eps,
        }

        variation_diagnostics_df = analyzer.table.copy() if analyzer.table is not None else pd.DataFrame()

        metadata = {
            "construct_mode": "non-visual",
            "construct_kind": "dynamic_binning",
            "source_columns": list(source_columns),
            "row_count": int(len(labeled_df)),
            "steps": {
                key: float(value)
                for key, value in (analyzer.steps or {}).items()
            },
            "variation_diagnostics": cls._records_from_dataframe(
                variation_diagnostics_df.reset_index()
            ),
            "binning_artifact": cls._json_ready_value(binner.export_artifact()),
            "labeled_rows": cls._records_from_dataframe(
                labeled_df.reset_index(drop=False)
            ),
        }

        return cls._empty_result(
            name="dynamic_binning",
            title="Dynamic Binning",
            data=data,
            params=effective_params,
            metadata=metadata,
        )


def calculate(*, data: pd.DataFrame, params: Dict[str, Any], context: Any = None) -> ConstructResult:
    return _Runtime._calculate_dynamic_binning_result(data=data, params=params)
