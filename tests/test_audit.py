import asyncio
import json

from leonardo.core.audit import (
    AuditEvent,
    CompositeAuditSink,
    InMemoryAuditSink,
    JsonlAuditSink,
    make_event,
)


def test_inmemory_audit_ring_buffer() -> None:
    sink = InMemoryAuditSink(max_events=2)

    async def scenario() -> None:
        await sink.emit(make_event("x", "info", "1"))
        await sink.emit(make_event("x", "info", "2"))
        await sink.emit(make_event("x", "info", "3"))

        snap = await sink.snapshot()
        assert [e.message for e in snap] == ["2", "3"]

    asyncio.run(scenario())


def test_composite_audit_sink_normalizes_mapping_events_for_jsonl(tmp_path) -> None:
    memory_sink = InMemoryAuditSink(max_events=10)
    jsonl_path = tmp_path / "audit.jsonl"
    jsonl_sink = JsonlAuditSink(jsonl_path)
    sink = CompositeAuditSink(memory_sink, jsonl_sink)

    async def scenario() -> None:
        await sink.emit({
            "event_type": "historical_download",
            "severity": "info",
            "message": "download started",
            "ts_ms": 1234,
            "source": "historical_downloader",
            "entity_id": "job-1",
            "fields": {
                "job_id": "job-1",
                "path": tmp_path / "candles.csv",
            },
            "payload": {"rows": 1},
        })
        events = await memory_sink.snapshot()
        assert len(events) == 1
        assert isinstance(events[0], AuditEvent)
        assert events[0].event_type == "historical_download"
        assert events[0].fields["job_id"] == "job-1"
        assert events[0].fields["path"] == str(tmp_path / "candles.csv")
        assert events[0].fields["payload"] == {"rows": 1}
        assert events[0].fields["source"] == "historical_downloader"
        assert events[0].fields["entity_id"] == "job-1"
        await sink.close()

    asyncio.run(scenario())

    lines = jsonl_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    persisted = json.loads(lines[0])
    assert persisted["event_type"] == "historical_download"
    assert persisted["fields"]["job_id"] == "job-1"
    assert persisted["fields"]["path"] == str(tmp_path / "candles.csv")


def test_core_runner_audit_snapshot_dict_uses_normalized_event_shape() -> None:
    from leonardo.gui.core_runner import CoreRunner

    event = CoreRunner._audit_event_to_dict({
        "event_type": "historical_download",
        "severity": "info",
        "message": "download progress",
        "ts_ms": 1234,
        "fields": {"job_id": "job-1"},
    })

    assert event["event_type"] == "historical_download"
    assert event["severity"] == "info"
    assert event["message"] == "download progress"
    assert event["ts_ms"] == 1234
    assert event["fields"]["job_id"] == "job-1"
