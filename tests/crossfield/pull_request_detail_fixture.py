"""Independent review, PR diff, commit membership and merge observations."""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path

import httpx

from vgi_github import github_api as api
from vgi_github.generated_worker import main

OWNER = "pull-detail-fixture"
A, B, C = (letter * 40 for letter in "abc")


def actor(login, identity):
    value = {
        "id": identity,
        "login": login,
        "node_id": f"U{identity}",
        "type": "User",
        "site_admin": False,
        "gravatar_id": "",
        "user_view_type": "public",
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


ALICE, BOB = actor("pull-detail-alice", 1401), actor("pull-detail-bob", 1402)
REPOSITORIES = [
    {
        "id": identity,
        "node_id": f"R{identity}",
        "full_name": f"{OWNER}/{name}",
        "name": name,
        "owner": {"id": 1300, "login": OWNER, "type": "Organization"},
        "private": False,
        "description": "Independent PR detail fixture",
        "topics": [],
        "language": "Python",
    }
    for identity, name in [(1301, "alpha"), (1302, "beta"), (1303, "empty")]
]


def pull(identity, number, *, merged=False, draft=False, commits=0, files=0):
    base_repository = REPOSITORIES[1 if identity == 1321 else 0]
    value = {
        "id": identity,
        "node_id": f"PR{identity}",
        "number": number,
        "state": "closed" if merged else "open",
        "title": "fix: independent PR",
        "body": None,
        "draft": draft,
        "user": ALICE,
        "created_at": "2026-08-01T00:00:00Z",
        "updated_at": "2026-08-03T00:00:00Z",
        "closed_at": "2026-08-03T00:00:00Z" if merged else None,
        "merged_at": "2026-08-03T00:00:00Z" if merged else None,
        "html_url": f"https://github.example/pulls/{identity}",
        "labels": [],
        "assignees": [],
        "commits": commits,
        "changed_files": files,
        "comments": 3 if identity == 1311 else 1 if identity == 1321 else 0,
        "review_comments": 2 if identity == 1311 else 0,
        "additions": 10 if identity == 1311 else 2 if identity == 1321 else 0,
        "deletions": 3 if identity == 1311 else 1 if identity == 1321 else 0,
        "locked": identity == 1311,
        "active_lock_reason": "resolved" if identity == 1311 else None,
        "author_association": "CONTRIBUTOR",
        "merge_commit_sha": C if merged else None,
        "base": {"label": f"{OWNER}:main", "ref": "main", "sha": A, "repo": base_repository},
        "head": {
            "label": f"pull-detail-alice:change-{number}",
            "ref": f"change-{number}",
            "sha": B,
            "repo": {"id": 91301, "node_id": "R91301", "full_name": "pull-detail-alice/alpha"}
            if identity == 1311
            else base_repository,
        },
        "milestone": {"id": 1711, "number": 1, "title": "Delivery", "state": "open", "due_on": None}
        if identity == 1311
        else None,
        "auto_merge": {
            "enabled_by": ALICE,
            "merge_method": "squash",
            "commit_title": "Ready change",
            "commit_message": "Ready",
        }
        if identity == 1321
        else None,
        "merged": merged,
        "mergeable": None if draft else not merged,
        "rebaseable": None if draft else not merged,
        "mergeable_state": "unknown" if draft else "clean",
        "maintainer_can_modify": True,
        "merged_by": BOB if merged else None,
    }
    for field in (
        "url",
        "diff_url",
        "patch_url",
        "issue_url",
        "commits_url",
        "review_comments_url",
        "review_comment_url",
        "comments_url",
        "statuses_url",
    ):
        value[field] = f"https://github.example/{OWNER}/pulls/{number}/{field}"
    return value


PULLS = {
    "alpha": [pull(1311, 1, merged=True, commits=2, files=2), pull(1312, 2, draft=True)],
    "beta": [pull(1321, 1, commits=1, files=1)],
    "empty": [],
}


def review(identity, state, reviewer):
    row = {
        "id": identity,
        "node_id": f"REVIEW{identity}",
        "state": state,
        "body": "Independent review",
        "commit_id": A,
        "user": reviewer,
        "html_url": f"https://github.example/reviews/{identity}",
        "pull_request_url": "https://api.github.example/pulls/1",
        "author_association": "COLLABORATOR",
        "_links": {
            "html": {"href": f"https://github.example/reviews/{identity}"},
            "pull_request": {"href": "https://api.github.example/pulls/1"},
        },
    }
    if state != "PENDING":
        row["submitted_at"] = "2026-08-02T00:00:00Z"
    return row


REVIEWS = {
    ("alpha", 1): [review(1511, "APPROVED", BOB), review(1512, "COMMENTED", ALICE)],
    ("alpha", 2): [],
    ("beta", 1): [review(1521, "PENDING", BOB)],
}


def comment(identity, pr, review_id, author, reply=None):
    row = {
        "id": identity,
        "node_id": f"RC{identity}",
        "pull_request_review_id": review_id,
        "body": "Independent diff comment",
        "path": "main.py",
        "diff_hunk": "@@ independent diff @@",
        "position": 3,
        "original_position": 3,
        "commit_id": A,
        "original_commit_id": A,
        "user": author,
        "created_at": "2026-08-02T00:00:00Z",
        "updated_at": "2026-08-03T00:00:00Z",
        "html_url": f"https://github.example/comments/{identity}",
        "url": f"https://api.github.example/comments/{identity}",
        "pull_request_url": f"https://api.github.example/repos/{OWNER}/{pr[0]}/pulls/{pr[1]}",
        "author_association": "COLLABORATOR",
        "line": 5,
        "original_line": 5,
        "side": "RIGHT",
        "subject_type": "line",
        "_links": {
            "self": {"href": f"https://api.github.example/comments/{identity}"},
            "html": {"href": f"https://github.example/comments/{identity}"},
            "pull_request": {"href": f"https://api.github.example/repos/{OWNER}/{pr[0]}/pulls/{pr[1]}"},
        },
    }
    if reply:
        row["in_reply_to_id"] = reply
    return row


COMMENTS = {
    ("alpha", 1): [comment(1611, ("alpha", 1), 1511, BOB), comment(1612, ("alpha", 1), 1512, ALICE, 1611)],
    ("alpha", 2): [comment(1621, ("alpha", 2), None, None)],
    ("beta", 1): [comment(1631, ("beta", 1), 1521, BOB)],
}


def change(name, added, deleted, status="modified", previous=None, patch=True):
    row = {
        "filename": name,
        "sha": A,
        "status": status,
        "additions": added,
        "deletions": deleted,
        "changes": added + deleted,
        "blob_url": f"https://github.example/blob/{name}",
        "raw_url": f"https://github.example/raw/{name}",
        "contents_url": f"https://api.github.example/contents/{name}",
    }
    if previous:
        row["previous_filename"] = previous
    if patch:
        row["patch"] = "@@ independent patch @@"
    return row


FILES = {
    ("alpha", 1): [change("main.py", 10, 3), change("image.png", 0, 0, "added", patch=False)],
    ("alpha", 2): [],
    ("beta", 1): [change("renamed.py", 2, 1, "renamed", "old.py")],
}
PR_COMMITS = {("alpha", 1): [A, B], ("alpha", 2): [], ("beta", 1): [C]}


def commit(sha):
    added, deleted = {A: (6, 1), B: (4, 2), C: (2, 1)}[sha]
    return {
        "sha": sha,
        "node_id": f"COMMIT{sha}",
        "html_url": f"https://github.example/commit/{sha}",
        "author": ALICE,
        "committer": BOB,
        "parents": [],
        "commit": {
            "message": "Independent commit",
            "author": {
                "name": "Original author",
                "email": "author@example.com",
                "date": "2026-08-01T00:00:00Z",
            },
            "committer": {
                "name": "Integrator",
                "email": "integrator@example.com",
                "date": "2026-08-02T00:00:00Z",
            },
            "tree": {"sha": "d" * 40},
            "comment_count": 0,
            "verification": {"verified": False, "reason": "unsigned"},
        },
        "stats": {"additions": added, "deletions": deleted, "total": added + deleted},
    }


TEAM = {
    "id": 1801,
    "node_id": "T1801",
    "name": "Reviewers",
    "slug": "reviewers",
    "description": None,
    "privacy": "closed",
    "notification_setting": "notifications_enabled",
    "html_url": "https://github.example/teams/reviewers",
}
REQUESTS = {
    ("alpha", 1): {"users": [BOB], "teams": [TEAM]},
    ("alpha", 2): {"users": [], "teams": []},
    ("beta", 1): {"users": [ALICE, BOB], "teams": []},
}


def stack(name):
    repo = next(repo for repo in REPOSITORIES if repo["name"] == name)
    return {
        "id": 1701 if name == "alpha" else 1702,
        "number": 7 if name == "alpha" else 8,
        "node_id": "STACK" + name,
        "url": f"https://api.github.example/repos/{OWNER}/{name}/stacks/7",
        "base": {"ref": "main"},
        "open": True,
        "created_at": "2026-08-01T00:00:00Z",
        "pull_requests": [
            {
                **{
                    field: row[field]
                    for field in [
                        "id",
                        "number",
                        "node_id",
                        "title",
                        "state",
                        "draft",
                        "merged_at",
                        "html_url",
                        "user",
                    ]
                },
                "head": {
                    "ref": f"feature-{row['number']}",
                    "sha": A,
                    "repo": {
                        "id": repo["id"],
                        "name": name,
                        "url": f"https://api.github.example/repos/{OWNER}/{name}",
                    },
                },
            }
            for row in PULLS[name]
        ],
    }


def merge_result(key):
    details = {"message": f"Request {key}"}
    if key == "pending":
        details.update(
            uuid=key, merge_method="merge", merge_action="default", expected_head_sha=A, bypass_rules=False
        )
    elif key == "merged":
        details["sha"] = C
    return {"status": key, "details": details}


def respond(request):
    path = request.url.path
    if not path.startswith((f"/repos/{OWNER}/", f"/orgs/{OWNER}", f"/users/{OWNER}", "/users/pull-detail-")):
        return None
    if request.method != "GET":
        raise AssertionError(f"Unexpected PR-detail method {request.method}")
    if os.environ.get("CROSSFIELD_GITHUB_API_LOG"):
        with Path(os.environ["CROSSFIELD_GITHUB_API_LOG"]).open("a") as log:
            log.write(json.dumps({"path": path, "query": request.url.query.decode()}) + "\n")
    headers = {"Cache-Control": "no-store", "X-RateLimit-Remaining": "5000"}

    def response(value=None, status=200, next_page=None):
        result_headers = dict(headers)
        if next_page:
            result_headers["Link"] = f'<{request.url.copy_set_param("page", str(next_page))}>; rel="next"'
        return httpx.Response(
            status,
            **({"json": copy.deepcopy(value)} if value is not None else {"content": b""}),
            headers=result_headers,
            request=request,
        )

    def pages(rows):
        page = int(request.url.params.get("page", "1"))
        return response(rows[page - 1 : page], next_page=page + 1 if page < len(rows) else None)

    if path in {f"/orgs/{OWNER}", f"/users/{OWNER}"}:
        return response({"id": 1300, "login": OWNER, "type": "Organization"})
    if path == f"/orgs/{OWNER}/repos":
        return pages(REPOSITORIES)
    for user in [ALICE, BOB]:
        if path == f"/users/{user['login']}":
            return response(user)
    parts = path.strip("/").split("/")
    name, tail = parts[2], parts[3:]
    if not tail:
        return response(next(repo for repo in REPOSITORIES if repo["name"] == name))
    if tail[0] == "commits":
        return response(commit(tail[1]))
    if tail[0] == "stacks":
        rows = [] if name == "empty" else [stack(name)]
        if len(tail) == 2:
            return response(next(row for row in rows if row["number"] == int(tail[1])))
        if request.url.params.get("pull_request"):
            rows = [
                row
                for row in rows
                if any(pr["number"] == int(request.url.params["pull_request"]) for pr in row["pull_requests"])
            ]
        return pages(rows)
    if tail == ["pulls"]:
        return pages(PULLS[name])
    if tail[:2] == ["pulls", "comments"]:
        rows = [
            row
            for (repository, number), comments in COMMENTS.items()
            if repository == name
            for row in comments
        ]
        return (
            pages(rows)
            if len(tail) == 2
            else response(next(row for row in rows if row["id"] == int(tail[2])))
        )
    if tail[0] == "pulls":
        number = int(tail[1])
        key = name, number
        pull_row = next(row for row in PULLS[name] if row["number"] == number)
        if len(tail) == 2:
            return response(pull_row)
        if tail[2] == "comments":
            return pages(COMMENTS[key])
        if tail[2] == "reviews":
            if len(tail) == 3:
                return pages(REVIEWS[key])
            if len(tail) == 4:
                return response(next(row for row in REVIEWS[key] if row["id"] == int(tail[3])))
            return pages([row for row in COMMENTS[key] if row["pull_request_review_id"] == int(tail[3])])
        if tail[2] == "files":
            return pages(FILES[key])
        if tail[2] == "commits":
            return pages([commit(sha) for sha in PR_COMMITS[key]])
        if tail[2] == "requested_reviewers":
            return response(REQUESTS[key])
        if tail[2] == "merge":
            return response(status=204 if pull_row["merged_at"] else 404)
        if tail[2] == "merge-async":
            return (
                response({"message": "Expired merge request"}, 404)
                if tail[3] == "expired"
                else response(merge_result(tail[3]))
            )
    raise AssertionError(f"Unexpected PR-detail fixture path {path}")


if __name__ == "__main__":
    api.open_client = lambda: httpx.Client(transport=httpx.MockTransport(respond), follow_redirects=True)
    main()
