"""
Structured (JSON) logging configuration for AI Ops Copilot.

Call `setup_logging()` once at application startup (in main.py).
Every other module should create its own logger with:

    import logging
    logger = logging.getLogger(__name__)

JSON format emitted to stdout (Render captures stdout → log stream):

    {
      "timestamp": "2026-09-10T01:00:00.000Z",
      "level":     "ERROR",
      "logger":    "routes.projects",
      "message":   "Failed to create project",
      "exc_info":  "<full traceback>",
      "context":   {"user_id": "...", "project_id": "..."}
    }
"""

import json
import logging
import sys
import traceback
from datetime import datetime, timezone


class _JsonFormatter(logging.Formatter):
    """Emit one JSON object per log record."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict = {
            "timestamp": datetime.fromtimestamp(
                record.created, tz=timezone.utc
            ).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
            "level":   record.levelname,
            "logger":  record.name,
            "message": record.getMessage(),
        }

        # Attach structured context if the caller passed `extra={"context": {...}}`
        if hasattr(record, "context"):
            payload["context"] = record.context

        # Attach full traceback when called via logger.exception(...)
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)

        return json.dumps(payload)


def setup_logging(level: str = "INFO") -> None:
    """
    Configure the root logger with structured JSON output to stdout.
    Call this exactly once, at the top of main.py before the app starts.
    """
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(_JsonFormatter())

    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Avoid duplicate handlers if called more than once (e.g., during tests)
    if not root.handlers:
        root.addHandler(handler)
    else:
        root.handlers.clear()
        root.addHandler(handler)
