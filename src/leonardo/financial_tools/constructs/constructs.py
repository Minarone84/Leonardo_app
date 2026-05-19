from __future__ import annotations

from dataclasses import replace
from typing import Any, Dict

from leonardo.financial_tools.execution_context import ToolExecutionContext, ensure_environment_supported
from leonardo.financial_tools.tool_contracts.registry import get_contract

from .constructs_runtime.contracts import ConstructLine, ConstructRequest, ConstructResult
from .constructs_runtime.common import ConstructRuntimeCommon
from .constructs_runtime import (
    angle,
    angle_momentum,
    braid_instability,
    braids,
    delta,
    derivative,
    dynamic_binning,
    percent_span_angle,
    trap_area,
)


class Constructs(ConstructRuntimeCommon):
    """
    Leonardo construct family bridge.

    This bridge owns the public normalized entrypoint, construct-name aliasing,
    and explicit registry dispatch. Construct computation is isolated in
    ``constructs_runtime`` modules, one module per construct.

    The family-level dataframe normalization remains available through
    ``ConstructRuntimeCommon`` so runtime modules receive the same ordered,
    timeline-safe dataframe contract as the original monolithic implementation.
    """

    _REGISTRY: Dict[str, str] = {
        "dynamic_binning": "_calculate_dynamic_binning_result",
        "derivative": "_calculate_derivative_result",
        "angle": "_calculate_angle_result",
        "braids": "_calculate_braids_result",
        "braid_instability": "_calculate_braid_instability_result",
        "delta": "_calculate_delta_result",
        "trap_area": "_calculate_trap_area_result",
        "percent_span_angle": "_calculate_percent_span_angle_result",
        "angle_momentum": "_calculate_angle_momentum_result",
    }

    _ALIASES: Dict[str, str] = {
        "dynamic_binning_analysis": "dynamic_binning",
        "derivative_analysis": "derivative",
        "angle_analysis": "angle",
        "percent_angle": "percent_span_angle",
        "percent_angle_analysis": "percent_span_angle",
        "percent_span_angle_analysis": "percent_span_angle",
    }

    @classmethod
    def calculate(cls, request: ConstructRequest) -> ConstructResult:
        raw_name = str(request.name).strip().lower()
        if not raw_name:
            raise ValueError("ConstructRequest.name must not be empty.")

        try:
            contract = get_contract(raw_name)
        except KeyError as exc:
            available = ", ".join(sorted(cls._REGISTRY.keys()))
            raise ValueError(f"Unknown construct '{raw_name}'. Available constructs: {available}") from exc
        if contract.family != "construct":
            raise ValueError(f"Financial tool {request.name!r} is not a construct.")

        context = request.context if request.context is not None else ToolExecutionContext()
        ensure_environment_supported(
            tool_key=contract.key,
            environment=context.environment,
            supported_environments=contract.behavior.supported_environments,
        )

        name = contract.key
        method_name = cls._REGISTRY.get(name)
        if method_name is None:
            available = ", ".join(sorted(cls._REGISTRY.keys()))
            raise ValueError(f"Unknown construct '{name}'. Available constructs: {available}")

        data = cls._normalize_input_dataframe(request.data)
        params = dict(request.params or {})

        method = getattr(cls, method_name)
        result = method(data=data, params=params, context=context)
        return replace(
            result,
            metadata={**dict(result.metadata or {}), "environment": context.environment},
        )

    @classmethod
    def _calculate_dynamic_binning_result(cls, *, data, params, context: ToolExecutionContext) -> ConstructResult:
        return dynamic_binning.calculate(data=data, params=params, context=context)

    @classmethod
    def _calculate_derivative_result(cls, *, data, params, context: ToolExecutionContext) -> ConstructResult:
        return derivative.calculate(data=data, params=params, context=context)

    @classmethod
    def _calculate_angle_result(cls, *, data, params, context: ToolExecutionContext) -> ConstructResult:
        return angle.calculate(data=data, params=params, context=context)

    @classmethod
    def _calculate_braids_result(cls, *, data, params, context: ToolExecutionContext) -> ConstructResult:
        return braids.calculate(data=data, params=params, context=context)

    @classmethod
    def _calculate_braid_instability_result(cls, *, data, params, context: ToolExecutionContext) -> ConstructResult:
        return braid_instability.calculate(data=data, params=params, context=context)

    @classmethod
    def _calculate_delta_result(cls, *, data, params, context: ToolExecutionContext) -> ConstructResult:
        return delta.calculate(data=data, params=params, context=context)

    @classmethod
    def _calculate_trap_area_result(cls, *, data, params, context: ToolExecutionContext) -> ConstructResult:
        return trap_area.calculate(data=data, params=params, context=context)

    @classmethod
    def _calculate_percent_span_angle_result(cls, *, data, params, context: ToolExecutionContext) -> ConstructResult:
        return percent_span_angle.calculate(data=data, params=params, context=context)

    @classmethod
    def _calculate_angle_momentum_result(cls, *, data, params, context: ToolExecutionContext) -> ConstructResult:
        return angle_momentum.calculate(data=data, params=params, context=context)


__all__ = [
    "Constructs",
    "ConstructRequest",
    "ConstructLine",
    "ConstructResult",
]
