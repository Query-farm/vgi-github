"""Independent security populations, canonical identities and typed dependency evidence."""

from copy import deepcopy

import httpx
import pytest

from scripts import generate_semantic_catalog as generator
from tests.helpers import install
from tests.test_generated_runtime import run
from tests.test_generation_artifacts import ROOT
from tests.test_generation_artifacts import pilot as pilot
from vgi_github.generated_runtime import GeneratedContractError
from vgi_github.generation.artifacts import validate_semantics
from vgi_github.generation.schema import compile_contract
from vgi_github.github_api import GitHubError


@pytest.fixture
def dependencies_api(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "tests/crossfield"))
    import dependencies_fixture

    return dependencies_fixture


def rows_for(contract, name, **arguments):
    entity = next(value for value in contract["functions"] if value["name"] == name)
    output = run(entity, {key: [value] for key, value in arguments.items()}, contract=contract)
    return [row for batch in output.batches for row in batch.to_pylist()]


def test_alert_organization_repository_and_lookup_share_qualified_identity(
    pilot, dependencies_api, monkeypatch
):
    _, contract, _ = pilot
    requests = install(monkeypatch, dependencies_api.respond)
    org = rows_for(contract, "dependabot_alerts", organization="dependency-fixture")
    assert [(row["repository_id"], row["alert_number"]) for row in org] == [
        (1101, 1),
        (1101, 2),
        (1101, 3),
        (1101, 4),
        (1102, 1),
    ]
    repo = rows_for(contract, "dependabot_alerts", repository="dependency-fixture/alpha")
    assert org[:4] == repo
    assert rows_for(
        contract, "dependabot_alerts", repository="dependency-fixture/alpha", dependabot_alert_number=2
    ) == [repo[1]]
    assert [row["state"] for row in repo] == ["open", "fixed", "dismissed", "auto_dismissed"]
    assert repo[0]["assignees"] == [{"id": 1201, "login": "dependency-fixture-alice", "type": "User"}]
    assert repo[2]["dismisser_id"] == 1202
    assert repo[2]["dependency_relationship"] == "unknown"
    assert any(request.url.params.get("page") == "5" for request in requests)


def test_alert_filters_and_repository_cohort_preserve_scope(pilot, dependencies_api, monkeypatch):
    _, contract, _ = pilot
    requests = install(monkeypatch, dependencies_api.respond)
    rows = rows_for(
        contract,
        "dependabot_alerts",
        organization="dependency-fixture",
        dependabot_state="open",
        dependabot_severity="high,critical",
        dependabot_ecosystem="npm",
        dependabot_package="core",
        dependabot_scope="runtime",
    )
    assert [(row["repository_id"], row["alert_number"]) for row in rows] == [(1101, 1), (1102, 1)]
    second = next(request for request in requests if request.url.params.get("page") == "2")
    assert second.url.params["state"] == "open"
    assert second.url.params["severity"] == "high,critical"
    assert (
        len(
            rows_for(
                contract,
                "dependabot_alerts",
                repositories=[
                    {"repository": "dependency-fixture/alpha"},
                    {"repository": "dependency-fixture/empty"},
                ],
            )
        )
        == 4
    )
    assert rows_for(contract, "dependabot_alerts", repositories=[]) == []


def test_global_and_repository_advisories_keep_identity_and_typed_patch_meaning(
    pilot, dependencies_api, monkeypatch
):
    _, contract, _ = pilot
    install(monkeypatch, dependencies_api.respond)
    global_rows = rows_for(contract, "security_advisories", advisory_type="reviewed")
    assert [row["ghsa_id"] for row in global_rows] == [dependencies_api.A, dependencies_api.B]
    exact = rows_for(contract, "security_advisories", global_advisory_id=dependencies_api.A)
    assert exact == [global_rows[0]]
    repo = rows_for(contract, "security_advisories", repository="dependency-fixture/alpha")
    assert [row["ghsa_id"] for row in repo] == [dependencies_api.A, dependencies_api.E]
    assert rows_for(
        contract, "security_advisories", repository="dependency-fixture/alpha", ghsa_id=dependencies_api.A
    ) == [repo[0]]
    assert global_rows[0]["ghsa_id"] == repo[0]["ghsa_id"]
    global_vulnerability, repo_vulnerability = (
        global_rows[0]["vulnerabilities"][0],
        repo[0]["vulnerabilities"][0],
    )
    assert (global_vulnerability["first_patched_version"], global_vulnerability["patched_versions"]) == (
        "2.0",
        None,
    )
    assert (repo_vulnerability["first_patched_version"], repo_vulnerability["patched_versions"]) == (
        None,
        ">= 2.0, < 3.0",
    )
    assert global_rows[0]["credits"][0]["state"] is None
    assert repo[0]["credits"][0]["state"] == "accepted"
    assert global_rows[0]["repository_id"] is None
    assert global_rows[0]["state"] is None
    assert repo[0]["advisory_type"] is None
    assert (repo[0]["advisory_author_id"], repo[0]["advisory_publisher_id"]) == (1201, 1202)
    assert repo[1]["published_at"] is None


def test_organization_advisories_do_not_invent_repository_from_private_fork_or_url(
    pilot, dependencies_api, monkeypatch
):
    _, contract, _ = pilot
    requests = install(monkeypatch, dependencies_api.respond)
    rows = rows_for(contract, "security_advisories", organization="dependency-fixture")
    assert [row["ghsa_id"] for row in rows] == [dependencies_api.A, dependencies_api.E, dependencies_api.B]
    assert all(row["repository_id"] is None and row["repository"] is None for row in rows)
    assert all(request.url.path == "/orgs/dependency-fixture/security-advisories" for request in requests)
    assert [
        row["ghsa_id"]
        for row in rows_for(
            contract, "security_advisories", organization="dependency-fixture", advisory_state="draft"
        )
    ] == [dependencies_api.E]


def test_global_malware_and_unknown_severity_are_explicit_populations(pilot, dependencies_api, monkeypatch):
    _, contract, _ = pilot
    install(monkeypatch, dependencies_api.respond)
    assert [row["ghsa_id"] for row in rows_for(contract, "security_advisories", advisory_type="malware")] == [
        dependencies_api.C
    ]
    unreviewed = rows_for(contract, "security_advisories", advisory_type="unreviewed")
    assert [(row["ghsa_id"], row["severity"]) for row in unreviewed] == [(dependencies_api.D, "unknown")]


def test_dependency_changes_keep_manifest_version_direction_and_vulnerability_associations(
    pilot, dependencies_api, monkeypatch
):
    _, contract, _ = pilot
    requests = install(monkeypatch, dependencies_api.respond)
    rows = rows_for(
        contract,
        "dependency_changes",
        repository="dependency-fixture/alpha",
        dependency_compare="main...topic",
    )
    assert [
        (row["name"], row["version"], row["change_type"], len(row["vulnerabilities"])) for row in rows
    ] == [("core", "1.0", "removed", 1), ("core", "2.0", "added", 0), ("plugin", "1.0", "added", 2)]
    assert all(row["comparison"] == "main...topic" for row in rows)
    assert any(request.url.params.get("page") == "3" for request in requests)
    assert (
        rows_for(
            contract,
            "dependency_changes",
            repository="dependency-fixture/alpha",
            dependency_compare="main...topic",
            dependency_manifest="missing.lock",
        )
        == []
    )
    assert rows_for(contract, "dependency_changes", repositories=[], dependency_compare="main...topic") == []


def test_sbom_snapshot_preserves_nested_spdx_and_unknown_fields(pilot, dependencies_api, monkeypatch):
    _, contract, _ = pilot
    install(monkeypatch, dependencies_api.respond)
    rows = rows_for(contract, "dependency_sboms", organization="dependency-fixture")
    assert [(row["repository_id"], row["document_namespace"], len(row["packages"])) for row in rows] == [
        (1101, "https://spdx.example/alpha/snapshot-1", 2),
        (1102, "https://spdx.example/beta/snapshot-1", 2),
        (1103, "https://spdx.example/empty/snapshot-1", 0),
    ]
    assert rows[0]["packages"][1]["externalRefs"][0]["referenceLocator"] == "pkg:npm/core@2.0"
    assert rows[0]["packages"][0]["licenseConcluded"] is None
    assert rows[1]["packages"][1]["versionInfo"] == ">= 1.0"
    assert rows[1]["relationships"] is None
    assert rows[2]["relationships"] == []
    assert rows[0]["created_text"] == "2026-09-01T00:00:00Z"


@pytest.mark.parametrize(
    "name,arguments",
    [
        ("security_advisories", {}),
        ("security_advisories", {"advisory_type": "all"}),
        (
            "security_advisories",
            {"global_advisory_id": "GHSA-deps-aaaa-0001", "repository": "dependency-fixture/alpha"},
        ),
        ("security_advisories", {"ghsa_id": "GHSA-deps-aaaa-0001"}),
        ("dependabot_alerts", {"dependabot_alert_number": 1}),
        (
            "dependabot_alerts",
            {
                "repository": "dependency-fixture/alpha",
                "dependabot_alert_number": 1,
                "dependabot_state": "open",
            },
        ),
        ("dependency_changes", {"repository": "dependency-fixture/alpha"}),
    ],
)
def test_invalid_security_populations_fail_before_http(pilot, monkeypatch, name, arguments):
    _, contract, _ = pilot
    install(monkeypatch, lambda request: pytest.fail("Invalid selector made an API request"))
    with pytest.raises(GeneratedContractError):
        rows_for(contract, name, **arguments)


@pytest.mark.parametrize(
    "entity,arguments,suffix,field,value",
    [
        (
            "dependabot_alerts",
            {"repository": "dependency-fixture/alpha", "dependabot_alert_number": 1},
            "/alerts/1",
            "number",
            2,
        ),
        (
            "security_advisories",
            {"global_advisory_id": "GHSA-deps-aaaa-0001"},
            "/advisories/GHSA-deps-aaaa-0001",
            "ghsa_id",
            "GHSA-deps-aaaa-0002",
        ),
        (
            "security_advisories",
            {"repository": "dependency-fixture/alpha", "ghsa_id": "GHSA-deps-aaaa-0001"},
            "/security-advisories/GHSA-deps-aaaa-0001",
            "ghsa_id",
            "GHSA-deps-aaaa-0002",
        ),
    ],
)
def test_lookup_identity_mismatch_fails(
    pilot, dependencies_api, monkeypatch, entity, arguments, suffix, field, value
):
    _, contract, _ = pilot

    def respond(request):
        response = dependencies_api.respond(request)
        if request.url.path.endswith(suffix):
            payload = deepcopy(response.json())
            payload[field] = value
            return httpx.Response(200, json=payload, headers=response.headers, request=request)
        return response

    install(monkeypatch, respond)
    with pytest.raises(GeneratedContractError, match="row assertion failed"):
        rows_for(contract, entity, **arguments)


def test_later_organization_alert_page_error_cannot_return_successful_prefix(
    pilot, dependencies_api, monkeypatch
):
    _, contract, _ = pilot

    def respond(request):
        if request.url.path.endswith("/dependabot/alerts") and request.url.params.get("page") == "2":
            return httpx.Response(403, json={"message": "Alert visibility changed"}, request=request)
        return dependencies_api.respond(request)

    install(monkeypatch, respond)
    with pytest.raises(GitHubError, match="Alert visibility changed"):
        rows_for(contract, "dependabot_alerts", organization="dependency-fixture")


def test_duplicate_dependency_coordinate_fails_qualification(pilot, dependencies_api, monkeypatch):
    _, contract, _ = pilot
    monkeypatch.setitem(dependencies_api.CHANGES, "alpha", [dependencies_api.CHANGES["alpha"][0]] * 2)
    install(monkeypatch, dependencies_api.respond)
    with pytest.raises(GeneratedContractError, match="duplicate row identity"):
        rows_for(
            contract,
            "dependency_changes",
            repository="dependency-fixture/alpha",
            dependency_compare="main...topic",
        )


def test_advisory_union_padding_and_navigation_are_explicit(pilot):
    overlay, contract, _ = pilot
    validate_semantics(contract, overlay)
    entity = next(row for row in overlay["functions"] if row["name"] == "security_advisories")
    assert entity["nullable_struct_fields"] == [
        "vulnerabilities[].first_patched_version",
        "vulnerabilities[].patched_versions",
        "credits[].state",
    ]
    relationships = {row["name"]: row for row in contract["relationships"]}
    assert relationships["dependabot_alerts_to_advisories"]["analytical"] is False
    assert relationships["dependabot_alerts_to_advisories"]["retrievals"] == [
        {"direction": "forward", "route": "global_lookup", "bindings": {"global_advisory_id": "ghsa_id"}}
    ]


@pytest.mark.parametrize(
    "mutation,error",
    [
        ("missing", "requires explicit nullable_struct_fields approval"),
        ("extra", "must name fields absent from at least one route"),
    ],
)
def test_advisory_nested_absence_requires_exact_reviewed_paths(pilot, mutation, error):
    overlay, _, _ = pilot
    entity = next(row for row in overlay["functions"] if row["name"] == "security_advisories")
    if mutation == "missing":
        entity["nullable_struct_fields"].remove("vulnerabilities[].patched_versions")
    else:
        entity["nullable_struct_fields"].append("vulnerabilities[].package")
    specs, sdl, _ = generator.locked_inputs(ROOT, overlay)
    with pytest.raises(ValueError, match=error):
        compile_contract(specs, sdl, overlay)
