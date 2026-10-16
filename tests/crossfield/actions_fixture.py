"""Independent Actions oracle with reruns, missing links and one-row pages.

Run 1001 has a failed first attempt and a successful second attempt. Its three
jobs must survive all-attempt enumeration. Artifact names repeat, one artifact
has expired, and another has no run link. None of these facts come from the model.
"""

from __future__ import annotations

import copy
import json
import os
import re
from pathlib import Path

import connected_fixture as baseline
import httpx

from vgi_github.generated_worker import main


def workflow(identity, name, state="active"):
    return {
        "id": identity,
        "node_id": f"W{identity}",
        "name": name,
        "path": f".github/workflows/{name.lower()}.yml",
        "state": state,
        "created_at": "2026-09-01T00:00:00Z",
        "updated_at": "2026-09-02T00:00:00Z",
        "url": f"https://api.github.com/repos/example/alpha/actions/workflows/{identity}",
        "html_url": f"https://github.com/example/alpha/actions/workflows/{identity}",
        "badge_url": f"https://github.com/example/alpha/actions/workflows/{identity}/badge.svg",
    }


WORKFLOWS = [workflow(601, "CI"), workflow(602, "Package", "disabled_manually")]


def run(identity, workflow_id, attempt, conclusion, actor="alice", triggering_actor="bob"):
    return {
        "id": identity,
        "node_id": f"RUN{identity}",
        "workflow_id": workflow_id,
        "run_number": identity - 1000,
        "run_attempt": attempt,
        "name": "CI" if workflow_id == 601 else "Package",
        "display_title": f"Run {identity}",
        "event": "push",
        "status": "completed" if conclusion else "queued",
        "conclusion": conclusion,
        "head_sha": "abc123",
        "head_branch": "main",
        "path": ".github/workflows/ci.yml@main",
        "created_at": "2026-09-01T00:00:00Z",
        "updated_at": "2026-09-03T00:00:00Z",
        "run_started_at": "2026-09-02T00:00:00Z",
        "actor": baseline.USERS[actor],
        "triggering_actor": baseline.USERS[triggering_actor],
        "check_suite_id": identity + 9000,
        "check_suite_node_id": f"CS{identity + 9000}",
        "referenced_workflows": [
            {
                "path": "other/reusable/.github/workflows/build.yml@main",
                "sha": "d" * 40,
                "ref": "refs/heads/main",
            }
        ]
        if identity == 1001
        else None,
        "pull_requests": [
            {
                "id": 77,
                "number": 7,
                "url": "https://api.github.com/repos/example/alpha/pulls/7",
                "head": {
                    "ref": "feature",
                    "sha": "abc123",
                    "repo": {
                        "id": 901,
                        "url": "https://api.github.com/repos/contributor/fork",
                        "name": "fork",
                    },
                },
                "base": {
                    "ref": "main",
                    "sha": "def456",
                    "repo": {"id": 101, "url": "https://api.github.com/repos/example/alpha", "name": "alpha"},
                },
            }
        ]
        if identity == 1001
        else [],
        "head_commit": {
            "id": "abc123",
            "tree_id": "t" * 40,
            "message": "Build this commit",
            "timestamp": "2026-09-01T00:00:00Z",
            "author": {"name": "Git Author", "email": "author@example.invalid"},
            "committer": None,
        }
        if identity != 1002
        else None,
        "repository": baseline.REPOSITORIES[0],
        "head_repository": {
            "id": 901,
            "node_id": "REPO901",
            "name": "fork",
            "full_name": "contributor/fork",
            "owner": {"id": 2, "login": "bob", "type": "User"},
            "private": False,
            "html_url": "https://github.com/contributor/fork",
            "description": None,
            "fork": True,
            "default_branch": "feature",
        }
        if identity == 1001
        else baseline.REPOSITORIES[0],
        "head_repository_id": 901 if identity == 1001 else 101,
        "url": f"https://api.github.com/repos/example/alpha/actions/runs/{identity}",
        "jobs_url": f"https://api.github.com/repos/example/alpha/actions/runs/{identity}/jobs",
        "logs_url": f"https://api.github.com/repos/example/alpha/actions/runs/{identity}/logs",
        "check_suite_url": f"https://api.github.com/repos/example/alpha/check-suites/{identity + 9000}",
        "artifacts_url": f"https://api.github.com/repos/example/alpha/actions/runs/{identity}/artifacts",
        "cancel_url": f"https://api.github.com/repos/example/alpha/actions/runs/{identity}/cancel",
        "rerun_url": f"https://api.github.com/repos/example/alpha/actions/runs/{identity}/rerun",
        "previous_attempt_url": (
            f"https://api.github.com/repos/example/alpha/actions/runs/{identity}" + f"/attempts/{attempt - 1}"
        )
        if attempt > 1
        else None,
        "workflow_url": f"https://api.github.com/repos/example/alpha/actions/workflows/{workflow_id}",
        "html_url": f"https://github.com/example/alpha/actions/runs/{identity}",
    }


RUNS = [run(1001, 601, 2, "success"), run(1002, 601, 1, None), run(1003, 602, 1, "failure")]
ATTEMPTS = {
    (1001, 1): run(1001, 601, 1, "failure", triggering_actor="alice"),
    (1001, 2): RUNS[0],
    (1002, 1): RUNS[1],
    (1003, 1): RUNS[2],
}


def step(number, conclusion):
    return {
        "number": number,
        "name": f"Step {number}",
        "status": "completed",
        "conclusion": conclusion,
        "started_at": None if conclusion == "skipped" else "2026-09-02T00:00:00Z",
        "completed_at": None if conclusion == "skipped" else "2026-09-02T00:30:00Z",
    }


def job(identity, run_id, attempt, conclusion, end, steps):
    return {
        "id": identity,
        "node_id": f"JOB{identity}",
        "run_id": run_id,
        "run_attempt": attempt,
        "name": f"Job {identity}",
        "workflow_name": "CI" if run_id == 1001 else "Package",
        "head_sha": "abc123",
        "head_branch": "main",
        "status": "completed",
        "conclusion": conclusion,
        "created_at": "2026-09-02T00:00:00Z",
        "started_at": "2026-09-02T00:00:00Z",
        "completed_at": end,
        "runner_id": 501,
        "runner_name": "linux",
        "runner_group_id": 1,
        "runner_group_name": "Default",
        "labels": ["ubuntu-latest"],
        "steps": [step(i + 1, value) for i, value in enumerate(steps)],
        "html_url": f"https://github.com/example/alpha/actions/runs/{run_id}/job/{identity}",
        "url": f"https://api.github.com/repos/example/alpha/actions/jobs/{identity}",
        "run_url": f"https://api.github.com/repos/example/alpha/actions/runs/{run_id}",
        "check_run_url": f"https://api.github.com/repos/example/alpha/check-runs/{identity}",
    }


JOBS = [
    job(2001, 1001, 1, "failure", "2026-09-02T01:00:00Z", ["success", "failure"]),
    job(2002, 1001, 2, "success", "2026-09-02T02:00:00Z", ["success", "success"]),
    job(2003, 1001, 2, "success", "2026-09-02T00:30:00Z", ["success"]),
    job(2004, 1003, 1, "failure", "2026-09-02T03:00:00Z", ["failure", "skipped"]),
]


def artifact(identity, run_id, size, expired=False):
    return {
        "id": identity,
        "node_id": f"ART{identity}",
        "name": "build-output",
        "size_in_bytes": size,
        "expired": expired,
        "created_at": "2026-09-02T00:00:00Z",
        "updated_at": "2026-09-02T01:00:00Z",
        "expires_at": "2026-09-03T00:00:00Z" if expired else "2026-12-03T00:00:00Z",
        "digest": None if expired else f"sha256:{identity}",
        "workflow_run": {
            "id": run_id,
            "head_sha": "abc123",
            "head_branch": "main",
            "repository_id": 101,
            "head_repository_id": 901 if run_id == 1001 else 101,
        }
        if run_id
        else None,
        "url": f"https://api.github.com/repos/example/alpha/actions/artifacts/{identity}",
        "archive_download_url": f"https://api.github.com/repos/example/alpha/actions/artifacts/{identity}/zip",
    }


ARTIFACTS = [
    artifact(3001, 1001, 10),
    artifact(3002, 1001, 20, True),
    artifact(3003, 1003, 40),
    artifact(3004, None, 5),
]


def respond(request):
    match = re.fullmatch(r"/repos/example/(alpha|beta|empty)/actions/(.*)", request.url.path)
    if not match:
        return None
    repo, suffix = match.groups()
    if os.environ.get("CROSSFIELD_GITHUB_API_LOG"):
        with Path(os.environ["CROSSFIELD_GITHUB_API_LOG"]).open("a") as log:
            log.write(json.dumps({"path": request.url.path, "query": str(request.url.query)}) + "\n")
    headers = {"Cache-Control": "no-store", "X-RateLimit-Remaining": "5000"}

    def response(value, status=200, extra=None):
        return httpx.Response(
            status, json=copy.deepcopy(value), headers=headers | (extra or {}), request=request
        )

    def listing(key, rows):
        assert request.url.params.get("per_page") == "100"
        rows = rows if repo == "alpha" else []
        page = int(request.url.params.get("page", "1"))
        extra = {}
        if page < len(rows):
            extra["Link"] = f'<{request.url.copy_set_param("page", str(page + 1))}>; rel="next"'
        return response({"total_count": len(rows), key: rows[page - 1 : page]}, extra=extra)

    def lookup(rows, identity):
        found = next((row for row in rows if row["id"] == int(identity)), None) if repo == "alpha" else None
        return response(found) if found else response({"message": "Not Found"}, 404)

    if suffix == "workflows":
        return listing("workflows", WORKFLOWS)
    if suffix == "runs":
        return listing("workflow_runs", RUNS)
    if suffix == "artifacts":
        return listing("artifacts", ARTIFACTS)
    parts = suffix.split("/")
    if len(parts) == 2 and parts[0] in {"workflows", "runs", "jobs", "artifacts"}:
        return lookup(
            {"workflows": WORKFLOWS, "runs": RUNS, "jobs": JOBS, "artifacts": ARTIFACTS}[parts[0]], parts[1]
        )
    if len(parts) == 3 and parts[0] == "workflows" and parts[2] == "runs":
        return listing("workflow_runs", [row for row in RUNS if row["workflow_id"] == int(parts[1])])
    if len(parts) == 3 and parts[0] == "runs":
        run_id = int(parts[1])
        if parts[2] == "jobs":
            assert request.url.params.get("filter") == "all", (
                "All-attempt population must explicitly request filter=all"
            )
            return listing("jobs", [row for row in JOBS if row["run_id"] == run_id])
        if parts[2] == "artifacts":
            return listing(
                "artifacts",
                [row for row in ARTIFACTS if row["workflow_run"] and row["workflow_run"]["id"] == run_id],
            )
    if len(parts) in {4, 5} and parts[0] == "runs" and parts[2] == "attempts":
        run_id, attempt = int(parts[1]), int(parts[3])
        if len(parts) == 5 and parts[4] == "jobs":
            return listing(
                "jobs", [row for row in JOBS if row["run_id"] == run_id and row["run_attempt"] == attempt]
            )
        if len(parts) == 4:
            row = ATTEMPTS.get((run_id, attempt))
            return response(row) if row else response({"message": "Not Found"}, 404)
    raise AssertionError(f"Unexpected Actions request: {request.url}")


def respond_with_baseline(request):
    response = respond(request)
    return response if response is not None else baseline.respond(request)


baseline.api.open_client = lambda: httpx.Client(
    transport=httpx.MockTransport(respond_with_baseline), follow_redirects=True
)
if __name__ == "__main__":
    main()
