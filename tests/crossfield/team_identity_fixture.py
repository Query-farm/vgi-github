"""Independent effective team membership, invitation and repository-access answers."""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path

import httpx

from vgi_github import github_api as api
from vgi_github.generated_worker import main

AUTH = "package-fixture-current"
ORG = {
    "id": 3300,
    "login": "team-fixture",
    "name": "Team fixture",
    "type": "Organization",
    "description": None,
    "created_at": "2020-01-01T00:00:00Z",
}


def actor(identity, login):
    row = {
        "id": identity,
        "login": login,
        "node_id": f"U{identity}",
        "type": "User",
        "name": login.title(),
        "created_at": "2020-01-01T00:00:00Z",
        "gravatar_id": None,
        "site_admin": False,
        "email": None,
    }
    for key in [
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
        row[key] = f"https://github.com/{login}/{key}"
    return row


ACTORS = {
    u["login"]: u
    for u in [actor(903, AUTH), actor(3401, "team-alice"), actor(3402, "team-bob"), actor(3403, "team-carol")]
}


def team(identity, slug, parent=None):
    return {
        "id": identity,
        "node_id": f"T{identity}",
        "name": slug.title(),
        "slug": slug,
        "description": None,
        "privacy": "closed",
        "notification_setting": "notifications_enabled",
        "permission": "push",
        "url": f"https://api.github.com/teams/{identity}",
        "html_url": f"https://github.com/orgs/team-fixture/teams/{slug}",
        "members_url": f"https://api.github.com/teams/{identity}/members{{/member}}",
        "repositories_url": f"https://api.github.com/teams/{identity}/repos",
        "type": "organization",
        "organization_id": 3300,
        "organization": ORG,
        "parent": parent,
        "created_at": "2020-02-01T00:00:00Z",
        "updated_at": "2025-01-01T00:00:00Z",
        "members_count": 0,
        "repos_count": 0,
    }


PLATFORM = team(3201, "platform")
UI = team(3202, "ui", PLATFORM)
EMPTY = team(3203, "empty", PLATFORM)
WIDGET = team(3204, "widget", UI)
TEAMS = {str(t["id"]): t for t in [PLATFORM, UI, EMPTY, WIDGET]}
BY_SLUG = {t["slug"]: t for t in TEAMS.values()}
MEMBERSHIPS = [
    (3201, AUTH, "active", "maintainer", False),
    (3201, "team-alice", "active", "member", True),
    (3201, "team-bob", "active", "member", False),
    (3201, "team-carol", "pending", "member", None),
    (3202, AUTH, "active", "member", False),
    (3202, "team-alice", "active", "member", True),
    (3204, "team-alice", "active", "member", False),
]
REPOSITORIES = {
    name: {
        "id": identity,
        "node_id": f"R{identity}",
        "name": name,
        "full_name": f"team-fixture/{name}",
        "owner": ORG,
        "private": False,
        "description": None,
        "topics": [],
        "language": "Python",
        "stargazers_count": 0,
    }
    for name, identity in [("alpha", 3601), ("beta", 3602), ("gamma", 3603)]
}
ACCESS = [(3201, "alpha", "push"), (3201, "beta", None), (3202, "alpha", "pull")]
for selected in TEAMS.values():
    selected["members_count"] = sum(t == selected["id"] and s == "active" for t, u, s, r, i in MEMBERSHIPS)
    selected["repos_count"] = sum(t == selected["id"] for t, name, role in ACCESS)


def access(row):
    team_id, name, role = row
    result = copy.deepcopy(REPOSITORIES[name])
    if role is not None:
        result.update(
            role_name=role,
            permissions={
                "admin": False,
                "maintain": False,
                "push": role == "push",
                "triage": False,
                "pull": True,
            },
        )
    return result


def invitation(identity, login, email, count):
    return {
        "id": identity,
        "node_id": f"I{identity}",
        "login": login,
        "email": email,
        "role": "direct_member",
        "created_at": "2025-01-01T00:00:00Z",
        "inviter": ACTORS[AUTH],
        "team_count": count,
        "invitation_teams_url": f"https://api.github.com/orgs/team-fixture/invitations/{identity}/teams",
        "invitation_source": "member",
        "failed_at": None,
        "failed_reason": None,
    }


INVITATIONS = {
    3501: invitation(3501, "team-carol", None, 1),
    3502: invitation(3502, None, "external@example.com", 2),
}
TEAM_INVITES = {3201: [3501, 3502], 3202: [3502]}


def respond(request):
    path = request.url.path
    if not (
        path == "/user/teams"
        or path.startswith("/teams/32")
        or path.startswith("/orgs/team-fixture")
        or path.startswith("/users/team-")
        or path.startswith("/repos/team-fixture/")
    ):
        return None
    if os.environ.get("CROSSFIELD_GITHUB_API_LOG"):
        with Path(os.environ["CROSSFIELD_GITHUB_API_LOG"]).open("a") as log:
            log.write(json.dumps({"path": path, "query": str(request.url.query)}) + "\n")
    headers = {"Cache-Control": "no-store", "X-RateLimit-Remaining": "5000"}

    def response(value=None, code=200, extra=None):
        if code == 204:
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

    parts = path.strip("/").split("/")
    if path == "/user/teams":
        return pages(
            [TEAMS[str(t)] for t, u, state, role, inherited in MEMBERSHIPS if u == AUTH and state == "active"]
        )
    if parts[0] == "users":
        return response(ACTORS[parts[1]]) if len(parts) == 2 and parts[1] in ACTORS else missing()
    if parts[0] == "repos":
        repository = REPOSITORIES.get(parts[2])
        if repository is None:
            return missing()
        if len(parts) == 3:
            return response(repository)
        if parts[3:] == ["teams"]:
            rows = []
            for tid, name, role in ACCESS:
                if name == parts[2]:
                    row = copy.deepcopy(TEAMS[str(tid)])
                    if role:
                        row.update(permissions=access((tid, name, role))["permissions"], permission=role)
                    rows.append(row)
            return pages(rows)
        raise AssertionError(f"Unexpected repository fixture request: {request.url}")
    if path == "/orgs/team-fixture":
        return response(ORG)
    if path == "/orgs/team-fixture/teams":
        return pages(list(TEAMS.values()))
    if parts[0] == "teams":
        selected = TEAMS.get(parts[1])
        tail = parts[2:]
    else:
        selected = BY_SLUG.get(parts[3]) if len(parts) >= 4 and parts[2] == "teams" else None
        tail = parts[4:]
    if selected is None:
        return missing()
    tid = selected["id"]
    if not tail:
        return response(selected)
    if tail == ["teams"]:
        return pages([t for t in TEAMS.values() if t["parent"] and t["parent"]["id"] == tid])
    if tail == ["members"]:
        role = request.url.params.get("role", "all")
        rows = [
            dict(ACTORS[u], role=r, inherited=i)
            for t, u, state, r, i in MEMBERSHIPS
            if t == tid and state == "active" and role in {"all", r}
        ]
        return pages(rows)
    if len(tail) == 2 and tail[0] in {"members", "memberships"}:
        membership = next((r for r in MEMBERSHIPS if r[0] == tid and r[1] == tail[1]), None)
        if tail[0] == "members":
            return response(code=204) if membership and membership[2] == "active" else missing()
        if membership:
            return response(
                {
                    "state": membership[2],
                    "role": membership[3],
                    "url": f"https://api.github.com/teams/{tid}/memberships/{membership[1]}",
                }
            )
        return missing()
    if tail == ["invitations"]:
        return pages([INVITATIONS[i] for i in TEAM_INVITES.get(tid, [])])
    if tail == ["repos"]:
        return pages([access(r) for r in ACCESS if r[0] == tid])
    if len(tail) == 3 and tail[:2] == ["repos", "team-fixture"]:
        row = next((r for r in ACCESS if r[0] == tid and r[1] == tail[2]), None)
        if row is None:
            return missing()
        if request.headers.get("accept") == "application/vnd.github.v3.repository+json":
            return response(access(row))
        return response(code=204)
    raise AssertionError(f"Unexpected team fixture request: {request.url}")


def respond_all(request):
    import user_identity_fixture

    return respond(request) or user_identity_fixture.respond(request)


if __name__ == "__main__":
    api.open_client = lambda: httpx.Client(transport=httpx.MockTransport(respond_all), follow_redirects=True)
    main()
