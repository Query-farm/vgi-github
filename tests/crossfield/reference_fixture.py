"""Independent reference catalogs, dictionaries and caller-scoped API observations."""

from __future__ import annotations

import json
import os
from copy import deepcopy
from pathlib import Path

import httpx

from vgi_github import github_api as api
from vgi_github.generated_worker import main

OWNER = "reference-fixture"
REPOSITORIES = [
    {
        "id": 4101,
        "node_id": "R4101",
        "full_name": OWNER + "/alpha",
        "name": "alpha",
        "owner": {"id": 4100, "login": OWNER, "type": "Organization"},
        "private": False,
        "description": "Reference facts",
        "topics": [],
        "language": "Python",
    },
    {
        "id": 4102,
        "node_id": "R4102",
        "full_name": OWNER + "/beta",
        "name": "beta",
        "owner": {"id": 4100, "login": OWNER, "type": "Organization"},
        "private": False,
        "description": "Empty language dictionary",
        "topics": [],
        "language": None,
    },
]
CONDUCTS = {
    "contributor_covenant": {
        "key": "contributor_covenant",
        "name": "Contributor Covenant",
        "url": "https://api.github.com/codes_of_conduct/contributor_covenant",
        "html_url": "https://example.invalid/covenant",
        "body": "Welcome contributors.\n",
    },
    "citizen_code_of_conduct": {
        "key": "citizen_code_of_conduct",
        "name": "Citizen Code",
        "url": "https://api.github.com/codes_of_conduct/citizen_code_of_conduct",
        "html_url": None,
        "body": "Respect participants.\n",
    },
}
TEMPLATES = {"Python": "__pycache__/\n*.pyc\n", "C++": "*.o\n*.so\n"}
LICENSES = {
    "mit": {
        "key": "mit",
        "name": "MIT License",
        "spdx_id": "MIT",
        "url": "https://api.github.com/licenses/mit",
        "node_id": "L-mit",
        "html_url": "https://example.invalid/mit",
        "description": "Permissive fixture",
        "implementation": "Include license text",
        "permissions": ["commercial-use", "distribution"],
        "conditions": ["include-copyright"],
        "limitations": ["liability"],
        "body": "MIT\n",
        "featured": True,
    },
    "apache-2.0": {
        "key": "apache-2.0",
        "name": "Apache License 2.0",
        "spdx_id": "Apache-2.0",
        "url": "https://api.github.com/licenses/apache-2.0",
        "node_id": "L-apache",
        "html_url": "https://example.invalid/apache",
        "description": "Patent fixture",
        "implementation": "Include notices",
        "permissions": ["commercial-use", "patent-use", "distribution"],
        "conditions": ["include-copyright", "state-changes"],
        "limitations": ["liability", "trademark-use"],
        "body": "Apache\n",
        "featured": False,
    },
}
EMOJIS = {
    "+1": "https://images.invalid/thumb.png",
    "thumbsup": "https://images.invalid/thumb.png",
    "wave": "https://images.invalid/wave.png",
}
VERSIONS = ["2022-11-28", "2026-03-10"]
ROOT_LINKS = {
    "current_user_url": "https://api.github.com/user",
    "current_user_authorizations_html_url": "https://github.com/settings/connections/applications{/client_id}",
    "authorizations_url": "https://api.github.com/authorizations",
    "code_search_url": "https://api.github.com/search/code?q={query}",
    "commit_search_url": "https://api.github.com/search/commits?q={query}",
    "emails_url": "https://api.github.com/user/emails",
    "emojis_url": "https://api.github.com/emojis",
    "events_url": "https://api.github.com/events",
    "feeds_url": "https://api.github.com/feeds",
    "followers_url": "https://api.github.com/user/followers",
    "following_url": "https://api.github.com/user/following{/target}",
    "gists_url": "https://api.github.com/gists{/gist_id}",
    "issue_search_url": "https://api.github.com/search/issues?q={query}",
    "issues_url": "https://api.github.com/issues",
    "keys_url": "https://api.github.com/user/keys",
    "label_search_url": "https://api.github.com/search/labels?q={query}",
    "notifications_url": "https://api.github.com/notifications",
    "organization_url": "https://api.github.com/orgs/{org}",
    "organization_repositories_url": "https://api.github.com/orgs/{org}/repos",
    "organization_teams_url": "https://api.github.com/orgs/{org}/teams",
    "public_gists_url": "https://api.github.com/gists/public",
    "rate_limit_url": "https://api.github.com/rate_limit",
    "repository_url": "https://api.github.com/repos/{owner}/{repo}",
    "repository_search_url": "https://api.github.com/search/repositories?q={query}",
    "current_user_repositories_url": "https://api.github.com/user/repos",
    "starred_url": "https://api.github.com/user/starred{/owner}{/repo}",
    "starred_gists_url": "https://api.github.com/gists/starred",
    "user_url": "https://api.github.com/users/{user}",
    "user_organizations_url": "https://api.github.com/user/orgs",
    "user_repositories_url": "https://api.github.com/users/{user}/repos",
    "user_search_url": "https://api.github.com/search/users?q={query}",
}
METADATA = {
    "verifiable_password_authentication": False,
    "ssh_key_fingerprints": {"SHA256_RSA": "fixture-rsa", "SHA256_ED25519": "fixture-ed25519"},
    "ssh_keys": ["ssh-ed25519 fixture"],
    "hooks": ["192.0.2.0/24"],
    "web": ["198.51.100.0/24"],
    "api": ["203.0.113.0/24"],
    "git": [],
    "domains": {
        "website": ["github.com"],
        "actions_inbound": {
            "full_domains": ["fixture.actions.invalid"],
            "wildcard_domains": ["*.fixture.invalid"],
        },
        "artifact_attestations": {"trust_domain": "github", "services": ["fixture.attestation.invalid"]},
    },
}
RATE = {
    "rate": {"limit": 5000, "remaining": 4900, "reset": 1800000000, "used": 100},
    "resources": {
        "core": {"limit": 5000, "remaining": 4900, "reset": 1800000000, "used": 100},
        "search": {"limit": 30, "remaining": 29, "reset": 1800000001, "used": 1},
        "graphql": {"limit": 5000, "remaining": 4990, "reset": 1800000002, "used": 10},
    },
}


def respond(request):
    path = request.url.path
    owned = (
        path
        in {
            "/",
            "/codes_of_conduct",
            "/emojis",
            "/gitignore/templates",
            "/licenses",
            "/meta",
            "/rate_limit",
            "/versions",
            "/zen",
            "/octocat",
        }
        or path.startswith(
            (
                "/codes_of_conduct/",
                "/gitignore/templates/",
                "/licenses/",
                "/repos/reference-fixture/",
                "/orgs/reference-fixture/",
            )
        )
        or path == "/users/reference-fixture"
    )
    if not owned:
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
        link = (
            {"Link": f'<{request.url.copy_set_param("page", str(number + 1))}>; rel="next"'}
            if number < len(rows)
            else {}
        )
        return response(rows[number - 1 : number], extra=link)

    if path == "/codes_of_conduct":
        return page([{k: v for k, v in row.items() if k != "body"} for row in CONDUCTS.values()])
    if path.startswith("/codes_of_conduct/"):
        row = CONDUCTS.get(path.rsplit("/", 1)[-1])
        return response(row) if row else response({"message": "Not Found"}, 404)
    if path == "/gitignore/templates":
        return page(list(TEMPLATES))
    if path.startswith("/gitignore/templates/"):
        name = path.rsplit("/", 1)[-1]
        return (
            response({"name": name, "source": TEMPLATES[name]})
            if name in TEMPLATES
            else response({"message": "Not Found"}, 404)
        )
    if path == "/licenses":
        rows = list(LICENSES.values())
        featured = request.url.params.get("featured")
        if featured is not None:
            rows = [row for row in rows if row["featured"] == (featured == "true")]
        return page([{k: row[k] for k in ["key", "name", "url", "spdx_id", "node_id"]} for row in rows])
    if path.startswith("/licenses/"):
        row = LICENSES.get(path.rsplit("/", 1)[-1])
        return response(row) if row else response({"message": "Not Found"}, 404)
    if path == "/emojis":
        assert "per_page" not in request.url.params
        return response(EMOJIS)
    if path == "/versions":
        return page(VERSIONS)
    if path == "/":
        return response(ROOT_LINKS)
    if path == "/meta":
        return response(METADATA)
    if path == "/rate_limit":
        return response(RATE)
    if path == "/zen":
        assert request.headers["accept"] == "text/plain"
        return httpx.Response(
            200, content=b"Keep it clear.\n", headers=headers | {"Content-Type": "text/plain; charset=utf-8"}
        )
    if path == "/octocat":
        assert request.headers["accept"] == "application/octocat-stream"
        text = " /\\_/\\\n( " + request.url.params.get("s", "Hello") + " )\n"
        return httpx.Response(
            200, content=text.encode(), headers=headers | {"Content-Type": "application/octocat-stream"}
        )
    if path == "/users/reference-fixture":
        return response({"id": 4100, "login": OWNER, "type": "Organization"})
    if path == "/orgs/reference-fixture/repos":
        return page(REPOSITORIES)
    pieces = path.split("/")
    name = pieces[3]
    repo = next((row for row in REPOSITORIES if row["name"] == name), None)
    if name == "missing":
        repo = REPOSITORIES[0] | {
            "id": 4103,
            "node_id": "R4103",
            "full_name": OWNER + "/missing",
            "name": "missing",
        }
    if repo is None:
        return response({"message": "Not Found"}, 404)
    if len(pieces) == 4:
        return response(repo)
    if pieces[4] == "languages":
        assert "per_page" not in request.url.params
        return response({"Python": 1200, "C++": 800} if name == "alpha" else {})
    if pieces[4] == "license" and name != "missing":
        old = request.url.params.get("ref") == "old"
        license_info = (
            {k: LICENSES["mit"][k] for k in ["key", "name", "url", "spdx_id", "node_id"]}
            if name == "alpha"
            else None
        )
        return response(
            {
                "name": "LICENSE",
                "path": "LICENSE",
                "sha": "a" * 40 if name == "alpha" and not old else "b" * 40,
                "size": 4 if name == "alpha" else 0,
                "url": "https://api.github.com/repos/" + repo["full_name"] + "/contents/LICENSE",
                "html_url": None,
                "git_url": None,
                "download_url": None,
                "type": "file",
                "content": "TUlUCg==" if name == "alpha" else "",
                "encoding": "base64",
                "_links": {
                    "git": None,
                    "html": None,
                    "self": "https://api.github.com/repos/" + repo["full_name"] + "/contents/LICENSE",
                },
                "license": license_info,
            }
        )
    return response({"message": "Not Found"}, 404)


if __name__ == "__main__":
    api.open_client = lambda: httpx.Client(transport=httpx.MockTransport(respond), follow_redirects=True)
    main()
