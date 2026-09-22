"""Mock GitHub payload factories for integration tests.

All ids live in a reserved range (>= TEST_ID_BASE) and all repos use TEST_REPO_PREFIX,
so test data can be found and deleted without touching real ingested data.
"""

TEST_ID_BASE = 9_000_000_000_000
TEST_REPO_PREFIX = "cortex-test/"
TEST_REPO = TEST_REPO_PREFIX + "repo"
TEST_REPO_URL = "https://github.com/" + TEST_REPO


def user(n: int, login: str | None = None) -> dict:
    uid = TEST_ID_BASE + n
    return {
        "id": uid,
        "login": login or f"tester{n}",
        "html_url": f"https://github.com/tester{n}",
        "type": "User",  # extra fields GitHub sends; must be ignored
    }


def pull_request(n: int, author: dict | None, **over) -> dict:
    base = {
        "id": TEST_ID_BASE + 1000 + n,
        "number": n,
        "title": f"PR {n}",
        "state": "closed",
        "body": None,
        "html_url": f"{TEST_REPO_URL}/pull/{n}",
        "created_at": "2024-01-01T00:00:00Z",
        "updated_at": "2024-01-02T00:00:00Z",
        "closed_at": "2024-01-02T00:00:00Z",
        "merged_at": "2024-01-02T00:00:00Z",
        "draft": False,
        "user": author,
        "head": {"ref": "feature"},
    }
    return {**base, **over}


def issue(n: int, author: dict | None, **over) -> dict:
    base = {
        "id": TEST_ID_BASE + 2000 + n,
        "number": n,
        "title": f"Issue {n}",
        "state": "open",
        "body": "something is broken",
        "html_url": f"{TEST_REPO_URL}/issues/{n}",
        "created_at": "2024-02-01T00:00:00Z",
        "updated_at": "2024-02-01T00:00:00Z",
        "closed_at": None,
        "user": author,
        "labels": [],
    }
    return {**base, **over}
