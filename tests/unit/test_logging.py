"""Unit tests for the structured logging contract."""

import json
import logging

from app.core.logging import JsonFormatter


def test_json_formatter_emits_core_and_context_fields() -> None:
    record = logging.LogRecord(
        name="test.logger",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="operation_finished",
        args=(),
        exc_info=None,
    )
    record.operation = "health_check"

    payload = json.loads(JsonFormatter().format(record))

    assert payload["level"] == "INFO"
    assert payload["message"] == "operation_finished"
    assert payload["operation"] == "health_check"
    assert payload["request_id"] == "unavailable"
