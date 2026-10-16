"""Search envelope fields remain typed, page-specific, and separately measured."""

import httpx
import pytest

from tests.helpers import install
from tests.test_generated_runtime import run
from vgi_github.auth import Credentials
from vgi_github.generated_runtime import GeneratedContractError, _page
from vgi_github.generation.coverage_keys import audit_contract_keys, rest_contract_keys
from vgi_github.generation.schema import SchemaError, compile_rest_entity


def document_source():
    schema = {
        "type": "object",
        "required": ["items", "search_type"],
        "properties": {
            "items": {
                "type": "array",
                "items": {"type": "object", "required": ["id"], "properties": {"id": {"type": "integer"}}},
            },
            "search_type": {"type": "string", "enum": ["lexical", "semantic"]},
            "reason": {"type": "string", "nullable": True},
        },
    }
    definition = {
        "name": "hits",
        "arguments": [],
        "grain": ["id"],
        "columns": [
            {"name": "id", "path": ["id"]},
            {"name": "mode", "source_document_path": ["search_type"]},
            {"name": "reason", "source_document_path": ["reason"]},
        ],
        "transport": {"kind": "rest", "operation_id": "search/hits", "result_path": ["items"]},
    }
    spec = {
        "paths": {
            "/search": {
                "get": {
                    "operationId": "search/hits",
                    "description": (
                        "This endpoint does not accept authentication and only returns public records."
                    ),
                    "responses": {"200": {"content": {"application/json": {"schema": schema}}}},
                }
            }
        }
    }
    return spec, definition


def test_envelope_metadata_is_decoded_per_page_without_clobbering_item_fields(monkeypatch):
    def respond(request):
        if request.url.params.get("page") == "2":
            return httpx.Response(
                200, json={"items": [{"id": 2}], "search_type": "semantic", "reason": "second page"}
            )
        return httpx.Response(
            200,
            json={"items": [{"id": 1, "search_type": "not envelope"}], "search_type": "lexical"},
            headers={"Link": '<https://api.github.com/search?page=2>; rel="next"'},
        )

    install(monkeypatch, respond)
    result = run(compile_rest_entity(*document_source()), {})
    assert [row for batch in result.batches for row in batch.to_pylist()] == [
        {"id": 1, "mode": "lexical", "reason": None},
        {"id": 2, "mode": "semantic", "reason": "second page"},
    ]


@pytest.mark.parametrize(
    "metadata", [{}, {"search_type": None}, {"search_type": 4}, {"search_type": "unknown"}]
)
def test_invalid_required_envelope_metadata_rejects_hits(monkeypatch, metadata):
    install(monkeypatch, lambda request: httpx.Response(200, json={"items": [{"id": 1}], **metadata}))
    with pytest.raises(GeneratedContractError):
        run(compile_rest_entity(*document_source()), {})


def test_document_metadata_coverage_uses_root_properties():
    spec, definition = document_source()
    source = compile_rest_entity(spec, definition)
    contract = {
        "entities": [source],
        "functions": [
            {
                "name": "public_hits",
                "traversal": {"stages": [{"name": "rows", "entity": "hits"}], "output_stage": "rows"},
                "columns": [{"name": "mode", "source_stage": "rows", "source_column": "mode"}],
            }
        ],
    }
    audit = audit_contract_keys(
        contract, {"rest": {"contract_keys_by_product": {"api.github.com": rest_contract_keys(spec)}}}
    )
    measured = audit["rest"]["products"]["api.github.com"]["operations"]["search/hits"]
    assert measured["public_properties"] == [
        "#/paths/~1search/get/responses/200/content/application~1json/schema/properties/search_type"
    ]


@pytest.mark.parametrize("failure", ["missing", "empty", "duplicate", "singleton"])
def test_document_fields_require_declared_unambiguous_array_paths(failure):
    spec, definition = document_source()
    if failure == "missing":
        definition["columns"][1]["source_document_path"] = ["missing"]
    elif failure == "empty":
        definition["columns"][1]["source_document_path"] = []
    elif failure == "duplicate":
        definition["columns"][1]["path"] = ["id"]
    else:
        definition["transport"].update(result_shape="object", result_path=[])
    with pytest.raises(SchemaError):
        compile_rest_entity(spec, definition)


def test_explicit_anonymous_transport_omits_credentials_on_every_page(monkeypatch):
    seen = install(
        monkeypatch, lambda request: httpx.Response(200, json={"items": [], "search_type": "lexical"})
    )
    spec, definition = document_source()
    definition["transport"]["authentication"] = "anonymous"
    source = compile_rest_entity(spec, definition)
    _page(source, {}, Credentials("fixture-token"), {})
    _page(
        source,
        {},
        Credentials("fixture-token"),
        {"page": 1, "next_url": "https://api.github.com/search?page=2"},
    )
    assert all("authorization" not in request.headers for request in seen)
    definition["transport"].pop("authentication")
    _page(compile_rest_entity(spec, definition), {}, Credentials("fixture-token"), {})
    assert seen[-1].headers["authorization"] == "Bearer fixture-token"


@pytest.mark.parametrize("failure", ["undocumented", "unknown_mode"])
def test_anonymous_transport_requires_exact_reviewed_opt_in(failure):
    spec, definition = document_source()
    definition["transport"]["authentication"] = "anonymous" if failure == "undocumented" else "automatic"
    if failure == "undocumented":
        spec["paths"]["/search"]["get"]["description"] = "Authentication is supported."
    with pytest.raises(SchemaError, match="anonymous authentication requires"):
        compile_rest_entity(spec, definition)


def test_empty_hit_population_still_validates_selected_response_metadata(monkeypatch):
    install(monkeypatch, lambda request: httpx.Response(200, json={"items": []}))
    with pytest.raises(GeneratedContractError, match="mode"):
        run(compile_rest_entity(*document_source()), {})
