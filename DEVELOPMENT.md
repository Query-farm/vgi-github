# Developing vgi-github

How the worker is built, and why. For using it, see the [README](README.md).

## Read-only, by construction

Every REST request goes through one `GET` chokepoint in
`github_api.py` — the only module in the package that imports `httpx`. The only POST is
GitHub's GraphQL query transport: `graphql_query()` first parses the entire document and
rejects every mutation, subscription and schema definition, including unselected operations.
It fixes the endpoint to the configured GitHub host and refuses redirects. A CI
guard (`tests/test_readonly_guard.py`) checks these transport boundaries. That
matters more here than on most APIs: GitHub's write endpoints share a host, a path and an
`Authorization` header with the reads, so a token with write scope would happily authorize a
`POST`. Names from user SQL are validated and percent-encoded so they cannot leave their path
segment, and pagination links — which are response *data* — are followed only while they stay
on the configured API origin, so a hostile `Link` header cannot walk the token off GitHub.

## Developing

```bash
git clone https://github.com/Query-farm/vgi-github
cd vgi-github

uv sync --all-extras     # Install dependencies
uv run pytest            # Offline suite, including every generated REST operation
uv run ruff check .      # Lint
```

Dependencies resolve from PyPI, so a fresh clone works with no sibling checkouts. To develop
against a local `vgi-python` or `vgi-rpc`, install them over the top rather than adding a path
source to the committed manifest:

```bash
uv pip install -e ../vgi-python -e ../vgi-rpc
```

## Function shapes

The curated `main` schema follows the contracts below. The generated `rest` schema
uses the same blended contract for operations with path parameters, and a single-worker
scan for operations without them. Results preserve whole response pages as JSON text
and bytes instead of flattening away fields. `api.rest()` dispatches only manifest GET
operation IDs; it cannot accept a URL or an HTTP method. `api.graphql()` accepts only
parsed queries and JSON variables. Both compose under `LATERAL`.

The checked-in `vgi_github/rest_manifest.json` is generated from GitHub's MIT-licensed
OpenAPI descriptions at a pinned revision. It includes source hashes and per-product
endpoint counts. There is no discovery-time network dependency. Regenerate or verify it:

```bash
python scripts/generate_rest_catalog.py
python scripts/generate_rest_catalog.py --check
```

`--source-dir` reads the two pinned source files locally. The manifest is the source of truth
for the pinned commit and request API version. To check upstream without writing files, run
`python scripts/generate_rest_catalog.py --check-upstream`. To refresh, run
`python scripts/generate_rest_catalog.py --revision latest`, or supply a full commit SHA.
The generator resolves `latest` once so both products use the same immutable commit; it reports
added, removed and changed operations. Review the manifest diff and run the offline suite and
catalog lint before accepting it. The request API version changes only with `--api-version`.
The read-only `api-coverage.yml` workflow verifies pinned generation on relevant PRs and checks
upstream weekly; drift fails the check without creating commits, issues or pull requests.
GET-only generation, unknown
operation rejection, encoded path parameters and the central HTTP boundary are independent
parts of the read-only contract. Query parameters are restricted to each operation's
published definitions. The additional functions do not expand the approved Crossfield model.

`tests/test_rest.py` drives every generated endpoint against a mock transport. It also
tests lossless binary and JSON responses, cursor preservation, ETags, token isolation on
download redirects and incomplete-result failures. `tests/test_graphql_reads.py` checks
parser-based mutation rejection and partial GraphQL errors. `tests/test_api_sql.py` runs
real SQL through the subprocess worker against a local fake GitHub server.

`datasets.py` adds six typed `main` functions: Projects, project items and field definitions
use REST; Discussions, comments and replies use GraphQL. Prefer REST for new typed datasets
when it supplies the needed data, and keep the transport behind typed columns and named filters.
GraphQL connection pagination is bounded, preserves opaque cursors, rejects malformed or repeated
cursors and fails on partial errors. Replies are a separate function so nested connection limits
cannot silently hide conversation data. Custom Project field values remain JSON because their
shape depends on each board. The new functions share keyed provenance and cache policy with
existing functions, but are excluded from the original Crossfield model and reject reporting mode.
`tests/test_datasets.py` covers these contracts; real subprocess SQL joins live in `test_api_sql.py`.

Functions come in two shapes, and the job decides which.

**Search is a streaming scan.** `search_repositories` and `search_issues` are where a question
*starts*, so they emit one page per tick with GitHub's `next` link held in scan state: rows
arrive immediately, and `LIMIT 10` costs one request of search's 30-a-minute budget rather than
ten. A streaming scan cannot be the inner side of a correlated `LATERAL` — drive a join *from*
it.

**Everything keyed is blended** (`RowTransformFunction`): its positional arguments *are*
per-row input columns, so one registration serves a literal call and a `LATERAL` alike.

| Function | Positional (per-row) | Named |
|---|---|---|
| `search_repositories(query)` *(scan)* | GitHub search syntax | `sort`, `order`, `cache_ttl` |
| `search_issues(query)` *(scan)* | GitHub search syntax | `sort`, `order`, `cache_ttl` |
| `repo(repo)` | `'owner/name'` | `cache_ttl` |
| `repos(owner)` | login | `type`, `sort`, `max_rows`, `cache_ttl` |
| `user(login)` | login | `cache_ttl` |
| `issues(repo)` | `'owner/name'` | `state`, `labels`, `since`, `include_pull_requests`, `max_rows`, `cache_ttl` |
| `pulls(repo)` | `'owner/name'` | `state`, `base`, `max_rows`, `cache_ttl` |
| `issue_comments(repo, number)` | both | `max_rows`, `cache_ttl` |
| `commits(repo)` | `'owner/name'` | `sha`, `path`, `author`, `since`, `until`, `max_rows`, `cache_ttl` |
| `releases(repo)` | `'owner/name'` | `max_rows`, `cache_ttl` |
| `contributors(repo)` | `'owner/name'` | `max_rows`, `cache_ttl` |
| `languages(repo)` | `'owner/name'` | `cache_ttl` |
| `stargazers(repo)` | `'owner/name'` | `max_rows`, `cache_ttl` |
| `workflow_runs(repo)` | `'owner/name'` | `branch`, `event`, `status`, `max_rows`, `cache_ttl` |

A repository is always one string, `'owner/name'`, and every row that belongs to one carries it
in a `repo` (or `full_name`) column. That is the whole composition story — the output of any
function is the input of the next:

```sql
-- Where a project's top contributors say they work
SELECT c.login, c.contributions, u.company, u.location
FROM github.contributors('duckdb/duckdb', max_rows => 10) c,
     LATERAL github.user(c.login, cache_ttl => 3600) u
ORDER BY c.contributions DESC;

-- The conversation on the most discussed recent issue — a two-column key
SELECT c.user_login, c.created_at, left(c.body, 80) AS excerpt
FROM (SELECT repo, number FROM github.issues('duckdb/duckdb', max_rows => 20)
      ORDER BY comments DESC LIMIT 1) i,
     LATERAL github.issue_comments(i.repo, i.number) c;

-- CI failure rate per workflow
SELECT name, count(*) FILTER (WHERE conclusion = 'failure') / count(*) AS failure_rate
FROM github.workflow_runs('duckdb/duckdb', status => 'completed')
GROUP BY name ORDER BY failure_rate DESC;
```

Output rows carry `parent_rows` provenance back to the input row that produced them, so
correlated columns line up; a key repeated within one input batch is fetched once.

## Design notes

**Every list function is capped, at 100 rows per input row by default.** A blended function has
to emit everything for its input in one `process()` call, and a call blocked inside its first
batch cannot be cancelled. On a paged endpoint, an uncapped walk is therefore not merely slow —
it *wedges the client* until it finishes. `max_rows` defaults to 100, which is exactly one
request per input row, newest first; `max_rows => 0` walks to the end, bounded at 10,000 rows,
past which it raises `GitHubPageLimitError` rather than returning a prefix that reads like a
complete result. `vgi-lint`'s VGI911 caught an example that broke this rule — an uncapped walk
of every open issue in `duckdb/duckdb` — before it shipped.

**Filter with arguments, not `WHERE`.** DuckDB does not push a `WHERE` clause into a
table-in-out function — `EXPLAIN` shows the `FILTER` sitting above the scan — so a predicate
only filters rows already fetched, and cannot reach past `max_rows`:

```sql
-- Wrong: only the closed ones among the 100 newest issues — 18 rows when this was written
SELECT * FROM github.issues('duckdb/duckdb') WHERE state = 'closed';

-- Right: GitHub filters before the cap
SELECT * FROM github.issues('duckdb/duckdb', state => 'closed');
```

| Function | Filters GitHub applies before the cap |
|---|---|
| `issues` | `state`, `labels`, `since`, `include_pull_requests` |
| `pulls` | `state`, `base` |
| `commits` | `sha`, `path`, `author`, `since`, `until` |
| `repos` | `type`, `sort` |
| `workflow_runs` | `branch`, `event`, `status` — a lifecycle status *or* a conclusion such as `'failure'` |
| `search_*` | everything: put qualifiers (`org:`, `label:`, `is:open`, `stars:>1000`) in the query |

This was found the hard way. An early build declared filter pushdown on the blended functions and
translated `WHERE state = ...` into GitHub's `state` parameter; the translation never ran,
because the filter never arrived, and `WHERE state = 'closed'` returned nothing at all.

**To rank a whole history, let search rank it.** "The most thumbs-up open issues ever" is not a
job for `max_rows => 0` over thousands of issues — it is one request:

```sql
SELECT number, title, reactions_plus_one
FROM github.search_issues('repo:duckdb/duckdb is:issue is:open', sort => 'reactions-+1')
LIMIT 10;
```

**`issues()` is issues.** GitHub's issue listing returns pull requests too. They are dropped by
default and `max_rows` counts only the issues kept; `include_pull_requests => true` keeps them,
flagged by `is_pull_request`. `state` defaults to `all` rather than GitHub's own `open`, so an
unfiltered call means what an unfiltered `SELECT` means.

**Merged is not a state.** A merged pull request has `state = 'closed'` and a non-NULL
`merged_at`; one closed unmerged has `merged_at` NULL.

```sql
SELECT median(date_diff('hour', created_at, merged_at)) AS median_hours_to_merge
FROM github.pulls('duckdb/duckdb', state => 'closed')
WHERE merged_at IS NOT NULL;
```

**A key that names nothing yields no rows, not an error.** A deleted repository, a private one
read without a token, an empty repository's commits (GitHub answers 409) — each produces zero
rows for that input row, so one bad name does not sink a whole `LATERAL`. A *missing page
mid-walk* is still an error: the object existed a moment ago, and a short result would look
whole.

**`stargazers()` only works on repositories you administer.** GitHub restricts the listing: for
anyone else's repository it refuses even though the repository plainly exists — 404 for a user
token, 403 for a GitHub App or Actions token, 401 anonymously. An empty result would read as "no stars", so this one function raises an
explanatory error instead. `repo()` still reports `stargazers_count` for any repository. Note
also that stargazers are listed oldest first, so the default cap returns the *first* hundred.

**Next links are followed by origin, not by path.** A repository's issues page hands back a
`next` link to `/repositories/{id}/issues?...&after=<cursor>` — not the path that was asked for
— so the check is that the link stays on the configured API scheme, host and path prefix.
Following it also has to preserve its query exactly: httpx *replaces* a URL's query string when
handed `params`, even an empty list, which silently turned page two of `state=closed` into page
one of open issues. `tests/test_api.py` pins both.

**GitHub's own quirks are kept, and documented on the column.** `open_issues_count` counts open
pull requests too; `watchers_count` is really the star count; a renamed repository redirects and
`repo()` returns its *current* `full_name`.

**Blended-function constraints.** Positional args are read off `batch`, not `params.args`; a
positional `const` arg is rejected, so every optional knob is a named arg; and no function may
define `finalize`/`finish`, because DuckDB forbids `FinalExecute` under correlated `LATERAL`. A
named argument cannot receive a correlated column either — `LATERAL f(x => t.col)` does not bind
— so pass a literal or a scalar subquery.

## Caching and rate limits

GitHub publishes generous headers and the worker uses all of them.

**Conditional requests.** Every response carries an `ETag`, and a `304 Not Modified` to an
authorized request is not charged against the primary rate limit. The worker keeps a bounded,
in-process cache of `(request, token) → (ETag, body)` and revalidates instead of refetching. A
`LATERAL` over five repositories charged 19 requests on its first run and **0** on a repeat
served by the same worker process. The cache is per process and the extension keeps a small pool
of them, so a repeat that lands on a cold process pays once. Entries are partitioned by a hash
of the token — a body fetched with one token is never replayed to another, or to an anonymous
caller — and bodies are re-decoded on every hit, so mutating rows cannot corrupt the cache.

**Result cache.** GitHub's `Cache-Control` is forwarded to DuckDB's result cache rather than
invented. Anonymous responses say `public, max-age=60` and are cached for 60 seconds.
Authenticated responses say `private` — what a token can see is specific to it — and a
`private` response is not reusable by a shared cache, so they are not cached unless you pass
`cache_ttl => N` or set `cache_ttl N` on ATTACH. Positive TTLs override GitHub's freshness
policy and enable per-value memoization for keyed lookups in a `LATERAL` that repeats keys.
Search scans use the same TTL policy without per-value memoization. An omitted or NULL
function TTL inherits the attach default; an explicit `cache_ttl => 0` uses GitHub's policy
even when ATTACH sets a positive TTL. The attach default is 0, preserving existing behavior.
`rate_limit` is always uncached.

**Rate limits.** GitHub says when you may retry, and the worker listens: `Retry-After` on a
secondary limit, `X-RateLimit-Remaining: 0` plus the reset epoch on the primary one. A wait of up
to 15 seconds is slept through; anything longer fails at once with the reset time and, for an
anonymous caller, how to authenticate. Fifteen seconds is deliberately short — the sleep happens
inside an uncancellable `process()` call, and even search's one-minute window is too long to
block a client for. Transient 5xx responses and dropped connections are retried with exponential
backoff.

| Budget | Anonymous | With a token |
|---|---|---|
| `core` — everything but search | 60 / hour | 5,000 / hour |
| `search` | 10 / minute | 30 / minute |

```sql
SELECT resource, remaining, request_limit, reset_at, authenticated FROM github.rate_limit;
```

## Catalog metadata

VGI Python 0.40.0 enables `catalog_contents`: clients supporting VGI protocol 2.1.0
can load all schemas, tables, functions, and their metadata in one RPC after ATTACH.
`GitHubCatalog` inherits this capability from `ReadOnlyCatalogInterface`; the existing
per-schema APIs remain available. Its catalog version stays frozen at 1.

We set `catalog_contents_attach_independent = False` because serialized schema records
include each attachment's auth mode, token source, and default cache TTL. Reusing VGI's
default shared snapshot would give later clients the first attachment's settings.
Bulk discovery reads only local declarations and makes no GitHub API requests.

Everything a client sees on `ATTACH` — object descriptions, column comments, result schemas,
examples, categories, agent test tasks — is published as `vgi.*` tags and checked by
[vgi-lint](https://github.com/Query-farm/vgi-lint-check):

```bash
vgi-lint lint                     # config lives in vgi-lint.toml
vgi-lint lint --audit-waivers     # prove the waivers still buy something
```

Agent task metadata contains only names and prompts. Reference SQL and grading criteria
live in `vgi-agent-tests.yaml`, which vgi-lint discovers beside `vgi-lint.toml`.

The structural tier validates the catalog and its documented exemptions. The behavioural tier
executes curated examples against the live API; generated endpoint coverage is exercised
with mock responses so it does not require access to every GitHub product and private resource.

Column documentation has a single source: `vgi_github/schemas.py` attaches a comment to every
Arrow field via `meta.field()`, and `meta.result_columns_schema()` reads those same strings back
out to build each function's declared result schema. A column documented once shows up in
`DESCRIBE`, in `duckdb_columns()` and in `vgi.result_columns_schema`, and cannot drift between
them.

Waivers live in `vgi-lint.toml`, each with a recorded kind and reason that
`--audit-waivers` re-checks. VGI311 asks that a parameterless scan be exposed as a table, which
`all_rate_limit` is — as `rate_limit`; the rule matches on name, and a function and a table
cannot share one. Two are on `stargazers`, and both come from GitHub listing
stargazers only to tokens that administer the repository: no agent test task can be written
that every caller's credentials can complete (VGI520), and VGI911's bare-`LIMIT` probe sees the
function's deliberate error for any token without that access — CI's workflow token included.

Generated REST bindings have two further exemptions: examples and analytical agent tasks
cannot be portable across hundreds of account-specific resources and product permissions.
The dispatcher and discovery have examples and agent tasks; every generated operation has
an offline transport test. The endpoint inventory also has an exemption from the rule
against duplicating `duckdb_functions()`: it supplies upstream paths, operation IDs, product
availability and query-parameter schemas required by generic dispatch.

## CI

CI and Live set `UV_PYTHON=3.14` for dependency installation, tools and standalone scripts.
The locked PyArrow, DuckDB and Haybarn releases have Linux wheels for that interpreter;
allowing uv to select Python 3.15 instead triggers unsupported source builds.

`.github/workflows/ci.yml` runs on every push: ruff (lint and format), the offline tests, a check
that both entry-point scripts start without the dev checkouts, and `vgi-lint`'s structural tier
with `--audit-waivers --fail-on warning`. All of it resolves from PyPI (`UV_NO_SOURCES=1`), so it
also proves the published dependencies are sufficient.

`.github/workflows/live.yml` runs daily, never concurrently, and is the half that touches GitHub:
live checks of GitHub's own behaviour, the end-to-end SQL suite against a real `ATTACH`, the
same worker served over HTTP to several
clients at once, then `vgi-lint --execute`, which runs every
shipped example. It authenticates with the workflow's own read-only `GITHUB_TOKEN`, passed as
`VGI_GITHUB_TOKEN`.

It earns its keep. The live tier found, in this worker's first day, a token that never reached
the functions, a `WHERE` that DuckDB never pushed down, pagination that dropped its own filters,
and an example that wedged the client — none of which an offline test could see.

## Tests

```bash
uv run pytest                                            # Offline tests
VGI_GITHUB_TOKEN=$(gh auth token) uv run pytest -m live    # 48 tests against the real API
```

`tests/test_live.py` pins the GitHub behaviour the design rests on, with no DuckDB involved:
`next` links pointing at `/repositories/{id}` and carrying their query, page size capped at 100,
search answering page 11 with a 422, the issue listing mixing in pull requests, a `304` not being
charged, authenticated responses being `private`, and stargazer listings being refused for other
people's repositories. If GitHub changes one of these, this tier goes red before a user sees a
wrong answer.

`tests/test_functions.py` drives every function's `process()` as DuckDB would — a batch of input
rows in, one batch with provenance out — against a mock GitHub. `tests/test_api.py` pins the
chokepoint: retries, rate-limit waits, origin-checked `next` links, the query string surviving a
followed link, and token-partitioned ETags. `tests/test_auth.py` covers secret selection by type
and scope, and that an ambient `GITHUB_TOKEN` is never borrowed. `tests/test_http_transport.py`
serves the worker over HTTP and attaches several clients to one server — the server holds no
token of its own, so it checks that a client's secret crosses the wire, and that it never
authorizes another client: an anonymous client stays anonymous even after a token client has
warmed every server-side cache, and with `VGI_GITHUB_PRIVATE_REPO` set it checks a private
repository stays invisible to the anonymous one. `tests/test_packaging.py`
checks the entry-point scripts' PEP-723 headers still cover every runtime dependency — they
resolve independently of `pyproject.toml`, so they drift silently and only an end-to-end
`ATTACH` notices.
