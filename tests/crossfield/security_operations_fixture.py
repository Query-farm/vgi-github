"""Independent campaigns, code-quality findings and Dependabot dismissal observations.

Campaign counters are memberships, not distinct alerts. Dismissal request IDs and
numbers deliberately differ from the alert selector. One request has two reviewers,
and requester identities never stand in for those response actors.
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
    "id": 2500,
    "login": "security-fixture",
    "type": "Organization",
    "name": "Security fixture",
    "description": "Independent security operation fixture",
    "created_at": "2020-01-01T00:00:00Z",
}
REPOSITORIES = [
    {
        "id": identity,
        "node_id": f"R{identity}",
        "name": name,
        "full_name": f"security-fixture/{name}",
        "owner": {"id": 2500, "login": "security-fixture", "type": "Organization"},
        "private": False,
        "description": "Security operation fixture",
        "topics": [],
        "language": "Python",
        "stargazers_count": 0,
    }
    for identity, name in [(2501, "alpha"), (2502, "beta"), (2503, "empty")]
]
REPOS = {r["name"]: r for r in REPOSITORIES}


def user(identity, login):
    row = {
        "id": identity,
        "node_id": f"U{identity}",
        "login": login,
        "type": "User",
        "name": login.title(),
        "email": None,
        "gravatar_id": None,
        "site_admin": False,
        "user_view_type": "public",
    }
    for key in [
        "avatar_url",
        "url",
        "html_url",
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
        row[key] = f"https://github.com/{login}/{key}"
    return row


ALICE, BOB, CAROL = user(2601, "security-alice"), user(2602, "security-bob"), user(2603, "security-carol")
TEAM = {
    "id": 2701,
    "node_id": "T2701",
    "name": "Security team",
    "slug": "security-team",
    "description": None,
    "privacy": "closed",
    "notification_setting": "notifications_enabled",
    "permission": "pull",
    "permissions": {"pull": True, "triage": False, "push": False, "maintain": False, "admin": False},
    "type": "organization",
    "organization_id": 2500,
    "parent": None,
    "url": "https://api.github.com/teams/2701",
    "html_url": "https://github.com/orgs/security-fixture/teams/security-team",
    "members_url": "https://api.github.com/teams/2701/members{/member}",
    "repositories_url": "https://api.github.com/teams/2701/repos",
}


def campaign(number, state, counters=None):
    row = {
        "number": number,
        "name": f"Campaign {number}",
        "description": "Remediate findings",
        "created_at": "2026-09-01T00:00:00Z",
        "updated_at": "2026-09-02T00:00:00Z",
        "managers": [ALICE, BOB] if number == 1 else [],
        "team_managers": [TEAM] if number == 1 else [],
        "published_at": "2026-09-02T00:00:00Z",
        "ends_at": "2026-10-31T00:00:00Z",
        "closed_at": "2026-09-05T00:00:00Z" if state == "closed" else None,
        "state": state,
        "contact_link": None,
    }
    if counters is not None:
        row["alert_stats"] = dict(
            zip(["open_count", "closed_count", "in_progress_count"], counters, strict=True)
        )
    return row


CAMPAIGNS = [campaign(1, "open", (4, 3, 1)), campaign(2, "closed", (0, 5, 0)), campaign(3, "open")]


def finding(repo, number, state, severity, category):
    return {
        "number": number,
        "state": state,
        "url": f"https://api.github.com/repos/security-fixture/{repo}/code-quality/findings/{number}",
        "rule": {
            "id": f"quality/{number}",
            "title": "Maintainable code",
            "description": "Avoid duplication",
            "help": "Extract a function",
            "severity": severity,
            "category": category,
        },
        "location": {
            "path": f"src/{number}.py",
            "start_line": 10,
            "end_line": 12,
            "start_column": 2,
            "end_column": 8,
        },
        "message": {"text": "Repeated logic", "markdown": "**Repeated logic**"},
        "created_at": "2026-09-03T00:00:00Z",
    }


FINDINGS = {
    "alpha": [
        finding("alpha", 1, "open", "error", "reliability"),
        finding("alpha", 2, "dismissed", "warning", "maintainability"),
        finding("alpha", 3, "open", "note", "none"),
    ],
    "beta": [finding("beta", 1, "open", "none", "none")],
    "empty": [],
}


def dismissal(repo, identity, request_number, alert_number, state, requester=ALICE, age_days=2):
    row = {
        "id": identity,
        "number": request_number,
        "repository": {k: REPOS[repo][k] for k in ["id", "name", "full_name"]},
        "organization": {"id": 2500, "name": "security-fixture"},
        "requester": {"actor_id": requester["id"], "actor_name": requester["login"]},
        "request_type": "dependabot_alert",
        "resource_identifier": str(alert_number),
        "data": [
            {
                "reason": "tolerable_risk",
                "alert_number": str(alert_number),
                "alert_title": "Vulnerable package",
            }
        ],
        "status": state,
        "requester_comment": None if state == "pending" else "Mitigation recorded",
        "expires_at": "2026-10-31T00:00:00Z",
        "created_at": "2026-10-13T00:00:00Z",
        "responses": [],
        "url": f"https://api.github.com/repos/security-fixture/{repo}/dismissal-requests/dependabot/{alert_number}",
        "html_url": f"https://github.com/security-fixture/{repo}/security/dependabot/{alert_number}",
        "_age_days": age_days,
    }
    if state == "approved":
        row["responses"] = [
            {
                "id": identity * 10 + 1,
                "reviewer": {"actor_id": BOB["id"], "actor_name": BOB["login"]},
                "message": "Review one",
                "status": "denied",
                "created_at": "2026-10-14T00:00:00Z",
            },
            {
                "id": identity * 10 + 2,
                "reviewer": {"actor_id": CAROL["id"], "actor_name": CAROL["login"]},
                "message": None,
                "status": "approved",
                "created_at": "2026-10-15T00:00:00Z",
            },
        ]
    elif state == "denied":
        row["responses"] = [
            {
                "id": identity * 10 + 1,
                "reviewer": {"actor_id": ALICE["id"], "actor_name": ALICE["login"]},
                "message": "Keep open",
                "status": "denied",
                "created_at": "2026-10-15T00:00:00Z",
            }
        ]
    return row


DISMISSALS = {
    "alpha": [
        dismissal("alpha", 2801, 51, 7, "approved"),
        dismissal("alpha", 2802, 52, 2, "pending", age_days=0),
        dismissal("alpha", 2803, 53, 9, "expired", age_days=40),
    ],
    "beta": [dismissal("beta", 2804, 51, 7, "denied", requester=BOB)],
    "empty": [],
}


def respond(request):
    path = request.url.path
    if not (
        path.startswith("/repos/security-fixture/")
        or path.startswith("/orgs/security-fixture")
        or path == "/users/security-fixture"
    ):
        return None
    if os.environ.get("CROSSFIELD_GITHUB_API_LOG"):
        with Path(os.environ["CROSSFIELD_GITHUB_API_LOG"]).open("a") as log:
            log.write(json.dumps({"path": path, "query": str(request.url.query)}) + "\n")
    headers = {"Cache-Control": "no-store", "X-RateLimit-Remaining": "5000"}

    def response(value, status=200, extra=None):
        value = copy.deepcopy(value)
        if isinstance(value, list):
            for row in value:
                row.pop("_age_days", None)
        elif isinstance(value, dict):
            value.pop("_age_days", None)
        return httpx.Response(status, json=value, headers=headers | (extra or {}), request=request)

    def listing(rows, cursor=False):
        key = "after" if cursor else "page"
        page = int(request.url.params.get(key, "1"))
        link = (
            {"Link": f'<{request.url.copy_set_param(key, str(page + 1))}>; rel="next"'}
            if page < len(rows)
            else {}
        )
        return response(rows[page - 1 : page], extra=link)

    def dismissal_filter(rows, org=False):
        params = request.url.params
        period = params.get("time_period", "day" if org else "month")
        days = {"hour": 1 / 24, "day": 1, "week": 7, "month": 31}[period]
        rows = [r for r in rows if r["_age_days"] < days]
        state = params.get("request_status", "all")
        if state != "all":
            rows = [r for r in rows if r["status"] == ("pending" if state == "open" else state)]
        if params.get("requester"):
            rows = [r for r in rows if r["requester"]["actor_name"] == params["requester"]]
        if params.get("reviewer"):
            rows = [
                r
                for r in rows
                if any(v["reviewer"]["actor_name"] == params["reviewer"] for v in r["responses"])
            ]
        if params.get("repository_name"):
            rows = [r for r in rows if r["repository"]["name"] == params["repository_name"]]
        return rows

    if path in {"/orgs/security-fixture", "/users/security-fixture"}:
        return response(ORG)
    if path == "/orgs/security-fixture/repos":
        return listing(REPOSITORIES)
    if path == "/orgs/security-fixture/campaigns":
        rows = CAMPAIGNS
        if request.url.params.get("state"):
            rows = [r for r in rows if r["state"] == request.url.params["state"]]
        return listing(rows)
    if path.startswith("/orgs/security-fixture/campaigns/"):
        row = next((r for r in CAMPAIGNS if str(r["number"]) == path.split("/")[-1]), None)
        return response(row if row else {"message": "Not Found"}, 200 if row else 404)
    if path == "/orgs/security-fixture/dismissal-requests/dependabot":
        return listing(dismissal_filter([r for values in DISMISSALS.values() for r in values], org=True))
    parts = path.split("/")
    repo = parts[3]
    if repo not in REPOS:
        return response({"message": "Not Found"}, 404)
    suffix = "/".join(parts[4:])
    if not suffix:
        return response(REPOS[repo])
    if suffix == "code-quality/findings":
        rows = FINDINGS[repo]
        if request.url.params.get("state"):
            rows = [r for r in rows if r["state"] == request.url.params["state"]]
        return listing(rows, cursor=True)
    if suffix.startswith("code-quality/findings/"):
        row = next((r for r in FINDINGS[repo] if str(r["number"]) == parts[-1]), None)
        return response(row if row else {"message": "Not Found"}, 200 if row else 404)
    if suffix == "dismissal-requests/dependabot":
        return listing(dismissal_filter(DISMISSALS[repo]))
    if suffix.startswith("dismissal-requests/dependabot/"):
        row = next((r for r in DISMISSALS[repo] if r["resource_identifier"] == parts[-1]), None)
        return response(row if row else {"message": "Not Found"}, 200 if row else 404)
    raise AssertionError(f"Unexpected security operations fixture request: {request.url}")


if __name__ == "__main__":
    api.open_client = lambda: httpx.Client(transport=httpx.MockTransport(respond), follow_redirects=True)
    main()
