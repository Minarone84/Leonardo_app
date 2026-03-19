from __future__ import annotations

import asyncio
import threading
import logging
from dataclasses import dataclass
from typing import Any, Callable, Optional, Awaitable
from concurrent.futures import Future
from concurrent.futures import TimeoutError as FutureTimeoutError

from leonardo.core.context import AppContext, TaskManager
from leonardo.core.audit import InMemoryAuditSink  # or your real audit sink
from leonardo.core.errors import ErrorRouter


@dataclass(frozen=True)
class AuditSnapshot:
    count: int
    events: list[dict[str, Any]]

class CoreRunner:
    """
    Runs an asyncio loop in a dedicated thread.
    Owns the CORE host lifecycle (start/stop) without blocking the UI thread.

    Key properties:
    - start() is idempotent
    - submit() fails fast if loop is not running
    - stop() stops the loop thread-safely and joins the thread
    """

    def __init__(self, on_status: Optional[Callable[[str], None]] = None) -> None:
        self._on_status = on_status or (lambda _: None)

        self._thread: Optional[threading.Thread] = None
        self._thread_lock = threading.Lock()

        self._loop_ready = threading.Event()
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._stop_evt: Optional[asyncio.Event] = None

        self.context: Optional[AppContext] = None

        self._audit_count = 0
        self._audit_lock = threading.Lock()

    # ---------------- Public API ----------------

    def start(self) -> None:
        """
        Start the core thread + loop. Safe to call multiple times.
        """
        with self._thread_lock:
            if self._thread is not None and self._thread.is_alive():
                return

            # reset state for a fresh start
            self._loop_ready.clear()
            self._loop = None
            self._stop_evt = None
            self.context = None

            self._thread = threading.Thread(
                target=self._thread_main,
                name="LeonardoCore",
                daemon=True,
            )
            self._thread.start()

        ok = self._loop_ready.wait(timeout=5)
        if not ok or self._loop is None:
            raise RuntimeError("CoreRunner failed to start (event loop not ready)")

    def is_running(self) -> bool:
        t = self._thread
        loop = self._loop
        return bool(t is not None and t.is_alive() and loop is not None)

    def stop(self) -> None:
        """
        Request core stop and join the core thread.
        Safe to call multiple times.
        """
        t = self._thread
        loop = self._loop
        stop_evt = self._stop_evt

        if t is None or loop is None or stop_evt is None:
            return

        self._on_status("Core stopping...")

        # Signal stop inside loop thread
        def _request_stop() -> None:
            try:
                stop_evt.set()
            finally:
                loop.stop()

        try:
            loop.call_soon_threadsafe(_request_stop)
        except RuntimeError:
            # loop already closed or not running
            return

        t.join(timeout=5)

        # Clear references
        with self._thread_lock:
            self._thread = None
            self._loop = None
            self._stop_evt = None

    def submit(self, coro: Awaitable[object]) -> Future:
        """
        Submit a coroutine to the core loop.
        Raises immediately if the core is not running (prevents "pending forever").
        """
        loop = self._loop
        t = self._thread
        if loop is None or t is None or not t.is_alive():
            raise RuntimeError("Core loop not running (did you call CoreRunner.start()?)")
        return asyncio.run_coroutine_threadsafe(coro, loop)

    def get_audit_snapshot(self) -> Optional[AuditSnapshot]:
        """
        Thread-safe snapshot of audit events.
        Must NOT touch the audit sink directly from the GUI thread.
        We ask the core loop to do it, then return the result.
        """
        if self._loop is None or self.context is None:
            return None

        audit = getattr(self.context, "audit", None)
        if audit is None:
            return AuditSnapshot(count=0, events=[])

        async def _snap() -> list[dict[str, Any]]:
            # support both async and sync snapshot implementations
            if hasattr(audit, "snapshot"):
                res = audit.snapshot()
                if asyncio.iscoroutine(res):
                    res = await res
                return list(res or [])
            if hasattr(audit, "get_snapshot"):
                res = audit.get_snapshot()
                if asyncio.iscoroutine(res):
                    res = await res
                return list(res or [])
            return []

        try:
            fut = asyncio.run_coroutine_threadsafe(_snap(), self._loop)
            events = fut.result(timeout=0.25)
        except (FutureTimeoutError, Exception):
            # best effort; don't hang GUI
            return None

        return AuditSnapshot(count=len(events), events=events)

    # ---------------- Internal ----------------

    def _thread_main(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        self._loop = loop
        self._stop_evt = asyncio.Event()

        # Create AppContext inside core thread
        self.context = self._create_context()

        self._loop_ready.set()

        # Run loop forever; _run_core will stop it via stop_evt
        core_task = loop.create_task(self._run_core())

        try:
            loop.run_forever()
        finally:
            # Cancel core task + any pending tasks
            try:
                core_task.cancel()
            except Exception:
                pass

            try:
                pending = asyncio.all_tasks(loop)
                for t in pending:
                    t.cancel()
                loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
                loop.run_until_complete(loop.shutdown_asyncgens())
            finally:
                loop.close()

    def _create_context(self) -> AppContext:
        logger = logging.getLogger("leonardo")
        logger.setLevel(logging.INFO)

        audit = InMemoryAuditSink()  # replace with real sink later
        errors = ErrorRouter(audit=audit, logger=logger)
        tasks = TaskManager(error_router=errors, audit=audit, logger=logger)

        cfg = object()  # replace with real config later

        return AppContext(
            config=cfg,
            logger=logger,
            audit=audit,
            error_router=errors,
            tasks=tasks,
        )

    async def _run_core(self) -> None:
        """
        Minimal core host loop. Keeps core alive until stop_evt is set.
        """
        self._on_status("Core started")

        assert self._stop_evt is not None
        while not self._stop_evt.is_set():
            await asyncio.sleep(1.0)
            with self._audit_lock:
                self._audit_count += 1

        self._on_status("Core stopped")