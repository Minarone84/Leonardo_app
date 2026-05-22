from __future__ import annotations

import asyncio
import threading

from dataclasses import dataclass
from typing import Any, Callable, Optional, Awaitable
from concurrent.futures import Future
from concurrent.futures import TimeoutError as FutureTimeoutError

from leonardo.core.context import AppContext
from leonardo.core.app import LeonardoApp
from leonardo.core.audit import normalize_audit_event
from leonardo.core.config import load_config

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
        self._app: Optional[LeonardoApp] = None
        self._startup_error: Optional[BaseException] = None
        
        self._thread: Optional[threading.Thread] = None
        self._thread_lock = threading.Lock()

        self._loop_ready = threading.Event()
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._stop_evt: Optional[asyncio.Event] = None

        self.context: Optional[AppContext] = None

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
            self._app = None
            self._startup_error = None

            self._thread = threading.Thread(
                target=self._thread_main,
                name="LeonardoCore",
                daemon=True,
            )
            self._thread.start()

        ok = self._loop_ready.wait(timeout=5)
        if not ok or self._loop is None:
            raise RuntimeError("CoreRunner failed to start (event loop not ready)")

        if self._startup_error is not None:
            err = self._startup_error
            self._startup_error = None
            raise RuntimeError("CoreRunner failed during LeonardoApp startup") from err
    
    def is_running(self) -> bool:
        t = self._thread
        loop = self._loop
        return bool(t is not None and t.is_alive() and loop is not None)

    def stop(self) -> None:
        t = self._thread
        loop = self._loop
        stop_evt = self._stop_evt

        if t is None or loop is None or stop_evt is None:
            return

        self._on_status("Core stopping...")

        def _request_stop() -> None:
            stop_evt.set()

        try:
            loop.call_soon_threadsafe(_request_stop)
        except RuntimeError:
            return

        t.join(timeout=5)

        with self._thread_lock:
            self._thread = None
            self._loop = None
            self._stop_evt = None
            self._app = None

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
            raw_events: list[object]
            if hasattr(audit, "snapshot"):
                res = audit.snapshot()
                if asyncio.iscoroutine(res):
                    res = await res
                raw_events = list(res or [])
            elif hasattr(audit, "get_snapshot"):
                res = audit.get_snapshot()
                if asyncio.iscoroutine(res):
                    res = await res
                raw_events = list(res or [])
            else:
                raw_events = []

            return [self._audit_event_to_dict(event) for event in raw_events]

        try:
            fut = asyncio.run_coroutine_threadsafe(_snap(), self._loop)
            events = fut.result(timeout=0.25)
        except (FutureTimeoutError, Exception):
            # best effort; don't hang GUI
            return None

        return AuditSnapshot(count=len(events), events=events)

    @staticmethod
    def _audit_event_to_dict(event: object) -> dict[str, Any]:
        """Normalize audit events for GUI consumers.

        The GUI sees a stable dictionary shape while Core owns compatibility
        normalization for legacy mapping-shaped audit events.
        """
        normalized = normalize_audit_event(event)
        payload = dict(normalized.__dict__)
        ts_ms = normalized.fields.get("ts_ms")
        if ts_ms is not None:
            payload["ts_ms"] = ts_ms
        return payload

    # ---------------- Internal ----------------

    def _thread_main(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        self._loop = loop
        self._stop_evt = asyncio.Event()

        async def _host_main() -> None:
            assert self._stop_evt is not None

            try:
                self._on_status("Core starting...")

                config = load_config()
                self._app = LeonardoApp(config)

                await self._app.startup()
                self.context = self._app.context

                self._on_status("Core started")
                self._loop_ready.set()

                while not self._stop_evt.is_set():
                    await asyncio.sleep(0.25)

            except Exception as e:
                self._startup_error = e
                self._loop_ready.set()
                return
            finally:
                if self._app is not None:
                    try:
                        await self._app.shutdown(reason="core_runner_stop")
                    except Exception:
                        pass
                    finally:
                        self._on_status("Core stopped")

        try:
            loop.run_until_complete(_host_main())
        finally:
            try:
                pending = asyncio.all_tasks(loop)
                for t in pending:
                    t.cancel()
                loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
                loop.run_until_complete(loop.shutdown_asyncgens())
            finally:
                loop.close()
