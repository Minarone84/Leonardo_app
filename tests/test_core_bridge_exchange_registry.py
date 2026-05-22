from __future__ import annotations

from leonardo.connection.exchange.registry import ExchangeRegistry
from leonardo.core.registry_keys import SVC_EXCHANGE_REGISTRY
from leonardo.gui.core_bridge import CoreBridge


class _FakeExchange:
    def supported_markets(self) -> set[str]:
        return {"linear", "spot"}

    def supported_timeframes(self, market: str) -> set[str]:
        assert market == "linear"
        return {"1d", "30m", "1h"}


class _Context:
    def __init__(self, registry: ExchangeRegistry) -> None:
        self.registry = registry
        self.lookups: list[tuple[str, type[object]]] = []

    def get_service(self, name: str, t: type[object]) -> object:
        self.lookups.append((name, t))
        assert name == SVC_EXCHANGE_REGISTRY
        assert t is ExchangeRegistry
        return self.registry


class _Bridge:
    _exchange_registry = CoreBridge._exchange_registry
    _timeframe_sort_key = staticmethod(CoreBridge._timeframe_sort_key)

    def __init__(self, registry: ExchangeRegistry) -> None:
        self.context = _Context(registry)


def test_core_bridge_exchange_capabilities_use_registered_registry() -> None:
    registry = ExchangeRegistry()
    registry.register("bybit", _FakeExchange)
    bridge = _Bridge(registry)

    assert CoreBridge.supported_exchange_names(bridge) == ["bybit"]
    assert CoreBridge.supported_exchange_markets(bridge, "bybit") == ["linear", "spot"]
    assert CoreBridge.supported_exchange_timeframes(bridge, "bybit", "linear") == ["30m", "1h", "1d"]

    assert bridge.context.lookups == [
        (SVC_EXCHANGE_REGISTRY, ExchangeRegistry),
        (SVC_EXCHANGE_REGISTRY, ExchangeRegistry),
        (SVC_EXCHANGE_REGISTRY, ExchangeRegistry),
    ]
