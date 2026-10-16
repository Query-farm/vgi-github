"""Independent secret-scanning observations; every secret value here is synthetic.

Alert lifecycle and credential validity intentionally disagree. Locations cover
all thirteen schema alternatives plus a second occurrence in one commit. Pattern
IDs and request numbers repeat across explicitly different owner contexts.
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
    "id": 1010,
    "login": "secret-fixture",
    "type": "Organization",
    "name": "Secret fixture",
    "description": "Independent fixture",
    "created_at": "2020-01-01T00:00:00Z",
}
REPOSITORIES = [
    {
        "id": identity,
        "node_id": f"R{identity}",
        "name": name,
        "full_name": f"secret-fixture/{name}",
        "owner": {"id": 1010, "login": "secret-fixture", "type": "Organization"},
        "private": False,
        "description": "Synthetic secret fixture",
        "topics": [],
        "language": "Python",
    }
    for identity, name in [(1011, "alpha"), (1012, "beta"), (1013, "empty")]
]
REPOS = {r["name"]: r for r in REPOSITORIES}


def actor(identity, login):
    return {"id": identity, "login": login, "type": "User", "html_url": f"https://github.com/{login}"}


ALICE, BOB, CAROL = actor(201, "alice"), actor(202, "bob"), actor(203, "carol")


def commit_location(line=1, wiki=False):
    detail = {
        "path": "fixture.txt",
        "start_line": line,
        "end_line": line,
        "start_column": 2,
        "end_column": 9,
        "blob_sha": "b" * 40,
        "commit_sha": "c" * 40,
        "commit_url": "https://api.github.com/repos/secret-fixture/alpha/commits/" + "c" * 40,
    }
    detail["page_url" if wiki else "blob_url"] = (
        "https://example.com/wiki"
        if wiki
        else "https://api.github.com/repos/secret-fixture/alpha/git/blobs/" + "b" * 40
    )
    if not wiki:
        detail["html_url"] = "https://github.com/secret-fixture/alpha/blob/main/fixture.txt#L1"
    return {"type": "wiki_commit" if wiki else "commit", "details": detail}


LOCATION_TYPES = [
    "commit",
    "wiki_commit",
    "issue_title",
    "issue_body",
    "issue_comment",
    "discussion_title",
    "discussion_body",
    "discussion_comment",
    "pull_request_title",
    "pull_request_body",
    "pull_request_comment",
    "pull_request_review",
    "pull_request_review_comment",
]
LOCATIONS = {
    1: [commit_location(), commit_location(wiki=True)]
    + [
        {"type": kind, "details": {kind + "_url": f"https://example.com/{kind}/11"}}
        for kind in LOCATION_TYPES[2:]
    ]
    + [commit_location(line=2)],
    2: [commit_location(line=3)],
    3: [],
}


def alert(repo, number, state, validity):
    bypassed = number == 1
    result = {
        "number": number,
        "created_at": "2026-09-01T00:00:00Z",
        "updated_at": "2026-09-02T00:00:00Z",
        "url": f"https://api.github.com/repos/secret-fixture/{repo}/secret-scanning/alerts/{number}",
        "html_url": f"https://github.com/secret-fixture/{repo}/security/secret-scanning/{number}",
        "locations_url": f"https://api.github.com/repos/secret-fixture/{repo}/secret-scanning/alerts/{number}/locations",
        "state": state,
        "resolution": None if state == "open" else "revoked" if number == 2 else "false_positive",
        "resolved_at": None if state == "open" else "2026-09-02T00:00:00Z",
        "resolved_by": None if state == "open" else BOB,
        "resolution_comment": None if state == "open" else "Fixture resolution",
        "secret_type": "github_personal_access_token" if number != 3 else "custom_pattern_1",
        "secret_type_display_name": "Synthetic fixture token",
        "provider": "GitHub" if number != 3 else None,
        "provider_slug": "github" if number != 3 else None,
        "secret": f"synthetic-fixture-value-{repo}-{number}",
        "push_protection_bypassed": bypassed,
        "push_protection_bypassed_by": ALICE if bypassed else None,
        "push_protection_bypassed_at": "2026-09-01T00:00:00Z" if bypassed else None,
        "push_protection_bypass_request_reviewer": CAROL if bypassed else None,
        "push_protection_bypass_request_reviewer_comment": "Reviewed" if bypassed else None,
        "push_protection_bypass_request_comment": "Fixture request" if bypassed else None,
        "push_protection_bypass_request_html_url": "https://example.com/bypass/41" if bypassed else None,
        "validity": validity,
        "publicly_leaked": number == 1,
        "multi_repo": number == 1,
        "is_base64_encoded": False,
        "first_location_detected": LOCATIONS[number][0]["details"] if LOCATIONS[number] else None,
        "has_more_locations": number == 1,
        "assigned_to": ALICE if number == 1 else None,
        "closure_request_comment": None,
        "closure_request_reviewer_comment": None,
        "closure_request_reviewer": BOB if state == "resolved" else None,
        "metadata": [
            {"key": "owner-email", "value": "synthetic@example.com"},
            {"key": "secret-id", "value": f"fixture-{number}"},
        ],
        "repository": REPOS[repo],
    }
    return result


ALERTS = {
    "alpha": [
        alert("alpha", 1, "open", "active"),
        alert("alpha", 2, "resolved", "inactive"),
        alert("alpha", 3, "resolved", "active"),
    ],
    "beta": [alert("beta", 1, "open", "unknown")],
    "empty": [],
}


def scan(kind, status):
    return {
        "type": kind,
        "status": status,
        "started_at": None if status == "pending" else "2026-09-01T00:00:00Z",
        "completed_at": "2026-09-01T01:00:00Z" if status == "completed" else None,
    }


HISTORY = {
    "incremental_scans": [scan("git", "completed"), scan("issues", "running")],
    "pattern_update_scans": [],
    "backfill_scans": [scan("git", "pending")],
    "custom_pattern_backfill_scans": [
        {**scan("git", "completed"), "pattern_name": "Fixture pattern", "pattern_scope": "organization"}
    ],
    "generic_secrets_backfill_scans": [scan("git", "failed")],
}


def request_record(repo, family, identity, number, status):
    data = (
        {
            "secret_type": "github_personal_access_token",
            "bypass_reason": "used_in_tests",
            "path": "fixture.txt",
            "branch": "main",
        }
        if family == "bypass"
        else {"secret_type": "github_personal_access_token", "alert_number": "2", "reason": "revoked"}
    )
    return {
        "id": identity,
        "number": number,
        "repository": REPOS[repo],
        "organization": {"id": 1010, "name": "secret-fixture"},
        "requester": {"actor_id": 201, "actor_name": "alice"},
        "request_type": family,
        "data": [data],
        "resource_identifier": "c" * 40 if family == "bypass" else "2",
        "status": status,
        "requester_comment": "Synthetic fixture",
        "created_at": "2026-09-01T00:00:00Z",
        "expires_at": "2026-10-01T00:00:00Z",
        "responses": [
            {
                "id": identity + 100,
                "reviewer": {"actor_id": 202, "actor_name": "bob"},
                "status": "approved" if status != "denied" else "denied",
                "created_at": "2026-09-02T00:00:00Z",
            }
        ]
        if status != "pending"
        else [],
        "url": f"https://api.github.com/repos/secret-fixture/{repo}/{family}-requests/secret-scanning/{number}",
        "html_url": f"https://github.com/secret-fixture/{repo}/requests/{number}",
    }


BYPASSES = {
    "alpha": [
        request_record("alpha", "bypass", 801, 41, "approved"),
        request_record("alpha", "bypass", 802, 42, "completed"),
    ],
    "beta": [request_record("beta", "bypass", 803, 41, "pending")],
    "empty": [],
}
DISMISSALS = {
    "alpha": [request_record("alpha", "dismissal", 901, 91, "approved")],
    "beta": [request_record("beta", "dismissal", 902, 91, "denied")],
    "empty": [],
}


def pattern(identity, name, published, protected):
    return {
        "id": identity,
        "name": name,
        "pattern": "SYNTHETIC_[A-Z]{4}",
        "slug": name.lower().replace(" ", "-"),
        "state": "published" if published else "unpublished",
        "push_protection_enabled": protected,
        "start_delimiter": None,
        "end_delimiter": None,
        "must_match": ["SYNTHETIC_"],
        "must_not_match": [],
        "custom_pattern_version": "version-1",
        "created_at": "2026-09-01T00:00:00Z",
        "updated_at": "2026-09-02T00:00:00Z",
    }


PATTERNS = {
    "alpha": [pattern(701, "Repository fixture", True, True), pattern(702, "Draft fixture", False, False)],
    "beta": [],
    "empty": [],
    "organization": [
        pattern(701, "Organization fixture", True, True),
        pattern(703, "Audit fixture", True, False),
    ],
}


def override(token, total, positives, rate):
    return {
        "token_type": token,
        "custom_pattern_version": None,
        "slug": token,
        "display_name": "Fixture pattern",
        "alert_total": total,
        "alert_total_percentage": 70 if total == 7 else 30,
        "false_positives": positives,
        "false_positive_rate": rate,
        "bypass_rate": 12,
        "default_setting": "enabled",
        "enterprise_setting": None,
        "setting": "not-set",
    }


CONFIGURATION = {
    "pattern_config_version": "config-1",
    "provider_pattern_overrides": [override("github_personal_access_token", 7, 2, 29)],
    "custom_pattern_overrides": [override("custom_pattern_1", 3, 1, 33)],
}


def respond(request):
    path = request.url.path
    if not (
        path.startswith("/repos/secret-fixture/")
        or path.startswith("/orgs/secret-fixture")
        or path == "/users/secret-fixture"
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

    def selected_alerts(rows):
        for query, field in [
            ("state", "state"),
            ("secret_type", "secret_type"),
            ("providers", "provider_slug"),
            ("resolution", "resolution"),
            ("validity", "validity"),
        ]:
            if request.url.params.get(query):
                rows = [r for r in rows if r[field] in request.url.params[query].split(",")]
        for query, field in [("exclude_secret_types", "secret_type"), ("exclude_providers", "provider_slug")]:
            if request.url.params.get(query):
                rows = [r for r in rows if r[field] not in request.url.params[query].split(",")]
        for query, field in [("is_publicly_leaked", "publicly_leaked"), ("is_multi_repo", "multi_repo")]:
            if request.url.params.get(query) == "true":
                rows = [r for r in rows if r[field]]
        if request.url.params.get("is_bypassed"):
            rows = [
                r
                for r in rows
                if r["push_protection_bypassed"] == (request.url.params["is_bypassed"] == "true")
            ]
        if request.url.params.get("assignee"):
            rows = [
                r
                for r in rows
                if r["assigned_to"] and r["assigned_to"]["login"] == request.url.params["assignee"]
            ]
        if request.url.params.get("included_metadata"):
            required = set(request.url.params["included_metadata"].split(","))
            rows = [r for r in rows if required <= {m["key"] for m in r["metadata"]}]
        return rows

    def selected_requests(rows):
        if request.url.params.get("request_status") not in {None, "all"}:
            selected = request.url.params["request_status"]
            rows = [r for r in rows if r["status"] == ("pending" if selected == "open" else selected)]
        if request.url.params.get("requester"):
            rows = [r for r in rows if r["requester"]["actor_name"] == request.url.params["requester"]]
        if request.url.params.get("reviewer"):
            rows = [
                r
                for r in rows
                if any(v["reviewer"]["actor_name"] == request.url.params["reviewer"] for v in r["responses"])
            ]
        return rows

    def selected_patterns(rows):
        if request.url.params.get("state"):
            rows = [r for r in rows if r["state"] == request.url.params["state"]]
        if request.url.params.get("push_protection"):
            rows = [
                r
                for r in rows
                if r["push_protection_enabled"] == (request.url.params["push_protection"] == "enabled")
            ]
        return rows

    if path in {"/users/secret-fixture", "/orgs/secret-fixture"}:
        return response(ORG)
    if path == "/orgs/secret-fixture/repos":
        return listing(REPOSITORIES)
    if path == "/orgs/secret-fixture/secret-scanning/alerts":
        return listing(selected_alerts([r for rs in ALERTS.values() for r in rs]))
    if path == "/orgs/secret-fixture/secret-scanning/custom-patterns":
        return listing(selected_patterns(PATTERNS["organization"]))
    if path == "/orgs/secret-fixture/secret-scanning/pattern-configurations":
        return response(CONFIGURATION)
    for family, records in [("bypass", BYPASSES), ("dismissal", DISMISSALS)]:
        if path == f"/orgs/secret-fixture/{family}-requests/secret-scanning":
            return listing(selected_requests([r for rs in records.values() for r in rs]))
    parts = path.split("/")
    repo = parts[3]
    suffix = "/".join(parts[4:])
    if not suffix:
        return response(REPOS[repo])
    if suffix == "secret-scanning/alerts":
        return listing(selected_alerts(ALERTS[repo]))
    if suffix.startswith("secret-scanning/alerts/"):
        pieces = suffix.split("/")
        number = int(pieces[2])
        if len(pieces) == 4:
            return listing(LOCATIONS[number])
        item = copy.deepcopy(next(r for r in ALERTS[repo] if r["number"] == number))
        if request.url.params.get("hide_secret") == "true":
            item.pop("secret")
        return response(item)
    if suffix == "secret-scanning/scan-history":
        return response(HISTORY if repo == "alpha" else {k: [] for k in HISTORY})
    if suffix == "secret-scanning/custom-patterns":
        return listing(selected_patterns(PATTERNS[repo]))
    for family, records in [("bypass", BYPASSES), ("dismissal", DISMISSALS)]:
        if suffix == f"{family}-requests/secret-scanning":
            return listing(selected_requests(records[repo]))
        if suffix.startswith(f"{family}-requests/secret-scanning/"):
            return response(
                next(
                    r
                    for r in records[repo]
                    if (r["request_type"] == "bypass" and r["number"] == int(parts[-1]))
                    or (r["request_type"] == "dismissal" and r["data"][0]["alert_number"] == parts[-1])
                )
            )
    raise AssertionError(f"Unexpected secret-scanning request: {request.url}")


if __name__ == "__main__":
    api.open_client = lambda: httpx.Client(transport=httpx.MockTransport(respond), follow_redirects=True)
    main()
