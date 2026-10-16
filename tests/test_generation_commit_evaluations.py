"""Canonical status events and comments retain alternate routes and API evidence."""

from copy import deepcopy

import httpx
import pytest

from tests.helpers import install
from tests.test_generated_runtime import run
from tests.test_generation_artifacts import ROOT
from tests.test_generation_artifacts import pilot as pilot
from vgi_github.generated_runtime import GeneratedContractError

OWNER = "commit-evaluation-fixture"
ALPHA = OWNER + "/alpha"


@pytest.fixture
def evaluations(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "tests/crossfield"))
    import commit_evaluations_fixture

    return commit_evaluations_fixture


def rows_for(contract, name, **arguments):
    entity = next(row for row in contract["functions"] if row["name"] == name)
    result = run(entity, {key: [value] for key, value in arguments.items()}, contract=contract)
    return [row for batch in result.batches for row in batch.to_pylist()]


def test_status_history_and_latest_share_identity_without_timestamp_coercion(pilot, evaluations, monkeypatch):
    _, contract, _ = pilot
    requests = install(monkeypatch, evaluations.respond)
    history = rows_for(contract, "commit_statuses", organization=OWNER, commit_ref="main")
    latest = rows_for(
        contract, "commit_statuses", organization=OWNER, commit_ref="main", commit_status_population="latest"
    )
    assert [r["status_id"] for r in history] == [82003, 82002, 82001, 82004]
    assert [r["status_id"] for r in latest] == [82003, 82002, 82004]
    common = ["repository_id", "status_id", "node_id", "state", "context", "url", "target_url", "description"]
    assert [{k: r[k] for k in common} for r in latest] == [
        {k: history[i][k] for k in common} for i in [0, 1, 3]
    ]
    assert all(r["created_at"] is None and r["required"] is None and r["commit_sha"] is None for r in history)
    assert all(r["created_at_raw"] is None and r["creator_id"] is None for r in latest)
    assert history[0]["created_at_raw"] == "2026-09-01T00:00:00Z"
    assert latest[0]["created_at"].year == 2026 and latest[0]["required"] is True
    assert history[1]["creator"] is None and history[-1]["state"] == "future-state"
    assert any(r.url.path.endswith("/statuses") and r.url.params.get("page") == "3" for r in requests)
    assert any(r.url.path.endswith("/status") and r.url.params.get("page") == "2" for r in requests)


def test_combined_status_summary_retains_empty_parent(pilot, evaluations, monkeypatch):
    _, contract, _ = pilot
    install(monkeypatch, evaluations.respond)
    rows = rows_for(contract, "commit_status_summaries", organization=OWNER, commit_ref="main")
    assert [(r["repository_id"], r["state"], r["total_count"]) for r in rows] == [
        (81001, "failure", 2),
        (81002, "future-state", 1),
        (81003, "pending", 0),
    ]
    assert "statuses" not in rows[0]
    assert (
        rows_for(
            contract,
            "commit_statuses",
            repository=OWNER + "/empty",
            commit_ref="main",
            commit_status_population="latest",
        )
        == []
    )


def test_latest_statuses_reject_missing_terminal_page(pilot, evaluations, monkeypatch):
    _, contract, _ = pilot

    def respond(request):
        response = evaluations.respond(request)
        if request.url.path.endswith("/status"):
            response.headers.pop("Link", None)
        return response

    install(monkeypatch, respond)
    with pytest.raises(GeneratedContractError, match="pagination"):
        rows_for(
            contract,
            "commit_statuses",
            repository=ALPHA,
            commit_ref="main",
            commit_status_population="latest",
        )


def test_comment_repository_and_commit_routes_share_canonical_null_author_rows(
    pilot, evaluations, monkeypatch
):
    _, contract, _ = pilot
    requests = install(monkeypatch, evaluations.respond)
    rows = rows_for(contract, "commit_comments", repository=ALPHA)
    assert [r["comment_id"] for r in rows] == [83001, 83002]
    assert rows[1]["author_id"] is None and rows[1]["author_login"] is None
    assert rows_for(contract, "commit_comments", repository=ALPHA, commit_comment_id=83002) == rows[1:]
    assert (
        rows_for(contract, "commit_comments", repository=ALPHA, commit_comment_sha=evaluations.SHAS["alpha"])
        == rows
    )
    assert rows[0]["path"] == "src/main.py" and rows[0]["position"] is None
    assert rows[0]["repository_node_id"] == "R81001"
    assert any(r.url.path.endswith("/comments") and r.url.params.get("page") == "2" for r in requests)


def test_rule_suite_org_repo_and_lookup_routes_retain_full_evaluations(pilot, evaluations, monkeypatch):
    _, contract, _ = pilot
    requests = install(monkeypatch, evaluations.respond)
    org = rows_for(contract, "rule_suites", organization=OWNER)
    repo = rows_for(
        contract,
        "rule_suites",
        repositories=[
            {"repository": repository} for repository in [ALPHA, OWNER + "/beta", OWNER + "/empty"]
        ],
    )
    assert [r["rule_suite_id"] for r in org] == [84001, 84002, 84003]
    assert [r["rule_suite_id"] for r in repo] == [84001, 84002, 84003]
    assert [len(r["rule_evaluations"]) for r in org] == [2, 1, 0]
    assert org[1]["actor_id"] is None and org[1]["evaluation_result"] is None
    assert all(r["repository"] is None and r["organization"] == OWNER for r in org)
    assert [r["repository"] for r in repo] == [ALPHA, ALPHA, OWNER + "/beta"]
    assert rows_for(contract, "rule_suites", organization=OWNER, rule_suite_id=84002) == org[1:2]
    assert rows_for(contract, "rule_suites", repository=ALPHA, rule_suite_id=84002) == repo[1:2]
    assert rows_for(contract, "rule_suites", organization=OWNER, rule_evaluation_repository="beta") == org[2:]
    assert rows_for(contract, "rule_suites", repository=ALPHA, rule_evaluation_result="fail") == repo[1:2]
    assert any(r.url.params.get("page") == "3" for r in requests)


def test_rule_suite_optional_id_is_qualified_before_emission(pilot, evaluations, monkeypatch):
    _, contract, _ = pilot
    broken = deepcopy(evaluations.RULES["alpha"])
    broken[0].pop("id")
    monkeypatch.setitem(evaluations.RULES, "alpha", broken)
    install(monkeypatch, evaluations.respond)
    with pytest.raises(GeneratedContractError, match="rule_suite_id"):
        rows_for(contract, "rule_suites", repository=ALPHA)


def test_bypass_requests_keep_requester_reviewer_and_lookup_identity(pilot, evaluations, monkeypatch):
    _, contract, _ = pilot
    requests = install(monkeypatch, evaluations.respond)
    rows = rows_for(contract, "push_bypass_requests", organization=OWNER)
    assert [(r["bypass_request_id"], r["request_number"], r["status"]) for r in rows] == [
        (85001, 1, "approved"),
        (85002, 2, "pending"),
        (85003, 1, "denied"),
    ]
    assert [len(r["responses"]) for r in rows] == [2, 0, 1]
    assert rows[0]["requester_id"] == 88101 and rows[0]["responses"][0]["reviewer"]["actor_id"] == 88102
    assert rows_for(contract, "push_bypass_requests", repository=ALPHA, bypass_request_number=1) == rows[:1]
    assert (
        rows_for(contract, "push_bypass_requests", repository=ALPHA, bypass_request_status="approved")
        == rows[:1]
    )
    assert any(r.url.path.endswith("push-rules") and r.url.params.get("page") == "2" for r in requests)


def test_bypass_wrong_repository_and_suite_wrong_id_fail(pilot, evaluations, monkeypatch):
    _, contract, _ = pilot

    def respond(request):
        response = evaluations.respond(request)
        if response is not None and request.url.path.endswith("/push-rules/1"):
            value = response.json()
            value["repository"]["id"] = 999
            return httpx.Response(200, json=value, request=request)
        if response is not None and request.url.path.endswith("/rule-suites/84001"):
            value = response.json()
            value["id"] = 999
            return httpx.Response(200, json=value, request=request)
        if response is not None and request.url.path.endswith("/comments/83001"):
            value = response.json()
            value["id"] = 999
            return httpx.Response(200, json=value, request=request)
        return response

    install(monkeypatch, respond)
    with pytest.raises(GeneratedContractError, match="repository_id"):
        rows_for(contract, "push_bypass_requests", repository=ALPHA, bypass_request_number=1)
    with pytest.raises(GeneratedContractError, match="rule_suite_id"):
        rows_for(contract, "rule_suites", repository=ALPHA, rule_suite_id=84001)
    with pytest.raises(GeneratedContractError, match="comment_id"):
        rows_for(contract, "commit_comments", repository=ALPHA, commit_comment_id=83001)


@pytest.mark.parametrize(
    ("entity", "arguments"),
    [
        ("commit_statuses", {"repository": ALPHA}),
        (
            "commit_statuses",
            {"repository": ALPHA, "commit_ref": "main", "commit_status_population": "recent"},
        ),
        ("commit_status_summaries", {"repository": ALPHA, "commit_ref": ""}),
        ("rule_suites", {"rule_suite_id": 84001}),
        ("rule_suites", {"repository": ALPHA, "organization": OWNER, "rule_suite_id": 84001}),
        ("rule_suites", {"repository": ALPHA, "rule_evaluation_time_period": "year"}),
        ("rule_suites", {"repository": ALPHA, "rule_suite_id": 84001, "rule_evaluation_result": "pass"}),
        (
            "push_bypass_requests",
            {"repository": ALPHA, "bypass_request_number": 1, "bypass_request_status": "approved"},
        ),
        ("push_bypass_requests", {"repository": ALPHA, "bypass_request_status": "pending"}),
    ],
)
def test_invalid_scopes_fail_before_http(pilot, monkeypatch, entity, arguments):
    _, contract, _ = pilot
    requests = install(monkeypatch, lambda request: pytest.fail("invalid selection reached HTTP"))
    with pytest.raises((GeneratedContractError, ValueError)):
        rows_for(contract, entity, **arguments)
    assert requests == []
