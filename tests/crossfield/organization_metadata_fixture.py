"""Organization metadata has independent property, invitation and issue-type identities."""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path

import httpx

from vgi_github import github_api as api
from vgi_github.generated_worker import main

ORG = {
    "id": 3700,
    "login": "organization-metadata-fixture",
    "name": "Organization metadata",
    "type": "Organization",
    "description": None,
    "created_at": "2020-01-01T00:00:00Z",
}
LOGIN = ORG["login"]


def actor(identity, login, kind="User"):
    value = {
        "id": identity,
        "login": login,
        "node_id": f"U{identity}",
        "type": kind,
        "name": login,
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
        value[key] = f"https://github.com/{login}/{key}"
    return value


INVITER = actor(47001, "metadata-inviter")
OUTSIDE = [actor(4801, "metadata-external"), actor(4802, "metadata-bot", "Bot")]
REPOS = {
    name: {
        "id": identity,
        "name": name,
        "full_name": f"{LOGIN}/{name}",
        "node_id": f"R{identity}",
        "owner": ORG,
        "private": False,
        "description": None,
        "topics": [],
        "language": "Python",
        "stargazers_count": 0,
    }
    for name, identity in [("alpha", 3711), ("beta", 3712), ("empty", 3713)]
}
DEFINITIONS = [
    {
        "property_name": "risk",
        "value_type": "single_select",
        "source_type": "organization",
        "required": True,
        "default_value": "medium",
        "allowed_values": ["low", "medium", "high"],
        "description": "Risk classification",
        "values_editable_by": "org_actors",
        "require_explicit_values": True,
    },
    {
        "property_name": "labels",
        "value_type": "multi_select",
        "source_type": "organization",
        "required": False,
        "default_value": ["reviewed"],
        "allowed_values": ["reviewed", "critical"],
        "description": None,
        "values_editable_by": "org_and_repo_actors",
        "require_explicit_values": False,
    },
    {
        "property_name": "flag",
        "value_type": "true_false",
        "source_type": "enterprise",
        "required": False,
        "default_value": "false",
        "allowed_values": None,
        "description": None,
        "values_editable_by": None,
    },
    {
        "property_name": "unset",
        "value_type": "string",
        "source_type": "organization",
        "default_value": None,
        "description": None,
    },
]
for definition in DEFINITIONS:
    definition["url"] = f"https://api.github.com/orgs/{LOGIN}/properties/schema/{definition['property_name']}"
VALUES = {
    "alpha": [
        {"property_name": "risk", "value": "high"},
        {"property_name": "labels", "value": ["critical", "reviewed"]},
        {"property_name": "unset", "value": None},
    ],
    "beta": [{"property_name": "risk", "value": "low"}, {"property_name": "flag", "value": "false"}],
    "empty": [],
}
TYPES = [
    {
        "id": 3801,
        "node_id": "IT3801",
        "name": "Bug",
        "description": "A defect",
        "color": "red",
        "is_enabled": True,
        "created_at": "2024-01-01T00:00:00Z",
        "updated_at": "2025-01-01T00:00:00Z",
    },
    {
        "id": 3802,
        "node_id": "IT3802",
        "name": "Task",
        "description": None,
        "color": None,
        "is_enabled": False,
    },
]
FIELDS = [
    {
        "id": 3901,
        "node_id": "IF3901",
        "name": "Priority",
        "data_type": "single_select",
        "description": None,
        "visibility": "all",
        "options": [
            {"id": 3911, "name": "P1", "color": "red", "priority": 1},
            {"id": 3912, "name": "P2", "color": "yellow", "priority": 2},
        ],
    },
    {
        "id": 3902,
        "node_id": "IF3902",
        "name": "Estimate",
        "data_type": "number",
        "description": None,
        "visibility": "organization_members_only",
        "options": None,
    },
]


def team(identity, slug):
    return {
        "id": identity,
        "node_id": f"T{identity}",
        "slug": slug,
        "name": slug.title(),
        "description": None,
        "privacy": "closed",
        "notification_setting": "notifications_enabled",
        "permission": "pull",
        "members_url": f"https://api.github.com/teams/{identity}/members",
        "repositories_url": f"https://api.github.com/teams/{identity}/repos",
        "url": f"https://api.github.com/teams/{identity}",
        "html_url": f"https://github.com/orgs/{LOGIN}/teams/{slug}",
        "type": "organization",
        "organization_id": 3700,
        "organization": ORG,
        "parent": None,
        "members_count": 0,
        "repos_count": 0,
        "created_at": "2020-01-01T00:00:00Z",
        "updated_at": "2025-01-01T00:00:00Z",
    }


TEAMS = {4201: team(4201, "platform"), 4202: team(4202, "ui")}


def invitation(identity, login, email, state, count):
    return {
        "id": identity,
        "node_id": f"I{identity}",
        "login": login,
        "email": email,
        "role": "direct_member",
        "created_at": "2025-01-01T00:00:00Z",
        "failed_at": "2025-01-02T00:00:00Z" if state == "failed" else None,
        "failed_reason": "Unconfirmed email" if state == "failed" else None,
        "inviter": INVITER,
        "team_count": count,
        "invitation_teams_url": f"https://api.github.com/orgs/{LOGIN}/invitations/{identity}/teams",
        "invitation_source": "member",
    }


PENDING = [
    invitation(4101, "metadata-invitee", None, "pending", 1),
    invitation(4102, None, "external@example.com", "pending", 2),
]
FAILED = [invitation(4103, "metadata-failed", None, "failed", 0)]
ASSOCIATIONS = [(4101, 4201), (4102, 4201), (4102, 4202)]


def respond(request):
    path = request.url.path
    if not (
        path.startswith(f"/orgs/{LOGIN}")
        or path.startswith(f"/repos/{LOGIN}/")
        or path.startswith("/teams/42")
        or path.startswith("/users/metadata-")
    ):
        return None
    if os.environ.get("CROSSFIELD_GITHUB_API_LOG"):
        with Path(os.environ["CROSSFIELD_GITHUB_API_LOG"]).open("a") as log:
            log.write(json.dumps({"path": path, "query": str(request.url.query)}) + "\n")
    headers = {"Cache-Control": "no-store", "X-RateLimit-Remaining": "5000"}

    def response(value, code=200, extra=None):
        return httpx.Response(
            code, json=copy.deepcopy(value), headers=headers | (extra or {}), request=request
        )

    def missing():
        return response({"message": "Not Found"}, 404)

    def pages(rows):
        page = int(request.url.params.get("page", "1"))
        extra = (
            {"Link": f'<{request.url.copy_set_param("page", str(page + 1))}>; rel="next"'}
            if page < len(rows)
            else {}
        )
        return response(rows[page - 1 : page], extra=extra)

    parts = path.strip("/").split("/")
    if parts[0] == "users":
        account = next((u for u in [INVITER, *OUTSIDE] if u["login"] == parts[1]), None)
        return response(account) if account else missing()
    if parts[0] == "repos":
        name = parts[2]
        if name not in REPOS:
            return missing()
        if len(parts) == 3:
            return response(REPOS[name])
        if parts[3:] == ["properties", "values"]:
            return response(VALUES[name])
        if parts[3:] == ["issue-types"]:
            return response(TYPES[:1] if name == "alpha" else TYPES if name == "beta" else [])
        raise AssertionError(f"Unexpected organization metadata repository request: {request.url}")
    if parts[0] == "teams":
        selected = TEAMS.get(int(parts[1]))
        if selected is None:
            return missing()
        if len(parts) == 2:
            return response(selected)
        if parts[2:] == ["invitations"]:
            return pages([r for r in PENDING if (r["id"], selected["id"]) in ASSOCIATIONS])
    if len(parts) == 2:
        return response(ORG)
    tail = parts[2:]
    if tail == ["properties", "schema"]:
        return response(DEFINITIONS)
    if tail[:2] == ["properties", "schema"] and len(tail) == 3:
        row = next((r for r in DEFINITIONS if r["property_name"] == tail[2]), None)
        return response(row) if row else missing()
    if tail == ["properties", "values"]:
        names = ["alpha"] if request.url.params.get("repository_query") == "name:alpha" else list(REPOS)
        return pages(
            [
                {
                    "repository_id": REPOS[n]["id"],
                    "repository_name": n,
                    "repository_full_name": REPOS[n]["full_name"],
                    "properties": VALUES[n],
                }
                for n in names
            ]
        )
    if tail == ["issue-types"]:
        return response(TYPES)
    if tail == ["issue-fields"]:
        return response(FIELDS)
    if tail == ["outside_collaborators"]:
        return pages(
            OUTSIDE[:1] if request.url.params.get("filter") in {"2fa_disabled", "2fa_insecure"} else OUTSIDE
        )
    if tail == ["invitations"]:
        return pages(
            [
                r
                for r in PENDING
                if request.url.params.get("role", "all") in {"all", r["role"]}
                and request.url.params.get("invitation_source", "all") in {"all", r["invitation_source"]}
            ]
        )
    if tail == ["failed_invitations"]:
        return pages(FAILED)
    if len(tail) == 3 and tail[0] == "invitations" and tail[2] == "teams":
        return pages([TEAMS[t] for invitation_id, t in ASSOCIATIONS if invitation_id == int(tail[1])])
    if tail[:1] == ["teams"] and len(tail) >= 2:
        selected = next((t for t in TEAMS.values() if t["slug"] == tail[1]), None)
        if selected is None:
            return missing()
        if len(tail) == 2:
            return response(selected)
        if tail[2:] == ["invitations"]:
            return pages([r for r in PENDING if (r["id"], selected["id"]) in ASSOCIATIONS])
    raise AssertionError(f"Unexpected organization metadata request: {request.url}")


if __name__ == "__main__":
    api.open_client = lambda: httpx.Client(transport=httpx.MockTransport(respond), follow_redirects=True)
    main()
