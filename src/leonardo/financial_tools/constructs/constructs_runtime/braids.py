from __future__ import annotations

from typing import Any, Dict

import numpy as np
import pandas as pd

from leonardo.financial_tools.ft_naming import build_source_token, build_unary_name

from .common import ConstructRuntimeCommon
from .contracts import ConstructResult


class _Runtime(ConstructRuntimeCommon):
    @classmethod
    def _calculate_braids_result(
        cls,
        *,
        data: pd.DataFrame,
        params: Dict[str, Any],
    ) -> ConstructResult:
        """
        Braid structural construct.

        This construct intentionally preserves the raw ambient ordering state while
        also emitting the two core geometric companions required to interpret that
        state honestly:

        - ambient state: categorical ordering identity
        - braid width: total braid envelope spread
        - braid compression: minimum pairwise separation

        Emitted columns
        ---------------
        Let ``base`` be the braid token:
        - ``base``                 -> ambient state (1..6, or NaN on ties / invalid rows)
        - ``base_width``           -> max(fast, mid, slow) - min(fast, mid, slow)
        - ``base_compression``     -> min(|fast-mid|, |fast-slow|, |mid-slow|)

        Ambient state values
        --------------------
        - 1: slow > mid > fast
        - 2: slow > fast > mid
        - 3: fast > slow > mid
        - 4: fast > mid > slow
        - 5: mid  > fast > slow
        - 6: mid  > slow > fast

        Tie handling
        ------------
        Ties produce NaN in the raw ambient state. With ``tie_policy="carry"``,
        the most recent non-null ambient state is forward-filled. With ``"drop"``,
        ties remain NaN.

        Important:
        - width and compression are always computed directly from the numeric rows
        - carry policy affects only the ambient categorical state
        """
        role_sources = cls._resolve_fast_mid_slow_sources(
            params=params,
            context="braids input",
        )
        if set(role_sources.keys()) != {"fast", "mid", "slow"}:
            raise ValueError("braids requires exactly fast, mid, and slow sources")

        frame = cls._extract_numeric_role_frame(
            data=data,
            role_sources=role_sources,
            context="braids input",
        )

        tie_policy = str(params.get("tie_policy", "carry")).strip().lower()
        if tie_policy not in {"carry", "drop"}:
            raise ValueError("braids.tie_policy must be 'carry' or 'drop'")

        ambient_raw = cls._raw_braid_state_series(frame)
        ambient = ambient_raw.ffill() if tie_policy == "carry" else ambient_raw.copy()

        braid_width = (frame.max(axis=1) - frame.min(axis=1)).astype("float64")

        pair_gaps = pd.DataFrame(
            {
                "fast_mid_gap": (frame["fast"] - frame["mid"]).abs(),
                "fast_slow_gap": (frame["fast"] - frame["slow"]).abs(),
                "mid_slow_gap": (frame["mid"] - frame["slow"]).abs(),
            },
            index=frame.index,
        ).astype("float64")
        braid_compression = pair_gaps.min(axis=1).astype("float64")

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

        line_specs = [
            (base_key, base_key, ambient),
            (f"{base_key}_width", f"{base_key}_width", braid_width),
            (f"{base_key}_compression", f"{base_key}_compression", braid_compression),
        ]

        effective_params = dict(params)
        effective_params["fast"] = fast_name
        effective_params["mid"] = mid_name
        effective_params["slow"] = slow_name
        effective_params["tie_policy"] = tie_policy

        return cls._multi_line_result(
            name="braids",
            title="Braids",
            line_specs=line_specs,
            data=data,
            params=effective_params,
            metadata={
                "construct_mode": "oscillator-pane",
                "construct_kind": "braids",
                "fast": fast_name,
                "mid": mid_name,
                "slow": slow_name,
                "tie_policy": tie_policy,
                "outputs": ["ambient_state", "braid_width", "braid_compression"],
                "ambient_state_map": {
                    "1": "slow > mid > fast",
                    "2": "slow > fast > mid",
                    "3": "fast > slow > mid",
                    "4": "fast > mid > slow",
                    "5": "mid > fast > slow",
                    "6": "mid > slow > fast",
                },
                "width_formula": "max(fast, mid, slow) - min(fast, mid, slow)",
                "compression_formula": "min(abs(fast-mid), abs(fast-slow), abs(mid-slow))",
                "ambient_gap_policy": "nan-on-ties-before-optional-carry",
            },
        )


def calculate(*, data: pd.DataFrame, params: Dict[str, Any], context: Any = None) -> ConstructResult:
    return _Runtime._calculate_braids_result(data=data, params=params)
