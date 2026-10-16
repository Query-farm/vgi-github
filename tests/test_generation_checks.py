"""Independent Checks populations: reruns, complete refs and annotation occurrences."""

from copy import deepcopy
from types import SimpleNamespace

import httpx
import pytest

from tests.helpers import install
from tests.test_functions import _Out, _Params
from tests.test_generated_runtime import REPORTING, run
from tests.test_generation_artifacts import ROOT
from tests.test_generation_artifacts import pilot as pilot
from vgi_github.generated_runtime import GeneratedContractError, make_function
from vgi_github.github_api import GitHubError


@pytest.fixture
def checks(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "tests/crossfield"))
    import checks_fixture

    return checks_fixture


def scan(contract, name, **arguments):
    entity = next(value for value in contract["functions"] if value["name"] == name)
    output = run(entity, {key: [value] for key, value in arguments.items()}, contract=contract)
    return [row for batch in output.batches for row in batch.to_pylist()]


@pytest.mark.parametrize(
    "entity,arguments,key,expected",
    [
        ("check_suites", {"git_ref": "main"}, "check_suite_id", [100, 101]),
        ("check_suites", {"check_suite_id": 101}, "check_suite_id", [101]),
        ("check_runs", {"git_ref": "main"}, "check_run_id", [6001, 6002, 6003]),
        ("check_runs", {"check_suite_id": 100}, "check_run_id", [6001, 6002]),
        ("check_runs", {"check_run_id": 6003}, "check_run_id", [6003]),
        ("check_annotations", {"check_run_id": 6001}, "annotation_position", [1, 2, 3]),
        ("check_annotations", {"check_suite_id": 100}, "annotation_position", [1, 2, 3, 1]),
        ("check_annotations", {"git_ref": "main"}, "annotation_position", [1, 2, 3, 1]),
    ],
)
def test_all_check_routes(pilot, checks, monkeypatch, entity, arguments, key, expected):
    _, contract, _ = pilot
    install(monkeypatch, checks.respond_all)
    rows = scan(contract, entity, repository="example/alpha", **arguments)
    assert [row[key] for row in rows] == expected
    assert all(row["repository_id"] == 101 and row["repository"] == "example/alpha" for row in rows)


def test_ref_enumerates_suites_then_all_reruns(pilot, checks, monkeypatch):
    _, contract, _ = pilot
    requests = install(monkeypatch, checks.respond_all)
    rows = scan(contract, "check_runs", repository="example/alpha", git_ref="main")
    assert [(row["name"], row["conclusion"]) for row in rows] == [
        ("lint", "failure"),
        ("lint", "success"),
        ("build", None),
    ]
    listings = [request for request in requests if request.url.path.endswith("/check-runs")]
    assert len(listings) == 3
    assert all(request.url.params["filter"] == "all" for request in listings)
    assert not any("/commits/" in request.url.path for request in listings)


def test_duplicate_annotations_are_distinct_occurrences_across_pages(pilot, checks, monkeypatch):
    _, contract, _ = pilot
    install(monkeypatch, checks.respond_all)
    rows = scan(contract, "check_annotations", repository="example/alpha", check_run_id=6001)
    first, second = (dict(rows[index]) for index in [0, 1])
    assert first.pop("annotation_position") == 1
    assert second.pop("annotation_position") == 2
    assert first == second
    assert [row["annotation_level"] for row in rows] == ["failure", "failure", "warning"]


def test_nullable_parent_and_actor_do_not_discard_run(pilot, checks, monkeypatch):
    _, contract, _ = pilot
    install(monkeypatch, checks.respond_all)
    rows = scan(contract, "check_runs", repository="example/alpha", check_run_id=6005)
    assert len(rows) == 1
    assert rows[0]["check_suite_id"] is rows[0]["app_id"] is rows[0]["app_slug"] is None


@pytest.mark.parametrize("entity", ["check_suites", "check_runs", "check_annotations"])
def test_empty_ref_population(pilot, checks, monkeypatch, entity):
    _, contract, _ = pilot
    install(monkeypatch, checks.respond_all)
    assert scan(contract, entity, repository="example/empty", git_ref="main") == []


@pytest.mark.parametrize(
    "entity,arguments",
    [
        ("check_suites", {"repository": "example/alpha"}),
        ("check_runs", {"git_ref": "main"}),
        ("check_runs", {"repository": "example/alpha", "git_ref": "main", "check_suite_id": 100}),
        ("check_runs", {"repository": "example/alpha", "check_run_id": 0}),
        ("check_annotations", {"repository": "example/alpha", "check_run_id": -1}),
    ],
)
def test_invalid_selection_precedes_http(pilot, monkeypatch, entity, arguments):
    _, contract, _ = pilot
    install(monkeypatch, lambda request: pytest.fail("Invalid selectors must not fetch"))
    with pytest.raises(GeneratedContractError):
        scan(contract, entity, **arguments)


@pytest.mark.parametrize(
    "entity,arguments,match",
    [
        ("check_runs", {"git_ref": "private-ref"}, "403"),
        ("check_runs", {"git_ref": "late-ref"}, "503"),
        ("check_annotations", {"check_run_id": 6006}, "503"),
        ("check_runs", {"check_run_id": 999}, "404"),
    ],
)
def test_visibility_and_later_page_errors_propagate(pilot, checks, monkeypatch, entity, arguments, match):
    _, contract, _ = pilot
    install(monkeypatch, checks.respond_all)
    with pytest.raises(Exception, match=match):
        scan(contract, entity, repository="example/alpha", **arguments)


def test_more_than_one_thousand_suites_are_not_truncated(pilot, checks, monkeypatch):
    _, contract, _ = pilot
    seen = []

    def respond(request):
        path = request.url.path
        headers = {"Cache-Control": "no-store", "X-RateLimit-Remaining": "5000"}
        if path.endswith("/commits/many/check-suites"):
            page = int(request.url.params.get("page", "1"))
            ids = range(1000, 2000) if page == 1 else [2000]
            payload = {"total_count": 1001, "check_suites": [checks.suite(identity) for identity in ids]}
            if page == 1:
                headers["Link"] = f'<{request.url.copy_set_param("page", "2")}>; rel="next"'
            return httpx.Response(200, json=payload, headers=headers)
        if "/check-suites/" in path and path.endswith("/check-runs"):
            identity = int(path.split("/")[-2])
            seen.append(identity)
            assert request.url.params["filter"] == "all"
            values = [checks.run(8001, identity, "success")] if identity == 2000 else []
            return httpx.Response(
                200, json={"total_count": len(values), "check_runs": values}, headers=headers
            )
        return checks.respond_all(request)

    install(monkeypatch, respond)
    entity = next(value for value in contract["functions"] if value["name"] == "check_runs")
    function = make_function(entity, contract)
    params = _Params(
        SimpleNamespace(repository="example/alpha", git_ref="many"),
        function.FIXED_SCHEMA,
        attach_opaque_data=REPORTING,
    )
    state, output = function.initial_state(params), _Out()
    for _ in range(1100):
        function.process(params, state, output)
        if output.finished:
            break
    assert output.finished, "The complete traversal needs more than the shared 1000-tick test bound"
    rows = [row for batch in output.batches for row in batch.to_pylist()]
    assert [row["check_run_id"] for row in rows] == [8001]
    assert seen == list(range(1000, 2001))


def test_direct_and_reference_runs_have_identical_fields(pilot, checks, monkeypatch):
    _, contract, _ = pilot
    install(monkeypatch, checks.respond_all)
    by_ref = scan(contract, "check_runs", repository="example/alpha", git_ref="main")
    by_id = scan(contract, "check_runs", repository="example/alpha", check_run_id=6001)
    assert by_id == by_ref[:1]


def test_duplicate_check_run_identity_is_rejected(pilot, checks, monkeypatch):
    _, contract, _ = pilot
    monkeypatch.setitem(checks.RUNS, 100, [deepcopy(checks.RUNS[100][0])] * 2)
    install(monkeypatch, checks.respond_all)
    with pytest.raises(GeneratedContractError, match="duplicate row identity"):
        scan(contract, "check_runs", repository="example/alpha", check_suite_id=100)


@pytest.mark.parametrize(
    "arguments,expected",
    [
        ({"check_run_id": 6001}, [(6001, 1), (6001, 2)]),
        ({"check_suite_id": 100}, [(6001, 1), (6001, 2), (6002, 1), (6002, 2)]),
        ({"git_ref": "main"}, [(6001, 1), (6001, 2), (6002, 1), (6002, 2), (6003, 1)]),
        ({"check_run_id": 6004}, []),
    ],
)
def test_check_steps_paginate_every_selected_run(pilot, checks, monkeypatch, arguments, expected):
    import json

    _, contract, _ = pilot
    requests = install(monkeypatch, checks.respond_all)
    rows = scan(
        contract,
        "check_steps",
        repository="example/beta" if arguments.get("check_run_id") == 6004 else "example/alpha",
        **arguments,
    )
    assert [(r["check_run_id"], r["step_number"]) for r in rows] == expected
    assert all(r["repository_id"] == 101 for r in rows)
    if rows:
        assert any(
            json.loads(r.content)["variables"].get("cursor") == "step:1"
            for r in requests
            if r.method == "POST"
        )
        assert rows[0]["external_id"] == "checkout"
        assert rows[0]["seconds_to_completion"] == 5


def test_steps_keep_missing_timing_and_do_not_invent_action_job_identity(pilot, checks, monkeypatch):
    _, contract, _ = pilot
    install(monkeypatch, checks.respond_all)
    rows = scan(contract, "check_steps", repository="example/alpha", check_run_id=6005)
    assert len(rows) == 1
    assert rows[0]["status"] == "PENDING"
    assert rows[0]["seconds_to_completion"] is rows[0]["started_at"] is rows[0]["completed_at"] is None
    assert "job_id" not in rows[0]


def test_node_enrichment_preserves_canonical_ids_without_changing_rest_routes(pilot, checks, monkeypatch):
    _, contract, _ = pilot
    requests = install(monkeypatch, checks.respond_all)
    ordinary = scan(contract, "check_suites", repository="example/alpha", check_suite_id=100)
    assert not any(r.method == "POST" for r in requests)
    assert ordinary[0]["creator"] is ordinary[0]["workflow_run"] is None
    enriched = scan(contract, "check_suites", repository="example/alpha", check_suite_node_id="CS100")
    assert enriched[0]["check_suite_id"] == ordinary[0]["check_suite_id"] == 100
    assert (enriched[0]["creator_id"], enriched[0]["creator_login"]) == (1, "alice")
    assert enriched[0]["pusher_type"] == "Bot"
    assert enriched[0]["pusher_login"] == "ci-bot"
    assert enriched[0]["push"]["nextSha"] == "a" * 40
    assert enriched[0]["branch"] == {"id": "REF-main", "name": "main", "prefix": "refs/heads/"}
    assert enriched[0]["workflow_run_id"] == 9001
    assert enriched[0]["workflow_run"]["file"]["repositoryName"] == "other/reusable"
    assert enriched[0]["workflow_run"]["file"]["viewerCanReadRepository"] is True
    assert enriched[0]["workflow_run"]["file"]["viewerCanPushRepository"] is False
    null_context = scan(contract, "check_suites", repository="example/alpha", check_suite_node_id="CS101")
    assert null_context[0]["creator"] is null_context[0]["push"] is null_context[0]["workflow_run"] is None


def test_run_enrichment_preserves_deployment_and_pending_approval_types(pilot, checks, monkeypatch):
    _, contract, _ = pilot
    install(monkeypatch, checks.respond_all)
    deployment = scan(contract, "check_runs", repository="example/alpha", check_run_node_id="CR6001")[0]
    assert deployment["check_run_id"] == 6001
    assert deployment["deployment_id"] == 501
    assert deployment["deployment"]["production_environment"] is True
    ordinary = scan(contract, "check_runs", repository="example/alpha", check_run_id=6001)[0]
    assert ordinary["deployment_id"] == 501
    assert ordinary["deployment"] == deployment["deployment"]
    assert ordinary["deployment_context"] is None
    assert deployment["deployment_context"]["state"] == "ACTIVE"
    assert deployment["deployment_context"]["originalEnvironment"] == "staging"
    assert deployment["pending_deployment_request"] is None
    pending = scan(contract, "check_runs", repository="example/alpha", check_run_node_id="CR6003")[0]
    assert pending["deployment"] is None
    assert pending["pending_deployment_request"]["waitTimer"] == 5
    assert pending["pending_deployment_request"]["waitTimerStartedAt"] is None
    assert pending["pending_deployment_request"]["currentUserCanApprove"] is False
    assert pending["pending_deployment_request"]["environment"]["name"] == "production"


@pytest.mark.parametrize(
    "failure",
    ["null_node", "null_connection", "null_item", "duplicate_step", "invalid_seconds", "later_error"],
)
def test_missing_or_invalid_step_connections_never_shrink_known_runs(pilot, checks, monkeypatch, failure):
    import json

    _, contract, _ = pilot

    def handler(request):
        if request.method == "POST":
            payload = json.loads(request.content)
            if failure == "null_node":
                return httpx.Response(200, json={"data": {"node": None}})
            if failure == "later_error" and payload["variables"].get("cursor"):
                return httpx.Response(200, json={"errors": [{"message": "Connection became unavailable"}]})
            result = checks.respond_all(request)
            value = result.json()
            if failure == "null_connection":
                value["data"]["node"]["steps"] = None
            if failure == "null_item":
                value["data"]["node"]["steps"]["nodes"] = [None]
            if failure == "duplicate_step":
                value["data"]["node"]["steps"]["nodes"][0]["number"] = 1
            if failure == "invalid_seconds":
                value["data"]["node"]["steps"]["nodes"][0]["secondsToCompletion"] = True
            return httpx.Response(200, json=value)
        return checks.respond_all(request)

    install(monkeypatch, handler)
    with pytest.raises((GeneratedContractError, GitHubError)):
        scan(contract, "check_steps", repository="example/alpha", check_run_id=6001)


@pytest.mark.parametrize("failure", ["wrong_repository", "missing_numeric_id", "wrong_node_id", "null_node"])
def test_check_node_identity_is_validated_before_rest_lookup(pilot, checks, monkeypatch, failure):
    _, contract, _ = pilot

    def handler(request):
        if request.method == "POST":
            value = checks.respond_all(request).json()
            if failure == "wrong_repository":
                value["data"]["node"]["repository"]["databaseId"] = 102
            if failure == "missing_numeric_id":
                value["data"]["node"]["databaseId"] = None
            if failure == "wrong_node_id":
                value["data"]["node"]["id"] = "CR6002"
            if failure == "null_node":
                value["data"]["node"] = None
            return httpx.Response(200, json=value)
        return checks.respond_all(request)

    requests = install(monkeypatch, handler)
    with pytest.raises(GeneratedContractError):
        scan(contract, "check_runs", repository="example/alpha", check_run_node_id="CR6001")
    assert not any("/check-runs/" in r.url.path for r in requests)


def test_workflow_run_navigation_selects_its_suite_not_the_run_id(pilot, checks, monkeypatch):
    _, contract, _ = pilot
    relation = next(
        row for row in contract["relationships"] if row["name"] == "check_suites_to_workflow_runs"
    )
    reverse = next(row for row in relation["retrievals"] if row["direction"] == "reverse")
    parent = {"repository": "example/alpha", "run_id": 9001, "check_suite_id": 100}
    arguments = {name: parent[column] for name, column in reverse["bindings"].items()}
    requests = install(monkeypatch, checks.respond_all)
    rows = scan(contract, "check_suites", **arguments)
    assert len(rows) == 1 and rows[0]["check_suite_id"] == 100
    assert rows[0]["repository_id"] == 101 and rows[0]["head_sha"] == "a" * 40
    assert [request.url.path for request in requests] == [
        "/repos/example/alpha",
        "/repos/example/alpha/check-suites/100",
    ]
    # An absent association is guarded in navigation metadata; an attempted NULL
    # lookup also fails selector validation rather than fetching a broad population.
    requests.clear()
    assert reverse["when_not_null"] == ["check_suite_id"]
    with pytest.raises(GeneratedContractError):
        scan(contract, "check_suites", repository="example/alpha", check_suite_id=None)
    assert requests == []
