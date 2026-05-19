from __future__ import annotations

from typing import Any, Dict

import numpy as np
import pandas as pd

from leonardo.financial_tools.ft_naming import build_source_token, build_unary_name

from .common import ConstructRuntimeCommon
from .contracts import ConstructResult


class _Runtime(ConstructRuntimeCommon):
    @classmethod
    def _calculate_delta_result(
        cls,
        *,
        data: pd.DataFrame,
        params: Dict[str, Any],
    ) -> ConstructResult:
        """
        Delta construct.

        Purpose
        -------
        Delta is the primitive signed relational construct for two series.

        In Leonardo, delta is intentionally directional and always anchored as:

            delta = fast - slow

        This fixed directional rule is a design choice. It provides a stable
        semantic pole for all delta features:
        - positive values mean the fast/reference-leading source is above the slow source
        - negative values mean the fast source is below the slow source

        This construct is therefore not a generic symmetric distance measure.
        It is a directed relational feature.

        Supported modes
        ---------------
        1. Absolute mode
           ``mode="abs"``

           Formula:
               delta_abs = fast - slow

           Meaning:
               raw signed separation in source units.

        2. Percent-relative mode
           ``mode="pct"``

           Formula:
               delta_pct = ((fast - slow) / max(abs(slow), eps)) * 100

           Meaning:
               signed relative separation of ``fast`` from ``slow``, expressed
               as a percent of the slow reference magnitude.

        Why percent mode exists
        -----------------------
        Absolute deltas are useful but scale-dependent. A raw difference of 5
        means very different things when comparing:
        - 105 vs 100
        - 5005 vs 5000

        Percent-relative delta preserves the same directional meaning while
        making the magnitude more comparable across differently scaled series.

        Why the denominator is ``slow``
        -------------------------------
        Delta in this construct family is interpreted as the position of
        ``fast`` relative to ``slow``.

        Therefore, in percent mode, ``slow`` is the reference baseline and the
        denominator is:

            max(abs(slow), eps)

        This keeps the sign logic aligned with the absolute delta and avoids
        denominator blow-ups near zero.

        Input shapes
        ------------
        1. Single pair:
           - ``fast``
           - ``slow``

        2. Multiple pairs:
           - ``pairs=[{"fast": "...", "slow": "..."}, ...]``

        Each pair emits one output line.

        NaN handling
        ------------
        Delta is computed row-wise on the original timeline.

        If either source is NaN at a row:
        - output is NaN for that row

        There is:
        - no gap skipping
        - no interpolation
        - no timeline compression

        Emitted naming
        --------------
        Absolute mode:
            ``fast_slow_delta``

        Percent mode:
            ``fast_slow_delta_pct``

        Examples:
        - ``ema_9_ema_21_delta``
        - ``ema_9_ema_21_delta_pct``

        Metadata contract
        -----------------
        Metadata explicitly records:
        - mode
        - pair definitions
        - percent semantics when applicable
        - epsilon stabilization rule when applicable

        Notes
        -----
        This construct is intentionally minimal.

        It does not include:
        - momentum
        - dynamic binning
        - label assignment
        - persistence helpers

        Those belong to higher-level analysis pipelines built on top of delta,
        not inside the primitive construct itself.
        """
        pairs = cls._resolve_delta_pairs(
            params=params,
            context="delta input",
        )

        mode = str(params.get("mode", "abs")).strip().lower()
        if mode not in {"abs", "pct"}:
            raise ValueError("delta.mode must be 'abs' or 'pct'")

        eps = float(params.get("eps", 1e-12))
        if mode == "pct":
            if (not np.isfinite(eps)) or (eps <= 0.0):
                raise ValueError("delta.eps must be a finite value > 0 when mode='pct'")

        required_columns = []
        for pair in pairs:
            required_columns.extend([pair["fast"], pair["slow"]])
        cls._require_columns(data, required_columns, context="delta input")

        line_specs: list[tuple[str, str, pd.Series]] = []
        pair_metadata: list[dict[str, Any]] = []

        for pair in pairs:
            fast_name = pair["fast"]
            slow_name = pair["slow"]

            fast_series = cls._extract_numeric_source_series(
                data=data,
                source_column=fast_name,
                context=f"delta input ({fast_name}, {slow_name})",
            ).astype("float64")
            slow_series = cls._extract_numeric_source_series(
                data=data,
                source_column=slow_name,
                context=f"delta input ({fast_name}, {slow_name})",
            ).astype("float64")

            delta_abs = (fast_series - slow_series).astype("float64")

            if mode == "abs":
                values = delta_abs
                suffix = "delta"
            else:
                denom = slow_series.abs().clip(lower=eps)
                values = ((delta_abs / denom) * 100.0).replace([np.inf, -np.inf], np.nan).astype("float64")
                suffix = "delta_pct"

            line_key = f"{build_source_token(fast_name)}_{build_source_token(slow_name)}_{suffix}"
            line_specs.append((line_key, line_key, values))
            pair_metadata.append(
                {
                    "fast": fast_name,
                    "slow": slow_name,
                    "line_key": line_key,
                }
            )

        effective_params = dict(params)
        effective_params["pairs"] = [{"fast": p["fast"], "slow": p["slow"]} for p in pairs]
        effective_params["mode"] = mode
        effective_params.pop("fast", None)
        effective_params.pop("slow", None)
        if mode == "pct":
            effective_params["eps"] = eps
        else:
            effective_params.pop("eps", None)

        metadata = {
            "construct_mode": "oscillator-pane",
            "construct_kind": "delta",
            "mode": mode,
            "pairs": pair_metadata,
            "direction_rule": "fast_minus_slow",
            "boundary_behavior": "nan",
            "gap_behavior": "nan-through-gaps",
            "percent_based": mode == "pct",
        }
        if mode == "pct":
            metadata.update(
                {
                    "reference": "slow",
                    "denominator_formula": "max(abs(slow), eps)",
                    "eps": eps,
                }
            )

        return cls._multi_line_result(
            name="delta",
            title="Delta",
            line_specs=line_specs,
            data=data,
            params=effective_params,
            metadata=metadata,
        )


def calculate(*, data: pd.DataFrame, params: Dict[str, Any], context: Any = None) -> ConstructResult:
    return _Runtime._calculate_delta_result(data=data, params=params)
