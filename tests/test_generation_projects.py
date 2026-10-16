"""Projects preserve owner, project, item, field and collection-member grains."""

from copy import deepcopy
from datetime import date

import pytest

from tests.helpers import install
from tests.test_generated_runtime import run
from tests.test_generation_artifacts import ROOT
from tests.test_generation_artifacts import pilot as pilot
from vgi_github.generated_runtime import GeneratedContractError


@pytest.fixture
def projects(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "tests/crossfield"))
    import projects_fixture

    return projects_fixture


def scan(contract, name, **arguments):
    entity = next(value for value in contract["functions"] if value["name"] == name)
    output = run(entity, {key: [value] for key, value in arguments.items()}, contract=contract)
    return [row for batch in output.batches for row in batch.to_pylist()]


@pytest.mark.parametrize(
    "arguments,expected",
    [
        ({"organization": "example"}, ["PVT1", "PVT2"]),
        ({"owner": "example"}, ["PVT1", "PVT2"]),
        ({"user": "alice"}, ["PVT3"]),
        ({"owner": "alice"}, ["PVT3"]),
        ({"organization": "example", "project_number": 2}, ["PVT2"]),
        ({"project_owners": [{"login": "example"}, {"login": "alice"}]}, ["PVT1", "PVT2", "PVT3"]),
        ({"project_owners": []}, []),
        ({"organization": "empty-org"}, []),
    ],
)
def test_project_owner_and_lookup_routes(pilot, projects, monkeypatch, arguments, expected):
    _, contract, _ = pilot
    install(monkeypatch, projects.respond_all)
    assert [row["project_node_id"] for row in scan(contract, "projects", **arguments)] == expected


def test_fields_are_project_qualified_and_keep_typed_options(pilot, projects, monkeypatch):
    _, contract, _ = pilot
    install(monkeypatch, projects.respond_all)
    fields = scan(contract, "project_fields", organization="example")
    assert len(fields) == 11
    assert [(row["project_node_id"], row["name"]) for row in fields if row["project_field_id"] == 10] == [
        ("PVT1", "Status"),
        ("PVT2", "Unused"),
    ]
    status = scan(contract, "project_fields", owner="example", project_number=1, project_field_id=10)[0]
    assert status["options"][0]["name"]["raw"] == "Done"
    iteration = next(row for row in fields if row["project_field_id"] == 18)
    assert iteration["configuration"]["iterations"][0]["start_date"] == date(2026, 10, 1)


def test_item_types_archive_and_redaction_survive(pilot, projects, monkeypatch):
    _, contract, _ = pilot
    install(monkeypatch, projects.respond_all)
    rows = scan(contract, "project_items", organization="example")
    assert [row["item_type"] for row in rows] == ["ISSUE", "PULL_REQUEST", "DRAFT_ISSUE", "REDACTED"]
    assert rows[1]["is_archived"] is True
    assert rows[3]["content"] is None
    assert rows[0]["content"]["Issue"]["title"] == "One issue in two projects"
    assert rows[0]["content"]["PullRequest"] is None
    assert scan(contract, "project_items", project_item_node_id="PVTI1") == rows[:1]


def test_field_values_have_typed_scalar_and_variant_access(pilot, projects, monkeypatch):
    _, contract, _ = pilot
    install(monkeypatch, projects.respond_all)
    rows = scan(contract, "project_field_values", organization="example")
    assert len(rows) == 14
    number = next(
        row for row in rows if row["project_item_node_id"] == "PVTI1" and row["project_field_id"] == 11
    )
    assert number["number_value"] == 3.5
    assert number["text_value"] is None
    assert number["value"]["ProjectV2ItemFieldNumberValue"]["number"] == 3.5
    selected = scan(
        contract, "project_field_values", project_item_node_id="PVTI1", project_field_node_id="PVTF1-12"
    )
    assert len(selected) == 1 and selected[0]["date_value"] == date(2026, 11, 1)
    assert (
        len(scan(contract, "project_field_values", owner="example", project_number=1, project_field_id=10))
        == 2
    )
    assert (
        scan(
            contract,
            "project_field_values",
            project_item_node_id="PVTI1",
            project_field_node_id="PVTF1-12",
            project_field_id=11,
        )
        == []
    )


@pytest.mark.parametrize(
    "entity,expected",
    [
        ("project_field_labels", ["L1", "L2", "L1"]),
        ("project_field_users", ["USER201", "USER202"]),
        ("project_field_pull_requests", ["PR1001", "PR1002"]),
        ("project_field_reviewers", ["USER201", "TEAM501"]),
    ],
)
def test_each_collection_value_is_independently_paginated(pilot, projects, monkeypatch, entity, expected):
    _, contract, _ = pilot
    install(monkeypatch, projects.respond_all)
    rows = scan(contract, entity, organization="example")
    assert [row["member_node_id"] for row in rows] == expected
    assert all(row["project_node_id"] == "PVT1" for row in rows)
    if entity == "project_field_reviewers":
        assert rows[1]["reviewer"]["Team"]["slug"] == "core"


def test_duplicate_field_names_only_reject_name_based_member_lookup(pilot, projects, monkeypatch):
    _, contract, _ = pilot
    original = projects.ITEMS["PVT1"][0]
    changed = deepcopy(original)
    changed["fieldValues"][3]["field"]["name"] = "Labels"
    monkeypatch.setitem(projects.ITEMS, "PVT1", [changed, *projects.ITEMS["PVT1"][1:]])
    install(monkeypatch, projects.respond_all)
    assert len(scan(contract, "project_field_values", project_item_node_id="PVTI1")) == 10
    with pytest.raises(GeneratedContractError, match="duplicate row identity"):
        scan(contract, "project_field_labels", project_item_node_id="PVTI1")


@pytest.mark.parametrize(
    "entity,arguments",
    [
        ("projects", {}),
        ("projects", {"owner": "example", "organization": "example"}),
        ("project_fields", {"owner": "example", "project_field_id": 10}),
        ("project_items", {"project_item_node_id": "PVTI1", "owner": "example"}),
        ("project_field_values", {"project_field_id": 10}),
        ("projects", {"organization": "example", "project_number": 0}),
    ],
)
def test_invalid_project_selectors_fail_before_http(pilot, monkeypatch, entity, arguments):
    _, contract, _ = pilot
    install(monkeypatch, lambda request: pytest.fail("Invalid project selection must not fetch"))
    with pytest.raises(GeneratedContractError):
        scan(contract, entity, **arguments)


def test_empty_project_cohort_does_not_fetch(pilot, monkeypatch):
    _, contract, _ = pilot
    install(monkeypatch, lambda request: pytest.fail("An empty owner cohort must not fetch"))
    assert scan(contract, "project_field_values", project_owners=[]) == []


def test_later_field_value_page_error_propagates(pilot, projects, monkeypatch):
    _, contract, _ = pilot
    install(monkeypatch, projects.respond_all)
    with pytest.raises(Exception, match="503"):
        scan(contract, "project_field_values", project_item_node_id="PVTI-LATE")


def test_projects_permission_failure_is_not_empty_population(pilot, projects, monkeypatch):
    _, contract, _ = pilot
    install(monkeypatch, projects.respond_all)
    with pytest.raises(Exception, match="403"):
        scan(contract, "projects", organization="private-owner")


def test_nullable_milestone_value_retains_its_typed_branch(pilot, projects, monkeypatch):
    _, contract, _ = pilot
    changed = deepcopy(projects.ITEMS["PVT1"][0])
    definition = {
        "__typename": "ProjectV2Field",
        "dataType": "MILESTONE",
        "id": "PVTF1-20",
        "databaseId": 20,
        "name": "Milestone",
    }
    changed["fieldValues"] = [
        {"__typename": "ProjectV2ItemFieldMilestoneValue", "field": definition, "milestone": None}
    ]
    monkeypatch.setitem(projects.ITEMS, "PVT1", [changed, *projects.ITEMS["PVT1"][1:]])
    install(monkeypatch, projects.respond_all)
    rows = scan(contract, "project_field_values", project_item_node_id="PVTI1")
    assert len(rows) == 1
    assert rows[0]["value"]["ProjectV2ItemFieldMilestoneValue"] == {
        "field": {
            "__typename": "ProjectV2Field",
            "ProjectV2Field": {"id": "PVTF1-20", "name": "Milestone", "dataType": "MILESTONE"},
            "ProjectV2IterationField": None,
            "ProjectV2SingleSelectField": None,
        },
        "milestone": None,
    }


@pytest.mark.parametrize(
    "arguments,expected",
    [
        ({"organization": "example", "project_items_rest": True}, ["PVTI1", "PVTI2", "PVTI3", "PVTI4"]),
        (
            {"owner": "example", "project_number": 1, "project_items_rest": True},
            ["PVTI1", "PVTI2", "PVTI3", "PVTI4"],
        ),
        ({"user": "alice", "project_items_rest": True}, ["PVTI5"]),
        ({"organization": "example", "project_number": 1, "project_item_id": 1001}, ["PVTI1"]),
        ({"user": "alice", "project_number": 1, "project_item_id": 1005}, ["PVTI5"]),
        ({"owner": "alice", "project_number": 1, "project_item_id": 1005}, ["PVTI5"]),
        ({"organization": "example", "project_number": 1, "project_view_number": 1}, ["PVTI1", "PVTI2"]),
        ({"organization": "example", "project_number": 1, "project_view_number": 2}, ["PVTI3", "PVTI4"]),
        ({"user": "alice", "project_number": 1, "project_view_number": 1}, ["PVTI5"]),
        ({"organization": "example", "project_item_query": "is:issue"}, ["PVTI1"]),
        ({"user": "alice", "project_item_query": "is:issue"}, ["PVTI5"]),
        ({"organization": "example", "project_item_query": "is:pr"}, ["PVTI2"]),
        ({"organization": "example", "project_number": 2, "project_view_number": 1}, []),
        (
            {
                "project_owners": [{"login": "example"}, {"login": "alice"}],
                "project_number": 1,
                "project_view_number": 1,
            },
            ["PVTI1", "PVTI2", "PVTI5"],
        ),
    ],
)
def test_rest_item_collection_lookup_view_and_query_routes(pilot, projects, monkeypatch, arguments, expected):
    _, contract, _ = pilot
    install(monkeypatch, projects.respond_all)
    rows = scan(contract, "project_items", **arguments)
    assert [row["project_item_node_id"] for row in rows] == expected


def test_rest_item_routes_preserve_exact_canonical_typed_graphql_rows(pilot, projects, monkeypatch):
    _, contract, _ = pilot
    requests = install(monkeypatch, projects.respond_all)
    graph = scan(contract, "project_items", organization="example", project_number=1)
    rest = scan(contract, "project_items", organization="example", project_number=1, project_items_rest=True)
    numeric = scan(contract, "project_items", organization="example", project_number=1, project_item_id=1001)
    node = scan(contract, "project_items", project_item_node_id="PVTI1")
    assert graph == rest
    assert graph[:1] == numeric == node
    assert rest[1]["is_archived"] is True and rest[3]["content"] is None
    assert rest[0]["content"]["Issue"]["title"] == "One issue in two projects"
    assert len([r for r in requests if r.url.path == "/orgs/example/projectsV2/1/items"]) == 4


@pytest.mark.parametrize(
    "entity,expected",
    [
        ("project_field_values", 13),
        ("project_field_labels", 3),
        ("project_field_users", 2),
        ("project_field_pull_requests", 2),
        ("project_field_reviewers", 2),
    ],
)
def test_view_population_applies_to_existing_field_and_member_entities(
    pilot, projects, monkeypatch, entity, expected
):
    _, contract, _ = pilot
    install(monkeypatch, projects.respond_all)
    rows = scan(contract, entity, organization="example", project_number=1, project_view_number=1)
    assert len(rows) == expected
    assert {r["project_item_node_id"] for r in rows} <= {"PVTI1", "PVTI2"}


def test_numeric_rest_lookup_retains_independent_field_values_not_rest_projection(
    pilot, projects, monkeypatch
):
    _, contract, _ = pilot
    install(monkeypatch, projects.respond_all)
    rows = scan(
        contract, "project_field_values", organization="example", project_number=1, project_item_id=1001
    )
    assert len(rows) == 10
    numeric = next(r for r in rows if r["project_field_id"] == 11)
    assert numeric["number_value"] == 3.5
    selected = scan(
        contract,
        "project_field_values",
        organization="example",
        project_number=1,
        project_view_number=1,
        project_field_id=11,
    )
    assert [r["number_value"] for r in selected] == [3.5, 8.0]


def test_rest_query_is_encoded_and_applied_to_item_discovery_only(pilot, projects, monkeypatch):
    _, contract, _ = pilot
    requests = install(monkeypatch, projects.respond_all)
    rows = scan(contract, "project_field_values", user="alice", project_item_query="is:issue")
    assert len(rows) == 1 and rows[0]["project_node_id"] == "PVT3"
    discovery = [r for r in requests if r.url.path.endswith("/items")]
    assert len(discovery) == 1 and discovery[0].url.params["q"] == "is:issue"
    assert all("q" not in r.url.params for r in requests if not r.url.path.endswith("/items"))


@pytest.mark.parametrize(
    "arguments",
    [
        {"organization": "example", "project_item_id": 1001},
        {"organization": "example", "project_view_number": 1},
        {"organization": "example", "project_number": 1, "project_item_id": 1001, "project_view_number": 1},
        {
            "organization": "example",
            "project_number": 1,
            "project_view_number": 1,
            "project_item_query": "is:issue",
        },
        {"organization": "example", "project_items_rest": True, "project_item_query": "is:issue"},
        {"organization": "example", "project_item_query": ""},
        {"organization": "example", "project_number": 1, "project_view_number": 0},
        {"organization": "example", "project_number": 1, "project_item_id": 0},
        {"organization": "example", "project_items_rest": False},
    ],
)
def test_rest_item_invalid_scope_selectors_fail_before_http(pilot, monkeypatch, arguments):
    _, contract, _ = pilot
    requests = install(monkeypatch, lambda request: pytest.fail("Invalid Projects scope must not fetch"))
    with pytest.raises(GeneratedContractError):
        scan(contract, "project_items", **arguments)
    assert requests == []


@pytest.mark.parametrize(
    "arguments",
    [
        {"organization": "example", "project_number": 1, "project_item_id": 999},
        {"user": "alice", "project_number": 1, "project_item_id": 1001},
        {"organization": "example", "project_number": 1, "project_view_number": 999},
    ],
)
def test_missing_or_wrong_owner_item_and_view_are_errors_not_empty_populations(
    pilot, projects, monkeypatch, arguments
):
    _, contract, _ = pilot
    install(monkeypatch, projects.respond_all)
    with pytest.raises(Exception, match="404"):
        scan(contract, "project_items", **arguments)


def test_rest_discovery_requires_node_identity_before_hydration(pilot, projects, monkeypatch):
    import httpx

    _, contract, _ = pilot

    def respond(request):
        result = projects.respond_all(request)
        if request.url.path.endswith("/1/items"):
            payload = result.json()
            payload[0].pop("node_id")
            return httpx.Response(200, json=payload, headers=result.headers, request=request)
        return result

    requests = install(monkeypatch, respond)
    with pytest.raises(GeneratedContractError, match="required|NULL|non.null"):
        scan(contract, "project_items", organization="example", project_number=1, project_items_rest=True)
    assert not any(r.url.path == "/graphql" for r in requests)


def test_discovered_item_cannot_disappear_during_node_hydration(pilot, projects, monkeypatch):
    import httpx

    _, contract, _ = pilot

    def respond(request):
        if request.url.path == "/graphql":
            return httpx.Response(200, json={"data": {"node": None}}, request=request)
        return projects.respond_all(request)

    install(monkeypatch, respond)
    with pytest.raises(GeneratedContractError, match="one|single|required"):
        scan(contract, "project_items", organization="example", project_number=1, project_items_rest=True)


@pytest.mark.parametrize("failure", ["node", "project", "numeric"])
def test_rest_hydration_preserves_discovered_node_project_and_numeric_identity(
    pilot, projects, monkeypatch, failure
):
    import httpx

    _, contract, _ = pilot

    def respond(request):
        result = projects.respond_all(request)
        if request.url.path == "/graphql":
            payload = result.json()
            row = payload["data"]["node"]
            if failure == "node":
                row["id"] = "PVTI2"
            elif failure == "project":
                row["project"]["id"] = "PVT3"
            else:
                row["fullDatabaseId"] = "1002"
            return httpx.Response(200, json=payload, headers=result.headers, request=request)
        return result

    install(monkeypatch, respond)
    with pytest.raises(GeneratedContractError, match="row assertion"):
        scan(contract, "project_items", organization="example", project_number=1, project_item_id=1001)


def test_later_rest_item_page_permission_failure_is_not_complete_population(pilot, projects, monkeypatch):
    import httpx

    _, contract, _ = pilot

    def respond(request):
        if request.url.path.endswith("/1/items") and request.url.params.get("after") == "1":
            return httpx.Response(403, json={"message": "Projects item page denied"}, request=request)
        return projects.respond_all(request)

    install(monkeypatch, respond)
    with pytest.raises(Exception, match="403|denied"):
        scan(contract, "project_items", organization="example", project_number=1, project_items_rest=True)


def test_empty_owner_cohort_with_rest_selector_does_not_fetch(pilot, monkeypatch):
    _, contract, _ = pilot
    requests = install(monkeypatch, lambda request: pytest.fail("Empty cohort must not fetch"))
    assert scan(contract, "project_items", project_owners=[], project_items_rest=True) == []
    assert requests == []
