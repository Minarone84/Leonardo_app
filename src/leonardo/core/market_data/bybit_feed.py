from __future__ import annotations

import asyncio
from typing import Callable

from leonardo.common.chart_messages import ChartPatch, ChartSnapshot
from leonardo.connection.exchange.adapters.bybit import BybitExchange, BybitMarket, Bybit_Timeframe
from leonardo.core.state import StateStore


async def run_bybit_chart_feed(
    *,
    emit_snapshot: Callable[[ChartSnapshot], None],
    emit_patch: Callable[[ChartPatch], None],
    state: StateStore,
    market: BybitMarket,
    symbol: str,
    timeframe: Bybit_Timeframe,
    limit: int = 800,
    testnet: bool = False,
) -> None:
    """Run the Bybit chart feed task and mirror its connection runtime state.

    This feed task remains the operational boundary between the transport
    adapter and the rest of the application. The adapter continues to own
    protocol details, while this function owns the feed-level lifecycle that
    should be visible in runtime state.

    Lifecycle model:
        - register the connection runtime entry
        - mark it as starting before the bootstrap fetch
        - mark it as running once the bootstrap fetch succeeds
        - emit chart snapshots and patches through neutral callbacks while the stream is active
        - mark it as stopped on normal shutdown or cancellation
        - mark it as failed when an unexpected exception aborts the feed

    Notes:
        Connection runtime truth is intentionally tracked at the feed level,
        not inside the exchange adapter. The adapter remains transport-only and
        reusable across runtime contexts. GUI signal emission is supplied by the
        caller as plain callbacks so this Core module does not depend on GUI
        classes.
    """
    # Feed-level runtime identity. This intentionally describes the operational
    # connection being supervised here rather than the lower-level adapter
    # instance used to speak to the venue.
    conn_id = f"bybit:{market}:{symbol}:{timeframe}"

    ex = BybitExchange(testnet=testnet)
    terminal_status: str | None = None

    await state.register_connection(conn_id, kind="market_data", where="feed")
    await state.set_connection_status(conn_id, "starting", where="feed")

    try:
        candles = await ex.fetch_ohlcv(
            market=market,
            symbol=symbol,
            timeframe=timeframe,
            limit=limit,
        )

        # The feed becomes operational only after the bootstrap fetch succeeds.
        await state.set_connection_status(conn_id, "running", where="feed")

        emit_snapshot(
            ChartSnapshot(symbol=symbol, timeframe=timeframe, candles=candles)
        )

        async for op, candle in ex.stream_ohlcv(
            market=market,
            symbol=symbol,
            timeframe=timeframe,
        ):
            emit_patch(
                ChartPatch(symbol=symbol, timeframe=timeframe, op=op, candle=candle)
            )

    except asyncio.CancelledError:
        # Cancellation is an intentional stop path, not a runtime failure.
        terminal_status = "stopped"
        await state.set_connection_status(conn_id, terminal_status, where="feed")
        raise

    except Exception as e:
        # Preserve failure as the current runtime truth. Do not overwrite it in
        # the final cleanup path with a synthetic "stopped" transition.
        terminal_status = "failed"
        await state.set_connection_status(
            conn_id,
            terminal_status,
            where="feed",
            error=str(e),
        )
        raise

    else:
        # A clean stream exit is unusual but still represents a stopped
        # connection from the runtime perspective.
        terminal_status = "stopped"
        await state.set_connection_status(conn_id, terminal_status, where="feed")

    finally:
        # Transport cleanup must always happen, regardless of the terminal
        # runtime outcome recorded above.
        await ex.close()
