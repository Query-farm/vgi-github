# Changelog

## 0.1.0 — 2026-10-01

Initial release.

- Streaming search scans: `search_repositories`, `search_issues`.
- LATERAL-composable functions: `repo`, `repos`, `user`, `issues`, `pulls`, `issue_comments`,
  `commits`, `releases`, `contributors`, `languages`, `stargazers`, `workflow_runs`.
- `rate_limit` table.
- Optional token authentication via a `github` DuckDB secret (selected by type and scope, so any
  secret name works and GitHub Enterprise tokens can be scoped), the `auth` ATTACH option
  (`auto` / `required` / `off`), and an opt-in `VGI_GITHUB_TOKEN` operator fallback.
- Single read-only `GET` chokepoint with retry/backoff, rate-limit awareness, origin-checked
  `Link` paging and a token-partitioned ETag cache.
