"""Independent deployment/environment populations; every list page has one row."""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path

import httpx

from vgi_github import github_api as api
from vgi_github.generated_worker import main

OWNER = "deployment-fixture"


def actor(login, identity):
    return {"id": identity, "login": login, "type": "User"}


REPOSITORIES = [
    {
        "id": identity,
        "node_id": f"R{identity}",
        "full_name": f"{OWNER}/{name}",
        "name": name,
        "owner": {"id": 800, "login": OWNER, "type": "Organization"},
        "private": name == "beta",
        "description": "Independent deployment fixture repository",
        "topics": [],
        "language": None,
    }
    for identity, name in [(801, "alpha"), (802, "beta"), (803, "empty")]
]


def deployment(identity, environment, creator="alice", *, production=False, transient=False):
    return {
        "id": identity,
        "node_id": f"DEP{identity}",
        "sha": f"{identity:040x}",
        "ref": "main",
        "task": "deploy",
        "payload": {"build": identity},
        "environment": environment,
        "original_environment": environment,
        "description": None,
        "creator": actor(creator, 201 if creator == "alice" else 202) if creator else None,
        "created_at": "2026-09-01T00:00:00Z",
        "updated_at": "2026-09-02T00:00:00Z",
        "url": f"https://api.github.example/deployments/{identity}",
        "statuses_url": f"https://api.github.example/deployments/{identity}/statuses",
        "repository_url": "https://api.github.example/repos/deployment-fixture/alpha",
        "transient_environment": transient,
        "production_environment": production,
    }


DEPLOYMENTS = {
    "alpha": [
        deployment(11, "production", production=True),
        deployment(12, "staging", "bob", transient=True),
        deployment(13, "deleted-environment", None, production=True),
    ],
    "beta": [deployment(21, "production", production=True)],
    "empty": [],
}


def status(identity, state, environment="production", creator="bob"):
    return {
        "id": identity,
        "node_id": f"DS{identity}",
        "state": state,
        "description": f"Observed {state}",
        "creator": actor(creator, 202) if creator else None,
        "environment": environment,
        "created_at": "2026-09-02T00:00:00Z",
        "updated_at": "2026-09-02T00:00:00Z",
        "url": f"https://api.github.example/statuses/{identity}",
        "target_url": f"https://deploy.example/{identity}",
        "environment_url": "https://production.example",
        "log_url": f"https://logs.example/{identity}",
        "deployment_url": "https://api.github.example/deployments/11",
        "repository_url": "https://api.github.example/repos/deployment-fixture/alpha",
    }


STATUSES = {
    11: [status(112, "success"), status(111, "pending")],
    12: [
        status(123, "in_progress", "staging", None),
        status(122, "error", "staging"),
        status(121, "failure", "staging"),
    ],
    13: [],
    21: [status(211, "success")],
}


def environment(identity, name, settings=None, rules=None):
    return {
        "id": identity,
        "node_id": f"ENV{identity}",
        "name": name,
        "url": f"https://api.github.example/environments/{name}",
        "html_url": f"https://github.example/environments/{name}",
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-09-01T00:00:00Z",
        "deployment_branch_policy": settings,
        "protection_rules": rules or [],
    }


ENVIRONMENTS = {
    "alpha": [
        environment(
            701,
            "production",
            {"protected_branches": True, "custom_branch_policies": False},
            [
                {"id": 71, "node_id": "RULE71", "type": "wait_timer", "wait_timer": 30},
                {
                    "id": 72,
                    "node_id": "RULE72",
                    "type": "required_reviewers",
                    "prevent_self_review": True,
                    "reviewers": [
                        {"type": "User", "reviewer": {"id": 201, "login": "alice", "type": "User"}},
                        {"type": "Team", "reviewer": {"id": 501, "name": "Operators", "slug": "operators"}},
                    ],
                },
            ],
        ),
        environment(
            702,
            "staging",
            {"protected_branches": False, "custom_branch_policies": True},
            [
                {"id": 73, "node_id": "RULE73", "type": "branch_policy"},
            ],
        ),
        environment(703, "unused"),
    ],
    "beta": [environment(704, "production")],
    "empty": [],
}
BRANCH_POLICIES = {
    ("alpha", "staging"): [
        {"id": 901, "node_id": "BP901", "name": "release/*", "type": "branch"},
        {"id": 902, "node_id": "BP902", "name": "v*", "type": "tag"},
    ]
}
INTEGRATIONS = [
    {
        "id": 201,
        "node_id": "APP201",
        "slug": "quality",
        "integration_url": "https://api.github.example/apps/quality",
    },
    {
        "id": 202,
        "node_id": "APP202",
        "slug": "security",
        "integration_url": "https://api.github.example/apps/security",
    },
]
CUSTOM_RULES = {
    ("alpha", "production"): [{"id": 1001, "node_id": "CUSTOM1001", "enabled": True, "app": INTEGRATIONS[0]}],
    ("alpha", "staging"): [{"id": 1002, "node_id": "CUSTOM1002", "enabled": True, "app": INTEGRATIONS[1]}],
}
AVAILABLE = {
    ("alpha", "production"): INTEGRATIONS,
    ("alpha", "staging"): INTEGRATIONS[1:],
    ("beta", "production"): INTEGRATIONS[:1],
}


def respond(request):
    path = request.url.path
    if not (path.startswith((f"/repos/{OWNER}/", f"/orgs/{OWNER}/")) or path == f"/users/{OWNER}"):
        return None
    if request.method != "GET":
        raise AssertionError(f"Unexpected deployment method {request.method}")
    if os.environ.get("CROSSFIELD_GITHUB_API_LOG"):
        with Path(os.environ["CROSSFIELD_GITHUB_API_LOG"]).open("a") as log:
            log.write(json.dumps({"path": path, "query": request.url.query.decode()}) + "\n")
    headers = {"Cache-Control": "no-store", "X-RateLimit-Remaining": "5000"}

    def response(value, code=200, next_page=None):
        result_headers = dict(headers)
        if next_page:
            result_headers["Link"] = f'<{request.url.copy_set_param("page", str(next_page))}>; rel="next"'
        return httpx.Response(code, json=copy.deepcopy(value), headers=result_headers, request=request)

    def pages(values, key=None):
        page = int(request.url.params.get("page", "1"))
        selected = values[page - 1 : page]
        return response(
            {"total_count": len(values), key: selected} if key else selected,
            next_page=page + 1 if page < len(values) else None,
        )

    def lookup(values, key, identity):
        found = next((value for value in values if value[key] == identity), None)
        return response(found) if found is not None else response({"message": "Not Found"}, 404)

    if path == f"/users/{OWNER}":
        return response({"id": 800, "login": OWNER, "type": "Organization"})
    if path == f"/orgs/{OWNER}/repos":
        return pages(REPOSITORIES)
    parts = path.strip("/").split("/")
    if len(parts) >= 3 and parts[:2] == ["repos", OWNER]:
        repo = parts[2]
        if repo not in DEPLOYMENTS:
            return response({"message": "Not Found"}, 404)
        if len(parts) == 3:
            return lookup(REPOSITORIES, "name", repo)
        if parts[3] == "deployments":
            values = DEPLOYMENTS[repo]
            if len(parts) == 4:
                selected_environment = request.url.params.get("environment")
                return pages(
                    [
                        row
                        for row in values
                        if not selected_environment or row["environment"] == selected_environment
                    ]
                )
            deployment_id = int(parts[4])
            if len(parts) == 5:
                return lookup(values, "id", deployment_id)
            if any(row["id"] == deployment_id for row in values) and parts[5] == "statuses":
                return (
                    pages(STATUSES[deployment_id])
                    if len(parts) == 6
                    else lookup(STATUSES[deployment_id], "id", int(parts[6]))
                )
            return response({"message": "Not Found"}, 404)
        if parts[3] == "environments":
            if len(parts) == 4:
                return pages(ENVIRONMENTS[repo], "environments")
            name = parts[4]
            if len(parts) == 5:
                return lookup(ENVIRONMENTS[repo], "name", name)
            if not any(row["name"] == name for row in ENVIRONMENTS[repo]):
                return response({"message": "Not Found"}, 404)
            if parts[5] == "deployment-branch-policies":
                values = BRANCH_POLICIES.get((repo, name), [])
                return (
                    pages(values, "branch_policies")
                    if len(parts) == 6
                    else lookup(values, "id", int(parts[6]))
                )
            if parts[5] == "deployment_protection_rules":
                if len(parts) == 7 and parts[6] == "apps":
                    return pages(
                        AVAILABLE.get((repo, name), []),
                        "available_custom_deployment_protection_rule_integrations",
                    )
                values = CUSTOM_RULES.get((repo, name), [])
                return (
                    pages(values, "custom_deployment_protection_rules")
                    if len(parts) == 6
                    else lookup(values, "id", int(parts[6]))
                )
        if parts[3:5] == ["pages", "deployments"] and len(parts) == 6:
            return response({} if parts[5] == "unknown" else {"status": "succeed"})
    raise AssertionError(f"Unexpected deployment fixture path {path}")


if __name__ == "__main__":
    api.open_client = lambda: httpx.Client(transport=httpx.MockTransport(respond), follow_redirects=True)
    main()
