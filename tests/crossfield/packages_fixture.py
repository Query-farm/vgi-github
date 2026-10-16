"""Independent org, named-user and authenticated package/version populations."""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path

import httpx

from vgi_github import github_api as api
from vgi_github.generated_worker import main

ORG = "package-fixture-org"
USER = "package-fixture-user"
AUTH = "package-fixture-current"
ACCOUNTS = {
    ORG: {"id": 901, "login": ORG, "type": "Organization"},
    USER: {"id": 902, "login": USER, "type": "User"},
    AUTH: {"id": 903, "login": AUTH, "type": "User"},
}
REPOSITORY = {
    "id": 910,
    "node_id": "R910",
    "full_name": f"{ORG}/source",
    "name": "source",
    "owner": ACCOUNTS[ORG],
    "private": False,
    "description": "Package source repository",
    "topics": [],
    "language": None,
}


def package(
    identity,
    owner,
    name,
    count,
    *,
    kind="container",
    visibility="public",
    no_owner=False,
    no_repository=False,
):
    return {
        "id": identity,
        "name": name,
        "package_type": kind,
        "url": f"https://api.github.example/packages/{identity}",
        "html_url": f"https://github.example/packages/{identity}",
        "version_count": count,
        "visibility": visibility,
        "owner": None if no_owner else ACCOUNTS[owner],
        "repository": None if no_repository else REPOSITORY,
        "created_at": "2026-08-01T00:00:00Z",
        "updated_at": "2026-09-01T00:00:00Z",
    }


PACKAGES = {
    ORG: [
        package(11, ORG, "shared", 2),
        package(12, ORG, "private-image", 1, visibility="private"),
        package(13, ORG, "legacy", 0, kind="docker"),
    ],
    USER: [package(21, USER, "shared", 1), package(23, USER, "legacy", 0, kind="docker")],
    AUTH: [
        package(31, AUTH, "shared", 1, visibility="private", no_owner=True),
        package(32, AUTH, "unlinked", 0, no_repository=True),
        package(33, AUTH, "legacy", 0, kind="docker", visibility="private", no_owner=True),
    ],
}


def version(identity, name, *, deleted=False, kind="container"):
    value = {
        "id": identity,
        "name": name,
        "url": f"https://api.github.example/versions/{identity}",
        "html_url": f"https://github.example/versions/{identity}",
        "package_html_url": "https://github.example/packages/shared",
        "license": "MIT",
        "description": "Independent version metadata",
        "created_at": "2026-08-02T00:00:00Z",
        "updated_at": "2026-09-01T00:00:00Z",
        "metadata": {"package_type": kind, "container": {"tags": [name, "latest"]}},
    }
    if deleted:
        value["deleted_at"] = "2026-09-02T00:00:00Z"
    return value


VERSIONS = {
    11: [version(111, "v1"), version(112, "v2"), version(113, "old", deleted=True)],
    12: [version(121, "v1")],
    13: [],
    21: [version(211, "v1")],
    23: [],
    31: [version(311, "v1"), version(312, "old", deleted=True)],
    32: [],
    33: [],
}


def respond(request):
    path = request.url.path
    owned = path == "/user" or path.startswith(
        (
            "/user/packages",
            "/user/docker/conflicts",
            "/orgs/package-fixture-",
            "/users/package-fixture-",
            "/repos/package-fixture-",
        )
    )
    if not owned:
        return None
    if request.method != "GET":
        raise AssertionError(f"Unexpected packages method {request.method}")
    if os.environ.get("CROSSFIELD_GITHUB_API_LOG"):
        with Path(os.environ["CROSSFIELD_GITHUB_API_LOG"]).open("a") as log:
            log.write(json.dumps({"path": path, "query": request.url.query.decode()}) + "\n")
    headers = {"Cache-Control": "no-store", "X-RateLimit-Remaining": "5000"}

    def response(value, code=200, next_page=None):
        result_headers = dict(headers)
        if next_page:
            result_headers["Link"] = f'<{request.url.copy_set_param("page", str(next_page))}>; rel="next"'
        return httpx.Response(code, json=copy.deepcopy(value), headers=result_headers, request=request)

    def pages(rows):
        page = int(request.url.params.get("page", "1"))
        return response(rows[page - 1 : page], next_page=page + 1 if page < len(rows) else None)

    def missing():
        return response({"message": "Not Found"}, 404)

    if path == "/user":
        return response(ACCOUNTS[AUTH])
    parts = path.strip("/").split("/")
    if path == f"/repos/{ORG}/source":
        return response(REPOSITORY)
    if parts[0] == "user":
        owner, tail = AUTH, parts[1:]
    elif parts[0] in {"orgs", "users"} and len(parts) >= 2 and parts[1] in ACCOUNTS:
        owner, tail = parts[1], parts[2:]
        if not tail:
            return response(ACCOUNTS[owner])
    else:
        return missing()
    if tail == ["docker", "conflicts"]:
        return pages([row for row in PACKAGES[owner] if row["package_type"] == "docker"])
    if tail == ["packages"]:
        kind = request.url.params["package_type"]
        return pages([row for row in PACKAGES[owner] if row["package_type"] == kind])
    if len(tail) >= 3 and tail[0] == "packages":
        kind, name = tail[1:3]
        package_row = next(
            (row for row in PACKAGES[owner] if row["package_type"] == kind and row["name"] == name), None
        )
        if package_row is None or (parts[0] == "users" and package_row["visibility"] == "private"):
            return missing()
        if len(tail) == 3:
            return response(package_row)
        if tail[3] != "versions":
            raise AssertionError(f"Unexpected package fixture path {path}")
        rows = VERSIONS[package_row["id"]]
        if len(tail) == 4:
            if owner == USER:
                assert "state" not in request.url.params, "Named-user listing has no state parameter"
            state = request.url.params.get("state", "active")
            return pages([row for row in rows if ("deleted_at" in row) == (state == "deleted")])
        if len(tail) == 5:
            value = next((row for row in rows if row["id"] == int(tail[4])), None)
            return response(value) if value is not None else missing()
    raise AssertionError(f"Unexpected package fixture path {path}")


if __name__ == "__main__":
    api.open_client = lambda: httpx.Client(transport=httpx.MockTransport(respond), follow_redirects=True)
    main()
