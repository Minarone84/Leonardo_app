import asyncio

from leonardo.core.audit import InMemoryAuditSink, make_event


def test_inmemory_audit_ring_buffer() -> None:
    sink = InMemoryAuditSink(max_events=2)

    async def scenario() -> None:
        await sink.emit(make_event("x", "info", "1"))
        await sink.emit(make_event("x", "info", "2"))
        await sink.emit(make_event("x", "info", "3"))

        snap = await sink.snapshot()
        assert [e.message for e in snap] == ["2", "3"]

    asyncio.run(scenario())
