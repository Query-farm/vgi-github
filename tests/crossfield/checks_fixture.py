"""Independent Checks oracle with reruns, null actors and repeated annotations.

Every collection page contains one row. The ref run endpoint deliberately fails:
complete reference traversal must enumerate suites and then all runs per suite.
"""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path

import connected_fixture as baseline
import httpx
from graphql import parse

from vgi_github.generated_worker import main

SHA = "a" * 40


def suite(identity, *, branch="main", conclusion="success", app=True):
    return {
        "id": identity,
        "node_id": f"CS{identity}",
        "head_branch": branch,
        "head_sha": SHA,
        "status": "completed" if conclusion else "in_progress",
        "conclusion": conclusion,
        "url": f"https://api.github.example/check-suites/{identity}",
        "before": "b" * 40,
        "after": SHA,
        "created_at": "2026-10-01T00:00:00Z",
        "updated_at": "2026-10-01T01:00:00Z",
        "latest_check_runs_count": 1,
        "check_runs_url": f"https://api.github.example/check-suites/{identity}/check-runs",
        "app": {"id": 10, "slug": "fixture-ci"} if app else None,
        "pull_requests": [{"id": 1001, "number": 1}],
        "repository": baseline.REPOSITORIES[0],
        "head_commit": {"id": SHA},
    }


def run(identity, suite_id, conclusion, *, annotations=0, app=True):
    return {
        "id": identity,
        "node_id": f"CR{identity}",
        "name": "lint" if suite_id == 100 else "build",
        "head_sha": SHA,
        "external_id": None,
        "url": f"https://api.github.example/check-runs/{identity}",
        "html_url": None,
        "details_url": None,
        "status": "completed" if conclusion else "in_progress",
        "conclusion": conclusion,
        "started_at": "2026-10-01T00:00:00Z",
        "completed_at": "2026-10-01T01:00:00Z" if conclusion else None,
        "check_suite": {"id": suite_id} if suite_id else None,
        "app": {"id": 10, "slug": "fixture-ci"} if app else None,
        "output": {
            "title": None,
            "summary": None,
            "text": None,
            "annotations_count": annotations,
            "annotations_url": f"https://api.github.example/check-runs/{identity}/annotations",
        },
        "pull_requests": [],
        **(
            {
                "deployment": {
                    "id": 501,
                    "node_id": "D501",
                    "url": "https://api.github.example/deployments/501",
                    "task": "deploy",
                    "environment": "production",
                    "original_environment": "staging",
                    "description": "Deploy build",
                    "created_at": "2026-10-01T00:00:00Z",
                    "updated_at": "2026-10-01T01:00:00Z",
                    "statuses_url": "https://api.github.example/deployments/501/statuses",
                    "repository_url": "https://api.github.example/repos/example/alpha",
                    "transient_environment": False,
                    "production_environment": True,
                    "performed_via_github_app": None,
                }
            }
            if identity == 6001
            else {}
        ),
    }


def annotation(level, path="src/main.py"):
    return {
        "path": path,
        "start_line": 10,
        "end_line": 12,
        "start_column": None,
        "end_column": None,
        "annotation_level": level,
        "title": None,
        "message": "Repeated content is not a duplicate entity.",
        "raw_details": None,
        "blob_href": f"https://github.example/blob/{SHA}/{path}",
    }


SUITES = {
    "alpha": [suite(100), suite(101, branch=None, conclusion=None, app=False)],
    "beta": [suite(200)],
    "empty": [],
}
RUNS = {
    100: [run(6001, 100, "failure", annotations=3), run(6002, 100, "success", annotations=1)],
    101: [run(6003, 101, None, app=False)],
    200: [run(6004, 200, "neutral")],
}
ORPHAN_RUN = run(6005, None, None, annotations=1, app=False)
LATE_RUN = run(6006, 100, "failure", annotations=2)
ANNOTATIONS = {
    6001: [annotation("failure"), annotation("failure"), annotation("warning")],
    6002: [annotation("notice", "README.md")],
    6003: [],
    6004: [],
    6005: [annotation("notice", "orphan.py")],
    6006: [annotation("failure"), annotation("failure")],
}


def step(number, name, status, conclusion, seconds=None, external=None):
    return {
        "number": number,
        "name": name,
        "status": status,
        "conclusion": conclusion,
        "externalId": external,
        "secondsToCompletion": seconds,
        "startedAt": "2026-10-01T00:00:00Z" if status != "PENDING" else None,
        "completedAt": "2026-10-01T00:00:20Z" if status == "COMPLETED" else None,
    }


STEPS = {
    6001: [
        step(1, "Checkout", "COMPLETED", "SUCCESS", 5, "checkout"),
        step(2, "Lint", "COMPLETED", "FAILURE", 12),
    ],
    6002: [step(1, "Checkout", "COMPLETED", "SUCCESS", 5), step(2, "Lint", "COMPLETED", "SUCCESS", 8)],
    6003: [step(1, "Build", "IN_PROGRESS", None)],
    6004: [],
    6005: [step(1, "Await runner", "PENDING", None)],
    6006: [],
}
GRAPH_NODES = {}
for name, suites in SUITES.items():
    for value in suites:
        identity = value["id"]
        repository = {"databaseId": 101 if name == "alpha" else 102, "nameWithOwner": "example/" + name}
        GRAPH_NODES["CS" + str(identity)] = {
            "__typename": "CheckSuite",
            "id": "CS" + str(identity),
            "databaseId": identity,
            "repository": repository,
            "creator": {"id": "U1", "databaseId": 1, "login": "alice", "url": "https://github.example/alice"}
            if identity == 100
            else None,
            "branch": {"id": "REF-main", "name": "main", "prefix": "refs/heads/"}
            if identity == 100
            else None,
            "push": {
                "id": "PUSH1",
                "previousSha": "b" * 40,
                "nextSha": SHA,
                "permalink": "https://github.example/push/1",
                "pusher": {"__typename": "Bot", "login": "ci-bot"},
            }
            if identity == 100
            else None,
            "workflowRun": {
                "id": "WR9001",
                "databaseId": 9001,
                "runNumber": 7,
                "event": "push",
                "url": "https://github.example/run/9001",
                "file": {
                    "id": "WRF1",
                    "path": ".github/workflows/build.yml",
                    "repositoryName": "other/reusable",
                    "repositoryFileUrl": "https://github.example/other/reusable/blob/main/.github/workflows/build.yml",
                    "resourcePath": "/other/reusable/workflow",
                    "url": "https://github.example/workflow/file",
                    "viewerCanPushRepository": False,
                    "viewerCanReadRepository": True,
                },
            }
            if identity == 100
            else None,
            "url": "https://github.example/suite/" + str(identity),
            "resourcePath": "/suite/" + str(identity),
        }
        for check_run in RUNS[identity]:
            run_id = check_run["id"]
            GRAPH_NODES["CR" + str(run_id)] = {
                "__typename": "CheckRun",
                "id": "CR" + str(run_id),
                "databaseId": run_id,
                "repository": repository,
                "deployment": {
                    "id": "D501",
                    "databaseId": 501,
                    "commitOid": SHA,
                    "createdAt": "2026-10-01T00:00:00Z",
                    "updatedAt": "2026-10-01T01:00:00Z",
                    "description": "Deploy build",
                    "environment": "production",
                    "latestEnvironment": "production",
                    "originalEnvironment": "staging",
                    "state": "ACTIVE",
                    "task": "deploy",
                }
                if run_id == 6001
                else None,
                "pendingDeploymentRequest": {
                    "currentUserCanApprove": False,
                    "waitTimer": 5,
                    "waitTimerStartedAt": None,
                    "environment": {
                        "id": "ENV50",
                        "databaseId": 50,
                        "name": "production",
                        "isPinned": True,
                        "pinnedPosition": 1,
                    },
                }
                if run_id == 6003
                else None,
                "permalink": "https://github.example/check/" + str(run_id),
                "resourcePath": "/check/" + str(run_id),
            }
for run_id in [6005, 6006]:
    GRAPH_NODES["CR" + str(run_id)] = {
        "__typename": "CheckRun",
        "id": "CR" + str(run_id),
        "databaseId": run_id,
        "repository": {"databaseId": 101, "nameWithOwner": "example/alpha"},
        "deployment": None,
        "pendingDeploymentRequest": None,
        "permalink": "https://github.example/check/" + str(run_id),
        "resourcePath": "/check/" + str(run_id),
    }


def wire(selection_set, value):
    """Return the requested wire names, including generated aliases and fragments."""
    if value is None:
        return None
    if isinstance(value, list):
        return [wire(selection_set, item) for item in value]
    output = {}
    for selection in selection_set.selections:
        if selection.kind == "inline_fragment":
            if selection.type_condition.name.value == value.get("__typename"):
                output.update(wire(selection.selection_set, value))
            continue
        name = selection.name.value
        child = value.get(name)
        output[selection.alias.value if selection.alias else name] = (
            wire(selection.selection_set, child) if selection.selection_set else child
        )
    return output


def respond(request):
    path = request.url.path
    pieces = path.strip("/").split("/")
    headers = {"Cache-Control": "no-store", "X-RateLimit-Remaining": "5000"}

    def response(value, status=200, next_page=None):
        result_headers = dict(headers)
        if next_page:
            result_headers["Link"] = f'<{request.url.copy_set_param("page", str(next_page))}>; rel="next"'
        if os.environ.get("CROSSFIELD_GITHUB_API_LOG"):
            with Path(os.environ["CROSSFIELD_GITHUB_API_LOG"]).open("a") as log:
                log.write(json.dumps({"path": path, "query": request.url.query.decode()}) + "\n")
        return httpx.Response(status, json=copy.deepcopy(value), headers=result_headers, request=request)

    def pages(rows, key=None, fail_later=False):
        page = int(request.url.params.get("page", "1"))
        if fail_later and page > 1:
            return response({"message": "Later Checks page unavailable"}, 503)
        value = rows[page - 1 : page]
        if key:
            value = {"total_count": len(rows), key: value}
        return response(value, next_page=page + 1 if page < len(rows) else None)

    if path == "/graphql" and request.method == "POST":
        payload = json.loads(request.content)
        identity = payload.get("variables", {}).get("node_id", "")
        if not identity.startswith(("CR", "CS")):
            return None
        node = copy.deepcopy(GRAPH_NODES.get(identity))
        if node is not None and identity.startswith("CR"):
            rows = STEPS[int(identity[2:])]
            cursor = payload["variables"].get("cursor")
            index = int(cursor.split(":")[-1]) if cursor else 0
            node["steps"] = {
                "nodes": rows[index : index + 1],
                "pageInfo": {
                    "hasNextPage": index + 1 < len(rows),
                    "endCursor": "step:" + str(index + 1) if index + 1 < len(rows) else None,
                },
            }
        operation = next(
            definition
            for definition in parse(payload["query"]).definitions
            if definition.kind == "operation_definition"
        )
        return response({"data": wire(operation.selection_set, {"node": node})})

    if request.method != "GET" or len(pieces) < 4 or pieces[:2] != ["repos", "example"]:
        return None
    repo, endpoint = pieces[2:4]
    if endpoint == "commits" and len(pieces) == 6:
        git_ref, collection = pieces[4:6]
        if collection == "check-runs":
            return response({"message": "The capped reference endpoint must not be used"}, 422)
        if collection == "check-suites":
            if git_ref == "private-ref":
                return response({"message": "Checks are not visible to this credential"}, 403)
            rows = SUITES.get(repo, []) if git_ref in {"main", SHA, "late-ref"} else []
            return pages(rows, "check_suites", fail_later=git_ref == "late-ref")
    if endpoint == "check-suites" and len(pieces) in {5, 6}:
        identity = int(pieces[4])
        if len(pieces) == 6 and pieces[5] == "check-runs":
            if identity not in {value["id"] for value in SUITES.get(repo, [])}:
                return response({"message": "No such suite in this repository"}, 404)
            if request.url.params.get("filter") != "all":
                return response({"message": "Every run listing must explicitly request filter=all"}, 422)
            return pages(RUNS.get(identity, []), "check_runs")
        row = next((value for value in SUITES.get(repo, []) if value["id"] == identity), None)
        return response(row) if row else response({"message": "No such suite"}, 404)
    if endpoint == "check-runs" and len(pieces) in {5, 6}:
        identity = int(pieces[4])
        if len(pieces) == 6 and pieces[5] == "annotations":
            return pages(ANNOTATIONS.get(identity, []), fail_later=identity == 6006)
        rows = [value for group in SUITES.get(repo, []) for value in RUNS[group["id"]]]
        if repo == "alpha":
            rows += [ORPHAN_RUN, LATE_RUN]
        row = next((value for value in rows if value["id"] == identity), None)
        return response(row) if row else response({"message": "No such run"}, 404)
    return None


def respond_all(request):
    response = respond(request)
    return response if response is not None else baseline.respond(request)


baseline.api.open_client = lambda: httpx.Client(
    transport=httpx.MockTransport(respond_all), follow_redirects=True
)
if __name__ == "__main__":
    main()
