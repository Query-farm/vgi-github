"""Independent dependency, alert, advisory and SPDX populations with page boundaries."""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path

import httpx

from vgi_github import github_api as api
from vgi_github.generated_worker import main

OWNER = "dependency-fixture"
A, B, C, D, E = [f"GHSA-deps-aaaa-{n:04d}" for n in range(1, 6)]


def actor(login, identity):
    return {"id": identity, "login": login, "type": "User"}


ALICE, BOB = actor("dependency-fixture-alice", 1201), actor("dependency-fixture-bob", 1202)
REPOSITORIES = [
    {
        "id": identity,
        "node_id": f"R{identity}",
        "full_name": f"{OWNER}/{name}",
        "name": name,
        "owner": {"id": 1100, "login": OWNER, "type": "Organization"},
        "private": False,
        "description": "Independent dependency fixture",
        "topics": [],
        "language": None,
    }
    for identity, name in [(1101, "alpha"), (1102, "beta"), (1103, "empty")]
]


def alert(number, state, severity, ghsa, ecosystem="npm", name="core", scope="runtime"):
    dismissed = state in {"dismissed", "auto_dismissed"}
    return {
        "number": number,
        "state": state,
        "dependency": {
            "package": {"ecosystem": ecosystem, "name": name},
            "manifest_path": "requirements.txt" if ecosystem == "pip" else "package-lock.json",
            "scope": scope,
            "relationship": "unknown" if state == "dismissed" else "direct",
        },
        "security_advisory": {
            "ghsa_id": ghsa,
            "cve_id": None,
            "summary": "Independent advisory",
            "classification": "malware" if ghsa == C else "general",
            "cvss_severities": {"cvss_v3": {"score": 9.5, "vector_string": None}, "cvss_v4": None},
            "epss": {"percentage": 5.0, "percentile": 90.0},
        },
        "security_vulnerability": {
            "severity": severity,
            "vulnerable_version_range": "< 2.0",
            "first_patched_version": {"identifier": "2.0"} if state != "open" else None,
        },
        "created_at": "2026-08-01T00:00:00Z",
        "updated_at": "2026-09-01T00:00:00Z",
        "fixed_at": "2026-09-01T00:00:00Z" if state == "fixed" else None,
        "dismissed_at": "2026-09-01T00:00:00Z" if dismissed else None,
        "auto_dismissed_at": "2026-09-01T00:00:00Z" if state == "auto_dismissed" else None,
        "dismissed_by": BOB if state == "dismissed" else None,
        "dismissed_reason": "not_used" if dismissed else None,
        "dismissed_comment": "Removed from use" if dismissed else None,
        "url": f"https://api.github.example/alerts/{number}",
        "html_url": f"https://github.example/alerts/{number}",
        "assignees": [ALICE] if state == "open" else [],
        "dismissal_request": None,
    }


ALERTS = {
    "alpha": [
        alert(1, "open", "critical", A),
        alert(2, "fixed", "high", B, "pip", "library", "development"),
        alert(3, "dismissed", "low", A),
        alert(4, "auto_dismissed", "medium", C),
    ],
    "beta": [alert(1, "open", "high", A)],
    "empty": [],
}


def advisory(ghsa, severity, *, kind="reviewed", state=None, repository=None):
    row = {
        "ghsa_id": ghsa,
        "cve_id": None,
        "url": f"https://api.github.example/advisories/{ghsa}",
        "html_url": f"https://github.example/advisories/{ghsa}",
        "summary": "Independent security advisory",
        "description": "Typed vulnerability evidence",
        "severity": severity,
        "identifiers": [{"type": "GHSA", "value": ghsa}],
        "cwes": [{"cwe_id": "CWE-79", "name": "Cross-site scripting"}],
        "cvss_severities": {"cvss_v3": None, "cvss_v4": {"score": 9.0, "vector_string": None}},
        "updated_at": "2026-09-01T00:00:00Z",
        "published_at": None if state == "draft" else "2026-08-02T00:00:00Z",
        "withdrawn_at": "2026-09-05T00:00:00Z" if ghsa == B else None,
    }
    vulnerability = {
        "package": {"ecosystem": "npm", "name": "core"},
        "vulnerable_version_range": "< 2.0",
        "vulnerable_functions": ["parse"],
    }
    if state is None:
        row.update(
            type=kind,
            github_reviewed_at="2026-08-02T00:00:00Z" if kind == "reviewed" else None,
            nvd_published_at=None,
            source_code_location=None,
            repository_advisory_url=None,
            epss={"percentage": 5.0, "percentile": 90.0},
            credits=[{"user": ALICE, "type": "finder"}],
        )
        vulnerability["first_patched_version"] = "2.0"
    else:
        row.update(
            state=state,
            author=ALICE,
            publisher=None if state == "draft" else BOB,
            created_at="2026-08-01T00:00:00Z",
            closed_at=None,
            submission={"accepted": True},
            credits_detailed=[{"user": ALICE, "type": "finder", "state": "accepted"}],
            url=f"https://api.github.example/repos/{OWNER}/{repository}/security-advisories/{ghsa}",
        )
        vulnerability["patched_versions"] = ">= 2.0, < 3.0"
    row["vulnerabilities"] = [vulnerability]
    return row


GLOBAL_ADVISORIES = [
    advisory(A, "critical"),
    advisory(B, "high"),
    advisory(C, "low", kind="malware"),
    advisory(D, "unknown", kind="unreviewed"),
]
REPOSITORY_ADVISORIES = {
    "alpha": [
        advisory(A, "critical", state="published", repository="alpha"),
        advisory(E, None, state="draft", repository="alpha"),
    ],
    "beta": [advisory(B, "high", state="withdrawn", repository="beta")],
    "empty": [],
}


def change(direction, name, version, vulnerabilities=()):
    return {
        "change_type": direction,
        "manifest": "package-lock.json",
        "ecosystem": "npm",
        "name": name,
        "version": version,
        "package_url": f"pkg:npm/{name}@{version}",
        "license": "MIT",
        "source_repository_url": None,
        "scope": "runtime",
        "vulnerabilities": [
            {
                "severity": "critical",
                "advisory_ghsa_id": ghsa,
                "advisory_summary": "Independent advisory",
                "advisory_url": f"https://github.example/advisories/{ghsa}",
            }
            for ghsa in vulnerabilities
        ],
    }


CHANGES = {
    "alpha": [
        change("removed", "core", "1.0", [A]),
        change("added", "core", "2.0"),
        change("added", "plugin", "1.0", [A, B]),
    ],
    "beta": [],
    "empty": [],
}


def sbom(name):
    packages = (
        []
        if name == "empty"
        else [
            {
                "SPDXID": "SPDXRef-root",
                "name": f"{OWNER}/{name}",
                "versionInfo": "main",
                "downloadLocation": "NOASSERTION",
                "filesAnalyzed": False,
                "externalRefs": [],
            },
            {
                "SPDXID": "SPDXRef-core",
                "name": "core",
                "versionInfo": "2.0" if name == "alpha" else ">= 1.0",
                "downloadLocation": "NOASSERTION",
                "filesAnalyzed": False,
                "licenseDeclared": "MIT",
                "externalRefs": [
                    {
                        "referenceCategory": "PACKAGE-MANAGER",
                        "referenceType": "purl",
                        "referenceLocator": "pkg:npm/core@2.0",
                    }
                ],
            },
        ]
    )
    document = {
        "SPDXID": "SPDXRef-DOCUMENT",
        "spdxVersion": "SPDX-2.3",
        "creationInfo": {"created": "2026-09-01T00:00:00Z", "creators": ["Tool: GitHub"]},
        "name": f"{OWNER}/{name}",
        "dataLicense": "CC0-1.0",
        "documentNamespace": f"https://spdx.example/{name}/snapshot-1",
        "packages": packages,
    }
    if name != "beta":
        document["relationships"] = (
            [
                {
                    "relationshipType": "DEPENDS_ON",
                    "spdxElementId": "SPDXRef-root",
                    "relatedSpdxElement": "SPDXRef-core",
                }
            ]
            if packages
            else []
        )
    return {"sbom": document}


def respond(request):
    path = request.url.path
    if not (
        path == "/advisories"
        or path.startswith(
            (
                "/advisories/GHSA-deps-",
                "/repos/dependency-fixture/",
                "/orgs/dependency-fixture",
                "/users/dependency-fixture",
            )
        )
    ):
        return None
    if request.method != "GET":
        raise AssertionError(f"Unexpected dependency method {request.method}")
    if os.environ.get("CROSSFIELD_GITHUB_API_LOG"):
        with Path(os.environ["CROSSFIELD_GITHUB_API_LOG"]).open("a") as log:
            log.write(json.dumps({"path": path, "query": request.url.query.decode()}) + "\n")
    headers = {"Cache-Control": "no-store", "X-RateLimit-Remaining": "5000"}

    def response(value, code=200, next_page=None):
        result_headers = dict(headers)
        if next_page:
            result_headers["Link"] = f'<{request.url.copy_set_param("page", str(next_page))}>; rel="next"'
        return httpx.Response(code, json=copy.deepcopy(value), headers=result_headers, request=request)

    def pages(rows):
        page = int(request.url.params.get("page", "1"))
        return response(rows[page - 1 : page], next_page=page + 1 if page < len(rows) else None)

    def filtered_alerts(rows):
        for param, field in [
            ("state", lambda row: row["state"]),
            ("severity", lambda row: row["security_vulnerability"]["severity"]),
            ("ecosystem", lambda row: row["dependency"]["package"]["ecosystem"]),
            ("package", lambda row: row["dependency"]["package"]["name"]),
            ("scope", lambda row: row["dependency"]["scope"]),
        ]:
            if request.url.params.get(param):
                rows = [row for row in rows if field(row) in request.url.params[param].split(",")]
        return rows

    def filtered_advisories(rows):
        state = request.url.params.get("state")
        return [row for row in rows if row["state"] == state] if state else rows

    if path == "/advisories":
        return pages(
            [row for row in GLOBAL_ADVISORIES if row["type"] == request.url.params.get("type", "reviewed")]
        )
    if path.startswith("/advisories/"):
        return response(next(row for row in GLOBAL_ADVISORIES if row["ghsa_id"] == path.rsplit("/", 1)[1]))
    if path in {f"/orgs/{OWNER}", f"/users/{OWNER}"}:
        return response({"id": 1100, "login": OWNER, "type": "Organization"})
    if path == f"/orgs/{OWNER}/repos":
        return pages(REPOSITORIES)
    if path == f"/orgs/{OWNER}/dependabot/alerts":
        return pages(
            filtered_alerts(
                [dict(row, repository=repo) for repo in REPOSITORIES for row in ALERTS[repo["name"]]]
            )
        )
    if path == f"/orgs/{OWNER}/security-advisories":
        return pages(filtered_advisories([row for rows in REPOSITORY_ADVISORIES.values() for row in rows]))
    for user in [ALICE, BOB]:
        if path == f"/users/{user['login']}":
            return response(user)
    parts = path.strip("/").split("/")
    if len(parts) < 3 or parts[:2] != ["repos", OWNER]:
        raise AssertionError(f"Unexpected dependency fixture path {path}")
    name, tail = parts[2], parts[3:]
    repository = next(repo for repo in REPOSITORIES if repo["name"] == name)
    if not tail:
        return response(repository)
    if tail[:2] == ["dependabot", "alerts"]:
        rows = ALERTS[name]
        return (
            pages(filtered_alerts(rows))
            if len(tail) == 2
            else response(next(row for row in rows if row["number"] == int(tail[2])))
        )
    if tail[0] == "security-advisories":
        rows = REPOSITORY_ADVISORIES[name]
        return (
            pages(filtered_advisories(rows))
            if len(tail) == 1
            else response(next(row for row in rows if row["ghsa_id"] == tail[1]))
        )
    if tail[:2] == ["dependency-graph", "compare"]:
        assert tail[2] == "main...topic", "Unexpected comparison fixture token"
        rows = CHANGES[name]
        manifest = request.url.params.get("name")
        return pages([row for row in rows if row["manifest"] == manifest] if manifest else rows)
    if tail == ["dependency-graph", "sbom"]:
        return response(sbom(name))
    raise AssertionError(f"Unexpected dependency fixture path {path}")


if __name__ == "__main__":
    api.open_client = lambda: httpx.Client(transport=httpx.MockTransport(respond), follow_redirects=True)
    main()
