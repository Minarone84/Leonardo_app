
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import json
import asyncio
from typing import Any, Protocol


@dataclass(frozen=True)
class AuditEvent:
    """Immutable structured audit payload emitted by the core runtime.

    Attributes:
        ts: UTC timestamp serialized as an ISO-8601 string.
        event_type: Logical event family or subject, such as ``service`` or
            ``task``.
        severity: Event severity or lifecycle label associated with the event.
        message: Human-readable summary describing the event.
        fields: Additional structured payload attached to the event.
    """

    ts: str
    event_type: str
    severity: str
    message: str
    fields: dict[str, Any]


class AuditSink(Protocol):
    """Protocol implemented by audit event consumers.

    Audit sinks are intentionally minimal: they must accept event emission and
    support a best-effort shutdown/flush step.
    """

    async def emit(self, event: AuditEvent) -> None:
        """Consume a structured audit event."""
        ...

    async def close(self) -> None:
        """Flush and release any sink resources during shutdown."""
        ...


class InMemoryAuditSink:
    """Bounded in-memory audit sink used for runtime inspection.

    This sink stores only the most recent ``max_events`` items. It is useful for
    diagnostics, GUI snapshots, and tests where durable persistence is not
    required.
    """

    def __init__(self, max_events: int = 2000) -> None:
        """Initialize the bounded in-memory event buffer.

        Args:
            max_events: Maximum number of recent events retained in memory.
        """
        self._max = max_events
        self._events: list[AuditEvent] = []
        self._lock = asyncio.Lock()

    async def emit(self, event: AuditEvent) -> None:
        """Append an event and evict older entries when capacity is exceeded."""
        async with self._lock:
            self._events.append(event)
            if len(self._events) > self._max:
                self._events = self._events[-self._max :]

    async def close(self) -> None:
        """Close the sink.

        The in-memory sink does not own external resources, so shutdown is a
        no-op.
        """
        return

    async def snapshot(self) -> list[AuditEvent]:
        """Return a copy of the currently retained in-memory audit events."""
        async with self._lock:
            return list(self._events)


class JsonlAuditSink:
    """Append-only JSONL audit sink used for durable event persistence."""

    def __init__(self, path: Path) -> None:
        """Open the target JSONL file and ensure its parent directory exists.

        Args:
            path: Filesystem path where events will be appended in JSONL format.
        """
        self._path = path
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._fp = self._path.open("a", encoding="utf-8")

    async def emit(self, event: AuditEvent) -> None:
        """Serialize and append a single event to the JSONL stream."""
        self._fp.write(json.dumps(event.__dict__, ensure_ascii=False) + "\n")
        self._fp.flush()

    async def close(self) -> None:
        """Flush buffered data and close the underlying file handle."""
        try:
            self._fp.flush()
        finally:
            self._fp.close()


class CompositeAuditSink:
    """Fan out audit events to multiple sinks using fail-soft semantics.

    A failure in one downstream sink must not prevent the remaining sinks from
    receiving the same event. This keeps audit emission resilient during
    startup, runtime, and shutdown.
    """

    def __init__(self, *sinks: AuditSink) -> None:
        """Store the ordered sink collection used for fan-out emission."""
        self._sinks = sinks

    async def emit(self, event: AuditEvent) -> None:
        """Emit an event to all configured sinks on a best-effort basis."""
        # Fail-soft fan-out is intentional: one broken sink must not cascade
        # into a broader runtime failure.
        for s in self._sinks:
            try:
                await s.emit(event)
            except Exception:
                # Last-resort suppression is preserved here because audit
                # emission should never become a single point of runtime
                # failure.
                pass

    async def snapshot(self) -> list[object]:
        """Return a best-effort in-memory snapshot from snapshot-capable sinks.

        CompositeAuditSink is commonly used as the application audit fan-out.
        GUI consumers should not need to know which child sink owns the bounded
        in-memory history, so the composite exposes a narrow snapshot facade.
        Durable sinks such as JSONL normally do not implement snapshot and are
        skipped.
        """
        for s in self._sinks:
            snapshot_fn = getattr(s, "snapshot", None)
            if snapshot_fn is None:
                continue
            try:
                result = snapshot_fn()
                if asyncio.iscoroutine(result):
                    result = await result
                return list(result or [])
            except Exception:
                continue
        return []

    async def close(self) -> None:
        """Close all configured sinks on a best-effort basis."""
        for s in self._sinks:
            try:
                await s.close()
            except Exception:
                pass


def make_event(event_type: str, severity: str, message: str, **fields: Any) -> AuditEvent:
    """Build a normalized audit event with the current UTC timestamp.

    Args:
        event_type: Logical event family or subject.
        severity: Event severity or lifecycle label.
        message: Human-readable event summary.
        **fields: Additional structured payload values attached to the event.
    """
    return AuditEvent(
        ts=datetime.now(timezone.utc).isoformat(),
        event_type=event_type,
        severity=severity,
        message=message,
        fields=dict(fields),
    )
