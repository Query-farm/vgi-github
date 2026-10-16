"""Artifact metadata keeps optional identity and cross-route occurrence scope explicit."""

import json
from copy import deepcopy

import httpx
import pytest

from tests.helpers import install
from tests.test_generated_runtime import run
from tests.test_generation_artifacts import ROOT
from tests.test_generation_artifacts import pilot as pilot
from vgi_github.generated_runtime import GeneratedContractError

ORG = "provenance-fixture"
USER = "provenance-user"
DIGEST = "sha256:" + "a" * 64
OTHER = "sha256:" + "b" * 64


@pytest.fixture
def provenance(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "tests/crossfield"))
    import artifact_provenance_fixture

    return artifact_provenance_fixture


def rows_for(contract, name, **args):
    f = next(f for f in contract["functions"] if f["name"] == name)
    result = run(f, {k: [v] for k, v in args.items()}, contract=contract)
    return [r for batch in result.batches for r in batch.to_pylist()]


@pytest.mark.parametrize(
    "name,args,key,expected",
    [
        (
            "artifact_deployment_records",
            {"organization": ORG, "artifact_subject_digest": DIGEST},
            "record_ordinal",
            [1, 2, 3],
        ),
        (
            "artifact_storage_records",
            {"organization": ORG, "artifact_subject_digest": DIGEST},
            "record_ordinal",
            [1, 2],
        ),
        (
            "artifact_storage_records",
            {"organization": ORG, "artifact_subject_digest": OTHER},
            "record_ordinal",
            [],
        ),
        (
            "artifact_metadata_jobs",
            {"organization": ORG, "artifact_cluster": "production", "artifact_metadata_job_id": 57001},
            "status",
            ["completed"],
        ),
        (
            "artifact_metadata_jobs",
            {"organization": ORG, "artifact_cluster": "production", "artifact_metadata_job_id": 57002},
            "status",
            ["pending"],
        ),
        (
            "repositories",
            {"organization": ORG, "attested_repositories": True},
            "repository_id",
            [54101, 54102],
        ),
        (
            "repositories",
            {"organization": ORG, "attested_repositories": True, "attestation_predicate_type": "sbom"},
            "repository_id",
            [54101],
        ),
        (
            "attestation_envelopes",
            {"organization": ORG, "attestation_subject_digest": DIGEST},
            "attestation_ordinal",
            [1, 2, 3],
        ),
        (
            "attestation_envelopes",
            {"user": USER, "attestation_subject_digest": DIGEST},
            "attestation_ordinal",
            [1, 2],
        ),
        (
            "attestation_envelopes",
            {"user": USER, "attestation_subject_digest": OTHER},
            "attestation_ordinal",
            [],
        ),
    ],
)
def test_artifact_retrieval_populations(pilot, provenance, monkeypatch, name, args, key, expected):
    _, contract, _ = pilot
    install(monkeypatch, provenance.respond)
    assert [r[key] for r in rows_for(contract, name, **args)] == expected


def test_missing_record_ids_preserve_occurrences_typed_tags_and_raw_times(pilot, provenance, monkeypatch):
    _, contract, _ = pilot
    install(monkeypatch, provenance.respond)
    records = rows_for(
        contract, "artifact_deployment_records", organization=ORG, artifact_subject_digest=DIGEST
    )
    assert [r["record_id"] for r in records] == [55001, None, None]
    assert dict(records[0]["tags"]) == {"env": "prod", "team": "platform"}
    assert records[1]["tags"] == [] and records[2]["tags"] is None
    assert records[0]["runtime_risks"] == ["internet-exposed", "sensitive-data"]
    assert records[1]["runtime_risks"] == [] and records[2]["runtime_risks"] is None
    assert records[1]["created_at_raw"] == "upstream-unformatted-time"
    assert records[2]["reported_digest"] is None and records[2]["artifact_subject_digest"] == DIGEST
    storage = rows_for(contract, "artifact_storage_records", organization=ORG, artifact_subject_digest=DIGEST)
    assert [r["registry_repository"] for r in storage] == ["bar", "archive"]
    assert storage[1]["record_id"] is None and storage[1]["updated_at_raw"] is None


def test_job_lifecycle_missing_values_remain_unknown(pilot, provenance, monkeypatch):
    _, contract, _ = pilot
    install(monkeypatch, provenance.respond)
    completed = rows_for(
        contract,
        "artifact_metadata_jobs",
        organization=ORG,
        artifact_cluster="production",
        artifact_metadata_job_id=57001,
    )[0]
    pending = rows_for(
        contract,
        "artifact_metadata_jobs",
        organization=ORG,
        artifact_cluster="production",
        artifact_metadata_job_id=57002,
    )[0]
    failed = rows_for(
        contract,
        "artifact_metadata_jobs",
        organization=ORG,
        artifact_cluster="production",
        artifact_metadata_job_id=57003,
    )[0]
    assert completed["mutated_record_count"] == 5 and completed["started_at"].year == 2026
    assert pending["mutated_record_count"] is None and pending["started_at"] is None
    assert failed["status"] == "failed" and failed["mutated_record_count"] is None
    assert "errors" not in failed


def test_attestation_ordinals_are_scope_qualified_and_unknown_repository_rows_survive(
    pilot, provenance, monkeypatch
):
    _, contract, _ = pilot
    requests = install(monkeypatch, provenance.respond)
    org = rows_for(contract, "attestation_envelopes", organization=ORG, attestation_subject_digest=DIGEST)
    user = rows_for(contract, "attestation_envelopes", user=USER, attestation_subject_digest=DIGEST)
    repo = rows_for(
        contract, "attestation_envelopes", repository=f"{ORG}/alpha", attestation_subject_digest=DIGEST
    )
    assert [(r["retrieval_scope_type"], r["retrieval_scope_id"], r["attestation_ordinal"]) for r in org] == [
        ("organization", 54000, 1),
        ("organization", 54000, 2),
        ("organization", 54000, 3),
    ]
    assert [(r["retrieval_scope_type"], r["retrieval_scope_id"]) for r in user] == [
        ("user", 54001),
        ("user", 54001),
    ]
    assert (repo[0]["retrieval_scope_type"], repo[0]["retrieval_scope_id"]) == ("repository", 54101)
    assert org[0]["repository_id"] == 54101 and org[0]["repository"] is None
    assert org[2]["repository_id"] is None and user[1]["repository_id"] is None
    assert org[0]["retrieval_organization_id"] == 54000 and org[0]["retrieval_user_id"] is None
    assert user[0]["retrieval_user_login"] == USER and user[0]["retrieval_organization_id"] is None
    assert repo[0]["retrieval_organization_id"] is None and repo[0]["retrieval_user_id"] is None
    assert all(r.url.host == "api.github.com" for r in requests)
    assert all("evidence.example" not in str(r.url) for r in requests)
    assert any(r.url.params.get("after") == "3" for r in requests)


def test_optional_total_count_is_not_required_for_returned_occurrences(pilot, provenance, monkeypatch):
    _, contract, _ = pilot

    def without_count(request):
        response = provenance.respond(request)
        if request.url.path.endswith("/storage-records"):
            body = response.json()
            body.pop("total_count")
            return httpx.Response(200, json=body, request=request)
        return response

    install(monkeypatch, without_count)
    assert (
        len(rows_for(contract, "artifact_storage_records", organization=ORG, artifact_subject_digest=DIGEST))
        == 2
    )


def test_reported_digest_mismatch_fails_without_silently_filtering_rows(pilot, provenance, monkeypatch):
    _, contract, _ = pilot
    changed = deepcopy(provenance.DEPLOYMENTS)
    changed[0]["digest"] = OTHER
    monkeypatch.setattr(provenance, "DEPLOYMENTS", changed)
    install(monkeypatch, provenance.respond)
    with pytest.raises(GeneratedContractError, match="reported_digest|assertion"):
        rows_for(contract, "artifact_deployment_records", organization=ORG, artifact_subject_digest=DIGEST)


def test_directory_identity_drift_and_later_attestation_error_fail(pilot, provenance, monkeypatch):
    _, contract, _ = pilot

    def drift(request):
        response = provenance.respond(request)
        if request.url.path == f"/repos/{ORG}/alpha":
            value = response.json()
            value["id"] = 99999
            return httpx.Response(200, json=value, request=request)
        return response

    install(monkeypatch, drift)
    with pytest.raises(GeneratedContractError, match="repository_id|assertion"):
        rows_for(contract, "repositories", organization=ORG, attested_repositories=True)

    def denied(request):
        if (
            request.url.path.startswith(f"/orgs/{ORG}/attestations/")
            and request.url.params.get("after") == "2"
        ):
            return httpx.Response(403, json={"message": "Page denied"}, request=request)
        return provenance.respond(request)

    install(monkeypatch, denied)
    with pytest.raises(Exception, match="403|denied"):
        rows_for(contract, "attestation_envelopes", organization=ORG, attestation_subject_digest=DIGEST)


def test_ambiguous_user_201_is_not_a_complete_attestation_population(pilot, provenance, monkeypatch):
    _, contract, _ = pilot

    def pending(request):
        if "/attestations/" in request.url.path:
            return httpx.Response(201, json=None, request=request)
        return provenance.respond(request)

    install(monkeypatch, pending)
    with pytest.raises(GeneratedContractError, match="201|status"):
        rows_for(contract, "attestation_envelopes", user=USER, attestation_subject_digest=DIGEST)


@pytest.mark.parametrize(
    "name,args",
    [
        ("artifact_storage_records", {"organization": ORG, "artifact_subject_digest": "short"}),
        ("artifact_storage_records", {"organization": ORG, "artifact_subject_digest": DIGEST + "a"}),
        ("artifact_storage_records", {"organization": ORG, "artifact_subject_digest": "sha512:" + "a" * 64}),
        ("artifact_storage_records", {"organization": ORG, "artifact_subject_digest": "sha256:" + "A" * 64}),
        ("artifact_storage_records", {"organization": ORG, "artifact_subject_digest": "sha256:" + "g" * 64}),
        ("artifact_storage_records", {"organization": ORG, "artifact_subject_digest": DIGEST + "\n"}),
        ("artifact_metadata_jobs", {"organization": ORG, "artifact_metadata_job_id": 57001}),
        ("repositories", {"organization": ORG, "attested_repositories": True, "repository": f"{ORG}/alpha"}),
        ("attestation_envelopes", {"organization": ORG, "user": USER, "attestation_subject_digest": DIGEST}),
    ],
)
def test_invalid_or_conflicting_artifact_scopes_reject_before_http(
    pilot, provenance, monkeypatch, name, args
):
    _, contract, _ = pilot
    requests = install(monkeypatch, provenance.respond)
    with pytest.raises(
        GeneratedContractError, match="argument|required|at least|at most|pattern|route|parameter"
    ):
        rows_for(contract, name, **args)
    assert requests == []


def test_provenance_source_inventory_and_untyped_payload_limits_are_explicit():
    domain = json.loads((ROOT / "generation/domains/artifact_provenance.json").read_text())
    assert {s["transport"]["operation_id"] for s in domain["entities"]} == {
        "orgs/list-artifact-deployment-records",
        "orgs/list-artifact-storage-records",
        "orgs/get-cluster-deployment-records-job",
        "orgs/list-attestation-repositories",
        "repos/get",
        "orgs/list-attestations",
        "users/list-attestations",
    }
    assert {f["name"] for f in domain["functions"]} == {
        "artifact_deployment_records",
        "artifact_storage_records",
        "artifact_metadata_jobs",
    }
    assert (
        "uncovered"
        in next(f for f in domain["functions"] if f["name"] == "artifact_metadata_jobs")["description"]
    )
