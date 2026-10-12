"""Complete reporting reads fail before malformed/truncated data becomes an aggregate."""

from __future__ import annotations

from types import SimpleNamespace

import httpx
import pyarrow as pa
import pytest

from tests.helpers import install
from tests.test_functions import _input, _Out, _Params
from vgi_github import auth, reporting
from vgi_github import functions as fn
from vgi_github import github_api as api
from vgi_github.caching import result_cache_control
from vgi_github.paging import PagedScanState, emit_search_page
from vgi_github.schemas import flatten_repo
from vgi_github.worker import GitHubCatalog

REPORTING = auth.encode_attach("off", "", reporting=True, operation_timeout_seconds=120)


def pull(index=1, **changes):
    return {
        "id": index * 10,
        "number": index,
        "state": "closed",
        "draft": False,
        "created_at": "2026-01-01T00:00:00Z",
        "closed_at": "2026-01-01T02:00:00Z",
        "merged_at": "2026-01-01T02:00:00Z",
        "labels": [{"name": "bug"}],
        **changes,
    }


def run_pulls(monkeypatch, payload, *, max_rows=0, output=None):
    install(monkeypatch, lambda r: httpx.Response(200, json=payload))
    out = _Out()
    fn.PullsFunction.process(
        _Params(
            fn.PullsArgs(repo="", max_rows=max_rows), output or fn.PULL_SCHEMA, attach_opaque_data=REPORTING
        ),
        None,
        _input(repo=["o/r"]),
        out,
    )
    return out


class TestReportingAttach:
    def test_policy_and_origin_are_discoverable(self):
        result = GitHubCatalog().catalog_attach(
            name="github",
            options={"reporting": True, "operation_timeout_seconds": 17},
            data_version_spec=None,
            implementation_version=None,
        )
        assert auth.reporting_of(result.attach_opaque_data)
        assert auth.operation_timeout_of(result.attach_opaque_data) == 17
        assert result.tags["vgi_github_reporting"] == "true"
        assert result.tags["vgi_github_operation_timeout_seconds"] == "17"
        assert result.tags["vgi_github_api_origin"] == api.base_url()

    @pytest.mark.parametrize("value", ["true", 1, None])
    def test_reporting_is_boolean(self, value):
        with pytest.raises(ValueError, match="reporting must be a boolean"):
            GitHubCatalog().catalog_attach(name="github", options={"reporting": value})

    @pytest.mark.parametrize("value", [0, -1, 3601, True, "120", 1.5])
    def test_deadline_is_finite_bounded_integer(self, value):
        with pytest.raises(ValueError, match="operation_timeout_seconds"):
            GitHubCatalog().catalog_attach(name="github", options={"operation_timeout_seconds": value})

    def test_bind_identity_nullability_does_not_request_data(self, monkeypatch):
        seen = install(monkeypatch, lambda r: pytest.fail("bind must not fetch data"))
        bound = fn.PullsFunction.on_bind(SimpleNamespace(attach_opaque_data=REPORTING))
        assert not bound.output_schema.field("id").nullable
        assert not bound.output_schema.field("repo").nullable
        assert bound.output_schema.field("labels").type == pa.list_(pa.string())
        assert fn.PULL_SCHEMA.field("id").nullable
        assert seen == []


class TestReportingCompleteness:
    def test_follows_all_pages_including_empty_page_with_next_link(self, monkeypatch):
        base = api.base_url()
        pages = iter(
            [
                httpx.Response(200, json=[pull(1)], headers={"link": f'<{base}/next>; rel="next"'}),
                httpx.Response(200, json=[], headers={"link": f'<{base}/last>; rel="next"'}),
                httpx.Response(200, json=[pull(2)]),
            ]
        )
        seen = install(monkeypatch, lambda r: next(pages))
        out = _Out()
        fn.PullsFunction.process(
            _Params(fn.PullsArgs(repo="", max_rows=0), fn.PULL_SCHEMA, attach_opaque_data=REPORTING),
            None,
            _input(repo=["o/r"]),
            out,
        )
        assert out.batches[0].column("number").to_pylist() == [1, 2]
        assert len(seen) == 3
        assert out.cache[0].no_store

    def test_nonzero_cap_is_rejected_before_any_fetch(self, monkeypatch):
        with pytest.raises(api.GitHubReportingError, match="max_rows => 0"):
            run_pulls(monkeypatch, [], max_rows=1)

    @pytest.mark.parametrize("status", [401, 403, 404, 409, 410, 451])
    def test_missing_or_inaccessible_is_never_zero(self, monkeypatch, status):
        install(monkeypatch, lambda r: httpx.Response(status, json={"message": "Not Found"}))
        with api.reporting_operation(REPORTING):
            with pytest.raises(api.GitHubError):
                api.collect("/repos/o/r/pulls")
            with pytest.raises(api.GitHubError):
                api.lookup("/repos/o/r")

    def test_only_explicit_empty_commit_repository_is_empty(self, monkeypatch):
        install(monkeypatch, lambda r: httpx.Response(409, json={"message": "Git Repository is empty."}))
        with api.reporting_operation(REPORTING):
            assert api.collect("/repos/o/r/commits") == []
            with pytest.raises(api.GitHubError):
                api.collect("/repos/o/r/pulls")

    @pytest.mark.parametrize("payload", [None, {}, [None], ["oops"]])
    def test_malformed_payload_never_becomes_zero(self, monkeypatch, payload):
        with pytest.raises(api.GitHubReportingError):
            run_pulls(monkeypatch, payload)

    def test_page_limit_still_errors(self, monkeypatch):
        monkeypatch.setattr(api, "MAX_PAGES", 1)
        install(
            monkeypatch,
            lambda r: httpx.Response(
                200, json=[pull()], headers={"link": f'<{api.base_url()}/next>; rel="next"'}
            ),
        )
        with api.reporting_operation(REPORTING), pytest.raises(api.GitHubPageLimitError):
            api.collect("/repos/o/r/pulls")

    def test_workflow_endpoint_truncation_errors(self, monkeypatch):
        install(
            monkeypatch,
            lambda r: httpx.Response(200, json={"total_count": 1001, "workflow_runs": [{"id": 1}]}),
        )
        with api.reporting_operation(REPORTING), pytest.raises(api.GitHubReportingError, match="total_count"):
            api.collect("/repos/o/r/actions/runs", key="workflow_runs")

    def test_reported_cache_policy_never_serves_stale(self):
        hint = api.CacheHint(max_age=60)
        assert result_cache_control(hint, 1000, REPORTING).no_store
        assert result_cache_control(hint, 0, REPORTING).stale_if_error is None
        assert result_cache_control(hint, 1000, None).stale_if_error == api.STALE_IF_ERROR


class TestReportingValidation:
    @pytest.mark.parametrize(
        "changes",
        [
            {"id": None},
            {"id": 1.5},
            {"id": True},
            {"id": 0},
            {"number": None},
            {"created_at": None},
            {"created_at": "yesterday"},
            {"created_at": "2026-01-01T00:00:00"},
            {"merged_at": "bad"},
            {"merged_at": "2025-12-01T00:00:00Z"},
            {"closed_at": None},
            {"state": "open"},
        ],
    )
    def test_bad_identity_or_duration_rejected_even_if_projected_away(self, monkeypatch, changes):
        with pytest.raises(api.GitHubReportingError):
            run_pulls(monkeypatch, [pull(**changes)], output=pa.schema([fn.PULL_SCHEMA.field("labels")]))

    def test_missing_merge_evidence_is_not_unmerged(self, monkeypatch):
        row = pull()
        del row["merged_at"]
        with pytest.raises(api.GitHubReportingError, match="missing merged_at"):
            run_pulls(monkeypatch, [row])

    def test_duplicate_ids_error_before_output(self, monkeypatch):
        with pytest.raises(api.GitHubReportingError, match="duplicate id"):
            run_pulls(monkeypatch, [pull(1), pull(2, id=10)])

    def test_nullable_unmerged_timestamp_and_list_details_survive(self, monkeypatch):
        out = run_pulls(monkeypatch, [pull(1, merged_at=None), pull(2)])
        assert out.batches[0].column("merged_at").null_count == 1
        assert out.batches[0].column("labels").to_pylist() == [["bug"], ["bug"]]


class TestReportingDeadline:
    def test_retry_wait_larger_than_remaining_budget_fails_without_sleep(self, monkeypatch):
        install(monkeypatch, lambda r: httpx.Response(429, json={}, headers={"retry-after": "3"}))
        waits = []
        monkeypatch.setattr(api.time, "sleep", waits.append)
        with (
            api.reporting_operation(
                auth.encode_attach("off", "", reporting=True, operation_timeout_seconds=1)
            ),
            pytest.raises(api.GitHubDeadlineError, match="retry wait"),
        ):
            api._get("/x")
        assert waits == []

    def test_late_success_is_rejected_and_request_timeout_is_clamped(self, monkeypatch):
        clock = [10.0]
        monkeypatch.setattr(api.time, "monotonic", lambda: clock[0])

        def handler(request):
            assert request.extensions["timeout"]["read"] == 5.0
            clock[0] += 6
            return httpx.Response(200, json=[])

        install(monkeypatch, handler)
        with pytest.raises(api.GitHubDeadlineError), api.reporting_operation(REPORTING, deadline=15):
            api.collect("/x")
        assert not api.reporting_enabled()

    def test_operation_deadline_is_shared_across_pages(self, monkeypatch):
        clock = [10.0]
        monkeypatch.setattr(api.time, "monotonic", lambda: clock[0])

        def handler(request):
            clock[0] += 3
            return httpx.Response(
                200, json=[{"id": 1}], headers={"link": f'<{api.base_url()}/next>; rel="next"'}
            )

        seen = install(monkeypatch, handler)
        with pytest.raises(api.GitHubDeadlineError), api.reporting_operation(REPORTING, deadline=15):
            api.collect("/x")
        assert len(seen) == 2

    def test_search_is_capped_discovery_with_no_store(self, monkeypatch):
        install(
            monkeypatch,
            lambda r: httpx.Response(
                200,
                json={
                    "total_count": 10000,
                    "incomplete_results": True,
                    "items": [{"id": 1, "full_name": "o/r"}],
                },
            ),
        )
        out = _Out()
        state = PagedScanState()
        emit_search_page(
            _Params(SimpleNamespace(cache_ttl=None), fn.REPO_SCHEMA, attach_opaque_data=REPORTING),
            state,
            out,
            path="/search/repositories",
            query={"q": "duckdb"},
            flatten=flatten_repo,
        )
        assert out.cache[0].no_store
        assert state.deadline > 0
        assert out.batches[0].num_rows == 1


class TestReportingMeasures:
    @pytest.mark.parametrize("value", [None, -1, 1.5, True, "5", 2**63])
    def test_raw_release_download_counts_are_not_repaired(self, value):
        with api.reporting_operation(REPORTING), pytest.raises(api.GitHubReportingError):
            reporting.validate_release_payloads([{"assets": [{"download_count": value}]}])

    @pytest.mark.parametrize("value", [None, {}, [None]])
    def test_missing_or_malformed_assets_are_not_an_empty_release(self, value):
        with api.reporting_operation(REPORTING), pytest.raises(api.GitHubReportingError):
            reporting.validate_release_payloads([{"assets": value}])

    def test_release_and_language_zero_counts_are_valid(self):
        with api.reporting_operation(REPORTING):
            reporting.validate_release_payloads([{"assets": []}, {"assets": [{"download_count": 0}]}])
            reporting.validate_languages({"Python": 0})

    @pytest.mark.parametrize("value", [None, -1, 1.5, True, "5"])
    def test_language_bytes_are_not_coerced(self, value):
        with api.reporting_operation(REPORTING), pytest.raises(api.GitHubReportingError):
            reporting.validate_languages({"Python": value})

    @pytest.mark.parametrize(
        "name, row",
        [
            ("contributors", {"repo": "o/r", "id": 1, "contributions": None}),
            ("repo", {"id": 1, "full_name": "o/r", "stargazers_count": None, "forks_count": 3}),
            ("repos", {"id": 1, "full_name": "o/r", "stargazers_count": 2, "forks_count": -1}),
        ],
    )
    def test_required_metric_counters_cannot_be_null_or_negative(self, name, row):
        with api.reporting_operation(REPORTING), pytest.raises(api.GitHubReportingError):
            reporting.validate_rows(name, [row])

    def test_negative_issue_closure_duration_is_rejected(self):
        row = {"repo": "o/r", **pull(closed_at="2025-12-01T00:00:00Z")}
        with (
            api.reporting_operation(REPORTING),
            pytest.raises(api.GitHubReportingError, match="negative closure"),
        ):
            reporting.validate_rows("issues", [row])


class TestReportingCohortFields:
    @pytest.mark.parametrize(
        "column,value",
        [
            ("committer_date", None),
            ("committer_date", "not-a-date"),
            ("author_date", "not-a-date"),
            ("author_date", "2026-01-01T12:00:00"),
            ("is_verified", None),
            ("is_verified", "false"),
        ],
    )
    def test_commit_cohort_and_verification_cannot_silently_drop_rows(self, column, value):
        row = {
            "repo": "o/r",
            "sha": "abc",
            "committer_date": "2026-01-01T12:00:00Z",
            "author_date": None,
            "is_verified": False,
            column: value,
        }
        with api.reporting_operation(REPORTING), pytest.raises(api.GitHubReportingError):
            reporting.validate_rows("commits", [row])

    @pytest.mark.parametrize("value", [None, "false", 0])
    def test_pr_draft_flag_must_be_boolean_before_projection(self, monkeypatch, value):
        with pytest.raises(api.GitHubReportingError, match="is_draft"):
            run_pulls(monkeypatch, [pull(draft=value)], output=pa.schema([fn.PULL_SCHEMA.field("labels")]))

    @pytest.mark.parametrize(
        "changes",
        [
            {"is_draft": None},
            {"is_prerelease": None},
            {"is_prerelease": "false"},
            {"published_at": None},
            {"published_at": "not-a-date"},
        ],
    )
    def test_published_release_cohort_requires_its_evidence(self, changes):
        row = {
            "repo": "o/r",
            "id": 1,
            "download_count": 0,
            "is_draft": False,
            "is_prerelease": False,
            "created_at": "2026-01-01T00:00:00Z",
            "published_at": "2026-01-02T00:00:00Z",
            **changes,
        }
        with api.reporting_operation(REPORTING), pytest.raises(api.GitHubReportingError):
            reporting.validate_rows("releases", [row])

    def test_draft_release_can_have_no_publication_timestamp(self):
        row = {
            "repo": "o/r",
            "id": 1,
            "download_count": 0,
            "is_draft": True,
            "is_prerelease": False,
            "created_at": "2026-01-01T00:00:00Z",
            "published_at": None,
        }
        with api.reporting_operation(REPORTING):
            reporting.validate_rows("releases", [row])

    @pytest.mark.parametrize(
        "changes",
        [
            {"status": None},
            {"status": "bogus"},
            {"conclusion": None},
            {"conclusion": "unknown"},
            {"status": "queued", "conclusion": "success"},
        ],
    )
    def test_workflow_outcome_denominator_requires_a_valid_lifecycle(self, changes):
        row = {
            "repo": "o/r",
            "id": 1,
            "status": "completed",
            "conclusion": "success",
            "created_at": "2026-01-01T00:00:00Z",
            "updated_at": "2026-01-01T01:00:00Z",
            **changes,
        }
        with api.reporting_operation(REPORTING), pytest.raises(api.GitHubReportingError):
            reporting.validate_rows("workflow_runs", [row])

    @pytest.mark.parametrize("status,conclusion", [("queued", None), ("completed", "cancelled")])
    def test_pending_or_never_started_cancelled_runs_are_valid(self, status, conclusion):
        row = {
            "repo": "o/r",
            "id": 1,
            "status": status,
            "conclusion": conclusion,
            "created_at": "2026-01-01T00:00:00Z",
            "updated_at": "2026-01-01T01:00:00Z",
            "run_started_at": None,
        }
        with api.reporting_operation(REPORTING):
            reporting.validate_rows("workflow_runs", [row])


@pytest.mark.parametrize(
    "function,args,column",
    [
        (fn.RepoFunction, fn.RepoArgs(repo=""), "repo"),
        (fn.UserFunction, fn.LoginArgs(login=""), "login"),
    ],
)
def test_reporting_empty_object_is_not_a_missing_point_lookup(monkeypatch, function, args, column):
    install(monkeypatch, lambda r: httpx.Response(200, json={}))
    with pytest.raises(api.GitHubReportingError, match="exactly one valid object"):
        function.process(
            _Params(args, function.FIXED_SCHEMA, attach_opaque_data=REPORTING),
            None,
            _input(**{column: ["o/r" if column == "repo" else "alice"]}),
            _Out(),
        )
