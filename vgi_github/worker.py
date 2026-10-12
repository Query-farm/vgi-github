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

from vgi_github import __version__, auth, github_api
from vgi_github.datasets import DATASET_FUNCTIONS
from vgi_github.functions import KEYED_FUNCTIONS
from vgi_github.graphql_reads import GraphQLFunction
from vgi_github.meta import column_comments, docs, examples, keywords
from vgi_github.reference import REFERENCE_FUNCTIONS, RateLimitFunction
from vgi_github.rest import ENDPOINT_SCHEMA, REST_FUNCTIONS, EndpointsFunction, RestFunction
from vgi_github.schemas import RATE_LIMIT_SCHEMA
from vgi_github.search import SEARCH_FUNCTIONS

IMPLEMENTATION_VERSION = __version__
DATA_VERSION_SPEC = f"=={__version__}"
SOURCE_URL = "https://github.com/Query-farm/vgi-github"

_FUNCTIONS = [*SEARCH_FUNCTIONS, *KEYED_FUNCTIONS, *REFERENCE_FUNCTIONS, *DATASET_FUNCTIONS]

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
        },
        {
            "name": "open_issue_hotspots",
            "prompt": "Which open issues in duckdb/duckdb have the most thumbs-up reactions?",
        },
        {
            "name": "merged_pull_requests",
            "prompt": "How many of the last 100 pull requests in duckdb/duckdb were merged?",
        },
        {
            "name": "contributor_profiles",
            "prompt": "Where do the top five contributors to duckdb/duckdb say they are located?",
        },
        {
            "name": "ci_health",
            "prompt": "Which GitHub Actions workflows in duckdb/duckdb failed most often recently?",
        },
        {"name": "language_mix", "prompt": "What share of duckdb/duckdb's code is in each language?"},
        {
            "name": "remaining_budget",
            "prompt": "How many GitHub API requests can I still make this hour, and is a token in use?",
        },
        {
            "name": "repository_snapshot",
            "prompt": "How many stars and forks does duckdb/duckdb have, and under what license?",
        },
        {
            "name": "recently_active_repositories",
            "prompt": "Which repositories in the duckdb organization saw a push most recently?",
        },
        {
            "name": "recent_authors",
            "prompt": "Who authored the last 20 commits on duckdb/duckdb's default branch?",
        },
        {
            "name": "release_cadence",
            "prompt": "When were the last five non-pre-release versions of duckdb/duckdb published?",
        },
        {
            "name": "cross_repository_search",
            "prompt": "Find open issues anywhere in the duckdb organization that mention parquet.",
        },
        {
            "name": "who_joined_the_discussion",
            "prompt": (
                "Among the 20 most recent issues in duckdb/duckdb, take the one with the most "
                "comments. Who commented on it?"
            ),
        },
        {
            "name": "discover_rest_reads",
            "prompt": (
                "Which documented GitHub REST read operations cover pull requests? Show their IDs and paths."
            ),
        },
        {
            "name": "complete_repository_json",
            "prompt": (
                "Read duckdb/duckdb's full repository response using the generic REST dispatcher "
                "and show full_name."
            ),
        },
        {
            "name": "graphql_viewer",
            "prompt": (
                "Using the supplied GitHub credentials, query GraphQL for the authenticated account's login."
            ),
        },
        {
            "name": "unanswered_discussions",
            "prompt": "Using GitHub credentials, list the ten most recently updated unanswered discussions "
            "in duckdb/duckdb, with title and category.",
        },
        {
            "name": "discussion_conversation",
            "prompt": "Using GitHub credentials, show up to ten comments on duckdb/duckdb's most recently "
            "updated discussion, and up to ten replies to each comment, keeping the parent comment ID.",
        },
        {
            "name": "project_contents",
            "prompt": "List up to ten items for the first project returned for the github organization. "
            "Include item content types and titles.",
        },
        {
            "name": "project_field_definitions",
            "prompt": "List up to twenty field definitions for the first project returned for the github "
            "organization, including field IDs, names and types.",
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
        {
            "name": "discussions",
            "title": "Discussions",
            "description": "Typed discussions, comments and replies with automatic GraphQL pagination.",
            "keywords": ["discussions", "questions", "answers", "replies"],
        },
        {
            "name": "projects",
            "title": "Projects",
            "description": "Projects, items and field definitions read through REST.",
            "keywords": ["projects", "planning", "fields", "items"],
        },
    ]
)

_CATALOG_TAGS = {
    "provider": "github",
    "domain": "software-development",
    "vgi.title": "GitHub (read-only APIs)",
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
        "Read-only access to GitHub's APIs as SQL: repositories, issues, pull requests, "
        "comments, commits, releases, contributors, stargazers, languages, Actions runs, Projects "
        "and Discussions. Reach "
        "for it to answer questions about open-source projects — activity, health, who works on "
        "what, CI reliability. Start from search_repositories() when you do not know a repository's "
        "name; every per-repository function takes 'owner/name' and composes under LATERAL. A "
        "token is optional but anonymous access is only 60 requests an hour. "
        "The main schema has curated typed tables. The rest schema covers the pinned GitHub.com "
        "and Enterprise Cloud GET operations with complete response pages. The api schema "
        "provides endpoint discovery, operation-ID dispatch and read-only GraphQL queries. "
        "Prefer typed main functions: Projects uses REST and Discussions uses GraphQL with automatic paging."
    ),
    "vgi.doc_md": (
        "GitHub's REST and GraphQL APIs, read-only, as SQL.\n\n"
        "Use `main` for curated typed tables, `rest` for all pinned REST GET operations, "
        "and `api` for endpoint discovery and GraphQL queries. REST pages retain complete "
        "JSON and binary bodies. GraphQL mutation documents are rejected before transport.\n\n"
        "### Key concepts\n\n"
        "- **A repository is written `'owner/name'`.** That one string is the key for everything "
        "repository-scoped, and every row that belongs to a repository carries it in a `repo` or "
        "`full_name` column — so the output of one function is the input of the next.\n"
        "- **Search starts a question; lookups answer it.** The search functions take GitHub's "
        "own query syntax and stream results, so they drive a query. The keyed functions take a "
        "repository or a login and are built to sit inside a correlated `LATERAL`.\n"
        "- **List functions are capped.** A function under `LATERAL` has to fetch everything for "
        "its input before it returns, so the keyed list functions take `max_rows`, default 100 — "
        "one page per input row. Discussion lists default to recently updated first; comments, replies "
        "and Projects retain GitHub's connection/listing order. "
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
    "vgi.title": "Typed GitHub Datasets",
    "vgi.categories": _CATEGORIES,
    "vgi.keywords": keywords("github", "repositories", "issues", "pull requests", "commits", "actions"),
    "vgi.example_queries": _EXAMPLE_QUERIES,
    "vgi.doc_llm": (
        "Curated GitHub tables with typed columns. Discover with search_repositories() "
        "or search_issues(), then pass each repository's full_name ('owner/name') to the "
        "per-repository functions — under LATERAL to cover many repositories in one query. List "
        "functions return at most max_rows (default 100) rows per input row; check each function's "
        "documented ordering. Projects use REST and Discussions use automatically paged GraphQL. "
        "Search functions stream instead and stop at 1,000 results; filter "
        "with their named arguments (state =>, since =>, ...) rather than WHERE, which only sees "
        "fetched rows. Set max_rows => 0 for complete history."
    ),
    "vgi.doc_md": (
        "Typed datasets from GitHub's read-only REST and GraphQL APIs.\n\n"
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
    comment="Read-only GitHub: repositories, issues, PRs, code, people, Actions, Projects and Discussions",
    tags=_CATALOG_TAGS,
    schemas=[
        Schema(
            path=["main"],
            comment="Typed GitHub REST and GraphQL datasets; Discussions requires credentials",
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
        Schema(
            path=["rest"],
            comment="All documented GitHub.com and Enterprise Cloud REST GET operations; complete responses",
            tags=docs(
                llm="One function per documented GET operation. Discover signatures in api.endpoints. "
                "Path parameters are positional; query is a JSON object of filters. "
                "Each row preserves an entire response page in data (JSON text) and body (`BLOB`).",
                md="### Complete REST responses\n\n"
                "Generated from a pinned official OpenAPI description. No write operations. "
                "Default `max_pages=1`; use `max_pages=0` to follow all Link pages, bounded at 100.\n\n"
                "GitHub's permissions, product availability and data limits still apply. "
                "Use the endpoint inventory to find operations and all supported query parameters.",
                example_queries=examples(
                    (
                        "Discover available REST reads",
                        "SELECT operation_id, path FROM github.api.endpoints WHERE category = 'pulls'",
                    )
                ),
                extra={
                    "provider": "github",
                    "vgi.title": "Complete REST Reads",
                    "vgi.keywords": keywords("REST", "GitHub", "OpenAPI", "read-only", "downloads"),
                    "vgi.categories": json.dumps(
                        [{"name": "rest", "description": "Documented REST GET operations"}]
                    ),
                },
            ),
            functions=REST_FUNCTIONS,
        ),
        Schema(
            path=["api"],
            comment="Read-only API discovery, REST operation dispatch and GraphQL queries",
            tags=docs(
                llm="Discover reads with endpoints; call rest(operation_id, path_parameters, query => JSON) "
                "or graphql(query, variables). GraphQL mutations are rejected before sending.",
                md="### API discovery and queries\n\n"
                "The endpoint inventory is local. REST returns complete response pages, "
                "preserving nested fields, media types and binary downloads.\n\n"
                "GraphQL executes query operations only; pagination uses explicit cursor variables. "
                "Mutation documents and REST write operations are rejected before network access.",
                example_queries=examples(
                    (
                        "Discover available REST reads",
                        "SELECT operation_id, path FROM github.api.endpoints WHERE category = 'pulls'",
                    )
                ),
                extra={
                    "provider": "github",
                    "vgi.title": "API Discovery and GraphQL",
                    "vgi.keywords": keywords("API", "REST", "GraphQL", "endpoints", "query"),
                    "vgi.categories": json.dumps(
                        [
                            {"name": "rest", "description": "Documented REST GET operations"},
                            {"name": "graphql", "description": "Read-only GraphQL queries"},
                        ]
                    ),
                },
            ),
            functions=[RestFunction, GraphQLFunction, EndpointsFunction],
            tables=[
                Table(
                    name="endpoints",
                    function=EndpointsFunction,
                    comment="Pinned inventory of all documented GitHub REST GET operations",
                    tags={
                        **EndpointsFunction.Meta.tags,
                        "vgi.example_queries": examples(
                            (
                                "Discover PR reads",
                                "SELECT operation_id, path FROM github.api.endpoints "
                                "WHERE category = 'pulls'",
                            )
                        ),
                    },
                    column_comments=column_comments(ENDPOINT_SCHEMA),
                    primary_key=(("operation_id",),),
                    not_null=("operation_id",),
                    cardinality_estimate=len(REST_FUNCTIONS),
                )
            ],
        ),
    ],
)


class GitHubCatalog(ReadOnlyCatalogInterface):
    """Advertises the worker's versions, its optional credential, and the auth mode.

    The credential is a DuckDB secret rather than an ATTACH option because ATTACH
    option strings are visible in ``duckdb_databases()``. Attach options select
    authentication behavior and the default result cache TTL.
    """

    catalog = _GITHUB_CATALOG
    catalog_name = _GITHUB_CATALOG.name
    # ReadOnlyCatalogInterface enables the single-RPC catalog_contents API.
    # SchemaInfo embeds our per-attach auth/token_source/cache_ttl payload, so
    # its serialized snapshot must not be reused across different attaches.
    catalog_contents_attach_independent = False
    secret_types = [auth.SECRET_SPEC]
    attach_option_specs = [
        AttachOptionSpec(
            name="reporting",
            desc="Reporting: complete validated keyed listings with max_rows=0; no result caching.",
            type=pa.bool_(),
            default=False,
        ),
        AttachOptionSpec(
            name="operation_timeout_seconds",
            desc="Reporting operation deadline across a blended input batch, in seconds (1..3600).",
            type=pa.int64(),
            default=120,
        ),
        AttachOptionSpec(
            name="cache_ttl",
            desc="Default result cache seconds; 0 uses GitHub policy. Per-call cache_ttl overrides this.",
            type=pa.int64(),
            default=0,
        ),
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
        """Validate attach policies and carry them through to the functions.

        An unknown mode is rejected here rather than ignored: a typo'd
        'require' would otherwise read as 'auto' and quietly run anonymously —
        where a private repository returns no rows rather than an error.

        The mode becomes the catalog's attach bytes, which the framework hands
        back to every ``process()`` as ``attach_opaque_data`` — the only route
        an ATTACH-time choice has into a function body.
        """
        reporting = options.get("reporting", False)
        if not isinstance(reporting, bool):
            raise ValueError("ATTACH option reporting must be a boolean")
        timeout = options.get("operation_timeout_seconds", 120)
        if isinstance(timeout, bool) or not isinstance(timeout, int) or not 1 <= timeout <= 3600:
            raise ValueError("ATTACH option operation_timeout_seconds must be an integer from 1 to 3600")
        cache_ttl = options.get("cache_ttl", 0)
        if isinstance(cache_ttl, bool) or not isinstance(cache_ttl, int) or cache_ttl < 0:
            raise ValueError("ATTACH option cache_ttl must be a non-negative integer number of seconds")
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
            attach_opaque_data=AttachOpaqueData(
                auth.encode_attach(
                    mode, source, cache_ttl, reporting=reporting, operation_timeout_seconds=timeout
                )
            ),
            attach_opaque_data_required=True,
            tags={
                **result.tags,
                "vgi_github_reporting": str(reporting).lower(),
                "vgi_github_operation_timeout_seconds": str(timeout),
                "vgi_github_api_origin": github_api.base_url(),
            },
        )

    def catalog_version(self, **kwargs: Any) -> int:
        """Match the frozen version advertised by the read-only attach result."""
        return 1

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
