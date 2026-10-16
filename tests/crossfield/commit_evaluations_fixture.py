"""Independent commit comments, status histories, rule suites and bypass observations."""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path

import httpx

from vgi_github import github_api as api
from vgi_github.generated_worker import main

OWNER = "commit-evaluation-fixture"


def actor(login, identity):
    row = {
        "id": identity,
        "login": login,
        "node_id": f"U{identity}",
        "type": "User",
        "site_admin": False,
        "gravatar_id": "",
    }
    for name in [
        "avatar_url",
        "events_url",
        "followers_url",
        "following_url",
        "gists_url",
        "html_url",
        "organizations_url",
        "received_events_url",
        "repos_url",
        "starred_url",
        "subscriptions_url",
        "url",
    ]:
        row[name] = f"https://github.example/{login}/{name}"
    return row


ALICE = actor("commit-evaluation-alice", 88101)
BOB = actor("commit-evaluation-bob", 88102)
ORG = actor(OWNER, 81000) | {
    "type": "Organization",
    "name": OWNER,
    "description": "Independent evaluation fixture",
    "created_at": "2020-01-01T00:00:00Z",
}


def repository(name, identity):
    row = {
        "id": identity,
        "node_id": f"R{identity}",
        "name": name,
        "full_name": f"{OWNER}/{name}",
        "owner": ORG,
        "private": False,
        "fork": False,
        "description": "Evaluation fixture",
        "topics": [],
        "language": "Python",
    }
    for key in [
        "archive_url",
        "assignees_url",
        "blobs_url",
        "branches_url",
        "collaborators_url",
        "comments_url",
        "commits_url",
        "compare_url",
        "contents_url",
        "contributors_url",
        "deployments_url",
        "downloads_url",
        "events_url",
        "forks_url",
        "git_commits_url",
        "git_refs_url",
        "git_tags_url",
        "hooks_url",
        "html_url",
        "issue_comment_url",
        "issue_events_url",
        "issues_url",
        "keys_url",
        "labels_url",
        "languages_url",
        "merges_url",
        "milestones_url",
        "notifications_url",
        "pulls_url",
        "releases_url",
        "stargazers_url",
        "statuses_url",
        "subscribers_url",
        "subscription_url",
        "tags_url",
        "teams_url",
        "trees_url",
        "url",
    ]:
        row[key] = f"https://api.github.com/repos/{OWNER}/{name}/{key}"
    return row


REPOSITORIES = [repository("alpha", 81001), repository("beta", 81002), repository("empty", 81003)]
SHAS = {"alpha": "a" * 40, "beta": "b" * 40, "empty": "e" * 40}


def status(identity, context, state, creator=ALICE):
    return {
        "id": identity,
        "node_id": f"S{identity}",
        "context": context,
        "state": state,
        "creator": creator,
        "description": None,
        "target_url": None,
        "avatar_url": None,
        "url": f"https://api.github.com/statuses/{identity}",
        "created_at": "2026-09-01T00:00:00Z",
        "updated_at": "2026-09-01T01:00:00Z",
    }


HISTORY = {
    "alpha": [
        status(82003, "build", "success"),
        status(82002, "lint", "failure", None),
        status(82001, "build", "pending", BOB),
    ],
    "beta": [status(82004, "test", "future-state")],
    "empty": [],
}
LATEST = {"alpha": HISTORY["alpha"][:2], "beta": HISTORY["beta"], "empty": []}


def comment(identity, commit, actor_value):
    return {
        "id": identity,
        "node_id": f"CC{identity}",
        "commit_id": commit,
        "body": "Independent comment",
        "html_url": f"https://github.example/comments/{identity}",
        "created_at": "2026-09-01T00:00:00Z",
        "updated_at": "2026-09-02T00:00:00Z",
        "user": actor_value,
        "path": "src/main.py",
        "position": None,
        "author_association": "CONTRIBUTOR",
    }


COMMENTS = {
    "alpha": [comment(83001, SHAS["alpha"], ALICE), comment(83002, SHAS["alpha"], None)],
    "beta": [comment(83003, SHAS["beta"], BOB)],
    "empty": [],
}


def rule(identity, repo, result, actor_id=88101, evaluations=None):
    return {
        "id": identity,
        "actor_id": actor_id,
        "actor_name": "commit-evaluation-alice" if actor_id else None,
        "before_sha": "0" * 40,
        "after_sha": SHAS[repo],
        "ref": "refs/heads/main",
        "repository_id": next(r["id"] for r in REPOSITORIES if r["name"] == repo),
        "repository_name": repo,
        "pushed_at": "2026-09-01T00:00:00Z",
        "result": result,
        "evaluation_result": None,
        "rule_evaluations": evaluations,
    }


def evaluation(result):
    return {
        "rule_source": {"type": "ruleset", "id": 1, "name": "CI"},
        "enforcement": "active",
        "result": result,
        "rule_type": "required_status_checks",
        "details": None if result == "pass" else "Missing status",
    }


RULES = {
    "alpha": [
        rule(84001, "alpha", "pass", evaluations=[evaluation("pass"), evaluation("pass")]),
        rule(84002, "alpha", "fail", actor_id=None, evaluations=[evaluation("fail")]),
    ],
    "beta": [rule(84003, "beta", "bypass", evaluations=[])],
    "empty": [],
}


def bypass(identity, number, repo, state, response_count):
    r = next(r for r in REPOSITORIES if r["name"] == repo)
    return {
        "id": identity,
        "number": number,
        "repository": {"id": r["id"], "name": repo, "full_name": r["full_name"]},
        "organization": {"id": 81000, "name": OWNER},
        "requester": {"actor_id": 88101, "actor_name": "commit-evaluation-alice"},
        "request_type": "push_rules",
        "data": [
            {"ruleset_id": 91, "ruleset_name": "Large files", "total_violations": 2, "rule_type": "file_size"}
        ],
        "resource_identifier": SHAS[repo],
        "status": state,
        "requester_comment": None,
        "expires_at": "2026-09-08T00:00:00Z",
        "created_at": "2026-09-01T00:00:00Z",
        "responses": [
            {
                "id": 86000 + n,
                "reviewer": {"actor_id": 88102, "actor_name": "commit-evaluation-bob"},
                "status": "approved",
                "created_at": "2026-09-02T00:00:00Z",
            }
            for n in range(response_count)
        ],
        "url": f"https://api.github.com/repos/{OWNER}/{repo}/bypass-requests/push-rules/{number}",
        "html_url": f"https://github.com/{OWNER}/{repo}/exemptions/{number}",
    }


BYPASSES = {
    "alpha": [bypass(85001, 1, "alpha", "approved", 2), bypass(85002, 2, "alpha", "pending", 0)],
    "beta": [bypass(85003, 1, "beta", "denied", 1)],
    "empty": [],
}


def respond(request):
    path = request.url.path
    if not (
        path.startswith(f"/repos/{OWNER}/") or path.startswith(f"/orgs/{OWNER}") or path == f"/users/{OWNER}"
    ):
        return None
    if os.environ.get("CROSSFIELD_GITHUB_API_LOG"):
        with Path(os.environ["CROSSFIELD_GITHUB_API_LOG"]).open("a") as log:
            log.write(json.dumps({"path": path, "query": request.url.query.decode()}) + "\n")

    def response(value, next_page=None):
        headers = {"Cache-Control": "no-store", "X-RateLimit-Remaining": "5000"}
        if next_page:
            headers["Link"] = f'<{request.url.copy_set_param("page", str(next_page))}>; rel="next"'
        return httpx.Response(200, json=copy.deepcopy(value), headers=headers, request=request)

    def pages(rows, envelope=None):
        page = int(request.url.params.get("page", "1"))
        values = rows[page - 1 : page]
        return response(
            envelope | {"statuses": values} if envelope is not None else values,
            page + 1 if page < len(rows) else None,
        )

    pieces = path.strip("/").split("/")
    if path in {f"/orgs/{OWNER}", f"/users/{OWNER}"}:
        return response(ORG)
    if path == f"/orgs/{OWNER}/repos":
        return pages(REPOSITORIES)
    if path == f"/orgs/{OWNER}/bypass-requests/push-rules":
        rows = [row for values in BYPASSES.values() for row in values]
        repository_name = request.url.params.get("repository_name")
        if repository_name:
            rows = [row for row in rows if row["repository"]["name"] == repository_name]
        outcome = request.url.params.get("request_status")
        if outcome and outcome != "all":
            rows = [row for row in rows if row["status"] == outcome]
        return pages(rows)
    if pieces[:2] == ["orgs", OWNER] and pieces[2:4] == ["rulesets", "rule-suites"]:
        rows = [r for values in RULES.values() for r in values]
        if len(pieces) == 5:
            return response(next(r for r in rows if r["id"] == int(pieces[4])))
        name = request.url.params.get("repository_name")
        if name:
            rows = [r for r in rows if r["repository_name"] == name]
        return pages(rows)
    name = pieces[2]
    if len(pieces) == 3:
        return response(next(r for r in REPOSITORIES if r["name"] == name))
    endpoint = pieces[3:]
    if endpoint == ["comments"]:
        return pages(COMMENTS[name])
    if len(endpoint) == 2 and endpoint[0] == "comments":
        return response(next(row for row in COMMENTS[name] if row["id"] == int(endpoint[1])))
    if len(endpoint) == 3 and endpoint[0] == "commits":
        ref, kind = endpoint[1:]
        assert ref in {"main", SHAS[name]}, "Unexpected ref must not silently select fixture history"
        if kind == "comments":
            return pages([r for r in COMMENTS[name] if r["commit_id"] == ref])
        if kind == "statuses":
            return pages(HISTORY[name])
        if kind == "status":
            rows = [{k: v for k, v in r.items() if k != "creator"} | {"required": True} for r in LATEST[name]]
            repo = next(r for r in REPOSITORIES if r["name"] == name)
            envelope = {
                "state": {"alpha": "failure", "beta": "future-state", "empty": "pending"}[name],
                "sha": SHAS[name],
                "total_count": len(rows),
                "repository": repo,
                "commit_url": f"https://api.github.com/repos/{OWNER}/{name}/commits/{SHAS[name]}",
                "url": str(request.url),
            }
            return pages(rows, envelope)
    if endpoint[:2] == ["rulesets", "rule-suites"]:
        rows = RULES[name]
        if len(endpoint) == 3:
            return response(next(r for r in rows if r["id"] == int(endpoint[2])))
        outcome = request.url.params.get("rule_suite_result")
        if outcome and outcome != "all":
            rows = [r for r in rows if r["result"] == outcome]
        return pages(rows)
    if endpoint[:2] == ["bypass-requests", "push-rules"]:
        rows = BYPASSES[name]
        if len(endpoint) == 3:
            return response(next(r for r in rows if r["number"] == int(endpoint[2])))
        outcome = request.url.params.get("request_status")
        if outcome and outcome != "all":
            rows = [r for r in rows if r["status"] == outcome]
        return pages(rows)
    raise AssertionError(f"Unexpected evaluation fixture request: {request.url}")


api.open_client = lambda: httpx.Client(transport=httpx.MockTransport(respond))
if __name__ == "__main__":
    main()
