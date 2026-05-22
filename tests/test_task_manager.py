from __future__ import annotations

import asyncio
import logging

from leonardo.core.context import TaskManager


class _ErrorRouterProbe:
    def __init__(self) -> None:
        self.captured: list[tuple[BaseException, str, bool]] = []

    async def capture(self, exc: BaseException, *, where: str, fatal: bool = False, **fields: object) -> None:
        _ = fields
        self.captured.append((exc, where, fatal))


class _AuditProbe:
    def __init__(self) -> None:
        self.events: list[object] = []

    async def emit(self, event: object) -> None:
        self.events.append(event)


def _manager() -> tuple[TaskManager, _ErrorRouterProbe, _AuditProbe]:
    errors = _ErrorRouterProbe()
    audit = _AuditProbe()
    return (
        TaskManager(
            error_router=errors,  # type: ignore[arg-type]
            audit=audit,  # type: ignore[arg-type]
            logger=logging.getLogger("test.task_manager"),
        ),
        errors,
        audit,
    )


async def _settle_task_callbacks() -> None:
    for _ in range(5):
        await asyncio.sleep(0)


def test_task_manager_removes_completed_task_from_internal_map() -> None:
    async def scenario() -> None:
        manager, _errors, _audit = _manager()

        async def work() -> None:
            return None

        manager.create("job", work())
        assert "job" in manager._tasks

        await _settle_task_callbacks()

        assert "job" not in manager._tasks

    asyncio.run(scenario())


def test_task_manager_removes_failed_task_from_internal_map() -> None:
    async def scenario() -> None:
        manager, errors, _audit = _manager()

        async def work() -> None:
            raise RuntimeError("boom")

        manager.create("job", work(), where="unit")

        await _settle_task_callbacks()

        assert "job" not in manager._tasks
        assert [(str(exc), where, fatal) for exc, where, fatal in errors.captured] == [
            ("boom", "unit:job", False)
        ]

    asyncio.run(scenario())


def test_task_manager_removes_cancelled_task_from_internal_map() -> None:
    async def scenario() -> None:
        manager, _errors, _audit = _manager()

        async def work() -> None:
            await asyncio.Event().wait()

        manager.create("job", work())
        await asyncio.sleep(0)

        assert manager.cancel("job") is True
        await _settle_task_callbacks()

        assert "job" not in manager._tasks
        assert manager.cancel("job") is False

    asyncio.run(scenario())


def test_task_manager_terminal_cleanup_does_not_remove_replaced_task() -> None:
    async def scenario() -> None:
        manager, _errors, _audit = _manager()
        replacement_tasks: list[asyncio.Task[None]] = []

        async def replacement_work() -> None:
            await asyncio.Event().wait()

        async def work() -> None:
            replacement = asyncio.create_task(replacement_work())
            replacement_tasks.append(replacement)
            manager._tasks["job"] = replacement

        manager.create("job", work())
        await _settle_task_callbacks()

        replacement = replacement_tasks[0]
        assert manager._tasks.get("job") is replacement

        replacement.cancel()
        await asyncio.gather(replacement, return_exceptions=True)
        manager._tasks.pop("job", None)

    asyncio.run(scenario())
