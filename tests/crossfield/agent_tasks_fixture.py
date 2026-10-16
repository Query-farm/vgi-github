"""Independent task observations with archived, orphan and waiting-state cases."""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path

import httpx

from vgi_github import github_api as api
from vgi_github.generated_worker import main

OWNER = "agent-task-fixture"
ORGANIZATION = {
    "id": 31000,
    "login": OWNER,
    "type": "Organization",
    "name": OWNER,
    "description": "Agent task fixture",
    "created_at": "2020-01-01T00:00:00Z",
}
REPOSITORIES = [
    {
        "id": identity,
        "node_id": f"R{identity}",
        "full_name": f"{OWNER}/{name}",
        "name": name,
        "owner": ORGANIZATION,
        "private": False,
        "description": "Agent task fixture",
        "topics": [],
        "language": None,
    }
    for identity, name in [(31001, "alpha"), (31002, "beta"), (31003, "empty")]
]


def session(identity, task, state, creator, amount=1.5):
    return {
        "id": identity,
        "name": "Session " + identity,
        "state": state,
        "created_at": "2026-09-01T12:00:00Z",
        "updated_at": "2026-09-01T13:00:00Z",
        "completed_at": "2026-09-01T13:00:00Z",
        "user": {"id": creator},
        "owner": {"id": 31000},
        "repository": {"id": 31001},
        "task_id": task,
        "prompt": "Review the implementation",
        "head_ref": "agent/patch",
        "base_ref": "main",
        "model": "fixture-model",
        "usage": {"type": "premium_requests", "amount": amount},
    }


def task(identity, repository_id, creator, state, day, sessions, reported, artifacts, archived=False):
    return {
        "id": identity,
        "url": f"https://api.github.com/agents/tasks/{identity}",
        "html_url": f"https://github.example/tasks/{identity}",
        "name": "Task " + identity,
        "repository": {"id": repository_id},
        "owner": {"id": 31000},
        "creator": {"id": creator},
        "creator_type": "user",
        "user_collaborators": [{"id": 38102}],
        "state": state,
        "session_count": reported,
        "sessions": sessions,
        "artifacts": artifacts,
        "created_at": f"2026-09-{day:02}T00:00:00Z",
        "updated_at": f"2026-09-{day:02}T01:00:00Z",
        "archived_at": "2026-09-05T00:00:00Z" if archived else None,
        "custom_agent": {"id": "reviewer"},
    }


TASKS = {
    "task-a": task(
        "task-a",
        31001,
        38101,
        "completed",
        1,
        [session("session-a", "task-a", "failed", 38102), session("session-b", "task-a", "completed", 38101)],
        3,
        [
            {"provider": "github", "type": "pull", "data": {"id": 39101, "global_id": "PR_39101"}},
            {"provider": "github", "type": "branch", "data": {"head_ref": "agent/patch", "base_ref": "main"}},
        ],
    ),
    "task-b": task("task-b", 31001, 38102, "failed", 2, [], 0, []),
    "task-c": task(
        "task-c",
        31002,
        38102,
        "waiting_for_user",
        3,
        [session("session-c", "task-c", "waiting_for_user", 38102, 2.25)],
        1,
        [{"provider": "github", "type": "pull", "data": {"id": 39102}}],
    ),
    "task-archived": task(
        "task-archived",
        31001,
        38101,
        "completed",
        4,
        [session("session-d", "task-archived", "completed", 38101)],
        1,
        [],
        True,
    ),
    # The global API does not promise repository identity, a display name or sessions.
    "task-orphan": {"id": "task-orphan", "state": "queued", "created_at": "2026-09-05T00:00:00Z"},
}
TASKS["task-a"]["sessions"][0]["error"] = {"message": "First attempt failed"}
TASKS["task-c"]["sessions"][0]["repository"]["id"] = 31002
REPOSITORY_TASKS = {"alpha": ["task-a", "task-b", "task-archived"], "beta": ["task-c"], "empty": []}


def respond(request):
    path = request.url.path
    if not (
        path.startswith((f"/repos/{OWNER}/", f"/orgs/{OWNER}", f"/users/{OWNER}", f"/agents/repos/{OWNER}/"))
        or path == "/agents/tasks"
        or path.startswith("/agents/tasks/task-")
    ):
        return None
    if request.method != "GET":
        raise AssertionError(f"Unexpected agent-task method {request.method}")
    if os.environ.get("CROSSFIELD_GITHUB_API_LOG"):
        with Path(os.environ["CROSSFIELD_GITHUB_API_LOG"]).open("a") as log:
            log.write(json.dumps({"path": path, "query": request.url.query.decode()}) + "\n")

    def response(value, status=200, next_page=None):
        headers = {"Cache-Control": "no-store", "X-RateLimit-Remaining": "5000"}
        if next_page:
            headers["Link"] = f'<{request.url.copy_set_param("page", str(next_page))}>; rel="next"'
        return httpx.Response(status, json=copy.deepcopy(value), headers=headers, request=request)

    def pages(rows, task_list=False):
        page = int(request.url.params.get("page", "1"))
        selected = rows[page - 1 : page]
        if task_list:
            selected = {
                "tasks": [{k: v for k, v in row.items() if k != "sessions"} for row in selected],
                "total_active_count": 19,
                "total_archived_count": 7,
            }
        return response(selected, next_page=page + 1 if page < len(rows) else None)

    if path in {f"/orgs/{OWNER}", f"/users/{OWNER}"}:
        return response(ORGANIZATION)
    if path == f"/orgs/{OWNER}/repos":
        return pages(REPOSITORIES)
    if path.startswith(f"/repos/{OWNER}/"):
        name = path.rsplit("/", 1)[-1]
        row = next((r for r in REPOSITORIES if r["name"] == name), None)
        return response(row if row else {"message": "Not Found"}, 200 if row else 404)
    if path.startswith(f"/agents/repos/{OWNER}/"):
        parts = path.strip("/").split("/")
        name = parts[3]
        identities = REPOSITORY_TASKS.get(name, [])
        lookup = parts[5] if len(parts) == 6 else None
    else:
        identities = list(TASKS)
        lookup = path.rsplit("/", 1)[-1] if path != "/agents/tasks" else None
    if lookup:
        row = TASKS.get(lookup) if lookup in identities else None
        return response(row if row else {"message": "Not Found"}, 200 if row else 404)
    rows = [TASKS[key] for key in identities]
    archived = request.url.params.get("is_archived", "false") == "true"
    rows = [row for row in rows if (row.get("archived_at") is not None) == archived]
    if "state" in request.url.params:
        states = request.url.params["state"].split(",")
        rows = [row for row in rows if row["state"] in states]
    if "creator_id" in request.url.params:
        creators = {int(value) for value in request.url.params.get_list("creator_id")}
        rows = [row for row in rows if row.get("creator", {}).get("id") in creators]
    if "since" in request.url.params:
        since = request.url.params["since"].replace("+00:00", "Z")
        rows = [row for row in rows if row.get("updated_at", "") >= since]
    return pages(rows, task_list=True)


if __name__ == "__main__":
    api.http_client = lambda: httpx.Client(transport=httpx.MockTransport(respond))
    main()
