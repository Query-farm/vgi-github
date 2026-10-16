"""Detailed repository changes retain repository grain, performer role and opaque cursors."""

import json
from copy import deepcopy

import httpx
import pytest

from tests.helpers import install
from tests.test_generated_runtime import run
from tests.test_generation_artifacts import ROOT
from tests.test_generation_artifacts import pilot as pilot
from vgi_github.generated_runtime import GeneratedContractError
from vgi_github.github_api import GitHubError


@pytest.fixture
def changes(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "tests/crossfield"))
    import repository_activity_fixture

    return repository_activity_fixture


def rows_for(contract, **arguments):
    entity = next(value for value in contract["functions"] if value["name"] == "repository_changes")
    output = run(entity, {key: [value] for key, value in arguments.items()}, contract=contract)
    return [row for batch in output.batches for row in batch.to_pylist()]


def test_change_history_is_one_entity_distinct_from_public_events():
    domain = json.loads((ROOT / "generation/domains/repository_activity.json").read_text())
    assert [s["transport"]["operation_id"] for s in domain["entities"]] == ["repos/list-activities"]
    assert domain["functions"][0]["name"] == "repository_changes"
    assert domain["functions"][0]["grain"] == ["repository_id", "change_id"]
    assert len(domain["relationships"]) == 2


def test_changes_follow_opaque_cursors_and_preserve_nullable_performer(pilot, changes, monkeypatch):
    _, contract, _ = pilot
    requests = install(monkeypatch, changes.respond)
    rows = rows_for(contract, organization="changes-fixture")
    assert [(r["repository_id"], r["change_id"], r["activity_type"], r["actor_id"]) for r in rows] == [
        (6801, 1, "push", 6850),
        (6801, 2, "force_push", None),
        (6801, 3, "branch_deletion", 6850),
        (6802, 1, "pr_merge", 6850),
    ]
    assert rows[1]["actor"] is None
    assert rows[2]["after_sha"] == "0" * 40
    assert any(r.url.params.get("after") == "cursor:2" for r in requests)
    assert rows_for(contract, owner="changes-fixture") == rows


def test_changes_bind_every_named_filter_and_preserve_cursor_subpopulation(pilot, changes, monkeypatch):
    _, contract, _ = pilot
    requests = install(monkeypatch, changes.respond)
    rows = rows_for(
        contract,
        repository="changes-fixture/alpha",
        repository_activity_ref="refs/heads/main",
        repository_activity_actor="changes-fixture-actor",
        repository_activity_period="month",
        repository_activity_type="push",
        repository_activity_direction="asc",
    )
    assert [r["change_id"] for r in rows] == [1]
    query = next(r.url.params for r in requests if r.url.path.endswith("/activity"))
    assert dict(query) == {
        "ref": "refs/heads/main",
        "actor": "changes-fixture-actor",
        "time_period": "month",
        "activity_type": "push",
        "direction": "asc",
        "per_page": "100",
    }
    assert [
        r["change_id"]
        for r in rows_for(contract, repository="changes-fixture/alpha", repository_activity_after="cursor:1")
    ] == [2, 3]
    assert [
        r["change_id"]
        for r in rows_for(contract, repository="changes-fixture/alpha", repository_activity_before="cursor:1")
    ] == [1]


def test_changes_empty_cohort_and_empty_filter_population(pilot, changes, monkeypatch):
    _, contract, _ = pilot
    requests = install(monkeypatch, changes.respond)
    assert rows_for(contract, repositories=[]) == []
    assert requests == []
    assert (
        rows_for(
            contract,
            repositories=[{"repository": "changes-fixture/alpha"}],
            repository_activity_type="merge_queue_merge",
        )
        == []
    )


@pytest.mark.parametrize("failure", ["later_denial", "duplicate_identity", "unknown_kind", "bad_actor"])
def test_changes_invalid_pages_cannot_claim_complete_history(pilot, changes, monkeypatch, failure):
    _, contract, _ = pilot

    def handler(request):
        if request.url.path.endswith("/activity"):
            if failure == "later_denial" and request.url.params.get("after"):
                return httpx.Response(403, json={"message": "Forbidden"})
            if failure != "later_denial":
                rows = deepcopy(changes.CHANGES["alpha"])
                if failure == "duplicate_identity":
                    rows[1]["id"] = rows[0]["id"]
                if failure == "unknown_kind":
                    rows[0]["activity_type"] = "something_new"
                if failure == "bad_actor":
                    rows[0]["actor"]["id"] = "6850"
                return httpx.Response(200, json=rows)
        return changes.respond(request)

    install(monkeypatch, handler)
    with pytest.raises((GeneratedContractError, GitHubError)):
        rows_for(contract, repository="changes-fixture/alpha")
