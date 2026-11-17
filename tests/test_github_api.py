import io
import json
import urllib.error

import pytest

from radar.github_api import GitHubClient, GitHubError


class FakeResponse:
    def __init__(self, payload):
        self.body = json.dumps(payload).encode()

    def read(self):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def http_error(code, body=b"", headers=None):
    return urllib.error.HTTPError("https://api.github.com/graphql", code, "err", headers or {},
                                  io.BytesIO(body))


def client(*responses):
    queue = list(responses)
    sleeps = []

    def urlopen(request, timeout):
        item = queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return FakeResponse(item)

    gh = GitHubClient("token", sleep=sleeps.append, urlopen=urlopen, min_interval=0, search_interval=0)
    return gh, sleeps


RATE = {"cost": 1, "remaining": 4000, "resetAt": "2026-11-16T10:00:00Z"}


def test_retries_server_errors_then_succeeds():
    gh, sleeps = client(http_error(502), {"data": {"x": 1, "rateLimit": RATE}})
    assert gh.graphql("query")["x"] == 1
    assert sleeps and gh.points_used == 1 and gh.remaining == 4000


def test_bad_token_fails_fast():
    gh, _ = client(http_error(401, b"Bad credentials"))
    with pytest.raises(GitHubError, match="401"):
        gh.graphql("query")


def test_secondary_rate_limit_waits():
    gh, sleeps = client(http_error(403, b"You have exceeded a secondary rate limit"),
                        {"data": {"x": 2}})
    assert gh.graphql("query")["x"] == 2
    assert 60.0 in sleeps


def test_plain_403_is_not_retried():
    gh, _ = client(http_error(403, b"Resource not accessible"))
    with pytest.raises(GitHubError):
        gh.graphql("query")


def test_not_found_is_allowed_when_asked():
    payload = {"data": {"nodes": [None]}, "errors": [{"type": "NOT_FOUND", "message": "gone"}]}
    gh, _ = client(payload, payload)
    assert gh.graphql("query", allow_not_found=True) == {"nodes": [None]}
    with pytest.raises(GitHubError, match="gone"):
        gh.graphql("query")


def test_untyped_errors_are_retried():
    gh, sleeps = client({"data": None, "errors": [{"message": "timeout"}]}, {"data": {"ok": True}})
    assert gh.graphql("query") == {"ok": True}
    assert sleeps
