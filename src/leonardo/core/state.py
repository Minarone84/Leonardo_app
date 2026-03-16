from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict

from leonardo.core.audit import AuditSink, make_event
from leonardo.core.registry_keys import RT_REALTIME_ACTIVE, RT_WINDOWS


@dataclass(frozen=True)
class WindowMeta:
    name: str
    type: str
    is_open: bool


class StateStore:
    """
    Single writer for runtime state + audit events.
    Rule: if it happens, state updates + audit event emitted.
    """

    def __init__(self, *, registry: Any, audit: AuditSink) -> None:
        self._registry = registry
        self._audit = audit

        # Ensure required roots exist
        if self._registry.get(RT_WINDOWS, None) is None:
            self._registry.set(RT_WINDOWS, {})
        if self._registry.get(RT_REALTIME_ACTIVE, None) is None:
            self._registry.set(RT_REALTIME_ACTIVE, False)

    # ---- Realtime ----

    def is_realtime_active(self) -> bool:
        return bool(self._registry.get(RT_REALTIME_ACTIVE, False))

    async def set_realtime_active(self, active: bool, *, where: str = "gui") -> None:
        active = bool(active)
        prev = bool(self._registry.get(RT_REALTIME_ACTIVE, False))
        if prev == active:
            return

        self._registry.set(RT_REALTIME_ACTIVE, active)
        await self._audit.emit(
            make_event(
                "realtime",
                "started" if active else "stopped",
                f"realtime {'started' if active else 'stopped'}",
                where=where,
            )
        )

    # ---- Windows ----

    def windows_state(self) -> Dict[str, Dict[str, Any]]:
        """
        Returns a COPY of current windows state to prevent accidental external mutation.
        """
        st = self._registry.get(RT_WINDOWS, {})
        if not isinstance(st, dict):
            return {}
        return dict(st)

    async def window_open(self, name: str, type_: str, *, where: str = "gui") -> None:
        st = self.windows_state()

        meta = st.get(name)
        if isinstance(meta, dict) and meta.get("is_open") is True:
            return

        st[name] = {"name": name, "type": type_, "is_open": True}
        self._registry.set(RT_WINDOWS, st)

        await self._audit.emit(
            make_event("gui.window", "opened", "window opened", name=name, type=type_, where=where)
        )

    async def window_close(self, name: str, *, where: str = "gui") -> None:
        st = self.windows_state()

        meta = st.get(name)
        if not isinstance(meta, dict):
            return

        st.pop(name, None)
        self._registry.set(RT_WINDOWS, st)

        await self._audit.emit(
            make_event("gui.window", "closed", "window closed", name=name, where=where)
        )