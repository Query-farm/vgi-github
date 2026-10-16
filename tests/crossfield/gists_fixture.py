"""Independent gist populations, file dictionaries, comments and revision snapshots."""

from __future__ import annotations

import json
import os
from copy import deepcopy
from pathlib import Path

import httpx

from vgi_github import github_api as api
from vgi_github.generated_worker import main

OWNER = "gist-fixture-owner"
CALLER = {"id": 903, "login": "package-fixture-current", "type": "User"}
AUTHOR = {
    "id": 5100,
    "login": OWNER,
    "type": "User",
    "node_id": "U5100",
    "html_url": "https://github.com/" + OWNER,
}
REVISIONS = ["a" * 40, "b" * 40, "c" * 40]


def file(name, size, content, *, language="", truncated=False):
    return {
        "filename": name,
        "type": "text/plain",
        "language": language,
        "raw_url": "https://gist.invalid/raw/" + name,
        "size": size,
        "content": content,
        "truncated": truncated,
        "encoding": "utf-8",
    }


def gist(identity, *, public, files, parent=None):
    return {
        "id": identity,
        "node_id": "G-" + identity,
        "url": "https://api.github.com/gists/" + identity,
        "forks_url": "https://api.github.com/gists/" + identity + "/forks",
        "commits_url": "https://api.github.com/gists/" + identity + "/commits",
        "git_pull_url": "https://gist.github.com/" + identity + ".git",
        "git_push_url": "https://gist.github.com/" + identity + ".git",
        "html_url": "https://gist.github.com/" + identity,
        "files": files,
        "public": public,
        "created_at": "creation timestamp is unformatted in the pinned detail schema",
        "updated_at": "2026-05-03T00:00:00Z",
        "description": "Independent " + identity,
        "comments": {"gist-a": 2, "gist-b": 1, "gist-c": 0, "gist-unknown": 0}[identity],
        "comments_enabled": True,
        "comments_url": "https://api.github.com/gists/" + identity + "/comments",
        "owner": deepcopy(AUTHOR),
        "truncated": identity == "gist-b",
        "fork_of": (
            {
                "id": parent,
                "node_id": "G-" + parent,
                "url": "https://api.github.com/gists/" + parent,
                "owner": deepcopy(AUTHOR),
                "created_at": "2026-04-01T00:00:00Z",
                "updated_at": "2026-05-03T00:00:00Z",
            }
            if parent
            else None
        ),
    }


GISTS = {
    "gist-a": gist(
        "gist-a",
        public=True,
        files={"main.py": file("main.py", 5, "x=1\n", language="Python"), "gone.txt": None},
    ),
    "gist-b": gist("gist-b", public=False, files={"README": file("README", 4, "ab", truncated=True)}),
    "gist-c": gist("gist-c", public=True, files={}, parent="gist-a"),
    # Direct-only fixture: unknown counters must not alter the discovery populations above.
    "gist-unknown": gist(
        "gist-unknown",
        public=False,
        files={
            "unavailable.txt": None,
            "missing-size.txt": {
                "filename": "missing-size.txt",
                "type": "text/plain",
                "content": "Available content does not supply the omitted byte-size measurement.",
            },
        },
    ),
}


def comment(identity, gist_id, author):
    return {
        "id": identity,
        "node_id": "GC" + str(identity),
        "url": "https://api.github.com/gists/" + gist_id + "/comments/" + str(identity),
        "body": "Comment " + str(identity),
        "user": deepcopy(author),
        "created_at": "2026-05-02T00:00:00Z",
        "updated_at": "2026-05-03T00:00:00Z",
        "author_association": "OWNER" if author else "NONE",
    }


COMMENTS = {
    "gist-a": [comment(1, "gist-a", AUTHOR), comment(2, "gist-a", None)],
    "gist-b": [comment(1, "gist-b", AUTHOR)],
    "gist-c": [],
    "gist-unknown": [],
}


def commit(gist_id, sha, additions, deletions, user):
    return {
        "url": "https://api.github.com/gists/" + gist_id + "/" + sha,
        "version": sha,
        "user": deepcopy(user),
        "change_status": {"total": additions + deletions, "additions": additions, "deletions": deletions},
        "committed_at": "2026-05-01T00:00:00Z",
    }


COMMITS = {
    "gist-a": [commit("gist-a", REVISIONS[0], 10, 2, AUTHOR), commit("gist-a", REVISIONS[1], 3, 1, None)],
    "gist-b": [commit("gist-b", REVISIONS[2], 4, 0, AUTHOR)],
    "gist-c": [],
    "gist-unknown": [
        {
            "url": "https://api.github.com/gists/gist-unknown/" + "e" * 40,
            "version": "e" * 40,
            "user": None,
            # The required object exists, but its optional counters were not reported.
            "change_status": {},
            "committed_at": "2026-05-01T00:00:00Z",
        }
    ],
}


def respond(request):
    path = request.url.path
    if not (
        path == "/user"
        or path == "/users/" + OWNER
        or path == "/users/" + OWNER + "/gists"
        or path == "/gists"
        or path in {"/gists/public", "/gists/starred"}
        or path.startswith(
            ("/gists/gist-a", "/gists/gist-b", "/gists/gist-c", "/gists/gist-missing", "/gists/gist-unknown")
        )
    ):
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

    if path == "/user":
        return response(CALLER)
    if path == "/users/" + OWNER:
        return response(AUTHOR | {"name": "Gist owner", "created_at": "2020-01-01T00:00:00Z"})
    if path in {"/gists", "/gists/public", "/gists/starred", "/users/" + OWNER + "/gists"}:
        ids = {"/gists": ["gist-a", "gist-b"], "/gists/starred": ["gist-b"]}.get(path, ["gist-a", "gist-c"])
        if request.url.params.get("since", "") >= "2027":
            ids = []
        return page([{"id": identity} for identity in ids])
    pieces = path.strip("/").split("/")
    identity = pieces[1]
    if len(pieces) == 3 and pieces[2] == "star":
        if identity == "gist-b":
            return httpx.Response(204, request=request, headers=headers)
        return response({}, 404)
    value = GISTS.get(identity)
    if value is None:
        return response({"message": "Not Found"}, 404)
    if len(pieces) == 2:
        return response(value)
    if pieces[2] == "forks":
        return page([{"id": "gist-c"}] if identity == "gist-a" else [])
    if pieces[2] == "comments":
        if len(pieces) == 3:
            return page(COMMENTS[identity])
        found = next((row for row in COMMENTS[identity] if row["id"] == int(pieces[3])), None)
        return response(found) if found else response({"message": "Not Found"}, 404)
    if pieces[2] == "commits":
        return page(COMMITS[identity])
    if pieces[2] in {row["version"] for row in COMMITS[identity]}:
        snapshot = deepcopy(value)
        if pieces[2] == REVISIONS[1]:
            snapshot["files"] = {"main.py": file("main.py", 2, "x\n", language="Python")}
        return response(snapshot)
    return response({"message": "Not Found"}, 404)


if __name__ == "__main__":
    api.open_client = lambda: httpx.Client(transport=httpx.MockTransport(respond), follow_redirects=True)
    main()
