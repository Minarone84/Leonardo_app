
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass, is_dataclass
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


_RESERVED_EVENT_KEYS = {
    "ts",
    "ts_ms",
    "event_type",
    "type",
    "severity",
    "level",
    "message",
    "msg",
    "fields",
    "payload",
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Mapping):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_json_safe(item) for item in value]
    if is_dataclass(value) and not isinstance(value, type):
        return _json_safe(asdict(value))
    return str(value)


def _fields_from(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, Mapping):
        return {str(k): _json_safe(v) for k, v in value.items()}
    return {"payload": _json_safe(value)}


def _ts_from_mapping(raw: Mapping[str, Any]) -> str:
    ts = raw.get("ts")
    if ts:
        return str(ts)
    ts_ms = raw.get("ts_ms")
    if ts_ms is not None:
        try:
            return datetime.fromtimestamp(float(ts_ms) / 1000.0, timezone.utc).isoformat()
        except (TypeError, ValueError, OverflowError):
            return _now_iso()
    return _now_iso()


def normalize_audit_event(event: object) -> AuditEvent:
    """Return a JSON-safe structured audit event.

    The audit boundary accepts the current ``AuditEvent`` model and legacy
    mapping-shaped subsystem events. Mapping compatibility is centralized here
    so sinks and GUI snapshot adapters do not need separate historical-download
    special cases.
    """
    if isinstance(event, AuditEvent):
        return AuditEvent(
            ts=str(event.ts or _now_iso()),
            event_type=str(event.event_type or "unknown"),
            severity=str(event.severity or "info"),
            message=str(event.message or ""),
            fields=_fields_from(event.fields),
        )

    if isinstance(event, Mapping):
        fields = _fields_from(event.get("fields"))
        if "payload" in event and "payload" not in fields:
            fields["payload"] = _json_safe(event["payload"])
        if "ts_ms" in event and "ts_ms" not in fields:
            fields["ts_ms"] = _json_safe(event["ts_ms"])
        for key, value in event.items():
            if key in _RESERVED_EVENT_KEYS or key in fields:
                continue
            fields[str(key)] = _json_safe(value)

        event_type = event.get("event_type") or event.get("type") or "unknown"
        severity = event.get("severity") or event.get("level") or "info"
        message = event.get("message") or event.get("msg") or event_type
        return AuditEvent(
            ts=_ts_from_mapping(event),
            event_type=str(event_type),
            severity=str(severity),
            message=str(message),
            fields=fields,
        )

    payload = getattr(event, "__dict__", None)
    if isinstance(payload, Mapping):
        return normalize_audit_event(payload)

    return AuditEvent(
        ts=_now_iso(),
        event_type="unknown",
        severity="info",
        message=str(event),
        fields={},
    )


class AuditSink(Protocol):
    """Protocol implemented by audit event consumers.

    Audit sinks are intentionally minimal: they must accept event emission and
    support a best-effort shutdown/flush step.
    """

    async def emit(self, event: object) -> None:
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

    async def emit(self, event: object) -> None:
        """Append an event and evict older entries when capacity is exceeded."""
        normalized = normalize_audit_event(event)
        async with self._lock:
            self._events.append(normalized)
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

    async def emit(self, event: object) -> None:
        """Serialize and append a single event to the JSONL stream."""
        normalized = normalize_audit_event(event)
        self._fp.write(json.dumps(normalized.__dict__, ensure_ascii=False) + "\n")
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

    async def emit(self, event: object) -> None:
        """Emit an event to all configured sinks on a best-effort basis."""
        normalized = normalize_audit_event(event)
        # Fail-soft fan-out is intentional: one broken sink must not cascade
        # into a broader runtime failure.
        for s in self._sinks:
            try:
                await s.emit(normalized)
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
