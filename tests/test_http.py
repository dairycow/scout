"""Tests for post_sse retry/backoff, with urlopen and sleep faked
(no network)."""

import email.message
import io
import urllib.error

import pytest

from scout import http
from scout.errors import ScoutError


def sse_response(*events):
    """A context-manager response whose body is one `data:` line per event."""
    lines = [f'data: {e}\n'.encode() for e in events]
    return FakeResponse(lines)


class FakeResponse:
    def __init__(self, lines):
        self._lines = lines

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def __iter__(self):
        return iter(self._lines)


class ExplodingResponse(FakeResponse):
    """Yields its lines, then the connection dies mid-stream."""

    def __iter__(self):
        for line in self._lines:
            yield line
        raise urllib.error.URLError("connection reset")


def http_error(code, body="", headers=None):
    hdrs = email.message.Message()
    for key, value in (headers or {}).items():
        hdrs[key] = value
    return urllib.error.HTTPError("https://x", code, "err", hdrs,
                                  io.BytesIO(body.encode()))


@pytest.fixture
def no_jitter(monkeypatch):
    monkeypatch.setattr(http.random, "uniform", lambda a, b: 0.0)


class Script:
    """urlopen stand-in popping one scripted outcome per call."""

    def __init__(self, *outcomes):
        self.outcomes = list(outcomes)
        self.calls = 0

    def __call__(self, req, timeout=None):
        self.calls += 1
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def test_429_then_success(monkeypatch, no_jitter):
    script = Script(http_error(429), http_error(429), sse_response('{"a": 1}'))
    slept = []
    monkeypatch.setattr(http.urllib.request, "urlopen", script)
    monkeypatch.setattr(http.time, "sleep", slept.append)
    got = list(http.post_sse("https://x", {}, {}, 5, retries=2))
    assert got == [{"a": 1}]
    assert script.calls == 3
    assert slept == [0.5, 1.0]  # 0.5 * 2^0, 0.5 * 2^1, jitter zeroed


def test_retry_after_header_honored(monkeypatch):
    script = Script(http_error(429, headers={"Retry-After": "3"}),
                    sse_response('{"a": 1}'))
    slept = []
    monkeypatch.setattr(http.urllib.request, "urlopen", script)
    monkeypatch.setattr(http.time, "sleep", slept.append)
    got = list(http.post_sse("https://x", {}, {}, 5))
    assert got == [{"a": 1}]
    assert slept == [3.0]


def test_retry_after_capped_at_30s(monkeypatch):
    script = Script(http_error(503, headers={"Retry-After": "600"}),
                    http_error(503))
    slept = []
    monkeypatch.setattr(http.urllib.request, "urlopen", script)
    monkeypatch.setattr(http.time, "sleep", slept.append)
    with pytest.raises(ScoutError, match="HTTP 503"):
        list(http.post_sse("https://x", {}, {}, 5, retries=1))
    assert slept == [30.0]


def test_non_retryable_raises_immediately(monkeypatch, no_jitter):
    script = Script(http_error(400, body='{"error": "bad"}'))
    slept = []
    monkeypatch.setattr(http.urllib.request, "urlopen", script)
    monkeypatch.setattr(http.time, "sleep", slept.append)
    with pytest.raises(ScoutError, match="HTTP 400.*bad"):
        list(http.post_sse("https://x", {}, {}, 5))
    assert script.calls == 1 and slept == []


def test_exhaustion_raises_with_last_body(monkeypatch, no_jitter):
    err = http_error(503, body="overloaded")
    script = Script(err, http_error(503, body="overloaded again"),
                    http_error(503, body="overloaded again"))
    monkeypatch.setattr(http.urllib.request, "urlopen", script)
    monkeypatch.setattr(http.time, "sleep", lambda s: None)
    with pytest.raises(ScoutError, match="overloaded again"):
        list(http.post_sse("https://x", {}, {}, 5, retries=2))
    assert script.calls == 3


def test_urlerror_retried_then_success(monkeypatch, no_jitter):
    script = Script(urllib.error.URLError("refused"), sse_response('{"a": 1}'))
    slept = []
    monkeypatch.setattr(http.urllib.request, "urlopen", script)
    monkeypatch.setattr(http.time, "sleep", slept.append)
    got = list(http.post_sse("https://x", {}, {}, 5))
    assert got == [{"a": 1}]
    assert slept == [0.5]


def test_midstream_failure_not_retried(monkeypatch):
    script = Script(ExplodingResponse(['data: {"a": 1}\n'.encode()]))
    monkeypatch.setattr(http.urllib.request, "urlopen", script)
    monkeypatch.setattr(http.time, "sleep",
                        lambda s: (_ for _ in ()).throw(AssertionError("no retry")))
    got = []
    with pytest.raises(ScoutError, match="cannot reach"):
        for event in http.post_sse("https://x", {}, {}, 5):
            got.append(event)
    assert got == [{"a": 1}]  # the event before the failure was delivered
    assert script.calls == 1


def test_done_sentinel_stops(monkeypatch):
    script = Script(sse_response('{"a": 1}', "[DONE]", '{"b": 2}'))
    monkeypatch.setattr(http.urllib.request, "urlopen", script)
    got = list(http.post_sse("https://x", {}, {}, 5))
    assert got == [{"a": 1}]
