"""The health check of a local model server, before a job that uses it runs.

A job whose agent sets `ANTHROPIC_BASE_URL` talks to a local server. When
that server is down, each trial waits out its timeouts and fails with
NetworkConnectionError, which costs hours and no tokens. The check asks the
server first: `GET <base>/health`, as `llama-server` serves it (PRD,
"Inference server"). A 200 is healthy; a 404 is a server without that
route, and counts as up. A connection error, a timeout or a 5xx (503 while
`llama-server` loads the model) is not.
"""

from __future__ import annotations

import urllib.error
import urllib.request

TIMEOUT_SEC = 10


def check_server(base_url: str) -> str | None:
    """None when the server at `base_url` answers; otherwise what went wrong."""
    url = base_url.rstrip("/") + "/health"
    try:
        with urllib.request.urlopen(url, timeout=TIMEOUT_SEC):
            return None
    except urllib.error.HTTPError as e:
        if e.code < 500:
            return None
        return f"{url} answered HTTP {e.code}"
    except (urllib.error.URLError, OSError, ValueError) as e:
        reason = e.reason if isinstance(e, urllib.error.URLError) else e
        return f"cannot reach {url}: {reason}"
