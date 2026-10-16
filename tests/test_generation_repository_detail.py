"""Repository discovery and metadata reads preserve canonical and observation grains."""

from copy import deepcopy

import httpx
import pytest

from tests.helpers import install
from tests.test_generated_runtime import run
from tests.test_generation_artifacts import ROOT
from tests.test_generation_artifacts import pilot as pilot
from vgi_github.generated_runtime import GeneratedContractError

OWNER = "repository-detail-fixture"
ALPHA = OWNER + "/alpha"
DIGEST = "sha256:" + "a" * 64


@pytest.fixture
def details(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "tests/crossfield"))
    import repository_detail_fixture

    return repository_detail_fixture


def rows_for(contract, name, **arguments):
    entity = next(row for row in contract["functions"] if row["name"] == name)
    result = run(entity, {key: [value] for key, value in arguments.items()}, contract=contract)
    return [row for batch in result.batches for row in batch.to_pylist()]


def test_public_authenticated_and_fork_routes_hydrate_canonical_repositories(pilot, details, monkeypatch):
    _, contract, _ = pilot
    requests = install(monkeypatch, details.respond)
    public = rows_for(contract, "repositories", public_repositories=True)
    assert [r["repository_id"] for r in public] == [71001, 71002]
    assert [(r["repository_node_id"], r["repository_language"]) for r in public] == [
        ("R71001", "Python"),
        ("R71002", "Python"),
    ]
    assert (
        rows_for(contract, "repositories", public_repositories=True, public_repository_since_id=71001)
        == public[1:]
    )
    authenticated = rows_for(contract, "repositories", authenticated_user=True)
    assert [r["repository_id"] for r in authenticated] == [71001, 71002, 71003]
    assert authenticated[:2] == public
    assert (
        rows_for(contract, "repositories", authenticated_user=True, repository_visibility="private")
        == authenticated[2:]
    )
    assert (
        rows_for(contract, "repositories", authenticated_user=True, repository_access_type="public") == public
    )
    forks = rows_for(contract, "repositories", forks_of=ALPHA, repository_fork_sort="oldest")
    assert [r["repository_id"] for r in forks] == [71011, 71012]
    assert rows_for(contract, "repositories", repository=forks[0]["repository"]) == forks[:1]
    assert any(r.url.path == "/repositories" and r.url.params.get("since") == "71001" for r in requests)
    assert any(r.url.path.endswith("/forks") and r.url.params.get("page") == "2" for r in requests)


def test_fork_memberships_preserve_parent_and_child_roles(pilot, details, monkeypatch):
    _, contract, _ = pilot
    install(monkeypatch, details.respond)
    rows = rows_for(contract, "repository_fork_memberships", organization=OWNER)
    assert [(r["parent_repository_id"], r["repository_id"]) for r in rows] == [(71001, 71011), (71001, 71012)]
    assert all(r["parent_repository"] == ALPHA for r in rows)


def test_topics_error_occurrences_and_property_variants_keep_every_page(pilot, details, monkeypatch):
    _, contract, _ = pilot
    requests = install(monkeypatch, details.respond)
    topics = rows_for(contract, "repository_topics", organization=OWNER)
    assert [(r["repository_id"], r["topic"]) for r in topics] == [
        (71001, "analytics"),
        (71001, "python"),
        (71002, "analytics"),
    ]
    errors = rows_for(contract, "repository_codeowners_errors", organization=OWNER, codeowners_ref="topic/a")
    assert [(r["repository_id"], r["error_ordinal"], r["line"]) for r in errors] == [
        (71001, 1, 7),
        (71001, 2, 7),
        (71002, 1, 2),
    ]
    assert errors[0]["message"] == errors[1]["message"]
    assert errors[2]["source"] is None and errors[2]["suggestion"] is None
    props = rows_for(contract, "repository_property_values", repository=ALPHA)
    assert [r["property_name"] for r in props] == ["tier", "languages", "owner"]
    assert props[0]["value"]["variant_1"] == "gold" and props[0]["value"]["variant_2"] is None
    assert props[1]["value"]["variant_1"] is None and props[1]["value"]["variant_2"] == ["python", "sql"]
    assert props[2]["value"] is None
    assert any(r.url.path.endswith("/topics") and r.url.params.get("page") == "2" for r in requests)
    assert any(r.url.params.get("ref") == "topic/a" for r in requests)


def test_community_and_hash_observations_preserve_unknowns(pilot, details, monkeypatch):
    _, contract, _ = pilot
    install(monkeypatch, details.respond)
    rows = rows_for(contract, "repository_community_profiles", organization=OWNER)
    assert [(r["repository_id"], r["health_percentage"]) for r in rows] == [
        (71001, 100),
        (71002, 50),
        (71003, 0),
    ]
    assert all(r["files"]["readme"] is None and r["updated_at"] is None for r in rows)
    hashes = rows_for(contract, "repository_hash_observations", organization=OWNER)
    assert [r["hash_algorithm"] for r in hashes] == ["sha1", "sha256", "sha1"]


def test_organization_property_discovery_pages_hydrate_canonical_repository_assignments(
    pilot, details, monkeypatch
):
    _, contract, _ = pilot
    requests = install(monkeypatch, details.respond)
    rows = rows_for(contract, "repository_property_values", organization=OWNER)
    assert [(row["repository_id"], row["property_name"]) for row in rows] == [
        (71001, "tier"),
        (71001, "languages"),
        (71001, "owner"),
        (71002, "tier"),
    ]
    assert rows[0]["value"]["variant_1"] == "gold"
    assert rows[1]["value"]["variant_2"] == ["python", "sql"]
    assert rows[2]["value"] is None
    assert rows[3]["value"]["variant_1"] == "silver"
    discovery = [request for request in requests if request.url.path == f"/orgs/{OWNER}/properties/values"]
    assert [request.url.params.get("page", "1") for request in discovery] == ["1", "2", "3"]
    for name in ["alpha", "beta", "empty"]:
        assert any(request.url.path == f"/repos/{OWNER}/{name}" for request in requests)
        assert any(request.url.path == f"/repos/{OWNER}/{name}/properties/values" for request in requests)
    assert any(
        request.url.path == f"/repos/{OWNER}/alpha/properties/values"
        and request.url.params.get("page") == "3"
        for request in requests
    )


def test_contributors_retain_anonymous_occurrences_and_empty_204(pilot, details, monkeypatch):
    _, contract, _ = pilot
    requests = install(monkeypatch, details.respond)
    rows = rows_for(
        contract, "repository_contributor_observations", organization=OWNER, contributor_anonymous="true"
    )
    assert [
        (r["repository_id"], r["contributor_ordinal"], r["contributor_id"], r["contributions"]) for r in rows
    ] == [(71001, 1, 78101, 5), (71001, 2, None, 3), (71001, 3, None, 2), (71002, 1, 78102, 7)]
    assert rows[1]["email"] == "author@example.test" and rows[2]["email"] is None
    linked = rows_for(contract, "repository_contributor_observations", organization=OWNER)
    assert [r["contributions"] for r in linked] == [5, 7]
    assert (
        rows_for(
            contract,
            "repository_contributor_observations",
            repository=OWNER + "/empty",
            contributor_anonymous="true",
        )
        == []
    )
    assert any(r.url.path.endswith("/contributors") and r.url.params.get("page") == "3" for r in requests)


def test_permission_roles_and_membership_checks_are_distinct_observations(pilot, details, monkeypatch):
    _, contract, _ = pilot
    install(monkeypatch, details.respond)
    rows = rows_for(
        contract, "repository_collaborator_permissions", organization=OWNER, user="repository-detail-alice"
    )
    assert [(r["permission"], r["role_name"], r["user_id"]) for r in rows] == [
        ("write", "maintain", 78101),
        ("none", "none", None),
        ("read", "custom-reader", 78101),
    ]
    assert rows[1]["requested_user"] == "repository-detail-alice" and rows[1]["user"] is None
    checks = rows_for(
        contract, "repository_collaborator_checks", organization=OWNER, user="repository-detail-alice"
    )
    assert [(r["repository_id"], r["status_code"]) for r in checks] == [
        (71001, 204),
        (71002, 404),
        (71003, 204),
    ]


def test_invitation_routes_share_ids_and_keep_optional_actor_roles(pilot, details, monkeypatch):
    _, contract, _ = pilot
    install(monkeypatch, details.respond)
    all_rows = rows_for(contract, "repository_invitations", organization=OWNER)
    caller = rows_for(contract, "repository_invitations", authenticated_user=True)
    assert [r["invitation_id"] for r in all_rows] == [79001, 79002, 79003]
    assert caller == [all_rows[0], all_rows[2]]
    assert all_rows[0]["invitee_id"] == 78101 and all_rows[0]["inviter_id"] == 78102
    assert all_rows[1]["invitee_id"] is None and all_rows[1]["expired"] is True
    assert all_rows[2]["inviter_id"] is None and all_rows[2]["expired"] is None


def test_attestation_envelopes_keep_pages_without_claiming_verification(pilot, details, monkeypatch):
    _, contract, _ = pilot
    requests = install(monkeypatch, details.respond)
    rows = rows_for(
        contract,
        "attestation_envelopes",
        organization=OWNER,
        attestation_subject_digest=DIGEST,
        attestation_predicate_type="provenance",
    )
    assert all(r["retrieval_scope_type"] == "organization" for r in rows)
    assert all(r["retrieval_scope_id"] == 71000 for r in rows)
    assert [(r["repository_id"], r["attestation_ordinal"], r["reported_repository_id"]) for r in rows] == [
        (71001, 1, 71001),
        (None, 2, None),
        (71002, 3, 71002),
    ]
    assert all(r["repository"] is None for r in rows)
    assert rows[1]["bundle_url"] is None and rows[2]["bundle_media_type"] is None
    assert any(r.url.params.get("after") == "2" for r in requests)
    assert all(r.url.host == "api.github.com" for r in requests)
    wrong = deepcopy(details.ATTESTATIONS["alpha"])
    wrong[0]["repository_id"] = 99999
    monkeypatch.setitem(details.ATTESTATIONS, "alpha", wrong)
    with pytest.raises(GeneratedContractError, match="reported_repository_id"):
        rows_for(contract, "attestation_envelopes", repository=ALPHA, attestation_subject_digest=DIGEST)


def test_malformed_200_contributor_response_is_not_empty(pilot, details, monkeypatch):
    _, contract, _ = pilot

    def invalid(request):
        if request.url.path.endswith("/contributors"):
            return httpx.Response(200, json={}, request=request)
        return details.respond(request)

    install(monkeypatch, invalid)
    with pytest.raises(GeneratedContractError):
        rows_for(contract, "repository_contributor_observations", repository=ALPHA)


@pytest.mark.parametrize(
    "name,arguments",
    [
        ("repositories", {"public_repositories": False}),
        (
            "repositories",
            {
                "authenticated_user": True,
                "repository_access_type": "public",
                "repository_visibility": "public",
            },
        ),
        (
            "repositories",
            {"authenticated_user": True, "repository_access_type": "all", "repository_affiliation": "owner"},
        ),
        ("repositories", {"forks_of": ALPHA, "repository": ALPHA}),
        ("repository_collaborator_checks", {"repository": ALPHA}),
        ("repository_collaborator_permissions", {"user": "repository-detail-alice"}),
        ("attestation_envelopes", {"repository": ALPHA}),
        ("repository_contributor_observations", {"repository": ALPHA, "contributor_anonymous": "no"}),
    ],
)
def test_invalid_population_selectors_fail_without_http(pilot, details, monkeypatch, name, arguments):
    _, contract, _ = pilot
    requests = install(monkeypatch, details.respond)
    with pytest.raises(GeneratedContractError):
        rows_for(contract, name, **arguments)
    assert requests == []


def test_unrecognized_hash_algorithm_rejects_schema_drift(pilot, details, monkeypatch):
    _, contract, _ = pilot

    def respond(request):
        if request.url.path.endswith("/hash-algorithm"):
            return httpx.Response(200, json={"hash_algorithm": "future-hash"})
        return details.respond(request)

    install(monkeypatch, respond)
    with pytest.raises(GeneratedContractError, match="declared enum"):
        rows_for(contract, "repository_hash_observations", repository=ALPHA)
