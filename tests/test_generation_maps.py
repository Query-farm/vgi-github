"""Independent dictionary, wide-integer and reviewed path transport contracts."""

import json
from copy import deepcopy
from datetime import date

import httpx
import pyarrow as pa
import pytest

from tests.helpers import install
from tests.test_generated_runtime import run
from vgi_github.generated_runtime import GeneratedContractError, _decode, make_function
from vgi_github.generation.graph import compile_functions
from vgi_github.generation.schema import SchemaError, compile_graphql_entity, compile_rest_entity


def rest_source(response, *, shape="object", path="/dictionary", parameters=None):
    spec = {
        "paths": {
            path: {
                "get": {
                    "operationId": "fixture/get",
                    "parameters": parameters or [],
                    "responses": {"200": {"content": {"application/json": {"schema": response}}}},
                }
            }
        }
    }
    entity = {
        "name": "dictionary",
        "arguments": [{"name": "scope", "type": "VARCHAR"}],
        "grain": ["scope"],
        "columns": [{"name": "scope", "source_argument": "scope"}],
        "transport": {"kind": "rest", "operation_id": "fixture/get", "result_shape": shape},
    }
    return spec, entity


def map_source(value=None, *, nullable=False, entries=False):
    value = {"type": "integer"} if value is None else value
    spec, entity = rest_source(
        {"type": "object", "additionalProperties": value, "nullable": nullable},
        shape="object_entries" if entries else "object",
    )
    if entries:
        entity["grain"].append("key")
        entity["columns"] += [
            {"name": "key", "source_entry": "key"},
            {"name": "value", "source_entry": "value"},
        ]
    else:
        entity["columns"].append({"name": "values", "path": []})
    return spec, entity


def emitted(entity, inputs=None, contract=None):
    result = run(entity, {name: [value] for name, value in (inputs or {}).items()}, contract=contract)
    return [row for batch in result.batches for row in batch.to_pylist()]


def test_map_is_native_arrow_map_with_exact_values_and_arbitrary_string_keys(monkeypatch):
    spec, entity = map_source()
    compiled = compile_rest_entity(spec, entity)
    assert compiled["columns"][1]["type"] == "MAP(VARCHAR, BIGINT)"
    descriptor = compiled["columns"][1]["schema"]
    assert descriptor == {
        "kind": "map",
        "key": {"kind": "scalar", "type": "VARCHAR", "nullable": False},
        "value": {"kind": "scalar", "type": "BIGINT", "nullable": False},
        "nullable": False,
    }
    arrow = make_function(compiled).FIXED_SCHEMA.field("values").type
    assert pa.types.is_map(arrow)
    assert arrow.key_type == pa.string()
    assert arrow.item_type == pa.int64()
    assert not arrow.key_field.nullable
    assert not arrow.item_field.nullable
    install(monkeypatch, lambda request: httpx.Response(200, json={"C++": 17, "λ/file": 2**40, "": 0}))
    assert emitted(compiled, {"scope": "example"}) == [
        {"scope": "example", "values": [("", 0), ("C++", 17), ("λ/file", 2**40)]}
    ]
    install(monkeypatch, lambda request: httpx.Response(200, json={}))
    assert emitted(compiled, {"scope": "example"}) == [{"scope": "example", "values": []}]


def test_nested_map_values_keep_struct_list_date_and_nullable_members(monkeypatch):
    value = {
        "type": "object",
        "required": ["dates", "totals"],
        "properties": {
            "dates": {"type": "array", "items": {"type": "string", "format": "date", "nullable": True}},
            "totals": {"type": "object", "additionalProperties": {"type": "integer", "nullable": True}},
            "note": {"type": "string"},
        },
    }
    spec, entity = map_source(value)
    compiled = compile_rest_entity(spec, entity)
    install(
        monkeypatch,
        lambda request: httpx.Response(
            200, json={"a": {"dates": ["2026-02-03", None], "totals": {"yes": 9, "unknown": None}}}
        ),
    )
    assert emitted(compiled, {"scope": "example"}) == [
        {
            "scope": "example",
            "values": [
                (
                    "a",
                    {
                        "dates": [date(2026, 2, 3), None],
                        "totals": [("unknown", None), ("yes", 9)],
                        "note": None,
                    },
                )
            ],
        }
    ]
    value_schema = compiled["columns"][1]["schema"]
    with pytest.raises(GeneratedContractError, match="missing required"):
        _decode({"a": {"dates": []}}, value_schema, "fixture")
    with pytest.raises(GeneratedContractError, match="string keys"):
        _decode({1: {}}, value_schema, "fixture")


@pytest.mark.parametrize("value", [True, "7", 1.5, None, 2**63, -(2**63) - 1])
def test_map_values_do_not_coerce_invalid_integers(monkeypatch, value):
    spec, entity = map_source()
    compiled = compile_rest_entity(spec, entity)
    install(monkeypatch, lambda request: httpx.Response(200, json={"count": value}))
    with pytest.raises(GeneratedContractError, match="invalid BIGINT|NULL is not allowed"):
        emitted(compiled, {"scope": "example"})


def test_nullable_map_field_distinguishes_null_empty_and_null_member(monkeypatch):
    spec, entity = rest_source(
        {
            "type": "object",
            "required": ["counts"],
            "properties": {
                "counts": {
                    "type": "object",
                    "nullable": True,
                    "additionalProperties": {"type": "integer", "nullable": True},
                }
            },
        }
    )
    entity["columns"].append({"name": "counts", "path": ["counts"]})
    compiled = compile_rest_entity(spec, entity)
    for payload, expected in [(None, None), ({}, []), ({"a": None}, [("a", None)])]:
        install(monkeypatch, lambda request, payload=payload: httpx.Response(200, json={"counts": payload}))
        assert emitted(compiled, {"scope": "example"})[0]["counts"] == expected


def test_object_entries_are_sorted_key_grain_rows_and_empty_dictionary_is_zero_rows(monkeypatch):
    spec, entity = map_source(entries=True)
    compiled = compile_rest_entity(spec, entity)
    assert compiled["columns"][1]["source_entry"] == "key"
    assert "path" not in compiled["columns"][1]
    assert compiled["columns"][2]["path"] == []
    assert compiled["source"]["response_schema"]["root"]["additionalProperties"] == {"type": "integer"}

    def handler(request):
        assert "per_page" not in request.url.params
        return httpx.Response(200, json={"z": 9, "a": 2, "": 0})

    install(monkeypatch, handler)
    assert emitted(compiled, {"scope": "example"}) == [
        {"scope": "example", "key": "", "value": 0},
        {"scope": "example", "key": "a", "value": 2},
        {"scope": "example", "key": "z", "value": 9},
    ]
    install(monkeypatch, lambda request: httpx.Response(200, json={}))
    assert emitted(compiled, {"scope": "example"}) == []


def test_object_entries_value_paths_and_explicit_struct_selection(monkeypatch):
    spec, entity = map_source(
        {
            "type": "object",
            "required": ["stats"],
            "properties": {
                "stats": {
                    "type": "object",
                    "required": ["count"],
                    "properties": {"count": {"type": "integer"}, "details": {"type": "object"}},
                }
            },
        },
        entries=True,
    )
    entity["columns"][2].update(path=["stats"], selection={"count": True})
    entity["columns"].append({"name": "count", "source_entry": "value", "path": ["stats", "count"]})
    compiled = compile_rest_entity(spec, entity)
    assert compiled["columns"][2]["path"] == ["stats"]
    install(
        monkeypatch,
        lambda request: httpx.Response(
            200, json={"a": {"stats": {"count": 11, "details": {"anything": "omitted"}}}}
        ),
    )
    assert emitted(compiled, {"scope": "example"}) == [
        {"scope": "example", "key": "a", "value": {"count": 11}, "count": 11}
    ]


@pytest.mark.parametrize("payload", [[], None, "wrong"])
def test_object_entries_reject_non_dictionary_population(monkeypatch, payload):
    spec, entity = map_source(entries=True)
    compiled = compile_rest_entity(spec, entity)
    install(
        monkeypatch,
        lambda request: httpx.Response(
            200, content=json.dumps(payload), headers={"Content-Type": "application/json"}
        ),
    )
    with pytest.raises(GeneratedContractError, match="dictionary"):
        emitted(compiled, {"scope": "example"})


def test_object_entries_reject_unmodeled_pagination(monkeypatch):
    spec, entity = map_source(entries=True)
    compiled = compile_rest_entity(spec, entity)
    install(
        monkeypatch,
        lambda request: httpx.Response(
            200, json={"a": 1}, headers={"Link": '<https://api.github.com/dictionary?page=2>; rel="next"'}
        ),
    )
    with pytest.raises(GeneratedContractError, match="cannot paginate"):
        emitted(compiled, {"scope": "example"})


@pytest.mark.parametrize("value", [True, False, {}, {"description": "unspecified"}])
@pytest.mark.parametrize("entries", [True, False])
def test_untyped_dictionaries_are_not_coerced_to_json(value, entries):
    spec, entity = map_source(value, entries=entries)
    with pytest.raises(SchemaError, match="typed additionalProperties|unsupported selected type"):
        compile_rest_entity(spec, entity)


def test_mixed_dictionary_is_rejected_but_explicit_fixed_struct_projection_remains_supported():
    spec, entity = map_source(entries=True)
    schema = spec["paths"]["/dictionary"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]
    schema["properties"] = {"known": {"type": "integer"}}
    with pytest.raises(SchemaError, match="mixed fixed"):
        compile_rest_entity(spec, entity)
    entity["transport"]["result_shape"] = "object"
    entity["grain"] = ["scope"]
    entity["columns"] = [entity["columns"][0], {"name": "values", "path": []}]
    with pytest.raises(SchemaError, match="mixed fixed"):
        compile_rest_entity(spec, entity)
    entity["columns"][1]["selection"] = {"known": True}
    assert compile_rest_entity(spec, entity)["columns"][1]["type"] == 'STRUCT("known" BIGINT)'


def test_object_entries_requires_key_grain_and_disallows_key_paths_and_nullable_population():
    spec, entity = map_source(entries=True)
    bad = deepcopy(entity)
    bad["grain"] = ["scope"]
    with pytest.raises(SchemaError, match="grain must include"):
        compile_rest_entity(spec, bad)
    bad = deepcopy(entity)
    bad["columns"][1]["path"] = []
    with pytest.raises(SchemaError, match="keys cannot select"):
        compile_rest_entity(spec, bad)
    spec, entity = map_source(entries=True, nullable=True)
    with pytest.raises(SchemaError, match="non-null dictionary"):
        compile_rest_entity(spec, entity)


def test_recursive_map_value_requires_finite_explicit_projection():
    spec, entity = map_source({"$ref": "#/components/schemas/Value"})
    spec["components"] = {
        "schemas": {
            "Value": {
                "type": "object",
                "required": ["id"],
                "properties": {"id": {"type": "integer"}, "next": {"$ref": "#/components/schemas/Value"}},
            }
        }
    }
    with pytest.raises(SchemaError, match="recursive reference"):
        compile_rest_entity(spec, entity)
    entity["columns"][1]["selection"] = {"id": True}
    assert compile_rest_entity(spec, entity)["columns"][1]["type"] == 'MAP(VARCHAR, STRUCT("id" BIGINT))'


def child_source():
    spec, entity = rest_source(
        {
            "type": "array",
            "items": {"type": "object", "required": ["id"], "properties": {"id": {"type": "integer"}}},
        },
        shape="array",
        path="/children/{parent}",
        parameters=[{"name": "parent", "in": "path", "required": True, "schema": {"type": "integer"}}],
    )
    entity.update(
        name="children",
        arguments=[{"name": "parent", "type": "BIGINT"}],
        grain=["id"],
        columns=[{"name": "id", "path": ["id"]}],
    )
    entity["transport"]["path_bindings"] = {"parent": {"argument": "parent"}}
    return compile_rest_entity(spec, entity)


def parent_traversal(parent, names, *, source_paths=None):
    child = child_source()
    definition = {
        "name": "joined",
        "arguments": [],
        "grain": ["child_id"],
        "semantics": {},
        "columns": [{"name": "child_id", "source_stage": "child", "source_column": "id"}]
        + [{"name": name, "source_stage": "parent", "source_column": name} for name in names],
        "traversal": {
            "stages": [
                {"name": "parent", "entity": parent["name"], "arguments": {}},
                {
                    "name": "child",
                    "entity": child["name"],
                    "arguments": {"parent": {"stage": "parent", "column": "id"}},
                },
            ],
            "output_stage": "child",
        },
    }
    if source_paths:
        definition["columns"] = [definition["columns"][0], *source_paths]
    return compile_functions({"entities": [parent, child]}, {"functions": [definition]})


def test_map_ancestor_dates_survive_serialized_producer_continuations(monkeypatch):
    spec, entity = rest_source(
        {
            "type": "object",
            "required": ["id", "dates"],
            "properties": {
                "id": {"type": "integer"},
                "dates": {"type": "object", "additionalProperties": {"type": "string", "format": "date"}},
            },
        }
    )
    entity.update(
        arguments=[],
        grain=["id"],
        columns=[{"name": "id", "path": ["id"]}, {"name": "dates", "path": ["dates"]}],
    )
    contract = parent_traversal(compile_rest_entity(spec, entity), ["id", "dates"])

    def handler(request):
        if request.url.path == "/dictionary":
            return httpx.Response(200, json={"id": 5, "dates": {"reviewed": "2026-04-03"}})
        assert request.url.path == "/children/5"
        if request.url.params.get("page") == "2":
            return httpx.Response(200, json=[{"id": 12}])
        return httpx.Response(
            200, json=[{"id": 11}], headers={"Link": '<https://api.github.com/children/5?page=2>; rel="next"'}
        )

    install(monkeypatch, handler)
    assert emitted(contract["functions"][0], contract=contract) == [
        {"child_id": 11, "id": 5, "dates": [("reviewed", date(2026, 4, 3))]},
        {"child_id": 12, "id": 5, "dates": [("reviewed", date(2026, 4, 3))]},
    ]


BIGINT_SDL = "scalar BigInt\ntype Query { record: Record! }\ntype Record { fullDatabaseId: BigInt! }"


def bigint_source():
    return compile_graphql_entity(
        BIGINT_SDL,
        {
            "name": "big_record",
            "arguments": [],
            "grain": ["id"],
            "columns": [{"name": "id", "path": ["fullDatabaseId"]}],
            "transport": {
                "kind": "graphql",
                "field_path": ["record"],
                "field_arguments": {},
                "result_path": [],
                "pagination": {"kind": "none"},
            },
        },
    )


@pytest.mark.parametrize(
    "wire,expected",
    [
        ("4294967297", 4294967297),
        ("9223372036854775807", 2**63 - 1),
        ("-9223372036854775808", -(2**63)),
        ("+0007", 7),
    ],
)
def test_graphql_bigint_is_strict_string_wire_and_native_int64(monkeypatch, wire, expected):
    compiled = bigint_source()
    assert compiled["columns"][0]["schema"] == {
        "kind": "scalar",
        "type": "BIGINT",
        "nullable": False,
        "encoding": "decimal_string",
    }
    install(
        monkeypatch, lambda request: httpx.Response(200, json={"data": {"record": {"fullDatabaseId": wire}}})
    )
    assert emitted(compiled) == [{"id": expected}]


@pytest.mark.parametrize(
    "wire",
    [
        1,
        True,
        1.0,
        "1.0",
        "1e3",
        " 7",
        "7 ",
        "",
        "--7",
        "７",
        "9223372036854775808",
        "-9223372036854775809",
        "9" * 5000,
    ],
)
def test_graphql_bigint_rejects_invalid_wire_and_int64_overflow(monkeypatch, wire):
    install(
        monkeypatch, lambda request: httpx.Response(200, json={"data": {"record": {"fullDatabaseId": wire}}})
    )
    with pytest.raises(GeneratedContractError, match="BIGINT"):
        emitted(bigint_source())


def test_decoded_bigint_survives_parent_binding_and_continuation(monkeypatch):
    contract = parent_traversal(bigint_source(), ["id"])

    def handler(request):
        if request.url.path == "/graphql":
            return httpx.Response(200, json={"data": {"record": {"fullDatabaseId": "4294967297"}}})
        assert request.url.path == "/children/4294967297"
        if request.url.params.get("page") == "2":
            return httpx.Response(200, json=[{"id": 2}])
        return httpx.Response(
            200,
            json=[{"id": 1}],
            headers={"Link": '<https://api.github.com/children/4294967297?page=2>; rel="next"'},
        )

    install(monkeypatch, handler)
    assert emitted(contract["functions"][0], contract=contract) == [
        {"child_id": 1, "id": 4294967297},
        {"child_id": 2, "id": 4294967297},
    ]


def path_source(*, opt_in=True, parameter_type=None):
    spec, entity = rest_source(
        {
            "type": "array",
            "items": {"type": "object", "required": ["id"], "properties": {"id": {"type": "integer"}}},
        },
        shape="array",
        path="/refs/{prefix}",
        parameters=[
            {"name": "prefix", "in": "path", "required": True, "schema": parameter_type or {"type": "string"}}
        ],
    )
    entity.update(
        arguments=[{"name": "prefix", "type": "VARCHAR"}],
        grain=["id"],
        columns=[{"name": "id", "path": ["id"]}],
    )
    entity["transport"]["path_bindings"] = {"prefix": {"argument": "prefix"}}
    if opt_in:
        entity["transport"]["allow_empty_path_parameters"] = ["prefix"]
    return spec, entity


def test_empty_path_opt_in_keeps_escaping_and_dot_segment_validation(monkeypatch):
    spec, entity = path_source()
    compiled = compile_rest_entity(spec, entity)
    requests = install(monkeypatch, lambda request: httpx.Response(200, json=[]))
    assert emitted(compiled, {"prefix": ""}) == []
    assert requests[-1].url.path == "/refs/"
    emitted(compiled, {"prefix": "heads/a?x#y%"})
    assert requests[-1].url.raw_path.split(b"?", 1)[0] == b"/refs/heads%2Fa%3Fx%23y%25"
    for value in (".", "..", "heads/../main", "heads\\..\\main"):
        with pytest.raises(ValueError, match="dot segments"):
            emitted(compiled, {"prefix": value})
    spec, entity = path_source(opt_in=False)
    with pytest.raises(ValueError, match="not a valid GitHub name"):
        emitted(compile_rest_entity(spec, entity), {"prefix": ""})


@pytest.mark.parametrize(
    "schema",
    [
        {"type": "string", "minLength": 1},
        {"type": "string", "enum": ["main"]},
        {"type": "string", "pattern": ".+"},
    ],
)
def test_empty_path_opt_in_cannot_override_pinned_constraints(schema):
    spec, entity = path_source(parameter_type=schema)
    with pytest.raises(SchemaError, match="empty VARCHAR"):
        compile_rest_entity(spec, entity)


def test_public_variant_projection_reads_typed_parent_and_preserves_null_alternative(monkeypatch):
    def branch(name, kind):
        return {
            "type": "object",
            "required": ["id", name],
            "properties": {"id": {"type": "integer"}, name: {"type": kind}},
        }

    spec, entity = rest_source({"oneOf": [branch("text", "string"), branch("count", "integer")]})
    entity.update(
        arguments=[],
        grain=["id"],
        columns=[
            {"name": "id", "path": ["id"], "variant_paths": True},
            {"name": "payload", "path": [], "representation": "tagged"},
        ],
    )
    contract = parent_traversal(
        compile_rest_entity(spec, entity),
        [],
        source_paths=[
            {
                "name": "text_detail",
                "source_stage": "parent",
                "source_column": "payload",
                "source_path": ["variant_1"],
            },
            {
                "name": "count_detail",
                "source_stage": "parent",
                "source_column": "payload",
                "source_path": ["variant_2"],
            },
            {
                "name": "types",
                "source_stage": "parent",
                "source_column": "payload",
                "source_path": ["matched_types"],
            },
        ],
    )

    def handler(request):
        if request.url.path == "/dictionary":
            return httpx.Response(200, json={"id": 5, "text": "hello"})
        return httpx.Response(200, json=[{"id": 9}])

    install(monkeypatch, handler)
    assert emitted(contract["functions"][0], contract=contract) == [
        {
            "child_id": 9,
            "text_detail": {"id": 5, "text": "hello"},
            "count_detail": None,
            "types": ["variant_1"],
        }
    ]


def test_graphql_bigint_input_is_encoded_from_public_native_integer(monkeypatch):
    definition = {
        "name": "lookup",
        "arguments": [{"name": "id", "type": "BIGINT"}],
        "grain": ["id"],
        "columns": [{"name": "id", "path": ["fullDatabaseId"]}],
        "transport": {
            "kind": "graphql",
            "field_path": ["record"],
            "field_arguments": {"record": {"id": {"argument": "id"}}},
            "result_path": [],
            "pagination": {"kind": "none"},
        },
    }
    compiled = compile_graphql_entity(
        BIGINT_SDL.replace("record: Record!", "record(id: BigInt!): Record!"), definition
    )

    def handler(request):
        variables = json.loads(request.content)["variables"]
        assert list(variables.values()) == ["4294967297"]
        return httpx.Response(200, json={"data": {"record": {"fullDatabaseId": "4294967297"}}})

    install(monkeypatch, handler)
    assert emitted(compiled, {"id": 4294967297}) == [{"id": 4294967297}]
