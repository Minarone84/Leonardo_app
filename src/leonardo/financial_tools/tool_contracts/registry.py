from __future__ import annotations

from typing import Literal

from .contracts import ToolContract
from .manifests.indicators import INDICATOR_CONTRACTS
from .manifests.oscillators import OSCILLATOR_CONTRACTS
from .manifests.constructs import CONSTRUCT_CONTRACTS

ToolFamily = Literal["indicator", "oscillator", "construct"]

ALL_TOOL_CONTRACTS: dict[str, ToolContract] = {
    **INDICATOR_CONTRACTS,
    **OSCILLATOR_CONTRACTS,
    **CONSTRUCT_CONTRACTS,
}

CONTRACTS_BY_FAMILY: dict[str, dict[str, ToolContract]] = {
    "indicator": INDICATOR_CONTRACTS,
    "oscillator": OSCILLATOR_CONTRACTS,
    "construct": CONSTRUCT_CONTRACTS,
}

CONTRACT_ALIASES: dict[str, str] = {}
for _key, _contract in ALL_TOOL_CONTRACTS.items():
    for _alias in _contract.aliases:
        CONTRACT_ALIASES[str(_alias).strip().lower()] = _key


def normalize_tool_key(key: str) -> str:
    raw = str(key).strip().lower()
    return CONTRACT_ALIASES.get(raw, raw)


def get_contract(key: str) -> ToolContract:
    normalized = normalize_tool_key(key)
    try:
        return ALL_TOOL_CONTRACTS[normalized]
    except KeyError as exc:
        raise KeyError(f"Unknown financial tool contract: {key}") from exc


def get_contracts_by_family(family: ToolFamily) -> dict[str, ToolContract]:
    return dict(CONTRACTS_BY_FAMILY[str(family)])


def tool_keys_by_family(family: ToolFamily) -> tuple[str, ...]:
    return tuple(sorted(CONTRACTS_BY_FAMILY[str(family)].keys()))
