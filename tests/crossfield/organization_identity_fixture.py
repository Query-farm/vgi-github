"""Active, pending, public and hidden organization memberships are distinct.

The authenticated identity matches the shared package/user identity fixtures.
A private active member is deliberately invisible to the public-members check.
"""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path

import httpx

from vgi_github import github_api as api
from vgi_github.generated_worker import main

AUTH = "package-fixture-current"


def actor(identity, login):
    row = {
        "id": identity,
        "login": login,
        "node_id": f"U{identity}",
        "type": "User",
        "name": login.title(),
        "email": None,
        "gravatar_id": None,
        "site_admin": False,
        "created_at": "2020-01-01T00:00:00Z",
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


ACTORS = {
    a["login"]: a
    for a in [
        actor(903, AUTH),
        actor(3001, "membership-alice"),
        actor(3002, "membership-bob"),
        actor(3003, "membership-carol"),
    ]
}


def organization(identity, login):
    row = {
        "id": identity,
        "login": login,
        "node_id": f"O{identity}",
        "type": "Organization",
        "name": login.title(),
        "description": None,
        "created_at": "2020-01-01T00:00:00Z",
    }
    for key in [
        "url",
        "repos_url",
        "events_url",
        "hooks_url",
        "issues_url",
        "members_url",
        "public_members_url",
        "avatar_url",
    ]:
        row[key] = f"https://api.github.com/orgs/{login}/{key}"
    return row


ORGS = {
    o["login"]: o
    for o in [
        organization(3101, "membership-fixture-alpha"),
        organization(3102, "membership-fixture-beta"),
        organization(3103, "membership-fixture-empty"),
    ]
}
BY_ID = {str(o["id"]): o for o in ORGS.values()}
MEMBERSHIPS = [
    ("membership-fixture-alpha", AUTH, "active", "admin", False),
    ("membership-fixture-alpha", "membership-alice", "active", "member", True),
    ("membership-fixture-alpha", "membership-bob", "active", "admin", False),
    ("membership-fixture-alpha", "membership-carol", "pending", "member", False),
    ("membership-fixture-beta", AUTH, "pending", "member", False),
]


def membership(row):
    org, login, state, role, public = row
    return {
        "url": f"https://api.github.com/orgs/{org}/memberships/{login}",
        "state": state,
        "role": role,
        "direct_membership": login != "membership-bob",
        "enterprise_teams_providing_indirect_membership": ["ent:security", "ent:reviewers"]
        if login == "membership-bob"
        else [],
        "organization_url": f"https://api.github.com/orgs/{org}",
        "organization": ORGS[org],
        "user": None if login == "membership-bob" else ACTORS[login],
        "permissions": {"can_create_repository": role == "admin"},
    }


def respond(request):
    path = request.url.path
    owned = (
        path == "/organizations"
        or path == "/user/orgs"
        or path.startswith("/user/memberships/orgs")
        or path.startswith("/orgs/membership-fixture-")
        or path.startswith("/users/membership-")
    )
    owned |= path == f"/users/{AUTH}/orgs"
    if not owned:
        return None
    if os.environ.get("CROSSFIELD_GITHUB_API_LOG"):
        with Path(os.environ["CROSSFIELD_GITHUB_API_LOG"]).open("a") as log:
            log.write(json.dumps({"path": path, "query": str(request.url.query)}) + "\n")
    headers = {"Cache-Control": "no-store", "X-RateLimit-Remaining": "5000"}

    def response(value=None, code=200, extra=None):
        if code in {204, 302}:
            return httpx.Response(code, headers=headers | (extra or {}), request=request)
        return httpx.Response(
            code, json=copy.deepcopy(value), headers=headers | (extra or {}), request=request
        )

    def missing():
        return response({"message": "Not Found"}, 404)

    def pages(rows):
        page = int(request.url.params.get("page", "1"))
        link = (
            {"Link": f'<{request.url.copy_set_param("page", str(page + 1))}>; rel="next"'}
            if page < len(rows)
            else {}
        )
        return response(rows[page - 1 : page], extra=link)

    if path == "/organizations":
        after = int(request.url.params.get("since", "0"))
        rows = [v for v in ORGS.values() if v["id"] > after]
        link = (
            {"Link": f'<{request.url.copy_set_param("since", str(rows[0]["id"]))}>; rel="next"'}
            if len(rows) > 1
            else {}
        )
        return response(rows[:1], extra=link)
    if path == "/user/orgs":
        return pages(
            [ORGS[o] for o, u, state, role, public in MEMBERSHIPS if u == AUTH and state == "active"]
        )
    if path == "/user/memberships/orgs":
        rows = [r for r in MEMBERSHIPS if r[1] == AUTH]
        if request.url.params.get("state"):
            rows = [r for r in rows if r[2] == request.url.params["state"]]
        return pages([membership(r) for r in rows])
    if path.startswith("/user/memberships/orgs/"):
        org = path.split("/")[-1]
        row = next((r for r in MEMBERSHIPS if r[0] == org and r[1] == AUTH), None)
        return response(membership(row)) if row else missing()
    parts = path.strip("/").split("/")
    if parts[0] == "users":
        login = parts[1]
        if len(parts) == 2:
            return response(ACTORS[login]) if login in ACTORS else missing()
        if parts[2:] == ["orgs"]:
            return pages(
                [
                    ORGS[o]
                    for o, u, state, role, public in MEMBERSHIPS
                    if u == login and state == "active" and public
                ]
            )
    if parts[0] == "orgs":
        org = parts[1]
        if org not in ORGS:
            return missing()
        if len(parts) == 2:
            return response(ORGS[org])
        if parts[2:] in [["members"], ["public_members"]]:
            public_only = parts[2] == "public_members"
            return pages(
                [
                    ACTORS[u]
                    for o, u, state, role, public in MEMBERSHIPS
                    if o == org and state == "active" and (public or not public_only)
                ]
            )
        if len(parts) == 4 and parts[2] == "memberships":
            row = next((r for r in MEMBERSHIPS if r[0] == org and r[1] == parts[3]), None)
            return response(membership(row)) if row else missing()
        if len(parts) == 4 and parts[2] in {"members", "public_members"}:
            login = parts[3]
            row = next((r for r in MEMBERSHIPS if r[0] == org and r[1] == login and r[2] == "active"), None)
            if parts[2] == "members" and login == "membership-carol":
                return response(
                    code=302, extra={"Location": f"https://api.github.com/orgs/{org}/public_members/{login}"}
                )
            return response(code=204) if row and (parts[2] == "members" or row[4]) else missing()
    raise AssertionError(f"Unexpected organization identity request: {request.url}")


def respond_all(request):
    import user_identity_fixture

    return respond(request) or user_identity_fixture.respond(request)


if __name__ == "__main__":
    api.open_client = lambda: httpx.Client(transport=httpx.MockTransport(respond_all), follow_redirects=True)
    main()
