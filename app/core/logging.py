"""
Structured JSON logging configuration.

The formatter deliberately uses the Python standard library. It produces one JSON
object per line for log aggregation without introducing an additional dependency.
Sensitive request bodies, headers, credentials, and tokens are never recorded.
"""

import json
import logging
from datetime import UTC, datetime
from typing import Any

from app.core.middleware import get_request_id

_STANDARD_RECORD_ATTRIBUTES = set(logging.LogRecord("", 0, "", 0, "", (), None).__dict__)
_STANDARD_RECORD_ATTRIBUTES.update({"message", "asctime"})


class JsonFormatter(logging.Formatter):
    """Serialize log records into a stable, aggregation-friendly JSON shape."""

    def format(self, record: logging.LogRecord) -> str:
        # Driver diagnostics may carry SQL literals or rejected record values even
        # when SQLAlchemy hide_parameters=True. Keep infrastructure records opaque.
        if record.name.startswith(("sqlalchemy.", "asyncpg.")):
            return json.dumps(
                {
                    "timestamp": datetime.now(UTC).isoformat(),
                    "level": record.levelname,
                    "logger": record.name,
                    "message": "database_driver_event",
                    "request_id": get_request_id(),
                }
            )
        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": get_request_id(),
        }
        for key, value in record.__dict__.items():
            if key not in _STANDARD_RECORD_ATTRIBUTES and not key.startswith("_"):
                payload[key] = value
        if record.exc_info:
            # Stack traces remain server-side and are serialized for log collectors.
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str, separators=(",", ":"))


def configure_logging(log_level: str) -> None:
    """Configure root logging once with the selected validated level."""
    root_logger = logging.getLogger()
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(log_level)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
