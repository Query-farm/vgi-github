"""Independent repository change history with opaque cursor pagination and actor roles."""

from __future__ import annotations

import json
import os
from copy import deepcopy
from pathlib import Path

import httpx

from vgi_github import github_api as api
from vgi_github.generated_worker import main

ORG = "changes-fixture"
OWNER = {"id": 6800, "login": ORG, "type": "Organization"}
REPOSITORIES = {
    name: {
        "id": identity,
        "node_id": "R" + str(identity),
        "name": name,
        "full_name": ORG + "/" + name,
        "owner": OWNER,
        "private": False,
        "description": "Change-history fixture",
        "topics": [],
        "language": "Python",
    }
    for name, identity in [("alpha", 6801), ("beta", 6802)]
}


def actor(identity):
    login = "changes-fixture-actor"
    url = "https://api.github.com/users/" + login
    return {
        "id": identity,
        "login": login,
        "type": "User",
        "node_id": "U" + str(identity),
        "avatar_url": "https://avatars.githubusercontent.com/u/" + str(identity),
        "gravatar_id": None,
        "html_url": "https://github.com/" + login,
        "url": url,
        "followers_url": url + "/followers",
        "following_url": url + "/following{/other_user}",
        "gists_url": url + "/gists{/gist_id}",
        "starred_url": url + "/starred{/owner}{/repo}",
        "subscriptions_url": url + "/subscriptions",
        "organizations_url": url + "/orgs",
        "repos_url": url + "/repos",
        "events_url": url + "/events{/privacy}",
        "received_events_url": url + "/received_events",
        "site_admin": False,
    }


ACTOR = actor(6850)


def change(identity, kind, performer, ref="refs/heads/main"):
    return {
        "id": identity,
        "node_id": "ACT" + str(identity),
        "before": "a" * 40,
        "after": "0" * 40 if kind == "branch_deletion" else "b" * 40,
        "ref": ref,
        "timestamp": "2026-05-01T00:00:00Z",
        "activity_type": kind,
        "actor": performer,
    }


CHANGES = {
    "alpha": [
        change(1, "push", ACTOR),
        change(2, "force_push", None),
        change(3, "branch_deletion", ACTOR, "refs/heads/old"),
    ],
    "beta": [change(1, "pr_merge", ACTOR)],
}


def respond(request):
    path = request.url.path
    if not path.startswith(("/repos/" + ORG + "/", "/orgs/" + ORG, "/users/" + ORG)):
        return None
    if os.environ.get("CROSSFIELD_GITHUB_API_LOG"):
        with Path(os.environ["CROSSFIELD_GITHUB_API_LOG"]).open("a") as output:
            output.write(json.dumps({"path": path, "query": request.url.query.decode()}) + "\n")
    headers = {"Cache-Control": "no-store", "X-RateLimit-Remaining": "5000"}

    def response(value, status=200, extra=None):
        return httpx.Response(status, json=deepcopy(value), request=request, headers=headers | (extra or {}))

    if path == "/users/" + ORG:
        return response(OWNER)
    if path == "/users/changes-fixture-actor":
        return response(ACTOR | {"created_at": "2020-01-01T00:00:00Z"})
    if path == "/orgs/" + ORG + "/repos":
        number = int(request.url.params.get("page", "1"))
        links = {"Link": f'<{request.url.copy_set_param("page", "2")}>; rel="next"'} if number == 1 else {}
        return response(list(REPOSITORIES.values())[number - 1 : number], extra=links)
    parts = path.strip("/").split("/")
    name = parts[2]
    if name not in REPOSITORIES:
        return response({"message": "Not Found"}, 404)
    if len(parts) == 3:
        return response(REPOSITORIES[name])
    if parts[3:] == ["activity"]:
        rows = deepcopy(CHANGES[name])
        q = request.url.params
        if q.get("activity_type"):
            rows = [r for r in rows if r["activity_type"] == q["activity_type"]]
        if q.get("ref"):
            rows = [r for r in rows if r["ref"] == q["ref"]]
        if q.get("actor"):
            rows = [r for r in rows if r["actor"] and r["actor"]["login"] == q["actor"]]
        if q.get("direction") == "asc":
            rows.reverse()
        index = int(q.get("after", "cursor:0").split(":")[-1])
        if q.get("before") == "cursor:1":
            rows = rows[:1]
        next_url = request.url.copy_set_param("after", "cursor:" + str(index + 1))
        links = {"Link": f'<{next_url}>; rel="next"'} if index + 1 < len(rows) else {}
        return response(rows[index : index + 1], extra=links)
    return response({"message": "Not Found"}, 404)


if __name__ == "__main__":
    api.open_client = lambda: httpx.Client(transport=httpx.MockTransport(respond), follow_redirects=True)
    main()
