"""Catalog regeneration and read-only upstream drift detection."""

from __future__ import annotations

import copy
import io
import json

import pytest

from scripts import generate_rest_catalog as gen

SHA = "a" * 40


def test_generator_ignores_writes_and_unifies_products(tmp_path):
    operation = {"operationId": "example/list", "summary": "List examples", "parameters": []}
    for product in gen.PRODUCTS:
        spec = {
            "paths": {
                "/examples": {"get": operation, "post": {"operationId": "example/create"}},
                "/write-only": {"put": {"operationId": "example/replace"}},
            }
        }
        (tmp_path / f"{product}.json").write_text(json.dumps(spec))
    manifest = gen.build(tmp_path, revision=SHA, api_version="2026-03-10")
    assert manifest["revision"] == SHA
    assert [o["operation_id"] for o in manifest["operations"]] == ["example/list"]
    assert manifest["operations"][0]["products"] == list(gen.PRODUCTS)
    assert manifest["operations"][0]["method"] == "GET"
    assert all(SHA in s["url"] and len(s["sha256"]) == 64 for s in manifest["sources"])


def test_diff_detects_additions_removals_and_parameter_changes():
    old = {
        "revision": SHA,
        "operations": [
            {"operation_id": "gone"},
            {"operation_id": "same"},
            {"operation_id": "changed", "parameters": []},
        ],
    }
    new = {
        "revision": "b" * 40,
        "operations": [
            {"operation_id": "new"},
            {"operation_id": "same"},
            {"operation_id": "changed", "parameters": [{"name": "q"}]},
        ],
    }
    assert gen.operation_diff(old, new) == {"added": ["new"], "removed": ["gone"], "changed": ["changed"]}
    metadata_only = {**old, "revision": "c" * 40, "sources": [{"sha256": "new-hash"}]}
    assert not any(gen.operation_diff(old, metadata_only).values())


def test_response_closure_drift_is_product_specific_and_keeps_parameter_variants(tmp_path):
    for index, product in enumerate(gen.PRODUCTS):
        spec = {
            "paths": {
                "/examples": {
                    "get": {
                        "operationId": "example/list",
                        "summary": "Examples",
                        "parameters": [
                            {
                                "name": "limit",
                                "in": "query",
                                "schema": {"type": "integer", "maximum": index + 10},
                            }
                        ],
                        "responses": {
                            "200": {
                                "content": {
                                    "application/json": {"schema": {"$ref": "#/components/schemas/Result"}}
                                }
                            }
                        },
                    }
                }
            },
            "components": {
                "schemas": {
                    "Result": {"type": "array", "items": {"$ref": "#/components/schemas/Item"}},
                    "Item": {"type": "object", "properties": {"id": {"type": "integer"}}},
                }
            },
        }
        (tmp_path / f"{product}.json").write_text(json.dumps(spec))
    before = gen.build(tmp_path, revision=SHA, api_version="2026-03-10")
    path = tmp_path / "ghec.json"
    changed = json.loads(path.read_text())
    changed["components"]["schemas"]["Item"]["properties"]["id"]["type"] = "string"
    path.write_text(json.dumps(changed))
    after = gen.build(tmp_path, revision=SHA, api_version="2026-03-10")
    assert gen.operation_diff(before, after)["changed"] == ["example/list"]
    old, new = before["operations"][0], after["operations"][0]
    assert old["response_schema_sha256"]["api.github.com"] == new["response_schema_sha256"]["api.github.com"]
    assert old["response_schema_sha256"]["ghec"] != new["response_schema_sha256"]["ghec"]
    assert new["parameters_by_product"]["api.github.com"][0]["schema"]["maximum"] == 10
    assert "ghec" not in new["parameters_by_product"]
    assert new["parameters"][0]["schema"]["maximum"] == 11


def test_response_hash_handles_recursive_refs_and_rejects_unresolved_refs():
    spec = {
        "components": {
            "schemas": {
                "Node": {"type": "object", "properties": {"child": {"$ref": "#/components/schemas/Node"}}}
            }
        }
    }
    value = {"$ref": "#/components/schemas/Node"}
    assert len(gen.closure_hash(spec, value)) == 64
    with pytest.raises(ValueError, match="unresolved reference"):
        gen.closure_hash(spec, {"$ref": "#/missing"})


def test_response_hash_does_not_treat_example_payload_as_schema_reference():
    spec = {
        "components": {
            "schemas": {
                "Record": {
                    "type": "object",
                    "properties": {"example": {"$ref": "#/components/schemas/Field"}},
                    "example": {"$ref": "external-file.yaml"},
                    "default": {"$ref": "also-data.json"},
                },
                "Field": {"type": "string"},
            }
        }
    }
    node = {"$ref": "#/components/schemas/Record"}
    before = gen.closure_hash(spec, node)
    spec["components"]["schemas"]["Field"]["type"] = "integer"
    assert gen.closure_hash(spec, node) != before


def test_latest_resolves_to_immutable_commit_with_get(monkeypatch):
    def open_url(request, **kwargs):
        assert request.get_method() == "GET"
        assert request.full_url == "https://api.github.com/repos/github/rest-api-description/commits/main"
        return io.BytesIO(json.dumps({"sha": SHA}).encode())

    monkeypatch.setattr(gen.urllib.request, "urlopen", open_url)
    assert gen.resolve_revision("latest") == SHA
    assert gen.resolve_revision(SHA) == SHA
    with pytest.raises(ValueError, match="commit SHA"):
        gen.resolve_revision("main/../../bad")


@pytest.mark.parametrize("drift", [False, True])
def test_upstream_check_never_changes_manifest(monkeypatch, tmp_path, drift):
    path = tmp_path / "manifest.json"
    current = {"revision": SHA, "api_version": "2026-03-10", "operations": [{"operation_id": "old"}]}
    path.write_text(json.dumps(current))
    before = path.read_bytes()
    newer = copy.deepcopy(current)
    newer["revision"] = "b" * 40
    if drift:
        newer["operations"].append({"operation_id": "new"})
    monkeypatch.setattr(gen, "OUTPUT", path)
    monkeypatch.setattr(gen, "resolve_revision", lambda revision: "b" * 40)
    monkeypatch.setattr(gen, "build", lambda *a, **kw: newer)
    monkeypatch.setattr("sys.argv", ["generate_rest_catalog.py", "--check-upstream"])
    if drift:
        with pytest.raises(SystemExit, match="coverage changed"):
            gen.main()
    else:
        gen.main()
    assert path.read_bytes() == before


def test_refresh_persists_new_pin_and_next_check_uses_it(monkeypatch, tmp_path):
    path = tmp_path / "manifest.json"
    current = {"revision": SHA, "api_version": "2026-03-10", "operations": []}
    path.write_text(json.dumps(current))
    monkeypatch.setattr(gen, "OUTPUT", path)
    monkeypatch.setattr(gen, "resolve_revision", lambda value: "b" * 40 if value == "latest" else value)
    seen = []

    def build(source_dir, *, revision, api_version):
        seen.append(revision)
        return {**current, "revision": revision, "api_version": api_version}

    monkeypatch.setattr(gen, "build", build)
    monkeypatch.setattr("sys.argv", ["generate_rest_catalog.py", "--revision", "latest"])
    gen.main()
    monkeypatch.setattr("sys.argv", ["generate_rest_catalog.py", "--check"])
    gen.main()
    assert seen == ["b" * 40, "b" * 40]
