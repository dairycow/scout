"""HTTP: one POST helper that streams Server-Sent Events. That is scout's
entire network layer — no SDKs, no dependencies, just urllib."""

import json
import random
import time
import urllib.error
import urllib.request

from .errors import ScoutError

RETRYABLE = {429, 500, 502, 503, 504, 529}  # 529 = Anthropic overloaded
BACKOFF_CAP = 8.0
RETRY_AFTER_CAP = 30.0


def _post_sse_once(url: str, headers: dict, payload: dict, timeout: int):
    """POST JSON to `url`, yield each SSE `data:` payload as a parsed dict.

    Raises urllib errors; post_sse converts them to ScoutError.
    """
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", **headers},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        for raw in resp:
            line = raw.decode("utf-8", "replace").rstrip("\r\n")
            if not line.startswith("data:"):
                continue
            data = line[len("data:"):].strip()
            if data == "[DONE]":
                break
            if data:
                yield json.loads(data)


def _backoff(attempt: int) -> float:
    """0.5 * 2^n plus jitter, capped at 8s."""
    return min(0.5 * 2**attempt, BACKOFF_CAP) + random.uniform(0, 0.25)


def _retry_after(e: urllib.error.HTTPError):
    """Retry-After header as float seconds (capped), or None if absent."""
    raw = e.headers.get("Retry-After") if e.headers else None
    try:
        return min(float(raw), RETRY_AFTER_CAP)
    except (TypeError, ValueError):
        return None


def post_sse(url: str, headers: dict, payload: dict, timeout: int, retries: int = 2):
    """POST JSON to `url`, yield each SSE `data:` payload as a parsed dict.

    Transient pre-stream failures — HTTP 429/500/502/503/504/529 or a
    URLError — are retried up to `retries` times with backoff. Once the
    first event has yielded, a later failure raises ScoutError
    immediately (retrying would duplicate already-streamed text).
    """
    attempt = 0
    while True:
        started = False
        try:
            for event in _post_sse_once(url, headers, payload, timeout):
                started = True
                yield event
        except urllib.error.HTTPError as e:
            if not started and e.code in RETRYABLE and attempt < retries:
                after = _retry_after(e)
                time.sleep(after if after is not None else _backoff(attempt))
                attempt += 1
                continue
            body = e.read().decode("utf-8", "replace")[:500]
            raise ScoutError(f"HTTP {e.code} from {url}: {body}") from e
        except urllib.error.URLError as e:
            if not started and attempt < retries:
                time.sleep(_backoff(attempt))
                attempt += 1
                continue
            raise ScoutError(f"cannot reach {url}: {e.reason}") from e
        return
