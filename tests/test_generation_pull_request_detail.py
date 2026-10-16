"""Canonical PR relationships, complete capped populations and merge observations."""

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
def pull_detail_api(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "tests/crossfield"))
    import pull_request_detail_fixture

    return pull_request_detail_fixture


def rows_for(contract, name, **arguments):
    entity = next(row for row in contract["functions"] if row["name"] == name)
    output = run(entity, {key: [value] for key, value in arguments.items()}, contract=contract)
    return [row for batch in output.batches for row in batch.to_pylist()]


PR_DETAIL_FIELDS = (
    "comments_count",
    "review_comments_count",
    "commits_count",
    "additions",
    "deletions",
    "changed_files",
    "merged",
    "mergeable",
    "rebaseable",
    "mergeable_state",
    "maintainer_can_modify",
    "merged_by",
)


def test_canonical_pr_common_fields_and_full_response_counters(pilot, pull_detail_api, monkeypatch):
    _, contract, _ = pilot
    requests = install(monkeypatch, pull_detail_api.respond)
    listed = rows_for(contract, "pull_requests", repository="pull-detail-fixture/alpha")
    assert [(row["pull_request_id"], row["base_ref"], row["head_ref"]) for row in listed] == [
        (1311, "main", "change-1"),
        (1312, "main", "change-2"),
    ]
    assert all(row[field] is None for row in listed for field in PR_DETAIL_FIELDS)
    assert [request.url.path for request in requests] == [
        "/repos/pull-detail-fixture/alpha",
        "/repos/pull-detail-fixture/alpha/pulls",
        "/repos/pull-detail-fixture/alpha/pulls",
    ]
    requests.clear()
    detail = rows_for(
        contract, "pull_requests", repository="pull-detail-fixture/alpha", pull_request_number=1
    )[0]
    assert {**detail, **dict.fromkeys(PR_DETAIL_FIELDS)} == listed[0]
    assert tuple(detail[field] for field in PR_DETAIL_FIELDS[:6]) == (3, 2, 2, 10, 3, 2)
    assert detail["merged_by"] == {"id": 1402, "login": "pull-detail-bob", "type": "User"}
    assert detail["head"]["repo"] == {
        "id": 91301,
        "node_id": "R91301",
        "full_name": "pull-detail-alice/alpha",
    }
    assert detail["base"]["repo"] == {
        "id": 1301,
        "node_id": "R1301",
        "full_name": "pull-detail-fixture/alpha",
    }
    assert detail["base"]["sha"] == "a" * 40 and detail["head"]["sha"] == "b" * 40
    assert detail["merge_commit_sha"] == "c" * 40
    assert detail["locked"] is True and detail["active_lock_reason"] == "resolved"
    assert detail["milestone"] == {
        "id": 1711,
        "number": 1,
        "title": "Delivery",
        "state": "open",
        "due_on": None,
    }
    assert [request.url.path for request in requests] == [
        "/repos/pull-detail-fixture/alpha",
        "/repos/pull-detail-fixture/alpha/pulls/1",
    ]


def test_full_pr_zero_counters_and_unknown_mergeability_are_distinct_from_list_absence(
    pilot, pull_detail_api, monkeypatch
):
    _, contract, _ = pilot
    install(monkeypatch, pull_detail_api.respond)
    draft = rows_for(
        contract, "pull_requests", repository="pull-detail-fixture/alpha", pull_request_number=2
    )[0]
    assert tuple(draft[field] for field in PR_DETAIL_FIELDS[:6]) == (0, 0, 0, 0, 0, 0)
    assert draft["merged"] is False and draft["mergeable"] is None and draft["rebaseable"] is None
    assert draft["mergeable_state"] == "unknown" and draft["merged_by"] is None
    pending = rows_for(
        contract, "pull_requests", repository="pull-detail-fixture/beta", pull_request_number=1
    )[0]
    assert pending["auto_merge"]["enabled_by"]["id"] == 1401
    assert pending["auto_merge"]["merge_method"] == "squash"
    assert pending["merged_by"] is None


def test_missing_required_full_pr_counter_rejects_without_reinterpreting_as_list_response(
    pilot, pull_detail_api, monkeypatch
):
    _, contract, _ = pilot

    def respond(request):
        response = pull_detail_api.respond(request)
        if request.url.path.endswith("/pulls/1"):
            value = deepcopy(response.json())
            value.pop("comments")
            return httpx.Response(200, json=value, request=request)
        return response

    install(monkeypatch, respond)
    with pytest.raises(GeneratedContractError, match="comments_count.*missing required"):
        rows_for(contract, "pull_requests", repository="pull-detail-fixture/alpha", pull_request_number=1)


def test_pr_detail_parent_navigation_targets_the_exact_lookup_route(pilot):
    _, contract, _ = pilot
    for relationship in contract["relationships"]:
        if relationship["to"] != "pull_requests":
            continue
        for retrieval in relationship.get("retrievals", []):
            if retrieval["direction"] == "forward" and "pull_request_number" in retrieval["bindings"]:
                assert retrieval["route"] == "lookup"


def test_review_lookup_is_the_same_canonical_review(pilot, pull_detail_api, monkeypatch):
    _, contract, _ = pilot
    install(monkeypatch, pull_detail_api.respond)
    rows = rows_for(
        contract, "pull_request_reviews", repository="pull-detail-fixture/alpha", pull_request_number=1
    )
    assert [row["review_id"] for row in rows] == [1511, 1512]
    assert rows_for(
        contract,
        "pull_request_reviews",
        repository="pull-detail-fixture/alpha",
        pull_request_number=1,
        review_id=1511,
    ) == [rows[0]]
    assert (rows[0]["author_id"], rows[0]["reviewer_id"]) == (1401, 1402)


def test_review_comment_routes_keep_one_identity_and_honest_parent_context(
    pilot, pull_detail_api, monkeypatch
):
    _, contract, _ = pilot
    requests = install(monkeypatch, pull_detail_api.respond)
    repo = rows_for(contract, "pull_request_review_comments", repository="pull-detail-fixture/alpha")
    assert [(row["review_comment_id"], row["pull_request_number"]) for row in repo] == [
        (1611, None),
        (1612, None),
        (1621, None),
    ]
    assert rows_for(
        contract,
        "pull_request_review_comments",
        repository="pull-detail-fixture/alpha",
        review_comment_id=1611,
    ) == [repo[0]]
    pr = rows_for(
        contract,
        "pull_request_review_comments",
        repository="pull-detail-fixture/alpha",
        pull_request_number=1,
    )
    assert [(row["review_comment_id"], row["pull_request_number"]) for row in pr] == [(1611, 1), (1612, 1)]
    assert {key: value for key, value in pr[0].items() if key != "pull_request_number"} == {
        key: value for key, value in repo[0].items() if key != "pull_request_number"
    }
    assert rows_for(
        contract,
        "pull_request_review_comments",
        repository="pull-detail-fixture/alpha",
        pull_request_number=1,
        review_id=1511,
    ) == [pr[0]]
    assert pr[1]["in_reply_to_id"] == 1611
    assert repo[2]["comment_author_id"] is None and repo[2]["review_id"] is None
    assert any(request.url.params.get("page") == "3" for request in requests)


def test_pr_file_population_matches_parent_count_and_preserves_absent_binary_patch(
    pilot, pull_detail_api, monkeypatch
):
    _, contract, _ = pilot
    requests = install(monkeypatch, pull_detail_api.respond)
    rows = rows_for(contract, "pull_request_files", organization="pull-detail-fixture")
    assert [(row["repository_id"], row["pull_request_number"], row["filename"]) for row in rows] == [
        (1301, 1, "main.py"),
        (1301, 1, "image.png"),
        (1302, 1, "renamed.py"),
    ]
    assert (sum(row["additions"] for row in rows), sum(row["deletions"] for row in rows)) == (12, 4)
    assert rows[1]["patch"] is None
    assert rows[2]["previous_filename"] == "old.py"
    assert any(
        request.url.path.endswith("/files") and request.url.params.get("page") == "2" for request in requests
    )
    assert (
        rows_for(
            contract, "pull_request_files", repository="pull-detail-fixture/alpha", pull_request_number=2
        )
        == []
    )


def test_pr_commit_discovery_hydrates_canonical_commits_and_reverses_existing_memberships(
    pilot, pull_detail_api, monkeypatch
):
    _, contract, _ = pilot
    install(monkeypatch, pull_detail_api.respond)
    rows = rows_for(contract, "commits", repository="pull-detail-fixture/alpha", pull_request_number=1)
    assert [row["commit_sha"] for row in rows] == [pull_detail_api.A, pull_detail_api.B]
    assert rows_for(
        contract, "commits", repository="pull-detail-fixture/alpha", commit_ref=pull_detail_api.A
    ) == [rows[0]]
    pairs = rows_for(
        contract,
        "commit_pull_request_memberships",
        repository="pull-detail-fixture/alpha",
        pull_request_number=1,
    )
    assert [(row["repository_id"], row["pull_request_id"], row["commit_sha"]) for row in pairs] == [
        (1301, 1311, pull_detail_api.A),
        (1301, 1311, pull_detail_api.B),
    ]
    assert all(row["author_id"] == 1401 for row in pairs)
    assert rows_for(contract, "commits", repository="pull-detail-fixture/alpha", pull_request_number=2) == []


@pytest.mark.parametrize(
    "entity,counter,count", [("commits", "commits", 251), ("pull_request_files", "changed_files", 3001)]
)
def test_capped_or_changed_populations_fail_instead_of_reporting_a_complete_prefix(
    pilot, pull_detail_api, monkeypatch, entity, counter, count
):
    _, contract, _ = pilot
    changed = deepcopy(pull_detail_api.PULLS["alpha"])
    changed[0][counter] = count
    monkeypatch.setitem(pull_detail_api.PULLS, "alpha", changed)
    install(monkeypatch, pull_detail_api.respond)
    with pytest.raises(GeneratedContractError, match="count"):
        rows_for(contract, entity, repository="pull-detail-fixture/alpha", pull_request_number=1)


def test_requested_reviewers_keep_users_teams_and_empty_prs(pilot, pull_detail_api, monkeypatch):
    _, contract, _ = pilot
    install(monkeypatch, pull_detail_api.respond)
    rows = rows_for(contract, "pull_request_review_requests", organization="pull-detail-fixture")
    assert [
        (
            row["repository_id"],
            row["pull_request_number"],
            len(row["requested_users"]),
            len(row["requested_teams"]),
        )
        for row in rows
    ] == [(1301, 1, 1, 1), (1301, 2, 0, 0), (1302, 1, 2, 0)]
    assert rows[0]["requested_users"][0]["id"] == 1402
    assert rows[0]["requested_teams"][0]["id"] == 1801


def test_merge_predicate_has_declared_negative_status_but_other_errors_fail(
    pilot, pull_detail_api, monkeypatch
):
    _, contract, _ = pilot
    requests = install(monkeypatch, pull_detail_api.respond)
    rows = rows_for(contract, "pull_request_merge_statuses", organization="pull-detail-fixture")
    assert [row["status_code"] for row in rows] == [204, 404, 404]
    assert all(request.method == "GET" for request in requests)

    def forbidden(request):
        return (
            httpx.Response(403, json={"message": "Merge status forbidden"}, request=request)
            if request.url.path.endswith("/merge")
            else pull_detail_api.respond(request)
        )

    install(monkeypatch, forbidden)
    with pytest.raises(GitHubError, match="403"):
        rows_for(
            contract,
            "pull_request_merge_statuses",
            repository="pull-detail-fixture/alpha",
            pull_request_number=1,
        )


@pytest.mark.parametrize("status", ["pending", "merged", "enqueued", "failed"])
def test_async_result_preserves_queue_outcome_and_variant_absence(
    pilot, pull_detail_api, monkeypatch, status
):
    _, contract, _ = pilot
    install(monkeypatch, pull_detail_api.respond)
    row = rows_for(
        contract,
        "pull_request_merge_results",
        repository="pull-detail-fixture/alpha",
        pull_request_number=1,
        merge_request_uuid=status,
    )[0]
    assert row["merge_status"] == status
    assert row["merge_commit_sha"] == (pull_detail_api.C if status == "merged" else None)
    assert row["reported_uuid"] == ("pending" if status == "pending" else None)
    assert row["bypass_rules"] == (False if status == "pending" else None)


def test_expired_async_result_is_not_an_unmerged_request(pilot, pull_detail_api, monkeypatch):
    _, contract, _ = pilot
    install(monkeypatch, pull_detail_api.respond)
    with pytest.raises(GitHubError, match="404"):
        rows_for(
            contract,
            "pull_request_merge_results",
            repository="pull-detail-fixture/alpha",
            pull_request_number=1,
            merge_request_uuid="expired",
        )


def test_async_result_rejects_another_pending_request_uuid(pilot, pull_detail_api, monkeypatch):
    _, contract, _ = pilot

    def respond(request):
        response = pull_detail_api.respond(request)
        if request.url.path.endswith("/merge-async/pending"):
            value = response.json()
            value["details"]["uuid"] = "another-request"
            return httpx.Response(200, json=value, headers=response.headers, request=request)
        return response

    install(monkeypatch, respond)
    with pytest.raises(GeneratedContractError, match="row assertion failed"):
        rows_for(
            contract,
            "pull_request_merge_results",
            repository="pull-detail-fixture/alpha",
            pull_request_number=1,
            merge_request_uuid="pending",
        )


def test_stack_list_lookup_and_pr_filter_share_stable_identity(pilot, pull_detail_api, monkeypatch):
    _, contract, _ = pilot
    requests = install(monkeypatch, pull_detail_api.respond)
    rows = rows_for(contract, "pull_request_stacks", organization="pull-detail-fixture")
    assert [(row["repository_id"], row["stack_id"], len(row["pull_requests"])) for row in rows] == [
        (1301, 1701, 2),
        (1302, 1702, 1),
    ]
    assert rows_for(
        contract, "pull_request_stacks", repository="pull-detail-fixture/alpha", stack_number=7
    ) == [rows[0]]
    assert rows_for(
        contract, "pull_request_stacks", repository="pull-detail-fixture/alpha", pull_request_number=1
    ) == [rows[0]]
    assert rows[0]["pull_requests"][0]["head"]["repo"]["id"] == 1301
    assert any(request.url.params.get("pull_request") == "1" for request in requests)


@pytest.mark.parametrize(
    "entity,args",
    [
        ("pull_request_reviews", {"review_id": 1}),
        ("pull_request_review_comments", {"review_comment_id": 1}),
        ("pull_request_review_comments", {"repository": "pull-detail-fixture/alpha", "review_id": 1511}),
        (
            "pull_request_merge_results",
            {"repository": "pull-detail-fixture/alpha", "merge_request_uuid": "pending"},
        ),
        ("pull_request_stacks", {"stack_number": 7}),
    ],
)
def test_invalid_pr_scopes_fail_before_http(pilot, monkeypatch, entity, args):
    _, contract, _ = pilot
    install(monkeypatch, lambda request: pytest.fail("Invalid scope made a request"))
    with pytest.raises(GeneratedContractError):
        rows_for(contract, entity, **args)


@pytest.mark.parametrize(
    "entity,args,suffix,field,bad",
    [
        ("pull_request_reviews", {"pull_request_number": 1, "review_id": 1511}, "/reviews/1511", "id", 1512),
        ("pull_request_review_comments", {"review_comment_id": 1611}, "/comments/1611", "id", 1612),
        ("pull_requests", {"pull_request_number": 1}, "/pulls/1", "number", 2),
        ("pull_request_stacks", {"stack_number": 7}, "/stacks/7", "number", 8),
    ],
)
def test_direct_lookup_identity_mismatch_fails(
    pilot, pull_detail_api, monkeypatch, entity, args, suffix, field, bad
):
    _, contract, _ = pilot

    def respond(request):
        response = pull_detail_api.respond(request)
        if request.url.path.endswith(suffix):
            value = response.json()
            value[field] = bad
            return httpx.Response(200, json=value, headers=response.headers, request=request)
        return response

    install(monkeypatch, respond)
    with pytest.raises(GeneratedContractError, match="row assertion failed"):
        rows_for(contract, entity, repository="pull-detail-fixture/alpha", **args)
