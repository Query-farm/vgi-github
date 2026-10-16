"""Signed report metadata only; deliberately no downloaded usage payload fixture."""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path

import httpx

from vgi_github import github_api as api
from vgi_github.generated_worker import main

OWNER = "copilot-report-fixture"
ORGANIZATION = {
    "id": 51000,
    "login": OWNER,
    "type": "Organization",
    "name": OWNER,
    "description": "Copilot reports fixture",
    "created_at": "2020-01-01T00:00:00Z",
}
LINKS = {
    "organization-1-day": [
        "https://signed.example/organization/part1?signature=fixture",
        "https://signed.example/organization/part2?signature=fixture",
    ],
    "repos-1-day": ["https://signed.example/repositories?signature=fixture"],
    "user-teams-1-day": [],
    "users-1-day": ["https://signed.example/users?signature=fixture"],
    "organization-28-day/latest": ["https://signed.example/organization28?signature=fixture"],
    "users-28-day/latest": [
        "https://signed.example/users28/part1?signature=fixture",
        "https://signed.example/users28/part2?signature=fixture",
        "https://signed.example/users28/part3?signature=fixture",
    ],
}


def respond(request):
    path = request.url.path
    if not path.startswith((f"/orgs/{OWNER}", f"/users/{OWNER}")):
        return None
    if request.method != "GET":
        raise AssertionError(f"Unexpected Copilot report method {request.method}")
    if os.environ.get("CROSSFIELD_GITHUB_API_LOG"):
        with Path(os.environ["CROSSFIELD_GITHUB_API_LOG"]).open("a") as log:
            log.write(json.dumps({"path": path, "query": request.url.query.decode()}) + "\n")
    headers = {"Cache-Control": "no-store", "X-RateLimit-Remaining": "5000"}
    if path in {f"/orgs/{OWNER}", f"/users/{OWNER}"}:
        return httpx.Response(200, json=copy.deepcopy(ORGANIZATION), headers=headers, request=request)
    tail = path.removeprefix(f"/orgs/{OWNER}/copilot/metrics/reports/")
    if tail not in LINKS:
        raise AssertionError(f"Unexpected Copilot report request {request.url}")
    daily = tail.endswith("1-day")
    if daily and request.url.params["day"] == "2026-09-02":
        return httpx.Response(204, headers=headers, request=request)
    value = {"download_links": LINKS[tail]}
    if daily:
        value["report_day"] = request.url.params["day"]
    else:
        value.update(report_start_day="2026-08-05", report_end_day="2026-09-01")
    return httpx.Response(200, json=copy.deepcopy(value), headers=headers, request=request)


if __name__ == "__main__":
    api.http_client = lambda: httpx.Client(transport=httpx.MockTransport(respond))
    main()
