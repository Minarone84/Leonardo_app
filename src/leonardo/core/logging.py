from __future__ import annotations

import contextvars
import json
import logging
import sys
from datetime import datetime, timezone
from typing import Any

run_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("run_id", default="unknown")
component_var: contextvars.ContextVar[str] = contextvars.ContextVar("component", default="core")
correlation_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("correlation_id", default="-")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "run_id": run_id_var.get(),
            "component": component_var.get(),
            "correlation_id": correlation_id_var.get(),
        }
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        if hasattr(record, "fields") and isinstance(record.fields, dict):
            payload["fields"] = record.fields
        return json.dumps(payload, ensure_ascii=False)


def configure_logging(level: str = "INFO", json_mode: bool = True) -> logging.Logger:
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(level.upper())

    handler = logging.StreamHandler(sys.stdout)
    if json_mode:
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))

    root.addHandler(handler)
    return logging.getLogger("leonardo")


def log(logger: logging.Logger, level: int, msg: str, **fields: Any) -> None:
    logger.log(level, msg, extra={"fields": fields} if fields else None)
