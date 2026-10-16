"""Independent Codespaces populations and context-specific machine eligibility."""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path

import httpx

from vgi_github import github_api as api
from vgi_github.generated_worker import main

OWNER = "codespaces-fixture"


def actor(login, identity):
    value = {
        "id": identity,
        "login": login,
        "node_id": f"U{identity}",
        "type": "User",
        "site_admin": False,
        "gravatar_id": "",
    }
    for field in [
        "url",
        "html_url",
        "avatar_url",
        "followers_url",
        "following_url",
        "gists_url",
        "starred_url",
        "subscriptions_url",
        "organizations_url",
        "repos_url",
        "events_url",
        "received_events_url",
    ]:
        value[field] = f"https://github.example/{login}/{field}"
    return value


ALICE, BOB = actor("codespaces-alice", 48101), actor("codespaces-bob", 48102)
ORGANIZATION = {
    "id": 41000,
    "login": OWNER,
    "type": "Organization",
    "name": OWNER,
    "description": "Codespaces fixture",
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
        "description": "Codespaces fixture",
        "topics": [],
        "language": None,
    }
    for identity, name in [(41001, "alpha"), (41002, "beta"), (41003, "empty")]
]


def machine(name, cores, memory, storage, prebuild):
    return {
        "name": name,
        "display_name": f"{cores} cores",
        "operating_system": "linux",
        "storage_in_bytes": storage,
        "memory_in_bytes": memory,
        "cpus": cores,
        "prebuild_availability": prebuild,
    }


SMALL, MEDIUM, LARGE = (
    machine("small", 2, 20, 100, None),
    machine("medium", 4, 40, 200, "ready"),
    machine("large", 8, 80, 400, "ready"),
)


def codespace(identity, name, repo, owner, machine_value, state, prebuild):
    value = {
        "id": identity,
        "name": name,
        "display_name": name.title(),
        "environment_id": None,
        "owner": owner,
        "billable_owner": ALICE,
        "repository": REPOSITORIES[repo],
        "machine": machine_value,
        "devcontainer_path": ".devcontainer/devcontainer.json",
        "prebuild": prebuild,
        "created_at": "2026-09-01T00:00:00Z",
        "updated_at": "2026-09-03T00:00:00Z",
        "last_used_at": "2026-09-02T00:00:00Z",
        "state": state,
        "git_status": {
            "ahead": 2,
            "behind": 1,
            "has_unpushed_changes": True,
            "has_uncommitted_changes": False,
            "ref": "main",
        },
        "location": "WestUs2",
        "idle_timeout_minutes": None,
        "pulls_url": None,
        "recent_folders": ["/workspaces/project", "/workspaces/shared"],
        "runtime_constraints": {"allowed_port_privacy_settings": ["private"]},
        "pending_operation": False,
        "retention_period_minutes": 1440,
        "retention_expires_at": "2026-09-03T00:00:00Z",
    }
    for field in ["url", "web_url", "machines_url", "start_url", "stop_url"]:
        value[field] = f"https://api.github.com/user/codespaces/{name}/{field}"
    return value


CODESPACES = [
    codespace(42001, "fixture-space-a", 0, ALICE, SMALL, "Available", True),
    codespace(42002, "fixture-space-b", 0, BOB, None, "Shutdown", None),
    codespace(42003, "fixture-space-c", 1, ALICE, MEDIUM, "Unknown", False),
]
MACHINES = {"alpha": [SMALL, MEDIUM], "beta": [MEDIUM], "empty": []}
SPACE_MACHINES = {"fixture-space-a": [LARGE], "fixture-space-b": [], "fixture-space-c": [SMALL]}
DEVCONTAINERS = {
    "alpha": [
        {"path": ".devcontainer/devcontainer.json", "name": "Default", "display_name": "Default environment"},
        {"path": ".devcontainer/python/devcontainer.json"},
    ],
    "beta": [{"path": ".devcontainer/devcontainer.json", "name": "Default"}],
    "empty": [],
}
DEFAULTS = {
    "alpha": {
        "billable_owner": ALICE,
        "defaults": {"location": "WestUs2", "devcontainer_path": ".devcontainer/devcontainer.json"},
    },
    "beta": {},
    "empty": {"defaults": {"location": "EastUs", "devcontainer_path": None}},
}
EXPORTS = {
    "fixture-space-a": {
        "id": "export-a",
        "state": "succeeded",
        "completed_at": "2026-09-04T00:00:00Z",
        "branch": "codespace/export-a",
        "sha": "a" * 40,
        "export_url": "https://api.github.com/user/codespaces/fixture-space-a/exports/export-a",
        "html_url": "https://github.example/exports/a",
    },
    "fixture-space-b": {},
    "fixture-space-c": {
        "state": "failed",
        "completed_at": None,
        "branch": None,
        "sha": None,
        "html_url": None,
    },
}


def respond(request):
    path = request.url.path
    if not (
        path.startswith(
            (
                f"/repos/{OWNER}/",
                f"/orgs/{OWNER}",
                f"/users/{OWNER}",
                "/user/codespaces/fixture-space-",
                "/users/codespaces-",
            )
        )
        or path == "/user/codespaces"
    ):
        return None
    if request.method != "GET":
        raise AssertionError(f"Unexpected Codespaces method {request.method}")
    if os.environ.get("CROSSFIELD_GITHUB_API_LOG"):
        with Path(os.environ["CROSSFIELD_GITHUB_API_LOG"]).open("a") as log:
            log.write(json.dumps({"path": path, "query": request.url.query.decode()}) + "\n")

    def response(value, status=200, next_page=None):
        headers = {"Cache-Control": "no-store", "X-RateLimit-Remaining": "5000"}
        if next_page:
            headers["Link"] = f'<{request.url.copy_set_param("page", str(next_page))}>; rel="next"'
        return httpx.Response(status, json=copy.deepcopy(value), headers=headers, request=request)

    def pages(rows, key=None):
        page = int(request.url.params.get("page", "1"))
        selected = rows[page - 1 : page]
        return response(
            {"total_count": len(rows), key: selected} if key else selected,
            next_page=page + 1 if page < len(rows) else None,
        )

    if path in {f"/orgs/{OWNER}", f"/users/{OWNER}"}:
        return response(ORGANIZATION)
    if path == f"/orgs/{OWNER}/repos":
        return pages(REPOSITORIES)
    if path == f"/orgs/{OWNER}/codespaces":
        return pages(CODESPACES, "codespaces")
    for user in [ALICE, BOB]:
        if path == f"/users/{user['login']}":
            return response(user)
        if path == f"/orgs/{OWNER}/members/{user['login']}/codespaces":
            return pages([row for row in CODESPACES if row["owner"]["id"] == user["id"]], "codespaces")
    if path == "/user/codespaces":
        rows = [row for row in CODESPACES if row["owner"]["id"] == ALICE["id"]]
        if "repository_id" in request.url.params:
            rows = [
                row for row in rows if row["repository"]["id"] == int(request.url.params["repository_id"])
            ]
        return pages(rows, "codespaces")
    if path.startswith("/user/codespaces/fixture-space-"):
        parts = path.strip("/").split("/")
        name = parts[2]
        if len(parts) == 3:
            return response(next(row for row in CODESPACES if row["name"] == name))
        if parts[3:] == ["machines"]:
            return response({"total_count": len(SPACE_MACHINES[name]), "machines": SPACE_MACHINES[name]})
        if len(parts) == 5 and parts[3] == "exports":
            if parts[4] not in {"latest", "export-a"}:
                return response({"message": "Not Found"}, 404)
            return response(EXPORTS[name])
    if path.startswith(f"/repos/{OWNER}/"):
        parts = path.strip("/").split("/")
        name, tail = parts[2], parts[3:]
        if not tail:
            return response(next(row for row in REPOSITORIES if row["name"] == name))
        if tail == ["codespaces"]:
            return pages(
                [
                    row
                    for row in CODESPACES
                    if row["repository"]["name"] == name and row["owner"]["id"] == ALICE["id"]
                ],
                "codespaces",
            )
        if tail == ["codespaces", "machines"]:
            return response({"total_count": len(MACHINES[name]), "machines": MACHINES[name]})
        if tail == ["codespaces", "devcontainers"]:
            return pages(DEVCONTAINERS[name], "devcontainers")
        if tail == ["codespaces", "new"]:
            return response(DEFAULTS[name])
        if tail == ["codespaces", "permissions_check"]:
            assert "ref" in request.url.params and "devcontainer_path" in request.url.params
            return response({"accepted": name == "alpha"})
    raise AssertionError(f"Unexpected Codespaces request {request.url}")


if __name__ == "__main__":
    api.http_client = lambda: httpx.Client(transport=httpx.MockTransport(respond))
    main()
