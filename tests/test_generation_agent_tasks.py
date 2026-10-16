"""Task routes share identity while preserving provenance and typed nested details."""

from copy import deepcopy

import pytest

from tests.helpers import install
from tests.test_generated_runtime import run
from tests.test_generation_artifacts import ROOT
from tests.test_generation_artifacts import pilot as pilot
from vgi_github.generated_runtime import GeneratedContractError

OWNER = "agent-task-fixture"
ALPHA = OWNER + "/alpha"


@pytest.fixture
def tasks(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "tests/crossfield"))
    import agent_tasks_fixture

    return agent_tasks_fixture


def rows_for(contract, **arguments):
    entity = next(row for row in contract["functions"] if row["name"] == "agent_tasks")
    result = run(entity, {key: [value] for key, value in arguments.items()}, contract=contract)
    return [row for batch in result.batches for row in batch.to_pylist()]


def test_cohort_hydration_keeps_every_page_waiting_for_users_and_empty_parents(pilot, tasks, monkeypatch):
    _, contract, _ = pilot
    requests = install(monkeypatch, tasks.respond)
    rows = rows_for(contract, organization=OWNER)
    assert [(r["task_id"], r["repository_id"], r["state"]) for r in rows] == [
        ("task-a", 31001, "completed"),
        ("task-b", 31001, "failed"),
        ("task-c", 31002, "waiting_for_user"),
    ]
    assert sum(r["session_count"] for r in rows) == 4
    assert sum(len(r["sessions"]) for r in rows) == 3
    assert sum(len(r["artifacts"]) for r in rows) == 3
    assert any(r.url.path.endswith("/alpha/tasks") and r.url.params.get("page") == "2" for r in requests)
    assert any(r.url.path.endswith("/empty/tasks") for r in requests)
    assert len([r for r in requests if "/tasks/task-" in r.url.path]) == 3
    assert rows_for(contract, repository=OWNER + "/empty") == []


def test_lookup_and_authenticated_routes_share_identity_without_inventing_names(pilot, tasks, monkeypatch):
    _, contract, _ = pilot
    install(monkeypatch, tasks.respond)
    scoped = rows_for(contract, repository=ALPHA, agent_task_id="task-a")[0]
    global_row = rows_for(contract, agent_task_id="task-a")[0]
    assert scoped["repository"] == ALPHA and global_row["repository"] is None
    assert {k: v for k, v in scoped.items() if k != "repository"} == {
        k: v for k, v in global_row.items() if k != "repository"
    }
    rows = rows_for(contract, authenticated_user=True)
    assert [r["task_id"] for r in rows] == ["task-a", "task-b", "task-c", "task-orphan"]
    assert all(r["repository"] is None for r in rows)
    assert rows[-1]["repository_id"] is None and rows[-1]["sessions"] is None
    assert rows[-1]["creator_id"] is None and rows[-1]["artifacts"] is None


def test_typed_artifact_variants_and_session_actor_roles(pilot, tasks, monkeypatch):
    _, contract, _ = pilot
    install(monkeypatch, tasks.respond)
    row = rows_for(contract, agent_task_id="task-a")[0]
    assert row["creator_id"] == 38101 and row["repository_owner_id"] == 31000
    assert row["sessions"][0]["user"]["id"] == 38102
    assert row["sessions"][0]["usage"] == {"type": "premium_requests", "amount": 1.5}
    assert row["sessions"][0]["error"]["message"] == "First attempt failed"
    assert row["sessions"][1]["error"] is None
    pull, branch = row["artifacts"]
    assert pull["data"]["variant_1"] == {"id": 39101, "global_id": "PR_39101"}
    assert pull["data"]["variant_2"] is None
    assert branch["data"]["variant_1"] is None
    assert branch["data"]["variant_2"] == {"head_ref": "agent/patch", "base_ref": "main"}


def test_archived_and_filtered_populations_are_explicit(pilot, tasks, monkeypatch):
    _, contract, _ = pilot
    requests = install(monkeypatch, tasks.respond)
    assert [r["task_id"] for r in rows_for(contract, repository=ALPHA, agent_task_archived=True)] == [
        "task-archived"
    ]
    assert [r["task_id"] for r in rows_for(contract, authenticated_user=True, agent_task_archived=True)] == [
        "task-archived"
    ]
    rows = rows_for(
        contract,
        organization=OWNER,
        agent_task_states="failed,waiting_for_user",
        agent_task_sort="created_at",
        agent_task_direction="asc",
    )
    assert [r["task_id"] for r in rows] == ["task-b", "task-c"]
    assert any(r.url.params.get("is_archived") == "true" for r in requests)
    assert any(
        r.url.params.get("sort") == "created_at" and r.url.params.get("direction") == "asc" for r in requests
    )


def test_creator_array_uses_repeated_query_keys_and_retains_pages(pilot, tasks, monkeypatch):
    _, contract, _ = pilot
    requests = install(monkeypatch, tasks.respond)
    rows = rows_for(contract, repository=ALPHA, agent_task_creator_ids=[38101, 38102])
    assert [r["task_id"] for r in rows] == ["task-a", "task-b"]
    lists = [r for r in requests if r.url.path.endswith("/alpha/tasks")]
    assert len(lists) == 2
    assert all(r.url.params.get_list("creator_id") == ["38101", "38102"] for r in lists)
    assert [r["task_id"] for r in rows_for(contract, repository=ALPHA, agent_task_creator_ids=[38102])] == [
        "task-b"
    ]


def test_lookup_identity_mismatch_fails(pilot, tasks, monkeypatch):
    _, contract, _ = pilot
    row = deepcopy(tasks.TASKS["task-a"])
    row["id"] = "task-other"
    monkeypatch.setitem(tasks.TASKS, "task-a", row)
    install(monkeypatch, tasks.respond)
    with pytest.raises(GeneratedContractError, match="task_id"):
        rows_for(contract, agent_task_id="task-a")


@pytest.mark.parametrize("nested_session", [False, True])
def test_undeclared_task_and_session_states_fail_pinned_schema(pilot, tasks, monkeypatch, nested_session):
    _, contract, _ = pilot
    row = deepcopy(tasks.TASKS["task-a"])
    target = row["sessions"][0] if nested_session else row
    target["state"] = "future_state"
    monkeypatch.setitem(tasks.TASKS, "task-a", row)
    install(monkeypatch, tasks.respond)
    with pytest.raises(GeneratedContractError, match="state.*declared enum"):
        rows_for(contract, agent_task_id="task-a")


def test_invalid_artifact_union_and_missing_required_task_state_fail(pilot, tasks, monkeypatch):
    _, contract, _ = pilot
    row = deepcopy(tasks.TASKS["task-a"])
    row["artifacts"][0]["data"] = {"id": 1, "head_ref": "x", "base_ref": "main"}
    monkeypatch.setitem(tasks.TASKS, "task-a", row)
    install(monkeypatch, tasks.respond)
    with pytest.raises(GeneratedContractError):
        rows_for(contract, agent_task_id="task-a")
    row["artifacts"] = []
    del row["state"]
    with pytest.raises(GeneratedContractError, match="state"):
        rows_for(contract, agent_task_id="task-a")


@pytest.mark.parametrize(
    "arguments",
    [
        {"repository": ALPHA, "agent_task_id": "task-a", "agent_task_states": "completed"},
        {"authenticated_user": True, "agent_task_creator_ids": [38101]},
        {"authenticated_user": False},
        {"repository": ALPHA, "agent_task_creator_ids": []},
        {"repository": ALPHA, "agent_task_sort": "random"},
        {"repository": ALPHA, "agent_task_direction": "sideways"},
        {"agent_task_id": ""},
        {"authenticated_user": True, "repository": ALPHA},
    ],
)
def test_invalid_or_conflicting_selectors_fail_without_http(pilot, tasks, monkeypatch, arguments):
    _, contract, _ = pilot
    requests = install(monkeypatch, tasks.respond)
    with pytest.raises(GeneratedContractError):
        rows_for(contract, **arguments)
    assert requests == []


def test_empty_repository_cohort_is_explicit_and_makes_no_http(pilot, tasks, monkeypatch):
    _, contract, _ = pilot
    requests = install(monkeypatch, tasks.respond)
    assert rows_for(contract, repositories=[]) == []
    assert requests == []
