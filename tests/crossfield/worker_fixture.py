"""Real vgi-github worker with an independently authored, deterministic GitHub API.

Run with vgi-github's Python environment and PYTHONPATH pointing at that checkout.
Only the HTTP transport is replaced: catalog RPCs, argument binding, Arrow types,
pagination, strict reporting validation, and native DuckDB callbacks remain real.
No request can reach the network. CROSSFIELD_GITHUB_API_LOG records request paths
to support assertions that discovery and EXPLAIN do not read source rows.
"""

from __future__ import annotations

import copy
import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx

from vgi_github import github_api as api
from vgi_github.worker import main


def stamp(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def account(login: str, identity: int) -> dict:
    return {
        "id": identity,
        "login": login,
        "type": "User",
        "name": login.title(),
        "public_repos": 2,
        "followers": 5,
        "following": 1,
        "created_at": "2020-01-01T00:00:00Z",
        "updated_at": "2026-09-01T00:00:00Z",
    }


def repository(name: str, identity: int = 10) -> dict:
    return {
        "id": identity,
        "full_name": name,
        "name": name.split("/")[-1],
        "owner": account(name.split("/")[0], 100),
        "private": False,
        "fork": False,
        "archived": False,
        "disabled": False,
        "language": "Python",
        "stargazers_count": 12,
        "forks_count": 3,
        "open_issues_count": 2,
        "topics": ["sql", "semantic"],
        "default_branch": "main",
        "permissions": {"admin": True},
        "license": {"spdx_id": "MIT"},
        "created_at": "2020-01-01T00:00:00Z",
        "updated_at": "2026-09-01T00:00:00Z",
        "pushed_at": "2026-09-01T00:00:00Z",
    }


def pull(number: int, merged: str | None, hours: int, *, state: str = "closed", draft: bool = False) -> dict:
    finish = (
        datetime.fromisoformat(merged.replace("Z", "+00:00")) if merged else datetime(2026, 9, 15, tzinfo=UTC)
    )
    return {
        "id": 1000 + number,
        "number": number,
        "title": f"Change {number}",
        "state": state,
        "draft": draft,
        "user": account("alice" if number % 2 else "bob", 101 + number % 2),
        "author_association": "MEMBER",
        "head": {"ref": f"work-{number}", "sha": f"{number:040x}", "repo": {"full_name": "example/project"}},
        "base": {"ref": "main", "repo": {"full_name": "example/project"}},
        "labels": [{"name": "feature"}, {"name": "sql"}],
        "assignees": [],
        "requested_reviewers": [{"login": "reviewer"}],
        "milestone": None,
        "created_at": stamp(finish - timedelta(hours=hours)),
        "updated_at": stamp(finish),
        "closed_at": stamp(finish) if state == "closed" else None,
        "merged_at": merged,
        "html_url": f"https://github.example/project/pull/{number}",
        "body": "Fixture change",
    }


# The [2026-09-01, 2026-10-01) merge cohort has durations 2, 4, 10, 20 hours:
# count 4, mean 9, median 7, continuous p90 17. The first row is exactly at
# the inclusive start; row 5 is exactly at the exclusive end; row 6 precedes it.
PULLS = [
    pull(1, "2026-09-01T00:00:00Z", 2),
    pull(2, "2026-09-10T12:00:00Z", 4),
    pull(3, "2026-09-20T12:00:00Z", 10),
    pull(4, "2026-09-30T12:00:00Z", 20),
    pull(5, "2026-10-01T00:00:00Z", 30),
    pull(6, "2026-08-31T23:59:59Z", 40),
    pull(7, None, 3),
    pull(8, None, 2, state="open"),
    pull(9, None, 1, state="open", draft=True),
]


def issue(number: int, *, closed: bool = False) -> dict:
    return {
        "id": 2000 + number,
        "number": number,
        "title": f"Issue {number}",
        "state": "closed" if closed else "open",
        "state_reason": "completed" if closed else None,
        "user": account("alice", 101),
        "labels": [{"name": "bug"}],
        "assignees": [],
        "comments": number,
        "reactions": {"total_count": 5, "+1": 3},
        "locked": False,
        "created_at": "2026-09-01T00:00:00Z",
        "updated_at": "2026-09-03T00:00:00Z",
        "closed_at": "2026-09-03T00:00:00Z" if closed else None,
        "repository_url": "https://api.github.com/repos/example/project",
    }


def run(identity: int, conclusion: str, minutes: int) -> dict:
    return {
        "id": identity,
        "workflow_id": 300,
        "name": "Checks",
        "run_number": identity,
        "run_attempt": 1,
        "event": "push",
        "status": "completed",
        "conclusion": conclusion,
        "head_branch": "main",
        "head_sha": f"{identity:040x}",
        "actor": account("alice", 101),
        "created_at": "2026-09-10T00:00:00Z",
        "run_started_at": "2026-09-10T00:00:00Z",
        "updated_at": stamp(datetime(2026, 9, 10, tzinfo=UTC) + timedelta(minutes=minutes)),
    }


def respond(request: httpx.Request) -> httpx.Response:
    if request.method != "GET":
        raise AssertionError("The GitHub fixture only permits GET")
    if os.environ.get("CROSSFIELD_GITHUB_API_LOG"):
        with Path(os.environ["CROSSFIELD_GITHUB_API_LOG"]).open("a") as log:
            log.write(json.dumps({"path": request.url.path, "query": str(request.url.params)}) + "\n")
    path = request.url.path
    page = int(request.url.params.get("page", "1"))
    headers = {"Cache-Control": "no-store", "X-RateLimit-Remaining": "5000"}

    def result(data: object, code: int = 200) -> httpx.Response:
        return httpx.Response(code, json=data, headers=headers, request=request)

    if path == "/rate_limit":
        return result(
            {
                "resources": {
                    "core": {"limit": 60, "remaining": 55, "used": 5, "reset": 1788224400},
                    "search": {"limit": 10, "remaining": 9, "used": 1, "reset": 1788220860},
                }
            }
        )
    if path.startswith("/search/"):
        rows = (
            [repository("example/project"), repository("example/second", 20)]
            if path.endswith("repositories")
            else [issue(1), issue(2, closed=True)]
        )
        return result({"total_count": len(rows), "incomplete_results": False, "items": rows})
    if path.startswith("/users/"):
        login = path.split("/")[2]
        return result(
            [repository(f"{login}/project"), repository(f"{login}/second", 20)]
            if path.endswith("/repos")
            else account(login, 101)
        )
    pieces = path.split("/")
    if len(pieces) < 4 or pieces[1] != "repos":
        return result({"message": "Unknown fixture endpoint"}, 404)
    repo = "/".join(pieces[2:4])
    mode = pieces[3]
    endpoint = "/".join(pieces[4:])
    if mode == "missing":
        return result({"message": "Not Found"}, 404)
    if not endpoint:
        return result(repository(repo, 20 if mode == "second" else 10))
    if endpoint == "languages":
        return result({} if mode == "empty" else {"Python": 750, "C++": 250})
    if endpoint == "pulls":
        rows = copy.deepcopy(PULLS)
        if mode in ("second", "other"):
            rows = [pull(1, "2026-09-15T12:00:00Z", 6)]
            rows[0]["id"] = 9001
        elif mode == "duplicate":
            rows[1]["id"] = rows[0]["id"]
        elif mode == "null-id":
            rows[0]["id"] = None
        elif mode == "negative-duration":
            rows[0]["created_at"] = "2026-10-02T00:00:00Z"
        elif mode == "missing-merge":
            del rows[0]["merged_at"]
        state = request.url.params.get("state", "all")
        if state != "all":
            rows = [row for row in rows if row["state"] == state]
    elif endpoint == "issues":
        rows = [issue(1), issue(2, closed=True)]
    elif endpoint.endswith("/comments"):
        rows = [
            {
                "id": 3001,
                "user": account("alice", 101),
                "body": "Reviewed",
                "created_at": "2026-09-02T00:00:00Z",
                "updated_at": "2026-09-02T00:00:00Z",
            }
        ]
    elif endpoint == "commits":
        rows = [
            {
                "sha": f"{i:040x}",
                "commit": {
                    "message": f"Commit {i}",
                    "author": {
                        "name": "Alice",
                        "email": "alice@example.test",
                        "date": "2026-09-01T00:00:00Z",
                    },
                    "committer": {"date": "2026-09-01T00:00:00Z"},
                    "verification": {"verified": i == 1},
                },
                "author": account("alice", 101),
                "parents": [{"sha": f"{i + 5:040x}"}],
            }
            for i in (1, 2)
        ]
    elif endpoint == "releases":
        rows = [
            {
                "id": 4001,
                "tag_name": "v1.0.0",
                "name": "First release",
                "draft": False,
                "prerelease": False,
                "author": account("alice", 101),
                "assets": [{"download_count": 10}, {"download_count": 25}],
                "created_at": "2026-09-01T00:00:00Z",
                "published_at": "2026-09-02T00:00:00Z",
            }
        ]
    elif endpoint == "contributors":
        rows = [{**account("alice", 101), "contributions": 8}, {**account("bob", 102), "contributions": 2}]
    elif endpoint == "stargazers":
        rows = [
            {"starred_at": "2026-09-01T00:00:00Z", "user": account("alice", 101)},
            {"starred_at": "2026-09-02T00:00:00Z", "user": account("bob", 102)},
        ]
    elif endpoint == "actions/runs":
        rows = [run(5001, "success", 10), run(5002, "failure", 20), run(5003, "cancelled", 30)]
    else:
        return result({"message": "Unknown fixture endpoint"}, 404)
    if mode == "empty":
        rows = []
    # Small pages deliberately exercise real Link-header traversal.
    size = 3
    if mode == "late-error" and page > 1:
        return result({"message": "Later page denied"}, 403)
    if page * size < len(rows):
        next_url = request.url.copy_set_param("page", str(page + 1))
        headers["Link"] = f'<{next_url}>; rel="next"'
    selected = rows[(page - 1) * size : page * size]
    return result(
        {"total_count": len(rows), "workflow_runs": selected} if endpoint == "actions/runs" else selected
    )


api.open_client = lambda: httpx.Client(transport=httpx.MockTransport(respond), follow_redirects=True)
if __name__ == "__main__":
    main()
