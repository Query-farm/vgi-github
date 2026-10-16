"""String response identities can traverse integer API paths without lossy casts."""

from copy import deepcopy

import httpx
import pytest

from tests.helpers import install
from tests.test_generated_runtime import run
from vgi_github.generated_runtime import GeneratedContractError, _decimal_identity
from vgi_github.generation.graph import compile_functions
from vgi_github.generation.schema import SchemaError, compile_rest_entity


def identities():
    sources = []
    for name, kind in (("parents", "string"), ("children", "integer")):
        child = name == "children"
        spec = {
            "paths": {
                "/" + name + ("/{id}" if child else ""): {
                    "get": {
                        "operationId": name + "/get",
                        "parameters": (
                            [{"name": "id", "in": "path", "required": True, "schema": {"type": "integer"}}]
                            if child
                            else []
                        ),
                        "responses": {
                            "200": {
                                "content": {
                                    "application/json": {
                                        "schema": {
                                            "type": "array",
                                            "items": {
                                                "type": "object",
                                                "required": ["id"],
                                                "properties": {"id": {"type": kind}},
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
        sources.append(
            compile_rest_entity(
                spec,
                {
                    "name": name,
                    "arguments": [{"name": "id", "type": "BIGINT"}] if child else [],
                    "grain": ["id"],
                    "columns": [{"name": "id", "path": ["id"]}],
                    "transport": {
                        "kind": "rest",
                        "operation_id": name + "/get",
                        "path_bindings": {"id": {"argument": "id"}} if child else {},
                    },
                },
            )
        )
    overlay = {
        "functions": [
            {
                "name": "records",
                "arguments": [],
                "grain": ["id"],
                "semantics": {},
                "columns": [{"name": "id", "source_stage": "children", "source_column": "id"}],
                "traversal": {
                    "stages": [
                        {"name": "parents", "entity": "parents", "arguments": {}},
                        {
                            "name": "children",
                            "entity": "children",
                            "arguments": {
                                "id": {
                                    "stage": "parents",
                                    "column": "id",
                                    "transform": "decimal_string_to_bigint",
                                },
                            },
                        },
                    ],
                    "output_stage": "children",
                },
            }
        ]
    }
    return {"entities": sources}, overlay


def test_discovered_string_identity_retrieves_exact_integer_endpoint(monkeypatch):
    contract, overlay = identities()
    compiled = compile_functions(contract, overlay)
    requests = install(
        monkeypatch,
        lambda request: httpx.Response(
            200,
            json=[{"id": "17"}] if request.url.path == "/parents" else [{"id": 17}],
        ),
    )
    output = run(compiled["functions"][0], {}, contract=compiled)
    assert [row for batch in output.batches for row in batch.to_pylist()] == [{"id": 17}]
    assert [request.url.path for request in requests] == ["/parents", "/children/17"]


@pytest.mark.parametrize("value", ["", "017", "+17", "-1", " 17", "17 ", "1e2", "1.0", "１２", str(2**63)])
def test_invalid_discovered_identity_never_reaches_child_endpoint(monkeypatch, value):
    contract, overlay = identities()
    compiled = compile_functions(contract, overlay)
    requests = install(monkeypatch, lambda request: httpx.Response(200, json=[{"id": value}]))
    with pytest.raises(
        GeneratedContractError, match="empty row identity" if value == "" else "decimal identity"
    ):
        run(compiled["functions"][0], {}, contract=compiled)
    assert [request.url.path for request in requests] == ["/parents"]


def test_decimal_identity_boundaries_and_non_string_values():
    assert _decimal_identity("0") == 0
    assert _decimal_identity(str(2**63 - 1)) == 2**63 - 1
    assert _decimal_identity(None) is None
    for value in (17, True, 17.0, ["17"]):
        with pytest.raises(GeneratedContractError, match="decimal identity"):
            _decimal_identity(value)


@pytest.mark.parametrize("failure", ["unknown", "numeric_source", "nullable_source", "string_target"])
def test_identity_binding_requires_explicit_compatible_nonnull_types(failure):
    contract, overlay = identities()
    if failure == "unknown":
        overlay["functions"][0]["traversal"]["stages"][1]["arguments"]["id"]["transform"] = "cast"
    elif failure == "numeric_source":
        contract["entities"][0]["columns"][0]["type"] = "BIGINT"
    elif failure == "nullable_source":
        contract["entities"][0]["columns"][0]["nullable"] = True
        contract["entities"][0]["columns"][0]["schema"]["nullable"] = True
    else:
        contract["entities"][1]["arguments"][0]["type"] = "VARCHAR"
    with pytest.raises(SchemaError, match="stage transforms|exact types"):
        compile_functions(deepcopy(contract), deepcopy(overlay))


def text_identity_source():
    document = {
        "paths": {
            "/threads/{id}": {
                "get": {
                    "operationId": "threads/get",
                    "parameters": [
                        {"name": "id", "in": "path", "required": True, "schema": {"type": "integer"}}
                    ],
                    "responses": {
                        "200": {
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "required": ["id"],
                                        "properties": {"id": {"type": "string"}},
                                    }
                                }
                            }
                        }
                    },
                }
            }
        }
    }
    definition = {
        "name": "threads",
        "arguments": [{"name": "thread_id", "type": "VARCHAR"}],
        "grain": ["id"],
        "columns": [{"name": "id", "path": ["id"]}],
        "transport": {
            "kind": "rest",
            "operation_id": "threads/get",
            "result_shape": "object",
            "path_bindings": {"id": {"argument": "thread_id", "transform": "decimal_string_to_bigint"}},
        },
    }
    return document, definition


def test_public_text_identity_binds_integer_path_and_preserves_wire_identity(monkeypatch):
    source = compile_rest_entity(*text_identity_source())
    requests = install(monkeypatch, lambda request: httpx.Response(200, json={"id": "17"}))
    result = run(source, {"thread_id": ["17"]})
    assert [row for batch in result.batches for row in batch.to_pylist()] == [{"id": "17"}]
    assert [request.url.path for request in requests] == ["/threads/17"]


@pytest.mark.parametrize("value", ["017", "-1", "+17", " 17", "1e2", str(2**63)])
def test_invalid_public_text_identity_never_sends_http(monkeypatch, value):
    source = compile_rest_entity(*text_identity_source())
    requests = install(monkeypatch, lambda request: httpx.Response(200, json={"id": "17"}))
    with pytest.raises(GeneratedContractError, match="decimal identity"):
        run(source, {"thread_id": [value]})
    assert requests == []


def test_reviewed_root_path_identity_accepts_only_explicit_empty_string(monkeypatch):
    spec, definition = text_identity_source()
    definition["arguments"] = []
    definition["transport"]["path_bindings"] = {"id": {"literal": 1}}
    definition["columns"][0]["allow_empty_identity"] = True
    source = compile_rest_entity(spec, definition)
    install(monkeypatch, lambda request: httpx.Response(200, json={"id": ""}))
    assert [row for batch in run(source, {}).batches for row in batch.to_pylist()] == [{"id": ""}]
    for identity in (None, " "):
        install(monkeypatch, lambda request, identity=identity: httpx.Response(200, json={"id": identity}))
        with pytest.raises(GeneratedContractError):
            run(source, {})
    del definition["columns"][0]["allow_empty_identity"]
    install(monkeypatch, lambda request: httpx.Response(200, json={"id": ""}))
    with pytest.raises(GeneratedContractError, match="empty row identity"):
        run(compile_rest_entity(spec, definition), {})
    definition["columns"][0]["allow_empty_identity"] = True
    response = spec["paths"]["/threads/{id}"]["get"]["responses"]["200"]["content"]["application/json"][
        "schema"
    ]
    response["properties"]["id"]["minLength"] = 1
    with pytest.raises(SchemaError, match="contradicts"):
        compile_rest_entity(spec, definition)
