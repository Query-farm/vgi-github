"""Independent repository identities, metadata snapshots and membership evidence."""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path

import httpx

from vgi_github import github_api as api
from vgi_github.generated_worker import main

OWNER = "repository-detail-fixture"
FORK_OWNER = "repository-fork-fixture"


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


ALICE, BOB = actor("repository-detail-alice", 78101), actor("repository-detail-bob", 78102)
ORGANIZATION = {
    "id": 71000,
    "login": OWNER,
    "type": "Organization",
    "name": OWNER,
    "description": "Repository detail fixture",
    "created_at": "2020-01-01T00:00:00Z",
}
FORK_ORGANIZATION = ORGANIZATION | {"id": 71900, "login": FORK_OWNER}


def repository(identity, name, owner=ORGANIZATION, private=False):
    return {
        "id": identity,
        "node_id": f"R{identity}",
        "full_name": f"{owner['login']}/{name}",
        "name": name,
        "owner": owner,
        "private": private,
        "description": "Repository detail fixture",
        "topics": ["fixture", name],
        "language": "Python",
    }


REPOSITORIES = [
    repository(71001, "alpha"),
    repository(71002, "beta"),
    repository(71003, "empty", private=True),
]
FORKS = {
    "alpha": [repository(71011, "fork-a", FORK_ORGANIZATION), repository(71012, "fork-b", FORK_ORGANIZATION)],
    "beta": [],
    "empty": [],
}
TOPICS = {"alpha": ["analytics", "python"], "beta": ["analytics"], "empty": []}
ERROR = {
    "line": 7,
    "column": 3,
    "source": "* unknown",
    "kind": "Invalid owner",
    "suggestion": None,
    "message": "Invalid owner on line7",
    "path": ".github/CODEOWNERS",
}
ERRORS = {
    "alpha": [ERROR, copy.deepcopy(ERROR)],
    "beta": [
        {
            "line": 2,
            "column": 1,
            "kind": "Invalid pattern",
            "message": "Invalid pattern",
            "path": "CODEOWNERS",
        }
    ],
    "empty": [],
}
PROPERTIES = {
    "alpha": [
        {"property_name": "tier", "value": "gold"},
        {"property_name": "languages", "value": ["python", "sql"]},
        {"property_name": "owner", "value": None},
    ],
    "beta": [{"property_name": "tier", "value": "silver"}],
    "empty": [],
}
FILES = {
    "code_of_conduct": None,
    "code_of_conduct_file": None,
    "license": None,
    "contributing": None,
    "readme": None,
    "issue_template": None,
    "pull_request_template": None,
}
PROFILES = {
    name: {
        "health_percentage": health,
        "description": None,
        "documentation": None,
        "files": copy.deepcopy(FILES),
        "updated_at": None,
    }
    for name, health in [("alpha", 100), ("beta", 50), ("empty", 0)]
}
HASHES = {"alpha": "sha1", "beta": "sha256", "empty": "sha1"}
CONTRIBUTORS = {
    "alpha": [
        ALICE | {"contributions": 5},
        {"type": "Anonymous", "email": "author@example.test", "name": "Anonymous Author", "contributions": 3},
        {"type": "Anonymous", "contributions": 2},
    ],
    "beta": [BOB | {"contributions": 7}],
    "empty": [],
}
PERMISSIONS = {
    "alpha": {"permission": "write", "role_name": "maintain", "user": ALICE | {"role_name": "maintain"}},
    "beta": {"permission": "none", "role_name": "none", "user": None},
    "empty": {
        "permission": "read",
        "role_name": "custom-reader",
        "user": ALICE | {"role_name": "custom-reader"},
    },
}


def invitation(identity, repo, invitee, inviter, permission, expired=None):
    value = {
        "id": identity,
        "node_id": f"I{identity}",
        "repository": repo,
        "invitee": invitee,
        "inviter": inviter,
        "permissions": permission,
        "created_at": "2026-09-01T00:00:00Z",
        "url": f"https://api.github.com/user/repository_invitations/{identity}",
        "html_url": f"https://github.example/invites/{identity}",
    }
    if expired is not None:
        value["expired"] = expired
    return value


INVITATIONS = {
    "alpha": [
        invitation(79001, REPOSITORIES[0], ALICE, BOB, "write", False),
        invitation(79002, REPOSITORIES[0], None, ALICE, "read", True),
    ],
    "beta": [invitation(79003, REPOSITORIES[1], ALICE, None, "triage")],
    "empty": [],
}
ATTESTATIONS = {
    "alpha": [
        {
            "repository_id": 71001,
            "bundle": {
                "mediaType": "application/vnd.dev.sigstore.bundle.v0.3+json",
                "verificationMaterial": {"opaque": [1, "x"]},
                "dsseEnvelope": {"payload": "opaque"},
            },
            "bundle_url": "https://signed.example/bundle/a",
            "initiator": "github-actions",
        },
        {"bundle": {"mediaType": "application/vnd.dev.sigstore.bundle.v0.3+json"}, "initiator": "manual"},
    ],
    "beta": [{"repository_id": 71002, "bundle_url": "https://signed.example/bundle/b"}],
    "empty": [],
}


def respond(request):
    path = request.url.path
    if not (
        path.startswith(
            (
                f"/repos/{OWNER}/",
                f"/repos/{FORK_OWNER}/",
                f"/orgs/{OWNER}",
                f"/users/{OWNER}",
                "/users/repository-detail-",
            )
        )
        or path in {"/repositories", "/user/repos", "/user/repository_invitations"}
    ):
        return None
    if request.method != "GET":
        raise AssertionError(f"Unexpected repository method {request.method}")
    if os.environ.get("CROSSFIELD_GITHUB_API_LOG"):
        with Path(os.environ["CROSSFIELD_GITHUB_API_LOG"]).open("a") as log:
            log.write(json.dumps({"path": path, "query": request.url.query.decode()}) + "\n")

    def response(value=None, status=200, next_cursor=None, cursor="page"):
        headers = {"Cache-Control": "no-store", "X-RateLimit-Remaining": "5000"}
        if next_cursor:
            headers["Link"] = f'<{request.url.copy_set_param(cursor, str(next_cursor))}>; rel="next"'
        if status in {204, 404} and value is None:
            return httpx.Response(status, headers=headers, request=request)
        return httpx.Response(status, json=copy.deepcopy(value), headers=headers, request=request)

    def pages(rows, key=None, cursor="page"):
        page = int(request.url.params.get(cursor, "1"))
        selected = rows[page - 1 : page]
        return response(
            {key: selected} if key else selected,
            next_cursor=page + 1 if page < len(rows) else None,
            cursor=cursor,
        )

    if path in {f"/orgs/{OWNER}", f"/users/{OWNER}"}:
        return response(ORGANIZATION)
    if path == f"/orgs/{OWNER}/repos":
        return pages(REPOSITORIES)
    if path == f"/orgs/{OWNER}/properties/values":
        return pages(
            [
                {
                    "repository_id": repo["id"],
                    "repository_name": repo["name"],
                    "repository_full_name": repo["full_name"],
                    "properties": PROPERTIES[repo["name"]],
                }
                for repo in REPOSITORIES
            ]
        )
    if path.startswith(f"/orgs/{OWNER}/attestations/"):
        return pages([r for rows in ATTESTATIONS.values() for r in rows], "attestations", cursor="after")
    for user in [ALICE, BOB]:
        if path == f"/users/{user['login']}":
            return response(user)
    if path == "/repositories":
        rows = [
            r
            for r in REPOSITORIES
            if not r["private"] and r["id"] > int(request.url.params.get("since", "0"))
        ]
        return response(rows[:1], next_cursor=rows[0]["id"] if len(rows) > 1 else None, cursor="since")
    if path == "/user/repos":
        rows = REPOSITORIES
        visibility = request.url.params.get("visibility") or request.url.params.get("type")
        if visibility in {"public", "private"}:
            rows = [r for r in rows if r["private"] == (visibility == "private")]
        return pages(rows)
    if path == "/user/repository_invitations":
        return pages([INVITATIONS["alpha"][0], INVITATIONS["beta"][0]])
    parts = path.strip("/").split("/")
    owner, name, tail = parts[1], parts[2], parts[3:]
    if not tail:
        all_repos = REPOSITORIES + FORKS["alpha"]
        row = next((r for r in all_repos if r["full_name"] == f"{owner}/{name}"), None)
        return response(row or {"message": "Not Found"}, 200 if row else 404)
    if tail == ["forks"]:
        return pages(FORKS[name])
    if tail == ["topics"]:
        return pages(TOPICS[name], "names")
    if tail == ["codeowners", "errors"]:
        return pages(ERRORS[name], "errors")
    if tail == ["properties", "values"]:
        return pages(PROPERTIES[name])
    if tail == ["community", "profile"]:
        return response(PROFILES[name])
    if tail == ["hash-algorithm"]:
        return response({"hash_algorithm": HASHES[name]})
    if tail == ["contributors"]:
        if name == "empty":
            return response(status=204)
        rows = CONTRIBUTORS[name]
        if request.url.params.get("anon") not in {"true", "1"}:
            rows = [r for r in rows if r["type"] != "Anonymous"]
        return pages(rows)
    if tail[:1] == ["collaborators"] and len(tail) == 2:
        return response(status=204 if name in {"alpha", "empty"} else 404)
    if tail[:1] == ["collaborators"] and tail[-1] == "permission":
        return response(PERMISSIONS[name])
    if tail == ["invitations"]:
        return pages(INVITATIONS[name])
    if tail[:1] == ["attestations"]:
        return pages(ATTESTATIONS[name], "attestations", cursor="after")
    raise AssertionError(f"Unexpected repository detail request {request.url}")


if __name__ == "__main__":
    api.http_client = lambda: httpx.Client(transport=httpx.MockTransport(respond))
    main()
