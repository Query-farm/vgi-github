"""Independent whole-API cases: omitted paths must remain visible as gaps."""

import json
from copy import deepcopy
from pathlib import Path

import pytest

from scripts import generate_semantic_catalog as generator
from vgi_github.generation.coverage import (
    api_inventory,
    audit_coverage,
    graphql_inventory,
    rest_response_shapes,
)
from vgi_github.generation.overlay import load_overlay
from vgi_github.generation.schema import compile_contract

SDL = """
interface Actor { id: ID! }
type Person implements Actor { id: ID!, organization: Organization, friends(first: Int): PersonConnection! }
type Robot implements Actor { id: ID!, owner: Person }
type PersonConnection { nodes: [Person!]!, pageInfo: PageInfo! }
type PageInfo { hasNextPage: Boolean!, endCursor: String }
type Organization { id: ID!, members: PersonConnection! }
union Result = Organization | Robot
type Query { actor: Actor, search: [Result!]!, person(login: String!): Person, old: Int @deprecated }
type Secret { value: String }
type Mutation { remove: Secret }
"""
SELECTED = """
type Query { person(login: String!): Person }
type Person { id: ID! }
"""


def test_query_graph_covers_inverse_edges_cycles_abstract_variants_and_pagination():
    inventory = graphql_inventory(SDL)
    rows = {row["coordinate"]: row for row in inventory["fields"]}
    assert set(rows) == {
        "Actor.id",
        "Person.id",
        "Person.organization",
        "Person.friends",
        "Robot.id",
        "Robot.owner",
        "PersonConnection.nodes",
        "PersonConnection.pageInfo",
        "PageInfo.hasNextPage",
        "PageInfo.endCursor",
        "Organization.id",
        "Organization.members",
        "Query.actor",
        "Query.search",
        "Query.person",
        "Query.old",
    }
    assert rows["Person.organization"]["target_type"] == "Organization"
    assert rows["Person.organization"]["collection"] is False
    assert rows["Organization.members"]["target_type"] == "Person"
    assert rows["Organization.members"]["collection"] is True
    assert rows["Organization.members"]["opposite_direction_candidates"] == ["Person.organization"]
    assert rows["Person.organization"]["opposite_direction_candidates"] == ["Organization.members"]
    assert rows["Person.friends"]["arguments"] == {"first": "Int"}
    assert rows["Query.search"]["collection"] is True
    assert rows["Query.old"]["deprecated"] is True
    assert inventory["excluded_roots"] == ["Mutation"]
    assert not inventory["schema_diagnostics"]


def test_full_schema_errors_remain_visible_even_when_selected_schema_is_valid():
    inventory = graphql_inventory(SDL.replace("id: ID!, owner", "id: ID!, id: ID!, owner"))
    assert inventory["schema_diagnostics"] == ["Field 'Robot.id' can only be defined once."]


def test_rest_shapes_keep_envelopes_binary_responses_and_writes_separate():
    spec = {
        "paths": {
            "/runs": {
                "get": {
                    "operationId": "runs/list",
                    "responses": {
                        "200": {
                            "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Runs"}}}
                        },
                        "403": {"description": "Forbidden"},
                    },
                },
                "post": {"operationId": "runs/create"},
            },
            "/logs": {
                "get": {
                    "operationId": "runs/logs",
                    "responses": {
                        "200": {
                            "content": {"application/zip": {"schema": {"type": "string", "format": "binary"}}}
                        },
                        "204": {"description": "No body"},
                    },
                }
            },
        },
        "components": {
            "schemas": {
                "Runs": {
                    "type": "object",
                    "properties": {
                        "total_count": {"type": "integer"},
                        "workflow_runs": {"type": "array", "items": {"$ref": "#/components/schemas/Run"}},
                    },
                },
                "Run": {"type": "object", "properties": {"id": {"type": "integer"}}},
            }
        },
    }
    result = rest_response_shapes(spec)
    assert set(result) == {"runs/list", "runs/logs"}
    assert result["runs/list"][0]["collections"] == {
        "workflow_runs": {
            "type": "array",
            "items": {"type": "object", "schema_ref": "#/components/schemas/Run"},
        }
    }
    assert result["runs/logs"] == [
        {
            "status": "200",
            "media_type": "application/zip",
            "root": {"type": "string", "format": "binary"},
            "collections": {},
        },
        {"status": "204", "body": "none"},
    ]


def fixtures():
    operation = {
        "operation_id": "people/get",
        "path": "/people/{login}",
        "category": "people",
        "products": ["cloud", "enterprise"],
        "deprecated": False,
        "parameters": [],
        "response_schema_sha256": {},
        "documentation_url": "",
    }
    other = {**operation, "operation_id": "organizations/members", "path": "/organizations/{org}/members"}
    inventory = api_inventory(
        {"revision": "a" * 40, "sources": [], "operations": [operation, other]}, SDL, {}
    )
    source = {
        "name": "person_lookup",
        "transport": {"kind": "rest", "operation_id": "people/get", "product": "cloud"},
    }
    function = {
        "name": "people",
        "grain": ["id"],
        "arguments": [{"name": "login"}],
        "traversal": {
            "stages": [
                {"name": "people", "entity": "person_lookup", "arguments": {"login": {"parameter": "login"}}}
            ]
        },
    }
    contract = {"entities": [source], "functions": [function], "scopes": {}, "relationships": []}
    return contract, inventory


def test_unselected_api_routes_are_gaps_and_product_selection_is_not_inferred():
    contract, inventory = fixtures()
    result = audit_coverage(contract, inventory, SELECTED)
    assert result["semantic_coverage_complete"] is False
    assert result["summary"]["rest_operations"] == 2
    assert result["summary"]["rest_selected_operations"] == 1
    assert result["rest_operations"][0]["selected_sources_by_product"] == {
        "cloud": ["person_lookup"],
        "enterprise": [],
    }
    assert result["rest_operations"][1]["selected_sources_by_product"] == {"cloud": [], "enterprise": []}
    graph = {row["coordinate"]: row for row in result["graphql_fields"]}
    assert graph["Organization.members"]["selected_sources"] == []
    assert graph["Organization.members"]["in_selected_schema"] is False
    assert graph["Person.id"]["in_selected_schema"] is True
    assert result["entity_routes"][0]["stages"][0]["sources"] == ["person_lookup"]


def test_compiled_but_unreachable_sources_do_not_inflate_operation_or_graphql_path_selection():
    contract, inventory = fixtures()
    contract["entities"].extend(
        [
            {
                "name": "unused_members",
                "transport": {
                    "kind": "rest",
                    "operation_id": "organizations/members",
                    "product": "cloud",
                },
            },
            {
                "name": "unused_person",
                "transport": {
                    "kind": "graphql",
                    "result_path": ["person"],
                    "document": '{ person(login: "unused") { id } }',
                },
                "source": {"field_path": ["person"]},
                "columns": [],
            },
        ]
    )
    result = audit_coverage(contract, inventory, SELECTED)
    assert result["summary"]["rest_operations"] == 2
    assert result["summary"]["rest_selected_operations"] == 1
    assert result["summary"]["graphql_selected_schema_fields"] == 2
    assert result["summary"]["graphql_source_path_fields"] == 0
    assert result["contract_keys"]["graphql"]["summary"]["fetched_fields"] == 0
    assert result["contract_keys"]["graphql"]["summary"]["bound_arguments"] == 0
    assert result["contract_keys"]["source_reachability"]["unreachable_sources"] == [
        "unused_members",
        "unused_person",
    ]
    assert len(contract["entities"]) == 3


def test_scope_exclusions_and_intentional_alternatives_do_not_inflate_selection():
    contract, inventory = fixtures()
    policy = {
        "excluded_rest_categories": {"people": "User excluded this category."},
        "operation_decisions": {
            "organizations/members": {
                "status": "intentionally_unselected",
                "reason": "A complete alternative is modeled.",
                "alternative_entities": ["people"],
            }
        },
        "milestones": {"first": {"operation_ids": ["people/get", "organizations/members"]}},
    }
    result = audit_coverage(contract, inventory, SELECTED, policy=policy)
    assert result["summary"]["rest_operations"] == 2
    assert result["summary"]["rest_excluded_operations"] == 2
    assert result["summary"]["rest_in_scope_operations"] == 0
    assert result["summary"]["rest_selected_operations"] == 1
    assert result["milestones"]["first"]["selected_operations"] == 1
    assert result["milestones"]["first"]["remaining_operations"] == []
    assert result["milestones"]["first"]["intentionally_unselected_operations"] == ["organizations/members"]
    policy["excluded_rest_categories"]["not-an-api-category"] = "Typo"
    with pytest.raises(ValueError, match="known REST categories"):
        audit_coverage(contract, inventory, SELECTED, policy=policy)


def test_operation_exclusions_preserve_other_reads_in_the_same_category():
    contract, inventory = fixtures()
    policy = {"excluded_rest_operations": {"organizations/members": "Enterprise-only membership."}}
    result = audit_coverage(contract, inventory, SELECTED, policy=policy)
    assert result["summary"]["rest_operations"] == 2
    assert result["summary"]["rest_excluded_operations"] == 1
    assert result["summary"]["rest_in_scope_operations"] == 1
    assert result["summary"]["rest_in_scope_selected_operations"] == 1
    assert result["rest_categories"][0]["implementation_scope"] == "partial"
    policy["excluded_rest_operations"]["unknown/get"] = "Typo"
    with pytest.raises(ValueError, match="known REST operations"):
        audit_coverage(contract, inventory, SELECTED, policy=policy)


def test_graphql_policy_marks_fields_without_hiding_schema_selection_or_shared_types():
    contract, inventory = fixtures()
    policy = {
        "excluded_graphql_types": {
            "Organization": "Organization administration is excluded in this fixture."
        },
        "excluded_graphql_fields": {
            "Organization.id": "The explicit field reason overrides its type reason.",
            "Query.person": "This one retrieval is excluded in this fixture.",
        },
    }
    result = audit_coverage(contract, inventory, SELECTED, policy=policy)
    graph = {row["coordinate"]: row for row in result["graphql_fields"]}
    assert result["summary"]["graphql_read_fields"] == 16
    assert result["summary"]["graphql_excluded_fields"] == 3
    assert result["summary"]["graphql_in_scope_read_fields"] == 13
    assert result["summary"]["graphql_selected_schema_fields"] == 2
    assert result["summary"]["graphql_in_scope_selected_schema_fields"] == 1
    assert result["summary"]["graphql_excluded_selected_schema_fields"] == 1
    assert graph["Query.person"]["in_selected_schema"] is True
    assert graph["Query.person"]["implementation_scope"] == "excluded"
    assert (
        graph["Organization.id"]["exclusion_reason"] == policy["excluded_graphql_fields"]["Organization.id"]
    )
    assert (
        graph["Organization.members"]["exclusion_reason"] == policy["excluded_graphql_types"]["Organization"]
    )
    for coordinate in (
        "Person.id",
        "Person.organization",
        "PersonConnection.nodes",
        "Actor.id",
        "Robot.owner",
    ):
        assert graph[coordinate]["implementation_scope"] == "included"
        assert graph[coordinate]["exclusion_reason"] is None
    keys = result["contract_keys"]["graphql"]["summary"]
    assert keys["declared_arguments"] == 2
    assert keys["in_scope_declared_arguments"] == 1
    assert keys["excluded_declared_arguments"] == 1
    assert keys["fetched_fields"] == keys["public_fields"] == 0
    policy["excluded_graphql_types"]["Unknown"] = "Unknown type"
    with pytest.raises(ValueError, match="GraphQL type exclusions.*known exact names"):
        audit_coverage(contract, inventory, SELECTED, policy=policy)


def test_inventory_detects_missing_endpoints_and_graphql_signature_drift():
    contract, inventory = fixtures()
    broken = deepcopy(inventory)
    broken["rest"]["operations"].pop(0)
    with pytest.raises(ValueError, match="Selected REST operations are absent"):
        audit_coverage(contract, broken, SELECTED)
    with pytest.raises(ValueError, match="signature differs"):
        audit_coverage(contract, inventory, SELECTED.replace("ID!", "Int!"))


def test_relationship_does_not_claim_reverse_fetch_or_implicit_binding():
    contract, inventory = fixtures()
    target = deepcopy(contract["functions"][0])
    target.update(name="organizations", arguments=[{"name": "organization"}])
    contract["functions"].append(target)
    contract["relationships"] = [{"name": "people_to_organizations", "from": "people", "to": "organizations"}]
    relation = audit_coverage(contract, inventory, SELECTED)["relationship_directions"][0]
    assert relation["retrieval_route_binding"] == "not_declared"
    assert relation["directions"] == [
        {
            "from": "people",
            "to": "organizations",
            "target_routes": ["organizations"],
            "target_parameters": ["organization"],
            "retrievals": [],
        },
        {
            "from": "organizations",
            "to": "people",
            "target_routes": ["people"],
            "target_parameters": ["login"],
            "retrievals": [],
        },
    ]


def test_full_pinned_surface_tracks_implemented_and_remaining_navigation():
    root = Path(__file__).resolve().parents[1]
    overlay = load_overlay(root / "generation/pilot.json")
    specs, sdl, lock = generator.locked_inputs(root, overlay)
    inventory = generator.locked_inventory(root, lock)
    contract = compile_contract(specs, sdl, overlay)
    policy = json.loads((root / "generation/coverage-policy.json").read_text())
    result = audit_coverage(contract, inventory, sdl, policy=policy)
    assert result["summary"]["rest_operations"] == 780
    assert result["summary"]["rest_categories"] == 48
    assert result["summary"]["rest_excluded_operations"] == 390
    assert result["summary"]["rest_in_scope_operations"] == 390
    assert result["summary"]["rest_in_scope_selected_operations"] == 381
    assert result["milestones"]["releases_ci_artifacts"]["selected_operations"] == 23
    assert result["milestones"]["releases_ci_artifacts"]["remaining_operations"] == []
    assert result["summary"]["graphql_read_fields"] == 5389
    assert result["summary"]["graphql_excluded_fields"] == 2024
    assert result["summary"]["graphql_in_scope_read_fields"] == 3365
    graphql_keys = result["contract_keys"]["graphql"]["summary"]
    assert graphql_keys["declared_arguments"] == 1957
    assert graphql_keys["excluded_declared_arguments"] == 375
    assert graphql_keys["in_scope_declared_arguments"] == 1582
    assert graphql_keys["excluded_fetched_fields"] == 0
    assert graphql_keys["excluded_public_fields"] == 0
    assert graphql_keys["excluded_bound_arguments"] == 0
    assert result["summary"]["entities"] == 206
    graph = {row["coordinate"]: row for row in result["graphql_fields"]}
    for name in (
        "Repository.issues",
        "Repository.discussions",
        "Discussion.comments",
        "DiscussionComment.replies",
        "Label.issues",
        "Label.pullRequests",
    ):
        assert graph[name]["selected_sources"]
    assert result["summary"]["routes"] == 526
    assert result["summary"]["relationships"] == 298
    assert result["summary"]["analytical_relationships"] == 190
    assert {
        row["name"]
        for row in result["relationship_directions"]
        if row["retrieval_route_binding"] != "declared"
    } == {"codespace_permissions_to_devcontainers"}
    permissions = next(
        row
        for row in result["relationship_directions"]
        if row["name"] == "codespace_permissions_to_devcontainers"
    )
    assert permissions["retrieval_route_binding"] == "not_declared"
    assert all(direction["retrievals"] == [] for direction in permissions["directions"])
    for name in (
        "Issue.comments",
        "IssueComment.pullRequest",
        "CommitComment.commit",
        "User.organizations",
        "Organization.membersWithRole",
        "Team.repositories",
        "Team.childTeams",
        "PullRequestReview.pullRequest",
    ):
        assert graph[name]["navigation"] is True
        assert graph[name]["selected_sources"] == []
    assert "projects" in {row["category"] for row in result["rest_categories"]}
    assert "actions" in {row["category"] for row in result["rest_categories"]}
    manifest = json.loads((root / "vgi_github/rest_manifest.json").read_text())
    assert {row["operation_id"] for row in result["rest_operations"]} == {
        row["operation_id"] for row in manifest["operations"]
    }
