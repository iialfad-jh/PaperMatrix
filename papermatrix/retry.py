from __future__ import annotations

import time
import ssl
from collections.abc import Callable
from typing import TypeVar
from urllib.error import HTTPError, URLError


T = TypeVar("T")
TRANSIENT_STATUS_CODES = {408, 409, 429}


def call_with_retries(
    operation: Callable[[], T],
    retries: int,
    *,
    sleep: Callable[[float], None] | None = None,
) -> tuple[T, int]:
    sleep = sleep or time.sleep
    attempts = 0
    while True:
        attempts += 1
        try:
            return operation(), attempts
        except Exception as exc:
            if attempts > retries or not is_transient_error(exc):
                raise
            sleep(_retry_delay(exc, attempts))


def is_transient_error(exc: Exception) -> bool:
    status_code = error_status_code(exc)
    if status_code is not None:
        return status_code in TRANSIENT_STATUS_CODES or 500 <= status_code <= 599
    if isinstance(exc, URLError) and isinstance(exc.reason, ssl.SSLCertVerificationError):
        return False
    if isinstance(exc, (TimeoutError, ConnectionError, URLError)):
        return True
    error_name = exc.__class__.__name__.lower()
    return "timeout" in error_name or "connection" in error_name or "ratelimit" in error_name


def error_status_code(exc: Exception) -> int | None:
    status_code = getattr(exc, "status_code", None)
    if status_code is None and isinstance(exc, HTTPError):
        status_code = exc.code
    try:
        return int(status_code) if status_code is not None else None
    except (TypeError, ValueError):
        return None


def _retry_delay(exc: Exception, attempts: int) -> float:
    headers = getattr(exc, "headers", None)
    if headers is None:
        response = getattr(exc, "response", None)
        headers = getattr(response, "headers", None)
    if headers is not None:
        retry_after = headers.get("retry-after") or headers.get("Retry-After")
        try:
            if retry_after is not None:
                return min(max(float(retry_after), 0.0), 60.0)
        except (TypeError, ValueError):
            pass
    return min(2 ** (attempts - 1), 30.0)
