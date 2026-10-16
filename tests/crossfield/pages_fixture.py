"""Independent Pages configuration and list/latest/exact build populations."""

from __future__ import annotations

import json
import os
from copy import deepcopy
from pathlib import Path

import httpx

from vgi_github import github_api as api
from vgi_github.generated_worker import main

ORG = "pages-fixture"
OWNER = {"id": 6400, "login": ORG, "type": "Organization"}
PUSHER = {
    "id": 6450,
    "login": "pages-fixture-pusher",
    "type": "User",
    "node_id": "U6450",
    "html_url": "https://github.com/pages-fixture-pusher",
}
REPOSITORIES = {
    name: {
        "id": identity,
        "node_id": "R" + str(identity),
        "name": name,
        "full_name": ORG + "/" + name,
        "owner": OWNER,
        "private": False,
        "description": "Pages fixture",
        "topics": [],
        "language": "HTML",
    }
    for name, identity in [("alpha", 6401), ("beta", 6402)]
}


def build(repository, identity, status, duration, pusher):
    return {
        "url": "https://api.github.com/repos/" + ORG + "/" + repository + "/pages/builds/" + str(identity),
        "status": status,
        "error": {"message": "Build failed" if status == "errored" else None},
        "pusher": pusher,
        "commit": "a" * 40 if repository == "alpha" else "b" * 40,
        "duration": duration,
        "created_at": "2026-05-01T00:00:00Z",
        "updated_at": "2026-05-01T00:00:02Z",
    }


BUILDS = {
    "alpha": [
        build("alpha", 103, "errored", 20, None),
        build("alpha", 102, "built", 30, PUSHER),
        build("alpha", 101, "built", 40, PUSHER),
    ],
    "beta": [build("beta", 201, "building", 0, PUSHER)],
}
SITES = {
    name: {
        "url": "https://api.github.com/repos/" + ORG + "/" + name + "/pages",
        "status": "built" if name == "alpha" else "building",
        "cname": "pages.example.invalid" if name == "alpha" else None,
        "protected_domain_state": "verified" if name == "alpha" else None,
        "pending_domain_unverified_at": None,
        "custom_404": False,
        "html_url": "https://pages.example.invalid/" + name,
        "build_type": "legacy" if name == "alpha" else "workflow",
        "source": {"branch": "main", "path": "/docs"},
        "public": name == "alpha",
        "https_enforced": True,
        "https_certificate": {
            "state": "approved",
            "description": "Fixture certificate",
            "domains": ["pages.example.invalid"],
            "expires_at": "2027-01-01",
        },
    }
    for name in REPOSITORIES
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

    def page(rows):
        number = int(request.url.params.get("page", "1"))
        links = (
            {"Link": f'<{request.url.copy_set_param("page", str(number + 1))}>; rel="next"'}
            if number < len(rows)
            else {}
        )
        return response(rows[number - 1 : number], extra=links)

    if path == "/users/" + ORG:
        return response(OWNER)
    if path == "/orgs/" + ORG + "/repos":
        return page(list(REPOSITORIES.values()))
    if path == "/users/pages-fixture-pusher":
        return response(PUSHER | {"name": "Build pusher", "created_at": "2020-01-01T00:00:00Z"})
    parts = path.strip("/").split("/")
    name = parts[2]
    if name not in REPOSITORIES:
        return response({"message": "Not Found"}, 404)
    if len(parts) == 3:
        return response(REPOSITORIES[name])
    if parts[3:] == ["pages"]:
        return response(SITES[name])
    if parts[3:] == ["pages", "builds"]:
        return page(BUILDS[name])
    if parts[3:5] == ["pages", "builds"] and len(parts) == 6:
        target = parts[5]
        row = (
            BUILDS[name][0]
            if target == "latest"
            else next((row for row in BUILDS[name] if row["url"].endswith("/" + target)), None)
        )
        return response(row) if row else response({"message": "Not Found"}, 404)
    return response({"message": "Not Found"}, 404)


if __name__ == "__main__":
    api.open_client = lambda: httpx.Client(transport=httpx.MockTransport(respond), follow_redirects=True)
    main()
