"""Independent Contents and README responses, including root identity and omitted bytes."""

from __future__ import annotations

import json
import os
from copy import deepcopy
from pathlib import Path

import httpx

from vgi_github import github_api as api
from vgi_github.generated_worker import main

ORG = "contents-fixture"
OWNER = {"id": 6700, "login": ORG, "type": "Organization"}
REPOSITORIES = {
    name: {
        "id": identity,
        "node_id": "R" + str(identity),
        "name": name,
        "full_name": ORG + "/" + name,
        "owner": OWNER,
        "private": False,
        "description": "Contents fixture",
        "topics": [],
        "language": "Python",
    }
    for name, identity in [("alpha", 6701), ("beta", 6702)]
}


def content(repository, path, sha, size, kind="file", encoded=None, encoding=None):
    url = "https://api.github.com/repos/" + ORG + "/" + repository + "/contents/" + path
    git = (
        "https://api.github.com/repos/"
        + ORG
        + "/"
        + repository
        + "/git/"
        + ("trees/" if kind == "dir" else "blobs/")
        + sha
    )
    html = "https://github.com/" + ORG + "/" + repository + "/blob/main/" + path
    result = {
        "type": kind,
        "size": size,
        "name": path.rsplit("/", 1)[-1],
        "path": path,
        "sha": sha,
        "url": url,
        "git_url": git,
        "html_url": html,
        "download_url": None if kind == "dir" else "https://raw.example.invalid/expiring/" + path,
        "_links": {"git": git, "html": html, "self": url},
    }
    if encoded is not None:
        result["content"] = encoded
    if encoding is not None:
        result["encoding"] = encoding
    return result


README = {
    "alpha": content("alpha", "README.md", "a" * 40, 6, encoded="aGVsbG8K", encoding="base64"),
    "beta": content("beta", "README.rst", "b" * 40, 4, encoded="YmV0YQ==", encoding="base64"),
}
DOCS_README = content("alpha", "docs/README.md", "e" * 40, 4, encoded="ZG9jcw==", encoding="base64")
OLD_DOCS_README = content("alpha", "docs/README.md", "7" * 40, 3, encoded="b2xk", encoding="base64")
OLD_README = content("alpha", "README.md", "f" * 40, 3, encoded="b2xk", encoding="base64")
LARGE = content("alpha", "big.bin", "c" * 40, 2000000, encoded="", encoding="none")
ROOTS = {}
for name in REPOSITORIES:
    root = content(name, "", "d" * 40 if name == "alpha" else "9" * 40, 0, "dir")
    entry = {key: value for key, value in README[name].items() if key not in {"content", "encoding"}}
    root["entries"] = [entry]
    if name == "alpha":
        root["entries"].append(content(name, "docs", "8" * 40, 0, "dir"))
    ROOTS[name] = root


def respond(request):
    path = request.url.path
    if not path.startswith(("/repos/" + ORG + "/", "/orgs/" + ORG, "/users/" + ORG)):
        return None
    if os.environ.get("CROSSFIELD_GITHUB_API_LOG"):
        with Path(os.environ["CROSSFIELD_GITHUB_API_LOG"]).open("a") as output:
            output.write(json.dumps({"path": path, "query": request.url.query.decode()}) + "\n")
    headers = {"Cache-Control": "no-store", "X-RateLimit-Remaining": "5000"}

    def response(value, status=200, extra=None):
        return httpx.Response(status, json=deepcopy(value), request=request, headers=headers | (extra or {}))

    if path == "/users/" + ORG:
        return response(OWNER)
    if path == "/orgs/" + ORG + "/repos":
        number = int(request.url.params.get("page", "1"))
        links = {"Link": f'<{request.url.copy_set_param("page", "2")}>; rel="next"'} if number == 1 else {}
        return response(list(REPOSITORIES.values())[number - 1 : number], extra=links)
    parts = path.strip("/").split("/")
    name = parts[2]
    if name not in REPOSITORIES:
        return response({"message": "Not Found"}, 404)
    if len(parts) == 3:
        return response(REPOSITORIES[name])
    if parts[3] == "readme":
        assert request.headers["accept"] == "application/json"
        if len(parts) == 4:
            return response(
                OLD_README if name == "alpha" and request.url.params.get("ref") == "old" else README[name]
            )
        if name == "alpha" and parts[4:] == ["docs"]:
            return response(OLD_DOCS_README if request.url.params.get("ref") == "old" else DOCS_README)
    if parts[3] == "contents":
        assert request.headers["accept"] == "application/vnd.github.object+json"
        selected = "/".join(parts[4:])
        if not selected:
            return response(ROOTS[name])
        if selected == README[name]["path"]:
            return response(
                OLD_README if name == "alpha" and request.url.params.get("ref") == "old" else README[name]
            )
        if name == "alpha" and selected == "docs/README.md":
            return response(OLD_DOCS_README if request.url.params.get("ref") == "old" else DOCS_README)
        if name == "alpha" and selected == "big.bin":
            return response(LARGE)
        if name == "alpha" and selected == "link.md":
            return response(content(name, selected, "a" * 40, 6, encoded="aGVsbG8K", encoding="base64"))
    return response({"message": "Not Found"}, 404)


if __name__ == "__main__":
    api.open_client = lambda: httpx.Client(transport=httpx.MockTransport(respond), follow_redirects=True)
    main()
