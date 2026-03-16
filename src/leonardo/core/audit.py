from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import json
import asyncio
from typing import Any, Protocol


@dataclass(frozen=True)
class AuditEvent:
    ts: str
    event_type: str
    severity: str
    message: str
    fields: dict[str, Any]


class AuditSink(Protocol):
    async def emit(self, event: AuditEvent) -> None: ...
    async def close(self) -> None: ...


class InMemoryAuditSink:
    def __init__(self, max_events: int = 2000) -> None:
        self._max = max_events
        self._events: list[AuditEvent] = []
        self._lock = asyncio.Lock()

    async def emit(self, event: AuditEvent) -> None:
        async with self._lock:
            self._events.append(event)
            if len(self._events) > self._max:
                self._events = self._events[-self._max :]

    async def close(self) -> None:
        return

    async def snapshot(self) -> list[AuditEvent]:
        async with self._lock:
            return list(self._events)


class JsonlAuditSink:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._fp = self._path.open("a", encoding="utf-8")

    async def emit(self, event: AuditEvent) -> None:
        self._fp.write(json.dumps(event.__dict__, ensure_ascii=False) + "\n")
        self._fp.flush()

    async def close(self) -> None:
        try:
            self._fp.flush()
        finally:
            self._fp.close()


class CompositeAuditSink:
    def __init__(self, *sinks: AuditSink) -> None:
        self._sinks = sinks

    async def emit(self, event: AuditEvent) -> None:
        # Fail-soft: one sink dying shouldn't nuke the app.
        for s in self._sinks:
            try:
                await s.emit(event)
            except Exception:
                # last resort: ignore; error router will likely log elsewhere
                pass

    async def close(self) -> None:
        for s in self._sinks:
            try:
                await s.close()
            except Exception:
                pass


def make_event(event_type: str, severity: str, message: str, **fields: Any) -> AuditEvent:
    return AuditEvent(
        ts=datetime.now(timezone.utc).isoformat(),
        event_type=event_type,
        severity=severity,
        message=message,
        fields=dict(fields),
    )
