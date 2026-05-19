from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Dict

from leonardo.core import registry_keys as _registry_keys
from leonardo.core.audit import AuditSink, make_event

RT_APP = _registry_keys.RT_APP
RT_SERVICES = _registry_keys.RT_SERVICES
RT_TASKS = _registry_keys.RT_TASKS
RT_WINDOWS = _registry_keys.RT_WINDOWS
RT_REALTIME_ACTIVE = _registry_keys.RT_REALTIME_ACTIVE
RT_CONNECTIONS = getattr(_registry_keys, "RT_CONNECTIONS", "runtime.connections")
RT_SESSION = getattr(_registry_keys, "RT_SESSION", "runtime.session")


def _now_iso() -> str:
    """Return the current UTC timestamp serialized as an ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat()


@dataclass
class AppRuntimeState:
    """Runtime snapshot for the application lifecycle state.

    Attributes:
        status: Current high-level application status.
        updated_at: UTC timestamp of the last lifecycle transition recorded
            for the application.
    """

    status: str
    updated_at: str


@dataclass
class ServiceRuntimeState:
    """Runtime snapshot for a registered service.

    Attributes:
        name: Canonical service name used in the runtime registry.
        status: Current lifecycle status for the service.
        updated_at: UTC timestamp of the last status transition.
        error: Optional textual error payload associated with the latest
            failure state.
    """

    name: str
    status: str
    updated_at: str
    error: str | None = None


@dataclass
class TaskRuntimeState:
    """Runtime snapshot for an actively tracked background task.

    Attributes:
        name: Task identifier used by the task manager.
        status: Current lifecycle status for the task while it remains active
            in runtime state.
        created_at: UTC timestamp recorded when the task entered the tracked
            runtime state.
        updated_at: UTC timestamp of the latest active task state transition.
        error: Optional textual error payload associated with the latest
            active failure state.

    Notes:
        Runtime task state is intentionally limited to currently active tasks.
        Terminal task outcomes are emitted to the audit layer and then removed
        from runtime state so the runtime surface remains a view of current
        operational truth rather than historical task accumulation.
    """

    name: str
    status: str
    created_at: str
    updated_at: str
    error: str | None = None


@dataclass
class SessionRuntimeState:
    """Runtime snapshot for the currently tracked application session.

    Attributes:
        session_id: Stable identifier for the current runtime session.
        user_id: Optional user identity associated with the current session.
        status: Current session lifecycle or presence status.
        updated_at: UTC timestamp of the last session state transition.
        error: Optional textual error payload associated with the latest
            session failure state.

    Notes:
        Session runtime state represents the single current session surface.
        Historical session transitions remain in the audit layer.
    """

    session_id: str
    user_id: str | None
    status: str
    updated_at: str
    error: str | None = None


@dataclass
class ConnectionRuntimeState:
    """Runtime snapshot for a tracked external connection surface.

    Attributes:
        name: Canonical runtime identifier for the connection.
        kind: Connection provider or semantic connection type.
        status: Current operational lifecycle status.
        updated_at: UTC timestamp of the last connection state transition.
        error: Optional textual error payload associated with the latest
            failure state.
    """

    name: str
    kind: str
    status: str
    updated_at: str
    error: str | None = None


@dataclass(frozen=True)
class WindowMeta:
    """Minimal runtime metadata for an open GUI window.

    Attributes:
        name: Stable runtime window identifier.
        type: Window class or semantic window type.
        is_open: Flag indicating whether the window is currently open.
        opened_at: UTC timestamp captured when the active window entry was
            created.
    """

    name: str
    type: str
    is_open: bool
    opened_at: str


class StateStore:
    """Single-writer facade for runtime state and matching audit emission.

    This store owns the mutation path for the runtime facts currently tracked
    during phase 3 of the core refactor. Each meaningful state transition is
    responsible for:

    - updating the runtime registry-backed state
    - preserving simple idempotent behavior when no change is needed
    - emitting a structured audit event describing the transition

    Notes:
        The store currently uses the existing registry compatibility layer as
        its persistence backend. This preserves current application behavior
        while making runtime mutations explicit and auditable.

        Task runtime state is intentionally retained only while tasks are
        active. Terminal task outcomes belong to audit history, not to the
        runtime state surface.
    """

    def __init__(self, *, registry: Any, audit: AuditSink) -> None:
        """Initialize the runtime state roots required by the current core.

        Args:
            registry: Compatibility registry used as the backing store for
                runtime data during the phase-1 transition.
            audit: Audit sink used to persist state transitions as structured
                events.
        """
        self._registry = registry
        self._audit = audit

        # Ensure the runtime roots required by the current phase exist before
        # any lifecycle method attempts to read or mutate them.
        if self._registry.get(RT_APP) is None:
            self._registry.set(RT_APP, asdict(AppRuntimeState(status="starting", updated_at=_now_iso())))

        if self._registry.get(RT_SERVICES) is None:
            self._registry.set(RT_SERVICES, {})

        if self._registry.get(RT_TASKS) is None:
            self._registry.set(RT_TASKS, {})

        if self._registry.get(RT_CONNECTIONS) is None:
            self._registry.set(RT_CONNECTIONS, {})

        if self._registry.get(RT_SESSION) is None:
            self._registry.set(RT_SESSION, {})

        # Preserve existing GUI/runtime keys so current consumers keep working
        # while the broader runtime model is being formalized.
        if self._registry.get(RT_WINDOWS, None) is None:
            self._registry.set(RT_WINDOWS, {})
        if self._registry.get(RT_REALTIME_ACTIVE, None) is None:
            self._registry.set(RT_REALTIME_ACTIVE, False)

    def _runtime_dict(self, key: str) -> Dict[str, Any]:
        """Return a defensive shallow copy of a dict-backed runtime root.

        Args:
            key: Registry key for the runtime root to read.

        Returns:
            A shallow copy of the stored dictionary when the backing value is a
            dictionary; otherwise an empty dictionary.

        Notes:
            The registry remains a transitional compatibility layer. Runtime
            reads therefore stay defensive so malformed or stale values cannot
            leak unexpected types into the state store's mutation paths.
        """
        st = self._registry.get(key, {})
        if not isinstance(st, dict):
            return {}
        return dict(st)

    async def _emit_runtime_event(
        self,
        kind: str,
        action: str,
        message: str,
        *,
        where: str,
        entity_type: str,
        entity_id: str,
        **fields: Any,
    ) -> None:
        """Emit a structured audit event for a runtime state transition.

        Args:
            kind: High-level runtime entity family such as ``app`` or
                ``service``.
            action: Canonical action or transition label.
            message: Human-readable summary associated with the transition.
            where: Logical origin of the transition for traceability.
            entity_type: Canonical entity type for downstream filtering.
            entity_id: Stable entity identifier within the given entity type.
            **fields: Additional structured fields to attach to the event.

        Notes:
            This helper centralizes runtime-origin audit construction so event
            families, action names, entity metadata, and free-form fields stay
            consistent across the state store without changing sink behavior.
        """
        payload = {
            "where": where,
            "entity_type": entity_type,
            "entity_id": entity_id,
            **fields,
        }
        await self._audit.emit(make_event(kind, action, message, **payload))

    def get_app_status(self) -> str:
        """Return the current application lifecycle status."""
        return self._runtime_dict(RT_APP).get("status", "unknown")

    async def set_app_status(self, status: str, *, where: str = "core") -> None:
        """Persist and audit an application lifecycle transition.

        Args:
            status: New application lifecycle status to record.
            where: Logical origin of the transition for audit traceability.
        """
        st = self._runtime_dict(RT_APP)
        if st.get("status") == status:
            return

        st["status"] = status
        st["updated_at"] = _now_iso()
        self._registry.set(RT_APP, st)
        await self._emit_runtime_event(
            "app",
            status,
            f"app {status}",
            where=where,
            entity_type="app",
            entity_id="core",
        )

    def services_state(self) -> Dict[str, Dict[str, Any]]:
        """Return a shallow copy of the current tracked service state map.

        Returning a copy prevents callers from mutating the underlying runtime
        state outside the store's controlled write path.
        """
        return self._runtime_dict(RT_SERVICES)

    async def register_service(self, name: str, *, where: str = "core") -> None:
        """Create the initial runtime entry for a service.

        Args:
            name: Canonical service name.
            where: Logical origin of the registration event.
        """
        st = self.services_state()
        if name in st:
            return

        st[name] = asdict(ServiceRuntimeState(name=name, status="registered", updated_at=_now_iso()))
        self._registry.set(RT_SERVICES, st)
        await self._emit_runtime_event(
            "service",
            "registered",
            "service registered",
            where=where,
            entity_type="service",
            entity_id=name,
            name=name,
        )

    async def set_service_status(
        self,
        name: str,
        status: str,
        *,
        where: str = "core",
        error: str | None = None,
    ) -> None:
        """Persist and audit a service lifecycle transition.

        Args:
            name: Canonical service name.
            status: New lifecycle status to assign.
            where: Logical origin of the transition.
            error: Optional error payload associated with a failure state.
        """
        st = self.services_state()
        meta = st.get(name)
        if not isinstance(meta, dict):
            return

        if meta.get("status") == status and meta.get("error") == error:
            return

        meta["status"] = status
        meta["updated_at"] = _now_iso()
        meta["error"] = error

        st[name] = meta
        self._registry.set(RT_SERVICES, st)
        await self._emit_runtime_event(
            "service",
            status,
            f"service {status}",
            where=where,
            entity_type="service",
            entity_id=name,
            name=name,
            error=error,
        )

    def tasks_state(self) -> Dict[str, Dict[str, Any]]:
        """Return a shallow copy of the current tracked active-task state map.

        Runtime task state intentionally contains only currently active tasks.
        Terminal task outcomes are preserved in audit history.
        """
        return self._runtime_dict(RT_TASKS)

    async def task_started(self, name: str, *, where: str = "task") -> None:
        """Create or replace the runtime state entry for a started task.

        Args:
            name: Task identifier supplied by the task manager.
            where: Logical origin of the task transition.
        """
        st = self.tasks_state()
        now = _now_iso()
        st[name] = asdict(TaskRuntimeState(name=name, status="running", created_at=now, updated_at=now))
        self._registry.set(RT_TASKS, st)
        await self._emit_runtime_event(
            "task",
            "started",
            "task started",
            where=where,
            entity_type="task",
            entity_id=name,
            name=name,
        )

    async def task_completed(self, name: str, *, where: str = "task") -> None:
        """Remove a completed task from runtime state and emit audit.

        Args:
            name: Task identifier supplied by the task manager.
            where: Logical origin of the task transition.
        """
        removed = self._pop_task_runtime(name)
        if removed is None:
            return

        await self._emit_runtime_event(
            "task",
            "completed",
            "task completed",
            where=where,
            entity_type="task",
            entity_id=name,
            name=name,
        )

    async def task_failed(self, name: str, error: str, *, where: str = "task") -> None:
        """Remove a failed task from runtime state and record the failure.

        Args:
            name: Task identifier supplied by the task manager.
            error: Stringified error payload associated with the failure.
            where: Logical origin of the task transition.
        """
        removed = self._pop_task_runtime(name)
        if removed is None:
            return

        await self._emit_runtime_event(
            "task",
            "failed",
            "task failed",
            where=where,
            entity_type="task",
            entity_id=name,
            name=name,
            error=error,
        )

    async def task_cancelled(self, name: str, *, where: str = "task") -> None:
        """Remove a cancelled task from runtime state and emit audit.

        Args:
            name: Task identifier supplied by the task manager.
            where: Logical origin of the task transition.
        """
        removed = self._pop_task_runtime(name)
        if removed is None:
            return

        await self._emit_runtime_event(
            "task",
            "cancelled",
            "task cancelled",
            where=where,
            entity_type="task",
            entity_id=name,
            name=name,
        )

    def _pop_task_runtime(self, name: str) -> Dict[str, Any] | None:
        """Remove and return a tracked task runtime entry.

        Args:
            name: Task identifier supplied by the task manager.

        Returns:
            The removed task metadata when a tracked entry exists; otherwise
            ``None``.

        Notes:
            This helper enforces the phase-2 task retention rule: runtime task
            state contains only active tasks. Terminal outcomes remain visible
            through audit history.
        """
        st = self.tasks_state()
        meta = st.get(name)
        if not isinstance(meta, dict):
            return None

        st.pop(name, None)
        self._registry.set(RT_TASKS, st)
        return meta

    def session_state(self) -> Dict[str, Any] | None:
        """Return the current tracked session snapshot, if one exists."""
        st = self._runtime_dict(RT_SESSION)
        if not st:
            return None
        return st

    async def set_session(
        self,
        session_id: str,
        *,
        user_id: str | None = None,
        status: str = "active",
        where: str = "core",
        error: str | None = None,
    ) -> None:
        """Create or replace the current runtime session snapshot.

        Args:
            session_id: Stable identifier for the current runtime session.
            user_id: Optional user identity associated with the session.
            status: Current session lifecycle or presence status.
            where: Logical origin of the transition.
            error: Optional error payload associated with the session state.
        """
        st = asdict(
            SessionRuntimeState(
                session_id=session_id,
                user_id=user_id,
                status=status,
                updated_at=_now_iso(),
                error=error,
            )
        )
        current = self.session_state()
        if (
            isinstance(current, dict)
            and current.get("session_id") == session_id
            and current.get("user_id") == user_id
            and current.get("status") == status
            and current.get("error") == error
        ):
            return

        self._registry.set(RT_SESSION, st)
        await self._emit_runtime_event(
            "session",
            status,
            f"session {status}",
            where=where,
            entity_type="session",
            entity_id=session_id,
            session_id=session_id,
            user_id=user_id,
            error=error,
        )

    async def set_session_status(
        self,
        status: str,
        *,
        where: str = "core",
        error: str | None = None,
    ) -> None:
        """Persist and audit a lifecycle transition for the current session.

        Args:
            status: New session lifecycle or presence status.
            where: Logical origin of the transition.
            error: Optional error payload associated with the transition.
        """
        st = self.session_state()
        if not isinstance(st, dict):
            return

        if st.get("status") == status and st.get("error") == error:
            return

        st["status"] = status
        st["updated_at"] = _now_iso()
        st["error"] = error
        self._registry.set(RT_SESSION, st)
        session_id = str(st.get("session_id", "current"))
        await self._emit_runtime_event(
            "session",
            status,
            f"session {status}",
            where=where,
            entity_type="session",
            entity_id=session_id,
            session_id=session_id,
            user_id=st.get("user_id"),
            error=error,
        )

    async def clear_session(self, *, where: str = "core") -> None:
        """Clear the current runtime session snapshot and emit audit.

        Args:
            where: Logical origin of the transition.
        """
        st = self.session_state()
        if not isinstance(st, dict):
            return

        self._registry.set(RT_SESSION, {})
        session_id = str(st.get("session_id", "current"))
        await self._emit_runtime_event(
            "session",
            "cleared",
            "session cleared",
            where=where,
            entity_type="session",
            entity_id=session_id,
            session_id=session_id,
            user_id=st.get("user_id"),
        )

    def connections_state(self) -> Dict[str, Dict[str, Any]]:
        """Return a shallow copy of the current tracked connection state map.

        Returning a copy prevents callers from mutating the underlying runtime
        state outside the store's controlled write path.
        """
        return self._runtime_dict(RT_CONNECTIONS)

    async def register_connection(self, name: str, kind: str, *, where: str = "connection") -> None:
        """Create the initial runtime entry for a connection surface.

        Args:
            name: Canonical runtime connection identifier.
            kind: Connection provider or semantic connection type.
            where: Logical origin of the registration event.
        """
        st = self.connections_state()
        if name in st:
            return

        st[name] = asdict(
            ConnectionRuntimeState(name=name, kind=kind, status="registered", updated_at=_now_iso())
        )
        self._registry.set(RT_CONNECTIONS, st)
        await self._emit_runtime_event(
            "connection",
            "registered",
            "connection registered",
            where=where,
            entity_type="connection",
            entity_id=name,
            name=name,
            connection_kind=kind,
        )

    async def set_connection_status(
        self,
        name: str,
        status: str,
        *,
        where: str = "connection",
        error: str | None = None,
    ) -> None:
        """Persist and audit a connection lifecycle transition.

        Args:
            name: Canonical runtime connection identifier.
            status: New lifecycle or operational status to assign.
            where: Logical origin of the transition.
            error: Optional error payload associated with a failure state.
        """
        st = self.connections_state()
        meta = st.get(name)
        if not isinstance(meta, dict):
            return

        if meta.get("status") == status and meta.get("error") == error:
            return

        meta["status"] = status
        meta["updated_at"] = _now_iso()
        meta["error"] = error

        st[name] = meta
        self._registry.set(RT_CONNECTIONS, st)
        await self._emit_runtime_event(
            "connection",
            status,
            f"connection {status}",
            where=where,
            entity_type="connection",
            entity_id=name,
            name=name,
            connection_kind=meta.get("kind"),
            error=error,
        )

    def is_realtime_active(self) -> bool:
        """Return whether realtime mode is currently marked as active."""
        return bool(self._registry.get(RT_REALTIME_ACTIVE, False))

    async def set_realtime_active(self, active: bool, *, where: str = "gui") -> None:
        """Persist and audit a realtime on/off transition.

        Args:
            active: Desired realtime state.
            where: Logical origin of the transition.
        """
        active = bool(active)
        prev = bool(self._registry.get(RT_REALTIME_ACTIVE, False))
        if prev == active:
            return

        self._registry.set(RT_REALTIME_ACTIVE, active)
        action = "started" if active else "stopped"
        await self._emit_runtime_event(
            "realtime",
            action,
            f"realtime {action}",
            where=where,
            entity_type="realtime",
            entity_id="global",
        )

    def windows_state(self) -> Dict[str, Dict[str, Any]]:
        """Return a shallow copy of the currently tracked open-window map."""
        return self._runtime_dict(RT_WINDOWS)

    async def window_open(self, name: str, type_: str, *, where: str = "gui") -> None:
        """Create or refresh the active runtime entry for a window.

        Args:
            name: Stable runtime window identifier.
            type_: Semantic or class-level window type.
            where: Logical origin of the transition.
        """
        st = self.windows_state()
        meta = st.get(name)
        if isinstance(meta, dict) and meta.get("is_open") is True:
            return

        st[name] = asdict(WindowMeta(name=name, type=type_, is_open=True, opened_at=_now_iso()))
        self._registry.set(RT_WINDOWS, st)
        await self._emit_runtime_event(
            "window",
            "opened",
            "window opened",
            where=where,
            entity_type="window",
            entity_id=name,
            name=name,
            type=type_,
        )

    async def window_close(self, name: str, *, where: str = "gui") -> None:
        """Remove an active runtime entry for a window and emit audit.

        Args:
            name: Stable runtime window identifier.
            where: Logical origin of the transition.
        """
        st = self.windows_state()
        meta = st.get(name)
        if not isinstance(meta, dict):
            return

        st.pop(name, None)
        self._registry.set(RT_WINDOWS, st)
        await self._emit_runtime_event(
            "window",
            "closed",
            "window closed",
            where=where,
            entity_type="window",
            entity_id=name,
            name=name,
        )
