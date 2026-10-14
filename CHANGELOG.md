# Changelog

## Unreleased

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
