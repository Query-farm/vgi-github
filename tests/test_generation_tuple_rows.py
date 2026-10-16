"""Reviewed statistics tuples preserve positions and reject partial or malformed rows."""

import httpx
import pytest

from tests.helpers import install
from tests.test_generated_runtime import run
from vgi_github.generated_runtime import GeneratedContractError
from vgi_github.generation.schema import SchemaError, compile_rest_entity


def tuple_source():
    row = {"type": "array", "items": {"type": "integer"}}
    spec = {
        "paths": {
            "/statistics": {
                "get": {
                    "operationId": "statistics/list",
                    "responses": {
                        "200": {"content": {"application/json": {"schema": {"type": "array", "items": row}}}}
                    },
                }
            }
        }
    }
    definition = {
        "name": "statistics",
        "arguments": [],
        "grain": ["week"],
        "columns": [
            {"name": name, "source_index": index} for index, name in enumerate(["week", "added", "deleted"])
        ],
        "transport": {"kind": "rest", "operation_id": "statistics/list", "item_length": 3},
    }
    return spec, definition


def test_statistics_tuple_preserves_signed_values_and_exact_positions(monkeypatch):
    source = compile_rest_entity(*tuple_source())
    install(monkeypatch, lambda request: httpx.Response(200, json=[[1700000000, 12, -4], [1700604800, 0, 0]]))
    result = run(source, {})
    assert [row for batch in result.batches for row in batch.to_pylist()] == [
        {"week": 1700000000, "added": 12, "deleted": -4},
        {"week": 1700604800, "added": 0, "deleted": 0},
    ]


@pytest.mark.parametrize(
    "row", [[1, 2], [1, 2, 3, 4], {"week": 1}, None, [1, True, -1], [1, "2", -1], [1, 2, None]]
)
def test_invalid_tuples_are_not_silently_truncated_or_coerced(monkeypatch, row):
    source = compile_rest_entity(*tuple_source())
    install(monkeypatch, lambda request: httpx.Response(200, json=[row]))
    with pytest.raises(GeneratedContractError):
        run(source, {})


@pytest.mark.parametrize(
    "failure", ["missing_length", "negative", "boolean", "outside", "zero_length", "nested", "pinned_min"]
)
def test_tuple_projection_requires_reviewed_length_and_scalar_item_schema(failure):
    spec, definition = tuple_source()
    row = spec["paths"]["/statistics"]["get"]["responses"]["200"]["content"]["application/json"]["schema"][
        "items"
    ]
    if failure == "missing_length":
        del definition["transport"]["item_length"]
    elif failure in {"negative", "boolean", "outside"}:
        definition["columns"][0]["source_index"] = {"negative": -1, "boolean": True, "outside": 3}[failure]
    elif failure == "zero_length":
        definition["transport"]["item_length"] = 0
    elif failure == "nested":
        row["items"] = {"type": "array", "items": {"type": "integer"}}
    else:
        row["minItems"] = 4
    with pytest.raises(SchemaError):
        compile_rest_entity(spec, definition)


def test_explicit_nonpaginated_statistics_keep_whole_array_and_reject_links(monkeypatch):
    spec, definition = tuple_source()
    definition["transport"]["pagination"] = {"kind": "none"}
    source = compile_rest_entity(spec, definition)
    rows = [[1700000000, 12, -4], [1700604800, 0, 0]]
    install(monkeypatch, lambda request: httpx.Response(200, json=rows))
    assert sum(batch.num_rows for batch in run(source, {}).batches) == 2
    install(
        monkeypatch,
        lambda request: httpx.Response(
            200, json=rows, headers={"Link": '<https://api.github.com/statistics?page=2>; rel="next"'}
        ),
    )
    with pytest.raises(GeneratedContractError, match="unexpected pagination"):
        run(source, {})


def test_nonpaginated_array_cannot_hide_a_declared_page_parameter():
    spec, definition = tuple_source()
    spec["paths"]["/statistics"]["get"]["parameters"] = [
        {"name": "page", "in": "query", "schema": {"type": "integer"}}
    ]
    definition["transport"]["pagination"] = {"kind": "none"}
    with pytest.raises(SchemaError, match="page controls require Link"):
        compile_rest_entity(spec, definition)
