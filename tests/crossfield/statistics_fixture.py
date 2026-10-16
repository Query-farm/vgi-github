"""Independent statistics with nullable contributors, signed tuples and typed weekly series."""

from __future__ import annotations

import json
import os
from copy import deepcopy
from pathlib import Path

import httpx

from vgi_github import github_api as api
from vgi_github.generated_worker import main

ORG = "statistics-fixture"
OWNER = {"id": 6600, "login": ORG, "type": "Organization"}
REPOSITORIES = {
    name: {
        "id": identity,
        "node_id": "R" + str(identity),
        "name": name,
        "full_name": ORG + "/" + name,
        "owner": OWNER,
        "private": False,
        "description": "Statistics fixture",
        "topics": [],
        "language": "Python",
    }
    for name, identity in [("alpha", 6601), ("beta", 6602)]
}


def actor(identity):
    login = "statistics-fixture-" + str(identity)
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


STATISTICS = {
    ("alpha", "code_frequency"): [[1704585600, 12, -4], [1705190400, 8, -3]],
    ("alpha", "commit_activity"): [
        {"week": 1704585600, "total": 4, "days": [0, 1, 0, 2, 1, 0, 0]},
        {"week": 1705190400, "total": 3, "days": [1, 0, 0, 0, 0, 0, 2]},
    ],
    ("beta", "commit_activity"): [{"week": 1705190400, "total": 2, "days": [0, 0, 0, 0, 1, 1, 0]}],
    ("alpha", "contributors"): [
        {
            "author": actor(6650),
            "total": 7,
            "weeks": [{"w": 1704585600, "a": 12, "d": 4, "c": 4}, {"w": 1705190400, "a": 8, "d": 3, "c": 3}],
        },
        {"author": None, "total": 2, "weeks": [{"w": 1705190400, "a": 0, "d": 0, "c": 2}]},
    ],
    ("beta", "contributors"): [
        {"author": actor(6651), "total": 3, "weeks": [{"w": 1705190400, "a": 5, "d": 1, "c": 3}]}
    ],
    ("alpha", "participation"): {"all": [0] * 50 + [4, 3], "owner": [0] * 50 + [1, 1]},
    ("beta", "participation"): {"all": [0] * 51 + [2], "owner": [0] * 52},
    ("alpha", "punch_card"): [[0, 9, 2], [2, 14, 5]],
    ("beta", "punch_card"): [[6, 22, 3]],
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
    if path == "/orgs/" + ORG + "/repos":
        number = int(request.url.params.get("page", "1"))
        links = {"Link": f'<{request.url.copy_set_param("page", "2")}>; rel="next"'} if number == 1 else {}
        return response(list(REPOSITORIES.values())[number - 1 : number], extra=links)
    if path.startswith("/users/statistics-fixture-"):
        return response(actor(int(path.rsplit("-", 1)[-1])) | {"created_at": "2020-01-01T00:00:00Z"})
    parts = path.strip("/").split("/")
    name = parts[2]
    if name not in REPOSITORIES:
        return response({"message": "Not Found"}, 404)
    if len(parts) == 3:
        return response(REPOSITORIES[name])
    if parts[3:] == ["stats", "code_frequency"] and name == "beta":
        return httpx.Response(204, request=request, headers=headers)
    if len(parts) == 5 and parts[3] == "stats":
        return response(STATISTICS[(name, parts[4])])
    return response({"message": "Not Found"}, 404)


if __name__ == "__main__":
    api.open_client = lambda: httpx.Client(transport=httpx.MockTransport(respond), follow_redirects=True)
    main()
