"""Qualified package identity across account populations and version retrievals."""

import json
from copy import deepcopy

import httpx
import pytest

from tests.helpers import install
from tests.test_generated_runtime import run
from tests.test_generation_artifacts import ROOT
from tests.test_generation_artifacts import pilot as pilot
from vgi_github.generated_runtime import GeneratedContractError
from vgi_github.generation.artifacts import build_model, validate_semantics
from vgi_github.github_api import GitHubError


@pytest.fixture
def packages_api(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "tests/crossfield"))
    import packages_fixture

    return packages_fixture


def rows_for(contract, name, **arguments):
    entity = next(value for value in contract["functions"] if value["name"] == name)
    output = run(entity, {key: [value] for key, value in arguments.items()}, contract=contract)
    return [row for batch in output.batches for row in batch.to_pylist()]


@pytest.mark.parametrize(
    "selector,owner_id,kind,package_ids,version_ids,shared_id,version_id",
    [
        ({"organization": "package-fixture-org"}, 901, "Organization", [11, 12], [111, 112, 121], 11, 111),
        ({"user": "package-fixture-user"}, 902, "User", [21], [211], 21, 211),
        ({"authenticated_user": True}, 903, "User", [31, 32], [311], 31, 311),
    ],
)
def test_all_account_package_and_version_routes(
    pilot,
    packages_api,
    monkeypatch,
    selector,
    owner_id,
    kind,
    package_ids,
    version_ids,
    shared_id,
    version_id,
):
    _, contract, _ = pilot
    requests = install(monkeypatch, packages_api.respond)
    listed = rows_for(contract, "packages", package_type="container", **selector)
    assert [row["package_id"] for row in listed] == package_ids
    assert {(row["package_owner_kind"], row["package_owner_id"]) for row in listed} == {(kind, owner_id)}
    assert rows_for(contract, "packages", package_type="container", package_name="shared", **selector) == [
        listed[0]
    ]
    conflict = rows_for(contract, "packages", package_population="docker_migration_conflicts", **selector)
    assert [(row["package_name"], row["package_type"]) for row in conflict] == [("legacy", "docker")]
    versions = rows_for(contract, "package_versions", package_type="container", **selector)
    assert [row["package_version_id"] for row in versions] == version_ids
    exact = rows_for(
        contract,
        "package_versions",
        package_type="container",
        package_name="shared",
        package_version_id=version_id,
        **selector,
    )
    assert exact == [versions[0]]
    assert exact[0]["package_id"] == shared_id
    assert all(request.method == "GET" for request in requests)


@pytest.mark.parametrize(
    "selector,expected",
    [
        ({"organization": "package-fixture-org"}, 113),
        ({"authenticated_user": True}, 312),
    ],
)
def test_deleted_versions_are_explicit_and_preserve_creation_and_deletion(
    pilot, packages_api, monkeypatch, selector, expected
):
    _, contract, _ = pilot
    requests = install(monkeypatch, packages_api.respond)
    rows = rows_for(
        contract, "package_versions", package_type="container", package_version_state="deleted", **selector
    )
    assert [row["package_version_id"] for row in rows] == [expected]
    assert rows[0]["deleted_at"] is not None
    assert rows[0]["created_at"] < rows[0]["deleted_at"]
    assert all(
        request.url.params.get("state") == "deleted"
        for request in requests
        if request.url.path.endswith("/versions")
    )
    assert (
        rows_for(
            contract,
            "package_versions",
            package_type="container",
            package_name="shared",
            package_version_state="deleted",
            **selector,
        )
        == rows
    )


def test_nullable_response_owner_uses_authenticated_account_identity(pilot, packages_api, monkeypatch):
    _, contract, _ = pilot
    requests = install(monkeypatch, packages_api.respond)
    rows = rows_for(contract, "packages", authenticated_user=True, package_type="container")
    assert [(row["package_owner_id"], row["reported_owner_id"], row["repository_id"]) for row in rows] == [
        (903, None, 910),
        (903, 903, None),
    ]
    assert requests[0].url.path == "/user"
    assert {row["package_access_mode"] for row in rows} == {"authenticated"}


def test_container_tags_are_complete_values_not_version_identity(pilot, packages_api, monkeypatch):
    _, contract, _ = pilot
    install(monkeypatch, packages_api.respond)
    rows = rows_for(
        contract,
        "package_versions",
        organization="package-fixture-org",
        package_type="container",
        package_name="shared",
    )
    assert [row["container_tags"] for row in rows] == [["v1", "latest"], ["v2", "latest"]]
    assert [row["package_version_id"] for row in rows] == [111, 112]
    assert all(row["deleted_at"] is None for row in rows)


def test_named_user_private_object_error_is_not_an_empty_package(pilot, packages_api, monkeypatch):
    _, contract, _ = pilot
    install(monkeypatch, packages_api.respond)
    with pytest.raises(GitHubError, match="404"):
        rows_for(
            contract,
            "packages",
            user="package-fixture-current",
            package_type="container",
            package_name="shared",
        )
    assert (
        rows_for(
            contract, "packages", authenticated_user=True, package_type="container", package_name="shared"
        )[0]["package_id"]
        == 31
    )


@pytest.mark.parametrize(
    "name,args",
    [
        ("packages", {"organization": "package-fixture-org"}),
        ("packages", {"authenticated_user": False, "package_type": "container"}),
        (
            "packages",
            {
                "user": "package-fixture-user",
                "organization": "package-fixture-org",
                "package_type": "container",
            },
        ),
        ("packages", {"organization": "package-fixture-org", "package_type": "unknown"}),
        (
            "packages",
            {
                "organization": "package-fixture-org",
                "package_population": "docker_migration_conflicts",
                "package_name": "shared",
            },
        ),
        (
            "package_versions",
            {"user": "package-fixture-user", "package_type": "container", "package_version_state": "deleted"},
        ),
        (
            "package_versions",
            {
                "organization": "package-fixture-org",
                "package_type": "container",
                "package_name": "shared",
                "package_version_id": 111,
                "package_version_state": "active",
            },
        ),
    ],
)
def test_invalid_package_selections_fail_before_http(pilot, monkeypatch, name, args):
    _, contract, _ = pilot
    install(monkeypatch, lambda request: pytest.fail("Invalid package selector made an API request"))
    with pytest.raises(GeneratedContractError):
        rows_for(contract, name, **args)


@pytest.mark.parametrize(
    "entity,arguments,tail,field,value",
    [
        ("packages", {"package_name": "shared"}, "/container/shared", "name", "other"),
        ("packages", {"package_name": "shared"}, "/container/shared", "package_type", "npm"),
        (
            "package_versions",
            {"package_name": "shared", "package_version_id": 111},
            "/versions/111",
            "id",
            112,
        ),
    ],
)
def test_lookup_identity_mismatches_are_rejected(
    pilot, packages_api, monkeypatch, entity, arguments, tail, field, value
):
    _, contract, _ = pilot

    def respond(request):
        response = packages_api.respond(request)
        if request.url.path.endswith(tail):
            payload = deepcopy(response.json())
            payload[field] = value
            return httpx.Response(200, json=payload, headers=response.headers, request=request)
        return response

    install(monkeypatch, respond)
    with pytest.raises(GeneratedContractError, match="row assertion failed"):
        rows_for(contract, entity, organization="package-fixture-org", package_type="container", **arguments)


def test_later_version_page_error_does_not_become_a_complete_population(pilot, packages_api, monkeypatch):
    _, contract, _ = pilot

    def respond(request):
        if request.url.path.endswith("/container/shared/versions") and request.url.params.get("page") == "2":
            return httpx.Response(403, json={"message": "Version visibility changed"}, request=request)
        return packages_api.respond(request)

    install(monkeypatch, respond)
    with pytest.raises(GitHubError, match="Version visibility changed"):
        rows_for(
            contract,
            "package_versions",
            organization="package-fixture-org",
            package_type="container",
            package_name="shared",
        )


def test_package_parent_navigation_preserves_access_population(pilot):
    overlay, contract, _ = pilot
    validate_semantics(contract, overlay)
    relation = next(row for row in contract["relationships"] if row["name"] == "package_versions_to_packages")
    assert {(row["direction"], row["when"]["package_access_mode"]) for row in relation["retrievals"]} == {
        (direction, mode)
        for direction in ["forward", "reverse"]
        for mode in ["organization", "user", "authenticated"]
    }
    auth = [row for row in relation["retrievals"] if row["when"]["package_access_mode"] == "authenticated"]
    assert all(row["bindings"]["authenticated_user"] == {"literal": True} for row in auth)


@pytest.mark.parametrize(
    "mutation,error",
    [
        ("predicate_field", "declared scalar fields"),
        ("predicate_type", "literal does not match VARCHAR"),
        ("literal_type", "literal does not match BOOLEAN"),
        ("literal_enum", "outside the parameter enum"),
    ],
)
def test_package_navigation_rejects_invalid_conditions_and_literals(pilot, mutation, error):
    overlay, contract, _ = pilot
    relation = next(row for row in contract["relationships"] if row["name"] == "package_versions_to_packages")
    retrieval = next(
        row for row in relation["retrievals"] if row["when"]["package_access_mode"] == "authenticated"
    )
    if mutation == "predicate_field":
        retrieval["when"] = {"missing_access_mode": "authenticated"}
    elif mutation == "predicate_type":
        retrieval["when"] = {"package_access_mode": True}
    elif mutation == "literal_type":
        retrieval["bindings"]["authenticated_user"] = {"literal": "true"}
    else:
        retrieval["bindings"]["authenticated_user"] = {"literal": False}
    with pytest.raises(ValueError, match=error):
        validate_semantics(contract, overlay)


def test_package_repository_context_uses_conformance_and_keeps_exact_navigation(pilot):
    overlay, contract, _ = pilot
    model, _ = build_model(contract, overlay)
    relation = next(row for row in contract["relationships"] if row["name"] == "packages_to_repositories")
    assert relation["analytical"] is False
    assert relation["retrievals"] == [
        {"direction": "forward", "route": "lookup", "bindings": {"repository": "package_repository"}}
    ]
    assert "packages_to_repositories" not in model["policy"]["relationships"]
    assert "package_versions_to_packages" in model["policy"]["relationships"]
    metadata = model["policy"]["field_semantics"]
    assert metadata["packages.package_repository"]["shared_dimension"] == "github.repository.full_name.v1"
    assert metadata["packages.repository_id"]["shared_dimension"] == "github.repository.id.v1"
    published = json.loads(model["policy"]["tags"]["github.relationship_retrievals"])
    assert published["packages_to_repositories"] == relation["retrievals"]
    conformances = {item["id"]: item for item in model["conformances"]}
    assert conformances["github.packages.repository_id.v1"] == {
        "id": "github.packages.repository_id.v1",
        "domain": "github.repository",
        "fields": ["repositories.repository_id", "packages.repository_id"],
        "datatype": "Integer",
        "null_policy": "equal",
    }
    assert conformances["github.packages.repository_full_name.v1"] == {
        "id": "github.packages.repository_full_name.v1",
        "domain": "github.repository",
        "fields": ["repositories.repository", "packages.package_repository"],
        "datatype": "String",
        "null_policy": "equal",
    }
