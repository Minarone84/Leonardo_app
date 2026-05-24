from __future__ import annotations

import asyncio
from concurrent.futures import Future
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional, Sequence, TypeVar

from PySide6.QtCore import QObject, Qt, QTimer, Signal, Slot

from leonardo.connection.exchange.registry import ExchangeRegistry
from leonardo.core.context import AppContext
from leonardo.core.registry_keys import (
    SVC_EXCHANGE_REGISTRY,
    SVC_HISTORICAL_DATASET,
    SVC_HISTORICAL_OHLCV_MAINTENANCE,
)
from leonardo.data.historical.dataset_service import DatasetId, HistoricalDatasetService
from leonardo.data.historical.downloader import DownloadBatchRequest, DownloadRequest, HistoricalDownloader
from leonardo.data.historical.ohlcv_maintenance import HistoricalOhlcvMaintenanceService
from leonardo.gui.core_runner import CoreRunner

T = TypeVar("T")


class _GuiDispatcher(QObject):
    """Dispatch callables onto the Qt GUI thread."""

    _invoke = Signal(object, object, object)  # fn, args(tuple), kwargs(dict)

    def __init__(self) -> None:
        super().__init__()
        self._invoke.connect(self._on_invoke, Qt.QueuedConnection)

    @Slot(object, object, object)
    def _on_invoke(self, fn_obj: object, args_obj: object, kwargs_obj: object) -> None:
        """Execute a queued callable on the GUI thread."""
        fn = fn_obj  # type: ignore[assignment]
        args = args_obj  # type: ignore[assignment]
        kwargs = kwargs_obj  # type: ignore[assignment]
        try:
            fn(*args, **kwargs)  # type: ignore[misc]
        except Exception as e:
            # Keep the GUI alive and avoid raising across the Qt signal boundary.
            print(f"[CoreBridge.gui_call] GUI callable raised: {e!r}")


class CoreBridge(QObject):
    """GUI-facing seam for Core runtime access and realtime feed control.

    Responsibilities:
        - start/stop the CoreRunner thread
        - submit coroutines onto the Core event loop
        - marshal callables back onto the Qt GUI thread
        - expose a narrow explicit realtime control boundary for the GUI

    Notes:
        Realtime feed lifecycle ownership is intentionally kept here rather than
        in MainWindow. The window may request start/stop actions, but it should
        not own feed futures or orchestrate feed execution directly.
    """

    status_changed = Signal(str)

    # payload: ChartSnapshot / ChartPatch from leonardo.common.chart_messages
    chart_snapshot = Signal(object)
    chart_patch = Signal(object)

    # explicit realtime lifecycle signal for GUI consumers
    realtime_state_changed = Signal(bool)

    def __init__(self) -> None:
        super().__init__()
        self._runner: Optional[CoreRunner] = None
        self._gui = _GuiDispatcher()
        self._realtime_future: Optional[Future[object]] = None

        # Ensure dispatcher lives in the GUI thread even if CoreBridge is
        # created before the main event loop fully settles.
        QTimer.singleShot(0, self._ensure_gui_thread)

    @Slot()
    def _ensure_gui_thread(self) -> None:
        """Move the dispatcher to the thread that owns this bridge."""
        self._gui.moveToThread(self.thread())

    @property
    def is_running(self) -> bool:
        """Return whether the core runner thread is currently active."""
        return self._runner is not None

    def start(self) -> None:
        """Start the Core runtime thread if it is not already running."""
        if self._runner is not None:
            return
        self.status_changed.emit("Starting core...")
        self._runner = CoreRunner(on_status=self.status_changed.emit)
        self._runner.start()
        self.status_changed.emit("Ready")

    def stop(self) -> None:
        """Stop the realtime feed if needed, then stop the Core runtime."""
        if self._runner is None:
            return

        # Stop GUI-controlled realtime first so runtime truth and connection
        # cleanup paths are given a chance to execute before the runner dies.
        self.stop_realtime_feed()

        self.status_changed.emit("Stopping core...")
        self._runner.stop()
        self._runner = None
        self.status_changed.emit("Stopped")

    def submit(self, coro: Awaitable[T]) -> Future[T]:
        """Schedule a coroutine on the CoreRunner event loop."""
        if self._runner is None:
            raise RuntimeError("Core not started")
        return self._runner.submit(coro)  # type: ignore[arg-type]

    def gui_call(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
        """Queue ``fn(*args, **kwargs)`` onto the Qt GUI thread."""
        self._gui._invoke.emit(fn, args, kwargs)

    def try_get_audit_snapshot(self) -> Optional[dict[str, Any]]:
        """Return a lightweight snapshot of in-memory audit events, if any."""
        if self._runner is None:
            return None
        snap = self._runner.get_audit_snapshot()
        if snap is None:
            return None
        events = getattr(snap, "events", [])
        return {"count": getattr(snap, "count", len(events)), "events": list(events)}

    @property
    def context(self) -> AppContext:
        """Return the active AppContext exposed by the CoreRunner."""
        if self._runner is None or self._runner.context is None:
            raise RuntimeError("Core not started or context not available")
        return self._runner.context

    def _historical_dataset_service(self) -> HistoricalDatasetService:
        """Return the Core-owned historical dataset service for catalog access."""
        return self.context.get_service(SVC_HISTORICAL_DATASET, HistoricalDatasetService)

    def _historical_ohlcv_maintenance_service(self) -> HistoricalOhlcvMaintenanceService:
        """Return the Core-owned OHLCV maintenance service."""
        return self.context.get_service(
            SVC_HISTORICAL_OHLCV_MAINTENANCE,
            HistoricalOhlcvMaintenanceService,
        )

    def _exchange_registry(self) -> ExchangeRegistry:
        """Return the Core-owned exchange registry capability provider."""
        return self.context.get_service(SVC_EXCHANGE_REGISTRY, ExchangeRegistry)

    @staticmethod
    def _historical_download_root(ctx: AppContext) -> Path:
        """Return the configured historical storage root for download commands."""
        return Path(ctx.config.runtime.data_dir) / "historical"

    def list_historical_dataset_exchanges(self) -> list[str]:
        """Return exchanges that have at least one Core-loadable OHLCV dataset."""
        return self._historical_dataset_service().list_dataset_exchanges()

    def list_historical_dataset_market_types(self, exchange: str) -> list[str]:
        """Return market types available in the Core-owned historical dataset catalog."""
        return self._historical_dataset_service().list_dataset_market_types(exchange)

    def list_historical_dataset_symbols(self, exchange: str, market_type: str) -> list[str]:
        """Return symbols available in the Core-owned historical dataset catalog."""
        return self._historical_dataset_service().list_dataset_symbols(exchange, market_type)

    def list_historical_dataset_timeframes(
        self,
        exchange: str,
        market_type: str,
        symbol: str,
    ) -> list[str]:
        """Return timeframes available in the Core-owned historical dataset catalog."""
        return self._historical_dataset_service().list_dataset_timeframes(
            exchange,
            market_type,
            symbol,
        )

    def historical_dataset_exists(
        self,
        *,
        exchange: str,
        market_type: str,
        symbol: str,
        timeframe: str,
    ) -> bool:
        """Return whether Core can identify the exact OHLCV dataset value file."""
        dataset_id = DatasetId(exchange, market_type, symbol, timeframe)
        return self._historical_dataset_service().has_dataset(dataset_id)

    def list_historical_ohlcv_datasets(self) -> Future[object]:
        """Return read-only OHLCV dataset summaries through the Core boundary."""
        service = self._historical_ohlcv_maintenance_service()

        async def _list() -> object:
            return await asyncio.to_thread(service.list_ohlcv_datasets)

        return self.submit(_list())

    def inspect_historical_ohlcv_dataset(
        self,
        *,
        exchange: str,
        market_type: str,
        symbol: str,
        timeframe: str,
    ) -> Future[object]:
        """Inspect one OHLCV dataset without mutating stored data."""
        service = self._historical_ohlcv_maintenance_service()
        dataset_id = DatasetId(exchange, market_type, symbol, timeframe)

        async def _inspect() -> object:
            return await asyncio.to_thread(service.inspect_ohlcv, dataset_id)

        return self.submit(_inspect())

    def validate_historical_ohlcv_dataset(
        self,
        *,
        exchange: str,
        market_type: str,
        symbol: str,
        timeframe: str,
    ) -> Future[object]:
        """Validate one OHLCV dataset without mutating stored data."""
        service = self._historical_ohlcv_maintenance_service()
        dataset_id = DatasetId(exchange, market_type, symbol, timeframe)

        async def _validate() -> object:
            return await asyncio.to_thread(service.validate_ohlcv, dataset_id)

        return self.submit(_validate())

    def plan_historical_ohlcv_repair(
        self,
        *,
        exchange: str,
        market_type: str,
        symbol: str,
        timeframe: str,
    ) -> Future[object]:
        """Plan OHLCV repair ranges through the Core/data maintenance boundary."""
        service = self._historical_ohlcv_maintenance_service()
        dataset_id = DatasetId(exchange, market_type, symbol, timeframe)

        async def _plan() -> object:
            return await asyncio.to_thread(service.plan_ohlcv_repair, dataset_id)

        return self.submit(_plan())

    def execute_historical_ohlcv_repair(
        self,
        *,
        exchange: str,
        market_type: str,
        symbol: str,
        timeframe: str,
        plan: object,
    ) -> Future[object]:
        """Execute a reviewed OHLCV repair plan through the Core/data boundary."""
        ctx = self.context
        service = self._historical_ohlcv_maintenance_service()
        dataset_id = DatasetId(exchange, market_type, symbol, timeframe)

        async def _execute() -> object:
            return await service.execute_ohlcv_repair(ctx, dataset_id, plan)  # type: ignore[arg-type]

        return self.submit(_execute())

    def plan_historical_ohlcv_source_correction(
        self,
        *,
        exchange: str,
        market_type: str,
        symbol: str,
        timeframe: str,
    ) -> Future[object]:
        """Plan OHLCV source correction through the Core/data maintenance boundary."""
        service = self._historical_ohlcv_maintenance_service()
        dataset_id = DatasetId(exchange, market_type, symbol, timeframe)

        async def _plan() -> object:
            return await asyncio.to_thread(service.plan_ohlcv_source_correction, dataset_id)

        return self.submit(_plan())

    def execute_historical_ohlcv_source_correction(
        self,
        *,
        exchange: str,
        market_type: str,
        symbol: str,
        timeframe: str,
        plan: object,
    ) -> Future[object]:
        """Execute a reviewed OHLCV source-correction plan through the Core/data boundary."""
        service = self._historical_ohlcv_maintenance_service()
        dataset_id = DatasetId(exchange, market_type, symbol, timeframe)

        async def _execute() -> object:
            return await asyncio.to_thread(
                service.execute_ohlcv_source_correction,
                dataset_id,
                plan,
            )

        return self.submit(_execute())

    def delete_historical_ohlcv_dataset(
        self,
        *,
        exchange: str,
        market_type: str,
        symbol: str,
        timeframe: str,
    ) -> Future[object]:
        """Delete one OHLCV dataset through the Core/data maintenance boundary."""
        service = self._historical_ohlcv_maintenance_service()
        dataset_id = DatasetId(exchange, market_type, symbol, timeframe)

        async def _delete() -> object:
            return await asyncio.to_thread(service.delete_ohlcv, dataset_id)

        return self.submit(_delete())

    def rebuild_historical_ohlcv_metadata(
        self,
        *,
        exchange: str,
        market_type: str,
        symbol: str,
        timeframe: str,
    ) -> Future[object]:
        """Rebuild one OHLCV metadata sidecar through the Core/data boundary."""
        service = self._historical_ohlcv_maintenance_service()
        dataset_id = DatasetId(exchange, market_type, symbol, timeframe)

        async def _rebuild() -> object:
            return await asyncio.to_thread(service.rebuild_ohlcv_metadata, dataset_id)

        return self.submit(_rebuild())

    def cancel_historical_download(self, job_id: str) -> Future[bool]:
        """Request cancellation of one active historical download task.

        Historical downloads are Core-owned tasks named by HistoricalDownloader
        as ``historical_download:{job_id}``. The GUI may request cancellation,
        but Core/TaskManager owns the actual task state transition and audit.
        """
        normalized_job_id = str(job_id or "").strip()
        if not normalized_job_id:
            fut: Future[bool] = Future()
            fut.set_result(False)
            return fut

        ctx = self.context
        task_name = f"historical_download:{normalized_job_id}"

        async def _cancel() -> bool:
            tasks = getattr(ctx, "tasks", None)
            cancel = getattr(tasks, "cancel", None)
            if not callable(cancel):
                return False
            return bool(cancel(task_name))

        return self.submit(_cancel())

    def preflight_historical_download(
        self,
        *,
        exchange: str,
        market_type: str,
        symbol: str,
        timeframe: str,
        start_ms: Optional[int] = None,
        end_ms: Optional[int] = None,
        limit: Optional[int] = None,
    ) -> Future[object]:
        """Build a Core-owned single-timeframe historical download preflight."""
        ctx = self.context

        async def _preflight() -> object:
            historical_root = CoreBridge._historical_download_root(ctx)
            downloader = HistoricalDownloader(root=historical_root)
            return await downloader.preflight(
                ctx,
                DownloadRequest(
                    exchange=exchange,
                    market_type=market_type,
                    symbol=symbol,
                    timeframe=timeframe,
                    start_ms=start_ms,
                    end_ms=end_ms,
                    limit=limit,
                ),
            )

        return self.submit(_preflight())

    def preflight_historical_download_batch(
        self,
        *,
        exchange: str,
        market_type: str,
        symbol: str,
        timeframes: Sequence[str],
        start_ms: Optional[int] = None,
        end_ms: Optional[int] = None,
        limit: Optional[int] = None,
    ) -> Future[object]:
        """Build a Core-owned multi-timeframe historical download preflight."""
        ctx = self.context
        requested_timeframes = tuple(timeframes)

        async def _preflight() -> object:
            historical_root = CoreBridge._historical_download_root(ctx)
            downloader = HistoricalDownloader(root=historical_root)
            return await downloader.preflight_batch(
                ctx,
                DownloadBatchRequest(
                    exchange=exchange,
                    market_type=market_type,
                    symbol=symbol,
                    timeframes=requested_timeframes,
                    start_ms=start_ms,
                    end_ms=end_ms,
                    limit=limit,
                ),
            )

        return self.submit(_preflight())

    def start_historical_download(
        self,
        *,
        exchange: str,
        market_type: str,
        symbol: str,
        timeframe: str,
        start_ms: Optional[int] = None,
        end_ms: Optional[int] = None,
        limit: Optional[int] = None,
    ) -> Future[dict[str, object]]:
        """Submit a Core-owned single-timeframe historical download task."""
        ctx = self.context

        async def _start() -> dict[str, object]:
            historical_root = CoreBridge._historical_download_root(ctx)
            downloader = HistoricalDownloader(root=historical_root)
            job_id = downloader.start(
                ctx,
                DownloadRequest(
                    exchange=exchange,
                    market_type=market_type,
                    symbol=symbol,
                    timeframe=timeframe,
                    start_ms=start_ms,
                    end_ms=end_ms,
                    limit=limit,
                ),
            )
            return {"job_id": job_id, "timeframes": (timeframe,)}

        return self.submit(_start())

    def start_historical_download_batch(
        self,
        *,
        exchange: str,
        market_type: str,
        symbol: str,
        timeframes: Sequence[str],
        start_ms: Optional[int] = None,
        end_ms: Optional[int] = None,
        limit: Optional[int] = None,
    ) -> Future[dict[str, object]]:
        """Submit a Core-owned multi-timeframe historical download task."""
        ctx = self.context
        requested_timeframes = tuple(timeframes)

        async def _start() -> dict[str, object]:
            historical_root = CoreBridge._historical_download_root(ctx)
            downloader = HistoricalDownloader(root=historical_root)
            job_id = downloader.start_batch(
                ctx,
                DownloadBatchRequest(
                    exchange=exchange,
                    market_type=market_type,
                    symbol=symbol,
                    timeframes=requested_timeframes,
                    start_ms=start_ms,
                    end_ms=end_ms,
                    limit=limit,
                ),
            )
            return {"job_id": job_id, "timeframes": requested_timeframes}

        return self.submit(_start())

    def supported_exchange_names(self) -> list[str]:
        """Return exchanges available through the current GUI/Core bridge."""
        return self._exchange_registry().supported_exchange_names()

    def supported_exchange_markets(self, exchange: str) -> list[str]:
        """Return canonical market types reported by the selected exchange adapter."""
        return self._exchange_registry().supported_markets(exchange)

    def supported_exchange_timeframes(self, exchange: str, market_type: str) -> list[str]:
        """Return canonical timeframes reported by the selected exchange adapter."""
        values = self._exchange_registry().supported_timeframes(exchange, market_type)
        return sorted((str(timeframe) for timeframe in values), key=self._timeframe_sort_key)

    @staticmethod
    def _timeframe_sort_key(timeframe: str) -> tuple[int, int, str]:
        text = str(timeframe).strip()
        if len(text) < 2:
            return (99, 0, text)
        unit = text[-1]
        value_text = text[:-1]
        unit_order = {"m": 0, "h": 1, "d": 2, "w": 3, "M": 4}.get(unit, 99)
        try:
            value = int(value_text)
        except Exception:
            value = 0
        return (unit_order, value, text)

    def is_realtime_running(self) -> bool:
        """Return whether a realtime feed future is currently active."""
        fut = self._realtime_future
        return fut is not None and not fut.done()

    def start_realtime_feed(
        self,
        *,
        market: str = "linear",
        symbol: str = "BTCUSDT",
        timeframe: str = "30m",
        limit: int = 200,
        testnet: bool = False,
    ) -> None:
        """Start the GUI-requested realtime feed through the Core boundary.

        The bridge owns the feed future and the runtime flag transition so the
        GUI does not directly orchestrate background feed execution.
        """
        if self.is_realtime_running():
            self.status_changed.emit("Realtime already running")
            self.realtime_state_changed.emit(True)
            return

        from leonardo.core.market_data.bybit_feed import run_bybit_chart_feed

        ctx = self.context
        self.submit(ctx.state.set_realtime_active(True, where="gui"))
        self.status_changed.emit("Streaming")

        self._realtime_future = self.submit(
            run_bybit_chart_feed(
                emit_snapshot=self.chart_snapshot.emit,
                emit_patch=self.chart_patch.emit,
                state=ctx.state,
                market=market,
                symbol=symbol,
                timeframe=timeframe,
                limit=limit,
                testnet=testnet,
            )
        )
        self._realtime_future.add_done_callback(self._on_realtime_feed_done)
        self.realtime_state_changed.emit(True)

    def stop_realtime_feed(self) -> None:
        """Stop the current GUI-requested realtime feed if one is active."""
        if self._runner is None:
            self._realtime_future = None
            self.realtime_state_changed.emit(False)
            return

        try:
            self.submit(self.context.state.set_realtime_active(False, where="gui"))
        except Exception:
            # The core may already be coming down. Best-effort only.
            pass

        fut = self._realtime_future
        if fut is not None and not fut.done():
            fut.cancel()
        self._realtime_future = None

        self.status_changed.emit("Ready")
        self.realtime_state_changed.emit(False)

    def _on_realtime_feed_done(self, fut: Future[object]) -> None:
        """Handle realtime feed termination and keep GUI state honest.
    
        Cancellation is treated as a normal stop path. Unexpected failures are
        surfaced through the status signal and the runtime realtime flag is
        forced back to False so the GUI does not remain stuck in a fake
        streaming state.
        """
        if fut is not self._realtime_future:
            return

        self._realtime_future = None
    
        # --- Proper cancellation handling ---
        if fut.cancelled():
            self.status_changed.emit("Ready")
            self.realtime_state_changed.emit(False)
            return
    
        try:
            exc = fut.exception()
        except Exception as e:
            print("FAILED TO READ FEED FUTURE:", repr(e))
            self.status_changed.emit("Feed status unavailable")
            self.realtime_state_changed.emit(False)
            return
    
        if exc is None:
            self.status_changed.emit("Ready")
            self.realtime_state_changed.emit(False)
            return
    
        print("FEED CRASHED:", repr(exc))
    
        try:
            self.submit(self.context.state.set_realtime_active(False, where="core_bridge"))
        except Exception:
            pass
        
        self.status_changed.emit(f"Feed crashed: {type(exc).__name__}")
        self.realtime_state_changed.emit(False)
