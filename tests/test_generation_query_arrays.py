"""Reviewed REST array filters preserve typed values and repeated query keys."""

import httpx
import pyarrow as pa
import pytest
from vgi.argument_spec import extract_argument_specs

from tests.helpers import install
from tests.test_generated_runtime import run
from vgi_github.generated_runtime import GeneratedContractError, _page, make_function
from vgi_github.generation.schema import SchemaError, compile_rest_entity


def query_array_source(kind="BIGINT", *, parameter=None, item_enum=None):
    item = {"type": "integer" if kind == "BIGINT" else "string"}
    if item_enum is not None:
        item["enum"] = item_enum
    argument = {"name": "ids", "type": kind + "[]", "nullable": True, "default": None}
    definition = {
        "name": "observations",
        "arguments": [argument],
        "grain": ["id"],
        "columns": [{"name": "id", "path": ["id"]}],
        "transport": {
            "kind": "rest",
            "operation_id": "fixture/list",
            "query_bindings": {"ids": {"argument": "ids"}},
        },
    }
    spec = {
        "paths": {
            "/observations": {
                "get": {
                    "operationId": "fixture/list",
                    "parameters": [
                        {
                            "name": "ids",
                            "in": "query",
                            "schema": {"type": "array", "items": item},
                            **(parameter or {}),
                        }
                    ],
                    "responses": {
                        "200": {
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "array",
                                        "items": {
                                            "type": "object",
                                            "required": ["id"],
                                            "properties": {"id": {"type": "integer"}},
                                        },
                                    }
                                }
                            }
                        }
                    },
                }
            }
        }
    }
    return compile_rest_entity(spec, definition)


def test_integer_array_filter_repeats_keys_and_preserves_pagination(monkeypatch):
    def respond(request):
        assert request.url.params.get_list("ids") == ["17", "23"]
        if request.url.params.get("page") == "2":
            return httpx.Response(200, json=[{"id": 23}])
        return httpx.Response(
            200,
            json=[{"id": 17}],
            headers={"Link": '<https://api.github.com/observations?ids=17&ids=23&page=2>; rel="next"'},
        )

    requests = install(monkeypatch, respond)
    source = query_array_source()
    output = run(source, {"ids": [[17, 23]]})
    assert [row for batch in output.batches for row in batch.to_pylist()] == [{"id": 17}, {"id": 23}]
    assert len(requests) == 2


def test_integer_array_publishes_exact_concrete_sdk_type():
    specifications = extract_argument_specs(make_function(query_array_source()))
    assert specifications[0].arrow_type == pa.list_(pa.field("item", pa.int64(), nullable=False))
    assert specifications[0].is_any_type is False


def test_string_array_filters_are_encoded_and_nullable_omission_is_explicit(monkeypatch):
    requests = install(monkeypatch, lambda request: httpx.Response(200, json=[]))
    source = query_array_source("VARCHAR")
    run(source, {"ids": [["a/b", "x&y"]]})
    assert requests[-1].url.params.get_list("ids") == ["a/b", "x&y"]
    assert b"ids=a%2Fb&ids=x%26y" in requests[-1].url.raw_path
    run(source, {})
    assert "ids" not in requests[-1].url.params


@pytest.mark.parametrize("value", [[], [None], [True], ["17"], [1.5], [2**63], "17,23", 17])
def test_invalid_or_empty_array_filter_fails_before_http(monkeypatch, value):
    requests = install(monkeypatch, lambda request: pytest.fail("invalid filter reached HTTP"))
    with pytest.raises(GeneratedContractError):
        _page(query_array_source(), {"ids": value}, None, {})
    assert requests == []


def test_query_item_enum_is_validated_before_http(monkeypatch):
    requests = install(monkeypatch, lambda request: pytest.fail("invalid enum reached HTTP"))
    with pytest.raises(GeneratedContractError, match="declared enum"):
        _page(query_array_source("VARCHAR", item_enum=["open", "closed"]), {"ids": ["unknown"]}, None, {})
    assert requests == []


@pytest.mark.parametrize(
    "parameter",
    [
        {"style": "pipeDelimited"},
        {"explode": False},
        {"allowReserved": True},
        {"in": "path"},
        {"schema": {"type": "array", "items": {"type": "integer"}, "minItems": 2}},
        {"schema": {"type": "array", "items": {"type": "object", "properties": {"id": {"type": "integer"}}}}},
    ],
)
def test_unreviewed_array_serializations_and_constraints_are_rejected(parameter):
    with pytest.raises(SchemaError, match="query arrays|unknown query parameter"):
        query_array_source(parameter=parameter)
