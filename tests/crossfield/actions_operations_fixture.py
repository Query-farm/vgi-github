"""Independent operational Actions observations, including drift and empty run groups."""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path

import httpx

from vgi_github import github_api as api
from vgi_github.generated_worker import main

OWNER = "actions-ops-fixture"


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


ALICE, BOB = actor("actions-ops-alice", 8101), actor("actions-ops-bob", 8102)
ORGANIZATION = {
    "id": 2100,
    "login": OWNER,
    "type": "Organization",
    "name": OWNER,
    "description": "Independent operational fixture",
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
        "description": "Operational Actions fixture",
        "html_url": f"https://github.example/{OWNER}/{name}",
        "fork": False,
        "default_branch": "main",
        "topics": [],
        "language": None,
    }
    for identity, name in [(2101, "alpha"), (2102, "beta"), (2103, "empty")]
]


def run(identity, workflow):
    repo = REPOSITORIES[0 if identity < 3200 else 1]
    url = f"https://api.github.example/repos/{repo['full_name']}/actions/runs/{identity}"
    return {
        "id": identity,
        "node_id": f"RUN{identity}",
        "workflow_id": workflow,
        "run_number": identity,
        "run_attempt": 1,
        "name": "CI",
        "display_title": "Independent CI",
        "event": "push",
        "status": "in_progress",
        "conclusion": None,
        "head_sha": "a" * 40,
        "head_branch": "main",
        "path": ".github/workflows/ci.yml@main",
        "created_at": "2026-09-01T00:00:00Z",
        "updated_at": "2026-09-03T00:00:00Z",
        "run_started_at": "2026-09-02T00:00:00Z",
        "actor": ALICE,
        "triggering_actor": BOB,
        "check_suite_id": identity + 10000,
        "check_suite_node_id": f"CS{identity + 10000}",
        "head_commit": None,
        "repository": repo,
        "head_repository": repo,
        "pull_requests": [],
        "url": url,
        "jobs_url": url + "/jobs",
        "logs_url": url + "/logs",
        "check_suite_url": f"https://api.github.example/check-suites/{identity + 10000}",
        "artifacts_url": url + "/artifacts",
        "cancel_url": url + "/cancel",
        "rerun_url": url + "/rerun",
        "workflow_url": f"https://api.github.example/workflows/{workflow}",
        "html_url": f"https://github.example/runs/{identity}",
    }


RUNS = {"alpha": [run(3101, 4101), run(3102, 4101)], "beta": [run(3201, 4201)], "empty": []}


def cache(identity, key, version, size, ref="refs/heads/main"):
    return {
        "id": identity,
        "key": key,
        "version": version,
        "ref": ref,
        "size_in_bytes": size,
        "created_at": "2026-09-01T00:00:00Z",
        "last_accessed_at": "2026-09-03T00:00:00Z",
    }


CACHES = {
    "alpha": [
        cache(5101, "linux-main", "v1", 100),
        cache(5102, "linux-main", "v2", 250),
        cache(5103, "windows", "v1", 50, "refs/pull/3/merge"),
    ],
    "beta": [cache(5201, "linux-main", "v1", 80)],
    "empty": [],
}
# Deliberately independent from enumerated caches and from the organization total.
USAGE = {
    name: {"full_name": f"{OWNER}/{name}", "active_caches_count": count, "active_caches_size_in_bytes": size}
    for name, count, size in [("alpha", 4, 450), ("beta", 1, 90), ("empty", 0, 0)]
}
ORG_USAGE = {"total_active_caches_count": 6, "total_active_caches_size_in_bytes": 600}


def member(run_id, status, job_id=None):
    value = {
        "run_id": run_id,
        "run_name": "CI",
        "run_url": f"https://api.github.example/runs/{run_id}",
        "run_html_url": f"https://github.example/runs/{run_id}",
        "status": status,
    }
    if job_id is not None:
        value.update(
            job_id=job_id,
            job_name=f"Job {job_id}",
            job_url=None,
            job_html_url=f"https://github.example/jobs/{job_id}",
        )
    return value


def group(name, members):
    return {
        "group_name": name,
        "group_url": f"https://api.github.example/groups/{name}",
        "total_count": len(members),
        "group_members": members,
    }


GROUPS = {
    "alpha": [
        group(
            "deploy-main",
            [member(3101, "in_progress"), member(3102, "pending", 6102), member(3102, "pending", 6103)],
        ),
        group("test", [member(3102, "in_progress")]),
    ],
    "beta": [group("deploy-main", [member(3201, "pending", 6201)])],
    "empty": [],
}


def run_group(name, members):
    value = group(name, [])
    value.pop("total_count")
    value["group_members"] = [
        {
            **record,
            "position": position,
            "position_url": f"https://api.github.example/groups/{name}?ahead={record['run_id']}",
        }
        for record, position in members
    ]
    return value


RUN_GROUPS = {
    3101: [
        run_group("deploy-main", [(GROUPS["alpha"][0]["group_members"][0], 0)]),
        run_group("old-group", []),
    ],
    3102: [
        run_group(
            "deploy-main",
            [(GROUPS["alpha"][0]["group_members"][1], 1), (GROUPS["alpha"][0]["group_members"][2], 2)],
        ),
        run_group("test", [(GROUPS["alpha"][1]["group_members"][0], 0)]),
    ],
    3201: [run_group("deploy-main", [(GROUPS["beta"][0]["group_members"][0], 1)])],
}
TEAM = {
    "id": 8201,
    "node_id": "TEAM8201",
    "name": "Operators",
    "slug": "operators",
    "description": None,
    "permission": "pull",
    "type": "organization",
    "parent": None,
    "url": "https://api.github.example/teams/8201",
    "html_url": "https://github.example/teams/8201",
    "members_url": "https://api.github.example/teams/8201/members",
    "repositories_url": "https://api.github.example/teams/8201/repos",
}


def environment(identity, name):
    return {
        "id": identity,
        "node_id": f"ENV{identity}",
        "name": name,
        "url": f"https://api.github.example/environments/{identity}",
        "html_url": f"https://github.example/environments/{identity}",
    }


PRODUCTION, STAGING, BETA = (
    environment(7101, "production"),
    environment(7102, "staging"),
    environment(7201, "production"),
)


def pending(env, wait, approve, reviewers):
    return {
        "environment": env,
        "wait_timer": wait,
        "wait_timer_started_at": "2026-09-03T00:00:00Z" if wait else None,
        "current_user_can_approve": approve,
        "reviewers": reviewers,
    }


PENDING = {
    3101: [
        pending(
            PRODUCTION, 30, True, [{"type": "User", "reviewer": ALICE}, {"type": "Team", "reviewer": TEAM}]
        ),
        pending(STAGING, 0, False, []),
    ],
    3102: [],
    3201: [pending(BETA, 10, False, [{"type": "User", "reviewer": BOB}])],
}
APPROVAL = {"state": "approved", "user": ALICE, "comment": "Ship it", "environments": [PRODUCTION, STAGING]}
REVIEWS = {
    3101: [
        APPROVAL,
        copy.deepcopy(APPROVAL),
        {"state": "rejected", "user": BOB, "comment": "Retry", "environments": [PRODUCTION]},
    ],
    3102: [{"state": "pending", "user": ALICE, "comment": "Checking", "environments": []}],
    3201: [{"state": "approved", "user": BOB, "comment": "Ship", "environments": [BETA]}],
}


def respond(request):
    path = request.url.path
    if not path.startswith((f"/repos/{OWNER}/", f"/orgs/{OWNER}", f"/users/{OWNER}", "/users/actions-ops-")):
        return None
    if request.method != "GET":
        raise AssertionError(f"Unexpected operational Actions method {request.method}")
    if os.environ.get("CROSSFIELD_GITHUB_API_LOG"):
        with Path(os.environ["CROSSFIELD_GITHUB_API_LOG"]).open("a") as log:
            log.write(json.dumps({"path": path, "query": request.url.query.decode()}) + "\n")
    headers = {"Cache-Control": "no-store", "X-RateLimit-Remaining": "5000"}

    def response(value, status=200, next_page=None, cursor=False):
        result_headers = dict(headers)
        if next_page:
            name = "after" if cursor else "page"
            result_headers["Link"] = f'<{request.url.copy_set_param(name, str(next_page))}>; rel="next"'
        return httpx.Response(status, json=copy.deepcopy(value), headers=result_headers, request=request)

    def pages(rows, key=None, cursor=False):
        page = int(request.url.params.get("after" if cursor else "page", "1"))
        values = rows[page - 1 : page]
        return response(
            {"total_count": len(rows), key: values} if key else values,
            next_page=page + 1 if page < len(rows) else None,
            cursor=cursor,
        )

    if path in {f"/orgs/{OWNER}", f"/users/{OWNER}"}:
        return response(ORGANIZATION)
    if path == f"/orgs/{OWNER}/repos":
        return pages(REPOSITORIES)
    if path == f"/orgs/{OWNER}/actions/cache/usage":
        return response(ORG_USAGE)
    if path == f"/orgs/{OWNER}/actions/cache/usage-by-repository":
        return pages(list(USAGE.values()), "repository_cache_usages")
    for user in [ALICE, BOB]:
        if path == f"/users/{user['login']}":
            return response(user)
    parts = path.strip("/").split("/")
    name, tail = parts[2], parts[3:]
    if name not in CACHES:
        return response({"message": "Not Found"}, 404)
    if not tail:
        return response(next(repo for repo in REPOSITORIES if repo["name"] == name))
    if tail == ["actions", "caches"]:
        rows = CACHES[name]
        if request.url.params.get("ref"):
            rows = [row for row in rows if row["ref"] == request.url.params["ref"]]
        if request.url.params.get("key"):
            rows = [row for row in rows if row["key"].startswith(request.url.params["key"])]
        return pages(rows, "actions_caches")
    if tail == ["actions", "cache", "usage"]:
        return response(USAGE[name])
    if tail == ["actions", "concurrency_groups"]:
        return pages(
            [
                {k: value[k] for k in ["group_name", "group_url"]}
                | {"last_acquired_at": None if value["group_name"] == "test" else "2026-09-03T00:00:00Z"}
                for value in GROUPS[name]
            ],
            "concurrency_groups",
            cursor=True,
        )
    if tail[:2] == ["actions", "concurrency_groups"] and len(tail) == 3:
        value = next((copy.deepcopy(row) for row in GROUPS[name] if row["group_name"] == tail[2]), None)
        if value is None:
            return response({"message": "Inactive group"}, 404)
        for parameter, field in [("ahead_of_run", "run_id"), ("ahead_of_job", "job_id")]:
            if parameter in request.url.params:
                index = next(
                    (
                        i
                        for i, row in enumerate(value["group_members"])
                        if row.get(field) == int(request.url.params[parameter])
                        and (field != "run_id" or "job_id" not in row)
                    ),
                    None,
                )
                if index is None:
                    return response({"message": "Item is not in this concurrency group"}, 422)
                value["group_members"] = value["group_members"][: index + 1]
                value["total_count"] = len(value["group_members"])
        return response(value)
    if tail == ["actions", "runs"]:
        return pages(RUNS[name], "workflow_runs")
    if len(tail) == 4 and tail[:2] == ["actions", "workflows"] and tail[3] == "runs":
        return pages([row for row in RUNS[name] if row["workflow_id"] == int(tail[2])], "workflow_runs")
    if tail[:2] == ["actions", "runs"]:
        identity = int(tail[2])
        if identity not in {row["id"] for row in RUNS[name]}:
            return response({"message": "Not Found"}, 404)
        if len(tail) == 3:
            return response(next(row for row in RUNS[name] if row["id"] == identity))
        if tail[3] == "concurrency_groups":
            return pages(RUN_GROUPS[identity], "concurrency_groups", cursor=True)
        if tail[3] == "pending_deployments":
            return pages(PENDING[identity])
        if tail[3] == "approvals":
            return pages(REVIEWS[identity])
    raise AssertionError(f"Unexpected operational Actions path {path}")


if __name__ == "__main__":
    api.open_client = lambda: httpx.Client(transport=httpx.MockTransport(respond), follow_redirects=True)
    main()
