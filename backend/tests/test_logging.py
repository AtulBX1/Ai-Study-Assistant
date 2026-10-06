"""Tests for structured log formatting and request correlation."""

import json
import logging

from app.logging_config import JsonFormatter, RequestIdFilter, request_id_context


def test_json_formatter_includes_request_id() -> None:
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="request handled",
        args=(),
        exc_info=None,
    )
    token = request_id_context.set("test-request-456")
    try:
        RequestIdFilter().filter(record)
        payload = json.loads(JsonFormatter().format(record))
    finally:
        request_id_context.reset(token)

    assert payload["level"] == "INFO"
    assert payload["message"] == "request handled"
    assert payload["request_id"] == "test-request-456"
