"""Independent rolling traffic windows, buckets and bounded popular populations."""

from __future__ import annotations

import json
import os
from copy import deepcopy
from pathlib import Path

import httpx

from vgi_github import github_api as api
from vgi_github.generated_worker import main

ORG = "traffic-fixture"
OWNER = {"id": 6500, "login": ORG, "type": "Organization"}
REPOSITORIES = {
    name: {
        "id": identity,
        "node_id": "R" + str(identity),
        "name": name,
        "full_name": ORG + "/" + name,
        "owner": OWNER,
        "private": False,
        "description": "Traffic fixture",
        "topics": [],
        "language": "Python",
    }
    for name, identity in [("alpha", 6501), ("beta", 6502)]
}


def bucket(day, count, uniques):
    return {"timestamp": "2026-05-" + day + "T00:00:00Z", "count": count, "uniques": uniques}


TRAFFIC = {
    ("alpha", "clones", "day"): {
        "count": 8,
        "uniques": 4,
        "clones": [bucket("04", 3, 2), bucket("05", 5, 3)],
    },
    ("alpha", "clones", "week"): {"count": 8, "uniques": 4, "clones": [bucket("04", 8, 4)]},
    ("beta", "clones", "day"): {"count": 0, "uniques": 0, "clones": []},
    ("beta", "clones", "week"): {"count": 0, "uniques": 0, "clones": []},
    ("alpha", "views", "day"): {
        "count": 15,
        "uniques": 5,
        "views": [bucket("04", 10, 4), bucket("05", 5, 3)],
    },
    ("alpha", "views", "week"): {"count": 15, "uniques": 5, "views": [bucket("04", 15, 5)]},
    ("beta", "views", "day"): {"count": 2, "uniques": 2, "views": [bucket("05", 2, 2)]},
    ("beta", "views", "week"): {"count": 2, "uniques": 2, "views": [bucket("04", 2, 2)]},
}
PATHS = {
    "alpha": [
        {"path": "/one", "title": "One", "count": 10, "uniques": 4},
        {"path": "/two", "title": "Two", "count": 5, "uniques": 3},
    ],
    "beta": [{"path": "/", "title": "Root", "count": 2, "uniques": 2}],
}
REFERRERS = {
    "alpha": [
        {"referrer": "Google", "count": 6, "uniques": 3},
        {"referrer": "Direct", "count": 2, "uniques": 2},
    ],
    "beta": [],
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
    parts = path.strip("/").split("/")
    name = parts[2]
    if name not in REPOSITORIES:
        return response({"message": "Not Found"}, 404)
    if len(parts) == 3:
        return response(REPOSITORIES[name])
    if parts[3:5] == ["traffic", "popular"]:
        return response(PATHS[name] if parts[5] == "paths" else REFERRERS[name])
    if parts[3] == "traffic":
        return response(TRAFFIC[(name, parts[4], request.url.params.get("per", "day"))])
    return response({"message": "Not Found"}, 404)


if __name__ == "__main__":
    api.open_client = lambda: httpx.Client(transport=httpx.MockTransport(respond), follow_redirects=True)
    main()
