"""GitHub's own behaviour, pinned against the real API — no DuckDB involved.

Every design decision in this worker rests on something GitHub does, and most
of those were learned by probing it: where ``next`` links point, what a 304
costs, where search stops, who may list stargazers. This file turns each probe
into a test, so the day GitHub changes one of them is the day the suite goes
red — not the day a user notices a wrong answer. It has already happened once:
the stargazer restriction is recent, and was found by accident.

Marked `live`. Most tests need VGI_GITHUB_TOKEN; anonymous ones run without.
"""

from __future__ import annotations

import os
import time

import httpx
import pytest

from vgi_github import auth
from vgi_github import github_api as api

pytestmark = pytest.mark.live

REPO = "duckdb/duckdb"
#: An organization repository the token's owner administers, for the
#: stargazer listing. Override for a token from another account.
ADMIN_REPO = os.environ.get("VGI_GITHUB_ADMIN_REPO", "Query-farm/vgi-kalshi")
#: A repository known to have been renamed, so its old name redirects.
RENAMED = "rustyconover/duckdb-crypto-extension"


@pytest.fixture(scope="module")
def creds() -> auth.Credentials:
    token = os.environ.get("VGI_GITHUB_TOKEN")
    if not token:
        pytest.skip("needs VGI_GITHUB_TOKEN")
    return auth.load(token)


def _raw(path: str, creds: auth.Credentials | None = None, **params) -> httpx.Response:
    """One request with no retries and no cache, to observe GitHub as it is."""
    return _raw_with(path, creds, {}, **params)


def _raw_with(path: str, creds: auth.Credentials | None, extra: dict[str, str], **params) -> httpx.Response:
    headers = {
        "Accept": api.ACCEPT_JSON,
        "X-GitHub-Api-Version": api.API_VERSION,
        "User-Agent": api.USER_AGENT,
    }
    if creds:
        headers.update(creds.headers())
    headers.update(extra)
    return httpx.get(f"{api.base_url()}{path}", params=params, headers=headers, timeout=30)


def _core_used(creds: auth.Credentials) -> int:
    return int(_raw("/rate_limit", creds).json()["resources"]["core"]["used"])


class TestPaging:
    def test_next_link_points_at_repositories_by_id(self, creds) -> None:
        """Why next links are checked by origin, not by the path that was asked for."""
        link = api.next_link(_raw(f"/repos/{REPO}/issues", creds, per_page=5, state="all").headers)
        assert link is not None and "/repositories/" in link

    def test_next_link_carries_the_query_and_a_cursor(self, creds) -> None:
        """Why a followed link must keep its query string intact."""
        link = api.next_link(_raw(f"/repos/{REPO}/issues", creds, per_page=5, state="closed").headers)
        params = httpx.URL(link).params
        assert params["state"] == "closed" and "after" in params

    def test_a_multi_page_walk_keeps_its_filter(self, creds) -> None:
        """Regression for the dropped query: page two of closed issues came back open."""
        rows = api.collect(f"/repos/{REPO}/issues", {"state": "closed"}, limit=250, credentials=creds)
        assert len(rows) == 250
        assert {row["state"] for row in rows} == {"closed"}

    def test_page_size_is_capped_at_100(self, creds) -> None:
        """PER_PAGE: asking for more is clamped, not an error."""
        response = _raw(f"/repos/{REPO}/commits", creds, per_page=500)
        assert response.status_code == 200 and len(response.json()) == api.PER_PAGE

    def test_search_stops_serving_at_1000_results(self, creds) -> None:
        """SEARCH_RESULT_CAP: page 11 of 100 is a 422, not an empty page."""
        response = _raw("/search/repositories", creds, q="language:python", per_page=100, page=11)
        assert response.status_code == 422


class TestPayloadShapes:
    def test_the_issue_listing_mixes_in_pull_requests(self, creds) -> None:
        """Why issues() drops rows carrying `pull_request` by default."""
        rows = _raw(f"/repos/{REPO}/issues", creds, state="all", per_page=100).json()
        assert any("pull_request" in row for row in rows)
        assert any("pull_request" not in row for row in rows)

    def test_lists_are_newest_first(self, creds) -> None:
        """Why max_rows keeps the most recent rows."""
        issues = api.collect(
            f"/repos/{REPO}/issues", {"state": "all", "sort": "created"}, limit=20, credentials=creds
        )
        created = [row["created_at"] for row in issues]
        assert created == sorted(created, reverse=True)
        commits = api.collect(f"/repos/{REPO}/commits", limit=20, credentials=creds)
        dates = [c["commit"]["committer"]["date"] for c in commits]
        assert dates[0] >= dates[-1]

    def test_since_bounds_updated_at(self, creds) -> None:
        since = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 7 * 86_400))
        rows = api.collect(
            f"/repos/{REPO}/issues", {"state": "all", "since": since}, limit=50, credentials=creds
        )
        assert rows and all(row["updated_at"] >= since for row in rows)

    def test_workflow_status_also_filters_by_conclusion(self, creds) -> None:
        """Why workflow_runs documents `status => 'failure'` as valid."""
        runs = api.collect(
            f"/repos/{REPO}/actions/runs",
            {"status": "failure"},
            key="workflow_runs",
            limit=10,
            credentials=creds,
        )
        assert runs and {run["conclusion"] for run in runs} == {"failure"}

    def test_star_media_type_adds_starred_at(self, creds) -> None:
        rows = api.collect(
            f"/repos/{ADMIN_REPO}/stargazers", limit=1, credentials=creds, accept=api.ACCEPT_STAR
        )
        if not rows:
            pytest.skip(f"{ADMIN_REPO} has no stars, or the token cannot list them")
        assert "starred_at" in rows[0] and "user" in rows[0]


class TestAccess:
    def test_stargazers_of_others_repositories_are_refused(self, creds) -> None:
        """Why stargazers() raises instead of returning zero rows.

        If this starts passing with a 200, GitHub has lifted the restriction and
        the error, the docs and the vgi-lint waivers should all go.
        """
        assert _raw(f"/repos/{REPO}/stargazers", creds, per_page=1).status_code == 404

    def test_stargazers_need_a_token(self) -> None:
        assert _raw(f"/repos/{REPO}/stargazers", per_page=1).status_code == 401

    def test_a_missing_repository_is_404(self, creds) -> None:
        assert _raw("/repos/duckdb/no-such-repo-vgi-live-test", creds).status_code == 404

    def test_a_private_repository_is_404_anonymously(self) -> None:
        """Why auth => 'required' exists: private and missing look identical."""
        private = os.environ.get("VGI_GITHUB_PRIVATE_REPO")
        if not private:
            pytest.skip("set VGI_GITHUB_PRIVATE_REPO")
        assert _raw(f"/repos/{private}").status_code == 404

    def test_a_renamed_repository_redirects(self, creds) -> None:
        """Why the client follows redirects, and repo() may return a different full_name."""
        assert _raw(f"/repos/{RENAMED}", creds).status_code == 301
        found = api.lookup(f"/repos/{RENAMED}", credentials=creds)
        assert found is not None and found["full_name"] != RENAMED


class TestCachingAndBudget:
    def test_anonymous_responses_are_public(self) -> None:
        directives = _raw(f"/repos/{REPO}").headers["cache-control"]
        assert "public" in directives and "max-age=60" in directives

    def test_authenticated_responses_are_private(self, creds) -> None:
        """Why authenticated results are not forwarded to DuckDB's shared result cache."""
        assert "private" in _raw(f"/repos/{REPO}", creds).headers["cache-control"]

    #: Calls per budget check. The `used` counter is the whole token's, shared
    #: with anything else using it, so "unchanged" is racy; "fewer than N for
    #: N calls" still proves the calls are not charged one by one.
    CALLS = 5

    def test_a_304_is_not_charged(self, creds) -> None:
        """The premise of the ETag cache: revalidating costs no primary budget.

        The revalidation must repeat the original request's headers exactly:
        ETags vary by `Accept`, so a request without it gets a fresh 200.
        """
        etag = _raw(f"/repos/{REPO}", creds).headers["etag"]
        before = _core_used(creds)
        for _ in range(self.CALLS):
            revalidated = _raw_with(f"/repos/{REPO}", creds, {"If-None-Match": etag})
            assert revalidated.status_code == 304
        assert _core_used(creds) - before < self.CALLS

    def test_reading_the_rate_limit_is_free(self, creds) -> None:
        before = _core_used(creds)
        for _ in range(self.CALLS):
            _raw("/rate_limit", creds)
        assert _core_used(creds) - before < self.CALLS

    def test_the_token_raises_the_core_budget(self, creds) -> None:
        assert _raw("/rate_limit", creds).json()["resources"]["core"]["limit"] > 60
        assert _raw("/rate_limit").json()["resources"]["core"]["limit"] == 60
