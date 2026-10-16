"""Independent issue graph with cross-repository parent/dependency edges and mixed timelines."""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path

import httpx
from graphql import parse, value_from_ast_untyped

from vgi_github import github_api as api
from vgi_github.generated_worker import main


def actor(identity, login):
    return {
        "id": identity,
        "node_id": f"U{identity}",
        "login": login,
        "type": "User",
        "html_url": f"https://github.com/{login}",
        "name": login,
        "created_at": "2020-01-01T00:00:00Z",
        "followers": 0,
        "public_repos": 0,
        "location": None,
        "bio": None,
        "company": None,
    }


ALICE, BOB = actor(1201, "issue-author"), actor(1202, "issue-bob")
REPOSITORIES = [
    {
        "id": i,
        "node_id": f"R{i}",
        "full_name": f"issue-fixture/{name}",
        "name": name,
        "owner": {"id": 1100, "login": "issue-fixture", "type": "Organization"},
        "private": False,
        "description": "Issue graph fixture",
        "topics": [],
        "language": "Python",
    }
    for i, name in [(1101, "alpha"), (1102, "beta"), (1103, "empty")]
]
REPOS = {r["name"]: r for r in REPOSITORIES}
LABELS = [
    {
        "id": n,
        "node_id": f"L{n}",
        "name": name,
        "color": color,
        "description": name + " label",
        "default": False,
        "url": f"https://api.github.com/repos/issue-fixture/alpha/labels/{name}",
    }
    for n, name, color in [(11, "bug", "ff0000"), (12, "triage", "00ff00")]
]


def issue(repo, number, identity, author, state="open", pull=False):
    value = {
        "id": identity,
        "node_id": ("PR" if pull else "I") + str(identity),
        "number": number,
        "title": "fix: fixture" if number == 1 else "docs: fixture",
        "body": "Independent issue evidence",
        "state": state,
        "created_at": "2026-09-01T00:00:00Z",
        "updated_at": "2026-09-03T00:00:00Z",
        "closed_at": "2026-09-02T00:00:00Z" if state == "closed" else None,
        "user": author,
        "repository_url": f"https://api.github.com/repos/issue-fixture/{repo}",
        "html_url": f"https://github.com/issue-fixture/{repo}/issues/{number}",
        "url": f"https://api.github.com/repos/issue-fixture/{repo}/issues/{number}",
        "assignees": [ALICE, BOB] if number == 1 else [BOB],
        "labels": LABELS if number == 1 else [],
        "comments": 1,
        "locked": state == "closed",
        "milestone": None,
        "assignee": ALICE if number == 1 else BOB,
        "labels_url": "https://example.com/labels",
        "comments_url": "https://example.com/comments",
        "events_url": "https://example.com/events",
        "state_reason": "not_planned" if state == "closed" else None,
        "active_lock_reason": "resolved" if state == "closed" else None,
        "author_association": "MEMBER" if author["id"] == 1202 else "CONTRIBUTOR",
        "closed_by": ALICE if state == "closed" else None,
        "type": {
            "id": 8101,
            "node_id": "IT8101",
            "name": "Bug",
            "description": "Defect",
            "color": "red",
            "is_enabled": True,
            "created_at": "2026-01-01T00:00:00Z",
            "updated_at": "2026-09-01T00:00:00Z",
        }
        if identity == 2101
        else None,
        "reactions": {
            "url": f"https://api.github.com/repos/issue-fixture/{repo}/issues/{number}/reactions",
            "total_count": 5 if identity == 2101 else 1 if identity == 2102 else 0,
            "+1": 3 if identity == 2101 else 0,
            "-1": 1 if identity == 2102 else 0,
            "heart": 2 if identity == 2101 else 0,
            "laugh": 0,
            "confused": 0,
            "hooray": 0,
            "eyes": 0,
            "rocket": 0,
        },
        "issue_dependencies_summary": {
            "blocked_by": 1 if identity == 2102 else 0,
            "blocking": 1 if identity == 2103 else 0,
            "total_blocked_by": 1 if identity == 2102 else 0,
            "total_blocking": 1 if identity == 2103 else 0,
        },
        "performed_via_github_app": {
            "id": 8201,
            "node_id": "APP8201",
            "slug": "issue-automation",
            "name": "Issue Automation",
            "html_url": "https://github.com/apps/issue-automation",
        }
        if identity == 2101
        else None,
    }
    if pull:
        # A nullable URL inside the PR object must still exclude this record from canonical issues.
        value["pull_request"] = {"url": None, "html_url": None, "diff_url": None, "patch_url": None}
    return value


I1, I2, I3, PR = (
    issue("alpha", 1, 2101, ALICE),
    issue("alpha", 2, 2102, BOB, "closed"),
    issue("beta", 1, 2103, ALICE),
    issue("alpha", 3, 2104, BOB, pull=True),
)
ISSUES = {"alpha": [I1, I2, PR], "beta": [I3], "empty": []}
BY_NODE = {r["node_id"]: r for rs in ISSUES.values() for r in rs}
GRAPHQL_STATE_REASONS = {2101: None, 2102: "NOT_PLANNED", 2103: None, 2104: None}


def graphql_issue(row):
    repo = row["repository_url"].rsplit("/", 1)[1]
    milestone = row["milestone"]
    return {
        "__typename": "Issue",
        "id": row["node_id"],
        "number": row["number"],
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
        "url": row["html_url"],
        "body": row["body"],
        "title": row["title"],
        "state": row["state"].upper(),
        "closedAt": row["closed_at"],
        "fullDatabaseId": str(row["id"]),
        "stateReason": GRAPHQL_STATE_REASONS[row["id"]],
        "bodyHTML": "<p>Independent issue evidence</p>",
        "bodyText": "Independent issue evidence",
        "closed": row["state"] == "closed",
        "locked": row["locked"],
        "activeLockReason": row["active_lock_reason"].upper() if row["active_lock_reason"] else None,
        "authorAssociation": row["author_association"],
        "createdViaEmail": False,
        "lastEditedAt": "2026-09-03T00:00:00Z" if row["id"] == 2101 else None,
        "publishedAt": row["created_at"],
        "isPinned": True if row["id"] == 2101 else False if row["id"] == 2102 else None,
        "subIssuesSummary": {
            "total": 1 if row["id"] == 2103 else 0,
            "completed": 1 if row["id"] == 2103 else 0,
            "percentCompleted": 100 if row["id"] == 2103 else 0,
        },
        "milestone": {
            "id": milestone["node_id"],
            "number": milestone["number"],
            "title": milestone["title"],
            "description": milestone["description"],
            "state": milestone["state"].upper(),
            "closed": milestone["state"] == "closed",
            "createdAt": milestone["created_at"],
            "updatedAt": milestone["updated_at"],
            "closedAt": milestone["closed_at"],
            "dueOn": milestone["due_on"],
            "url": milestone["html_url"],
            "progressPercentage": 60.0,
        }
        if milestone
        else None,
        "repository": {
            "id": REPOS[repo]["node_id"],
            "nameWithOwner": "issue-fixture/" + repo,
            "primaryLanguage": {"name": "Python"},
        },
        "author": {"__typename": "User", "login": row["user"]["login"], "databaseId": row["user"]["id"]},
    }


def graphql_label(row):
    return {
        "__typename": "Label",
        "id": row["node_id"],
        "name": row["name"],
        "color": row["color"],
        "description": row["description"],
        "isDefault": row["default"],
        "createdAt": "2026-01-01T00:00:00Z",
        "updatedAt": "2026-09-01T00:00:00Z",
        "url": row["url"],
    }


COMMENTS = [
    {
        "id": i,
        "node_id": f"C{i}",
        "body": body,
        "user": author,
        "created_at": "2026-09-01T12:00:00Z",
        "updated_at": "2026-09-02T00:00:00Z",
        "html_url": f"https://github.com/issue-fixture/alpha/issues/{number}#issuecomment-{i}",
        "url": f"https://api.github.com/repos/issue-fixture/alpha/issues/comments/{i}",
        "issue_url": f"https://api.github.com/repos/issue-fixture/alpha/issues/{number}",
        "author_association": "CONTRIBUTOR",
    }
    for i, body, author, number in [(501, "First comment", ALICE, 1), (502, "PR conversation", BOB, 3)]
]


def event(identity, name, row, actor_value):
    return {
        "id": identity,
        "node_id": f"E{identity}",
        "url": f"https://api.github.com/repos/issue-fixture/alpha/issues/events/{identity}",
        "actor": actor_value,
        "event": name,
        "commit_id": None,
        "commit_url": None,
        "created_at": "2026-09-02T00:00:00Z",
        "issue": row,
        "performed_via_github_app": None,
    }


EVENTS = [event(301, "labeled", I1, BOB), event(302, "assigned", I2, ALICE)]
EVENTS[0]["label"] = {"name": "bug", "color": "ff0000"}
EVENTS[1].update(assignee=BOB, assigner=ALICE)
COMMIT_EVENT = {
    "event": "committed",
    "sha": "c" * 40,
    "node_id": "COMMIT_C",
    "url": "https://api.github.com/repos/issue-fixture/alpha/commits/" + "c" * 40,
    "html_url": "https://github.com/issue-fixture/alpha/commit/" + "c" * 40,
    "author": {"name": "Original author", "email": "author@example.com", "date": "2026-09-01T00:00:00Z"},
    "committer": {"name": "Integrator", "email": "committer@example.com", "date": "2026-09-02T00:00:00Z"},
    "tree": {"sha": "d" * 40, "url": "https://example.com/tree"},
    "message": "Fix issue",
    "parents": [],
    "verification": {
        "verified": False,
        "reason": "unsigned",
        "signature": None,
        "payload": None,
        "verified_at": None,
    },
}
TIMELINE = [
    EVENTS[0],
    {**COMMENTS[0], "event": "commented", "actor": ALICE},
    COMMIT_EVENT,
    event(303, "closed", I1, BOB),
]
FIELD_VALUES = [
    {
        "issue_field_id": 1,
        "node_id": "FV1",
        "issue_field_name": "Effort",
        "data_type": "number",
        "value": 3.5,
    },
    {
        "issue_field_id": 2,
        "node_id": "FV2",
        "issue_field_name": "Components",
        "data_type": "multi_select",
        "value": None,
        "multi_select_options": [
            {"id": 11, "name": "Parser", "color": "blue"},
            {"id": 12, "name": "API", "color": "red"},
        ],
    },
]
SUGGESTIONS = [
    {
        "id": identity,
        "issue_id": 2101,
        "action": action,
        "state": state,
        "target_id": target,
        "target_value": value,
        "rationale": "Fixture suggestion",
        "confidence": "HIGH",
        "actor_id": 1301,
        "issue_event_id": 301 if state == "applied" else None,
        "resolved_by": 1202 if state != "pending" else None,
        "created_at": "2026-09-01T00:00:00Z",
        "updated_at": "2026-09-02T00:00:00Z",
    }
    for identity, action, state, target, value in [
        (701, "add_label", "pending", 11, "bug"),
        (702, "add_field", "applied", 1, True),
        (703, "add_field", "dismissed", 2, ["Parser", "API"]),
    ]
]
MILESTONES = [
    {
        "id": identity,
        "node_id": f"M{identity}",
        "number": number,
        "title": "Milestone " + str(number),
        "state": state,
        "description": "Fixture milestone",
        "creator": ALICE,
        "open_issues": opened,
        "closed_issues": closed,
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-09-01T00:00:00Z",
        "closed_at": "2026-09-01T00:00:00Z" if state == "closed" else None,
        "due_on": "2026-10-01T00:00:00Z",
        "url": f"https://api.github.com/repos/issue-fixture/alpha/milestones/{number}",
        "html_url": f"https://github.com/issue-fixture/alpha/milestone/{number}",
        "labels_url": f"https://api.github.com/repos/issue-fixture/alpha/milestones/{number}/labels",
    }
    for identity, number, state, opened, closed in [(401, 1, "open", 2, 3), (402, 2, "closed", 0, 4)]
]


I1["milestone"] = MILESTONES[0]
I2["parent_issue_url"] = I3["url"]


def respond(request):
    path = request.url.path
    graphql_body = json.loads(request.content) if path == "/graphql" else None
    if graphql_body is not None:
        variables = graphql_body.get("variables", {})
        if not any(
            str(v).startswith(("issue-fixture", "issue-author", "I210", "L11", "L12"))
            for v in variables.values()
        ):
            return None
    elif not (
        path.startswith("/repos/issue-fixture/")
        or path.startswith("/orgs/issue-fixture")
        or path in {"/users/issue-fixture", "/users/issue-author", "/issues", "/user/issues"}
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

    def listing(rows):
        page = int(request.url.params.get("page", "1"))
        extra = (
            {"Link": f'<{request.url.copy_set_param("page", str(page + 1))}>; rel="next"'}
            if page < len(rows)
            else {}
        )
        return response(rows[page - 1 : page], extra=extra)

    def selected_issues(rows):
        state = request.url.params.get("state", "open")
        if state != "all":
            rows = [r for r in rows if r["state"] == state]
        if request.url.params.get("creator"):
            rows = [r for r in rows if r["user"]["login"] == request.url.params["creator"]]
        if request.url.params.get("assignee"):
            rows = [
                r for r in rows if any(a["login"] == request.url.params["assignee"] for a in r["assignees"])
            ]
        return rows

    if graphql_body is not None:
        root = parse(graphql_body["query"]).definitions[0].selection_set.selections[0]
        rootargs = {a.name.value: value_from_ast_untyped(a.value, variables) for a in root.arguments}
        if root.name.value == "node":
            identity = rootargs["id"]
            node = (
                graphql_issue(BY_NODE[identity])
                if identity.startswith("I")
                else graphql_label(next(r for r in LABELS if r["node_id"] == identity))
            )
            return response({"data": {"node": node}})
        if root.name.value == "user":
            connection = next(f for f in root.selection_set.selections if f.name.value == "issues")
            rows = [graphql_issue(I1), graphql_issue(I3)]
            key = "user"
        else:
            repo = rootargs["name"]
            connection = next(
                f
                for f in root.selection_set.selections
                if getattr(f, "name", None) and f.name.value in ["issues", "issue", "labels", "label"]
            )
            if connection.name.value == "issue":
                a = {v.name.value: value_from_ast_untyped(v.value, variables) for v in connection.arguments}
                row = next(r for r in ISSUES[repo] if r["number"] == a["number"])
                result = graphql_issue(row)
                result["labels"] = {
                    "totalCount": len(row["labels"]),
                    "nodes": [graphql_label(v) for v in row["labels"]],
                    "pageInfo": {"hasNextPage": False, "endCursor": None},
                }
                return response({"data": {"repository": {"issue": result}}})
            rows = (
                [graphql_issue(r) for r in ISSUES[repo] if "pull_request" not in r]
                if connection.name.value == "issues"
                else [graphql_label(r) for r in LABELS]
                if repo == "alpha"
                else []
            )
            key = "repository"
        ca = {a.name.value: value_from_ast_untyped(a.value, variables) for a in connection.arguments}
        offset = int(ca.get("after") or 0)
        return response(
            {
                "data": {
                    key: {
                        connection.name.value: {
                            "nodes": rows[offset : offset + 1],
                            "pageInfo": {
                                "hasNextPage": offset + 1 < len(rows),
                                "endCursor": str(offset + 1) if offset + 1 < len(rows) else None,
                            },
                        }
                    }
                }
            }
        )
    if path == "/users/issue-author":
        return response(ALICE)
    if path == "/users/issue-fixture":
        return response({"id": 1100, "login": "issue-fixture", "type": "Organization"})
    if path == "/orgs/issue-fixture/repos":
        return listing(REPOSITORIES)
    if path in ["/issues", "/user/issues", "/orgs/issue-fixture/issues"]:
        rows = [I1, I2, I3, PR] if path == "/issues" else [I1, PR] if path == "/user/issues" else [I2]
        return listing(selected_issues(rows))
    parts = path.split("/")
    repo = parts[3]
    suffix = "/".join(parts[4:])
    if not suffix:
        return response(REPOS[repo])
    if suffix == "issues":
        return listing(selected_issues(ISSUES[repo]))
    if suffix == "issues/comments":
        return listing(COMMENTS if repo == "alpha" else [])
    if suffix.startswith("issues/comments/"):
        return response(next(r for r in COMMENTS if r["id"] == int(parts[-1])))
    if suffix == "issues/events":
        return listing(EVENTS if repo == "alpha" else [])
    if suffix.startswith("issues/events/"):
        return response(next(r for r in EVENTS if r["id"] == int(parts[-1])))
    if suffix.startswith("issues/"):
        number = int(parts[5])
        row = next(r for r in ISSUES[repo] if r["number"] == number)
        tail = "/".join(parts[6:])
        if not tail:
            return response(row)
        if tail == "parent":
            return response(I3) if row is I2 else response({"message": "No parent"}, 404)
        if tail in ["sub_issues", "dependencies/blocking"]:
            return listing([I2] if row is I3 else [])
        if tail == "dependencies/blocked_by":
            return listing([I3] if row is I2 else [])
        if tail == "relates_to":
            return listing([I3] if row is I1 else [I1] if row is I3 else [])
        if tail == "comments":
            return listing([r for r in COMMENTS if r["issue_url"] == row["url"]])
        if tail == "events":
            return listing([r for r in EVENTS if r["issue"]["node_id"] == row["node_id"]])
        if tail == "timeline":
            return listing(TIMELINE if row is I1 else [])
        if tail == "issue-field-values":
            return listing(FIELD_VALUES if row is I1 else [])
        if tail == "suggestions":
            rows = SUGGESTIONS if row is I1 else []
            state = request.url.params.get("state", "pending")
            if state != "all":
                rows = [r for r in rows if r["state"] == state]
            if request.url.params.get("action"):
                rows = [r for r in rows if r["action"] == request.url.params["action"]]
            return listing(rows)
        if tail == "labels":
            return listing(row["labels"])
        if tail.startswith("assignees/"):
            return httpx.Response(204 if parts[-1] == "issue-author" else 404, request=request)
    if suffix == "assignees":
        return listing([ALICE, BOB] if repo == "alpha" else [])
    if suffix.startswith("assignees/"):
        return httpx.Response(204 if parts[-1] == "issue-author" else 404, request=request)
    if suffix == "labels":
        return listing(LABELS if repo == "alpha" else [])
    if suffix.startswith("labels/"):
        return response(next(r for r in LABELS if r["name"] == parts[-1]))
    if suffix == "milestones":
        rows = MILESTONES if repo == "alpha" else []
        state = request.url.params.get("state", "open")
        return listing(rows if state == "all" else [r for r in rows if r["state"] == state])
    if suffix.startswith("milestones/"):
        if parts[-1] == "labels":
            return listing(LABELS[:1])
        return response(next(r for r in MILESTONES if r["number"] == int(parts[-1])))
    raise AssertionError(f"Unexpected issue fixture request: {request.url}")


if __name__ == "__main__":
    api.open_client = lambda: httpx.Client(transport=httpx.MockTransport(respond), follow_redirects=True)
    main()
