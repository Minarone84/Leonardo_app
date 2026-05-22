from __future__ import annotations

import asyncio
from pathlib import Path
import logging
import uuid
import os

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

from leonardo.connection.exchange import build_default_exchange_registry
from leonardo.core.registry_keys import SVC_EXCHANGE_REGISTRY, SVC_HISTORICAL_DATASET
from leonardo.data.historical.dataset_service import HistoricalDatasetService


class LeonardoApp:
    """Composition root and lifecycle coordinator for the Leonardo core.

    This class is responsible for constructing the core runtime singletons,
    wiring runtime services and capability providers into the application
    context, and executing the high-level startup/run/shutdown sequence.

    Notes:
        The current implementation remains intentionally small. It provides the
        phase-2 runtime spine while preserving the existing application
        behavior and smoke-test hooks.
    """

    def __init__(self, config: AppConfig) -> None:
        """Build the core runtime objects required for application startup.

        Args:
            config: Fully loaded application configuration.
        """
        self._config = config

        # Establish the base logging context once for the current app run so
        # downstream logs and audit events can be correlated consistently.
        run_id_var.set(uuid.uuid4().hex)
        component_var.set("core")

        self._logger = configure_logging(config.logging.level, config.logging.json)

        # Build the audit fan-out first because both runtime state transitions
        # and error routing depend on it during startup and shutdown.
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

        # Startup order is captured explicitly so shutdown can unwind services
        # deterministically in reverse order.
        self._services_start_order: list[str] = []

    @classmethod
    async def run_main(cls) -> None:
        """Load configuration, construct the app, and run it to completion."""
        config = load_config()
        app = cls(config)
        await app.run()

    @property
    def context(self) -> AppContext:
        """Return the fully-initialized application context for the current runtime.

        The returned ``AppContext`` is the authoritative container for all core
        runtime dependencies, including:

            - configuration (``config``)
            - logging infrastructure (``logger``)
            - audit pipeline (``audit``)
            - error routing (``error_router``)
            - task supervision (``tasks``)
            - registered services and capability providers (``services``)
            - runtime state store (``state``)

        This property is the *only supported access point* for external consumers
        (e.g. GUI bridge, integration layers) to interact with the core runtime.

        Lifecycle expectations:
            - Before ``startup()``:
                The context exists but is *not fully initialized*.
                Services may not be registered and lifecycle services are not started.
                Consumers MUST NOT assume availability of any capability providers.

            - After ``startup()`` completes:
                The context is fully initialized.
                All capability providers (e.g. HistoricalDatasetService) are registered.
                All lifecycle-managed services are started and in a consistent state.

            - After ``shutdown()``:
                The context remains accessible for inspection (e.g. audit snapshots),
                but services may be stopped and should be considered inactive.

        Threading model:
            The context is owned by the core event loop thread. External callers
            (such as the GUI) must NOT mutate context state directly. All mutations
            must be performed via coroutines submitted to the core loop.

        Returns:
            AppContext: The current runtime context instance.
        """
        return self._ctx

    async def startup(self) -> None:
        """Execute the full core runtime startup sequence.

        This method is the public entry point for initializing the Leonardo core
        when it is hosted by an external runtime (e.g. CoreRunner in a GUI
        application). It performs the same initialization logic as ``run()``,
        but without entering the main idle loop.

        Responsibilities:
            - Set application lifecycle state to "starting"
            - Emit structured audit events for startup begin/end
            - Register all capability providers (e.g. HistoricalDatasetService)
            - Register all lifecycle-managed services
            - Start lifecycle services in deterministic order
            - Transition application state to "running"

        Guarantees after successful completion:
            - ``self.context`` is fully initialized and safe for consumption
            - All required services are registered and available via
              ``ctx.get_service(...)`` or ``ctx.registry.get(...)``
            - Lifecycle services are running and tracked in the state store
            - Application lifecycle state is ``"running"``

        Idempotency:
            This method is not strictly idempotent. It is expected to be called
            exactly once per application lifecycle. Calling it multiple times may
            result in duplicate service registration or inconsistent state.

        Error handling:
            If any service fails to start, the method updates runtime state,
            emits audit and error events, performs partial shutdown cleanup,
            and re-raises the failure.

        Raises:
            Exception: Propagates any startup failure after partial cleanup.
        """
        await self._startup()
        await self._audit.emit(make_event("lifecycle", "info", "app running"))
        await self._ctx.state.set_app_status("running", where="core.startup")
        log(self._logger, logging.INFO, "app running")

    async def shutdown(self, reason: str = "gui_stop") -> None:
        """Execute the full core runtime shutdown sequence.

        This method is the public entry point for gracefully stopping the Leonardo
        core runtime when it is hosted externally (e.g. GUI-driven shutdown).

        Responsibilities:
            - Transition application state to "stopping"
            - Emit structured audit event for shutdown begin
            - Stop all lifecycle-managed services in reverse startup order
            - Cancel all tracked background tasks with a bounded timeout
            - Emit shutdown completion audit event
            - Transition application state to "stopped"
            - Flush and close audit sinks

        Shutdown order:
            Lifecycle services are stopped in *reverse registration order* to ensure
            that dependencies are unwound safely and predictably.

        Reason parameter:
            The ``reason`` string is recorded in audit logs and runtime state to
            provide traceability for why the shutdown occurred.

            Common values:
                - "gui_stop"          → user closed the GUI
                - "core_runner_stop"  → host requested shutdown
                - "keyboard_interrupt"
                - "startup_failure:<service_name>"

        Threading model:
            This method must be executed on the core event loop. External callers
            (e.g. GUI thread) should invoke it via a submission mechanism such as
            ``CoreRunner.submit(...)``.

        Idempotency:
            This method is safe to call once per lifecycle. Repeated calls after
            shutdown has completed are undefined and should be avoided.

        Guarantees after completion:
            - All lifecycle services are stopped or marked as failed
            - No background tasks remain running (subject to timeout constraints)
            - Audit pipeline has been flushed and closed
            - Application state is "stopped"

        Raises:
            Exceptions during shutdown are captured and routed through the error
            router. The shutdown process continues on best-effort basis to ensure
            maximum cleanup.
        """
        await self._shutdown(reason)
        
    async def run(self) -> None:
        """Execute the main lifecycle loop for the current application run.

        The method delegates lifecycle setup to ``_startup()``, transitions the
        application into the running state, optionally executes the historical
        smoke test, and otherwise keeps the core alive until interrupted.
        """
        await self._startup()
        try:
            # For now the runtime remains alive through a simple idle loop. This
            # preserves current behavior until the GUI or engine loop becomes
            # the primary top-level driver.
            await self._audit.emit(make_event("lifecycle", "info", "app running"))
            await self._ctx.state.set_app_status("running", where="core.run")
            log(self._logger, logging.INFO, "app running")

            # Optional core-only smoke path used to validate historical dataset
            # access without changing the default runtime entry behavior.
            if os.environ.get("LEONARDO_SMOKE_HISTORICAL") == "1":
                await self._smoke_test_historical()
                return

            while True:
                await asyncio.sleep(0.25)

        except asyncio.CancelledError:
            raise
        except KeyboardInterrupt:
            pass
        finally:
            # Preserve the existing reason semantics so shutdown audit trails
            # remain stable for both normal and smoke-test execution paths.
            reason = "keyboard_interrupt" if os.environ.get("LEONARDO_SMOKE_HISTORICAL") != "1" else "smoke_test_done"
            await self._shutdown(reason=reason)

    async def _startup(self) -> None:
        """Initialize runtime state, register services, and start them.

        This method establishes the application lifecycle status, registers
        capability providers that do not participate in lifecycle management,
        registers core lifecycle services, and starts each tracked service in
        startup order.
        """
        await self._ctx.state.set_app_status("starting", where="core.startup")
        await self._audit.emit(make_event("lifecycle", "info", "startup begin", profile=self._config.profile))
        log(self._logger, logging.INFO, "startup begin", profile=self._config.profile)

        data_root = Path(self._config.runtime.data_dir)

        self._ctx.register_service(SVC_EXCHANGE_REGISTRY, build_default_exchange_registry())

        # Historical dataset access is a capability provider, not a lifecycle-
        # managed service. It is registered explicitly for lookup through the
        # application context without routing through the compatibility registry.
        self._ctx.register_service(
            SVC_HISTORICAL_DATASET,
            HistoricalDatasetService(
                data_root=data_root,
                slice_cache_entries=256,
            ),
        )

        # Register core lifecycle services before attempting to start them.
        await self._register_service(HeartbeatService(interval_s=1.0))

        # Start services in deterministic order and reflect each transition into
        # the runtime state store for observability and diagnostics.
        for name in self._services_start_order:
            svc = self._ctx.services[name]
            try:
                await self._ctx.state.set_service_status(name, "starting", where="core.startup")
                await svc.start(self._ctx)
                await self._ctx.state.set_service_status(name, "running", where="core.startup")
            except Exception as e:
                await self._ctx.state.set_service_status(name, "failed", where="core.startup", error=str(e))
                await self._ctx.state.set_app_status("failed", where="core.startup")
                await self._error_router.capture(e, where=f"service.start:{name}", fatal=True)
                await self._shutdown(reason=f"startup_failure:{name}")
                raise

        await self._audit.emit(make_event("lifecycle", "info", "startup complete"))
        log(self._logger, logging.INFO, "startup complete")

    async def _register_service(self, svc: object) -> None:
        """Register a lifecycle-managed service with runtime tracking.

        Args:
            svc: Service instance exposing a stable runtime name and lifecycle
                contract.
        """
        name = getattr(svc, "name", svc.__class__.__name__)
        self._ctx.register_lifecycle_service(name, svc)
        self._services_start_order.append(name)
        await self._ctx.state.register_service(name, where="core.register_service")

    async def _shutdown(self, reason: str) -> None:
        """Stop services, cancel tasks, and close the audit pipeline.

        Args:
            reason: High-level shutdown reason used for audit and diagnostics.
        """
        await self._ctx.state.set_app_status("stopping", where="core.shutdown")
        await self._audit.emit(make_event("lifecycle", "info", "shutdown begin", reason=reason))
        log(self._logger, logging.INFO, "shutdown begin", reason=reason)

        # Unwind lifecycle services in reverse startup order so dependencies are
        # stopped in a predictable and safer sequence.
        for name in reversed(self._services_start_order):
            svc = self._ctx.services[name]
            try:
                await self._ctx.state.set_service_status(name, "stopping", where="core.shutdown")
                await svc.stop(self._ctx)
                await self._ctx.state.set_service_status(name, "stopped", where="core.shutdown")
            except Exception as e:
                await self._ctx.state.set_service_status(name, "failed", where="core.shutdown", error=str(e))
                await self._error_router.capture(e, where=f"service.stop:{name}", fatal=False)

        # Cancel tracked background tasks only after service stop requests have
        # been issued, so cooperative shutdown paths have a chance to run first.
        await self._tasks.cancel_all(timeout_s=self._config.runtime.shutdown_timeout_s)

        await self._audit.emit(make_event("lifecycle", "info", "shutdown complete"))
        await self._ctx.state.set_app_status("stopped", where="core.shutdown")
        log(self._logger, logging.INFO, "shutdown complete")

        await self._audit.close()

    async def _smoke_test_historical(self) -> None:
        """Exercise historical dataset access through explicit service lookup.

        This helper is intentionally scoped to the temporary smoke-test flow
        used during core bring-up. It validates that the historical dataset
        capability is available and that slice retrieval works end to end.
        """
        from leonardo.data.historical.dataset_service import DatasetId, SliceRequest

        try:
            svc = self._ctx.get_service(SVC_HISTORICAL_DATASET, HistoricalDatasetService)
        except (KeyError, TypeError) as exc:
            raise RuntimeError("HistoricalDatasetService not registered in application context") from exc

        dataset = DatasetId(
            exchange="bybit",
            market_type="linear",
            symbol="BTCUSDT",
            timeframe="1h",
        )

        self._logger.info("SMOKE: opening dataset")

        meta = await svc.open_dataset(dataset)

        self._logger.info(
            "SMOKE: dataset meta",
            extra={"fields": {
                "first_ts": meta.first_ts_ms,
                "last_ts": meta.last_ts_ms,
                "count": meta.count,
            }},
        )

        req = SliceRequest(
            tab_id="smoke",
            request_id="smoke-1",
            dataset_id=dataset,
            center_ts_ms=meta.last_ts_ms,
            visible_max=1000,
            buffer_left=500,
            buffer_right=500,
            reason="initial",
        )

        slice_payload = await svc.get_slice(req)

        self._logger.info(
            "SMOKE: slice received",
            extra={"fields": {
                "slice_len": len(slice_payload.ts_ms),
                "base_index": slice_payload.base_index,
                "has_more_left": slice_payload.has_more_left,
                "has_more_right": slice_payload.has_more_right,
            }},
        )
