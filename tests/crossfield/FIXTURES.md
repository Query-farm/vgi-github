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

`surface_fixture.py` extends the same mock transport with independently authored
typed and raw API examples. Discussions have three rows: two currently answered
after 2 and 10 hours and one unanswered. Expected count/answered/unanswered is
3/2/1, answer rate 2/3, mean and median answer time 6 hours. Q&A contains two rows
with one answer at 2 hours; Ideas contains one answer at 10 hours. Top-level
comments and replies each contain two distinct identities; replies retain C1 as
their parent. Small GraphQL connection pages exercise cursor traversal.

Two projects are open/closed. Four project items have Issue/PullRequest/DraftIssue/
Issue types; the last has inaccessible NULL content and still counts. One item
is archived. Two field definitions preserve selection options and custom item
values as JSON. Separate item/board identities prevent counting content twice
within one population or discarding inaccessible entries.

The REST review fixture returns two complete response pages, one review each.
Their page numbers are 1/2; nested `extra: [1, null]` is retained. The binary
download is exactly hex `00FF806172636869766500`, including NUL and invalid UTF-8
bytes. Membership checks can explicitly retain HTTP 404. Raw GraphQL returns
request-dependent login values, extensions and a connection cursor with
`hasNextPage: true`; exposing that envelope does not imply complete entity data.
Mutation input and partial-data errors reject. The endpoint inventory contains
the pinned 780 GET operations and makes no data request.

`connected_fixture.py` exercises the opt-in generated producer worker and the
standalone `models/generated-pilot/` package. Every REST list and GraphQL
connection uses one-row pages. The organization `example` has public `alpha`,
private `beta` and empty `empty` repositories; the token-visible inventory is
three. A separate user account lists one public repository through the user
route. This fixture does not claim live credential qualification.

| Repository | PR records | Merged PRs / elapsed hours | Review records | Label definitions |
| --- | --- | --- | --- | --- |
| alpha | 3 | 2 / 48 and 12 | 3 | 2 |
| beta | 1 | 1 / 6 | 1 | 1 |
| empty | 0 | 0 | 0 | 0 |

PR number 1 exists in both alpha and beta with distinct repository identities.
Alice authored three PRs, including the 48-hour and 6-hour merges; her median is
27 hours. Bob authored the 12-hour merge. The all-owner median is **12 hours**.
Bob submitted two approved reviews, Alice one comment and Carol one comment:
four submitted reviews and two approval records. Combining review and PR
measures must retain PR count **4** and merged count **3**. Including the
repository count establishes an inventory population with the empty parent.

The fixture and `connected.test` are independently authored; expected answers
are not generated from the semantic recipes. Native cases cover owner/repository
and one-PR scope, caller-selected dimensions/filters, callable detail, prepared
queries, CTEs, no-fetch discovery, duplicate identities, malformed types, a late
HTTP failure, invalid scopes and recovery. SDK tests separately cover protocol
state round trips, empty batches, nested contracts, GraphQL errors, deadlines
and limits. The generated worker uses the existing producer protocol and keeps
current traversal pages, rather than collecting complete result sets.

`people.test` uses the same fixture with independent membership populations.
Organization `example` has members Alice (201) and Carol (203); PR contributor
Bob (202) is not a member. Its teams are `core`, `docs` and `empty`: Alice and
Carol belong to `core`, Alice also belongs to `docs`, and `empty` has no members.
Thus member count is **2**, team count **3**, and team membership count **3**.
The fixture omits optional role/inheritance fields; detail preserves NULL.
Team membership grants no contribution-attribution relationship.

Alice's user activity contains four authored PRs: two in `example/alpha`, one
in `example/beta` and one in `other/project`. Three are merged, with durations
**48, 6 and 18 hours** and median **18**. September 3 has two merges, September 7
has one, and the unmerged PR has a NULL merge date. Alice's owned-repository
inventory is a different population. Bob has one 12-hour merge; Carol and
`empty-user` have no PRs. `empty-org` has a profile but no members, teams or
repositories. Including profile counts establishes their zero-activity groups.

Native cases also cover organization/repository composition, authored date
filters, CTEs, prepared users, no-fetch discovery, invalid/mixed scopes, rejecting
an organization passed as a user, and wrong/NULL authors on later pages followed
by successful recovery. REST lists and GraphQL connections still paginate one
row at a time; no test derives its expected numbers from generated recipes.

## User activity and period comparison

`research_fixture.py` adds independent users without changing the preceding oracle.
`research.test` covers six user-owned activity populations, using one-row GraphQL
pages and the actual generated worker. `researcher` has the following creation
cohorts; timestamps use explicit UTC offsets at month boundaries.

| Population | August | September |
| --- | ---: | ---: |
| PR | 2 | 3 |
| Issue | 2 | 3 |
| Discussion | 1 | 2 |
| Issue/PR comment | 2 | 2 |
| Discussion comment | 1 | 2 |
| Commit comment | 1 | 2 |

The total is **9 -> 14**, over **31 -> 30** calendar days: per-day growth is
**60.74074074074074%**. PR active days and distinct repositories are both **2 -> 2**;
these distinct counts must not be summed across groups. PR repository counts are
August `lab/compiler=1`, `outside/docs=1`; September `lab/compiler=1`, `lab/sdk=2`.
PR creation-cohort median merge hours are **12 -> 18**; September has three merges
but only two PRs that were both created and merged during September.

Original text and `https://github.example/activity/<ID>` URLs support evidence
queries. Prefix categories are literal, case-insensitive conventions, with an
unclassified fallback. An orphan discussion comment retains its identity with
NULL subject/repository context and increments the unknown-repository measure.
`idle-researcher` has no activity. Wrong/deleted actors and `late-researcher`'s
later-page 503 fail; a subsequent healthy request succeeds. Fixtures assert the
issue connection's explicit `createdBy` input. No expected value is computed
from model recipes, and no fixture can access live GitHub.
