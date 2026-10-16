"""Reviewed content negotiation selects a pinned typed response alternative."""

from copy import deepcopy
from datetime import UTC, datetime

import httpx
import pytest

from tests.helpers import install
from tests.test_generated_runtime import run
from vgi_github.generated_runtime import GeneratedContractError, _selected
from vgi_github.generation.schema import SchemaError, compile_rest_entity


def media_source(*, separate=False):
    plain = {
        "type": "array",
        "items": {"type": "object", "required": ["id"], "properties": {"id": {"type": "integer"}}},
    }
    starred = {
        "type": "array",
        "items": {
            "type": "object",
            "required": ["starred_at", "user"],
            "properties": {
                "starred_at": {"type": "string", "format": "date-time"},
                "user": {"type": "object", "required": ["id"], "properties": {"id": {"type": "integer"}}},
            },
        },
    }
    media = "application/vnd.fixture.star+json"
    content = {"application/json": {"schema": {"anyOf": [plain, starred]}}}
    if separate:
        content = {"application/json": {"schema": plain}, media: {"schema": starred}}
    spec = {
        "paths": {
            "/stars": {
                "get": {
                    "operationId": "fixture/stars",
                    "description": f"The {media} representation includes a creation timestamp.",
                    "responses": {"200": {"content": content}},
                }
            }
        }
    }
    definition = {
        "name": "stars",
        "arguments": [],
        "grain": ["id"],
        "columns": [{"name": "id", "path": ["user", "id"]}, {"name": "starred_at", "path": ["starred_at"]}],
        "transport": {"kind": "rest", "operation_id": "fixture/stars"},
    }
    if separate:
        definition["transport"]["response_media_type"] = media
    else:
        definition["transport"].update(
            accept=media,
            response_variant={
                "kind": "anyOf",
                "index": 1,
                "comment": "Pinned documentation maps star media to the timestamped user alternative.",
            },
        )
    return spec, definition


@pytest.mark.parametrize("separate", [False, True])
def test_pinned_media_controls_wire_accept_and_preserves_provenance(monkeypatch, separate):
    spec, definition = media_source(separate=separate)
    compiled = compile_rest_entity(spec, definition)

    def handler(request):
        assert request.headers["accept"] == "application/vnd.fixture.star+json"
        return httpx.Response(200, json=[{"starred_at": "2026-04-03T02:01:00Z", "user": {"id": 17}}])

    install(monkeypatch, handler)
    assert [row for batch in run(compiled, {}).batches for row in batch.to_pylist()] == [
        {"id": 17, "starred_at": datetime(2026, 4, 3, 2, 1, tzinfo=UTC)}
    ]
    projection = compiled["source"]["response_projection"]
    assert projection["media_type"] == (
        "application/vnd.fixture.star+json" if separate else "application/json"
    )
    if not separate:
        assert projection["variant"]["index"] == 1
        assert len(compiled["source"]["response_schema"]["root"]["anyOf"]) == 2


def test_wrong_wire_representation_is_not_coerced_to_selected_shape(monkeypatch):
    spec, definition = media_source()
    compiled = compile_rest_entity(spec, definition)
    install(monkeypatch, lambda request: httpx.Response(200, json=[{"id": 17}]))
    with pytest.raises(GeneratedContractError, match="missing required"):
        run(compiled, {})


@pytest.mark.parametrize(
    "change,error",
    [
        ({"response_media_type": "application/vnd.missing+json"}, "pinned"),
        ({"response_media_type": "text/plain"}, "JSON representation"),
        ({"accept": "application/vnd.unknown+json"}, "pinned"),
        ({"accept": "application/json\nUnsafe: injected"}, "pinned"),
        ({"response_variant": {"kind": "anyOf", "index": 2, "comment": "Out of bounds"}}, "reviewed pinned"),
        ({"response_variant": {"kind": "oneOf", "index": 0, "comment": "Wrong union"}}, "reviewed pinned"),
        (
            {"response_variant": {"kind": "anyOf", "index": True, "comment": "Not integer index"}},
            "reviewed pinned",
        ),
        ({"response_variant": {"kind": [], "index": 0, "comment": "Bad union"}}, "reviewed pinned"),
        ({"response_variant": {"kind": "anyOf", "index": 1, "comment": ""}}, "reviewed pinned"),
    ],
)
def test_media_selection_rejects_unsupported_or_unreviewed_contract(change, error):
    spec, definition = media_source()
    definition["transport"].update(change)
    with pytest.raises(SchemaError, match=error):
        compile_rest_entity(spec, definition)


def test_variant_requires_explicit_media_and_array_shape():
    spec, definition = media_source()
    invalid = deepcopy(definition)
    del invalid["transport"]["accept"]
    with pytest.raises(SchemaError, match="explicit media"):
        compile_rest_entity(spec, invalid)
    spec["paths"]["/stars"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]["anyOf"][
        1
    ] = {"type": "string"}
    with pytest.raises(SchemaError, match="top-level array"):
        compile_rest_entity(spec, definition)


def test_route_value_predicates_require_selected_population_and_all_values():
    public = {"selection": ["population"], "select_values": {"population": ["public"]}}
    starred = {"selection": ["population"], "select_values": {"population": ["starred"]}}
    assert _selected(public, {"population": "public"})
    assert not _selected(public, {"population": "starred"})
    assert _selected(starred, {"population": "starred"})
    assert not _selected(starred, {"population": None})
    assert _selected({"default": True, "selection": []}, {})
    assert not _selected(
        {"selection": ["first", "second"], "select_values": {"first": ["a"], "second": ["b"]}},
        {"first": "a", "second": "c"},
    )


def test_pinned_vendor_media_name_can_use_its_documented_json_accept(monkeypatch):
    spec, definition = media_source(separate=True)
    operation = spec["paths"]["/stars"]["get"]
    content = operation["responses"]["200"]["content"]
    content["application/vnd.fixture.star"] = content.pop("application/vnd.fixture.star+json")
    definition["transport"].update(
        response_media_type="application/vnd.fixture.star", accept="application/vnd.fixture.star+json"
    )
    source = compile_rest_entity(spec, definition)
    seen = install(
        monkeypatch,
        lambda request: httpx.Response(
            200, json=[{"starred_at": "2026-04-03T02:01:00Z", "user": {"id": 17}}]
        ),
    )
    assert sum(batch.num_rows for batch in run(source, {}).batches) == 1
    assert seen[0].headers["accept"] == "application/vnd.fixture.star+json"
    operation["description"] = "No documented JSON representation."
    with pytest.raises(SchemaError, match="pinned"):
        compile_rest_entity(spec, definition)
    definition["transport"].pop("accept")
    with pytest.raises(SchemaError, match="JSON representation"):
        compile_rest_entity(spec, definition)
