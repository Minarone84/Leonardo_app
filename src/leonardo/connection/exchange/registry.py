from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict

from .base import BaseExchange

ExchangeFactory = Callable[[], BaseExchange]


@dataclass
class ExchangeRegistry:
    _factories: Dict[str, ExchangeFactory]

    def __init__(self) -> None:
        self._factories = {}

    def register(self, name: str, factory: ExchangeFactory) -> None:
        key = name.lower().strip()
        if key in self._factories:
            raise ValueError(f"exchange already registered: {key}")
        self._factories[key] = factory

    def list(self) -> list[str]:
        return sorted(self._factories.keys())

    def supported_exchange_names(self) -> list[str]:
        """Return registered exchange names in stable display order."""
        return self.list()

    def supported_markets(self, name: str) -> list[str]:
        """Return market capabilities reported by a fresh adapter instance."""
        return sorted(str(market) for market in self.get(name).supported_markets())

    def supported_timeframes(self, name: str, market: str) -> list[str]:
        """Return timeframe capabilities reported by a fresh adapter instance."""
        return sorted(str(timeframe) for timeframe in self.get(name).supported_timeframes(market))

    def get(self, name: str) -> BaseExchange:
        key = name.lower().strip()
        try:
            return self._factories[key]()
        except KeyError:
            raise KeyError(f"unknown exchange: {key}. supported={self.list()}") from None


def build_default_exchange_registry() -> ExchangeRegistry:
    """Build the application default exchange registry.

    The registry stores factories rather than live adapter instances. Adapter
    creation remains local to the caller that needs transport/API access.
    """
    registry = ExchangeRegistry()

    def _bybit_factory() -> BaseExchange:
        from leonardo.connection.exchange.adapters.bybit import BybitExchange

        return BybitExchange(testnet=False)

    registry.register("bybit", _bybit_factory)
    return registry
