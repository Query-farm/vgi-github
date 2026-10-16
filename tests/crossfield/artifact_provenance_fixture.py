"""Artifact occurrences and attestation positions are explicitly retrieval-scoped."""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path

import httpx

from vgi_github import github_api as api
from vgi_github.generated_worker import main

DIGEST = "sha256:" + "a" * 64
OTHER_DIGEST = "sha256:" + "b" * 64
ORG = {
    "id": 54000,
    "login": "provenance-fixture",
    "name": "Provenance fixture",
    "type": "Organization",
    "description": None,
    "created_at": "2020-01-01T00:00:00Z",
}
USER = {
    "id": 54001,
    "login": "provenance-user",
    "name": "Provenance user",
    "type": "User",
    "created_at": "2020-01-01T00:00:00Z",
}
REPOS = {
    name: {
        "id": identity,
        "name": name,
        "full_name": f"provenance-fixture/{name}",
        "node_id": f"R{identity}",
        "owner": ORG,
        "private": False,
        "description": None,
        "topics": [],
        "language": "Python",
        "stargazers_count": 0,
    }
    for name, identity in [("alpha", 54101), ("beta", 54102)]
}
DEPLOYMENTS = [
    {
        "id": 55001,
        "digest": DIGEST,
        "logical_environment": "production",
        "physical_environment": "us-east",
        "cluster": "production",
        "deployment_name": "api",
        "tags": {"env": "prod", "team": "platform"},
        "runtime_risks": ["internet-exposed", "sensitive-data"],
        "created_at": "2026-10-01T12:00:00Z",
        "updated_at": "2026-10-15T12:00:00Z",
        "attestation_id": 56001,
    },
    {
        "digest": DIGEST,
        "logical_environment": "production",
        "physical_environment": "us-west",
        "cluster": "production",
        "deployment_name": "worker",
        "tags": {},
        "runtime_risks": [],
        "created_at": "upstream-unformatted-time",
        "updated_at": "upstream-unformatted-time",
        "attestation_id": None,
    },
    {"cluster": "staging", "deployment_name": "canary"},
]
STORAGE = [
    {
        "id": 55101,
        "name": "libfoo",
        "digest": DIGEST,
        "artifact_url": "https://registry.example/bar/libfoo",
        "registry_url": "https://registry.example",
        "repository": "bar",
        "status": "active",
        "created_at": "2026-10-01T12:00:00Z",
        "updated_at": "2026-10-15T12:00:00Z",
    },
    {
        "name": "libfoo-copy",
        "digest": DIGEST,
        "artifact_url": "https://registry.example/archive/libfoo",
        "registry_url": "https://registry.example",
        "repository": "archive",
        "status": "deleted",
        "created_at": "upstream-unformatted-time",
    },
]
JOBS = {
    57001: {"job_id": 57001, "status": "completed", "started_at": "2026-10-15T12:00:00Z", "total_count": 5},
    57002: {"job_id": 57002, "status": "pending"},
    57003: {
        "job_id": 57003,
        "status": "failed",
        "started_at": "2026-10-15T12:00:00Z",
        "errors": [{"untyped_upstream_key": "retained outside typed model"}],
    },
}
ORG_ATTESTATIONS = [
    {
        "repository_id": 54101,
        "bundle": {
            "mediaType": "application/vnd.dev.sigstore.bundle.v0.3+json",
            "verificationMaterial": {"opaque": 1},
            "dsseEnvelope": {"opaque": 2},
        },
        "bundle_url": "https://evidence.example/org/1",
        "initiator": "provenance-user",
    },
    {
        "repository_id": 54102,
        "bundle": None,
        "bundle_url": "https://evidence.example/org/2",
        "initiator": "automation",
    },
    {"initiator": "unknown-repository"},
]
USER_ATTESTATIONS = [
    {"repository_id": 54201, "bundle_url": "https://evidence.example/user/1", "initiator": "provenance-user"},
    {
        "bundle": {"mediaType": "application/vnd.dev.sigstore.bundle.v0.3+json"},
        "initiator": "provenance-user",
    },
]


def respond(request):
    path = request.url.path
    if not (
        path.startswith("/orgs/provenance-fixture")
        or path.startswith("/users/provenance-user")
        or path.startswith("/repos/provenance-fixture/")
    ):
        return None
    if os.environ.get("CROSSFIELD_GITHUB_API_LOG"):
        with Path(os.environ["CROSSFIELD_GITHUB_API_LOG"]).open("a") as log:
            log.write(json.dumps({"path": path, "query": str(request.url.query)}) + "\n")
    headers = {"Cache-Control": "no-store", "X-RateLimit-Remaining": "5000"}

    def response(value=None, code=200, extra=None):
        return (
            httpx.Response(code, json=copy.deepcopy(value), headers=headers | (extra or {}), request=request)
            if code != 204
            else httpx.Response(204, headers=headers, request=request)
        )

    def pages(rows, envelope=None):
        page = int(request.url.params.get("after", "1"))
        extra = (
            {"Link": f'<{request.url.copy_set_param("after", str(page + 1))}>; rel="next"'}
            if page < len(rows)
            else {}
        )
        selected = rows[page - 1 : page]
        return response({envelope: selected} if envelope else selected, extra=extra)

    parts = path.strip("/").split("/")
    if path == "/orgs/provenance-fixture":
        return response(ORG)
    if path == "/users/provenance-user":
        return response(USER)
    if path == "/orgs/provenance-fixture/attestations/repositories":
        values = list(REPOS.values())
        if request.url.params.get("predicate_type") == "sbom":
            values = values[:1]
        return pages([{"id": r["id"], "name": r["name"]} for r in values])
    if parts[:2] == ["users", "provenance-user"] and parts[2:3] == ["attestations"]:
        if parts[-1] == OTHER_DIGEST:
            return response(code=204)
        return pages(USER_ATTESTATIONS, "attestations")
    if parts[:2] == ["orgs", "provenance-fixture"] and parts[2:3] == ["attestations"]:
        return pages(ORG_ATTESTATIONS if parts[-1] == DIGEST else [], "attestations")
    if parts[:3] == ["orgs", "provenance-fixture", "artifacts"]:
        if parts[3:6] == ["metadata", "deployment-record", "cluster"]:
            row = JOBS.get(int(parts[-1]))
            return response(row) if row else response({"message": "Not Found"}, 404)
        if parts[-1] == "deployment-records":
            rows = DEPLOYMENTS if parts[3] == DIGEST else []
            return response({"deployment_records": rows, "total_count": len(rows)})
        if parts[-1] == "storage-records":
            rows = STORAGE if parts[3] == DIGEST else []
            return response({"storage_records": rows, "total_count": len(rows)})
    if parts[0] == "repos":
        name = parts[2]
        if name not in REPOS:
            return response({"message": "Not Found"}, 404)
        if len(parts) == 3:
            return response(REPOS[name])
        if parts[3:4] == ["attestations"]:
            rows = [r for r in ORG_ATTESTATIONS if r.get("repository_id") == REPOS[name]["id"]]
            return pages(rows, "attestations")
    raise AssertionError(f"Unexpected artifact provenance request: {request.url}")


if __name__ == "__main__":
    api.open_client = lambda: httpx.Client(transport=httpx.MockTransport(respond), follow_redirects=True)
    main()
