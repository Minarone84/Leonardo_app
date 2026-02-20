from __future__ import annotations

import asyncio
import threading
import logging
from dataclasses import dataclass
from typing import Callable, Optional, Awaitable
from concurrent.futures import Future

from leonardo.core.context import AppContext, TaskManager
from leonardo.core.audit import InMemoryAuditSink  # or your real audit sink
from leonardo.core.errors import ErrorRouter


@dataclass(frozen=True)
class AuditSnapshot:
    count: int


class CoreRunner:
    """
    Runs an asyncio loop in a dedicated thread.
    Owns the CORE host lifecycle (start/stop) without blocking the UI thread.
    """

    def __init__(self, on_status: Optional[Callable[[str], None]] = None) -> None:
        self._on_status = on_status or (lambda _: None)

        self._thread = threading.Thread(
            target=self._thread_main,
            name="LeonardoCore",
            daemon=True,
        )

        self._loop_ready = threading.Event()
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._stop_evt: Optional[asyncio.Event] = None

        self.context: Optional[AppContext] = None

        self._audit_count = 0
        self._audit_lock = threading.Lock()

    # ---------------- Public API ----------------

    def start(self) -> None:
        self._thread.start()
        ok = self._loop_ready.wait(timeout=5)
        if not ok or self._loop is None:
            raise RuntimeError("CoreRunner failed to start (event loop not ready)")


    def stop(self) -> None:
        if self._loop is None or self._stop_evt is None:
            return
        self._on_status("Core stopping...")
        self._loop.call_soon_threadsafe(self._stop_evt.set)
        self._thread.join(timeout=5)
        self._loop = None
        self._stop_evt = None

    def submit(self, coro: Awaitable[object]) -> Future:
        if self._loop is None:
            raise RuntimeError("Core loop not running")
        return asyncio.run_coroutine_threadsafe(coro, self._loop)

    def get_audit_snapshot(self) -> Optional[AuditSnapshot]:
        with self._audit_lock:
            return AuditSnapshot(count=self._audit_count)

    # ---------------- Internal ----------------

    def _thread_main(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop
        self._stop_evt = asyncio.Event()

        # Create AppContext inside core thread
        self.context = self._create_context()

        self._loop_ready.set()

        try:
            loop.run_until_complete(self._run_core())
        finally:
            try:
                pending = asyncio.all_tasks(loop)
                for t in pending:
                    t.cancel()
                loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
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
        self._on_status("Core started")

        assert self._stop_evt is not None
        while not self._stop_evt.is_set():
            await asyncio.sleep(1.0)
            with self._audit_lock:
                self._audit_count += 1

        self._on_status("Core stopped")
