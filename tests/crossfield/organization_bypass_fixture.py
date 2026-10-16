"""Organization bypass requests retain requests with unknown repository evidence."""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path

import httpx

from vgi_github import github_api as api
from vgi_github.generated_worker import main

ORG = {
    "id": 53000,
    "login": "organization-bypass-fixture",
    "name": "Bypass fixture",
    "type": "Organization",
    "description": None,
    "created_at": "2020-01-01T00:00:00Z",
}
OWNER = ORG["login"]


def request_row(identity, number, name, status, responses):
    row = {
        "id": identity,
        "number": number,
        "organization": {"id": 53000, "name": OWNER},
        "requester": {"actor_id": 53101, "actor_name": "bypass-requester"},
        "request_type": "push_rules",
        "status": status,
        "created_at": "2026-10-15T12:00:00Z",
        "expires_at": "2026-10-16T12:00:00Z",
        "requester_comment": None,
        "responses": [
            {
                "id": identity * 10 + i,
                "reviewer": {"actor_id": 53102, "actor_name": "bypass-reviewer"},
                "status": "approved",
                "created_at": "2026-10-15T12:30:00Z",
            }
            for i in range(responses)
        ],
    }
    if name:
        row["repository"] = {
            "id": 53201 if name == "alpha" else 53202,
            "name": name,
            "full_name": f"{OWNER}/{name}",
        }
    return row


ROWS = [
    request_row(53301, 1, "alpha", "approved", 2),
    request_row(53302, 2, None, "denied", 0),
    request_row(53303, 1, "beta", "pending", 1),
]


def respond(request):
    path = request.url.path
    if not (path.startswith(f"/orgs/{OWNER}") or path.startswith(f"/repos/{OWNER}/")):
        return None
    if os.environ.get("CROSSFIELD_GITHUB_API_LOG"):
        with Path(os.environ["CROSSFIELD_GITHUB_API_LOG"]).open("a") as log:
            log.write(json.dumps({"path": path, "query": str(request.url.query)}) + "\n")
    headers = {"Cache-Control": "no-store", "X-RateLimit-Remaining": "5000"}
    if path == f"/orgs/{OWNER}":
        return httpx.Response(200, json=ORG, headers=headers, request=request)
    parts = path.strip("/").split("/")
    if parts[0] == "repos" and len(parts) == 3:
        name = parts[2]
        row = next((r["repository"] for r in ROWS if r.get("repository", {}).get("name") == name), None)
        return httpx.Response(
            200 if row else 404,
            json=(
                row
                | {
                    "owner": ORG,
                    "private": False,
                    "description": None,
                    "topics": [],
                    "node_id": f"R{row['id']}",
                    "language": None,
                }
            )
            if row
            else {"message": "Not Found"},
            headers=headers,
            request=request,
        )
    values = ROWS
    repository = request.url.params.get("repository_name") or (parts[2] if parts[0] == "repos" else None)
    if repository:
        values = [r for r in values if r.get("repository", {}).get("name") == repository]
    status = request.url.params.get("request_status")
    if status and status != "all":
        values = [r for r in values if r["status"] == status]
    requester = request.url.params.get("requester")
    if requester:
        values = [r for r in values if r["requester"]["actor_name"] == requester]
    reviewer = request.url.params.get("reviewer")
    if reviewer:
        values = [r for r in values if any(v["reviewer"]["actor_name"] == reviewer for v in r["responses"])]
    page = int(request.url.params.get("page", "1"))
    if page < len(values):
        headers["Link"] = f'<{request.url.copy_set_param("page", str(page + 1))}>; rel="next"'
    return httpx.Response(200, json=copy.deepcopy(values[page - 1 : page]), headers=headers, request=request)


if __name__ == "__main__":
    api.open_client = lambda: httpx.Client(transport=httpx.MockTransport(respond), follow_redirects=True)
    main()
