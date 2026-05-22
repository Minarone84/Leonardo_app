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
    """Own and supervise background asyncio tasks created by the core runtime.

    This manager provides a narrow runtime contract for task creation and
    coordinated shutdown. It also bridges task lifecycle events into the
    runtime state store when one has been attached.

    Notes:
        The manager currently tracks tasks by unique runtime name. A task name
        may not be reused while the previous task with the same name is still
        active.
    """

    def __init__(self, *, error_router: ErrorRouter, audit: AuditSink, logger: logging.Logger) -> None:
        """Initialize the task manager dependencies and internal task map.

        Args:
            error_router: Centralized error capture component for task failures.
            audit: Audit sink used for task-related lifecycle emission when
                needed.
            logger: Logger reserved for future task-level diagnostics.
        """
        self._error_router = error_router
        self._audit = audit
        self._logger = logger
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._state: StateStore | None = None

    def attach_state(self, state: StateStore) -> None:
        """Attach the runtime state store used for task lifecycle tracking.

        Args:
            state: Runtime state store that will receive started/completed/
                failed/cancelled transitions for tracked tasks.
        """
        self._state = state

    def cancel(self, name: str) -> bool:
        """Cancel one active tracked task by runtime name.

        Returns True when an active task was found and cancellation was
        requested. Returns False when the task is unknown or already terminal.
        The task done-callback remains responsible for emitting the runtime
        cancelled transition through StateStore.
        """
        task = self._tasks.get(name)
        if task is None or task.done():
            return False
        task.cancel()
        return True

    def create(
        self,
        name: str,
        coro: Awaitable[None],
        *,
        critical: bool = False,
        where: str = "task",
    ) -> None:
        """Create, register, and supervise a named background task.

        Args:
            name: Unique runtime identifier for the task.
            coro: Awaitable workload to schedule on the running event loop.
            critical: Whether an unhandled task failure should be treated as a
                critical runtime event.
            where: Logical origin label used for runtime state and audit
                traceability.

        Raises:
            RuntimeError: If another active task with the same name already
                exists.
        """
        if name in self._tasks and not self._tasks[name].done():
            raise RuntimeError(f"task already running: {name}")

        task = asyncio.create_task(coro, name=name)
        self._tasks[name] = task

        # Emit the runtime transition asynchronously so task creation remains
        # lightweight and aligned with the event-loop-driven execution model.
        if self._state is not None:
            asyncio.create_task(self._state.task_started(name, where=where))

        def _done(t: asyncio.Task[None]) -> None:
            """Handle terminal task states and route side effects safely.

            The callback is intentionally small and schedules async follow-up
            work instead of awaiting directly, because done callbacks execute in
            a synchronous context.
            """
            try:
                _ = t.result()
            except asyncio.CancelledError:
                if self._state is not None:
                    asyncio.create_task(self._state.task_cancelled(name, where=where))
                return
            except Exception as e:
                if self._state is not None:
                    asyncio.create_task(self._state.task_failed(name, str(e), where=where))
                asyncio.create_task(self._error_router.capture(e, where=f"{where}:{name}", fatal=critical))
                if critical:
                    asyncio.create_task(
                        self._audit.emit(make_event("lifecycle", "fatal", "critical task failed", task=name))
                    )
            else:
                if self._state is not None:
                    asyncio.create_task(self._state.task_completed(name, where=where))
            finally:
                if self._tasks.get(name) is task:
                    self._tasks.pop(name, None)

        task.add_done_callback(_done)

    async def cancel_all(self, timeout_s: float) -> None:
        """Cancel all active tracked tasks and wait for their completion.

        Args:
            timeout_s: Maximum number of seconds to wait for the gathered task
                cancellation/cleanup sequence to finish.
        """
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
    """Compatibility facade over service lookup and runtime state payloads.

    This class preserves the historical get/set access pattern used by the
    application while the core runtime is being split more cleanly into:

    - service lookup via AppContext.services / get_service(...)
    - runtime truth mutation via StateStore

    Registry remains available as a transitional compatibility boundary, but
    service registration is no longer allowed through ``set()``. Long-lived
    service objects must be registered explicitly via AppContext.
    """

    _RUNTIME_COMPAT_TYPES = (str, int, float, bool, type(None), dict, list, tuple)

    def __init__(self, services: dict[str, Any], runtime_state: dict[str, Any]) -> None:
        """Bind the compatibility facade to the current context dictionaries.

        Args:
            services: Mapping of long-lived service or capability objects.
            runtime_state: Mapping containing runtime metadata and state
                payloads.
        """
        self._services = services
        self._state = runtime_state

    def get(self, key: str, default: Any = None) -> Any:
        """Return a value from services first, then runtime state.

        Args:
            key: Lookup key to resolve.
            default: Fallback value returned when the key is not present in
                either backing map.
        """
        if key in self._services:
            return self._services[key]
        return self._state.get(key, default)

    def set(self, key: str, value: Any) -> None:
        """Store a compatibility runtime payload in the runtime-state mapping.

        Registry writes are now restricted to legacy runtime payload storage.
        Long-lived service objects must be registered explicitly through
        ``AppContext.register_service()`` so that service lookup and runtime
        state ownership remain separate.

        Args:
            key: Storage key to assign.
            value: Runtime payload to store.

        Raises:
            TypeError: If the caller attempts to register a service-like object
                through the compatibility facade instead of using the explicit
                service registration API.
        """
        if not isinstance(value, self._RUNTIME_COMPAT_TYPES):
            raise TypeError(
                "Registry.set no longer accepts service objects; "
                "use AppContext.register_service() for service registration"
            )
        self._state[key] = value

    def has(self, key: str) -> bool:
        """Return whether the key exists in services or runtime state."""
        return key in self._services or key in self._state

    def pop(self, key: str, default: Any = None) -> Any:
        """Remove and return a value from services or runtime state.

        Args:
            key: Storage key to remove.
            default: Fallback value returned when the key does not exist in the
                runtime-state mapping.
        """
        if key in self._services:
            return self._services.pop(key)
        return self._state.pop(key, default)


@dataclass
class AppContext:
    """Dependency container for the Leonardo core runtime.

    The context groups together the core singletons and runtime dictionaries
    that need to move through startup, service lifecycle, task execution, and
    GUI bridge boundaries without relying on module-level globals.

    Attributes:
        config: Loaded application configuration.
        logger: Core logger instance.
        audit: Structured audit sink fan-out.
        error_router: Centralized runtime error capture component.
        tasks: Shared task manager used by the runtime.
        services: Mapping of explicitly registered long-lived service and
            capability-provider objects.
        lifecycle_services: Names of registered services that participate in
            explicit start/stop lifecycle management.
        runtime_state: Backing mapping for compatibility state payloads.
        registry: Transitional compatibility facade over services and runtime
            state.
        state: Authoritative runtime mutation facade used for tracked state
            transitions.
    """

    config: Any
    logger: logging.Logger
    audit: AuditSink
    error_router: ErrorRouter
    tasks: TaskManager
    services: dict[str, Any] = field(default_factory=dict)
    lifecycle_services: set[str] = field(default_factory=set)
    runtime_state: dict[str, Any] = field(default_factory=dict)

    registry: Registry = field(init=False)
    state: StateStore = field(init=False)

    def __post_init__(self) -> None:
        """Construct the compatibility facade and authoritative state store."""
        self.registry = Registry(self.services, self.runtime_state)
        self.state = StateStore(registry=self.registry, audit=self.audit)
        self.tasks.attach_state(self.state)

    def register_service(self, name: str, svc: Any) -> None:
        """Register a long-lived service or capability provider in the context.

        This method is the explicit registration path for objects that should
        be available through application-level service lookup. Registration
        alone does not imply lifecycle management.

        Args:
            name: Canonical service name.
            svc: Service or capability-provider instance to register.

        Raises:
            KeyError: If another service is already registered under the same
                name.
        """
        if name in self.services:
            raise KeyError(f"service already registered: {name}")
        self.services[name] = svc

    def register_lifecycle_service(self, name: str, svc: Any) -> None:
        """Register a long-lived service that participates in lifecycle management.

        Lifecycle-managed services are a strict subset of registered services.
        They are expected to participate in explicit startup/shutdown handling
        and corresponding runtime lifecycle tracking.

        Args:
            name: Canonical service name.
            svc: Lifecycle-managed service instance to register.

        Raises:
            KeyError: If another service is already registered under the same
                name.
        """
        self.register_service(name, svc)
        self.lifecycle_services.add(name)

    def is_lifecycle_service(self, name: str) -> bool:
        """Return whether the named registered service is lifecycle-managed."""
        return name in self.lifecycle_services

    def get_service(self, name: str, t: type[T]) -> T:
        """Return a registered service and validate its expected type.

        Args:
            name: Canonical service name.
            t: Expected concrete type for the registered service.

        Raises:
            TypeError: If the registered service does not match the requested
                type.
        """
        svc = self.services[name]
        if not isinstance(svc, t):
            raise TypeError(f"service {name} is not {t.__name__}")
        return svc
