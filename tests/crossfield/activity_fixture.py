"""Independent bidirectional activity relationships and caller-qualified observations."""

from __future__ import annotations

import json
import os
from copy import deepcopy
from pathlib import Path

import httpx

from vgi_github import github_api as api
from vgi_github.generated_worker import main

ORG = "activity-fixture"
USER = "activity-fixture-user"
CALLER = {"id": 903, "login": "package-fixture-current", "type": "User"}
ACCOUNT = {"id": 6110, "login": USER, "type": "User"}
OTHER = {"id": 6111, "login": "activity-fixture-other", "type": "User"}
ORGANIZATION = {"id": 6100, "login": ORG, "type": "Organization"}
REPOSITORIES = {
    name: {
        "id": identity,
        "node_id": "R" + str(identity),
        "name": name,
        "full_name": ORG + "/" + name,
        "owner": ORGANIZATION,
        "private": False,
        "description": "Activity fixture " + name,
        "topics": [],
        "language": "Python" if name == "alpha" else None,
    }
    for name, identity in [("alpha", 6101), ("beta", 6102)]
}
STARS = {
    "alpha": [
        {"starred_at": "2026-01-01T00:00:00Z", "user": ACCOUNT},
        {"starred_at": "2026-01-02T00:00:00Z", "user": CALLER},
    ],
    "beta": [],
}
WATCHERS = {"alpha": [ACCOUNT], "beta": [CALLER]}
HISTORY = {
    "alpha": [
        {"week": 1754784000, "total": 2, "days": [1, 1, 0, 0, 0, 0, 0]},
        {"week": 1754179200, "total": 1, "days": [0, 1, 0, 0, 0, 0, 0]},
    ],
    "beta": [{"week": 1754784000, "total": 0, "days": [0, 0, 0, 0, 0, 0, 0]}],
}


def notification(identity, repo, unread):
    return {
        "id": identity,
        "repository": REPOSITORIES[repo],
        "subject": {
            "title": "Thread " + identity,
            "url": "https://api.github.com/repos/" + ORG + "/" + repo + "/issues/1",
            "latest_comment_url": "https://api.github.com/comments/" + identity,
            "type": "Issue",
        },
        "reason": "mention" if unread else "subscribed",
        "unread": unread,
        "updated_at": "2026-05-01T00:00:00Z",
        "last_read_at": None if unread else "2026-05-02T00:00:00Z",
        "url": "https://api.github.com/notifications/threads/" + identity,
        "subscription_url": "https://api.github.com/notifications/threads/" + identity + "/subscription",
    }


NOTIFICATIONS = [
    notification("7101", "alpha", True),
    notification("7102", "alpha", False),
    notification("7103", "beta", True),
]


def actor(account):
    return {
        "id": account["id"],
        "login": account["login"],
        "display_login": account["login"],
        "gravatar_id": None,
        "url": "https://api.github.com/users/" + account["login"],
        "avatar_url": "https://images.invalid/" + str(account["id"]),
    }


def event(identity, account, repo, kind, public, organization=False):
    value = {
        "id": identity,
        "type": kind,
        "actor": actor(account),
        "repo": {
            "id": REPOSITORIES[repo]["id"],
            "name": ORG + "/" + repo,
            "url": "https://api.github.com/repos/" + ORG + "/" + repo,
        },
        "public": public,
        "created_at": "2026-10-10T00:00:00Z" if kind else None,
        "payload": {"opaque_fixture": "must not be guessed as a typed event payload"},
    }
    if organization:
        value["org"] = actor(ORGANIZATION)
    return value


EVENTS = [
    event("E6101", ACCOUNT, "alpha", "PushEvent", True, True),
    event("E6102", CALLER, "beta", None, False),
    event("E6103", OTHER, "alpha", "WatchEvent", True),
]
FEEDS = {
    "timeline_url": "https://github.com/timeline",
    "user_url": "https://github.com/{user}",
    "current_user_url": "https://feeds.invalid/private?token=fixture-not-a-credential",
    "current_user_organization_urls": ["https://feeds.invalid/org-one", "https://feeds.invalid/org-two"],
    "_links": {
        "timeline": {"href": "https://github.com/timeline", "type": "application/atom+xml"},
        "user": {"href": "https://github.com/{user}", "type": "application/atom+xml"},
    },
}


def respond(request):
    path = request.url.path
    if not (
        path in {"/user", "/user/starred", "/user/subscriptions", "/notifications", "/events", "/feeds"}
        or path.startswith(
            (
                "/repos/" + ORG + "/",
                "/networks/" + ORG + "/",
                "/orgs/" + ORG,
                "/users/" + ORG,
                "/notifications/threads/71",
                "/user/starred/" + ORG + "/",
            )
        )
    ):
        return None
    if os.environ.get("CROSSFIELD_GITHUB_API_LOG"):
        with Path(os.environ["CROSSFIELD_GITHUB_API_LOG"]).open("a") as output:
            output.write(
                json.dumps(
                    {
                        "path": path,
                        "query": request.url.query.decode(),
                        "accept": request.headers.get("accept"),
                    }
                )
                + "\n"
            )
    headers = {"Cache-Control": "no-store", "X-RateLimit-Remaining": "5000"}

    def response(value, status=200, extra=None):
        return httpx.Response(status, json=deepcopy(value), request=request, headers=headers | (extra or {}))

    def page(rows):
        number = int(request.url.params.get("page", "1"))
        links = (
            {"Link": f'<{request.url.copy_set_param("page", str(number + 1))}>; rel="next"'}
            if number < len(rows)
            else {}
        )
        return response(rows[number - 1 : number], extra=links)

    def notices(repository=None):
        assert request.url.params["all"] == "true"
        rows = [row for row in NOTIFICATIONS if repository is None or row["repository"]["name"] == repository]
        if request.url.params.get("participating") == "true":
            rows = [row for row in rows if row["id"] == "7101"]
        if request.url.params.get("since", "") >= "2027":
            rows = []
        return page(rows)

    if path == "/user":
        return response(CALLER)
    if path == "/feeds":
        return response(FEEDS)
    if path == "/events":
        return page([EVENTS[0], EVENTS[2]])
    if path == "/notifications":
        return notices()
    if path.startswith("/notifications/threads/"):
        identity = path.split("/")[3]
        row = next((row for row in NOTIFICATIONS if row["id"] == identity), None)
        if row is None:
            return response({"message": "Not Found"}, 404)
        if path.endswith("/subscription"):
            return response(
                {
                    "subscribed": identity != "7102",
                    "ignored": identity == "7102",
                    "reason": None,
                    "created_at": None if identity == "7102" else "2026-05-01T00:00:00Z",
                    "url": row["subscription_url"],
                    "thread_url": row["url"],
                }
            )
        return response(row)
    if path.startswith("/user/starred/"):
        if path.endswith("/alpha"):
            return httpx.Response(204, request=request, headers=headers)
        return response({}, 404)
    if path in {"/user/starred", "/users/" + USER + "/starred"}:
        assert request.headers["accept"] == (
            "application/vnd.github.v3.star+json"
            if path.startswith("/user/")
            else "application/vnd.github.star+json"
        )
        return page(
            [
                {
                    "starred_at": "2026-01-02T00:00:00Z"
                    if path.startswith("/user/")
                    else "2026-01-01T00:00:00Z",
                    "repo": REPOSITORIES["alpha"],
                }
            ]
        )
    if path in {"/user/subscriptions", "/users/" + USER + "/subscriptions"}:
        return page([REPOSITORIES["beta" if path.startswith("/user/") else "alpha"]])
    if path == "/users/" + ORG:
        return response(ORGANIZATION)
    if path == "/orgs/" + ORG:
        return response(
            ORGANIZATION
            | {
                "name": "Activity organization",
                "description": "Independent",
                "created_at": "2020-01-01T00:00:00Z",
            }
        )
    if path == "/orgs/" + ORG + "/repos":
        return page(list(REPOSITORIES.values()))
    if path == "/orgs/" + ORG + "/events":
        return page([EVENTS[0], EVENTS[2]])
    if path == "/users/" + USER:
        return response(ACCOUNT | {"name": "Activity actor", "created_at": "2020-01-01T00:00:00Z"})
    if path.startswith("/users/" + USER + "/"):
        tail = path.split("/", 3)[3]
        if tail == "events/orgs/" + ORG:
            return page(EVENTS)
        if tail == "received_events":
            return page(EVENTS[:2])
        if tail in {"events", "events/public", "received_events/public"}:
            return page([EVENTS[0]])
    if path.startswith("/networks/"):
        return page(EVENTS)
    if path.startswith("/repos/" + ORG + "/"):
        pieces = path.strip("/").split("/")
        name = pieces[2]
        repo = REPOSITORIES.get(name)
        if repo is None:
            return response({"message": "Not Found"}, 404)
        if len(pieces) == 3:
            return response(repo)
        tail = "/".join(pieces[3:])
        if tail == "stargazers":
            assert request.headers["accept"] == "application/vnd.github.star+json"
            return page(STARS[name])
        if tail == "stargazers/count":
            return response({"count": len(STARS[name])})
        if tail == "stargazers/history":
            assert request.url.params["per_page"] == "30"
            return page(HISTORY[name])
        if tail == "subscribers":
            return page(WATCHERS[name])
        if tail == "subscription":
            return response(
                {
                    "subscribed": name == "beta",
                    "ignored": name == "alpha",
                    "reason": None,
                    "created_at": "2026-05-01T00:00:00Z",
                    "url": "https://api.github.com" + path,
                    "repository_url": "https://api.github.com/repos/" + ORG + "/" + name,
                }
            )
        if tail == "notifications":
            return notices(name)
        if tail == "events":
            return page([row for row in EVENTS if row["repo"]["id"] == repo["id"]])
    return response({"message": "Not Found"}, 404)


if __name__ == "__main__":
    api.open_client = lambda: httpx.Client(transport=httpx.MockTransport(respond), follow_redirects=True)
    main()
