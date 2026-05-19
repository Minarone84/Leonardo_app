from __future__ import annotations

from typing import Any, Dict

import numpy as np
import pandas as pd

from leonardo.financial_tools.ft_naming import build_source_token, build_unary_name

from .common import ConstructRuntimeCommon
from .contracts import ConstructResult


class _Runtime(ConstructRuntimeCommon):
    @classmethod
    def _calculate_braid_instability_result(
        cls,
        *,
        data: pd.DataFrame,
        params: Dict[str, Any],
    ) -> ConstructResult:
        """
        Braid instability construct.

        Purpose inside the braids pipeline
        ----------------------------------
        This construct is part of the broader braids pipeline and exists to
        describe the *temporal stability* of braid structure.

        The raw ``braids`` construct already tells us:
        - the ambient ordering state
        - the braid width
        - the braid compression

        Those outputs describe the *current structure* of the braid at a given
        bar, but they do not tell us whether that structure has been stable or
        whether it has been changing frequently.

        This construct fills that gap.

        Core meaning
        ------------
        Let ``S_t`` be the braid ambient state at bar ``t``.

        We define a state-change indicator:

            change_t = 1  if S_t != S_{t-1}
                     = 0  if S_t == S_{t-1}

        Then, over a rolling window of size ``n``:

            braid_instability_n = mean(change_t over the last n bars)

        So the output is a normalized instability score in the range [0, 1]:

        - 0.0 means the braid state has been completely stable over the window
        - 1.0 means the braid state has changed on every bar in the window

        Why this matters
        ----------------
        Two market situations may produce the same instantaneous ambient state
        but have very different structural behavior:

        - a clean, persistent ordering regime
        - a noisy, indecisive regime with frequent reordering

        Without an instability descriptor, these two situations are not
        distinguishable from the braid state alone.

        This construct therefore provides an explicit temporal descriptor of
        braid regime stability.

        Tie and NaN handling
        --------------------
        This construct recomputes the *raw* braid ambient state internally
        using the same ordering logic as the braid construct before any
        optional carry-forward policy would be applied.

        Important design decision:
        - instability measures actual structural changes
        - it does NOT use carried ambient state memory as the basis of the
          calculation
        - ties / invalid rows produce NaN in the raw state and therefore break
          the local change comparison

        This is intentional. The goal here is to measure real ordering churn,
        not a memory-smoothed version of it.

        Boundary behavior
        -----------------
        - the first bar is NaN because there is no previous state
        - the first ``n`` bars are NaN because a full instability window is not
          yet available
        - any comparison involving NaN states remains NaN

        Expected interpretation
        -----------------------
        Low instability values usually suggest:
        - persistent ordering
        - regime continuity
        - cleaner structural separation

        High instability values usually suggest:
        - frequent reordering
        - braid churn
        - compression / ambiguity / indecision
        - structurally noisy local behavior

        Emitted column
        --------------
        Let ``base`` be the braid token built from fast / mid / slow.

        This construct emits:
        - ``base_inst_{n}``

        Example:
        - ``ema_9_ema_13_ema_21_inst_5``

        Notes for future pipeline integration
        -------------------------------------
        This construct is intended to be consumed together with:
        - ambient braid state
        - braid width
        - braid compression

        It should not be interpreted in isolation as a full braid descriptor.
        It is the temporal-stability layer of the braids pipeline.
        """
        role_sources = cls._resolve_fast_mid_slow_sources(
            params=params,
            context="braid_instability input",
        )
        if set(role_sources.keys()) != {"fast", "mid", "slow"}:
            raise ValueError("braid_instability requires exactly fast, mid, and slow sources")

        frame = cls._extract_numeric_role_frame(
            data=data,
            role_sources=role_sources,
            context="braid_instability input",
        )

        n = int(params.get("n", 5))
        if n < 1:
            raise ValueError("braid_instability.n must be >= 1")

        # Recompute the raw ambient braid state directly from the role frame.
        # We intentionally do not use tie_policy carry-forward here because this
        # construct is meant to measure actual ordering churn, not memory-smoothed
        # state persistence.
        ambient_raw = cls._raw_braid_state_series(frame)

        # A state-change event is recorded when two consecutive valid ambient
        # states differ. If either side is NaN, the comparison is undefined and
        # remains NaN.
        prev = ambient_raw.shift(1)
        change = (ambient_raw != prev).astype("float64")
        change[(ambient_raw.isna()) | (prev.isna())] = np.nan

        # Rolling mean of state-change events gives a normalized instability
        # score in [0, 1], provided the window is fully valid.
        instability = change.rolling(window=n, min_periods=n).mean().astype("float64")

        if len(instability) > 0:
            instability.iloc[:n] = np.nan

        fast_name = role_sources["fast"]
        mid_name = role_sources["mid"]
        slow_name = role_sources["slow"]
        base_key = "_".join(
            (
                build_source_token(fast_name),
                build_source_token(mid_name),
                build_source_token(slow_name),
            )
        )
        line_key = f"{base_key}_inst_{n}"

        effective_params = dict(params)
        effective_params["fast"] = fast_name
        effective_params["mid"] = mid_name
        effective_params["slow"] = slow_name
        effective_params["n"] = n

        return cls._single_line_result(
            name="braid_instability",
            title="Braid Instability",
            line_key=line_key,
            line_title=line_key,
            values=instability,
            data=data,
            params=effective_params,
            metadata={
                "construct_mode": "oscillator-pane",
                "construct_kind": "braid_instability",
                "fast": fast_name,
                "mid": mid_name,
                "slow": slow_name,
                "n": n,
                "definition": "rolling mean of raw braid state changes over n bars",
                "range": "[0, 1]",
                "uses_carried_state": False,
                "boundary_behavior": "nan",
                "gap_behavior": "nan-through-gaps",
            },
        )


def calculate(*, data: pd.DataFrame, params: Dict[str, Any], context: Any = None) -> ConstructResult:
    return _Runtime._calculate_braid_instability_result(data=data, params=params)
