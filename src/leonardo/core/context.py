from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import logging
from typing import Any, Awaitable, TypeVar

from leonardo.core.audit import AuditSink, make_event
from leonardo.core.errors import ErrorRouter
from leonardo.core.state import StateStore

T = TypeVar("T")


class TaskManager:
    def __init__(self, *, error_router: ErrorRouter, audit: AuditSink, logger: logging.Logger) -> None:
        self._error_router = error_router
        self._audit = audit
        self._logger = logger
        self._tasks: dict[str, asyncio.Task[None]] = {}

    def create(
        self,
        name: str,
        coro: Awaitable[None],
        *,
        critical: bool = False,
        where: str = "task",
    ) -> None:
        if name in self._tasks and not self._tasks[name].done():
            raise RuntimeError(f"task already running: {name}")

        task = asyncio.create_task(coro, name=name)
        self._tasks[name] = task

        def _done(t: asyncio.Task[None]) -> None:
            try:
                _ = t.result()
            except asyncio.CancelledError:
                # normal shutdown path
                return
            except Exception as e:
                asyncio.create_task(self._error_router.capture(e, where=f"{where}:{name}", fatal=critical))
                if critical:
                    asyncio.create_task(
                        self._audit.emit(make_event("lifecycle", "fatal", "critical task failed", task=name))
                    )

        task.add_done_callback(_done)

    async def cancel_all(self, timeout_s: float) -> None:
        for t in self._tasks.values():
            if not t.done():
                t.cancel()

        pending = [t for t in self._tasks.values() if not t.done()]
        if not pending:
            return

        try:
            await asyncio.wait_for(asyncio.gather(*pending, return_exceptions=True), timeout=timeout_s)
        except asyncio.TimeoutError:
            await self._audit.emit(
                make_event("lifecycle", "error", "shutdown timeout; tasks still pending", pending=len(pending))
            )


class Registry:
    """
    Stable get/set facade over AppContext.services + AppContext.runtime_state.

    Convention:
    - services: long-lived objects (managers, bridges)
    - runtime_state: current facts/metadata (flags, window state dicts)
    """

    def __init__(self, services: dict[str, Any], runtime_state: dict[str, Any]) -> None:
        self._services = services
        self._state = runtime_state

    def get(self, key: str, default: Any = None) -> Any:
        if key in self._services:
            return self._services[key]
        return self._state.get(key, default)

    def set(self, key: str, value: Any) -> None:
        # Keep it boring and predictable:
        # primitives + dict/list go to runtime_state; everything else goes to services.
        if isinstance(value, (str, int, float, bool, type(None), dict, list, tuple)):
            self._state[key] = value
        else:
            self._services[key] = value

    def has(self, key: str) -> bool:
        return key in self._services or key in self._state

    def pop(self, key: str, default: Any = None) -> Any:
        if key in self._services:
            return self._services.pop(key)
        return self._state.pop(key, default)


@dataclass
class AppContext:
    config: Any
    logger: logging.Logger
    audit: AuditSink
    error_router: ErrorRouter
    tasks: TaskManager
    services: dict[str, Any] = field(default_factory=dict)
    runtime_state: dict[str, Any] = field(default_factory=dict)

    # New: stable registry facade + single-writer state store
    registry: Registry = field(init=False)
    state: StateStore = field(init=False)

    def __post_init__(self) -> None:
        self.registry = Registry(self.services, self.runtime_state)
        self.state = StateStore(registry=self.registry, audit=self.audit)

    def register_service(self, name: str, svc: Any) -> None:
        if name in self.services:
            raise KeyError(f"service already registered: {name}")
        self.services[name] = svc

    def get_service(self, name: str, t: type[T]) -> T:
        svc = self.services[name]
        if not isinstance(svc, t):
            raise TypeError(f"service {name} is not {t.__name__}")
        return svc
