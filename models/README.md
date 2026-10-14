# GitHub reporting with Crossfield

For connected organization, user and repository analysis, start with the
[generated model guide](generated-pilot/README.md). It offers 15 freely selected
measures across 10 entities, including organization inventory, members, teams
and user-authored PRs across repositories. Use `organization => ...` or
`user => ...` without supplying a repository. The broad package described below
retains its wider endpoint coverage; these remain separate packages/workers.

This model covers the worker's 21 typed `main` functions, all 780 pinned REST GET
operations, GraphQL queries and endpoint discovery: 24 sources, 51 approved
business metrics and 49 named reports. REST uses the operation-ID dispatcher;
one source covers the same operations as the generated `rest` functions. Business
definitions live in [build_model.py](build_model.py); [source_inventory.json](source_inventory.json)
records the worker signatures and field descriptions. The generated
[package](github-reporting.package.json) contains the model, named parameters,
comments and revision together.
Typed datasets have reviewed business definitions. Raw REST and GraphQL reports
preserve response payloads and request identity; they do not declare entity totals
or approve arbitrary calculations inside those payloads.

Start with `engineering.semantic.github(repository => 'owner/repo')`:
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
FROM engineering.semantic.github(
    repository => 'Query-farm/crossfield'
)
WHERE pulls_merged_day >= DATE '2026-09-01'
  AND pulls_merged_day < DATE '2026-10-01'
GROUP BY pulls_user_login
ORDER BY author;

-- Remove the author dimension to calculate repository totals from the same
-- approved measures. Percentiles are recomputed across the full cohort.
SELECT merged_prs, mean_merge_hours, median_merge_hours, p90_merge_hours
FROM engineering.semantic.github(repository => 'Query-farm/crossfield')
WHERE pulls_merged_day >= DATE '2026-09-01'
  AND pulls_merged_day < DATE '2026-10-01';

EXPLAIN (SEMANTIC)
SELECT merged_prs, median_merge_hours
FROM engineering.semantic.github(repository => 'Query-farm/crossfield');

EXPLAIN (SQL)
SELECT merged_prs, median_merge_hours
FROM engineering.semantic.github(repository => 'Query-farm/crossfield');
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
| `repository` | `VARCHAR` | Repository metrics, PRs, issues, comments, commits, releases, contributors, languages, stargazers, CI and Discussions. |
| `owner` | `VARCHAR` | Public owned-repository count and Projects. |
| `issue_number` | `BIGINT` | `issue_comment_count`, together with `repository`. |
| `discussion_number` | `BIGINT` | Top-level discussion comments, together with `repository`. |
| `comment_node_id` | `VARCHAR` | Replies to one discussion comment. |
| `project_owner_type` | `VARCHAR` | Projects, items and fields: `organization` or `user`. |
| `project_number` | `BIGINT` | The owner's GitHub Projects board number, returned by `projects_detail`; used with `owner` and `project_owner_type`. |

```sql
SELECT repository_count
FROM engineering.semantic.github(owner => 'Query-farm');

SELECT issue_comment_count
FROM engineering.semantic.github(
    repository => 'Query-farm/crossfield', issue_number => 1
);

-- Independent PR and workflow facts aggregate before combination at the
-- requested repository; raw PR rows never multiply raw workflow rows.
SELECT repository_input_repo AS repository,
       merged_prs, workflow_run_count, ci_success_rate
FROM engineering.semantic.github(repository => 'Query-farm/crossfield')
GROUP BY repository_input_repo;
```

`repository_count(owner => ...)` currently uses GitHub's
[`/users/{owner}/repos` endpoint](https://docs.github.com/en/rest/repos/repos#list-repositories-for-a-user),
which lists public repositories even when authenticated. It does not discover
private organization repositories or traverse the listed repositories for PR
metrics. PR metrics require one `repository` input. The
[proposed workflow improvements](../docs/CROSSFIELD_USABILITY.md) describe the
planned owner-wide scope; that interface is not implemented yet.

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
FROM engineering.semantic.github(repository => $1)
WHERE pulls_merged_day >= $2::DATE AND pulls_merged_day < $3::DATE;
EXECUTE merges('Query-farm/crossfield', '2026-09-01', '2026-10-01');

WITH merges AS (
    SELECT merged_prs
    FROM engineering.semantic.github(repository => 'Query-farm/crossfield')
    WHERE pulls_merged_day >= DATE '2026-09-01'
      AND pulls_merged_day < DATE '2026-10-01'
)
SELECT merged_prs FROM merges;
```

## Discussions and Projects

```sql
SELECT discussions_category_name, discussion_count, answered_discussions,
       discussion_answer_rate, mean_discussion_answer_hours
FROM engineering.semantic.github(repository => 'Query-farm/crossfield')
GROUP BY discussions_category_name;
```

For Projects, first discover the boards owned by the organization:

```sql
SELECT number, title, state
FROM engineering.reports.projects_detail(
    owner => 'Query-farm', project_owner_type => 'organization'
)
ORDER BY number;
```

Use the selected board's `number` as `project_number`, retaining the same owner
and owner type. GitHub exposes this number in the board URL, for example
`https://github.com/orgs/OWNER/projects/NUMBER`; see
[GitHub's project lookup documentation](https://docs.github.com/en/issues/planning-and-tracking-with-projects/automating-your-project/using-the-api-to-manage-projects).
A board belongs to an organization or user and may contain work from multiple
repositories. Its number differs from its global `id` and GraphQL `node_id`.

The following examples use **7 as an illustrative board number** from the test
fixture; they do not establish that Query Farm owns board 7. Replace it with the
number returned above. Likewise, replace custom-field IDs `123,456` with IDs
returned by `project_fields_detail`.

```sql
SELECT project_item_count, project_issue_items, project_pull_request_items,
       project_draft_items, archived_project_items
FROM engineering.semantic.github(
    owner => 'Query-farm', project_number => 7,
    project_owner_type => 'organization'
);

SELECT id, name, data_type
FROM engineering.reports.project_fields_detail(
    owner => 'Query-farm', project_number => 7,
    project_owner_type => 'organization'
);

SELECT id, content_type, title, fields_json
FROM engineering.reports.project_item_values_detail(
    owner => 'Query-farm', project_number => 7,
    project_owner_type => 'organization', project_fields => '123,456'
);
```

Answer rate means currently answered discussions divided by all visible
discussions, including categories without a selected answer. Answer time measures
creation to the currently recorded answer selection. It is not first-response
time or an SLA. Fixture durations of 2 and 10 hours give mean/median 6 hours;
with one unanswered discussion the answer rate is 2/3.

Project item counts preserve item identities, including drafts and inaccessible
content. One issue appearing on two projects is two project items. Archival is
not completion. Custom fields remain JSON because each project defines its own
types; choose field IDs explicitly for the detail report. Ordinary item metrics
need no custom-field input and use the provider's title-only selection.
The current callable model requires one selected project for item metrics;
automatic discovery and aggregation across all of an owner's projects is not
defined by this package.

## Raw REST and GraphQL detail

Discover every supported REST operation without a GitHub request:

```sql
SELECT operation_id, function_name, path, parameters
FROM engineering.reports.api_endpoints_detail
WHERE category = 'pulls';

SELECT page_number, status_code, data, next_url
FROM engineering.reports.rest_responses_detail(
    operation_id => 'pulls/list-reviews',
    path_parameters => '{"owner":"Query-farm","repo":"crossfield","pull_number":1}',
    rest_query => '{}', rest_accept => 'application/vnd.github+json',
    rest_allow_not_found => false
);

SELECT body
FROM engineering.reports.rest_responses_detail(
    operation_id => 'repos/download-zipball-archive',
    path_parameters => '{"owner":"Query-farm","repo":"crossfield","ref":"main"}',
    rest_query => '{}', rest_accept => 'application/octet-stream',
    rest_allow_not_found => false
);

SELECT data
FROM engineering.reports.graphql_responses_detail(
    graphql_document => 'query Identity($login:String!){user(login:$login){login}}',
    graphql_variables => '{"login":"octocat"}', graphql_operation_name => 'Identity'
);
```

Every displayed argument is required; use `{}` for empty query/variable maps and
an empty string for an unnamed GraphQL operation. REST operations are restricted
to the pinned GET inventory. API version, complete Link pagination and cache
policy remain model-owned. `rest_allow_not_found => true` explicitly retains a
404 response for existence/membership checks. Binary responses keep exact BLOB
bytes, and `data` keeps JSON text without flattening nested values.

REST grain is one HTTP response page per request. GraphQL grain is one response
per document/variables/operation; nested connections retain their own cursors and
may still have more pages. GraphQL errors fail, including partial-data errors.
Strict mode permits approved response detail, but rejects turning response rows
into business totals. To calculate review, deployment or other entity metrics,
add a typed reporting source and approved definitions for that population.

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
| `repository_summary`, `account_repository_summary` | Current stars/forks for one repository, or a complete public owned-repository count for one account through `/users/{owner}/repos`. Authentication does not add private repositories to that listing. |
| `discussion_overview`, `discussion_answer_summary`, `discussion_comments_summary`, `discussion_replies_summary` | Current selected-answer coverage/time, with separate top-level comment and reply populations. |
| `projects_summary`, `project_items_summary`, `project_fields_summary` | Current boards, item identities and field definitions; project closure/archival do not imply completed work. |
| `<source>_detail`, `project_item_values_detail` | Complete typed schemas, including arrays and selected custom-field JSON. Search is capped discovery and rate-limit data is diagnostic. |
| `rest_responses_detail`, `graphql_responses_detail`, `api_endpoints_detail` | Full raw API surface at response grain, plus local endpoint discovery. No entity metrics on raw payloads. |

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
latency, exact workflow completion duration, deployment frequency and code churn
still need approved typed entity definitions over the raw endpoints. Historical
reopened backlog and lost-star history remain unmodeled. Calendar smoothing/window
reports are not published for this invocation profile.

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

`python models/build_model.py --check` verifies source/endpoint coverage and exact
generated artifacts. A changed worker registration or REST operation inventory
fails until its semantic coverage is reviewed and regenerated.

The [existing reporting suite](../tests/crossfield/reporting.test),
[whole-surface suite](../tests/crossfield/surface.test) and
[raw API suite](../tests/crossfield/raw_api.test) run the real worker through
native VGI/Crossfield against an independently authored mock HTTP API.
[Fixture notes](../tests/crossfield/FIXTURES.md) specify expected answers and errors.
Python implements the worker/HTTP fixture; all SQL executes in native DuckDB.
The worker's [reporting tests](../tests/test_reporting.py) separately exercise
pagination, validation, cache policy and deadlines. Exact build commands and
current results belong in [the integration notes](../docs/CROSSFIELD_SPEC.md).
