from __future__ import annotations

import asyncio
import json
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, List, Sequence

from leonardo.core.audit import make_event
from leonardo.core.context import AppContext
from leonardo.core.registry_keys import SVC_EXCHANGE_REGISTRY, SVC_HISTORICAL_DATASET
from leonardo.data.historical.artifact_metadata_contracts import HistoricalCsvArtifactManifest
from leonardo.data.historical.artifact_metadata_naming import metadata_path_for_csv
from leonardo.data.historical.dataset_service import DatasetId, HistoricalDatasetService
from leonardo.data.historical.paths import HistoricalPaths, default_historical_root
from leonardo.data.historical.store_csv import Candle, CsvOHLCVStore, merge_idempotent
from leonardo.data.historical.validator import HistoricalDatasetValidator
from leonardo.data.naming import MarketId, canonicalize

from leonardo.connection.exchange.base import BaseExchange
from leonardo.connection.exchange.registry import ExchangeRegistry


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
    market: MarketId
    file_path: Path
    total_rows: int
    fetched_rows: int = 0
    downloaded_first_ts_ms: Optional[int] = None
    downloaded_last_ts_ms: Optional[int] = None


@dataclass(frozen=True)
class DownloadBatchRequest:
    """Core-owned request for downloading one symbol across multiple timeframes.

    This keeps the single-timeframe DownloadRequest intact while giving Core a
    batch surface that the future task dialog can call. Batch execution is
    intentionally sequential in this first phase.
    """

    exchange: str
    market_type: str
    symbol: str
    timeframes: Sequence[str]
    start_ms: Optional[int] = None
    end_ms: Optional[int] = None
    limit: Optional[int] = None


@dataclass(frozen=True)
class DownloadBatchResult:
    job_id: str
    requested_timeframes: tuple[str, ...]
    completed_timeframes: tuple[str, ...]
    results: tuple[DownloadResult, ...]


@dataclass(frozen=True)
class DownloadPreflightItem:
    exchange: str
    market_type: str
    symbol: str
    timeframe: str
    mode: str
    path: Path
    local_csv_exists: bool
    local_metadata_exists: bool
    local_metadata_valid: bool
    local_first_ts_ms: Optional[int]
    local_last_ts_ms: Optional[int]
    local_row_count: int
    local_state_issues: tuple[str, ...]
    exchange_oldest_ts_ms: Optional[int]
    exchange_youngest_ts_ms: Optional[int]
    planned_start_ms: Optional[int]
    planned_end_ms: Optional[int]
    expected_bars: Optional[int]
    expected_pages: Optional[int]
    page_limit: int
    up_to_date: bool
    can_download: bool
    reason: Optional[str] = None


@dataclass(frozen=True)
class DownloadPreflightResult:
    exchange: str
    market_type: str
    symbol: str
    timeframes: tuple[str, ...]
    items: tuple[DownloadPreflightItem, ...]

    @property
    def can_download(self) -> bool:
        return all(item.can_download for item in self.items)


@dataclass(frozen=True)
class DownloadPlan:
    """Core-owned single-timeframe OHLCV download plan.

    The GUI may display this plan from audit events, but it must not build or
    reinterpret the download range locally.
    """

    mode: str
    effective_start_ms: Optional[int]
    end_cursor_ms: Optional[int]
    planned_end_ms: Optional[int]
    latest_closed_ts_ms: Optional[int]
    oldest_available_ts_ms: Optional[int]
    page_limit: int
    max_pages: int
    expected_bars: Optional[int]
    expected_pages: Optional[int]
    determinate_progress: bool
    up_to_date: bool = False
    reason: Optional[str] = None
    derived_from_now: bool = False


class HistoricalDownloader:
    REQUEST_TIMEOUT_SECONDS = 30.0
    MAX_REQUEST_ATTEMPTS = 3
    RETRY_BACKOFF_SECONDS = 1.0

    """
    Core-side historical download orchestration.

    Paging strategy (Bybit-friendly):
    - page backwards using end_ms cursor:
        adapter.fetch_ohlcv_historical(end_ms=cursor_end, limit=page_limit, start_ms=effective_start_ms)
    - merge+persist after each page (idempotent)
    - move cursor_end to (oldest_ts - 1)

    Default existing-file policy:
    - If an OHLCV file already exists and no explicit range is supplied, update forward
      from the local last timestamp instead of backfilling older candles.

    Last-bar policy:
    - If (start_ms is None and end_ms is None), drop newest candle if it is not closed.
    """

    def __init__(self, root: Optional[Path] = None) -> None:
        self._paths = HistoricalPaths(root or default_historical_root())
        self._store = CsvOHLCVStore()

    async def run(self, ctx: AppContext, req: DownloadRequest) -> DownloadResult:
        job_id = uuid.uuid4().hex[:12]
        return await self.run_with_job_id(ctx, req, job_id)

    async def run_batch(self, ctx: AppContext, req: DownloadBatchRequest) -> DownloadBatchResult:
        job_id = uuid.uuid4().hex[:12]
        return await self.run_batch_with_job_id(ctx, req, job_id)

    async def preflight(self, ctx: AppContext, req: DownloadRequest) -> DownloadPreflightResult:
        """Build a Core-owned download preflight without writing OHLCV data."""
        batch_req = DownloadBatchRequest(
            exchange=req.exchange,
            market_type=req.market_type,
            symbol=req.symbol,
            timeframes=(req.timeframe,),
            start_ms=req.start_ms,
            end_ms=req.end_ms,
            limit=req.limit,
        )
        return await self.preflight_batch(ctx, batch_req)

    async def preflight_batch(self, ctx: AppContext, req: DownloadBatchRequest) -> DownloadPreflightResult:
        """Build Core-owned preflight items for one symbol across timeframes.

        This method inspects local CSV/metadata state and exchange range
        boundaries, but it does not start a background task and does not write
        candles.csv. The GUI may display this result and ask the user to confirm
        before calling start()/start_batch().
        """
        timeframes = self._normalize_batch_timeframes(req)
        first_market = canonicalize(req.exchange, req.market_type, req.symbol, timeframes[0])
        adapter: Optional[BaseExchange] = None
        items: list[DownloadPreflightItem] = []

        try:
            adapter = await self._get_exchange(ctx, first_market.exchange)
            for timeframe in timeframes:
                item_req = DownloadRequest(
                    exchange=first_market.exchange,
                    market_type=first_market.market_type,
                    symbol=first_market.symbol,
                    timeframe=timeframe,
                    start_ms=req.start_ms,
                    end_ms=req.end_ms,
                    limit=req.limit,
                )
                items.append(await self._preflight_one(adapter=adapter, req=item_req))
        finally:
            if adapter is not None:
                try:
                    await adapter.close()
                except Exception:
                    pass

        return DownloadPreflightResult(
            exchange=first_market.exchange,
            market_type=first_market.market_type,
            symbol=first_market.symbol,
            timeframes=timeframes,
            items=tuple(items),
        )

    async def _preflight_one(self, *, adapter: BaseExchange, req: DownloadRequest) -> DownloadPreflightItem:
        market = canonicalize(req.exchange, req.market_type, req.symbol, req.timeframe)
        ohlcv_dir = self._paths.ensure_ohlcv_dir(market)
        file_path = self._store.file_path(ohlcv_dir)
        local_state = self._store.inspect(file_path, market=market, repair_metadata=False)
        existing = self._store.read(file_path)

        plan = await self._build_plan(
            adapter=adapter,
            market=market,
            req=req,
            existing=existing,
            local_last_ts_ms=local_state.last_ts_ms,
            max_pages=10_000,
        )

        requires_start = req.start_ms is None and req.end_ms is None and not existing
        can_download = True
        reason = plan.reason
        if requires_start and plan.effective_start_ms is None:
            can_download = False
            reason = "oldest_available_timestamp_unresolved"

        return DownloadPreflightItem(
            exchange=market.exchange,
            market_type=market.market_type,
            symbol=market.symbol,
            timeframe=market.timeframe,
            mode=plan.mode,
            path=file_path,
            local_csv_exists=local_state.csv_exists,
            local_metadata_exists=local_state.metadata_exists,
            local_metadata_valid=local_state.metadata_valid,
            local_first_ts_ms=local_state.first_ts_ms,
            local_last_ts_ms=local_state.last_ts_ms,
            local_row_count=local_state.row_count,
            local_state_issues=tuple(local_state.issues),
            exchange_oldest_ts_ms=plan.oldest_available_ts_ms,
            exchange_youngest_ts_ms=plan.latest_closed_ts_ms or plan.planned_end_ms,
            planned_start_ms=plan.effective_start_ms,
            planned_end_ms=plan.planned_end_ms,
            expected_bars=plan.expected_bars,
            expected_pages=plan.expected_pages,
            page_limit=plan.page_limit,
            up_to_date=plan.up_to_date,
            can_download=can_download,
            reason=reason,
        )

    async def run_batch_with_job_id(
        self,
        ctx: AppContext,
        req: DownloadBatchRequest,
        job_id: str,
    ) -> DownloadBatchResult:
        timeframes = self._normalize_batch_timeframes(req)
        first_market = canonicalize(req.exchange, req.market_type, req.symbol, timeframes[0])

        await self._emit_batch(ctx, "download batch started", job_id, extra={
            "exchange": first_market.exchange,
            "market_type": first_market.market_type,
            "symbol": first_market.symbol,
            "timeframes": list(timeframes),
            "total_timeframes": len(timeframes),
            "start_ms": req.start_ms,
            "end_ms": req.end_ms,
            "limit": req.limit,
        })

        results: list[DownloadResult] = []
        completed: list[str] = []

        try:
            for index, timeframe in enumerate(timeframes, start=1):
                await self._emit_batch(ctx, "download batch item started", job_id, extra={
                    "exchange": first_market.exchange,
                    "market_type": first_market.market_type,
                    "symbol": first_market.symbol,
                    "timeframe": timeframe,
                    "timeframe_index": index,
                    "total_timeframes": len(timeframes),
                    "completed_timeframes": list(completed),
                    "remaining_timeframes": list(timeframes[index - 1:]),
                })

                item_req = DownloadRequest(
                    exchange=first_market.exchange,
                    market_type=first_market.market_type,
                    symbol=first_market.symbol,
                    timeframe=timeframe,
                    start_ms=req.start_ms,
                    end_ms=req.end_ms,
                    limit=req.limit,
                )
                result = await self.run_with_job_id(ctx, item_req, job_id)
                results.append(result)
                completed.append(result.market.timeframe)

                await self._emit_batch(ctx, "download batch item completed", job_id, extra={
                    "exchange": first_market.exchange,
                    "market_type": first_market.market_type,
                    "symbol": first_market.symbol,
                    "timeframe": result.market.timeframe,
                    "timeframe_index": index,
                    "total_timeframes": len(timeframes),
                    "completed_timeframes": list(completed),
                    "remaining_timeframes": list(timeframes[index:]),
                    "path": str(result.file_path),
                    "total_rows": result.total_rows,
                })
                await self._emit_batch(ctx, "download batch progress", job_id, extra={
                    "exchange": first_market.exchange,
                    "market_type": first_market.market_type,
                    "symbol": first_market.symbol,
                    "timeframes": list(timeframes),
                    "total_timeframes": len(timeframes),
                    "completed_timeframes": list(completed),
                    "completed_count": len(completed),
                    "remaining_timeframes": list(timeframes[index:]),
                    "progress_ratio": float(len(completed)) / float(len(timeframes)),
                })

            timeframe_results = [self._download_result_summary(result) for result in results]

            await self._emit_batch(ctx, "download batch completed", job_id, extra={
                "exchange": first_market.exchange,
                "market_type": first_market.market_type,
                "symbol": first_market.symbol,
                "timeframes": list(timeframes),
                "total_timeframes": len(timeframes),
                "completed_timeframes": list(completed),
                "completed_count": len(completed),
                "timeframe_results": timeframe_results,
            })

            return DownloadBatchResult(
                job_id=job_id,
                requested_timeframes=timeframes,
                completed_timeframes=tuple(completed),
                results=tuple(results),
            )

        except asyncio.CancelledError:
            await self._emit_batch(ctx, "download batch cancelled", job_id, extra={
                "exchange": first_market.exchange,
                "market_type": first_market.market_type,
                "symbol": first_market.symbol,
                "timeframes": list(timeframes),
                "completed_timeframes": list(completed),
                "completed_count": len(completed),
                "remaining_timeframes": list(timeframes[len(completed):]),
                "reason": "cancelled_by_user",
            })
            raise

        except Exception as e:
            await self._emit_batch(ctx, "download batch failed", job_id, extra={
                "exchange": first_market.exchange,
                "market_type": first_market.market_type,
                "symbol": first_market.symbol,
                "timeframes": list(timeframes),
                "completed_timeframes": list(completed),
                "completed_count": len(completed),
                "failed_timeframe": timeframes[len(completed)] if len(completed) < len(timeframes) else None,
                "remaining_timeframes": list(timeframes[len(completed):]),
                "timeframe_results": [self._download_result_summary(result) for result in results],
                "error": repr(e),
            })
            raise

    def _download_result_summary(self, result: DownloadResult) -> dict[str, object]:
        candles: list[Candle] = []
        try:
            candles = self._store.read(result.file_path)
        except Exception:
            candles = []

        validation_status: str | None = None
        validation_issues: list[str] = []
        validation_issue_count = 0
        validation_warning_count = 0
        validation_error_count = 0
        timeframe_step_ms: int | None = None
        validation_rows = len(candles) if candles else result.total_rows

        try:
            validator = HistoricalDatasetValidator(result.market.timeframe)
            report = validator.validate(result.file_path)
            validation_status = report.status
            validation_rows = report.row_count
            validation_issues = [f"{issue.severity}: {issue.message}" for issue in report.issues]
            validation_issue_count = len(report.issues)
            validation_warning_count = sum(1 for issue in report.issues if issue.severity == "warning")
            validation_error_count = sum(1 for issue in report.issues if issue.severity == "error")
            timeframe_step_ms = validator.step_ms
        except Exception as e:
            validation_status = "error"
            validation_issues = [f"error: validation engine failed during batch finalization: {repr(e)}"]
            validation_issue_count = 1
            validation_error_count = 1

        return {
            "timeframe": result.market.timeframe,
            "status": "completed",
            "path": str(result.file_path),
            "total_rows": len(candles) if candles else result.total_rows,
            "dataframe_first_ts_ms": candles[0].ts_ms if candles else None,
            "dataframe_last_ts_ms": candles[-1].ts_ms if candles else None,
            "validation_status": validation_status,
            "validation_rows": validation_rows,
            "validation_issues": validation_issues,
            "validation_issue_count": validation_issue_count,
            "validation_warning_count": validation_warning_count,
            "validation_error_count": validation_error_count,
            "metadata_validation_status": self._metadata_validation_status(result.file_path),
            "timeframe_step_ms": timeframe_step_ms,
            "timeframe_continuity": "variable" if timeframe_step_ms is None else "fixed",
        }

    async def run_with_job_id(self, ctx: AppContext, req: DownloadRequest, job_id: str) -> DownloadResult:
        return await self._run_with_job_id(ctx, req, job_id, replace_existing_range=False)

    async def run_repair_range_with_job_id(
        self,
        ctx: AppContext,
        req: DownloadRequest,
        job_id: str,
    ) -> DownloadResult:
        """Download a reviewed repair range and replace local rows in that range."""
        return await self._run_with_job_id(ctx, req, job_id, replace_existing_range=True)

    async def _run_with_job_id(
        self,
        ctx: AppContext,
        req: DownloadRequest,
        job_id: str,
        *,
        replace_existing_range: bool,
    ) -> DownloadResult:
        market = canonicalize(req.exchange, req.market_type, req.symbol, req.timeframe)

        ohlcv_dir = self._paths.ensure_ohlcv_dir(market)
        file_path = self._store.file_path(ohlcv_dir)

        adapter: Optional[BaseExchange] = None
        existing: List[Candle] = []
        plan: Optional[DownloadPlan] = None
        try:
            local_state = self._store.inspect(file_path, market=market, repair_metadata=True)

            await self._emit(ctx, "download started", job_id, market, extra={
                "start_ms": req.start_ms,
                "end_ms": req.end_ms,
                "limit": req.limit,
                "path": str(file_path),
                "local_csv_exists": local_state.csv_exists,
                "local_metadata_exists": local_state.metadata_exists,
                "local_metadata_valid": local_state.metadata_valid,
                "local_metadata_repaired": local_state.metadata_repaired,
                "local_first_ts_ms": local_state.first_ts_ms,
                "local_last_ts_ms": local_state.last_ts_ms,
                "local_row_count": local_state.row_count,
                "local_state_source": local_state.source,
                "local_state_issues": list(local_state.issues),
            })

            adapter = await self._get_exchange(ctx, market.exchange)
            existing = self._store.read(file_path)

            max_pages = 10_000
            plan = await self._build_plan(
                adapter=adapter,
                market=market,
                req=req,
                existing=existing,
                local_last_ts_ms=local_state.last_ts_ms,
                max_pages=max_pages,
            )

            await self._emit(ctx, "download plan ready", job_id, market, extra={
                "path": str(file_path),
                "mode": plan.mode,
                "effective_start_ms": plan.effective_start_ms,
                "planned_end_ms": plan.planned_end_ms,
                "latest_closed_ts_ms": plan.latest_closed_ts_ms,
                "oldest_available_ts_ms": plan.oldest_available_ts_ms,
                "page_limit": plan.page_limit,
                "max_pages": plan.max_pages,
                "expected_bars": plan.expected_bars,
                "expected_pages": plan.expected_pages,
                "determinate_progress": plan.determinate_progress,
                "up_to_date": plan.up_to_date,
                "reason": plan.reason,
            })

            if plan.up_to_date:
                await self._emit(ctx, "download completed", job_id, market, extra={
                    "fetched": 0,
                    "downloaded_bars": 0,
                    "total": len(existing),
                    "path": str(file_path),
                    "mode": plan.mode,
                    "reason": plan.reason or "up_to_date",
                    "effective_start_ms": plan.effective_start_ms,
                    "planned_end_ms": plan.planned_end_ms,
                    "latest_closed_ts_ms": plan.latest_closed_ts_ms,
                    "expected_bars": plan.expected_bars,
                    "expected_pages": plan.expected_pages,
                    "progress_ratio": 1.0,
                    "first_ts": existing[0].ts_ms if existing else None,
                    "last_ts": existing[-1].ts_ms if existing else None,
                    "dataframe_first_ts_ms": existing[0].ts_ms if existing else None,
                    "dataframe_last_ts_ms": existing[-1].ts_ms if existing else None,
                    "downloaded_first_ts_ms": None,
                    "downloaded_last_ts_ms": None,
                })
                await self._validate_and_emit(ctx, job_id, market, file_path, len(existing))
                return DownloadResult(
                    job_id=job_id,
                    market=market,
                    file_path=file_path,
                    total_rows=len(existing),
                    fetched_rows=0,
                    downloaded_first_ts_ms=None,
                    downloaded_last_ts_ms=None,
                )

            total_fetched = 0
            downloaded_first_ts_ms: Optional[int] = None
            downloaded_last_ts_ms: Optional[int] = None
            page_no = 0
            last_end_cursor: Optional[int] = None

            page_limit = plan.page_limit
            end_cursor_ms = plan.end_cursor_ms
            effective_start_ms = plan.effective_start_ms
            download_mode = plan.mode
            planned_end_ms = plan.planned_end_ms
            derived_from_now = plan.derived_from_now
            drop_open_last_bar = (req.start_ms is None and req.end_ms is None)
            replace_start_ms = int(effective_start_ms) if replace_existing_range and effective_start_ms is not None else None
            replace_end_ms = int(planned_end_ms) if replace_existing_range and planned_end_ms is not None else None
            if replace_existing_range and (replace_start_ms is None or replace_end_ms is None):
                raise ValueError("repair replacement requires explicit start and end timestamps")
            replacement_rows: List[Candle] = []

            while page_no < plan.max_pages:
                page_no += 1

                if end_cursor_ms is not None and end_cursor_ms < 0:
                    break

                # Infinite-loop guard: end cursor must decrease
                if last_end_cursor is not None and end_cursor_ms is not None and end_cursor_ms >= last_end_cursor:
                    raise RuntimeError(
                        f"paging end cursor did not move backwards (end_cursor_ms={end_cursor_ms}, last_end_cursor={last_end_cursor})"
                    )
                last_end_cursor = end_cursor_ms

                batch = await self._fetch_page_with_retries(
                    ctx=ctx,
                    job_id=job_id,
                    market=market,
                    adapter=adapter,
                    market_type=market.market_type,
                    symbol=market.symbol,
                    timeframe=market.timeframe,
                    start_ms=effective_start_ms,
                    end_ms=end_cursor_ms,
                    limit=page_limit,
                    page_no=page_no,
                    expected_pages=plan.expected_pages,
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
                if replace_existing_range:
                    incoming = [
                        candle
                        for candle in incoming
                        if replace_start_ms is not None
                        and replace_end_ms is not None
                        and replace_start_ms <= candle.ts_ms <= replace_end_ms
                    ]
                if not incoming:
                    break

                total_fetched += len(incoming)

                if replace_existing_range:
                    replacement_rows = merge_idempotent(replacement_rows, incoming)
                else:
                    merged = merge_idempotent(existing, incoming)
                    self._store.write_atomic(file_path, merged, market=market)
                    await self._invalidate_dataset_cache_after_write(ctx, job_id, market)
                    existing = merged

                oldest_ts = incoming[0].ts_ms
                newest_ts = incoming[-1].ts_ms
                downloaded_first_ts_ms = (
                    oldest_ts
                    if downloaded_first_ts_ms is None
                    else min(downloaded_first_ts_ms, oldest_ts)
                )
                downloaded_last_ts_ms = (
                    newest_ts
                    if downloaded_last_ts_ms is None
                    else max(downloaded_last_ts_ms, newest_ts)
                )
                end_cursor_ms = oldest_ts - 1  # move backwards

                await self._emit(ctx, "download progress", job_id, market, extra={
                    "page": page_no,
                    "page_fetched": len(incoming),
                    "downloaded_bars": total_fetched,
                    "total_fetched": total_fetched,
                    "expected_bars": plan.expected_bars,
                    "expected_pages": plan.expected_pages,
                    "progress_ratio": self._progress_ratio(total_fetched, plan.expected_bars),
                    "total_rows": len(existing),
                    "cursor_ms": end_cursor_ms,
                    "oldest_ts": oldest_ts,
                    "newest_ts": newest_ts,
                    "downloaded_first_ts_ms": downloaded_first_ts_ms,
                    "downloaded_last_ts_ms": downloaded_last_ts_ms,
                    "first_ts": existing[0].ts_ms if existing else None,
                    "last_ts": existing[-1].ts_ms if existing else None,
                    "dataframe_first_ts_ms": existing[0].ts_ms if existing else None,
                    "dataframe_last_ts_ms": existing[-1].ts_ms if existing else None,
                    "mode": download_mode,
                    "effective_start_ms": effective_start_ms,
                    "planned_end_ms": planned_end_ms,
                    "next_cursor_ms": end_cursor_ms,
                    "path": str(file_path),
                })

                # Stop if we reached (or crossed) requested/effective start bound
                if effective_start_ms is not None and oldest_ts <= int(effective_start_ms):
                    break

                # If we received fewer than requested, likely hit the beginning of history.
                # Kept disabled because Bybit may return short pages around sparse/edge windows.
                # if len(incoming) < page_limit:
                #     break

            if replace_existing_range and replacement_rows:
                existing = self._replace_existing_range(
                    existing,
                    replacement_rows,
                    start_ms=int(replace_start_ms),
                    end_ms=int(replace_end_ms),
                )
                self._store.write_atomic(file_path, existing, market=market)
                await self._invalidate_dataset_cache_after_write(ctx, job_id, market)

            await self._emit(ctx, "download completed", job_id, market, extra={
                "fetched": total_fetched,
                "downloaded_bars": total_fetched,
                "expected_bars": plan.expected_bars,
                "expected_pages": plan.expected_pages,
                "progress_ratio": self._progress_ratio(total_fetched, plan.expected_bars),
                "total": len(existing),
                "path": str(file_path),
                "mode": download_mode,
                "effective_start_ms": effective_start_ms,
                "planned_end_ms": planned_end_ms,
                "first_ts": existing[0].ts_ms if existing else None,
                "last_ts": existing[-1].ts_ms if existing else None,
                "dataframe_first_ts_ms": existing[0].ts_ms if existing else None,
                "dataframe_last_ts_ms": existing[-1].ts_ms if existing else None,
                "downloaded_first_ts_ms": downloaded_first_ts_ms,
                "downloaded_last_ts_ms": downloaded_last_ts_ms,
            })

            await self._validate_and_emit(ctx, job_id, market, file_path, len(existing))

            return DownloadResult(
                job_id=job_id,
                market=market,
                file_path=file_path,
                total_rows=len(existing),
                fetched_rows=total_fetched,
                downloaded_first_ts_ms=downloaded_first_ts_ms,
                downloaded_last_ts_ms=downloaded_last_ts_ms,
            )

        except asyncio.CancelledError:
            await self._emit(ctx, "download cancelled", job_id, market, extra={
                "path": str(file_path),
                "total": len(existing),
                "mode": plan.mode if plan is not None else None,
                "effective_start_ms": plan.effective_start_ms if plan is not None else None,
                "planned_end_ms": plan.planned_end_ms if plan is not None else None,
                "first_ts": existing[0].ts_ms if existing else None,
                "last_ts": existing[-1].ts_ms if existing else None,
                "dataframe_first_ts_ms": existing[0].ts_ms if existing else None,
                "dataframe_last_ts_ms": existing[-1].ts_ms if existing else None,
                "expected_bars": plan.expected_bars if plan is not None else None,
                "expected_pages": plan.expected_pages if plan is not None else None,
                "reason": "cancelled_by_user",
            })
            raise

        except Exception as e:
            await self._emit(ctx, "download failed", job_id, market, extra={"error": repr(e)})
            raise

        finally:
            if adapter is not None:
                try:
                    await adapter.close()
                except Exception:
                    pass

    async def _invalidate_dataset_cache_after_write(
        self,
        ctx: AppContext,
        job_id: str,
        market: MarketId,
    ) -> None:
        try:
            svc = ctx.get_service(SVC_HISTORICAL_DATASET, HistoricalDatasetService)
        except (AttributeError, KeyError, TypeError) as e:
            await self._emit_cache_invalidation_issue(
                ctx,
                job_id,
                market,
                reason="historical_dataset_service_unavailable",
                error=repr(e),
            )
            return

        try:
            svc.invalidate_dataset_cache(
                DatasetId(
                    exchange=market.exchange,
                    market_type=market.market_type,
                    symbol=market.symbol,
                    timeframe=market.timeframe,
                )
            )
        except Exception as e:
            await self._emit_cache_invalidation_issue(
                ctx,
                job_id,
                market,
                reason="cache_invalidation_failed",
                error=repr(e),
            )

    async def _emit_cache_invalidation_issue(
        self,
        ctx: AppContext,
        job_id: str,
        market: MarketId,
        *,
        reason: str,
        error: str,
    ) -> None:
        try:
            await self._emit(ctx, "download cache invalidation failed", job_id, market, extra={
                "reason": reason,
                "error": error,
            })
        except Exception:
            # Cache invalidation diagnostics must not convert a successful
            # data write into a failed download result.
            return

    def _normalize_batch_timeframes(self, req: DownloadBatchRequest) -> tuple[str, ...]:
        seen: set[str] = set()
        normalized: list[str] = []

        for raw_timeframe in req.timeframes:
            raw = str(raw_timeframe or "").strip()
            if not raw:
                continue
            market = canonicalize(req.exchange, req.market_type, req.symbol, raw)
            timeframe = market.timeframe
            if timeframe in seen:
                continue
            seen.add(timeframe)
            normalized.append(timeframe)

        if not normalized:
            raise ValueError("at least one timeframe is required for a batch download")

        return tuple(normalized)

    async def _build_plan(
        self,
        *,
        adapter: BaseExchange,
        market: MarketId,
        req: DownloadRequest,
        existing: List[Candle],
        local_last_ts_ms: Optional[int],
        max_pages: int,
    ) -> DownloadPlan:
        page_limit = self._effective_page_limit(adapter, market.market_type, req.limit)

        mode = "custom_range" if (req.start_ms is not None or req.end_ms is not None) else "new_download"
        effective_start_ms: Optional[int] = req.start_ms
        latest_closed_ts_ms: Optional[int] = None
        oldest_available_ts_ms: Optional[int] = None
        derived_from_now = False

        if req.end_ms is not None:
            end_cursor_ms: Optional[int] = int(req.end_ms)
        elif existing and req.start_ms is None:
            mode = "update_latest"
            effective_start_ms = local_last_ts_ms if local_last_ts_ms is not None else existing[-1].ts_ms
            latest_closed_ts_ms = await self._latest_closed_ts_ms(adapter, market.timeframe)
            if latest_closed_ts_ms is not None and effective_start_ms is not None:
                end_cursor_ms = latest_closed_ts_ms
            else:
                end_cursor_ms = await self._server_time_ms(adapter)
                derived_from_now = True
        else:
            latest_closed_ts_ms = await self._latest_closed_ts_ms(adapter, market.timeframe)
            end_cursor_ms = latest_closed_ts_ms
            if end_cursor_ms is None:
                end_cursor_ms = await self._server_time_ms(adapter)
                derived_from_now = True

            # New full-history downloads need an exchange-side lower bound so
            # the GUI can show a real planned range and Core can compute
            # determinate progress before downloading.
            if req.start_ms is None and req.end_ms is None:
                oldest_available_ts_ms = await self._oldest_available_ts_ms(adapter, market, page_limit)
                if oldest_available_ts_ms is not None:
                    effective_start_ms = oldest_available_ts_ms

        expected_bars = self._expected_bars(
            start_ms=effective_start_ms,
            end_ms=end_cursor_ms,
            timeframe=market.timeframe,
        )
        expected_pages = self._expected_pages(expected_bars, page_limit)

        up_to_date = False
        reason: Optional[str] = None
        if (
            mode == "update_latest"
            and latest_closed_ts_ms is not None
            and effective_start_ms is not None
            and effective_start_ms >= latest_closed_ts_ms
        ):
            up_to_date = True
            reason = "up_to_date"
            expected_bars = 0
            expected_pages = 0

        return DownloadPlan(
            mode=mode,
            effective_start_ms=effective_start_ms,
            end_cursor_ms=end_cursor_ms,
            planned_end_ms=end_cursor_ms,
            latest_closed_ts_ms=latest_closed_ts_ms,
            oldest_available_ts_ms=oldest_available_ts_ms,
            page_limit=page_limit,
            max_pages=max_pages,
            expected_bars=expected_bars,
            expected_pages=expected_pages,
            determinate_progress=expected_bars is not None,
            up_to_date=up_to_date,
            reason=reason,
            derived_from_now=derived_from_now,
        )

    async def _oldest_available_ts_ms(
        self,
        adapter: BaseExchange,
        market: MarketId,
        page_limit: int,
    ) -> Optional[int]:
        try:
            return await adapter.oldest_historical_ohlcv_ts_ms(
                market=market.market_type,
                symbol=market.symbol,
                timeframe=market.timeframe,
                limit=page_limit,
            )
        except NotImplementedError:
            return None

    def _effective_page_limit(self, adapter: BaseExchange, market_type: str, requested_limit: Optional[int]) -> int:
        adapter_limit = adapter.max_historical_ohlcv_limit(market_type)
        adapter_limit_int = int(adapter_limit) if adapter_limit is not None and adapter_limit > 0 else None

        page_limit = int(requested_limit) if requested_limit is not None else (adapter_limit_int or 500)
        if page_limit < 1:
            page_limit = 1

        if adapter_limit_int is not None:
            page_limit = min(page_limit, adapter_limit_int)

        return page_limit

    def _expected_bars(
        self,
        *,
        start_ms: Optional[int],
        end_ms: Optional[int],
        timeframe: str,
    ) -> Optional[int]:
        if start_ms is None or end_ms is None:
            return None

        duration_ms = self._fixed_timeframe_duration_ms(timeframe)
        if duration_ms is None or duration_ms <= 0:
            return None

        if end_ms < start_ms:
            return 0

        return int((int(end_ms) - int(start_ms)) // duration_ms) + 1

    def _expected_pages(self, expected_bars: Optional[int], page_limit: int) -> Optional[int]:
        if expected_bars is None:
            return None
        if expected_bars <= 0:
            return 0
        return int((expected_bars + page_limit - 1) // page_limit)

    def _progress_ratio(self, downloaded_bars: int, expected_bars: Optional[int]) -> Optional[float]:
        if expected_bars is None or expected_bars <= 0:
            return None
        return min(1.0, max(0.0, float(downloaded_bars) / float(expected_bars)))

    async def _fetch_page_with_retries(
        self,
        *,
        ctx: AppContext,
        job_id: str,
        market: MarketId,
        adapter: BaseExchange,
        market_type: str,
        symbol: str,
        timeframe: str,
        start_ms: Optional[int],
        end_ms: Optional[int],
        limit: int,
        page_no: int,
        expected_pages: Optional[int],
    ) -> Sequence[object]:
        """Fetch one OHLCV page with Core-owned retry/stall audit events."""
        last_error: BaseException | None = None

        for attempt in range(1, self.MAX_REQUEST_ATTEMPTS + 1):
            try:
                return await asyncio.wait_for(
                    adapter.fetch_ohlcv_historical(
                        market=market_type,
                        symbol=symbol,
                        timeframe=timeframe,
                        start_ms=start_ms,
                        end_ms=end_ms,
                        limit=limit,
                    ),
                    timeout=self.REQUEST_TIMEOUT_SECONDS,
                )
            except asyncio.CancelledError:
                raise
            except asyncio.TimeoutError as e:
                last_error = e
                if attempt >= self.MAX_REQUEST_ATTEMPTS:
                    await self._emit(ctx, "download stalled", job_id, market, extra={
                        "reason": "request_timeout",
                        "attempt": attempt,
                        "max_attempts": self.MAX_REQUEST_ATTEMPTS,
                        "timeout_seconds": self.REQUEST_TIMEOUT_SECONDS,
                        "page": page_no,
                        "expected_pages": expected_pages,
                        "cursor_ms": end_ms,
                        "effective_start_ms": start_ms,
                    })
                    raise RuntimeError(
                        "historical download stalled: "
                        f"no response for page {page_no} after {attempt} attempts"
                    ) from e

                await self._emit(ctx, "download retrying", job_id, market, extra={
                    "reason": "request_timeout",
                    "attempt": attempt,
                    "next_attempt": attempt + 1,
                    "max_attempts": self.MAX_REQUEST_ATTEMPTS,
                    "timeout_seconds": self.REQUEST_TIMEOUT_SECONDS,
                    "page": page_no,
                    "expected_pages": expected_pages,
                    "cursor_ms": end_ms,
                    "effective_start_ms": start_ms,
                    "error": repr(e),
                })
            except Exception as e:
                last_error = e
                if attempt >= self.MAX_REQUEST_ATTEMPTS:
                    raise

                await self._emit(ctx, "download retrying", job_id, market, extra={
                    "reason": "request_error",
                    "attempt": attempt,
                    "next_attempt": attempt + 1,
                    "max_attempts": self.MAX_REQUEST_ATTEMPTS,
                    "timeout_seconds": self.REQUEST_TIMEOUT_SECONDS,
                    "page": page_no,
                    "expected_pages": expected_pages,
                    "cursor_ms": end_ms,
                    "effective_start_ms": start_ms,
                    "error": repr(e),
                })

            await asyncio.sleep(self.RETRY_BACKOFF_SECONDS * attempt)

        if last_error is not None:
            raise RuntimeError("historical download request failed") from last_error
        raise RuntimeError("historical download request failed before receiving a page")

    async def _validate_and_emit(
        self,
        ctx: AppContext,
        job_id: str,
        market: MarketId,
        file_path: Path,
        fallback_row_count: int,
    ) -> None:
        # ---- validation phase ----
        try:
            validator = HistoricalDatasetValidator(market.timeframe)
            report = validator.validate(file_path)
            candles = self._store.read(file_path)
            issue_count = len(report.issues)
            warning_count = sum(1 for issue in report.issues if issue.severity == "warning")
            error_count = sum(1 for issue in report.issues if issue.severity == "error")

            await self._emit(ctx, "download validated", job_id, market, extra={
                "status": report.status,
                "row_count": report.row_count,
                "issues": [f"{i.severity}: {i.message}" for i in report.issues],
                "issue_count": issue_count,
                "warning_count": warning_count,
                "error_count": error_count,
                "path": str(file_path),
                "first_ts": candles[0].ts_ms if candles else None,
                "last_ts": candles[-1].ts_ms if candles else None,
                "dataframe_first_ts_ms": candles[0].ts_ms if candles else None,
                "dataframe_last_ts_ms": candles[-1].ts_ms if candles else None,
                "metadata_validation_status": self._metadata_validation_status(file_path),
                "timeframe_step_ms": validator.step_ms,
                "timeframe_continuity": "variable" if validator.step_ms is None else "fixed",
            })
        except Exception as e:
            try:
                candles = self._store.read(file_path)
            except Exception:
                candles = []
            await self._emit(ctx, "download validated", job_id, market, extra={
                "status": "error",
                "row_count": len(candles) if candles else fallback_row_count,
                "issues": [f"error: validation engine failed: {repr(e)}"],
                "issue_count": 1,
                "warning_count": 0,
                "error_count": 1,
                "path": str(file_path),
                "first_ts": candles[0].ts_ms if candles else None,
                "last_ts": candles[-1].ts_ms if candles else None,
                "dataframe_first_ts_ms": candles[0].ts_ms if candles else None,
                "dataframe_last_ts_ms": candles[-1].ts_ms if candles else None,
                "metadata_validation_status": self._metadata_validation_status(file_path),
                "timeframe_step_ms": None,
                "timeframe_continuity": "unknown",
            })

    def _metadata_validation_status(self, file_path: Path) -> str | None:
        metadata_path = metadata_path_for_csv(file_path)
        if not metadata_path.is_file():
            return None
        try:
            with metadata_path.open("r", encoding="utf-8") as handle:
                manifest = HistoricalCsvArtifactManifest.from_dict(json.load(handle))
        except Exception:
            return None
        return manifest.validation.status

    async def _latest_closed_ts_ms(self, adapter: BaseExchange, timeframe: str) -> Optional[int]:
        duration_ms = self._fixed_timeframe_duration_ms(timeframe)
        if duration_ms is None:
            return None
        server_time_ms = await self._server_time_ms(adapter)
        current_open_ms = (server_time_ms // duration_ms) * duration_ms
        return max(0, current_open_ms - duration_ms)

    def _fixed_timeframe_duration_ms(self, timeframe: str) -> Optional[int]:
        tf = (timeframe or "").strip()
        if not tf or tf == "1M" or tf.lower().endswith("w"):
            return None
        tf_lower = tf.lower()
        if tf_lower.endswith("m"):
            return int(tf_lower[:-1]) * 60_000
        if tf_lower.endswith("h"):
            return int(tf_lower[:-1]) * 3_600_000
        if tf_lower.endswith("d"):
            return int(tf_lower[:-1]) * 86_400_000
        return None

    async def _server_time_ms(self, adapter: BaseExchange) -> int:
        server_time = getattr(adapter, "get_server_time_ms", None)
        if callable(server_time):
            return int(await server_time())
        return int(time.time() * 1000)

    async def _get_exchange(self, ctx: AppContext, exchange_name: str) -> BaseExchange:
        try:
            registry = ctx.get_service(SVC_EXCHANGE_REGISTRY, ExchangeRegistry)
            adapter = registry.get(exchange_name)
        except (KeyError, TypeError) as e:
            raise ValueError(f"unsupported exchange: {exchange_name!r}") from e
        await adapter.open()
        return adapter

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

    def _replace_existing_range(
        self,
        existing: Sequence[Candle],
        incoming: Sequence[Candle],
        *,
        start_ms: int,
        end_ms: int,
    ) -> List[Candle]:
        remaining = [candle for candle in existing if not (start_ms <= candle.ts_ms <= end_ms)]
        replacements = [candle for candle in incoming if start_ms <= candle.ts_ms <= end_ms]
        return merge_idempotent(remaining, replacements)

    async def _emit_batch(self, ctx: AppContext, message: str, job_id: str, *, extra: dict) -> None:
        severity = "info"
        if message == "download batch failed":
            severity = "error"
        elif message == "download batch cancelled":
            severity = "warning"

        event = make_event(
            "historical_download",
            severity,
            message,
            ts_ms=int(time.time() * 1000),
            job_id=job_id,
            batch=True,
            **extra,
        )
        await ctx.audit.emit(event)  # type: ignore[attr-defined]

    async def _emit(self, ctx: AppContext, message: str, job_id: str, market: MarketId, *, extra: dict) -> None:
        severity = "info"
        if message == "download failed":
            severity = "error"
        elif message == "download stalled":
            severity = "error"
        elif message == "download retrying":
            severity = "warning"
        elif message == "download cancelled":
            severity = "warning"
        elif message == "download validated":
            status = str(extra.get("status", "")).lower()
            if status == "error":
                severity = "error"
            elif status == "warning":
                severity = "warning"

        event = make_event(
            "historical_download",
            severity,
            message,
            ts_ms=int(time.time() * 1000),
            job_id=job_id,
            exchange=market.exchange,
            market_type=market.market_type,
            symbol=market.symbol,
            timeframe=market.timeframe,
            **extra,
        )
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

    def start_batch(self, ctx: AppContext, req: DownloadBatchRequest) -> str:
        job_id = uuid.uuid4().hex[:12]

        async def _runner():
            await self.run_batch_with_job_id(ctx, req, job_id)

        tasks = getattr(ctx, "tasks", None)

        if tasks is not None and hasattr(tasks, "create"):
            created = tasks.create(name=f"historical_download:{job_id}", coro=_runner())  # type: ignore[attr-defined]
            if asyncio.iscoroutine(created):
                asyncio.create_task(created)
        else:
            asyncio.create_task(_runner())

        return job_id
