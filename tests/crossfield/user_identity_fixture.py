"""Independent ordered follow edges, personal directory and account contact metadata.

The authenticated identity deliberately matches packages_fixture so the shared
worker has one coherent /user identity. Reverse listings contain the same edges.
"""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path

import httpx

from vgi_github import github_api as api
from vgi_github.generated_worker import main

AUTH = "package-fixture-current"
ACCOUNTS = {
    login: {"id": identity, "login": login, "type": kind, "name": label, "created_at": "2020-01-01T00:00:00Z"}
    for identity, login, kind, label in [
        (903, AUTH, "User", "Authenticated Person"),
        (2901, "identity-alice", "User", "Alice"),
        (2902, "identity-bob", "User", "Bob"),
        (2903, "identity-carol", "User", "Carol"),
        (2904, "identity-org", "Organization", "Organization"),
        (2905, "identity-bot", "Bot", "Service Bot"),
    ]
}
BY_ID = {str(row["id"]): row for row in ACCOUNTS.values()}
EDGES = [
    ("identity-alice", AUTH),
    ("identity-carol", AUTH),
    (AUTH, "identity-bob"),
    (AUTH, "identity-alice"),
    ("identity-alice", "identity-bob"),
    ("identity-alice", "identity-carol"),
    ("identity-bob", "identity-alice"),
]
EMAILS = [
    {"email": "public@example.com", "primary": True, "verified": True, "visibility": "public"},
    {"email": "private@example.com", "primary": False, "verified": True, "visibility": "private"},
    {"email": "pending@example.com", "primary": False, "verified": False, "visibility": None},
]
SOCIAL = {
    AUTH: [{"provider": "mastodon", "url": "https://social.example/@current"}],
    "identity-alice": [
        {"provider": "mastodon", "url": "https://one.example/@alice"},
        {"provider": "mastodon", "url": "https://two.example/@alice"},
        {"provider": "linkedin", "url": "https://www.linkedin.com/in/alice"},
    ],
    "identity-bob": [],
    "identity-carol": [],
}


def respond(request):
    path = request.url.path
    parts = path.strip("/").split("/")
    owned = path in {
        "/user",
        "/users",
        "/user/emails",
        "/user/public_emails",
        "/user/social_accounts",
        "/user/followers",
        "/user/following",
    }
    owned |= path.startswith("/user/following/")
    owned |= len(parts) == 2 and parts[0] == "user" and parts[1].isdigit()
    owned |= (
        len(parts) >= 2
        and parts[0] == "users"
        and (parts[1].startswith("identity-") or parts[1] == AUTH)
        and (len(parts) == 2 or parts[2] in {"followers", "following", "social_accounts", "hovercard"})
    )
    if not owned:
        return None
    if os.environ.get("CROSSFIELD_GITHUB_API_LOG"):
        with Path(os.environ["CROSSFIELD_GITHUB_API_LOG"]).open("a") as log:
            log.write(json.dumps({"path": path, "query": str(request.url.query)}) + "\n")
    headers = {"Cache-Control": "no-store", "X-RateLimit-Remaining": "5000"}

    def response(value=None, status=200, extra=None):
        if status == 204:
            return httpx.Response(status, headers=headers, request=request)
        return httpx.Response(
            status, json=copy.deepcopy(value), headers=headers | (extra or {}), request=request
        )

    def missing():
        return response({"message": "Not Found"}, 404)

    def pages(rows):
        page = int(request.url.params.get("page", "1"))
        link = (
            {"Link": f'<{request.url.copy_set_param("page", str(page + 1))}>; rel="next"'}
            if page < len(rows)
            else {}
        )
        return response(rows[page - 1 : page], extra=link)

    if path == "/user":
        return response(ACCOUNTS[AUTH])
    if len(parts) == 2 and parts[0] == "user" and parts[1].isdigit():
        return response(BY_ID[parts[1]]) if parts[1] in BY_ID else missing()
    if path == "/users":
        after = int(request.url.params.get("since", "0"))
        remaining = [v for v in ACCOUNTS.values() if v["id"] > after]
        link = (
            {"Link": f'<{request.url.copy_set_param("since", str(remaining[0]["id"]))}>; rel="next"'}
            if len(remaining) > 1
            else {}
        )
        return response(remaining[:1], extra=link)
    if parts[0] == "user":
        login, tail = AUTH, parts[1:]
    else:
        login, tail = parts[1], parts[2:]
        if login not in ACCOUNTS:
            return missing()
        if not tail:
            return response(ACCOUNTS[login])
    if tail in [["emails"], ["public_emails"]]:
        rows = EMAILS if tail == ["emails"] else [v for v in EMAILS if v["visibility"] == "public"]
        return pages(rows)
    if tail == ["social_accounts"]:
        return pages(SOCIAL.get(login, []))
    if tail == ["followers"]:
        return pages([ACCOUNTS[a] for a, b in EDGES if b == login])
    if tail == ["following"]:
        return pages([ACCOUNTS[b] for a, b in EDGES if a == login])
    if len(tail) == 2 and tail[0] == "following":
        return response(None, 204) if (login, tail[1]) in EDGES else missing()
    if tail == ["hovercard"]:
        if login == "identity-bob":
            return response({"contexts": []})
        if request.url.params.get("subject_type"):
            return response(
                {
                    "contexts": [
                        {"message": "Contributor to repository 123", "octicon": "repo"},
                        {"message": "One open issue", "octicon": "issue-opened"},
                    ]
                }
            )
        return response({"contexts": [{"message": "Personal account", "octicon": "person"}]})
    raise AssertionError(f"Unexpected identity fixture request: {request.url}")


if __name__ == "__main__":
    api.open_client = lambda: httpx.Client(transport=httpx.MockTransport(respond), follow_redirects=True)
    main()
