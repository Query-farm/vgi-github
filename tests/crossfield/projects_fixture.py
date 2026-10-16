"""Independent Projects graph: owner scopes, typed values and paginated members.

Project and field numbers overlap across owners/projects. Four project item types
include a redacted item, and one issue appears in two projects as distinct items.
Every REST and GraphQL connection has one record per page.
"""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path

import connected_fixture as baseline
import httpx
from graphql import parse, value_from_ast_untyped

from vgi_github.generated_worker import main

STAMP = "2026-10-01T00:00:00Z"


def project(owner, number, identity, *, closed=False):
    account = baseline.user(owner, 100 if owner == "example" else 201)
    account["type"] = "Organization" if owner == "example" else "User"
    return {
        "id": identity,
        "node_id": f"PVT{identity}",
        "number": number,
        "owner": account,
        "creator": baseline.user("alice", 201),
        "title": f"{owner} project {number}",
        "description": None,
        "short_description": None,
        "public": True,
        "is_template": False,
        "state": "closed" if closed else "open",
        "closed_at": STAMP if closed else None,
        "created_at": STAMP,
        "updated_at": STAMP,
        "deleted_at": None,
        "deleted_by": None,
        "latest_status_update": None,
    }


PROJECTS = {
    "example": [project("example", 1, 1), project("example", 2, 2, closed=True)],
    "alice": [project("alice", 1, 3)],
    "empty-org": [],
}


def field(identity, name, kind, project_id):
    result = {
        "id": identity,
        "node_id": f"PVTF{project_id}-{identity}",
        "name": name,
        "data_type": kind,
        "project_url": f"https://api.github.example/projects/{project_id}",
        "created_at": STAMP,
        "updated_at": STAMP,
    }
    if kind == "single_select":
        result["options"] = [
            {
                "id": "done",
                "name": {"raw": "Done", "html": "Done"},
                "description": {"raw": "Finished", "html": "Finished"},
                "color": "GREEN",
            }
        ]
    if kind == "iteration":
        result["configuration"] = {
            "start_day": 1,
            "duration": 14,
            "iterations": [
                {
                    "id": "iter1",
                    "start_date": "2026-10-01",
                    "duration": 14,
                    "title": {"raw": "Sprint 1", "html": "Sprint 1"},
                    "completed": False,
                }
            ],
        }
    return result


FIELDS = {
    1: [
        field(identity, name, kind, 1)
        for identity, name, kind in [
            (10, "Status", "single_select"),
            (11, "Estimate", "number"),
            (12, "Due", "date"),
            (13, "Notes", "text"),
            (14, "Labels", "labels"),
            (15, "Assignees", "assignees"),
            (16, "Linked PRs", "linked_pull_requests"),
            (17, "Reviewers", "reviewers"),
            (18, "Iteration", "iteration"),
            (19, "Repository", "repository"),
        ]
    ],
    2: [field(10, "Unused", "text", 2)],
    3: [field(10, "Personal status", "single_select", 3)],
}


def graph_project(value):
    owner = value["owner"]
    return {
        "__typename": "ProjectV2",
        "id": value["node_id"],
        "number": value["number"],
        "owner": {
            "__typename": owner["type"],
            "id": owner["node_id"],
            "databaseId": owner["id"],
            "login": owner["login"],
        },
    }


def graph_field(project_id, identity):
    value = next(row for row in FIELDS[project_id] if row["id"] == identity)
    typ = {"single_select": "ProjectV2SingleSelectField", "iteration": "ProjectV2IterationField"}.get(
        value["data_type"], "ProjectV2Field"
    )
    return {
        "__typename": typ,
        "id": value["node_id"],
        "databaseId": identity,
        "name": value["name"],
        "dataType": value["data_type"].upper(),
    }


def value(kind, identity, project_id=1, **payload):
    return {
        "__typename": "ProjectV2ItemField" + kind + "Value",
        "field": graph_field(project_id, identity),
        **payload,
    }


def label(identity, name):
    return {
        "__typename": "Label",
        "id": identity,
        "name": name,
        "color": "abcdef",
        "description": None,
        "url": f"https://github.example/label/{name}",
    }


def user(identity, login):
    return {
        "__typename": "User",
        "id": identity,
        "login": login,
        "name": login.title(),
        "url": f"https://github.example/{login}",
    }


def pull(identity, number):
    return {
        "__typename": "PullRequest",
        "id": identity,
        "number": number,
        "title": f"PR {number}",
        "state": "OPEN",
        "url": f"https://github.example/pull/{number}",
        "repository": {"id": "REPO101", "nameWithOwner": "example/alpha"},
    }


VALUES = {
    "PVTI1": [
        value("SingleSelect", 10, optionId="done", name="Done", color="GREEN", description="Finished"),
        value("Number", 11, number=3.5),
        value("Date", 12, date="2026-11-01"),
        value("Text", 13, text="ship"),
        value("Label", 14, labels=[label("L1", "bug"), label("L2", "docs")]),
        value("User", 15, users=[user("USER201", "alice"), user("USER202", "bob")]),
        value("PullRequest", 16, pullRequests=[pull("PR1001", 1), pull("PR1002", 2)]),
        value(
            "Reviewer",
            17,
            reviewers=[
                user("USER201", "alice"),
                {"__typename": "Team", "id": "TEAM501", "slug": "core", "name": "Core"},
            ],
        ),
        value("Iteration", 18, iterationId="iter1", startDate="2026-10-01", duration=14, title="Sprint 1"),
        value(
            "Repository",
            19,
            repository={
                "__typename": "Repository",
                "id": "REPO101",
                "nameWithOwner": "example/alpha",
                "url": "https://github.example/example/alpha",
            },
        ),
    ],
    "PVTI2": [
        value("SingleSelect", 10, optionId="todo", name="Todo", color="GRAY", description=None),
        value("Number", 11, number=8.0),
        value("Label", 14, labels=[label("L1", "bug")]),
    ],
    "PVTI3": [value("Text", 13, text="draft")],
    "PVTI4": [],
    "PVTI5": [
        value(
            "SingleSelect",
            10,
            project_id=3,
            optionId="done",
            name="Done",
            color="GREEN",
            description="Finished",
        )
    ],
}


def item(identity, project_value, kind, *, archived=False):
    common = {
        "id": {"ISSUE": "ISSUE1", "PULL_REQUEST": "PR1001", "DRAFT_ISSUE": "DRAFT1"}.get(kind, ""),
        "title": "One issue in two projects",
        "body": "Independent issue body",
        "state": "OPEN",
        "number": 1,
        "url": "https://github.example/issue/1",
        "createdAt": STAMP,
        "updatedAt": STAMP,
        "repository": {"id": "REPO101", "nameWithOwner": "example/alpha"},
    }
    typename = {"ISSUE": "Issue", "PULL_REQUEST": "PullRequest", "DRAFT_ISSUE": "DraftIssue"}.get(kind)
    return {
        "__typename": "ProjectV2Item",
        "id": identity,
        "project": graph_project(project_value),
        "type": kind,
        "fullDatabaseId": str(1000 + int(identity.removeprefix("PVTI"))),
        "isArchived": archived,
        "creator": {"__typename": "User", "login": "alice", "databaseId": 201},
        "createdAt": STAMP,
        "updatedAt": STAMP,
        "content": {"__typename": typename, **common} if typename else None,
        "fieldValues": VALUES[identity],
    }


ITEMS = {
    "PVT1": [
        item("PVTI1", PROJECTS["example"][0], "ISSUE"),
        item("PVTI2", PROJECTS["example"][0], "PULL_REQUEST", archived=True),
        item("PVTI3", PROJECTS["example"][0], "DRAFT_ISSUE"),
        item("PVTI4", PROJECTS["example"][0], "REDACTED"),
    ],
    "PVT2": [],
    "PVT3": [item("PVTI5", PROJECTS["alice"][0], "ISSUE")],
}
CONNECTIONS = {"items", "fieldValues", "labels", "users", "pullRequests", "reviewers"}
VIEWS = {
    ("PVT1", 1): ["PVTI1", "PVTI2"],
    ("PVT1", 2): ["PVTI3", "PVTI4"],
    ("PVT2", 1): [],
    ("PVT3", 1): ["PVTI5"],
}


def rest_item(row):
    return {
        "id": int(row["fullDatabaseId"]),
        "node_id": row["id"],
        "content_type": {
            "ISSUE": "Issue",
            "PULL_REQUEST": "PullRequest",
            "DRAFT_ISSUE": "DraftIssue",
            "REDACTED": "Issue",
        }[row["type"]],
        # The pinned REST content/fields properties are unbounded objects. Public data comes from
        # the canonical GraphQL hydration, never by guessing properties from this fixture payload.
        "content": {"rest_only_title": "Do not reinterpret this property"} if row["content"] else None,
        "fields": [{"arbitrary_rest_value": "not a typed field definition"}],
        "project_url": "https://api.github.com/projects/" + row["project"]["id"],
        "created_at": row["createdAt"],
        "updated_at": row["updatedAt"],
        "archived_at": STAMP if row["isArchived"] else None,
    }


def respond(request):
    path = request.url.path
    headers = {"Cache-Control": "no-store", "X-RateLimit-Remaining": "5000"}

    def response(payload, status=200, next_cursor=None):
        outgoing = dict(headers)
        if next_cursor:
            outgoing["Link"] = f'<{request.url.copy_set_param("after", str(next_cursor))}>; rel="next"'
        if os.environ.get("CROSSFIELD_GITHUB_API_LOG"):
            with Path(os.environ["CROSSFIELD_GITHUB_API_LOG"]).open("a") as log:
                log.write(json.dumps({"path": path, "query": request.url.query.decode()}) + "\n")
        return httpx.Response(status, json=copy.deepcopy(payload), headers=outgoing, request=request)

    if request.method == "GET":
        parts = path.strip("/").split("/")
        if len(parts) < 3 or parts[0] not in {"orgs", "users"} or parts[2] != "projectsV2":
            return None
        owner = parts[1]
        if owner == "private-owner":
            return response({"message": "Projects access denied"}, 403)
        projects = PROJECTS.get(owner, [])
        if len(parts) == 3:
            index = int(request.url.params.get("after", "0"))
            return response(
                projects[index : index + 1], next_cursor=index + 1 if index + 1 < len(projects) else None
            )
        project_value = next((p for p in projects if p["number"] == int(parts[3])), None)
        if project_value is None:
            return response({"message": "No such project"}, 404)
        if len(parts) == 4:
            return response(project_value)
        if parts[4] == "fields":
            rows = FIELDS[project_value["id"]]
            if len(parts) == 6:
                row = next((row for row in rows if row["id"] == int(parts[5])), None)
                return response(row) if row else response({"message": "No such field"}, 404)
            index = int(request.url.params.get("after", "0"))
            return response(rows[index : index + 1], next_cursor=index + 1 if index + 1 < len(rows) else None)
        if parts[4] in {"items", "views"}:
            rows = ITEMS[project_value["node_id"]]
            if parts[4] == "views":
                view = VIEWS.get((project_value["node_id"], int(parts[5])))
                if view is None:
                    return response({"message": "No such project view"}, 404)
                rows = [row for row in rows if row["id"] in view]
            elif len(parts) == 6:
                row = next((row for row in rows if int(row["fullDatabaseId"]) == int(parts[5])), None)
                return response(rest_item(row)) if row else response({"message": "No such project item"}, 404)
            query = request.url.params.get("q")
            if query:
                kind = {"is:issue": "ISSUE", "is:pr": "PULL_REQUEST", "is:draft": "DRAFT_ISSUE"}.get(query)
                rows = [row for row in rows if row["type"] == kind]
            index = int(request.url.params.get("after", "0"))
            return response(
                [rest_item(row) for row in rows[index : index + 1]],
                next_cursor=index + 1 if index + 1 < len(rows) else None,
            )
        return response({"message": "Unexpected Projects REST route"}, 404)
    if request.method != "POST" or path != "/graphql":
        return None
    body = json.loads(request.content)
    operation = parse(body["query"]).definitions[0]
    root = operation.selection_set.selections[0]
    variables = body.get("variables", {})
    arguments = {arg.name.value: value_from_ast_untyped(arg.value, variables) for arg in root.arguments}
    identity = arguments.get("id", "")
    if root.name.value != "node" or not identity.startswith("PVT"):
        return None
    node = next((row for rows in ITEMS.values() for row in rows if row["id"] == identity), None)
    for projects in PROJECTS.values():
        for project_value in projects:
            if project_value["node_id"] == identity:
                node = {**graph_project(project_value), "items": ITEMS[identity]}
    if identity == "PVTI-LATE":
        node = {**ITEMS["PVT1"][0], "id": identity}
        if any(value == "1" for key, value in variables.items() if "cursor" in key):
            return response({"message": "Later project field page unavailable"}, 503)

    def render(raw, selection):
        if raw is None:
            return None
        if isinstance(raw, list):
            return [render(value, selection) for value in raw]
        result = {}
        for field_node in selection.selections:
            if field_node.kind == "inline_fragment":
                if (
                    not field_node.type_condition
                    or raw.get("__typename") == field_node.type_condition.name.value
                ):
                    result.update(render(raw, field_node.selection_set))
                continue
            name = field_node.name.value
            args = {
                arg.name.value: value_from_ast_untyped(arg.value, variables) for arg in field_node.arguments
            }
            value = raw.get(name)
            if name == "fieldValueByName":
                value = next(
                    (row for row in raw["fieldValues"] if row["field"]["name"] == args["name"]), None
                )
            elif name in CONNECTIONS:
                rows = value or []
                offset = int(args.get("after") or "0")
                more = offset + 1 < len(rows)
                value = {
                    "nodes": rows[offset : offset + 1],
                    "totalCount": len(rows),
                    "pageInfo": {"hasNextPage": more, "endCursor": str(offset + 1) if more else None},
                }
            result[field_node.alias.value if field_node.alias else name] = (
                render(value, field_node.selection_set) if field_node.selection_set else value
            )
        return result

    return response({"data": {"node": render(node, root.selection_set)}})


def respond_all(request):
    value = respond(request)
    return value if value is not None else baseline.respond(request)


baseline.api.open_client = lambda: httpx.Client(
    transport=httpx.MockTransport(respond_all), follow_redirects=True
)
if __name__ == "__main__":
    main()
