"""Reference data uses canonical keys, typed dictionaries and explicit observations."""

import json
from datetime import date

import httpx
import pytest

from tests.helpers import install
from tests.test_generated_runtime import run
from tests.test_generation_artifacts import ROOT
from tests.test_generation_artifacts import pilot as pilot
from vgi_github.generated_runtime import GeneratedContractError
from vgi_github.generation.schema import SchemaError, compile_graphql_entity, compile_rest_entity


@pytest.fixture
def reference(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "tests/crossfield"))
    import reference_fixture

    return reference_fixture


def rows_for(contract, name, **arguments):
    entity = next(value for value in contract["functions"] if value["name"] == name)
    output = run(entity, {key: [value] for key, value in arguments.items()}, contract=contract)
    return [row for batch in output.batches for row in batch.to_pylist()]


def test_reference_selects_all_fifteen_declared_operations():
    domain = json.loads((ROOT / "generation/domains/reference.json").read_text())
    assert {entity["transport"]["operation_id"] for entity in domain["entities"]} == {
        "codes-of-conduct/get-all-codes-of-conduct",
        "codes-of-conduct/get-conduct-code",
        "emojis/get",
        "gitignore/get-all-templates",
        "gitignore/get-template",
        "licenses/get-all-commonly-used",
        "licenses/get",
        "licenses/get-for-repo",
        "meta/root",
        "meta/get",
        "meta/get-all-versions",
        "meta/get-zen",
        "meta/get-octocat",
        "rate-limit/get",
        "repos/list-languages",
    }
    assert len(domain["entities"]) == 15
    assert len(domain["functions"]) == 12


@pytest.mark.parametrize(
    "name,key,selected,identity,count",
    [
        ("codes_of_conduct", "conduct_key", "contributor_covenant", "conduct_key", 2),
        ("gitignore_templates", "gitignore_name", "C++", "template_name", 2),
        ("licenses", "license_key", "mit", "license_key", 2),
    ],
)
def test_default_catalog_and_direct_lookup_are_one_hydrated_entity(
    pilot, reference, monkeypatch, name, key, selected, identity, count
):
    _, contract, _ = pilot
    requests = install(monkeypatch, reference.respond)
    catalog = rows_for(contract, name)
    assert len(catalog) == count
    exact = rows_for(contract, name, **{key: selected})
    assert exact == [next(row for row in catalog if row[identity] == selected)]
    assert any(request.url.params.get("page") == "2" for request in requests)
    if name == "licenses":
        assert exact[0]["permissions"] == ["commercial-use", "distribution"]
        assert exact[0]["body"] == "MIT\n"
    elif name == "gitignore_templates":
        assert exact[0]["source"] == "*.o\n*.so\n"
        assert any(b"C%2B%2B" in request.url.raw_path for request in requests)
    else:
        assert exact[0]["body"] == "Welcome contributors.\n"


def test_license_featured_filter_applies_only_to_catalog_route(pilot, reference, monkeypatch):
    _, contract, _ = pilot
    install(monkeypatch, reference.respond)
    assert [row["license_key"] for row in rows_for(contract, "licenses", license_featured=True)] == ["mit"]
    assert [row["license_key"] for row in rows_for(contract, "licenses", license_featured=False)] == [
        "apache-2.0"
    ]
    with pytest.raises(GeneratedContractError, match="do not apply"):
        rows_for(contract, "licenses", license_key="mit", license_featured=True)


def test_discovered_catalog_lookup_failure_never_silently_shrinks_population(pilot, reference, monkeypatch):
    _, contract, _ = pilot

    def handler(request):
        if request.url.path == "/gitignore/templates/C++":
            return httpx.Response(404, json={"message": "Disappeared"})
        return reference.respond(request)

    requests = install(monkeypatch, handler)
    with pytest.raises(Exception, match="404"):
        rows_for(contract, "gitignore_templates")
    assert any(request.url.path == "/gitignore/templates/Python" for request in requests)


def test_emojis_keep_alias_names_and_versions_keep_date_values(pilot, reference, monkeypatch):
    _, contract, _ = pilot
    install(monkeypatch, reference.respond)
    emojis = rows_for(contract, "emojis")
    assert [row["emoji_name"] for row in emojis] == ["+1", "thumbsup", "wave"]
    assert emojis[0]["image_url"] == emojis[1]["image_url"]
    assert rows_for(contract, "api_versions") == [
        {"api_version": date(2022, 11, 28)},
        {"api_version": date(2026, 3, 10)},
    ]


def test_repository_languages_use_qualified_keys_and_empty_dictionary(pilot, reference, monkeypatch):
    _, contract, _ = pilot
    requests = install(monkeypatch, reference.respond)
    organization = rows_for(contract, "repository_languages", organization="reference-fixture")
    assert organization == [
        {
            "repository_id": 4101,
            "repository": "reference-fixture/alpha",
            "language": "C++",
            "byte_count": 800,
        },
        {
            "repository_id": 4101,
            "repository": "reference-fixture/alpha",
            "language": "Python",
            "byte_count": 1200,
        },
    ]
    assert rows_for(contract, "repository_languages", owner="reference-fixture") == organization
    assert rows_for(contract, "repository_languages", repository="reference-fixture/beta") == []
    assert (
        rows_for(
            contract,
            "repository_languages",
            repositories=[
                {"repository": "reference-fixture/alpha"},
                {"repository": "reference-fixture/beta"},
            ],
        )
        == organization
    )
    before = len(requests)
    assert rows_for(contract, "repository_languages", repositories=[]) == []
    assert len(requests) == before


def test_license_files_keep_blob_identity_encoding_and_unknown_classification(pilot, reference, monkeypatch):
    _, contract, _ = pilot
    requests = install(monkeypatch, reference.respond)
    files = rows_for(contract, "repository_license_files", organization="reference-fixture")
    assert [
        (row["repository_id"], row["file_path"], row["byte_size"], row["license_key"]) for row in files
    ] == [(4101, "LICENSE", 4, "mit"), (4102, "LICENSE", 0, None)]
    assert (files[0]["encoding"], files[0]["encoded_content"]) == ("base64", "TUlUCg==")
    assert files[1]["detected_license"] is None
    old = rows_for(
        contract, "repository_license_files", repository="reference-fixture/alpha", license_ref="old"
    )[0]
    assert old["blob_sha"] != files[0]["blob_sha"]
    assert old["requested_ref"] == "old"
    assert any(request.url.params.get("ref") == "old" for request in requests)
    with pytest.raises(Exception, match="404"):
        rows_for(contract, "repository_license_files", repository="reference-fixture/missing")


def test_api_observations_keep_typed_metadata_requester_limits_and_exact_text(pilot, reference, monkeypatch):
    _, contract, _ = pilot
    install(monkeypatch, reference.respond)
    root = rows_for(contract, "api_root_observations")[0]
    assert root["repository_url"] == "https://api.github.com/repos/{owner}/{repo}"
    metadata = rows_for(contract, "api_metadata_observations")[0]
    assert metadata["hooks"] == ["192.0.2.0/24"]
    assert metadata["domains"]["actions_inbound"]["full_domains"] == ["fixture.actions.invalid"]
    assert metadata["domains"]["codespaces"] is None
    rate = rows_for(contract, "api_rate_limit_observations")[0]
    assert (rate["core_limit"], rate["core_remaining"], rate["core_used"], rate["core_reset"]) == (
        5000,
        4900,
        100,
        1800000000,
    )
    assert rate["resources"]["graphql"]["remaining"] == 4990
    assert rate["resources"]["dependency_sbom"] is None
    zen = rows_for(contract, "api_zen_observations")[0]
    assert (zen["body"], zen["text"], zen["byte_length"]) == (b"Keep it clear.\n", "Keep it clear.\n", 15)
    octocat = rows_for(contract, "api_octocat_observations", octocat_speech="Hi")[0]
    assert octocat["text"] == " /\\_/\\\n( Hi )\n"
    assert octocat["body"] == octocat["text"].encode()
    assert octocat["speech"] == "Hi"


def scalar_source(item=None):
    spec = {
        "paths": {
            "/values": {
                "get": {
                    "operationId": "fixture/values",
                    "responses": {
                        "200": {
                            "content": {
                                "application/json": {
                                    "schema": {"type": "array", "items": item or {"type": "integer"}}
                                }
                            }
                        }
                    },
                }
            }
        }
    }
    definition = {
        "name": "values",
        "arguments": [{"name": "scope", "type": "VARCHAR"}],
        "grain": ["scope", "value"],
        "columns": [{"name": "scope", "source_argument": "scope"}, {"name": "value", "source_value": True}],
        "transport": {"kind": "rest", "operation_id": "fixture/values"},
    }
    return spec, definition


def test_scalar_array_rows_remain_typed_values_across_link_pages(monkeypatch):
    spec, definition = scalar_source()
    compiled = compile_rest_entity(spec, definition)
    assert compiled["columns"][1]["source_value"] is True
    assert "path" not in compiled["columns"][1]

    def handler(request):
        if request.url.params.get("page") == "2":
            return httpx.Response(200, json=[2**40])
        return httpx.Response(
            200, json=[7], headers={"Link": '<https://api.github.com/values?page=2>; rel="next"'}
        )

    install(monkeypatch, handler)
    result = run(compiled, {"scope": ["sample"]})
    assert [row for batch in result.batches for row in batch.to_pylist()] == [
        {"scope": "sample", "value": 7},
        {"scope": "sample", "value": 2**40},
    ]


@pytest.mark.parametrize(
    "payload,error",
    [
        ([True], "invalid BIGINT"),
        (["7"], "invalid BIGINT"),
        ([None], "NULL is not allowed"),
        ([{"value": 7}], "invalid BIGINT"),
        ([7, 7], "duplicate row identity"),
    ],
)
def test_scalar_array_rejects_coercion_wrappers_and_duplicate_grain(monkeypatch, payload, error):
    spec, definition = scalar_source()
    install(monkeypatch, lambda request: httpx.Response(200, json=payload))
    with pytest.raises(GeneratedContractError, match=error):
        run(compile_rest_entity(spec, definition), {"scope": ["sample"]})


def test_scalar_selector_is_explicit_and_rejects_object_rows():
    spec, definition = scalar_source({"type": "object", "properties": {"id": {"type": "integer"}}})
    with pytest.raises(SchemaError, match="scalar array"):
        compile_rest_entity(spec, definition)
    spec, definition = scalar_source()
    definition["columns"][1]["source_value"] = False
    with pytest.raises(SchemaError, match="source_value requires true"):
        compile_rest_entity(spec, definition)
    definition["columns"][1]["source_value"] = True
    definition["columns"][1]["path"] = []
    with pytest.raises(SchemaError, match="exactly one"):
        compile_rest_entity(spec, definition)


def singleton_source(required=True):
    return compile_graphql_entity(
        "type Query { node: Record } type Record { id: ID! }",
        {
            "name": "required_node",
            "arguments": [],
            "grain": ["id"],
            "columns": [{"name": "id", "path": ["id"]}],
            "policy": {"require_one_row": True} if required else {},
            "transport": {
                "kind": "graphql",
                "field_path": ["node"],
                "field_arguments": {},
                "result_path": [],
                "pagination": {"kind": "none"},
            },
        },
    )


def test_required_discovered_node_never_becomes_empty_success(monkeypatch):
    install(monkeypatch, lambda request: httpx.Response(200, json={"data": {"node": None}}))
    with pytest.raises(GeneratedContractError, match="exactly one row"):
        run(singleton_source(), {})
    assert [
        row for batch in run(singleton_source(required=False), {}).batches for row in batch.to_pylist()
    ] == []
    install(monkeypatch, lambda request: httpx.Response(200, json={"data": {"node": {"id": "R1"}}}))
    assert [row for batch in run(singleton_source(), {}).batches for row in batch.to_pylist()] == [
        {"id": "R1"}
    ]
    install(
        monkeypatch,
        lambda request: httpx.Response(200, json={"data": {"node": [{"id": "R1"}, {"id": "R2"}]}}),
    )
    with pytest.raises(GeneratedContractError, match="entity object"):
        run(singleton_source(), {})


def test_required_singleton_policy_rejects_paginated_populations():
    spec, definition = scalar_source()
    definition["policy"] = {"require_one_row": True}
    with pytest.raises(SchemaError, match="unpaginated single-object"):
        compile_rest_entity(spec, definition)
