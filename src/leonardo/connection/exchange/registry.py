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

    def get(self, name: str) -> BaseExchange:
        key = name.lower().strip()
        try:
            return self._factories[key]()
        except KeyError:
            raise KeyError(f"unknown exchange: {key}. supported={self.list()}") from None