"""Independent reverse-route oracle; one row per page exposes pagination errors.

Organization membership, collaboration, authorship and team access deliberately
have different populations. Discussion replies include a deleted author and a
second reply level so walking only root comments cannot pass the count checks.
"""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path

import connected_fixture as baseline
import httpx
from graphql import parse, value_from_ast_untyped

PUBLIC_ORGS = {"alice": ["example", "public-org"], "carol": ["example"], "bob": [], "empty-user": []}
TEAM_REPOS = {"core": ["alpha", "beta"], "docs": ["alpha"], "empty": []}
COLLABORATORS = {"alpha": ["alice", "bob"], "beta": ["alice", "carol"], "empty": []}


def event(identity, repo, author, number=1):
    return {
        "id": identity,
        "number": number,
        "author": {"__typename": "User", "login": author, "databaseId": baseline.USERS[author]["id"]}
        if author
        else None,
        "createdAt": "2026-09-01T00:00:00Z",
        "updatedAt": "2026-09-02T00:00:00Z",
        "url": f"https://github.example/activity/{identity}",
        "body": f"Evidence {identity}",
        "title": f"Subject {identity}",
        "state": "OPEN",
        "closedAt": None,
        "repository": {
            "id": {"alpha": "REPO101", "beta": "REPO102"}[repo],
            "databaseId": {"alpha": 101, "beta": 102}[repo],
            "nameWithOwner": f"example/{repo}",
            "primaryLanguage": None,
        },
    }


ISSUES = [
    event("I1", "alpha", "alice", 1),
    event("I2", "alpha", "bob", 2),
    event("I3", "alpha", None, 3),
    event("I4", "beta", "carol", 4),
]
for row in ISSUES:
    row.update(
        fullDatabaseId=str(int(row["id"][1:])),
        stateReason=None,
        bodyHTML="<p>Issue evidence</p>",
        bodyText=row["body"],
        closed=False,
        locked=False,
        activeLockReason=None,
        authorAssociation="CONTRIBUTOR",
        createdViaEmail=False,
        lastEditedAt=None,
        publishedAt=row["createdAt"],
        isPinned=None,
        milestone=None,
        subIssuesSummary={"total": 0, "completed": 0, "percentCompleted": 0},
    )

DISCUSSIONS = [
    event("D1", "alpha", "alice", 1),
    event("D2", "alpha", "bob", 2),
    event("D3", "beta", "carol", 3),
]
COMMIT_COMMENTS = [
    event("CC1", "alpha", "alice"),
    event("CC2", "alpha", "bob"),
    event("CC3", "beta", "carol"),
]
for index, row in enumerate(COMMIT_COMMENTS, 1):
    row.update(
        databaseId=7000 + index,
        commit={"oid": str(index) * 40},
        path=None,
        position=None,
        authorAssociation="CONTRIBUTOR",
    )
ISSUE_COMMENTS = [
    event("IC1", "alpha", "alice", 1),
    event("IC2", "alpha", "bob", 2),
    event("IC3", "alpha", None, 2),
    event("IC4", "beta", "carol", 1),
]


def comment(identity, discussion, author, parent=None):
    row = event(identity, "alpha", author)
    row.pop("repository")
    row.update(discussion=copy.deepcopy(discussion), replyTo={"id": parent} if parent else None)
    return row


DISCUSSION_COMMENTS = [
    comment("C1", DISCUSSIONS[0], "alice"),
    comment("C2", DISCUSSIONS[0], "bob"),
    comment("R1", DISCUSSIONS[0], "bob", "C1"),
    comment("R2", DISCUSSIONS[0], None, "C1"),
    comment("N1", DISCUSSIONS[0], "alice", "R1"),
    comment("C3", DISCUSSIONS[1], "carol"),
]
EVENTS = {
    "issues": ISSUES,
    "repositoryDiscussions": DISCUSSIONS,
    "commitComments": COMMIT_COMMENTS,
    "issueComments": ISSUE_COMMENTS,
    "repositoryDiscussionComments": DISCUSSION_COMMENTS,
}


def respond(request):
    """Return None for established fixture endpoints; never derive answers from the model."""
    path = request.url.path
    headers = {"Cache-Control": "no-store", "X-RateLimit-Remaining": "5000"}

    def response(value, *, next_page=None):
        result_headers = dict(headers)
        if next_page:
            result_headers["Link"] = f'<{request.url.copy_set_param("page", str(next_page))}>; rel="next"'
        if os.environ.get("CROSSFIELD_GITHUB_API_LOG"):
            with Path(os.environ["CROSSFIELD_GITHUB_API_LOG"]).open("a") as log:
                log.write(json.dumps({"path": path, "query": request.url.query.decode()}) + "\n")
        return httpx.Response(200, json=copy.deepcopy(value), headers=result_headers, request=request)

    def pages(rows):
        page = int(request.url.params.get("page", "1"))
        return response(rows[page - 1 : page], next_page=page + 1 if page < len(rows) else None)

    pieces = path.strip("/").split("/")
    if request.method == "GET":
        if path == "/orgs/public-org":
            return response(baseline.organization("public-org", 401))
        if len(pieces) == 3 and pieces[0] == "users" and pieces[2] == "orgs":
            return pages([{"login": name} for name in PUBLIC_ORGS.get(pieces[1], [])])
        if len(pieces) == 5 and pieces[:3] == ["orgs", "example", "teams"] and pieces[-1] == "repos":
            return pages([row for row in baseline.REPOSITORIES if row["name"] in TEAM_REPOS[pieces[3]]])
        if len(pieces) >= 4 and pieces[:2] == ["repos", "example"]:
            repo, endpoint = pieces[2:4]
            if endpoint == "comments" and len(pieces) == 4:
                rows = [
                    row for row in COMMIT_COMMENTS if row["repository"]["nameWithOwner"] == f"example/{repo}"
                ]
                return pages(
                    [
                        {
                            "id": row["databaseId"],
                            "node_id": row["id"],
                            "created_at": row["createdAt"],
                            "updated_at": row["updatedAt"],
                            "html_url": row["url"],
                            "body": row["body"],
                            "user": {"id": row["author"]["databaseId"], "login": row["author"]["login"]}
                            if row["author"]
                            else None,
                            "commit_id": row["commit"]["oid"],
                            "path": row["path"],
                            "position": row["position"],
                            "author_association": row["authorAssociation"],
                        }
                        for row in rows
                    ]
                )
            if endpoint == "collaborators":
                return pages([baseline.USERS[name] for name in COLLABORATORS[repo]])
            if endpoint == "teams":
                return pages([row for row in baseline.TEAMS["example"] if repo in TEAM_REPOS[row["slug"]]])
            if endpoint == "issues" and len(pieces) == 5 and pieces[-1].isdigit():
                row = next(
                    (
                        row
                        for row in ISSUES
                        if row["repository"]["nameWithOwner"] == f"example/{repo}"
                        and row["number"] == int(pieces[-1])
                    ),
                    None,
                )
                if row is None:
                    return httpx.Response(404, json={"message": "Not Found"}, request=request)
                return response(
                    {
                        "node_id": row["id"],
                        "number": row["number"],
                        "repository_url": f"https://api.github.com/repos/example/{repo}",
                        "assignee": None,
                    }
                )
            if endpoint == "issues" and pieces[-1] == "comments":
                rows = [
                    row
                    for row in ISSUE_COMMENTS
                    if row["repository"]["nameWithOwner"] == f"example/{repo}"
                    and (len(pieces) == 5 or row["number"] == int(pieces[4]))
                ]
                return pages(
                    [
                        {
                            "node_id": row["id"],
                            "created_at": row["createdAt"],
                            "updated_at": row["updatedAt"],
                            "html_url": row["url"],
                            "body": row["body"],
                            "user": baseline.USERS[row["author"]["login"]] if row["author"] else None,
                        }
                        for row in rows
                    ]
                )
        return None
    if request.method != "POST" or path != "/graphql":
        return None
    body = json.loads(request.content)
    operation = parse(body["query"]).definitions[0]
    variables = body.get("variables", {})

    def connection_path(selection, prefix=()):
        fields = [node for node in selection.selections if node.kind == "field"]
        if any(node.name.value == "nodes" for node in fields):
            return prefix
        for node in selection.selections:
            if node.selection_set:
                found = connection_path(
                    node.selection_set, prefix + (node,) if node.kind == "field" else prefix
                )
                if found:
                    return found
        return None

    nodes = connection_path(operation.selection_set)
    if not nodes:
        root = operation.selection_set.selections[0]
        if root.name.value == "node":
            identity = value_from_ast_untyped(root.arguments[0].value, variables)
            row = next((row for row in ISSUES if row["id"] == identity), None)
            if row:
                return response({"data": {"node": {**row, "__typename": "Issue"}}})
        if root.name.value == "repository":
            parent = root.selection_set.selections[0]
            if parent.name.value in {"issue", "discussion"}:
                repo = value_from_ast_untyped(
                    next(arg.value for arg in root.arguments if arg.name.value == "name"), variables
                )
                number = value_from_ast_untyped(parent.arguments[0].value, variables)
                rows = ISSUES if parent.name.value == "issue" else DISCUSSIONS
                row = next(
                    (
                        row
                        for row in rows
                        if row["number"] == number and row["repository"]["nameWithOwner"] == f"example/{repo}"
                    ),
                    None,
                )
                return response({"data": {"repository": {parent.name.value: row}}})
        return None
    names = [node.name.value for node in nodes]
    arguments = [
        {arg.name.value: value_from_ast_untyped(arg.value, variables) for arg in node.arguments}
        for node in nodes
    ]
    root, connection = names[0], names[-1]
    if root == "user" and connection in EVENTS and arguments[0]["login"] in PUBLIC_ORGS:
        login = arguments[0]["login"]
        rows = [row for row in EVENTS[connection] if row["author"] and row["author"]["login"] == login]
    elif root == "organization" and connection == "repositoryDiscussionComments":
        rows = DISCUSSION_COMMENTS if arguments[0]["login"] == "example" else []
    elif root == "node" and connection == "replies":
        rows = [
            row
            for row in DISCUSSION_COMMENTS
            if row["replyTo"] and row["replyTo"]["id"] == arguments[0]["id"]
        ]
    elif root == "repository":
        repo = arguments[0]["name"]
        if names == ["repository", "labels"]:
            return None
        if connection == "labels":
            number = arguments[1]["number"]
            label_names = (
                ["bug", "docs"]
                if names[1] == "pullRequest" and number == 1
                else ["bug"]
                if number == 2
                else []
            )
            rows = [
                {
                    "id": f"L-{repo}-{name}",
                    "name": name,
                    "color": "abcdef",
                    "description": None,
                    "isDefault": name == "bug",
                    "createdAt": None,
                    "updatedAt": None,
                    "url": f"https://github.example/labels/{name}",
                }
                for name in label_names
            ]
        elif names[1] == "label" and connection == "pullRequests":
            rows = [
                baseline.authored_pull(row, f"example/{repo}", 101 if repo == "alpha" else 102)
                for row in baseline.PULLS[repo]
                if any(label["name"] == arguments[1]["name"] for label in row["labels"])
            ]
        elif connection == "comments":
            rows = [
                row
                for row in DISCUSSION_COMMENTS
                if row["discussion"]["number"] == arguments[1]["number"]
                and row["discussion"]["repository"]["nameWithOwner"] == f"example/{repo}"
                and row["replyTo"] is None
            ]
        elif connection in {"issues", "discussions", "commitComments"}:
            rows = {"issues": ISSUES, "discussions": DISCUSSIONS, "commitComments": COMMIT_COMMENTS}[
                connection
            ]
            rows = [row for row in rows if row["repository"]["nameWithOwner"] == f"example/{repo}"]
            if names[1] == "label":
                rows = [row for row in rows if arguments[1]["name"] == "bug" and row["number"] in (1, 2)]
        else:
            return None
    else:
        return None
    offset = int(arguments[-1].get("after") or "0")
    more = offset + 1 < len(rows)
    payload = {
        "nodes": rows[offset : offset + 1],
        "pageInfo": {"hasNextPage": more, "endCursor": str(offset + 1) if more else None},
    }
    for name in reversed(names):
        payload = {name: payload}
    return response({"data": payload})
