"""HTTP: one POST helper that streams Server-Sent Events. That is scout's
entire network layer — no SDKs, no dependencies, just urllib."""

import json
import urllib.error
import urllib.request

from .errors import ScoutError


def post_sse(url: str, headers: dict, payload: dict, timeout: int):
    """POST JSON to `url`, yield each SSE `data:` payload as a parsed dict.

    Raises ScoutError with the server's response on HTTP/URL errors.
    """
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", **headers},
        method="POST",
    )
    try:
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
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")[:500]
        raise ScoutError(f"HTTP {e.code} from {url}: {body}") from e
    except urllib.error.URLError as e:
        raise ScoutError(f"cannot reach {url}: {e.reason}") from e
