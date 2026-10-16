"""Independent reactions with overlapping subject IDs, a large comment ID and deleted reactors."""

from __future__ import annotations

import json
import os
from copy import deepcopy
from pathlib import Path

import httpx
from graphql import parse, value_from_ast_untyped

from vgi_github import github_api as api
from vgi_github.generated_worker import main


def actor(identity, login, kind="User"):
    result = {
        "id": identity,
        "node_id": f"RU{identity}",
        "login": login,
        "type": kind,
        "gravatar_id": None,
        "site_admin": False,
        "name": login,
        "email": None,
        "user_view_type": "public",
    }
    for name in [
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
        result[name] = f"https://api.github.com/users/{login}/{name}"
    return result


ALICE, BOB, BOT = (
    actor(1601, "reaction-alice"),
    actor(1602, "reaction-bob"),
    actor(1603, "reaction-bot", "Bot"),
)
REPOSITORY = {
    "id": 1501,
    "node_id": "RR1501",
    "full_name": "reaction-fixture/alpha",
    "name": "alpha",
    "owner": {"id": 1500, "login": "reaction-fixture", "type": "Organization"},
    "private": False,
    "description": "Independent reaction facts",
    "topics": [],
    "language": "Python",
}
LARGE_COMMENT_ID = 5_000_000_501
SUBJECTS = {
    "issues/1": {"id": 5101, "node_id": "RI5101", "number": 1},
    "issues/2": {
        "id": 5102,
        "node_id": "RPR5102",
        "number": 2,
        "pull_request": {
            "url": "https://api.github.com/repos/reaction-fixture/alpha/pulls/2",
            "diff_url": None,
            "html_url": None,
            "patch_url": None,
        },
    },
    "issues/3": {"id": 5103, "node_id": "RI5103", "number": 3},
    f"issues/comments/{LARGE_COMMENT_ID}": {"id": LARGE_COMMENT_ID, "node_id": f"RIC{LARGE_COMMENT_ID}"},
    "pulls/comments/701": {"id": 701, "node_id": "RRC701"},
    "comments/701": {"id": 701, "node_id": "RCC701"},
    "releases/701": {"id": 701, "node_id": "RREL701"},
}


def reaction(identity, content, user):
    return {
        "id": identity,
        "node_id": f"REACT{identity}",
        "content": content,
        "user": user,
        "created_at": "2026-09-03T12:00:00Z",
    }


REACTIONS = {
    "issues/1": [
        reaction(9001, "+1", ALICE),
        reaction(9002, "heart", ALICE),
        reaction(9003, "-1", BOB),
        reaction(9004, "eyes", None),
        reaction(9005, "+1", BOB),
    ],
    "issues/2": [reaction(9010, "rocket", BOT)],
    "issues/3": [],
    f"issues/comments/{LARGE_COMMENT_ID}": [reaction(9021, "+1", BOB), reaction(9022, "laugh", None)],
    "pulls/comments/701": [
        reaction(9031, "confused", ALICE),
        reaction(9032, "+1", BOB),
        reaction(9033, "-1", ALICE),
    ],
    "comments/701": [reaction(9041, "hooray", ALICE), reaction(9042, "heart", BOT)],
    "releases/701": [
        reaction(9051, "+1", ALICE),
        reaction(9052, "heart", BOB),
        reaction(9053, "rocket", None),
    ],
}


def respond(request):
    path = request.url.path
    body = json.loads(request.content) if path == "/graphql" else None
    if body is not None:
        values = body.get("variables", {})
        if not any(str(v).startswith(("RIC", "RCC")) for v in values.values()):
            return None
    elif not path.startswith("/repos/reaction-fixture/"):
        return None
    if os.environ.get("CROSSFIELD_GITHUB_API_LOG"):
        with Path(os.environ["CROSSFIELD_GITHUB_API_LOG"]).open("a") as output:
            output.write(json.dumps({"path": path, "query": request.url.query.decode()}) + "\n")
    headers = {"Cache-Control": "no-store", "X-RateLimit-Remaining": "5000"}

    def response(value, status=200, extra=None):
        return httpx.Response(status, json=deepcopy(value), request=request, headers=headers | (extra or {}))

    if body is not None:
        field = parse(body["query"]).definitions[0].selection_set.selections[0]
        identity = value_from_ast_untyped(field.arguments[0].value, values)
        node = next((s for s in SUBJECTS.values() if s["node_id"] == identity), None)
        if node is None:
            return response({"data": {"node": None}})
        return response(
            {
                "data": {
                    "node": {
                        "__typename": "IssueComment" if identity.startswith("RIC") else "CommitComment",
                        "id": identity,
                        "fullDatabaseId": str(node["id"]),
                        "databaseId": node["id"],
                        "repository": {"nameWithOwner": "reaction-fixture/alpha"},
                    }
                }
            }
        )
    pieces = path.split("/")
    assert pieces[3] == "alpha", request.url
    suffix = "/".join(pieces[4:])
    if not suffix:
        return response(REPOSITORY)
    if suffix.endswith("/reactions"):
        subject = suffix.removesuffix("/reactions")
        if subject not in REACTIONS:
            return response({"message": "Not Found"}, 404)
        rows = REACTIONS[subject]
        if request.url.params.get("content"):
            rows = [r for r in rows if r["content"] == request.url.params["content"]]
        page = int(request.url.params.get("page", "1"))
        link = (
            {"Link": f'<{request.url.copy_set_param("page", str(page + 1))}>; rel="next"'}
            if page < len(rows)
            else {}
        )
        return response(rows[page - 1 : page], extra=link)
    if suffix in SUBJECTS:
        # Parent authors and publishers deliberately differ from every reacting account.
        return response(
            SUBJECTS[suffix]
            | {"user": {"id": 1699, "login": "parent-author"}, "author": {"id": 1698, "login": "publisher"}}
        )
    return response({"message": "Not Found"}, 404)


if __name__ == "__main__":
    api.open_client = lambda: httpx.Client(transport=httpx.MockTransport(respond), follow_redirects=True)
    main()
