from __future__ import annotations

import asyncio
from pathlib import Path
import logging
import uuid

from leonardo.core.config import load_config, AppConfig
from leonardo.core.logging import configure_logging, run_id_var, component_var, log
from leonardo.core.audit import (
    CompositeAuditSink,
    InMemoryAuditSink,
    JsonlAuditSink,
    make_event,
)
from leonardo.core.errors import ErrorRouter
from leonardo.core.context import AppContext, TaskManager
from leonardo.core.services.heartbeat import HeartbeatService


class LeonardoApp:
    def __init__(self, config: AppConfig) -> None:
        self._config = config

        # logging context
        run_id_var.set(uuid.uuid4().hex)
        component_var.set("core")

        self._logger = configure_logging(config.logging.level, config.logging.json)

        # audit sinks
        sinks = [InMemoryAuditSink(max_events=config.audit.memory_max_events)]
        if config.audit.enabled and config.audit.file_enabled:
            sinks.append(JsonlAuditSink(Path(config.audit.file_path)))

        self._audit = CompositeAuditSink(*sinks)

        self._error_router = ErrorRouter(self._logger, self._audit)
        self._tasks = TaskManager(error_router=self._error_router, audit=self._audit, logger=self._logger)

        self._ctx = AppContext(
            config=config,
            logger=self._logger,
            audit=self._audit,
            error_router=self._error_router,
            tasks=self._tasks,
        )

        self._services_start_order: list[str] = []

    @classmethod
    async def run_main(cls) -> None:
        config = load_config()
        app = cls(config)
        await app.run()

    async def run(self) -> None:
        await self._startup()
        try:
            # For now: run until Ctrl+C; later this becomes GUI loop / engine loop.
            await self._audit.emit(make_event("lifecycle", "info", "app running"))
            log(self._logger, logging.INFO, "app running")
            while True:
                await asyncio.sleep(0.25)
        except asyncio.CancelledError:
            raise
        except KeyboardInterrupt:
            pass
        finally:
            await self._shutdown(reason="keyboard_interrupt")

    async def _startup(self) -> None:
        await self._audit.emit(make_event("lifecycle", "info", "startup begin", profile=self._config.profile))
        log(self._logger, logging.INFO, "startup begin", profile=self._config.profile)

        # Register services here (CORE only)
        self._register_service(HeartbeatService(interval_s=1.0))

        # Start services
        for name in self._services_start_order:
            svc = self._ctx.services[name]
            try:
                await svc.start(self._ctx)
            except Exception as e:
                await self._error_router.capture(e, where=f"service.start:{name}", fatal=True)
                await self._shutdown(reason=f"startup_failure:{name}")
                raise

        await self._audit.emit(make_event("lifecycle", "info", "startup complete"))
        log(self._logger, logging.INFO, "startup complete")

    def _register_service(self, svc: object) -> None:
        name = getattr(svc, "name", svc.__class__.__name__)
        self._ctx.register_service(name, svc)
        self._services_start_order.append(name)

    async def _shutdown(self, reason: str) -> None:
        await self._audit.emit(make_event("lifecycle", "info", "shutdown begin", reason=reason))
        log(self._logger, logging.INFO, "shutdown begin", reason=reason)

        # Stop services in reverse order
        for name in reversed(self._services_start_order):
            svc = self._ctx.services[name]
            try:
                await svc.stop(self._ctx)
            except Exception as e:
                await self._error_router.capture(e, where=f"service.stop:{name}", fatal=False)

        # Cancel tasks
        await self._tasks.cancel_all(timeout_s=self._config.runtime.shutdown_timeout_s)

        await self._audit.emit(make_event("lifecycle", "info", "shutdown complete"))
        log(self._logger, logging.INFO, "shutdown complete")

        await self._audit.close()
