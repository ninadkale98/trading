"""Logging to the database (events timeline, errors) and to rotating files in logs/."""
from __future__ import annotations

import json
import logging
import logging.handlers
import traceback as tb

from core.config import ROOT
from core.db import execute

_file_logger: logging.Logger | None = None


def file_logger() -> logging.Logger:
    global _file_logger
    if _file_logger is None:
        (ROOT / "logs").mkdir(exist_ok=True)
        lg = logging.getLogger("tradebot")
        lg.setLevel(logging.INFO)
        h = logging.handlers.RotatingFileHandler(ROOT / "logs" / "tradebot.log", maxBytes=20_000_000, backupCount=5)
        h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(threadName)s %(message)s"))
        lg.addHandler(h)
        _file_logger = lg
    return _file_logger


def event(kind: str, message: str, data: dict | None = None, level: str = "info", task_id: int | None = None) -> None:
    """Add a line to the 'Today' timeline. Never raises: logging must not break a job."""
    file_logger().log(getattr(logging, level.upper(), logging.INFO), f"[{kind}] {message}")
    try:
        execute(
            "INSERT INTO events (level, kind, message, data, task_id) VALUES (%s, %s, %s, %s, %s)",
            (level, kind, message, json.dumps(data, default=str) if data else None, task_id),
        )
    except Exception as e:  # pragma: no cover
        file_logger().error(f"event log failed: {e}")


def error(exc: BaseException, task_id: int | None = None, task_type: str | None = None) -> None:
    trace = "".join(tb.format_exception(exc))
    file_logger().error(f"[{task_type}#{task_id}] {type(exc).__name__}: {exc}\n{trace}")
    try:
        execute(
            "INSERT INTO errors (task_id, task_type, error_type, message, traceback) VALUES (%s, %s, %s, %s, %s)",
            (task_id, task_type, type(exc).__name__, str(exc)[:2000], trace[-8000:]),
        )
    except Exception as e:  # pragma: no cover
        file_logger().error(f"error log failed: {e}")
