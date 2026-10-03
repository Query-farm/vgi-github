<p align="center">
  <a href="https://query.farm/vgi/">
    <img src="https://raw.githubusercontent.com/Query-farm/vgi-github/main/docs/vgi-logo.png" alt="Vector Gateway Interface logo" width="320">
  </a>
</p>

<h1 align="center">vgi-github</h1>

<p align="center">
  Query <a href="https://github.com">GitHub</a> with SQL in DuckDB — repositories, issues, pull requests,<br>
  commits, releases, contributors and CI runs.<br>
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
| `rate_limit` | How many API requests you have left |

Every column is documented — `DESCRIBE github.issues('duckdb/duckdb')` shows what each one means.

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
