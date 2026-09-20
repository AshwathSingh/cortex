import httpx
import pytest

from app.github.client import (
    GitHubClient,
    InvalidRepoURL,
    RateLimitExceeded,
    RepoNotFound,
    parse_repo_url,
)


def make_client(handler, **kwargs):
    return GitHubClient(transport=httpx.MockTransport(handler), sleep=lambda s: None, **kwargs)


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://github.com/octo/cat", ("octo", "cat")),
        ("https://github.com/octo/cat/", ("octo", "cat")),
        ("https://github.com/octo/cat.git", ("octo", "cat")),
        ("https://github.com/octo/cat/pulls", ("octo", "cat")),
    ],
)
def test_parse_valid(url, expected):
    assert parse_repo_url(url) == expected


@pytest.mark.parametrize(
    "url",
    ["", "not a url", "https://gitlab.com/a/b", "https://github.com/onlyowner", "ftp://github.com/a/b"],
)
def test_parse_invalid(url):
    with pytest.raises(InvalidRepoURL):
        parse_repo_url(url)


def test_pagination_follows_next_links():
    def handler(request: httpx.Request) -> httpx.Response:
        page = request.url.params.get("page", "1")
        if page == "1":
            return httpx.Response(
                200,
                json=[{"number": 1}],
                headers={"Link": '<https://api.github.com/repos/o/r/pulls?page=2>; rel="next"'},
            )
        return httpx.Response(200, json=[{"number": 2}])

    client = make_client(handler)
    assert [p["number"] for p in client.iter_pull_requests("o", "r")] == [1, 2]


def test_issues_exclude_pull_requests():
    def handler(request):
        return httpx.Response(
            200, json=[{"number": 1}, {"number": 2, "pull_request": {"url": "x"}}]
        )

    client = make_client(handler)
    assert [i["number"] for i in client.iter_issues("o", "r")] == [1]


def test_rate_limit_waits_then_retries():
    calls = {"n": 0}
    sleeps = []

    def handler(request):
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(
                403, headers={"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "1060"}
            )
        return httpx.Response(200, json=[{"number": 1}])

    client = GitHubClient(
        transport=httpx.MockTransport(handler), sleep=sleeps.append, now=lambda: 1000
    )
    assert len(list(client.iter_pull_requests("o", "r"))) == 1
    assert sleeps == [61]


def test_retry_after_header_respected():
    calls = {"n": 0}
    sleeps = []

    def handler(request):
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, headers={"Retry-After": "7"})
        return httpx.Response(200, json=[])

    client = GitHubClient(transport=httpx.MockTransport(handler), sleep=sleeps.append)
    list(client.iter_pull_requests("o", "r"))
    assert sleeps == [7]


def test_rate_limit_wait_too_long_raises():
    def handler(request):
        return httpx.Response(
            403, headers={"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "999999"}
        )

    client = make_client(handler, max_rate_limit_wait=60)
    with pytest.raises(RateLimitExceeded):
        list(client.iter_pull_requests("o", "r"))


def test_plain_403_is_not_treated_as_rate_limit():
    def handler(request):
        return httpx.Response(403, headers={"X-RateLimit-Remaining": "42"})

    client = make_client(handler)
    with pytest.raises(Exception) as exc:
        list(client.iter_pull_requests("o", "r"))
    assert not isinstance(exc.value, RateLimitExceeded)


def test_missing_repo_raises_repo_not_found():
    client = make_client(lambda request: httpx.Response(404))
    with pytest.raises(RepoNotFound):
        list(client.iter_pull_requests("o", "nope"))


def test_invalid_url_makes_no_requests():
    def handler(request):
        raise AssertionError("no HTTP call expected")

    client = make_client(handler)
    with pytest.raises(InvalidRepoURL):
        client.fetch_repo("https://example.com/a/b")
