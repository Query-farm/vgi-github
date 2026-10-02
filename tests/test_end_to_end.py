"""SQL executed against a real ATTACH, through Haybarn's DuckDB.

The offline tests pin each piece; these pin the contract DuckDB actually holds
the worker to. Two defects in this worker were only visible here: a token that
never reached the functions because secrets are keyed by name, and a WHERE
on `state` that DuckDB never pushed into a blended function.

Marked `live`: a real ATTACH talks to GitHub. Set VGI_GITHUB_TOKEN to run
authenticated — anonymously this tier alone can exhaust the hourly budget.
"""

from __future__ import annotations

import os
import time
from collections.abc import Iterator
from typing import Any

import pytest

pytestmark = pytest.mark.live

REPO = "duckdb/duckdb"


@pytest.fixture(scope="module")
def con() -> Iterator[Any]:
    haybarn = pytest.importorskip("haybarn")
    connection = haybarn.connect()
    # A failed ATTACH is a failure, not a skip. It used to skip, and on a CI
    # runner without the vgi extension the whole tier reported "20 skipped"
    # under a green check while testing nothing.
    connection.execute("ATTACH 'github' (TYPE vgi, LOCATION 'uv run github_worker.py')")
    yield connection
    connection.close()


def _one(con: Any, sql: str, *params: Any) -> Any:
    return con.execute(sql, list(params)).fetchone()


class TestAuthentication:
    def test_a_secret_under_any_name_is_used(self, con: Any) -> None:
        token = os.environ.get("VGI_GITHUB_TOKEN")
        if not token:
            pytest.skip("needs VGI_GITHUB_TOKEN to create a secret from")
        con.execute(f"CREATE OR REPLACE SECRET some_name (TYPE github, token '{token}')")
        try:
            (authenticated, limit) = _one(
                con, "SELECT authenticated, request_limit FROM github.main.rate_limit WHERE resource = 'core'"
            )
            assert authenticated and limit > 60
        finally:
            con.execute("DROP SECRET some_name")

    def test_required_mode_fails_without_a_credential(self) -> None:
        if os.environ.get("VGI_GITHUB_TOKEN"):
            pytest.skip("the environment fallback satisfies 'required'")
        haybarn = pytest.importorskip("haybarn")
        strict = haybarn.connect()
        strict.execute("ATTACH 'github' (TYPE vgi, LOCATION 'uv run github_worker.py', auth 'required')")
        with pytest.raises(Exception, match="required"):
            strict.execute("SELECT * FROM github.main.repo('duckdb/duckdb')").fetchall()


class TestLateral:
    def test_fans_out_once_per_driving_row(self, con: Any) -> None:
        rows = con.execute(
            "SELECT t.name, count(*) FROM (VALUES ('duckdb/duckdb'), ('duckdb/duckdb-wasm')) t(name), "
            "LATERAL github.main.languages(t.name) l GROUP BY t.name ORDER BY t.name"
        ).fetchall()
        assert [name for name, _ in rows] == ["duckdb/duckdb", "duckdb/duckdb-wasm"]
        assert all(count > 0 for _, count in rows)

    def test_correlated_columns_line_up_with_their_rows(self, con: Any) -> None:
        """parent_rows provenance: every output row carries its own driving row."""
        (mismatches,) = _one(
            con,
            "SELECT count(*) FILTER (WHERE t.name <> i.repo) FROM "
            "(VALUES ('duckdb/duckdb'), ('duckdb/duckdb-wasm')) t(name), "
            "LATERAL github.main.issues(t.name, max_rows => 5) i",
        )
        assert mismatches == 0

    def test_search_drives_a_lateral(self, con: Any) -> None:
        rows = con.execute(
            "SELECT r.full_name, count(c.sha) FROM (SELECT full_name FROM "
            "github.main.search_repositories('org:duckdb', sort => 'stars') LIMIT 2) r, "
            "LATERAL github.main.commits(r.full_name, max_rows => 3) c GROUP BY r.full_name"
        ).fetchall()
        assert len(rows) == 2 and all(n == 3 for _, n in rows)


class TestSemantics:
    def test_state_argument_reaches_github(self, con: Any) -> None:
        (count, states) = _one(
            con,
            "SELECT count(*), list(DISTINCT state) "
            "FROM github.main.issues(?, state => 'closed', max_rows => 20)",
            REPO,
        )
        assert count == 20 and states == ["closed"]

    def test_issues_exclude_pull_requests(self, con: Any) -> None:
        (any_pr,) = _one(
            con, "SELECT bool_or(is_pull_request) FROM github.main.issues(?, max_rows => 30)", REPO
        )
        assert any_pr is False

    def test_missing_repository_is_no_rows(self, con: Any) -> None:
        (count,) = _one(con, "SELECT count(*) FROM github.main.repo('duckdb/no-such-repo-vgi-test')")
        assert count == 0

    def test_merged_pull_requests_have_merged_at(self, con: Any) -> None:
        (merged, closed) = _one(
            con,
            "SELECT count(*) FILTER (WHERE merged_at IS NOT NULL), count(*) FILTER (WHERE state = 'closed') "
            "FROM github.main.pulls(?, state => 'closed', max_rows => 30)",
            REPO,
        )
        assert 0 < merged <= closed == 30


class TestStreaming:
    def test_a_search_limit_returns_promptly(self, con: Any) -> None:
        start = time.perf_counter()
        rows = con.execute("SELECT * FROM github.main.search_repositories('duckdb') LIMIT 5").fetchall()
        assert len(rows) == 5
        assert time.perf_counter() - start < 30


class TestMaterialization:
    @pytest.mark.parametrize(
        "relation",
        [
            "github.main.repo('duckdb/duckdb')",
            "github.main.user('duckdb')",
            "github.main.issues('duckdb/duckdb', max_rows => 20)",
            "github.main.pulls('duckdb/duckdb', max_rows => 20)",
            "github.main.commits('duckdb/duckdb', max_rows => 20)",
            "github.main.releases('duckdb/duckdb', max_rows => 5)",
            "github.main.contributors('duckdb/duckdb', max_rows => 5)",
            "github.main.workflow_runs('duckdb/duckdb', max_rows => 5)",
            "github.main.repos('duckdb', max_rows => 5)",
            "github.main.rate_limit",
        ],
    )
    def test_every_column_can_be_fetched(self, con: Any, relation: str) -> None:
        assert con.execute(f"SELECT * FROM {relation}").fetchall()
