"""Reviewed event tags resolve overlapping upstream variants without guessing."""

from copy import deepcopy

import httpx
import pytest

from tests.helpers import install
from tests.test_generated_runtime import run
from vgi_github.generated_runtime import GeneratedContractError
from vgi_github.generation.schema import SchemaError, compile_rest_entity


def event_source(mode="anyOf"):
    def branch(properties, required):
        return {
            "type": "object",
            "properties": {"id": {"type": "integer"}, "event": {"type": "string"}, **properties},
            "required": ["id", "event", *required],
        }

    first = branch({"message": {"type": "string"}}, ["message"])
    second = branch({"count": {"type": "integer"}}, ["count"])
    response = {"type": "array", "items": {mode: [first, second]}}
    spec = {
        "paths": {
            "/events": {
                "get": {
                    "operationId": "events/list",
                    "responses": {"200": {"content": {"application/json": {"schema": response}}}},
                }
            }
        }
    }
    entity = {
        "name": "events",
        "arguments": [],
        "grain": ["id"],
        "columns": [
            {"name": "id", "path": ["id"], "variant_paths": True},
            {
                "name": "payload",
                "path": [],
                "representation": "tagged",
                "discriminator": {
                    "path": ["event"],
                    "mapping": {"commented": "variant_1", "closed": "variant_2", "reopened": "variant_2"},
                    "comment": "Reviewed fixture: comments carry messages; state changes carry counts.",
                },
            },
        ],
        "transport": {"kind": "rest", "operation_id": "events/list"},
    }
    return spec, entity


def scan(entity):
    return [row for batch in run(entity, {}).batches for row in batch.to_pylist()]


@pytest.mark.parametrize("mode", ["oneOf", "anyOf"])
def test_reviewed_event_selects_one_branch_when_both_structural_shapes_match(monkeypatch, mode):
    spec, entity = event_source(mode)
    compiled = compile_rest_entity(spec, entity)
    install(
        monkeypatch,
        lambda request: httpx.Response(
            200,
            json=[
                {"id": 1, "event": "commented", "message": "First", "count": 7},
                {"id": 2, "event": "reopened", "message": "Overlapping property", "count": 9},
            ],
        ),
    )
    assert scan(compiled) == [
        {
            "id": 1,
            "payload": {
                "matched_types": ["variant_1"],
                "variant_1": {"id": 1, "event": "commented", "message": "First"},
                "variant_2": None,
            },
        },
        {
            "id": 2,
            "payload": {
                "matched_types": ["variant_2"],
                "variant_1": None,
                "variant_2": {"id": 2, "event": "reopened", "count": 9},
            },
        },
    ]


@pytest.mark.parametrize("event", [None, "future-event", 42, True, ["commented"]])
def test_unknown_null_and_nonstrings_never_fall_back_to_structural_matching(monkeypatch, event):
    spec, entity = event_source()
    compiled = compile_rest_entity(spec, entity)
    install(
        monkeypatch,
        lambda request: httpx.Response(
            200, json=[{"id": 1, "event": event, "message": "Present", "count": 7}]
        ),
    )
    with pytest.raises(GeneratedContractError, match="reviewed variant discriminator"):
        scan(compiled)


def test_missing_event_fails_even_if_optional_in_pinned_branch(monkeypatch):
    spec, entity = event_source()
    for branch in spec["paths"]["/events"]["get"]["responses"]["200"]["content"]["application/json"][
        "schema"
    ]["items"]["anyOf"]:
        branch["required"].remove("event")
    compiled = compile_rest_entity(spec, entity)
    install(
        monkeypatch, lambda request: httpx.Response(200, json=[{"id": 1, "message": "Present", "count": 7}])
    )
    with pytest.raises(GeneratedContractError, match="reviewed variant discriminator"):
        scan(compiled)


def test_selected_branch_failure_does_not_fall_back_to_valid_other_branch(monkeypatch):
    spec, entity = event_source()
    compiled = compile_rest_entity(spec, entity)
    install(
        monkeypatch, lambda request: httpx.Response(200, json=[{"id": 1, "event": "commented", "count": 7}])
    )
    with pytest.raises(GeneratedContractError, match="variant_1.message: missing required"):
        scan(compiled)
    install(
        monkeypatch, lambda request: httpx.Response(200, json=[{"id": 1, "event": "closed", "count": True}])
    )
    with pytest.raises(GeneratedContractError, match="variant_2.count: invalid BIGINT"):
        scan(compiled)


def test_whole_object_projection_keeps_all_variants_with_explicit_narrowed_fields(monkeypatch):
    spec, entity = event_source()
    entity["columns"][1]["selection"] = {"variant_1": {"message": True}, "variant_2": {"count": True}}
    compiled = compile_rest_entity(spec, entity)
    install(monkeypatch, lambda request: httpx.Response(200, json=[{"id": 1, "event": "closed", "count": 8}]))
    assert scan(compiled)[0]["payload"] == {
        "matched_types": ["variant_2"],
        "variant_1": None,
        "variant_2": {"count": 8},
    }
    assert compiled["columns"][1]["schema"]["variant"]["source_discriminator"]["path"] == ["event"]


@pytest.mark.parametrize(
    "mapping",
    [
        {},
        {"commented": "variant_1"},
        {"commented": "variant_1", "closed": "variant_3"},
        {"": "variant_1", "closed": "variant_2"},
    ],
)
def test_mapping_must_cover_every_pinned_variant_without_default_guessing(mapping):
    spec, entity = event_source()
    entity["columns"][1]["discriminator"]["mapping"] = mapping
    with pytest.raises(SchemaError, match="cover every numbered variant"):
        compile_rest_entity(spec, entity)


def test_mapping_requires_review_evidence_and_agrees_with_pinned_field_types_and_enums():
    spec, entity = event_source()
    invalid = deepcopy(entity)
    invalid["columns"][1]["discriminator"]["comment"] = ""
    with pytest.raises(SchemaError, match="evidence comment"):
        compile_rest_entity(spec, invalid)
    first = spec["paths"]["/events"]["get"]["responses"]["200"]["content"]["application/json"]["schema"][
        "items"
    ]["anyOf"][0]
    first["properties"]["event"] = {"type": "integer"}
    with pytest.raises(SchemaError, match="select a string"):
        compile_rest_entity(spec, entity)
    first["properties"]["event"] = {"type": "string", "enum": ["another-event"]}
    with pytest.raises(SchemaError, match="contradicts the pinned field enum"):
        compile_rest_entity(spec, entity)


def test_root_plain_struct_selection_is_explicit_and_typed(monkeypatch):
    spec, entity = event_source()
    schema = spec["paths"]["/events"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]
    schema["items"] = schema["items"]["anyOf"][0]
    entity["columns"] = [
        {"name": "id", "path": ["id"]},
        {"name": "payload", "path": [], "selection": {"event": True, "message": True}},
    ]
    compiled = compile_rest_entity(spec, entity)
    install(
        monkeypatch,
        lambda request: httpx.Response(200, json=[{"id": 1, "event": "commented", "message": "Text"}]),
    )
    assert scan(compiled) == [{"id": 1, "payload": {"event": "commented", "message": "Text"}}]
