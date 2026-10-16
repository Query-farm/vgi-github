"""Independent Actions populations and canonical identity across retrieval paths."""

import json
from copy import deepcopy

import httpx
import pytest

from tests.helpers import install
from tests.test_generated_runtime import run
from tests.test_generation_artifacts import ROOT
from tests.test_generation_artifacts import pilot as pilot
from vgi_github.generated_runtime import GeneratedContractError
from vgi_github.generation.artifacts import build_model


@pytest.fixture
def actions(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "tests/crossfield"))
    import actions_fixture

    return actions_fixture


def rows_for(contract, name, **arguments):
    entity = next(value for value in contract["functions"] if value["name"] == name)
    output = run(entity, {key: [value] for key, value in arguments.items()}, contract=contract)
    return [row for batch in output.batches for row in batch.to_pylist()]


@pytest.mark.parametrize(
    "name,arguments,key,expected",
    [
        ("workflows", {}, "workflow_id", [601, 602]),
        ("workflows", {"workflow_id": 601}, "workflow_id", [601]),
        ("workflow_runs", {}, "run_id", [1001, 1002, 1003]),
        ("workflow_runs", {"workflow_id": 601}, "run_id", [1001, 1002]),
        ("workflow_runs", {"run_id": 1001}, "run_id", [1001]),
        ("workflow_run_attempts", {"run_id": 1001, "attempt_number": 1}, "attempt_number", [1]),
        ("workflow_jobs", {}, "job_id", [2001, 2002, 2003, 2004]),
        ("workflow_jobs", {"workflow_id": 601}, "job_id", [2001, 2002, 2003]),
        ("workflow_jobs", {"run_id": 1001}, "job_id", [2001, 2002, 2003]),
        ("workflow_jobs", {"run_id": 1001, "attempt_number": 2}, "job_id", [2002, 2003]),
        ("workflow_jobs", {"job_id": 2001}, "job_id", [2001]),
        ("workflow_artifacts", {}, "artifact_id", [3001, 3002, 3003, 3004]),
        ("workflow_artifacts", {"run_id": 1001}, "artifact_id", [3001, 3002]),
        ("workflow_artifacts", {"workflow_id": 601}, "artifact_id", [3001, 3002]),
        ("workflow_artifacts", {"artifact_id": 3002}, "artifact_id", [3002]),
    ],
)
def test_actions_retrieval_populations(pilot, actions, monkeypatch, name, arguments, key, expected):
    _, contract, _ = pilot
    install(monkeypatch, actions.respond_with_baseline)
    rows = rows_for(contract, name, repository="example/alpha", **arguments)
    assert [row[key] for row in rows] == expected
    assert all(row["repository_id"] == 101 for row in rows)


@pytest.mark.parametrize(
    "name,key,lookup",
    [
        ("workflows", "workflow_id", {"workflow_id": 601}),
        ("workflow_runs", "run_id", {"run_id": 1001}),
        ("workflow_jobs", "job_id", {"job_id": 2001}),
        ("workflow_artifacts", "artifact_id", {"artifact_id": 3002}),
    ],
)
def test_list_and_lookup_share_canonical_fields(pilot, actions, monkeypatch, name, key, lookup):
    _, contract, _ = pilot
    install(monkeypatch, actions.respond_with_baseline)
    listed = rows_for(contract, name, repository="example/alpha")
    exact = rows_for(contract, name, repository="example/alpha", **lookup)
    assert exact == [row for row in listed if row[key] == lookup[key]]


def test_rerun_attempts_have_distinct_outcomes_and_actor_roles(pilot, actions, monkeypatch):
    _, contract, _ = pilot
    install(monkeypatch, actions.respond_with_baseline)
    latest = rows_for(contract, "workflow_runs", repository="example/alpha", run_id=1001)[0]
    first = rows_for(
        contract, "workflow_run_attempts", repository="example/alpha", run_id=1001, attempt_number=1
    )[0]
    assert (latest["run_attempt"], latest["conclusion"]) == (2, "success")
    assert (first["attempt_number"], first["conclusion"]) == (1, "failure")
    assert (latest["actor_login"], latest["triggering_actor_login"]) == ("alice", "bob")
    assert first["triggering_actor_login"] == "alice"


def test_artifact_missing_run_is_not_dropped_or_renamed(pilot, actions, monkeypatch):
    _, contract, _ = pilot
    install(monkeypatch, actions.respond_with_baseline)
    rows = rows_for(contract, "workflow_artifacts", repository="example/alpha")
    assert len(rows) == 4 and sum(row["size_in_bytes"] for row in rows) == 75
    assert {row["name"] for row in rows} == {"build-output"}
    assert rows[1]["expired"] is True and rows[1]["digest"] is None
    assert rows[3]["run_id"] is None


def test_jobs_include_prior_attempts_and_do_not_multiply_by_steps(pilot, actions, monkeypatch):
    _, contract, _ = pilot
    requests = install(monkeypatch, actions.respond_with_baseline)
    rows = rows_for(contract, "workflow_jobs", repository="example/alpha", run_id=1001)
    assert [(row["job_id"], row["run_attempt"]) for row in rows] == [(2001, 1), (2002, 2), (2003, 2)]
    assert sum(len(row["steps"]) for row in rows) == 5
    job_requests = [request for request in requests if request.url.path.endswith("/jobs")]
    assert len(job_requests) == 3 and all(request.url.params["filter"] == "all" for request in job_requests)


@pytest.mark.parametrize("name", ["workflows", "workflow_runs", "workflow_jobs", "workflow_artifacts"])
def test_empty_actions_population(pilot, actions, monkeypatch, name):
    _, contract, _ = pilot
    install(monkeypatch, actions.respond_with_baseline)
    assert rows_for(contract, name, repository="example/empty") == []


@pytest.mark.parametrize(
    "name,arguments",
    [
        ("workflow_run_attempts", {"repository": "example/alpha", "run_id": 1001}),
        ("workflow_run_attempts", {"repository": "example/alpha", "attempt_number": 1}),
        ("workflow_jobs", {"attempt_number": 1}),
        ("workflow_jobs", {"repository": "example/alpha", "job_id": 2001, "run_id": 1001}),
        ("workflow_artifacts", {"artifact_id": 3001}),
    ],
)
def test_invalid_actions_selectors_fail_before_http(pilot, monkeypatch, name, arguments):
    _, contract, _ = pilot
    install(monkeypatch, lambda request: pytest.fail("Invalid selectors must not fetch"))
    with pytest.raises(GeneratedContractError):
        rows_for(contract, name, **arguments)


def test_later_actions_page_failure_does_not_return_a_complete_population(pilot, actions, monkeypatch):
    _, contract, _ = pilot

    def respond(request):
        if request.url.path.endswith("/artifacts") and request.url.params.get("page") == "2":
            return httpx.Response(403, json={"message": "Fixture permission revoked"}, request=request)
        return actions.respond_with_baseline(request)

    install(monkeypatch, respond)
    with pytest.raises(Exception, match="403|permission revoked"):
        rows_for(contract, "workflow_artifacts", repository="example/alpha")


def test_missing_step_list_remains_unknown_not_a_synthetic_step(pilot, actions, monkeypatch):
    _, contract, _ = pilot
    changed = deepcopy(actions.JOBS)
    changed[0].pop("steps")
    monkeypatch.setattr(actions, "JOBS", changed)
    install(monkeypatch, actions.respond_with_baseline)
    rows = rows_for(contract, "workflow_jobs", repository="example/alpha", job_id=2001)
    assert rows[0]["steps"] is None


@pytest.mark.parametrize(
    "name,arguments,suffix",
    [
        ("workflows", {}, "/workflows"),
        ("workflow_runs", {}, "/runs"),
        ("workflow_jobs", {"run_id": 1001}, "/runs/1001/jobs"),
        ("workflow_artifacts", {}, "/artifacts"),
    ],
)
@pytest.mark.parametrize("corruption", ["missing_next", "missing_total", "changing_total", "stale_total"])
def test_incomplete_actions_listings_fail(pilot, actions, monkeypatch, name, arguments, suffix, corruption):
    _, contract, _ = pilot

    def respond(request):
        response = actions.respond_with_baseline(request)
        if not request.url.path.endswith(suffix):
            return response
        payload, headers = response.json(), dict(response.headers)
        page = int(request.url.params.get("page", "1"))
        if corruption == "missing_next" and page == 1:
            headers.pop("link", None)
        elif corruption == "missing_total":
            payload.pop("total_count")
        elif corruption == "changing_total" and page > 1:
            payload["total_count"] += 1
        elif corruption == "stale_total":
            payload["total_count"] += 10
        return httpx.Response(200, json=payload, headers=headers, request=request)

    install(monkeypatch, respond)
    with pytest.raises(GeneratedContractError, match="total_count|total count"):
        rows_for(contract, name, repository="example/alpha", **arguments)


@pytest.mark.parametrize(
    "name,arguments,suffix,column,value",
    [
        ("workflows", {"workflow_id": 601}, "/workflows/601", "id", 9999),
        ("workflow_runs", {"run_id": 1001}, "/runs/1001", "id", 9999),
        ("workflow_jobs", {"job_id": 2001}, "/jobs/2001", "id", 9999),
        ("workflow_artifacts", {"artifact_id": 3001}, "/artifacts/3001", "id", 9999),
        (
            "workflow_run_attempts",
            {"run_id": 1001, "attempt_number": 1},
            "/runs/1001/attempts/1",
            "run_attempt",
            2,
        ),
    ],
)
def test_wrong_lookup_identity_or_attempt_fails(
    pilot, actions, monkeypatch, name, arguments, suffix, column, value
):
    _, contract, _ = pilot

    def respond(request):
        response = actions.respond_with_baseline(request)
        if request.url.path.endswith(suffix):
            payload = response.json()
            payload[column] = value
            return httpx.Response(200, json=payload, headers=response.headers, request=request)
        return response

    install(monkeypatch, respond)
    with pytest.raises(GeneratedContractError, match="row assertion"):
        rows_for(contract, name, repository="example/alpha", **arguments)


def test_job_in_wrong_attempt_fails(pilot, actions, monkeypatch):
    _, contract, _ = pilot
    original = actions.respond_with_baseline

    def respond(request):
        response = original(request)
        if request.url.path.endswith("/attempts/2/jobs"):
            payload = response.json()
            payload["jobs"][0]["run_attempt"] = 1
            return httpx.Response(200, json=payload, headers=response.headers, request=request)
        return response

    install(monkeypatch, respond)
    with pytest.raises(GeneratedContractError, match="row assertion"):
        rows_for(contract, "workflow_jobs", repository="example/alpha", run_id=1001, attempt_number=2)


@pytest.mark.parametrize("run_link", ["absent", None, {}, {"id": 9999}])
def test_artifact_unknown_run_metadata_preserves_artifact_identity(pilot, actions, monkeypatch, run_link):
    _, contract, _ = pilot
    changed = deepcopy(actions.ARTIFACTS)
    if run_link == "absent":
        changed[0].pop("workflow_run")
    else:
        changed[0]["workflow_run"] = run_link
    monkeypatch.setattr(actions, "ARTIFACTS", changed)
    install(monkeypatch, actions.respond_with_baseline)
    rows = rows_for(contract, "workflow_artifacts", repository="example/alpha", artifact_id=3001)
    assert rows[0]["artifact_id"] == 3001
    assert rows[0]["run_id"] == (9999 if run_link == {"id": 9999} else None)
    assert rows[0]["head_sha"] is None


def test_optional_attempt_and_actors_may_be_absent(pilot, actions, monkeypatch):
    _, contract, _ = pilot
    changed = deepcopy(actions.ATTEMPTS)
    for field in ["run_attempt", "actor", "triggering_actor"]:
        changed[(1001, 1)].pop(field)
    monkeypatch.setattr(actions, "ATTEMPTS", changed)
    install(monkeypatch, actions.respond_with_baseline)
    row = rows_for(
        contract, "workflow_run_attempts", repository="example/alpha", run_id=1001, attempt_number=1
    )[0]
    assert row["attempt_number"] == 1 and row["run_attempt"] is None
    assert row["actor_id"] is None and row["triggering_actor_id"] is None


def test_optional_steps_are_not_explicitly_nullable(pilot, actions, monkeypatch):
    _, contract, _ = pilot
    changed = deepcopy(actions.JOBS)
    changed[0]["steps"] = None
    monkeypatch.setattr(actions, "JOBS", changed)
    install(monkeypatch, actions.respond_with_baseline)
    with pytest.raises(GeneratedContractError, match="NULL is not allowed"):
        rows_for(contract, "workflow_jobs", repository="example/alpha", job_id=2001)


def test_navigation_relationships_remain_declared_without_analytical_diamonds(pilot):
    overlay, contract, _ = pilot
    model, _ = build_model(contract, overlay)
    navigation = {
        "workflow_runs_to_repositories",
        "workflow_run_attempts_to_repositories",
        "workflow_jobs_to_repositories",
        "workflow_artifacts_to_runs",
        "workflow_jobs_to_attempts",
    }
    assert navigation <= {relation["name"] for relation in model["relationships"]}
    assert navigation.isdisjoint(model["policy"]["relationships"])
    bindings = json.loads(model["policy"]["tags"]["github.relationship_retrievals"])
    assert navigation <= bindings.keys()
    assert {entry["direction"] for entry in bindings["workflow_jobs_to_attempts"]} == {"forward", "reverse"}


def test_actions_typed_context_preserves_reusable_workflows_and_actor_roles(pilot, actions, monkeypatch):
    _, contract, _ = pilot
    requests = install(monkeypatch, actions.respond_with_baseline)
    row = rows_for(contract, "workflow_runs", repository="example/alpha", run_id=1001)[0]
    assert row["referenced_workflows"] == [
        {
            "path": "other/reusable/.github/workflows/build.yml@main",
            "sha": "d" * 40,
            "ref": "refs/heads/main",
        }
    ]
    assert row["event"] == "push"
    assert row["matching_pull_requests"][0]["number"] == 7
    assert row["matching_pull_requests"][0]["head"]["repo"]["id"] == 901
    assert row["head_commit"]["author"] == {"name": "Git Author", "email": "author@example.invalid"}
    assert row["head_commit"]["committer"] is None
    assert row["actor"]["login"] == "alice"
    assert row["triggering_actor"]["login"] == "bob"
    assert row["repository_snapshot"]["id"] == 101
    assert (
        row["head_repository_snapshot"]["id"]
        == row["head_repository_id"]
        == row["reported_head_repository_id"]
        == 901
    )
    assert row["head_repository"] == "contributor/fork"
    assert row["check_suite_node_id"] == "CS10001"
    assert row["previous_attempt_url"].endswith("/1001/attempts/1")
    assert all(request.method == "GET" for request in requests)
    assert not any(request.url.path.endswith(("/cancel", "/rerun", "/logs")) for request in requests)
    first = rows_for(
        contract, "workflow_run_attempts", repository="example/alpha", run_id=1001, attempt_number=1
    )[0]
    assert first["previous_attempt_url"] is None
    assert first["triggering_actor"]["login"] == "alice"


def test_actions_nullable_context_and_artifact_repository_provenance(pilot, actions, monkeypatch):
    _, contract, _ = pilot
    install(monkeypatch, actions.respond_with_baseline)
    pending = rows_for(contract, "workflow_runs", repository="example/alpha", run_id=1002)[0]
    assert pending["head_commit"] is pending["referenced_workflows"] is None
    assert pending["matching_pull_requests"] == []
    linked = rows_for(contract, "workflow_artifacts", repository="example/alpha", artifact_id=3001)[0]
    assert linked["workflow_run"] == {
        "id": 1001,
        "repository_id": 101,
        "head_repository_id": 901,
        "head_branch": "main",
        "head_sha": "abc123",
    }
    assert linked["run_repository_id"] == 101
    assert linked["head_repository_id"] == 901
    unlinked = rows_for(contract, "workflow_artifacts", repository="example/alpha", artifact_id=3004)[0]
    assert unlinked["workflow_run"] is unlinked["run_repository_id"] is unlinked["head_repository_id"] is None
    job = rows_for(contract, "workflow_jobs", repository="example/alpha", job_id=2001)[0]
    assert job["url"].endswith("/jobs/2001")
    assert job["run_url"].endswith("/runs/1001")
    workflow = rows_for(contract, "workflows", repository="example/alpha", workflow_id=601)[0]
    assert workflow["url"].endswith("/workflows/601")


@pytest.mark.parametrize(
    "field", ["referenced_workflow", "matching_pull_request", "head_commit", "head_repository"]
)
def test_new_actions_nested_fields_are_validated_before_projection(pilot, actions, monkeypatch, field):
    _, contract, _ = pilot

    def handler(request):
        if request.url.path.endswith("/runs/1001"):
            value = deepcopy(actions.RUNS[0])
            if field == "referenced_workflow":
                value["referenced_workflows"][0]["sha"] = 123
            if field == "matching_pull_request":
                value["pull_requests"][0]["head"]["repo"]["id"] = "901"
            if field == "head_commit":
                value["head_commit"]["author"]["email"] = False
            if field == "head_repository":
                value["head_repository"]["private"] = "false"
            return httpx.Response(200, json=value)
        return actions.respond_with_baseline(request)

    install(monkeypatch, handler)
    with pytest.raises(GeneratedContractError):
        rows_for(contract, "workflow_runs", repository="example/alpha", run_id=1001)
