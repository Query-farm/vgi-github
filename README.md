<p align="center">
  <a href="https://query.farm/vgi/">
    <img src="https://raw.githubusercontent.com/Query-farm/vgi-github/main/docs/vgi-logo.png" alt="Vector Gateway Interface logo" width="320">
  </a>
</p>

<h1 align="center">vgi-github</h1>

<p align="center">
  <a href="https://github.com">GitHub</a> as ordinary DuckDB tables — repositories, issues, pull requests,<br>
  commits, releases, contributors and Actions runs, joined with <code>LATERAL</code>.<br>
  A <strong>read-only</strong> <a href="https://query.farm/vgi/">VGI</a> worker, built by <a href="https://query.farm">🚜 Query.Farm</a>
</p>

<p align="center">
  <a href="https://github.com/Query-farm/vgi-github/actions/workflows/ci.yml"><img src="https://github.com/Query-farm/vgi-github/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue.svg" alt="License: MIT"></a>
  <img src="https://img.shields.io/badge/python-3.13%2B-blue.svg" alt="Python 3.13+">
  <a href="https://query.farm/vgi/"><img src="https://img.shields.io/badge/VGI-Vector%20Gateway%20Interface-2f7d32.svg" alt="VGI"></a>
</p>

---

```sql
-- Open issues across an organization's five most-starred repositories, in one query
SELECT r.full_name, count(i.number) AS open_issues
FROM (SELECT full_name FROM github.search_repositories('org:duckdb', sort => 'stars') LIMIT 5) r,
     LATERAL github.issues(r.full_name, state => 'open') i
GROUP BY r.full_name
ORDER BY open_issues DESC;
```

> **Read-only, by construction.** Every request goes through one `GET` chokepoint in
> `github_api.py` — the only module in the package that so much as imports `httpx` — and a CI
> guard (`tests/test_readonly_guard.py`) fails the build if a write verb appears anywhere. That
> matters more here than on most APIs: GitHub's write endpoints share a host, a path and an
> `Authorization` header with the reads, so a token with write scope would happily authorize a
> `POST`. Names from user SQL are validated and percent-encoded so they cannot leave their path
> segment, and pagination links — which are response *data* — are followed only while they stay
> on the configured API origin, so a hostile `Link` header cannot walk the token off GitHub.

## Run

```bash
uv run github_worker.py            # stdio
uv run serve.py --port 8000        # HTTP
```

```sql
ATTACH 'github' (TYPE vgi, LOCATION 'uv run github_worker.py');
CREATE SECRET github (TYPE github, token 'ghp_...');   -- optional; see Authentication
```

Both scripts carry PEP-723 headers pinning their dependencies, so they run from a fresh clone
with nothing installed. That `LOCATION` resolves `github_worker.py` against the working
directory, though, so it only works from inside the clone.

Anywhere else, point the `LOCATION` at this repository directly. `uvx` fetches and caches the
worker on first use — nothing to install, and the working directory stops mattering:

```sql
ATTACH 'github' (TYPE vgi,
  LOCATION 'uvx --from git+https://github.com/Query-farm/vgi-github vgi-github');
```

**This package is not published to PyPI** — install it from this repository. Its
*dependencies* are all published, so `uvx` resolves them normally.

To run the worker as a server and attach to a URL instead, `vgi-github-http` is the HTTP entry
point:

```sql
ATTACH 'github' (TYPE vgi, LOCATION 'http://localhost:8000');
```

The catalog must be attached as `github` — that is the name the worker exposes.

### Developing

```bash
git clone https://github.com/Query-farm/vgi-github
cd vgi-github

uv sync --all-extras     # Install dependencies
uv run pytest            # 126 offline tests
uv run ruff check .      # Lint
```

Dependencies resolve from PyPI, so a fresh clone works with no sibling checkouts. To develop
against a local `vgi-python` or `vgi-rpc`, install them over the top rather than adding a path
source to the committed manifest:

```bash
uv pip install -e ../vgi-python -e ../vgi-rpc
```

## Surface

Names are bare — they are already qualified by the `github` catalog. Every column carries a
comment, so `DESCRIBE github.issues('duckdb/duckdb')` or `duckdb_columns()` says what each one
means.

### Table

| Table | |
|---|---|
| `rate_limit` | One row per API budget: limit, used, remaining, reset — and whether a token is in use |

### Functions

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
| `search_repositories(query)` *(scan)* | GitHub search syntax | `sort`, `order` |
| `search_issues(query)` *(scan)* | GitHub search syntax | `sort`, `order` |
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
anyone else's repository it answers 404 even though the repository plainly exists (401
anonymously). An empty result would read as "no stars", so this one function raises an
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
`cache_ttl => N`, which also turns on per-value memoization for a `LATERAL` that repeats keys.

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

## Authentication (optional, and usually worth it)

Unlike most public APIs, GitHub's anonymous budget is tiny: 60 requests an hour per IP, shared
by everything on that IP. A `LATERAL` issues at least one request per input row, so one modest
query can spend the hour. A token raises it to 5,000 and is the only way to read a private
repository.

Credentials are a **DuckDB secret**, not an ATTACH option, because ATTACH strings show up in
`duckdb_databases()`:

```sql
CREATE SECRET github (TYPE github, token 'ghp_...');

-- In the DuckDB CLI, straight from the environment:
CREATE SECRET github (TYPE github, token getenv('GITHUB_TOKEN'));
```

Any bearer token GitHub accepts works — a classic or fine-grained personal access token, the
OAuth token `gh auth token` prints, or a GitHub App installation token — and read-only scopes are
enough. `token` is declared redacted, so `duckdb_secrets()` masks it.

**The secret can have any name.** The framework keys resolved secrets by name, not by type, so
the worker selects by each secret's `type` field — an early build looked the secret up by type
string, found it only when it happened to be named `github`, and silently ran everything else
anonymously. (The same bug was then found, and fixed, in vgi-kalshi.)

**GitHub Enterprise Server.** Point the worker at your server with `GITHUB_API_URL`
(`https://ghe.example.com/api/v3`, the variable GitHub Actions itself sets), and scope its secret.
When several `github` secrets exist, the one whose `SCOPE` is the longest prefix of the API URL
wins, and an unscoped one is the fallback:

```sql
CREATE SECRET ghe (TYPE github, token '...', SCOPE 'https://ghe.example.com');
```

One ATTACH option decides what happens when no secret resolves:

```sql
ATTACH 'github' (TYPE vgi, LOCATION 'uv run github_worker.py', auth 'required');
```

| `auth` | behaviour |
|---|---|
| `auto` *(default)* | authenticate when a secret resolves, go anonymous otherwise |
| `required` | fail the query when no credential resolves |
| `off` | never authenticate, even if a secret exists |

Use `required` whenever you query private repositories. GitHub answers an unauthorized read of a
private repository with 404, so an anonymous query does not fail — it returns *no rows*, which
reads exactly like an empty repository.

**Operator token.** If `VGI_GITHUB_TOKEN` is set in the worker's environment, it is used when no
secret resolves. It exists for CI and `vgi-lint`, which cannot run `CREATE SECRET` before a
query. It is deliberately *not* the ambient `GITHUB_TOKEN` or `GH_TOKEN`: on an HTTP-served
worker every caller inherits the operator token's identity and private-repository access, so it
has to be set on purpose, never inherited from a developer's shell.

Authenticating stays read-only: it adds one `Authorization` header to a `GET`, and httpx drops
that header on any cross-origin redirect.

## Catalog metadata

Everything a client sees on `ATTACH` — object descriptions, column comments, result schemas,
examples, categories, agent test tasks — is published as `vgi.*` tags and checked by
[vgi-lint](https://github.com/Query-farm/vgi-lint-check):

```bash
vgi-lint lint                     # config lives in vgi-lint.toml
vgi-lint lint --audit-waivers     # prove both waivers still buy something
```

The catalog scores 99/100 with no findings, structural and behavioural — the behavioural tier
executes every documented example against the live API.

Column documentation has a single source: `vgi_github/schemas.py` attaches a comment to every
Arrow field via `meta.field()`, and `meta.result_columns_schema()` reads those same strings back
out to build each function's declared result schema. A column documented once shows up in
`DESCRIBE`, in `duckdb_columns()` and in `vgi.result_columns_schema`, and cannot drift between
them.

Two rules are waived in `vgi-lint.toml`, each with a recorded kind and reason that
`--audit-waivers` re-checks. VGI311 asks that a parameterless scan be exposed as a table, which
`all_rate_limit` is — as `rate_limit`; the rule matches on name, and a function and a table
cannot share one. VGI520 asks for an agent test task on `stargazers`, which cannot be written
portably: the listing needs admin access to the repository.

## CI

`.github/workflows/ci.yml` runs on every push: ruff (lint and format), the offline tests, a check
that both entry-point scripts start without the dev checkouts, and `vgi-lint`'s structural tier
with `--audit-waivers --fail-on warning`. All of it resolves from PyPI (`UV_NO_SOURCES=1`), so it
also proves the published dependencies are sufficient.

`.github/workflows/live.yml` runs daily, never concurrently, and is the half that touches GitHub:
the end-to-end SQL suite against a real `ATTACH`, then `vgi-lint --execute`, which runs every
shipped example. It authenticates with the workflow's own read-only `GITHUB_TOKEN`, passed as
`VGI_GITHUB_TOKEN`.

It earns its keep. The live tier found, in this worker's first day, a token that never reached
the functions, a `WHERE` that DuckDB never pushed down, pagination that dropped its own filters,
and an example that wedged the client — none of which an offline test could see.

## Tests

```bash
uv run pytest                                              # 126 offline tests
VGI_GITHUB_TOKEN=$(gh auth token) uv run pytest -m live    # 20 tests against a real ATTACH
```

`tests/test_functions.py` drives every function's `process()` as DuckDB would — a batch of input
rows in, one batch with provenance out — against a mock GitHub. `tests/test_api.py` pins the
chokepoint: retries, rate-limit waits, origin-checked `next` links, the query string surviving a
followed link, and token-partitioned ETags. `tests/test_auth.py` covers secret selection by type
and scope, and that an ambient `GITHUB_TOKEN` is never borrowed. `tests/test_packaging.py`
checks the entry-point scripts' PEP-723 headers still cover every runtime dependency — they
resolve independently of `pyproject.toml`, so they drift silently and only an end-to-end
`ATTACH` notices.

## License

Copyright © 2026 [Query Farm LLC](https://query.farm)

Released under the **MIT License** — see [LICENSE](LICENSE).

The data this worker returns belongs to GitHub, Inc. and its users, is not covered by that
license, and is subject to
[GitHub's terms of service](https://docs.github.com/site-policy/github-terms/github-terms-of-service).
See [NOTICE](NOTICE). This project is not affiliated with or endorsed by GitHub.

---

<p align="center">
  Built with <a href="https://query.farm/vgi/">VGI — the Vector Gateway Interface</a><br>
  by <a href="https://query.farm">🚜 Query.Farm</a>
</p>
