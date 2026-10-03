"""VGI worker exposing the GitHub REST API to DuckDB/SQL (read-only).

    ATTACH 'github' (TYPE vgi, LOCATION 'uv run github_worker.py');
    SELECT full_name, stargazers_count FROM github.search_repositories('duckdb') LIMIT 10;
    SELECT number, title FROM github.issues('duckdb/duckdb') WHERE state = 'open';

Credentials are optional but strongly recommended: anonymous access is 60
requests an hour. Supply a token as a DuckDB secret::

    CREATE SECRET github (TYPE github, token 'ghp_...');

Function names are bare (``issues``, not ``github_issues``) because they are
already qualified by the catalog they live in.
"""

from __future__ import annotations

import json
import sys
from dataclasses import replace
from typing import Any

import pyarrow as pa
from vgi import Worker
from vgi.catalog import Catalog, ReadOnlyCatalogInterface, Schema
from vgi.catalog.attach_option import AttachOptionSpec
from vgi.catalog.catalog_interface import AttachOpaqueData, CatalogAttachResult, CatalogInfo
from vgi.catalog.descriptors import Table

from vgi_github import __version__, auth
from vgi_github.functions import KEYED_FUNCTIONS
from vgi_github.meta import column_comments, docs, examples, keywords
from vgi_github.reference import REFERENCE_FUNCTIONS, RateLimitFunction
from vgi_github.schemas import RATE_LIMIT_SCHEMA
from vgi_github.search import SEARCH_FUNCTIONS

IMPLEMENTATION_VERSION = __version__
DATA_VERSION_SPEC = f"=={__version__}"
SOURCE_URL = "https://github.com/Query-farm/vgi-github"

_FUNCTIONS = [*SEARCH_FUNCTIONS, *KEYED_FUNCTIONS, *REFERENCE_FUNCTIONS]

_EXAMPLE_QUERIES = examples(
    (
        "The most starred repositories about DuckDB",
        "SELECT full_name, stargazers_count, language "
        "FROM github.main.search_repositories('duckdb', sort => 'stars') LIMIT 10",
    ),
    (
        "Open issues with the most thumbs-up in one repository, ranked by search",
        "SELECT number, title, reactions_plus_one FROM github.main.search_issues("
        "'repo:duckdb/duckdb is:issue is:open', sort => 'reactions-+1') LIMIT 10",
    ),
    (
        "Open issues for an organization's top repositories, via LATERAL",
        "SELECT r.full_name, count(i.number) AS open_issues "
        "FROM (SELECT full_name FROM github.main.search_repositories('org:duckdb', sort => 'stars') "
        "LIMIT 5) r, LATERAL github.main.issues(r.full_name, state => 'open') i "
        "GROUP BY r.full_name ORDER BY open_issues DESC",
    ),
    (
        "Profiles of a repository's top contributors, via LATERAL",
        "SELECT c.login, c.contributions, u.company, u.location "
        "FROM github.main.contributors('duckdb/duckdb', max_rows => 10) c, "
        "LATERAL github.main.user(c.login, cache_ttl => 3600) u ORDER BY c.contributions DESC",
    ),
    (
        "CI failure rate per workflow",
        "SELECT name, count(*) FILTER (WHERE conclusion = 'failure') / count(*) AS failure_rate "
        "FROM github.main.workflow_runs('duckdb/duckdb', status => 'completed') GROUP BY name",
    ),
    (
        "How much API budget is left",
        "SELECT resource, remaining, request_limit, reset_at FROM github.main.rate_limit",
    ),
)

#: Examples the linter runs against a live worker, so each must be true for as
#: long as GitHub and these long-lived repositories exist — no counts that
#: move, no issue numbers that could be deleted.
_EXECUTABLE_EXAMPLES = json.dumps(
    [
        {
            "name": "rate_limit_lists_the_core_budget",
            "description": "The rate_limit table always reports a core budget.",
            "sql": "SELECT count(*) FROM github.main.rate_limit WHERE resource = 'core'",
            "expected_result": [[1]],
        },
        {
            "name": "repo_lookup_returns_one_row",
            "description": "A point lookup of a known repository returns exactly that repository.",
            "sql": "SELECT full_name FROM github.main.repo('duckdb/duckdb')",
            "expected_result": [["duckdb/duckdb"]],
        },
        {
            "name": "a_missing_repo_is_no_rows",
            "description": "A repository that does not exist is an empty result, not an error.",
            "sql": "SELECT count(*) FROM github.main.repo('duckdb/this-repository-does-not-exist-vgi')",
            "expected_result": [[0]],
        },
        {
            "name": "issues_are_stamped_with_their_repo",
            "description": "Every issue row carries the repository it was fetched from.",
            "sql": (
                "SELECT bool_and(repo = 'duckdb/duckdb') "
                "FROM github.main.issues('duckdb/duckdb', max_rows => 10)"
            ),
            "expected_result": [[True]],
        },
        {
            "name": "issues_exclude_pull_requests_by_default",
            "description": "GitHub mixes pull requests into the issue listing; issues() removes them.",
            "sql": (
                "SELECT bool_or(is_pull_request) FROM github.main.issues('duckdb/duckdb', max_rows => 30)"
            ),
            "expected_result": [[False]],
        },
        {
            "name": "max_rows_caps_each_input_row",
            "description": "max_rows bounds what one repository contributes.",
            "sql": "SELECT count(*) FROM github.main.commits('duckdb/duckdb', max_rows => 7)",
            "expected_result": [[7]],
        },
        {
            "name": "lateral_fans_out_per_input_row",
            "description": "A correlated LATERAL calls the function once per driving row.",
            "sql": (
                "SELECT count(DISTINCT l.repo) FROM (VALUES ('duckdb/duckdb'), ('duckdb/duckdb-wasm')) "
                "t(name), LATERAL github.main.languages(t.name) l"
            ),
            "expected_result": [[2]],
        },
        {
            "name": "search_limit_stops_early",
            "description": "A search scan streams, so LIMIT returns exactly that many rows.",
            "sql": (
                "SELECT count(*) FROM (SELECT full_name "
                "FROM github.main.search_repositories('duckdb') LIMIT 5)"
            ),
            "expected_result": [[5]],
        },
    ]
)

#: Tasks an analyst should be able to complete from the catalog metadata alone,
#: written to exercise what this worker is easy to get wrong: the issue/PR mix,
#: 'merged' not being a state, and stargazers being oldest-first.
_AGENT_TEST_TASKS = json.dumps(
    [
        {
            "name": "find_repositories",
            "prompt": "What are the five most starred GitHub repositories that mention DuckDB?",
            "reference_sql": (
                "SELECT full_name, stargazers_count FROM github.main.search_repositories("
                "'duckdb', sort => 'stars') LIMIT 5"
            ),
            "success_criteria": "Uses search_repositories sorted by stars rather than guessing names.",
            "unordered": True,
        },
        {
            "name": "open_issue_hotspots",
            "prompt": "Which open issues in duckdb/duckdb have the most thumbs-up reactions?",
            "reference_sql": (
                "SELECT number, title, reactions_plus_one FROM github.main.search_issues("
                "'repo:duckdb/duckdb is:issue is:open', sort => 'reactions-+1') LIMIT 10"
            ),
            "success_criteria": (
                "Ranks across ALL open issues — via search_issues sorted by reactions-+1, or "
                "issues() with no row cap — not just the 100 most recent, and excludes pull requests."
            ),
        },
        {
            "name": "merged_pull_requests",
            "prompt": "How many of the last 100 pull requests in duckdb/duckdb were merged?",
            "reference_sql": (
                "SELECT count(*) FILTER (WHERE merged_at IS NOT NULL) FROM github.main.pulls('duckdb/duckdb')"
            ),
            "success_criteria": (
                "Counts merged_at IS NOT NULL. Filtering state = 'merged' is wrong — merged is not a state."
            ),
        },
        {
            "name": "contributor_profiles",
            "prompt": "Where do the top five contributors to duckdb/duckdb say they are located?",
            "reference_sql": (
                "SELECT c.login, u.location FROM github.main.contributors('duckdb/duckdb', max_rows => 5) c, "
                "LATERAL github.main.user(c.login) u"
            ),
            "success_criteria": "Drives user() from contributors() with a LATERAL join.",
            "unordered": True,
        },
        {
            "name": "ci_health",
            "prompt": "Which GitHub Actions workflows in duckdb/duckdb failed most often recently?",
            "reference_sql": (
                "SELECT name, count(*) FILTER (WHERE conclusion = 'failure') AS failures "
                "FROM github.main.workflow_runs('duckdb/duckdb', status => 'completed') "
                "GROUP BY name ORDER BY failures DESC"
            ),
            "success_criteria": "Uses workflow_runs and counts conclusion = 'failure', not status.",
        },
        {
            "name": "language_mix",
            "prompt": "What share of duckdb/duckdb's code is in each language?",
            "reference_sql": (
                "SELECT language, bytes / sum(bytes) OVER () AS share "
                "FROM github.main.languages('duckdb/duckdb')"
            ),
            "success_criteria": "Uses languages() and normalises bytes into a share.",
            "unordered": True,
        },
        {
            "name": "remaining_budget",
            "prompt": "How many GitHub API requests can I still make this hour, and is a token in use?",
            "reference_sql": (
                "SELECT remaining, request_limit, authenticated "
                "FROM github.main.rate_limit WHERE resource = 'core'"
            ),
            "success_criteria": "Reads the core row of rate_limit and reports authenticated.",
            "check_sql": (
                "SELECT count(*) = (SELECT count(*) FROM github.main.all_rate_limit()) "
                "FROM github.main.rate_limit"
            ),
        },
        {
            "name": "repository_snapshot",
            "prompt": "How many stars and forks does duckdb/duckdb have, and under what license?",
            "reference_sql": (
                "SELECT stargazers_count, forks_count, license_spdx_id FROM github.main.repo('duckdb/duckdb')"
            ),
            "success_criteria": "Uses the repo() point lookup rather than searching.",
        },
        {
            "name": "recently_active_repositories",
            "prompt": "Which repositories in the duckdb organization saw a push most recently?",
            "reference_sql": (
                "SELECT full_name, pushed_at FROM github.main.repos('duckdb') "
                "ORDER BY pushed_at DESC LIMIT 10"
            ),
            "success_criteria": "Lists the organization's repositories with repos() and orders by pushed_at.",
        },
        {
            "name": "recent_authors",
            "prompt": "Who authored the last 20 commits on duckdb/duckdb's default branch?",
            "reference_sql": (
                "SELECT coalesce(author_login, author_name) AS author, count(*) AS commits "
                "FROM github.main.commits('duckdb/duckdb', max_rows => 20) GROUP BY author "
                "ORDER BY commits DESC"
            ),
            "success_criteria": "Uses commits() capped at 20 rather than contributors(), which is all-time.",
            "unordered": True,
        },
        {
            "name": "release_cadence",
            "prompt": "When were the last five non-pre-release versions of duckdb/duckdb published?",
            "reference_sql": (
                "SELECT tag_name, published_at FROM github.main.releases('duckdb/duckdb') "
                "WHERE NOT is_prerelease ORDER BY published_at DESC LIMIT 5"
            ),
            "success_criteria": "Uses releases() and excludes pre-releases.",
        },
        {
            "name": "cross_repository_search",
            "prompt": "Find open issues anywhere in the duckdb organization that mention parquet.",
            "reference_sql": (
                "SELECT repo, number, title FROM github.main.search_issues("
                "'org:duckdb is:issue is:open parquet') LIMIT 20"
            ),
            "success_criteria": (
                "Uses search_issues with org:, is:issue and is:open qualifiers in the query rather "
                "than calling issues() on every repository."
            ),
            "unordered": True,
        },
        {
            "name": "who_joined_the_discussion",
            "prompt": (
                "Among the 20 most recent issues in duckdb/duckdb, take the one with the most "
                "comments. Who commented on it?"
            ),
            "reference_sql": (
                "SELECT DISTINCT c.user_login FROM ("
                "SELECT repo, number FROM github.main.issues('duckdb/duckdb', max_rows => 20) "
                "ORDER BY comments DESC LIMIT 1) i, "
                "LATERAL github.main.issue_comments(i.repo, i.number) c"
            ),
            "success_criteria": "Drives issue_comments() from issues() output with both repo and number.",
            "unordered": True,
        },
    ]
)

_CATEGORIES = json.dumps(
    [
        {
            "name": "search",
            "title": "Search & Discovery",
            "description": "Find repositories, issues and pull requests with GitHub's query syntax.",
            "keywords": ["search", "discovery", "find"],
        },
        {
            "name": "repositories",
            "title": "Repositories",
            "description": "Repository metadata, by name or by owner.",
            "keywords": ["repositories", "repos", "stars", "forks"],
        },
        {
            "name": "issues",
            "title": "Issues & Comments",
            "description": "Issue trackers and their conversations.",
            "keywords": ["issues", "bugs", "comments", "labels"],
        },
        {
            "name": "pull-requests",
            "title": "Pull Requests",
            "description": "Proposed changes, review state and merge history.",
            "keywords": ["pull requests", "prs", "merges", "code review"],
        },
        {
            "name": "code",
            "title": "Code History",
            "description": "Commits, releases and language composition.",
            "keywords": ["commits", "releases", "languages", "history"],
        },
        {
            "name": "people",
            "title": "People",
            "description": "Profiles, contributors and stargazers.",
            "keywords": ["users", "organizations", "contributors", "stargazers"],
        },
        {
            "name": "actions",
            "title": "GitHub Actions",
            "description": "CI/CD workflow runs and their outcomes.",
            "keywords": ["actions", "ci", "workflows", "builds"],
        },
        {
            "name": "reference",
            "title": "API Budget",
            "description": "Rate-limit state for the credentials in use.",
            "keywords": ["rate limit", "quota", "authentication"],
        },
    ]
)

_CATALOG_TAGS = {
    "provider": "github",
    "domain": "software-development",
    "vgi.title": "GitHub (read-only REST API)",
    "vgi.source_url": SOURCE_URL,
    "vgi.author": "Query Farm LLC <hello@query.farm>",
    "vgi.copyright": (
        "Worker (c) 2026 Query Farm LLC - https://query.farm. Data (c) GitHub, Inc. and its users, "
        "accessed under GitHub's terms of service."
    ),
    "vgi.license": "MIT",
    "vgi.support_contact": "https://github.com/Query-farm/vgi-github/issues",
    "vgi.support_policy_url": "https://github.com/Query-farm/vgi-github/blob/main/README.md",
    "vgi.keywords": keywords(
        "github",
        "repositories",
        "issues",
        "pull requests",
        "commits",
        "releases",
        "actions",
        "open source",
    ),
    "vgi.executable_examples": _EXECUTABLE_EXAMPLES,
    "vgi.agent_test_tasks": _AGENT_TEST_TASKS,
    "vgi.doc_llm": (
        "Read-only access to GitHub's REST API as SQL: repositories, issues, pull requests, "
        "comments, commits, releases, contributors, stargazers, languages and Actions runs. Reach "
        "for it to answer questions about open-source projects — activity, health, who works on "
        "what, CI reliability. Start from search_repositories() when you do not know a repository's "
        "name; every per-repository function takes 'owner/name' and composes under LATERAL. A "
        "token is optional but anonymous access is only 60 requests an hour."
    ),
    "vgi.doc_md": (
        "GitHub's REST API, read-only, as SQL.\n\n"
        "### Key concepts\n\n"
        "- **A repository is written `'owner/name'`.** That one string is the key for everything "
        "repository-scoped, and every row that belongs to a repository carries it in a `repo` or "
        "`full_name` column — so the output of one function is the input of the next.\n"
        "- **Search starts a question; lookups answer it.** The search functions take GitHub's "
        "own query syntax and stream results, so they drive a query. The keyed functions take a "
        "repository or a login and are built to sit inside a correlated `LATERAL`.\n"
        "- **List functions are capped.** A function under `LATERAL` has to fetch everything for "
        "its input before it returns, so the keyed list functions take `max_rows`, default 100 — "
        "one request per input row, newest first (stargazers are the exception: oldest first). "
        "`max_rows => 0` fetches everything, up to 10,000 rows per input row. The two search "
        "functions stream instead, take no `max_rows`, and stop at GitHub's 1,000-result cap.\n"
        "- **Filter with arguments.** DuckDB applies a WHERE clause after the rows are fetched, "
        "so it cannot reach past `max_rows`. Named arguments such as `state =>` and `since =>` are "
        "sent to GitHub and narrow before the cap.\n\n"
        "### A typical shape\n\n"
        "A search drives, and a keyed function fans out from each row it returns:\n\n"
        "```sql\n"
        "FROM github.main.search_repositories('org:duckdb') r,\n"
        "     LATERAL github.main.issues(r.full_name, state => 'open') i\n"
        "```\n\n"
        "### Authentication and rate limits\n\n"
        "A token raises the budget from 60 requests an hour to 5,000 and makes private "
        "repositories visible. Without one, a private repository is indistinguishable from a "
        "missing one: both return no rows. Supply it as a DuckDB secret of type `github`; the "
        "`rate_limit` table shows what remains and whether a token is in use."
    ),
}

_SCHEMA_TAGS = {
    "provider": "github",
    "domain": "software-development",
    "vgi.title": "GitHub REST API",
    "vgi.categories": _CATEGORIES,
    "vgi.keywords": keywords("github", "repositories", "issues", "pull requests", "commits", "actions"),
    "vgi.example_queries": _EXAMPLE_QUERIES,
    "vgi.doc_llm": (
        "The whole read-only GitHub surface in one schema. Discover with search_repositories() "
        "or search_issues(), then pass each repository's full_name ('owner/name') to the "
        "per-repository functions — under LATERAL to cover many repositories in one query. List "
        "functions return at most max_rows (default 100) rows per input row, newest first "
        "(stargazers: oldest first); search functions stream instead and stop at 1,000 results; filter "
        "with their named arguments (state =>, since =>, ...) rather than WHERE, which only sees "
        "fetched rows. Set max_rows => 0 for complete history."
    ),
    "vgi.doc_md": (
        "One schema holding the read-only GitHub surface.\n\n"
        "### Finding your way in\n\n"
        "If you know the repository, call its function directly: `issues('duckdb/duckdb')`. If "
        "you do not, `search_repositories()` finds it, and its `full_name` column feeds every "
        "per-repository function.\n\n"
        "### The traps\n\n"
        "- GitHub's issue listing includes pull requests. `issues()` removes them by default.\n"
        "- A merged pull request has `state = 'closed'`; test `merged_at IS NOT NULL`.\n"
        "- `stargazers()` is oldest first, so its default cap returns the *first* stars.\n"
        "- A WHERE clause filters what was already fetched; it cannot reach rows past "
        "`max_rows`, and DuckDB does not push it into these functions. Filter with the named "
        "arguments (`state =>`, `labels =>`, `since =>`, `branch =>`, `status =>`, ...), which "
        "GitHub applies before the cap."
    ),
}

_RATE_LIMIT_DOCS = docs(
    category="reference",
    llm=(
        "How many GitHub API requests remain in each budget, and when each resets. Check it before "
        "a large LATERAL fan-out, or to confirm a token is in use: authenticated core budgets are "
        "5,000 an hour, anonymous ones 60. Reading it is free."
    ),
    md=(
        "One row per budget GitHub tracks for the current credentials.\n\n"
        "### Which budget applies\n\n"
        "`core` is an hourly window covering every function in this catalog except "
        "`search_repositories()` and `search_issues()`, which spend `search` — a per-minute "
        "window. The other resources are for APIs this worker does not call and can be "
        "ignored. The column is `request_limit`, not `limit`, because LIMIT is an SQL keyword.\n\n"
        "### Planning a LATERAL\n\n"
        "A list function costs ceil(rows / 100) requests per input row — the default max_rows of "
        "100 is exactly one — and a point lookup one "
        "per distinct key. Compare that with `remaining` before running something wide."
    ),
    example_queries=examples(
        (
            "Remaining budget and reset time",
            "SELECT resource, remaining, request_limit, reset_at FROM github.main.rate_limit "
            "WHERE resource IN ('core', 'search')",
        ),
        (
            "Is a token being used?",
            "SELECT authenticated, request_limit FROM github.main.rate_limit WHERE resource = 'core'",
        ),
    ),
    extra={
        "provider": "github",
        "domain": "software-development",
        "vgi.title": "API Rate Limits",
        "vgi.keywords": keywords("rate limit", "quota", "budget", "authentication", "token"),
    },
)

_GITHUB_CATALOG = Catalog(
    name="github",
    default_schema="main",
    comment="Read-only GitHub data: repositories, issues, pull requests, commits, releases, people, Actions",
    tags=_CATALOG_TAGS,
    schemas=[
        Schema(
            path=["main"],
            comment="GitHub REST API — anonymous or token-authenticated",
            tags=_SCHEMA_TAGS,
            functions=list(_FUNCTIONS),
            tables=[
                Table(
                    name="rate_limit",
                    function=RateLimitFunction,
                    comment="Remaining GitHub API budget for the credentials in use",
                    tags=_RATE_LIMIT_DOCS,
                    column_comments=column_comments(RATE_LIMIT_SCHEMA),
                    primary_key=(("resource",),),
                    not_null=("resource",),
                    cardinality_estimate=12,
                ),
            ],
        ),
    ],
)


class GitHubCatalog(ReadOnlyCatalogInterface):
    """Advertises the worker's versions, its optional credential, and the auth mode.

    The credential is a DuckDB secret rather than an ATTACH option because ATTACH
    option strings are visible in ``duckdb_databases()``. The one thing worth
    deciding at ATTACH time is what should happen when no credential resolves,
    which is what the ``auth`` option selects.
    """

    catalog = _GITHUB_CATALOG
    catalog_name = _GITHUB_CATALOG.name
    secret_types = [auth.SECRET_SPEC]
    attach_option_specs = [
        AttachOptionSpec(
            name="auth",
            desc=(
                "How to treat the optional 'github' secret: 'auto' (default) authenticates when "
                "one is present and goes anonymous otherwise; 'required' fails the query when none "
                "resolves; 'off' never authenticates."
            ),
            type=pa.string(),
            default=auth.AUTO,
        ),
        AttachOptionSpec(
            name="token_source",
            desc=(
                "Where to find your GitHub identity when no 'github' secret resolves: 'gh' uses "
                "the GitHub CLI's login (gh auth token), 'env' uses GH_TOKEN or GITHUB_TOKEN. "
                "Only when DuckDB launches the worker locally; refused by a shared HTTP server."
            ),
            type=pa.string(),
            default=auth.SOURCE_NONE,
        ),
    ]

    def catalog_attach(self, *, name: str, options: dict[str, Any], **kwargs: Any) -> CatalogAttachResult:
        """Validate the ``auth`` option and carry it through to the functions.

        An unknown mode is rejected here rather than ignored: a typo'd
        'require' would otherwise read as 'auto' and quietly run anonymously —
        where a private repository returns no rows rather than an error.

        The mode becomes the catalog's attach bytes, which the framework hands
        back to every ``process()`` as ``attach_opaque_data`` — the only route
        an ATTACH-time choice has into a function body.
        """
        mode = str(options.get("auth") or auth.AUTO).strip().lower()
        if mode not in auth.MODES:
            raise ValueError(f"ATTACH option auth => {mode!r} is not one of {', '.join(auth.MODES)}")
        source = str(options.get("token_source") or auth.SOURCE_NONE).strip().lower()
        if source not in auth.SOURCES:
            choices = ", ".join(repr(s) for s in auth.SOURCES if s)
            raise ValueError(f"ATTACH option token_source => {source!r} is not one of {choices}")
        # Refused at ATTACH, not at the first query: on a shared server it is
        # never going to work, and failing here says so before anything runs.
        if source and not auth.local_sources_allowed():
            raise ValueError(
                f"ATTACH option token_source => {source!r} is not enabled on this worker, which is "
                "shared over HTTP or a socket; send your own token with CREATE SECRET (TYPE github, "
                "token '...'), or start the server with "
                f"{auth.ALLOW_SOURCES_ENV}=1 to let clients use the server's own GitHub login"
            )
        result = super().catalog_attach(name=name, options=options, **kwargs)
        return replace(
            result,
            attach_opaque_data=AttachOpaqueData(auth.encode_attach(mode, source)),
            attach_opaque_data_required=True,
        )

    def catalogs(self) -> list[CatalogInfo]:
        """Advertise the single read-only GitHub catalog."""
        return [
            CatalogInfo(
                name=self._effective_catalog_name,
                implementation_version=IMPLEMENTATION_VERSION,
                data_version_spec=DATA_VERSION_SPEC,
                source_url=SOURCE_URL,
                attach_option_specs=[spec.serialize() for spec in self.attach_option_specs],
            )
        ]


class GitHubWorker(Worker):
    """Worker process hosting the read-only GitHub catalog."""

    catalog = _GITHUB_CATALOG
    catalog_interface = GitHubCatalog


#: Flags that make the worker a server for many clients rather than a child
#: process of one DuckDB.
_SHARED_SERVER_FLAGS = ("--http", "--unix", "--tcp")


def _start(argv: list[str]) -> None:
    """Run the worker, refusing ``token_source`` if it serves many clients.

    A server refuses it unless the operator sets ``VGI_GITHUB_ALLOW_TOKEN_SOURCE=1``:
    the token would come from the server's own login, so every client asking
    for it would act as the operator.
    """
    serving = any(arg == flag or arg.startswith(flag + "=") for arg in argv for flag in _SHARED_SERVER_FLAGS)
    if serving and not auth.sources_allowed_on_server():
        auth.disallow_local_sources()
    sys.argv = [sys.argv[0], *argv]
    GitHubWorker.main()


def main() -> None:
    """Run the worker (stdio by default; pass ``--http`` for the HTTP server)."""
    _start(sys.argv[1:])


def main_http() -> None:
    """Run the worker over HTTP."""
    argv = sys.argv[1:]
    if "--http" not in argv:
        argv = ["--http", *argv]
    _start(argv)
