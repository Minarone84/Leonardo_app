from __future__ import annotations

import sys
import types
from concurrent.futures import Future
from types import SimpleNamespace


class _SignalProbe:
    def __init__(self) -> None:
        self.values: list[object] = []

    def emit(self, value: object) -> None:
        self.values.append(value)


def _core_bridge_class(monkeypatch):
    bybit_module = types.ModuleType("leonardo.connection.exchange.adapters.bybit")

    class _BybitExchange:
        name = "bybit"

        def __init__(self, *, testnet: bool = False) -> None:
            self.testnet = testnet

        def supported_markets(self) -> list[str]:
            return ["linear"]

        def supported_timeframes(self, _market_type: str) -> list[str]:
            return ["1h"]

    bybit_module.BybitExchange = _BybitExchange
    bybit_module.BybitMarket = str
    bybit_module.Bybit_Timeframe = str
    monkeypatch.setitem(sys.modules, "leonardo.connection.exchange.adapters.bybit", bybit_module)

    from leonardo.gui.core_bridge import CoreBridge

    return CoreBridge


def test_stale_realtime_future_completion_does_not_clear_active_future(monkeypatch) -> None:
    CoreBridge = _core_bridge_class(monkeypatch)

    stale_future: Future[object] = Future()
    active_future: Future[object] = Future()
    stale_future.set_result(None)

    bridge = SimpleNamespace(
        _realtime_future=active_future,
        status_changed=_SignalProbe(),
        realtime_state_changed=_SignalProbe(),
    )

    CoreBridge._on_realtime_feed_done(bridge, stale_future)

    assert bridge._realtime_future is active_future
    assert bridge.status_changed.values == []
    assert bridge.realtime_state_changed.values == []
