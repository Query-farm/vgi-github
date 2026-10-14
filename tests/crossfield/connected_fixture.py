"""Independent graph for connected semantic queries; HTTP never leaves this process.

Three repositories: alpha has 3 PRs (two merged in 48/12 hours), beta has
one PR (merged in 6 hours), empty has none. PR numbers overlap across repos.
Four reviews belong to three PRs; adding reviews must never multiply PR counts.
Organization members are alice and carol; PR author bob is a nonmember.
Two nonempty teams overlap on alice and a third team is empty. Alice authored
a fourth PR in another owner's repository; user scope must include it.
"""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path

import httpx
from graphql import parse, value_from_ast_untyped

from vgi_github import github_api as api
from vgi_github.generated_worker import main


def user(login, identity):
    value = {
        "login": login,
        "id": identity,
        "node_id": f"U{identity}",
        "gravatar_id": None,
        "type": "User",
        "site_admin": False,
        "name": login.title(),
        "company": None,
        "location": None,
        "email": None,
        "bio": None,
        "public_repos": 0,
        "followers": 2,
        "following": 1,
        "created_at": "2020-01-01T00:00:00Z",
        "updated_at": "2026-09-01T00:00:00Z",
    }
    for name in (
        "avatar_url",
        "url",
        "html_url",
        "followers_url",
        "following_url",
        "gists_url",
        "starred_url",
        "subscriptions_url",
        "organizations_url",
        "repos_url",
        "events_url",
        "received_events_url",
    ):
        value[name] = f"https://github.example/{login}/{name}"
    return value


def repository(name, identity):
    return {
        "id": identity,
        "node_id": f"REPO{identity}",
        "name": name,
        "full_name": f"example/{name}",
        "owner": {**user("example", 100), "type": "Organization"},
        "private": name == "beta",
        "archived": False,
        "fork": False,
        "description": "Independent fixture repository",
        "default_branch": "main",
        "html_url": f"https://github.example/example/{name}",
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-09-05T00:00:00Z",
        "topics": {"alpha": ["duckdb", "analytics"], "beta": ["analytics"]}.get(name, []),
    }


def pull(number, identity, author, created, merged):
    return {
        "id": identity,
        "node_id": f"PR{identity}",
        "number": number,
        "user": user(author, 201 if author == "alice" else 202),
        "title": f"Change {identity}",
        "body": "Independent pull request",
        "state": "closed" if merged else "open",
        "draft": False,
        "created_at": created,
        "merged_at": merged,
        "closed_at": merged,
        "updated_at": "2026-09-05T00:00:00Z",
        "html_url": f"https://github.example/pull/{identity}",
        "labels": {
            1001: [{"id": 501, "name": "bug"}, {"id": 502, "name": "docs"}],
            1002: [{"id": 501, "name": "bug"}],
            2001: [{"id": 601, "name": "bug"}],
        }.get(identity, []),
        "assignees": {
            1001: [user("alice", 201), user("bob", 202)],
            1002: [user("bob", 202)],
            2001: [user("carol", 203)],
        }.get(identity, []),
    }


REPOSITORIES = [repository("alpha", 101), repository("beta", 102), repository("empty", 103)]
PULLS = {
    "alpha": [
        pull(1, 1001, "alice", "2026-09-01T00:00:00Z", "2026-09-03T00:00:00Z"),
        pull(2, 1002, "bob", "2026-09-02T00:00:00Z", "2026-09-02T12:00:00Z"),
        pull(3, 1003, "alice", "2026-09-04T00:00:00Z", None),
    ],
    "beta": [pull(1, 2001, "alice", "2026-09-03T00:00:00Z", "2026-09-03T06:00:00Z")],
    "empty": [],
}


def review(identity, state, reviewer):
    return {
        "id": identity,
        "node_id": f"R{identity}",
        "state": state,
        "user": user(reviewer, {"alice": 201, "bob": 202, "carol": 203}[reviewer]),
        "body": "Independent review",
        "submitted_at": "2026-09-03T01:00:00Z",
        "commit_id": "abc123",
        "author_association": "CONTRIBUTOR",
        "html_url": f"https://github.example/reviews/{identity}",
        "pull_request_url": "https://github.example/pull",
        "_links": {
            "html": {"href": "https://github.example/review"},
            "pull_request": {"href": "https://github.example/pull"},
        },
    }


REVIEWS = {
    ("alpha", 1): [review(11, "APPROVED", "bob"), review(12, "COMMENTED", "alice")],
    ("alpha", 2): [review(13, "APPROVED", "bob")],
    ("beta", 1): [review(21, "COMMENTED", "carol")],
}


def organization(login, identity):
    return {
        **user(login, identity),
        "type": "Organization",
        "description": f"Independent {login} organization",
        "blog": "https://github.example",
        "is_verified": False,
        "has_organization_projects": True,
        "has_repository_projects": True,
        "public_gists": 0,
        "public_repos": 3 if login == "example" else 0,
    }


def team(slug, identity):
    return {
        "id": identity,
        "node_id": f"TEAM{identity}",
        "name": slug.title(),
        "slug": slug,
        "description": f"Independent {slug} team",
        "privacy": "closed",
        "type": "organization",
        "permission": "pull",
        "url": f"https://api.github.com/teams/{identity}",
        "html_url": f"https://github.example/orgs/example/teams/{slug}",
        "members_url": f"https://api.github.com/teams/{identity}/members{{/member}}",
        "repositories_url": f"https://api.github.com/teams/{identity}/repos",
        "parent": None,
        "organization": organization("example", 100),
        "members_count": {"core": 2, "docs": 1, "empty": 0}[slug],
        "repos_count": 0,
        "created_at": "2021-01-01T00:00:00Z",
        "updated_at": "2026-09-01T00:00:00Z",
    }


USERS = {
    login: user(login, identity)
    for login, identity in [
        ("alice", 201),
        ("bob", 202),
        ("carol", 203),
        ("empty-user", 204),
        ("wrong-author", 205),
        ("null-author", 206),
    ]
}
ORGANIZATIONS = {"example": organization("example", 100), "empty-org": organization("empty-org", 400)}
ORGANIZATION_MEMBERS = {"example": [USERS["alice"], USERS["carol"]], "empty-org": []}
TEAMS = {"example": [team("core", 501), team("docs", 502), team("empty", 503)], "empty-org": []}
TEAM_MEMBERS = {"core": [USERS["alice"], USERS["carol"]], "docs": [USERS["alice"]], "empty": []}


def authored_pull(row, repo_name, repo_id):
    return {
        "id": row["node_id"],
        "databaseId": row["id"],
        "number": row["number"],
        "title": row["title"],
        "body": row["body"],
        "state": "MERGED" if row["merged_at"] else "OPEN",
        "isDraft": row["draft"],
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
        "closedAt": row["closed_at"],
        "mergedAt": row["merged_at"],
        "merged": bool(row["merged_at"]),
        "url": row["html_url"],
        "author": {
            "login": row["user"]["login"],
            "id": row["user"]["node_id"],
            "databaseId": row["user"]["id"],
        },
        "repository": {
            "id": f"REPO{repo_id}",
            "databaseId": repo_id,
            "name": repo_name.split("/")[1],
            "nameWithOwner": repo_name,
            "primaryLanguage": None,
            "owner": {"login": repo_name.split("/")[0]},
        },
    }


AUTHORED_PULLS = {
    "alice": [
        authored_pull(PULLS["alpha"][0], "example/alpha", 101),
        authored_pull(PULLS["alpha"][2], "example/alpha", 101),
        authored_pull(PULLS["beta"][0], "example/beta", 102),
        authored_pull(
            pull(1, 3001, "alice", "2026-09-06T18:00:00Z", "2026-09-07T12:00:00Z"), "other/project", 301
        ),
    ],
    "bob": [authored_pull(PULLS["alpha"][1], "example/alpha", 101)],
    "carol": [],
    "empty-user": [],
}

# The associated-PR endpoint is not itself proof of authorship. A valid first
# page followed by an unverifiable author must fail, never silently drop a row.
for account in ("wrong-author", "null-author"):
    rows = copy.deepcopy(AUTHORED_PULLS["alice"][:2])
    rows[0]["author"]["login"] = account
    if account == "null-author":
        rows[1]["author"] = None
    AUTHORED_PULLS[account] = rows


def respond(request):
    if os.environ.get("CROSSFIELD_GITHUB_API_LOG"):
        with Path(os.environ["CROSSFIELD_GITHUB_API_LOG"]).open("a") as log:
            log.write(json.dumps({"path": request.url.path, "query": str(request.url.params)}) + "\n")
    headers = {"Cache-Control": "no-store", "X-RateLimit-Remaining": "5000"}

    def result(value, status=200):
        return httpx.Response(status, json=value, headers=headers, request=request)

    def pages(rows):
        page = int(request.url.params.get("page", "1"))
        if page < len(rows):
            headers["Link"] = f'<{request.url.copy_set_param("page", str(page + 1))}>; rel="next"'
        return result(rows[page - 1 : page])

    path = request.url.path
    if request.method == "GET":
        if path.startswith("/users/") and path.count("/") == 2 and path.split("/")[-1] in USERS:
            return result(copy.deepcopy(USERS[path.split("/")[-1]]))
        if path == "/users/empty-org":
            return result(copy.deepcopy(ORGANIZATIONS["empty-org"]))
        if path in {"/users/example", "/users/public-user"}:
            return result(
                {
                    **user(path.split("/")[-1], 100),
                    "type": "Organization" if path == "/users/example" else "User",
                }
            )
        if path == "/orgs/example/repos":
            return pages(copy.deepcopy(REPOSITORIES))
        if path == "/users/public-user/repos":
            row = copy.deepcopy(REPOSITORIES[0])
            row["full_name"] = "public-user/alpha"
            row["owner"] = user("public-user", 100)
            return pages([row])
        pieces = path.strip("/").split("/")
        if len(pieces) >= 2 and pieces[0] == "orgs" and pieces[1] in ORGANIZATIONS:
            org = pieces[1]
            if len(pieces) == 2:
                return result(copy.deepcopy(ORGANIZATIONS[org]))
            if len(pieces) == 3 and pieces[2] == "members":
                return pages(copy.deepcopy(ORGANIZATION_MEMBERS[org]))
            if len(pieces) == 3 and pieces[2] == "teams":
                return pages(copy.deepcopy(TEAMS[org]))
            if len(pieces) == 3 and pieces[2] == "repos" and org == "empty-org":
                return pages([])
            if len(pieces) >= 4 and pieces[2] == "teams":
                slug = pieces[3]
                found = next((row for row in TEAMS[org] if row["slug"] == slug), None)
                if found is None:
                    return result({"message": "Not Found"}, 404)
                if len(pieces) == 4:
                    return result(copy.deepcopy(found))
                if len(pieces) == 5 and pieces[4] == "members":
                    return pages(copy.deepcopy(TEAM_MEMBERS[slug]))
        if len(pieces) >= 3 and pieces[:2] == ["repos", "example"]:
            name = pieces[2]
            if name == "missing":
                return result({"message": "Not Found"}, 404)
            mode = name if name in {"duplicate", "late-error", "bad-type"} else ""
            actual = "alpha" if mode else name
            if len(pieces) == 3:
                row = next((copy.deepcopy(r) for r in REPOSITORIES if r["name"] == actual), None)
                if row is not None:
                    row["full_name"] = f"example/{name}"
                    return result(row)
            if len(pieces) == 4 and pieces[3] == "pulls":
                assert request.url.params.get("state") == "all", "PR enumeration must include all states"
                rows = copy.deepcopy(PULLS.get(actual, []))
                if mode == "duplicate":
                    rows[1] = rows[0]
                if mode == "bad-type":
                    rows[1]["id"] = "wrong-type"
                if mode == "late-error" and request.url.params.get("page") == "2":
                    return result({"message": "Second PR page denied"}, 403)
                return pages(rows)
            if len(pieces) >= 5 and pieces[3] == "pulls":
                number = int(pieces[4])
                if len(pieces) == 5:
                    row = next((p for p in PULLS.get(actual, []) if p["number"] == number), None)
                    return result(copy.deepcopy(row)) if row else result({"message": "Not Found"}, 404)
                if len(pieces) == 6 and pieces[5] == "reviews":
                    return pages(copy.deepcopy(REVIEWS.get((actual, number), [])))
        return result({"message": "Not Found"}, 404)

    if request.method == "POST" and path == "/graphql":
        body = json.loads(request.content)
        operation = parse(body["query"]).definitions[0]
        root = operation.selection_set.selections[0]
        variables = body.get("variables", {})
        args = {arg.name.value: value_from_ast_untyped(arg.value, variables) for arg in root.arguments}
        connection = next(
            field for field in root.selection_set.selections if field.name.value in {"labels", "pullRequests"}
        )
        conn_args = {
            arg.name.value: value_from_ast_untyped(arg.value, variables) for arg in connection.arguments
        }
        if root.name.value == "user" and connection.name.value == "pullRequests":
            rows = AUTHORED_PULLS[args["login"]]
            offset = int(conn_args.get("after") or "0")
            more = offset + 1 < len(rows)
            return result(
                {
                    "data": {
                        "user": {
                            "pullRequests": {
                                "nodes": copy.deepcopy(rows[offset : offset + 1]),
                                "pageInfo": {
                                    "hasNextPage": more,
                                    "endCursor": str(offset + 1) if more else None,
                                },
                            }
                        }
                    }
                }
            )
        assert root.name.value == "repository" and connection.name.value == "labels"
        names = {"alpha": ["bug", "feature"], "beta": ["help"], "empty": []}[args["name"]]
        offset = int(conn_args.get("after") or "0")
        rows = [
            {
                "id": f"L-{args['name']}-{name}",
                "name": name,
                "color": "abcdef",
                "description": None,
                "isDefault": name == "bug",
                "createdAt": None,
                "updatedAt": None,
                "url": f"https://github.example/labels/{name}",
            }
            for name in names[offset : offset + 1]
        ]
        more = offset + 1 < len(names)
        return result(
            {
                "data": {
                    "repository": {
                        "labels": {
                            "nodes": rows,
                            "pageInfo": {"hasNextPage": more, "endCursor": str(offset + 1) if more else None},
                        }
                    }
                }
            }
        )
    raise AssertionError(f"Unexpected connected request {request.method} {request.url}")


api.open_client = lambda: httpx.Client(transport=httpx.MockTransport(respond), follow_redirects=True)
if __name__ == "__main__":
    main()
