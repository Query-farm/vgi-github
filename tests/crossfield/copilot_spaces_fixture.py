"""Independent Spaces, resources and actor-qualified collaborator memberships."""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path

import httpx

from vgi_github import github_api as api
from vgi_github.generated_worker import main

OWNER = "copilot-space-fixture"
USER = "copilot-space-alice"


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


ALICE, BOB = actor(USER, 68101), actor("copilot-space-bob", 68102)
ORGANIZATION = actor(OWNER, 61000) | {"type": "Organization", "description": "Copilot Spaces fixture"}
for field in ["hooks_url", "issues_url", "members_url", "public_members_url"]:
    ORGANIZATION[field] = f"https://github.example/{OWNER}/{field}"


def resource(identity, kind, metadata):
    return {
        "id": identity,
        "resource_type": kind,
        "copilot_chat_attachment_id": None,
        "metadata": metadata,
        "created_at": "2026-09-01T00:00:00Z",
        "updated_at": "2026-09-03T00:00:00Z",
    }


RESOURCES = {
    (OWNER, 1): [
        resource(
            63001,
            "repository",
            {
                "repository_id": 64001,
                "name": "alpha",
                "extra_shape": {"enabled": True, "values": [1, "x", None]},
            },
        ),
        resource(63002, "free_text", {"text": "Independent fixture text", "name": "Instructions"}),
    ],
    (OWNER, 2): [],
    (USER, 1): [resource(63003, "github_file", {"repository_id": 64002, "file_path": "README.md"})],
}


def space(identity, number, name, owner, creator, resources):
    return {
        "id": identity,
        "number": number,
        "name": name,
        "description": None,
        "general_instructions": "Use the source evidence",
        "base_role": "reader",
        "owner": owner,
        "creator": creator,
        "created_at": "2026-09-01T00:00:00Z",
        "updated_at": "2026-09-03T00:00:00Z",
        "html_url": f"https://github.example/spaces/{identity}",
        "api_url": f"https://api.github.com/organizations/{owner['id']}/copilot-spaces/{number}",
        "resources_attributes": resources,
    }


SPACES = {
    OWNER: [
        space(61001, 1, "Engineering", ORGANIZATION, ALICE, RESOURCES[(OWNER, 1)]),
        space(61002, 2, "Empty", ORGANIZATION, BOB, []),
    ],
    USER: [space(61003, 1, "Personal", ALICE, ALICE, RESOURCES[(USER, 1)])],
}
# Same numeric ID in different actor domains must remain two memberships.
TEAM = {
    "id": 68101,
    "node_id": "T68101",
    "actor_type": "Team",
    "type": "Team",
    "name": "Reviewers",
    "slug": "reviewers",
    "role": "reader",
    "organization_id": 61000,
    "description": None,
    "parent": {"id": 999, "opaque": [1, "x"]},
}
COLLABORATORS = {
    (OWNER, 1): [ALICE | {"actor_type": "User", "role": "writer"}, TEAM],
    (OWNER, 2): [],
    (USER, 1): [BOB | {"actor_type": "User", "role": "admin"}],
}


def respond(request):
    path = request.url.path
    if not path.startswith((f"/orgs/{OWNER}", "/users/copilot-space-")):
        return None
    if request.method != "GET":
        raise AssertionError(f"Unexpected Copilot Spaces method {request.method}")
    if os.environ.get("CROSSFIELD_GITHUB_API_LOG"):
        with Path(os.environ["CROSSFIELD_GITHUB_API_LOG"]).open("a") as log:
            log.write(json.dumps({"path": path, "query": request.url.query.decode()}) + "\n")

    def response(value, status=200, next_page=None):
        headers = {"Cache-Control": "no-store", "X-RateLimit-Remaining": "5000"}
        if next_page:
            headers["Link"] = f'<{request.url.copy_set_param("after", str(next_page))}>; rel="next"'
        return httpx.Response(status, json=copy.deepcopy(value), headers=headers, request=request)

    def pages(rows, key):
        page = int(request.url.params.get("after", "1"))
        return response({key: rows[page - 1 : page]}, next_page=page + 1 if page < len(rows) else None)

    if path == f"/orgs/{OWNER}":
        return response(ORGANIZATION)
    for user in [ALICE, BOB]:
        if path == f"/users/{user['login']}":
            return response(user)
    parts = path.strip("/").split("/")
    owner = parts[1]
    if owner not in SPACES or parts[2] != "copilot-spaces":
        raise AssertionError(f"Unexpected Copilot Spaces path {path}")
    if len(parts) == 3:
        return pages(SPACES[owner], "spaces")
    number = int(parts[3])
    row = next((r for r in SPACES[owner] if r["number"] == number), None)
    if row is None:
        return response({"message": "Not Found"}, 404)
    if len(parts) == 4:
        return response(row)
    if parts[4:] == ["collaborators"]:
        return pages(COLLABORATORS[(owner, number)], "collaborators")
    if parts[4:] == ["resources"]:
        return pages(RESOURCES[(owner, number)], "resources")
    if len(parts) == 6 and parts[4] == "resources":
        value = next((r for r in RESOURCES[(owner, number)] if r["id"] == int(parts[5])), None)
        return response(value if value else {"message": "Not Found"}, 200 if value else 404)
    raise AssertionError(f"Unexpected Copilot Spaces request {request.url}")


if __name__ == "__main__":
    api.http_client = lambda: httpx.Client(transport=httpx.MockTransport(respond))
    main()
