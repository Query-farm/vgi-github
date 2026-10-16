"""Independent Git graph: distinct author/committer roles, rerouted refs and repeated blobs.

Three commits have four per-commit file changes; their two-commit comparison has
only two net changed paths. One-page-per-record lists expose missing pagination.
Two root paths share a blob, and a nested tree contains another blob.
"""

from __future__ import annotations

import base64
import copy
import json
import os
from datetime import datetime
from pathlib import Path

import httpx

from vgi_github import github_api as api
from vgi_github.generated_worker import main

A, B, C = (letter * 40 for letter in "abc")
TREE, SUBTREE, TAG, BLOB1, BLOB2, SUBMODULE = (letter * 40 for letter in "d12345")
REPOSITORIES = [
    {
        "id": identity,
        "node_id": f"R{identity}",
        "full_name": f"git-fixture/{name}",
        "name": name,
        "owner": {"id": 810, "login": "git-fixture", "type": "Organization"},
        "private": False,
        "description": "Independent Git fixture",
        "topics": [],
        "language": "Python",
    }
    for identity, name in [(811, "alpha"), (812, "empty")]
]


def actor(login, identity):
    return {"id": identity, "login": login, "type": "User"}


ALICE, BOB = actor("alice", 201), actor("bob", 202)


def change(path, sha, added, deleted, status="modified", previous=None, patch=True):
    result = {
        "filename": path,
        "sha": sha,
        "status": status,
        "additions": added,
        "deletions": deleted,
        "changes": added + deleted,
        "blob_url": f"https://github.example/blob/{sha}/{path}",
        "raw_url": f"https://github.example/raw/{sha}/{path}",
        "contents_url": f"https://api.github.example/contents/{path}",
    }
    if previous:
        result["previous_filename"] = previous
    if patch:
        result["patch"] = "@@ independent patch @@"
    return result


FILES = {
    A: [change("alpha.txt", BLOB1, 10, 0, "added")],
    B: [
        change("beta.txt", BLOB2, 3, 1, "renamed", "alpha.txt"),
        change("binary.png", BLOB1, 0, 0, "added", patch=False),
    ],
    C: [change("beta.txt", BLOB2, 2, 2)],
}


def commit(sha, parent, author, committer, authored, committed):
    files = FILES[sha]
    return {
        "sha": sha,
        "node_id": f"COMMIT{sha}",
        "html_url": f"https://github.example/commit/{sha}",
        "author": author,
        "committer": committer,
        "parents": [
            {
                "sha": parent,
                "url": f"https://api.github.example/commits/{parent}",
                "html_url": f"https://github.example/commit/{parent}",
            }
        ]
        if parent
        else [],
        "commit": {
            "message": f"Commit {sha[0]}",
            "author": {"name": "Original author", "email": "author@example.com", "date": authored},
            "committer": {"name": "Commit integrator", "email": "committer@example.com", "date": committed},
            "tree": {"sha": TREE, "url": f"https://api.github.example/git/trees/{TREE}"},
            "comment_count": 0,
            "verification": {
                "verified": False,
                "reason": "unsigned",
                "signature": None,
                "payload": None,
                "verified_at": None,
            },
        },
        "stats": {
            "additions": sum(f["additions"] for f in files),
            "deletions": sum(f["deletions"] for f in files),
            "total": sum(f["changes"] for f in files),
        },
        "files": files,
    }


COMMITS = {
    A: commit(A, None, ALICE, BOB, "2026-09-01T00:00:00Z", "2026-09-01T01:00:00Z"),
    B: commit(B, A, BOB, ALICE, "2026-09-02T00:00:00Z", "2026-09-02T01:00:00Z"),
    C: commit(C, B, {}, None, "2026-09-01T02:00:00Z", "2026-09-03T01:00:00Z"),
}
ALIASES = {"main": C, "feature": B, "v1": A, "v0": A, "main-copy": C}
BRANCHES = [
    {
        "name": name,
        "commit": {"sha": sha, "url": f"https://api.github.example/commits/{sha}"},
        "protected": name == "main",
    }
    for name, sha in [("main", C), ("feature", B), ("main-copy", C)]
]
TAGS = [
    {
        "name": name,
        "node_id": f"TAGREF{name}",
        "commit": {"sha": A, "url": f"https://api.github.example/commits/{A}"},
        "zipball_url": f"https://github.example/{name}.zip",
        "tarball_url": f"https://github.example/{name}.tar.gz",
    }
    for name in ["v1", "v0"]
]


def reference(name, sha, kind="commit"):
    return {
        "ref": "refs/" + name,
        "node_id": "REF" + name,
        "url": "https://api.github.example/git/ref/" + name,
        "object": {"sha": sha, "type": kind, "url": "https://api.github.example/git/objects/" + sha},
    }


REFERENCES = [
    reference("heads/main", C),
    reference("heads/feature", B),
    reference("heads/main-copy", C),
    reference("tags/v1", TAG, "tag"),
    reference("tags/v0", A),
    reference("notes/comment", BLOB1, "blob"),
]
TAG_OBJECT = {
    "sha": TAG,
    "node_id": "ANNOTATEDTAG",
    "tag": "v1",
    "message": "Annotated release tag",
    "tagger": {"name": "Tagger", "email": "tagger@example.com", "date": "2026-09-01T00:00:00Z"},
    "object": {"sha": A, "type": "commit", "url": "https://api.github.example/git/commits/" + A},
    "verification": {
        "verified": False,
        "reason": "unsigned",
        "signature": None,
        "payload": None,
        "verified_at": None,
    },
    "url": "https://api.github.example/git/tags/" + TAG,
}


def entry(path, sha, kind="blob", size=None):
    row = {
        "path": path,
        "sha": sha,
        "type": kind,
        "mode": {"blob": "100644", "tree": "040000", "commit": "160000"}[kind],
        "url": "https://api.github.example/git/objects/" + sha,
    }
    if size is not None:
        row["size"] = size
    return row


TREES = {
    TREE: [
        entry("alpha.txt", BLOB1, size=10),
        entry("copy.txt", BLOB1, size=10),
        entry("src", SUBTREE, "tree"),
        entry("module", SUBMODULE, "commit"),
    ],
    SUBTREE: [entry("main.py", BLOB2, size=20)],
}
BLOBS = {
    sha: {
        "sha": sha,
        "node_id": "BLOB" + sha,
        "url": "https://api.github.example/git/blobs/" + sha,
        "size": len(content),
        "encoding": "base64",
        "content": base64.b64encode(content).decode(),
    }
    for sha, content in [(BLOB1, b"0123456789"), (BLOB2, b"x" * 20)]
}
COMPARISON_FILES = [
    change("beta.txt", BLOB2, 5, 3, "renamed", "alpha.txt"),
    change("binary.png", BLOB1, 0, 0, "added", patch=False),
]
PULLS = {
    sha: [
        {
            "id": identity,
            "number": number,
            "state": "closed",
            "title": f"PR {number}",
            "user": ALICE,
            "html_url": f"https://github.example/pulls/{number}",
        }
    ]
    for sha, identity, number in [(A, 9001, 11), (B, 9001, 11), (C, 9002, 12)]
}


def respond(request):
    path = request.url.path
    if not (
        path.startswith("/repos/git-fixture/") or path in {"/users/git-fixture", "/orgs/git-fixture/repos"}
    ):
        return None
    if os.environ.get("CROSSFIELD_GITHUB_API_LOG"):
        with Path(os.environ["CROSSFIELD_GITHUB_API_LOG"]).open("a") as log:
            log.write(json.dumps({"path": path, "query": str(request.url.query)}) + "\n")
    headers = {"Cache-Control": "no-store", "X-RateLimit-Remaining": "5000"}

    def response(value, status=200, extra=None):
        return httpx.Response(
            status, json=copy.deepcopy(value), headers=headers | (extra or {}), request=request
        )

    def listing(rows, envelope=None):
        page = int(request.url.params.get("page", "1"))
        extra = (
            {"Link": f'<{request.url.copy_set_param("page", str(page + 1))}>; rel="next"'}
            if page < len(rows)
            else {}
        )
        payload = rows[page - 1 : page]
        if envelope is not None:
            payload = {**envelope, "commits": payload}
        return response(payload, extra=extra)

    if path == "/users/git-fixture":
        return response({"id": 810, "login": "git-fixture", "type": "Organization"})
    if path == "/orgs/git-fixture/repos":
        return listing(REPOSITORIES)
    prefix = "/repos/git-fixture/"
    rest = path[len(prefix) :]
    repository_name, _, suffix = rest.partition("/")
    repo = next((r for r in REPOSITORIES if r["name"] == repository_name), None)
    if repo is None:
        return response({"message": "Not Found"}, 404)
    if not suffix:
        return response(repo)
    if suffix == "commits":
        rows = [COMMITS[C], COMMITS[B], COMMITS[A]] if repository_name == "alpha" else []
        history = request.url.params.get("sha")
        if history:
            sha = ALIASES.get(history, history)
            index = next((i for i, row in enumerate(rows) if row["sha"] == sha), len(rows))
            rows = rows[index:]
        for role in ["author", "committer"]:
            if request.url.params.get(role):
                rows = [row for row in rows if (row[role] or {}).get("login") == request.url.params[role]]
        if request.url.params.get("path"):
            rows = [
                row
                for row in rows
                if any(f["filename"] == request.url.params["path"] for f in FILES[row["sha"]])
            ]
        for bound, lower in [("since", True), ("until", False)]:
            if request.url.params.get(bound):
                supplied = request.url.params[bound]
                assert "T" in supplied, "Typed date-time query bindings must use ISO8601"
                instant = datetime.fromisoformat(supplied.replace("Z", "+00:00"))
                rows = [
                    row
                    for row in rows
                    if (
                        datetime.fromisoformat(row["commit"]["committer"]["date"].replace("Z", "+00:00"))
                        >= instant
                        if lower
                        else datetime.fromisoformat(row["commit"]["committer"]["date"].replace("Z", "+00:00"))
                        <= instant
                    )
                ]
        return listing([{k: v for k, v in row.items() if k not in {"stats", "files"}} for row in rows])
    if suffix.startswith("commits/"):
        value = suffix[len("commits/") :]
        for ending in ["/branches-where-head", "/pulls"]:
            if value.endswith(ending):
                sha = value[: -len(ending)]
                return listing(
                    [branch for branch in BRANCHES if branch["commit"]["sha"] == sha]
                    if ending.endswith("head")
                    else PULLS.get(sha, [])
                )
        sha = ALIASES.get(value, value)
        if sha not in COMMITS:
            return response({"message": "Not Found"}, 404)
        row = copy.deepcopy(COMMITS[sha])
        page = int(request.url.params.get("page", "1"))
        row["files"] = FILES[sha][page - 1 : page]
        extra = (
            {"Link": f'<{request.url.copy_set_param("page", str(page + 1))}>; rel="next"'}
            if page < len(FILES[sha])
            else {}
        )
        return response(row, extra=extra)
    if suffix == "branches":
        rows = BRANCHES if repository_name == "alpha" else []
        if "protected" in request.url.params:
            protected = request.url.params["protected"] == "true"
            rows = [row for row in rows if row["protected"] == protected]
        return listing(rows)
    if suffix.startswith("branches/"):
        name = suffix[len("branches/") :]
        branch = next((row for row in BRANCHES if row["name"] == name), None)
        return response(branch) if branch else response({"message": "Not Found"}, 404)
    if suffix == "tags":
        return listing(TAGS if repository_name == "alpha" else [])
    if suffix.startswith("compare/"):
        selected = suffix[len("compare/") :]
        assert selected == "v1...main", selected
        assert request.url.params.get("per_page") == "100", "Comparisons must request explicit pagination"
        payload = {
            "base_commit": COMMITS[A],
            "merge_base_commit": COMMITS[A],
            "status": "ahead",
            "ahead_by": 2,
            "behind_by": 0,
            "total_commits": 2,
            "html_url": "https://github.example/compare/v1...main",
        }
        if request.url.params.get("page", "1") == "1":
            payload["files"] = COMPARISON_FILES
        return listing([COMMITS[B], COMMITS[C]], payload)
    if suffix.startswith("git/commits/"):
        sha = suffix[len("git/commits/") :]
        row = COMMITS[sha]
        return response(
            {
                "sha": sha,
                "message": row["commit"]["message"],
                "author": row["commit"]["author"],
                "committer": row["commit"]["committer"],
                "tree": row["commit"]["tree"],
                "parents": row["parents"],
                "verification": row["commit"]["verification"],
            }
        )
    if suffix.startswith("git/matching-refs/"):
        prefix = suffix[len("git/matching-refs/") :]
        return listing(
            [row for row in REFERENCES if row["ref"].startswith("refs/" + prefix)]
            if repository_name == "alpha"
            else []
        )
    if suffix.startswith("git/ref/"):
        name = suffix[len("git/ref/") :]
        row = next((row for row in REFERENCES if row["ref"] == "refs/" + name), None)
        return response(row) if row else response({"message": "Not Found"}, 404)
    if suffix.startswith("git/tags/"):
        return response(TAG_OBJECT)
    if suffix.startswith("git/trees/"):
        sha = suffix[len("git/trees/") :]
        entries = copy.deepcopy(TREES[sha])
        if request.url.params.get("recursive") and sha == TREE:
            entries.append(entry("src/main.py", BLOB2, size=20))
        return response(
            {
                "sha": sha,
                "url": "https://api.github.example/git/trees/" + sha,
                "truncated": False,
                "tree": entries,
            }
        )
    if suffix.startswith("git/blobs/"):
        return response(BLOBS[suffix[len("git/blobs/") :]])
    raise AssertionError(f"Unexpected Git fixture request: {request.url}")


if __name__ == "__main__":
    api.open_client = lambda: httpx.Client(transport=httpx.MockTransport(respond), follow_redirects=True)
    main()
