# Deterministic native-worker data

`worker_fixture.py` runs the real GitHub worker with an HTTP mock transport.
It cannot access the network. The origin remains `https://api.github.com` for
normal model authority checks. Every list endpoint uses three-row pages.

For `example/project`, merged PRs in `[2026-09-01, 2026-10-01)` have durations
2, 4, 10 and 20 hours: count **4**, mean **9**, median **7**, continuous p90
**17**. The two-hour PR merges exactly at the inclusive start. A 30-hour PR
merges exactly at the excluded end, and a 40-hour PR merges one second before
the start. Also present: one closed unmerged, one open and one draft open PR.
There are nine PRs total, seven closed and six merged across all dates.
`example/other` has PR number 1 with a distinct ID (9001), merged September 15
after six hours. PR labels are `['feature', 'sql']`, assignees are empty, and
requested reviewers are `['reviewer']`.

| Source | Independent expected data |
| --- | --- |
| Repository lookup | One repository; 12 stars, 3 forks, 2 open issue/PR counter; topics `['sql','semantic']` |
| Repositories/search repositories | `example/project` and `example/second` |
| User | One user, 5 followers, 1 following, 2 public repositories |
| Issues/search issues | Two issues: one open, one closed; closed issue takes 48 hours |
| Issue comments | One comment, September 2 |
| Commits | Two distinct commit hashes; one verified; one parent hash each |
| Releases | One published non-prerelease; two assets, 35 total downloads |
| Contributors | Alice 8, Bob 2 contributions |
| Languages | Python 750 bytes, C++ 250 bytes |
| Stargazers | Alice September 1, Bob September 2 |
| Workflow runs | Completed success 10 minutes, failure 20 minutes, cancelled 30 minutes; same workflow |
| Rate limits | Core: limit 60, used 5, remaining 55; search: limit 10, used 1, remaining 9 |

Adverse repository names are `example/empty`, `example/missing` (404),
`example/late-error` (403 on the second page), `example/duplicate` (duplicate PR
ID), `example/null-id`, `example/negative-duration` and `example/missing-merge`.
The empty repository exists and has successful empty listings. Bad PR rows
appear on the first page; strict worker validation must reject them regardless
of output projection or downstream SQL filters.

Set `CROSSFIELD_GITHUB_API_LOG` to a writable file path in the worker's environment
to append `{ "path": ..., "query": ... }` JSON lines for data requests.
Catalog discovery and binding do not add entries. The log records no credentials.
