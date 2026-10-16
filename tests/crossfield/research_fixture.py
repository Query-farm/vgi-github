"""Independent user-activity oracle across August and September 2026.

Creation counts, before -> after: PRs 2 -> 3, issues 2 -> 3, discussions
1 -> 2, issue/PR comments 2 -> 2, discussion comments 1 -> 2, commit
comments 1 -> 2. The separate original connected fixture remains unchanged.
"""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path

import actions_fixture
import actions_operations_fixture
import activity_fixture
import agent_tasks_fixture
import artifact_provenance_fixture
import checks_fixture
import code_scanning_fixture
import codespaces_fixture
import commit_evaluations_fixture
import connected_fixture as baseline
import content_fixture
import copilot_reports_fixture
import copilot_spaces_fixture
import dependencies_fixture
import deployments_fixture
import gists_fixture
import git_fixture
import httpx
import issue_detail_fixture
import organization_bypass_fixture
import organization_identity_fixture
import organization_metadata_fixture
import packages_fixture
import pages_fixture
import projects_fixture
import pull_request_detail_fixture
import reactions_fixture
import reference_fixture
import releases_fixture
import repository_activity_fixture
import repository_contents_fixture
import repository_detail_fixture
import retrieval_fixture
import search_fixture
import secret_scanning_fixture
import security_operations_fixture
import statistics_fixture
import team_identity_fixture
import traffic_fixture
import user_identity_fixture
from graphql import parse, value_from_ast_untyped

from vgi_github.generated_worker import main


def repository(name, identity, language):
    return {
        "id": identity,
        "databaseId": int(identity[1:]),
        "name": name.split("/")[1],
        "nameWithOwner": name,
        "url": f"https://github.example/{name}",
        "owner": {"login": name.split("/")[0]},
        "primaryLanguage": {"name": language, "id": f"LANG-{language}"} if language else None,
    }


COMPILER = repository("lab/compiler", "R501", "C++")
SDK = repository("lab/sdk", "R502", "Python")
DOCS = repository("outside/docs", "R503", None)


def event(identity, created, repo, *, title=None, body=None, number=1):
    value = {
        "id": identity,
        "number": number,
        "author": {"__typename": "User", "login": "researcher"},
        "createdAt": created,
        "updatedAt": created,
        "publishedAt": created,
        "url": f"https://github.example/activity/{identity}",
        "repository": copy.deepcopy(repo),
        "body": body or f"Independent evidence for {identity}.",
    }
    if title is not None:
        value["title"] = title
    return value


def pull(identity, created, merged, repo, title):
    row = event(identity, created, repo, title=title, number=int(identity[2:]))
    row.update({"state": "MERGED" if merged else "OPEN", "mergedAt": merged, "isDraft": False})
    return row


PULLS = [
    pull("PR201", "2026-08-01T00:00:00Z", "2026-08-01T12:00:00Z", COMPILER, "feat: add planner"),
    pull("PR202", "2026-08-31T23:30:00-02:00", "2026-09-02T01:30:00Z", COMPILER, "fix: repair parse"),
    pull("PR203", "2026-09-01T00:30:00+02:00", "2026-09-01T10:30:00Z", DOCS, "DoCs: clarify setup"),
    pull("PR204", "2026-09-08T00:00:00Z", None, SDK, "chore: update tooling"),
    pull("PR205", "2026-09-08T12:00:00Z", "2026-09-09T00:00:00Z", SDK, "feat: add query helper"),
    pull("PR206", "2026-10-01T00:00:00Z", None, COMPILER, "fix: next period"),
]


def issue(identity, created, repo, title, closed=None):
    row = event(identity, created, repo, title=title, number=int(identity[1:]))
    row.update({"state": "CLOSED" if closed else "OPEN", "closedAt": closed})
    row.update(
        fullDatabaseId=str(int(identity[1:])),
        stateReason="COMPLETED" if closed else None,
        bodyHTML="<p>Independent issue evidence</p>",
        bodyText=row["body"],
        closed=bool(closed),
        locked=False,
        activeLockReason=None,
        authorAssociation="CONTRIBUTOR",
        createdViaEmail=False,
        lastEditedAt=None,
        publishedAt=created,
        isPinned=None,
        milestone=None,
        subIssuesSummary={"total": 0, "completed": 0, "percentCompleted": 0},
    )
    return row


ISSUES = [
    issue("I301", "2026-08-05T09:00:00Z", COMPILER, "FiX: crash on empty query", "2026-09-07T00:00:00Z"),
    issue("I302", "2026-08-05T12:00:00Z", SDK, "TEST: notebook output"),
    issue("I303", "2026-09-02T00:00:00Z", SDK, "Bug: wrong timezone"),
    issue("I304", "2026-09-07T00:00:00Z", COMPILER, "refactor: improve cache", "2026-09-08T00:00:00Z"),
    issue("I305", "2026-09-07T12:00:00Z", COMPILER, "Feat: add importer"),
    issue("I306", "2026-10-01T00:00:00Z", SDK, "Future issue"),
]
# A later edit/closure is not a new issue-created event.
ISSUES[0]["updatedAt"] = "2026-09-10T00:00:00Z"

DISCUSSIONS = [
    event("D401", "2026-08-09T00:00:00Z", COMPILER, title="Planner roadmap", number=401),
    event("D402", "2026-09-05T00:00:00Z", SDK, title="Research notebooks", number=402),
    event("D403", "2026-09-05T12:00:00Z", DOCS, title="DoCs: guide feedback", number=403),
]
for row in DISCUSSIONS:
    row.update({"closedAt": None, "category": {"id": "CAT1", "name": "Ideas", "slug": "ideas"}})


def issue_comment(identity, created, subject, pr=None):
    row = event(identity, created, subject["repository"])
    row["issue"] = copy.deepcopy(subject)
    row["pullRequest"] = copy.deepcopy(pr)
    return row


ISSUE_COMMENTS = [
    issue_comment("IC501", "2026-08-10T00:00:00Z", ISSUES[0]),
    issue_comment("IC502", "2026-08-10T12:00:00Z", PULLS[0], PULLS[0]),
    issue_comment("IC503", "2026-09-04T00:00:00Z", ISSUES[2]),
    issue_comment("IC504", "2026-09-09T00:00:00Z", ISSUES[3]),
]


def discussion_comment(identity, created, subject, reply_to=None):
    row = event(identity, created, None)
    row.pop("repository")
    row["discussion"] = copy.deepcopy(subject)
    row["replyTo"] = {"id": reply_to} if reply_to else None
    return row


DISCUSSION_COMMENTS = [
    discussion_comment("DC601", "2026-08-11T00:00:00Z", DISCUSSIONS[0]),
    discussion_comment("DC602", "2026-09-06T00:00:00Z", DISCUSSIONS[1], "DC600"),
    discussion_comment("DC603", "2026-09-06T12:00:00Z", None),
]


def commit_comment(identity, created, repo, commit):
    row = event(identity, created, repo)
    row.update(databaseId=int(identity[2:]), position=None, authorAssociation="CONTRIBUTOR")
    row["commit"] = (
        {
            "oid": commit,
            "messageHeadline": f"Commit {commit}",
            "url": f"https://github.example/commit/{commit}",
        }
        if commit
        else None
    )
    row["path"] = "src/query.cc" if commit else None
    return row


COMMIT_COMMENTS = [
    commit_comment("CC701", "2026-08-12T00:00:00Z", COMPILER, "abc1"),
    commit_comment("CC702", "2026-09-10T00:00:00Z", COMPILER, "def2"),
    commit_comment("CC703", "2026-09-10T12:00:00Z", SDK, None),
]

EVENTS = {
    "pullRequests": PULLS,
    "issues": ISSUES,
    "repositoryDiscussions": DISCUSSIONS,
    "issueComments": ISSUE_COMMENTS,
    "repositoryDiscussionComments": DISCUSSION_COMMENTS,
    "commitComments": COMMIT_COMMENTS,
}
for login, identity in [
    ("researcher", 701),
    ("idle-researcher", 702),
    ("foreign-researcher", 703),
    ("deleted-researcher", 704),
    ("late-researcher", 705),
]:
    baseline.USERS[login] = baseline.user(login, identity)

for row in PULLS:
    baseline.register_pull_details(row, 701, int(row["repository"]["id"][1:]))


def respond(request):
    for fixture in (
        content_fixture,
        user_identity_fixture,
        releases_fixture,
        actions_fixture,
        actions_operations_fixture,
        checks_fixture,
        deployments_fixture,
        git_fixture,
        projects_fixture,
        packages_fixture,
        code_scanning_fixture,
        dependencies_fixture,
        secret_scanning_fixture,
        pull_request_detail_fixture,
        issue_detail_fixture,
        reactions_fixture,
        reference_fixture,
        security_operations_fixture,
        agent_tasks_fixture,
        gists_fixture,
        codespaces_fixture,
        copilot_reports_fixture,
        copilot_spaces_fixture,
        activity_fixture,
        artifact_provenance_fixture,
        organization_identity_fixture,
        search_fixture,
        repository_detail_fixture,
        team_identity_fixture,
        pages_fixture,
        organization_bypass_fixture,
        repository_contents_fixture,
        repository_activity_fixture,
        organization_metadata_fixture,
        commit_evaluations_fixture,
        statistics_fixture,
        traffic_fixture,
    ):
        result = fixture.respond(request)
        if result is not None:
            return result
    retrieved = retrieval_fixture.respond(request)
    if retrieved is not None:
        return retrieved
    if request.method != "POST" or request.url.path != "/graphql":
        return baseline.respond(request)
    body = json.loads(request.content)
    operation = parse(body["query"]).definitions[0]
    root = operation.selection_set.selections[0]
    variables = body.get("variables", {})
    args = {arg.name.value: value_from_ast_untyped(arg.value, variables) for arg in root.arguments}
    if root.name.value != "user" or args.get("login") not in baseline.USERS:
        return baseline.respond(request)
    login = args["login"]
    if login not in {
        "researcher",
        "idle-researcher",
        "foreign-researcher",
        "deleted-researcher",
        "late-researcher",
    }:
        return baseline.respond(request)
    connection = next(field for field in root.selection_set.selections if field.name.value in EVENTS)
    conn_args = {arg.name.value: value_from_ast_untyped(arg.value, variables) for arg in connection.arguments}
    if connection.name.value == "issues":
        assert conn_args.get("filterBy") == {"createdBy": login}, "Issue enumeration must restrict authorship"
    if connection.name.value == "repositoryDiscussionComments":
        assert conn_args.get("onlyAnswers") in (None, False), "Comment population must include non-answers"
    if os.environ.get("CROSSFIELD_GITHUB_API_LOG"):
        with Path(os.environ["CROSSFIELD_GITHUB_API_LOG"]).open("a") as log:
            log.write(json.dumps({"path": "/graphql", "query": connection.name.value}) + "\n")
    rows = [] if login == "idle-researcher" else copy.deepcopy(EVENTS[connection.name.value])
    for index, row in enumerate(rows):
        row["author"] = {"__typename": "User", "login": login}
        if login == "foreign-researcher" and index == 1:
            row["author"] = {"__typename": "User", "login": "other-author"}
        if login == "deleted-researcher" and index == 1:
            row["author"] = None
    offset = int(conn_args.get("after") or "0")
    headers = {"Cache-Control": "no-store", "X-RateLimit-Remaining": "5000"}
    if login == "late-researcher" and offset == 1:
        return httpx.Response(
            503, json={"message": "Later activity page unavailable"}, headers=headers, request=request
        )
    more = offset + 1 < len(rows)
    payload = {
        "data": {
            "user": {
                connection.name.value: {
                    "nodes": rows[offset : offset + 1],
                    "pageInfo": {"hasNextPage": more, "endCursor": str(offset + 1) if more else None},
                }
            }
        }
    }
    return httpx.Response(200, json=payload, headers=headers, request=request)


baseline.api.open_client = lambda: httpx.Client(transport=httpx.MockTransport(respond), follow_redirects=True)
if __name__ == "__main__":
    main()
