<p align="center">
  <a href="https://query.farm/vgi/">
    <img src="https://raw.githubusercontent.com/Query-farm/vgi-github/main/docs/vgi-logo.png" alt="Vector Gateway Interface logo" width="320">
  </a>
</p>

<h1 align="center">vgi-github</h1>

<p align="center">
  Query <a href="https://github.com">GitHub</a> with SQL in DuckDB — repositories, issues, pull requests,<br>
  commits, releases, contributors, CI runs, Projects and Discussions.<br>
  A <strong>read-only</strong> <a href="https://query.farm/vgi/">VGI</a> worker, built by <a href="https://query.farm">🚜 Query.Farm</a>
</p>

<p align="center">
  <a href="https://github.com/Query-farm/vgi-github/actions/workflows/ci.yml"><img src="https://github.com/Query-farm/vgi-github/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue.svg" alt="License: MIT"></a>
  <img src="https://img.shields.io/badge/python-3.13%2B-blue.svg" alt="Python 3.13+">
  <a href="https://query.farm/vgi/"><img src="https://img.shields.io/badge/VGI-Vector%20Gateway%20Interface-2f7d32.svg" alt="VGI"></a>
</p>

---

Ask GitHub questions in SQL and get tables back: compare projects, triage issues, measure how
fast pull requests get merged, see who contributes, track releases and CI health — across one
repository or a whole organization in a single query. It only ever reads; it never changes
anything on GitHub.

For approved business definitions, typed named reports and strict SQL, use the
[Crossfield semantic model](models/README.md). It covers the typed `main` functions,
including PR merge durations, issue state, CI reliability, Discussions and Projects.
Generated REST operations, `api.rest()` and `api.graphql()` are also available as raw
response detail; business metrics use the validated typed sources. Crossfield requires
the matching patched DuckDB 2.0 and native VGI build.

## Get started

You need [DuckDB](https://duckdb.org) (or [Haybarn](https://query.farm)) and
[uv](https://docs.astral.sh/uv/). Then, in DuckDB:

```sql
INSTALL vgi FROM community;   -- once per machine
LOAD vgi;

ATTACH 'github' (TYPE vgi,
  LOCATION 'uvx --from git+https://github.com/Query-farm/vgi-github@v0.1.0 vgi-github');

CREATE SECRET github (TYPE github, token 'ghp_...');   -- recommended, see "Use a token"
```

That's it — `uvx` downloads and runs the worker on first use.

```sql
SELECT full_name, stargazers_count, forks_count, language, license_spdx_id
FROM github.repo('duckdb/duckdb');
```

## What you can ask

### Explore projects

```sql
-- Compare projects side by side
SELECT r.full_name, r.stargazers_count, r.forks_count, r.open_issues_count, r.pushed_at
FROM (VALUES ('duckdb/duckdb'), ('pola-rs/polars'), ('apache/datafusion')) AS t(name),
     LATERAL github.repo(t.name) r
ORDER BY r.stargazers_count DESC;

-- Find popular projects on a topic, with GitHub's search syntax
SELECT full_name, stargazers_count, description
FROM github.search_repositories('topic:duckdb stars:>100', sort => 'stars')
LIMIT 10;
```

### Issues and pull requests

```sql
-- The most-wanted open feature requests and bugs, by thumbs-up
SELECT number, title, reactions_plus_one, html_url
FROM github.search_issues('repo:duckdb/duckdb is:issue is:open', sort => 'reactions-+1')
LIMIT 10;

-- What was reported this week
SELECT number, title, user_login, created_at
FROM github.issues('duckdb/duckdb', state => 'open',
                   since => strftime(now() - INTERVAL 7 DAY, '%Y-%m-%d'))
WHERE created_at > now() - INTERVAL 7 DAY
ORDER BY created_at DESC;

-- How quickly pull requests get merged
SELECT count(*) AS merged,
       median(date_diff('hour', created_at, merged_at)) AS median_hours_to_merge
FROM github.pulls('duckdb/duckdb', state => 'closed')
WHERE merged_at IS NOT NULL;
```

### People and activity

```sql
-- Top contributors, and where they say they work
SELECT c.login, c.contributions, u.name, u.company, u.location
FROM github.contributors('duckdb/duckdb', max_rows => 10) c,
     LATERAL github.user(c.login) u
ORDER BY c.contributions DESC;

-- Who committed in the last week
SELECT coalesce(author_login, author_name) AS author, count(*) AS commits
FROM github.commits('duckdb/duckdb',
                    since => strftime(now() - INTERVAL 7 DAY, '%Y-%m-%d'), max_rows => 500)
GROUP BY author
ORDER BY commits DESC;
```

### Releases and CI

```sql
-- Recent releases and their downloads
SELECT tag_name, published_at, download_count
FROM github.releases('duckdb/duckdb', max_rows => 10)
WHERE NOT is_prerelease
ORDER BY published_at DESC;

-- Which CI workflows fail most often
SELECT name AS workflow, count(*) AS runs,
       count(*) FILTER (WHERE conclusion = 'failure') AS failures
FROM github.workflow_runs('duckdb/duckdb', status => 'completed')
GROUP BY name
ORDER BY failures DESC;
```

### Across a whole organization

```sql
-- Open issues mentioning a topic, in every repository of an organization
SELECT repo, number, title, comments
FROM github.search_issues('org:duckdb is:issue is:open parquet', sort => 'comments')
LIMIT 10;

-- The languages an organization writes in
SELECT l.language, sum(l.bytes) AS bytes
FROM github.repos('duckdb', max_rows => 30) r,
     LATERAL github.languages(r.full_name) l
GROUP BY l.language
ORDER BY bytes DESC
LIMIT 10;
```

### Keep the results

Everything is an ordinary DuckDB result, so you can save it, join it with your own data, or
build a dashboard on it:

```sql
COPY (SELECT * FROM github.issues('duckdb/duckdb', state => 'open', max_rows => 0))
TO 'open_issues.parquet';

CREATE TABLE releases AS SELECT * FROM github.releases('duckdb/duckdb', max_rows => 0);
```

## What's available

Repositories are always written `'owner/name'`, and accounts by their login.

| Function | What you get |
|---|---|
| `search_repositories(query)` | Repositories matching a GitHub search, e.g. `'topic:sql stars:>500'` |
| `search_issues(query)` | Issues and pull requests matching a search, e.g. `'org:duckdb is:issue is:open'` |
| `repo('owner/name')` | One repository: stars, forks, language, license, activity |
| `repos('login')` | Every repository a user or organization owns |
| `user('login')` | A user or organization profile |
| `issues('owner/name')` | Issues (pull requests left out), newest first |
| `pulls('owner/name')` | Pull requests, with branches, draft status and merge time |
| `issue_comments('owner/name', number)` | The conversation on an issue or pull request |
| `commits('owner/name')` | Commit history |
| `releases('owner/name')` | Releases with download counts |
| `contributors('owner/name')` | Contributors, ranked by commits |
| `languages('owner/name')` | How much code is in each language |
| `stargazers('owner/name')` | Who starred and when (repositories you administer only) |
| `workflow_runs('owner/name')` | GitHub Actions runs and their outcomes |
| `discussions('owner/name')` | Typed discussions, categories, answer state and counts; GraphQL |
| `discussion_comments('owner/name', number)` | Top-level discussion comments; GraphQL |
| `discussion_replies(node_id)` | Replies to a discussion comment; GraphQL |
| `projects(owner)` | Projects v2 owned by an organization or user; REST |
| `project_items(owner, number)` | Project items with typed issue, PR and draft content; REST |
| `project_fields(owner, number)` | Project field IDs, names, types and options; REST |
| `rate_limit` | How many API requests you have left |

Every column is documented — `DESCRIBE github.issues('duckdb/duckdb')` shows what each one means.

### Discussions and Projects as SQL tables

Use these typed functions for everyday queries. They select the appropriate API and follow
pagination automatically; no GraphQL document or cursor handling is needed in SQL.
Discussions require GitHub credentials with access to the repository.

```sql
-- GitHub filters before the cap; most recently updated first by default
SELECT number, title, category_name, comments, upvote_count
FROM github.discussions('duckdb/duckdb', answered => false, max_rows => 20);

-- Comments on the five most recently updated discussions
SELECT d.title, c.node_id, c.user_login, c.body, c.replies
FROM github.discussions('duckdb/duckdb', max_rows => 5) d,
     LATERAL github.discussion_comments(d.repo, d.number, max_rows => 20) c;

-- Read a comment's replies with its node_id, preserving the parent link
SELECT reply_to_id, user_login, body
FROM github.discussion_replies('COMMENT_NODE_ID', max_rows => 100);

-- Organization Projects use REST
SELECT p.title AS project_title, i.content_type, i.title, i.state
FROM github.projects('github', query => 'is:open', max_rows => 5) p,
     LATERAL github.project_items(p.owner, p.number, max_rows => 100) i;

-- For personal projects use owner_type => 'user' on each function
SELECT number, title FROM github.projects('octocat', owner_type => 'user');

-- Discover custom field IDs, then select the values needed
SELECT id, name, data_type, options_json
FROM github.project_fields('OWNER', 7);

SELECT title, fields_json
FROM github.project_items('OWNER', 7, fields => '123,456');
```

All six functions default to 100 rows **per input key**. `max_rows => 0` follows every page,
bounded at 100 pages; if more remain the query fails. Discussion sorting supports
`sort => 'created'` or `'updated'` and `direction => 'asc'` or `'desc'`. Comments and replies
are separate connections with separate caps, in GitHub's connection order. Project listing
order is controlled by GitHub. Use the owner's project **number**, not the global project ID.

Project items retain rows with inaccessible content, with NULL content columns. Custom fields
vary by project, so their values remain in `fields_json`; without `fields`, GitHub returns only
the title field. `project_fields` provides the IDs, types, select options and iteration settings.
Errors, including permission failures and partial GraphQL errors, fail the query.
All six datasets support `reporting true` and the Crossfield model. Reporting requires
`max_rows => 0`, validates row identities, timestamps, counters and state before projection,
and disables result caching. Missing or inaccessible GraphQL resources raise errors;
a successfully empty connection remains an empty result. Project items with explicitly
inaccessible content remain valid items, with NULL content columns.

REST is the default for new typed datasets when it supplies the data. GraphQL fills coverage
gaps such as Discussions; the SQL interface remains typed either way. GitHub documents both
[Projects REST reads](https://docs.github.com/en/rest/projects) and
[Discussions GraphQL reads](https://docs.github.com/en/graphql/guides/using-the-graphql-api-for-discussions).

### Full read-only API coverage

The `main` functions above provide convenient typed tables. The `rest` schema additionally
exposes **780 distinct GET operations** from the pinned GitHub.com and Enterprise Cloud
OpenAPI descriptions (644 and 770 operations respectively, with overlap). This includes
reviews, files, branches, Actions jobs/logs/artifacts, checks, deployments, security alerts,
organization membership, enterprise administration, billing, packages and the other REST reads.

Discover operations, path arguments and query parameters without making an API request:

```sql
SELECT operation_id, function_name, path, parameters
FROM github.api.endpoints
WHERE category IN ('pulls', 'actions', 'code-scanning');
```

Function names come from GitHub's operation IDs with `/` and `-` replaced by `_`.
Path placeholders become positional arguments in their path order. Optional filters go in
the `query` JSON object. Each result row represents **one complete response page**, with
`data` containing the original JSON text, `body` containing the exact bytes, and
`status_code`, `content_type`, `page_number` and `next_url` describing the response.
Nested fields and large integer identifiers are preserved.

```sql
-- Reviews on one PR, expanded into ordinary SQL rows
SELECT review.value ->> 'state' AS review_state,
       review.value -> 'user' ->> 'login' AS reviewer
FROM github.rest.pulls_list_reviews('duckdb', 'duckdb', 1, max_pages => 0) page,
     LATERAL json_each(page.data) review;

-- Full PR details, including fields absent from the curated PR listing
SELECT data::JSON ->> 'mergeable_state', data::JSON ->> 'additions'
FROM github.rest.pulls_get('duckdb', 'duckdb', 1);

-- Private repositories accessible to the authenticated user
SELECT data
FROM github.rest.repos_list_for_authenticated_user(
  query => '{"visibility":"private","per_page":100}', max_pages => 0);

-- Every REST read is also available through the operation-ID dispatcher
SELECT data
FROM github.api.rest('actions/list-jobs-for-workflow-run',
  '{"owner":"OWNER","repo":"REPO","run_id":123}', query => '{"filter":"all"}');

-- Binary downloads and alternate media types use the same interface
SELECT body
FROM github.rest.pulls_get('duckdb', 'duckdb', 1, accept => 'application/vnd.github.diff');
```

The default is one page. A non-NULL `next_url` on the final row means more pages exist.
`max_pages => 0` follows all advertised next links, failing if the 100-page limit is reached.
GitHub's own search caps, tree truncation and endpoint-specific limits still apply; requesting
all pages cannot recover data GitHub does not serve. Complete search/tree requests reject
explicitly incomplete responses. Query parameters such as `page`, `before` and `after` can
also be supplied when supported by the endpoint. The Crossfield model provides raw detail
reports for the generated REST operations and dispatcher. Their grain is one response page,
including binary or empty responses; counting these rows counts pages, not GitHub entities.
Approved business metrics come from typed sources with defined populations and row identities.

Missing or forbidden resources raise errors. For endpoints where 404 is a useful negative
answer, such as membership checks, use `allow_not_found => true` and inspect `status_code`.
Some reads require specific token permissions or an Enterprise subscription. The generated
catalog uses API version `2026-03-10`; override `api_version` for a compatible Enterprise
Server. The inventory covers the pinned cloud specifications, not every historical
Enterprise Server release or future API addition.

The [API coverage workflow](.github/workflows/api-coverage.yml) checks upstream weekly and
reports added, removed or changed GET operations. It has read-only permissions and creates no
commits or pull requests. Maintainers can refresh the local snapshot with
`python scripts/generate_rest_catalog.py --revision latest`, review the diff and run the tests.
`--check-upstream` checks for drift without modifying files. The request API version remains
pinned unless explicitly updated with `--api-version`.

### Read-only GraphQL

`github.api.graphql(query, variables)` exposes all GraphQL query fields, including Discussions
and Projects. Both arguments support `LATERAL`; variables are a JSON object. Use
`operation_name => 'Name'` when a document contains multiple queries.

```sql
SELECT data::JSON -> 'data' -> 'repository' -> 'discussions'
FROM github.api.graphql(
  'query($owner:String!, $name:String!) {
     repository(owner:$owner, name:$name) {
       discussions(first:10) { nodes { number title } pageInfo { hasNextPage endCursor } }
     }
   }',
  '{"owner":"OWNER","name":"REPO"}');
```

Pagination is explicit: pass each connection's `endCursor` back through an `after` variable.
GraphQL responses containing errors fail the query, including partial-data responses.
The Crossfield raw GraphQL detail report preserves one response envelope per invocation.
It does not certify the completeness of nested connections or define entity metrics from JSON.
GraphQL uses GitHub's required HTTP POST transport, but a real GraphQL parser rejects
**all mutations and subscriptions before network access**, even unselected operations in
the same document. REST remains GET-only. No GitHub write operation is available.

## Good to know

- **Lists return 100 rows by default.** Functions like `issues` and `commits` fetch the newest 100
  rows per repository. Pass `max_rows => 500`, or `max_rows => 0` for everything (up to 10,000).
- **Filter with the function's own options.** `issues('owner/name', state => 'closed')` asks GitHub
  for closed issues; `WHERE state = 'closed'` only filters the 100 rows already fetched, and can
  come back empty. The same goes for `since =>`, `labels =>`, `branch =>` and `status =>`.
- **To rank across everything, use search.** "Most thumbs-up ever" is one `search_issues(...,
  sort => 'reactions-+1')` request rather than downloading every issue.
- **"Merged" is not a state.** A merged pull request is `closed` with a `merged_at` time.
- **Join many repositories with `LATERAL`.** Any function that takes `'owner/name'` can be fed from
  another query, as in the examples above.
- **A missing repository returns no rows**, rather than an error.

## See what it's doing

A query that waits out a GitHub rate limit just looks slow. Turn on DuckDB's logging to see why:
the worker reports every rate-limit wait and retry, warns when your remaining budget runs low, and
logs a one-line summary of each call.

```sql
SET enable_logging = true;
SET logging_level = 'INFO';        -- leave this out to see only warnings
SET logging_storage = 'memory';    -- keep the messages queryable

SELECT count(*) FROM github.languages('duckdb/duckdb');

SELECT timestamp, log_level, event AS message
FROM duckdb_logs_parsed('VGI')
WHERE event LIKE '%GitHub%'
ORDER BY timestamp;
```

```
INFO  1 GitHub request; core budget 4664/5000, resets 14:51:02 UTC
WARN  GitHub rate limited on /repos/duckdb/duckdb/issues; waiting 3s before retrying (attempt 2 of 5)
WARN  GitHub core budget is low: 42 of 5000 requests left, resets at 14:51:02 UTC
```

`SELECT * FROM github.rate_limit` shows your remaining budget at any time.

## Use a token

Without a token GitHub allows **60 requests an hour**, which a single query across a few
repositories can use up. With one you get **5,000**, and you can read private repositories you
have access to.

**Already logged in with the [GitHub CLI](https://cli.github.com)?** Tell the worker to use that
login when you attach:

```sql
ATTACH 'github' (TYPE vgi,
  LOCATION 'uvx --from git+https://github.com/Query-farm/vgi-github@v0.1.0 vgi-github',
  token_source 'gh');
```

`token_source 'env'` does the same with a `GH_TOKEN` or `GITHUB_TOKEN` environment variable. Either
way the token never appears in the `ATTACH` statement. By default these only work when DuckDB
starts the worker itself; a shared server (below) refuses them unless you turn them on.

Or create a token at **GitHub → Settings → Developer settings → Personal access tokens** (a
fine-grained token with read-only access is enough) and give it to DuckDB as a secret:

```sql
CREATE SECRET github (TYPE github, token 'github_pat_...');

SELECT resource, remaining, request_limit, authenticated FROM github.rate_limit;
```

Querying private repositories? Attach with `auth 'required'`, so a missing token is an error
instead of an empty result:

```sql
ATTACH 'github' (TYPE vgi,
  LOCATION 'uvx --from git+https://github.com/Query-farm/vgi-github@v0.1.0 vgi-github',
  auth 'required');
```

## Cache results

Set a default cache lifetime in seconds when you attach:

```sql
ATTACH 'github' (TYPE vgi, LOCATION 'uv run github_worker.py', cache_ttl 300);

SELECT * FROM github.repo('duckdb/duckdb'); -- inherits 300 seconds
SELECT * FROM github.repo('duckdb/duckdb', cache_ttl => 30); -- overrides the default
SELECT * FROM github.repo('duckdb/duckdb', cache_ttl => 0); -- uses GitHub's cache policy
```

This applies to lookups and searches. An omitted or NULL per-call TTL inherits the attach
setting. Positive TTLs override GitHub's freshness policy, including for authenticated results;
keyed lookups also memoize repeated input values. The default is 0: follow GitHub's cache
headers, leaving private responses out of the result cache. Zero does not disable the separate
ETag revalidation cache. `rate_limit` always fetches fresh data.

## Share one server with a team

Instead of every DuckDB starting its own worker, run one server and point everyone at it:

```bash
uvx --from git+https://github.com/Query-farm/vgi-github@v0.1.0 vgi-github-http --port 8000
```

```sql
INSTALL vgi FROM community;
LOAD vgi;
ATTACH 'github' (TYPE vgi, LOCATION 'http://localhost:8000');
CREATE SECRET github (TYPE github, token 'github_pat_...');   -- each person uses their own
```

Each person's token is used only for their own queries. A few things before sharing it beyond your
own machine:

- **The server doesn't check who is connecting.** Anyone who can reach the port can use it. Keep
  it on `localhost`, or put it behind something that handles access (a VPN, or a proxy with login).
- Use `--host 0.0.0.0` to accept connections from other machines, `--prefix /github` to serve it
  under a path, and `--http-threads 16` for many people at once.
- Don't set `VGI_GITHUB_TOKEN` on a shared server unless you want everyone without their own
  token to use yours.
- **Running the server just for yourself?** Start it with `VGI_GITHUB_ALLOW_TOKEN_SOURCE=1` and
  you can attach with `token_source 'gh'` instead of a secret. The token comes from the *server's*
  GitHub CLI login, so anyone else who can reach it would act as you too.

  ```bash
  VGI_GITHUB_ALLOW_TOKEN_SOURCE=1 uvx --from git+https://github.com/Query-farm/vgi-github@v0.1.0 vgi-github-http --port 8000
  ```

  ```sql
  ATTACH 'github' (TYPE vgi, LOCATION 'http://localhost:8000', token_source 'gh');
  ```

## GitHub Enterprise

Point the worker at your server with the `GITHUB_API_URL` environment variable
(`https://github.example.com/api/v3`), and scope your token to it:

```sql
CREATE SECRET ghe (TYPE github, token '...', SCOPE 'https://github.example.com');
```

## More

- [DEVELOPMENT.md](DEVELOPMENT.md) — how it works inside, running the tests, contributing
- [CHANGELOG.md](CHANGELOG.md) — what changed in each release

## License

Copyright © 2026 [Query Farm LLC](https://query.farm). Released under the **MIT License** — see
[LICENSE](LICENSE).

The data this worker returns belongs to GitHub, Inc. and its users and is subject to
[GitHub's terms of service](https://docs.github.com/site-policy/github-terms/github-terms-of-service).
See [NOTICE](NOTICE). This project is not affiliated with or endorsed by GitHub.

---

<p align="center">
  Built with <a href="https://query.farm/vgi/">VGI — the Vector Gateway Interface</a><br>
  by <a href="https://query.farm">🚜 Query.Farm</a>
</p>
