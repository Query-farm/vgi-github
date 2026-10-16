"""Defaulted scalar selections retain upstream semantics without partial collections."""

import httpx
import pytest
from graphql import build_schema, parse, validate

from scripts.generate_semantic_catalog import select_graphql
from tests.helpers import install
from tests.test_generated_runtime import run
from vgi_github.generation.schema import SchemaError, compile_graphql_entity


def definition(column):
    return {
        "name": "records",
        "arguments": [],
        "grain": ["id"],
        "columns": [{"name": "id", "path": ["id"]}, column],
        "transport": {
            "kind": "graphql",
            "field_path": ["record"],
            "field_arguments": {},
            "result_path": [],
            "pagination": {"kind": "none"},
        },
    }


@pytest.mark.parametrize("argument", ["Boolean", "Boolean = false", "Boolean! = false"])
@pytest.mark.parametrize("nested", [False, True])
def test_optional_scalar_arguments_use_pinned_defaults(monkeypatch, argument, nested):
    sdl = (
        "enum Reason { COMPLETED DUPLICATE } "
        f"type Record {{ id: ID! reason(enableDuplicate: {argument}): Reason nested: Record }} "
        "type Query { record: Record! }"
    )
    column = (
        {"name": "reason", "path": ["nested"], "selection": {"reason": True}}
        if nested
        else {"name": "reason", "path": ["reason"]}
    )
    entity = definition(column)
    selected = select_graphql(sdl, [entity])
    assert f"enableDuplicate: {argument}" in selected
    compiled = compile_graphql_entity(selected, entity)
    query = compiled["transport"]["document"]
    assert validate(build_schema(sdl), parse(query)) == []
    assert "enableDuplicate:" not in query
    record = (
        {"id": "I1", "nested": {"reason": "COMPLETED"}} if nested else {"id": "I1", "reason": "COMPLETED"}
    )
    install(monkeypatch, lambda request: httpx.Response(200, json={"data": {"record": record}}))
    rows = [row for batch in run(compiled, {}).batches for row in batch.to_pylist()]
    assert rows == [{"id": "I1", "reason": {"reason": "COMPLETED"} if nested else "COMPLETED"}]


@pytest.mark.parametrize(
    "field,column",
    [
        ("reason(enabled: Boolean!): String", {"name": "value", "path": ["reason"]}),
        ("names(first: Int): [String!]!", {"name": "value", "path": ["names"]}),
        (
            "children(first: Int): Record",
            {"name": "value", "path": ["children"], "selection": {"id": True}},
        ),
        ("children(first: Int): Record", {"name": "value", "path": ["children", "id"]}),
    ],
)
def test_required_arguments_and_argument_bearing_collections_stay_explicit(field, column):
    sdl = f"type Record {{ id: ID! {field} }} type Query {{ record: Record! }}"
    entity = definition(column)
    with pytest.raises(SchemaError, match="arguments require a separate entity"):
        compile_graphql_entity(sdl, entity)
    with pytest.raises(SchemaError, match="arguments require a separate entity"):
        select_graphql(sdl, [entity])
