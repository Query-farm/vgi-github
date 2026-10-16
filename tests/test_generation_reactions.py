"""One reaction grain across subject APIs with explicit parent roles and unknown reactors."""

import json
from copy import deepcopy

import httpx
import pytest

from tests.helpers import install
from tests.test_generated_runtime import run
from tests.test_generation_artifacts import ROOT
from tests.test_generation_artifacts import pilot as pilot
from vgi_github.generated_runtime import GeneratedContractError


@pytest.fixture
def reactions(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "tests/crossfield"))
    import reactions_fixture

    return reactions_fixture


def rows_for(contract, **arguments):
    entity = next(f for f in contract["functions"] if f["name"] == "reactions")
    output = run(entity, {k: [v] for k, v in arguments.items()}, contract=contract)
    return [row for batch in output.batches for row in batch.to_pylist()]


@pytest.mark.parametrize(
    "arguments,kind,subject_id,identities",
    [
        ({"issue_number": 1}, "issue_thread", 5101, [9001, 9002, 9003, 9004, 9005]),
        ({"issue_number": 2}, "issue_thread", 5102, [9010]),
        ({"issue_number": 3}, "issue_thread", 5103, []),
        ({"issue_comment_id": 5_000_000_501}, "issue_comment", 5_000_000_501, [9021, 9022]),
        ({"review_comment_id": 701}, "pull_request_review_comment", 701, [9031, 9032, 9033]),
        ({"commit_comment_id": 701}, "commit_comment", 701, [9041, 9042]),
        ({"release_id": 701}, "release", 701, [9051, 9052, 9053]),
    ],
)
def test_subject_routes_share_reaction_fields_and_grain(
    pilot, reactions, monkeypatch, arguments, kind, subject_id, identities
):
    _, contract, _ = pilot
    requests = install(monkeypatch, reactions.respond)
    rows = rows_for(contract, repository="reaction-fixture/alpha", **arguments)
    assert [r["reaction_id"] for r in rows] == identities
    assert all(
        (r["subject_kind"], r["subject_id"], r["repository_id"]) == (kind, subject_id, 1501) for r in rows
    )
    assert len([r for r in requests if r.url.path.endswith("/reactions")]) == max(len(identities), 1)


def test_thread_parent_kind_uses_object_presence_even_when_all_urls_are_null(pilot, reactions, monkeypatch):
    _, contract, _ = pilot
    subject = deepcopy(reactions.SUBJECTS["issues/2"])
    subject["pull_request"] = {"url": None, "diff_url": None, "html_url": None, "patch_url": None}
    monkeypatch.setitem(reactions.SUBJECTS, "issues/2", subject)
    install(monkeypatch, reactions.respond)
    issue = rows_for(contract, repository="reaction-fixture/alpha", issue_number=1)[0]
    pull = rows_for(contract, repository="reaction-fixture/alpha", issue_number=2)[0]
    assert issue["subject_pull_request"] is None
    assert pull["subject_pull_request"] == {
        "url": None,
        "diff_url": None,
        "html_url": None,
        "patch_url": None,
        "merged_at": None,
    }
    relations = {r["name"]: r for r in contract["relationships"]}
    issue_navigation = next(
        r for r in relations["reactions_to_issues"]["retrievals"] if r["direction"] == "forward"
    )
    pull_navigation = next(
        r for r in relations["reactions_to_pull_requests"]["retrievals"] if r["direction"] == "forward"
    )
    assert issue_navigation["when_null"] == ["subject_pull_request"]
    assert "subject_pull_request" in pull_navigation["when_not_null"]
    assert issue_navigation["when"] == pull_navigation["when"] == {"subject_kind": "issue_thread"}


@pytest.mark.parametrize(
    "numeric,node,identity",
    [
        ("issue_comment_id", "reaction_issue_comment_node_id", "RIC5000000501"),
        ("commit_comment_id", "reaction_commit_comment_node_id", "RCC701"),
    ],
)
def test_comment_node_reverse_routes_match_direct_numeric_routes(
    pilot, reactions, monkeypatch, numeric, node, identity
):
    _, contract, _ = pilot
    install(monkeypatch, reactions.respond)
    direct = rows_for(
        contract,
        repository="reaction-fixture/alpha",
        **{numeric: 5_000_000_501 if numeric == "issue_comment_id" else 701},
    )
    reverse = rows_for(contract, **{node: identity})
    assert direct == reverse
    assert reverse[0]["subject_node_id"] == identity
    assert reverse[0]["repository"] == "reaction-fixture/alpha"


def test_large_comment_id_survives_graphql_string_wire_and_multi_page_continuations(
    pilot, reactions, monkeypatch
):
    _, contract, _ = pilot
    requests = install(monkeypatch, reactions.respond)
    rows = rows_for(contract, reaction_issue_comment_node_id="RIC5000000501")
    assert [r["subject_id"] for r in rows] == [5_000_000_501, 5_000_000_501]
    assert all(r["subject_issue_comment_id"] == 5_000_000_501 for r in rows)
    assert sum(r.url.path.endswith("/5000000501/reactions") for r in requests) == 2
    assert b"fullDatabaseId" in requests[0].content


def test_subject_role_ids_do_not_collide_across_equal_numeric_namespaces(pilot, reactions, monkeypatch):
    _, contract, _ = pilot
    install(monkeypatch, reactions.respond)
    for arg, role in [
        ("review_comment_id", "subject_review_comment_id"),
        ("commit_comment_id", "subject_commit_comment_id"),
        ("release_id", "subject_release_id"),
    ]:
        row = rows_for(contract, repository="reaction-fixture/alpha", **{arg: 701})[0]
        assert row["subject_id"] == row[role] == 701
        assert all(
            row[other] is None
            for other in [
                "subject_number",
                "subject_issue_comment_id",
                "subject_review_comment_id",
                "subject_commit_comment_id",
                "subject_release_id",
            ]
            if other != role
        )


def test_reactor_role_is_not_parent_author_and_null_actor_remains_reaction(pilot, reactions, monkeypatch):
    _, contract, _ = pilot
    install(monkeypatch, reactions.respond)
    rows = rows_for(contract, repository="reaction-fixture/alpha", issue_number=1)
    assert len(rows) == 5 and {r["reactor_id"] for r in rows} == {1601, 1602, None}
    assert rows[0]["reactor"]["site_admin"] is False
    assert rows[0]["reactor"]["user_view_type"] == "public"
    assert rows[0]["reactor"]["email"] is None
    assert rows[3]["reactor"] is None and rows[3]["reactor_login"] is None
    assert all(r["reactor_id"] not in [1698, 1699] for r in rows)
    bot = rows_for(contract, repository="reaction-fixture/alpha", issue_number=2)[0]
    assert bot["reactor_type"] == "Bot"
    assert bot["subject_number"] == 2 and bot["subject_id"] == 5102


def test_reaction_filter_survives_link_pages_and_preserves_literal_plus(pilot, reactions, monkeypatch):
    _, contract, _ = pilot
    requests = install(monkeypatch, reactions.respond)
    rows = rows_for(contract, repository="reaction-fixture/alpha", issue_number=1, reaction_content="+1")
    assert [r["reaction_id"] for r in rows] == [9001, 9005]
    pages = [r for r in requests if r.url.path.endswith("/reactions")]
    assert len(pages) == 2 and all(r.url.params["content"] == "+1" for r in pages)
    assert all(b"%2B1" in r.url.query for r in pages)


@pytest.mark.parametrize("content,ids", [("-1", [9033]), ("confused", [9031]), ("heart", [])])
def test_comment_filters_retain_full_pinned_reaction_vocabulary(pilot, reactions, monkeypatch, content, ids):
    _, contract, _ = pilot
    install(monkeypatch, reactions.respond)
    rows = rows_for(
        contract, repository="reaction-fixture/alpha", review_comment_id=701, reaction_content=content
    )
    assert [r["reaction_id"] for r in rows] == ids


def test_release_rejects_symbols_not_supported_by_pinned_release_operation(pilot, reactions, monkeypatch):
    _, contract, _ = pilot
    requests = install(monkeypatch, reactions.respond)
    with pytest.raises(GeneratedContractError, match="enum"):
        rows_for(contract, repository="reaction-fixture/alpha", release_id=701, reaction_content="-1")
    assert not any(r.url.path.endswith("/reactions") for r in requests)


@pytest.mark.parametrize(
    "argument", ["issue_number", "issue_comment_id", "review_comment_id", "commit_comment_id", "release_id"]
)
def test_invalid_parent_id_rejects_before_http(pilot, reactions, monkeypatch, argument):
    _, contract, _ = pilot
    requests = install(monkeypatch, reactions.respond)
    with pytest.raises(GeneratedContractError, match="minimum|positive|at least"):
        rows_for(contract, repository="reaction-fixture/alpha", **{argument: 0})
    assert requests == []


def test_incompatible_subjects_reject_before_http(pilot, reactions, monkeypatch):
    _, contract, _ = pilot
    requests = install(monkeypatch, reactions.respond)
    with pytest.raises(GeneratedContractError, match="argument|route|consume"):
        rows_for(contract, repository="reaction-fixture/alpha", issue_number=1, release_id=701)
    assert requests == []


def test_missing_legacy_commit_database_id_fails_instead_of_empty_reactions(pilot, reactions, monkeypatch):
    _, contract, _ = pilot

    def respond(request):
        result = reactions.respond(request)
        if request.url.path == "/graphql":
            payload = result.json()
            payload["data"]["node"]["databaseId"] = None
            return httpx.Response(200, json=payload, request=request)
        return result

    requests = install(monkeypatch, respond)
    with pytest.raises(GeneratedContractError, match="required|NULL|non.null"):
        rows_for(contract, reaction_commit_comment_node_id="RCC701")
    assert len(requests) == 1


def test_mismatched_parent_identity_is_rejected(pilot, reactions, monkeypatch):
    _, contract, _ = pilot

    def respond(request):
        result = reactions.respond(request)
        if request.url.path.endswith("/comments/701"):
            payload = result.json()
            payload["id"] = 702
            return httpx.Response(200, json=payload, request=request)
        return result

    install(monkeypatch, respond)
    with pytest.raises(GeneratedContractError, match="row assertion"):
        rows_for(contract, repository="reaction-fixture/alpha", commit_comment_id=701)


@pytest.mark.parametrize(
    "failure,error",
    [
        ("missing_identity", "missing required field"),
        ("wrong_content_type", "invalid VARCHAR value"),
        ("missing_required_user", "missing required field"),
    ],
)
def test_invalid_reaction_payload_does_not_become_partial_metric_population(
    pilot, reactions, monkeypatch, failure, error
):
    _, contract, _ = pilot

    def respond(request):
        result = reactions.respond(request)
        if request.url.path.endswith("/issues/1/reactions"):
            payload = result.json()
            if failure == "missing_identity":
                payload[0].pop("id")
            elif failure == "wrong_content_type":
                payload[0]["content"] = 1
            else:
                payload[0].pop("user")
            return httpx.Response(200, json=payload, headers=result.headers, request=request)
        return result

    install(monkeypatch, respond)
    with pytest.raises(GeneratedContractError, match=error):
        rows_for(contract, repository="reaction-fixture/alpha", issue_number=1)


def test_later_page_http_failure_never_reports_complete_collection(pilot, reactions, monkeypatch):
    _, contract, _ = pilot

    def respond(request):
        if request.url.path.endswith("/reactions") and request.url.params.get("page") == "2":
            return httpx.Response(403, json={"message": "Reaction page denied"}, request=request)
        return reactions.respond(request)

    install(monkeypatch, respond)
    with pytest.raises(Exception, match="403|denied"):
        rows_for(contract, repository="reaction-fixture/alpha", issue_number=1)


def test_one_canonical_entity_covers_all_five_get_routes_and_reverse_parent_roles():
    domain = json.loads((ROOT / "generation/domains/reactions.json").read_text())
    assert [f["name"] for f in domain["functions"]] == ["reactions"]
    assert domain["functions"][0]["grain"] == ["repository_id", "reaction_id"]
    operations = {e["transport"].get("operation_id") for e in domain["entities"]}
    assert {o for o in operations if o and o.startswith("reactions/")} == {
        "reactions/list-for-issue",
        "reactions/list-for-issue-comment",
        "reactions/list-for-pull-request-review-comment",
        "reactions/list-for-commit-comment",
        "reactions/list-for-release",
    }
    by_target = {r["to"]: r for r in domain["relationships"]}
    for parent in [
        "issues",
        "pull_requests",
        "issue_comments",
        "pull_request_review_comments",
        "commit_comments",
        "releases",
    ]:
        assert any(r["direction"] == "reverse" for r in by_target[parent]["retrievals"])
        assert by_target[parent]["analytical"] is False
