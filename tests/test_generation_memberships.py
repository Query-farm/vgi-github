"""Independent typed membership arrays from the pinned REST schemas."""

from copy import deepcopy
from pathlib import Path

import httpx
import pyarrow as pa
import pytest

from scripts import generate_semantic_catalog as generator
from tests.helpers import install
from tests.test_generated_runtime import run
from vgi_github.generated_runtime import GeneratedContractError
from vgi_github.generation.overlay import load_overlay
from vgi_github.generation.schema import compile_rest_entity

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def membership_sources():
    overlay = load_overlay(ROOT / "generation/pilot.json")
    specs, _, _ = generator.locked_inputs(ROOT, overlay)
    selected = {}
    for original in overlay["entities"]:
        if original["name"] not in {
            "repository_lookup", "organization_repositories", "user_repositories",
            "pull_request_list", "pull_request_lookup",
        }:
            continue
        entity = deepcopy(original)
        # Keep the real source grain and complete nested selections, without
        # making unrelated API fields part of this independent payload fixture.
        fields = set(entity["grain"]) | {"topic_names", "labels", "assignees"}
        entity["columns"] = [column for column in entity["columns"] if column["name"] in fields]
        selected[entity["name"]] = compile_rest_entity(specs["api.github.com"], entity)
    return selected


def arguments(entity):
    return {
        item["name"]: [
            7 if item["type"] == "BIGINT" else "example/alpha" if item["name"] == "repository" else "example"
        ]
        for item in entity["arguments"]
    }


def response(entity, row):
    return httpx.Response(200, json=row if entity["transport"]["result_shape"] == "object" else [row])


@pytest.mark.parametrize("source", ["repository_lookup", "organization_repositories", "user_repositories"])
def test_rest_topics_preserve_every_returned_membership(monkeypatch, membership_sources, source):
    entity = membership_sources[source]
    topics = [f"topic-{index}" for index in range(150)]
    install(monkeypatch, lambda request: response(entity, {"id": 101, "topics": topics}))
    out = run(entity, arguments(entity))
    assert out.batches[0].to_pylist()[0]["topic_names"] == topics
    assert pa.types.is_list(out.batches[0].schema.field("topic_names").type)
    assert out.finished


@pytest.mark.parametrize("source", ["pull_request_list", "pull_request_lookup"])
def test_rest_pr_memberships_remain_typed_complete_arrays(monkeypatch, membership_sources, source):
    entity = membership_sources[source]
    labels = [{"id": index, "name": f"label-{index}"} for index in range(150)]
    assignees = [{"id": 201, "login": "alice"}, {"id": 202, "login": "bob"}]
    row = {"id": 1001, "number": 7, "labels": labels, "assignees": assignees}
    install(monkeypatch, lambda request: response(entity, row))
    out = run(entity, arguments(entity))
    decoded = out.batches[0].to_pylist()[0]
    assert decoded["labels"] == labels and decoded["assignees"] == assignees
    label_type = out.batches[0].schema.field("labels").type.value_type
    assignee_type = out.batches[0].schema.field("assignees").type.value_type
    assert label_type == pa.struct(
        [pa.field("id", pa.int64(), nullable=False), pa.field("name", pa.string(), nullable=False)]
    )
    assert assignee_type == pa.struct(
        [pa.field("id", pa.int64(), nullable=False), pa.field("login", pa.string(), nullable=False)]
    )


def test_rest_membership_identity_type_errors_are_not_hidden(monkeypatch, membership_sources):
    entity = membership_sources["pull_request_list"]
    row = {"id": 1001, "number": 7, "labels": [{"id": "501", "name": "bug"}], "assignees": []}
    install(monkeypatch, lambda request: response(entity, row))
    with pytest.raises(GeneratedContractError, match=r"labels\[0\].id: invalid BIGINT"):
        run(entity, arguments(entity))


def test_empty_arrays_do_not_invent_memberships(monkeypatch, membership_sources):
    entity = membership_sources["pull_request_lookup"]
    install(
        monkeypatch,
        lambda request: response(entity, {"id": 1003, "number": 7, "labels": [], "assignees": []}),
    )
    out = run(entity, arguments(entity))
    row = out.batches[0].to_pylist()[0]
    assert row["labels"] == [] and row["assignees"] == []
