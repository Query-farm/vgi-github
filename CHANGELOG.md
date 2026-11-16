# Changelog

## 0.3.1 (2026-11-16)

- Require vgi-python `>=0.52.2,<0.53`; uv.lock re-locked.
- Move to Python 3.14: `requires-python >=3.14`, CI, the Docker image and lint tooling target 3.14.
- Accept GitHub REST API description revision `2a33d9cc5d1dc6ca603b908e0796454af88c1999`
  (was `58b1e0c0`): 34 new and 179 changed GET operations, no removals. The `rest` schema now
  exposes 814 GET operations (667 GitHub.com, 804 Enterprise Cloud), and the regenerated
  semantic sources, generated pilot and Crossfield model pin them. Upstream added a `oneOf`
  `metadata` field to rule-suite evaluations; the `rule_evaluations` columns keep their
  previous fields through an explicit selection. Secret-scanning locations gain an
  `actions_log` details variant (`variant_14`); it requires only path and line/column fields, so
  commit and wiki-commit details now also list it in `matched_types`. The GraphQL schema
  revision is unchanged.
- Add `main.job_logs(repo, job_id)` and `main.run_logs(repo, run_id, attempt => n)`: GitHub
  Actions logs as one row per line with parsed timestamps, ANSI-stripped text (raw kept),
  `##[group]` paths and decoded workflow commands; `run_logs` reads the run's zip archive per job
  and step. Bodies stream through an anonymous temporary file and rows go out in resumable batches.
  Descriptions warn that logs are untrusted and may contain leaked secrets; results are never cached.
- Add scalars `log_ts(line)`, `log_text(line, strip_ansi)` and `workflow_command(line)`.
- `workflow_runs` takes `created =>`, GitHub's date-range filter, as an incremental-load cursor.
- `projects`, `project_items` and `project_fields`: GitHub answers 404 when a token cannot read
  Projects. For an owner that exists, the error now says so and names the permission to grant
  (`read:project`, or Projects read for fine-grained and App tokens) instead of a bare Not Found.
- `projects`, `project_items` and `project_fields` treat a first-page 401/403 the same way, so an
  installation token's refusal (a workflow `GITHUB_TOKEN`) also names the missing permission.
- The organization-wide `workflow_runs` example uses a closed one-day `created` window. The open
  `>=` cursor with `max_rows => 0` walked a growing history and outlived the lint timeout.
- The `discussion_replies` example reads a fixed duckdb/duckdb discussion (#1688) that has replies.
- The API coverage drift workflow runs the generator inside the project environment (`uv run`).

## 0.3.0 — 2026-11-12

- Speak VGI protocol 3.3 (vgi-python 0.51.0). The published `vgi` extension matches
  major+minor exactly, so 0.2.x workers are rejected at `ATTACH` by the current extension.
- The `github` secret type documents its `token` parameter and links to how to create a
  personal access token (vgi-lint-check 2.5 VGI1011/VGI1012).

## 0.2.0 — 2026-11-10

- Speak VGI protocol 3.2 (vgi-python 0.50.0, vgi-rpc 0.53.1); protocol 3.1 support came with
  the previous SDK upgrade.
- Catalog metadata for vgi-lint 2.2: the display title is now the short name `GitHub API`
  (was `GitHub (read-only APIs)`), and a one-sentence `vgi.subtitle` describes the catalog
  in listings. CI now lints with vgi-lint-check 2.2.0 (protocol 3.2) and fails on info-level
  findings.

- Add typed `main.discussions`, `discussion_comments` and `discussion_replies` through
  GraphQL, and `projects`, `project_items` and `project_fields` through REST. All support
  bounded automatic pagination, named filters and correlated `LATERAL`; custom Project
  field values remain JSON. Reporting mode validates complete listings, stable row keys,
  dates, counters and state, while retaining declared nullable project content. Extend the
  Crossfield model with approved Discussions and Projects metrics and detail reports.
- Cover generated REST operations, `api.rest()` and `api.graphql()` in Crossfield detail
  reports. Raw REST rows represent response pages and GraphQL rows represent envelopes;
  approved entity metrics remain defined on validated typed sources.
- Check upstream REST coverage weekly with read-only workflow permissions. Add
  `--check-upstream` for drift detection and `--revision latest` for reviewed local refreshes;
  preserve the pinned API version unless explicitly changed.
- Report GraphQL errors before partial response data so large responses cannot hide the cause.

- Add a generated `rest` schema for all 780 distinct GET operations in pinned GitHub.com
  and Enterprise Cloud API descriptions, plus `api.endpoints` discovery and `api.rest()`
  dispatch. Preserve complete JSON, HTTP statuses, binary downloads and pagination links.
- Add `api.graphql()` for query-only access, including Discussions and Projects. Parse
  every document before transport and reject mutations, subscriptions and schema definitions.
  REST remains GET-only; the sole POST is the validated GraphQL query transport.

- Update published dependencies to VGI Python 0.40.0 and VGI RPC 0.48.0, refresh the
  dependency lockfile, and update development/build tools and CI's VGI linter.
  Move agent-task grading data to `vgi-agent-tests.yaml` for the updated metadata contract.
- Support `catalog_contents` for loading the full catalog in one RPC, preserving
  each attachment's authentication and cache settings in the serialized metadata.

- `cache_ttl` ATTACH option sets a default result TTL for lookups and searches. Per-call TTLs
  override it; omitted/NULL TTLs inherit it, and explicit zero uses GitHub's cache policy.
  Positive TTLs now take precedence over GitHub's default freshness. `rate_limit` stays uncached.

- The worker reports what it is doing to DuckDB's log: a warning for every rate-limit wait and
  retry, a warning when the remaining budget drops below 10%, and a one-line summary per call
  (requests made, free 304 revalidations, budget left and its reset time). Read them with
  `SET enable_logging = true` and `duckdb_logs_parsed('VGI')`.
- `token_source` ATTACH option: `'gh'` authenticates with the GitHub CLI's login, `'env'` with
  `GH_TOKEN` or `GITHUB_TOKEN` — no secret needed, and the token never appears in the ATTACH
  statement. A worker serving HTTP or a socket refuses it at ATTACH by default, so a remote client
  cannot borrow the operator's login; start the server with `VGI_GITHUB_ALLOW_TOKEN_SOURCE=1` to
  allow it, using the server's own login, for a server you run for yourself. A `github` secret still
  takes precedence.

## 0.1.0 — 2026-10-02

Initial release.

### Surface

- Streaming search scans: `search_repositories`, `search_issues` (GitHub's query syntax, at most 1,000
  results per query; a `LIMIT` stops the walk early).
- LATERAL-composable functions: `repo`, `repos`, `user`, `issues`, `pulls`, `issue_comments`,
  `commits`, `releases`, `contributors`, `languages`, `stargazers`, `workflow_runs`. List functions
  take `max_rows` (default 100, one request per input row; `0` fetches up to 10,000).
- `rate_limit` table: remaining budget per resource, and whether a token is in use.

### Authentication

- Optional token via a `github` DuckDB secret, selected by type and `SCOPE`, so any secret name works
  and GitHub Enterprise tokens can be scoped per host (`GITHUB_API_URL`).
- `auth` ATTACH option: `auto` (default), `required`, `off`.
- Opt-in `VGI_GITHUB_TOKEN` operator fallback for CI and vgi-lint. Deliberately not the ambient
  `GITHUB_TOKEN`, so a shell token cannot leak into a shared HTTP worker.

### Transport and safety

- One read-only `GET` chokepoint with retry/backoff on 5xx and dropped connections.
- Rate limits: waits of up to 15 seconds are slept through; longer ones fail at once with the reset
  time, since the wait would block an uncancellable call.
- `Link` paging followed only on the configured API origin, with the link's query string preserved.
- ETag cache partitioned by token; `304 Not Modified` revalidations cost no primary budget.
- Works over stdio and HTTP; one HTTP server keeps each client's credentials to that client.

### Testing

- 126 offline tests; 48 live tests covering GitHub's own behaviour, end-to-end SQL through DuckDB,
  and the HTTP transport with client isolation. The live tiers install the `vgi` extension themselves.
- vgi-lint: no findings in the structural, behavioural and doc-review tiers.

### Known issues

- On macOS (libc++), DuckDB 1.5's `duckdb_functions()` can show named arguments of mixed types with
  each other's types. Binding is unaffected and `vgi_function_arguments()` is correct. A fix is
  proposed upstream in duckdb/duckdb#26409, with a workaround planned in the vgi extension.
- `stargazers()` only works for repositories the token administers; GitHub refuses the listing for
  any other repository. `repo()` still reports `stargazers_count`.
