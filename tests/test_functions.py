"""Drive each function's ``process()`` as DuckDB would, against a mock GitHub.

The blended functions receive a batch of input rows — one per driving row of a
LATERAL — and must emit one batch whose ``parent_rows`` maps every output row
back to the input row that produced it. These tests pin that contract, plus
the row caps and argument-to-query translation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import httpx
import pyarrow as pa
import pytest

from tests.helpers import install
from vgi_github import functions as fn
from vgi_github import search
from vgi_github.github_api import GitHubError
from vgi_github.paging import PagedScanState
from vgi_github.reference import RateLimitFunction


@dataclass
class _Params:
    args: Any
    output_schema: pa.Schema
    secrets: Any = None
    attach_opaque_data: bytes | None = None


@dataclass
class _Out:
    batches: list[pa.RecordBatch] = field(default_factory=list)
    parents: list[list[int] | None] = field(default_factory=list)
    cache: list[Any] = field(default_factory=list)
    finished: bool = False

    def emit(self, batch, parent_rows=None, cache_control=None) -> None:
        self.batches.append(batch)
        self.parents.append(parent_rows)
        self.cache.append(cache_control)

    def finish(self) -> None:
        self.finished = True


def _run(func, args, batch: pa.RecordBatch) -> _Out:
    out = _Out()
    func.process(_Params(args=args, output_schema=func.FIXED_SCHEMA), None, batch, out)
    assert len(out.batches) == 1, "a blended function emits exactly once per input batch"
    return out


def _input(**columns: list[Any]) -> pa.RecordBatch:
    return pa.record_batch({k: pa.array(v) for k, v in columns.items()})


def _issue(number: int, *, pr: bool = False, repo: str = "o/r") -> dict[str, Any]:
    row = {
        "number": number,
        "id": number * 10,
        "title": f"t{number}",
        "state": "open",
        "user": {"login": "alice"},
        "labels": [{"name": "bug"}, {"name": "p1"}],
        "assignees": [{"login": "bob"}],
        "reactions": {"total_count": 3, "+1": 2},
        "repository_url": f"https://api.github.com/repos/{repo}",
        "created_at": "2026-01-02T03:04:05Z",
    }
    if pr:
        row["pull_request"] = {"url": "..."}
    return row


class TestLateralProvenance:
    def test_each_input_row_fans_out_with_parent_rows(self, monkeypatch) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            repo = request.url.path.split("/")[3]
            count = {"a": 2, "b": 1}[repo]
            return httpx.Response(200, json=[_issue(i) for i in range(count)])

        install(monkeypatch, handler)
        out = _run(fn.IssuesFunction, fn.IssuesArgs(repo=""), _input(repo=["o/a", "o/b"]))
        assert out.parents[0] == [0, 0, 1]
        assert out.batches[0].column("repo").to_pylist() == ["o/a", "o/a", "o/b"]

    def test_null_inputs_emit_nothing_and_keep_alignment(self, monkeypatch) -> None:
        install(monkeypatch, lambda r: httpx.Response(200, json={"full_name": "o/r", "id": 1}))
        out = _run(fn.RepoFunction, fn.RepoArgs(repo=""), _input(repo=[None, "o/r", None]))
        assert out.parents[0] == [1]

    def test_repeated_keys_are_fetched_once(self, monkeypatch) -> None:
        seen = install(monkeypatch, lambda r: httpx.Response(200, json={"login": "alice", "id": 1}))
        out = _run(fn.UserFunction, fn.LoginArgs(login=""), _input(login=["alice", "alice", "alice"]))
        assert len(seen) == 1
        assert out.parents[0] == [0, 1, 2]

    def test_a_missing_key_yields_no_rows_not_an_error(self, monkeypatch) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if "gone" in request.url.path:
                return httpx.Response(404, json={"message": "Not Found"})
            return httpx.Response(200, json={"full_name": "o/here", "id": 1})

        install(monkeypatch, handler)
        out = _run(fn.RepoFunction, fn.RepoArgs(repo=""), _input(repo=["o/gone", "o/here"]))
        assert out.parents[0] == [1]

    def test_two_column_key(self, monkeypatch) -> None:
        seen = install(monkeypatch, lambda r: httpx.Response(200, json=[{"id": 1, "user": {"login": "z"}}]))
        out = _run(
            fn.IssueCommentsFunction,
            fn.IssueCommentsArgs(repo="", number=0),
            _input(repo=["o/r", "o/r"], number=[5, 6]),
        )
        assert [r.url.path for r in seen] == ["/repos/o/r/issues/5/comments", "/repos/o/r/issues/6/comments"]
        assert out.batches[0].column("issue_number").to_pylist() == [5, 6]

    def test_projection_is_honoured(self, monkeypatch) -> None:
        install(monkeypatch, lambda r: httpx.Response(200, json={"full_name": "o/r", "id": 9}))
        schema = pa.schema([fn.REPO_SCHEMA.field("id")])
        out = _Out()
        fn.RepoFunction.process(
            _Params(args=fn.RepoArgs(repo=""), output_schema=schema), None, _input(repo=["o/r"]), out
        )
        assert out.batches[0].schema.names == ["id"]

    def test_invalid_repository_is_named(self, monkeypatch) -> None:
        install(monkeypatch, lambda r: httpx.Response(200, json={}))
        with pytest.raises(ValueError, match="owner/name"):
            _run(fn.RepoFunction, fn.RepoArgs(repo=""), _input(repo=["not-a-repo"]))


class TestIssues:
    def test_pull_requests_are_dropped_and_not_counted(self, monkeypatch) -> None:
        install(monkeypatch, lambda r: httpx.Response(200, json=[_issue(1, pr=True), _issue(2), _issue(3)]))
        out = _run(fn.IssuesFunction, fn.IssuesArgs(repo="", max_rows=2), _input(repo=["o/r"]))
        batch = out.batches[0]
        assert batch.column("number").to_pylist() == [2, 3]
        assert batch.column("is_pull_request").to_pylist() == [False, False]

    def test_pull_requests_can_be_kept(self, monkeypatch) -> None:
        install(monkeypatch, lambda r: httpx.Response(200, json=[_issue(1, pr=True), _issue(2)]))
        out = _run(
            fn.IssuesFunction, fn.IssuesArgs(repo="", include_pull_requests=True), _input(repo=["o/r"])
        )
        assert out.batches[0].column("is_pull_request").to_pylist() == [True, False]

    def test_arguments_become_query_parameters(self, monkeypatch) -> None:
        seen = install(monkeypatch, lambda r: httpx.Response(200, json=[]))
        args = fn.IssuesArgs(repo="", state="closed", labels="bug,p1", since="2026-01-01")
        _run(fn.IssuesFunction, args, _input(repo=["o/r"]))
        params = seen[0].url.params
        assert params["state"] == "closed"
        assert params["labels"] == "bug,p1"
        assert params["since"] == "2026-01-01T00:00:00Z"

    def test_state_defaults_to_all_not_githubs_open(self, monkeypatch) -> None:
        seen = install(monkeypatch, lambda r: httpx.Response(200, json=[]))
        _run(fn.IssuesFunction, fn.IssuesArgs(repo=""), _input(repo=["o/r"]))
        assert seen[0].url.params["state"] == "all"

    def test_bad_since_is_named(self, monkeypatch) -> None:
        install(monkeypatch, lambda r: httpx.Response(200, json=[]))
        with pytest.raises(ValueError, match="since"):
            _run(fn.IssuesFunction, fn.IssuesArgs(repo="", since="yesterday"), _input(repo=["o/r"]))

    def test_nested_fields_are_flattened(self, monkeypatch) -> None:
        install(monkeypatch, lambda r: httpx.Response(200, json=[_issue(1)]))
        row = _run(fn.IssuesFunction, fn.IssuesArgs(repo=""), _input(repo=["o/r"])).batches[0].to_pylist()[0]
        assert row["user_login"] == "alice"
        assert row["labels"] == ["bug", "p1"]
        assert row["assignees"] == ["bob"]
        assert row["reactions_plus_one"] == 2
        assert row["created_at"].year == 2026


class TestRowCaps:
    def test_default_cap_is_one_full_page(self, monkeypatch) -> None:
        seen = install(monkeypatch, lambda r: httpx.Response(200, json=[]))
        _run(fn.CommitsFunction, fn.CommitsArgs(repo=""), _input(repo=["o/r"]))
        assert seen[0].url.params["per_page"] == "100"

    def test_zero_walks_every_page(self, monkeypatch) -> None:
        pages = iter(
            [
                httpx.Response(
                    200,
                    json=[{"sha": "a"}],
                    headers={"link": '<https://api.github.com/x?page=2>; rel="next"'},
                ),
                httpx.Response(200, json=[{"sha": "b"}]),
            ]
        )
        install(monkeypatch, lambda r: next(pages))
        out = _run(fn.CommitsFunction, fn.CommitsArgs(repo="", max_rows=0), _input(repo=["o/r"]))
        assert out.batches[0].column("sha").to_pylist() == ["a", "b"]


class TestCaching:
    def test_anonymous_public_responses_forward_githubs_ttl(self, monkeypatch) -> None:
        install(
            monkeypatch,
            lambda r: httpx.Response(200, json={}, headers={"cache-control": "public, max-age=60"}),
        )
        out = _run(fn.LanguagesFunction, fn.RepoArgs(repo=""), _input(repo=["o/r"]))
        assert out.cache[0] is not None and out.cache[0].ttl == 60

    def test_private_responses_are_uncached_unless_opted_in(self, monkeypatch) -> None:
        install(
            monkeypatch,
            lambda r: httpx.Response(200, json={}, headers={"cache-control": "private, max-age=60"}),
        )
        assert _run(fn.LanguagesFunction, fn.RepoArgs(repo=""), _input(repo=["o/r"])).cache[0] is None
        out = _run(fn.LanguagesFunction, fn.RepoArgs(repo="", cache_ttl=300), _input(repo=["o/r"]))
        assert out.cache[0].ttl == 300 and out.cache[0].per_value


class TestStargazers:
    def test_star_media_type_and_timestamp(self, monkeypatch) -> None:
        seen = install(
            monkeypatch,
            lambda r: httpx.Response(
                200, json=[{"starred_at": "2020-01-01T00:00:00Z", "user": {"login": "x"}}]
            ),
        )
        out = _run(fn.StargazersFunction, fn.RepoListArgs(repo=""), _input(repo=["o/r"]))
        assert seen[0].headers["Accept"] == "application/vnd.github.star+json"
        assert out.batches[0].column("login").to_pylist() == ["x"]

    def test_refused_listing_is_an_explained_error_not_zero_stars(self, monkeypatch) -> None:
        install(monkeypatch, lambda r: httpx.Response(404, json={"message": "Not Found"}))
        with pytest.raises(GitHubError, match="administer"):
            _run(fn.StargazersFunction, fn.RepoListArgs(repo=""), _input(repo=["big/repo"]))


class TestLanguagesAndActions:
    def test_languages_become_rows_largest_first(self, monkeypatch) -> None:
        install(monkeypatch, lambda r: httpx.Response(200, json={"C": 10, "C++": 90}))
        rows = _run(fn.LanguagesFunction, fn.RepoArgs(repo=""), _input(repo=["o/r"])).batches[0].to_pylist()
        assert [(r["language"], r["bytes"]) for r in rows] == [("C++", 90), ("C", 10)]

    def test_workflow_runs_unwrap_and_filter_at_source(self, monkeypatch) -> None:
        seen = install(
            monkeypatch,
            lambda r: httpx.Response(
                200, json={"total_count": 1, "workflow_runs": [{"id": 1, "conclusion": "failure"}]}
            ),
        )
        args = fn.WorkflowRunsArgs(repo="", branch="main", status="failure")
        out = _run(fn.WorkflowRunsFunction, args, _input(repo=["o/r"]))
        assert seen[0].url.params["branch"] == "main" and seen[0].url.params["status"] == "failure"
        assert out.batches[0].column("conclusion").to_pylist() == ["failure"]


class TestSearchScan:
    def test_streams_one_page_per_tick(self, monkeypatch) -> None:
        pages = iter(
            [
                httpx.Response(
                    200,
                    json={"items": [{"full_name": "a/b"}]},
                    headers={"link": '<https://api.github.com/search/repositories?q=x&page=2>; rel="next"'},
                ),
                httpx.Response(200, json={"items": [{"full_name": "c/d"}]}),
            ]
        )
        seen = install(monkeypatch, lambda r: next(pages))
        func = search.SearchRepositoriesFunction
        params = _Params(
            args=search.SearchRepositoriesArgs(query="x", sort="stars"), output_schema=func.FIXED_SCHEMA
        )
        state = PagedScanState()
        out = _Out()
        func.process(params, state, out)
        assert len(seen) == 1 and not state.done, "the first tick must not fetch the second page"
        assert seen[0].url.params["q"] == "x" and seen[0].url.params["sort"] == "stars"
        func.process(params, state, out)
        assert state.done
        func.process(params, state, out)
        assert out.finished
        assert [b.column("full_name").to_pylist() for b in out.batches] == [["a/b"], ["c/d"]]

    def test_stops_at_the_thousand_result_cap(self, monkeypatch) -> None:
        """Page 11 is a 422, not an empty page, so the scan must stop itself."""
        install(
            monkeypatch,
            lambda r: httpx.Response(
                200,
                json={"items": [{"number": 1}] * 100},
                headers={"link": '<https://api.github.com/search/issues?page=n>; rel="next"'},
            ),
        )
        func = search.SearchIssuesFunction
        params = _Params(args=search.SearchIssuesArgs(query="x"), output_schema=func.FIXED_SCHEMA)
        state, out, ticks = PagedScanState(), _Out(), 0
        while not state.done:
            func.process(params, state, out)
            ticks += 1
        assert ticks == 10

    def test_search_issues_derives_repo(self, monkeypatch) -> None:
        install(monkeypatch, lambda r: httpx.Response(200, json={"items": [_issue(1, repo="x/y")]}))
        func = search.SearchIssuesFunction
        out = _Out()
        func.process(
            _Params(args=search.SearchIssuesArgs(query="q"), output_schema=func.FIXED_SCHEMA),
            PagedScanState(),
            out,
        )
        assert out.batches[0].column("repo").to_pylist() == ["x/y"]


class TestRateLimitTable:
    def test_one_row_per_budget_with_auth_flag(self, monkeypatch) -> None:
        monkeypatch.delenv("VGI_GITHUB_TOKEN", raising=False)
        install(
            monkeypatch,
            lambda r: httpx.Response(
                200,
                json={"resources": {"core": {"limit": 60, "used": 1, "remaining": 59, "reset": 1790000000}}},
            ),
        )
        out = _Out()
        RateLimitFunction.process(_Params(args=None, output_schema=RateLimitFunction.FIXED_SCHEMA), None, out)
        row = out.batches[0].to_pylist()[0]
        assert row["resource"] == "core" and row["request_limit"] == 60 and row["authenticated"] is False
        assert out.finished
