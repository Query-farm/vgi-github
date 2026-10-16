"""Search observations keep complete query populations and canonical subject identity."""

import json
from copy import deepcopy

import httpx
import pytest

from tests.helpers import install
from tests.test_generated_runtime import run
from tests.test_generation_artifacts import ROOT
from tests.test_generation_artifacts import pilot as pilot
from vgi_github.auth import Credentials
from vgi_github.generated_runtime import GeneratedContractError, _page
from vgi_github.github_api import GitHubError


@pytest.fixture
def search(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "tests/crossfield"))
    import search_fixture

    return search_fixture


def rows_for(contract, name, **arguments):
    entity = next(value for value in contract["functions"] if value["name"] == name)
    output = run(entity, {key: [value] for key, value in arguments.items()}, contract=contract)
    return [row for batch in output.batches for row in batch.to_pylist()]


def test_all_seven_search_operations_are_query_qualified_hit_entities():
    domain = json.loads((ROOT / "generation/domains/search.json").read_text())
    assert {
        source["transport"]["operation_id"]
        for source in domain["entities"]
        if source["transport"]["kind"] == "rest"
    } == {
        "search/code",
        "search/commits",
        "search/issues-and-pull-requests",
        "search/labels",
        "search/repos",
        "search/topics",
        "search/users",
    }
    assert {entity["name"] for entity in domain["functions"]} == {
        "search_code_hits",
        "search_commit_hits",
        "search_issue_hits",
        "search_label_hits",
        "search_repository_hits",
        "search_topic_hits",
        "search_account_hits",
    }
    assert all(entity["grain"][0] == "search_query" for entity in domain["functions"])
    assert len(domain["relationships"]) == 11
    account = next(source for source in domain["entities"] if source["name"] == "search_account_hits_source")
    assert account["transport"]["authentication"] == "anonymous"


@pytest.mark.parametrize(
    "name,extra,count",
    [
        ("search_code_hits", {}, 2),
        ("search_commit_hits", {}, 2),
        ("search_issue_hits", {}, 2),
        ("search_label_hits", {"organization": "search-fixture"}, 3),
        ("search_repository_hits", {}, 2),
        ("search_topic_hits", {}, 2),
        ("search_account_hits", {}, 2),
    ],
)
def test_search_counts_follow_every_advertised_page(pilot, search, monkeypatch, name, extra, count):
    _, contract, _ = pilot
    requests = install(monkeypatch, search.respond)
    rows = rows_for(contract, name, search_query="fixture", **extra)
    assert len(rows) == count
    assert {row["search_query"] for row in rows} == {"fixture"}
    assert all(row["incomplete_results"] is False for row in rows)
    assert any(request.url.params.get("page") == "2" for request in requests)
    if name != "search_label_hits":
        assert [row["result_position"] for row in rows] == [1, 2]
        assert [row["reported_total_count"] for row in rows] == [2, 2]
    else:
        assert [
            (row["repository_id"], row["label_id"], row["reported_total_count"], row["result_position"])
            for row in rows
        ] == [(8101, 9201, 2, 1), (8101, 9202, 2, 2), (8102, 9203, 1, 1)]
    assert rows_for(contract, name, search_query="empty", **extra) == []


def test_transferred_issue_and_mixed_pr_hits_use_current_node_identity(pilot, search, monkeypatch):
    _, contract, _ = pilot
    requests = install(monkeypatch, search.respond)
    rows = rows_for(
        contract,
        "search_issue_hits",
        search_query="fixture",
        issue_search_type="hybrid",
        issue_advanced_search="true",
    )
    assert [
        (
            row["node_id"],
            row["subject_kind"],
            row["repository_id"],
            row["repository"],
            row["indexed_number"],
            row["number"],
        )
        for row in rows
    ] == [
        ("SEARCH_I1", "Issue", 8102, "search-fixture/beta", 3, 8),
        ("SEARCH_PR1", "PullRequest", 8101, "search-fixture/alpha", 9, 9),
    ]
    assert all(
        row["issue_search_type"] == "hybrid"
        and row["performed_search_type"] == "lexical"
        and row["lexical_fallback_reason"] == ["service_unavailable"]
        for row in rows
    )
    assert rows[0]["issue_field_values"][0]["data_type"] == "number"
    graph_requests = [request for request in requests if request.url.path == "/graphql"]
    assert len(graph_requests) == 2
    assert "_vgi_Issue_number" in json.loads(graph_requests[0].content)["query"]
    assert "_vgi_PullRequest_number" in json.loads(graph_requests[1].content)["query"]
    assert all(request.url.host == "api.github.com" for request in requests)


def test_typed_nested_search_fields_and_relevance_are_not_resource_totals(pilot, search, monkeypatch):
    _, contract, _ = pilot
    install(monkeypatch, search.respond)
    code = rows_for(contract, "search_code_hits", search_query="fixture")
    assert [row["score"] for row in code] == [2.5, 1.5]
    assert code[0]["line_numbers"] == ["1..2"]
    assert code[0]["text_matches"][0]["matches"][0]["indices"] == [0, 7]
    commits = rows_for(contract, "search_commit_hits", search_query="fixture")
    assert commits[1]["author_account"] is None
    assert commits[0]["committer_signature"]["name"] == "Committer"
    assert commits[0]["commit"]["author"]["name"] == "Git author"
    assert commits[0]["commit"]["committer"] is None
    topics = rows_for(contract, "search_topic_hits", search_query="fixture")
    assert topics[0]["released"] == "sometime in 2020"
    assert topics[0]["related"][0]["topic_relation"]["name"] == "other"
    accounts = rows_for(contract, "search_account_hits", search_query="fixture")
    assert [row["account_type"] for row in accounts] == ["User", "Organization"]


def test_anonymous_account_search_never_forwards_configured_credential(pilot, search, monkeypatch):
    _, contract, _ = pilot
    requests = install(monkeypatch, search.respond)
    source = next(source for source in contract["entities"] if source["name"] == "search_account_hits_source")
    arguments = {"search_query": "fixture", "search_users_sort": None, "search_order": None}
    cursor = {}
    _page(source, arguments, Credentials("fixture-secret"), cursor)
    _page(source, arguments, Credentials("fixture-secret"), cursor)
    assert len(requests) == 2
    assert all("authorization" not in request.headers for request in requests)


def test_sort_bindings_and_invalid_enum_reject_before_search_http(pilot, search, monkeypatch):
    _, contract, _ = pilot
    requests = install(monkeypatch, search.respond)
    rows_for(
        contract,
        "search_repository_hits",
        search_query="fixture",
        search_repositories_sort="stars",
        search_order="asc",
    )
    assert all(
        request.url.params["sort"] == "stars" and request.url.params["order"] == "asc" for request in requests
    )
    requests.clear()
    with pytest.raises(GeneratedContractError, match="enum|allowed"):
        rows_for(contract, "search_repository_hits", search_query="fixture", search_repositories_sort="score")
    assert requests == []


@pytest.mark.parametrize(
    "failure", ["incomplete", "capped", "changed", "duplicate", "invalid_nested", "later_error"]
)
def test_search_refuses_partial_or_invalid_populations(pilot, search, monkeypatch, failure):
    _, contract, _ = pilot

    def handler(request):
        response = search.respond(request)
        if request.url.path != "/search/code":
            return response
        later = request.url.params.get("page") == "2"
        if failure == "later_error" and later:
            return httpx.Response(403, json={"message": "Forbidden"})
        value = response.json()
        if failure == "incomplete":
            value["incomplete_results"] = True
        elif failure == "capped":
            value["total_count"] = 1001
        elif failure == "changed" and later:
            value["total_count"] = 3
        elif failure == "duplicate" and later:
            value["items"] = [deepcopy(search.CODE[0])]
        elif failure == "invalid_nested":
            value["items"][0]["text_matches"][0]["matches"][0]["indices"] = ["0", "7"]
        return httpx.Response(200, json=value, headers=response.headers)

    install(monkeypatch, handler)
    with pytest.raises((GeneratedContractError, GitHubError)):
        rows_for(contract, "search_code_hits", search_query="fixture")


def test_null_discovered_node_does_not_silently_shrink_search_hits(pilot, search, monkeypatch):
    _, contract, _ = pilot

    def handler(request):
        if request.url.path == "/graphql":
            return httpx.Response(200, json={"data": {"node": None}})
        return search.respond(request)

    install(monkeypatch, handler)
    with pytest.raises(GeneratedContractError, match="exactly one row"):
        rows_for(contract, "search_issue_hits", search_query="fixture")
