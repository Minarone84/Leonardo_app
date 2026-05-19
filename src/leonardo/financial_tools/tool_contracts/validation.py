from __future__ import annotations

from collections import Counter
from typing import Any

from leonardo.financial_tools.execution_context import ensure_environment_supported

from .registry import (
    ALL_TOOL_CONTRACTS,
    CONTRACT_ALIASES,
    INDICATOR_CONTRACTS,
    OSCILLATOR_CONTRACTS,
    CONSTRUCT_CONTRACTS,
)


class ContractValidationError(ValueError):
    """Raised when the financial-tool contract registry is internally inconsistent."""


def _raise_if(condition: bool, message: str) -> None:
    if condition:
        raise ContractValidationError(message)


def validate_contract_registry() -> None:
    """Validate contract keys, aliases, params, and resolver declarations."""
    keys = list(ALL_TOOL_CONTRACTS)
    counts = Counter(keys)
    duplicate_keys = sorted(key for key, count in counts.items() if count > 1)
    _raise_if(bool(duplicate_keys), f"Duplicate tool contract keys: {duplicate_keys}")

    for key, contract in ALL_TOOL_CONTRACTS.items():
        _raise_if(contract.key != key, f"Contract key mismatch: mapping={key}, contract.key={contract.key}")
        _raise_if(contract.family not in {"indicator", "oscillator", "construct"}, f"Invalid family for {key}: {contract.family}")
        _raise_if(not contract.title, f"Contract {key} must have a title")
        _raise_if(contract.output is None, f"Contract {key} must define an output contract")
        _raise_if(contract.behavior is None, f"Contract {key} must define a behavior contract")
        try:
            ensure_environment_supported(
                tool_key=key,
                environment=contract.behavior.default_environment,
                supported_environments=contract.behavior.supported_environments,
            )
        except ValueError as exc:
            raise ContractValidationError(f"{key} has invalid execution-environment metadata: {exc}") from exc
        _raise_if(not contract.output.naming_resolver, f"Contract {key} must define output.naming_resolver")
        _raise_if(
            contract.output.structure not in {
                "line-series",
                "multi-line-series",
                "levels",
                "bands",
                "state",
                "events",
                "analysis-only",
            },
            f"{key} has invalid output.structure {contract.output.structure}",
        )

        for signal_idx, signal in enumerate(contract.output.signals):
            _raise_if(
                signal.signal_type not in {"signal", "utility"},
                f"{key}.output.signals[{signal_idx}] has invalid signal_type {signal.signal_type}",
            )
            _raise_if(
                signal.value_type not in {"numeric", "categorical", "boolean"},
                f"{key}.output.signals[{signal_idx}] has invalid value_type {signal.value_type}",
            )

        param_names = [param.name for param in contract.params]
        dup_params = sorted(name for name, count in Counter(param_names).items() if count > 1)
        _raise_if(bool(dup_params), f"Contract {key} has duplicate params: {dup_params}")

        for param in contract.params:
            _raise_if(param.dtype not in {"int", "float", "bool", "str"}, f"{key}.{param.name} has invalid dtype {param.dtype}")
            if param.choices:
                _raise_if(param.default is not None and param.default not in param.choices, f"{key}.{param.name} default is outside choices")
            if param.minimum is not None and param.maximum is not None:
                _raise_if(param.minimum > param.maximum, f"{key}.{param.name} minimum exceeds maximum")

    for alias, target in CONTRACT_ALIASES.items():
        _raise_if(target not in ALL_TOOL_CONTRACTS, f"Alias {alias} points at unknown tool {target}")
        _raise_if(alias in ALL_TOOL_CONTRACTS and alias != target, f"Alias {alias} collides with canonical tool key")


def validate_runtime_registry_alignment() -> None:
    """Validate contract keys against the explicit family compute bridges."""
    from leonardo.financial_tools.indicators.indicators import Indicators
    from leonardo.financial_tools.oscillators.oscillators import Oscillators
    from leonardo.financial_tools.constructs.constructs import Constructs

    indicator_runtime = set(Indicators._registry().keys())
    oscillator_runtime = set(Oscillators._registry().keys())
    construct_runtime = set(Constructs._REGISTRY.keys())

    expected_indicator = set(INDICATOR_CONTRACTS.keys())
    expected_oscillator = set(OSCILLATOR_CONTRACTS.keys())
    expected_construct = set(CONSTRUCT_CONTRACTS.keys())

    _raise_if(indicator_runtime != expected_indicator, f"Indicator registry mismatch: runtime={sorted(indicator_runtime)}, contracts={sorted(expected_indicator)}")
    _raise_if(oscillator_runtime != expected_oscillator, f"Oscillator registry mismatch: runtime={sorted(oscillator_runtime)}, contracts={sorted(expected_oscillator)}")
    _raise_if(construct_runtime != expected_construct, f"Construct registry mismatch: runtime={sorted(construct_runtime)}, contracts={sorted(expected_construct)}")


def validate_naming_resolver_coverage() -> None:
    """Validate that each contract's naming resolver can be resolved using default params.

    Dynamic multi-source construct tools may need runtime-selected source params;
    default contract params are used only as a smoke test for resolver availability.
    """
    from leonardo.financial_tools.ft_naming import get_tool_signal_names

    for key, contract in ALL_TOOL_CONTRACTS.items():
        params: dict[str, Any] = contract.default_params()
        if contract.family == "construct" and contract.construct_io is not None:
            binding = contract.construct_io.input_binding

            def ensure_param(name: str, value: Any) -> None:
                if name not in params or str(params.get(name, "")).strip() == "":
                    params[name] = value

            if binding == "unary_source":
                ensure_param("source", "close")
            elif binding == "fast_slow":
                ensure_param("fast", "ema_9")
                ensure_param("slow", "ema_21")
            elif binding == "fast_mid_slow":
                ensure_param("fast", "ema_9")
                ensure_param("mid", "ema_13")
                ensure_param("slow", "ema_21")
            elif binding == "multi_source":
                ensure_param("source_columns", "close")
        resolver_family, _, resolver_key = contract.output.naming_resolver.partition(":")
        _raise_if(not resolver_family or not resolver_key, f"{key} has malformed naming resolver {contract.output.naming_resolver!r}")
        if contract.output.accepts_empty_render_output and contract.family == "construct":
            continue
        try:
            names = get_tool_signal_names(resolver_family, resolver_key, **params)
        except Exception as exc:
            raise ContractValidationError(f"Naming resolver failed for {key}: {exc}") from exc

        if (not contract.output.dynamic_signals) or contract.output.signals:
            _raise_if(
                len(contract.output.signals) != len(names),
                f"{key} output signal metadata count does not match naming output count: "
                f"signals={len(contract.output.signals)}, names={len(names)}",
            )


def validate_all_contracts(*, include_runtime: bool = True, include_naming: bool = True) -> None:
    validate_contract_registry()
    if include_runtime:
        validate_runtime_registry_alignment()
    if include_naming:
        validate_naming_resolver_coverage()
