# GitHub reporting with Crossfield

This model covers the original 15 `main` functions: 34 approved metrics, 32 named
reports, and the complete detail schemas, including array columns. Business
definitions live in [build_model.py](build_model.py); [source_inventory.json](source_inventory.json)
records the worker signatures and field descriptions. The generated
[package](github-reporting.package.json) contains the model, named parameters,
comments and revision together.

Start with `engineering.semantic.github_reporting(repository => 'owner/repo')`:
choose approved metrics, dimensions and filters in ordinary SQL. Named reports
remain available for reusable presentations and complete detail rows.

Use the matching patched DuckDB 2.0 engine, Crossfield and native VGI extensions.
The community VGI binary for another DuckDB release is not compatible. This
profile uses a local subprocess; HTTP transport has not been qualified here.

## Attach and discover

Run from this checkout. Replace the worker project path with its absolute path:

```sql
LOAD vgi;
LOAD crossfield;
SET TimeZone = 'UTC';

ATTACH 'github' AS github_source (
  TYPE vgi,
  LOCATION 'uv run --project /absolute/path/to/vgi-github vgi-github',
  token_source 'gh', auth 'required',
  reporting true, operation_timeout_seconds 120
);

ATTACH 'models/github-reporting.package.json' AS engineering (
  TYPE crossfield,
  BINDINGS '{"github_source":{"catalog":"github_source","provider_id":"queryfarm.vgi.github","instance_id":"github.com"}}'
);
SET crossfield_mode = 'strict';

SELECT name, sql_name, comment FROM crossfield_members()
WHERE database_name = 'engineering';

SELECT name, type, nullable, comment, source_datasets, metric_names
FROM crossfield_parameters()
WHERE database_name = 'engineering';
```

The logical binding `github_source` is independent of the attachment alias.
The model requires the attachment's reporting policy, 120-second worker budget
and API origin to match. The package scopes identities to `github.com`; generate
a separately reviewed package for another instance. A token, credentials and
private repository names are never stored in the model.

## Choose metrics and dimensions

```sql
SELECT
    pulls_user_login AS author,
    merged_prs,
    median_merge_hours,
    p90_merge_hours
FROM engineering.semantic.github_reporting(
    repository => 'Query-farm/crossfield'
)
WHERE pulls_merged_day >= DATE '2026-09-01'
  AND pulls_merged_day < DATE '2026-10-01'
GROUP BY pulls_user_login
ORDER BY author;

-- Remove the author dimension to calculate repository totals from the same
-- approved measures. Percentiles are recomputed across the full cohort.
SELECT merged_prs, mean_merge_hours, median_merge_hours, p90_merge_hours
FROM engineering.semantic.github_reporting(repository => 'Query-farm/crossfield')
WHERE pulls_merged_day >= DATE '2026-09-01'
  AND pulls_merged_day < DATE '2026-10-01';

EXPLAIN (SEMANTIC)
SELECT merged_prs, median_merge_hours
FROM engineering.semantic.github_reporting(repository => 'Query-farm/crossfield');

EXPLAIN (SQL)
SELECT merged_prs, median_merge_hours
FROM engineering.semantic.github_reporting(repository => 'Query-farm/crossfield');
```

The cohort is **merge time in `[start_day, end_day)` in UTC**. Bots remain
included. Elapsed hours use millisecond differences divided by 3,600,000, so
draft and waiting time count. This is not review time or business hours.
Four merge durations of 2, 4, 10 and 20 hours produce **4 merged PRs, mean 9,
median 7 and continuous p90 17**. Empty cohorts return `0, NULL, NULL, NULL`.
By author, durations 2 and 10 produce median 6 and p90 9.2; durations 4 and 20
produce median 12 and p90 18.4. Do not average grouped means or percentiles to
recover a total: remove the dimension and let Crossfield recompute it.

Parameters select provider inputs; SQL `WHERE` defines the analytical cohort.
Only inputs needed by the selected source dependencies are required:

| Input | SQL type | Used by |
| --- | --- | --- |
| `repository` | `VARCHAR` | Repository metrics, PRs, issues, comments, commits, releases, contributors, languages, stargazers and CI. |
| `owner` | `VARCHAR` | `repository_count`, the visible owned-repository count for an account. |
| `issue_number` | `BIGINT` | `issue_comment_count`, together with `repository`. |

```sql
SELECT repository_count
FROM engineering.semantic.github_reporting(owner => 'Query-farm');

SELECT issue_comment_count
FROM engineering.semantic.github_reporting(
    repository => 'Query-farm/crossfield', issue_number => 1
);

-- Independent PR and workflow facts aggregate before combination at the
-- requested repository; raw PR rows never multiply raw workflow rows.
SELECT repository_input_repo AS repository,
       merged_prs, workflow_run_count, ci_success_rate
FROM engineering.semantic.github_reporting(repository => 'Query-farm/crossfield')
GROUP BY repository_input_repo;
```

Calls accept named literals or native prepared parameters. Unknown, missing,
unused, NULL and incorrectly typed inputs reject with repair guidance. For
example, supplying `owner` to a PR-only query rejects; it cannot silently look
like an extra filter. Callers cannot override complete pagination or cache policy.
Crossfield invokes only required sources, so PR metrics do not fetch CI,
comments or account data. Discovery, preparation and `EXPLAIN` do not fetch rows.
CTEs and prepared queries use the same callable entry:

```sql
PREPARE merges AS
SELECT merged_prs, median_merge_hours, p90_merge_hours
FROM engineering.semantic.github_reporting(repository => $1)
WHERE pulls_merged_day >= $2::DATE AND pulls_merged_day < $3::DATE;
EXECUTE merges('Query-farm/crossfield', '2026-09-01', '2026-10-01');

WITH merges AS (
    SELECT merged_prs
    FROM engineering.semantic.github_reporting(repository => 'Query-farm/crossfield')
    WHERE pulls_merged_day >= DATE '2026-09-01'
      AND pulls_merged_day < DATE '2026-10-01'
)
SELECT merged_prs FROM merges;
```

## Saved reports and detail

Saved reports package a model-owned selection and presentation. Their parameter
contract is fixed; every declared argument is required. SQL date literals may be
ISO strings, and prepared arguments use the declared DATE type. Empty or reversed
intervals retain ordinary SQL empty-cohort semantics.

```sql
SELECT * FROM crossfield_queries() WHERE database_name = 'engineering';
SELECT * FROM crossfield_query_parameters()
WHERE database_name = 'engineering' AND query_name = 'pr_merge_summary';

SELECT * FROM engineering.reports.pr_merge_summary(
  repository => 'Query-farm/crossfield',
  start_day => '2026-09-01', end_day => '2026-10-01'
);

SELECT * FROM engineering.reports.merged_pr_detail(
  repository => 'Query-farm/crossfield',
  start_day => '2026-09-01', end_day => '2026-10-01'
);
```

The detail report returns the same merged population, preserving each PR identity.
`pr_merges_daily` groups by UTC merge date; absent dates stay absent.

## Reporting coverage

| Reports | Definition |
| --- | --- |
| `pr_overview`, `pr_merge_summary`, `pr_merges_daily`, `pr_merges_by_author`, `merged_pr_detail` | Complete PR listing, current state or explicitly selected merge-date cohort. |
| `issue_backlog`, `issue_closure_summary` | Issues exclude PRs. Backlog is current; closure duration uses the currently recorded closure, including any reopening history in elapsed time. |
| `ci_summary`, `ci_by_workflow` | Runs created in the UTC interval, using each run's latest reported attempt. Reliability is success / (success + failure + timed_out); cancellation/skipped/other outcomes are excluded; zero denominator is NULL. |
| `repository_activity` | Complete PR and CI populations independently aggregate at requested repository before combination. All visible history and current outcomes; no fact-to-fact multiplication. |
| `commits_summary` | Listed default-branch commits by committer UTC date and signature verification. Not all branches or deployment frequency. |
| `release_summary` | Published stable releases/prereleases by publication date. Downloads are current lifetime asset counters for those releases, not downloads during the interval; generated source archives are excluded. |
| `contributors_summary` | GitHub's current default-branch attribution, not interchangeable with commit-history counts. |
| `languages_summary` | Current language bytes, not lines of code. |
| `stars_summary` | Current visible stargazers; removed stars disappear. The worker requires administrator access. |
| `repository_summary`, `account_repository_summary` | Current stars/forks for one repository, or a complete visible owned-repository count for one account. |
| `<function>_detail` | All 15 functions expose their complete field schemas. Search reports are capped discovery and `all_rate_limit_detail` is diagnostic; neither has approved aggregate metrics. |

```sql
SELECT * FROM engineering.reports.ci_summary(
  repository => 'Query-farm/crossfield',
  start_day => '2026-09-01', end_day => '2026-10-01'
);

SELECT * FROM engineering.reports.repository_activity(
  repository => 'Query-farm/crossfield'
);

SELECT * FROM engineering.reports.pulls_detail(repository => 'Query-farm/crossfield');
SELECT * FROM engineering.reports.issue_comments_detail(
  repository => 'Query-farm/crossfield', issue_number => 1
);
SELECT * FROM engineering.reports.search_repositories_detail(query => 'topic:duckdb');
SELECT * FROM engineering.reports.all_rate_limit_detail;
```

Report and column comments expose population choices through Crossfield discovery.
Array-valued labels, reviewers, assignees, topics and commit parents remain detail
values; their elements do not multiply the source grain. Current worker objects
are flattened fields, so this model does not invent STRUCT columns.

## Completeness, failures and limits

Reporting mode requires `max_rows => 0` for keyed listings and the model fixes
that argument. Missing/inaccessible sources, exhausted page bounds, malformed
required identities/timestamps/counters and provider errors raise exceptions.
It disables result caching and stale-on-error reuse. Source pages may still be
conditionally revalidated using ETags. An empty accessible listing can return
zero; a missing repository cannot masquerade as one.

Complete means all rows visible through the selected endpoint and credentials,
within the worker's 100-page bound and the model's 10,000-row source ceiling.
Large populations that exceed bounds fail. SQL LIMIT is a presentation operation,
not a completeness proof. Consume every result successfully before treating it
as a completed report: native execution may deliver rows before a later error.

GitHub offers no transactional snapshot across these requests. Changing data
between pages or independently fetched facts remains possible. Repository names
and logins are mutable labels; numeric IDs and composite source grains retain
identity within the configured instance. This is live execution, not historical
`AT` or materialized reporting.

Search can return at most 1,000 selected matches and GitHub may mark responses
incomplete. Its reports provide discovery rows, not approved totals. First-review
latency, historical reopened backlog, exact workflow completion duration,
deployment frequency, code churn and lost-star history need additional facts.
Calendar smoothing/window reports are not published for this invocation profile.

## Rebuild and test

Generate on the build host using only the Python standard library:

```sh
python models/build_model.py
```

This writes the standalone invocation model, `reports.json` and portable package.
The model's `semantic_query` section declares typed public inputs and their
provider mappings. Its shared repository driver and fixed provider options are
the same reviewed definitions used by the named reports.
Changing an API instance uses `--instance` and `--api-origin` and receives a
separate package identity. Review its policies and use `--revision` to advance
the revision before distributing changed definitions for an existing instance.
The package has no publication receipt (`checks: []`); attachment validates its
definitions, while deterministic tests supply implementation evidence.

The [SQLLogicTest suite](../tests/crossfield/reporting.test) runs the real worker
and native VGI/Crossfield against an independently authored mock HTTP API.
[Fixture notes](../tests/crossfield/FIXTURES.md) specify expected answers and errors.
Python implements the worker/HTTP fixture; all SQL executes in native DuckDB.
The worker's [reporting tests](../tests/test_reporting.py) separately exercise
pagination, validation, cache policy and deadlines. Exact build commands and
current results belong in [the integration notes](../docs/CROSSFIELD_SPEC.md).
