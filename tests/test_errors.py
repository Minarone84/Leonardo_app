import asyncio

from leonardo.core.audit import InMemoryAuditSink
from leonardo.core.errors import ErrorRouter
from leonardo.core.logging import configure_logging


def test_error_router_emits_audit_event() -> None:
    logger = configure_logging("INFO", json_mode=False)
    sink = InMemoryAuditSink()
    router = ErrorRouter(logger, sink)

    async def scenario() -> None:
        try:
            raise ValueError("boom")
        except Exception as e:
            await router.capture(e, where="test", fatal=False)

        events = await sink.snapshot()
        assert any(ev.event_type == "error" and "boom" in ev.message for ev in events)

    asyncio.run(scenario())
