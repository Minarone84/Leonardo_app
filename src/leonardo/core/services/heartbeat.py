from __future__ import annotations

import asyncio
import logging

from leonardo.core.context import AppContext
from leonardo.core.audit import make_event
from leonardo.core.logging import log


class HeartbeatService:
    """
    Dummy service proving:
      - start/stop hooks
      - background task management
      - audit + structured logging
    """
    name = "heartbeat"

    def __init__(self, interval_s: float = 1.0) -> None:
        self._interval_s = interval_s
        self._running = False

    async def start(self, ctx: AppContext) -> None:
        self._running = True
        await ctx.audit.emit(make_event("service", "info", "heartbeat starting"))
        log(ctx.logger, logging.INFO, "heartbeat service start", interval_s=self._interval_s)

        ctx.tasks.create(
            "heartbeat.loop",
            self._loop(ctx),
            critical=False,
            where="service",
        )

    async def stop(self, ctx: AppContext) -> None:
        self._running = False
        await ctx.audit.emit(make_event("service", "info", "heartbeat stopping"))
        log(ctx.logger, logging.INFO, "heartbeat service stop")

    async def _loop(self, ctx: AppContext) -> None:
        n = 0
        while self._running:
            n += 1
            await ctx.audit.emit(make_event("heartbeat", "debug", "tick", n=n))
            log(ctx.logger, logging.DEBUG, "heartbeat tick", n=n)
            await asyncio.sleep(self._interval_s)
