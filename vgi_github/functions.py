"""Keyed GitHub functions: everything addressed by a repository or an account.

All of these are **blended** (:class:`~vgi.table_in_out_function.RowTransformFunction`)
table functions. Their positional arguments *are* the per-row input columns, so a
single registration serves both a literal call and a correlated LATERAL::

    SELECT * FROM github.main.issues('duckdb/duckdb');

    SELECT r.full_name, i.number, i.title
    FROM github.main.search_repositories('org:duckdb') r,
         LATERAL github.main.issues(r.full_name, state => 'open') i;

Three constraints from the blended contract shape these signatures:

* No ``finalize``/``finish`` — DuckDB forbids ``FinalExecute`` under correlated
  LATERAL, so nothing here may accumulate across batches.
* Positional args are read off ``batch`` by declared name; they are **not**
  surfaced on ``params.args``.
* A positional ``const`` arg is rejected, so every optional knob (``state``,
  ``max_rows``, ``cache_ttl``) is a *named* arg instead.

A blended function must emit everything for its input batch in a single
``process()`` call, so it cannot stream page by page the way a scan does. Every
list function therefore takes ``max_rows``, defaulting to **100** — exactly one
request per input row, since GitHub's largest page is 100. ``max_rows => 0``
walks to the end, bounded by :data:`~vgi_github.github_api.MAX_PAGES`.

Each function is 1->N: one input row fans out to many output rows, so every
``emit`` carries ``parent_rows`` provenance mapping each output row back to the
input row that produced it. Without it the batched-LATERAL operator cannot stamp
the correlated columns onto the right rows.

A key that names nothing — a deleted repository, a private one read without a
token, an empty repository's commits — yields **no rows** for that input row
rather than failing the whole query. Across a LATERAL that is what you want; for
a single literal lookup it means an empty result is the "not found" answer.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Annotated, Any, ClassVar, cast

import pyarrow as pa
from vgi.arguments import Arg, SecretLookupEntry
from vgi.cache_control import CacheControl
from vgi.invocation import BindResponse
from vgi.metadata import FunctionExample
from vgi.table_function import BindParams, ProcessParams
from vgi.table_in_out_function import RowTransformFunction
from vgi_rpc.rpc import OutputCollector

from vgi_github import auth
from vgi_github import github_api as api
from vgi_github.auth import Credentials
from vgi_github.github_api import STALE_IF_ERROR, CacheHint, GitHubInputError
from vgi_github.meta import docs, examples
from vgi_github.schemas import (
    COMMIT_SCHEMA,
    CONTRIBUTOR_SCHEMA,
    ISSUE_COMMENT_SCHEMA,
    ISSUE_SCHEMA,
    LANGUAGE_SCHEMA,
    PULL_SCHEMA,
    RELEASE_SCHEMA,
    REPO_SCHEMA,
    STARGAZER_SCHEMA,
    USER_SCHEMA,
    WORKFLOW_RUN_SCHEMA,
    batch_from_rows,
    flatten_commit,
    flatten_contributor,
    flatten_issue,
    flatten_issue_comment,
    flatten_languages,
    flatten_pull,
    flatten_release,
    flatten_repo,
    flatten_stargazer,
    flatten_user,
    flatten_workflow_run,
    to_timestamp,
)

if TYPE_CHECKING:
    from vgi.protocol import VgiOutputCollector

#: Default per-input-row cap for every list function: one full page.
DEFAULT_MAX_ROWS = 100

#: What a list function's `max_rows` argument says, shared so they cannot drift.
_MAX_ROWS_DOC = "Cap on rows fetched per input row (default 100 = one request; 0 = all, up to 10,000)"

#: Fetches one key's rows: ``(key, hint, credentials) -> rows``.
Fetch = Callable[[Any, CacheHint, Credentials | None], list[dict[str, Any]]]


def _origin_cache_control(hint: CacheHint) -> CacheControl | None:
    """Forward GitHub's own Cache-Control, when it is reusable by a shared cache.

    GitHub says ``public, max-age=60`` on anonymous responses, which is
    forwarded. Authenticated responses say ``private`` — what a token can see is
    specific to it — and are left uncached unless the caller opts in.
    """
    if not hint.cacheable:
        return None
    return CacheControl(ttl=hint.max_age, stale_if_error=STALE_IF_ERROR)


def _opt_in_cache_control(ttl: int) -> CacheControl | None:
    """Cache metadata for an explicit ``cache_ttl``, with per-value memoization.

    A correlated LATERAL repeats lookups — the same author across many issues,
    the same repository across many search hits — and per-value memoization
    turns each repeat into a cache hit. It trades freshness for that, which is
    why the default is off.
    """
    if ttl <= 0:
        return None
    return CacheControl(ttl=ttl, stale_if_error=STALE_IF_ERROR, per_value=True)


def _limit(max_rows: int) -> int | None:
    """``max_rows`` as :func:`~vgi_github.github_api.collect` wants it: 0 means no cap."""
    return max_rows or None


def _fan_out(
    params: ProcessParams[Any],
    batch: pa.RecordBatch,
    out: OutputCollector,
    columns: Sequence[str],
    fetch: Fetch,
    *,
    cache_ttl: int,
) -> None:
    """Fetch every input row's rows and emit them as one 1->N batch with provenance.

    Repeated keys within the batch are fetched once and fanned back out in
    input order — a LATERAL from issues to their authors repeats logins
    constantly — so provenance is unchanged while the request count drops. A
    NULL in any key column emits nothing for that row.

    Cache metadata rides on this, the only batch each call emits: GitHub's own
    policy when it declared a reusable one, otherwise the caller's opt-in TTL.
    """
    keys = list(zip(*(batch.column(name).to_pylist() for name in columns), strict=True))
    hint = CacheHint()
    credentials = auth.for_call(params.secrets, params.attach_opaque_data)
    fetched: dict[tuple[Any, ...], list[dict[str, Any]]] = {}
    rows: list[dict[str, Any]] = []
    parents: list[int] = []
    for index, key in enumerate(keys):
        if any(part is None for part in key):
            continue
        if key not in fetched:
            fetched[key] = fetch(key[0] if len(key) == 1 else key, hint, credentials)
        found = fetched[key]
        rows.extend(found)
        parents.extend([index] * len(found))
    cache_control = _origin_cache_control(hint) or _opt_in_cache_control(cache_ttl)
    cast("VgiOutputCollector", out).emit(
        batch_from_rows(rows, params.output_schema), parent_rows=parents, cache_control=cache_control
    )


# ==========================================================================
# Point lookups: repo, user
# ==========================================================================


@dataclass(slots=True, frozen=True, kw_only=True)
class RepoArgs:
    """A lone ``owner/name`` input column, plus an opt-in cache TTL."""

    repo: Annotated[str, Arg(0, doc="Repository as 'owner/name', e.g. 'duckdb/duckdb'")]
    cache_ttl: Annotated[
        int, Arg("cache_ttl", doc="Seconds to cache this result (0 = GitHub's own policy)", default=0, ge=0)
    ] = 0


class RepoFunction(RowTransformFunction[RepoArgs]):
    """One repository by ``owner/name``."""

    FIXED_SCHEMA: ClassVar[pa.Schema] = REPO_SCHEMA

    class Meta:
        name = "repo"
        description = "One GitHub repository by 'owner/name'"
        categories = ["repositories", "blended"]
        required_secrets = [SecretLookupEntry(secret_type=auth.SECRET_TYPE)]
        projection_pushdown = True
        tags = docs(
            category="repositories",
            result_schema=REPO_SCHEMA,
            llm=(
                "A single repository's current metadata — stars, forks, language, license, "
                "activity timestamps — by its exact 'owner/name'. Use it as a point lookup, or "
                "under LATERAL to enrich any column of repository names (from search results, "
                "say). Returns no row for a repository that does not exist or that the current "
                "credentials cannot see."
            ),
            md=(
                "One row per repository, with the same columns `search_repositories()` and "
                "`repos()` return, so the three are interchangeable downstream.\n\n"
                "### Renamed and transferred repositories\n\n"
                "GitHub redirects an old name to the new one, and the row comes back with the "
                "*current* `full_name` — it may differ from what you passed.\n\n"
                "### Not found means no row\n\n"
                "GitHub answers both 'does not exist' and 'private, and you are not allowed' "
                "with 404. Either way this returns zero rows for that input rather than failing "
                "the query, which is what a LATERAL over many names needs.\n\n"
                "### Counts to read carefully\n\n"
                "`open_issues_count` includes open pull requests, and `watchers_count` is the "
                "star count under an old name — both are GitHub's own quirks, kept for fidelity."
            ),
            example_queries=examples(
                (
                    "One repository's headline numbers",
                    "SELECT full_name, stargazers_count, forks_count, language, license_spdx_id "
                    "FROM github.main.repo('duckdb/duckdb')",
                ),
                (
                    "Enrich a list of repositories via LATERAL",
                    "SELECT r.full_name, r.stargazers_count, r.pushed_at "
                    "FROM (VALUES ('duckdb/duckdb'), ('apache/arrow')) t(name), "
                    "LATERAL github.main.repo(t.name) r ORDER BY r.stargazers_count DESC",
                ),
            ),
        )
        examples = [
            FunctionExample(
                sql=(
                    "SELECT full_name, stargazers_count, forks_count, language, license_spdx_id "
                    "FROM github.main.repo('duckdb/duckdb')"
                ),
                description="One repository's headline numbers",
            ),
        ]

    @classmethod
    def on_bind(cls, params: BindParams[RepoArgs]) -> BindResponse:
        return BindResponse(output_schema=cls.FIXED_SCHEMA)

    @classmethod
    def process(
        cls, params: ProcessParams[RepoArgs], state: None, batch: pa.RecordBatch, out: OutputCollector
    ) -> None:
        def fetch(repo: str, hint: CacheHint, credentials: Credentials | None) -> list[dict[str, Any]]:
            found = api.lookup(api.repo_path(repo), hint=hint, credentials=credentials)
            return [flatten_repo(found)] if found else []

        _fan_out(params, batch, out, ["repo"], fetch, cache_ttl=params.args.cache_ttl)


@dataclass(slots=True, frozen=True, kw_only=True)
class LoginArgs:
    """A lone account-login input column, plus an opt-in cache TTL."""

    login: Annotated[str, Arg(0, doc="User or organization login, e.g. 'torvalds' or 'duckdb'")]
    cache_ttl: Annotated[
        int, Arg("cache_ttl", doc="Seconds to cache this result (0 = GitHub's own policy)", default=0, ge=0)
    ] = 0


class UserFunction(RowTransformFunction[LoginArgs]):
    """One account — user or organization — by login."""

    FIXED_SCHEMA: ClassVar[pa.Schema] = USER_SCHEMA

    class Meta:
        name = "user"
        description = "One GitHub user or organization profile by login"
        categories = ["people", "blended"]
        required_secrets = [SecretLookupEntry(secret_type=auth.SECRET_TYPE)]
        projection_pushdown = True
        tags = docs(
            category="people",
            result_schema=USER_SCHEMA,
            llm=(
                "A GitHub account's public profile — name, company, location, follower counts, "
                "account age — by login. Works for organizations too (type = 'Organization'). "
                "An unknown login yields no row rather than an error. "
                "Use it under LATERAL to turn any column of logins (issue authors, contributors, "
                "stargazers) into profiles; pass cache_ttl so repeated logins are fetched once."
            ),
            md=(
                "One row per account. Users and organizations share an endpoint, so this is also "
                "the organization lookup; `type` says which you got.\n\n"
                "### Enriching other results\n\n"
                "Every function that names a person returns a login column (`user_login`, "
                "`login`, `author_login`), and each feeds this directly under LATERAL. Repeated "
                "logins inside one batch are fetched once; `cache_ttl` extends that across "
                "batches and queries.\n\n"
                "### Free-text fields\n\n"
                "`company`, `location` and `blog` are whatever the account typed — useful for "
                "grouping, not reliable for joining."
            ),
            example_queries=examples(
                (
                    "One profile",
                    "SELECT login, name, type, followers, public_repos, created_at "
                    "FROM github.main.user('torvalds')",
                ),
                (
                    "Where a repository's top contributors say they work",
                    "SELECT c.login, c.contributions, u.company, u.location "
                    "FROM github.main.contributors('duckdb/duckdb', max_rows => 10) c, "
                    "LATERAL github.main.user(c.login, cache_ttl => 3600) u "
                    "ORDER BY c.contributions DESC",
                ),
            ),
        )
        examples = [
            FunctionExample(
                sql=(
                    "SELECT login, name, type, followers, public_repos, created_at "
                    "FROM github.main.user('torvalds')"
                ),
                description="One profile",
            ),
        ]

    @classmethod
    def on_bind(cls, params: BindParams[LoginArgs]) -> BindResponse:
        return BindResponse(output_schema=cls.FIXED_SCHEMA)

    @classmethod
    def process(
        cls, params: ProcessParams[LoginArgs], state: None, batch: pa.RecordBatch, out: OutputCollector
    ) -> None:
        def fetch(login: str, hint: CacheHint, credentials: Credentials | None) -> list[dict[str, Any]]:
            found = api.lookup(f"/users/{api.segment(str(login))}", hint=hint, credentials=credentials)
            return [flatten_user(found)] if found else []

        _fan_out(params, batch, out, ["login"], fetch, cache_ttl=params.args.cache_ttl)


# ==========================================================================
# An account's repositories
# ==========================================================================


@dataclass(slots=True, frozen=True, kw_only=True)
class ReposArgs:
    """``repos(owner)`` with named ordering, ownership filter and row cap."""

    owner: Annotated[str, Arg(0, doc="User or organization login whose repositories to list")]
    type: Annotated[
        str,
        Arg(
            "type",
            doc="Which repositories: owner (default), member or all",
            default="owner",
            choices=["owner", "member", "all"],
        ),
    ] = "owner"
    sort: Annotated[
        str,
        Arg(
            "sort",
            doc="Order before max_rows applies: pushed (default), updated, created or full_name",
            default="pushed",
            choices=["pushed", "updated", "created", "full_name"],
        ),
    ] = "pushed"
    max_rows: Annotated[int, Arg("max_rows", doc=_MAX_ROWS_DOC, default=DEFAULT_MAX_ROWS, ge=0)] = (
        DEFAULT_MAX_ROWS
    )
    cache_ttl: Annotated[
        int, Arg("cache_ttl", doc="Seconds to cache this result (0 = GitHub's own policy)", default=0, ge=0)
    ] = 0


class ReposFunction(RowTransformFunction[ReposArgs]):
    """Public repositories owned by a user or organization."""

    FIXED_SCHEMA: ClassVar[pa.Schema] = REPO_SCHEMA

    class Meta:
        name = "repos"
        description = "Repositories owned by a GitHub user or organization"
        categories = ["repositories", "blended"]
        required_secrets = [SecretLookupEntry(secret_type=auth.SECRET_TYPE)]
        projection_pushdown = True
        tags = docs(
            category="repositories",
            result_schema=REPO_SCHEMA,
            llm=(
                "Every repository an account owns, most recently pushed first, with the same "
                "columns as repo(). The way to go from an organization or user to its "
                "repositories — and, under LATERAL, from a set of accounts to all of theirs. "
                "Capped at max_rows per account (default 100); pass max_rows => 0 for all. "
                "type => 'owner' (default) lists what the account owns; 'member' and 'all' add "
                "repositories it collaborates on. An unknown owner yields no rows."
            ),
            md=(
                "One row per repository owned by the account.\n\n"
                "### Ordering and the row cap\n\n"
                "`max_rows` (default 100) caps what is *fetched* per account, and `sort` decides "
                "which rows survive it: by default the most recently pushed, which is usually "
                "what 'their repositories' means. A WHERE clause filters what was fetched — it "
                "cannot reach repositories past the cap, so raise `max_rows` (or pass 0) when "
                "filtering for something rare.\n\n"
                "### Private repositories\n\n"
                "This lists what the account shows publicly. A token adds private repositories "
                "only for your own account; for a private organization's repositories, use "
                "`search_repositories('org:NAME')` with a token that can see them."
            ),
            example_queries=examples(
                (
                    "An organization's most starred repositories",
                    "SELECT full_name, stargazers_count, language FROM github.main.repos('duckdb') "
                    "ORDER BY stargazers_count DESC LIMIT 10",
                ),
                (
                    "Repositories across several organizations, via LATERAL",
                    "SELECT r.owner_login, count(*) AS repos, sum(r.stargazers_count) AS stars "
                    "FROM (VALUES ('duckdb'), ('apache')) o(name), "
                    "LATERAL github.main.repos(o.name, max_rows => 50) r GROUP BY r.owner_login",
                ),
            ),
        )
        examples = [
            FunctionExample(
                sql=(
                    "SELECT full_name, stargazers_count, language FROM github.main.repos('duckdb') "
                    "ORDER BY stargazers_count DESC LIMIT 10"
                ),
                description="An organization's most starred repositories",
            ),
        ]

    @classmethod
    def on_bind(cls, params: BindParams[ReposArgs]) -> BindResponse:
        return BindResponse(output_schema=cls.FIXED_SCHEMA)

    @classmethod
    def process(
        cls, params: ProcessParams[ReposArgs], state: None, batch: pa.RecordBatch, out: OutputCollector
    ) -> None:
        args = params.args

        def fetch(owner: str, hint: CacheHint, credentials: Credentials | None) -> list[dict[str, Any]]:
            found = api.collect(
                f"/users/{api.segment(str(owner))}/repos",
                {
                    "type": args.type,
                    "sort": args.sort,
                    "direction": "asc" if args.sort == "full_name" else "desc",
                },
                limit=_limit(args.max_rows),
                hint=hint,
                credentials=credentials,
            )
            return [flatten_repo(r) for r in found]

        _fan_out(params, batch, out, ["owner"], fetch, cache_ttl=args.cache_ttl)


# ==========================================================================
# Issues, pull requests, comments
# ==========================================================================


@dataclass(slots=True, frozen=True, kw_only=True)
class IssuesArgs:
    """``issues(repo)`` with named state, label, since and row-cap filters."""

    repo: Annotated[str, Arg(0, doc="Repository as 'owner/name'")]
    state: Annotated[
        str,
        Arg(
            "state",
            doc="open, closed or all (default). Filter here, not in WHERE: WHERE only sees fetched rows",
            default="all",
            choices=["open", "closed", "all"],
        ),
    ] = "all"
    labels: Annotated[
        str, Arg("labels", doc="Comma-separated label names; an issue must carry all of them", default="")
    ] = ""
    since: Annotated[
        str, Arg("since", doc="Only issues updated at or after this instant, e.g. '2026-01-01'", default="")
    ] = ""
    include_pull_requests: Annotated[
        bool,
        Arg(
            "include_pull_requests",
            doc="Also return pull requests, which GitHub's issue listing mixes in",
            default=False,
        ),
    ] = False
    max_rows: Annotated[int, Arg("max_rows", doc=_MAX_ROWS_DOC, default=DEFAULT_MAX_ROWS, ge=0)] = (
        DEFAULT_MAX_ROWS
    )
    cache_ttl: Annotated[
        int, Arg("cache_ttl", doc="Seconds to cache this result (0 = GitHub's own policy)", default=0, ge=0)
    ] = 0


class IssuesFunction(RowTransformFunction[IssuesArgs]):
    """A repository's issues, newest first, excluding pull requests by default."""

    FIXED_SCHEMA: ClassVar[pa.Schema] = ISSUE_SCHEMA

    class Meta:
        name = "issues"
        description = "Issues in a GitHub repository, newest first"
        categories = ["issues", "blended"]
        required_secrets = [SecretLookupEntry(secret_type=auth.SECRET_TYPE)]
        projection_pushdown = True
        tags = docs(
            category="issues",
            result_schema=ISSUE_SCHEMA,
            llm=(
                "A repository's issues, newest first by creation — state defaults to 'all' "
                "(GitHub's own default is open-only) — with "
                "author, labels, assignees, comment and reaction counts. Pull requests are "
                "excluded by default (GitHub mixes them in); use pulls() for those. Capped at "
                "max_rows per repository (default 100), newest first. Filter with the named "
                "arguments (state => 'open', labels => 'bug', since => '2026-01-01' — since "
                "filters on UPDATED time), not WHERE: a WHERE clause only sees fetched rows."
            ),
            md=(
                "One row per issue, newest first.\n\n"
                "### Pull requests are not issues here\n\n"
                "GitHub's issue listing returns pull requests too. They are dropped by default, "
                "and `max_rows` counts only the issues kept; pass `include_pull_requests => true` "
                "to keep them, flagged by `is_pull_request`.\n\n"
                "### Filter with arguments, not WHERE\n\n"
                "`max_rows` (default 100, one request) caps what is fetched per repository, "
                "newest first, and a WHERE clause is applied *after* that — so "
                "`WHERE state = 'closed'` over the newest 100 issues of a busy repository can "
                "return nothing even though thousands are closed. `state`, `labels` and `since` "
                "are sent to GitHub and narrow *before* the cap; use them. For anything else, "
                "raise `max_rows` and then filter.\n\n"
                "### Ranking across the whole history\n\n"
                "To find the most-reacted or most-commented issues ever, ask search to rank "
                "them — `search_issues('repo:OWNER/NAME is:issue is:open', sort => 'reactions-+1')` "
                "— rather than fetching every issue with `max_rows => 0`. A function under "
                "LATERAL cannot stream, so a walk of thousands of issues blocks the query, "
                "uncancellably, until it finishes.\n\n"
                "### Open and closed\n\n"
                "Unlike GitHub's own default of open-only, `state` defaults to `all`."
            ),
            example_queries=examples(
                (
                    "The most discussed of the latest 100 open issues",
                    "SELECT number, title, comments, reactions_plus_one "
                    "FROM github.main.issues('duckdb/duckdb', state => 'open') "
                    "ORDER BY comments DESC LIMIT 10",
                ),
                (
                    "Labels on recent open issues, across several repositories via LATERAL",
                    "SELECT repo, label, count(*) AS issues FROM ("
                    "SELECT i.repo, unnest(i.labels) AS label "
                    "FROM (VALUES ('duckdb/duckdb'), ('duckdb/duckdb-wasm')) t(name), "
                    "LATERAL github.main.issues(t.name, state => 'open') i) "
                    "GROUP BY repo, label ORDER BY issues DESC",
                ),
            ),
        )
        examples = [
            FunctionExample(
                sql=(
                    "SELECT number, title, comments, reactions_plus_one "
                    "FROM github.main.issues('duckdb/duckdb', state => 'open') "
                    "ORDER BY comments DESC LIMIT 10"
                ),
                description="The most discussed of the latest 100 open issues",
            ),
        ]

    @classmethod
    def on_bind(cls, params: BindParams[IssuesArgs]) -> BindResponse:
        return BindResponse(output_schema=cls.FIXED_SCHEMA)

    @classmethod
    def process(
        cls, params: ProcessParams[IssuesArgs], state: None, batch: pa.RecordBatch, out: OutputCollector
    ) -> None:
        args = params.args
        query = {
            "state": args.state,
            "labels": args.labels or None,
            "since": _timestamp_arg("since", args.since),
            "sort": "created",
            "direction": "desc",
        }
        keep = None if args.include_pull_requests else (lambda row: "pull_request" not in row)

        def fetch(repo: str, hint: CacheHint, credentials: Credentials | None) -> list[dict[str, Any]]:
            found = api.collect(
                f"{api.repo_path(repo)}/issues",
                query,
                limit=_limit(args.max_rows),
                keep=keep,
                hint=hint,
                credentials=credentials,
            )
            return [flatten_issue(i, repo) for i in found]

        _fan_out(params, batch, out, ["repo"], fetch, cache_ttl=args.cache_ttl)


@dataclass(slots=True, frozen=True, kw_only=True)
class PullsArgs:
    """``pulls(repo)`` with named state, base branch and row cap."""

    repo: Annotated[str, Arg(0, doc="Repository as 'owner/name'")]
    state: Annotated[
        str,
        Arg(
            "state",
            doc="open, closed or all (default). Filter here, not in WHERE: WHERE only sees fetched rows",
            default="all",
            choices=["open", "closed", "all"],
        ),
    ] = "all"
    base: Annotated[str, Arg("base", doc="Only pull requests targeting this branch", default="")] = ""
    max_rows: Annotated[int, Arg("max_rows", doc=_MAX_ROWS_DOC, default=DEFAULT_MAX_ROWS, ge=0)] = (
        DEFAULT_MAX_ROWS
    )
    cache_ttl: Annotated[
        int, Arg("cache_ttl", doc="Seconds to cache this result (0 = GitHub's own policy)", default=0, ge=0)
    ] = 0


class PullsFunction(RowTransformFunction[PullsArgs]):
    """A repository's pull requests, newest first."""

    FIXED_SCHEMA: ClassVar[pa.Schema] = PULL_SCHEMA

    class Meta:
        name = "pulls"
        description = "Pull requests in a GitHub repository, newest first"
        categories = ["pull-requests", "blended"]
        required_secrets = [SecretLookupEntry(secret_type=auth.SECRET_TYPE)]
        projection_pushdown = True
        tags = docs(
            category="pull-requests",
            result_schema=PULL_SCHEMA,
            llm=(
                "A repository's pull requests, newest first, open and closed, with branches, "
                "draft flag, reviewers and merge time. A merged PR has state 'closed' and a "
                "non-NULL merged_at — test merged_at, not state, for 'merged'. Capped at max_rows "
                "per repository (default 100)."
            ),
            md=(
                "One row per pull request, newest first.\n\n"
                "### Merged is not a state\n\n"
                "GitHub's `state` is only `open` or `closed`. A merged pull request is closed "
                "with a `merged_at`; one closed without merging has `merged_at` NULL. Time to "
                "merge is `merged_at - created_at`.\n\n"
                "### Forks\n\n"
                "`head_repo` is where the branch lives. When it differs from `repo`, the change "
                "came from a fork.\n\n"
                "### The row cap\n\n"
                "`max_rows` (default 100, one request) caps what is fetched per repository, "
                "newest first. `state` and `base` are sent to GitHub and narrow before the cap; "
                "a WHERE clause only filters what was fetched."
            ),
            example_queries=examples(
                (
                    "Median hours to merge for recent pull requests",
                    "SELECT median(date_diff('hour', created_at, merged_at)) AS median_hours "
                    "FROM github.main.pulls('duckdb/duckdb', state => 'closed') "
                    "WHERE merged_at IS NOT NULL",
                ),
                (
                    "Open pull requests that came from forks",
                    "SELECT number, title, user_login, head_repo "
                    "FROM github.main.pulls('duckdb/duckdb', state => 'open') "
                    "WHERE head_repo <> repo ORDER BY number DESC",
                ),
            ),
        )
        examples = [
            FunctionExample(
                sql=(
                    "SELECT median(date_diff('hour', created_at, merged_at)) AS median_hours "
                    "FROM github.main.pulls('duckdb/duckdb', state => 'closed') "
                    "WHERE merged_at IS NOT NULL"
                ),
                description="Median hours to merge for recent pull requests",
            ),
        ]

    @classmethod
    def on_bind(cls, params: BindParams[PullsArgs]) -> BindResponse:
        return BindResponse(output_schema=cls.FIXED_SCHEMA)

    @classmethod
    def process(
        cls, params: ProcessParams[PullsArgs], state: None, batch: pa.RecordBatch, out: OutputCollector
    ) -> None:
        args = params.args
        query = {
            "state": args.state,
            "base": args.base or None,
            "sort": "created",
            "direction": "desc",
        }

        def fetch(repo: str, hint: CacheHint, credentials: Credentials | None) -> list[dict[str, Any]]:
            found = api.collect(
                f"{api.repo_path(repo)}/pulls",
                query,
                limit=_limit(args.max_rows),
                hint=hint,
                credentials=credentials,
            )
            return [flatten_pull(p, repo) for p in found]

        _fan_out(params, batch, out, ["repo"], fetch, cache_ttl=args.cache_ttl)


@dataclass(slots=True, frozen=True, kw_only=True)
class IssueCommentsArgs:
    """``issue_comments(repo, number)`` — both are per-row input columns."""

    repo: Annotated[str, Arg(0, doc="Repository as 'owner/name'")]
    number: Annotated[int, Arg(1, doc="Issue or pull request number")]
    max_rows: Annotated[int, Arg("max_rows", doc=_MAX_ROWS_DOC, default=DEFAULT_MAX_ROWS, ge=0)] = (
        DEFAULT_MAX_ROWS
    )
    cache_ttl: Annotated[
        int, Arg("cache_ttl", doc="Seconds to cache this result (0 = GitHub's own policy)", default=0, ge=0)
    ] = 0


class IssueCommentsFunction(RowTransformFunction[IssueCommentsArgs]):
    """The conversation on one issue or pull request, oldest first."""

    FIXED_SCHEMA: ClassVar[pa.Schema] = ISSUE_COMMENT_SCHEMA

    class Meta:
        name = "issue_comments"
        description = "Comments on a GitHub issue or pull request"
        categories = ["issues", "blended"]
        required_secrets = [SecretLookupEntry(secret_type=auth.SECRET_TYPE)]
        projection_pushdown = True
        tags = docs(
            category="issues",
            result_schema=ISSUE_COMMENT_SCHEMA,
            llm=(
                "The comment thread on one issue or pull request, oldest first. Takes the "
                "repository AND the number — the repo and number columns of issues() and pulls() "
                "output — so it composes directly under LATERAL (i.repo, i.number). max_rows "
                "(default 100) keeps the EARLIEST comments of a long thread. Pull request review "
                "comments on code lines are a different thing and are not included."
            ),
            md=(
                "One row per comment, in posting order.\n\n"
                "### Issues and pull requests share this\n\n"
                "A pull request's conversation tab is an issue thread underneath, so the same "
                "function serves both. Inline review comments attached to lines of a diff are a "
                "separate API and are not returned.\n\n"
                "### Driving it from issues()\n\n"
                "Both positional arguments are columns `issues()` and `pulls()` return, so a "
                "LATERAL needs no reshaping. Each input row costs at least one request."
            ),
            example_queries=examples(
                (
                    "The conversation on the most discussed of the latest issues",
                    "SELECT c.user_login, c.created_at, left(c.body, 80) AS excerpt FROM ("
                    "SELECT repo, number FROM github.main.issues('duckdb/duckdb', max_rows => 20) "
                    "ORDER BY comments DESC LIMIT 1) i, "
                    "LATERAL github.main.issue_comments(i.repo, i.number) c ORDER BY c.created_at",
                ),
                (
                    "Who comments most on the busiest recent issues",
                    "SELECT c.user_login, count(*) AS comments FROM ("
                    "SELECT repo, number FROM github.main.issues('duckdb/duckdb', max_rows => 20) "
                    "ORDER BY comments DESC LIMIT 5) i, "
                    "LATERAL github.main.issue_comments(i.repo, i.number) c "
                    "GROUP BY c.user_login ORDER BY comments DESC",
                ),
            ),
        )
        examples = [
            FunctionExample(
                sql=(
                    "SELECT c.user_login, c.created_at, left(c.body, 80) AS excerpt FROM ("
                    "SELECT repo, number FROM github.main.issues('duckdb/duckdb', max_rows => 20) "
                    "ORDER BY comments DESC LIMIT 1) i, "
                    "LATERAL github.main.issue_comments(i.repo, i.number) c ORDER BY c.created_at"
                ),
                description="The conversation on the most discussed of the latest issues",
            ),
        ]

    @classmethod
    def on_bind(cls, params: BindParams[IssueCommentsArgs]) -> BindResponse:
        return BindResponse(output_schema=cls.FIXED_SCHEMA)

    @classmethod
    def process(
        cls,
        params: ProcessParams[IssueCommentsArgs],
        state: None,
        batch: pa.RecordBatch,
        out: OutputCollector,
    ) -> None:
        args = params.args

        def fetch(
            key: tuple[str, int], hint: CacheHint, credentials: Credentials | None
        ) -> list[dict[str, Any]]:
            repo, number = str(key[0]), int(key[1])
            found = api.collect(
                f"{api.repo_path(repo)}/issues/{number}/comments",
                limit=_limit(args.max_rows),
                hint=hint,
                credentials=credentials,
            )
            return [flatten_issue_comment(c, repo, number) for c in found]

        _fan_out(params, batch, out, ["repo", "number"], fetch, cache_ttl=args.cache_ttl)


# ==========================================================================
# Code history: commits, releases, contributors, languages
# ==========================================================================


@dataclass(slots=True, frozen=True, kw_only=True)
class CommitsArgs:
    """``commits(repo)`` with named branch, path, author, window and row cap."""

    repo: Annotated[str, Arg(0, doc="Repository as 'owner/name'")]
    sha: Annotated[
        str,
        Arg(
            "sha",
            doc="Where the history starts: any ref name or commit hash (empty = default branch)",
            default="",
        ),
    ] = ""
    path: Annotated[str, Arg("path", doc="Only commits touching this file or directory", default="")] = ""
    author: Annotated[str, Arg("author", doc="Only commits by this login or email", default="")] = ""
    since: Annotated[
        str, Arg("since", doc="Only commits at or after this instant, e.g. '2026-01-01'", default="")
    ] = ""
    until: Annotated[
        str,
        Arg("until", doc="Only commits at or before this instant, e.g. '2026-06-30T12:00:00Z'", default=""),
    ] = ""
    max_rows: Annotated[int, Arg("max_rows", doc=_MAX_ROWS_DOC, default=DEFAULT_MAX_ROWS, ge=0)] = (
        DEFAULT_MAX_ROWS
    )
    cache_ttl: Annotated[
        int, Arg("cache_ttl", doc="Seconds to cache this result (0 = GitHub's own policy)", default=0, ge=0)
    ] = 0


def _timestamp_arg(name: str, value: str) -> str | None:
    """Validate an ISO 8601 argument and normalise it to GitHub's ``Z`` form."""
    if not value:
        return None
    parsed = to_timestamp(value)
    if parsed is None:
        raise GitHubInputError(f"{name} => {value!r} is not an ISO 8601 timestamp")
    return parsed.strftime("%Y-%m-%dT%H:%M:%SZ")


class CommitsFunction(RowTransformFunction[CommitsArgs]):
    """A repository's commit history, newest first."""

    FIXED_SCHEMA: ClassVar[pa.Schema] = COMMIT_SCHEMA

    class Meta:
        name = "commits"
        description = "Commit history of a GitHub repository, newest first"
        categories = ["code", "blended"]
        required_secrets = [SecretLookupEntry(secret_type=auth.SECRET_TYPE)]
        projection_pushdown = True
        tags = docs(
            category="code",
            result_schema=COMMIT_SCHEMA,
            llm=(
                "A repository's commit history, newest first, with git author and committer "
                "identities, dates, messages, parents and signature verification. Defaults to the "
                "default branch; pass sha => 'branch' for another, path => 'dir/' to follow one "
                "part of the tree, author => 'login-or-email', since/until (ISO 8601, e.g. "
                "'2026-01-01'; an unparseable value is an error) for a window. Capped at "
                "max_rows (default 100)."
            ),
            md=(
                "One row per commit reachable from `sha` (the default branch unless given), "
                "newest first.\n\n"
                "### Two identities per commit\n\n"
                "`author_*` is who wrote the change and `committer_*` who applied it; they differ "
                "after a rebase, a cherry-pick or a web merge. `author_login` is GitHub's match "
                "from the email to an account, and is NULL when the email maps to none — group by "
                "`author_email` when completeness matters more than identity.\n\n"
                "### Filtering at the source\n\n"
                "`sha`, `path`, `author`, `since` and `until` are sent to GitHub, so they narrow "
                "before `max_rows` applies. A WHERE clause on the output filters only what was "
                "fetched.\n\n"
                "### Empty repositories\n\n"
                "A repository with no commits answers 409; that returns zero rows, not an error."
            ),
            example_queries=examples(
                (
                    "The ten most recent commits on the default branch",
                    "SELECT sha[:10] AS sha, author_login, committer_date, split_part(message, chr(10), 1) "
                    "AS summary FROM github.main.commits('duckdb/duckdb', max_rows => 10)",
                ),
                (
                    "Commits per author over the last week",
                    "SELECT coalesce(author_login, author_email) AS who, count(*) AS commits "
                    "FROM github.main.commits('duckdb/duckdb', since => "
                    "strftime(now() - INTERVAL 7 DAY, '%Y-%m-%dT%H:%M:%SZ'), max_rows => 500) "
                    "GROUP BY who ORDER BY commits DESC",
                ),
            ),
        )
        examples = [
            FunctionExample(
                sql=(
                    "SELECT sha[:10] AS sha, author_login, committer_date, split_part(message, chr(10), 1) "
                    "AS summary FROM github.main.commits('duckdb/duckdb', max_rows => 10)"
                ),
                description="The ten most recent commits on the default branch",
            ),
        ]

    @classmethod
    def on_bind(cls, params: BindParams[CommitsArgs]) -> BindResponse:
        return BindResponse(output_schema=cls.FIXED_SCHEMA)

    @classmethod
    def process(
        cls, params: ProcessParams[CommitsArgs], state: None, batch: pa.RecordBatch, out: OutputCollector
    ) -> None:
        args = params.args
        query = {
            "sha": args.sha or None,
            "path": args.path or None,
            "author": args.author or None,
            "since": _timestamp_arg("since", args.since),
            "until": _timestamp_arg("until", args.until),
        }

        def fetch(repo: str, hint: CacheHint, credentials: Credentials | None) -> list[dict[str, Any]]:
            found = api.collect(
                f"{api.repo_path(repo)}/commits",
                query,
                limit=_limit(args.max_rows),
                hint=hint,
                credentials=credentials,
            )
            return [flatten_commit(c, repo) for c in found]

        _fan_out(params, batch, out, ["repo"], fetch, cache_ttl=args.cache_ttl)


@dataclass(slots=True, frozen=True, kw_only=True)
class RepoListArgs:
    """A repository input column plus the standard row cap and cache TTL."""

    repo: Annotated[str, Arg(0, doc="Repository as 'owner/name'")]
    max_rows: Annotated[int, Arg("max_rows", doc=_MAX_ROWS_DOC, default=DEFAULT_MAX_ROWS, ge=0)] = (
        DEFAULT_MAX_ROWS
    )
    cache_ttl: Annotated[
        int, Arg("cache_ttl", doc="Seconds to cache this result (0 = GitHub's own policy)", default=0, ge=0)
    ] = 0


class ReleasesFunction(RowTransformFunction[RepoListArgs]):
    """A repository's releases, newest first."""

    FIXED_SCHEMA: ClassVar[pa.Schema] = RELEASE_SCHEMA

    class Meta:
        name = "releases"
        description = "Releases of a GitHub repository, newest first"
        categories = ["code", "blended"]
        required_secrets = [SecretLookupEntry(secret_type=auth.SECRET_TYPE)]
        projection_pushdown = True
        tags = docs(
            category="code",
            result_schema=RELEASE_SCHEMA,
            llm=(
                "A repository's published releases, newest first: tag, title, pre-release flag, "
                "publish date, release notes and download_count (summed over attached assets). "
                "Use it for release cadence, version history or download counts. Capped at "
                "max_rows (default 100). A repository with no releases, or none at all, yields no rows."
            ),
            md=(
                "One row per release, newest first.\n\n"
                "### Releases are not tags\n\n"
                "A release is a GitHub object attached to a tag, with notes and assets. Projects "
                "that only push tags have no releases, and this returns nothing for them.\n\n"
                "### Download counts\n\n"
                "`download_count` sums the release's attached assets. The source archives GitHub "
                "generates for every tag are not assets and are not counted, so a project that "
                "ships no binaries shows zero.\n\n"
                "### Drafts\n\n"
                "Draft releases are visible only to tokens with push access, so the result can "
                "differ with credentials."
            ),
            example_queries=examples(
                (
                    "Recent releases and how long apart they were",
                    "SELECT tag_name, published_at, published_at - lag(published_at) "
                    "OVER (ORDER BY published_at) AS gap "
                    "FROM github.main.releases('duckdb/duckdb', max_rows => 20) "
                    "WHERE NOT is_prerelease ORDER BY published_at DESC",
                ),
                (
                    "Most downloaded releases",
                    "SELECT tag_name, download_count FROM github.main.releases('duckdb/duckdb') "
                    "ORDER BY download_count DESC LIMIT 5",
                ),
            ),
        )
        examples = [
            FunctionExample(
                sql=(
                    "SELECT tag_name, download_count FROM github.main.releases('duckdb/duckdb') "
                    "ORDER BY download_count DESC LIMIT 5"
                ),
                description="Most downloaded releases",
            ),
        ]

    @classmethod
    def on_bind(cls, params: BindParams[RepoListArgs]) -> BindResponse:
        return BindResponse(output_schema=cls.FIXED_SCHEMA)

    @classmethod
    def process(
        cls, params: ProcessParams[RepoListArgs], state: None, batch: pa.RecordBatch, out: OutputCollector
    ) -> None:
        limit = _limit(params.args.max_rows)

        def fetch(repo: str, hint: CacheHint, credentials: Credentials | None) -> list[dict[str, Any]]:
            found = api.collect(
                f"{api.repo_path(repo)}/releases", limit=limit, hint=hint, credentials=credentials
            )
            return [flatten_release(r, repo) for r in found]

        _fan_out(params, batch, out, ["repo"], fetch, cache_ttl=params.args.cache_ttl)


class ContributorsFunction(RowTransformFunction[RepoListArgs]):
    """A repository's contributors, most commits first."""

    FIXED_SCHEMA: ClassVar[pa.Schema] = CONTRIBUTOR_SCHEMA

    class Meta:
        name = "contributors"
        description = "Contributors to a GitHub repository, most commits first"
        categories = ["people", "blended"]
        required_secrets = [SecretLookupEntry(secret_type=auth.SECRET_TYPE)]
        projection_pushdown = True
        tags = docs(
            category="people",
            result_schema=CONTRIBUTOR_SCHEMA,
            llm=(
                "Who has contributed to a repository and how many commits each, largest first. "
                "Counts only commits on the default branch that GitHub can attribute to an "
                "account; anonymous (unlinked-email) contributors are not included. Feed login to "
                "user() under LATERAL for profiles. Capped at max_rows (default 100). GitHub may "
                "refuse to compute the list for an enormous history and answer with an error."
            ),
            md=(
                "One row per contributing account, ordered by commit count.\n\n"
                "### What is counted\n\n"
                "Commits on the default branch whose author email maps to a GitHub account. "
                "Commits from unlinked emails are not attributed to anyone here; use `commits()` "
                "and group by `author_email` for a complete count.\n\n"
                "### Very large repositories\n\n"
                "GitHub may decline to compute the list for repositories with an enormous "
                "history, and answers with an error rather than a partial list."
            ),
            example_queries=examples(
                (
                    "Top contributors",
                    "SELECT login, contributions "
                    "FROM github.main.contributors('duckdb/duckdb', max_rows => 10) "
                    "ORDER BY contributions DESC",
                ),
                (
                    "How concentrated a project's commits are",
                    "SELECT sum(contributions) FILTER (WHERE rn <= 5) / sum(contributions) AS top5_share "
                    "FROM (SELECT contributions, row_number() OVER (ORDER BY contributions DESC) AS rn "
                    "FROM github.main.contributors('duckdb/duckdb', max_rows => 0))",
                ),
            ),
        )
        examples = [
            FunctionExample(
                sql=(
                    "SELECT login, contributions "
                    "FROM github.main.contributors('duckdb/duckdb', max_rows => 10) "
                    "ORDER BY contributions DESC"
                ),
                description="Top contributors",
            ),
        ]

    @classmethod
    def on_bind(cls, params: BindParams[RepoListArgs]) -> BindResponse:
        return BindResponse(output_schema=cls.FIXED_SCHEMA)

    @classmethod
    def process(
        cls, params: ProcessParams[RepoListArgs], state: None, batch: pa.RecordBatch, out: OutputCollector
    ) -> None:
        limit = _limit(params.args.max_rows)

        def fetch(repo: str, hint: CacheHint, credentials: Credentials | None) -> list[dict[str, Any]]:
            found = api.collect(
                f"{api.repo_path(repo)}/contributors", limit=limit, hint=hint, credentials=credentials
            )
            return [flatten_contributor(c, repo) for c in found]

        _fan_out(params, batch, out, ["repo"], fetch, cache_ttl=params.args.cache_ttl)


class LanguagesFunction(RowTransformFunction[RepoArgs]):
    """A repository's language breakdown, one row per language."""

    FIXED_SCHEMA: ClassVar[pa.Schema] = LANGUAGE_SCHEMA

    class Meta:
        name = "languages"
        description = "Bytes of code per language in a GitHub repository"
        categories = ["code", "blended"]
        required_secrets = [SecretLookupEntry(secret_type=auth.SECRET_TYPE)]
        projection_pushdown = True
        tags = docs(
            category="code",
            result_schema=LANGUAGE_SCHEMA,
            llm=(
                "How much code a repository has in each language, in bytes, largest first — the "
                "breakdown behind the language bar on a repository page. One request per "
                "repository, so it is cheap under LATERAL. The repo's single `language` column "
                "is just the largest of these."
            ),
            md=(
                "One row per language GitHub's linguist detected.\n\n"
                "### Shares\n\n"
                "Rows come back largest first. Divide `bytes` by the repository's total for a "
                "share — the first example does it with a window function. A byte share is not a "
                "line count, so it can differ from other 'language share' measures.\n\n"
                "### What linguist excludes\n\n"
                "Vendored code, generated files and documentation are excluded by linguist's own "
                "rules, and a repository can override them, so this measures what GitHub "
                "considers the project's code."
            ),
            example_queries=examples(
                (
                    "A repository's language mix as percentages",
                    "SELECT language, round(100.0 * bytes / sum(bytes) OVER (), 1) AS pct "
                    "FROM github.main.languages('duckdb/duckdb') ORDER BY bytes DESC",
                ),
                (
                    "Languages across an organization's repositories, via LATERAL",
                    "SELECT l.language, sum(l.bytes) AS bytes "
                    "FROM github.main.repos('duckdb', max_rows => 20) r, "
                    "LATERAL github.main.languages(r.full_name) l GROUP BY l.language ORDER BY bytes DESC",
                ),
            ),
        )
        examples = [
            FunctionExample(
                sql=(
                    "SELECT language, round(100.0 * bytes / sum(bytes) OVER (), 1) AS pct "
                    "FROM github.main.languages('duckdb/duckdb') ORDER BY bytes DESC"
                ),
                description="A repository's language mix as percentages",
            ),
        ]

    @classmethod
    def on_bind(cls, params: BindParams[RepoArgs]) -> BindResponse:
        return BindResponse(output_schema=cls.FIXED_SCHEMA)

    @classmethod
    def process(
        cls, params: ProcessParams[RepoArgs], state: None, batch: pa.RecordBatch, out: OutputCollector
    ) -> None:
        def fetch(repo: str, hint: CacheHint, credentials: Credentials | None) -> list[dict[str, Any]]:
            found = api.lookup(f"{api.repo_path(repo)}/languages", hint=hint, credentials=credentials)
            return flatten_languages(found, repo)

        _fan_out(params, batch, out, ["repo"], fetch, cache_ttl=params.args.cache_ttl)


class StargazersFunction(RowTransformFunction[RepoListArgs]):
    """Who starred a repository and when, oldest first."""

    FIXED_SCHEMA: ClassVar[pa.Schema] = STARGAZER_SCHEMA

    class Meta:
        name = "stargazers"
        description = "Stars on a GitHub repository with when each was given, oldest first"
        categories = ["people", "blended"]
        required_secrets = [SecretLookupEntry(secret_type=auth.SECRET_TYPE)]
        projection_pushdown = True
        tags = docs(
            category="people",
            result_schema=STARGAZER_SCHEMA,
            llm=(
                "Stars on a repository with their timestamps (up to 10,000), OLDEST first — the raw data "
                "behind a star-history chart. Only works for repositories your token can "
                "administer: GitHub refuses the listing for anyone else's, and this raises an "
                "error rather than reporting zero stars. The default max_rows of 100 returns the "
                "first hundred stars; pass max_rows => 0 for the full history. For anyone else's "
                "repository, use repo() and its stargazers_count instead."
            ),
            md=(
                "One row per star, in the order they were given.\n\n"
                "### Only for repositories you administer\n\n"
                "GitHub restricts who may list a repository's stargazers. For repositories the "
                "token does not administer it refuses the listing even though the repository "
                "exists — 404 for a user token, 403 for a GitHub App or Actions token, 401 "
                "anonymously — so this function raises an explanatory error instead of "
                "returning an empty result that would read as 'no stars'. For anyone else's "
                "repository, `repo()` still reports `stargazers_count`.\n\n"
                "### Oldest first\n\n"
                "GitHub lists stargazers chronologically and offers no reverse order, so "
                "`max_rows` keeps the *earliest* stars. For a star-history chart pass "
                "`max_rows => 0` and bucket `starred_at`; the walk stops with an error past "
                "10,000 rows rather than returning a silently truncated history."
            ),
            example_queries=examples(
                (
                    "A repository's first stargazers",
                    "SELECT starred_at, login "
                    "FROM github.main.stargazers('Query-farm/vgi-kalshi', max_rows => 10)",
                ),
                (
                    "Stars per month",
                    "SELECT date_trunc('month', starred_at) AS month, count(*) AS stars "
                    "FROM github.main.stargazers('Query-farm/vgi-kalshi', max_rows => 0) "
                    "GROUP BY month ORDER BY month",
                ),
            ),
        )
        examples = [
            FunctionExample(
                sql=(
                    "SELECT starred_at, login "
                    "FROM github.main.stargazers('Query-farm/vgi-kalshi', max_rows => 10)"
                ),
                description="A repository's first stargazers",
            ),
        ]

    @classmethod
    def on_bind(cls, params: BindParams[RepoListArgs]) -> BindResponse:
        return BindResponse(output_schema=cls.FIXED_SCHEMA)

    @classmethod
    def process(
        cls, params: ProcessParams[RepoListArgs], state: None, batch: pa.RecordBatch, out: OutputCollector
    ) -> None:
        limit = _limit(params.args.max_rows)

        def fetch(repo: str, hint: CacheHint, credentials: Credentials | None) -> list[dict[str, Any]]:
            path = f"{api.repo_path(repo)}/stargazers"
            try:
                found = api.collect(
                    path,
                    limit=limit,
                    # Not missing_ok: GitHub answers 404 here for repositories
                    # that plainly exist but whose stargazers it will not list
                    # to this token, and "no rows" would read as "no stars".
                    missing_ok=False,
                    hint=hint,
                    credentials=credentials,
                    # The star+json media type is what adds `starred_at`; the
                    # default one returns bare user objects with no timestamp.
                    accept=api.ACCEPT_STAR,
                )
            except api.GitHubError as exc:
                # 404 for a user token, 403 ("Resource not accessible by
                # integration") for a GitHub App or Actions token, 401 anonymously.
                if exc.status in (401, 403, 404):
                    raise api.GitHubError(
                        exc.status,
                        path,
                        "GitHub will not list this repository's stargazers to these credentials. "
                        "It restricts the listing to repositories the token can administer, and "
                        "refuses every other one (404 for a user token, 403 for an app token, 401 "
                        "anonymously) — or the repository does not exist.",
                    ) from exc
                raise
            return [flatten_stargazer(s, repo) for s in found]

        _fan_out(params, batch, out, ["repo"], fetch, cache_ttl=params.args.cache_ttl)


# ==========================================================================
# GitHub Actions
# ==========================================================================


@dataclass(slots=True, frozen=True, kw_only=True)
class WorkflowRunsArgs:
    """``workflow_runs(repo)`` with named branch, event, status filters and row cap."""

    repo: Annotated[str, Arg(0, doc="Repository as 'owner/name'")]
    branch: Annotated[str, Arg("branch", doc="Only runs triggered on this branch", default="")] = ""
    event: Annotated[str, Arg("event", doc="Only runs triggered by this event, e.g. 'push'", default="")] = ""
    status: Annotated[
        str,
        Arg(
            "status",
            doc="A status (completed, in_progress, ...) or a conclusion (success, failure, ...)",
            default="",
        ),
    ] = ""
    max_rows: Annotated[int, Arg("max_rows", doc=_MAX_ROWS_DOC, default=DEFAULT_MAX_ROWS, ge=0)] = (
        DEFAULT_MAX_ROWS
    )
    cache_ttl: Annotated[
        int, Arg("cache_ttl", doc="Seconds to cache this result (0 = GitHub's own policy)", default=0, ge=0)
    ] = 0


class WorkflowRunsFunction(RowTransformFunction[WorkflowRunsArgs]):
    """A repository's GitHub Actions runs, newest first."""

    FIXED_SCHEMA: ClassVar[pa.Schema] = WORKFLOW_RUN_SCHEMA

    class Meta:
        name = "workflow_runs"
        description = "GitHub Actions workflow runs for a repository, newest first"
        categories = ["actions", "blended"]
        required_secrets = [SecretLookupEntry(secret_type=auth.SECRET_TYPE)]
        projection_pushdown = True
        tags = docs(
            category="actions",
            result_schema=WORKFLOW_RUN_SCHEMA,
            llm=(
                "A repository's GitHub Actions runs, newest first: workflow name, trigger event, "
                "branch, status and conclusion, timing. Use it for CI reliability (failure rate "
                "by workflow), duration, or what is running now. Narrow at the source with "
                "branch =>, event => and status => (which also accepts a conclusion such as "
                "'failure'); a WHERE clause only sees the max_rows (default 100) runs fetched, so a "
                "failure rate over the default is over the last 100 runs. For a longer window "
                "raise max_rows (GitHub caps a filtered listing at 1,000 runs)."
            ),
            md=(
                "One row per workflow run, newest first.\n\n"
                "### Status versus conclusion\n\n"
                "`status` is where the run is in its lifecycle; `conclusion` is how it ended and "
                "is NULL until `status = 'completed'`. Failure rate is "
                "`count(*) FILTER (WHERE conclusion = 'failure') / count(*)` over completed runs.\n\n"
                "### Filter with arguments\n\n"
                "`branch`, `event` and `status` are GitHub's own filters and narrow before "
                "`max_rows` applies. `status` takes either a lifecycle status (`completed`) or a "
                "conclusion (`failure`) — GitHub has one parameter for both. GitHub caps any "
                "filtered listing at 1,000 runs.\n\n"
                "### Duration\n\n"
                "For a completed run, `updated_at - run_started_at` approximates wall-clock time "
                "of the last attempt."
            ),
            example_queries=examples(
                (
                    "Failure rate per workflow over the last 100 runs",
                    "SELECT name, count(*) AS runs, "
                    "count(*) FILTER (WHERE conclusion = 'failure') AS failures "
                    "FROM github.main.workflow_runs('duckdb/duckdb') WHERE status = 'completed' "
                    "GROUP BY name ORDER BY failures DESC",
                ),
                (
                    "Recent failed runs on main",
                    "SELECT name, head_sha[:10] AS sha, created_at, html_url "
                    "FROM github.main.workflow_runs('duckdb/duckdb', branch => 'main', status => 'failure', "
                    "max_rows => 30) ORDER BY created_at DESC",
                ),
            ),
        )
        examples = [
            FunctionExample(
                sql=(
                    "SELECT name, count(*) AS runs, "
                    "count(*) FILTER (WHERE conclusion = 'failure') AS failures "
                    "FROM github.main.workflow_runs('duckdb/duckdb') WHERE status = 'completed' "
                    "GROUP BY name ORDER BY failures DESC"
                ),
                description="Failure rate per workflow over the last 100 runs",
            ),
        ]

    @classmethod
    def on_bind(cls, params: BindParams[WorkflowRunsArgs]) -> BindResponse:
        return BindResponse(output_schema=cls.FIXED_SCHEMA)

    @classmethod
    def process(
        cls,
        params: ProcessParams[WorkflowRunsArgs],
        state: None,
        batch: pa.RecordBatch,
        out: OutputCollector,
    ) -> None:
        args = params.args
        query = {
            "branch": args.branch or None,
            "event": args.event or None,
            "status": args.status or None,
        }

        def fetch(repo: str, hint: CacheHint, credentials: Credentials | None) -> list[dict[str, Any]]:
            found = api.collect(
                f"{api.repo_path(repo)}/actions/runs",
                query,
                key="workflow_runs",
                limit=_limit(args.max_rows),
                hint=hint,
                credentials=credentials,
            )
            return [flatten_workflow_run(w, repo) for w in found]

        _fan_out(params, batch, out, ["repo"], fetch, cache_ttl=args.cache_ttl)


KEYED_FUNCTIONS: list[type] = [
    RepoFunction,
    UserFunction,
    ReposFunction,
    IssuesFunction,
    PullsFunction,
    IssueCommentsFunction,
    CommitsFunction,
    ReleasesFunction,
    ContributorsFunction,
    LanguagesFunction,
    StargazersFunction,
    WorkflowRunsFunction,
]
