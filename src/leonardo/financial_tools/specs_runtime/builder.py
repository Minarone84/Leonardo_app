from __future__ import annotations

from typing import Mapping

from leonardo.financial_tools.tool_contracts.contracts import ToolContract
from .models import ToolSpec
from .registry import get_tool_spec


def build_spec_from_contract(contract: ToolContract) -> ToolSpec:
    """Return the current ToolSpec projection for a ToolContract.

    The registry preserves exact historical ToolSpec definitions in this
    transition phase. This function is the explicit bridge point for the
    next phase where specs become fully generated from contracts.
    """
    return get_tool_spec(contract.key)


def build_specs_from_contracts(contracts: Mapping[str, ToolContract]) -> dict[str, ToolSpec]:
    return {key: build_spec_from_contract(contract) for key, contract in contracts.items()}
