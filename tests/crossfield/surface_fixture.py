"""Independent fixtures for the expanded semantic model; no live network access.

Discussions have answer durations 2 and 10 hours plus one unanswered question.
Projects contain four items, including a draft and inaccessible content. REST
preserves response-page grain and binary bytes; GraphQL preserves its envelope.
"""

from __future__ import annotations

import copy
import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
from worker_fixture import account, api, main, stamp
from worker_fixture import respond as original_respond


def discussion(number, hours):
    created = datetime(2026, 9, number, tzinfo=UTC)
    return {
        "id": f"D{number}",
        "number": number,
        "title": f"Question {number}",
        "body": "Question",
        "author": {"login": "alice" if number < 3 else "bob"},
        "category": {"id": "QA" if number < 3 else "IDEAS", "name": "Q&A" if number < 3 else "Ideas"},
        "isAnswered": hours is not None,
        "answer": {"id": f"C{number}"} if hours is not None else None,
        "comments": {"totalCount": 2},
        "upvoteCount": number,
        "locked": False,
        "createdAt": stamp(created),
        "updatedAt": "2026-09-10T00:00:00Z",
        "answerChosenAt": stamp(created + timedelta(hours=hours)) if hours is not None else None,
        "url": f"https://github.example/example/project/discussions/{number}",
        "repository": {"nameWithOwner": "example/project"},
    }


def comment(identity, parent=None):
    return {
        "id": identity,
        "body": "Response",
        "author": {"login": "alice"},
        "isAnswer": identity == "C1",
        "replyTo": {"id": parent} if parent else None,
        "replies": {"totalCount": 2 if identity == "C1" else 0},
        "upvoteCount": 1,
        "createdAt": "2026-09-01T02:00:00Z",
        "updatedAt": "2026-09-02T00:00:00Z",
        "url": f"https://github.example/discussion#{identity}",
        "discussion": {"number": 1, "repository": {"nameWithOwner": "example/project"}},
    }


def project(number, closed=False):
    return {
        "id": number + 1000,
        "node_id": f"P{number}",
        "number": number,
        "title": f"Board {number}",
        "description": "Reporting fixture",
        "short_description": "Board",
        "state": "closed" if closed else "open",
        "public": True,
        "is_template": False,
        "owner": {"login": "example"},
        "creator": account("alice", 101),
        "created_at": "2026-09-01T00:00:00Z",
        "updated_at": "2026-09-10T00:00:00Z",
        "closed_at": "2026-09-10T00:00:00Z" if closed else None,
    }


def items(fields):
    rows = []
    for index, kind in enumerate(("Issue", "PullRequest", "DraftIssue", "Issue"), 1):
        content = (
            None
            if index == 4
            else {
                "id": 9000 + index,
                "number": None if index == 3 else index,
                "title": f"Work {index}",
                "body": "Work",
                "state": "closed" if index == 2 else "open" if index == 1 else None,
                "user": account("alice", 101),
                "html_url": None if index == 3 else f"https://github.example/work/{index}",
            }
        )
        rows.append(
            {
                "id": 100 + index,
                "node_id": f"I{index}",
                "content_type": kind,
                "content": content,
                "creator": account("alice", 101),
                "created_at": "2026-09-01T00:00:00Z",
                "updated_at": "2026-09-10T00:00:00Z",
                "archived_at": "2026-09-10T00:00:00Z" if index == 2 else None,
                "fields": [{"id": 1, "value": "Ready"}, {"id": 2, "value": index * 2}]
                if fields
                else [{"id": 0, "value": f"Work {index}"}],
            }
        )
    return rows


def project_fields():
    return [
        {
            "id": index,
            "node_id": f"F{index}",
            "name": name,
            "data_type": kind,
            "options": [{"id": "ready", "name": "Ready"}] if index == 1 else None,
            "configuration": None,
            "created_at": "2026-09-01T00:00:00Z",
            "updated_at": "2026-09-10T00:00:00Z",
        }
        for index, name, kind in ((1, "Status", "single_select"), (2, "Points", "number"))
    ]


def record(request):
    if os.environ.get("CROSSFIELD_GITHUB_API_LOG"):
        with Path(os.environ["CROSSFIELD_GITHUB_API_LOG"]).open("a") as log:
            log.write(
                json.dumps(
                    {"path": request.url.path, "query": str(request.url.params), "method": request.method}
                )
                + "\n"
            )


def respond(request):
    path = request.url.path
    headers = {"Cache-Control": "no-store", "X-RateLimit-Remaining": "5000"}

    def result(payload, status=200):
        return httpx.Response(status, json=payload, headers=headers, request=request)

    if request.method == "POST" and path == "/graphql":
        record(request)
        body = json.loads(request.content)
        document, values = body["query"], body.get("variables", {})
        mode = values.get("name", "project")
        if mode == "partial-error" or values.get("login") == "error":
            return result(
                {
                    "data": {"viewer": {"login": "partial"}},
                    "errors": [{"message": "Fixture partial GraphQL error"}],
                }
            )
        if document.lstrip().startswith("query Discussions("):
            rows = [discussion(1, 2), discussion(2, None), discussion(3, 10)]
            key, prefix = "discussions", "repository"
        elif document.lstrip().startswith("query DiscussionComments("):
            rows = [comment("C1"), comment("C2")]
            key, prefix = "comments", "discussion"
        elif document.lstrip().startswith("query DiscussionReplies("):
            rows = [comment("R1", "C1"), comment("R2", "C1")]
            key, prefix = "replies", "node"
        else:
            # The real worker parser has already rejected mutations/subscriptions.
            return result(
                {
                    "data": {
                        "user": {"login": values.get("login", "fixture")},
                        "pageInfo": {"hasNextPage": True, "endCursor": "next-cursor"},
                    },
                    "extensions": {"fixture": "retained"},
                }
            )
        for row in rows:
            repository = f"{values.get('owner', 'example')}/{mode}"
            if "repository" in row:
                row["repository"]["nameWithOwner"] = repository
            elif "discussion" in row:
                row["discussion"]["repository"]["nameWithOwner"] = repository
        if mode == "missing":
            return result({"data": {"repository": None}})
        if mode == "empty":
            rows = []
        if mode == "duplicate" and rows:
            rows.append(copy.deepcopy(rows[0]))
        if mode == "negative-duration" and rows:
            rows[0]["answerChosenAt"] = "2020-01-01T00:00:00Z"
        if mode == "null-id" and rows:
            rows[0]["id"] = None
        offset = 2 if values.get("after") else 0
        selected = rows[offset : offset + 2]
        connection = {
            "nodes": selected,
            "pageInfo": {
                "hasNextPage": offset + 2 < len(rows),
                "endCursor": "page-two" if offset + 2 < len(rows) else None,
            },
        }
        if prefix == "discussion":
            payload = {"repository": {"discussion": {key: connection}}}
        elif prefix == "node":
            payload = {"node": {"__typename": "DiscussionComment", key: connection}}
        else:
            payload = {prefix: {key: connection}}
        return result({"data": payload})

    if request.method != "GET":
        raise AssertionError("Only GET and validated GraphQL POST are permitted")
    if "/projectsV2" in path:
        record(request)
        pieces = path.split("/")
        owner = pieces[2]
        if owner == "missing":
            return result({"message": "Not Found"}, 404)
        if path.endswith("/items"):
            rows = items(request.url.params.get("fields"))
        elif path.endswith("/fields"):
            rows = project_fields()
        else:
            rows = [project(7), project(8, True)]
        if not path.endswith(("/items", "/fields")):
            for row in rows:
                row["owner"]["login"] = owner
        if owner == "empty":
            rows = []
        if owner == "duplicate" and rows:
            rows.append(copy.deepcopy(rows[0]))
        page = int(request.url.params.get("page", "1"))
        if page * 2 < len(rows):
            headers["Link"] = f'<{request.url.copy_set_param("page", str(page + 1))}>; rel="next"'
        return result(rows[(page - 1) * 2 : page * 2])
    if path.endswith("/pulls/1/reviews"):
        record(request)
        page = int(request.url.params.get("page", "1"))
        if page == 1:
            headers["Link"] = f'<{request.url.copy_set_param("page", "2")}>; rel="next"'
        return result([{"id": page, "state": "APPROVED" if page == 1 else "COMMENTED", "extra": [1, None]}])
    if "/zipball/" in path:
        record(request)
        return httpx.Response(
            200,
            content=b"\x00\xff\x80archive\x00",
            headers={**headers, "Content-Type": "application/octet-stream"},
            request=request,
        )
    if path == "/orgs/example/members/outsider":
        record(request)
        return result({"message": "Not Found"}, 404)
    return original_respond(request)


api.open_client = lambda: httpx.Client(transport=httpx.MockTransport(respond), follow_redirects=True)
if __name__ == "__main__":
    main()
