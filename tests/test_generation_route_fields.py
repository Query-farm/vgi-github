"""Distinct patch-version facts survive routes with different typed structures."""

from copy import deepcopy

import httpx
import pytest

from tests.helpers import install
from tests.test_generated_runtime import run
from vgi_github.generation.artifacts import _parameter_constraints
from vgi_github.generation.routes import compile_routes
from vgi_github.generation.schema import compile_rest_entity


def advisory_routes():
    entities, routes = [], []
    for scope, property_name in (("global", "first_patched_version"), ("repository", "patched_versions")):
        entity = {
            "name": scope + "_source",
            "arguments": [{"name": "selector", "type": "BOOLEAN", "position": 0}],
            "grain": ["id"],
            "columns": [
                {"name": "id", "path": ["id"]},
                {"name": "vulnerabilities", "path": ["vulnerabilities"]},
            ],
            "transport": {
                "kind": "rest",
                "operation_id": scope + "/get",
                "result_shape": "object",
                "pagination": {"kind": "none"},
                "query_bindings": {"scope": {"argument": "selector"}},
            },
        }
        response = {
            "type": "object",
            "required": ["id", "vulnerabilities"],
            "properties": {
                "id": {"type": "string"},
                "vulnerabilities": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["package", property_name],
                        "properties": {"package": {"type": "string"}, property_name: {"type": "string"}},
                    },
                },
            },
        }
        spec = {
            "paths": {
                "/" + scope: {
                    "get": {
                        "operationId": scope + "/get",
                        "parameters": [
                            {"name": "scope", "in": "query", "required": True, "schema": {"type": "boolean"}}
                        ],
                        "responses": {"200": {"content": {"application/json": {"schema": response}}}},
                    }
                }
            }
        }
        entities.append(compile_rest_entity(spec, entity))
        parameter = scope + "_scope"
        routes.append(
            {
                "name": scope,
                "arguments": [{"name": parameter, "type": "BOOLEAN", "position": 0}],
                "select": [parameter],
                "columns": [
                    {"name": name, "source_stage": "rows", "source_column": name}
                    for name in ("id", "vulnerabilities")
                ],
                "traversal": {
                    "stages": [
                        {
                            "name": "rows",
                            "entity": entity["name"],
                            "arguments": {"selector": {"parameter": parameter}},
                        }
                    ],
                    "output_stage": "rows",
                },
            }
        )
    function = {
        "name": "advisories",
        "description": "Distinct patch facts.",
        "grain": ["id"],
        "semantics": {},
        "routes": routes,
        "nullable_struct_fields": [
            "vulnerabilities[].first_patched_version",
            "vulnerabilities[].patched_versions",
        ],
    }
    return {"entities": entities, "scopes": {}}, {"functions": [function]}


def test_route_specific_nested_facts_remain_distinct_and_absence_is_null(monkeypatch):
    contract, overlay = advisory_routes()
    contract = compile_routes(contract, overlay)
    function = contract["functions"][0]
    assert (
        function["columns"][1]["type"]
        == 'STRUCT("package" VARCHAR, "first_patched_version" VARCHAR, "patched_versions" VARCHAR)[]'
    )

    def respond(request):
        patch = (
            {"first_patched_version": "2.0"}
            if request.url.path == "/global"
            else {"patched_versions": ">=2.0,<3"}
        )
        return httpx.Response(200, json={"id": "GHSA-1", "vulnerabilities": [{"package": "pkg", **patch}]})

    install(monkeypatch, respond)
    for arguments, expected in (
        ({"global_scope": [True]}, {"first_patched_version": "2.0", "patched_versions": None}),
        ({"repository_scope": [True]}, {"first_patched_version": None, "patched_versions": ">=2.0,<3"}),
    ):
        result = run(function, arguments, contract=contract)
        rows = [row for batch in result.batches for row in batch.to_pylist()]
        assert rows == [{"id": "GHSA-1", "vulnerabilities": [{"package": "pkg", **expected}]}]


def test_route_specific_fields_require_exact_explicit_absence_approval():
    contract, overlay = advisory_routes()
    missing = deepcopy(overlay)
    missing["functions"][0].pop("nullable_struct_fields")
    with pytest.raises(ValueError, match="explicit nullable_struct_fields approval"):
        compile_routes(contract, missing)
    overlay["functions"][0]["nullable_struct_fields"].append("vulnerabilities[].invented")
    with pytest.raises(ValueError, match="absent from at least one route"):
        compile_routes(contract, overlay)


def test_route_struct_union_cannot_coerce_a_common_field_type():
    contract, overlay = advisory_routes()
    package = contract["entities"][1]["columns"][1]["schema"]["item"]["fields"][0]
    package["schema"]["type"] = "BIGINT"
    with pytest.raises(ValueError, match="identical selected concrete types"):
        compile_routes(contract, overlay)


def default_routes():
    contract, overlay = advisory_routes()
    route = overlay["functions"][0]["routes"][-1]
    route.pop("select")
    route.update(default=True, arguments=[])
    route["traversal"]["stages"][0]["arguments"]["selector"] = {"literal": True}
    return contract, overlay


def test_default_catalog_route_and_explicit_lookup_share_one_entity(monkeypatch):
    contract, overlay = default_routes()
    contract = compile_routes(contract, overlay)
    assert _parameter_constraints(contract) == []
    requests = install(
        monkeypatch,
        lambda request: httpx.Response(
            200,
            json={
                "id": "GHSA-1",
                "vulnerabilities": [
                    {
                        "package": "pkg",
                        **(
                            {"first_patched_version": "2.0"}
                            if request.url.path == "/global"
                            else {"patched_versions": ">=2.0"}
                        ),
                    }
                ],
            },
        ),
    )
    for args, path in (({}, "/repository"), ({"global_scope": [True]}, "/global")):
        result = run(contract["functions"][0], args, contract=contract)
        assert sum(batch.num_rows for batch in result.batches) == 1
        assert requests[-1].url.path == path


@pytest.mark.parametrize("mutation", ["not_final", "false", "select", "required_argument"])
def test_default_route_requires_explicit_unambiguous_callable_fallback(mutation):
    contract, overlay = default_routes()
    routes = overlay["functions"][0]["routes"]
    if mutation == "not_final":
        routes.reverse()
    elif mutation == "false":
        routes[-1]["default"] = False
    elif mutation == "select":
        routes[-1]["select"] = []
    else:
        routes[-1]["arguments"] = [{"name": "required", "type": "BIGINT"}]
    with pytest.raises(ValueError, match="default route"):
        compile_routes(contract, overlay)


def value_routes():
    contract, overlay = advisory_routes()
    for route, value in zip(overlay["functions"][0]["routes"], (True, False), strict=True):
        route["arguments"] = [{"name": "population", "type": "BOOLEAN", "enum": [True, False]}]
        route["select"] = ["population"]
        route["select_values"] = {"population": [value]}
        route["traversal"]["stages"][0]["arguments"]["selector"] = {"parameter": "population"}
    return contract, overlay


def test_route_value_selection_preserves_reviewed_enum_subsets():
    contract, overlay = value_routes()
    result = compile_routes(contract, overlay)["functions"][0]
    assert [route["select_values"] for route in result["routes"]] == [
        {"population": [True]},
        {"population": [False]},
    ]
    assert result["arguments"][0]["enum"] == [True, False]


@pytest.mark.parametrize(
    "conditions",
    [
        None,
        {},
        [],
        {"absent": [True]},
        {"population": []},
        {"population": [True, True]},
        {"population": [1]},
        {"population": ["public"]},
        {"population": True},
    ],
)
def test_route_value_selection_requires_nonempty_typed_enum_subsets(conditions):
    contract, overlay = value_routes()
    overlay["functions"][0]["routes"][0]["select_values"] = conditions
    with pytest.raises(ValueError, match="select_values"):
        compile_routes(contract, overlay)


def test_route_value_selection_requires_declared_parameter_enum():
    contract, overlay = value_routes()
    overlay["functions"][0]["routes"][0]["arguments"][0].pop("enum")
    with pytest.raises(ValueError, match="select_values"):
        compile_routes(contract, overlay)


def test_default_route_cannot_have_value_selection():
    contract, overlay = default_routes()
    overlay["functions"][0]["routes"][-1]["select_values"] = {"population": [True]}
    with pytest.raises(ValueError, match="default route"):
        compile_routes(contract, overlay)


def test_native_presence_constraints_keep_only_shared_value_route_requirements():
    from vgi_github.generation.artifacts import _parameter_constraints

    contract = {
        "scopes": {},
        "functions": [
            {
                "name": "reports",
                "routes": [
                    {
                        "selection": ["kind"],
                        "select_values": {"kind": ["day"]},
                        "arguments": [
                            {"name": name, "nullable": False} for name in ["kind", "organization", "day"]
                        ],
                        "traversal": {"stages": []},
                    },
                    {
                        "selection": ["kind"],
                        "select_values": {"kind": ["latest"]},
                        "arguments": [{"name": name, "nullable": False} for name in ["kind", "organization"]],
                        "traversal": {"stages": []},
                    },
                ],
            }
        ],
    }
    assert _parameter_constraints(contract) == [
        {"kind": "at_least_one", "parameters": ["kind"], "datasets": ["reports"]},
        {"kind": "requires", "parameters": ["organization"], "datasets": ["reports"], "when": "kind"},
    ]


@pytest.mark.parametrize("entity_name", ["team_memberships", "organization_invitations"])
def test_route_local_identity_pairs_do_not_constrain_organization_wide_routes(entity_name):
    lookup = {
        "selection": ["lookup"],
        "arguments": [
            {"name": "lookup", "nullable": False},
            {"name": "organization", "nullable": True},
            {"name": "team_slug", "nullable": True},
            {"name": "team_numeric_id", "nullable": True},
        ],
        "traversal": {"stages": [{"name": "team", "scope": "exact_team"}]},
    }
    if entity_name == "team_memberships":
        broad = {
            "selection": ["organization"],
            "arguments": [
                {"name": "organization", "nullable": False},
                {"name": "team_slug", "nullable": True},
            ],
            "traversal": {"stages": [{"name": "teams", "scope": "organization_teams"}]},
        }
        selectors = ["lookup", "organization"]
        expected_extra = []
    else:
        broad = {
            "selection": ["population"],
            "arguments": [{"name": name, "nullable": False} for name in ["population", "organization"]],
            "traversal": {"stages": []},
        }
        selectors = ["lookup", "population"]
        expected_extra = [
            {
                "kind": "requires",
                "parameters": ["organization"],
                "datasets": [entity_name],
                "when": "population",
            }
        ]
    contract = {
        "functions": [{"name": entity_name, "routes": [lookup, broad]}],
        "scopes": {
            "exact_team": {
                "requires_parameters": {"organization": ["team_slug"], "team_slug": ["organization"]}
            },
            "organization_teams": {"requires_parameters": {"team_slug": ["organization"]}},
        },
    }
    assert _parameter_constraints(contract) == [
        {"kind": "at_least_one", "parameters": selectors, "datasets": [entity_name]},
        *expected_extra,
        {
            "kind": "requires",
            "parameters": ["organization"],
            "datasets": [entity_name],
            "when": "team_slug",
        },
    ]


def test_explicit_missing_route_column_has_derived_type_and_null_absence(monkeypatch):
    contract, overlay = advisory_routes()
    definition = overlay["functions"][0]
    definition["routes"][1]["columns"] = definition["routes"][1]["columns"][:1]
    definition["nullable_struct_fields"] = []
    definition["nullable_route_fields"] = ["vulnerabilities"]
    compiled = compile_routes(contract, overlay)
    install(
        monkeypatch,
        lambda request: httpx.Response(
            200,
            json={
                "id": "GHSA-1",
                "vulnerabilities": [
                    {"package": "pkg", "first_patched_version": "2.0", "patched_versions": ">=2.0"}
                ],
            },
        ),
    )
    for selected, expected in (
        ({"global_scope": [True]}, [{"package": "pkg", "first_patched_version": "2.0"}]),
        ({"repository_scope": [True]}, None),
    ):
        output = run(compiled["functions"][0], selected, contract=compiled)
        rows = [row for batch in output.batches for row in batch.to_pylist()]
        assert rows == [{"id": "GHSA-1", "vulnerabilities": expected}]
    assert compiled["functions"][0]["columns"][1]["nullable"] is True


@pytest.mark.parametrize("approved", [[], ["absent"], ["vulnerabilities", "vulnerabilities"]])
def test_missing_route_columns_require_exact_reviewed_approval(approved):
    contract, overlay = advisory_routes()
    definition = overlay["functions"][0]
    definition["routes"][1]["columns"] = definition["routes"][1]["columns"][:1]
    definition["nullable_struct_fields"] = []
    definition["nullable_route_fields"] = approved
    with pytest.raises(ValueError, match="nullable_route_fields"):
        compile_routes(contract, overlay)
