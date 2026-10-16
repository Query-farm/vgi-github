"""Domain composition checks; business meanings still pass the normal validators."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from scripts import generate_semantic_catalog as generator
from vgi_github.generation.artifacts import validate_semantics
from vgi_github.generation.overlay import load_overlay, overlay_bytes
from vgi_github.generation.schema import compile_contract

ROOT = Path(__file__).resolve().parents[1]


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))


def manifest(tmp_path, domains):
    path = tmp_path / "pilot.json"
    write_json(
        path,
        {
            "format": "vgi-github-semantic-overlay",
            "version": 1,
            "model": {"name": "github", "id": "queryfarm.github.generated_pilot"},
            "domains": domains,
        },
    )
    return path


def test_declared_domain_and_definition_order_is_stable(tmp_path):
    path = manifest(tmp_path, ["domains/z.json", "domains/a.json"])
    write_json(tmp_path / "domains/z.json", {"entities": [{"name": "second"}, {"name": "first"}]})
    write_json(tmp_path / "domains/a.json", {"entities": [{"name": "third"}]})
    overlay = load_overlay(path)
    assert [entity["name"] for entity in overlay["entities"]] == ["second", "first", "third"]
    assert overlay_bytes(overlay) == overlay_bytes(load_overlay(path))
    assert "domains" not in overlay


def test_provenance_covers_domain_contents_not_json_whitespace(tmp_path):
    path = manifest(tmp_path, ["domain.json"])
    domain = tmp_path / "domain.json"
    definition = {"entities": [{"name": "first", "description": "before"}]}
    write_json(domain, definition)
    before = overlay_bytes(load_overlay(path))
    domain.write_text(json.dumps(definition, indent=4))
    assert overlay_bytes(load_overlay(path)) == before
    definition["entities"][0]["description"] = "after"
    write_json(domain, definition)
    assert overlay_bytes(load_overlay(path)) != before


def test_missing_domain_has_file_context(tmp_path):
    path = manifest(tmp_path, ["domains/missing.json"])
    with pytest.raises(ValueError, match=r"Cannot read semantic definitions .*domains/missing.json"):
        load_overlay(path)


@pytest.mark.parametrize("duplicate", ["domain.json", "./domain.json", "alias.json"])
def test_duplicate_domain_files_reject_including_aliases(tmp_path, duplicate):
    path = manifest(tmp_path, ["domain.json", duplicate])
    write_json(tmp_path / "domain.json", {"entities": [{"name": "one"}]})
    (tmp_path / "alias.json").symlink_to(tmp_path / "domain.json")
    with pytest.raises(ValueError, match="duplicate or recursive domain file"):
        load_overlay(path)


@pytest.mark.parametrize("relative", ["../outside.json", "/tmp/outside.json", "other.txt", "pilot.json"])
def test_domain_paths_are_explicit_local_json_files(tmp_path, relative):
    path = manifest(tmp_path, [relative])
    with pytest.raises(ValueError, match="relative JSON paths|JSON file under|recursive domain file"):
        load_overlay(path)


@pytest.mark.parametrize("section", ["entities", "functions", "relationships", "scopes", "shared_dimensions"])
def test_cross_domain_names_cannot_overwrite_case_insensitively(tmp_path, section):
    path = manifest(tmp_path, ["a.json", "b.json"])
    for filename, name in (("a.json", "source"), ("b.json", "SOURCE")):
        definitions = {name: {}} if section in {"scopes", "shared_dimensions"} else [{"name": name}]
        write_json(tmp_path / filename, {section: definitions})
    with pytest.raises(
        ValueError, match=rf"b.json: duplicate {section} name 'SOURCE'; first declared in .*a.json"
    ):
        load_overlay(path)


def test_duplicate_json_keys_reject_before_overwrite(tmp_path):
    path = manifest(tmp_path, ["a.json"])
    (tmp_path / "a.json").write_text('{"scopes":{"users":{},"users":{}}}')
    with pytest.raises(ValueError, match="duplicate JSON key 'users'"):
        load_overlay(path)


@pytest.mark.parametrize(
    "fragment, message",
    [
        ({"domains": ["nested.json"]}, "unknown keys"),
        ({"model": {"name": "override"}}, "unknown keys"),
        ({"entities": {}}, "entities must be a list"),
        ({"scopes": []}, "scopes must be a named object"),
        ({"entities": [None]}, "declaration must be an object"),
        ({"entities": [{}]}, "require nonempty names"),
    ],
)
def test_domains_do_not_add_an_override_or_import_language(tmp_path, fragment, message):
    path = manifest(tmp_path, ["a.json"])
    write_json(tmp_path / "a.json", fragment)
    with pytest.raises(ValueError, match=message):
        load_overlay(path)


def test_pilot_domains_keep_public_identity_and_cross_domain_bindings():
    overlay = load_overlay(ROOT / "generation/pilot.json")
    specs, sdl, _ = generator.locked_inputs(ROOT, overlay)
    contract = compile_contract(specs, sdl, overlay)
    validate_semantics(contract, overlay)
    assert overlay["model"]["name"] == "github"
    assert overlay["model"]["id"] == "queryfarm.github.generated_pilot"
    assert len(contract["entities"]) == 472
    assert len(contract["functions"]) == 206
    assert len(contract["relationships"]) == 298
    assert any(
        relation["from"] == "issues" and relation["to"] == "users" for relation in contract["relationships"]
    )
    assert "issues.author_id" in contract["shared_dimensions"]["github.user.id.v1"]


@pytest.fixture
def pilot_copy(tmp_path):
    shutil.copytree(ROOT / "generation", tmp_path / "generation")
    return tmp_path / "generation/pilot.json"


def test_missing_cross_domain_source_is_still_rejected(pilot_copy):
    people = pilot_copy.parent / "domains/people.json"
    domain = json.loads(people.read_text())
    domain["entities"] = []
    write_json(people, domain)
    overlay = load_overlay(pilot_copy)
    specs, sdl, _ = generator.locked_inputs(ROOT, load_overlay(ROOT / "generation/pilot.json"))
    with pytest.raises(ValueError, match="unknown source entity 'user_profile_lookup'"):
        compile_contract(specs, sdl, overlay)


def test_invalid_cross_domain_relationship_reaches_semantic_validation(pilot_copy):
    contributions = pilot_copy.parent / "domains/contributions.json"
    domain = json.loads(contributions.read_text())
    domain["relationships"][0]["to"] = "unknown_users"
    write_json(contributions, domain)
    overlay = load_overlay(pilot_copy)
    specs, sdl, _ = generator.locked_inputs(ROOT, overlay)
    contract = compile_contract(specs, sdl, overlay)
    with pytest.raises(ValueError, match="Relationship names and entity references"):
        validate_semantics(contract, overlay)
