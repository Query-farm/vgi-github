"""Independent search-hit populations with paginated envelope metadata and node aliases."""

from __future__ import annotations

import json
import os
from copy import deepcopy
from pathlib import Path

import httpx
from graphql import parse, value_from_ast_untyped

from vgi_github import github_api as api
from vgi_github.generated_worker import main

ORG = "search-fixture"
OWNER = {
    "id": 8100,
    "node_id": "O8100",
    "login": ORG,
    "type": "Organization",
    "html_url": "https://github.com/" + ORG,
}
AUTHOR = {
    "id": 8110,
    "node_id": "U8110",
    "login": "search-fixture-user",
    "type": "User",
    "html_url": "https://github.com/search-fixture-user",
}
MATCHES = [
    {
        "object_url": "https://example.invalid/match",
        "object_type": "FileContent",
        "property": "content",
        "fragment": "fixture code",
        "matches": [{"text": "fixture", "indices": [0, 7]}],
    }
]


def repository(name, identity, score):
    row = {
        "id": identity,
        "node_id": "R" + str(identity),
        "name": name,
        "full_name": ORG + "/" + name,
        "owner": OWNER,
        "private": False,
        "description": "Search fixture " + name,
        "fork": False,
        "created_at": "2025-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:00:00Z",
        "pushed_at": "2026-01-01T00:00:00Z",
        "homepage": None,
        "size": 10,
        "stargazers_count": 2,
        "watchers_count": 2,
        "language": "Python",
        "forks_count": 1,
        "open_issues_count": 3,
        "default_branch": "main",
        "score": score,
        "git_url": "git://example.invalid/repo",
        "ssh_url": "git@example.invalid:repo",
        "clone_url": "https://example.invalid/repo.git",
        "forks": 1,
        "open_issues": 3,
        "watchers": 2,
        "mirror_url": None,
        "has_issues": True,
        "has_projects": False,
        "has_pages": False,
        "has_wiki": False,
        "has_downloads": True,
        "archived": False,
        "disabled": False,
        "license": None,
        "topics": ["fixture"],
        "text_matches": MATCHES,
    }
    for key in [
        "html_url",
        "url",
        "forks_url",
        "keys_url",
        "collaborators_url",
        "teams_url",
        "hooks_url",
        "issue_events_url",
        "events_url",
        "assignees_url",
        "branches_url",
        "tags_url",
        "blobs_url",
        "git_tags_url",
        "git_refs_url",
        "trees_url",
        "statuses_url",
        "languages_url",
        "stargazers_url",
        "contributors_url",
        "subscribers_url",
        "subscription_url",
        "commits_url",
        "git_commits_url",
        "comments_url",
        "issue_comment_url",
        "contents_url",
        "compare_url",
        "merges_url",
        "archive_url",
        "downloads_url",
        "issues_url",
        "pulls_url",
        "milestones_url",
        "notifications_url",
        "labels_url",
        "releases_url",
        "deployments_url",
        "svn_url",
    ]:
        row[key] = "https://api.github.com/repos/" + ORG + "/" + name + "/" + key
    return row


REPOSITORIES = {"alpha": repository("alpha", 8101, 10.0), "beta": repository("beta", 8102, 5.0)}
CODE = [
    {
        "name": "first.py",
        "path": "src/first.py",
        "sha": "a" * 40,
        "url": "https://api.github.com/code/1",
        "git_url": "https://api.github.com/git/1",
        "html_url": "https://github.com/code/1",
        "repository": REPOSITORIES["alpha"],
        "score": 2.5,
        "file_size": 8,
        "language": "Python",
        "last_modified_at": "2026-01-01T00:00:00Z",
        "line_numbers": ["1..2"],
        "text_matches": MATCHES,
    },
    {
        "name": "second.py",
        "path": "src/second.py",
        "sha": "b" * 40,
        "url": "https://api.github.com/code/2",
        "git_url": "https://api.github.com/git/2",
        "html_url": "https://github.com/code/2",
        "repository": REPOSITORIES["beta"],
        "score": 1.5,
    },
]


def commit(sha, repo, score, author):
    return {
        "sha": sha,
        "node_id": "C" + sha[0],
        "url": "https://api.github.com/commits/" + sha,
        "html_url": "https://github.com/commits/" + sha,
        "comments_url": "https://api.github.com/commits/" + sha + "/comments",
        "author": author,
        "committer": {
            "name": "Committer",
            "email": "committer@example.invalid",
            "date": "2026-01-02T00:00:00Z",
        },
        "parents": [],
        "repository": REPOSITORIES[repo],
        "score": score,
        "text_matches": MATCHES,
        "commit": {
            "author": {
                "name": "Git author",
                "email": "author@example.invalid",
                "date": "2026-01-01T00:00:00Z",
            },
            "committer": None,
            "comment_count": 0,
            "message": "Fixture commit",
            "tree": {"sha": "d" * 40, "url": "https://api.github.com/tree"},
            "url": "https://api.github.com/commit",
            "verification": {
                "verified": False,
                "reason": "unsigned",
                "payload": None,
                "signature": None,
                "verified_at": None,
            },
        },
    }


COMMITS = [commit("a" * 40, "alpha", 3.0, AUTHOR), commit("b" * 40, "beta", 2.0, None)]


def label(identity, name):
    return {
        "id": identity,
        "node_id": "L" + str(identity),
        "url": "https://api.github.com/labels/" + str(identity),
        "name": name,
        "color": "ff0000",
        "default": name == "bug",
        "description": None,
        "archived_at": None,
        "archived_by": None,
        "score": 6.0,
        "text_matches": MATCHES,
    }


LABELS = {8101: [label(9201, "bug"), label(9202, "work")], 8102: [label(9203, "bug")]}


def issue(identity, number, node_id, score, pull=False):
    row = {
        "id": identity,
        "node_id": node_id,
        "number": number,
        "title": "Fixture search subject",
        "locked": False,
        "user": AUTHOR,
        "assignee": None,
        "assignees": [],
        "labels": [LABELS[8101][0]],
        "milestone": None,
        "comments": 1,
        "state": "open",
        "state_reason": None,
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-02T00:00:00Z",
        "closed_at": None,
        "body": "Fixture body",
        "score": score,
        "author_association": "CONTRIBUTOR",
        "draft": False,
        "text_matches": MATCHES,
        "type": None,
        "issue_field_values": [
            {
                "issue_field_id": 1,
                "issue_field_name": "Priority",
                "node_id": "IF1",
                "data_type": "number",
                "value": 12,
            }
        ],
    }
    for key in ["url", "repository_url", "labels_url", "comments_url", "events_url", "html_url"]:
        row[key] = "https://old.invalid/previous-repository/" + key
    if pull:
        row["pull_request"] = {
            "url": "https://api.github.com/pulls/9",
            "diff_url": None,
            "html_url": None,
            "patch_url": None,
            "merged_at": None,
        }
    return row


ISSUES = [issue(9301, 3, "SEARCH_I1", 4.0), issue(9302, 9, "SEARCH_PR1", 1.0, pull=True)]
NODES = {
    "SEARCH_I1": {
        "__typename": "Issue",
        "id": "SEARCH_I1",
        "number": 8,
        "repository": {
            "__typename": "Repository",
            "id": "R8102",
            "databaseId": 8102,
            "nameWithOwner": ORG + "/beta",
        },
    },
    "SEARCH_PR1": {
        "__typename": "PullRequest",
        "id": "SEARCH_PR1",
        "number": 9,
        "repository": {
            "__typename": "Repository",
            "id": "R8101",
            "databaseId": 8101,
            "nameWithOwner": ORG + "/alpha",
        },
    },
}
TOPICS = [
    {
        "name": name,
        "display_name": None,
        "short_description": "Fixture",
        "description": None,
        "created_by": "descriptive creator text",
        "released": "sometime in 2020",
        "created_at": "2020-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:00:00Z",
        "featured": name == "typed",
        "curated": True,
        "score": score,
        "related": [
            {"topic_relation": {"id": 1, "name": "other", "topic_id": 2, "relation_type": "related"}}
        ],
        "aliases": None,
    }
    for name, score in [("typed", 7.0), ("dictionary", 2.0)]
]


def account(value, score):
    row = value | {
        "score": score,
        "gravatar_id": None,
        "site_admin": False,
        "name": None,
        "bio": None,
        "email": None,
        "location": None,
        "text_matches": MATCHES,
    }
    for key in [
        "avatar_url",
        "url",
        "followers_url",
        "subscriptions_url",
        "organizations_url",
        "repos_url",
        "received_events_url",
        "following_url",
        "gists_url",
        "starred_url",
        "events_url",
    ]:
        row[key] = "https://api.github.com/users/" + row["login"] + "/" + key
    return row


ACCOUNTS = [account(AUTHOR, 8.0), account(OWNER, 1.0)]


def wire(selection_set, value):
    if value is None:
        return None
    if isinstance(value, list):
        return [wire(selection_set, row) for row in value]
    output = {}
    for selection in selection_set.selections:
        if selection.kind == "inline_fragment":
            if selection.type_condition.name.value == value.get("__typename"):
                output.update(wire(selection.selection_set, value))
            continue
        name = selection.name.value
        field = value.get(name)
        output[selection.alias.value if selection.alias else name] = (
            wire(selection.selection_set, field) if selection.selection_set else field
        )
    return output


def respond(request):
    path = request.url.path
    graphql_field = None
    if request.method == "POST" and path == "/graphql":
        body = json.loads(request.content)
        operation = parse(body["query"]).definitions[0]
        graphql_field = operation.selection_set.selections[0]
        if graphql_field.name.value != "node":
            return None
        identity = value_from_ast_untyped(graphql_field.arguments[0].value, body.get("variables", {}))
        if identity not in NODES:
            return None
    elif not (
        path.startswith("/search/")
        or path.startswith(("/repos/" + ORG + "/", "/orgs/" + ORG, "/users/" + ORG))
    ):
        return None
    if os.environ.get("CROSSFIELD_GITHUB_API_LOG"):
        with Path(os.environ["CROSSFIELD_GITHUB_API_LOG"]).open("a") as output:
            output.write(json.dumps({"path": path, "query": request.url.query.decode()}) + "\n")
    headers = {"Cache-Control": "no-store", "X-RateLimit-Remaining": "5000"}

    def response(value, extra=None):
        return httpx.Response(200, json=deepcopy(value), request=request, headers=headers | (extra or {}))

    def page(rows, envelope=False):
        number = int(request.url.params.get("page", "1"))
        links = (
            {"Link": f'<{request.url.copy_set_param("page", str(number + 1))}>; rel="next"'}
            if number < len(rows)
            else {}
        )
        selected = rows[number - 1 : number]
        if not envelope:
            return response(selected, links)
        root = {"total_count": len(rows), "incomplete_results": False, "items": selected}
        if path == "/search/issues":
            mode = request.url.params.get("search_type")
            root["search_type"] = "lexical"
            if mode:
                root["lexical_fallback_reason"] = ["service_unavailable"]
        return response(root, links)

    if graphql_field:
        return response(
            {
                "data": {
                    graphql_field.alias.value if graphql_field.alias else "node": wire(
                        graphql_field.selection_set, NODES[identity]
                    )
                }
            }
        )
    if path == "/users/" + ORG:
        return response(OWNER)
    if path == "/orgs/" + ORG + "/repos":
        return page(list(REPOSITORIES.values()))
    if path.startswith("/repos/"):
        return response(REPOSITORIES[path.rsplit("/", 1)[-1]])
    if path.startswith("/search/"):
        kind = path.rsplit("/", 1)[-1]
        if kind == "users":
            assert "authorization" not in request.headers
        rows = {
            "code": CODE,
            "commits": COMMITS,
            "issues": ISSUES,
            "repositories": list(REPOSITORIES.values()),
            "topics": TOPICS,
            "users": ACCOUNTS,
        }.get(kind)
        if kind == "labels":
            rows = LABELS[int(request.url.params["repository_id"])]
        assert rows is not None
        return page([] if request.url.params["q"] == "empty" else rows, True)
    return None


if __name__ == "__main__":
    api.open_client = lambda: httpx.Client(transport=httpx.MockTransport(respond), follow_redirects=True)
    main()
