"""Independent deployment events, environment identity and policy retrieval contracts."""

from copy import deepcopy

import httpx
import pytest

from tests.helpers import install
from tests.test_generated_runtime import run
from tests.test_generation_artifacts import ROOT
from tests.test_generation_artifacts import pilot as pilot
from vgi_github.generated_runtime import GeneratedContractError
from vgi_github.github_api import GitHubError


@pytest.fixture
def deployments_api(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "tests/crossfield"))
    import deployments_fixture

    return deployments_fixture


def rows_for(contract, name, **arguments):
    entity = next(value for value in contract["functions"] if value["name"] == name)
    output = run(entity, {key: [value] for key, value in arguments.items()}, contract=contract)
    return [row for batch in output.batches for row in batch.to_pylist()]


@pytest.mark.parametrize(
    "name,arguments,key,expected",
    [
        ("deployments", {}, "deployment_id", [11, 12, 13]),
        ("deployments", {"deployment_id": 12}, "deployment_id", [12]),
        ("deployments", {"environment_name": "production"}, "deployment_id", [11]),
        ("deployments", {"environment_name": "deleted-environment"}, "deployment_id", [13]),
        ("deployment_statuses", {}, "deployment_status_id", [112, 111, 123, 122, 121]),
        ("deployment_statuses", {"deployment_id": 11}, "deployment_status_id", [112, 111]),
        ("deployment_statuses", {"deployment_id": 13}, "deployment_status_id", []),
        (
            "deployment_statuses",
            {"deployment_id": 11, "deployment_status_id": 111},
            "deployment_status_id",
            [111],
        ),
        ("deployment_statuses", {"environment_name": "staging"}, "deployment_status_id", [123, 122, 121]),
        ("environments", {}, "environment_id", [701, 702, 703]),
        ("environments", {"environment_name": "production"}, "environment_id", [701]),
        ("deployment_branch_policies", {}, "deployment_branch_policy_id", [901, 902]),
        (
            "deployment_branch_policies",
            {"environment_name": "staging"},
            "deployment_branch_policy_id",
            [901, 902],
        ),
        (
            "deployment_branch_policies",
            {"environment_name": "staging", "deployment_branch_policy_id": 902},
            "deployment_branch_policy_id",
            [902],
        ),
        ("deployment_protection_rules", {}, "deployment_protection_rule_id", [1001, 1002]),
        (
            "deployment_protection_rules",
            {"environment_name": "production", "deployment_protection_rule_id": 1001},
            "deployment_protection_rule_id",
            [1001],
        ),
        ("deployment_rule_integrations", {}, "integration_id", [201, 202, 202]),
        ("deployment_rule_integrations", {"environment_name": "unused"}, "integration_id", []),
        ("pages_deployment_statuses", {"pages_deployment_id": "101"}, "status", ["succeed"]),
        ("pages_deployment_statuses", {"pages_deployment_id": "unknown"}, "status", [None]),
    ],
)
def test_deployment_and_policy_routes(pilot, deployments_api, monkeypatch, name, arguments, key, expected):
    _, contract, _ = pilot
    install(monkeypatch, deployments_api.respond)
    rows = rows_for(contract, name, repository="deployment-fixture/alpha", **arguments)
    assert [row[key] for row in rows] == expected


def test_deployment_and_environment_routes_preserve_complete_identity(pilot, deployments_api, monkeypatch):
    _, contract, _ = pilot
    requests = install(monkeypatch, deployments_api.respond)
    listed = rows_for(contract, "deployments", repository="deployment-fixture/alpha")
    assert rows_for(contract, "deployments", repository="deployment-fixture/alpha", deployment_id=12) == [
        listed[1]
    ]
    environments = rows_for(contract, "environments", repository="deployment-fixture/alpha")
    assert rows_for(
        contract, "environments", repository="deployment-fixture/alpha", environment_name="staging"
    ) == [environments[1]]
    assert [
        row["environment_id"] for row in rows_for(contract, "environments", owner="deployment-fixture")
    ] == [701, 702, 703, 704]
    assert any(request.url.params.get("page") == "3" for request in requests)
    assert rows_for(contract, "environments", repositories=[]) == []
    assert rows_for(contract, "deployments", repository="deployment-fixture/empty") == []


def test_deleted_environment_label_does_not_require_current_environment_resource(
    pilot, deployments_api, monkeypatch
):
    _, contract, _ = pilot
    requests = install(monkeypatch, deployments_api.respond)
    rows = rows_for(
        contract, "deployments", repository="deployment-fixture/alpha", environment_name="deleted-environment"
    )
    assert [(row["deployment_id"], row["deployment_creator_id"]) for row in rows] == [(13, None)]
    assert not any("/environments/" in request.url.path for request in requests)


def test_statuses_preserve_history_and_distinct_creator_role(pilot, deployments_api, monkeypatch):
    _, contract, _ = pilot
    install(monkeypatch, deployments_api.respond)
    statuses = rows_for(contract, "deployment_statuses", repository="deployment-fixture/alpha")
    assert [(row["deployment_id"], row["state"], row["status_creator_login"]) for row in statuses] == [
        (11, "success", "bob"),
        (11, "pending", "bob"),
        (12, "in_progress", None),
        (12, "error", "bob"),
        (12, "failure", "bob"),
    ]
    deployment = rows_for(contract, "deployments", repository="deployment-fixture/alpha", deployment_id=11)[0]
    assert deployment["deployment_creator_login"] == "alice"


@pytest.mark.parametrize("field,value", [("id", None), ("id", "901")])
def test_policy_identity_must_be_present_and_typed(pilot, deployments_api, monkeypatch, field, value):
    _, contract, _ = pilot

    def respond(request):
        response = deployments_api.respond(request)
        if request.url.path.endswith("/deployment-branch-policies"):
            payload = deepcopy(response.json())
            payload["branch_policies"][0][field] = value
            return httpx.Response(200, json=payload, headers=response.headers, request=request)
        return response

    install(monkeypatch, respond)
    with pytest.raises(GeneratedContractError):
        rows_for(
            contract,
            "deployment_branch_policies",
            repository="deployment-fixture/alpha",
            environment_name="staging",
        )


def test_branch_policy_total_count_rejects_silently_missing_next_page(pilot, deployments_api, monkeypatch):
    _, contract, _ = pilot

    def respond(request):
        response = deployments_api.respond(request)
        if request.url.path.endswith("/deployment-branch-policies"):
            headers = dict(response.headers)
            headers.pop("link", None)
            return httpx.Response(200, json=response.json(), headers=headers, request=request)
        return response

    install(monkeypatch, respond)
    with pytest.raises(GeneratedContractError, match="incomplete pagination total_count"):
        rows_for(
            contract,
            "deployment_branch_policies",
            repository="deployment-fixture/alpha",
            environment_name="staging",
        )


@pytest.mark.parametrize(
    "name,selector,tail",
    [
        ("deployments", {"deployment_id": 11}, "/deployments/11"),
        ("deployment_statuses", {"deployment_id": 11, "deployment_status_id": 111}, "/statuses/111"),
        (
            "deployment_branch_policies",
            {"environment_name": "staging", "deployment_branch_policy_id": 901},
            "/deployment-branch-policies/901",
        ),
        (
            "deployment_protection_rules",
            {"environment_name": "production", "deployment_protection_rule_id": 1001},
            "/deployment_protection_rules/1001",
        ),
    ],
)
def test_lookup_response_must_match_requested_identity(
    pilot, deployments_api, monkeypatch, name, selector, tail
):
    _, contract, _ = pilot

    def respond(request):
        response = deployments_api.respond(request)
        if request.url.path.endswith(tail):
            payload = deepcopy(response.json())
            payload["id"] += 1
            return httpx.Response(200, json=payload, headers=response.headers, request=request)
        return response

    install(monkeypatch, respond)
    with pytest.raises(GeneratedContractError, match="row assertion failed"):
        rows_for(contract, name, repository="deployment-fixture/alpha", **selector)


@pytest.mark.parametrize(
    "name,args",
    [
        ("deployment_statuses", {"deployment_status_id": 111}),
        (
            "deployments",
            {"repository": "deployment-fixture/alpha", "deployment_id": 11, "environment_name": "staging"},
        ),
        (
            "deployment_branch_policies",
            {"repository": "deployment-fixture/alpha", "deployment_branch_policy_id": 901},
        ),
        ("deployment_protection_rules", {"deployment_protection_rule_id": 1001}),
        ("pages_deployment_statuses", {"repository": "deployment-fixture/alpha"}),
    ],
)
def test_invalid_selector_combinations_fail_before_http(pilot, monkeypatch, name, args):
    _, contract, _ = pilot
    install(monkeypatch, lambda request: pytest.fail("Invalid selectors made an API request"))
    with pytest.raises(GeneratedContractError):
        rows_for(contract, name, **args)


def test_permission_failure_is_not_an_empty_integration_inventory(pilot, deployments_api, monkeypatch):
    _, contract, _ = pilot

    def respond(request):
        if request.url.path.endswith("/deployment_protection_rules/apps"):
            return httpx.Response(
                403, json={"message": "Administration permission required"}, request=request
            )
        return deployments_api.respond(request)

    install(monkeypatch, respond)
    with pytest.raises(GitHubError, match="Administration permission required"):
        rows_for(
            contract,
            "deployment_rule_integrations",
            repository="deployment-fixture/alpha",
            environment_name="production",
        )


def test_parent_navigation_does_not_create_competing_analytical_paths(pilot):
    _, contract, _ = pilot
    relationships = {relation["name"]: relation for relation in contract["relationships"]}
    for name in [
        "deployment_statuses_to_deployments",
        "deployment_branch_policies_to_environments",
        "deployment_protection_rules_to_environments",
        "deployment_rule_integrations_to_environments",
    ]:
        relation = relationships[name]
        assert relation["analytical"] is False
        assert {item["direction"] for item in relation["retrievals"]} == {"forward", "reverse"}
    assert not any(
        relation["from"] == "deployments" and relation["to"] == "environments"
        for relation in relationships.values()
    )


def test_builtin_environment_rules_preserve_wait_timers_and_reviewer_roles(
    pilot, deployments_api, monkeypatch
):
    _, contract, _ = pilot
    install(monkeypatch, deployments_api.respond)
    environment = rows_for(
        contract, "environments", repository="deployment-fixture/alpha", environment_name="production"
    )[0]
    wait, reviewers = environment["protection_rules"]
    assert wait["variant_1"]["wait_timer"] == 30
    assert reviewers["variant_2"]["prevent_self_review"] is True
    user, team = reviewers["variant_2"]["reviewers"]
    assert user["type"] == "User" and user["reviewer"]["variant_1"]["login"] == "alice"
    assert team["type"] == "Team" and team["reviewer"]["variant_2"]["slug"] == "operators"
    assert "variant_1" in wait["matched_types"]
    assert "variant_2" in reviewers["matched_types"]
