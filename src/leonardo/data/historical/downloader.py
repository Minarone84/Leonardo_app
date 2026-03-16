# leonardo/data/historical/downloader.py
from __future__ import annotations

import time
import uuid
import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, List, Sequence

from leonardo.core.context import AppContext
from leonardo.data.naming import CanonicalMarket, canonicalize
from leonardo.data.historical.paths import HistoricalPaths, default_historical_root
from leonardo.data.historical.store_csv import Candle, CsvOHLCVStore, merge_idempotent

from leonardo.connection.exchange.adapters.bybit import BybitExchange
from leonardo.connection.exchange.base import BaseExchange


@dataclass(frozen=True)
class DownloadRequest:
    exchange: str
    market_type: str
    symbol: str
    timeframe: str
    start_ms: Optional[int] = None
    end_ms: Optional[int] = None
    limit: Optional[int] = None


@dataclass(frozen=True)
class DownloadResult:
    job_id: str
    market: CanonicalMarket
    file_path: Path
    total_rows: int


class HistoricalDownloader:
    """
    Core-side historical download orchestration.

    Paging strategy (Bybit-friendly):
    - page backwards using end_ms cursor:
        adapter.fetch_ohlcv_historical(end_ms=cursor_end, limit=page_limit, start_ms=req.start_ms)
    - merge+persist after each page (idempotent)
    - move cursor_end to (oldest_ts - 1)

    Last-bar policy:
    - If (start_ms is None and end_ms is None), drop newest candle if it is not closed.
    """

    def __init__(self, root: Optional[Path] = None) -> None:
        self._paths = HistoricalPaths(root or default_historical_root())
        self._store = CsvOHLCVStore()

    async def run(self, ctx: AppContext, req: DownloadRequest) -> DownloadResult:
        job_id = uuid.uuid4().hex[:12]
        return await self.run_with_job_id(ctx, req, job_id)

    async def run_with_job_id(self, ctx: AppContext, req: DownloadRequest, job_id: str) -> DownloadResult:
        market = canonicalize(req.exchange, req.market_type, req.symbol, req.timeframe)

        ohlcv_dir = self._paths.ensure_ohlcv_dir(market)
        file_path = self._store.file_path(ohlcv_dir)

        await self._emit(ctx, "download started", job_id, market, extra={
            "start_ms": req.start_ms,
            "end_ms": req.end_ms,
            "limit": req.limit,
            "path": str(file_path),
        })

        adapter: Optional[BaseExchange] = None
        try:
            adapter = await self._get_exchange(ctx, market.exchange)

            existing = self._store.read(file_path)

            page_limit = int(req.limit) if req.limit is not None else 500
            if page_limit < 1:
                page_limit = 1

            max_pages = 10_000

            total_fetched = 0
            page_no = 0
            last_end_cursor: Optional[int] = None

            # Decide initial end cursor:
            # - If user set end_ms, respect it.
            # - Else if file exists and user didn't set start_ms, extend backwards from oldest stored candle.
            # - Else use server time (prefer exchange server time when available).
            end_cursor_ms: Optional[int]
            derived_from_now = False
            if req.end_ms is not None:
                end_cursor_ms = int(req.end_ms)
            elif existing and req.start_ms is None:
                end_cursor_ms = max(0, existing[0].ts_ms - 1)
            else:
                end_cursor_ms = await self._server_time_ms(adapter)
                derived_from_now = True

            drop_open_last_bar = (req.start_ms is None and req.end_ms is None)

            while page_no < max_pages:
                page_no += 1

                if end_cursor_ms is not None and end_cursor_ms < 0:
                    break

                # Infinite-loop guard: end cursor must decrease
                if last_end_cursor is not None and end_cursor_ms is not None and end_cursor_ms >= last_end_cursor:
                    raise RuntimeError(
                        f"paging end cursor did not move backwards (end_cursor_ms={end_cursor_ms}, last_end_cursor={last_end_cursor})"
                    )
                last_end_cursor = end_cursor_ms

                batch = await adapter.fetch_ohlcv_historical(
                    market=market.market_type if market.market_type != "options" else "option",
                    symbol=market.symbol,
                    timeframe=market.timeframe,
                    start_ms=req.start_ms,
                    end_ms=end_cursor_ms,
                    limit=page_limit,
                )

                if not batch:
                    break

                # Drop newest still-forming candle only when user did NOT request a range,
                # and only when we are actually fetching "up to now" (not resuming older history).
                # (Bybit marks closePrice as last traded price when candle not closed).
                if drop_open_last_bar and derived_from_now and page_no == 1:
                    newest_src = batch[-1]  # adapter returns chronological; newest is last
                    is_closed = bool(getattr(newest_src, "is_closed", True))
                    if not is_closed:
                        batch = batch[:-1]

                incoming = self._to_store_candles(batch)
                if not incoming:
                    break

                total_fetched += len(incoming)

                merged = merge_idempotent(existing, incoming)
                self._store.write_atomic(file_path, merged)
                existing = merged

                oldest_ts = incoming[0].ts_ms
                end_cursor_ms = oldest_ts - 1  # move backwards

                await self._emit(ctx, "download progress", job_id, market, extra={
                    "page": page_no,
                    "page_fetched": len(incoming),
                    "total_fetched": total_fetched,
                    "total_rows": len(existing),
                    "cursor_ms": end_cursor_ms,
                    "oldest_ts": oldest_ts,
                    "path": str(file_path),
                })

                # Stop if we reached (or crossed) requested start bound
                if req.start_ms is not None and oldest_ts <= int(req.start_ms):
                    break

                # If we received fewer than requested, likely hit the beginning of history
                #if len(incoming) < page_limit:
                #    break

            await self._emit(ctx, "download completed", job_id, market, extra={
                "fetched": total_fetched,
                "total": len(existing),
                "path": str(file_path),
            })

            return DownloadResult(
                job_id=job_id,
                market=market,
                file_path=file_path,
                total_rows=len(existing),
            )

        except Exception as e:
            await self._emit(ctx, "download failed", job_id, market, extra={"error": repr(e)})
            raise

        finally:
            if adapter is not None:
                try:
                    await adapter.close()
                except Exception:
                    pass

    async def _server_time_ms(self, adapter: BaseExchange) -> int:
        # Prefer exchange server time when available (Bybit provides /v5/market/time).
        if isinstance(adapter, BybitExchange) and hasattr(adapter, "get_server_time_ms"):
            return await adapter.get_server_time_ms()
        return int(time.time() * 1000)

    async def _get_exchange(self, ctx: AppContext, exchange_name: str) -> BaseExchange:
        ex = exchange_name.strip().lower()
        if ex == "bybit":
            adapter = BybitExchange(testnet=False)
            await adapter.open()
            return adapter
        raise ValueError(f"unsupported exchange: {exchange_name!r}")

    def _to_store_candles(self, seq: Sequence[object]) -> List[Candle]:
        out: List[Candle] = []
        for c in seq:
            ts_ms = int(getattr(c, "ts_ms"))
            out.append(
                Candle(
                    ts_ms=ts_ms,
                    open=float(getattr(c, "open")),
                    high=float(getattr(c, "high")),
                    low=float(getattr(c, "low")),
                    close=float(getattr(c, "close")),
                    volume=float(getattr(c, "volume")),
                )
            )
        out.sort(key=lambda x: x.ts_ms)
        return out

    async def _emit(self, ctx: AppContext, message: str, job_id: str, market: CanonicalMarket, *, extra: dict) -> None:
        event = {
            "event_type": "historical_download",
            "severity": "info" if "failed" not in message else "error",
            "message": message,
            "ts_ms": int(time.time() * 1000),
            "fields": {
                "job_id": job_id,
                "exchange": market.exchange,
                "market_type": market.market_type,
                "symbol": market.symbol,
                "timeframe": market.timeframe,
                **extra,
            },
        }
        await ctx.audit.emit(event)  # type: ignore[attr-defined]

    def start(self, ctx: AppContext, req: DownloadRequest) -> str:
        job_id = uuid.uuid4().hex[:12]

        async def _runner():
            await self.run_with_job_id(ctx, req, job_id)

        tasks = getattr(ctx, "tasks", None)

        if tasks is not None and hasattr(tasks, "create"):
            created = tasks.create(name=f"historical_download:{job_id}", coro=_runner())  # type: ignore[attr-defined]
            if asyncio.iscoroutine(created):
                asyncio.create_task(created)
        else:
            asyncio.create_task(_runner())

        return job_id