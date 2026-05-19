from __future__ import annotations

from typing import Any, Dict

import numpy as np
import pandas as pd

from leonardo.financial_tools.ft_naming import build_source_token, build_unary_name

from .common import ConstructRuntimeCommon
from .contracts import ConstructResult


class _Runtime(ConstructRuntimeCommon):
    @classmethod
    def _calculate_trap_area_result(
        cls,
        *,
        data: pd.DataFrame,
        params: Dict[str, Any],
    ) -> ConstructResult:
        """
        Trap area construct.

        Supported input shapes:
        - fast + slow
        - fast + mid + slow

        Emitted columns use actual source names, for example:
        - ``ema_9_ema_13_trapA``
        - ``ema_9_ema_21_trapA``
        - ``ema_13_ema_21_trapA``

        Sign convention:
        Each trap area is computed as faster minus slower, so the trap area is
        positive when the faster signal is above the slower signal.
        """
        role_sources = cls._resolve_fast_mid_slow_sources(
            params=params,
            context="trap_area input",
        )
        frame = cls._extract_numeric_role_frame(
            data=data,
            role_sources=role_sources,
            context="trap_area input",
        )

        zero_eps = float(params.get("zero_eps", 0.0))
        pair_specs = cls._build_trap_area_pairs(role_sources=role_sources)

        line_specs: list[tuple[str, str, pd.Series]] = []
        pair_metadata: list[dict[str, Any]] = []

        for faster_role, slower_role, line_key in pair_specs:
            diff = frame[faster_role] - frame[slower_role]
            seg_id = cls._trap_segments_from(diff, zero_eps=zero_eps)
            trap_values = cls._cum_trap_by_segment(diff, seg_id)

            line_specs.append((line_key, line_key, trap_values))
            pair_metadata.append(
                {
                    "faster_role": faster_role,
                    "slower_role": slower_role,
                    "faster_source": role_sources[faster_role],
                    "slower_source": role_sources[slower_role],
                    "line_key": line_key,
                }
            )

        effective_params = dict(params)
        effective_params["fast"] = role_sources["fast"]
        effective_params["slow"] = role_sources["slow"]
        if "mid" in role_sources:
            effective_params["mid"] = role_sources["mid"]
        effective_params["zero_eps"] = zero_eps

        return cls._multi_line_result(
            name="trap_area",
            title="Trap Area",
            line_specs=line_specs,
            data=data,
            params=effective_params,
            metadata={
                "construct_mode": "oscillator-pane",
                "construct_kind": "trap_area",
                "fast": role_sources["fast"],
                "slow": role_sources["slow"],
                "mid": role_sources.get("mid"),
                "zero_eps": zero_eps,
                "pairs": pair_metadata,
                "boundary_behavior": "segment-start-zero",
                "gap_behavior": "nan-preserved-reset-on-next-valid-bar",
            },
        )


def calculate(*, data: pd.DataFrame, params: Dict[str, Any], context: Any = None) -> ConstructResult:
    return _Runtime._calculate_trap_area_result(data=data, params=params)
