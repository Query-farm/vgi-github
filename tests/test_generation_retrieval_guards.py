"""Navigation guards preserve unavailable or polymorphic parent identity."""

import json

import pytest

from tests.test_generation_artifacts import pilot as pilot
from vgi_github.generation.artifacts import emit_artifacts, validate_semantics


def guarded_relation(contract):
    relation = next(
        row for row in contract["relationships"] if row["name"] == "pull_requests_to_repositories"
    )
    return relation, relation["retrievals"][0]


def test_null_guards_are_preserved_for_scalar_and_nested_evidence(pilot):
    overlay, contract, provenance = pilot
    relation, retrieval = guarded_relation(contract)
    retrieval.update(when_not_null=["repository_id", "labels"])
    output = emit_artifacts(contract, overlay, provenance)
    model = json.loads(output["models/generated-pilot/github-generated.crossfield.json"])
    tags = json.loads(model["policy"]["tags"]["github.relationship_retrievals"])
    assert tags[relation["name"]][0]["when_not_null"] == ["repository_id", "labels"]


@pytest.mark.parametrize("guard", ["when_null", "when_not_null"])
@pytest.mark.parametrize(
    "columns", [[], "repository_id", ["missing"], [1], ["repository_id", "repository_id"]]
)
def test_null_guards_require_distinct_declared_source_columns(pilot, guard, columns):
    overlay, contract, _ = pilot
    _, retrieval = guarded_relation(contract)
    retrieval[guard] = columns
    with pytest.raises(ValueError, match="null guards require distinct declared typed fields"):
        validate_semantics(contract, overlay)


@pytest.mark.parametrize(
    "guards",
    [
        {"when_null": ["repository_id"], "when_not_null": ["repository_id"]},
        {"when": {"repository_id": 1}, "when_null": ["repository_id"]},
    ],
)
def test_contradictory_null_guards_are_not_advertised_as_navigation(pilot, guards):
    overlay, contract, _ = pilot
    _, retrieval = guarded_relation(contract)
    retrieval.update(guards)
    with pytest.raises(ValueError, match="both NULL and non-NULL|contradict"):
        validate_semantics(contract, overlay)
