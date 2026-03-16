from __future__ import annotations

import logging
from typing import Any

from leonardo.core.audit import AuditSink, make_event
from leonardo.core.logging import log


class ErrorRouter:
    """
    Central exception routing:
      - structured log with traceback
      - audit event for GUI / product-level visibility later
    """

    def __init__(self, logger: logging.Logger, audit: AuditSink) -> None:
        self._logger = logger
        self._audit = audit

    async def capture(self, exc: BaseException, *, where: str, fatal: bool = False, **fields: Any) -> None:
        log(self._logger, logging.ERROR, "exception captured", where=where, fatal=fatal, **fields)
        self._logger.exception("traceback", exc_info=exc)

        await self._audit.emit(
            make_event(
                event_type="error",
                severity="fatal" if fatal else "error",
                message=str(exc),
                where=where,
                fatal=fatal,
                **fields,
            )
        )
