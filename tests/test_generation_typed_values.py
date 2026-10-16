"""Independent values exercise complete typed variants and population safeguards."""

from copy import deepcopy
from datetime import UTC, datetime

import httpx
import pytest
from graphql import build_schema, parse, validate

from scripts.generate_semantic_catalog import select_graphql
from tests.helpers import install
from tests.test_generated_runtime import run
from vgi_github.generated_runtime import GeneratedContractError
from vgi_github.generation.graph import compile_functions
from vgi_github.generation.schema import SchemaError, compile_graphql_entity, compile_rest_entity


def source(properties=None, required=None):
    row = {
        "type": "object",
        "properties": {"id": {"type": "integer"}, **(properties or {})},
        "required": ["id"] if required is None else required,
    }
    spec = {
        "paths": {
            "/records": {
                "get": {
                    "operationId": "records/list",
                    "responses": {
                        "200": {
                            "content": {
                                "application/json": {"schema": {"type": "array", "items": row}},
                            }
                        }
                    },
                }
            }
        }
    }
    entity = {
        "name": "records",
        "arguments": [],
        "columns": [{"name": "id", "path": ["id"]}],
        "grain": ["id"],
        "transport": {"kind": "rest", "operation_id": "records/list"},
    }
    return spec, entity


def emitted(entity, inputs=None, contract=None):
    result = run(entity, {name: [value] for name, value in (inputs or {}).items()}, contract=contract)
    return [row for batch in result.batches for row in batch.to_pylist()]


@pytest.mark.parametrize("record,error", [({}, "missing required"), ({"id": None}, "NULL is not allowed")])
def test_explicit_identity_qualification_rejects_optional_or_null_api_ids(monkeypatch, record, error):
    spec, entity = source(required=[])
    with pytest.raises(SchemaError, match="grain column"):
        compile_rest_entity(spec, entity)
    entity["policy"] = {"required_non_null_fields": ["id"]}
    compiled = compile_rest_entity(spec, entity)
    install(monkeypatch, lambda request: httpx.Response(200, json=[record]))
    with pytest.raises(GeneratedContractError, match=error):
        emitted(compiled)


def test_tagged_scalars_preserve_concrete_types_and_reject_boolean_as_integer(monkeypatch):
    spec, entity = source({"value": {"oneOf": [{"type": "integer"}, {"type": "string"}]}})
    entity["columns"].append({"name": "value", "path": ["value"], "representation": "tagged"})
    compiled = compile_rest_entity(spec, entity)
    install(
        monkeypatch,
        lambda request: httpx.Response(200, json=[{"id": 1, "value": 7}, {"id": 2, "value": "7"}]),
    )
    rows = emitted(compiled)
    assert rows == [
        {"id": 1, "value": {"matched_types": ["variant_1"], "variant_1": 7, "variant_2": None}},
        {"id": 2, "value": {"matched_types": ["variant_2"], "variant_1": None, "variant_2": "7"}},
    ]
    install(monkeypatch, lambda request: httpx.Response(200, json=[{"id": 3, "value": True}]))
    with pytest.raises(GeneratedContractError, match="oneOf variants"):
        emitted(compiled)


def test_anyof_keeps_overlapping_object_branches_without_selecting_an_arbitrary_winner(monkeypatch):
    spec, entity = source(
        {
            "value": {
                "anyOf": [
                    {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]},
                    {"type": "object", "properties": {"count": {"type": "integer"}}, "required": ["count"]},
                ]
            }
        }
    )
    entity["columns"].append({"name": "value", "path": ["value"], "representation": "tagged"})
    compiled = compile_rest_entity(spec, entity)
    install(
        monkeypatch, lambda request: httpx.Response(200, json=[{"id": 1, "value": {"name": "n", "count": 2}}])
    )
    value = emitted(compiled)[0]["value"]
    assert value == {
        "matched_types": ["variant_1", "variant_2"],
        "variant_1": {"name": "n"},
        "variant_2": {"count": 2},
    }


def test_variant_paths_keep_empty_and_nullable_actor_objects(monkeypatch):
    spec, entity = source(
        {
            "actor": {
                "nullable": True,
                "oneOf": [
                    {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]},
                    {"type": "object", "properties": {}},
                ],
            }
        }
    )
    entity["columns"].append({"name": "actor_name", "path": ["actor", "name"], "variant_paths": True})
    compiled = compile_rest_entity(spec, entity)
    install(
        monkeypatch,
        lambda request: httpx.Response(
            200,
            json=[
                {"id": 1, "actor": {"name": "Alice"}},
                {"id": 2, "actor": {}},
                {"id": 3, "actor": None},
            ],
        ),
    )
    assert [row["actor_name"] for row in emitted(compiled)] == ["Alice", None, None]


def test_optional_typed_dates_survive_continuations_and_null_query_parameters_are_absent(monkeypatch):
    spec, entity = source()
    spec["paths"]["/records"]["get"]["parameters"] = [
        {
            "name": "since",
            "in": "query",
            "schema": {"type": "string", "format": "date-time"},
        }
    ]
    entity["arguments"] = [
        {"name": "since", "type": "TIMESTAMP WITH TIME ZONE", "nullable": True, "default": None}
    ]
    entity["transport"]["query_bindings"] = {"since": {"argument": "since"}}
    compiled = compile_rest_entity(spec, entity)
    requests = install(monkeypatch, lambda request: httpx.Response(200, json=[{"id": 1}]))
    assert emitted(compiled, {"since": datetime(2026, 1, 2, 3, 4, tzinfo=UTC)}) == [{"id": 1}]
    assert requests[0].url.params["since"] == "2026-01-02T03:04:00+00:00"
    emitted(compiled, {"since": None})
    assert "since" not in requests[-1].url.params


def test_cumulative_upstream_cap_rejects_complete_looking_final_page(monkeypatch):
    spec, entity = source()
    entity["transport"]["pagination"] = {"kind": "link", "reject_at_rows": 3}
    compiled = compile_rest_entity(spec, entity)

    def handle(request):
        if "page" not in request.url.params:
            return httpx.Response(
                200,
                json=[{"id": 1}, {"id": 2}],
                headers={"Link": '<https://api.github.com/records?page=2>; rel="next"'},
            )
        return httpx.Response(200, json=[{"id": 3}])

    install(monkeypatch, handle)
    with pytest.raises(GeneratedContractError, match="completeness boundary"):
        emitted(compiled)


@pytest.mark.parametrize("truncated,items", [(True, []), (False, [1, 2, 3])])
def test_response_guards_reject_truncation_before_row_projection(monkeypatch, truncated, items):
    spec, entity = source()
    response = spec["paths"]["/records"]["get"]["responses"]["200"]["content"]["application/json"]
    response["schema"] = {
        "type": "object",
        "properties": {
            "id": {"type": "integer"},
            "truncated": {"type": "boolean"},
            "files": {"type": "array", "items": {"type": "integer"}},
        },
        "required": ["id", "truncated", "files"],
    }
    entity["transport"].update(
        result_shape="object",
        response_assertions=[
            {"path": ["truncated"], "comparison": "equal", "value": False},
            {"path": ["files"], "comparison": "length_lt", "value": 3},
        ],
    )
    compiled = compile_rest_entity(spec, entity)
    install(
        monkeypatch,
        lambda request: httpx.Response(200, json={"id": 1, "truncated": truncated, "files": items}),
    )
    with pytest.raises(GeneratedContractError, match="response assertion failed"):
        emitted(compiled)


SDL = """
interface Node { id: ID! }
type Query { node(id: ID!): Node }
type Box implements Node { id: ID!, values(first: Int, after: String): ValueConnection! }
type ValueConnection { nodes: [Value!]!, pageInfo: PageInfo! }
type PageInfo { hasNextPage: Boolean!, endCursor: String }
union Value = TextValue | NumberValue
type TextValue { field: Field!, text: String! }
type NumberValue { field: Field!, number: Float! }
union Field = TextField | NumberField
type TextField { id: ID!, name: String! }
type NumberField { id: ID!, name: String! }
"""


def union_entity():
    field = {
        "__typename": True,
        "... on TextField": {"id": True, "name": True},
        "... on NumberField": {"id": True, "name": True},
    }
    return {
        "name": "values",
        "arguments": [{"name": "box", "type": "VARCHAR"}],
        "columns": [
            {"name": "field_id", "path": ["field", "id"]},
            {"name": "kind", "path": ["__typename"]},
            {
                "name": "value",
                "path": [],
                "selection": {
                    "__typename": True,
                    "... on TextValue": {"field": field, "text": True},
                    "... on NumberValue": {"field": field, "number": True},
                },
            },
        ],
        "grain": ["field_id"],
        "transport": {
            "kind": "graphql",
            "field_path": ["node", "values"],
            "field_types": {"node": "Box"},
            "field_arguments": {
                "node": {"id": {"argument": "box"}},
                "values": {"first": {"literal": 100}, "after": {"cursor": True}},
            },
            "result_path": ["nodes"],
            "pagination": {"kind": "cursor", "page_info_path": ["pageInfo"]},
        },
    }


def test_nested_graphql_unions_keep_typed_values_and_scalar_identity(monkeypatch):
    entity = union_entity()
    selected = select_graphql(SDL, [entity])
    compiled = compile_graphql_entity(selected, entity)
    assert validate(build_schema(SDL), parse(compiled["transport"]["document"])) == []
    values = [
        {
            "__typename": "TextValue",
            "field": {"__typename": "TextField", "id": "F1", "name": "Title"},
            "text": "hello",
        },
        {
            "__typename": "NumberValue",
            "field": {"__typename": "NumberField", "id": "F2", "name": "Score"},
            "number": 2.5,
        },
    ]
    install(
        monkeypatch,
        lambda request: httpx.Response(
            200,
            json={
                "data": {
                    "node": {
                        "values": {
                            "nodes": values,
                            "pageInfo": {"hasNextPage": False, "endCursor": None},
                        }
                    }
                }
            },
        ),
    )
    rows = emitted(compiled, {"box": "B1"})
    assert [row["field_id"] for row in rows] == ["F1", "F2"]
    assert rows[0]["value"]["TextValue"]["text"] == "hello"
    assert rows[0]["value"]["NumberValue"] is None
    assert rows[1]["value"]["NumberValue"]["number"] == 2.5
    assert rows[1]["value"]["NumberValue"]["field"]["NumberField"] == {"id": "F2", "name": "Score"}
    values[0].pop("text")
    with pytest.raises(GeneratedContractError, match="missing required field"):
        emitted(compiled, {"box": "B1"})


def test_union_common_path_requires_every_variant_and_compatible_types():
    with pytest.raises(SchemaError, match="absent"):
        compile_graphql_entity(SDL.replace("field: Field!, number", "number"), union_entity())


def test_optional_parameter_filter_preserves_population_without_implicit_coercion(monkeypatch):
    spec, entity = source({"field_id": {"type": "integer"}}, ["id", "field_id"])
    entity["columns"].append({"name": "field_id", "path": ["field_id"]})
    physical = compile_rest_entity(spec, entity)
    definition = {
        "name": "values",
        "semantics": {},
        "arguments": [{"name": "field_id", "type": "BIGINT", "nullable": True, "default": None}],
        "columns": [
            {"name": name, "source_stage": "values", "source_column": name} for name in ("id", "field_id")
        ],
        "grain": ["id"],
        "traversal": {
            "stages": [
                {
                    "name": "values",
                    "entity": "records",
                    "arguments": {},
                    "where_parameters": {"field_id": "field_id"},
                }
            ],
            "output_stage": "values",
        },
    }
    overlay = {"functions": [definition]}
    contract = compile_functions({"entities": [physical]}, overlay)
    install(
        monkeypatch,
        lambda request: httpx.Response(200, json=[{"id": 1, "field_id": 3}, {"id": 2, "field_id": 4}]),
    )
    function = contract["functions"][0]
    assert emitted(function, {"field_id": 3}, contract) == [{"id": 1, "field_id": 3}]
    assert len(emitted(function, {"field_id": None}, contract)) == 2
    bad = deepcopy(overlay)
    bad["functions"][0]["arguments"][0]["type"] = "VARCHAR"
    with pytest.raises(SchemaError, match="preserve scalar"):
        compile_functions({"entities": [physical]}, bad)


def test_absence_filter_distinguishes_optional_object_from_required_object(monkeypatch):
    spec, entity = source(
        {"marker": {"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]}}
    )
    entity["columns"].append({"name": "marker", "path": ["marker"]})
    physical = compile_rest_entity(spec, entity)
    definition = {
        "name": "unmarked",
        "semantics": {},
        "arguments": [],
        "columns": [{"name": "id", "source_stage": "rows", "source_column": "id"}],
        "grain": ["id"],
        "traversal": {
            "stages": [{"name": "rows", "entity": "records", "arguments": {}, "where": {"marker": None}}],
            "output_stage": "rows",
        },
    }
    contract = compile_functions({"entities": [physical]}, {"functions": [definition]})
    install(
        monkeypatch,
        lambda request: httpx.Response(
            200, json=[{"id": 1}, {"id": 2, "marker": {"url": "https://example/2"}}]
        ),
    )
    assert emitted(contract["functions"][0], contract=contract) == [{"id": 1}]
    required = deepcopy(physical)
    required["columns"][1]["required"] = True
    with pytest.raises(SchemaError, match="literal does not match"):
        compile_functions({"entities": [required]}, {"functions": [definition]})


def test_struct_projection_preserves_optional_parent_and_exact_member_type(monkeypatch):
    spec, entity = source(
        {"owner": {"type": "object", "properties": {"id": {"type": "integer"}}, "required": ["id"]}}
    )
    entity["columns"].append({"name": "owner", "path": ["owner"]})
    physical = compile_rest_entity(spec, entity)
    definition = {
        "name": "owners",
        "semantics": {},
        "arguments": [],
        "grain": ["id"],
        "columns": [
            {"name": "id", "source_stage": "rows", "source_column": "id"},
            {"name": "owner_id", "source_stage": "rows", "source_column": "owner", "source_path": ["id"]},
        ],
        "traversal": {
            "stages": [{"name": "rows", "entity": "records", "arguments": {}}],
            "output_stage": "rows",
        },
    }
    contract = compile_functions({"entities": [physical]}, {"functions": [definition]})
    column = contract["functions"][0]["columns"][1]
    assert column["type"] == "BIGINT" and column["nullable"]
    install(monkeypatch, lambda request: httpx.Response(200, json=[{"id": 1}, {"id": 2, "owner": {"id": 7}}]))
    assert emitted(contract["functions"][0], contract=contract) == [
        {"id": 1, "owner_id": None},
        {"id": 2, "owner_id": 7},
    ]
    for path in (["missing"], ["id", "missing"], []):
        invalid = deepcopy(definition)
        invalid["columns"][1]["source_path"] = path
        with pytest.raises(SchemaError, match="source_path"):
            compile_functions({"entities": [physical]}, {"functions": [invalid]})


def test_selected_sdl_retains_known_unselected_actor_types(monkeypatch):
    sdl = """
        type Query { record: Record! }
        type Record { id: ID!, actor: Actor! }
        interface Actor { login: String! }
        type User implements Actor { login: String!, databaseId: Int }
        type EnterpriseUserAccount implements Actor { login: String! }
    """
    entity = {
        "name": "actor_identity",
        "arguments": [],
        "grain": ["id"],
        "columns": [
            {"name": "id", "path": ["id"]},
            {"name": "user_id", "path": ["actor", "databaseId"], "on_types": ["User"]},
        ],
        "transport": {
            "kind": "graphql",
            "field_path": ["record"],
            "field_arguments": {},
            "result_path": [],
            "pagination": {"kind": "none"},
        },
    }
    selected = select_graphql(sdl, [entity])
    compiled = compile_graphql_entity(selected, entity)
    assert compiled["columns"][1]["parent_types"] == ["EnterpriseUserAccount", "User"]
    install(
        monkeypatch,
        lambda request: httpx.Response(
            200,
            json={
                "data": {
                    "record": {
                        "id": "R1",
                        "actor": {"__typename": "EnterpriseUserAccount", "login": "enterprise-account"},
                    }
                }
            },
        ),
    )
    assert emitted(compiled) == [{"id": "R1", "user_id": None}]
