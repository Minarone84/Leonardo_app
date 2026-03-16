from __future__ import annotations

import asyncio
from typing import Optional

from leonardo.common.market_types import BybitMarket, ChartPatch, ChartSnapshot, Timeframe
from leonardo.gui.core_bridge import CoreBridge
from leonardo.connection.exchange.adapters.bybit import BybitExchange


async def run_bybit_chart_feed(
    *,
    bridge: CoreBridge,
    market: BybitMarket,
    symbol: str,
    timeframe: Timeframe,
    limit: int = 800,
    testnet: bool = False,
) -> None:
    """
    Core-thread task:
    1) fetch history -> emit ChartSnapshot
    2) stream live -> emit ChartPatch until cancelled
    """
    ex = BybitExchange(testnet=testnet)
    try:
        candles = await ex.fetch_ohlcv(market=market, symbol=symbol, timeframe=timeframe, limit=limit)
        bridge.chart_snapshot.emit(ChartSnapshot(symbol=symbol, timeframe=timeframe, candles=candles))

        async for op, candle in ex.stream_ohlcv(market=market, symbol=symbol, timeframe=timeframe):
            bridge.chart_patch.emit(ChartPatch(symbol=symbol, timeframe=timeframe, op=op, candle=candle))

    finally:
        await ex.close()