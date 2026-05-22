from __future__ import annotations

import sys
import types

import pytest

from leonardo.connection.exchange.registry import ExchangeRegistry, build_default_exchange_registry


class _FakeBybitExchange:
    name = "bybit"

    def __init__(self, *, testnet: bool = False) -> None:
        self.testnet = testnet


def test_exchange_registry_lists_and_creates_registered_adapter() -> None:
    registry = ExchangeRegistry()
    registry.register("bybit", lambda: _FakeBybitExchange(testnet=False))

    assert registry.supported_exchange_names() == ["bybit"]
    assert isinstance(registry.get("BYBIT"), _FakeBybitExchange)


def test_exchange_registry_unsupported_exchange_fails_clearly() -> None:
    registry = ExchangeRegistry()

    with pytest.raises(KeyError, match="unknown exchange: kraken"):
        registry.get("kraken")


def test_default_exchange_registry_registers_lazy_bybit_factory(monkeypatch) -> None:
    bybit_module = types.ModuleType("leonardo.connection.exchange.adapters.bybit")
    bybit_module.BybitExchange = _FakeBybitExchange
    monkeypatch.setitem(sys.modules, "leonardo.connection.exchange.adapters.bybit", bybit_module)

    registry = build_default_exchange_registry()

    assert registry.supported_exchange_names() == ["bybit"]
    adapter = registry.get("bybit")
    assert isinstance(adapter, _FakeBybitExchange)
    assert adapter.testnet is False
