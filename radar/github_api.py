"""Minimal GitHub GraphQL client using only the standard library.

Handles pacing between calls, retries with backoff, secondary rate limits, and the hourly
point budget (every query asks for `rateLimit`, so the client always knows what's left).
"""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any, Callable

log = logging.getLogger(__name__)

API_URL = "https://api.github.com/graphql"
RATE_FIELDS = "rateLimit { cost remaining resetAt }"
LOW_BUDGET = 50  # points left before the client waits for the hourly reset


class GitHubError(RuntimeError):
    pass


class GitHubClient:
    def __init__(
        self,
        token: str,
        *,
        min_interval: float = 0.5,
        search_interval: float = 2.0,
        max_attempts: int = 6,
        timeout: float = 90,
        sleep: Callable[[float], None] = time.sleep,
        urlopen: Callable[..., Any] = urllib.request.urlopen,
        clock: Callable[[], float] = time.monotonic,
    ):
        self._token = token
        self._min_interval = min_interval
        self._search_interval = search_interval
        self._max_attempts = max_attempts
        self._timeout = timeout
        self._sleep = sleep
        self._urlopen = urlopen
        self._clock = clock
        self._last_call = float("-inf")
        self.points_used = 0
        self.remaining: int | None = None
        self.calls = 0

    def graphql(
        self,
        query: str,
        variables: dict | None = None,
        *,
        search: bool = False,
        allow_not_found: bool = False,
    ) -> dict:
        """Run a query and return its `data`. NOT_FOUND errors are fine when allowed."""
        body = json.dumps({"query": query, "variables": variables or {}}).encode("utf-8")
        delay = 5.0
        for attempt in range(1, self._max_attempts + 1):
            self._pace(self._search_interval if search else self._min_interval)
            request = urllib.request.Request(
                API_URL,
                data=body,
                method="POST",
                headers={
                    "Authorization": f"bearer {self._token}",
                    "Content-Type": "application/json",
                    "User-Agent": "oss-radar",
                },
            )
            self.calls += 1
            try:
                with self._urlopen(request, timeout=self._timeout) as response:
                    payload = json.loads(response.read().decode("utf-8"))
            except urllib.error.HTTPError as err:
                detail = err.read()[:500].decode("utf-8", "replace")
                wait = _retry_wait(err.code, err.headers or {}, detail, delay)
                if wait is None or attempt == self._max_attempts:
                    raise GitHubError(f"GitHub API HTTP {err.code}: {detail}") from err
                log.warning("GitHub API HTTP %s; retrying in %.0fs", err.code, wait)
                self._sleep(wait)
                delay = min(delay * 2, 300)
                continue
            except (urllib.error.URLError, TimeoutError, ConnectionError) as err:
                if attempt == self._max_attempts:
                    raise GitHubError(f"GitHub API unreachable: {err}") from err
                log.warning("GitHub API unreachable (%s); retrying in %.0fs", err, delay)
                self._sleep(delay)
                delay = min(delay * 2, 300)
                continue

            data = payload.get("data")
            errors = payload.get("errors") or []
            if errors:
                types = {error.get("type") for error in errors}
                messages = "; ".join(str(error.get("message", "")) for error in errors)[:500]
                if "RATE_LIMITED" in types and attempt < self._max_attempts:
                    log.warning("GitHub rate limit hit; waiting 60s")
                    self._sleep(60)
                    continue
                if not (allow_not_found and data is not None and types <= {"NOT_FOUND"}):
                    # Search occasionally times out server-side; those errors have no type
                    if None in types and attempt < self._max_attempts:
                        log.warning("GitHub query failed (%s); retrying in %.0fs", messages, delay)
                        self._sleep(delay)
                        delay = min(delay * 2, 300)
                        continue
                    raise GitHubError(f"GitHub API error: {messages}")
            self._track(data or {})
            return data or {}
        raise GitHubError("GitHub API: out of retries")

    def _pace(self, interval: float) -> None:
        wait = self._last_call + interval - self._clock()
        if wait > 0:
            self._sleep(wait)
        self._last_call = self._clock()

    def _track(self, data: dict) -> None:
        rate = data.get("rateLimit")
        if not rate:
            return
        self.points_used += rate.get("cost") or 0
        self.remaining = rate.get("remaining")
        if self.remaining is not None and self.remaining < LOW_BUDGET:
            reset = datetime.fromisoformat(rate["resetAt"].replace("Z", "+00:00"))
            wait = max(0.0, (reset - datetime.now(timezone.utc)).total_seconds()) + 5
            log.warning("GitHub points nearly used up (%s left); waiting %.0fs", self.remaining, wait)
            self._sleep(wait)


def _retry_wait(code: int, headers: Any, detail: str, delay: float) -> float | None:
    """Seconds to wait before retrying, or None when retrying won't help."""
    if code in (502, 503, 504):
        return delay
    if code in (403, 429):
        if headers.get("retry-after"):
            return float(headers["retry-after"]) + 1
        if headers.get("x-ratelimit-remaining") == "0" and headers.get("x-ratelimit-reset"):
            return max(0.0, float(headers["x-ratelimit-reset"]) - time.time()) + 5
        if code == 429 or "rate limit" in detail.lower():
            return 60.0  # secondary rate limit without a hint
    return None
