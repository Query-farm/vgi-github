"""Physical source constraints apply after public or parent-stage bindings."""

from datetime import UTC, date, datetime

import httpx
import pyarrow as pa
import pytest
from vgi.argument_spec import extract_argument_specs

from tests.helpers import install
from tests.test_generated_runtime import run
from vgi_github.generated_runtime import GeneratedContractError, _page, make_function
from vgi_github.generation.graph import compile_functions
from vgi_github.generation.schema import compile_rest_entity


def physical_source(arguments, *, columns=None):
    spec = {
        "paths": {
            "/observations": {
                "get": {
                    "operationId": "fixture/list",
                    "parameters": [
                        {
                            "name": argument["name"],
                            "in": "query",
                            "required": False,
                            "schema": {
                                "type": {
                                    "VARCHAR": "string",
                                    "BIGINT": "integer",
                                    "BOOLEAN": "boolean",
                                    "DATE": "string",
                                    "TIMESTAMP WITH TIME ZONE": "string",
                                }[argument["type"]],
                                **(
                                    {"format": "date"}
                                    if argument["type"] == "DATE"
                                    else {"format": "date-time"}
                                    if argument["type"] == "TIMESTAMP WITH TIME ZONE"
                                    else {}
                                ),
                            },
                        }
                        for argument in arguments
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
    definition = {
        "name": "observations",
        "arguments": arguments,
        "grain": ["id"],
        "columns": [{"name": "id", "path": ["id"]}, *(columns or [])],
        "transport": {
            "kind": "rest",
            "operation_id": "fixture/list",
            "query_bindings": {argument["name"]: {"argument": argument["name"]} for argument in arguments},
        },
    }
    return compile_rest_entity(spec, definition)


@pytest.mark.parametrize(
    "kind,expected", [("DATE", pa.date32()), ("TIMESTAMP WITH TIME ZONE", pa.timestamp("us", tz="UTC"))]
)
def test_temporal_arguments_publish_concrete_sdk_signatures(kind, expected):
    source = physical_source([{"name": "value", "type": kind, "nullable": True, "default": None}])
    specifications = extract_argument_specs(make_function(source))
    assert len(specifications) == 1
    assert specifications[0].arrow_type == expected
    assert specifications[0].is_any_type is False


@pytest.mark.parametrize(
    "definition,value,error",
    [
        ({"name": "value", "type": "VARCHAR", "enum": ["heart", "+1"]}, "eyes", "declared enum"),
        ({"name": "value", "type": "BIGINT", "minimum": 1}, 0, "at least 1"),
        ({"name": "value", "type": "VARCHAR", "min_length": 1}, "  ", "empty resource"),
        ({"name": "value", "type": "BIGINT"}, True, "invalid BIGINT"),
        ({"name": "value", "type": "BIGINT"}, "3", "invalid BIGINT"),
        ({"name": "value", "type": "BIGINT"}, 3.0, "invalid BIGINT"),
        ({"name": "value", "type": "BIGINT"}, 2**63, "invalid BIGINT"),
        ({"name": "value", "type": "BIGINT"}, -(2**63) - 1, "invalid BIGINT"),
        ({"name": "value", "type": "BOOLEAN"}, 1, "invalid BOOLEAN"),
        ({"name": "value", "type": "BOOLEAN", "enum": [True]}, False, "declared enum"),
        ({"name": "value", "type": "VARCHAR"}, None, "NULL is not allowed"),
        ({"name": "value", "type": "DATE"}, "2026-99-03", "invalid DATE"),
        ({"name": "value", "type": "TIMESTAMP WITH TIME ZONE"}, "2026-03-04T12:00:00", "invalid TIMESTAMP"),
    ],
)
def test_physical_argument_validation_precedes_any_http(monkeypatch, definition, value, error):
    source = physical_source([definition])
    requests = install(monkeypatch, lambda request: pytest.fail("invalid arguments must not reach HTTP"))
    with pytest.raises(GeneratedContractError, match=error):
        _page(source, {"value": value}, None, {})
    assert requests == []


def test_only_declared_defaults_fill_missing_physical_arguments(monkeypatch):
    requests = install(monkeypatch, lambda request: httpx.Response(200, json=[]))
    source = physical_source([{"name": "value", "type": "VARCHAR", "nullable": True, "default": None}])
    arguments = {}
    assert _page(source, arguments, None, {}) == []
    assert arguments == {"value": None}
    assert "value" not in requests[0].url.params
    source = physical_source([{"name": "value", "type": "VARCHAR", "nullable": True}])
    with pytest.raises(GeneratedContractError, match="missing required"):
        _page(source, {}, None, {})
    with pytest.raises(GeneratedContractError, match="unknown physical source argument"):
        _page(source, {"value": None, "unexpected": "x"}, None, {})
    assert len(requests) == 1


@pytest.mark.parametrize(
    "parent_id,content,error",
    [(42, "eyes", "content.*declared enum"), (0, "heart", "parent.*at least 1")],
)
def test_child_endpoint_checks_bound_constraints_after_parent_lookup(monkeypatch, parent_id, content, error):
    parent = physical_source([])
    child = physical_source(
        [
            {"name": "parent", "type": "BIGINT", "minimum": 1},
            {"name": "content", "type": "VARCHAR", "enum": ["heart", "+1"]},
        ]
    )
    child["name"] = "child_reactions"
    child["transport"]["path"] = "/reactions"
    contract = compile_functions(
        {"entities": [parent, child]},
        {
            "functions": [
                {
                    "name": "reactions",
                    "arguments": [{"name": "content", "type": "VARCHAR", "enum": ["heart", "+1", "eyes"]}],
                    "grain": ["id"],
                    "semantics": {},
                    "columns": [{"name": "id", "source_stage": "child", "source_column": "id"}],
                    "traversal": {
                        "stages": [
                            {"name": "parent", "entity": "observations", "arguments": {}},
                            {
                                "name": "child",
                                "entity": "child_reactions",
                                "arguments": {
                                    "parent": {"stage": "parent", "column": "id"},
                                    "content": {"parameter": "content"},
                                },
                            },
                        ],
                        "output_stage": "child",
                    },
                }
            ]
        },
    )

    def handler(request):
        assert request.url.path == "/observations"
        return httpx.Response(200, json=[{"id": parent_id}])

    requests = install(monkeypatch, handler)
    with pytest.raises(GeneratedContractError, match="child_reactions." + error):
        run(contract["functions"][0], {"content": [content]}, contract=contract)
    assert len(requests) == 1


def test_temporal_source_arguments_restore_on_every_serialized_page(monkeypatch):
    source = physical_source(
        [
            {"name": "day", "type": "DATE"},
            {"name": "since", "type": "TIMESTAMP WITH TIME ZONE"},
        ],
        columns=[
            {"name": "day", "source_argument": "day"},
            {"name": "since", "source_argument": "since"},
        ],
    )
    instant = datetime(2026, 3, 4, 12, 30, tzinfo=UTC)

    def handler(request):
        if request.url.params.get("page") == "2":
            return httpx.Response(200, json=[{"id": 2}])
        assert request.url.params["day"] == "2026-03-04"
        assert request.url.params["since"] == "2026-03-04T12:30:00+00:00"
        return httpx.Response(
            200,
            json=[{"id": 1}],
            headers={"Link": '<https://api.github.com/observations?page=2>; rel="next"'},
        )

    install(monkeypatch, handler)
    result = run(source, {"day": [date(2026, 3, 4)], "since": [instant]})
    rows = [row for batch in result.batches for row in batch.to_pylist()]
    assert rows == [
        {"id": 1, "day": date(2026, 3, 4), "since": instant},
        {"id": 2, "day": date(2026, 3, 4), "since": instant},
    ]


@pytest.mark.parametrize(
    "value,error",
    [
        ("a", "at least 2"),
        ("abcd", "at most 3"),
        ("AB", "required pattern"),
    ],
)
def test_string_bounds_reject_before_http_without_trimming(monkeypatch, value, error):
    source = physical_source(
        [
            {
                "name": "value",
                "type": "VARCHAR",
                "min_length": 2,
                "max_length": 3,
                "pattern": "^[a-z]+$",
            }
        ]
    )
    requests = install(monkeypatch, lambda request: pytest.fail("invalid bounds must not reach HTTP"))
    with pytest.raises(GeneratedContractError, match=error):
        run(source, {"value": [value]})
    assert requests == []


@pytest.mark.parametrize("value", ["é🙂", " a", "ab"])
def test_string_length_counts_raw_unicode_characters(monkeypatch, value):
    source = physical_source(
        [
            {
                "name": "value",
                "type": "VARCHAR",
                "min_length": 2,
                "max_length": 2,
            }
        ]
    )
    requests = install(monkeypatch, lambda request: httpx.Response(200, json=[{"id": 1}]))
    assert sum(batch.num_rows for batch in run(source, {"value": [value]}).batches) == 1
    assert requests[0].url.params["value"] == value


def test_nullable_pattern_parameter_skips_constraints_and_omits_query(monkeypatch):
    source = physical_source(
        [
            {
                "name": "value",
                "type": "VARCHAR",
                "nullable": True,
                "min_length": 2,
                "max_length": 2,
                "pattern": "[0-9]+",
            }
        ]
    )
    requests = install(monkeypatch, lambda request: httpx.Response(200, json=[]))
    run(source, {"value": [None]})
    assert "value" not in requests[0].url.params


@pytest.mark.parametrize(
    "bounds",
    [
        {"max_length": -1},
        {"max_length": True},
        {"min_length": 2**63},
        {"max_length": 2**63},
        {"pattern": "x" * 4097},
        {"min_length": 3, "max_length": 2},
        {"pattern": "["},
        {"pattern": 12},
        {"min_length": 2, "example": "a"},
        {"max_length": 2, "example": "abc"},
        {"pattern": "[0-9]+", "example": "abc"},
    ],
)
def test_invalid_string_constraints_and_examples_fail_compilation(bounds):
    with pytest.raises(ValueError, match="length|pattern"):
        physical_source([{"name": "value", "type": "VARCHAR", **bounds}])
