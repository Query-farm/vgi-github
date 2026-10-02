"""Search: the unkeyed way into GitHub, as streaming scans.

Search is how a query *starts* — "repositories about duckdb with over 1,000
stars", "open bugs mentioning parquet across an organization" — so these two
are the drivers of a join rather than lookups into one. That is why they are
paged scans (:mod:`vgi_github.paging`) instead of blended functions: rows
stream a page at a time, so ``LIMIT 10`` costs one request of search's tight
30-a-minute budget rather than ten.

The query string is GitHub's own search syntax, passed through untouched:
qualifiers such as ``org:``, ``language:``, ``stars:>1000``, ``is:open`` and
``label:bug`` are the expressive part, and re-modelling them as arguments would
only lose some.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, ClassVar

import pyarrow as pa
from vgi.arguments import Arg, SecretLookupEntry
from vgi.invocation import BindResponse
from vgi.metadata import FunctionExample
from vgi.table_function import BindParams, ProcessParams, TableFunctionGenerator, init_single_worker
from vgi_rpc.rpc import OutputCollector

from vgi_github import auth
from vgi_github.meta import docs, examples
from vgi_github.paging import PagedScanState, emit_search_page
from vgi_github.schemas import ISSUE_SCHEMA, REPO_SCHEMA, flatten_issue, flatten_repo


@dataclass(slots=True, frozen=True, kw_only=True)
class SearchRepositoriesArgs:
    """``search_repositories(query)`` with GitHub's ordering knobs."""

    query: Annotated[
        str, Arg(0, doc="GitHub search syntax, e.g. 'duckdb language:python stars:>100' or 'org:duckdb'")
    ]
    sort: Annotated[
        str,
        Arg(
            "sort",
            doc="Order: best match (default), stars, forks, help-wanted-issues or updated",
            default="",
            choices=["", "stars", "forks", "help-wanted-issues", "updated"],
        ),
    ] = ""
    order: Annotated[
        str,
        Arg(
            "order",
            doc="desc (default) or asc; ignored for best match",
            default="desc",
            choices=["desc", "asc"],
        ),
    ] = "desc"


@init_single_worker
class SearchRepositoriesFunction(TableFunctionGenerator[SearchRepositoriesArgs, PagedScanState]):
    """Repositories matching a GitHub search query, one API page per tick."""

    FIXED_SCHEMA: ClassVar[pa.Schema] = REPO_SCHEMA

    class Meta:
        name = "search_repositories"
        description = "Search GitHub repositories with GitHub's query syntax"
        categories = ["search"]
        required_secrets = [SecretLookupEntry(secret_type=auth.SECRET_TYPE)]
        projection_pushdown = True
        tags = docs(
            category="search",
            result_schema=REPO_SCHEMA,
            llm=(
                "Find repositories with GitHub's search syntax — topic words plus qualifiers like "
                "org:NAME, user:NAME, language:rust, stars:>1000, topic:database, pushed:>2026-01-01. "
                "The discovery entry point when you do not already know a repository's name; "
                "every row's full_name then feeds the per-repository functions under LATERAL. "
                "At most 1,000 results per query."
            ),
            md=(
                "Repositories matching a search, streamed one page of 100 at a time — a `LIMIT` "
                "stops the walk early.\n\n"
                "### Query syntax\n\n"
                "The argument is passed to GitHub untouched, so every qualifier GitHub documents "
                "works: `org:duckdb`, `language:python`, `stars:>1000`, `topic:sql`, "
                "`archived:false`, `pushed:>2026-01-01`. Put qualifiers in the query rather than "
                "a WHERE clause: a WHERE filters the results GitHub chose to return, and search "
                "returns at most 1,000.\n\n"
                "### Driving other functions\n\n"
                "Same columns as `repo()` and `repos()`. Being a streaming scan it cannot sit "
                "*inside* a LATERAL, but it is the natural thing to drive one:\n\n"
                "```sql\n"
                "FROM github.main.search_repositories('org:duckdb') r,\n"
                "     LATERAL github.main.issues(r.full_name, state => 'open') i\n"
                "```\n\n"
                "### Budget\n\n"
                "Search has its own rate limit: 30 requests a minute with a token, 10 without."
            ),
            example_queries=examples(
                (
                    "The most starred repositories about DuckDB",
                    "SELECT full_name, stargazers_count, language "
                    "FROM github.main.search_repositories('duckdb', sort => 'stars') LIMIT 10",
                ),
                (
                    "Open issue counts for an organization's most starred repositories, via LATERAL",
                    "SELECT r.full_name, count(i.number) AS open_issues "
                    "FROM (SELECT full_name FROM github.main.search_repositories('org:duckdb', "
                    "sort => 'stars') LIMIT 5) r, "
                    "LATERAL github.main.issues(r.full_name, state => 'open') i "
                    "GROUP BY r.full_name ORDER BY open_issues DESC",
                ),
            ),
        )
        examples = [
            FunctionExample(
                sql=(
                    "SELECT full_name, stargazers_count, language "
                    "FROM github.main.search_repositories('duckdb', sort => 'stars') LIMIT 10"
                ),
                description="The most starred repositories about DuckDB",
            ),
        ]

    @classmethod
    def on_bind(cls, params: BindParams[SearchRepositoriesArgs]) -> BindResponse:
        return BindResponse(output_schema=cls.FIXED_SCHEMA)

    @classmethod
    def initial_state(cls, params: ProcessParams[SearchRepositoriesArgs]) -> PagedScanState:
        return PagedScanState()

    @classmethod
    def process(
        cls, params: ProcessParams[SearchRepositoriesArgs], state: PagedScanState, out: OutputCollector
    ) -> None:
        """Emit one page of results, then remember where to resume."""
        args = params.args
        emit_search_page(
            params,
            state,
            out,
            path="/search/repositories",
            query={"q": args.query, "sort": args.sort or None, "order": args.order if args.sort else None},
            flatten=flatten_repo,
        )


@dataclass(slots=True, frozen=True, kw_only=True)
class SearchIssuesArgs:
    """``search_issues(query)`` with GitHub's ordering knobs."""

    query: Annotated[
        str,
        Arg(0, doc="GitHub search syntax, e.g. 'repo:duckdb/duckdb is:issue is:open label:bug parquet'"),
    ]
    sort: Annotated[
        str,
        Arg(
            "sort",
            doc="Order: best match (default), created, updated, comments or reactions",
            default="",
            choices=["", "created", "updated", "comments", "reactions", "reactions-+1", "interactions"],
        ),
    ] = ""
    order: Annotated[
        str,
        Arg(
            "order",
            doc="desc (default) or asc; ignored for best match",
            default="desc",
            choices=["desc", "asc"],
        ),
    ] = "desc"


@init_single_worker
class SearchIssuesFunction(TableFunctionGenerator[SearchIssuesArgs, PagedScanState]):
    """Issues and pull requests matching a GitHub search query, one page per tick."""

    FIXED_SCHEMA: ClassVar[pa.Schema] = ISSUE_SCHEMA

    class Meta:
        name = "search_issues"
        description = "Search GitHub issues and pull requests with GitHub's query syntax"
        categories = ["search"]
        required_secrets = [SecretLookupEntry(secret_type=auth.SECRET_TYPE)]
        projection_pushdown = True
        tags = docs(
            category="search",
            result_schema=ISSUE_SCHEMA,
            llm=(
                "Find issues and pull requests across GitHub with its search syntax: text plus "
                "qualifiers like repo:OWNER/NAME, org:NAME, is:issue or is:pr, is:open, label:bug, "
                "author:LOGIN, involves:LOGIN, created:>2026-01-01. The way to search across many "
                "repositories at once, or by text. Same columns as issues(). At most 1,000 "
                "results per query."
            ),
            md=(
                "Issues and pull requests matching a search, streamed one page of 100 at a time.\n\n"
                "### Issues and pull requests together\n\n"
                "Search covers both unless the query says `is:issue` or `is:pr`; "
                "`is_pull_request` tells them apart in the result. GitHub now requires one of "
                "those qualifiers for some queries, and rejects the query if it is missing.\n\n"
                "### Query, not WHERE\n\n"
                "Qualifiers are evaluated by GitHub across everything; a WHERE clause only "
                "filters the at-most-1,000 results it returned. `repo:`, `org:`, `label:`, "
                "`is:open` and date ranges belong in the query.\n\n"
                "### Budget\n\n"
                "Search has its own rate limit: 30 requests a minute with a token, 10 without."
            ),
            example_queries=examples(
                (
                    "Open bugs mentioning parquet in DuckDB",
                    "SELECT number, title, created_at FROM github.main.search_issues("
                    "'repo:duckdb/duckdb is:issue is:open parquet', sort => 'created') LIMIT 20",
                ),
                (
                    "Most discussed open issues across an organization",
                    "SELECT repo, number, title, comments FROM github.main.search_issues("
                    "'org:duckdb is:issue is:open', sort => 'comments') LIMIT 10",
                ),
            ),
        )
        examples = [
            FunctionExample(
                sql=(
                    "SELECT repo, number, title, comments FROM github.main.search_issues("
                    "'org:duckdb is:issue is:open', sort => 'comments') LIMIT 10"
                ),
                description="Most discussed open issues across an organization",
            ),
        ]

    @classmethod
    def on_bind(cls, params: BindParams[SearchIssuesArgs]) -> BindResponse:
        return BindResponse(output_schema=cls.FIXED_SCHEMA)

    @classmethod
    def initial_state(cls, params: ProcessParams[SearchIssuesArgs]) -> PagedScanState:
        return PagedScanState()

    @classmethod
    def process(
        cls, params: ProcessParams[SearchIssuesArgs], state: PagedScanState, out: OutputCollector
    ) -> None:
        """Emit one page of results, then remember where to resume."""
        args = params.args
        emit_search_page(
            params,
            state,
            out,
            path="/search/issues",
            query={"q": args.query, "sort": args.sort or None, "order": args.order if args.sort else None},
            flatten=flatten_issue,
        )


SEARCH_FUNCTIONS: list[type] = [SearchRepositoriesFunction, SearchIssuesFunction]
