"""A documented no-report response is distinct from malformed or pending data."""

from copy import deepcopy

import httpx
import pytest

from tests.helpers import install
from tests.test_generated_runtime import run
from vgi_github.generated_runtime import GeneratedContractError
from vgi_github.generation.schema import SchemaError, compile_rest_entity


def report_source():
    definition = {
        "name": "reports",
        "grain": ["day"],
        "arguments": [],
        "columns": [{"name": "day", "path": ["day"]}],
        "transport": {
            "kind": "rest",
            "operation_id": "reports/get",
            "result_shape": "object",
            "empty_response_statuses": ["204"],
        },
    }
    document = {
        "paths": {
            "/reports": {
                "get": {
                    "operationId": "reports/get",
                    "responses": {
                        "200": {
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "required": ["day"],
                                        "properties": {"day": {"type": "string"}},
                                    }
                                }
                            }
                        },
                        "204": {"description": "No report for the requested date."},
                    },
                }
            }
        }
    }
    return document, definition


def test_successful_report_and_explicit_no_report_preserve_population(monkeypatch):
    document, definition = report_source()
    source = compile_rest_entity(document, definition)
    for response, expected in (
        (httpx.Response(200, json={"day": "2026-09-01"}), 1),
        (httpx.Response(204), 0),
    ):
        requests = install(monkeypatch, lambda request, response=response: response)
        output = run(source, {})
        assert sum(batch.num_rows for batch in output.batches) == expected
        assert len(requests) == 1


@pytest.mark.parametrize(
    "response,error",
    [
        (httpx.Response(200, json=None), "expected an entity object"),
        (httpx.Response(202, json={"day": "2026-09-01"}), "unexpected response status"),
        (
            httpx.Response(204, headers={"Link": '<https://api.github.com/reports?page=2>; rel="next"'}),
            "pagination",
        ),
    ],
)
def test_empty_alternative_does_not_hide_invalid_or_pending_reports(monkeypatch, response, error):
    document, definition = report_source()
    install(monkeypatch, lambda request: response)
    with pytest.raises(GeneratedContractError, match=error):
        run(compile_rest_entity(document, definition), {})


@pytest.mark.parametrize("failure", ["missing", "body", "other_status", "require_one_row", "dictionary"])
def test_empty_alternative_requires_exact_pinned_bodyless_singleton_contract(failure):
    document, definition = report_source()
    responses = document["paths"]["/reports"]["get"]["responses"]
    if failure == "missing":
        del responses["204"]
    elif failure == "body":
        responses["204"] = deepcopy(responses["200"])
    elif failure == "other_status":
        definition["transport"]["empty_response_statuses"] = ["404"]
    elif failure == "require_one_row":
        definition["policy"] = {"require_one_row": True}
    else:
        definition["transport"]["result_shape"] = "object_entries"
    with pytest.raises(SchemaError, match="pinned bodyless 204 object or array"):
        compile_rest_entity(document, definition)


def test_undeclared_no_content_still_fails(monkeypatch):
    document, definition = report_source()
    definition["transport"].pop("empty_response_statuses")
    install(monkeypatch, lambda request: httpx.Response(204))
    with pytest.raises(GeneratedContractError, match="unexpected response status 204"):
        run(compile_rest_entity(document, definition), {})


def test_explicit_empty_array_alternative_does_not_create_a_row(monkeypatch):
    document, definition = report_source()
    definition["transport"]["result_shape"] = "array"
    media = document["paths"]["/reports"]["get"]["responses"]["200"]["content"]["application/json"]
    media["schema"] = {"type": "array", "items": media["schema"]}
    source = compile_rest_entity(document, definition)
    for response, expected in (
        (httpx.Response(204), []),
        (httpx.Response(200, json=[{"day": "2026-09-01"}]), [{"day": "2026-09-01"}]),
    ):
        install(monkeypatch, lambda request, response=response: response)
        result = run(source, {})
        assert [row for batch in result.batches for row in batch.to_pylist()] == expected
    install(monkeypatch, lambda request: httpx.Response(200, json={}))
    with pytest.raises(GeneratedContractError, match="expected an entity array"):
        run(source, {})


def test_singleton_link_requires_explicit_unselected_array_contract(monkeypatch):
    spec, definition = report_source()
    schema = spec["paths"]["/reports"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]
    schema["properties"]["statuses"] = {"type": "array", "items": {"type": "integer"}}
    install(
        monkeypatch,
        lambda request: httpx.Response(
            200,
            json={"day": "2026-09-01", "statuses": [1]},
            headers={"Link": '<https://api.github.com/reports?page=2>; rel="next"'},
        ),
    )
    with pytest.raises(GeneratedContractError, match="unexpected pagination"):
        run(compile_rest_entity(spec, definition), {})
    definition["transport"]["pagination"] = {"kind": "none", "unselected_collection_path": ["statuses"]}
    output = run(compile_rest_entity(spec, definition), {})
    assert [row for batch in output.batches for row in batch.to_pylist()] == [{"day": "2026-09-01"}]
    definition["columns"].append({"name": "statuses", "path": ["statuses"]})
    with pytest.raises(SchemaError, match="overlap"):
        compile_rest_entity(spec, definition)


def test_optional_array_bound_skips_only_absence_not_null_or_malformed_values(monkeypatch):
    spec, definition = report_source()
    schema = spec["paths"]["/reports"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]
    schema["properties"]["entries"] = {"type": "array", "items": {"type": "integer"}}
    definition["transport"]["response_assertions"] = [
        {"path": ["entries"], "comparison": "length_lt", "value": 3, "when_present": True}
    ]
    source = compile_rest_entity(spec, definition)
    for extra in ({}, {"entries": []}, {"entries": [1, 2]}):
        install(
            monkeypatch, lambda request, extra=extra: httpx.Response(200, json={"day": "2026-09-01", **extra})
        )
        assert sum(batch.num_rows for batch in run(source, {}).batches) == 1
    for value in (None, "", {}, [1, 2, 3]):
        install(
            monkeypatch,
            lambda request, value=value: httpx.Response(200, json={"day": "2026-09-01", "entries": value}),
        )
        with pytest.raises(GeneratedContractError, match="response assertion failed"):
            run(source, {})
    schema["required"].append("entries")
    with pytest.raises(SchemaError, match="optional array"):
        compile_rest_entity(spec, definition)
