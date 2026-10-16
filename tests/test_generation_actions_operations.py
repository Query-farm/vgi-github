"""Operational Actions populations retain independent totals and complete queues."""

from copy import deepcopy

import httpx
import pytest

from tests.helpers import install
from tests.test_generated_runtime import run
from tests.test_generation_artifacts import ROOT
from tests.test_generation_artifacts import pilot as pilot
from vgi_github.generated_runtime import GeneratedContractError
from vgi_github.github_api import GitHubError

OWNER = "actions-ops-fixture"
ALPHA = f"{OWNER}/alpha"


@pytest.fixture
def operations(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "tests/crossfield"))
    import actions_operations_fixture

    return actions_operations_fixture


def rows_for(contract, name, **arguments):
    entity = next(row for row in contract["functions"] if row["name"] == name)
    output = run(entity, {key: [value] for key, value in arguments.items()}, contract=contract)
    return [row for batch in output.batches for row in batch.to_pylist()]


def test_cache_identity_is_not_key_or_version(pilot, operations, monkeypatch):
    _, contract, _ = pilot
    requests = install(monkeypatch, operations.respond)
    rows = rows_for(contract, "actions_caches", organization=OWNER)
    assert [(row["repository_id"], row["cache_id"]) for row in rows] == [
        (2101, 5101),
        (2101, 5102),
        (2101, 5103),
        (2102, 5201),
    ]
    assert [row["cache_key"] for row in rows] == ["linux-main", "linux-main", "windows", "linux-main"]
    assert [row["cache_version"] for row in rows] == ["v1", "v2", "v1", "v1"]
    assert sum(row["size_in_bytes"] for row in rows) == 480
    assert any(
        request.url.path.endswith("/caches") and request.url.params.get("page") == "3" for request in requests
    )


def test_cache_filters_retain_all_matching_pages(pilot, operations, monkeypatch):
    _, contract, _ = pilot
    requests = install(monkeypatch, operations.respond)
    rows = rows_for(
        contract, "actions_caches", repository=ALPHA, cache_ref="refs/heads/main", cache_key="linux-"
    )
    assert [row["cache_id"] for row in rows] == [5101, 5102]
    calls = [request for request in requests if request.url.path.endswith("/caches")]
    assert len(calls) == 2
    assert all(
        request.url.params["ref"] == "refs/heads/main" and request.url.params["key"] == "linux-"
        for request in calls
    )


def test_missing_cache_size_is_unknown_but_missing_identity_fails(pilot, operations, monkeypatch):
    _, contract, _ = pilot
    caches = deepcopy(operations.CACHES["alpha"])
    caches[0].pop("size_in_bytes")
    monkeypatch.setitem(operations.CACHES, "alpha", caches)
    install(monkeypatch, operations.respond)
    assert rows_for(contract, "actions_caches", repository=ALPHA)[0]["size_in_bytes"] is None
    caches[0].pop("id")
    with pytest.raises(GeneratedContractError, match="cache_id"):
        rows_for(contract, "actions_caches", repository=ALPHA)


def test_usage_routes_share_repository_identity_and_keep_zero_observations(pilot, operations, monkeypatch):
    _, contract, _ = pilot
    requests = install(monkeypatch, operations.respond)
    rows = rows_for(contract, "actions_cache_usage", organization=OWNER)
    assert [
        (row["repository_id"], row["active_caches_count"], row["active_caches_size_in_bytes"]) for row in rows
    ] == [(2101, 4, 450), (2102, 1, 90), (2103, 0, 0)]
    assert not any(request.url.path == f"/orgs/{OWNER}/repos" for request in requests)
    for row in rows:
        assert rows_for(contract, "actions_cache_usage", repository=row["repository"]) == [row]
    # Inventory 4/480, repository summaries 5/540, organization summary 6/600
    # are independently reported observations rather than a reconciliation rule.
    summary = rows_for(contract, "organization_actions_cache_usage", organization=OWNER)
    assert len(summary) == 1
    assert (
        summary[0]["organization_id"],
        summary[0]["total_active_caches_count"],
        summary[0]["total_active_caches_size_in_bytes"],
    ) == (2100, 6, 600)


def test_active_group_discovery_hydrates_every_group_and_keeps_null_job_fields(
    pilot, operations, monkeypatch
):
    _, contract, _ = pilot
    requests = install(monkeypatch, operations.respond)
    rows = rows_for(contract, "actions_concurrency_groups", organization=OWNER)
    assert [(row["repository_id"], row["concurrency_group"], len(row["group_members"])) for row in rows] == [
        (2101, "deploy-main", 3),
        (2101, "test", 1),
        (2102, "deploy-main", 1),
    ]
    assert rows[0]["group_members"][0]["job_id"] is None
    assert rows[0]["group_members"][1]["job_url"] is None
    assert rows[0]["last_acquired_at"] is not None and rows[1]["last_acquired_at"] is None
    exact = rows_for(
        contract, "actions_concurrency_groups", repository=ALPHA, concurrency_group="deploy-main"
    )[0]
    assert exact["last_acquired_at"] is None
    assert {key: value for key, value in exact.items() if key != "last_acquired_at"} == {
        key: value for key, value in rows[0].items() if key != "last_acquired_at"
    }
    assert any(request.url.params.get("after") == "2" for request in requests)


@pytest.mark.parametrize(
    "selector,identity,expected",
    [("ahead_of_run_id", 3101, 1), ("ahead_of_job_id", 6102, 2), ("ahead_of_job_id", 6103, 3)],
)
def test_concurrency_prefix_is_explicit_in_observation(
    pilot, operations, monkeypatch, selector, identity, expected
):
    _, contract, _ = pilot
    requests = install(monkeypatch, operations.respond)
    row = rows_for(
        contract,
        "actions_concurrency_groups",
        repository=ALPHA,
        concurrency_group="deploy-main",
        **{selector: identity},
    )[0]
    assert len(row["group_members"]) == expected and row[selector] == identity
    assert row["reported_member_count"] == expected
    assert any(request.url.params.get(selector.removesuffix("_id")) == str(identity) for request in requests)


def test_run_group_memberships_retain_inactive_empty_groups_without_hydrating_them(
    pilot, operations, monkeypatch
):
    _, contract, _ = pilot
    requests = install(monkeypatch, operations.respond)
    rows = rows_for(contract, "workflow_run_concurrency_groups", organization=OWNER)
    assert [(row["run_id"], row["concurrency_group"], len(row["run_group_members"])) for row in rows] == [
        (3101, "deploy-main", 1),
        (3101, "old-group", 0),
        (3102, "deploy-main", 2),
        (3102, "test", 1),
        (3201, "deploy-main", 1),
    ]
    assert rows[2]["run_group_members"][1]["position"] == 2
    assert all("/actions/concurrency_groups/" not in request.url.path for request in requests)
    assert rows_for(contract, "workflow_run_concurrency_groups", repository=ALPHA, run_id=3101) == rows[:2]
    assert (
        rows_for(contract, "workflow_run_concurrency_groups", repository=ALPHA, workflow_id=4101) == rows[:4]
    )


def test_pending_gates_keep_typed_user_team_reviewers_and_empty_run(pilot, operations, monkeypatch):
    _, contract, _ = pilot
    install(monkeypatch, operations.respond)
    rows = rows_for(contract, "workflow_pending_deployments", organization=OWNER)
    assert [
        (row["run_id"], row["environment_id"], row["wait_timer"], row["current_user_can_approve"])
        for row in rows
    ] == [(3101, 7101, 30, True), (3101, 7102, 0, False), (3201, 7201, 10, False)]
    user, team = rows[0]["reviewers"]
    assert user["type"] == "User" and user["reviewer"]["variant_1"]["login"] == "actions-ops-alice"
    assert team["type"] == "Team" and team["reviewer"]["variant_2"]["slug"] == "operators"
    assert team["reviewer"]["variant_2"]["parent"] is None
    assert rows[1]["wait_timer_started_at"] is None and rows[1]["reviewers"] == []
    assert rows_for(contract, "workflow_pending_deployments", repository=ALPHA, run_id=3102) == []
    assert rows_for(contract, "workflow_pending_deployments", repository=ALPHA, workflow_id=4101) == rows[:2]


def test_missing_pending_environment_id_fails_qualification(pilot, operations, monkeypatch):
    _, contract, _ = pilot
    pending = deepcopy(operations.PENDING[3101])
    pending[0]["environment"].pop("id")
    monkeypatch.setitem(operations.PENDING, 3101, pending)
    install(monkeypatch, operations.respond)
    with pytest.raises(GeneratedContractError, match="environment_id"):
        rows_for(contract, "workflow_pending_deployments", repository=ALPHA, run_id=3101)


def test_review_occurrences_keep_duplicates_and_ordinal_across_pages(pilot, operations, monkeypatch):
    _, contract, _ = pilot
    requests = install(monkeypatch, operations.respond)
    rows = rows_for(contract, "workflow_deployment_reviews", organization=OWNER)
    assert [(row["run_id"], row["review_ordinal"], row["state"], row["reviewer_id"]) for row in rows] == [
        (3101, 1, "approved", 8101),
        (3101, 2, "approved", 8101),
        (3101, 3, "rejected", 8102),
        (3102, 1, "pending", 8101),
        (3201, 1, "approved", 8102),
    ]
    assert {key: value for key, value in rows[0].items() if key != "review_ordinal"} == {
        key: value for key, value in rows[1].items() if key != "review_ordinal"
    }
    assert [len(row["environments"]) for row in rows] == [2, 2, 1, 0, 1]
    assert rows[2]["reviewer"]["login"] == "actions-ops-bob"
    assert "created_at" not in rows[0] and "review_id" not in rows[0]
    assert any(
        request.url.path.endswith("/approvals") and request.url.params.get("page") == "3"
        for request in requests
    )
    assert rows_for(contract, "workflow_deployment_reviews", repository=ALPHA, workflow_id=4101) == rows[:4]


@pytest.mark.parametrize(
    "entity",
    [
        "actions_caches",
        "actions_concurrency_groups",
        "workflow_run_concurrency_groups",
        "workflow_pending_deployments",
        "workflow_deployment_reviews",
    ],
)
def test_empty_repository_and_empty_cohort_remain_empty(pilot, operations, monkeypatch, entity):
    _, contract, _ = pilot
    install(monkeypatch, operations.respond)
    assert rows_for(contract, entity, repository=f"{OWNER}/empty") == []
    assert rows_for(contract, entity, repositories=[]) == []


@pytest.mark.parametrize(
    "entity,arguments",
    [
        (
            "actions_concurrency_groups",
            {
                "repository": ALPHA,
                "concurrency_group": "deploy-main",
                "ahead_of_run_id": 3101,
                "ahead_of_job_id": 6102,
            },
        ),
        ("actions_concurrency_groups", {"repository": ALPHA, "ahead_of_run_id": 3101}),
        ("actions_concurrency_groups", {"concurrency_group": "deploy-main"}),
        (
            "actions_concurrency_groups",
            {"repository": ALPHA, "concurrency_group": "deploy-main", "ahead_of_job_id": 0},
        ),
        ("workflow_run_concurrency_groups", {"run_id": 3101}),
        ("workflow_pending_deployments", {"repository": ALPHA, "run_id": 3101, "workflow_id": 4101}),
        ("workflow_deployment_reviews", {"workflow_id": 4101}),
        ("organization_actions_cache_usage", {"repository": ALPHA}),
        ("actions_caches", {"repository": ALPHA, "cache_key": ""}),
    ],
)
def test_invalid_selectors_fail_before_http(pilot, monkeypatch, entity, arguments):
    _, contract, _ = pilot
    install(monkeypatch, lambda request: pytest.fail("Invalid selectors must not fetch"))
    with pytest.raises(GeneratedContractError):
        rows_for(contract, entity, **arguments)


@pytest.mark.parametrize(
    "entity,arguments,suffix",
    [
        ("actions_caches", {"repository": ALPHA}, "/actions/caches"),
        ("actions_cache_usage", {"organization": OWNER}, "/actions/cache/usage-by-repository"),
        ("actions_concurrency_groups", {"repository": ALPHA}, "/actions/concurrency_groups"),
        (
            "workflow_run_concurrency_groups",
            {"repository": ALPHA, "run_id": 3101},
            "/runs/3101/concurrency_groups",
        ),
    ],
)
@pytest.mark.parametrize("corruption", ["missing_next", "missing_total", "changing_total"])
def test_reported_complete_populations_reject_truncation(
    pilot, operations, monkeypatch, entity, arguments, suffix, corruption
):
    _, contract, _ = pilot

    def respond(request):
        response = operations.respond(request)
        if not request.url.path.endswith(suffix):
            return response
        payload, headers = response.json(), dict(response.headers)
        if corruption == "missing_next":
            headers.pop("link", None)
        elif corruption == "missing_total":
            payload.pop("total_count")
        elif request.url.params.get("page", request.url.params.get("after", "1")) != "1":
            payload["total_count"] += 1
        return httpx.Response(200, json=payload, headers=headers, request=request)

    install(monkeypatch, respond)
    with pytest.raises(GeneratedContractError, match="count|total_count"):
        rows_for(contract, entity, **arguments)


@pytest.mark.parametrize(
    "entity,suffix",
    [("workflow_pending_deployments", "/pending_deployments"), ("workflow_deployment_reviews", "/approvals")],
)
def test_later_page_failure_does_not_become_partial_success(pilot, operations, monkeypatch, entity, suffix):
    _, contract, _ = pilot

    def respond(request):
        if request.url.path.endswith(suffix) and request.url.params.get("page") == "2":
            return httpx.Response(403, json={"message": "Fixture permission revoked"}, request=request)
        return operations.respond(request)

    install(monkeypatch, respond)
    with pytest.raises(GitHubError, match="403|permission revoked"):
        rows_for(contract, entity, repository=ALPHA, run_id=3101)


@pytest.mark.parametrize(
    "entity,arguments,suffix,field,value",
    [
        ("actions_cache_usage", {}, "/actions/cache/usage", "full_name", f"{OWNER}/beta"),
        (
            "actions_concurrency_groups",
            {"concurrency_group": "deploy-main"},
            "/actions/concurrency_groups/deploy-main",
            "group_name",
            "another-group",
        ),
    ],
)
def test_lookup_asserts_returned_identity(
    pilot, operations, monkeypatch, entity, arguments, suffix, field, value
):
    _, contract, _ = pilot

    def respond(request):
        response = operations.respond(request)
        if request.url.path.endswith(suffix):
            payload = response.json()
            payload[field] = value
            return httpx.Response(200, json=payload, request=request)
        return response

    install(monkeypatch, respond)
    with pytest.raises(GeneratedContractError):
        rows_for(contract, entity, repository=ALPHA, **arguments)


def test_inactive_and_disappearing_groups_fail_without_dropping_memberships(pilot, operations, monkeypatch):
    _, contract, _ = pilot
    install(monkeypatch, operations.respond)
    with pytest.raises(GitHubError, match="404|Inactive"):
        rows_for(contract, "actions_concurrency_groups", repository=ALPHA, concurrency_group="old-group")

    def respond(request):
        if request.url.path.endswith("/actions/concurrency_groups/test"):
            return httpx.Response(404, json={"message": "Group became inactive"}, request=request)
        return operations.respond(request)

    install(monkeypatch, respond)
    with pytest.raises(GitHubError, match="404|inactive"):
        rows_for(contract, "actions_concurrency_groups", repository=ALPHA)
