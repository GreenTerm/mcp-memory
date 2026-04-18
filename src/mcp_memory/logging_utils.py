from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class RuntimeLogFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        timestamp = self.formatTime(record, "%Y-%m-%d %H:%M:%S")
        component = getattr(record, "component", record.name.rsplit(".", 1)[-1])
        event = getattr(record, "event", "log")
        fields = getattr(record, "fields", {})
        parts = [timestamp, record.levelname, component, event]
        if isinstance(fields, dict):
            for key in sorted(fields):
                value = fields[key]
                if value is None:
                    continue
                text = str(value).replace("\r", "\\r").replace("\n", "\\n")
                parts.append(f"{key}={text}")
        if record.getMessage():
            parts.append(f"message={record.getMessage()}")
        if record.exc_info:
            parts.append(self.formatException(record.exc_info).replace("\n", "\\n"))
        return " ".join(parts)


def get_logger(component: str) -> logging.Logger:
    logger = logging.getLogger(f"mcp_memory.{component}")
    if not logger.handlers:
        logger.addHandler(logging.NullHandler())
    return logger


def configure_logging(component: str, level: str = "INFO", log_path: Path | None = None) -> logging.Logger:
    logger = logging.getLogger(f"mcp_memory.{component}")
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()
    logger.setLevel(_resolve_level(level))
    logger.propagate = False

    formatter = RuntimeLogFormatter()

    console_handler = logging.StreamHandler()
    console_handler.setLevel(logger.level)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    if log_path is not None:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_path, encoding="utf-8")
        file_handler.setLevel(logger.level)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    return logger


def log_event(logger: logging.Logger, level: int, event: str, **fields: Any) -> None:
    logger.log(level, "", extra={"component": _component_name(logger), "event": event, "fields": fields})


def shutdown_logging(prefix: str = "mcp_memory") -> None:
    manager = logging.Logger.manager
    for name, value in list(manager.loggerDict.items()):
        if not isinstance(value, logging.Logger):
            continue
        if not name.startswith(prefix):
            continue
        for handler in list(value.handlers):
            value.removeHandler(handler)
            handler.close()


@dataclass(slots=True)
class RequestLogContext:
    method: str
    path: str
    started_at: float

    def finish(self, logger: logging.Logger, event: str, status: int, **fields: Any) -> None:
        log_event(
            logger,
            logging.INFO if status < 400 else logging.WARNING,
            event,
            method=self.method,
            path=self.path,
            status=status,
            duration_ms=int((time.perf_counter() - self.started_at) * 1000),
            **fields,
        )


def start_request_log(method: str, path: str) -> RequestLogContext:
    return RequestLogContext(method=method, path=path, started_at=time.perf_counter())


def _resolve_level(level: str) -> int:
    return getattr(logging, str(level).upper(), logging.INFO)


def _component_name(logger: logging.Logger) -> str:
    return logger.name.rsplit(".", 1)[-1]
