# Changelog

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
