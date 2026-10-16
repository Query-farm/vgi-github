"""Independent release/asset oracle with one entity per HTTP page.

Drafts, prereleases, empty repositories, nullable uploaders, an open upload,
and incomplete embedded assets distinguish release and asset populations.
Only metadata GET responses are available; unexpected requests fail closed.
"""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path

import httpx

from vgi_github import github_api as api
from vgi_github.generated_worker import main


def account(login, identity):
    return {
        "id": identity,
        "node_id": f"U{identity}",
        "login": login,
        "type": "User",
        "name": login.title(),
        "created_at": "2020-01-01T00:00:00Z",
        "avatar_url": f"https://github.release-fixture/avatars/{identity}",
        "gravatar_id": None,
        "url": f"https://api.github.release-fixture/users/{login}",
        "html_url": f"https://github.release-fixture/{login}",
        "followers_url": f"https://api.github.release-fixture/users/{login}/followers",
        "following_url": f"https://api.github.release-fixture/users/{login}/following{{/other_user}}",
        "gists_url": f"https://api.github.release-fixture/users/{login}/gists{{/gist_id}}",
        "starred_url": f"https://api.github.release-fixture/users/{login}/starred{{/owner}}{{/repo}}",
        "subscriptions_url": f"https://api.github.release-fixture/users/{login}/subscriptions",
        "organizations_url": f"https://api.github.release-fixture/users/{login}/orgs",
        "repos_url": f"https://api.github.release-fixture/users/{login}/repos",
        "events_url": f"https://api.github.release-fixture/users/{login}/events{{/privacy}}",
        "received_events_url": f"https://api.github.release-fixture/users/{login}/received_events",
        "site_admin": False,
    }


USERS = {"alice": account("alice", 201), "bob": account("bob", 202)}
REPOSITORIES = [
    {
        "id": identity,
        "node_id": f"R{identity}",
        "full_name": f"release-fixture/{name}",
        "name": name,
        "owner": {"id": 100, "login": "release-fixture", "type": "Organization"},
        "private": name == "beta",
        "description": "Independent releases fixture repository",
        "topics": [],
        "language": None,
    }
    for identity, name in [(101, "alpha"), (102, "beta"), (103, "empty")]
]


def asset(identity, size, downloads, uploader, *, state="uploaded"):
    return {
        "id": identity,
        "node_id": f"RA{identity}",
        "name": f"asset-{identity}.zip",
        "label": None,
        "state": state,
        "content_type": "application/zip",
        "size": size,
        "digest": f"sha256:{identity:064x}" if state == "uploaded" else None,
        "download_count": downloads,
        "created_at": "2026-09-03T00:00:00Z",
        "updated_at": "2026-09-04T00:00:00Z",
        "url": f"https://api.github.release-fixture/assets/{identity}",
        "browser_download_url": f"https://github.release-fixture/download/{identity}",
        "uploader": USERS[uploader] if uploader else None,
    }


ASSETS = {
    11: [asset(111, 100, 3, "bob"), asset(112, 200, 5, None)],
    12: [asset(121, 0, 0, "alice", state="open")],
    13: [],
    21: [asset(211, 400, 7, "alice")],
}


def release(identity, tag, *, draft=False, prerelease=False):
    value = {
        "id": identity,
        "node_id": f"REL{identity}",
        "tag_name": tag,
        "target_commitish": "main",
        "name": None if draft else f"Release {tag}",
        "body": "Independent release notes",
        "draft": draft,
        "prerelease": prerelease,
        "immutable": False,
        "created_at": "2026-08-31T12:00:00Z",
        "published_at": None if draft else f"2026-09-{'05' if prerelease else '02'}T12:00:00Z",
        "updated_at": "2026-09-06T00:00:00Z",
        "author": USERS["alice"],
        "url": f"https://api.github.release-fixture/releases/{identity}",
        "assets_url": f"https://api.github.release-fixture/releases/{identity}/assets",
        "upload_url": f"https://uploads.github.release-fixture/releases/{identity}/assets{{?name,label}}",
        "html_url": f"https://github.release-fixture/releases/{identity}",
        "tarball_url": None if draft else f"https://api.github.release-fixture/releases/{identity}/tarball",
        "zipball_url": None if draft else f"https://api.github.release-fixture/releases/{identity}/zipball",
        "discussion_url": f"https://github.release-fixture/discussions/{identity}",
        # Deliberately incomplete. Correct asset enumeration must follow its endpoint.
        "assets": ASSETS[identity][:1],
    }
    if identity in (11, 21):
        value.update(
            body_html="<p>Independent release notes</p>",
            body_text="Independent release notes",
            mentions_count=2 if identity == 11 else 0,
            reactions={
                "url": f"https://api.github.release-fixture/releases/{identity}/reactions",
                "total_count": 3 if identity == 11 else 0,
                "+1": 2 if identity == 11 else 0,
                "-1": 0,
                "laugh": 0,
                "confused": 0,
                "heart": 1 if identity == 11 else 0,
                "hooray": 0,
                "eyes": 0,
                "rocket": 0,
            },
        )
    return value


RELEASES = {
    "alpha": [release(13, "v3", draft=True), release(12, "v2-rc", prerelease=True), release(11, "v1")],
    "beta": [release(21, "v1")],
    "empty": [],
}
LATEST = {"alpha": 11, "beta": 21}


def respond(request):
    """Complete fixture handler shared by worker tests and native SQL tests."""
    path = request.url.path
    owned = (
        path.startswith(("/repos/release-fixture/", "/orgs/release-fixture/"))
        or path == "/users/release-fixture"
    )
    if not owned:
        return None
    if os.environ.get("CROSSFIELD_GITHUB_API_LOG"):
        with Path(os.environ["CROSSFIELD_GITHUB_API_LOG"]).open("a") as log:
            log.write(json.dumps({"path": path, "query": request.url.query.decode()}) + "\n")
    headers = {"Cache-Control": "no-store", "X-RateLimit-Remaining": "5000"}

    def response(value, status=200, *, next_page=None):
        response_headers = dict(headers)
        if next_page:
            response_headers["Link"] = f'<{request.url.copy_set_param("page", str(next_page))}>; rel="next"'
        return httpx.Response(status, json=copy.deepcopy(value), headers=response_headers, request=request)

    def pages(rows):
        page = int(request.url.params.get("page", "1"))
        return response(rows[page - 1 : page], next_page=page + 1 if page < len(rows) else None)

    def missing():
        return response({"message": "Not Found"}, 404)

    if request.method != "GET":
        raise AssertionError(f"Unexpected non-GET release fixture request: {request.method} {path}")
    if path == "/users/release-fixture":
        return response({"id": 100, "login": "release-fixture", "type": "Organization"})
    if path == "/orgs/release-fixture/repos":
        return pages(REPOSITORIES)
    pieces = path.strip("/").split("/")
    if len(pieces) >= 3 and pieces[:2] == ["repos", "release-fixture"]:
        name = pieces[2]
        repository = next((row for row in REPOSITORIES if row["name"] == name), None)
        if repository is None:
            return missing()
        if len(pieces) == 3:
            return response(repository)
        if pieces[3] == "releases":
            releases = RELEASES[name]
            if len(pieces) == 4:
                return pages(releases)
            if pieces[4] == "assets" and len(pieces) == 6:
                identity = int(pieces[5])
                value = next(
                    (
                        asset
                        for release in releases
                        for asset in ASSETS[release["id"]]
                        if asset["id"] == identity
                    ),
                    None,
                )
                return response(value) if value is not None else missing()
            if pieces[4] == "latest" and len(pieces) == 5:
                value = next((row for row in releases if row["id"] == LATEST.get(name)), None)
            elif pieces[4] == "tags" and len(pieces) == 6:
                value = next((row for row in releases if row["tag_name"] == pieces[5]), None)
            elif pieces[4].isdigit() and len(pieces) in (5, 6):
                value = next((row for row in releases if row["id"] == int(pieces[4])), None)
                if value is not None and len(pieces) == 6 and pieces[5] == "assets":
                    return pages(ASSETS[value["id"]])
            else:
                raise AssertionError(f"Unexpected release endpoint: {path}")
            return response(value) if value is not None else missing()
    raise AssertionError(f"Unexpected release fixture request: {path}")


if __name__ == "__main__":
    api.open_client = lambda: httpx.Client(transport=httpx.MockTransport(respond), follow_redirects=True)
    main()
