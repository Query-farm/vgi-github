"""Independent security observations with repeated analysis results and distinct actor roles.

Alert numbers repeat across repositories. One upload creates two analyses; one
alert has two current instances. Variant targets differ from the controller and
skipped repositories deliberately expose a nonexhaustive member list.
"""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path

import httpx

from vgi_github import github_api as api
from vgi_github.generated_worker import main

ORG = {
    "id": 910,
    "login": "scan-fixture",
    "type": "Organization",
    "name": "Scanning fixture",
    "description": "Independent fixture",
    "created_at": "2020-01-01T00:00:00Z",
}
REPOSITORIES = [
    {
        "id": i,
        "node_id": f"R{i}",
        "name": n,
        "full_name": f"scan-fixture/{n}",
        "owner": {"id": 910, "login": "scan-fixture", "type": "Organization"},
        "private": False,
        "description": "Security fixture",
        "topics": [],
        "language": "Python",
        "stargazers_count": 0,
        "updated_at": "2026-09-01T00:00:00Z",
    }
    for i, n in [(911, "alpha"), (912, "beta"), (913, "empty"), (914, "target")]
]
BY_NAME = {r["name"]: r for r in REPOSITORIES}


def actor(identity, login):
    return {"id": identity, "login": login, "type": "User", "html_url": f"https://github.com/{login}"}


ALICE, BOB = actor(201, "alice"), actor(202, "bob")
TOOL = {"name": "CodeQL", "version": "2.20", "guid": "tool-1"}


def instance(number, ref="refs/heads/main", state="open", environment='{"language":"python"}'):
    return {
        "ref": ref,
        "analysis_key": "workflow/analyze",
        "environment": environment,
        "category": "python",
        "state": state,
        "commit_sha": str(number) * 40,
        "message": {"text": "Untrusted input", "markdown": "**Untrusted input**"},
        "location": {
            "path": f"src/{number}.py",
            "start_line": 10,
            "end_line": 11,
            "start_column": 2,
            "end_column": 8,
        },
        "html_url": f"https://github.com/scan-fixture/alpha/security/code-scanning/{number}",
        "classifications": [],
    }


def alert(repo, number, state, severity):
    result = {
        "number": number,
        "created_at": "2026-09-01T00:00:00Z",
        "updated_at": "2026-09-03T00:00:00Z",
        "state": state,
        "fixed_at": "2026-09-02T00:00:00Z" if state == "fixed" else None,
        "dismissed_by": BOB if state == "dismissed" else None,
        "dismissal_approved_by": ALICE if state == "dismissed" else None,
        "dismissed_at": "2026-09-03T00:00:00Z" if state == "dismissed" else None,
        "dismissed_reason": "false positive" if state == "dismissed" else None,
        "dismissed_comment": "Fixture justification" if state == "dismissed" else None,
        "rule": {
            "id": f"py/rule-{number}",
            "name": "Untrusted input",
            "severity": "warning",
            "security_severity_level": severity,
            "description": "Rule summary",
            "full_description": "Independent complete rule",
            "tags": ["security", "external/cwe/cwe-020"],
            "help": "Validate input",
            "help_uri": "https://example.com/rule",
        },
        "tool": TOOL,
        "most_recent_instance": instance(number, state=state),
        "assignees": [ALICE] if number == 1 else [],
        "linked_pull_requests": [
            {
                "id": 801,
                "number": 12,
                "state": "open",
                "title": "Fix validation",
                "html_url": "https://github.com/scan-fixture/alpha/pull/12",
                "user": BOB,
            }
        ]
        if number == 1
        else [],
        "repository": BY_NAME[repo],
    }
    for name in ["url", "html_url", "instances_url"]:
        result[name] = f"https://github.com/scan-fixture/{repo}/security/code-scanning/{number}"
    return result


ALERTS = {
    "alpha": [
        alert("alpha", 1, "open", "high"),
        alert("alpha", 2, "fixed", "medium"),
        alert("alpha", 3, "dismissed", "critical"),
    ],
    "beta": [alert("beta", 1, "open", "low")],
    "empty": [],
    "target": [],
}
INSTANCES = {
    1: [instance(1), instance(1, "refs/heads/feature", environment='{"language":"javascript"}')],
    2: [instance(2, state="fixed")],
    # Dismissal is an alert lifecycle; the location can still be present in code.
    3: [instance(3, state="open")],
}
ANALYSES = [
    {
        "id": identity,
        "ref": ref,
        "commit_sha": str(identity)[-1] * 40,
        "analysis_key": "workflow/analyze",
        "environment": '{"language":"python"}',
        "category": "python",
        "error": "" if identity != 503 else "No database",
        "created_at": f"2026-09-0{index + 1}T00:00:00Z",
        "results_count": results,
        "rules_count": rules,
        "url": f"https://api.github.com/repos/scan-fixture/alpha/code-scanning/analyses/{identity}",
        "sarif_id": upload,
        "tool": TOOL,
        "deletable": True,
        "warning": "",
    }
    for index, (identity, ref, results, rules, upload) in enumerate(
        [
            (501, "refs/heads/main", 5, 100, "upload-1"),
            (502, "refs/heads/feature", 3, 100, "upload-1"),
            (503, "refs/heads/main", 0, 0, "upload-2"),
        ]
    )
]
DATABASES = [
    {
        "id": identity,
        "name": language + ".zip",
        "language": language,
        "uploader": BOB,
        "content_type": "application/zip",
        "size": size,
        "created_at": "2026-09-01T00:00:00Z",
        "updated_at": "2026-09-02T00:00:00Z",
        "url": f"https://api.github.com/repos/scan-fixture/alpha/code-scanning/codeql/databases/{language}",
        "commit_oid": "a" * 40 if language == "python" else None,
    }
    for identity, language, size in [(601, "python", 10), (602, "javascript", 30)]
]
TASKS = {
    "scan-fixture/alpha": {
        "repository": BY_NAME["alpha"],
        "analysis_status": "succeeded",
        "artifact_size_in_bytes": 50,
        "result_count": 7,
        "database_commit_sha": "a" * 40,
        "source_location_prefix": "/src",
        "artifact_url": "https://example.com/variant.zip",
    },
    "scan-fixture/target": {
        "repository": BY_NAME["target"],
        "analysis_status": "failed",
        "failure_message": "No supported database",
    },
}
VARIANT = {
    "id": 701,
    "controller_repo": BY_NAME["alpha"],
    "actor": ALICE,
    "query_language": "python",
    "query_pack_url": "https://example.com/query.zip",
    "created_at": "2026-09-01T00:00:00Z",
    "updated_at": "2026-09-02T00:00:00Z",
    "completed_at": "2026-09-02T00:00:00Z",
    "status": "succeeded",
    "actions_workflow_run_id": 1001,
    "scanned_repositories": list(TASKS.values()),
    "skipped_repositories": {
        "access_mismatch_repos": {"repository_count": 5, "repositories": [BY_NAME["beta"]]},
        "not_found_repos": {"repository_count": 2, "repository_full_names": ["missing/one"]},
        "no_codeql_db_repos": {"repository_count": 0, "repositories": []},
        "over_limit_repos": {"repository_count": 0, "repositories": []},
    },
}
SETUP = {
    "state": "configured",
    "languages": ["python", "javascript-typescript"],
    "runner_type": "standard",
    "runner_label": None,
    "query_suite": "extended",
    "threat_model": "remote",
    "updated_at": "2026-09-01T00:00:00Z",
    "schedule": "weekly",
}


def dismissal(repo, identity, number, state):
    return {
        "id": identity,
        "number": number + 100,
        "repository": BY_NAME[repo],
        "organization": {"id": 910, "name": "scan-fixture"},
        "requester": {"actor_id": 201, "actor_name": "alice"},
        "request_type": "code_scanning",
        "data": [
            {"reason": "false_positive", "alert_number": str(number), "pr_review_thread_id": "thread-1"}
        ],
        "resource_identifier": f"alert-{number}",
        "status": state,
        "requester_comment": None,
        "created_at": "2026-09-01T00:00:00Z",
        "expires_at": "2026-10-01T00:00:00Z",
        "responses": [
            {
                "id": identity + 100,
                "reviewer": {"actor_id": 202, "actor_name": "bob"},
                "message": "Reviewed",
                "status": state,
                "created_at": "2026-09-02T00:00:00Z",
            }
        ]
        if state != "pending"
        else [],
        "url": f"https://api.github.com/repos/scan-fixture/{repo}/dismissal-requests/code-scanning/{number}",
        "html_url": f"https://github.com/scan-fixture/{repo}/security/code-scanning/{number}",
    }


DISMISSALS = {
    "alpha": [dismissal("alpha", 901, 3, "approved"), dismissal("alpha", 902, 1, "pending")],
    "beta": [dismissal("beta", 903, 1, "denied")],
    "empty": [],
    "target": [],
}


def respond(request):
    path = request.url.path
    if not (
        path.startswith("/repos/scan-fixture/")
        or path.startswith("/orgs/scan-fixture")
        or path == "/users/scan-fixture"
    ):
        return None
    if os.environ.get("CROSSFIELD_GITHUB_API_LOG"):
        with Path(os.environ["CROSSFIELD_GITHUB_API_LOG"]).open("a") as log:
            log.write(json.dumps({"path": path, "query": str(request.url.query)}) + "\n")
    headers = {"Cache-Control": "no-store", "X-RateLimit-Remaining": "5000"}

    def response(value, status=200, extra=None):
        return httpx.Response(
            status, json=copy.deepcopy(value), headers=headers | (extra or {}), request=request
        )

    def listing(rows):
        page = int(request.url.params.get("page", "1"))
        extra = (
            {"Link": f'<{request.url.copy_set_param("page", str(page + 1))}>; rel="next"'}
            if page < len(rows)
            else {}
        )
        return response(rows[page - 1 : page], extra=extra)

    def alert_filter(rows):
        for key in ["tool_name", "tool_guid"]:
            if request.url.params.get(key) and request.url.params[key] != TOOL[key.removeprefix("tool_")]:
                rows = []
        state = request.url.params.get("state")
        if state:
            rows = [r for r in rows if (r["state"] != "open" if state == "closed" else r["state"] == state)]
        if request.url.params.get("severity"):
            rows = [r for r in rows if r["rule"]["security_severity_level"] == request.url.params["severity"]]
        if request.url.params.get("ref") == "refs/heads/feature" or request.url.params.get("pr") == "12":
            rows = [r for r in rows if r["number"] == 1]
        if request.url.params.get("assignees"):
            value = request.url.params["assignees"]
            rows = [
                r
                for r in rows
                if (
                    not r["assignees"]
                    if value == "none"
                    else bool(r["assignees"])
                    if value == "*"
                    else any(a["login"] in value.split(",") for a in r["assignees"])
                )
            ]
        return rows

    def dismissal_filter(rows):
        status = request.url.params.get("request_status")
        if status and status != "all":
            rows = [r for r in rows if r["status"] == ("pending" if status == "open" else status)]
        requester = request.url.params.get("requester")
        if requester:
            rows = [r for r in rows if r["requester"]["actor_name"] == requester]
        reviewer = request.url.params.get("reviewer")
        if reviewer:
            rows = [r for r in rows if any(v["reviewer"]["actor_name"] == reviewer for v in r["responses"])]
        return rows

    if path in {"/users/scan-fixture", "/orgs/scan-fixture"}:
        return response(ORG)
    if path == "/orgs/scan-fixture/repos":
        return listing(REPOSITORIES)
    if path == "/orgs/scan-fixture/code-scanning/alerts":
        return listing(alert_filter([a for values in ALERTS.values() for a in values]))
    if path == "/orgs/scan-fixture/code-scanning/ai-scan":
        return response({"pr_scan": "enabled"})
    if path == "/orgs/scan-fixture/dismissal-requests/code-scanning":
        return listing(dismissal_filter([r for values in DISMISSALS.values() for r in values]))
    parts = path.split("/")
    repo = parts[3]
    suffix = "/".join(parts[4:])
    if not suffix:
        return response(BY_NAME[repo])
    if suffix == "code-scanning/alerts":
        if request.url.params.get("tool_name") and request.url.params.get("tool_guid"):
            return response({"message": "tool_name and tool_guid are mutually exclusive"}, 422)
        return listing(alert_filter(ALERTS[repo]))
    if suffix.startswith("code-scanning/alerts/"):
        components = suffix.split("/")
        number = int(components[2])
        selected = next((a for a in ALERTS[repo] if a["number"] == number), None)
        if selected is None:
            return response({"message": "Not Found"}, 404)
        if len(components) == 3:
            return response(selected)
        if components[3] == "instances":
            rows = copy.deepcopy(INSTANCES[number])
            for row in rows:
                row["message"].pop("markdown", None)
            if request.url.params.get("ref"):
                rows = [r for r in rows if r["ref"] == request.url.params["ref"]]
            if request.url.params.get("pr"):
                rows = rows[1:]
            return listing(rows)
        if components[3] == "autofix":
            return response(
                {
                    "status": "success" if number == 1 else "pending",
                    "description": "Validate the input" if number == 1 else None,
                    "started_at": "2026-09-04T00:00:00Z",
                }
            )
    if suffix == "code-scanning/analyses":
        rows = ANALYSES if repo == "alpha" else []
        for query, field in [("ref", "ref"), ("sarif_id", "sarif_id")]:
            if request.url.params.get(query):
                rows = [r for r in rows if r[field] == request.url.params[query]]
        if request.url.params.get("pr"):
            rows = [r for r in rows if r["id"] == 502]
        return listing(rows)
    if suffix.startswith("code-scanning/analyses/"):
        return response(next(r for r in ANALYSES if r["id"] == int(parts[-1])))
    if suffix == "code-scanning/codeql/databases":
        return listing(DATABASES if repo == "alpha" else [])
    if suffix.startswith("code-scanning/codeql/databases/"):
        return response(next(r for r in DATABASES if r["language"] == parts[-1]))
    if suffix.startswith("code-scanning/sarifs/"):
        if parts[-1] == "upload-1":
            return response(
                {
                    "processing_status": "complete",
                    "analyses_url": "https://api.github.com/repos/scan-fixture/alpha/code-scanning/analyses?sarif_id=upload-1",
                    "errors": [],
                }
            )
        return response({"processing_status": "failed", "analyses_url": None, "errors": ["No database"]})
    if suffix == "code-scanning/default-setup":
        return response(SETUP if repo == "alpha" else {"state": "not-configured", "languages": []})
    if suffix == "code-scanning/ai-scan":
        return response({"pr_scan": "enabled" if repo == "alpha" else "disabled"})
    if suffix == "code-scanning/codeql/variant-analyses/701":
        return response(VARIANT)
    if suffix.startswith("code-scanning/codeql/variant-analyses/701/repos/"):
        return response(TASKS["/".join(parts[-2:])])
    if suffix == "dismissal-requests/code-scanning":
        return listing(dismissal_filter(DISMISSALS[repo]))
    if suffix.startswith("dismissal-requests/code-scanning/"):
        return response(next(r for r in DISMISSALS[repo] if r["data"][0]["alert_number"] == parts[-1]))
    raise AssertionError(f"Unexpected Code Scanning fixture request: {request.url}")


if __name__ == "__main__":
    api.open_client = lambda: httpx.Client(transport=httpx.MockTransport(respond), follow_redirects=True)
    main()
