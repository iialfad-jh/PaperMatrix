import ssl
from urllib.error import HTTPError
from urllib.error import URLError

import pytest

from papermatrix.retry import call_with_retries


def test_retries_transient_http_error_then_succeeds():
    calls = []
    delays = []

    def operation():
        calls.append("call")
        if len(calls) == 1:
            raise HTTPError("https://example.org", 503, "unavailable", {}, None)
        return "ok"

    result, attempts = call_with_retries(operation, 2, sleep=delays.append)

    assert result == "ok"
    assert attempts == 2
    assert calls == ["call", "call"]
    assert delays == [1]


def test_does_not_retry_permanent_http_error():
    calls = []

    def operation():
        calls.append("call")
        raise HTTPError("https://example.org", 400, "bad request", {}, None)

    with pytest.raises(HTTPError):
        call_with_retries(operation, 3, sleep=lambda _delay: None)

    assert calls == ["call"]


def test_retry_after_header_controls_delay():
    calls = []
    delays = []

    def operation():
        calls.append("call")
        if len(calls) == 1:
            raise HTTPError("https://example.org", 429, "rate limited", {"Retry-After": "2.5"}, None)
        return "ok"

    call_with_retries(operation, 1, sleep=delays.append)

    assert delays == [2.5]


def test_does_not_retry_certificate_verification_errors():
    calls = []

    def operation():
        calls.append("call")
        raise URLError(ssl.SSLCertVerificationError("invalid certificate"))

    with pytest.raises(URLError):
        call_with_retries(operation, 3, sleep=lambda _delay: None)

    assert calls == ["call"]
