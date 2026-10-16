# Connected generated GitHub model

Connected GitHub semantic model with canonical business entities and multiple retrieval routes. Reviewed populations, identities, actor roles, typed detail and explicit relationships support approved measures. The generated coverage ledger records remaining API gaps.

[coverage.json](coverage.json) compares this model with every pinned REST GET operation and the complete query-reachable GraphQL type graph. It records implemented routes, unselected API fields, possible opposite-direction fields and upstream schema errors. These schema candidates do not establish equivalent populations or approved retrieval paths; the audit does not execute live endpoints.

Start with an organization, a user or a repository. Organizations connect to visible members, teams and repository activity; users connect to authored pull requests, issues, discussions and comments across visible repositories. Ownership, membership, authorship and reviewing are separate roles. Each metric retains its own entity grain, and every public source also supports callable detail.

## Measured API coverage

The generated model selects 387 of 780 pinned REST read operations. The implementation scope contains 390 operations, of which 381 are selected. The 390 explicitly excluded operations remain in the ledger. [Coverage policy](../../generation/coverage-policy.json) records the user-selected scope and operation decisions; raw access does not count as semantic selection.

For `api.github.com`, 3139 of 5231 in-scope named response-property declarations are projected into public entity fields. Shared declarations count once; dynamic map keys are unenumerated. 1272 of 1482 operation parameters are bound, including literal and runtime pagination bindings. A binding does not imply that every allowed parameter value is supported.

For `ghec`, 150 of 5374 in-scope named response-property declarations are projected into public entity fields. Shared declarations count once; dynamic map keys are unenumerated. 100 of 1577 operation parameters are bound, including literal and runtime pagination bindings. A binding does not imply that every allowed parameter value is supported.

GraphQL queries fetch 297 of 3365 in-scope read-field coordinates; 212 are projected into public fields. The policy explicitly excludes 2024 coordinates from the 5389 raw total. Raw measurements remain 297 fetched and 212 publicly projected coordinates, including any excluded fields. Exclusions name exact owning types or fields and do not remove shared user, repository or actor fields transitively.

GraphQL queries bind 57 of 1582 in-scope field arguments; raw totals are 57 bound of 1957 declared, with 375 declared arguments excluded by their owning field's scope. Fetching requires an actual query selection; public exposure also requires a typed entity projection. Business information available through REST and fields merely present in the selected schema do not increase these GraphQL measurements. These measurements do not establish live endpoint qualification or business-domain completeness.

`checks/list-for-ref`: The endpoint considers only the 1000 most recent check suites. The check_runs reference route enumerates all suites with checks/list-suites-for-ref and then all runs with checks/list-for-suite.

`dependency-graph/generate-sbom-report`: This GET initiates an SBOM generation job. It is side-effecting and is not a read-only retrieval route.

`repos/get-pages-health-check`: The pinned API initiates a background Pages diagnostic task on the first GET. The read-only semantic worker does not initiate diagnostic jobs.

`classroom/get-an-assignment`: Retired upstream read: the pinned api.github.com and ghec operations document closure on 2026-08-28 and define only HTTP 410, with no successful retrieval response. No live Classroom entity population can be implemented from this contract.

`classroom/list-accepted-assignments-for-an-assignment`: Retired upstream read: the pinned api.github.com and ghec operations document closure on 2026-08-28 and define only HTTP 410, with no successful retrieval response. No live Classroom entity population can be implemented from this contract.

`classroom/get-assignment-grades`: Retired upstream read: the pinned api.github.com and ghec operations document closure on 2026-08-28 and define only HTTP 410, with no successful retrieval response. No live Classroom entity population can be implemented from this contract.

`classroom/list-classrooms`: Retired upstream read: the pinned api.github.com and ghec operations document closure on 2026-08-28 and define only HTTP 410, with no successful retrieval response. No live Classroom entity population can be implemented from this contract.

`classroom/get-a-classroom`: Retired upstream read: the pinned api.github.com and ghec operations document closure on 2026-08-28 and define only HTTP 410, with no successful retrieval response. No live Classroom entity population can be implemented from this contract.

`classroom/list-assignments-for-a-classroom`: Retired upstream read: the pinned api.github.com and ghec operations document closure on 2026-08-28 and define only HTTP 410, with no successful retrieval response. No live Classroom entity population can be implemented from this contract.

`workflow_run_attempts`: Requires an explicit run ID and attempt number; attempt history enumeration is not implemented.

`workflow_jobs`: Attempt-specific retrieval is supported. Analytical joins use the run's latest state; enrichment by attempt attributes is not approved. Job-local run_attempt remains available for grouping.

`workflow_artifacts`: Run and workflow retrieval routes are available. Analytical enrichment through the optional run relationship is not approved; direct repository enrichment preserves artifacts lacking run metadata.

`release_assets`: Release association is exposed when known and supports retrieval. Analytical enrichment by release/publisher is not approved; direct repository and uploader relationships preserve asset identity and actor roles.

`check_runs`: Suite association is exposed when known and supports retrieval. Analytical enrichment by suite is not approved; direct repository context preserves runs lacking suite metadata.


[research.sql](research.sql) is the runnable researcher workflow: compare contribution types over UTC periods, count active days and repositories, and inspect source evidence. Title categories use explicit model-owned rules; repository language supplies context. Neither is an inferred interest or employee-performance score.

```sql
-- Load the matching native extensions described in ../../docs/CROSSFIELD_SPEC.md first.
SET TimeZone='UTC';
ATTACH 'github' AS generated_source (TYPE vgi,
  LOCATION '/path/to/.venv/bin/python -m vgi_github.generated_worker', reporting true);
ATTACH 'models/generated-pilot/github-generated.package.json' AS engineering
  (TYPE crossfield, BINDINGS '{"github_source":{"catalog":"generated_source",
    "provider_id":"queryfarm.vgi.github","instance_id":"github.com"}}');
SET crossfield_mode='strict';

-- Organization inventory: no repository argument is needed.
SELECT organization_login, organization_member_count, team_count, repository_count
FROM engineering.semantic.github(organization => 'Query-farm')
GROUP BY organization_login;

SELECT team_slug, team_count, team_membership_count
FROM engineering.semantic.github(organization => 'Query-farm')
GROUP BY team_slug ORDER BY team_slug;

-- User activity includes PRs in repositories the user does not own.
SELECT user_login, user_count, pull_request_count, merged_prs,
       median_merge_hours
FROM engineering.semantic.github(user => 'octocat') GROUP BY user_login;

SELECT pull_request_repository_name, pull_request_count, merged_prs
FROM engineering.semantic.github(user => 'octocat')
GROUP BY pull_request_repository_name ORDER BY pull_request_repository_name;

SELECT pull_request_merged_day, merged_prs, median_merge_hours
FROM engineering.semantic.github(user => 'octocat')
WHERE pull_request_merged_day >= DATE '2026-09-01'
  AND pull_request_merged_day < DATE '2026-10-01'
GROUP BY pull_request_merged_day ORDER BY pull_request_merged_day;

SELECT * FROM engineering.detail.organization_memberships(organization => 'Query-farm');
SELECT * FROM engineering.detail.users(user => 'octocat');

-- Existing repository and owner scopes remain available.
SELECT repository_name, repository_count, pull_request_count, merged_prs,
       median_merge_hours, submitted_review_count, approved_review_count
FROM engineering.semantic.github(owner => 'Query-farm') GROUP BY repository_name;

SELECT author_login, pull_request_count, median_merge_hours
FROM engineering.semantic.github(repository => 'Query-farm/crossfield') GROUP BY author_login;

SELECT reviewer_login, submitted_review_count, approved_review_count
FROM engineering.semantic.github(repository => 'Query-farm/crossfield') GROUP BY reviewer_login;

-- Merge cohort: UTC dates, inclusive start and exclusive end.
SELECT pull_request_merged_day, merged_prs, median_merge_hours
FROM engineering.semantic.github(repository => 'Query-farm/crossfield')
WHERE pull_request_merged_day >= DATE '2026-09-01'
  AND pull_request_merged_day < DATE '2026-10-01'
GROUP BY pull_request_merged_day ORDER BY pull_request_merged_day;

SELECT review_submitted_day, reviewer_login, submitted_review_count
FROM engineering.semantic.github(repository => 'Query-farm/crossfield')
WHERE review_submitted_day >= DATE '2026-09-01'
  AND review_submitted_day < DATE '2026-10-01'
GROUP BY review_submitted_day, reviewer_login;

SELECT review_id, reviewer_login, state, body FROM engineering.detail.pull_request_reviews(
  repository => 'Query-farm/crossfield', pull_request_number => 1) ORDER BY review_id;

-- Discover names, types, calling conventions and scope rules without fetching GitHub data.
SELECT name, type, is_named, is_positional, is_const, example, constraints
FROM crossfield_parameters()
WHERE database_name='engineering' AND schema_name='semantic'
  AND invocation_name='engineering.semantic.github' ORDER BY ordinal;
```

For repository inventory and label definitions, choose exactly one of `organization`, `owner`, `repository` and `repositories`. `organization` explicitly selects an organization's visible repositories. The existing `owner` route resolves account type; a user owner lists PUBLIC owned repositories, not that person's contributions or private user inventory. Optional `pull_request_number` requires `repository`. Invalid, empty or conflicting scope arguments fail before HTTP.

The parameter catalog publishes example values as JSON and declares named, constant arguments. Examples are suggestions, never defaults: omitting `pull_request_number` still selects all PRs even though its example is `1`. The constraints include nonempty resource names, PR numbers of at least 1, mutually exclusive scope choices and the repository requirement for a PR number. Crossfield validates the rules for the selected datasets before provider execution; a user-only query does not require a repository. Detail entries publish the same rules for their own sources. NULL defaults count as absent when choosing a scope.

The entity contracts below list each selectable population and retrieval route. Only sources needed by the selected measures, dimensions and filters are fetched. Requesting a profile does not enumerate repositories; zero-activity users and empty organizations remain visible when `user_count` or `organization_count` establishes the inventory population.

For explicit cohorts use `users => [{'login': 'octocat'}, {'login': 'hubot'}]` or `repositories => [{'repository': 'Query-farm/crossfield'}, {'repository': 'Query-farm/vgi'}]`. Cohorts are mutually exclusive with their singular scope alternatives. NULL means absent; an empty list selects an empty population. Names must be nonempty and unique ignoring case. Source pages must respect their declared grain. Distinct-entity routes remove repeated targets across parents; membership routes retain each identity pair. Object numbers require one `repository`. Discovery publishes the exact LIST/STRUCT types and examples.

`pull_requests` is one entity under either repository or author selection. Supply a repository scope, `user`/`users`, or both; both selects their intersection. Reviews and PR label/assignee memberships follow the same PR population. For reviews, `user` means PR author, never reviewer. One metric family (`pull_request_count`, `merged_prs`, `median_merge_hours`) works across scopes. Use `pull_request_repository_name` for the repository carried on each PR; `repository_name` belongs to the separately selected repository inventory. The former `authored_*` public names are removed. Issues, discussions and comments also expose reverse retrieval routes; the entity contracts below describe each selectable population and its visibility.

Each selected function streams its own traversal. Separate functions may fetch the same ancestors; cross-function HTTP sharing awaits a paginated row-map interface in VGI. Native stages reuse their own parent relation without mixing independent fact grains.

User PR discovery uses GitHub's cursor-paginated user connection across visible repositories. Each row must identify the selected canonical user as its author; missing or different authors fail rather than silently changing the population. Each discovered PR is hydrated through repository and PR REST lookups, adding two requests per PR to preserve the same complete fields under either scope. PR state is open/closed; a merge timestamp identifies merged PRs. This is authored-PR activity, not an all-contributions score, an events timeline or a capped search result. Authored issues, discussions and issue/discussion/commit comments use their own cursor-paginated user connections with the same author check. Issue comments include comments on pull requests; commit comments describe comments, not authored commits. Private or inaccessible content is outside the visible population. Deleted discussion subjects may lack repository context; the unknown-repository count makes those records visible.

Active-day and distinct-repository metrics are non-additive counts: request the desired grouping directly instead of summing daily or category subtotals. DATE dimensions use UTC days; weekly periods start on ISO Monday and monthly periods on the first day. Ordered case-insensitive title-prefix rules label explicit conventions such as `docs:` or `fix:`; unmatched titles stay `unclassified`. Detail rows retain titles, bodies, timestamps and URLs for checking the evidence. Repository primary language is current repository context, not the language of an individual contribution.

Membership means GitHub membership visible to the caller, not employment. Public-only credentials cannot establish a complete private roster. Team membership includes members inherited from child teams; nullable role/inheritance fields preserve what the pinned API actually supplies. `team_membership_count` counts team/account pairs. Someone in two teams contributes two memberships, but does not become two organization members. PR/review measures cannot be grouped through a team's membership: that attribution rule has not been approved. Organization members are not silently equated with all contributors.

API meaning: [user activity](https://docs.github.com/en/graphql/reference/users#user), [organization membership](https://docs.github.com/en/rest/orgs/members#list-organization-members), [effective team membership](https://docs.github.com/en/rest/teams/members#list-team-members).

Include `repository_count` to establish repository inventory as the grouping axis, including empty repositories. PR-only reports describe the PR population. Label counts describe definitions, not assignments. Review counts describe records, not distinct reviewers, latest decisions or merge eligibility.
Count metrics return zero for an established group with no matching records. Median merge time remains NULL for an empty merged cohort.

`pull_request_created_day`, `pull_request_merged_day` and `review_submitted_day` are approved DATE dimensions computed by DuckDB from the corresponding timestamp. They use Gregorian UTC calendar days, with a required `TimeZone='UTC'` session. Unmerged PRs have a NULL merge day; a missing review submission timestamp stays NULL. A merge-day filter selects PRs merged in the interval; a creation-day filter selects PRs created in it. Review-day filtering selects review activity and does not define a PR merge cohort. The model preserves these different populations and roles.

Schema facts define types; declarative scopes select sources, traversals map parent fields to child inputs, and semantic relationships define approved many-to-one joins. Business recipes define populations and elapsed-hour calculations. Saved reports are optional; this package needs none.
Relationship retrieval bindings are validated against source fields and target route parameters. The generated model publishes them in `policy.tags.github.relationship_retrievals`; dataset tags publish `github.retrieval_routes`. Supplying the declared parameters executes the corresponding provider route. These metadata tags describe navigation; analytical join planning continues to use the approved relationship keys and cardinalities.
A retrieval's `when` equalities and `when_null`/`when_not_null` field guards must all hold before using its bindings. Unavailable identity evidence does not establish a navigable parent.
Relationships marked `analytical: false` retain their declared keys and retrieval bindings but are not approved as analytical join paths. Actions jobs and attempts join through runs and workflows. Artifacts join directly to repositories so artifacts without run metadata retain their repository context. Artifact run associations remain available for retrieval and identity fields; analytical enrichment by run outcome is not approved.

## Research a user's activity

After attaching `engineering` as above, choose a user and ask for approved measures
and dimensions directly. This monthly PR query is included verbatim in
the native SQLLogicTests, with independently authored expected answers:

```sql
-- Replace the fixture login 'researcher' and dates for a real account.
SELECT pull_request_created_month, pull_request_count,
       pull_request_active_days, pull_request_repository_count,
       median_merge_hours
FROM engineering.semantic.github(user => 'researcher')
WHERE pull_request_created_day >= DATE '2026-08-01'
  AND pull_request_created_day < DATE '2026-10-01'
GROUP BY pull_request_created_month
ORDER BY pull_request_created_month;
```

Swap the month dimension for `pull_request_created_week`, `pull_request_repository_name`,
`pull_request_title_category` or `pull_request_repository_language` to investigate timing,
repository mix or explicit title conventions. The issue, discussion and comment
families have their own count, active-day, repository and UTC date fields listed below.
Only the selected populations are fetched. Prefix the SELECT with `EXPLAIN (SEMANTIC)`
to inspect the approved grain, population and expanded SQL without fetching records.

To compare a cohort, pass typed resource rows instead of writing one query per user:

```sql
PREPARE github_user_cohort AS
SELECT user_login, user_count, pull_request_count, issue_count
FROM engineering.semantic.github(users => $1)
GROUP BY user_login
ORDER BY user_login;
EXECUTE github_user_cohort([{'login': 'octocat'}, {'login': 'hubot'}]);
```

The profile count keeps users with no observed activity in the result. An empty
cohort returns no grouped rows. Use `repositories => [{'repository': 'owner/name'}]`
for an explicit repository population. Each cohort is an alternative to its singular
scope inputs. Activity entities can combine author and repository selections to
retrieve their intersection; discovery exposes the inputs and examples.

The same entities can start from repository, organization and team populations.
The optional second input below selects an author within the repository; NULL
includes every visible author, including records whose author has been deleted.
Discussion comment counts follow every page of threaded replies.

```sql
PREPARE github_repository_activity AS
SELECT pull_request_count, issue_count, discussion_count,
       issue_comment_count, discussion_comment_count, commit_comment_count
FROM engineering.semantic.github(repository => $1, user => $2);
EXECUTE github_repository_activity('Query-farm/crossfield', NULL);
```

Retrieve public organization memberships from a user, or repositories accessible
to a team. GitHub's user-to-organization endpoint returns public memberships only;
it cannot establish the absence of a private membership.

```sql
PREPARE github_member_organizations AS
SELECT organization_login, organization_count
FROM engineering.semantic.github(user => $1)
GROUP BY organization_login
ORDER BY organization_login;
EXECUTE github_member_organizations('octocat');
PREPARE github_team_repositories AS
SELECT repository_name, repository_count
FROM engineering.semantic.github(organization => $1, team_slug => $2)
GROUP BY repository_name
ORDER BY repository_name;
EXECUTE github_team_repositories('Query-farm', 'core');
```

Release inventory counts visible release identities, including drafts and prereleases,
and follows every asset-list page. Asset byte sizes and download counters describe
current metadata; the download total is cumulative, not downloads during a date range.
Release assets are separate from Actions artifacts.

```sql
PREPARE github_release_inventory AS
SELECT release_count, published_release_count, draft_release_count, prerelease_count,
       release_asset_count, release_asset_size_bytes, release_asset_download_count
FROM engineering.semantic.github(repository => $1);
EXECUTE github_release_inventory('Query-farm/crossfield');
```

CI outcomes count each workflow run once and jobs across all returned attempts.
A rerun can therefore leave one successful run alongside an earlier failed job.
Artifact counts include retained expired metadata and artifacts without a known run;
unknown run outcomes do not count as successes or failures.

```sql
PREPARE github_ci_outcomes AS
SELECT workflow_run_count, workflow_run_success_count, workflow_run_failure_count,
       workflow_job_count, workflow_job_failure_count,
       workflow_artifact_count, workflow_artifact_bytes
FROM engineering.semantic.github(repository => $1);
EXECUTE github_ci_outcomes('Query-farm/crossfield');
```

Check results start from a commit SHA, branch or tag and enumerate suites before
runs and annotations. Distinct rerun IDs and repeated annotation occurrences remain
separate observations. A branch or tag resolves when GitHub serves the request;
use a commit SHA when a fixed revision is required.

```sql
PREPARE github_check_results AS
SELECT check_suite_count, check_run_count, successful_check_run_count,
       failed_check_run_count, unfinished_check_run_count,
       check_annotation_count, failure_annotation_count
FROM engineering.semantic.github(repository => $1, git_ref => $2);
EXECUTE github_check_results('Query-farm/crossfield', 'main');
```

For a complete comparison, load the supplied SQL into the DuckDB CLI, then execute
its prepared examples. Dates are inclusive start and exclusive end:

```sql
.read models/generated-pilot/research.sql
EXECUTE github_activity_compare('octocat',
    '2026-08-01', '2026-09-01', '2026-09-01', '2026-10-01');
EXECUTE github_pr_focus('octocat',
    '2026-08-01', '2026-09-01', '2026-09-01', '2026-10-01');
EXECUTE github_activity_evidence('octocat', '2026-09-01', '2026-10-01');
```

Run the `.read` command from the worker repository root, or use an absolute path.
Clients can send the contents of `research.sql` as SQL; `.read` is a CLI command.
The SQL comes from `generation/examples/research/*.sql`; generation includes the same
monthly query in this guide and the prepared queries in the runnable file. All
statements also appear in `tests/crossfield/research_examples.test`.
Edit those source files, not the generated copies. Test expectations live separately
in `generation/examples/research/research_examples.test.in` and are never recorded
from engine output.

The file sets UTC and `crossfield_mode='semantic'`, so approved inner selections can
feed ordinary outer SQL for rates, unions and comparisons. These are editable
session queries, not model-owned saved reports or a required report interface.
`github_activity_compare` keeps six activity types separate, supplies period counts,
active days, known repositories and records per calendar day, and returns NULL for
percentage growth without a baseline. `github_pr_focus` shows count and share changes
by repository. `github_activity_evidence` returns original text, source IDs, creation
timestamps and URLs for all six populations. A grouped query has no rows for an empty
period; an ungrouped count returns zero. Zero is never a substitute for an API error.

The independent `researcher` fixture gives this August-to-September comparison;
these are test data, not observations about a real account:

| Activity | August | September |
| --- | ---: | ---: |
| Authored PRs | 2 | 3 |
| Authored issues | 2 | 3 |
| Authored discussions | 1 | 2 |
| Issue or PR comments | 2 | 2 |
| Discussion comments | 1 | 2 |
| Commit comments | 1 | 2 |

That is 9 versus 14 records across disjoint activity kinds, or 0.2903 versus 0.4667
records per calendar day (+60.74%). PR activity occupied two UTC days in each month.
`lab/sdk` accounts for two of September's three PRs; it was absent from the August
PR population. This supports “the observed repository mix changed.” It does not
establish a new personal interest or the user's first-ever work on that repository.
Evidence records explain the activity; NULL repository context remains visible for
a comment whose discussion was deleted. Distinct days and repositories cannot be
summed across activity kinds, months or categories.

The user-activity portion covers visible authored PRs, issues, discussions and the three comment
families. Complete user review submissions, authored commits, pushes, stars and
historical membership are outside it. Existing repository review metrics remain
available, but are not a complete user contribution timeline. Current titles, state
and primary language are observed now; creation-date filtering does not reconstruct
historical content. Classifiers recognize only literal `docs:`, `fix:`, `feat:`,
`refactor:` and `test:` prefixes, case-insensitively; other titles stay `unclassified`.
Repository language is context, not a claim about changed files or personal interests.

User connections follow all advertised pages without a generated row or page cap,
with explicit author checks. Provider quotas, operation deadlines and native
cancellation still apply. Date predicates currently filter after source retrieval, so narrow windows
can still read full visible histories. Independent live scans are not an atomic
GitHub snapshot; saved snapshots and calendar-gap filling are not part of this
example. Failed or incomplete source retrieval raises an exception. Tests run the
actual worker and native engine against deterministic HTTP fixtures, not live GitHub.

## Review timing and activity composition

These freely selectable metrics use model-owned stages and windows. The examples below use independently tested fixture accounts; replace example/researcher/alice/bob/carol with your repository owner and users. Keep every selected grouping column for fixed-grain windows.

First-review latency gives each reviewed PR one observation before the mean, median and P90. Pending or untimestamped records do not qualify; unreviewed PRs are absent, not zero-hour responses.

```sql
SELECT review_record_count, submitted_review_count, reviewed_pr_count,
       mean_first_review_hours,
       median_first_review_hours, p90_first_review_hours
FROM engineering.semantic.github(owner=>'example');
```

Latest-review counts select one submitted record per PR/reviewer by timestamp, then review ID. Missing timestamps and anonymous reviewers are excluded. Latest approvals count PR/reviewer pairs, not distinct people across PRs or GitHub merge eligibility.

```sql
SELECT latest_reviewer_review_count, latest_approved_reviewer_count
FROM engineering.semantic.github(owner=>'example');
```

Repository shares require the complete approved user/month/repository grain, including identity and label columns. QUALIFY may select displayed groups after the denominator is computed; a repository WHERE filter cannot redefine that denominator. Hide identity columns in an outer projection if desired. An empty denominator yields NULL.

```sql
SELECT author_id, author_login, pull_request_created_month, activity_repository_id, pull_request_repository_name,
       pull_request_count, monthly_pr_total,
       monthly_repository_pr_share
FROM engineering.semantic.github(user=>'researcher')
GROUP BY author_id, author_login, pull_request_created_month,
         activity_repository_id, pull_request_repository_name;
```

Monthly ranks compare only the selected visible user cohort. Equal counts share rank; users with no observed PRs have no activity row. This is activity volume, not an impact score.

```sql
SELECT author_id, author_login, pull_request_created_month, pull_request_count, monthly_user_pr_rank
FROM engineering.semantic.github(users=>[{'login':'alice'},{'login':'bob'},{'login':'researcher'},{'login':'carol'}])
GROUP BY author_id, author_login, pull_request_created_month;
```

UTC days and fixed US Eastern reporting days are explicit alternatives. The _eastern_day dimension uses America/New_York daylight-saving rules, never a GitHub profile location. Keep the required session TimeZone='UTC'; a changed session raises TIMEZONE_MISMATCH.

```sql
SELECT pull_request_created_day, pull_request_created_eastern_day, pull_request_count
FROM engineering.semantic.github(user=>'researcher')
GROUP BY pull_request_created_day, pull_request_created_eastern_day;
```

## Entity contracts

### `repositories`

Canonical repositories selected directly, by owner/organization, by explicit cohort, or by team access. Detail retains the API node identity and reported primary language from each existing repository response; language may be NULL and is not a language-byte inventory.

Grain: `repository_id`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `repositories__attested_organizations` | `attested_repositories` | All advertised cursor pages of repositories with at least one attested artifact under the optional predicate filter; stable IDs are checked during canonical hydration. |
| `repositories__public_inventory` | `public_repositories` | Global public repository creation-order inventory, preserving all since-cursor pages; an explicit selector prevents accidental global enumeration. |
| `repositories__authenticated_type` | `repository_access_type` | All explicitly accessible authenticated repositories in the selected access/visibility/affiliation population. Incompatible API filter families fail before HTTP. |
| `repositories__authenticated` | `authenticated_user` | All explicitly accessible authenticated repositories in the selected access/visibility/affiliation population. Incompatible API filter families fail before HTTP. |
| `repositories__forks` | `forks_of` | Visible fork repositories of one selected parent, hydrated to the same canonical repository entity. |
| `repositories__numeric_teams` | `team_numeric_id` | Repositories visible through the selected numeric team identity; pinned legacy retrieval includes inherited access when returned. |
| `repositories__teams` | `team_slug` | Repositories accessible to the selected team, including inherited team access as returned by GitHub. |
| `repositories__lookup` | `owner`, `repository`, `organization`, `repositories` | Canonical repositories selected directly, by owner/organization, by explicit cohort, or by team access. Detail retains the API node identity and reported primary language from each existing repository response; language may be NULL and is not a language-byte inventory. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `repository_id` | `BIGINT` | no |
| `repository` | `VARCHAR` | no |
| `name` | `VARCHAR` | no |
| `owner_login` | `VARCHAR` | no |
| `private` | `BOOLEAN` | no |
| `description` | `VARCHAR` | yes |
| `owner_account_id` | `BIGINT` | no |
| `owner_account_type` | `VARCHAR` | no |
| `topic_names` | `VARCHAR[]` | yes |
| `repository_node_id` | `VARCHAR` | no |
| `repository_language` | `VARCHAR` | yes |

Approved metrics:

- `repository_count`: Visible repository entities, including repositories with no PRs or labels.

### `pull_requests`

Selected pull requests at stable repository/number grain. Repository, owner or organization lists current PRs; user/users and label scopes discover then hydrate full PR responses. Explicit repository/number lookup also returns full detail. Repository and author selection intersect. Common identity, branch/repository snapshots and state fields are retained across routes. Full-response counters and mergeability remain NULL on list routes; no extra per-PR requests are added. Embedded milestone/auto-merge records are snapshots, not complete relationship populations.

Grain: `repository_id`, `pull_request_number`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `pull_requests__lookup` | `pull_request_number` | One PR by repository and number, including full-response change counters and mergeability. |
| `pull_requests__labels` | `label` | All visible pull requests carrying the selected exact repository label. |
| `pull_requests__repositories` | `owner`, `repository`, `organization`, `repositories` | All selected repository PRs through complete list pagination. Fields exclusive to a full PR response remain NULL; this route does not request every PR separately. |
| `pull_requests__authors` | `user`, `users` | Selected pull requests at stable repository/number grain. Repository, owner or organization lists current PRs; user/users and label scopes discover then hydrate full PR responses. Explicit repository/number lookup also returns full detail. Repository and author selection intersect. Common identity, branch/repository snapshots and state fields are retained across routes. Full-response counters and mergeability remain NULL on list routes; no extra per-PR requests are added. Embedded milestone/auto-merge records are snapshots, not complete relationship populations. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `repository_id` | `BIGINT` | no |
| `repository` | `VARCHAR` | no |
| `pull_request_id` | `BIGINT` | no |
| `pull_request_number` | `BIGINT` | no |
| `state` | `VARCHAR` | no |
| `title` | `VARCHAR` | no |
| `body` | `VARCHAR` | yes |
| `draft` | `BOOLEAN` | yes |
| `created_at` | `TIMESTAMP WITH TIME ZONE` | no |
| `updated_at` | `TIMESTAMP WITH TIME ZONE` | no |
| `closed_at` | `TIMESTAMP WITH TIME ZONE` | yes |
| `merged_at` | `TIMESTAMP WITH TIME ZONE` | yes |
| `author_id` | `BIGINT` | yes |
| `author_login` | `VARCHAR` | yes |
| `html_url` | `VARCHAR` | no |
| `labels` | `STRUCT("id" BIGINT, "name" VARCHAR)[]` | no |
| `assignees` | `STRUCT("id" BIGINT, "login" VARCHAR)[]` | yes |
| `pull_request_node_id` | `VARCHAR` | no |
| `repository_node_id` | `VARCHAR` | no |
| `repository_language` | `VARCHAR` | yes |
| `url` | `VARCHAR` | no |
| `diff_url` | `VARCHAR` | no |
| `patch_url` | `VARCHAR` | no |
| `issue_url` | `VARCHAR` | no |
| `commits_url` | `VARCHAR` | no |
| `review_comments_url` | `VARCHAR` | no |
| `review_comment_url` | `VARCHAR` | no |
| `comments_url` | `VARCHAR` | no |
| `statuses_url` | `VARCHAR` | no |
| `locked` | `BOOLEAN` | no |
| `active_lock_reason` | `VARCHAR` | yes |
| `merge_commit_sha` | `VARCHAR` | yes |
| `author_association` | `VARCHAR` | no |
| `base` | `STRUCT("label" VARCHAR, "ref" VARCHAR, "sha" VARCHAR, "repo" STRUCT("id" BIGINT, "node_id" VARCHAR, "full_name" VARCHAR))` | no |
| `base_ref` | `VARCHAR` | no |
| `head` | `STRUCT("label" VARCHAR, "ref" VARCHAR, "sha" VARCHAR, "repo" STRUCT("id" BIGINT, "node_id" VARCHAR, "full_name" VARCHAR))` | no |
| `head_ref` | `VARCHAR` | no |
| `milestone` | `STRUCT("id" BIGINT, "number" BIGINT, "title" VARCHAR, "state" VARCHAR, "due_on" TIMESTAMP WITH TIME ZONE)` | yes |
| `auto_merge` | `STRUCT("enabled_by" STRUCT("id" BIGINT, "login" VARCHAR, "type" VARCHAR), "merge_method" VARCHAR, "commit_title" VARCHAR, "commit_message" VARCHAR)` | yes |
| `comments_count` | `BIGINT` | yes |
| `review_comments_count` | `BIGINT` | yes |
| `commits_count` | `BIGINT` | yes |
| `additions` | `BIGINT` | yes |
| `deletions` | `BIGINT` | yes |
| `changed_files` | `BIGINT` | yes |
| `merged` | `BOOLEAN` | yes |
| `mergeable` | `BOOLEAN` | yes |
| `rebaseable` | `BOOLEAN` | yes |
| `mergeable_state` | `VARCHAR` | yes |
| `maintainer_can_modify` | `BOOLEAN` | yes |
| `merged_by` | `STRUCT("id" BIGINT, "login" VARCHAR, "type" VARCHAR)` | yes |
| `merge_hours` | `DOUBLE` | yes |
| `pull_request_created_day` | `DATE` | no |
| `pull_request_merged_day` | `DATE` | yes |
| `pull_request_created_week` | `DATE` | no |
| `pull_request_created_month` | `DATE` | no |
| `pull_request_title_category` | `VARCHAR` | no |

Approved metrics:

- `pull_request_count`: All selected open and closed PR records; each PR counts once regardless of reviews.
- `merged_prs`: PRs with a merge timestamp, including bots and draft waiting time.
- `median_merge_hours`: Exact continuous median elapsed UTC hours from PR creation to merge. NULL for an empty merged cohort; independent of review multiplicity.
- `pull_request_active_days`: Distinct UTC creation dates represented by selected visible records. Non-additive across repositories and other overlapping groups; inactive dates contribute zero.
- `pull_request_repository_count`: Distinct known repository identities represented by selected visible records. Non-additive across dates/categories; unknown repository context is excluded.
- `pull_request_detail_observation_count`: Selected PRs retrieved through a full-response route with reported detail counters. List-only observations are excluded.
- `pull_request_reported_comment_count`: Sum of reported issue comments on selected full PR responses; unavailable list observations are NULL. Current PR snapshots, not event counts in a date window; shared commits/files may occur in multiple PRs.
- `pull_request_reported_review_comment_count`: Sum of reported review comments on selected full PR responses; unavailable list observations are NULL. Current PR snapshots, not event counts in a date window; shared commits/files may occur in multiple PRs.
- `pull_request_reported_commit_count`: Sum of reported included commits on selected full PR responses; unavailable list observations are NULL. Current PR snapshots, not event counts in a date window; shared commits/files may occur in multiple PRs.
- `pull_request_reported_additions`: Sum of reported added lines on selected full PR responses; unavailable list observations are NULL. Current PR snapshots, not event counts in a date window; shared commits/files may occur in multiple PRs.
- `pull_request_reported_deletions`: Sum of reported deleted lines on selected full PR responses; unavailable list observations are NULL. Current PR snapshots, not event counts in a date window; shared commits/files may occur in multiple PRs.
- `pull_request_reported_changed_file_count`: Sum of reported changed files on selected full PR responses; unavailable list observations are NULL. Current PR snapshots, not event counts in a date window; shared commits/files may occur in multiple PRs.

### `pull_request_reviews`

Review records including pending and dismissed records; reviewer and PR-author roles remain distinct. Not latest reviewer decisions or merge eligibility. User/users selects PR authors, never reviewers.

Grain: `repository_id`, `pull_request_number`, `review_id`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `pull_request_reviews__lookup` | `review_id` | One visible review identified within one pull request; review author remains separate from the PR author. |
| `pull_request_reviews__labels` | `label` | All visible pull requests carrying the selected exact repository label. |
| `pull_request_reviews__repositories` | `owner`, `repository`, `organization`, `repositories` | Review records including pending and dismissed records; reviewer and PR-author roles remain distinct. Not latest reviewer decisions or merge eligibility. User/users selects PR authors, never reviewers. |
| `pull_request_reviews__authors` | `user`, `users` | Review records including pending and dismissed records; reviewer and PR-author roles remain distinct. Not latest reviewer decisions or merge eligibility. User/users selects PR authors, never reviewers. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `repository_id` | `BIGINT` | no |
| `repository` | `VARCHAR` | no |
| `pull_request_number` | `BIGINT` | no |
| `author_id` | `BIGINT` | yes |
| `author_login` | `VARCHAR` | yes |
| `review_id` | `BIGINT` | no |
| `pull_request_created_at` | `TIMESTAMP WITH TIME ZONE` | no |
| `node_id` | `VARCHAR` | no |
| `state` | `VARCHAR` | no |
| `body` | `VARCHAR` | no |
| `submitted_at` | `TIMESTAMP WITH TIME ZONE` | yes |
| `commit_id` | `VARCHAR` | yes |
| `user` | `STRUCT("avatar_url" VARCHAR, "email" VARCHAR, "events_url" VARCHAR, "followers_url" VARCHAR, "following_url" VARCHAR, "gists_url" VARCHAR, "gravatar_id" VARCHAR, "html_url" VARCHAR, "id" BIGINT, "login" VARCHAR, "name" VARCHAR, "node_id" VARCHAR, "organizations_url" VARCHAR, "received_events_url" VARCHAR, "repos_url" VARCHAR, "site_admin" BOOLEAN, "starred_at" VARCHAR, "starred_url" VARCHAR, "subscriptions_url" VARCHAR, "type" VARCHAR, "url" VARCHAR, "user_view_type" VARCHAR)` | yes |
| `html_url` | `VARCHAR` | no |
| `pull_request_url` | `VARCHAR` | no |
| `author_association` | `VARCHAR` | no |
| `links` | `STRUCT("html" STRUCT("href" VARCHAR), "pull_request" STRUCT("href" VARCHAR))` | no |
| `reviewer_id` | `BIGINT` | yes |
| `reviewer_login` | `VARCHAR` | yes |
| `review_submitted_day` | `DATE` | yes |

Approved metrics:

- `submitted_review_count`: Review records whose current state is APPROVED, CHANGES_REQUESTED, COMMENTED or DISMISSED. Pending reviews are excluded; repeated submissions by one reviewer count separately.
- `approved_review_count`: Review records currently marked APPROVED. Dismissed approvals do not qualify; this is not distinct approvers or merge eligibility.

### `repository_labels`

Canonical repository label definitions with GraphQL and REST discovery, exact name, issue/PR attachment and milestone-used-label routes; every route hydrates the same node identity and fields.

Grain: `repository_id`, `label_id`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `repository_labels__lookup` | `label` | Canonical Label identities discovered through get-label and hydrated by node ID; milestone listing contains labels used by its work items, not all repository label definitions. |
| `repository_labels__rest_repositories` | `label_collection` | Canonical Label identities discovered through list-labels-for-repo and hydrated by node ID; milestone listing contains labels used by its work items, not all repository label definitions. |
| `repository_labels__rest_issues` | `label_issue_number` | Canonical Label identities discovered through list-labels-on-issue and hydrated by node ID; milestone listing contains labels used by its work items, not all repository label definitions. |
| `repository_labels__milestones` | `milestone_number` | Canonical Label identities discovered through list-labels-for-milestone and hydrated by node ID; milestone listing contains labels used by its work items, not all repository label definitions. |
| `repository_labels__issues` | `issue_number` | Labels attached to the selected issue. |
| `repository_labels__pull_requests` | `pull_request_number` | Labels attached to the selected pullRequest. |
| `repository_labels__repositories` | `owner`, `repository`, `organization`, `repositories` | Canonical repository label definitions with GraphQL and REST discovery, exact name, issue/PR attachment and milestone-used-label routes; every route hydrates the same node identity and fields. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `repository_id` | `BIGINT` | no |
| `repository` | `VARCHAR` | no |
| `label_id` | `VARCHAR` | no |
| `name` | `VARCHAR` | no |
| `color` | `VARCHAR` | no |
| `description` | `VARCHAR` | yes |
| `is_default` | `BOOLEAN` | no |
| `created_at` | `TIMESTAMP WITH TIME ZONE` | yes |
| `updated_at` | `TIMESTAMP WITH TIME ZONE` | yes |
| `url` | `VARCHAR` | no |

Approved metrics:

- `label_count`: Current label definitions, including unused labels; not issue or pull-request label assignments.

### `organizations`

Canonical organizations selected directly, through public user memberships, or through repository ownership.

Grain: `organization_id`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `organizations__directory` | `organization_directory` | All advertised since-based pages of the public organization directory, optionally after the selected numeric ID. |
| `organizations__authenticated` | `authenticated_user` | Credential-authorized organizations returned by /user/orgs. Fine-grained tokens may return an empty list by API contract; this does not prove absence of memberships. |
| `organizations__lookup` | `organization` | Canonical organizations selected directly, through public user memberships, or through repository ownership. |
| `organizations__members` | `user`, `users` | Public organization memberships of the selected personal users; private memberships are not returned by this endpoint. |
| `organizations__repository_owners` | `owner`, `repository`, `repositories` | Distinct organization owners of selected repositories; personal owners produce no organization. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `organization_id` | `BIGINT` | no |
| `organization_login` | `VARCHAR` | no |
| `name` | `VARCHAR` | yes |
| `description` | `VARCHAR` | yes |
| `created_at` | `TIMESTAMP WITH TIME ZONE` | no |

Approved metrics:

- `organization_count`: Selected organization identities, including organizations with no visible members, teams or repositories.

### `organization_memberships`

Organization/user membership pairs. Organization scope follows credential visibility; user scope enumerates public memberships only. Membership-object routes preserve active versus pending state and role. Enterprise team slugs are an observed list capped at 100 by GitHub, not a complete enterprise membership inventory. Summary endpoints establish active state but do not expose membership-object detail; those detail columns remain NULL.

Grain: `organization_id`, `user_id`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `organization_memberships__public_members` | `organization_public_members` | Active publicly declared organization memberships; private memberships are outside this population. |
| `organization_memberships__lookup` | `membership_user` | Visible membership object records retaining active or pending state. Exact missing affiliation and permission failures propagate. |
| `organization_memberships__authenticated` | `authenticated_user` | Authenticated account membership records across all organizations or one explicit organization. Optional state filters apply to the selected rows; pending records are retained but not counted as active members. Missing exact affiliation and permission errors fail. |
| `organization_memberships__organizations` | `organization` | Organization/user membership pairs. Organization scope follows credential visibility; user scope enumerates public memberships only. Membership-object routes preserve active versus pending state and role. Enterprise team slugs are an observed list capped at 100 by GitHub, not a complete enterprise membership inventory. Summary endpoints establish active state but do not expose membership-object detail; those detail columns remain NULL. |
| `organization_memberships__members` | `user`, `users` | Public memberships of selected users. This reverse endpoint excludes private memberships, even with authentication. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `organization_id` | `BIGINT` | no |
| `user_id` | `BIGINT` | no |
| `member_login` | `VARCHAR` | no |
| `member_type` | `VARCHAR` | no |
| `organization_login` | `VARCHAR` | no |
| `membership_state` | `VARCHAR` | no |
| `membership_role` | `VARCHAR` | yes |
| `direct_membership` | `BOOLEAN` | yes |
| `enterprise_team_slugs` | `VARCHAR[]` | yes |
| `membership_url` | `VARCHAR` | yes |
| `organization_url` | `VARCHAR` | yes |
| `can_create_repository` | `BOOLEAN` | yes |
| `organization_node_id` | `VARCHAR` | yes |
| `organization_api_url` | `VARCHAR` | yes |
| `organization_repos_url` | `VARCHAR` | yes |
| `organization_events_url` | `VARCHAR` | yes |
| `organization_hooks_url` | `VARCHAR` | yes |
| `organization_issues_url` | `VARCHAR` | yes |
| `organization_members_url` | `VARCHAR` | yes |
| `organization_public_members_url` | `VARCHAR` | yes |
| `organization_avatar_url` | `VARCHAR` | yes |
| `organization_description` | `VARCHAR` | yes |
| `observed_member_name` | `VARCHAR` | yes |
| `observed_member_email` | `VARCHAR` | yes |
| `observed_member_login` | `VARCHAR` | yes |
| `observed_member_id` | `BIGINT` | yes |
| `observed_member_node_id` | `VARCHAR` | yes |
| `observed_member_avatar_url` | `VARCHAR` | yes |
| `observed_member_gravatar_id` | `VARCHAR` | yes |
| `observed_member_url` | `VARCHAR` | yes |
| `observed_member_html_url` | `VARCHAR` | yes |
| `observed_member_followers_url` | `VARCHAR` | yes |
| `observed_member_following_url` | `VARCHAR` | yes |
| `observed_member_gists_url` | `VARCHAR` | yes |
| `observed_member_starred_url` | `VARCHAR` | yes |
| `observed_member_subscriptions_url` | `VARCHAR` | yes |
| `observed_member_organizations_url` | `VARCHAR` | yes |
| `observed_member_repos_url` | `VARCHAR` | yes |
| `observed_member_events_url` | `VARCHAR` | yes |
| `observed_member_received_events_url` | `VARCHAR` | yes |
| `observed_member_type` | `VARCHAR` | yes |
| `observed_member_site_admin` | `BOOLEAN` | yes |
| `observed_member_starred_at` | `VARCHAR` | yes |
| `observed_member_user_view_type` | `VARCHAR` | yes |

Approved metrics:

- `organization_member_count`: Active visible organization/account relationships. Pending invitations are retained as membership records but excluded from this active member count.
- `organization_membership_record_count`: Selected active or pending organization membership records at organization/account grain.
- `pending_organization_membership_count`: Selected organization memberships still pending acceptance; not active organization members.

### `teams`

Canonical teams selected by organization, one team slug, or repository access. Numeric, authenticated-account and immediate-child retrieval routes share stable team identity. Full-team-only fields remain NULL on summary routes; pinned numeric routes are deprecated upstream.

Grain: `team_id`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `teams__invitations` | `organization_invitation_id` | Teams associated with one invitation, hydrated to canonical team identity. |
| `teams__numeric_identity` | `team_numeric_id` | One exact team by stable numeric identity through the pinned deprecated endpoint. |
| `teams__authenticated` | `authenticated_user` | All advertised pages of teams available to the authenticated account; fine-grained token ownership limits the visible organizations. |
| `teams__children_named` | `parent_team_slug` | Immediate child teams only; each child hydrates to its canonical stable identity. |
| `teams__children_numeric` | `parent_team_numeric_id` | Immediate child teams only; each child hydrates to its canonical stable identity. |
| `teams__organizations` | `organization` | Canonical teams selected by organization, one team slug, or repository access. Numeric, authenticated-account and immediate-child retrieval routes share stable team identity. Full-team-only fields remain NULL on summary routes; pinned numeric routes are deprecated upstream. |
| `teams__repositories` | `owner`, `repository`, `repositories` | Distinct teams with access to the selected organization-owned repositories; requires permission to enumerate repository teams. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `organization_id` | `BIGINT` | no |
| `team_id` | `BIGINT` | no |
| `team_slug` | `VARCHAR` | no |
| `team_name` | `VARCHAR` | no |
| `description` | `VARCHAR` | yes |
| `privacy` | `VARCHAR` | yes |
| `team_type` | `VARCHAR` | no |
| `organization_login` | `VARCHAR` | no |
| `node_id` | `VARCHAR` | no |
| `url` | `VARCHAR` | no |
| `html_url` | `VARCHAR` | no |
| `notification_setting` | `VARCHAR` | yes |
| `permission` | `VARCHAR` | no |
| `members_url` | `VARCHAR` | no |
| `repositories_url` | `VARCHAR` | no |
| `owning_organization_id` | `BIGINT` | yes |
| `enterprise_id` | `BIGINT` | yes |
| `parent` | `STRUCT("id" BIGINT, "node_id" VARCHAR, "url" VARCHAR, "members_url" VARCHAR, "name" VARCHAR, "description" VARCHAR, "permission" VARCHAR, "privacy" VARCHAR, "notification_setting" VARCHAR, "html_url" VARCHAR, "repositories_url" VARCHAR, "slug" VARCHAR, "ldap_dn" VARCHAR, "type" VARCHAR, "organization_id" BIGINT, "enterprise_id" BIGINT)` | yes |
| `parent_team_id` | `BIGINT` | yes |
| `created_at` | `TIMESTAMP WITH TIME ZONE` | yes |
| `updated_at` | `TIMESTAMP WITH TIME ZONE` | yes |
| `members_count` | `BIGINT` | yes |
| `repos_count` | `BIGINT` | yes |
| `ldap_dn` | `VARCHAR` | yes |

Approved metrics:

- `team_count`: Current visible team identities in the selected organization, including empty teams.

### `team_memberships`

Effective membership returned for each visible team. One person in two teams contributes two memberships. Child-team membership may be included by GitHub; optional role and inherited fields remain NULL when absent. Exact object routes retain pending state. Active member lists do not expose membership-object URLs; object routes do not expose inherited status, which remains NULL.

Grain: `team_id`, `user_id`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `team_memberships__lookup` | `team_member_user` | Exact visible team/account membership with active or pending state; missingmembership404 fails. |
| `team_memberships__authenticated` | `authenticated_user` | Membership objects for every team returned for the authenticated account; token visibility scopes the population. |
| `team_memberships__numeric_identity` | `team_numeric_id` | All advertised pages of active effective members, including inherited membership, of one numeric team. |
| `team_memberships__organizations` | `organization` | Visible organization or team membership pairs, including inherited members as returned by GitHub; user/users optionally selects the member identity. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `organization_id` | `BIGINT` | no |
| `team_id` | `BIGINT` | no |
| `user_id` | `BIGINT` | no |
| `team_member_login` | `VARCHAR` | no |
| `member_role` | `VARCHAR` | yes |
| `membership_inherited` | `BOOLEAN` | yes |
| `organization_login` | `VARCHAR` | no |
| `team_slug` | `VARCHAR` | no |
| `membership_state` | `VARCHAR` | no |
| `membership_url` | `VARCHAR` | yes |

Approved metrics:

- `team_membership_count`: Active effective team/account relationships, including inherited members; pending invitations are excluded.
- `team_membership_record_count`: Selected active and pending team/account membership records.
- `pending_team_membership_count`: Selected pending team membership records, excluding active effective members.

### `users`

Canonical personal user profiles selected by identity, organization membership, team membership, or repository collaboration. Numeric identity, authenticated identity and explicit global directory routes preserve that personal User-only population.

Grain: `user_id`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `users__numeric_identity` | `user_account_id` | One numeric account ID, retained only when it is a personal User account. Bot and Organization accounts are excluded consistently with the canonical users contract. |
| `users__authenticated` | `authenticated_user` | The authenticated personal user account, resolved through /user. |
| `users__directory` | `user_directory` | Personal User accounts from the global public directory, optionally strictly after user_since_id. Organization and Bot rows are excluded before profile hydration; all advertised since-based pages are exhausted. |
| `users__lookup` | `user`, `users` | Canonical personal user profiles selected by identity, organization membership, team membership, or repository collaboration. Numeric identity, authenticated identity and explicit global directory routes preserve that personal User-only population. |
| `users__team_members` | `team_slug` | Personal user profiles for credential-visible team members. |
| `users__organization_members` | `organization` | Personal user profiles for credential-visible organization members. |
| `users__repository_collaborators` | `owner`, `repository`, `repositories` | Distinct collaborators visible to the credentials across the selected repositories. Access denials propagate. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `user_id` | `BIGINT` | no |
| `user_login` | `VARCHAR` | no |
| `account_type` | `VARCHAR` | no |
| `name` | `VARCHAR` | yes |
| `created_at` | `TIMESTAMP WITH TIME ZONE` | no |

Approved metrics:

- `user_count`: Selected personal user accounts, including users with no visible authored PRs.

### `issues`

Canonical GitHub issues across authored, repository, label, filtered REST, authenticated participation and linked-issue retrieval. GraphQL node identity and field values stay consistent; REST Issue endpoints exclude pull requests before hydration. Authenticated participation is not authorship. Common lifecycle, rendered-body, sub-issue summary and milestone observations come from existing GraphQL selections. REST-only actor, assignee, type, reaction and dependency snapshots are NULL on GraphQL-only routes; adding fields never introduces an extra request. REST reaction and dependency counts and GraphQL sub-issue counts are upstream observations; no nested connection populations are selected or declared complete.

Grain: `issue_node_id`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `issues__nodes` | `issue_node_id` | Exact Issue node identity, retaining actual repository and author context from GraphQL; other node kinds fail or return no Issue. |
| `issues__lookup` | `issue_number` | One canonical Issue discovered by REST repository/number and hydrated by node ID; pull requests are excluded. A transferred issue retains its current canonical repository. |
| `issues__viewer_visible` | `viewer_issues` | Authenticated-user issue participation population from list; filter defaults to assigned and does not imply authorship. Pull requests are excluded before canonical hydration. |
| `issues__viewer_member` | `viewer_member_issues` | Authenticated-user issue participation population from list-for-authenticated-user; filter defaults to assigned and does not imply authorship. Pull requests are excluded before canonical hydration. |
| `issues__viewer_organization` | `viewer_organization_issues` | Authenticated-user issue participation population from list-for-org; filter defaults to assigned and does not imply authorship. Pull requests are excluded before canonical hydration. |
| `issues__filtered_repositories` | `issue_state`, `issue_assignee`, `issue_creator`, `issue_mentioned`, `issue_labels`, `issue_milestone`, `issue_since` | REST-filtered issue population; state defaults to open when omitted, all advertised pages are followed, PR records are excluded and identities hydrate through GraphQL. |
| `issues__parent_of` | `issue_parent_of` | Canonical linked issues reached by get-parent. Target node identities preserve cross-repository relationships; missing parent or unavailable relationship access remains an upstream error. |
| `issues__children_of` | `issue_children_of` | Canonical linked issues reached by list-sub-issues. Target node identities preserve cross-repository relationships; missing parent or unavailable relationship access remains an upstream error. |
| `issues__blocked_by` | `issue_blocked_by` | Canonical linked issues reached by list-dependencies-blocked-by. Target node identities preserve cross-repository relationships; missing parent or unavailable relationship access remains an upstream error. |
| `issues__blocking` | `issue_blocking` | Canonical linked issues reached by list-dependencies-blocking. Target node identities preserve cross-repository relationships; missing parent or unavailable relationship access remains an upstream error. |
| `issues__related_to` | `issue_related_to` | Canonical linked issues reached by list-relates-to. Target node identities preserve cross-repository relationships; missing parent or unavailable relationship access remains an upstream error. |
| `issues__labels` | `label` | All visible issues carrying the selected exact repository label. |
| `issues__repositories` | `owner`, `repository`, `organization`, `repositories` | All visible issues in the selected repositories, across all authors. |
| `issues__authors` | `user`, `users` | Canonical GitHub issues across authored, repository, label, filtered REST, authenticated participation and linked-issue retrieval. GraphQL node identity and field values stay consistent; REST Issue endpoints exclude pull requests before hydration. Authenticated participation is not authorship. Common lifecycle, rendered-body, sub-issue summary and milestone observations come from existing GraphQL selections. REST-only actor, assignee, type, reaction and dependency snapshots are NULL on GraphQL-only routes; adding fields never introduces an extra request. REST reaction and dependency counts and GraphQL sub-issue counts are upstream observations; no nested connection populations are selected or declared complete. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `author_id` | `BIGINT` | yes |
| `issue_node_id` | `VARCHAR` | no |
| `created_at` | `TIMESTAMP WITH TIME ZONE` | no |
| `updated_at` | `TIMESTAMP WITH TIME ZONE` | no |
| `url` | `VARCHAR` | no |
| `body` | `VARCHAR` | no |
| `repository_node_id` | `VARCHAR` | no |
| `repository_name` | `VARCHAR` | no |
| `repository_language` | `VARCHAR` | yes |
| `author_login` | `VARCHAR` | yes |
| `number` | `BIGINT` | no |
| `title` | `VARCHAR` | no |
| `state` | `VARCHAR` | no |
| `closed_at` | `TIMESTAMP WITH TIME ZONE` | yes |
| `issue_id` | `BIGINT` | yes |
| `state_reason` | `VARCHAR` | yes |
| `body_html` | `VARCHAR` | no |
| `body_text` | `VARCHAR` | no |
| `closed` | `BOOLEAN` | no |
| `locked` | `BOOLEAN` | no |
| `active_lock_reason` | `VARCHAR` | yes |
| `author_association` | `VARCHAR` | no |
| `created_via_email` | `BOOLEAN` | no |
| `last_edited_at` | `TIMESTAMP WITH TIME ZONE` | yes |
| `published_at` | `TIMESTAMP WITH TIME ZONE` | yes |
| `is_pinned` | `BOOLEAN` | yes |
| `sub_issue_total` | `BIGINT` | no |
| `sub_issue_completed` | `BIGINT` | no |
| `sub_issue_completion_percentage` | `BIGINT` | no |
| `milestone_node_id` | `VARCHAR` | yes |
| `milestone_title` | `VARCHAR` | yes |
| `milestone_state` | `VARCHAR` | yes |
| `milestone_due_on` | `TIMESTAMP WITH TIME ZONE` | yes |
| `milestone` | `STRUCT("id" VARCHAR, "number" BIGINT, "title" VARCHAR, "description" VARCHAR, "state" VARCHAR, "closed" BOOLEAN, "createdAt" TIMESTAMP WITH TIME ZONE, "updatedAt" TIMESTAMP WITH TIME ZONE, "closedAt" TIMESTAMP WITH TIME ZONE, "dueOn" TIMESTAMP WITH TIME ZONE, "url" VARCHAR, "progressPercentage" DOUBLE)` | yes |
| `reported_state_reason` | `VARCHAR` | yes |
| `assignee` | `STRUCT("id" BIGINT, "node_id" VARCHAR, "login" VARCHAR, "type" VARCHAR, "html_url" VARCHAR)` | yes |
| `assignees` | `STRUCT("id" BIGINT, "node_id" VARCHAR, "login" VARCHAR, "type" VARCHAR, "html_url" VARCHAR)[]` | yes |
| `closed_by` | `STRUCT("id" BIGINT, "node_id" VARCHAR, "login" VARCHAR, "type" VARCHAR, "html_url" VARCHAR)` | yes |
| `issue_type` | `STRUCT("id" BIGINT, "node_id" VARCHAR, "name" VARCHAR, "description" VARCHAR, "color" VARCHAR, "created_at" TIMESTAMP WITH TIME ZONE, "updated_at" TIMESTAMP WITH TIME ZONE, "is_enabled" BOOLEAN)` | yes |
| `reaction_summary` | `STRUCT("url" VARCHAR, "total_count" BIGINT, "+1" BIGINT, "-1" BIGINT, "laugh" BIGINT, "confused" BIGINT, "heart" BIGINT, "hooray" BIGINT, "eyes" BIGINT, "rocket" BIGINT)` | yes |
| `dependency_summary` | `STRUCT("blocked_by" BIGINT, "blocking" BIGINT, "total_blocked_by" BIGINT, "total_blocking" BIGINT)` | yes |
| `performed_via_app` | `STRUCT("id" BIGINT, "node_id" VARCHAR, "slug" VARCHAR, "name" VARCHAR, "html_url" VARCHAR)` | yes |
| `parent_issue_url` | `VARCHAR` | yes |
| `issue_created_day` | `DATE` | no |
| `issue_created_week` | `DATE` | no |
| `issue_created_month` | `DATE` | no |
| `issue_title_category` | `VARCHAR` | no |

Approved metrics:

- `issue_count`: Canonical visible Issue identities in the explicitly selected route population. Pull requests are excluded. Authored routes prove authorship; participation and repository routes do not.
- `issue_active_days`: Distinct UTC creation dates represented by selected visible records. Non-additive across repositories and other overlapping groups; inactive dates contribute zero.
- `issue_repository_count`: Distinct known repository identities represented by selected visible records. Non-additive across dates/categories; unknown repository context is excluded.

### `discussions`

Repository discussions started by the selected user across visible repositories. Repository scope includes all authors; user scope selects authors; combining both intersects by canonical author identity.

Grain: `discussion_node_id`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `discussions__lookup` | `discussion_number` | One discussion selected by repository and number, preserving the same public schema. |
| `discussions__repositories` | `owner`, `repository`, `organization`, `repositories` | All visible discussions in the selected repositories, across all authors. |
| `discussions__authors` | `user`, `users` | Repository discussions started by the selected user across visible repositories. Repository scope includes all authors; user scope selects authors; combining both intersects by canonical author identity. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `author_id` | `BIGINT` | yes |
| `discussion_node_id` | `VARCHAR` | no |
| `created_at` | `TIMESTAMP WITH TIME ZONE` | no |
| `updated_at` | `TIMESTAMP WITH TIME ZONE` | no |
| `url` | `VARCHAR` | no |
| `body` | `VARCHAR` | no |
| `repository_node_id` | `VARCHAR` | no |
| `repository_name` | `VARCHAR` | no |
| `repository_language` | `VARCHAR` | yes |
| `author_login` | `VARCHAR` | yes |
| `number` | `BIGINT` | no |
| `title` | `VARCHAR` | no |
| `discussion_created_day` | `DATE` | no |
| `discussion_created_week` | `DATE` | no |
| `discussion_created_month` | `DATE` | no |
| `discussion_title_category` | `VARCHAR` | no |

Approved metrics:

- `discussion_count`: Repository discussions started by the selected user across visible repositories. Each visible source identity counts once; event time is its creation timestamp.
- `discussion_active_days`: Distinct UTC creation dates represented by selected visible records. Non-additive across repositories and other overlapping groups; inactive dates contribute zero.
- `discussion_repository_count`: Distinct known repository identities represented by selected visible records. Non-additive across dates/categories; unknown repository context is excluded.

### `issue_comments`

Issue and pull-request conversation comments selected by author, repository population, or one issue/PR thread.

Grain: `comment_node_id`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `issue_comments__lookup` | `issue_comment_id` | One issue or PR conversation comment by exact numeric comment ID; preserves canonical comment node identity and author. |
| `issue_comments__threads` | `issue_number` | Conversation comments on one issue or pull request, with full pagination. |
| `issue_comments__repositories` | `owner`, `repository`, `organization`, `repositories` | All visible issue and pull-request conversation comments in selected repositories; review comments are a different entity. |
| `issue_comments__authors` | `user`, `users` | Issue and pull-request conversation comments selected by author, repository population, or one issue/PR thread. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `author_id` | `BIGINT` | yes |
| `comment_node_id` | `VARCHAR` | no |
| `created_at` | `TIMESTAMP WITH TIME ZONE` | no |
| `updated_at` | `TIMESTAMP WITH TIME ZONE` | no |
| `url` | `VARCHAR` | no |
| `body` | `VARCHAR` | yes |
| `repository_node_id` | `VARCHAR` | no |
| `repository_name` | `VARCHAR` | no |
| `repository_language` | `VARCHAR` | yes |
| `author_login` | `VARCHAR` | yes |
| `issue_comment_created_day` | `DATE` | no |
| `issue_comment_created_week` | `DATE` | no |
| `issue_comment_created_month` | `DATE` | no |

Approved metrics:

- `issue_comment_count`: Canonical issue and PR conversation comment identities in the selected repository, thread, exact or authored population; not review submissions or distinct issues. Only the authored route proves selected-user authorship.
- `issue_comment_active_days`: Distinct UTC creation dates represented by selected visible records. Non-additive across repositories and other overlapping groups; inactive dates contribute zero.
- `issue_comment_repository_count`: Distinct known repository identities represented by selected visible records. Non-additive across dates/categories; unknown repository context is excluded.

### `discussion_comments`

Discussion comments and replies selected by author, organization, repository, discussion, or parent comment; all child connections are fully paginated.

Grain: `comment_node_id`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `discussion_comments__replies` | `discussion_comment_id` | All threaded descendants of the selected discussion comment; the selected parent itself is excluded. |
| `discussion_comments__discussions` | `discussion_number` | All comments and recursively paginated replies on one discussion, across all authors. |
| `discussion_comments__organizations` | `organization` | Credential-visible discussion comments and replies across repositories of the selected organization. |
| `discussion_comments__repositories` | `owner`, `repository`, `organization`, `repositories` | All comments and recursively paginated replies on all discussions in the selected repositories. |
| `discussion_comments__authors` | `user`, `users` | Discussion comments and replies selected by author, organization, repository, discussion, or parent comment; all child connections are fully paginated. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `author_id` | `BIGINT` | yes |
| `comment_node_id` | `VARCHAR` | no |
| `created_at` | `TIMESTAMP WITH TIME ZONE` | no |
| `updated_at` | `TIMESTAMP WITH TIME ZONE` | no |
| `url` | `VARCHAR` | no |
| `body` | `VARCHAR` | no |
| `repository_node_id` | `VARCHAR` | yes |
| `repository_name` | `VARCHAR` | yes |
| `repository_language` | `VARCHAR` | yes |
| `author_login` | `VARCHAR` | yes |
| `subject_title` | `VARCHAR` | yes |
| `discussion_comment_created_day` | `DATE` | no |
| `discussion_comment_created_week` | `DATE` | no |
| `discussion_comment_created_month` | `DATE` | no |

Approved metrics:

- `discussion_comment_count`: Discussion comments and replies authored by the selected user. Missing discussion/repository context remains NULL and does not discard an attributable comment. Each visible source identity counts once; event time is its creation timestamp.
- `discussion_comment_active_days`: Distinct UTC creation dates represented by selected visible records. Non-additive across repositories and other overlapping groups; inactive dates contribute zero.
- `discussion_comment_repository_count`: Distinct known repository identities represented by selected visible records. Non-additive across dates/categories; unknown repository context is excluded.
- `discussion_comment_unknown_repository_count`: Visible discussion comments with unavailable discussion/repository context. Included in comment count, excluded from distinct known repositories.

### `commit_comments`

Commit comments authored by the selected user, not commits or code-change counts. Repository scope includes all authors; user scope selects authors; combining both intersects by canonical author identity. Repository and exact-commit REST listings share the canonical node grain with authored GraphQL. The additional numeric comment ID is nullable where GraphQL does not expose it. Commit SHA, path, position and author association preserve their pinned GraphQL equivalents; a deleted or inaccessible GraphQL commit association remains NULL. REST-only line and reaction-rollup metadata are not yet public canonical fields.

Grain: `comment_node_id`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `commit_comments__lookup` | `commit_comment_id` | Commit comments authored by the selected user, not commits or code-change counts. Repository scope includes all authors; user scope selects authors; combining both intersects by canonical author identity. Repository and exact-commit REST listings share the canonical node grain with authored GraphQL. The additional numeric comment ID is nullable where GraphQL does not expose it. Commit SHA, path, position and author association preserve their pinned GraphQL equivalents; a deleted or inaccessible GraphQL commit association remains NULL. REST-only line and reaction-rollup metadata are not yet public canonical fields. |
| `commit_comments__commit` | `commit_comment_sha` | Commit comments authored by the selected user, not commits or code-change counts. Repository scope includes all authors; user scope selects authors; combining both intersects by canonical author identity. Repository and exact-commit REST listings share the canonical node grain with authored GraphQL. The additional numeric comment ID is nullable where GraphQL does not expose it. Commit SHA, path, position and author association preserve their pinned GraphQL equivalents; a deleted or inaccessible GraphQL commit association remains NULL. REST-only line and reaction-rollup metadata are not yet public canonical fields. |
| `commit_comments__repositories` | `owner`, `repository`, `organization`, `repositories` | Commit comments authored by the selected user, not commits or code-change counts. Repository scope includes all authors; user scope selects authors; combining both intersects by canonical author identity. Repository and exact-commit REST listings share the canonical node grain with authored GraphQL. The additional numeric comment ID is nullable where GraphQL does not expose it. Commit SHA, path, position and author association preserve their pinned GraphQL equivalents; a deleted or inaccessible GraphQL commit association remains NULL. REST-only line and reaction-rollup metadata are not yet public canonical fields. |
| `commit_comments__authors` | `user`, `users` | Commit comments authored by the selected user, not commits or code-change counts. Repository scope includes all authors; user scope selects authors; combining both intersects by canonical author identity. Repository and exact-commit REST listings share the canonical node grain with authored GraphQL. The additional numeric comment ID is nullable where GraphQL does not expose it. Commit SHA, path, position and author association preserve their pinned GraphQL equivalents; a deleted or inaccessible GraphQL commit association remains NULL. REST-only line and reaction-rollup metadata are not yet public canonical fields. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `comment_node_id` | `VARCHAR` | no |
| `comment_id` | `BIGINT` | yes |
| `created_at` | `TIMESTAMP WITH TIME ZONE` | no |
| `updated_at` | `TIMESTAMP WITH TIME ZONE` | no |
| `url` | `VARCHAR` | no |
| `body` | `VARCHAR` | no |
| `author_id` | `BIGINT` | yes |
| `author_login` | `VARCHAR` | yes |
| `repository_node_id` | `VARCHAR` | no |
| `repository_name` | `VARCHAR` | no |
| `repository_language` | `VARCHAR` | yes |
| `commit_sha` | `VARCHAR` | yes |
| `path` | `VARCHAR` | yes |
| `position` | `BIGINT` | yes |
| `author_association` | `VARCHAR` | no |
| `repository_id` | `BIGINT` | yes |
| `commit_comment_created_day` | `DATE` | no |
| `commit_comment_created_week` | `DATE` | no |
| `commit_comment_created_month` | `DATE` | no |

Approved metrics:

- `commit_comment_count`: Commit comments authored by the selected user, not commits or code-change counts. Each visible source identity counts once; event time is its creation timestamp.
- `commit_comment_active_days`: Distinct UTC creation dates represented by selected visible records. Non-additive across repositories and other overlapping groups; inactive dates contribute zero.
- `commit_comment_repository_count`: Distinct known repository identities represented by selected visible records. Non-additive across dates/categories; unknown repository context is excluded.

### `releases`

Canonical GitHub releases selected through repository populations, exact release ID, exact tag, or GitHub latest-release lookup. The release author is the publisher role; publication time and draft/prerelease state remain explicit. Existing REST responses retain typed publisher and reaction snapshots, optional rendered notes and reported mention/reaction counters. Absent optional fields stay NULL. Embedded assets are deliberately excluded; release_assets traverses the complete asset endpoint.

Grain: `repository_id`, `release_id`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `releases__lookup` | `release_id` | One identified release visible to current credentials. |
| `releases__tags` | `release_tag` | The release associated with an exact tag visible to current credentials. |
| `releases__latest` | `release_selection` | GitHub latest-release endpoint: the latest published non-prerelease release, using GitHub's selection semantics; never inferred from the first list row. |
| `releases__repositories` | `owner`, `repository`, `organization`, `repositories` | All releases visible to current credentials in the repository population, including visible drafts and prereleases; all pages are consumed. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `repository_id` | `BIGINT` | no |
| `repository` | `VARCHAR` | no |
| `release_id` | `BIGINT` | no |
| `release_node_id` | `VARCHAR` | no |
| `tag_name` | `VARCHAR` | no |
| `target_commitish` | `VARCHAR` | no |
| `name` | `VARCHAR` | yes |
| `body` | `VARCHAR` | yes |
| `draft` | `BOOLEAN` | no |
| `prerelease` | `BOOLEAN` | no |
| `immutable` | `BOOLEAN` | yes |
| `created_at` | `TIMESTAMP WITH TIME ZONE` | no |
| `published_at` | `TIMESTAMP WITH TIME ZONE` | yes |
| `updated_at` | `TIMESTAMP WITH TIME ZONE` | yes |
| `html_url` | `VARCHAR` | no |
| `tarball_url` | `VARCHAR` | yes |
| `zipball_url` | `VARCHAR` | yes |
| `discussion_url` | `VARCHAR` | yes |
| `publisher_id` | `BIGINT` | no |
| `publisher_login` | `VARCHAR` | no |
| `publisher_type` | `VARCHAR` | no |
| `url` | `VARCHAR` | no |
| `assets_url` | `VARCHAR` | no |
| `upload_url` | `VARCHAR` | no |
| `body_html` | `VARCHAR` | yes |
| `body_text` | `VARCHAR` | yes |
| `mentions_count` | `BIGINT` | yes |
| `publisher` | `STRUCT("avatar_url" VARCHAR, "email" VARCHAR, "events_url" VARCHAR, "followers_url" VARCHAR, "following_url" VARCHAR, "gists_url" VARCHAR, "gravatar_id" VARCHAR, "html_url" VARCHAR, "id" BIGINT, "login" VARCHAR, "name" VARCHAR, "node_id" VARCHAR, "organizations_url" VARCHAR, "received_events_url" VARCHAR, "repos_url" VARCHAR, "site_admin" BOOLEAN, "starred_at" VARCHAR, "starred_url" VARCHAR, "subscriptions_url" VARCHAR, "type" VARCHAR, "url" VARCHAR, "user_view_type" VARCHAR)` | no |
| `reaction_summary` | `STRUCT("+1" BIGINT, "-1" BIGINT, "confused" BIGINT, "eyes" BIGINT, "heart" BIGINT, "hooray" BIGINT, "laugh" BIGINT, "rocket" BIGINT, "total_count" BIGINT, "url" VARCHAR)` | yes |
| `reaction_total_count` | `BIGINT` | yes |
| `release_published_day` | `DATE` | yes |

Approved metrics:

- `release_count`: Selected release records, including visible drafts and prereleases; one observation per stable repository/release identity.
- `published_release_count`: Selected release records with a publication instant, including prereleases.
- `release_publication_day_count`: Distinct UTC dates with publication among selected releases; NULL draft publication dates are excluded and counts are non-additive across repositories.
- `draft_release_count`: Visible releases marked draft. Draft visibility depends on caller permissions.
- `prerelease_count`: Selected releases marked prerelease, independently of draft status.
- `release_reported_mention_count`: Sum of current mention counters reported for selected releases. Missing observations remain NULL; not mentions during a publication date range.
- `release_reported_reaction_count`: Sum of current reaction counters reported for selected releases. Missing observations remain NULL; not reaction creation events during a publication date range.

### `release_assets`

Canonical GitHub release assets, distinct from Actions artifacts. Lists traverse every asset page for each selected release. Direct asset lookup preserves the same asset identity and metadata but leaves release_id unknown because that API response omits its parent. Publisher and uploader are separate actor roles. Parent release identity remains available in detail and release-to-assets retrieval remains declared. Analytical enrichment through the parent release, including its publisher, is not approved; assets retain their direct repository and uploader relationships, including known repository context when release_id is unknown. The nullable uploader snapshot is retained as a typed account record without an additional account lookup.

Grain: `repository_id`, `release_asset_id`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `release_assets__lookup` | `release_asset_id` | One release asset metadata record by stable asset ID. Its release_id remains NULL because this response does not identify its parent release. |
| `release_assets__releases` | `release_id` | One identified release visible to current credentials. Every selected release is followed through its independently paginated asset list; embedded release.assets is not treated as complete. |
| `release_assets__tags` | `release_tag` | The release associated with an exact tag visible to current credentials. Every selected release is followed through its independently paginated asset list; embedded release.assets is not treated as complete. |
| `release_assets__latest` | `release_selection` | GitHub latest-release endpoint: the latest published non-prerelease release, using GitHub's selection semantics; never inferred from the first list row. Every selected release is followed through its independently paginated asset list; embedded release.assets is not treated as complete. |
| `release_assets__repositories` | `owner`, `repository`, `organization`, `repositories` | All releases visible to current credentials in the repository population, including visible drafts and prereleases; all pages are consumed. Every selected release is followed through its independently paginated asset list; embedded release.assets is not treated as complete. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `repository_id` | `BIGINT` | no |
| `repository` | `VARCHAR` | no |
| `release_id` | `BIGINT` | yes |
| `release_asset_id` | `BIGINT` | no |
| `release_asset_node_id` | `VARCHAR` | no |
| `name` | `VARCHAR` | no |
| `label` | `VARCHAR` | yes |
| `state` | `VARCHAR` | no |
| `content_type` | `VARCHAR` | no |
| `digest` | `VARCHAR` | yes |
| `download_count` | `BIGINT` | no |
| `created_at` | `TIMESTAMP WITH TIME ZONE` | no |
| `updated_at` | `TIMESTAMP WITH TIME ZONE` | no |
| `url` | `VARCHAR` | no |
| `browser_download_url` | `VARCHAR` | no |
| `size_bytes` | `BIGINT` | no |
| `uploader_id` | `BIGINT` | yes |
| `uploader_login` | `VARCHAR` | yes |
| `uploader_type` | `VARCHAR` | yes |
| `uploader` | `STRUCT("avatar_url" VARCHAR, "email" VARCHAR, "events_url" VARCHAR, "followers_url" VARCHAR, "following_url" VARCHAR, "gists_url" VARCHAR, "gravatar_id" VARCHAR, "html_url" VARCHAR, "id" BIGINT, "login" VARCHAR, "name" VARCHAR, "node_id" VARCHAR, "organizations_url" VARCHAR, "received_events_url" VARCHAR, "repos_url" VARCHAR, "site_admin" BOOLEAN, "starred_at" VARCHAR, "starred_url" VARCHAR, "subscriptions_url" VARCHAR, "type" VARCHAR, "url" VARCHAR, "user_view_type" VARCHAR)` | yes |
| `release_asset_created_day` | `DATE` | no |

Approved metrics:

- `release_asset_count`: Current release asset metadata records at repository/asset identity; not Actions artifacts and not historical uploads.
- `uploaded_release_asset_count`: Current assets whose upload state is uploaded; open assets are retained in release_asset_count.
- `median_release_asset_size_bytes`: Exact median current byte size across selected assets, including zero-byte open uploads.
- `release_asset_size_bytes`: Sum of current byte sizes over distinct selected assets; not cumulative transfer volume.
- `release_asset_download_count`: Sum of lifetime download counters observed now for distinct selected assets; not downloads during the query date range.

### `workflows`

Visible workflow definitions, including inactive workflows returned by GitHub; one row per stable workflow ID.

Grain: `workflow_id`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `workflows__lookup` | `workflow_id` | Visible records in the selected repository scope; pagination is exhausted, but deleted or inaccessible records are not a historical archive. |
| `workflows__repositories` | `owner`, `repository`, `organization`, `repositories` | Visible records in the selected repository scope; pagination is exhausted, but deleted or inaccessible records are not a historical archive. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `repository_id` | `BIGINT` | no |
| `repository` | `VARCHAR` | no |
| `workflow_id` | `BIGINT` | no |
| `workflow_node_id` | `VARCHAR` | no |
| `name` | `VARCHAR` | no |
| `path` | `VARCHAR` | no |
| `state` | `VARCHAR` | no |
| `created_at` | `TIMESTAMP WITH TIME ZONE` | no |
| `updated_at` | `TIMESTAMP WITH TIME ZONE` | no |
| `deleted_at` | `TIMESTAMP WITH TIME ZONE` | yes |
| `html_url` | `VARCHAR` | no |
| `badge_url` | `VARCHAR` | no |
| `url` | `VARCHAR` | no |

Approved metrics:

- `workflow_count`: Visible workflow definitions, including inactive workflows returned by GitHub; one row per stable workflow ID.

### `workflow_runs`

Visible workflow run identities. Reruns update the same run; status, conclusion and run_started_at describe the latest attempt. Actor and triggering actor are distinct roles, not commit authors. Typed referenced workflows retain their own path/ref/SHA; matching_pull_requests are open PRs sharing the head and do not establish trigger causality. Git commit author/committer remain separate from actor and triggering_actor. Repository snapshots describe base/head contexts; API action URLs are metadata and are never followed as commands.

Grain: `run_id`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `workflow_runs__lookup` | `run_id` | Visible records in the selected repository scope; pagination is exhausted, but deleted or inaccessible records are not a historical archive. |
| `workflow_runs__workflows` | `workflow_id` | Visible records in the selected repository scope; pagination is exhausted, but deleted or inaccessible records are not a historical archive. |
| `workflow_runs__repositories` | `owner`, `repository`, `organization`, `repositories` | Visible records in the selected repository scope; pagination is exhausted, but deleted or inaccessible records are not a historical archive. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `repository_id` | `BIGINT` | no |
| `repository` | `VARCHAR` | no |
| `run_id` | `BIGINT` | no |
| `run_node_id` | `VARCHAR` | no |
| `workflow_id` | `BIGINT` | no |
| `run_number` | `BIGINT` | no |
| `run_attempt` | `BIGINT` | yes |
| `name` | `VARCHAR` | yes |
| `display_title` | `VARCHAR` | no |
| `event` | `VARCHAR` | no |
| `status` | `VARCHAR` | yes |
| `conclusion` | `VARCHAR` | yes |
| `head_sha` | `VARCHAR` | no |
| `head_branch` | `VARCHAR` | yes |
| `path` | `VARCHAR` | no |
| `created_at` | `TIMESTAMP WITH TIME ZONE` | no |
| `updated_at` | `TIMESTAMP WITH TIME ZONE` | no |
| `run_started_at` | `TIMESTAMP WITH TIME ZONE` | yes |
| `actor_id` | `BIGINT` | yes |
| `actor_login` | `VARCHAR` | yes |
| `triggering_actor_id` | `BIGINT` | yes |
| `triggering_actor_login` | `VARCHAR` | yes |
| `check_suite_id` | `BIGINT` | yes |
| `html_url` | `VARCHAR` | no |
| `check_suite_node_id` | `VARCHAR` | yes |
| `referenced_workflows` | `STRUCT("path" VARCHAR, "ref" VARCHAR, "sha" VARCHAR)[]` | yes |
| `matching_pull_requests` | `STRUCT("base" STRUCT("ref" VARCHAR, "repo" STRUCT("id" BIGINT, "name" VARCHAR, "url" VARCHAR), "sha" VARCHAR), "head" STRUCT("ref" VARCHAR, "repo" STRUCT("id" BIGINT, "name" VARCHAR, "url" VARCHAR), "sha" VARCHAR), "id" BIGINT, "number" BIGINT, "url" VARCHAR)[]` | yes |
| `head_commit` | `STRUCT("author" STRUCT("email" VARCHAR, "name" VARCHAR), "committer" STRUCT("email" VARCHAR, "name" VARCHAR), "id" VARCHAR, "message" VARCHAR, "timestamp" TIMESTAMP WITH TIME ZONE, "tree_id" VARCHAR)` | yes |
| `actor` | `STRUCT("avatar_url" VARCHAR, "email" VARCHAR, "events_url" VARCHAR, "followers_url" VARCHAR, "following_url" VARCHAR, "gists_url" VARCHAR, "gravatar_id" VARCHAR, "html_url" VARCHAR, "id" BIGINT, "login" VARCHAR, "name" VARCHAR, "node_id" VARCHAR, "organizations_url" VARCHAR, "received_events_url" VARCHAR, "repos_url" VARCHAR, "site_admin" BOOLEAN, "starred_at" VARCHAR, "starred_url" VARCHAR, "subscriptions_url" VARCHAR, "type" VARCHAR, "url" VARCHAR, "user_view_type" VARCHAR)` | yes |
| `triggering_actor` | `STRUCT("avatar_url" VARCHAR, "email" VARCHAR, "events_url" VARCHAR, "followers_url" VARCHAR, "following_url" VARCHAR, "gists_url" VARCHAR, "gravatar_id" VARCHAR, "html_url" VARCHAR, "id" BIGINT, "login" VARCHAR, "name" VARCHAR, "node_id" VARCHAR, "organizations_url" VARCHAR, "received_events_url" VARCHAR, "repos_url" VARCHAR, "site_admin" BOOLEAN, "starred_at" VARCHAR, "starred_url" VARCHAR, "subscriptions_url" VARCHAR, "type" VARCHAR, "url" VARCHAR, "user_view_type" VARCHAR)` | yes |
| `repository_snapshot` | `STRUCT("id" BIGINT, "node_id" VARCHAR, "name" VARCHAR, "full_name" VARCHAR, "owner" STRUCT("id" BIGINT, "login" VARCHAR, "type" VARCHAR), "private" BOOLEAN, "html_url" VARCHAR, "description" VARCHAR, "fork" BOOLEAN, "default_branch" VARCHAR)` | no |
| `head_repository_snapshot` | `STRUCT("id" BIGINT, "node_id" VARCHAR, "name" VARCHAR, "full_name" VARCHAR, "owner" STRUCT("id" BIGINT, "login" VARCHAR, "type" VARCHAR), "private" BOOLEAN, "html_url" VARCHAR, "description" VARCHAR, "fork" BOOLEAN, "default_branch" VARCHAR)` | no |
| `head_repository_id` | `BIGINT` | no |
| `head_repository` | `VARCHAR` | no |
| `reported_head_repository_id` | `BIGINT` | yes |
| `url` | `VARCHAR` | no |
| `jobs_url` | `VARCHAR` | no |
| `logs_url` | `VARCHAR` | no |
| `check_suite_url` | `VARCHAR` | no |
| `artifacts_url` | `VARCHAR` | no |
| `cancel_url` | `VARCHAR` | no |
| `rerun_url` | `VARCHAR` | no |
| `previous_attempt_url` | `VARCHAR` | yes |
| `workflow_url` | `VARCHAR` | no |
| `created_day` | `DATE` | no |

Approved metrics:

- `workflow_run_count`: Visible workflow run identities. Reruns update the same run; status, conclusion and run_started_at describe the latest attempt. Actor and triggering actor are distinct roles, not commit authors.
- `workflow_run_success_count`: Visible workflow run identities. Reruns update the same run; status, conclusion and run_started_at describe the latest attempt. Actor and triggering actor are distinct roles, not commit authors. Counts records whose conclusion equals success; pending or unknown outcomes are excluded.
- `workflow_run_failure_count`: Visible workflow run identities. Reruns update the same run; status, conclusion and run_started_at describe the latest attempt. Actor and triggering actor are distinct roles, not commit authors. Counts records whose conclusion equals failure; pending or unknown outcomes are excluded.
- `workflow_run_cancelled_count`: Visible workflow run identities. Reruns update the same run; status, conclusion and run_started_at describe the latest attempt. Actor and triggering actor are distinct roles, not commit authors. Counts records whose conclusion equals cancelled; pending or unknown outcomes are excluded.

### `workflow_run_attempts`

Only explicitly selected workflow run attempts, keyed by run ID and attempt number; no exhaustive attempt-history claim. Typed referenced workflows retain their own path/ref/SHA; matching_pull_requests are open PRs sharing the head and do not establish trigger causality. Git commit author/committer remain separate from actor and triggering_actor. Repository snapshots describe base/head contexts; API action URLs are metadata and are never followed as commands.

Grain: `run_id`, `attempt_number`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `workflow_run_attempts__lookup` | `attempt_number` | One explicitly requested attempt. This route does not enumerate all historical attempts; omitted attempts are not zero observations. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `repository_id` | `BIGINT` | no |
| `repository` | `VARCHAR` | no |
| `run_id` | `BIGINT` | no |
| `run_node_id` | `VARCHAR` | no |
| `workflow_id` | `BIGINT` | no |
| `run_number` | `BIGINT` | no |
| `run_attempt` | `BIGINT` | yes |
| `name` | `VARCHAR` | yes |
| `display_title` | `VARCHAR` | no |
| `event` | `VARCHAR` | no |
| `status` | `VARCHAR` | yes |
| `conclusion` | `VARCHAR` | yes |
| `head_sha` | `VARCHAR` | no |
| `head_branch` | `VARCHAR` | yes |
| `path` | `VARCHAR` | no |
| `created_at` | `TIMESTAMP WITH TIME ZONE` | no |
| `updated_at` | `TIMESTAMP WITH TIME ZONE` | no |
| `run_started_at` | `TIMESTAMP WITH TIME ZONE` | yes |
| `actor_id` | `BIGINT` | yes |
| `actor_login` | `VARCHAR` | yes |
| `triggering_actor_id` | `BIGINT` | yes |
| `triggering_actor_login` | `VARCHAR` | yes |
| `check_suite_id` | `BIGINT` | yes |
| `html_url` | `VARCHAR` | no |
| `attempt_number` | `BIGINT` | no |
| `check_suite_node_id` | `VARCHAR` | yes |
| `referenced_workflows` | `STRUCT("path" VARCHAR, "ref" VARCHAR, "sha" VARCHAR)[]` | yes |
| `matching_pull_requests` | `STRUCT("base" STRUCT("ref" VARCHAR, "repo" STRUCT("id" BIGINT, "name" VARCHAR, "url" VARCHAR), "sha" VARCHAR), "head" STRUCT("ref" VARCHAR, "repo" STRUCT("id" BIGINT, "name" VARCHAR, "url" VARCHAR), "sha" VARCHAR), "id" BIGINT, "number" BIGINT, "url" VARCHAR)[]` | yes |
| `head_commit` | `STRUCT("author" STRUCT("email" VARCHAR, "name" VARCHAR), "committer" STRUCT("email" VARCHAR, "name" VARCHAR), "id" VARCHAR, "message" VARCHAR, "timestamp" TIMESTAMP WITH TIME ZONE, "tree_id" VARCHAR)` | yes |
| `actor` | `STRUCT("avatar_url" VARCHAR, "email" VARCHAR, "events_url" VARCHAR, "followers_url" VARCHAR, "following_url" VARCHAR, "gists_url" VARCHAR, "gravatar_id" VARCHAR, "html_url" VARCHAR, "id" BIGINT, "login" VARCHAR, "name" VARCHAR, "node_id" VARCHAR, "organizations_url" VARCHAR, "received_events_url" VARCHAR, "repos_url" VARCHAR, "site_admin" BOOLEAN, "starred_at" VARCHAR, "starred_url" VARCHAR, "subscriptions_url" VARCHAR, "type" VARCHAR, "url" VARCHAR, "user_view_type" VARCHAR)` | yes |
| `triggering_actor` | `STRUCT("avatar_url" VARCHAR, "email" VARCHAR, "events_url" VARCHAR, "followers_url" VARCHAR, "following_url" VARCHAR, "gists_url" VARCHAR, "gravatar_id" VARCHAR, "html_url" VARCHAR, "id" BIGINT, "login" VARCHAR, "name" VARCHAR, "node_id" VARCHAR, "organizations_url" VARCHAR, "received_events_url" VARCHAR, "repos_url" VARCHAR, "site_admin" BOOLEAN, "starred_at" VARCHAR, "starred_url" VARCHAR, "subscriptions_url" VARCHAR, "type" VARCHAR, "url" VARCHAR, "user_view_type" VARCHAR)` | yes |
| `repository_snapshot` | `STRUCT("id" BIGINT, "node_id" VARCHAR, "name" VARCHAR, "full_name" VARCHAR, "owner" STRUCT("id" BIGINT, "login" VARCHAR, "type" VARCHAR), "private" BOOLEAN, "html_url" VARCHAR, "description" VARCHAR, "fork" BOOLEAN, "default_branch" VARCHAR)` | no |
| `head_repository_snapshot` | `STRUCT("id" BIGINT, "node_id" VARCHAR, "name" VARCHAR, "full_name" VARCHAR, "owner" STRUCT("id" BIGINT, "login" VARCHAR, "type" VARCHAR), "private" BOOLEAN, "html_url" VARCHAR, "description" VARCHAR, "fork" BOOLEAN, "default_branch" VARCHAR)` | no |
| `head_repository_id` | `BIGINT` | no |
| `head_repository` | `VARCHAR` | no |
| `reported_head_repository_id` | `BIGINT` | yes |
| `url` | `VARCHAR` | no |
| `jobs_url` | `VARCHAR` | no |
| `logs_url` | `VARCHAR` | no |
| `check_suite_url` | `VARCHAR` | no |
| `artifacts_url` | `VARCHAR` | no |
| `cancel_url` | `VARCHAR` | no |
| `rerun_url` | `VARCHAR` | no |
| `previous_attempt_url` | `VARCHAR` | yes |
| `workflow_url` | `VARCHAR` | no |

Approved metrics:

- `workflow_run_attempt_count`: Only explicitly selected workflow run attempts, keyed by run ID and attempt number; no exhaustive attempt-history claim.
- `workflow_run_attempt_success_count`: Only explicitly selected workflow run attempts, keyed by run ID and attempt number; no exhaustive attempt-history claim. Counts records whose conclusion equals success; pending or unknown outcomes are excluded.
- `workflow_run_attempt_failure_count`: Only explicitly selected workflow run attempts, keyed by run ID and attempt number; no exhaustive attempt-history claim. Counts records whose conclusion equals failure; pending or unknown outcomes are excluded.
- `workflow_run_attempt_cancelled_count`: Only explicitly selected workflow run attempts, keyed by run ID and attempt number; no exhaustive attempt-history claim. Counts records whose conclusion equals cancelled; pending or unknown outcomes are excluded.

### `workflow_jobs`

Visible job executions at stable job-ID grain. Rerun jobs count separately; no default latest-attempt filter. Steps and runner labels are embedded lists, not job multipliers. Analytical parent enrichment follows job to run to workflow. Attempt identity remains an explicit job field and exact-attempt retrieval route; it does not implicitly join the exact-selector-only attempt dataset.

Grain: `job_id`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `workflow_jobs__lookup` | `job_id` | Visible records in the selected repository scope; pagination is exhausted, but deleted or inaccessible records are not a historical archive. |
| `workflow_jobs__attempts` | `attempt_number` | All visible jobs in the one requested run attempt. |
| `workflow_jobs__runs` | `run_id` | All visible jobs from all attempts of the selected run, using filter=all, including jobs from failed and superseded attempts. |
| `workflow_jobs__workflows` | `workflow_id` | All visible jobs across every returned run and all of its attempts for the selected workflow. |
| `workflow_jobs__repositories` | `owner`, `repository`, `organization`, `repositories` | All visible jobs across every returned run and all of its attempts in the repository selection. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `repository_id` | `BIGINT` | no |
| `repository` | `VARCHAR` | no |
| `job_id` | `BIGINT` | no |
| `job_node_id` | `VARCHAR` | no |
| `run_id` | `BIGINT` | no |
| `run_attempt` | `BIGINT` | yes |
| `name` | `VARCHAR` | no |
| `workflow_name` | `VARCHAR` | yes |
| `head_sha` | `VARCHAR` | no |
| `head_branch` | `VARCHAR` | yes |
| `status` | `VARCHAR` | no |
| `conclusion` | `VARCHAR` | yes |
| `created_at` | `TIMESTAMP WITH TIME ZONE` | no |
| `started_at` | `TIMESTAMP WITH TIME ZONE` | no |
| `completed_at` | `TIMESTAMP WITH TIME ZONE` | yes |
| `runner_id` | `BIGINT` | yes |
| `runner_name` | `VARCHAR` | yes |
| `runner_group_id` | `BIGINT` | yes |
| `runner_group_name` | `VARCHAR` | yes |
| `runner_labels` | `VARCHAR[]` | no |
| `steps` | `STRUCT("number" BIGINT, "name" VARCHAR, "status" VARCHAR, "conclusion" VARCHAR, "started_at" TIMESTAMP WITH TIME ZONE, "completed_at" TIMESTAMP WITH TIME ZONE)[]` | yes |
| `html_url` | `VARCHAR` | yes |
| `check_run_url` | `VARCHAR` | no |
| `url` | `VARCHAR` | no |
| `run_url` | `VARCHAR` | no |
| `execution_hours` | `DOUBLE` | yes |
| `created_day` | `DATE` | no |

Approved metrics:

- `workflow_job_count`: Visible job executions at stable job-ID grain. Rerun jobs count separately; no default latest-attempt filter. Steps and runner labels are embedded lists, not job multipliers.
- `workflow_job_success_count`: Visible job executions at stable job-ID grain. Rerun jobs count separately; no default latest-attempt filter. Steps and runner labels are embedded lists, not job multipliers. Counts records whose conclusion equals success; pending or unknown outcomes are excluded.
- `workflow_job_failure_count`: Visible job executions at stable job-ID grain. Rerun jobs count separately; no default latest-attempt filter. Steps and runner labels are embedded lists, not job multipliers. Counts records whose conclusion equals failure; pending or unknown outcomes are excluded.
- `workflow_job_cancelled_count`: Visible job executions at stable job-ID grain. Rerun jobs count separately; no default latest-attempt filter. Steps and runner labels are embedded lists, not job multipliers. Counts records whose conclusion equals cancelled; pending or unknown outcomes are excluded.
- `median_workflow_job_execution_hours`: Median elapsed job execution hours for completed, timestamped jobs; each job contributes once, including prior attempts.

### `workflow_artifacts`

Visible Actions artifact metadata, distinct from release assets. Expired artifacts remain if returned; deleted artifacts are absent. Artifact names are not identities and run linkage may be NULL. Repository selection includes artifacts without discoverable runs; workflow and run selections follow their listing endpoints. No attempt-specific artifact population is claimed. Analytical enrichment follows the known repository directly, preserving artifacts with no discoverable run. Run identity and bidirectional run retrieval remain explicit, but artifact aggregation by attributes from the run or workflow entities is not approved because it would introduce a competing analytical path and can lose orphan artifacts. Nullable workflow_run metadata includes its actual repository/head-repository IDs, without assigning a missing run or fork to the requested repository by assumption.

Grain: `artifact_id`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `workflow_artifacts__lookup` | `artifact_id` | Visible records in the selected repository scope; pagination is exhausted, but deleted or inaccessible records are not a historical archive. |
| `workflow_artifacts__runs` | `run_id` | Artifacts returned by the selected run endpoint, including expired artifacts still returned. Unknown run metadata remains NULL; no attempt filter is applied because GitHub does not expose attempt-specific artifact listing. |
| `workflow_artifacts__workflows` | `workflow_id` | Artifacts returned for all visible runs of the selected workflow, including expired artifacts still returned. Artifact metadata with unknown run identity stays NULL; run/workflow selection follows endpoint association and cannot include repository artifacts with no discoverable run. |
| `workflow_artifacts__repositories` | `owner`, `repository`, `organization`, `repositories` | All visible repository artifact identities, including expired artifacts still returned and metadata with missing or unknown run links. Artifact names are not identities. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `repository_id` | `BIGINT` | no |
| `repository` | `VARCHAR` | no |
| `artifact_id` | `BIGINT` | no |
| `artifact_node_id` | `VARCHAR` | no |
| `name` | `VARCHAR` | no |
| `size_in_bytes` | `BIGINT` | no |
| `expired` | `BOOLEAN` | no |
| `created_at` | `TIMESTAMP WITH TIME ZONE` | yes |
| `updated_at` | `TIMESTAMP WITH TIME ZONE` | yes |
| `expires_at` | `TIMESTAMP WITH TIME ZONE` | yes |
| `digest` | `VARCHAR` | yes |
| `run_id` | `BIGINT` | yes |
| `head_sha` | `VARCHAR` | yes |
| `head_branch` | `VARCHAR` | yes |
| `archive_download_url` | `VARCHAR` | no |
| `url` | `VARCHAR` | no |
| `workflow_run` | `STRUCT("head_branch" VARCHAR, "head_repository_id" BIGINT, "head_sha" VARCHAR, "id" BIGINT, "repository_id" BIGINT)` | yes |
| `run_repository_id` | `BIGINT` | yes |
| `head_repository_id` | `BIGINT` | yes |

Approved metrics:

- `workflow_artifact_count`: Visible Actions artifact metadata, distinct from release assets. Expired artifacts remain if returned; deleted artifacts are absent. Artifact names are not identities and run linkage may be NULL. Repository selection includes artifacts without discoverable runs; workflow and run selections follow their listing endpoints. No attempt-specific artifact population is claimed. Analytical enrichment follows the known repository directly, preserving artifacts with no discoverable run. Run identity and bidirectional run retrieval remain explicit, but artifact aggregation by attributes from the run or workflow entities is not approved because it would introduce a competing analytical path and can lose orphan artifacts.
- `workflow_artifact_bytes`: Sum of reported bytes for selected visible artifacts, including expired artifacts if returned; not retained storage usage or billing.

### `check_suites`

GitHub check suites with repository and commit identity, nullable producer metadata and explicit ref or ID retrieval. latest_check_runs_count is GitHub latest-run metadata and does not count all reruns. The explicit node-ID route adds typed GraphQL-only context; ordinary routes leave that context NULL as unrequested. Numeric IDs and repository membership are verified before REST hydration.

Grain: `repository_id`, `check_suite_id`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `check_suites__nodes` | `check_suite_node_id` | One explicitly selected GraphQL node in the matching canonical repository, followed by its REST detail lookup. GraphQL-only fields are populated on this route; NULL on ordinary REST routes means not retrieved, not confirmed absence. Nested reviewer/user/status connections are not silently truncated into this record. |
| `check_suites__lookup` | `check_suite_id` | One visible suite by repository and numeric suite ID. |
| `check_suites__references` | `git_ref` | All visible check suites for the selected commit SHA, branch or tag, following every Link page. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `repository_id` | `BIGINT` | no |
| `repository` | `VARCHAR` | no |
| `check_suite_id` | `BIGINT` | no |
| `check_suite_node_id` | `VARCHAR` | no |
| `head_branch` | `VARCHAR` | yes |
| `head_sha` | `VARCHAR` | no |
| `status` | `VARCHAR` | yes |
| `conclusion` | `VARCHAR` | yes |
| `url` | `VARCHAR` | yes |
| `before` | `VARCHAR` | yes |
| `after` | `VARCHAR` | yes |
| `created_at` | `TIMESTAMP WITH TIME ZONE` | yes |
| `updated_at` | `TIMESTAMP WITH TIME ZONE` | yes |
| `latest_check_runs_count` | `BIGINT` | no |
| `check_runs_url` | `VARCHAR` | no |
| `rerequestable` | `BOOLEAN` | yes |
| `runs_rerequestable` | `BOOLEAN` | yes |
| `app_id` | `BIGINT` | yes |
| `app_slug` | `VARCHAR` | yes |
| `pull_requests` | `STRUCT("id" BIGINT, "number" BIGINT)[]` | yes |
| `creator_id` | `BIGINT` | yes |
| `creator_login` | `VARCHAR` | yes |
| `creator` | `STRUCT("id" VARCHAR, "databaseId" BIGINT, "login" VARCHAR, "url" VARCHAR)` | yes |
| `branch` | `STRUCT("id" VARCHAR, "name" VARCHAR, "prefix" VARCHAR)` | yes |
| `push` | `STRUCT("id" VARCHAR, "previousSha" VARCHAR, "nextSha" VARCHAR, "permalink" VARCHAR)` | yes |
| `pusher_login` | `VARCHAR` | yes |
| `pusher_type` | `VARCHAR` | yes |
| `workflow_run_id` | `BIGINT` | yes |
| `workflow_run` | `STRUCT("id" VARCHAR, "databaseId" BIGINT, "runNumber" BIGINT, "event" VARCHAR, "url" VARCHAR, "file" STRUCT("id" VARCHAR, "path" VARCHAR, "repositoryName" VARCHAR, "repositoryFileUrl" VARCHAR, "resourcePath" VARCHAR, "url" VARCHAR, "viewerCanPushRepository" BOOLEAN, "viewerCanReadRepository" BOOLEAN))` | yes |
| `graph_url` | `VARCHAR` | yes |
| `resource_path` | `VARCHAR` | yes |

Approved metrics:

- `check_suite_count`: Visible check suites at the selected reference or suite ID; not Actions workflow runs.

### `check_runs`

GitHub check runs are distinct from Actions jobs and workflow attempts. All reruns remain separate identities; runs with missing suites or apps remain visible. The explicit node-ID route adds typed GraphQL-only context; ordinary routes leave that context NULL as unrequested. Numeric IDs and repository membership are verified before REST hydration. Deployment ID and typed deployment metadata are available from ordinary REST responses; the node route adds deployment_context with GraphQL current state/commit context and pending approvals.

Grain: `repository_id`, `check_run_id`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `check_runs__nodes` | `check_run_node_id` | One explicitly selected GraphQL node in the matching canonical repository, followed by its REST detail lookup. GraphQL-only fields are populated on this route; NULL on ordinary REST routes means not retrieved, not confirmed absence. Nested reviewer/user/status connections are not silently truncated into this record. |
| `check_runs__lookup` | `check_run_id` | One visible run by repository and numeric run ID; the nullable suite association does not discard orphaned runs. |
| `check_runs__suites` | `check_suite_id` | All visible runs in the selected suite, including earlier same-name runs, with filter=all. |
| `check_runs__references` | `git_ref` | All visible runs at the selected ref, following all suite pages and all run pages per suite with filter=all. This avoids the direct reference run endpoint's 1000-suite cap. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `repository_id` | `BIGINT` | no |
| `repository` | `VARCHAR` | no |
| `check_run_id` | `BIGINT` | no |
| `check_run_node_id` | `VARCHAR` | no |
| `name` | `VARCHAR` | no |
| `head_sha` | `VARCHAR` | no |
| `external_id` | `VARCHAR` | yes |
| `url` | `VARCHAR` | no |
| `html_url` | `VARCHAR` | yes |
| `details_url` | `VARCHAR` | yes |
| `status` | `VARCHAR` | no |
| `conclusion` | `VARCHAR` | yes |
| `started_at` | `TIMESTAMP WITH TIME ZONE` | yes |
| `completed_at` | `TIMESTAMP WITH TIME ZONE` | yes |
| `check_suite_id` | `BIGINT` | yes |
| `app_id` | `BIGINT` | yes |
| `app_slug` | `VARCHAR` | yes |
| `output_title` | `VARCHAR` | yes |
| `output_summary` | `VARCHAR` | yes |
| `output_text` | `VARCHAR` | yes |
| `annotations_count` | `BIGINT` | no |
| `annotations_url` | `VARCHAR` | no |
| `pull_requests` | `STRUCT("id" BIGINT, "number" BIGINT)[]` | no |
| `deployment_context` | `STRUCT("id" VARCHAR, "databaseId" BIGINT, "commitOid" VARCHAR, "createdAt" TIMESTAMP WITH TIME ZONE, "updatedAt" TIMESTAMP WITH TIME ZONE, "description" VARCHAR, "environment" VARCHAR, "latestEnvironment" VARCHAR, "originalEnvironment" VARCHAR, "state" VARCHAR, "task" VARCHAR)` | yes |
| `pending_deployment_request` | `STRUCT("currentUserCanApprove" BOOLEAN, "waitTimer" BIGINT, "waitTimerStartedAt" TIMESTAMP WITH TIME ZONE, "environment" STRUCT("id" VARCHAR, "databaseId" BIGINT, "name" VARCHAR, "isPinned" BOOLEAN, "pinnedPosition" BIGINT))` | yes |
| `permalink` | `VARCHAR` | yes |
| `resource_path` | `VARCHAR` | yes |
| `deployment_id` | `BIGINT` | yes |
| `deployment` | `STRUCT("url" VARCHAR, "id" BIGINT, "node_id" VARCHAR, "task" VARCHAR, "original_environment" VARCHAR, "environment" VARCHAR, "description" VARCHAR, "created_at" TIMESTAMP WITH TIME ZONE, "updated_at" TIMESTAMP WITH TIME ZONE, "statuses_url" VARCHAR, "repository_url" VARCHAR, "transient_environment" BOOLEAN, "production_environment" BOOLEAN, "performed_via_github_app" STRUCT("id" BIGINT, "slug" VARCHAR, "node_id" VARCHAR, "name" VARCHAR, "description" VARCHAR, "external_url" VARCHAR, "html_url" VARCHAR, "created_at" TIMESTAMP WITH TIME ZONE, "updated_at" TIMESTAMP WITH TIME ZONE, "events" VARCHAR[], "installations_count" BIGINT))` | yes |

Approved metrics:

- `check_run_count`: Visible check run identities including all reruns returned with filter=all.
- `successful_check_run_count`: Runs whose current conclusion is success.
- `failed_check_run_count`: Runs whose current conclusion is failure; excludes cancellation, timeout and unfinished runs.
- `unfinished_check_run_count`: Runs with no conclusion, including queued and in-progress runs.

### `check_annotations`

Check-run annotations have no API object ID. Grain uses repository, run and one-based response position across all pages of that run scan. Positions are snapshot-local and must not be used for historical annotation identity or cross-snapshot deduplication.

Grain: `repository_id`, `check_run_id`, `annotation_position`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `check_annotations__runs` | `check_run_id` | All annotation rows for the selected runs, retaining identical repeated annotations. Positions restart per run and span Link pages; they identify this retrieval snapshot only. One visible run by repository and numeric run ID; the nullable suite association does not discard orphaned runs. |
| `check_annotations__suites` | `check_suite_id` | All annotation rows for the selected runs, retaining identical repeated annotations. Positions restart per run and span Link pages; they identify this retrieval snapshot only. All visible runs in the selected suite, including earlier same-name runs, with filter=all. |
| `check_annotations__references` | `git_ref` | All visible runs at the selected ref, following all suite pages and all run pages per suite with filter=all. This avoids the direct reference run endpoint's 1000-suite cap. All annotation rows are retained; snapshot positions restart per run and span every annotation page. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `repository_id` | `BIGINT` | no |
| `repository` | `VARCHAR` | no |
| `check_run_id` | `BIGINT` | no |
| `check_suite_id` | `BIGINT` | yes |
| `head_sha` | `VARCHAR` | no |
| `annotation_position` | `BIGINT` | no |
| `path` | `VARCHAR` | no |
| `start_line` | `BIGINT` | no |
| `end_line` | `BIGINT` | no |
| `start_column` | `BIGINT` | yes |
| `end_column` | `BIGINT` | yes |
| `annotation_level` | `VARCHAR` | yes |
| `title` | `VARCHAR` | yes |
| `message` | `VARCHAR` | yes |
| `raw_details` | `VARCHAR` | yes |
| `blob_href` | `VARCHAR` | no |

Approved metrics:

- `check_annotation_count`: Annotation response rows, retaining duplicate content; snapshot positions are not durable annotation IDs.
- `failure_annotation_count`: Annotation rows whose level is failure.

### `check_steps`

Canonical check-run steps at repository/run/step-number grain. All run/suite/reference paths preserve reruns and independently paginate each run connection. These records belong to GraphQL CheckRun; no identity equivalence with an Actions job or its nested REST steps is invented. Step numbers are parent-local indices, with external ID and reported seconds-to-completion retained.

Grain: `repository_id`, `check_run_id`, `step_number`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `check_steps__runs` | `check_run_id` | Every available step of the selected check runs, following every GraphQL page. NULL discovered run or connection fails; an empty nodes array is a valid empty population. Suite/ref traversal retains earlier same-name runs with REST filter=all. |
| `check_steps__suites` | `check_suite_id` | Every available step of the selected check runs, following every GraphQL page. NULL discovered run or connection fails; an empty nodes array is a valid empty population. Suite/ref traversal retains earlier same-name runs with REST filter=all. |
| `check_steps__references` | `git_ref` | Every available step of the selected check runs, following every GraphQL page. NULL discovered run or connection fails; an empty nodes array is a valid empty population. Suite/ref traversal retains earlier same-name runs with REST filter=all. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `repository_id` | `BIGINT` | no |
| `repository` | `VARCHAR` | no |
| `check_run_id` | `BIGINT` | no |
| `check_suite_id` | `BIGINT` | yes |
| `head_sha` | `VARCHAR` | no |
| `step_number` | `BIGINT` | no |
| `name` | `VARCHAR` | no |
| `status` | `VARCHAR` | no |
| `conclusion` | `VARCHAR` | yes |
| `external_id` | `VARCHAR` | yes |
| `seconds_to_completion` | `BIGINT` | yes |
| `started_at` | `TIMESTAMP WITH TIME ZONE` | yes |
| `completed_at` | `TIMESTAMP WITH TIME ZONE` | yes |

Approved metrics:

- `check_step_count`: Steps at the selected repository/run/number grain.
- `failed_check_step_count`: Selected steps explicitly concluded FAILURE.
- `check_step_reported_seconds`: Sum of upstream seconds-to-completion where reported; NULL timing remains unavailable and is not inferred from timestamps. Empty selected populations yield zero; an observed population with no reported values yields NULL. Mixed populations sum only reported values.

### `deployments`

Deployment requests at stable repository/deployment identity, independent of status-event multiplicity. Environment names are labels in deployment records and may refer to renamed or deleted environments; no environment-ID relationship is invented. Actor is deployment_creator, distinct from status creators. Arbitrary deployment payload values are not currently typed.

Grain: `repository_id`, `deployment_id`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `deployments__lookup` | `deployment_id` | Visible deployment records, preserving production, transient and environment labels; environment selection uses GitHub's deployment filter without requiring that an environment resource still exists. |
| `deployments__environments` | `environment_name` | Visible deployment records, preserving production, transient and environment labels; environment selection uses GitHub's deployment filter without requiring that an environment resource still exists. |
| `deployments__repositories` | `owner`, `repository`, `organization`, `repositories` | Visible deployment records, preserving production, transient and environment labels; environment selection uses GitHub's deployment filter without requiring that an environment resource still exists. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `repository_id` | `BIGINT` | no |
| `repository` | `VARCHAR` | no |
| `deployment_id` | `BIGINT` | no |
| `deployment_node_id` | `VARCHAR` | no |
| `commit_sha` | `VARCHAR` | no |
| `git_ref` | `VARCHAR` | no |
| `task` | `VARCHAR` | no |
| `environment_name` | `VARCHAR` | no |
| `original_environment` | `VARCHAR` | yes |
| `description` | `VARCHAR` | yes |
| `created_at` | `TIMESTAMP WITH TIME ZONE` | no |
| `updated_at` | `TIMESTAMP WITH TIME ZONE` | no |
| `url` | `VARCHAR` | no |
| `statuses_url` | `VARCHAR` | no |
| `transient_environment` | `BOOLEAN` | yes |
| `production_environment` | `BOOLEAN` | yes |
| `deployment_creator_id` | `BIGINT` | yes |
| `deployment_creator_login` | `VARCHAR` | yes |
| `deployment_creator_type` | `VARCHAR` | yes |
| `deployment_created_day` | `DATE` | no |

Approved metrics:

- `deployment_count`: Selected deployment request records, not successful deployments and not status updates.
- `production_deployment_count`: Deployment records explicitly marked production; missing classification is not false.
- `transient_deployment_count`: Deployment records explicitly marked transient.

### `deployment_statuses`

All visible deployment status event records, including historical failures followed by success and states queued, pending, in_progress and inactive. This entity is not one latest state per deployment. Direct repository context is analytical; deployment parent navigation is retained without a competing analytical path or conflating deployment/status creator roles.

Grain: `repository_id`, `deployment_id`, `deployment_status_id`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `deployment_statuses__lookup` | `deployment_status_id` | One status event identified within one deployment. |
| `deployment_statuses__deployments` | `deployment_id` | All visible status event records for selected deployments, including superseded and nonterminal states; all pages are followed. |
| `deployment_statuses__environments` | `environment_name` | All visible status event records for selected deployments, including superseded and nonterminal states; all pages are followed. |
| `deployment_statuses__repositories` | `owner`, `repository`, `organization`, `repositories` | All visible status event records for selected deployments, including superseded and nonterminal states; all pages are followed. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `repository_id` | `BIGINT` | no |
| `repository` | `VARCHAR` | no |
| `deployment_id` | `BIGINT` | no |
| `deployment_status_id` | `BIGINT` | no |
| `deployment_status_node_id` | `VARCHAR` | no |
| `state` | `VARCHAR` | no |
| `description` | `VARCHAR` | no |
| `environment_name` | `VARCHAR` | yes |
| `created_at` | `TIMESTAMP WITH TIME ZONE` | no |
| `updated_at` | `TIMESTAMP WITH TIME ZONE` | no |
| `target_url` | `VARCHAR` | no |
| `environment_url` | `VARCHAR` | yes |
| `log_url` | `VARCHAR` | yes |
| `url` | `VARCHAR` | no |
| `status_creator_id` | `BIGINT` | yes |
| `status_creator_login` | `VARCHAR` | yes |
| `status_creator_type` | `VARCHAR` | yes |
| `deployment_status_created_day` | `DATE` | no |

Approved metrics:

- `deployment_status_count`: Selected deployment status event records; multiple records can belong to one deployment.
- `successful_deployment_status_count`: Status events reporting success, not distinct successful deployments.
- `failed_deployment_status_count`: Status events reporting failure or error, including events superseded later.
- `pending_deployment_status_count`: Status events in a nonterminal pending, queued or in-progress state.

### `environments`

Current visible deployment environments at numeric identity, independent of deployment or policy populations. Branch-policy flags remain nullable when settings are absent or unrestricted; NULL must not be interpreted as a protected environment. Built-in wait-timer/reviewer rules remain typed nested metadata with all matching pinned anyOf variants; custom integration rules are a separate entity.

Grain: `repository_id`, `environment_id`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `environments__lookup` | `environment_name` | One current environment by its exact name; stable identity remains numeric. |
| `environments__repositories` | `owner`, `repository`, `organization`, `repositories` | All current visible environments, including environments without deployments or configured policy entries. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `repository_id` | `BIGINT` | no |
| `repository` | `VARCHAR` | no |
| `environment_id` | `BIGINT` | no |
| `environment_node_id` | `VARCHAR` | no |
| `environment_name` | `VARCHAR` | no |
| `created_at` | `TIMESTAMP WITH TIME ZONE` | no |
| `updated_at` | `TIMESTAMP WITH TIME ZONE` | no |
| `url` | `VARCHAR` | no |
| `html_url` | `VARCHAR` | no |
| `protected_branches` | `BOOLEAN` | yes |
| `custom_branch_policies` | `BOOLEAN` | yes |
| `protection_rules` | `STRUCT("matched_types" VARCHAR[], "variant_1" STRUCT("id" BIGINT, "node_id" VARCHAR, "type" VARCHAR, "wait_timer" BIGINT), "variant_2" STRUCT("id" BIGINT, "node_id" VARCHAR, "type" VARCHAR, "prevent_self_review" BOOLEAN, "reviewers" STRUCT("type" VARCHAR, "reviewer" STRUCT("matched_types" VARCHAR[], "variant_1" STRUCT("id" BIGINT, "login" VARCHAR, "type" VARCHAR), "variant_2" STRUCT("id" BIGINT, "name" VARCHAR, "slug" VARCHAR)))[]), "variant_3" STRUCT("id" BIGINT, "node_id" VARCHAR, "type" VARCHAR))[]` | yes |
| `environment_created_day` | `DATE` | no |

Approved metrics:

- `environment_count`: Current visible environment resources, including unused environments.
- `protected_branch_environment_count`: Environments explicitly restricted to protected branches.
- `custom_branch_environment_count`: Environments explicitly using named branch or tag policies.

### `deployment_branch_policies`

Configured environment branch/tag name patterns. Each returned policy must have a numeric ID despite the optional upstream declaration; missing identity fails qualification. Matching names are patterns, not actual branch/tag resources. Direct repository enrichment is analytical; environment parent keys and navigation remain available without a duplicate analytical path.

Grain: `repository_id`, `environment_id`, `deployment_branch_policy_id`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `deployment_branch_policies__lookup` | `deployment_branch_policy_id` | One policy record in its identified environment. |
| `deployment_branch_policies__environments` | `environment_name` | All visible records in selected current environments; empty environments produce no child records and all advertised pages are followed. |
| `deployment_branch_policies__repositories` | `owner`, `repository`, `organization`, `repositories` | All visible records in selected current environments; empty environments produce no child records and all advertised pages are followed. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `repository_id` | `BIGINT` | no |
| `environment_id` | `BIGINT` | no |
| `repository` | `VARCHAR` | no |
| `environment_name` | `VARCHAR` | no |
| `deployment_branch_policy_id` | `BIGINT` | no |
| `policy_node_id` | `VARCHAR` | yes |
| `name_pattern` | `VARCHAR` | yes |
| `target_type` | `VARCHAR` | yes |

Approved metrics:

- `deployment_branch_policy_count`: Current configured branch/tag pattern policies, not matching branches or deployment events.
- `deployment_branch_pattern_count`: Configured policies targeting branch names.
- `deployment_tag_pattern_count`: Configured policies targeting tag names.

### `deployment_protection_rules`

Custom deployment protection rules enabled in current environments. Integration identity/slug describe the provider of the rule, not the actor who deployed or reviewed. Built-in reviewer/wait-timer configuration is separate from custom rules. Direct repository enrichment is analytical; environment parent keys and navigation remain available without a duplicate analytical path.

Grain: `repository_id`, `environment_id`, `deployment_protection_rule_id`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `deployment_protection_rules__lookup` | `deployment_protection_rule_id` | One policy record in its identified environment. |
| `deployment_protection_rules__environments` | `environment_name` | All visible records in selected current environments; empty environments produce no child records and all advertised pages are followed. |
| `deployment_protection_rules__repositories` | `owner`, `repository`, `organization`, `repositories` | All visible records in selected current environments; empty environments produce no child records and all advertised pages are followed. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `repository_id` | `BIGINT` | no |
| `environment_id` | `BIGINT` | no |
| `repository` | `VARCHAR` | no |
| `environment_name` | `VARCHAR` | no |
| `deployment_protection_rule_id` | `BIGINT` | no |
| `rule_node_id` | `VARCHAR` | no |
| `enabled` | `BOOLEAN` | no |
| `integration_id` | `BIGINT` | no |
| `integration_slug` | `VARCHAR` | no |
| `integration_node_id` | `VARCHAR` | no |
| `integration_url` | `VARCHAR` | no |

Approved metrics:

- `deployment_protection_rule_count`: Custom protection rules returned as enabled for each selected environment; not approval decisions.

### `deployment_rule_integrations`

Available custom deployment-rule integrations per environment; an app can appear in several environment populations and counts once per environment. This endpoint needs repository admin/owner permission. Inaccessibility fails rather than being reported as an empty inventory. Direct repository enrichment is analytical; environment parent keys and navigation remain available without a duplicate analytical path.

Grain: `repository_id`, `environment_id`, `integration_id`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `deployment_rule_integrations__environments` | `environment_name` | All visible records in selected current environments; empty environments produce no child records and all advertised pages are followed. |
| `deployment_rule_integrations__repositories` | `owner`, `repository`, `organization`, `repositories` | All visible records in selected current environments; empty environments produce no child records and all advertised pages are followed. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `repository_id` | `BIGINT` | no |
| `environment_id` | `BIGINT` | no |
| `repository` | `VARCHAR` | no |
| `environment_name` | `VARCHAR` | no |
| `integration_id` | `BIGINT` | no |
| `integration_slug` | `VARCHAR` | no |
| `integration_node_id` | `VARCHAR` | no |
| `integration_url` | `VARCHAR` | no |

Approved metrics:

- `deployment_rule_integration_count`: Available custom protection-rule integration/environment pairs visible with required repository administration permissions; availability does not imply enabled or installed on every environment.

### `pages_deployment_statuses`

One current GitHub Pages deployment-status observation per repository and supplied lookup token. GitHub accepts deployment ID or commit SHA but returns no canonical ID, so aliases are not deduplicated into deployment business entities. Missing status remains unknown, not success.

Grain: `repository_id`, `pages_deployment_id`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `pages_deployment_statuses__lookup` | `pages_deployment_id` | One requested Pages deployment lookup token; no API collection discovery is implied. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `repository_id` | `BIGINT` | no |
| `repository` | `VARCHAR` | no |
| `pages_deployment_id` | `VARCHAR` | no |
| `status` | `VARCHAR` | yes |

Approved metrics:

- `pages_deployment_status_count`: Status lookup observations, not a complete Pages deployment population or distinct deployments across aliases.
- `successful_pages_deployment_status_count`: Lookup observations whose returned state is succeed.

### `commits`

Canonical repository-qualified commits. Repository history follows the selected ref or default branch, not all branches or unreachable objects. Every discovered commit is hydrated by SHA for consistent stats and account metadata. Original Git author and committer identities are distinct; GitHub account associations may be absent and are not inferred from email.

Grain: `repository_id`, `commit_sha`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `commits__pull_requests` | `pull_request_number` | All PR commits when the capped API list matches the hydrated PR commit count, then canonical commit detail by SHA. Truncation or changing populations fail instead of silently reporting a prefix. |
| `commits__lookup` | `commit_ref` | Visible records at the declared repository-qualified grain. Current refs are mutable; missing permissions or upstream errors fail the query. |
| `commits__git_objects` | `git_commit_sha` | Visible records at the declared repository-qualified grain. Current refs are mutable; missing permissions or upstream errors fail the query. |
| `commits__comparisons` | `commit_comparison` | Every paginated BASE..HEAD comparison commit, hydrated by immutable SHA. total_commits must match actual retrieved records; changed-file caps do not cap the commit population. |
| `commits__repositories` | `owner`, `repository`, `organization`, `repositories` | Reachable history of the selected ref, or default branch if omitted, narrowed by supplied path/author/committer selectors. All pages are followed. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `repository_id` | `BIGINT` | no |
| `repository` | `VARCHAR` | no |
| `commit_sha` | `VARCHAR` | no |
| `commit_node_id` | `VARCHAR` | no |
| `message` | `VARCHAR` | no |
| `author_name` | `VARCHAR` | yes |
| `author_email` | `VARCHAR` | yes |
| `authored_at` | `TIMESTAMP WITH TIME ZONE` | yes |
| `committer_name` | `VARCHAR` | yes |
| `committer_email` | `VARCHAR` | yes |
| `committed_at` | `TIMESTAMP WITH TIME ZONE` | yes |
| `author_account_id` | `BIGINT` | yes |
| `author_login` | `VARCHAR` | yes |
| `committer_account_id` | `BIGINT` | yes |
| `committer_login` | `VARCHAR` | yes |
| `tree_sha` | `VARCHAR` | no |
| `comment_count` | `BIGINT` | no |
| `parents` | `STRUCT("sha" VARCHAR, "url" VARCHAR, "html_url" VARCHAR)[]` | no |
| `verified` | `BOOLEAN` | yes |
| `verification_reason` | `VARCHAR` | yes |
| `additions` | `BIGINT` | yes |
| `deletions` | `BIGINT` | yes |
| `changes` | `BIGINT` | yes |
| `html_url` | `VARCHAR` | no |
| `authored_day` | `DATE` | yes |
| `committed_day` | `DATE` | yes |

Approved metrics:

- `commit_count`: Canonical repository-qualified commits. Repository history follows the selected ref or default branch, not all branches or unreachable objects. Every discovered commit is hydrated by SHA for consistent stats and account metadata. Original Git author and committer identities are distinct; GitHub account associations may be absent and are not inferred from email.
- `commit_added_lines`: Sum of GitHub commit-stat added-line observations over selected commit identities. Repeated edits across commits count repeatedly; not unique surviving lines.
- `commit_deleted_lines`: Sum of GitHub deleted-line observations over selected commit identities; not unique lines or a productivity score.

### `commit_files`

One changed path per repository-qualified commit. Renames retain previous_filename; missing patch does not mean zero changes or text content.

Grain: `repository_id`, `commit_sha`, `filename`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `commit_files__lookup` | `commit_ref` | Visible records at the declared repository-qualified grain. Current refs are mutable; missing permissions or upstream errors fail the query. |
| `commit_files__repositories` | `owner`, `repository`, `organization`, `repositories` | File changes for every selected history commit. Link pages are exhausted; reaching the documented 3000-file cap fails conservatively, even if exactly 3000 might be complete. Binary or omitted patches remain unknown. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `repository_id` | `BIGINT` | no |
| `repository` | `VARCHAR` | no |
| `commit_sha` | `VARCHAR` | no |
| `filename` | `VARCHAR` | no |
| `blob_sha` | `VARCHAR` | yes |
| `status` | `VARCHAR` | no |
| `additions` | `BIGINT` | no |
| `deletions` | `BIGINT` | no |
| `changes` | `BIGINT` | no |
| `patch` | `VARCHAR` | yes |
| `previous_filename` | `VARCHAR` | yes |
| `blob_url` | `VARCHAR` | no |
| `raw_url` | `VARCHAR` | no |
| `contents_url` | `VARCHAR` | no |

Approved metrics:

- `commit_file_change_count`: Selected commit/file change pairs, not unique files across history.
- `commit_file_added_lines`: Sum added lines across returned commit/file pairs, with complete file enumeration required.
- `commit_file_deleted_lines`: Sum deleted lines across returned commit/file pairs; repeated paths across commits are separate changes.

### `branches`

Current repository-qualified branch identities. Head-commit reverse lookup returns only branches whose current HEAD equals that commit, not every branch containing it.

Grain: `repository_id`, `branch_name`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `branches__lookup` | `branch_name` | Visible records at the declared repository-qualified grain. Current refs are mutable; missing permissions or upstream errors fail the query. |
| `branches__commit_heads` | `head_commit_sha` | Visible records at the declared repository-qualified grain. Current refs are mutable; missing permissions or upstream errors fail the query. |
| `branches__repositories` | `owner`, `repository`, `organization`, `repositories` | Visible records at the declared repository-qualified grain. Current refs are mutable; missing permissions or upstream errors fail the query. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `repository_id` | `BIGINT` | no |
| `repository` | `VARCHAR` | no |
| `branch_name` | `VARCHAR` | no |
| `head_sha` | `VARCHAR` | no |
| `protected` | `BOOLEAN` | no |

Approved metrics:

- `branch_count`: Current visible repository branch names, including multiple branches pointing at the same commit.

### `repository_tags`

Repository tag references at repository/name grain. The commit SHA is the peeled commit returned by the repository tag listing; annotated Git tag objects are a separate object kind.

Grain: `repository_id`, `tag_name`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `repository_tags__repositories` | `owner`, `repository`, `organization`, `repositories` | Visible records at the declared repository-qualified grain. Current refs are mutable; missing permissions or upstream errors fail the query. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `repository_id` | `BIGINT` | no |
| `repository` | `VARCHAR` | no |
| `tag_name` | `VARCHAR` | no |
| `tag_node_id` | `VARCHAR` | no |
| `commit_sha` | `VARCHAR` | no |
| `zipball_url` | `VARCHAR` | no |
| `tarball_url` | `VARCHAR` | no |

Approved metrics:

- `repository_tag_count`: Current tag names returned by repository tag listing, including annotated and lightweight tags; distinct from release count.

### `git_references`

Canonical repository-qualified Git references. Exact lookup differs from prefix matching, which may return names that merely begin with the requested prefix. Repository selection includes every namespace returned by GitHub.

Grain: `repository_id`, `ref_name`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `git_references__lookup` | `reference_name` | Visible records at the declared repository-qualified grain. Current refs are mutable; missing permissions or upstream errors fail the query. |
| `git_references__prefixes` | `ref_prefix` | Visible records at the declared repository-qualified grain. Current refs are mutable; missing permissions or upstream errors fail the query. |
| `git_references__repositories` | `owner`, `repository`, `organization`, `repositories` | Visible records at the declared repository-qualified grain. Current refs are mutable; missing permissions or upstream errors fail the query. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `repository_id` | `BIGINT` | no |
| `repository` | `VARCHAR` | no |
| `ref_name` | `VARCHAR` | no |
| `ref_node_id` | `VARCHAR` | no |
| `object_sha` | `VARCHAR` | no |
| `object_type` | `VARCHAR` | no |
| `object_url` | `VARCHAR` | no |
| `url` | `VARCHAR` | no |

Approved metrics:

- `git_reference_count`: Current fully qualified Git references across selected namespaces; target object SHA/type are explicit and not assumed to be commits.

### `git_tag_objects`

Annotated tag objects at repository/SHA grain. Target object type is polymorphic and can itself be another tag. Tagger is Git signature identity, not an inferred GitHub actor. Tagged date remains VARCHAR because the pinned schema does not declare date-time format.

Grain: `repository_id`, `tag_sha`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `git_tag_objects__lookup` | `git_tag_sha` | Visible records at the declared repository-qualified grain. Current refs are mutable; missing permissions or upstream errors fail the query. |
| `git_tag_objects__references` | `reference_name` | Visible records at the declared repository-qualified grain. Current refs are mutable; missing permissions or upstream errors fail the query. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `repository_id` | `BIGINT` | no |
| `repository` | `VARCHAR` | no |
| `tag_sha` | `VARCHAR` | no |
| `tag_node_id` | `VARCHAR` | no |
| `tag_name` | `VARCHAR` | no |
| `message` | `VARCHAR` | no |
| `tagger_name` | `VARCHAR` | no |
| `tagger_email` | `VARCHAR` | no |
| `tagged_at_text` | `VARCHAR` | no |
| `object_sha` | `VARCHAR` | no |
| `object_type` | `VARCHAR` | no |
| `url` | `VARCHAR` | no |
| `verified` | `BOOLEAN` | yes |
| `verification_reason` | `VARCHAR` | yes |

Approved metrics:

- `git_tag_object_count`: Distinct selected annotated Git tag objects; lightweight tags do not contribute tag objects.

### `git_trees`

Git tree object identities. Tree lookups reject truncated responses; child entries are exposed separately with direct and recursive populations.

Grain: `repository_id`, `tree_sha`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `git_trees__lookup` | `tree_sha` | Visible records at the declared repository-qualified grain. Current refs are mutable; missing permissions or upstream errors fail the query. |
| `git_trees__commits` | `commit_ref` | Visible records at the declared repository-qualified grain. Current refs are mutable; missing permissions or upstream errors fail the query. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `repository_id` | `BIGINT` | no |
| `repository` | `VARCHAR` | no |
| `tree_sha` | `VARCHAR` | no |
| `url` | `VARCHAR` | yes |
| `truncated` | `BOOLEAN` | no |

Approved metrics:

- `git_tree_count`: Selected Git tree objects at repository/SHA grain; not a count of files or recursive entries.

### `git_tree_entries`

Tree entries at repository/root-tree/path grain. Direct and recursive routes share identity for overlapping entries; recursive path names retain their hierarchy. Modes distinguish normal files, executables, symlinks and submodules.

Grain: `repository_id`, `tree_sha`, `path`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `git_tree_entries__recursive` | `recursive_tree_sha` | All recursive root-tree/path entries, including tree and submodule entries. truncated:true fails rather than claiming completeness; large trees require selecting smaller subtrees. |
| `git_tree_entries__trees` | `tree_sha` | Direct child entries of one exact tree SHA. Child trees remain entries rather than being silently flattened; truncated:true fails. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `repository_id` | `BIGINT` | no |
| `repository` | `VARCHAR` | no |
| `tree_sha` | `VARCHAR` | no |
| `path` | `VARCHAR` | no |
| `mode` | `VARCHAR` | no |
| `object_type` | `VARCHAR` | no |
| `object_sha` | `VARCHAR` | no |
| `size_bytes` | `BIGINT` | yes |
| `url` | `VARCHAR` | yes |

Approved metrics:

- `git_tree_entry_count`: Returned tree/path entries in the selected direct or recursive population; includes directories and submodules.
- `git_tree_blob_entry_count`: Tree/path entries whose object type is blob. Identical blobs at different paths count as separate file entries.
- `git_tree_entry_bytes`: Sum reported blob sizes over selected tree paths. Identical blobs at several paths contribute repeatedly; tree and submodule sizes remain NULL.

### `git_blobs`

Git blob objects retain explicit encoded content and encoding; Base64 is not treated as decoded text. GitHub supports blobs up to 100 MB. Unknown size remains NULL.

Grain: `repository_id`, `blob_sha`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `git_blobs__lookup` | `blob_sha` | Visible records at the declared repository-qualified grain. Current refs are mutable; missing permissions or upstream errors fail the query. |
| `git_blobs__trees` | `tree_sha` | Distinct Git blob identities reached from the selected direct or recursive tree entries; symlinks are blobs, submodules and trees are not. Truncated trees fail; the API blob-size ceiling can fail an oversized blob lookup. |
| `git_blobs__recursive_trees` | `recursive_tree_sha` | Distinct Git blob identities reached from the selected direct or recursive tree entries; symlinks are blobs, submodules and trees are not. Truncated trees fail; the API blob-size ceiling can fail an oversized blob lookup. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `repository_id` | `BIGINT` | no |
| `repository` | `VARCHAR` | no |
| `blob_sha` | `VARCHAR` | no |
| `blob_node_id` | `VARCHAR` | no |
| `size_bytes` | `BIGINT` | yes |
| `content` | `VARCHAR` | no |
| `encoding` | `VARCHAR` | no |
| `url` | `VARCHAR` | no |

Approved metrics:

- `git_blob_count`: Distinct selected repository-qualified Git blobs. Repeated paths sharing one blob do not multiply object count.
- `git_blob_bytes`: Sum known byte sizes over distinct selected blob identities, not encoded-string length or disk usage.

### `commit_comparisons`

One selected BASE...HEAD comparison at repository/comparison-selector grain. Mutable refs are evaluated at request time. Summary total_commits describes the whole comparison; commits are enumerated through the canonical commits comparison route. Typed changed files are first-page data for the whole comparison and reaching the 300-file cap fails conservatively.

Grain: `repository_id`, `comparison`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `commit_comparisons__lookup` | `commit_comparison` | Visible records at the declared repository-qualified grain. Current refs are mutable; missing permissions or upstream errors fail the query. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `repository_id` | `BIGINT` | no |
| `repository` | `VARCHAR` | no |
| `comparison` | `VARCHAR` | no |
| `base_sha` | `VARCHAR` | no |
| `merge_base_sha` | `VARCHAR` | no |
| `status` | `VARCHAR` | no |
| `ahead_by` | `BIGINT` | no |
| `behind_by` | `BIGINT` | no |
| `total_commits` | `BIGINT` | no |
| `files` | `STRUCT("filename" VARCHAR, "sha" VARCHAR, "status" VARCHAR, "additions" BIGINT, "deletions" BIGINT, "changes" BIGINT, "patch" VARCHAR, "previous_filename" VARCHAR, "blob_url" VARCHAR, "raw_url" VARCHAR, "contents_url" VARCHAR)[]` | yes |
| `html_url` | `VARCHAR` | no |

Approved metrics:

- `commit_comparison_count`: One selected BASE...HEAD comparison at repository/comparison-selector grain. Mutable refs are evaluated at request time. Summary total_commits describes the whole comparison; commits are enumerated through the canonical commits comparison route. Typed changed files are first-page data for the whole comparison and reaching the 300-file cap fails conservatively.

### `commit_pull_request_memberships`

Explicit commit-to-PR associations. GitHub returns the merged PR introducing a default-branch commit, or merged/open associated PRs for commits outside the default branch. This does not establish that the PR author authored or committed each commit. PR-selected retrieval reverses this association by enumerating all its commits with exact parent-count qualification; it does not limit membership discovery to default-branch history.

Grain: `repository_id`, `commit_sha`, `pull_request_id`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `commit_pull_request_memberships__pull_requests` | `pull_request_number` | Every commit/PR membership discovered from a selected PR when enumerated commits match its hydrated count; this reverse direction does not inherit default-branch history limitations. |
| `commit_pull_request_memberships__commits` | `commit_ref` | Visible records at the declared repository-qualified grain. Current refs are mutable; missing permissions or upstream errors fail the query. |
| `commit_pull_request_memberships__repositories` | `owner`, `repository`, `organization`, `repositories` | Visible records at the declared repository-qualified grain. Current refs are mutable; missing permissions or upstream errors fail the query. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `repository_id` | `BIGINT` | no |
| `repository` | `VARCHAR` | no |
| `commit_sha` | `VARCHAR` | no |
| `pull_request_id` | `BIGINT` | no |
| `pull_request_number` | `BIGINT` | no |
| `state` | `VARCHAR` | no |
| `title` | `VARCHAR` | no |
| `author_id` | `BIGINT` | yes |
| `author_login` | `VARCHAR` | yes |
| `html_url` | `VARCHAR` | no |

Approved metrics:

- `commit_pull_request_membership_count`: Commit/PR association pairs returned by GitHub. One PR containing several selected commits contributes several pairs; this is not distinct PR count.

### `projects`

Canonical Projects v2 entities. Ownership is distinct from creator/publisher identity; global node ID is the stable project key.

Grain: `project_node_id`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `projects__owners` | `owner`, `organization`, `user`, `project_owners` | All visible projects owned by the selected organization or personal user, or one project number. Generic owner resolves account type; every Link page is followed. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `project_node_id` | `VARCHAR` | no |
| `project_api_id` | `DOUBLE` | no |
| `project_number` | `BIGINT` | no |
| `project_owner_id` | `BIGINT` | no |
| `project_owner_login` | `VARCHAR` | no |
| `project_owner_type` | `VARCHAR` | no |
| `creator_id` | `BIGINT` | no |
| `creator_login` | `VARCHAR` | no |
| `title` | `VARCHAR` | no |
| `description` | `VARCHAR` | yes |
| `short_description` | `VARCHAR` | yes |
| `state` | `VARCHAR` | yes |
| `created_at` | `TIMESTAMP WITH TIME ZONE` | no |
| `updated_at` | `TIMESTAMP WITH TIME ZONE` | no |
| `closed_at` | `TIMESTAMP WITH TIME ZONE` | yes |
| `deleted_at` | `TIMESTAMP WITH TIME ZONE` | yes |
| `is_template` | `BOOLEAN` | yes |
| `is_public` | `BOOLEAN` | no |
| `deleted_by_id` | `BIGINT` | yes |
| `latest_status_update` | `STRUCT("id" DOUBLE, "node_id" VARCHAR, "status" VARCHAR, "created_at" TIMESTAMP WITH TIME ZONE, "updated_at" TIMESTAMP WITH TIME ZONE, "start_date" DATE, "target_date" DATE, "body" VARCHAR, "creator" STRUCT("id" BIGINT, "login" VARCHAR))` | yes |
| `created_day` | `DATE` | no |

Approved metrics:

- `project_count`: Visible Projects v2 identities across selected owners and project numbers.
- `closed_project_count`: Projects with a closure timestamp.

### `project_fields`

Project-qualified field definitions with typed single-select options and iteration configurations.

Grain: `project_node_id`, `project_field_id`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `project_fields__projects` | `owner`, `organization`, `user`, `project_owners` | All field definitions for every selected project, or one project-qualified numeric field ID. Typed options and iteration configuration retain nested values without multiplying field counts. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `project_node_id` | `VARCHAR` | no |
| `project_number` | `BIGINT` | no |
| `project_owner_login` | `VARCHAR` | no |
| `project_field_id` | `BIGINT` | no |
| `field_node_id` | `VARCHAR` | yes |
| `issue_field_id` | `BIGINT` | yes |
| `name` | `VARCHAR` | no |
| `data_type` | `VARCHAR` | no |
| `project_url` | `VARCHAR` | no |
| `created_at` | `TIMESTAMP WITH TIME ZONE` | no |
| `updated_at` | `TIMESTAMP WITH TIME ZONE` | no |
| `options` | `STRUCT("id" VARCHAR, "name" STRUCT("raw" VARCHAR, "html" VARCHAR), "description" STRUCT("raw" VARCHAR, "html" VARCHAR), "color" VARCHAR)[]` | yes |
| `configuration` | `STRUCT("start_day" BIGINT, "duration" BIGINT, "iterations" STRUCT("id" VARCHAR, "start_date" DATE, "duration" BIGINT, "title" STRUCT("raw" VARCHAR, "html" VARCHAR), "completed" BOOLEAN)[])` | yes |

Approved metrics:

- `project_field_count`: Field definitions in selected projects, including fields with no assigned values.

### `project_items`

Typed project items retain item/content identity separately and preserve redacted content. Archived status is current state; creator is the actor who added the item. REST item collections, numeric item lookup, filtered item search and saved-view populations reuse these canonical node identities and typed fields.

Grain: `project_node_id`, `project_item_node_id`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `project_items__lookup` | `project_item_node_id` | One project item by global node ID; its actual project and owner are read from GitHub. |
| `project_items__rest_lookup` | `project_item_id` | One REST numeric item in the selected project and owner, hydrated into the same canonical node identity and typed fields. Returned node and numeric identity and project membership must match; missing or inaccessible records fail. |
| `project_items__views` | `project_view_number` | All current items in the selected saved project view, and their independently paginated field values or memberships when requested. View filters define the population; this is not every item in the project. |
| `project_items__filtered_projects` | `project_item_query` | All advertised pages of REST-discovered project items, optionally restricted by GitHub Projects search, followed by canonical typed node hydration. Field-value and collection-member populations remain independently paginated. |
| `project_items__rest_projects` | `project_items_rest` | All advertised pages of REST-discovered project items, optionally restricted by GitHub Projects search, followed by canonical typed node hydration. Field-value and collection-member populations remain independently paginated. |
| `project_items__projects` | `owner`, `organization`, `user`, `project_owners` | All current visible project items, including drafts, archived and redacted items; inaccessible content remains NULL without discarding item identity. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `project_item_node_id` | `VARCHAR` | no |
| `project_node_id` | `VARCHAR` | no |
| `project_number` | `BIGINT` | no |
| `project_owner_login` | `VARCHAR` | yes |
| `project_owner_id` | `BIGINT` | yes |
| `item_type` | `VARCHAR` | no |
| `is_archived` | `BOOLEAN` | no |
| `creator_login` | `VARCHAR` | yes |
| `creator_id` | `BIGINT` | yes |
| `created_at` | `TIMESTAMP WITH TIME ZONE` | no |
| `updated_at` | `TIMESTAMP WITH TIME ZONE` | no |
| `content` | `STRUCT("__typename" VARCHAR, "DraftIssue" STRUCT("id" VARCHAR, "title" VARCHAR, "body" VARCHAR, "createdAt" TIMESTAMP WITH TIME ZONE, "updatedAt" TIMESTAMP WITH TIME ZONE), "Issue" STRUCT("id" VARCHAR, "number" BIGINT, "title" VARCHAR, "body" VARCHAR, "state" VARCHAR, "url" VARCHAR, "repository" STRUCT("id" VARCHAR, "nameWithOwner" VARCHAR)), "PullRequest" STRUCT("id" VARCHAR, "number" BIGINT, "title" VARCHAR, "body" VARCHAR, "state" VARCHAR, "url" VARCHAR, "repository" STRUCT("id" VARCHAR, "nameWithOwner" VARCHAR)))` | yes |
| `created_day` | `DATE` | no |

Approved metrics:

- `project_item_count`: Project item identities, not distinct content issues or PRs. The same content in two projects counts twice.
- `project_issue_item_count`: Project items whose content type is ISSUE.
- `project_pull_request_item_count`: Project items whose content type is PULL_REQUEST.
- `project_draft_item_count`: Project draft issue items.

### `project_field_values`

Typed project field values use a tagged STRUCT for all pinned GraphQL variants; scalar text, number and date values also have direct typed columns. Field names are labels, not identity. Each field-value connection is fully paginated. REST item collections, numeric item lookup, filtered item search and saved-view populations reuse these canonical node identities and typed fields.

Grain: `project_node_id`, `project_item_node_id`, `field_node_id`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `project_field_values__items` | `project_item_node_id` | Every assigned field value in the selected items; absent/unset values are not invented. Numeric field-ID filter is project-qualified when project_number is supplied. Connection-valued members are independently available in project_field_labels/users/pull_requests/reviewers. |
| `project_field_values__rest_lookup` | `project_item_id` | One REST numeric item in the selected project and owner, hydrated into the same canonical node identity and typed fields. Returned node and numeric identity and project membership must match; missing or inaccessible records fail. |
| `project_field_values__views` | `project_view_number` | All current items in the selected saved project view, and their independently paginated field values or memberships when requested. View filters define the population; this is not every item in the project. |
| `project_field_values__filtered_projects` | `project_item_query` | All advertised pages of REST-discovered project items, optionally restricted by GitHub Projects search, followed by canonical typed node hydration. Field-value and collection-member populations remain independently paginated. |
| `project_field_values__rest_projects` | `project_items_rest` | All advertised pages of REST-discovered project items, optionally restricted by GitHub Projects search, followed by canonical typed node hydration. Field-value and collection-member populations remain independently paginated. |
| `project_field_values__projects` | `owner`, `organization`, `user`, `project_owners` | Every assigned field value in the selected items; absent/unset values are not invented. Numeric field-ID filter is project-qualified when project_number is supplied. Connection-valued members are independently available in project_field_labels/users/pull_requests/reviewers. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `project_item_node_id` | `VARCHAR` | no |
| `project_node_id` | `VARCHAR` | no |
| `project_number` | `BIGINT` | no |
| `project_owner_login` | `VARCHAR` | yes |
| `field_node_id` | `VARCHAR` | no |
| `project_field_id` | `BIGINT` | yes |
| `field_name` | `VARCHAR` | no |
| `field_data_type` | `VARCHAR` | no |
| `value_type` | `VARCHAR` | no |
| `text_value` | `VARCHAR` | yes |
| `number_value` | `DOUBLE` | yes |
| `date_value` | `DATE` | yes |
| `value` | `STRUCT("__typename" VARCHAR, "ProjectV2ItemFieldDateValue" STRUCT("field" STRUCT("__typename" VARCHAR, "ProjectV2Field" STRUCT("id" VARCHAR, "name" VARCHAR, "dataType" VARCHAR), "ProjectV2IterationField" STRUCT("id" VARCHAR, "name" VARCHAR, "dataType" VARCHAR), "ProjectV2SingleSelectField" STRUCT("id" VARCHAR, "name" VARCHAR, "dataType" VARCHAR)), "date" DATE), "ProjectV2ItemFieldIterationValue" STRUCT("field" STRUCT("__typename" VARCHAR, "ProjectV2Field" STRUCT("id" VARCHAR, "name" VARCHAR, "dataType" VARCHAR), "ProjectV2IterationField" STRUCT("id" VARCHAR, "name" VARCHAR, "dataType" VARCHAR), "ProjectV2SingleSelectField" STRUCT("id" VARCHAR, "name" VARCHAR, "dataType" VARCHAR)), "iterationId" VARCHAR, "startDate" DATE, "duration" BIGINT, "title" VARCHAR), "ProjectV2ItemFieldLabelValue" STRUCT("field" STRUCT("__typename" VARCHAR, "ProjectV2Field" STRUCT("id" VARCHAR, "name" VARCHAR, "dataType" VARCHAR), "ProjectV2IterationField" STRUCT("id" VARCHAR, "name" VARCHAR, "dataType" VARCHAR), "ProjectV2SingleSelectField" STRUCT("id" VARCHAR, "name" VARCHAR, "dataType" VARCHAR))), "ProjectV2ItemFieldMilestoneValue" STRUCT("field" STRUCT("__typename" VARCHAR, "ProjectV2Field" STRUCT("id" VARCHAR, "name" VARCHAR, "dataType" VARCHAR), "ProjectV2IterationField" STRUCT("id" VARCHAR, "name" VARCHAR, "dataType" VARCHAR), "ProjectV2SingleSelectField" STRUCT("id" VARCHAR, "name" VARCHAR, "dataType" VARCHAR)), "milestone" STRUCT("id" VARCHAR, "number" BIGINT, "title" VARCHAR, "state" VARCHAR, "dueOn" TIMESTAMP WITH TIME ZONE, "url" VARCHAR)), "ProjectV2ItemFieldNumberValue" STRUCT("field" STRUCT("__typename" VARCHAR, "ProjectV2Field" STRUCT("id" VARCHAR, "name" VARCHAR, "dataType" VARCHAR), "ProjectV2IterationField" STRUCT("id" VARCHAR, "name" VARCHAR, "dataType" VARCHAR), "ProjectV2SingleSelectField" STRUCT("id" VARCHAR, "name" VARCHAR, "dataType" VARCHAR)), "number" DOUBLE), "ProjectV2ItemFieldPullRequestValue" STRUCT("field" STRUCT("__typename" VARCHAR, "ProjectV2Field" STRUCT("id" VARCHAR, "name" VARCHAR, "dataType" VARCHAR), "ProjectV2IterationField" STRUCT("id" VARCHAR, "name" VARCHAR, "dataType" VARCHAR), "ProjectV2SingleSelectField" STRUCT("id" VARCHAR, "name" VARCHAR, "dataType" VARCHAR))), "ProjectV2ItemFieldRepositoryValue" STRUCT("field" STRUCT("__typename" VARCHAR, "ProjectV2Field" STRUCT("id" VARCHAR, "name" VARCHAR, "dataType" VARCHAR), "ProjectV2IterationField" STRUCT("id" VARCHAR, "name" VARCHAR, "dataType" VARCHAR), "ProjectV2SingleSelectField" STRUCT("id" VARCHAR, "name" VARCHAR, "dataType" VARCHAR)), "repository" STRUCT("id" VARCHAR, "nameWithOwner" VARCHAR, "url" VARCHAR)), "ProjectV2ItemFieldReviewerValue" STRUCT("field" STRUCT("__typename" VARCHAR, "ProjectV2Field" STRUCT("id" VARCHAR, "name" VARCHAR, "dataType" VARCHAR), "ProjectV2IterationField" STRUCT("id" VARCHAR, "name" VARCHAR, "dataType" VARCHAR), "ProjectV2SingleSelectField" STRUCT("id" VARCHAR, "name" VARCHAR, "dataType" VARCHAR))), "ProjectV2ItemFieldSingleSelectValue" STRUCT("field" STRUCT("__typename" VARCHAR, "ProjectV2Field" STRUCT("id" VARCHAR, "name" VARCHAR, "dataType" VARCHAR), "ProjectV2IterationField" STRUCT("id" VARCHAR, "name" VARCHAR, "dataType" VARCHAR), "ProjectV2SingleSelectField" STRUCT("id" VARCHAR, "name" VARCHAR, "dataType" VARCHAR)), "optionId" VARCHAR, "name" VARCHAR, "color" VARCHAR, "description" VARCHAR), "ProjectV2ItemFieldTextValue" STRUCT("field" STRUCT("__typename" VARCHAR, "ProjectV2Field" STRUCT("id" VARCHAR, "name" VARCHAR, "dataType" VARCHAR), "ProjectV2IterationField" STRUCT("id" VARCHAR, "name" VARCHAR, "dataType" VARCHAR), "ProjectV2SingleSelectField" STRUCT("id" VARCHAR, "name" VARCHAR, "dataType" VARCHAR)), "text" VARCHAR), "ProjectV2ItemFieldUserValue" STRUCT("field" STRUCT("__typename" VARCHAR, "ProjectV2Field" STRUCT("id" VARCHAR, "name" VARCHAR, "dataType" VARCHAR), "ProjectV2IterationField" STRUCT("id" VARCHAR, "name" VARCHAR, "dataType" VARCHAR), "ProjectV2SingleSelectField" STRUCT("id" VARCHAR, "name" VARCHAR, "dataType" VARCHAR))))` | no |

Approved metrics:

- `project_field_value_count`: Assigned project-item/field pairs. Multi-valued labels/users/reviewers/PRs still count as one field value.
- `numeric_project_field_value_count`: Assigned ProjectV2ItemFieldNumberValue records with non-NULL number.

### `project_field_labels`

Typed members of collection-valued project fields. Associations preserve project, item and field identity. Reviewer identities retain their concrete User/Bot/Mannequin/Team role. REST item collections, numeric item lookup, filtered item search and saved-view populations reuse these canonical node identities and typed fields.

Grain: `project_node_id`, `project_item_node_id`, `field_node_id`, `member_node_id`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `project_field_labels__items` | `project_item_node_id` | Every visible member of the selected field values, independently cursor-paginated. Name-based fieldValueByName lookup rejects duplicate assigned field names rather than silently selecting the first match. |
| `project_field_labels__rest_lookup` | `project_item_id` | One REST numeric item in the selected project and owner, hydrated into the same canonical node identity and typed fields. Returned node and numeric identity and project membership must match; missing or inaccessible records fail. |
| `project_field_labels__views` | `project_view_number` | All current items in the selected saved project view, and their independently paginated field values or memberships when requested. View filters define the population; this is not every item in the project. |
| `project_field_labels__filtered_projects` | `project_item_query` | All advertised pages of REST-discovered project items, optionally restricted by GitHub Projects search, followed by canonical typed node hydration. Field-value and collection-member populations remain independently paginated. |
| `project_field_labels__rest_projects` | `project_items_rest` | All advertised pages of REST-discovered project items, optionally restricted by GitHub Projects search, followed by canonical typed node hydration. Field-value and collection-member populations remain independently paginated. |
| `project_field_labels__projects` | `owner`, `organization`, `user`, `project_owners` | Every visible member of the selected field values, independently cursor-paginated. Name-based fieldValueByName lookup rejects duplicate assigned field names rather than silently selecting the first match. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `project_item_node_id` | `VARCHAR` | no |
| `project_node_id` | `VARCHAR` | no |
| `project_number` | `BIGINT` | no |
| `project_owner_login` | `VARCHAR` | yes |
| `field_node_id` | `VARCHAR` | no |
| `project_field_id` | `BIGINT` | yes |
| `field_name` | `VARCHAR` | no |
| `member_node_id` | `VARCHAR` | no |
| `name` | `VARCHAR` | no |
| `color` | `VARCHAR` | no |
| `description` | `VARCHAR` | yes |
| `url` | `VARCHAR` | no |

Approved metrics:

- `project_field_label_count`: Visible item/field/member associations; not distinct people, labels, reviewers or PRs across items.

### `project_field_users`

Typed members of collection-valued project fields. Associations preserve project, item and field identity. Reviewer identities retain their concrete User/Bot/Mannequin/Team role. REST item collections, numeric item lookup, filtered item search and saved-view populations reuse these canonical node identities and typed fields.

Grain: `project_node_id`, `project_item_node_id`, `field_node_id`, `member_node_id`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `project_field_users__items` | `project_item_node_id` | Every visible member of the selected field values, independently cursor-paginated. Name-based fieldValueByName lookup rejects duplicate assigned field names rather than silently selecting the first match. |
| `project_field_users__rest_lookup` | `project_item_id` | One REST numeric item in the selected project and owner, hydrated into the same canonical node identity and typed fields. Returned node and numeric identity and project membership must match; missing or inaccessible records fail. |
| `project_field_users__views` | `project_view_number` | All current items in the selected saved project view, and their independently paginated field values or memberships when requested. View filters define the population; this is not every item in the project. |
| `project_field_users__filtered_projects` | `project_item_query` | All advertised pages of REST-discovered project items, optionally restricted by GitHub Projects search, followed by canonical typed node hydration. Field-value and collection-member populations remain independently paginated. |
| `project_field_users__rest_projects` | `project_items_rest` | All advertised pages of REST-discovered project items, optionally restricted by GitHub Projects search, followed by canonical typed node hydration. Field-value and collection-member populations remain independently paginated. |
| `project_field_users__projects` | `owner`, `organization`, `user`, `project_owners` | Every visible member of the selected field values, independently cursor-paginated. Name-based fieldValueByName lookup rejects duplicate assigned field names rather than silently selecting the first match. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `project_item_node_id` | `VARCHAR` | no |
| `project_node_id` | `VARCHAR` | no |
| `project_number` | `BIGINT` | no |
| `project_owner_login` | `VARCHAR` | yes |
| `field_node_id` | `VARCHAR` | no |
| `project_field_id` | `BIGINT` | yes |
| `field_name` | `VARCHAR` | no |
| `member_node_id` | `VARCHAR` | no |
| `login` | `VARCHAR` | no |
| `name` | `VARCHAR` | yes |
| `url` | `VARCHAR` | no |

Approved metrics:

- `project_field_user_count`: Visible item/field/member associations; not distinct people, labels, reviewers or PRs across items.

### `project_field_pull_requests`

Typed members of collection-valued project fields. Associations preserve project, item and field identity. Reviewer identities retain their concrete User/Bot/Mannequin/Team role. REST item collections, numeric item lookup, filtered item search and saved-view populations reuse these canonical node identities and typed fields.

Grain: `project_node_id`, `project_item_node_id`, `field_node_id`, `member_node_id`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `project_field_pull_requests__items` | `project_item_node_id` | Every visible member of the selected field values, independently cursor-paginated. Name-based fieldValueByName lookup rejects duplicate assigned field names rather than silently selecting the first match. |
| `project_field_pull_requests__rest_lookup` | `project_item_id` | One REST numeric item in the selected project and owner, hydrated into the same canonical node identity and typed fields. Returned node and numeric identity and project membership must match; missing or inaccessible records fail. |
| `project_field_pull_requests__views` | `project_view_number` | All current items in the selected saved project view, and their independently paginated field values or memberships when requested. View filters define the population; this is not every item in the project. |
| `project_field_pull_requests__filtered_projects` | `project_item_query` | All advertised pages of REST-discovered project items, optionally restricted by GitHub Projects search, followed by canonical typed node hydration. Field-value and collection-member populations remain independently paginated. |
| `project_field_pull_requests__rest_projects` | `project_items_rest` | All advertised pages of REST-discovered project items, optionally restricted by GitHub Projects search, followed by canonical typed node hydration. Field-value and collection-member populations remain independently paginated. |
| `project_field_pull_requests__projects` | `owner`, `organization`, `user`, `project_owners` | Every visible member of the selected field values, independently cursor-paginated. Name-based fieldValueByName lookup rejects duplicate assigned field names rather than silently selecting the first match. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `project_item_node_id` | `VARCHAR` | no |
| `project_node_id` | `VARCHAR` | no |
| `project_number` | `BIGINT` | no |
| `project_owner_login` | `VARCHAR` | yes |
| `field_node_id` | `VARCHAR` | no |
| `project_field_id` | `BIGINT` | yes |
| `field_name` | `VARCHAR` | no |
| `member_node_id` | `VARCHAR` | no |
| `number` | `BIGINT` | no |
| `title` | `VARCHAR` | no |
| `state` | `VARCHAR` | no |
| `url` | `VARCHAR` | no |
| `repository` | `VARCHAR` | no |

Approved metrics:

- `project_field_pull_request_count`: Visible item/field/member associations; not distinct people, labels, reviewers or PRs across items.

### `project_field_reviewers`

Typed members of collection-valued project fields. Associations preserve project, item and field identity. Reviewer identities retain their concrete User/Bot/Mannequin/Team role. REST item collections, numeric item lookup, filtered item search and saved-view populations reuse these canonical node identities and typed fields.

Grain: `project_node_id`, `project_item_node_id`, `field_node_id`, `member_node_id`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `project_field_reviewers__items` | `project_item_node_id` | Every visible member of the selected field values, independently cursor-paginated. Name-based fieldValueByName lookup rejects duplicate assigned field names rather than silently selecting the first match. |
| `project_field_reviewers__rest_lookup` | `project_item_id` | One REST numeric item in the selected project and owner, hydrated into the same canonical node identity and typed fields. Returned node and numeric identity and project membership must match; missing or inaccessible records fail. |
| `project_field_reviewers__views` | `project_view_number` | All current items in the selected saved project view, and their independently paginated field values or memberships when requested. View filters define the population; this is not every item in the project. |
| `project_field_reviewers__filtered_projects` | `project_item_query` | All advertised pages of REST-discovered project items, optionally restricted by GitHub Projects search, followed by canonical typed node hydration. Field-value and collection-member populations remain independently paginated. |
| `project_field_reviewers__rest_projects` | `project_items_rest` | All advertised pages of REST-discovered project items, optionally restricted by GitHub Projects search, followed by canonical typed node hydration. Field-value and collection-member populations remain independently paginated. |
| `project_field_reviewers__projects` | `owner`, `organization`, `user`, `project_owners` | Every visible member of the selected field values, independently cursor-paginated. Name-based fieldValueByName lookup rejects duplicate assigned field names rather than silently selecting the first match. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `project_item_node_id` | `VARCHAR` | no |
| `project_node_id` | `VARCHAR` | no |
| `project_number` | `BIGINT` | no |
| `project_owner_login` | `VARCHAR` | yes |
| `field_node_id` | `VARCHAR` | no |
| `project_field_id` | `BIGINT` | yes |
| `field_name` | `VARCHAR` | no |
| `member_node_id` | `VARCHAR` | no |
| `reviewer_type` | `VARCHAR` | no |
| `reviewer` | `STRUCT("__typename" VARCHAR, "Bot" STRUCT("id" VARCHAR, "login" VARCHAR), "Mannequin" STRUCT("id" VARCHAR, "login" VARCHAR), "Team" STRUCT("id" VARCHAR, "slug" VARCHAR, "name" VARCHAR), "User" STRUCT("id" VARCHAR, "login" VARCHAR, "name" VARCHAR))` | no |

Approved metrics:

- `project_field_reviewer_count`: Visible item/field/member associations; not distinct people, labels, reviewers or PRs across items.

### `packages`

Canonical package metadata qualified by account kind, stable account ID, registry type and package ID. Names are lookup context, not global identities. Organization, named-user and authenticated-user APIs preserve their distinct visibility; named-user object reads are public-only. Nullable owner summaries are qualified through the selected account endpoint. Conflict listing is a separately declared population. GitHub's pinned package schemas provide no download counter. package_access_mode records the organization, named-user or authenticated population and controls retrieval metadata; it is not part of entity identity. Linked repository ID/name are conformed from package-local evidence, preserving NULL for unlinked packages. Exact repository retrieval remains declared. Analytical enrichment through independently scoped repository listings is not approved: an accessible package may reference a public repository outside the caller's affiliated repository listing.

Grain: `package_owner_kind`, `package_owner_id`, `package_type`, `package_id`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `packages__conflicts` | `package_population` | Docker migration conflicts only; this is not the entire package inventory. |
| `packages__lookup` | `package_name` | One exact package or package-version identity; named-user object reads are public-package metadata only. |
| `packages__owners` | `package_type` | Enumerate the selected registry across one owner population. Default version listings select active versions; named-user version endpoints are public-only. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `package_owner_id` | `BIGINT` | no |
| `package_owner_login` | `VARCHAR` | no |
| `package_owner_kind` | `VARCHAR` | no |
| `package_id` | `BIGINT` | no |
| `package_name` | `VARCHAR` | no |
| `package_type` | `VARCHAR` | no |
| `visibility` | `VARCHAR` | no |
| `reported_version_count` | `BIGINT` | no |
| `created_at` | `TIMESTAMP WITH TIME ZONE` | no |
| `updated_at` | `TIMESTAMP WITH TIME ZONE` | no |
| `url` | `VARCHAR` | no |
| `html_url` | `VARCHAR` | no |
| `reported_owner_id` | `BIGINT` | yes |
| `reported_owner_login` | `VARCHAR` | yes |
| `repository_id` | `BIGINT` | yes |
| `package_repository` | `VARCHAR` | yes |
| `package_access_mode` | `VARCHAR` | no |
| `package_created_day` | `DATE` | no |

Approved metrics:

- `package_count`: Selected canonical packages; registry and owner scopes remain explicit.
- `public_package_count`: Selected packages with public visibility.
- `private_package_count`: Selected packages with private visibility.
- `reported_package_version_count`: Sum of current API-reported package version counters, distinct from enumerated selected version records.

### `package_versions`

Canonical package version metadata at qualified package identity plus version ID. Parent package traversal establishes the stable package ID; tag/name arrays do not define identity. Organization/authenticated lists support explicit deleted versions; named-user version reads are public-only and offer no state filter. deleted_at remains optional evidence rather than an invented state flag. No pinned download counter is available. package_access_mode records the organization, named-user or authenticated population and controls retrieval metadata; it is not part of entity identity.

Grain: `package_owner_kind`, `package_owner_id`, `package_type`, `package_id`, `package_version_id`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `package_versions__lookup` | `package_version_id` | One exact package or package-version identity; named-user object reads are public-package metadata only. |
| `package_versions__states` | `package_version_state` | Explicit active or deleted versions for an organization or authenticated account. Named-user scope and exact version lookup are excluded because those endpoints do not support the state filter. |
| `package_versions__packages` | `package_name` | All default active versions of one exact package; named-user versions are public-only. |
| `package_versions__owners` | `package_type` | Enumerate the selected registry across one owner population. Default version listings select active versions; named-user version endpoints are public-only. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `package_owner_id` | `BIGINT` | no |
| `package_owner_login` | `VARCHAR` | no |
| `package_owner_kind` | `VARCHAR` | no |
| `package_id` | `BIGINT` | no |
| `package_name` | `VARCHAR` | no |
| `package_type` | `VARCHAR` | no |
| `package_version_id` | `BIGINT` | no |
| `version_name` | `VARCHAR` | no |
| `url` | `VARCHAR` | no |
| `package_html_url` | `VARCHAR` | no |
| `html_url` | `VARCHAR` | yes |
| `license` | `VARCHAR` | yes |
| `description` | `VARCHAR` | yes |
| `created_at` | `TIMESTAMP WITH TIME ZONE` | no |
| `updated_at` | `TIMESTAMP WITH TIME ZONE` | no |
| `deleted_at` | `TIMESTAMP WITH TIME ZONE` | yes |
| `metadata_package_type` | `VARCHAR` | yes |
| `container_tags` | `VARCHAR[]` | yes |
| `docker_tags` | `VARCHAR[]` | yes |
| `package_access_mode` | `VARCHAR` | no |
| `package_version_created_day` | `DATE` | no |

Approved metrics:

- `package_version_count`: Enumerated selected package version records, including deleted versions only where explicitly requested or returned by lookup.
- `deleted_package_version_count`: Returned versions carrying a deletion timestamp; absent timestamps are not proof of an active version.

### `code_scanning_alerts`

Canonical code scanning alerts, with one identity across direct repository, organization and object routes. Full typed rule, assignee, linked-PR and most-recent-instance metadata is hydrated consistently. Rule IDs are scoped to tool context and are not invented as globally unique business keys.

Grain: `repository_id`, `alert_number`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `code_scanning_alerts__lookup` | `code_scanning_alert_number` | Visible selected records at the stated repository-qualified grain; all advertised collection pages are exhausted. Upstream permission and processing errors fail. |
| `code_scanning_alerts__organizations` | `organization` | Organization-visible records from the direct organization endpoint, including all advertised pages. Requires appropriate organization security access. |
| `code_scanning_alerts__repositories` | `owner`, `repository`, `organization`, `repositories` | Alerts discovered on the selected ref/PR or default branch, then hydrated by repository/alert number. Detail most_recent_instance is the canonical object endpoint snapshot, not necessarily the discovery ref; use alert_instances for per-ref observations. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `repository_id` | `BIGINT` | no |
| `repository` | `VARCHAR` | no |
| `alert_number` | `BIGINT` | no |
| `created_at` | `TIMESTAMP WITH TIME ZONE` | no |
| `updated_at` | `TIMESTAMP WITH TIME ZONE` | yes |
| `state` | `VARCHAR` | yes |
| `fixed_at` | `TIMESTAMP WITH TIME ZONE` | yes |
| `dismissed_at` | `TIMESTAMP WITH TIME ZONE` | yes |
| `dismissed_reason` | `VARCHAR` | yes |
| `dismissed_comment` | `VARCHAR` | yes |
| `html_url` | `VARCHAR` | no |
| `dismissed_by_id` | `BIGINT` | yes |
| `dismissed_by_login` | `VARCHAR` | yes |
| `dismissal_approved_by_id` | `BIGINT` | yes |
| `dismissal_approved_by_login` | `VARCHAR` | yes |
| `rule` | `STRUCT("id" VARCHAR, "name" VARCHAR, "severity" VARCHAR, "security_severity_level" VARCHAR, "description" VARCHAR, "full_description" VARCHAR, "tags" VARCHAR[], "help" VARCHAR, "help_uri" VARCHAR)` | no |
| `rule_id` | `VARCHAR` | yes |
| `rule_severity` | `VARCHAR` | yes |
| `security_severity` | `VARCHAR` | yes |
| `tool` | `STRUCT("name" VARCHAR, "guid" VARCHAR, "version" VARCHAR)` | no |
| `tool_name` | `VARCHAR` | yes |
| `most_recent_instance` | `STRUCT("ref" VARCHAR, "analysis_key" VARCHAR, "environment" VARCHAR, "category" VARCHAR, "state" VARCHAR, "commit_sha" VARCHAR, "html_url" VARCHAR, "classifications" VARCHAR[], "message" STRUCT("text" VARCHAR, "markdown" VARCHAR), "location" STRUCT("path" VARCHAR, "start_line" BIGINT, "end_line" BIGINT, "start_column" BIGINT, "end_column" BIGINT))` | no |
| `assignees` | `STRUCT("id" BIGINT, "login" VARCHAR, "type" VARCHAR, "html_url" VARCHAR)[]` | yes |
| `linked_pull_requests` | `STRUCT("id" BIGINT, "number" BIGINT, "state" VARCHAR, "title" VARCHAR, "html_url" VARCHAR, "user" STRUCT("id" BIGINT, "login" VARCHAR, "type" VARCHAR, "html_url" VARCHAR))[]` | yes |

Approved metrics:

- `code_scanning_alert_count`: Distinct repository-qualified alerts in the selected discovery population.
- `code_scanning_open_alert_count`: Canonical alert state is open.
- `code_scanning_fixed_alert_count`: Canonical alert state is fixed.
- `code_scanning_dismissed_alert_count`: Canonical alert state is dismissed.
- `code_scanning_high_security_alert_count`: High or critical security severity; distinct from diagnostic severity.

### `code_scanning_alert_instances`

Current alert instances keyed by repository, alert number, ref, analysis_key and environment; no server instance ID is provided. Missing identity components fail explicitly. This is the current instance population, not full analysis history. Classification and location remain typed.

Grain: `repository_id`, `alert_number`, `ref`, `analysis_key`, `environment`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `code_scanning_alert_instances__alerts` | `code_scanning_alert_number` | Visible selected records at the stated repository-qualified grain; all advertised collection pages are exhausted. Upstream permission and processing errors fail. |
| `code_scanning_alert_instances__repositories` | `owner`, `repository`, `organization`, `repositories` | Visible selected records at the stated repository-qualified grain; all advertised collection pages are exhausted. Upstream permission and processing errors fail. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `repository_id` | `BIGINT` | no |
| `repository` | `VARCHAR` | no |
| `alert_number` | `BIGINT` | no |
| `ref` | `VARCHAR` | no |
| `analysis_key` | `VARCHAR` | no |
| `environment` | `VARCHAR` | no |
| `category` | `VARCHAR` | yes |
| `state` | `VARCHAR` | yes |
| `commit_sha` | `VARCHAR` | yes |
| `html_url` | `VARCHAR` | yes |
| `classifications` | `VARCHAR[]` | yes |
| `message` | `STRUCT("text" VARCHAR)` | yes |
| `location` | `STRUCT("path" VARCHAR, "start_line" BIGINT, "end_line" BIGINT, "start_column" BIGINT, "end_column" BIGINT)` | yes |

Approved metrics:

- `code_scanning_alert_instance_count`: Alert/ref/analysis-key/environment instances; not unique alerts or historical findings.

### `code_scanning_analyses`

Code scanning analysis records across repository listing, ref/PR/tool/SARIF filters and exact lookup. results_count counts analysis results and may repeat the same alert across analyses. Legacy rules_count=0 can mean unavailable; no rule-total measure treats that sentinel as observed zero. SARIF representation download remains outside this typed metadata contract.

Grain: `repository_id`, `analysis_id`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `code_scanning_analyses__lookup` | `code_scanning_analysis_id` | Visible selected records at the stated repository-qualified grain; all advertised collection pages are exhausted. Upstream permission and processing errors fail. |
| `code_scanning_analyses__repositories` | `owner`, `repository`, `organization`, `repositories` | Visible selected records at the stated repository-qualified grain; all advertised collection pages are exhausted. Upstream permission and processing errors fail. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `repository_id` | `BIGINT` | no |
| `repository` | `VARCHAR` | no |
| `analysis_id` | `BIGINT` | no |
| `ref` | `VARCHAR` | no |
| `commit_sha` | `VARCHAR` | no |
| `analysis_key` | `VARCHAR` | no |
| `environment` | `VARCHAR` | no |
| `category` | `VARCHAR` | yes |
| `error` | `VARCHAR` | no |
| `created_at` | `TIMESTAMP WITH TIME ZONE` | no |
| `results_count` | `BIGINT` | no |
| `rules_count` | `BIGINT` | no |
| `url` | `VARCHAR` | no |
| `sarif_id` | `VARCHAR` | no |
| `deletable` | `BOOLEAN` | no |
| `warning` | `VARCHAR` | no |
| `tool` | `STRUCT("name" VARCHAR, "guid" VARCHAR, "version" VARCHAR)` | no |
| `tool_name` | `VARCHAR` | yes |

Approved metrics:

- `code_scanning_analysis_count`: Selected analysis records; one SARIF upload can produce several analyses.
- `code_scanning_analysis_result_count`: Sum result observations over selected analyses; not distinct alerts, vulnerabilities or rules.

### `codeql_databases`

Current CodeQL database metadata unified across repository collection and language lookup. Uploader is distinct from commit authors. Binary ZIP content download is not represented by the metadata URL alone.

Grain: `repository_id`, `database_id`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `codeql_databases__languages` | `codeql_database_language` | Visible selected records at the stated repository-qualified grain; all advertised collection pages are exhausted. Upstream permission and processing errors fail. |
| `codeql_databases__repositories` | `owner`, `repository`, `organization`, `repositories` | Visible selected records at the stated repository-qualified grain; all advertised collection pages are exhausted. Upstream permission and processing errors fail. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `repository_id` | `BIGINT` | no |
| `repository` | `VARCHAR` | no |
| `database_id` | `BIGINT` | no |
| `name` | `VARCHAR` | no |
| `language` | `VARCHAR` | no |
| `uploader_id` | `BIGINT` | no |
| `uploader_login` | `VARCHAR` | no |
| `content_type` | `VARCHAR` | no |
| `size_bytes` | `BIGINT` | no |
| `created_at` | `TIMESTAMP WITH TIME ZONE` | no |
| `updated_at` | `TIMESTAMP WITH TIME ZONE` | no |
| `url` | `VARCHAR` | no |
| `commit_sha` | `VARCHAR` | yes |

Approved metrics:

- `codeql_database_count`: Current uploaded CodeQL database identities, not all prior uploads.
- `codeql_database_bytes`: Sum current CodeQL database archive byte sizes at database identity grain.

### `code_scanning_autofixes`

Default-branch autofix status for one selected alert. This is not fix history; an alert can be ineligible or have no generated fix, and upstream errors remain errors.

Grain: `repository_id`, `alert_number`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `code_scanning_autofixes__alerts` | `code_scanning_alert_number` | Visible selected records at the stated repository-qualified grain; all advertised collection pages are exhausted. Upstream permission and processing errors fail. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `repository_id` | `BIGINT` | no |
| `repository` | `VARCHAR` | no |
| `alert_number` | `BIGINT` | no |
| `status` | `VARCHAR` | no |
| `description` | `VARCHAR` | yes |
| `started_at` | `TIMESTAMP WITH TIME ZONE` | no |

Approved metrics:

- `code_scanning_autofix_status_count`: Explicitly selected alert autofix status observations, not the number of generated fixes.

### `code_scanning_sarif_uploads`

SARIF upload processing status, reached by exact upload ID or reverse from an analysis. This does not return the SARIF document; failed may mean partially processed. Missing errors are unknown and remain distinct from an empty error list.

Grain: `repository_id`, `sarif_id`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `code_scanning_sarif_uploads__lookup` | `code_scanning_sarif_id` | Visible selected records at the stated repository-qualified grain; all advertised collection pages are exhausted. Upstream permission and processing errors fail. |
| `code_scanning_sarif_uploads__analyses` | `code_scanning_analysis_id` | Visible selected records at the stated repository-qualified grain; all advertised collection pages are exhausted. Upstream permission and processing errors fail. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `repository_id` | `BIGINT` | no |
| `repository` | `VARCHAR` | no |
| `sarif_id` | `VARCHAR` | no |
| `processing_status` | `VARCHAR` | yes |
| `analyses_url` | `VARCHAR` | yes |
| `errors` | `VARCHAR[]` | yes |

Approved metrics:

- `code_scanning_sarif_upload_count`: Distinct explicitly selected SARIF upload IDs, not one upload per analysis.

### `code_scanning_repository_settings`

Repository code scanning settings combine default setup and repository AI scan state at repository grain. These are current configuration observations, not scan executions or organization policy.

Grain: `repository_id`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `code_scanning_repository_settings__repositories` | `owner`, `repository`, `organization`, `repositories` | Visible selected records at the stated repository-qualified grain; all advertised collection pages are exhausted. Upstream permission and processing errors fail. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `repository_id` | `BIGINT` | no |
| `repository` | `VARCHAR` | no |
| `state` | `VARCHAR` | yes |
| `languages` | `VARCHAR[]` | yes |
| `runner_type` | `VARCHAR` | yes |
| `runner_label` | `VARCHAR` | yes |
| `query_suite` | `VARCHAR` | yes |
| `threat_model` | `VARCHAR` | yes |
| `updated_at` | `TIMESTAMP WITH TIME ZONE` | yes |
| `schedule` | `VARCHAR` | yes |
| `pr_scan` | `VARCHAR` | no |

Approved metrics:

- `code_scanning_repository_settings_count`: Selected repositories whose default setup and AI scan settings were successfully retrieved.

### `code_scanning_organization_settings`

Organization AI scan setting respecting enterprise policy; repositories inherit it but may opt out when enabled. Kept at organization grain, distinct from repository configuration.

Grain: `organization_id`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `code_scanning_organization_settings__organizations` | `organization` | One selected organization current AI scan policy; organization security permissions are required. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `organization_id` | `BIGINT` | no |
| `organization_login` | `VARCHAR` | no |
| `pr_scan` | `VARCHAR` | no |

Approved metrics:

- `code_scanning_organization_settings_count`: Selected organizations with retrieved AI scan configuration.

### `codeql_variant_analyses`

CodeQL variant analysis with explicit controller repository and initiating actor. Scanned-repository tasks are typed members; skipped-repository lists may be incomplete and caller-dependent even when their reported repository_count is larger. No metric counts listed skipped repositories as the complete skipped population.

Grain: `repository_id`, `variant_analysis_id`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `codeql_variant_analyses__lookup` | `codeql_variant_analysis_id` | Visible selected records at the stated repository-qualified grain; all advertised collection pages are exhausted. Upstream permission and processing errors fail. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `repository_id` | `BIGINT` | no |
| `repository` | `VARCHAR` | no |
| `variant_analysis_id` | `BIGINT` | no |
| `controller_repository_id` | `BIGINT` | no |
| `controller_repository` | `VARCHAR` | no |
| `actor_id` | `BIGINT` | no |
| `actor_login` | `VARCHAR` | no |
| `query_language` | `VARCHAR` | no |
| `query_pack_url` | `VARCHAR` | no |
| `created_at` | `TIMESTAMP WITH TIME ZONE` | yes |
| `updated_at` | `TIMESTAMP WITH TIME ZONE` | yes |
| `completed_at` | `TIMESTAMP WITH TIME ZONE` | yes |
| `status` | `VARCHAR` | no |
| `actions_workflow_run_id` | `BIGINT` | yes |
| `failure_reason` | `VARCHAR` | yes |
| `scanned_repositories` | `STRUCT("repository" STRUCT("id" BIGINT, "name" VARCHAR, "full_name" VARCHAR, "private" BOOLEAN, "stargazers_count" BIGINT, "updated_at" TIMESTAMP WITH TIME ZONE), "analysis_status" VARCHAR, "result_count" BIGINT, "artifact_size_in_bytes" BIGINT, "failure_message" VARCHAR)[]` | yes |
| `skipped_repositories` | `STRUCT("access_mismatch_repos" STRUCT("repository_count" BIGINT, "repositories" STRUCT("id" BIGINT, "name" VARCHAR, "full_name" VARCHAR, "private" BOOLEAN, "stargazers_count" BIGINT, "updated_at" TIMESTAMP WITH TIME ZONE)[]), "no_codeql_db_repos" STRUCT("repository_count" BIGINT, "repositories" STRUCT("id" BIGINT, "name" VARCHAR, "full_name" VARCHAR, "private" BOOLEAN, "stargazers_count" BIGINT, "updated_at" TIMESTAMP WITH TIME ZONE)[]), "over_limit_repos" STRUCT("repository_count" BIGINT, "repositories" STRUCT("id" BIGINT, "name" VARCHAR, "full_name" VARCHAR, "private" BOOLEAN, "stargazers_count" BIGINT, "updated_at" TIMESTAMP WITH TIME ZONE)[]), "not_found_repos" STRUCT("repository_count" BIGINT, "repository_full_names" VARCHAR[]))` | yes |

Approved metrics:

- `codeql_variant_analysis_count`: Explicitly selected variant analyses; no API-wide enumeration is implied.

### `codeql_variant_repository_tasks`

Variant analysis tasks retain controller repository as repository context and target_repository as a separate role. Exact target retrieval and scanned-repository expansion hydrate the same canonical task fields; skipped repositories are not scanned tasks.

Grain: `repository_id`, `variant_analysis_id`, `target_repository_id`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `codeql_variant_repository_tasks__lookup` | `codeql_target_repository` | Visible selected records at the stated repository-qualified grain; all advertised collection pages are exhausted. Upstream permission and processing errors fail. |
| `codeql_variant_repository_tasks__analyses` | `codeql_variant_analysis_id` | Visible selected records at the stated repository-qualified grain; all advertised collection pages are exhausted. Upstream permission and processing errors fail. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `repository_id` | `BIGINT` | no |
| `repository` | `VARCHAR` | no |
| `variant_analysis_id` | `BIGINT` | no |
| `target_repository_id` | `BIGINT` | no |
| `target_repository` | `VARCHAR` | no |
| `analysis_status` | `VARCHAR` | no |
| `artifact_size_in_bytes` | `BIGINT` | yes |
| `result_count` | `BIGINT` | yes |
| `failure_message` | `VARCHAR` | yes |
| `database_commit_sha` | `VARCHAR` | yes |
| `source_location_prefix` | `VARCHAR` | yes |
| `artifact_url` | `VARCHAR` | yes |

Approved metrics:

- `codeql_variant_repository_task_count`: Controller-repository/variant-analysis/target-repository tasks, including pending or failed tasks.
- `codeql_variant_result_count`: Sum reported task results. Pending or failed tasks lacking counts remain NULL; results across repositories are not deduplicated alerts.
- `codeql_variant_artifact_bytes`: Sum known result-artifact bytes over selected variant repository tasks; URLs are not downloaded by this metadata route.

### `code_scanning_dismissal_requests`

GHEC code scanning dismissal requests unified across repository, organization and alert lookup. Request IDs and request numbers are distinct from alert numbers. Metadata data.alert_number is source VARCHAR and is not silently cast into an alert relationship. Requester and nested reviewer roles remain separate. Collection routes have a bounded API lookback window.

Grain: `repository_id`, `dismissal_request_id`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `code_scanning_dismissal_requests__alerts` | `code_scanning_alert_number` | Visible selected records at the stated repository-qualified grain; all advertised collection pages are exhausted. Upstream permission and processing errors fail. |
| `code_scanning_dismissal_requests__organizations` | `organization` | Organization-visible records from the direct organization endpoint, including all advertised pages. Requires appropriate organization security access. |
| `code_scanning_dismissal_requests__repositories` | `owner`, `repository`, `organization`, `repositories` | Visible selected records at the stated repository-qualified grain; all advertised collection pages are exhausted. Upstream permission and processing errors fail. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `repository_id` | `BIGINT` | no |
| `repository` | `VARCHAR` | yes |
| `dismissal_request_id` | `BIGINT` | no |
| `dismissal_request_number` | `BIGINT` | yes |
| `organization_id` | `BIGINT` | yes |
| `organization_name` | `VARCHAR` | yes |
| `requester_id` | `BIGINT` | yes |
| `requester_login` | `VARCHAR` | yes |
| `request_type` | `VARCHAR` | yes |
| `resource_identifier` | `VARCHAR` | yes |
| `status` | `VARCHAR` | yes |
| `requester_comment` | `VARCHAR` | yes |
| `expires_at` | `TIMESTAMP WITH TIME ZONE` | yes |
| `created_at` | `TIMESTAMP WITH TIME ZONE` | yes |
| `url` | `VARCHAR` | yes |
| `html_url` | `VARCHAR` | yes |
| `data` | `STRUCT("reason" VARCHAR, "alert_number" VARCHAR, "pr_review_thread_id" VARCHAR)[]` | yes |
| `responses` | `STRUCT("id" BIGINT, "reviewer" STRUCT("actor_id" BIGINT, "actor_name" VARCHAR), "message" VARCHAR, "status" VARCHAR, "created_at" TIMESTAMP WITH TIME ZONE)[]` | yes |

Approved metrics:

- `code_scanning_dismissal_request_count`: Requests within the selected API lookback window, default month; not all historical requests.

### `dependabot_alerts`

Dependabot vulnerability alerts at repository ID plus alert number, unified across repository, organization and direct lookup. Dismisser and assignees retain distinct roles. Package ecosystem/name describe a dependency, not a GitHub Packages registry entity. All visible states are retained when filters are omitted; fixed and dismissed are distinct outcomes. Direct repository context is analytical; advisory and dismisser navigation do not create additional actor/repository analytical paths.

Grain: `repository_id`, `alert_number`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `dependabot_alerts__lookup` | `dependabot_alert_number` | All visible selected records, following every advertised collection page; API failures do not become empty populations. |
| `dependabot_alerts__organizations` | `organization` | All visible selected records, following every advertised collection page; API failures do not become empty populations. |
| `dependabot_alerts__repositories` | `owner`, `repository`, `organization`, `repositories` | All visible selected records, following every advertised collection page; API failures do not become empty populations. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `repository_id` | `BIGINT` | no |
| `repository` | `VARCHAR` | no |
| `alert_number` | `BIGINT` | no |
| `state` | `VARCHAR` | no |
| `dependency_ecosystem` | `VARCHAR` | yes |
| `dependency_name` | `VARCHAR` | yes |
| `manifest_path` | `VARCHAR` | yes |
| `dependency_scope` | `VARCHAR` | yes |
| `dependency_relationship` | `VARCHAR` | yes |
| `ghsa_id` | `VARCHAR` | no |
| `cve_id` | `VARCHAR` | yes |
| `advisory_summary` | `VARCHAR` | no |
| `advisory_classification` | `VARCHAR` | yes |
| `severity` | `VARCHAR` | no |
| `vulnerable_version_range` | `VARCHAR` | no |
| `first_patched_version` | `VARCHAR` | yes |
| `cvss_v3_score` | `DOUBLE` | yes |
| `cvss_v4_score` | `DOUBLE` | yes |
| `epss_percentage` | `DOUBLE` | yes |
| `created_at` | `TIMESTAMP WITH TIME ZONE` | no |
| `updated_at` | `TIMESTAMP WITH TIME ZONE` | no |
| `fixed_at` | `TIMESTAMP WITH TIME ZONE` | yes |
| `dismissed_at` | `TIMESTAMP WITH TIME ZONE` | yes |
| `auto_dismissed_at` | `TIMESTAMP WITH TIME ZONE` | yes |
| `dismissed_reason` | `VARCHAR` | yes |
| `dismissed_comment` | `VARCHAR` | yes |
| `url` | `VARCHAR` | no |
| `html_url` | `VARCHAR` | no |
| `assignees` | `STRUCT("id" BIGINT, "login" VARCHAR, "type" VARCHAR)[]` | yes |
| `dismissal_request` | `STRUCT("id" BIGINT, "status" VARCHAR, "requester" STRUCT("id" BIGINT, "login" VARCHAR), "created_at" TIMESTAMP WITH TIME ZONE, "url" VARCHAR)` | yes |
| `dismisser_id` | `BIGINT` | yes |
| `dismisser_login` | `VARCHAR` | yes |
| `dismisser_type` | `VARCHAR` | yes |
| `dependabot_created_day` | `DATE` | no |

Approved metrics:

- `dependabot_alert_count`: Selected alerts, not advisory or dependency occurrences.
- `open_dependabot_alert_count`: Alerts explicitly reported open.
- `fixed_dependabot_alert_count`: Alerts explicitly reported fixed.
- `dismissed_dependabot_alert_count`: Manual and automatic dismissals, distinct from fixed alerts.
- `critical_dependabot_alert_count`: Alerts with critical vulnerability severity.

### `security_advisories`

One canonical GHSA identity across global database and repository advisory populations. Global type and repository workflow state remain separate nullable concepts. Repository and global patch metadata retain their distinct first-patched-version and patched-ranges fields. Organization responses contain no owning repository identity, so repository context is honestly NULL there; global source-code URLs are not invented repository keys. Author, publisher and credited accounts remain distinct. Global, organization and repository visibility differs; inaccessible private records fail rather than disappearing.

Grain: `ghsa_id`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `security_advisories__global_lookup` | `global_advisory_id` | One global advisory identified by GHSA; private unpublished repository advisories are not promised in the global database. |
| `security_advisories__lookup` | `ghsa_id` | One visible repository advisory identified by GHSA, including unpublished states visible to the current credentials. |
| `security_advisories__global` | `advisory_type` | All global advisories in the explicitly selected reviewed, unreviewed or malware population; all pages are exhausted. |
| `security_advisories__organizations` | `organization` | All visible organization repository advisories, optionally filtered by workflow state. The response does not identify the owning repository. |
| `security_advisories__repositories` | `owner`, `repository`, `organization`, `repositories` | All visible advisories from selected repositories or an explicit cohort, optionally filtered by workflow state; all pages are exhausted. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `repository_id` | `BIGINT` | yes |
| `repository` | `VARCHAR` | yes |
| `ghsa_id` | `VARCHAR` | no |
| `cve_id` | `VARCHAR` | yes |
| `url` | `VARCHAR` | no |
| `html_url` | `VARCHAR` | no |
| `summary` | `VARCHAR` | no |
| `description` | `VARCHAR` | yes |
| `severity` | `VARCHAR` | yes |
| `updated_at` | `TIMESTAMP WITH TIME ZONE` | yes |
| `published_at` | `TIMESTAMP WITH TIME ZONE` | yes |
| `withdrawn_at` | `TIMESTAMP WITH TIME ZONE` | yes |
| `identifiers` | `STRUCT("type" VARCHAR, "value" VARCHAR)[]` | yes |
| `cwes` | `STRUCT("cwe_id" VARCHAR, "name" VARCHAR)[]` | yes |
| `cvss_v3_score` | `DOUBLE` | yes |
| `cvss_v4_score` | `DOUBLE` | yes |
| `advisory_population` | `VARCHAR` | no |
| `advisory_type` | `VARCHAR` | yes |
| `state` | `VARCHAR` | yes |
| `created_at` | `TIMESTAMP WITH TIME ZONE` | yes |
| `closed_at` | `TIMESTAMP WITH TIME ZONE` | yes |
| `github_reviewed_at` | `TIMESTAMP WITH TIME ZONE` | yes |
| `nvd_published_at` | `TIMESTAMP WITH TIME ZONE` | yes |
| `source_code_location` | `VARCHAR` | yes |
| `repository_advisory_url` | `VARCHAR` | yes |
| `epss_percentage` | `DOUBLE` | yes |
| `submission_accepted` | `BOOLEAN` | yes |
| `advisory_author_id` | `BIGINT` | yes |
| `advisory_author_login` | `VARCHAR` | yes |
| `advisory_author_type` | `VARCHAR` | yes |
| `advisory_publisher_id` | `BIGINT` | yes |
| `advisory_publisher_login` | `VARCHAR` | yes |
| `advisory_publisher_type` | `VARCHAR` | yes |
| `vulnerabilities` | `STRUCT("package" STRUCT("ecosystem" VARCHAR, "name" VARCHAR), "vulnerable_version_range" VARCHAR, "first_patched_version" VARCHAR, "vulnerable_functions" VARCHAR[], "patched_versions" VARCHAR)[]` | yes |
| `credits` | `STRUCT("user" STRUCT("id" BIGINT, "login" VARCHAR), "type" VARCHAR, "state" VARCHAR)[]` | yes |
| `security_advisory_published_day` | `DATE` | yes |

Approved metrics:

- `security_advisory_count`: Selected distinct GHSA advisory records.
- `critical_security_advisory_count`: Advisories explicitly assigned critical severity.
- `draft_security_advisory_count`: Repository advisories explicitly in draft workflow state; no draft state is inferred for global records.
- `malware_security_advisory_count`: Global advisories explicitly classified malware.

### `dependency_changes`

Dependency additions/removals observed for a requested base...head comparison, qualified by repository, comparison token, manifest, ecosystem, name, version, scope and change direction. Moving ref tokens are observation context rather than stable commit IDs. Repeated exact identities fail instead of inflating counts. Vulnerability associations remain typed nested evidence, not extra changed dependency rows.

Grain: `repository_id`, `comparison`, `manifest`, `ecosystem`, `name`, `version`, `scope`, `change_type`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `dependency_changes__comparisons` | `dependency_compare` | All visible selected records, following every advertised collection page; API failures do not become empty populations. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `repository_id` | `BIGINT` | no |
| `repository` | `VARCHAR` | no |
| `comparison` | `VARCHAR` | no |
| `change_type` | `VARCHAR` | no |
| `manifest` | `VARCHAR` | no |
| `ecosystem` | `VARCHAR` | no |
| `name` | `VARCHAR` | no |
| `version` | `VARCHAR` | no |
| `package_url` | `VARCHAR` | yes |
| `license` | `VARCHAR` | yes |
| `source_repository_url` | `VARCHAR` | yes |
| `scope` | `VARCHAR` | no |
| `vulnerabilities` | `STRUCT("severity" VARCHAR, "advisory_ghsa_id" VARCHAR, "advisory_summary" VARCHAR, "advisory_url" VARCHAR)[]` | no |

Approved metrics:

- `dependency_change_count`: Selected changed dependency coordinates within one comparison observation.
- `added_dependency_count`: Dependency coordinates reported added.
- `removed_dependency_count`: Dependency coordinates reported removed.
- `dependency_change_vulnerability_count`: Advisory associations on changed dependency records; one advisory affecting several coordinates counts several associations.

### `dependency_sboms`

Typed SPDX document snapshots at repository ID and document namespace. Packages and SPDX relationships retain typed nested fields; entries are not equated with GitHub Packages registry records. creationInfo.created is a string in the pinned API, so it remains unparsed text. Optional SPDX fields and missing relationships remain unknown. This synchronous export is deprecated in the pinned contract; asynchronous report downloads have a separate content/status contract and are not silently counted as typed SBOM snapshots.

Grain: `repository_id`, `document_namespace`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `dependency_sboms__repositories` | `owner`, `repository`, `organization`, `repositories` | All visible selected records, following every advertised collection page; API failures do not become empty populations. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `repository_id` | `BIGINT` | no |
| `repository` | `VARCHAR` | no |
| `document_namespace` | `VARCHAR` | no |
| `spdx_id` | `VARCHAR` | no |
| `spdx_version` | `VARCHAR` | no |
| `document_name` | `VARCHAR` | no |
| `data_license` | `VARCHAR` | no |
| `comment` | `VARCHAR` | yes |
| `created_text` | `VARCHAR` | no |
| `creators` | `VARCHAR[]` | no |
| `packages` | `STRUCT("SPDXID" VARCHAR, "name" VARCHAR, "versionInfo" VARCHAR, "downloadLocation" VARCHAR, "filesAnalyzed" BOOLEAN, "licenseConcluded" VARCHAR, "licenseDeclared" VARCHAR, "supplier" VARCHAR, "copyrightText" VARCHAR, "externalRefs" STRUCT("referenceCategory" VARCHAR, "referenceLocator" VARCHAR, "referenceType" VARCHAR)[])[]` | no |
| `relationships` | `STRUCT("relationshipType" VARCHAR, "spdxElementId" VARCHAR, "relatedSpdxElement" VARCHAR)[]` | yes |

Approved metrics:

- `dependency_sbom_count`: Selected SPDX document snapshots, not historical SBOM inventory.
- `sbom_package_entry_count`: Declared package entries in selected documents, including the root repository package; not distinct registry packages.
- `sbom_relationship_entry_count`: SPDX relationship entries where reported; absent relationship data remains NULL.

### `workflow_run_log_archives`

Workflow run log archives. Parent selectors and alternate routes preserve the canonical resource population; payload bytes remain detail fields.

Grain: `run_id`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `workflow_run_log_archives__lookup` | `run_id` | One requested representation per visible selected parent. All parent pages are exhausted; any unavailable or expired download fails the scan. |
| `workflow_run_log_archives__workflows` | `workflow_id` | One requested representation per visible selected parent. All parent pages are exhausted; any unavailable or expired download fails the scan. |
| `workflow_run_log_archives__repositories` | `owner`, `repository`, `organization`, `repositories` | One requested representation per visible selected parent. All parent pages are exhausted; any unavailable or expired download fails the scan. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `repository_id` | `BIGINT` | no |
| `repository` | `VARCHAR` | no |
| `run_id` | `BIGINT` | no |
| `status_code` | `BIGINT` | no |
| `content_type` | `VARCHAR` | no |
| `byte_length` | `BIGINT` | no |
| `pending` | `BOOLEAN` | no |
| `body` | `BLOB` | no |

Approved metrics:

- `workflow_run_log_archives_count`: Retrieved representation rows, including explicitly pending rows.
- `workflow_run_log_archives_median_bytes`: Median downloaded byte length; pending responses have zero downloaded bytes.

### `workflow_attempt_log_archives`

Workflow attempt log archives. Parent selectors and alternate routes preserve the canonical resource population; payload bytes remain detail fields.

Grain: `run_id`, `attempt_number`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `workflow_attempt_log_archives__lookup` | `attempt_number` | One requested representation per visible selected parent. All parent pages are exhausted; any unavailable or expired download fails the scan. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `repository_id` | `BIGINT` | no |
| `repository` | `VARCHAR` | no |
| `run_id` | `BIGINT` | no |
| `attempt_number` | `BIGINT` | no |
| `status_code` | `BIGINT` | no |
| `content_type` | `VARCHAR` | no |
| `byte_length` | `BIGINT` | no |
| `pending` | `BOOLEAN` | no |
| `body` | `BLOB` | no |

Approved metrics:

- `workflow_attempt_log_archives_count`: Retrieved representation rows, including explicitly pending rows.
- `workflow_attempt_log_archives_median_bytes`: Median downloaded byte length; pending responses have zero downloaded bytes.

### `workflow_job_logs`

Workflow job logs. Parent selectors and alternate routes preserve the canonical resource population; payload bytes remain detail fields.

Grain: `job_id`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `workflow_job_logs__lookup` | `job_id` | One requested representation per visible selected parent. All parent pages are exhausted; any unavailable or expired download fails the scan. |
| `workflow_job_logs__attempts` | `attempt_number` | One requested representation per visible selected parent. All parent pages are exhausted; any unavailable or expired download fails the scan. |
| `workflow_job_logs__runs` | `run_id` | One requested representation per visible selected parent. All parent pages are exhausted; any unavailable or expired download fails the scan. |
| `workflow_job_logs__workflows` | `workflow_id` | One requested representation per visible selected parent. All parent pages are exhausted; any unavailable or expired download fails the scan. |
| `workflow_job_logs__repositories` | `owner`, `repository`, `organization`, `repositories` | One requested representation per visible selected parent. All parent pages are exhausted; any unavailable or expired download fails the scan. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `repository_id` | `BIGINT` | no |
| `repository` | `VARCHAR` | no |
| `job_id` | `BIGINT` | no |
| `status_code` | `BIGINT` | no |
| `content_type` | `VARCHAR` | no |
| `byte_length` | `BIGINT` | no |
| `pending` | `BOOLEAN` | no |
| `body` | `BLOB` | no |
| `body_text` | `VARCHAR` | no |

Approved metrics:

- `workflow_job_logs_count`: Retrieved representation rows, including explicitly pending rows.
- `workflow_job_logs_median_bytes`: Median downloaded byte length; pending responses have zero downloaded bytes.

### `workflow_artifact_archives`

Workflow artifact archives. Parent selectors and alternate routes preserve the canonical resource population; payload bytes remain detail fields.

Grain: `artifact_id`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `workflow_artifact_archives__lookup` | `artifact_id` | One requested representation per visible selected parent. All parent pages are exhausted; any unavailable or expired download fails the scan. |
| `workflow_artifact_archives__runs` | `run_id` | One requested representation per visible selected parent. All parent pages are exhausted; any unavailable or expired download fails the scan. |
| `workflow_artifact_archives__workflows` | `workflow_id` | One requested representation per visible selected parent. All parent pages are exhausted; any unavailable or expired download fails the scan. |
| `workflow_artifact_archives__repositories` | `owner`, `repository`, `organization`, `repositories` | One requested representation per visible selected parent. All parent pages are exhausted; any unavailable or expired download fails the scan. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `repository_id` | `BIGINT` | no |
| `repository` | `VARCHAR` | no |
| `artifact_id` | `BIGINT` | no |
| `status_code` | `BIGINT` | no |
| `content_type` | `VARCHAR` | no |
| `byte_length` | `BIGINT` | no |
| `pending` | `BOOLEAN` | no |
| `body` | `BLOB` | no |

Approved metrics:

- `workflow_artifact_archives_count`: Retrieved representation rows, including explicitly pending rows.
- `workflow_artifact_archives_median_bytes`: Median downloaded byte length; pending responses have zero downloaded bytes.

### `release_asset_content`

Release asset content. Parent selectors and alternate routes preserve the canonical resource population; payload bytes remain detail fields.

Grain: `repository_id`, `release_asset_id`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `release_asset_content__lookup` | `release_asset_id` | One requested representation per visible selected parent. All parent pages are exhausted; any unavailable or expired download fails the scan. |
| `release_asset_content__releases` | `release_id` | One requested representation per visible selected parent. All parent pages are exhausted; any unavailable or expired download fails the scan. |
| `release_asset_content__tags` | `release_tag` | One requested representation per visible selected parent. All parent pages are exhausted; any unavailable or expired download fails the scan. |
| `release_asset_content__latest` | `release_selection` | One requested representation per visible selected parent. All parent pages are exhausted; any unavailable or expired download fails the scan. |
| `release_asset_content__repositories` | `owner`, `repository`, `organization`, `repositories` | One requested representation per visible selected parent. All parent pages are exhausted; any unavailable or expired download fails the scan. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `repository_id` | `BIGINT` | no |
| `repository` | `VARCHAR` | no |
| `release_asset_id` | `BIGINT` | no |
| `status_code` | `BIGINT` | no |
| `content_type` | `VARCHAR` | no |
| `byte_length` | `BIGINT` | no |
| `pending` | `BOOLEAN` | no |
| `body` | `BLOB` | no |

Approved metrics:

- `release_asset_content_count`: Retrieved representation rows, including explicitly pending rows.
- `release_asset_content_median_bytes`: Median downloaded byte length; pending responses have zero downloaded bytes.

### `code_scanning_sarif_content`

Code scanning sarif content. Parent selectors and alternate routes preserve the canonical resource population; payload bytes remain detail fields.

Grain: `repository_id`, `analysis_id`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `code_scanning_sarif_content__lookup` | `code_scanning_analysis_id` | One requested representation per visible selected parent. All parent pages are exhausted; any unavailable or expired download fails the scan. |
| `code_scanning_sarif_content__repositories` | `owner`, `repository`, `organization`, `repositories` | One requested representation per visible selected parent. All parent pages are exhausted; any unavailable or expired download fails the scan. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `repository_id` | `BIGINT` | no |
| `repository` | `VARCHAR` | no |
| `analysis_id` | `BIGINT` | no |
| `status_code` | `BIGINT` | no |
| `content_type` | `VARCHAR` | no |
| `byte_length` | `BIGINT` | no |
| `pending` | `BOOLEAN` | no |
| `body` | `BLOB` | no |
| `body_text` | `VARCHAR` | no |

Approved metrics:

- `code_scanning_sarif_content_count`: Retrieved representation rows, including explicitly pending rows.
- `code_scanning_sarif_content_median_bytes`: Median downloaded byte length; pending responses have zero downloaded bytes.

### `codeql_database_archives`

Codeql database archives. Parent selectors and alternate routes preserve the canonical resource population; payload bytes remain detail fields.

Grain: `repository_id`, `database_id`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `codeql_database_archives__languages` | `codeql_database_language` | One requested representation per visible selected parent. All parent pages are exhausted; any unavailable or expired download fails the scan. |
| `codeql_database_archives__repositories` | `owner`, `repository`, `organization`, `repositories` | One requested representation per visible selected parent. All parent pages are exhausted; any unavailable or expired download fails the scan. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `repository_id` | `BIGINT` | no |
| `repository` | `VARCHAR` | no |
| `database_id` | `BIGINT` | no |
| `language` | `VARCHAR` | no |
| `status_code` | `BIGINT` | no |
| `content_type` | `VARCHAR` | no |
| `byte_length` | `BIGINT` | no |
| `pending` | `BOOLEAN` | no |
| `body` | `BLOB` | no |

Approved metrics:

- `codeql_database_archives_count`: Retrieved representation rows, including explicitly pending rows.
- `codeql_database_archives_median_bytes`: Median downloaded byte length; pending responses have zero downloaded bytes.

### `workflow_step_logs`

Explicitly identified read-only content. Pending downloads are represented with NULL body and pending=true; downloaded bytes have no inferred internal schema.

Grain: `repository_id`, `job_id`, `step_number`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `workflow_step_logs__lookup` | `job_id`, `step_number` | One current representation for the explicit repository-qualified identifier. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `repository_id` | `BIGINT` | no |
| `repository` | `VARCHAR` | no |
| `job_id` | `BIGINT` | no |
| `step_number` | `BIGINT` | no |
| `status_code` | `BIGINT` | no |
| `content_type` | `VARCHAR` | no |
| `byte_length` | `BIGINT` | no |
| `pending` | `BOOLEAN` | no |
| `body` | `BLOB` | no |
| `body_text` | `VARCHAR` | no |

Approved metrics:

- `workflow_step_logs_count`: Retrieved representation rows, including explicitly pending rows.
- `workflow_step_logs_median_bytes`: Median downloaded byte length; pending responses have zero downloaded bytes.

### `dependency_sbom_report_content`

Explicitly identified read-only content. Pending downloads are represented with NULL body and pending=true; downloaded bytes have no inferred internal schema.

Grain: `repository_id`, `sbom_uuid`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `dependency_sbom_report_content__lookup` | `sbom_uuid` | One current representation for the explicit repository-qualified identifier. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `repository_id` | `BIGINT` | no |
| `repository` | `VARCHAR` | no |
| `sbom_uuid` | `VARCHAR` | no |
| `status_code` | `BIGINT` | no |
| `content_type` | `VARCHAR` | no |
| `byte_length` | `BIGINT` | no |
| `pending` | `BOOLEAN` | no |
| `body` | `BLOB` | yes |

Approved metrics:

- `dependency_sbom_report_content_count`: Retrieved representation rows, including explicitly pending rows.
- `dependency_sbom_report_content_median_bytes`: Median downloaded byte length; pending responses have zero downloaded bytes.
- `dependency_sbom_report_pending_count`: Report requests whose declared bodyless HTTP 202 response remains pending.

### `repository_archives`

ZIP and tarball retrieval routes share one content entity. The format and supplied Git ref qualify each repository snapshot; bytes retain the upstream archive representation.

Grain: `repository_id`, `ref`, `archive_format`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `repository_archives__zip` | `zip_archive_ref` | Archive of the selected ref at retrieval time; moving branch and tag refs are snapshot selectors, not immutable identities. |
| `repository_archives__tar` | `tar_archive_ref` | Archive of the selected ref at retrieval time; moving branch and tag refs are snapshot selectors, not immutable identities. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `repository_id` | `BIGINT` | no |
| `repository` | `VARCHAR` | no |
| `ref` | `VARCHAR` | no |
| `archive_format` | `VARCHAR` | no |
| `status_code` | `BIGINT` | no |
| `content_type` | `VARCHAR` | no |
| `byte_length` | `BIGINT` | no |
| `pending` | `BOOLEAN` | no |
| `body` | `BLOB` | no |

Approved metrics:

- `repository_archives_count`: Retrieved representation rows, including explicitly pending rows.
- `repository_archives_median_bytes`: Median downloaded byte length; pending responses have zero downloaded bytes.

### `secret_scanning_alerts`

Canonical secret scanning alerts unified across repository, organization and exact object routes. Detail hydration preserves typed credential metadata and all first-location variants. Resolver, assignee, bypass requester/reviewer and closure reviewer remain distinct roles. The secret value follows the explicit hide-secret API option; multi-repo flags do not identify or deduplicate the same credential across repositories.

Grain: `repository_id`, `alert_number`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `secret_scanning_alerts__lookup` | `secret_scanning_alert_number` | All visible records in the selected repository scope, following advertised pages. Authorization failures and malformed identity fail the query. |
| `secret_scanning_alerts__organizations` | `organization` | Visible eligible organization records using the direct organization endpoint and all advertised pages. Delegated request lists retain the selected API lookback window, default month. |
| `secret_scanning_alerts__repositories` | `owner`, `repository`, `organization`, `repositories` | All visible records in the selected repository scope, following advertised pages. Authorization failures and malformed identity fail the query. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `repository_id` | `BIGINT` | no |
| `repository` | `VARCHAR` | no |
| `alert_number` | `BIGINT` | no |
| `created_at` | `TIMESTAMP WITH TIME ZONE` | yes |
| `updated_at` | `TIMESTAMP WITH TIME ZONE` | yes |
| `url` | `VARCHAR` | yes |
| `html_url` | `VARCHAR` | yes |
| `locations_url` | `VARCHAR` | yes |
| `state` | `VARCHAR` | yes |
| `resolution` | `VARCHAR` | yes |
| `resolved_at` | `TIMESTAMP WITH TIME ZONE` | yes |
| `resolution_comment` | `VARCHAR` | yes |
| `secret_type` | `VARCHAR` | yes |
| `secret_type_display_name` | `VARCHAR` | yes |
| `provider` | `VARCHAR` | yes |
| `provider_slug` | `VARCHAR` | yes |
| `secret` | `VARCHAR` | yes |
| `push_protection_bypassed` | `BOOLEAN` | yes |
| `push_protection_bypassed_at` | `TIMESTAMP WITH TIME ZONE` | yes |
| `push_protection_bypass_request_reviewer_comment` | `VARCHAR` | yes |
| `push_protection_bypass_request_comment` | `VARCHAR` | yes |
| `push_protection_bypass_request_html_url` | `VARCHAR` | yes |
| `validity` | `VARCHAR` | yes |
| `publicly_leaked` | `BOOLEAN` | yes |
| `multi_repo` | `BOOLEAN` | yes |
| `is_base64_encoded` | `BOOLEAN` | yes |
| `has_more_locations` | `BOOLEAN` | yes |
| `closure_request_comment` | `VARCHAR` | yes |
| `closure_request_reviewer_comment` | `VARCHAR` | yes |
| `first_location_detected` | `STRUCT("matched_types" VARCHAR[], "variant_1" STRUCT("blob_sha" VARCHAR, "blob_url" VARCHAR, "commit_sha" VARCHAR, "commit_url" VARCHAR, "end_column" DOUBLE, "end_line" DOUBLE, "html_url" VARCHAR, "path" VARCHAR, "start_column" DOUBLE, "start_line" DOUBLE), "variant_2" STRUCT("blob_sha" VARCHAR, "commit_sha" VARCHAR, "commit_url" VARCHAR, "end_column" DOUBLE, "end_line" DOUBLE, "page_url" VARCHAR, "path" VARCHAR, "start_column" DOUBLE, "start_line" DOUBLE), "variant_3" STRUCT("html_url" VARCHAR, "issue_title_url" VARCHAR), "variant_4" STRUCT("html_url" VARCHAR, "issue_body_url" VARCHAR), "variant_5" STRUCT("html_url" VARCHAR, "issue_comment_url" VARCHAR), "variant_6" STRUCT("discussion_title_url" VARCHAR), "variant_7" STRUCT("discussion_body_url" VARCHAR), "variant_8" STRUCT("discussion_comment_url" VARCHAR), "variant_9" STRUCT("html_url" VARCHAR, "pull_request_title_url" VARCHAR), "variant_10" STRUCT("html_url" VARCHAR, "pull_request_body_url" VARCHAR), "variant_11" STRUCT("html_url" VARCHAR, "pull_request_comment_url" VARCHAR), "variant_12" STRUCT("html_url" VARCHAR, "pull_request_review_url" VARCHAR), "variant_13" STRUCT("html_url" VARCHAR, "pull_request_review_comment_url" VARCHAR))` | yes |
| `metadata` | `STRUCT("key" VARCHAR, "value" VARCHAR)[]` | yes |
| `resolved_by_id` | `BIGINT` | yes |
| `resolved_by_login` | `VARCHAR` | yes |
| `push_protection_bypassed_by_id` | `BIGINT` | yes |
| `push_protection_bypassed_by_login` | `VARCHAR` | yes |
| `push_protection_bypass_request_reviewer_id` | `BIGINT` | yes |
| `push_protection_bypass_request_reviewer_login` | `VARCHAR` | yes |
| `assigned_to_id` | `BIGINT` | yes |
| `assigned_to_login` | `VARCHAR` | yes |
| `closure_request_reviewer_id` | `BIGINT` | yes |
| `closure_request_reviewer_login` | `VARCHAR` | yes |

Approved metrics:

- `secret_scanning_alert_count`: Distinct repository-qualified secret alerts, not distinct credentials across repositories.
- `secret_scanning_open_alert_count`: Alerts whose observed lifecycle state is open.
- `secret_scanning_resolved_alert_count`: Resolved alerts; resolution alone does not establish revoked or inactive credentials.
- `secret_scanning_active_alert_count`: Latest observed credential validity is active, independent of alert lifecycle.
- `secret_scanning_bypassed_alert_count`: Alerts explicitly marked as caused by a push-protection bypass. Unknown is not false.

### `secret_scanning_locations`

Every location for selected secret alerts, including code, wiki, issue, discussion and PR variants. The details column is a typed tagged STRUCT with all thirteen source alternatives. Grain uses repository, alert number and a page-spanning retrieval-local ordinal; ordinal is not a stable resource key. first_location_detected is not substituted for the full location collection.

Grain: `repository_id`, `alert_number`, `location_ordinal`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `secret_scanning_locations__alerts` | `secret_scanning_alert_number` | All visible records in the selected repository scope, following advertised pages. Authorization failures and malformed identity fail the query. |
| `secret_scanning_locations__repositories` | `owner`, `repository`, `organization`, `repositories` | All visible records in the selected repository scope, following advertised pages. Authorization failures and malformed identity fail the query. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `repository_id` | `BIGINT` | no |
| `repository` | `VARCHAR` | no |
| `alert_number` | `BIGINT` | no |
| `location_ordinal` | `BIGINT` | no |
| `location_type` | `VARCHAR` | no |
| `details` | `STRUCT("matched_types" VARCHAR[], "variant_1" STRUCT("blob_sha" VARCHAR, "blob_url" VARCHAR, "commit_sha" VARCHAR, "commit_url" VARCHAR, "end_column" DOUBLE, "end_line" DOUBLE, "html_url" VARCHAR, "path" VARCHAR, "start_column" DOUBLE, "start_line" DOUBLE), "variant_2" STRUCT("blob_sha" VARCHAR, "commit_sha" VARCHAR, "commit_url" VARCHAR, "end_column" DOUBLE, "end_line" DOUBLE, "page_url" VARCHAR, "path" VARCHAR, "start_column" DOUBLE, "start_line" DOUBLE), "variant_3" STRUCT("html_url" VARCHAR, "issue_title_url" VARCHAR), "variant_4" STRUCT("html_url" VARCHAR, "issue_body_url" VARCHAR), "variant_5" STRUCT("html_url" VARCHAR, "issue_comment_url" VARCHAR), "variant_6" STRUCT("discussion_title_url" VARCHAR), "variant_7" STRUCT("discussion_body_url" VARCHAR), "variant_8" STRUCT("discussion_comment_url" VARCHAR), "variant_9" STRUCT("html_url" VARCHAR, "pull_request_title_url" VARCHAR), "variant_10" STRUCT("html_url" VARCHAR, "pull_request_body_url" VARCHAR), "variant_11" STRUCT("html_url" VARCHAR, "pull_request_comment_url" VARCHAR), "variant_12" STRUCT("html_url" VARCHAR, "pull_request_review_url" VARCHAR), "variant_13" STRUCT("html_url" VARCHAR, "pull_request_review_comment_url" VARCHAR))` | no |

Approved metrics:

- `secret_scanning_location_count`: Returned location occurrences, including all pages. No durable server location ID exists; retrieval-local ordinal preserves distinct occurrences without inventing cross-snapshot identity.

### `secret_scanning_scan_snapshots`

Latest scan observations by API category: incremental, pattern update, backfill, custom-pattern backfill and generic-secret backfill. Typed arrays preserve scan type, status and nullable times. GitHub returns latest scans per type; no exhaustive historical execution count or stable scan ID is claimed.

Grain: `repository_id`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `secret_scanning_scan_snapshots__repositories` | `owner`, `repository`, `organization`, `repositories` | All visible records in the selected repository scope, following advertised pages. Authorization failures and malformed identity fail the query. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `repository_id` | `BIGINT` | no |
| `repository` | `VARCHAR` | no |
| `incremental_scans` | `STRUCT("type" VARCHAR, "status" VARCHAR, "completed_at" TIMESTAMP WITH TIME ZONE, "started_at" TIMESTAMP WITH TIME ZONE)[]` | yes |
| `pattern_update_scans` | `STRUCT("type" VARCHAR, "status" VARCHAR, "completed_at" TIMESTAMP WITH TIME ZONE, "started_at" TIMESTAMP WITH TIME ZONE)[]` | yes |
| `backfill_scans` | `STRUCT("type" VARCHAR, "status" VARCHAR, "completed_at" TIMESTAMP WITH TIME ZONE, "started_at" TIMESTAMP WITH TIME ZONE)[]` | yes |
| `custom_pattern_backfill_scans` | `STRUCT("type" VARCHAR, "status" VARCHAR, "completed_at" TIMESTAMP WITH TIME ZONE, "started_at" TIMESTAMP WITH TIME ZONE, "pattern_name" VARCHAR, "pattern_scope" VARCHAR)[]` | yes |
| `generic_secrets_backfill_scans` | `STRUCT("type" VARCHAR, "status" VARCHAR, "completed_at" TIMESTAMP WITH TIME ZONE, "started_at" TIMESTAMP WITH TIME ZONE)[]` | yes |

Approved metrics:

- `secret_scanning_scan_snapshot_count`: Repositories with a retrieved latest-scan snapshot, not historical scan executions.

### `secret_scanning_bypass_requests`

Canonical delegated secret scanning bypass requests across repository, organization and object lookup. Request identity is distinct from alert identity. Requester and nested reviewer roles are explicit. Typed data preserves source strings; no unapproved cast converts alert-number text or a polymorphic resource identifier into a relationship. Collection lookback defaults to month.

Grain: `repository_id`, `request_id`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `secret_scanning_bypass_requests__lookup` | `secret_scanning_bypass_number` | All visible records in the selected repository scope, following advertised pages. Authorization failures and malformed identity fail the query. |
| `secret_scanning_bypass_requests__organizations` | `organization` | Visible eligible organization records using the direct organization endpoint and all advertised pages. Delegated request lists retain the selected API lookback window, default month. |
| `secret_scanning_bypass_requests__repositories` | `owner`, `repository`, `organization`, `repositories` | All visible records in the selected repository scope, following advertised pages. Authorization failures and malformed identity fail the query. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `repository_id` | `BIGINT` | no |
| `repository` | `VARCHAR` | yes |
| `request_id` | `BIGINT` | no |
| `request_number` | `BIGINT` | yes |
| `organization_id` | `BIGINT` | yes |
| `organization_name` | `VARCHAR` | yes |
| `requester_id` | `BIGINT` | yes |
| `requester_login` | `VARCHAR` | yes |
| `request_type` | `VARCHAR` | yes |
| `resource_identifier` | `VARCHAR` | yes |
| `status` | `VARCHAR` | yes |
| `requester_comment` | `VARCHAR` | yes |
| `expires_at` | `TIMESTAMP WITH TIME ZONE` | yes |
| `created_at` | `TIMESTAMP WITH TIME ZONE` | yes |
| `url` | `VARCHAR` | yes |
| `html_url` | `VARCHAR` | yes |
| `responses` | `STRUCT("id" BIGINT, "reviewer" STRUCT("actor_id" BIGINT, "actor_name" VARCHAR), "status" VARCHAR, "created_at" TIMESTAMP WITH TIME ZONE)[]` | yes |
| `data` | `STRUCT("secret_type" VARCHAR, "bypass_reason" VARCHAR, "path" VARCHAR, "branch" VARCHAR)[]` | yes |

Approved metrics:

- `secret_scanning_bypass_request_count`: Delegated bypass requests in the selected API lookback window, default month; not all historical requests.
- `secret_scanning_bypass_approved_count`: Requests currently approved; approval is not equivalent to a completed bypass or resolved alert.

### `secret_scanning_dismissal_requests`

Canonical delegated secret scanning dismissal requests across repository, organization and object lookup. Request identity is distinct from alert identity. Requester and nested reviewer roles are explicit. Typed data preserves source strings; no unapproved cast converts alert-number text or a polymorphic resource identifier into a relationship. Collection lookback defaults to month.

Grain: `repository_id`, `request_id`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `secret_scanning_dismissal_requests__alerts` | `secret_scanning_alert_number` | All visible records in the selected repository scope, following advertised pages. Authorization failures and malformed identity fail the query. |
| `secret_scanning_dismissal_requests__organizations` | `organization` | Visible eligible organization records using the direct organization endpoint and all advertised pages. Delegated request lists retain the selected API lookback window, default month. |
| `secret_scanning_dismissal_requests__repositories` | `owner`, `repository`, `organization`, `repositories` | All visible records in the selected repository scope, following advertised pages. Authorization failures and malformed identity fail the query. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `repository_id` | `BIGINT` | no |
| `repository` | `VARCHAR` | yes |
| `request_id` | `BIGINT` | no |
| `request_number` | `BIGINT` | yes |
| `organization_id` | `BIGINT` | yes |
| `organization_name` | `VARCHAR` | yes |
| `requester_id` | `BIGINT` | yes |
| `requester_login` | `VARCHAR` | yes |
| `request_type` | `VARCHAR` | yes |
| `resource_identifier` | `VARCHAR` | yes |
| `status` | `VARCHAR` | yes |
| `requester_comment` | `VARCHAR` | yes |
| `expires_at` | `TIMESTAMP WITH TIME ZONE` | yes |
| `created_at` | `TIMESTAMP WITH TIME ZONE` | yes |
| `url` | `VARCHAR` | yes |
| `html_url` | `VARCHAR` | yes |
| `responses` | `STRUCT("id" BIGINT, "reviewer" STRUCT("actor_id" BIGINT, "actor_name" VARCHAR), "status" VARCHAR, "created_at" TIMESTAMP WITH TIME ZONE)[]` | yes |
| `data` | `STRUCT("secret_type" VARCHAR, "alert_number" VARCHAR, "reason" VARCHAR)[]` | yes |

Approved metrics:

- `secret_scanning_dismissal_request_count`: Delegated dismissal requests in the selected API lookback window, default month; not all historical requests.
- `secret_scanning_dismissal_approved_count`: Requests currently approved; approval is not equivalent to a completed bypass or resolved alert.

### `secret_scanning_custom_patterns`

Custom-pattern observations unified across organization and repository retrieval, qualified by explicit owner scope kind/id and pattern ID. Scope is where the pattern was retrieved; the API provides no separate original-definition owner. Regex and constraints remain typed values; pattern publication and push-protection are independent settings. Optional repository and organization owner keys preserve explicit scope roles; the absent owner kind is NULL.

Grain: `scope_kind`, `scope_id`, `pattern_id`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `secret_scanning_custom_patterns__organizations` | `organization` | Custom patterns returned for the selected owner scope, following every advertised cursor page. Scope records remain explicit; no global or inherited-pattern ownership is inferred. |
| `secret_scanning_custom_patterns__repositories` | `owner`, `repository`, `organization`, `repositories` | Custom patterns returned for the selected owner scope, following every advertised cursor page. Scope records remain explicit; no global or inherited-pattern ownership is inferred. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `scope_kind` | `VARCHAR` | no |
| `scope_id` | `BIGINT` | no |
| `scope_login` | `VARCHAR` | no |
| `pattern_id` | `BIGINT` | no |
| `name` | `VARCHAR` | no |
| `pattern` | `VARCHAR` | no |
| `slug` | `VARCHAR` | no |
| `state` | `VARCHAR` | no |
| `push_protection_enabled` | `BOOLEAN` | no |
| `start_delimiter` | `VARCHAR` | yes |
| `end_delimiter` | `VARCHAR` | yes |
| `must_match` | `VARCHAR[]` | yes |
| `must_not_match` | `VARCHAR[]` | yes |
| `custom_pattern_version` | `VARCHAR` | yes |
| `created_at` | `TIMESTAMP WITH TIME ZONE` | yes |
| `updated_at` | `TIMESTAMP WITH TIME ZONE` | yes |
| `repository_id` | `BIGINT` | yes |
| `repository` | `VARCHAR` | yes |
| `organization_id` | `BIGINT` | yes |
| `organization_login` | `VARCHAR` | yes |

Approved metrics:

- `secret_scanning_custom_pattern_count`: Pattern identities within explicit selected scope, not globally deduplicated inherited definitions.
- `secret_scanning_protected_pattern_count`: Selected scoped custom patterns with push protection enabled.

### `secret_scanning_pattern_configurations`

Organization secret scanning pattern configuration. Typed override arrays preserve reported alert totals, false positives and integer percentage rates with default, enterprise and organization settings. Rounded percentages are not summed or averaged as exact rates. Reported configuration alert totals are not interchangeable with a retrieved alert population.

Grain: `organization_id`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `secret_scanning_pattern_configurations__organizations` | `organization` | Current organization pattern configuration, with provider and custom override collections retained separately. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `organization_id` | `BIGINT` | no |
| `organization_login` | `VARCHAR` | no |
| `pattern_config_version` | `VARCHAR` | yes |
| `provider_pattern_overrides` | `STRUCT("alert_total" BIGINT, "alert_total_percentage" BIGINT, "bypass_rate" BIGINT, "custom_pattern_version" VARCHAR, "default_setting" VARCHAR, "display_name" VARCHAR, "enterprise_setting" VARCHAR, "false_positive_rate" BIGINT, "false_positives" BIGINT, "setting" VARCHAR, "slug" VARCHAR, "token_type" VARCHAR)[]` | yes |
| `custom_pattern_overrides` | `STRUCT("alert_total" BIGINT, "alert_total_percentage" BIGINT, "bypass_rate" BIGINT, "custom_pattern_version" VARCHAR, "default_setting" VARCHAR, "display_name" VARCHAR, "enterprise_setting" VARCHAR, "false_positive_rate" BIGINT, "false_positives" BIGINT, "setting" VARCHAR, "slug" VARCHAR, "token_type" VARCHAR)[]` | yes |

Approved metrics:

- `secret_scanning_pattern_configuration_count`: Selected organization configuration snapshots, not patterns, executions or alerts.

### `pull_request_review_comments`

One canonical review comment by repository ID and comment ID across repository lists, PR lists, review lists and direct lookup. Direct/repository responses supply a PR URL but no numeric PR key, so pull_request_number remains NULL there; no parent is invented from URL text. Review IDs and parent comment IDs can be absent. Direct repository and comment-author context are analytical; PR/review/reply parent associations retain navigation without competing analytical paths.

Grain: `repository_id`, `review_comment_id`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `pull_request_review_comments__lookup` | `review_comment_id` | Visible selected records at declared identity; every advertised collection page is exhausted and inaccessible or incomplete populations fail. |
| `pull_request_review_comments__reviews` | `review_id` | Visible selected records at declared identity; every advertised collection page is exhausted and inaccessible or incomplete populations fail. |
| `pull_request_review_comments__pull_requests` | `pull_request_number` | Visible selected records at declared identity; every advertised collection page is exhausted and inaccessible or incomplete populations fail. |
| `pull_request_review_comments__repositories` | `owner`, `repository`, `organization`, `repositories` | Visible selected records at declared identity; every advertised collection page is exhausted and inaccessible or incomplete populations fail. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `repository_id` | `BIGINT` | no |
| `repository` | `VARCHAR` | no |
| `pull_request_number` | `BIGINT` | yes |
| `review_comment_id` | `BIGINT` | no |
| `review_comment_node_id` | `VARCHAR` | no |
| `review_id` | `BIGINT` | yes |
| `body` | `VARCHAR` | no |
| `path` | `VARCHAR` | no |
| `diff_hunk` | `VARCHAR` | no |
| `position` | `BIGINT` | yes |
| `original_position` | `BIGINT` | yes |
| `commit_id` | `VARCHAR` | no |
| `original_commit_id` | `VARCHAR` | no |
| `in_reply_to_id` | `BIGINT` | yes |
| `created_at` | `TIMESTAMP WITH TIME ZONE` | no |
| `updated_at` | `TIMESTAMP WITH TIME ZONE` | no |
| `html_url` | `VARCHAR` | no |
| `pull_request_url` | `VARCHAR` | no |
| `author_association` | `VARCHAR` | no |
| `line` | `BIGINT` | yes |
| `original_line` | `BIGINT` | yes |
| `start_line` | `BIGINT` | yes |
| `original_start_line` | `BIGINT` | yes |
| `side` | `VARCHAR` | yes |
| `start_side` | `VARCHAR` | yes |
| `subject_type` | `VARCHAR` | yes |
| `comment_author_id` | `BIGINT` | yes |
| `comment_author_login` | `VARCHAR` | yes |
| `review_comment_created_day` | `DATE` | no |

Approved metrics:

- `pull_request_review_comment_count`: Visible diff review comments, separate from issue conversation comments.

### `pull_request_files`

Current net changed paths per pull request, distinct from commit-file changes. Filename is scoped by repository and PR; rename retains previous_filename and a missing binary/large-file patch stays NULL. All pages must match the hydrated changed_files count, so the API 3000-file cap or concurrent population changes fail qualification instead of returning complete-looking partial totals.

Grain: `repository_id`, `pull_request_number`, `filename`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `pull_request_files__pull_requests` | `pull_request_number` | Visible selected records at declared identity; every advertised collection page is exhausted and inaccessible or incomplete populations fail. |
| `pull_request_files__repositories` | `owner`, `repository`, `organization`, `repositories` | Visible selected records at declared identity; every advertised collection page is exhausted and inaccessible or incomplete populations fail. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `repository_id` | `BIGINT` | no |
| `repository` | `VARCHAR` | no |
| `pull_request_number` | `BIGINT` | no |
| `blob_sha` | `VARCHAR` | yes |
| `filename` | `VARCHAR` | no |
| `status` | `VARCHAR` | no |
| `additions` | `BIGINT` | no |
| `deletions` | `BIGINT` | no |
| `changes` | `BIGINT` | no |
| `blob_url` | `VARCHAR` | no |
| `raw_url` | `VARCHAR` | no |
| `contents_url` | `VARCHAR` | no |
| `patch` | `VARCHAR` | yes |
| `previous_filename` | `VARCHAR` | yes |

Approved metrics:

- `pull_request_file_count`: Net changed file paths across selected pull requests.
- `pull_request_file_additions`: Added lines in current PR file diffs.
- `pull_request_file_deletions`: Deleted lines in current PR file diffs.
- `pull_request_file_changes`: Total reported changed lines, not distinct repository lines across PRs.

### `pull_request_review_requests`

One current requested-reviewer population per pull request, with typed user and team memberships. Submitted reviewers disappear from this endpoint; these are outstanding requests, not review history or request event timestamps. Empty arrays preserve the selected PR with zero outstanding users and teams.

Grain: `repository_id`, `pull_request_number`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `pull_request_review_requests__pull_requests` | `pull_request_number` | Visible selected records at declared identity; every advertised collection page is exhausted and inaccessible or incomplete populations fail. |
| `pull_request_review_requests__repositories` | `owner`, `repository`, `organization`, `repositories` | Visible selected records at declared identity; every advertised collection page is exhausted and inaccessible or incomplete populations fail. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `repository_id` | `BIGINT` | no |
| `repository` | `VARCHAR` | no |
| `pull_request_number` | `BIGINT` | no |
| `requested_users` | `STRUCT("id" BIGINT, "login" VARCHAR, "type" VARCHAR)[]` | no |
| `requested_teams` | `STRUCT("id" BIGINT, "name" VARCHAR, "slug" VARCHAR, "node_id" VARCHAR, "description" VARCHAR, "privacy" VARCHAR, "notification_setting" VARCHAR, "html_url" VARCHAR)[]` | no |

Approved metrics:

- `review_request_population_count`: Selected per-PR current reviewer-request populations, including empty lists.
- `requested_user_review_count`: Outstanding PR/user review-request memberships.
- `requested_team_review_count`: Outstanding PR/team review-request memberships; teams are not individual reviewer accounts.

### `pull_request_merge_statuses`

Merge-check observations after confirming the selected PR is visible. GitHub declares HTTP 204 as merged and 404 as not merged for this endpoint; other failures are not converted to false. This is a current predicate observation, not a merge event history or asynchronous queue outcome.

Grain: `repository_id`, `pull_request_number`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `pull_request_merge_statuses__pull_requests` | `pull_request_number` | Visible selected records at declared identity; every advertised collection page is exhausted and inaccessible or incomplete populations fail. |
| `pull_request_merge_statuses__repositories` | `owner`, `repository`, `organization`, `repositories` | Visible selected records at declared identity; every advertised collection page is exhausted and inaccessible or incomplete populations fail. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `repository_id` | `BIGINT` | no |
| `repository` | `VARCHAR` | no |
| `pull_request_number` | `BIGINT` | no |
| `status_code` | `BIGINT` | no |

Approved metrics:

- `pull_request_merge_check_count`: Visible-PR merge predicate observations.
- `merged_pull_request_check_count`: Merge-check observations with the declared merged HTTP response.
- `unmerged_pull_request_check_count`: Merge-check observations with the declared not-merged HTTP response.

### `pull_request_merge_results`

Status of an externally supplied asynchronous merge request UUID, retained by GitHub for only 24 hours after its most recent update. Retrieval never performs a merge. Enqueued is a final queue-request result and does not imply eventual merge; pending, failed and merged remain distinct. Nullable detail fields preserve the API variant rather than inventing merge SHAs.

Grain: `repository_id`, `pull_request_number`, `merge_request_uuid`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `pull_request_merge_results__lookup` | `merge_request_uuid` | Visible selected records at declared identity; every advertised collection page is exhausted and inaccessible or incomplete populations fail. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `repository_id` | `BIGINT` | no |
| `repository` | `VARCHAR` | no |
| `pull_request_number` | `BIGINT` | no |
| `merge_request_uuid` | `VARCHAR` | no |
| `merge_status` | `VARCHAR` | no |
| `message` | `VARCHAR` | no |
| `reported_uuid` | `VARCHAR` | yes |
| `merge_method` | `VARCHAR` | yes |
| `merge_action` | `VARCHAR` | yes |
| `expected_head_sha` | `VARCHAR` | yes |
| `bypass_rules` | `BOOLEAN` | yes |
| `merge_commit_sha` | `VARCHAR` | yes |

Approved metrics:

- `pull_request_merge_result_count`: Selected asynchronous request result records.
- `successful_async_merge_count`: Asynchronous results explicitly reporting merged.
- `enqueued_async_merge_count`: Asynchronous results finalized as enqueued; not successful merges.

### `pull_request_stacks`

GHEC-documented pull request stacks at repository ID and stable stack ID, unified across list, stack-number lookup and containing-PR filter. Listing discovers stack numbers and hydrates full stack detail, preserving ordered PR members and head refs/SHAs. Stack openness means any member PR is open; no reviewer or merge eligibility inference is made.

Grain: `repository_id`, `stack_id`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `pull_request_stacks__lookup` | `stack_number` | Visible selected records at declared identity; every advertised collection page is exhausted and inaccessible or incomplete populations fail. |
| `pull_request_stacks__pull_requests` | `pull_request_number` | Visible selected records at declared identity; every advertised collection page is exhausted and inaccessible or incomplete populations fail. |
| `pull_request_stacks__repositories` | `owner`, `repository`, `organization`, `repositories` | Visible selected records at declared identity; every advertised collection page is exhausted and inaccessible or incomplete populations fail. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `repository_id` | `BIGINT` | no |
| `repository` | `VARCHAR` | no |
| `stack_id` | `BIGINT` | no |
| `stack_number` | `BIGINT` | no |
| `stack_node_id` | `VARCHAR` | no |
| `url` | `VARCHAR` | no |
| `base_ref` | `VARCHAR` | no |
| `open` | `BOOLEAN` | no |
| `created_at` | `TIMESTAMP WITH TIME ZONE` | no |
| `pull_requests` | `STRUCT("number" BIGINT, "node_id" VARCHAR, "title" VARCHAR, "state" VARCHAR, "draft" BOOLEAN, "merged_at" TIMESTAMP WITH TIME ZONE, "html_url" VARCHAR, "user" STRUCT("id" BIGINT, "login" VARCHAR), "head" STRUCT("ref" VARCHAR, "sha" VARCHAR, "repo" STRUCT("id" BIGINT, "name" VARCHAR, "url" VARCHAR)))[]` | no |
| `pull_request_stack_created_day` | `DATE` | no |

Approved metrics:

- `pull_request_stack_count`: Selected distinct stack resources.
- `open_pull_request_stack_count`: Stacks explicitly containing an open PR.
- `stack_pull_request_membership_count`: Ordered stack/PR memberships in selected stacks, not a count of all repository PRs.

### `issue_events`

Issue lifecycle event identities shared across direct and reverse retrieval. Per-issue polymorphic summaries hydrate through get-event, keeping consistent typed event details. Events may describe PRs because the underlying Issues event API includes them; this is explicitly not a count of standalone issues.

Grain: `repository_id`, `event_id`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `issue_events__lookup` | `issue_event_id` | Visible records at the stated grain, with all advertised collection pages exhausted. Missing permissions fail rather than silently return a partial population. |
| `issue_events__issues` | `issue_number` | Visible records at the stated grain, with all advertised collection pages exhausted. Missing permissions fail rather than silently return a partial population. |
| `issue_events__repositories` | `owner`, `repository`, `organization`, `repositories` | Visible records at the stated grain, with all advertised collection pages exhausted. Missing permissions fail rather than silently return a partial population. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `repository_id` | `BIGINT` | no |
| `repository` | `VARCHAR` | no |
| `event_id` | `BIGINT` | no |
| `event_node_id` | `VARCHAR` | no |
| `event` | `VARCHAR` | no |
| `url` | `VARCHAR` | no |
| `commit_id` | `VARCHAR` | yes |
| `commit_url` | `VARCHAR` | yes |
| `created_at` | `TIMESTAMP WITH TIME ZONE` | no |
| `author_association` | `VARCHAR` | yes |
| `lock_reason` | `VARCHAR` | yes |
| `issue` | `STRUCT("id" BIGINT, "node_id" VARCHAR, "number" BIGINT, "url" VARCHAR, "html_url" VARCHAR, "repository_url" VARCHAR)` | yes |
| `issue_node_id` | `VARCHAR` | yes |
| `issue_number` | `BIGINT` | yes |
| `actor_id` | `BIGINT` | yes |
| `actor_login` | `VARCHAR` | yes |
| `assignee_id` | `BIGINT` | yes |
| `assignee_login` | `VARCHAR` | yes |
| `assigner_id` | `BIGINT` | yes |
| `assigner_login` | `VARCHAR` | yes |
| `review_requester_id` | `BIGINT` | yes |
| `review_requester_login` | `VARCHAR` | yes |
| `requested_reviewer_id` | `BIGINT` | yes |
| `requested_reviewer_login` | `VARCHAR` | yes |
| `label` | `STRUCT("color" VARCHAR, "name" VARCHAR)` | yes |
| `dismissed_review` | `STRUCT("dismissal_commit_id" VARCHAR, "dismissal_message" VARCHAR, "review_id" BIGINT, "state" VARCHAR)` | yes |
| `milestone` | `STRUCT("title" VARCHAR)` | yes |
| `project_card` | `STRUCT("column_name" VARCHAR, "id" BIGINT, "previous_column_name" VARCHAR, "project_id" BIGINT, "project_url" VARCHAR, "url" VARCHAR)` | yes |
| `rename` | `STRUCT("from" VARCHAR, "to" VARCHAR)` | yes |
| `issue_type` | `STRUCT("color" VARCHAR, "id" BIGINT, "name" VARCHAR)` | yes |
| `prev_issue_type` | `STRUCT("color" VARCHAR, "id" BIGINT, "name" VARCHAR)` | yes |
| `sub_issue` | `STRUCT("issue_type" STRUCT("color" VARCHAR, "id" BIGINT, "name" VARCHAR, "node_id" VARCHAR), "number" BIGINT, "repository" STRUCT("archive_url" VARCHAR, "assignees_url" VARCHAR, "blobs_url" VARCHAR, "branches_url" VARCHAR, "collaborators_url" VARCHAR, "comments_url" VARCHAR, "commits_url" VARCHAR, "compare_url" VARCHAR, "contents_url" VARCHAR, "contributors_url" VARCHAR, "deployments_url" VARCHAR, "description" VARCHAR, "downloads_url" VARCHAR, "events_url" VARCHAR, "fork" BOOLEAN, "forks_url" VARCHAR, "full_name" VARCHAR, "git_commits_url" VARCHAR, "git_refs_url" VARCHAR, "git_tags_url" VARCHAR, "hooks_url" VARCHAR, "html_url" VARCHAR, "id" BIGINT, "issue_comment_url" VARCHAR, "issue_events_url" VARCHAR, "issues_url" VARCHAR, "keys_url" VARCHAR, "labels_url" VARCHAR, "languages_url" VARCHAR, "merges_url" VARCHAR, "milestones_url" VARCHAR, "name" VARCHAR, "node_id" VARCHAR, "notifications_url" VARCHAR, "owner" STRUCT("avatar_url" VARCHAR, "email" VARCHAR, "events_url" VARCHAR, "followers_url" VARCHAR, "following_url" VARCHAR, "gists_url" VARCHAR, "gravatar_id" VARCHAR, "html_url" VARCHAR, "id" BIGINT, "login" VARCHAR, "name" VARCHAR, "node_id" VARCHAR, "organizations_url" VARCHAR, "received_events_url" VARCHAR, "repos_url" VARCHAR, "site_admin" BOOLEAN, "starred_at" VARCHAR, "starred_url" VARCHAR, "subscriptions_url" VARCHAR, "type" VARCHAR, "url" VARCHAR, "user_view_type" VARCHAR), "private" BOOLEAN, "pulls_url" VARCHAR, "releases_url" VARCHAR, "stargazers_url" VARCHAR, "statuses_url" VARCHAR, "subscribers_url" VARCHAR, "subscription_url" VARCHAR, "tags_url" VARCHAR, "teams_url" VARCHAR, "trees_url" VARCHAR, "url" VARCHAR), "state" VARCHAR, "state_reason" VARCHAR, "title" VARCHAR)` | yes |
| `parent_issue` | `STRUCT("issue_type" STRUCT("color" VARCHAR, "id" BIGINT, "name" VARCHAR, "node_id" VARCHAR), "number" BIGINT, "repository" STRUCT("archive_url" VARCHAR, "assignees_url" VARCHAR, "blobs_url" VARCHAR, "branches_url" VARCHAR, "collaborators_url" VARCHAR, "comments_url" VARCHAR, "commits_url" VARCHAR, "compare_url" VARCHAR, "contents_url" VARCHAR, "contributors_url" VARCHAR, "deployments_url" VARCHAR, "description" VARCHAR, "downloads_url" VARCHAR, "events_url" VARCHAR, "fork" BOOLEAN, "forks_url" VARCHAR, "full_name" VARCHAR, "git_commits_url" VARCHAR, "git_refs_url" VARCHAR, "git_tags_url" VARCHAR, "hooks_url" VARCHAR, "html_url" VARCHAR, "id" BIGINT, "issue_comment_url" VARCHAR, "issue_events_url" VARCHAR, "issues_url" VARCHAR, "keys_url" VARCHAR, "labels_url" VARCHAR, "languages_url" VARCHAR, "merges_url" VARCHAR, "milestones_url" VARCHAR, "name" VARCHAR, "node_id" VARCHAR, "notifications_url" VARCHAR, "owner" STRUCT("avatar_url" VARCHAR, "email" VARCHAR, "events_url" VARCHAR, "followers_url" VARCHAR, "following_url" VARCHAR, "gists_url" VARCHAR, "gravatar_id" VARCHAR, "html_url" VARCHAR, "id" BIGINT, "login" VARCHAR, "name" VARCHAR, "node_id" VARCHAR, "organizations_url" VARCHAR, "received_events_url" VARCHAR, "repos_url" VARCHAR, "site_admin" BOOLEAN, "starred_at" VARCHAR, "starred_url" VARCHAR, "subscriptions_url" VARCHAR, "type" VARCHAR, "url" VARCHAR, "user_view_type" VARCHAR), "private" BOOLEAN, "pulls_url" VARCHAR, "releases_url" VARCHAR, "stargazers_url" VARCHAR, "statuses_url" VARCHAR, "subscribers_url" VARCHAR, "subscription_url" VARCHAR, "tags_url" VARCHAR, "teams_url" VARCHAR, "trees_url" VARCHAR, "url" VARCHAR), "state" VARCHAR, "state_reason" VARCHAR, "title" VARCHAR)` | yes |
| `blocked_by` | `STRUCT("issue_type" STRUCT("color" VARCHAR, "id" BIGINT, "name" VARCHAR, "node_id" VARCHAR), "number" BIGINT, "repository" STRUCT("archive_url" VARCHAR, "assignees_url" VARCHAR, "blobs_url" VARCHAR, "branches_url" VARCHAR, "collaborators_url" VARCHAR, "comments_url" VARCHAR, "commits_url" VARCHAR, "compare_url" VARCHAR, "contents_url" VARCHAR, "contributors_url" VARCHAR, "deployments_url" VARCHAR, "description" VARCHAR, "downloads_url" VARCHAR, "events_url" VARCHAR, "fork" BOOLEAN, "forks_url" VARCHAR, "full_name" VARCHAR, "git_commits_url" VARCHAR, "git_refs_url" VARCHAR, "git_tags_url" VARCHAR, "hooks_url" VARCHAR, "html_url" VARCHAR, "id" BIGINT, "issue_comment_url" VARCHAR, "issue_events_url" VARCHAR, "issues_url" VARCHAR, "keys_url" VARCHAR, "labels_url" VARCHAR, "languages_url" VARCHAR, "merges_url" VARCHAR, "milestones_url" VARCHAR, "name" VARCHAR, "node_id" VARCHAR, "notifications_url" VARCHAR, "owner" STRUCT("avatar_url" VARCHAR, "email" VARCHAR, "events_url" VARCHAR, "followers_url" VARCHAR, "following_url" VARCHAR, "gists_url" VARCHAR, "gravatar_id" VARCHAR, "html_url" VARCHAR, "id" BIGINT, "login" VARCHAR, "name" VARCHAR, "node_id" VARCHAR, "organizations_url" VARCHAR, "received_events_url" VARCHAR, "repos_url" VARCHAR, "site_admin" BOOLEAN, "starred_at" VARCHAR, "starred_url" VARCHAR, "subscriptions_url" VARCHAR, "type" VARCHAR, "url" VARCHAR, "user_view_type" VARCHAR), "private" BOOLEAN, "pulls_url" VARCHAR, "releases_url" VARCHAR, "stargazers_url" VARCHAR, "statuses_url" VARCHAR, "subscribers_url" VARCHAR, "subscription_url" VARCHAR, "tags_url" VARCHAR, "teams_url" VARCHAR, "trees_url" VARCHAR, "url" VARCHAR), "state" VARCHAR, "state_reason" VARCHAR, "title" VARCHAR)` | yes |
| `blocking` | `STRUCT("issue_type" STRUCT("color" VARCHAR, "id" BIGINT, "name" VARCHAR, "node_id" VARCHAR), "number" BIGINT, "repository" STRUCT("archive_url" VARCHAR, "assignees_url" VARCHAR, "blobs_url" VARCHAR, "branches_url" VARCHAR, "collaborators_url" VARCHAR, "comments_url" VARCHAR, "commits_url" VARCHAR, "compare_url" VARCHAR, "contents_url" VARCHAR, "contributors_url" VARCHAR, "deployments_url" VARCHAR, "description" VARCHAR, "downloads_url" VARCHAR, "events_url" VARCHAR, "fork" BOOLEAN, "forks_url" VARCHAR, "full_name" VARCHAR, "git_commits_url" VARCHAR, "git_refs_url" VARCHAR, "git_tags_url" VARCHAR, "hooks_url" VARCHAR, "html_url" VARCHAR, "id" BIGINT, "issue_comment_url" VARCHAR, "issue_events_url" VARCHAR, "issues_url" VARCHAR, "keys_url" VARCHAR, "labels_url" VARCHAR, "languages_url" VARCHAR, "merges_url" VARCHAR, "milestones_url" VARCHAR, "name" VARCHAR, "node_id" VARCHAR, "notifications_url" VARCHAR, "owner" STRUCT("avatar_url" VARCHAR, "email" VARCHAR, "events_url" VARCHAR, "followers_url" VARCHAR, "following_url" VARCHAR, "gists_url" VARCHAR, "gravatar_id" VARCHAR, "html_url" VARCHAR, "id" BIGINT, "login" VARCHAR, "name" VARCHAR, "node_id" VARCHAR, "organizations_url" VARCHAR, "received_events_url" VARCHAR, "repos_url" VARCHAR, "site_admin" BOOLEAN, "starred_at" VARCHAR, "starred_url" VARCHAR, "subscriptions_url" VARCHAR, "type" VARCHAR, "url" VARCHAR, "user_view_type" VARCHAR), "private" BOOLEAN, "pulls_url" VARCHAR, "releases_url" VARCHAR, "stargazers_url" VARCHAR, "statuses_url" VARCHAR, "subscribers_url" VARCHAR, "subscription_url" VARCHAR, "tags_url" VARCHAR, "teams_url" VARCHAR, "trees_url" VARCHAR, "url" VARCHAR), "state" VARCHAR, "state_reason" VARCHAR, "title" VARCHAR)` | yes |
| `intent` | `STRUCT("confidence" VARCHAR, "rationale" VARCHAR)` | yes |
| `requested_team` | `STRUCT("id" BIGINT, "node_id" VARCHAR, "name" VARCHAR, "slug" VARCHAR)` | yes |
| `performed_via_github_app` | `STRUCT("id" BIGINT, "node_id" VARCHAR, "slug" VARCHAR, "name" VARCHAR)` | yes |

Approved metrics:

- `issue_event_count`: Canonical issue event IDs across repository, issue-specific and exact routes; event actors are distinct from issue authors and assignment subjects.

### `issue_timeline_entries`

Complete selected issue/PR timeline stream with an explicitly discriminated typed payload for all 35 pinned alternatives. Some timeline records have no stable ID and some embed comment collections; a page-spanning ordinal identifies this retrieval observation only. Unknown event discriminators fail; no event is coerced into an unrelated branch. Typed event payload branches are separate nullable detail columns with one event_types discriminator, preserving all pinned variants without widening a single transport type beyond the native column limit.

Grain: `repository_id`, `issue_number`, `entry_ordinal`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `issue_timeline_entries__issues` | `issue_number` | Visible records at the stated grain, with all advertised collection pages exhausted. Missing permissions fail rather than silently return a partial population. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `repository_id` | `BIGINT` | no |
| `repository` | `VARCHAR` | no |
| `issue_number` | `BIGINT` | no |
| `entry_ordinal` | `BIGINT` | no |
| `event` | `VARCHAR` | yes |
| `event_id` | `BIGINT` | yes |
| `event_types` | `VARCHAR[]` | no |
| `labeled_payload` | `STRUCT("id" BIGINT, "node_id" VARCHAR, "url" VARCHAR, "actor" STRUCT("id" BIGINT, "node_id" VARCHAR, "login" VARCHAR, "type" VARCHAR), "event" VARCHAR, "commit_id" VARCHAR, "commit_url" VARCHAR, "created_at" VARCHAR, "performed_via_github_app" STRUCT("id" BIGINT, "slug" VARCHAR, "node_id" VARCHAR, "client_id" VARCHAR, "owner" STRUCT("matched_types" VARCHAR[], "variant_1" STRUCT("id" BIGINT, "node_id" VARCHAR, "login" VARCHAR, "type" VARCHAR), "variant_2" STRUCT("description" VARCHAR, "html_url" VARCHAR, "website_url" VARCHAR, "id" BIGINT, "node_id" VARCHAR, "name" VARCHAR, "slug" VARCHAR, "created_at" TIMESTAMP WITH TIME ZONE, "updated_at" TIMESTAMP WITH TIME ZONE, "avatar_url" VARCHAR)), "name" VARCHAR, "description" VARCHAR, "external_url" VARCHAR, "html_url" VARCHAR, "created_at" TIMESTAMP WITH TIME ZONE, "updated_at" TIMESTAMP WITH TIME ZONE, "permissions" STRUCT("issues" VARCHAR, "checks" VARCHAR, "metadata" VARCHAR, "contents" VARCHAR, "deployments" VARCHAR), "events" VARCHAR[], "installations_count" BIGINT), "label" STRUCT("name" VARCHAR, "color" VARCHAR), "intent" STRUCT("rationale" VARCHAR, "confidence" VARCHAR))` | yes |
| `unlabeled_payload` | `STRUCT("id" BIGINT, "node_id" VARCHAR, "url" VARCHAR, "actor" STRUCT("id" BIGINT, "node_id" VARCHAR, "login" VARCHAR, "type" VARCHAR), "event" VARCHAR, "commit_id" VARCHAR, "commit_url" VARCHAR, "created_at" VARCHAR, "performed_via_github_app" STRUCT("id" BIGINT, "slug" VARCHAR, "node_id" VARCHAR, "client_id" VARCHAR, "owner" STRUCT("matched_types" VARCHAR[], "variant_1" STRUCT("id" BIGINT, "node_id" VARCHAR, "login" VARCHAR, "type" VARCHAR), "variant_2" STRUCT("description" VARCHAR, "html_url" VARCHAR, "website_url" VARCHAR, "id" BIGINT, "node_id" VARCHAR, "name" VARCHAR, "slug" VARCHAR, "created_at" TIMESTAMP WITH TIME ZONE, "updated_at" TIMESTAMP WITH TIME ZONE, "avatar_url" VARCHAR)), "name" VARCHAR, "description" VARCHAR, "external_url" VARCHAR, "html_url" VARCHAR, "created_at" TIMESTAMP WITH TIME ZONE, "updated_at" TIMESTAMP WITH TIME ZONE, "permissions" STRUCT("issues" VARCHAR, "checks" VARCHAR, "metadata" VARCHAR, "contents" VARCHAR, "deployments" VARCHAR), "events" VARCHAR[], "installations_count" BIGINT), "label" STRUCT("name" VARCHAR, "color" VARCHAR), "intent" STRUCT("rationale" VARCHAR, "confidence" VARCHAR))` | yes |
| `milestoned_payload` | `STRUCT("id" BIGINT, "node_id" VARCHAR, "url" VARCHAR, "actor" STRUCT("id" BIGINT, "node_id" VARCHAR, "login" VARCHAR, "type" VARCHAR), "event" VARCHAR, "commit_id" VARCHAR, "commit_url" VARCHAR, "created_at" VARCHAR, "performed_via_github_app" STRUCT("id" BIGINT, "slug" VARCHAR, "node_id" VARCHAR, "client_id" VARCHAR, "owner" STRUCT("matched_types" VARCHAR[], "variant_1" STRUCT("id" BIGINT, "node_id" VARCHAR, "login" VARCHAR, "type" VARCHAR), "variant_2" STRUCT("description" VARCHAR, "html_url" VARCHAR, "website_url" VARCHAR, "id" BIGINT, "node_id" VARCHAR, "name" VARCHAR, "slug" VARCHAR, "created_at" TIMESTAMP WITH TIME ZONE, "updated_at" TIMESTAMP WITH TIME ZONE, "avatar_url" VARCHAR)), "name" VARCHAR, "description" VARCHAR, "external_url" VARCHAR, "html_url" VARCHAR, "created_at" TIMESTAMP WITH TIME ZONE, "updated_at" TIMESTAMP WITH TIME ZONE, "permissions" STRUCT("issues" VARCHAR, "checks" VARCHAR, "metadata" VARCHAR, "contents" VARCHAR, "deployments" VARCHAR), "events" VARCHAR[], "installations_count" BIGINT), "milestone" STRUCT("title" VARCHAR))` | yes |
| `demilestoned_payload` | `STRUCT("id" BIGINT, "node_id" VARCHAR, "url" VARCHAR, "actor" STRUCT("id" BIGINT, "node_id" VARCHAR, "login" VARCHAR, "type" VARCHAR), "event" VARCHAR, "commit_id" VARCHAR, "commit_url" VARCHAR, "created_at" VARCHAR, "performed_via_github_app" STRUCT("id" BIGINT, "slug" VARCHAR, "node_id" VARCHAR, "client_id" VARCHAR, "owner" STRUCT("matched_types" VARCHAR[], "variant_1" STRUCT("id" BIGINT, "node_id" VARCHAR, "login" VARCHAR, "type" VARCHAR), "variant_2" STRUCT("description" VARCHAR, "html_url" VARCHAR, "website_url" VARCHAR, "id" BIGINT, "node_id" VARCHAR, "name" VARCHAR, "slug" VARCHAR, "created_at" TIMESTAMP WITH TIME ZONE, "updated_at" TIMESTAMP WITH TIME ZONE, "avatar_url" VARCHAR)), "name" VARCHAR, "description" VARCHAR, "external_url" VARCHAR, "html_url" VARCHAR, "created_at" TIMESTAMP WITH TIME ZONE, "updated_at" TIMESTAMP WITH TIME ZONE, "permissions" STRUCT("issues" VARCHAR, "checks" VARCHAR, "metadata" VARCHAR, "contents" VARCHAR, "deployments" VARCHAR), "events" VARCHAR[], "installations_count" BIGINT), "milestone" STRUCT("title" VARCHAR))` | yes |
| `renamed_payload` | `STRUCT("id" BIGINT, "node_id" VARCHAR, "url" VARCHAR, "actor" STRUCT("id" BIGINT, "node_id" VARCHAR, "login" VARCHAR, "type" VARCHAR), "event" VARCHAR, "commit_id" VARCHAR, "commit_url" VARCHAR, "created_at" VARCHAR, "performed_via_github_app" STRUCT("id" BIGINT, "slug" VARCHAR, "node_id" VARCHAR, "client_id" VARCHAR, "owner" STRUCT("matched_types" VARCHAR[], "variant_1" STRUCT("id" BIGINT, "node_id" VARCHAR, "login" VARCHAR, "type" VARCHAR), "variant_2" STRUCT("description" VARCHAR, "html_url" VARCHAR, "website_url" VARCHAR, "id" BIGINT, "node_id" VARCHAR, "name" VARCHAR, "slug" VARCHAR, "created_at" TIMESTAMP WITH TIME ZONE, "updated_at" TIMESTAMP WITH TIME ZONE, "avatar_url" VARCHAR)), "name" VARCHAR, "description" VARCHAR, "external_url" VARCHAR, "html_url" VARCHAR, "created_at" TIMESTAMP WITH TIME ZONE, "updated_at" TIMESTAMP WITH TIME ZONE, "permissions" STRUCT("issues" VARCHAR, "checks" VARCHAR, "metadata" VARCHAR, "contents" VARCHAR, "deployments" VARCHAR), "events" VARCHAR[], "installations_count" BIGINT), "rename" STRUCT("from" VARCHAR, "to" VARCHAR))` | yes |
| `review_requested_payload` | `STRUCT("id" BIGINT, "node_id" VARCHAR, "url" VARCHAR, "actor" STRUCT("id" BIGINT, "node_id" VARCHAR, "login" VARCHAR, "type" VARCHAR), "event" VARCHAR, "commit_id" VARCHAR, "commit_url" VARCHAR, "created_at" VARCHAR, "performed_via_github_app" STRUCT("id" BIGINT, "slug" VARCHAR, "node_id" VARCHAR, "client_id" VARCHAR, "owner" STRUCT("matched_types" VARCHAR[], "variant_1" STRUCT("id" BIGINT, "node_id" VARCHAR, "login" VARCHAR, "type" VARCHAR), "variant_2" STRUCT("description" VARCHAR, "html_url" VARCHAR, "website_url" VARCHAR, "id" BIGINT, "node_id" VARCHAR, "name" VARCHAR, "slug" VARCHAR, "created_at" TIMESTAMP WITH TIME ZONE, "updated_at" TIMESTAMP WITH TIME ZONE, "avatar_url" VARCHAR)), "name" VARCHAR, "description" VARCHAR, "external_url" VARCHAR, "html_url" VARCHAR, "created_at" TIMESTAMP WITH TIME ZONE, "updated_at" TIMESTAMP WITH TIME ZONE, "permissions" STRUCT("issues" VARCHAR, "checks" VARCHAR, "metadata" VARCHAR, "contents" VARCHAR, "deployments" VARCHAR), "events" VARCHAR[], "installations_count" BIGINT), "review_requester" STRUCT("id" BIGINT, "node_id" VARCHAR, "login" VARCHAR, "type" VARCHAR), "requested_team" STRUCT("id" BIGINT, "node_id" VARCHAR, "name" VARCHAR, "slug" VARCHAR, "description" VARCHAR, "privacy" VARCHAR, "notification_setting" VARCHAR, "permission" VARCHAR, "permissions" STRUCT("pull" BOOLEAN, "triage" BOOLEAN, "push" BOOLEAN, "maintain" BOOLEAN, "admin" BOOLEAN), "url" VARCHAR, "html_url" VARCHAR, "members_url" VARCHAR, "repositories_url" VARCHAR, "type" VARCHAR, "access_source" VARCHAR, "organization_id" BIGINT, "enterprise_id" BIGINT, "parent" STRUCT("id" BIGINT, "node_id" VARCHAR, "url" VARCHAR, "members_url" VARCHAR, "name" VARCHAR, "description" VARCHAR, "permission" VARCHAR, "privacy" VARCHAR, "notification_setting" VARCHAR, "html_url" VARCHAR, "repositories_url" VARCHAR, "slug" VARCHAR, "ldap_dn" VARCHAR, "type" VARCHAR, "organization_id" BIGINT, "enterprise_id" BIGINT)), "requested_reviewer" STRUCT("id" BIGINT, "node_id" VARCHAR, "login" VARCHAR, "type" VARCHAR))` | yes |
| `review_request_removed_payload` | `STRUCT("id" BIGINT, "node_id" VARCHAR, "url" VARCHAR, "actor" STRUCT("id" BIGINT, "node_id" VARCHAR, "login" VARCHAR, "type" VARCHAR), "event" VARCHAR, "commit_id" VARCHAR, "commit_url" VARCHAR, "created_at" VARCHAR, "performed_via_github_app" STRUCT("id" BIGINT, "slug" VARCHAR, "node_id" VARCHAR, "client_id" VARCHAR, "owner" STRUCT("matched_types" VARCHAR[], "variant_1" STRUCT("id" BIGINT, "node_id" VARCHAR, "login" VARCHAR, "type" VARCHAR), "variant_2" STRUCT("description" VARCHAR, "html_url" VARCHAR, "website_url" VARCHAR, "id" BIGINT, "node_id" VARCHAR, "name" VARCHAR, "slug" VARCHAR, "created_at" TIMESTAMP WITH TIME ZONE, "updated_at" TIMESTAMP WITH TIME ZONE, "avatar_url" VARCHAR)), "name" VARCHAR, "description" VARCHAR, "external_url" VARCHAR, "html_url" VARCHAR, "created_at" TIMESTAMP WITH TIME ZONE, "updated_at" TIMESTAMP WITH TIME ZONE, "permissions" STRUCT("issues" VARCHAR, "checks" VARCHAR, "metadata" VARCHAR, "contents" VARCHAR, "deployments" VARCHAR), "events" VARCHAR[], "installations_count" BIGINT), "review_requester" STRUCT("id" BIGINT, "node_id" VARCHAR, "login" VARCHAR, "type" VARCHAR), "requested_team" STRUCT("id" BIGINT, "node_id" VARCHAR, "name" VARCHAR, "slug" VARCHAR, "description" VARCHAR, "privacy" VARCHAR, "notification_setting" VARCHAR, "permission" VARCHAR, "permissions" STRUCT("pull" BOOLEAN, "triage" BOOLEAN, "push" BOOLEAN, "maintain" BOOLEAN, "admin" BOOLEAN), "url" VARCHAR, "html_url" VARCHAR, "members_url" VARCHAR, "repositories_url" VARCHAR, "type" VARCHAR, "access_source" VARCHAR, "organization_id" BIGINT, "enterprise_id" BIGINT, "parent" STRUCT("id" BIGINT, "node_id" VARCHAR, "url" VARCHAR, "members_url" VARCHAR, "name" VARCHAR, "description" VARCHAR, "permission" VARCHAR, "privacy" VARCHAR, "notification_setting" VARCHAR, "html_url" VARCHAR, "repositories_url" VARCHAR, "slug" VARCHAR, "ldap_dn" VARCHAR, "type" VARCHAR, "organization_id" BIGINT, "enterprise_id" BIGINT)), "requested_reviewer" STRUCT("id" BIGINT, "node_id" VARCHAR, "login" VARCHAR, "type" VARCHAR))` | yes |
| `review_dismissed_payload` | `STRUCT("id" BIGINT, "node_id" VARCHAR, "url" VARCHAR, "actor" STRUCT("id" BIGINT, "node_id" VARCHAR, "login" VARCHAR, "type" VARCHAR), "event" VARCHAR, "commit_id" VARCHAR, "commit_url" VARCHAR, "created_at" VARCHAR, "performed_via_github_app" STRUCT("id" BIGINT, "slug" VARCHAR, "node_id" VARCHAR, "client_id" VARCHAR, "owner" STRUCT("matched_types" VARCHAR[], "variant_1" STRUCT("id" BIGINT, "node_id" VARCHAR, "login" VARCHAR, "type" VARCHAR), "variant_2" STRUCT("description" VARCHAR, "html_url" VARCHAR, "website_url" VARCHAR, "id" BIGINT, "node_id" VARCHAR, "name" VARCHAR, "slug" VARCHAR, "created_at" TIMESTAMP WITH TIME ZONE, "updated_at" TIMESTAMP WITH TIME ZONE, "avatar_url" VARCHAR)), "name" VARCHAR, "description" VARCHAR, "external_url" VARCHAR, "html_url" VARCHAR, "created_at" TIMESTAMP WITH TIME ZONE, "updated_at" TIMESTAMP WITH TIME ZONE, "permissions" STRUCT("issues" VARCHAR, "checks" VARCHAR, "metadata" VARCHAR, "contents" VARCHAR, "deployments" VARCHAR), "events" VARCHAR[], "installations_count" BIGINT), "dismissed_review" STRUCT("state" VARCHAR, "review_id" BIGINT, "dismissal_message" VARCHAR, "dismissal_commit_id" VARCHAR))` | yes |
| `locked_payload` | `STRUCT("id" BIGINT, "node_id" VARCHAR, "url" VARCHAR, "actor" STRUCT("id" BIGINT, "node_id" VARCHAR, "login" VARCHAR, "type" VARCHAR), "event" VARCHAR, "commit_id" VARCHAR, "commit_url" VARCHAR, "created_at" VARCHAR, "performed_via_github_app" STRUCT("id" BIGINT, "slug" VARCHAR, "node_id" VARCHAR, "client_id" VARCHAR, "owner" STRUCT("matched_types" VARCHAR[], "variant_1" STRUCT("id" BIGINT, "node_id" VARCHAR, "login" VARCHAR, "type" VARCHAR), "variant_2" STRUCT("description" VARCHAR, "html_url" VARCHAR, "website_url" VARCHAR, "id" BIGINT, "node_id" VARCHAR, "name" VARCHAR, "slug" VARCHAR, "created_at" TIMESTAMP WITH TIME ZONE, "updated_at" TIMESTAMP WITH TIME ZONE, "avatar_url" VARCHAR)), "name" VARCHAR, "description" VARCHAR, "external_url" VARCHAR, "html_url" VARCHAR, "created_at" TIMESTAMP WITH TIME ZONE, "updated_at" TIMESTAMP WITH TIME ZONE, "permissions" STRUCT("issues" VARCHAR, "checks" VARCHAR, "metadata" VARCHAR, "contents" VARCHAR, "deployments" VARCHAR), "events" VARCHAR[], "installations_count" BIGINT), "lock_reason" VARCHAR)` | yes |
| `added_to_project_payload` | `STRUCT("id" BIGINT, "node_id" VARCHAR, "url" VARCHAR, "actor" STRUCT("id" BIGINT, "node_id" VARCHAR, "login" VARCHAR, "type" VARCHAR), "event" VARCHAR, "commit_id" VARCHAR, "commit_url" VARCHAR, "created_at" VARCHAR, "performed_via_github_app" STRUCT("id" BIGINT, "slug" VARCHAR, "node_id" VARCHAR, "client_id" VARCHAR, "owner" STRUCT("matched_types" VARCHAR[], "variant_1" STRUCT("id" BIGINT, "node_id" VARCHAR, "login" VARCHAR, "type" VARCHAR), "variant_2" STRUCT("description" VARCHAR, "html_url" VARCHAR, "website_url" VARCHAR, "id" BIGINT, "node_id" VARCHAR, "name" VARCHAR, "slug" VARCHAR, "created_at" TIMESTAMP WITH TIME ZONE, "updated_at" TIMESTAMP WITH TIME ZONE, "avatar_url" VARCHAR)), "name" VARCHAR, "description" VARCHAR, "external_url" VARCHAR, "html_url" VARCHAR, "created_at" TIMESTAMP WITH TIME ZONE, "updated_at" TIMESTAMP WITH TIME ZONE, "permissions" STRUCT("issues" VARCHAR, "checks" VARCHAR, "metadata" VARCHAR, "contents" VARCHAR, "deployments" VARCHAR), "events" VARCHAR[], "installations_count" BIGINT), "project_card" STRUCT("id" BIGINT, "url" VARCHAR, "project_id" BIGINT, "project_url" VARCHAR, "column_name" VARCHAR, "previous_column_name" VARCHAR))` | yes |
| `moved_columns_in_project_payload` | `STRUCT("id" BIGINT, "node_id" VARCHAR, "url" VARCHAR, "actor" STRUCT("id" BIGINT, "node_id" VARCHAR, "login" VARCHAR, "type" VARCHAR), "event" VARCHAR, "commit_id" VARCHAR, "commit_url" VARCHAR, "created_at" VARCHAR, "performed_via_github_app" STRUCT("id" BIGINT, "slug" VARCHAR, "node_id" VARCHAR, "client_id" VARCHAR, "owner" STRUCT("matched_types" VARCHAR[], "variant_1" STRUCT("id" BIGINT, "node_id" VARCHAR, "login" VARCHAR, "type" VARCHAR), "variant_2" STRUCT("description" VARCHAR, "html_url" VARCHAR, "website_url" VARCHAR, "id" BIGINT, "node_id" VARCHAR, "name" VARCHAR, "slug" VARCHAR, "created_at" TIMESTAMP WITH TIME ZONE, "updated_at" TIMESTAMP WITH TIME ZONE, "avatar_url" VARCHAR)), "name" VARCHAR, "description" VARCHAR, "external_url" VARCHAR, "html_url" VARCHAR, "created_at" TIMESTAMP WITH TIME ZONE, "updated_at" TIMESTAMP WITH TIME ZONE, "permissions" STRUCT("issues" VARCHAR, "checks" VARCHAR, "metadata" VARCHAR, "contents" VARCHAR, "deployments" VARCHAR), "events" VARCHAR[], "installations_count" BIGINT), "project_card" STRUCT("id" BIGINT, "url" VARCHAR, "project_id" BIGINT, "project_url" VARCHAR, "column_name" VARCHAR, "previous_column_name" VARCHAR))` | yes |
| `removed_from_project_payload` | `STRUCT("id" BIGINT, "node_id" VARCHAR, "url" VARCHAR, "actor" STRUCT("id" BIGINT, "node_id" VARCHAR, "login" VARCHAR, "type" VARCHAR), "event" VARCHAR, "commit_id" VARCHAR, "commit_url" VARCHAR, "created_at" VARCHAR, "performed_via_github_app" STRUCT("id" BIGINT, "slug" VARCHAR, "node_id" VARCHAR, "client_id" VARCHAR, "owner" STRUCT("matched_types" VARCHAR[], "variant_1" STRUCT("id" BIGINT, "node_id" VARCHAR, "login" VARCHAR, "type" VARCHAR), "variant_2" STRUCT("description" VARCHAR, "html_url" VARCHAR, "website_url" VARCHAR, "id" BIGINT, "node_id" VARCHAR, "name" VARCHAR, "slug" VARCHAR, "created_at" TIMESTAMP WITH TIME ZONE, "updated_at" TIMESTAMP WITH TIME ZONE, "avatar_url" VARCHAR)), "name" VARCHAR, "description" VARCHAR, "external_url" VARCHAR, "html_url" VARCHAR, "created_at" TIMESTAMP WITH TIME ZONE, "updated_at" TIMESTAMP WITH TIME ZONE, "permissions" STRUCT("issues" VARCHAR, "checks" VARCHAR, "metadata" VARCHAR, "contents" VARCHAR, "deployments" VARCHAR), "events" VARCHAR[], "installations_count" BIGINT), "project_card" STRUCT("id" BIGINT, "url" VARCHAR, "project_id" BIGINT, "project_url" VARCHAR, "column_name" VARCHAR, "previous_column_name" VARCHAR))` | yes |
| `converted_note_to_issue_payload` | `STRUCT("id" BIGINT, "node_id" VARCHAR, "url" VARCHAR, "actor" STRUCT("id" BIGINT, "node_id" VARCHAR, "login" VARCHAR, "type" VARCHAR), "event" VARCHAR, "commit_id" VARCHAR, "commit_url" VARCHAR, "created_at" VARCHAR, "performed_via_github_app" STRUCT("id" BIGINT, "slug" VARCHAR, "node_id" VARCHAR, "client_id" VARCHAR, "owner" STRUCT("matched_types" VARCHAR[], "variant_1" STRUCT("id" BIGINT, "node_id" VARCHAR, "login" VARCHAR, "type" VARCHAR), "variant_2" STRUCT("description" VARCHAR, "html_url" VARCHAR, "website_url" VARCHAR, "id" BIGINT, "node_id" VARCHAR, "name" VARCHAR, "slug" VARCHAR, "created_at" TIMESTAMP WITH TIME ZONE, "updated_at" TIMESTAMP WITH TIME ZONE, "avatar_url" VARCHAR)), "name" VARCHAR, "description" VARCHAR, "external_url" VARCHAR, "html_url" VARCHAR, "created_at" TIMESTAMP WITH TIME ZONE, "updated_at" TIMESTAMP WITH TIME ZONE, "permissions" STRUCT("issues" VARCHAR, "checks" VARCHAR, "metadata" VARCHAR, "contents" VARCHAR, "deployments" VARCHAR), "events" VARCHAR[], "installations_count" BIGINT), "project_card" STRUCT("id" BIGINT, "url" VARCHAR, "project_id" BIGINT, "project_url" VARCHAR, "column_name" VARCHAR, "previous_column_name" VARCHAR))` | yes |
| `commented_payload` | `STRUCT("event" VARCHAR, "actor" STRUCT("id" BIGINT, "node_id" VARCHAR, "login" VARCHAR, "type" VARCHAR), "id" BIGINT, "node_id" VARCHAR, "url" VARCHAR, "body" VARCHAR, "body_text" VARCHAR, "body_html" VARCHAR, "html_url" VARCHAR, "user" STRUCT("id" BIGINT, "node_id" VARCHAR, "login" VARCHAR, "type" VARCHAR), "created_at" TIMESTAMP WITH TIME ZONE, "updated_at" TIMESTAMP WITH TIME ZONE, "issue_url" VARCHAR, "author_association" VARCHAR, "performed_via_github_app" STRUCT("id" BIGINT, "slug" VARCHAR, "node_id" VARCHAR, "client_id" VARCHAR, "owner" STRUCT("matched_types" VARCHAR[], "variant_1" STRUCT("id" BIGINT, "node_id" VARCHAR, "login" VARCHAR, "type" VARCHAR), "variant_2" STRUCT("description" VARCHAR, "html_url" VARCHAR, "website_url" VARCHAR, "id" BIGINT, "node_id" VARCHAR, "name" VARCHAR, "slug" VARCHAR, "created_at" TIMESTAMP WITH TIME ZONE, "updated_at" TIMESTAMP WITH TIME ZONE, "avatar_url" VARCHAR)), "name" VARCHAR, "description" VARCHAR, "external_url" VARCHAR, "html_url" VARCHAR, "created_at" TIMESTAMP WITH TIME ZONE, "updated_at" TIMESTAMP WITH TIME ZONE, "permissions" STRUCT("issues" VARCHAR, "checks" VARCHAR, "metadata" VARCHAR, "contents" VARCHAR, "deployments" VARCHAR), "events" VARCHAR[], "installations_count" BIGINT), "reactions" STRUCT("url" VARCHAR, "total_count" BIGINT, "+1" BIGINT, "-1" BIGINT, "laugh" BIGINT, "confused" BIGINT, "heart" BIGINT, "hooray" BIGINT, "eyes" BIGINT, "rocket" BIGINT), "pin" STRUCT("pinned_at" TIMESTAMP WITH TIME ZONE, "pinned_by" STRUCT("id" BIGINT, "node_id" VARCHAR, "login" VARCHAR, "type" VARCHAR)), "minimized" STRUCT("reason" VARCHAR))` | yes |
| `cross_referenced_payload` | `STRUCT("event" VARCHAR, "actor" STRUCT("id" BIGINT, "node_id" VARCHAR, "login" VARCHAR, "type" VARCHAR), "created_at" TIMESTAMP WITH TIME ZONE, "updated_at" TIMESTAMP WITH TIME ZONE, "source" STRUCT("type" VARCHAR, "issue" STRUCT("id" BIGINT, "node_id" VARCHAR, "number" BIGINT, "repository_url" VARCHAR, "html_url" VARCHAR, "title" VARCHAR, "state" VARCHAR)))` | yes |
| `committed_payload` | `STRUCT("event" VARCHAR, "sha" VARCHAR, "node_id" VARCHAR, "url" VARCHAR, "author" STRUCT("date" TIMESTAMP WITH TIME ZONE, "email" VARCHAR, "name" VARCHAR), "committer" STRUCT("date" TIMESTAMP WITH TIME ZONE, "email" VARCHAR, "name" VARCHAR), "message" VARCHAR, "tree" STRUCT("sha" VARCHAR, "url" VARCHAR), "parents" STRUCT("sha" VARCHAR, "url" VARCHAR, "html_url" VARCHAR)[], "verification" STRUCT("verified" BOOLEAN, "reason" VARCHAR, "signature" VARCHAR, "payload" VARCHAR, "verified_at" VARCHAR), "html_url" VARCHAR)` | yes |
| `reviewed_payload` | `STRUCT("event" VARCHAR, "id" BIGINT, "node_id" VARCHAR, "user" STRUCT("id" BIGINT, "node_id" VARCHAR, "login" VARCHAR, "type" VARCHAR), "body" VARCHAR, "state" VARCHAR, "html_url" VARCHAR, "pull_request_url" VARCHAR, "_links" STRUCT("html" STRUCT("href" VARCHAR), "pull_request" STRUCT("href" VARCHAR)), "submitted_at" TIMESTAMP WITH TIME ZONE, "updated_at" TIMESTAMP WITH TIME ZONE, "commit_id" VARCHAR, "body_html" VARCHAR, "body_text" VARCHAR, "author_association" VARCHAR)` | yes |
| `line_commented_payload` | `STRUCT("event" VARCHAR, "node_id" VARCHAR, "comments" STRUCT("url" VARCHAR, "pull_request_review_id" BIGINT, "id" BIGINT, "node_id" VARCHAR, "diff_hunk" VARCHAR, "path" VARCHAR, "position" BIGINT, "original_position" BIGINT, "commit_id" VARCHAR, "original_commit_id" VARCHAR, "in_reply_to_id" BIGINT, "user" STRUCT("id" BIGINT, "node_id" VARCHAR, "login" VARCHAR, "type" VARCHAR), "body" VARCHAR, "created_at" TIMESTAMP WITH TIME ZONE, "updated_at" TIMESTAMP WITH TIME ZONE, "html_url" VARCHAR, "pull_request_url" VARCHAR, "author_association" VARCHAR, "_links" STRUCT("self" STRUCT("href" VARCHAR), "html" STRUCT("href" VARCHAR), "pull_request" STRUCT("href" VARCHAR)), "start_line" BIGINT, "original_start_line" BIGINT, "start_side" VARCHAR, "line" BIGINT, "original_line" BIGINT, "side" VARCHAR, "subject_type" VARCHAR, "reactions" STRUCT("url" VARCHAR, "total_count" BIGINT, "+1" BIGINT, "-1" BIGINT, "laugh" BIGINT, "confused" BIGINT, "heart" BIGINT, "hooray" BIGINT, "eyes" BIGINT, "rocket" BIGINT), "body_html" VARCHAR, "body_text" VARCHAR)[])` | yes |
| `commit_commented_payload` | `STRUCT("event" VARCHAR, "node_id" VARCHAR, "commit_id" VARCHAR, "comments" STRUCT("html_url" VARCHAR, "url" VARCHAR, "id" BIGINT, "node_id" VARCHAR, "body" VARCHAR, "path" VARCHAR, "position" BIGINT, "line" BIGINT, "commit_id" VARCHAR, "user" STRUCT("id" BIGINT, "node_id" VARCHAR, "login" VARCHAR, "type" VARCHAR), "created_at" TIMESTAMP WITH TIME ZONE, "updated_at" TIMESTAMP WITH TIME ZONE, "author_association" VARCHAR, "reactions" STRUCT("url" VARCHAR, "total_count" BIGINT, "+1" BIGINT, "-1" BIGINT, "laugh" BIGINT, "confused" BIGINT, "heart" BIGINT, "hooray" BIGINT, "eyes" BIGINT, "rocket" BIGINT))[])` | yes |
| `assigned_payload` | `STRUCT("id" BIGINT, "node_id" VARCHAR, "url" VARCHAR, "actor" STRUCT("id" BIGINT, "node_id" VARCHAR, "login" VARCHAR, "type" VARCHAR), "event" VARCHAR, "commit_id" VARCHAR, "commit_url" VARCHAR, "created_at" VARCHAR, "performed_via_github_app" STRUCT("id" BIGINT, "slug" VARCHAR, "node_id" VARCHAR, "client_id" VARCHAR, "owner" STRUCT("matched_types" VARCHAR[], "variant_1" STRUCT("id" BIGINT, "node_id" VARCHAR, "login" VARCHAR, "type" VARCHAR), "variant_2" STRUCT("description" VARCHAR, "html_url" VARCHAR, "website_url" VARCHAR, "id" BIGINT, "node_id" VARCHAR, "name" VARCHAR, "slug" VARCHAR, "created_at" TIMESTAMP WITH TIME ZONE, "updated_at" TIMESTAMP WITH TIME ZONE, "avatar_url" VARCHAR)), "name" VARCHAR, "description" VARCHAR, "external_url" VARCHAR, "html_url" VARCHAR, "created_at" TIMESTAMP WITH TIME ZONE, "updated_at" TIMESTAMP WITH TIME ZONE, "permissions" STRUCT("issues" VARCHAR, "checks" VARCHAR, "metadata" VARCHAR, "contents" VARCHAR, "deployments" VARCHAR), "events" VARCHAR[], "installations_count" BIGINT), "assignee" STRUCT("id" BIGINT, "node_id" VARCHAR, "login" VARCHAR, "type" VARCHAR), "intent" STRUCT("rationale" VARCHAR, "confidence" VARCHAR))` | yes |
| `unassigned_payload` | `STRUCT("id" BIGINT, "node_id" VARCHAR, "url" VARCHAR, "actor" STRUCT("id" BIGINT, "node_id" VARCHAR, "login" VARCHAR, "type" VARCHAR), "event" VARCHAR, "commit_id" VARCHAR, "commit_url" VARCHAR, "created_at" VARCHAR, "performed_via_github_app" STRUCT("id" BIGINT, "slug" VARCHAR, "node_id" VARCHAR, "client_id" VARCHAR, "owner" STRUCT("matched_types" VARCHAR[], "variant_1" STRUCT("id" BIGINT, "node_id" VARCHAR, "login" VARCHAR, "type" VARCHAR), "variant_2" STRUCT("description" VARCHAR, "html_url" VARCHAR, "website_url" VARCHAR, "id" BIGINT, "node_id" VARCHAR, "name" VARCHAR, "slug" VARCHAR, "created_at" TIMESTAMP WITH TIME ZONE, "updated_at" TIMESTAMP WITH TIME ZONE, "avatar_url" VARCHAR)), "name" VARCHAR, "description" VARCHAR, "external_url" VARCHAR, "html_url" VARCHAR, "created_at" TIMESTAMP WITH TIME ZONE, "updated_at" TIMESTAMP WITH TIME ZONE, "permissions" STRUCT("issues" VARCHAR, "checks" VARCHAR, "metadata" VARCHAR, "contents" VARCHAR, "deployments" VARCHAR), "events" VARCHAR[], "installations_count" BIGINT), "assignee" STRUCT("id" BIGINT, "node_id" VARCHAR, "login" VARCHAR, "type" VARCHAR))` | yes |
| `state_change_payload` | `STRUCT("id" BIGINT, "node_id" VARCHAR, "url" VARCHAR, "actor" STRUCT("id" BIGINT, "node_id" VARCHAR, "login" VARCHAR, "type" VARCHAR), "event" VARCHAR, "commit_id" VARCHAR, "commit_url" VARCHAR, "created_at" VARCHAR, "performed_via_github_app" STRUCT("id" BIGINT, "slug" VARCHAR, "node_id" VARCHAR, "client_id" VARCHAR, "owner" STRUCT("matched_types" VARCHAR[], "variant_1" STRUCT("id" BIGINT, "node_id" VARCHAR, "login" VARCHAR, "type" VARCHAR), "variant_2" STRUCT("description" VARCHAR, "html_url" VARCHAR, "website_url" VARCHAR, "id" BIGINT, "node_id" VARCHAR, "name" VARCHAR, "slug" VARCHAR, "created_at" TIMESTAMP WITH TIME ZONE, "updated_at" TIMESTAMP WITH TIME ZONE, "avatar_url" VARCHAR)), "name" VARCHAR, "description" VARCHAR, "external_url" VARCHAR, "html_url" VARCHAR, "created_at" TIMESTAMP WITH TIME ZONE, "updated_at" TIMESTAMP WITH TIME ZONE, "permissions" STRUCT("issues" VARCHAR, "checks" VARCHAR, "metadata" VARCHAR, "contents" VARCHAR, "deployments" VARCHAR), "events" VARCHAR[], "installations_count" BIGINT), "state_reason" VARCHAR, "intent" STRUCT("rationale" VARCHAR, "confidence" VARCHAR))` | yes |
| `issue_type_added_payload` | `STRUCT("id" BIGINT, "node_id" VARCHAR, "url" VARCHAR, "actor" STRUCT("id" BIGINT, "node_id" VARCHAR, "login" VARCHAR, "type" VARCHAR), "event" VARCHAR, "commit_id" VARCHAR, "commit_url" VARCHAR, "created_at" VARCHAR, "performed_via_github_app" STRUCT("id" BIGINT, "slug" VARCHAR, "node_id" VARCHAR, "client_id" VARCHAR, "owner" STRUCT("matched_types" VARCHAR[], "variant_1" STRUCT("id" BIGINT, "node_id" VARCHAR, "login" VARCHAR, "type" VARCHAR), "variant_2" STRUCT("description" VARCHAR, "html_url" VARCHAR, "website_url" VARCHAR, "id" BIGINT, "node_id" VARCHAR, "name" VARCHAR, "slug" VARCHAR, "created_at" TIMESTAMP WITH TIME ZONE, "updated_at" TIMESTAMP WITH TIME ZONE, "avatar_url" VARCHAR)), "name" VARCHAR, "description" VARCHAR, "external_url" VARCHAR, "html_url" VARCHAR, "created_at" TIMESTAMP WITH TIME ZONE, "updated_at" TIMESTAMP WITH TIME ZONE, "permissions" STRUCT("issues" VARCHAR, "checks" VARCHAR, "metadata" VARCHAR, "contents" VARCHAR, "deployments" VARCHAR), "events" VARCHAR[], "installations_count" BIGINT), "issue_type" STRUCT("id" BIGINT, "name" VARCHAR, "color" VARCHAR), "intent" STRUCT("rationale" VARCHAR, "confidence" VARCHAR))` | yes |
| `issue_type_removed_payload` | `STRUCT("id" BIGINT, "node_id" VARCHAR, "url" VARCHAR, "actor" STRUCT("id" BIGINT, "node_id" VARCHAR, "login" VARCHAR, "type" VARCHAR), "event" VARCHAR, "commit_id" VARCHAR, "commit_url" VARCHAR, "created_at" VARCHAR, "performed_via_github_app" STRUCT("id" BIGINT, "slug" VARCHAR, "node_id" VARCHAR, "client_id" VARCHAR, "owner" STRUCT("matched_types" VARCHAR[], "variant_1" STRUCT("id" BIGINT, "node_id" VARCHAR, "login" VARCHAR, "type" VARCHAR), "variant_2" STRUCT("description" VARCHAR, "html_url" VARCHAR, "website_url" VARCHAR, "id" BIGINT, "node_id" VARCHAR, "name" VARCHAR, "slug" VARCHAR, "created_at" TIMESTAMP WITH TIME ZONE, "updated_at" TIMESTAMP WITH TIME ZONE, "avatar_url" VARCHAR)), "name" VARCHAR, "description" VARCHAR, "external_url" VARCHAR, "html_url" VARCHAR, "created_at" TIMESTAMP WITH TIME ZONE, "updated_at" TIMESTAMP WITH TIME ZONE, "permissions" STRUCT("issues" VARCHAR, "checks" VARCHAR, "metadata" VARCHAR, "contents" VARCHAR, "deployments" VARCHAR), "events" VARCHAR[], "installations_count" BIGINT), "prev_issue_type" STRUCT("id" BIGINT, "name" VARCHAR, "color" VARCHAR), "intent" STRUCT("rationale" VARCHAR, "confidence" VARCHAR))` | yes |
| `issue_type_changed_payload` | `STRUCT("id" BIGINT, "node_id" VARCHAR, "url" VARCHAR, "actor" STRUCT("id" BIGINT, "node_id" VARCHAR, "login" VARCHAR, "type" VARCHAR), "event" VARCHAR, "commit_id" VARCHAR, "commit_url" VARCHAR, "created_at" VARCHAR, "performed_via_github_app" STRUCT("id" BIGINT, "slug" VARCHAR, "node_id" VARCHAR, "client_id" VARCHAR, "owner" STRUCT("matched_types" VARCHAR[], "variant_1" STRUCT("id" BIGINT, "node_id" VARCHAR, "login" VARCHAR, "type" VARCHAR), "variant_2" STRUCT("description" VARCHAR, "html_url" VARCHAR, "website_url" VARCHAR, "id" BIGINT, "node_id" VARCHAR, "name" VARCHAR, "slug" VARCHAR, "created_at" TIMESTAMP WITH TIME ZONE, "updated_at" TIMESTAMP WITH TIME ZONE, "avatar_url" VARCHAR)), "name" VARCHAR, "description" VARCHAR, "external_url" VARCHAR, "html_url" VARCHAR, "created_at" TIMESTAMP WITH TIME ZONE, "updated_at" TIMESTAMP WITH TIME ZONE, "permissions" STRUCT("issues" VARCHAR, "checks" VARCHAR, "metadata" VARCHAR, "contents" VARCHAR, "deployments" VARCHAR), "events" VARCHAR[], "installations_count" BIGINT), "issue_type" STRUCT("id" BIGINT, "name" VARCHAR, "color" VARCHAR), "prev_issue_type" STRUCT("id" BIGINT, "name" VARCHAR, "color" VARCHAR), "intent" STRUCT("rationale" VARCHAR, "confidence" VARCHAR))` | yes |
| `sub_issue_added_payload` | `STRUCT("id" BIGINT, "node_id" VARCHAR, "url" VARCHAR, "actor" STRUCT("id" BIGINT, "node_id" VARCHAR, "login" VARCHAR, "type" VARCHAR), "event" VARCHAR, "commit_id" VARCHAR, "commit_url" VARCHAR, "created_at" VARCHAR, "performed_via_github_app" STRUCT("id" BIGINT, "slug" VARCHAR, "node_id" VARCHAR, "client_id" VARCHAR, "owner" STRUCT("matched_types" VARCHAR[], "variant_1" STRUCT("id" BIGINT, "node_id" VARCHAR, "login" VARCHAR, "type" VARCHAR), "variant_2" STRUCT("description" VARCHAR, "html_url" VARCHAR, "website_url" VARCHAR, "id" BIGINT, "node_id" VARCHAR, "name" VARCHAR, "slug" VARCHAR, "created_at" TIMESTAMP WITH TIME ZONE, "updated_at" TIMESTAMP WITH TIME ZONE, "avatar_url" VARCHAR)), "name" VARCHAR, "description" VARCHAR, "external_url" VARCHAR, "html_url" VARCHAR, "created_at" TIMESTAMP WITH TIME ZONE, "updated_at" TIMESTAMP WITH TIME ZONE, "permissions" STRUCT("issues" VARCHAR, "checks" VARCHAR, "metadata" VARCHAR, "contents" VARCHAR, "deployments" VARCHAR), "events" VARCHAR[], "installations_count" BIGINT), "sub_issue" STRUCT("number" BIGINT, "title" VARCHAR, "state" VARCHAR, "state_reason" VARCHAR, "repository" STRUCT("id" BIGINT, "node_id" VARCHAR, "name" VARCHAR, "full_name" VARCHAR, "private" BOOLEAN, "html_url" VARCHAR), "issue_type" STRUCT("id" BIGINT, "node_id" VARCHAR, "name" VARCHAR, "color" VARCHAR)))` | yes |
| `sub_issue_removed_payload` | `STRUCT("id" BIGINT, "node_id" VARCHAR, "url" VARCHAR, "actor" STRUCT("id" BIGINT, "node_id" VARCHAR, "login" VARCHAR, "type" VARCHAR), "event" VARCHAR, "commit_id" VARCHAR, "commit_url" VARCHAR, "created_at" VARCHAR, "performed_via_github_app" STRUCT("id" BIGINT, "slug" VARCHAR, "node_id" VARCHAR, "client_id" VARCHAR, "owner" STRUCT("matched_types" VARCHAR[], "variant_1" STRUCT("id" BIGINT, "node_id" VARCHAR, "login" VARCHAR, "type" VARCHAR), "variant_2" STRUCT("description" VARCHAR, "html_url" VARCHAR, "website_url" VARCHAR, "id" BIGINT, "node_id" VARCHAR, "name" VARCHAR, "slug" VARCHAR, "created_at" TIMESTAMP WITH TIME ZONE, "updated_at" TIMESTAMP WITH TIME ZONE, "avatar_url" VARCHAR)), "name" VARCHAR, "description" VARCHAR, "external_url" VARCHAR, "html_url" VARCHAR, "created_at" TIMESTAMP WITH TIME ZONE, "updated_at" TIMESTAMP WITH TIME ZONE, "permissions" STRUCT("issues" VARCHAR, "checks" VARCHAR, "metadata" VARCHAR, "contents" VARCHAR, "deployments" VARCHAR), "events" VARCHAR[], "installations_count" BIGINT), "sub_issue" STRUCT("number" BIGINT, "title" VARCHAR, "state" VARCHAR, "state_reason" VARCHAR, "repository" STRUCT("id" BIGINT, "node_id" VARCHAR, "name" VARCHAR, "full_name" VARCHAR, "private" BOOLEAN, "html_url" VARCHAR), "issue_type" STRUCT("id" BIGINT, "node_id" VARCHAR, "name" VARCHAR, "color" VARCHAR)))` | yes |
| `parent_issue_added_payload` | `STRUCT("id" BIGINT, "node_id" VARCHAR, "url" VARCHAR, "actor" STRUCT("id" BIGINT, "node_id" VARCHAR, "login" VARCHAR, "type" VARCHAR), "event" VARCHAR, "commit_id" VARCHAR, "commit_url" VARCHAR, "created_at" VARCHAR, "performed_via_github_app" STRUCT("id" BIGINT, "slug" VARCHAR, "node_id" VARCHAR, "client_id" VARCHAR, "owner" STRUCT("matched_types" VARCHAR[], "variant_1" STRUCT("id" BIGINT, "node_id" VARCHAR, "login" VARCHAR, "type" VARCHAR), "variant_2" STRUCT("description" VARCHAR, "html_url" VARCHAR, "website_url" VARCHAR, "id" BIGINT, "node_id" VARCHAR, "name" VARCHAR, "slug" VARCHAR, "created_at" TIMESTAMP WITH TIME ZONE, "updated_at" TIMESTAMP WITH TIME ZONE, "avatar_url" VARCHAR)), "name" VARCHAR, "description" VARCHAR, "external_url" VARCHAR, "html_url" VARCHAR, "created_at" TIMESTAMP WITH TIME ZONE, "updated_at" TIMESTAMP WITH TIME ZONE, "permissions" STRUCT("issues" VARCHAR, "checks" VARCHAR, "metadata" VARCHAR, "contents" VARCHAR, "deployments" VARCHAR), "events" VARCHAR[], "installations_count" BIGINT), "parent_issue" STRUCT("number" BIGINT, "title" VARCHAR, "state" VARCHAR, "state_reason" VARCHAR, "repository" STRUCT("id" BIGINT, "node_id" VARCHAR, "name" VARCHAR, "full_name" VARCHAR, "private" BOOLEAN, "html_url" VARCHAR), "issue_type" STRUCT("id" BIGINT, "node_id" VARCHAR, "name" VARCHAR, "color" VARCHAR)))` | yes |
| `parent_issue_removed_payload` | `STRUCT("id" BIGINT, "node_id" VARCHAR, "url" VARCHAR, "actor" STRUCT("id" BIGINT, "node_id" VARCHAR, "login" VARCHAR, "type" VARCHAR), "event" VARCHAR, "commit_id" VARCHAR, "commit_url" VARCHAR, "created_at" VARCHAR, "performed_via_github_app" STRUCT("id" BIGINT, "slug" VARCHAR, "node_id" VARCHAR, "client_id" VARCHAR, "owner" STRUCT("matched_types" VARCHAR[], "variant_1" STRUCT("id" BIGINT, "node_id" VARCHAR, "login" VARCHAR, "type" VARCHAR), "variant_2" STRUCT("description" VARCHAR, "html_url" VARCHAR, "website_url" VARCHAR, "id" BIGINT, "node_id" VARCHAR, "name" VARCHAR, "slug" VARCHAR, "created_at" TIMESTAMP WITH TIME ZONE, "updated_at" TIMESTAMP WITH TIME ZONE, "avatar_url" VARCHAR)), "name" VARCHAR, "description" VARCHAR, "external_url" VARCHAR, "html_url" VARCHAR, "created_at" TIMESTAMP WITH TIME ZONE, "updated_at" TIMESTAMP WITH TIME ZONE, "permissions" STRUCT("issues" VARCHAR, "checks" VARCHAR, "metadata" VARCHAR, "contents" VARCHAR, "deployments" VARCHAR), "events" VARCHAR[], "installations_count" BIGINT), "parent_issue" STRUCT("number" BIGINT, "title" VARCHAR, "state" VARCHAR, "state_reason" VARCHAR, "repository" STRUCT("id" BIGINT, "node_id" VARCHAR, "name" VARCHAR, "full_name" VARCHAR, "private" BOOLEAN, "html_url" VARCHAR), "issue_type" STRUCT("id" BIGINT, "node_id" VARCHAR, "name" VARCHAR, "color" VARCHAR)))` | yes |
| `blocked_by_added_payload` | `STRUCT("id" BIGINT, "node_id" VARCHAR, "url" VARCHAR, "actor" STRUCT("id" BIGINT, "node_id" VARCHAR, "login" VARCHAR, "type" VARCHAR), "event" VARCHAR, "commit_id" VARCHAR, "commit_url" VARCHAR, "created_at" VARCHAR, "performed_via_github_app" STRUCT("id" BIGINT, "slug" VARCHAR, "node_id" VARCHAR, "client_id" VARCHAR, "owner" STRUCT("matched_types" VARCHAR[], "variant_1" STRUCT("id" BIGINT, "node_id" VARCHAR, "login" VARCHAR, "type" VARCHAR), "variant_2" STRUCT("description" VARCHAR, "html_url" VARCHAR, "website_url" VARCHAR, "id" BIGINT, "node_id" VARCHAR, "name" VARCHAR, "slug" VARCHAR, "created_at" TIMESTAMP WITH TIME ZONE, "updated_at" TIMESTAMP WITH TIME ZONE, "avatar_url" VARCHAR)), "name" VARCHAR, "description" VARCHAR, "external_url" VARCHAR, "html_url" VARCHAR, "created_at" TIMESTAMP WITH TIME ZONE, "updated_at" TIMESTAMP WITH TIME ZONE, "permissions" STRUCT("issues" VARCHAR, "checks" VARCHAR, "metadata" VARCHAR, "contents" VARCHAR, "deployments" VARCHAR), "events" VARCHAR[], "installations_count" BIGINT), "blocked_by" STRUCT("number" BIGINT, "title" VARCHAR, "state" VARCHAR, "state_reason" VARCHAR, "repository" STRUCT("id" BIGINT, "node_id" VARCHAR, "name" VARCHAR, "full_name" VARCHAR, "private" BOOLEAN, "html_url" VARCHAR), "issue_type" STRUCT("id" BIGINT, "node_id" VARCHAR, "name" VARCHAR, "color" VARCHAR)))` | yes |
| `blocked_by_removed_payload` | `STRUCT("id" BIGINT, "node_id" VARCHAR, "url" VARCHAR, "actor" STRUCT("id" BIGINT, "node_id" VARCHAR, "login" VARCHAR, "type" VARCHAR), "event" VARCHAR, "commit_id" VARCHAR, "commit_url" VARCHAR, "created_at" VARCHAR, "performed_via_github_app" STRUCT("id" BIGINT, "slug" VARCHAR, "node_id" VARCHAR, "client_id" VARCHAR, "owner" STRUCT("matched_types" VARCHAR[], "variant_1" STRUCT("id" BIGINT, "node_id" VARCHAR, "login" VARCHAR, "type" VARCHAR), "variant_2" STRUCT("description" VARCHAR, "html_url" VARCHAR, "website_url" VARCHAR, "id" BIGINT, "node_id" VARCHAR, "name" VARCHAR, "slug" VARCHAR, "created_at" TIMESTAMP WITH TIME ZONE, "updated_at" TIMESTAMP WITH TIME ZONE, "avatar_url" VARCHAR)), "name" VARCHAR, "description" VARCHAR, "external_url" VARCHAR, "html_url" VARCHAR, "created_at" TIMESTAMP WITH TIME ZONE, "updated_at" TIMESTAMP WITH TIME ZONE, "permissions" STRUCT("issues" VARCHAR, "checks" VARCHAR, "metadata" VARCHAR, "contents" VARCHAR, "deployments" VARCHAR), "events" VARCHAR[], "installations_count" BIGINT), "blocked_by" STRUCT("number" BIGINT, "title" VARCHAR, "state" VARCHAR, "state_reason" VARCHAR, "repository" STRUCT("id" BIGINT, "node_id" VARCHAR, "name" VARCHAR, "full_name" VARCHAR, "private" BOOLEAN, "html_url" VARCHAR), "issue_type" STRUCT("id" BIGINT, "node_id" VARCHAR, "name" VARCHAR, "color" VARCHAR)))` | yes |
| `blocking_added_payload` | `STRUCT("id" BIGINT, "node_id" VARCHAR, "url" VARCHAR, "actor" STRUCT("id" BIGINT, "node_id" VARCHAR, "login" VARCHAR, "type" VARCHAR), "event" VARCHAR, "commit_id" VARCHAR, "commit_url" VARCHAR, "created_at" VARCHAR, "performed_via_github_app" STRUCT("id" BIGINT, "slug" VARCHAR, "node_id" VARCHAR, "client_id" VARCHAR, "owner" STRUCT("matched_types" VARCHAR[], "variant_1" STRUCT("id" BIGINT, "node_id" VARCHAR, "login" VARCHAR, "type" VARCHAR), "variant_2" STRUCT("description" VARCHAR, "html_url" VARCHAR, "website_url" VARCHAR, "id" BIGINT, "node_id" VARCHAR, "name" VARCHAR, "slug" VARCHAR, "created_at" TIMESTAMP WITH TIME ZONE, "updated_at" TIMESTAMP WITH TIME ZONE, "avatar_url" VARCHAR)), "name" VARCHAR, "description" VARCHAR, "external_url" VARCHAR, "html_url" VARCHAR, "created_at" TIMESTAMP WITH TIME ZONE, "updated_at" TIMESTAMP WITH TIME ZONE, "permissions" STRUCT("issues" VARCHAR, "checks" VARCHAR, "metadata" VARCHAR, "contents" VARCHAR, "deployments" VARCHAR), "events" VARCHAR[], "installations_count" BIGINT), "blocking" STRUCT("number" BIGINT, "title" VARCHAR, "state" VARCHAR, "state_reason" VARCHAR, "repository" STRUCT("id" BIGINT, "node_id" VARCHAR, "name" VARCHAR, "full_name" VARCHAR, "private" BOOLEAN, "html_url" VARCHAR), "issue_type" STRUCT("id" BIGINT, "node_id" VARCHAR, "name" VARCHAR, "color" VARCHAR)))` | yes |
| `blocking_removed_payload` | `STRUCT("id" BIGINT, "node_id" VARCHAR, "url" VARCHAR, "actor" STRUCT("id" BIGINT, "node_id" VARCHAR, "login" VARCHAR, "type" VARCHAR), "event" VARCHAR, "commit_id" VARCHAR, "commit_url" VARCHAR, "created_at" VARCHAR, "performed_via_github_app" STRUCT("id" BIGINT, "slug" VARCHAR, "node_id" VARCHAR, "client_id" VARCHAR, "owner" STRUCT("matched_types" VARCHAR[], "variant_1" STRUCT("id" BIGINT, "node_id" VARCHAR, "login" VARCHAR, "type" VARCHAR), "variant_2" STRUCT("description" VARCHAR, "html_url" VARCHAR, "website_url" VARCHAR, "id" BIGINT, "node_id" VARCHAR, "name" VARCHAR, "slug" VARCHAR, "created_at" TIMESTAMP WITH TIME ZONE, "updated_at" TIMESTAMP WITH TIME ZONE, "avatar_url" VARCHAR)), "name" VARCHAR, "description" VARCHAR, "external_url" VARCHAR, "html_url" VARCHAR, "created_at" TIMESTAMP WITH TIME ZONE, "updated_at" TIMESTAMP WITH TIME ZONE, "permissions" STRUCT("issues" VARCHAR, "checks" VARCHAR, "metadata" VARCHAR, "contents" VARCHAR, "deployments" VARCHAR), "events" VARCHAR[], "installations_count" BIGINT), "blocking" STRUCT("number" BIGINT, "title" VARCHAR, "state" VARCHAR, "state_reason" VARCHAR, "repository" STRUCT("id" BIGINT, "node_id" VARCHAR, "name" VARCHAR, "full_name" VARCHAR, "private" BOOLEAN, "html_url" VARCHAR), "issue_type" STRUCT("id" BIGINT, "node_id" VARCHAR, "name" VARCHAR, "color" VARCHAR)))` | yes |
| `connected_payload` | `STRUCT("id" BIGINT, "node_id" VARCHAR, "url" VARCHAR, "actor" STRUCT("id" BIGINT, "node_id" VARCHAR, "login" VARCHAR, "type" VARCHAR), "event" VARCHAR, "commit_id" VARCHAR, "commit_url" VARCHAR, "created_at" VARCHAR, "performed_via_github_app" STRUCT("id" BIGINT, "slug" VARCHAR, "node_id" VARCHAR, "client_id" VARCHAR, "owner" STRUCT("matched_types" VARCHAR[], "variant_1" STRUCT("id" BIGINT, "node_id" VARCHAR, "login" VARCHAR, "type" VARCHAR), "variant_2" STRUCT("description" VARCHAR, "html_url" VARCHAR, "website_url" VARCHAR, "id" BIGINT, "node_id" VARCHAR, "name" VARCHAR, "slug" VARCHAR, "created_at" TIMESTAMP WITH TIME ZONE, "updated_at" TIMESTAMP WITH TIME ZONE, "avatar_url" VARCHAR)), "name" VARCHAR, "description" VARCHAR, "external_url" VARCHAR, "html_url" VARCHAR, "created_at" TIMESTAMP WITH TIME ZONE, "updated_at" TIMESTAMP WITH TIME ZONE, "permissions" STRUCT("issues" VARCHAR, "checks" VARCHAR, "metadata" VARCHAR, "contents" VARCHAR, "deployments" VARCHAR), "events" VARCHAR[], "installations_count" BIGINT))` | yes |
| `disconnected_payload` | `STRUCT("id" BIGINT, "node_id" VARCHAR, "url" VARCHAR, "actor" STRUCT("id" BIGINT, "node_id" VARCHAR, "login" VARCHAR, "type" VARCHAR), "event" VARCHAR, "commit_id" VARCHAR, "commit_url" VARCHAR, "created_at" VARCHAR, "performed_via_github_app" STRUCT("id" BIGINT, "slug" VARCHAR, "node_id" VARCHAR, "client_id" VARCHAR, "owner" STRUCT("matched_types" VARCHAR[], "variant_1" STRUCT("id" BIGINT, "node_id" VARCHAR, "login" VARCHAR, "type" VARCHAR), "variant_2" STRUCT("description" VARCHAR, "html_url" VARCHAR, "website_url" VARCHAR, "id" BIGINT, "node_id" VARCHAR, "name" VARCHAR, "slug" VARCHAR, "created_at" TIMESTAMP WITH TIME ZONE, "updated_at" TIMESTAMP WITH TIME ZONE, "avatar_url" VARCHAR)), "name" VARCHAR, "description" VARCHAR, "external_url" VARCHAR, "html_url" VARCHAR, "created_at" TIMESTAMP WITH TIME ZONE, "updated_at" TIMESTAMP WITH TIME ZONE, "permissions" STRUCT("issues" VARCHAR, "checks" VARCHAR, "metadata" VARCHAR, "contents" VARCHAR, "deployments" VARCHAR), "events" VARCHAR[], "installations_count" BIGINT))` | yes |

Approved metrics:

- `issue_timeline_entry_count`: Returned mixed timeline observations, not distinct issue events, comments, reviews or commits. Retrieval-local ordinals preserve occurrences across pages.

### `issue_field_values`

Typed issue field values preserve text, number and integer anyOf alternatives, nullable value and explicit single/multi-select option metadata. Date strings remain source strings; no unsupported timezone or date precision is invented.

Grain: `repository_id`, `issue_number`, `issue_field_id`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `issue_field_values__issues` | `issue_number` | Visible records at the stated grain, with all advertised collection pages exhausted. Missing permissions fail rather than silently return a partial population. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `repository_id` | `BIGINT` | no |
| `repository` | `VARCHAR` | no |
| `issue_number` | `BIGINT` | no |
| `issue_field_id` | `BIGINT` | no |
| `issue_field_name` | `VARCHAR` | yes |
| `field_node_id` | `VARCHAR` | no |
| `data_type` | `VARCHAR` | no |
| `value` | `STRUCT("matched_types" VARCHAR[], "variant_1" VARCHAR, "variant_2" DOUBLE, "variant_3" BIGINT)` | yes |
| `single_select_option` | `STRUCT("color" VARCHAR, "id" BIGINT, "name" VARCHAR)` | yes |
| `multi_select_options` | `STRUCT("color" VARCHAR, "id" BIGINT, "name" VARCHAR)[]` | yes |

Approved metrics:

- `issue_field_value_count`: Returned issue/field assignments, including explicit NULL values; not field definition count.

### `issue_suggestions`

Issue suggestions keep proposing actor distinct from resolving user and linked event. Typed target values retain string/number/boolean/string-list alternatives; target_id is polymorphic by action and is not treated as an unconditional label, assignee or issue identity.

Grain: `repository_id`, `suggestion_id`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `issue_suggestions__states` | `issue_suggestion_state` | Visible records at the stated grain, with all advertised collection pages exhausted. Missing permissions fail rather than silently return a partial population. |
| `issue_suggestions__issues` | `issue_number` | Visible records at the stated grain, with all advertised collection pages exhausted. Missing permissions fail rather than silently return a partial population. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `repository_id` | `BIGINT` | no |
| `repository` | `VARCHAR` | no |
| `issue_number` | `BIGINT` | no |
| `suggestion_id` | `BIGINT` | no |
| `issue_id` | `BIGINT` | no |
| `action` | `VARCHAR` | no |
| `state` | `VARCHAR` | no |
| `target_id` | `BIGINT` | yes |
| `rationale` | `VARCHAR` | yes |
| `confidence` | `VARCHAR` | yes |
| `actor_id` | `BIGINT` | yes |
| `issue_event_id` | `BIGINT` | yes |
| `resolved_by` | `BIGINT` | yes |
| `created_at` | `TIMESTAMP WITH TIME ZONE` | no |
| `updated_at` | `TIMESTAMP WITH TIME ZONE` | no |
| `target_value` | `STRUCT("matched_types" VARCHAR[], "variant_1" VARCHAR, "variant_2" DOUBLE, "variant_3" BOOLEAN, "variant_4" VARCHAR[])` | yes |

Approved metrics:

- `issue_suggestion_count`: Agent-proposed issue changes in all lifecycle states unless a state filter is supplied; proposals are not applied changes.
- `issue_applied_suggestion_count`: Suggestions whose current lifecycle state is applied.

### `milestones`

Canonical repository milestones with exact and collection retrieval. Reported open_issues/closed_issues counts describe milestone work items including PRs; they are current snapshot counts, not historical completions or counts restricted to the selected issue population.

Grain: `repository_id`, `milestone_id`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `milestones__lookup` | `milestone_number` | Visible records at the stated grain, with all advertised collection pages exhausted. Missing permissions fail rather than silently return a partial population. |
| `milestones__states` | `milestone_state` | Visible records at the stated grain, with all advertised collection pages exhausted. Missing permissions fail rather than silently return a partial population. |
| `milestones__repositories` | `owner`, `repository`, `organization`, `repositories` | Visible records at the stated grain, with all advertised collection pages exhausted. Missing permissions fail rather than silently return a partial population. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `repository_id` | `BIGINT` | no |
| `repository` | `VARCHAR` | no |
| `milestone_id` | `BIGINT` | no |
| `milestone_node_id` | `VARCHAR` | no |
| `milestone_number` | `BIGINT` | no |
| `state` | `VARCHAR` | no |
| `title` | `VARCHAR` | no |
| `description` | `VARCHAR` | yes |
| `open_issues` | `BIGINT` | no |
| `closed_issues` | `BIGINT` | no |
| `created_at` | `TIMESTAMP WITH TIME ZONE` | no |
| `updated_at` | `TIMESTAMP WITH TIME ZONE` | no |
| `closed_at` | `TIMESTAMP WITH TIME ZONE` | yes |
| `due_on` | `TIMESTAMP WITH TIME ZONE` | yes |
| `url` | `VARCHAR` | no |
| `html_url` | `VARCHAR` | no |
| `labels_url` | `VARCHAR` | no |
| `creator_id` | `BIGINT` | yes |
| `creator_login` | `VARCHAR` | yes |

Approved metrics:

- `milestone_count`: Current repository milestone identities, including open and closed states unless explicitly filtered.
- `milestone_open_work_item_count`: Sum API-reported current open milestone work items, which can include pull requests.
- `milestone_closed_work_item_count`: Sum API-reported current closed milestone work items; not historical throughput.

### `repository_assignees`

Users eligible for issue assignment in a repository. Eligibility is not evidence that the user is currently assigned, has authored an issue or belongs to the owning organization.

Grain: `repository_id`, `assignee_id`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `repository_assignees__repositories` | `owner`, `repository`, `organization`, `repositories` | Visible records at the stated grain, with all advertised collection pages exhausted. Missing permissions fail rather than silently return a partial population. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `repository_id` | `BIGINT` | no |
| `repository` | `VARCHAR` | no |
| `assignee_id` | `BIGINT` | no |
| `assignee_login` | `VARCHAR` | no |
| `assignee_node_id` | `VARCHAR` | no |
| `account_type` | `VARCHAR` | no |
| `html_url` | `VARCHAR` | no |

Approved metrics:

- `repository_assignee_count`: Repository/user eligibility memberships; the same user eligible in two repositories contributes two memberships.

### `issue_assignments`

Current assignees of a selected issue or PR. This is the actual assignment relation, distinct from repository-wide eligibility and capability check responses.

Grain: `repository_id`, `issue_number`, `assignee_id`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `issue_assignments__issues` | `issue_number` | Visible records at the stated grain, with all advertised collection pages exhausted. Missing permissions fail rather than silently return a partial population. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `repository_id` | `BIGINT` | no |
| `repository` | `VARCHAR` | no |
| `issue_number` | `BIGINT` | no |
| `assignee_id` | `BIGINT` | no |
| `assignee_login` | `VARCHAR` | no |
| `assignee_node_id` | `VARCHAR` | no |
| `account_type` | `VARCHAR` | no |
| `html_url` | `VARCHAR` | no |

Approved metrics:

- `issue_assignment_count`: Current issue-or-PR/user assignment pairs, not unique assignees across issues.

### `issue_assignment_capabilities`

Assignment capability checks unify repository and exact-issue contexts. context_issue_number=0 is the explicit repository-context discriminator, not an issue number. 204 confirms assignability; 404 can reflect unavailability as well as ineligibility and is not proof that the user or private resource exists.

Grain: `repository_id`, `assignee_login`, `scope_kind`, `context_issue_number`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `issue_assignment_capabilities__issues` | `issue_number` | Visible records at the stated grain, with all advertised collection pages exhausted. Missing permissions fail rather than silently return a partial population. |
| `issue_assignment_capabilities__repositories` | `assignee_login` | Visible records at the stated grain, with all advertised collection pages exhausted. Missing permissions fail rather than silently return a partial population. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `repository_id` | `BIGINT` | no |
| `repository` | `VARCHAR` | no |
| `assignee_login` | `VARCHAR` | no |
| `scope_kind` | `VARCHAR` | no |
| `context_issue_number` | `BIGINT` | no |
| `status_code` | `BIGINT` | no |

Approved metrics:

- `issue_assignment_capability_count`: Explicit capability observations for one login in repository or issue context, including 404 responses.
- `issue_assignable_count`: Observed capability responses with HTTP 204; other statuses are not counted as confirmed assignability.

### `issue_subissue_memberships`

Canonical parent/child Issue pairs shared across parent lookup and sub-issue collection. A parent or child may be in another repository. This counts direct edges, not all descendants or distinct issue identities.

Grain: `parent_node_id`, `child_node_id`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `issue_subissue_memberships__parents` | `issue_parent_of` | Explicit related Issue pairs returned by the endpoint, with endpoint roles preserved across reverse traversal. Cross-repository targets retain their own repository_url and node identity. |
| `issue_subissue_memberships__children` | `issue_children_of` | Explicit related Issue pairs returned by the endpoint, with endpoint roles preserved across reverse traversal. Cross-repository targets retain their own repository_url and node identity. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `parent_node_id` | `VARCHAR` | no |
| `parent_number` | `BIGINT` | no |
| `parent_repository_url` | `VARCHAR` | no |
| `child_node_id` | `VARCHAR` | no |
| `child_number` | `BIGINT` | no |
| `child_repository_url` | `VARCHAR` | no |

Approved metrics:

- `issue_subissue_membership_count`: Canonical parent/child Issue pairs shared across parent lookup and sub-issue collection. A parent or child may be in another repository. This counts direct edges, not all descendants or distinct issue identities.

### `issue_dependencies`

Canonical blocking/blocked Issue pairs shared across both API directions. Direction means the blocking issue must be resolved before the blocked issue; no transitive closure or cycles are inferred.

Grain: `blocking_node_id`, `blocked_node_id`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `issue_dependencies__blocked_by` | `issue_blocked_by` | Explicit related Issue pairs returned by the endpoint, with endpoint roles preserved across reverse traversal. Cross-repository targets retain their own repository_url and node identity. |
| `issue_dependencies__blocking` | `issue_blocking` | Explicit related Issue pairs returned by the endpoint, with endpoint roles preserved across reverse traversal. Cross-repository targets retain their own repository_url and node identity. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `blocking_node_id` | `VARCHAR` | no |
| `blocking_number` | `BIGINT` | no |
| `blocking_repository_url` | `VARCHAR` | no |
| `blocked_node_id` | `VARCHAR` | no |
| `blocked_number` | `BIGINT` | no |
| `blocked_repository_url` | `VARCHAR` | no |

Approved metrics:

- `issue_dependency_count`: Canonical blocking/blocked Issue pairs shared across both API directions. Direction means the blocking issue must be resolved before the blocked issue; no transitive closure or cycles are inferred.

### `issue_related_memberships`

Directed source/related Issue observations returned by the API. A symmetric relationship retrieved from both endpoints produces two directed observations; this is not an undirected distinct-edge count.

Grain: `source_node_id`, `related_node_id`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `issue_related_memberships__issues` | `issue_related_to` | Explicit related Issue pairs returned by the endpoint, with endpoint roles preserved across reverse traversal. Cross-repository targets retain their own repository_url and node identity. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `source_node_id` | `VARCHAR` | no |
| `source_number` | `BIGINT` | no |
| `source_repository_url` | `VARCHAR` | no |
| `related_node_id` | `VARCHAR` | no |
| `related_number` | `BIGINT` | no |
| `related_repository_url` | `VARCHAR` | no |

Approved metrics:

- `issue_related_membership_count`: Directed source/related Issue observations returned by the API. A symmetric relationship retrieved from both endpoints produces two directed observations; this is not an undirected distinct-edge count.

### `reactions`

One canonical reaction entity across issue/PR threads, issue conversation comments, pull request review comments, commit comments and releases. Subject database/node IDs remain distinct from issue numbers and repository identity. issue_thread includes pull requests because the Issues reactions endpoint serves both. Reactors are distinct from parent authors, reviewers and publishers; deleted actors remain unknown. Each route exhausts its subject collection; there is no repository-wide route. Parent relationships preserve navigation but are not approved for analytical enrichment, avoiding ambiguous subject roles and loss of reactions whose optional actor is unavailable. Forward issue/PR navigation uses presence of the typed pull_request marker object; nullable marker URLs are never used to guess parent kind.

Grain: `repository_id`, `reaction_id`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `reactions__issue_threads` | `issue_number` | Every advertised page of reactions on the exact subject, optionally restricted to one supported reaction content. This is not a repository-wide reaction search. |
| `reactions__issue_comments` | `issue_comment_id` | Every advertised page of reactions on the exact subject, optionally restricted to one supported reaction content. This is not a repository-wide reaction search. |
| `reactions__review_comments` | `review_comment_id` | Every advertised page of reactions on the exact subject, optionally restricted to one supported reaction content. This is not a repository-wide reaction search. |
| `reactions__commit_comments` | `commit_comment_id` | Every advertised page of reactions on the exact subject, optionally restricted to one supported reaction content. This is not a repository-wide reaction search. |
| `reactions__releases` | `release_id` | Every advertised page of reactions on the exact subject, optionally restricted to one supported reaction content. This is not a repository-wide reaction search. |
| `reactions__issue_comment_nodes` | `reaction_issue_comment_node_id` | All pages of reactions on the canonical comment node, after resolving its actual repository and REST ID. Unknown numeric identity is an error, not an empty population. |
| `reactions__commit_comment_nodes` | `reaction_commit_comment_node_id` | All pages of reactions on the canonical comment node, after resolving its actual repository and REST ID. Unknown numeric identity is an error, not an empty population. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `repository_id` | `BIGINT` | no |
| `repository` | `VARCHAR` | no |
| `subject_kind` | `VARCHAR` | no |
| `subject_id` | `BIGINT` | no |
| `subject_node_id` | `VARCHAR` | no |
| `subject_number` | `BIGINT` | yes |
| `subject_issue_node_id` | `VARCHAR` | yes |
| `subject_issue_comment_id` | `BIGINT` | yes |
| `subject_issue_comment_node_id` | `VARCHAR` | yes |
| `subject_review_comment_id` | `BIGINT` | yes |
| `subject_commit_comment_id` | `BIGINT` | yes |
| `subject_commit_comment_node_id` | `VARCHAR` | yes |
| `subject_release_id` | `BIGINT` | yes |
| `reaction_id` | `BIGINT` | no |
| `reaction_node_id` | `VARCHAR` | no |
| `content` | `VARCHAR` | no |
| `created_at` | `TIMESTAMP WITH TIME ZONE` | no |
| `reactor` | `STRUCT("avatar_url" VARCHAR, "email" VARCHAR, "events_url" VARCHAR, "followers_url" VARCHAR, "following_url" VARCHAR, "gists_url" VARCHAR, "gravatar_id" VARCHAR, "html_url" VARCHAR, "id" BIGINT, "login" VARCHAR, "name" VARCHAR, "node_id" VARCHAR, "organizations_url" VARCHAR, "received_events_url" VARCHAR, "repos_url" VARCHAR, "site_admin" BOOLEAN, "starred_at" VARCHAR, "starred_url" VARCHAR, "subscriptions_url" VARCHAR, "type" VARCHAR, "url" VARCHAR, "user_view_type" VARCHAR)` | yes |
| `reactor_id` | `BIGINT` | yes |
| `reactor_node_id` | `VARCHAR` | yes |
| `reactor_login` | `VARCHAR` | yes |
| `reactor_type` | `VARCHAR` | yes |
| `subject_pull_request` | `STRUCT("diff_url" VARCHAR, "html_url" VARCHAR, "merged_at" TIMESTAMP WITH TIME ZONE, "patch_url" VARCHAR, "url" VARCHAR)` | yes |

Approved metrics:

- `reaction_count`: Current reaction identities attached to the selected subject, not distinct actors, parent records or historical reaction events.
- `reaction_reactor_count`: Distinct known reacting account identities. Deleted or unavailable reactors are excluded; non-additive across subjects and reaction symbols.
- `reaction_thumbsup_count`: Current +1 reactions only; no sentiment interpretation is assigned to other symbols.
- `reaction_thumbsdown_count`: Current -1 reactions only. Releases do not support this reaction symbol in the pinned API.
- `reaction_unknown_reactor_count`: Reaction rows whose reacting account ID is unavailable; these still contribute to reaction_count.

### `actions_caches`

Current Actions cache inventory, distinct from artifacts. Cache keys and versions are attributes rather than identities; missing cache IDs fail explicit qualification. Cache inventories can change during pagination and do not represent historic storage usage.

Grain: `repository_id`, `cache_id`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `actions_caches__repositories` | `owner`, `repository`, `organization`, `repositories` | All visible rows in the selected repository or repository cohort, preserving all Link pages. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `repository_id` | `BIGINT` | no |
| `repository` | `VARCHAR` | no |
| `cache_id` | `BIGINT` | no |
| `git_ref` | `VARCHAR` | yes |
| `cache_key` | `VARCHAR` | yes |
| `cache_version` | `VARCHAR` | yes |
| `last_accessed_at` | `TIMESTAMP WITH TIME ZONE` | yes |
| `created_at` | `TIMESTAMP WITH TIME ZONE` | yes |
| `size_in_bytes` | `BIGINT` | yes |
| `cache_created_day` | `DATE` | yes |

Approved metrics:

- `actions_cache_count`: Enumerated selected cache records.
- `actions_cache_bytes`: Sum of returned cache entry sizes; missing sizes stay unknown within observed rows.

### `actions_cache_usage`

One current repository cache-usage observation. Organization listing and repository lookup share repository identity. Counters refresh about every five minutes and may differ from a separately enumerated live cache inventory.

Grain: `repository_id`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `actions_cache_usage__organizations` | `organization` | Organization usage listing, with each returned repository hydrated to its canonical ID. Repositories absent from this API listing are not synthesized. |
| `actions_cache_usage__repositories` | `owner`, `repository`, `organization`, `repositories` | All visible rows in the selected repository or repository cohort, preserving all Link pages. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `repository_id` | `BIGINT` | no |
| `repository` | `VARCHAR` | no |
| `reported_repository` | `VARCHAR` | no |
| `active_caches_size_in_bytes` | `BIGINT` | no |
| `active_caches_count` | `BIGINT` | no |

Approved metrics:

- `actions_cache_usage_observation_count`: Repository usage observations, including reported zero usage.
- `reported_active_cache_count`: Sum of API-reported active cache counters.
- `reported_active_cache_bytes`: Sum of API-reported active cache bytes; not billing storage or retention policy.

### `organization_actions_cache_usage`

Organization-level cache usage observation refreshed approximately every five minutes. This summary is its own population and is not repeated once per repository.

Grain: `organization_id`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `organization_actions_cache_usage__organizations` | `organization` | One organization summary observation. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `organization_id` | `BIGINT` | no |
| `organization_login` | `VARCHAR` | no |
| `total_active_caches_count` | `BIGINT` | no |
| `total_active_caches_size_in_bytes` | `BIGINT` | no |

Approved metrics:

- `organization_cache_usage_observation_count`: Selected organization cache usage observations.
- `organization_reported_active_cache_count`: Organization-reported active cache count, independent from repository inventory.
- `organization_reported_active_cache_bytes`: Organization-reported active cache bytes.

### `actions_concurrency_groups`

Current repository concurrency-group observations identified by repository and group name. Typed group_members describe repository-wide leases or the explicitly selected queue prefix. Group URLs are evidence, not followed directly. last_acquired_at is supplied only by list discovery and remains NULL on direct lookup. Inactive groups are absent from repository inventory and return 404 by name; configured run/group memberships use their own association grain.

Grain: `repository_id`, `concurrency_group`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `actions_concurrency_groups__ahead_of_runs` | `ahead_of_run_id` | Current repository-wide queue, or an explicitly requested prefix through the selected run/job. Missing or inactive groups fail with the API status. |
| `actions_concurrency_groups__ahead_of_jobs` | `ahead_of_job_id` | Current repository-wide queue, or an explicitly requested prefix through the selected run/job. Missing or inactive groups fail with the API status. |
| `actions_concurrency_groups__lookup` | `concurrency_group` | Current repository-wide queue, or an explicitly requested prefix through the selected run/job. Missing or inactive groups fail with the API status. |
| `actions_concurrency_groups__repositories` | `owner`, `repository`, `organization`, `repositories` | All active repository groups, with queue details hydrated by name. If a group disappears during hydration the observation fails rather than silently dropping it. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `repository_id` | `BIGINT` | no |
| `repository` | `VARCHAR` | no |
| `concurrency_group` | `VARCHAR` | no |
| `group_url` | `VARCHAR` | no |
| `reported_member_count` | `BIGINT` | no |
| `group_members` | `STRUCT("job_html_url" VARCHAR, "job_id" BIGINT, "job_name" VARCHAR, "job_url" VARCHAR, "run_html_url" VARCHAR, "run_id" BIGINT, "run_name" VARCHAR, "run_url" VARCHAR, "status" VARCHAR)[]` | no |
| `last_acquired_at` | `TIMESTAMP WITH TIME ZONE` | yes |
| `ahead_of_run_id` | `BIGINT` | yes |
| `ahead_of_job_id` | `BIGINT` | yes |

Approved metrics:

- `actions_concurrency_group_count`: Selected active repository concurrency groups.
- `actions_concurrency_member_count`: Returned queue members, counting leases rather than distinct runs or jobs.
- `reported_concurrency_member_count`: API-reported queue member counters for the selected observations; not inferred from nested rows.

### `workflow_run_concurrency_groups`

Configured workflow-run/group memberships, including groups with no current leases. run_group_members contain only this run's members, with their repository-wide queue positions, and must not be confused with repository-wide group_members. Parent navigation is retained without analytical joins that would introduce competing repository paths.

Grain: `repository_id`, `run_id`, `concurrency_group`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `workflow_run_concurrency_groups__runs` | `run_id` | All visible selected run observations, preserving complete pagination and empty nested arrays. |
| `workflow_run_concurrency_groups__workflows` | `workflow_id` | All visible selected run observations, preserving complete pagination and empty nested arrays. |
| `workflow_run_concurrency_groups__repositories` | `owner`, `repository`, `organization`, `repositories` | All visible selected run observations, preserving complete pagination and empty nested arrays. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `repository_id` | `BIGINT` | no |
| `repository` | `VARCHAR` | no |
| `run_id` | `BIGINT` | no |
| `concurrency_group` | `VARCHAR` | no |
| `group_url` | `VARCHAR` | no |
| `run_group_members` | `STRUCT("job_html_url" VARCHAR, "job_id" BIGINT, "job_name" VARCHAR, "job_url" VARCHAR, "position" BIGINT, "position_url" VARCHAR, "run_html_url" VARCHAR, "run_id" BIGINT, "run_name" VARCHAR, "run_url" VARCHAR, "status" VARCHAR)[]` | no |

Approved metrics:

- `workflow_run_concurrency_group_count`: Run/group configuration memberships, including empty groups.
- `workflow_run_concurrency_member_count`: Current run-scoped leases returned for configured group memberships.

### `workflow_pending_deployments`

Current workflow-run/environment pairs waiting for deployment protection. This is pending-gate state, not deployment history. No deployment ID is returned or invented. The current-user approval boolean is caller-specific. Missing environment IDs fail identity qualification; parent run/environment navigation is retained without analytical diamonds.

Grain: `repository_id`, `run_id`, `environment_id`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `workflow_pending_deployments__runs` | `run_id` | All visible selected run observations, preserving complete pagination and empty nested arrays. |
| `workflow_pending_deployments__workflows` | `workflow_id` | All visible selected run observations, preserving complete pagination and empty nested arrays. |
| `workflow_pending_deployments__repositories` | `owner`, `repository`, `organization`, `repositories` | All visible selected run observations, preserving complete pagination and empty nested arrays. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `repository_id` | `BIGINT` | no |
| `repository` | `VARCHAR` | no |
| `run_id` | `BIGINT` | no |
| `environment_id` | `BIGINT` | no |
| `environment_node_id` | `VARCHAR` | yes |
| `environment_name` | `VARCHAR` | yes |
| `environment_url` | `VARCHAR` | yes |
| `environment_html_url` | `VARCHAR` | yes |
| `wait_timer` | `BIGINT` | no |
| `wait_timer_started_at` | `TIMESTAMP WITH TIME ZONE` | yes |
| `current_user_can_approve` | `BOOLEAN` | no |
| `reviewers` | `STRUCT("type" VARCHAR, "reviewer" STRUCT("matched_types" VARCHAR[], "variant_1" STRUCT("avatar_url" VARCHAR, "email" VARCHAR, "events_url" VARCHAR, "followers_url" VARCHAR, "following_url" VARCHAR, "gists_url" VARCHAR, "gravatar_id" VARCHAR, "html_url" VARCHAR, "id" BIGINT, "login" VARCHAR, "name" VARCHAR, "node_id" VARCHAR, "organizations_url" VARCHAR, "received_events_url" VARCHAR, "repos_url" VARCHAR, "site_admin" BOOLEAN, "starred_at" VARCHAR, "starred_url" VARCHAR, "subscriptions_url" VARCHAR, "type" VARCHAR, "url" VARCHAR, "user_view_type" VARCHAR), "variant_2" STRUCT("access_source" VARCHAR, "description" VARCHAR, "enterprise_id" BIGINT, "html_url" VARCHAR, "id" BIGINT, "members_url" VARCHAR, "name" VARCHAR, "node_id" VARCHAR, "notification_setting" VARCHAR, "organization_id" BIGINT, "parent" STRUCT("description" VARCHAR, "enterprise_id" BIGINT, "html_url" VARCHAR, "id" BIGINT, "ldap_dn" VARCHAR, "members_url" VARCHAR, "name" VARCHAR, "node_id" VARCHAR, "notification_setting" VARCHAR, "organization_id" BIGINT, "permission" VARCHAR, "privacy" VARCHAR, "repositories_url" VARCHAR, "slug" VARCHAR, "type" VARCHAR, "url" VARCHAR), "permission" VARCHAR, "permissions" STRUCT("admin" BOOLEAN, "maintain" BOOLEAN, "pull" BOOLEAN, "push" BOOLEAN, "triage" BOOLEAN), "privacy" VARCHAR, "repositories_url" VARCHAR, "slug" VARCHAR, "type" VARCHAR, "url" VARCHAR)))[]` | no |
| `wait_started_day` | `DATE` | yes |

Approved metrics:

- `workflow_pending_deployment_count`: Current run/environment deployment gates.
- `pending_deployment_wait_minutes`: Sum of configured wait durations in minutes; not elapsed waiting time.
- `pending_deployment_reviewer_count`: Configured user/team reviewer options, not approvals or all-required reviewers.
- `approvable_pending_deployment_count`: Pending gates the current caller is explicitly allowed to approve.

### `workflow_deployment_reviews`

Environment-deployment review log occurrences for selected runs. The API supplies no durable review ID or review timestamp; review_ordinal preserves distinct returned occurrences within this retrieval and is not a stable identifier across snapshots. Environment creation/update timestamps describe environments, not review events. Reviewer identity is separate from workflow initiating/triggering actors. Parent run navigation is retained without analytical diamonds.

Grain: `repository_id`, `run_id`, `review_ordinal`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `workflow_deployment_reviews__runs` | `run_id` | All visible selected run observations, preserving complete pagination and empty nested arrays. |
| `workflow_deployment_reviews__workflows` | `workflow_id` | All visible selected run observations, preserving complete pagination and empty nested arrays. |
| `workflow_deployment_reviews__repositories` | `owner`, `repository`, `organization`, `repositories` | All visible selected run observations, preserving complete pagination and empty nested arrays. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `repository_id` | `BIGINT` | no |
| `repository` | `VARCHAR` | no |
| `run_id` | `BIGINT` | no |
| `review_ordinal` | `BIGINT` | no |
| `environments` | `STRUCT("created_at" TIMESTAMP WITH TIME ZONE, "html_url" VARCHAR, "id" BIGINT, "name" VARCHAR, "node_id" VARCHAR, "updated_at" TIMESTAMP WITH TIME ZONE, "url" VARCHAR)[]` | no |
| `state` | `VARCHAR` | no |
| `reviewer` | `STRUCT("avatar_url" VARCHAR, "email" VARCHAR, "events_url" VARCHAR, "followers_url" VARCHAR, "following_url" VARCHAR, "gists_url" VARCHAR, "gravatar_id" VARCHAR, "html_url" VARCHAR, "id" BIGINT, "login" VARCHAR, "name" VARCHAR, "node_id" VARCHAR, "organizations_url" VARCHAR, "received_events_url" VARCHAR, "repos_url" VARCHAR, "site_admin" BOOLEAN, "starred_at" VARCHAR, "starred_url" VARCHAR, "subscriptions_url" VARCHAR, "type" VARCHAR, "url" VARCHAR, "user_view_type" VARCHAR)` | no |
| `reviewer_id` | `BIGINT` | no |
| `reviewer_login` | `VARCHAR` | no |
| `comment` | `VARCHAR` | no |

Approved metrics:

- `workflow_deployment_review_count`: Returned review-log occurrences; repeated identical reviews remain distinct.
- `approved_deployment_review_count`: Review occurrences reporting approved.
- `rejected_deployment_review_count`: Review occurrences reporting rejected.
- `pending_deployment_review_count`: Review occurrences reporting pending with comments.
- `reviewed_environment_association_count`: Review/environment associations; one review can refer to multiple environments.

### `codes_of_conduct`

Canonical GitHub code-of-conduct templates. Catalog entries and exact lookups share the same key and hydrated body; this does not assert adoption by any repository.

Grain: `conduct_key`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `codes_of_conduct__lookup` | `conduct_key` | One exact catalog key; missing or inaccessible lookups fail. |
| `codes_of_conduct__catalog` | Default | Every returned catalog entry across all advertised pages, hydrated by its exact key; a failed detail stops the retrieval. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `conduct_key` | `VARCHAR` | no |
| `name` | `VARCHAR` | no |
| `url` | `VARCHAR` | no |
| `html_url` | `VARCHAR` | yes |
| `body` | `VARCHAR` | yes |

Approved metrics:

- `code_of_conduct_count`: Canonical catalog records selected by listing or exact key; list entries are hydrated to the same complete detail shape.

### `gitignore_templates`

Canonical Gitignore templates selected by exact case-sensitive name or complete catalog discovery. Template source remains native text.

Grain: `template_name`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `gitignore_templates__lookup` | `gitignore_name` | One exact catalog key; missing or inaccessible lookups fail. |
| `gitignore_templates__catalog` | Default | Every returned catalog entry across all advertised pages, hydrated by its exact key; a failed detail stops the retrieval. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `template_name` | `VARCHAR` | no |
| `source` | `VARCHAR` | no |

Approved metrics:

- `gitignore_template_count`: Canonical catalog records selected by listing or exact key; list entries are hydrated to the same complete detail shape.

### `licenses`

Canonical license descriptions identified by GitHub license key. Catalog population is the API commonly used list, not every license ever recognized; list discovery hydrates exact license details. Permissions, conditions and limitations remain typed lists.

Grain: `license_key`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `licenses__lookup` | `license_key` | One exact catalog key; missing or inaccessible lookups fail. |
| `licenses__catalog` | Default | Every returned catalog entry across all advertised pages, hydrated by its exact key; a failed detail stops the retrieval. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `license_key` | `VARCHAR` | no |
| `name` | `VARCHAR` | no |
| `spdx_id` | `VARCHAR` | yes |
| `url` | `VARCHAR` | yes |
| `node_id` | `VARCHAR` | no |
| `html_url` | `VARCHAR` | no |
| `description` | `VARCHAR` | no |
| `implementation` | `VARCHAR` | no |
| `permissions` | `VARCHAR[]` | no |
| `conditions` | `VARCHAR[]` | no |
| `limitations` | `VARCHAR[]` | no |
| `body` | `VARCHAR` | no |
| `featured` | `BOOLEAN` | no |

Approved metrics:

- `license_count`: Canonical catalog records selected by listing or exact key; list entries are hydrated to the same complete detail shape.
- `featured_license_count`: Selected canonical licenses marked featured by GitHub.

### `emojis`

Named GitHub emoji image references. The dictionary key is the stable entry grain; aliases remain separate named entries even when they share an image URL.

Grain: `emoji_name`.

| Column | SQL type | Nullable |
| --- | --- | --- |
| `emoji_name` | `VARCHAR` | no |
| `image_url` | `VARCHAR` | no |

Approved metrics:

- `emoji_count`: Named dictionary entries, including distinct aliases with shared image URLs.

### `api_versions`

Supported GitHub REST API version dates from the pinned scalar date-array contract. One row per supported version; these are version labels, not release publication observations.

Grain: `api_version`.

| Column | SQL type | Nullable |
| --- | --- | --- |
| `api_version` | `DATE` | no |

Approved metrics:

- `api_version_count`: Distinct supported REST API version labels returned by GitHub.

### `api_root_observations`

GitHub root discovery URLs and URI templates as native text. Templates are descriptive values and are never followed as arbitrary request targets. Grain is one endpoint observation for the API host and current caller within an invocation; repeated invocations are snapshots, not historical records.

Grain: `api_host`.

| Column | SQL type | Nullable |
| --- | --- | --- |
| `api_host` | `VARCHAR` | no |
| `current_user_url` | `VARCHAR` | no |
| `current_user_authorizations_html_url` | `VARCHAR` | no |
| `authorizations_url` | `VARCHAR` | no |
| `code_search_url` | `VARCHAR` | no |
| `commit_search_url` | `VARCHAR` | no |
| `emails_url` | `VARCHAR` | no |
| `emojis_url` | `VARCHAR` | no |
| `events_url` | `VARCHAR` | no |
| `feeds_url` | `VARCHAR` | no |
| `followers_url` | `VARCHAR` | no |
| `following_url` | `VARCHAR` | no |
| `gists_url` | `VARCHAR` | no |
| `hub_url` | `VARCHAR` | yes |
| `issue_search_url` | `VARCHAR` | no |
| `issues_url` | `VARCHAR` | no |
| `keys_url` | `VARCHAR` | no |
| `label_search_url` | `VARCHAR` | no |
| `notifications_url` | `VARCHAR` | no |
| `organization_url` | `VARCHAR` | no |
| `organization_repositories_url` | `VARCHAR` | no |
| `organization_teams_url` | `VARCHAR` | no |
| `public_gists_url` | `VARCHAR` | no |
| `rate_limit_url` | `VARCHAR` | no |
| `repository_url` | `VARCHAR` | no |
| `repository_search_url` | `VARCHAR` | no |
| `current_user_repositories_url` | `VARCHAR` | no |
| `starred_url` | `VARCHAR` | no |
| `starred_gists_url` | `VARCHAR` | no |
| `topic_search_url` | `VARCHAR` | yes |
| `user_url` | `VARCHAR` | no |
| `user_organizations_url` | `VARCHAR` | no |
| `user_repositories_url` | `VARCHAR` | no |
| `user_search_url` | `VARCHAR` | no |

Approved metrics:

- `api_root_observation_count`: Endpoint observations retrieved for the current caller; not a count of durable GitHub resources.

### `api_metadata_observations`

Typed GitHub service metadata, network range lists, SSH fingerprints and nested service domains. Returned ranges are retained exactly; they are not inferred to be exhaustive access-control policy. Grain is one endpoint observation for the API host and current caller within an invocation; repeated invocations are snapshots, not historical records.

Grain: `api_host`.

| Column | SQL type | Nullable |
| --- | --- | --- |
| `api_host` | `VARCHAR` | no |
| `verifiable_password_authentication` | `BOOLEAN` | no |
| `ssh_key_fingerprints` | `STRUCT("SHA256_DSA" VARCHAR, "SHA256_ECDSA" VARCHAR, "SHA256_ED25519" VARCHAR, "SHA256_RSA" VARCHAR)` | yes |
| `ssh_keys` | `VARCHAR[]` | yes |
| `hooks` | `VARCHAR[]` | yes |
| `github_enterprise_importer` | `VARCHAR[]` | yes |
| `web` | `VARCHAR[]` | yes |
| `api` | `VARCHAR[]` | yes |
| `git` | `VARCHAR[]` | yes |
| `packages` | `VARCHAR[]` | yes |
| `pages` | `VARCHAR[]` | yes |
| `importer` | `VARCHAR[]` | yes |
| `actions` | `VARCHAR[]` | yes |
| `actions_macos` | `VARCHAR[]` | yes |
| `codespaces` | `VARCHAR[]` | yes |
| `dependabot` | `VARCHAR[]` | yes |
| `copilot` | `VARCHAR[]` | yes |
| `commit_signing_keys` | `VARCHAR[]` | yes |
| `domains` | `STRUCT("actions" VARCHAR[], "actions_inbound" STRUCT("full_domains" VARCHAR[], "wildcard_domains" VARCHAR[]), "artifact_attestations" STRUCT("services" VARCHAR[], "trust_domain" VARCHAR), "codespaces" VARCHAR[], "copilot" VARCHAR[], "packages" VARCHAR[], "storage" VARCHAR[], "website" VARCHAR[])` | yes |

Approved metrics:

- `api_metadata_observation_count`: Endpoint observations retrieved for the current caller; not a count of durable GitHub resources.

### `api_rate_limit_observations`

Typed rate-limit resources and compatibility rate summary. Values depend on the current credential identity or unauthenticated egress IP; reset values are explicit Unix seconds, not fabricated observation times. Grain is one endpoint observation for the API host and current caller within an invocation; repeated invocations are snapshots, not historical records.

Grain: `api_host`.

| Column | SQL type | Nullable |
| --- | --- | --- |
| `api_host` | `VARCHAR` | no |
| `resources` | `STRUCT("actions_runner_registration" STRUCT("limit" BIGINT, "remaining" BIGINT, "reset" BIGINT, "used" BIGINT), "code_scanning_autofix" STRUCT("limit" BIGINT, "remaining" BIGINT, "reset" BIGINT, "used" BIGINT), "code_search" STRUCT("limit" BIGINT, "remaining" BIGINT, "reset" BIGINT, "used" BIGINT), "copilot_usage_records" STRUCT("limit" BIGINT, "remaining" BIGINT, "reset" BIGINT, "used" BIGINT), "core" STRUCT("limit" BIGINT, "remaining" BIGINT, "reset" BIGINT, "used" BIGINT), "dependency_sbom" STRUCT("limit" BIGINT, "remaining" BIGINT, "reset" BIGINT, "used" BIGINT), "dependency_snapshots" STRUCT("limit" BIGINT, "remaining" BIGINT, "reset" BIGINT, "used" BIGINT), "graphql" STRUCT("limit" BIGINT, "remaining" BIGINT, "reset" BIGINT, "used" BIGINT), "integration_manifest" STRUCT("limit" BIGINT, "remaining" BIGINT, "reset" BIGINT, "used" BIGINT), "scim" STRUCT("limit" BIGINT, "remaining" BIGINT, "reset" BIGINT, "used" BIGINT), "search" STRUCT("limit" BIGINT, "remaining" BIGINT, "reset" BIGINT, "used" BIGINT), "source_import" STRUCT("limit" BIGINT, "remaining" BIGINT, "reset" BIGINT, "used" BIGINT))` | no |
| `rate` | `STRUCT("limit" BIGINT, "remaining" BIGINT, "reset" BIGINT, "used" BIGINT)` | no |
| `core_limit` | `BIGINT` | no |
| `core_remaining` | `BIGINT` | no |
| `core_reset` | `BIGINT` | no |
| `core_used` | `BIGINT` | no |

Approved metrics:

- `api_rate_limit_observation_count`: Endpoint observations retrieved for the current caller; not a count of durable GitHub resources.
- `api_core_requests_remaining`: Core requests remaining in the selected requester snapshot. Non-additive across callers or repeated invocations.

### `api_zen_observations`

One GitHub Zen text response, retaining UTF-8 text and exact response bytes. Grain is one endpoint observation for the API host and current caller within an invocation; repeated invocations are snapshots, not historical records.

Grain: `api_host`.

| Column | SQL type | Nullable |
| --- | --- | --- |
| `api_host` | `VARCHAR` | no |
| `status_code` | `BIGINT` | no |
| `content_type` | `VARCHAR` | no |
| `byte_length` | `BIGINT` | no |
| `body` | `BLOB` | no |
| `text` | `VARCHAR` | no |

Approved metrics:

- `api_zen_observation_count`: Endpoint observations retrieved for the current caller; not a count of durable GitHub resources.

### `api_octocat_observations`

One Octocat text rendering for the optional speech argument, retaining UTF-8 text and exact bytes. Grain is one endpoint observation for the API host and current caller within an invocation; repeated invocations are snapshots, not historical records.

Grain: `api_host`.

| Column | SQL type | Nullable |
| --- | --- | --- |
| `api_host` | `VARCHAR` | no |
| `speech` | `VARCHAR` | yes |
| `status_code` | `BIGINT` | no |
| `content_type` | `VARCHAR` | no |
| `byte_length` | `BIGINT` | no |
| `body` | `BLOB` | no |
| `text` | `VARCHAR` | no |

Approved metrics:

- `api_octocat_observation_count`: Endpoint observations retrieved for the current caller; not a count of durable GitHub resources.

### `repository_license_files`

Repository-qualified license file snapshots, keyed by stable repository ID, returned path and immutable blob SHA. Returned license classification may be NULL; it is not equivalent to absence of a file. Default-branch or explicit-ref retrieval follows owner, organization, repository or repository cohort populations. Missing/inaccessible endpoint responses fail closed rather than claim zero coverage.

Grain: `repository_id`, `file_path`, `blob_sha`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `repository_license_files__repositories` | `owner`, `repository`, `organization`, `repositories` | One detected license file for each selected repository/ref, with repository identity hydrated first. Missing/inaccessible file responses fail; a 404 is not silently counted as an unlicensed repository. Encoded content retains its declared encoding. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `repository_id` | `BIGINT` | no |
| `repository` | `VARCHAR` | no |
| `requested_ref` | `VARCHAR` | yes |
| `file_name` | `VARCHAR` | no |
| `file_path` | `VARCHAR` | no |
| `blob_sha` | `VARCHAR` | no |
| `byte_size` | `BIGINT` | no |
| `url` | `VARCHAR` | no |
| `html_url` | `VARCHAR` | yes |
| `git_url` | `VARCHAR` | yes |
| `download_url` | `VARCHAR` | yes |
| `file_type` | `VARCHAR` | no |
| `encoded_content` | `VARCHAR` | no |
| `encoding` | `VARCHAR` | no |
| `links` | `STRUCT("git" VARCHAR, "html" VARCHAR, "self" VARCHAR)` | no |
| `detected_license` | `STRUCT("html_url" VARCHAR, "key" VARCHAR, "name" VARCHAR, "node_id" VARCHAR, "spdx_id" VARCHAR, "url" VARCHAR)` | yes |
| `license_key` | `VARCHAR` | yes |
| `license_spdx_id` | `VARCHAR` | yes |

Approved metrics:

- `repository_license_file_count`: Selected repository license files, including files with no recognized catalog license classification.
- `repository_license_file_bytes`: Upstream file byte sizes for selected repository/path/blob snapshots; not the encoded string length.

### `repository_languages`

Canonical repository-qualified language byte statistics. Grain is repository ID plus the exact dictionary language name; values are GitHub language byte totals, not source-file counts or contributor ownership.

Grain: `repository_id`, `language`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `repository_languages__repositories` | `owner`, `repository`, `organization`, `repositories` | All language entries from each selected repository, with full repository/owner/organization/cohort traversal. An empty dictionary emits zero language facts while repository context remains available. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `repository_id` | `BIGINT` | no |
| `repository` | `VARCHAR` | no |
| `language` | `VARCHAR` | no |
| `byte_count` | `BIGINT` | no |

Approved metrics:

- `repository_language_count`: Repository/language entries; the same language in two repositories counts twice.
- `repository_language_bytes`: GitHub reported language bytes over the selected repository/language entries.

### `security_campaigns`

Organization-qualified security remediation campaigns, with complete typed user managers, team managers and observed alert statistics. Managers are distinct from alert authors or dismissal reviewers. Open/closed alert totals are membership observations and may overlap across campaigns.

Grain: `organization_id`, `campaign_number`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `security_campaigns__lookup` | `security_campaign_number` | All advertised pages of visible campaigns in the selected organization and optional state. Embedded alert statistics count campaign memberships, not distinct alerts across campaigns; optional absent statistics remain unknown. |
| `security_campaigns__organizations` | `organization` | All advertised pages of visible campaigns in the selected organization and optional state. Embedded alert statistics count campaign memberships, not distinct alerts across campaigns; optional absent statistics remain unknown. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `organization_id` | `BIGINT` | no |
| `organization_login` | `VARCHAR` | no |
| `campaign_number` | `BIGINT` | no |
| `created_at` | `TIMESTAMP WITH TIME ZONE` | no |
| `updated_at` | `TIMESTAMP WITH TIME ZONE` | no |
| `name` | `VARCHAR` | yes |
| `description` | `VARCHAR` | no |
| `published_at` | `TIMESTAMP WITH TIME ZONE` | yes |
| `ends_at` | `TIMESTAMP WITH TIME ZONE` | no |
| `closed_at` | `TIMESTAMP WITH TIME ZONE` | yes |
| `state` | `VARCHAR` | no |
| `contact_link` | `VARCHAR` | yes |
| `managers` | `STRUCT("name" VARCHAR, "email" VARCHAR, "login" VARCHAR, "id" BIGINT, "node_id" VARCHAR, "avatar_url" VARCHAR, "gravatar_id" VARCHAR, "url" VARCHAR, "html_url" VARCHAR, "followers_url" VARCHAR, "following_url" VARCHAR, "gists_url" VARCHAR, "starred_url" VARCHAR, "subscriptions_url" VARCHAR, "organizations_url" VARCHAR, "repos_url" VARCHAR, "events_url" VARCHAR, "received_events_url" VARCHAR, "type" VARCHAR, "site_admin" BOOLEAN, "starred_at" VARCHAR, "user_view_type" VARCHAR)[]` | no |
| `team_managers` | `STRUCT("id" BIGINT, "node_id" VARCHAR, "name" VARCHAR, "slug" VARCHAR, "description" VARCHAR, "privacy" VARCHAR, "notification_setting" VARCHAR, "permission" VARCHAR, "permissions" STRUCT("pull" BOOLEAN, "triage" BOOLEAN, "push" BOOLEAN, "maintain" BOOLEAN, "admin" BOOLEAN), "url" VARCHAR, "html_url" VARCHAR, "members_url" VARCHAR, "repositories_url" VARCHAR, "type" VARCHAR, "access_source" VARCHAR, "organization_id" BIGINT, "enterprise_id" BIGINT, "parent" STRUCT("id" BIGINT, "node_id" VARCHAR, "url" VARCHAR, "members_url" VARCHAR, "name" VARCHAR, "description" VARCHAR, "permission" VARCHAR, "privacy" VARCHAR, "notification_setting" VARCHAR, "html_url" VARCHAR, "repositories_url" VARCHAR, "slug" VARCHAR, "ldap_dn" VARCHAR, "type" VARCHAR, "organization_id" BIGINT, "enterprise_id" BIGINT))[]` | yes |
| `alert_stats` | `STRUCT("open_count" BIGINT, "closed_count" BIGINT, "in_progress_count" BIGINT)` | yes |
| `open_alert_count` | `BIGINT` | yes |
| `closed_alert_count` | `BIGINT` | yes |
| `in_progress_alert_count` | `BIGINT` | yes |

Approved metrics:

- `security_campaign_count`: Selected security_campaigns rows at the declared entity grain.
- `open_security_campaign_count`: Selected security_campaigns rows at the declared entity grain. Restricted to state=open.
- `closed_security_campaign_count`: Selected security_campaigns rows at the declared entity grain. Restricted to state=closed.
- `security_campaign_open_alert_occurrences`: Sum of reported campaign alert memberships; alerts can belong to more than one campaign. Missing statistics remain unknown.
- `security_campaign_closed_alert_occurrences`: Sum of reported campaign alert memberships; alerts can belong to more than one campaign. Missing statistics remain unknown.
- `security_campaign_in_progress_alert_occurrences`: Sum of reported campaign alert memberships; alerts can belong to more than one campaign. Missing statistics remain unknown.

### `code_quality_findings`

Canonical repository-qualified code-quality findings with typed rule, file location and plain/Markdown message. Code-quality severity is not a security vulnerability severity.

Grain: `repository_id`, `finding_number`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `code_quality_findings__lookup` | `code_quality_finding_number` | All visible findings in the selected repositories and optional state; exhausts advertised cursor Link pages. Finding numbers are repository-local. |
| `code_quality_findings__repositories` | `owner`, `repository`, `organization`, `repositories` | All visible findings in the selected repositories and optional state; exhausts advertised cursor Link pages. Finding numbers are repository-local. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `repository_id` | `BIGINT` | no |
| `repository` | `VARCHAR` | no |
| `finding_number` | `BIGINT` | no |
| `state` | `VARCHAR` | no |
| `url` | `VARCHAR` | no |
| `created_at` | `TIMESTAMP WITH TIME ZONE` | yes |
| `rule` | `STRUCT("id" VARCHAR, "title" VARCHAR, "description" VARCHAR, "help" VARCHAR, "severity" VARCHAR, "category" VARCHAR)` | no |
| `location` | `STRUCT("path" VARCHAR, "start_line" BIGINT, "start_column" BIGINT, "end_line" BIGINT, "end_column" BIGINT)` | no |
| `message` | `STRUCT("text" VARCHAR, "markdown" VARCHAR)` | no |
| `rule_id` | `VARCHAR` | no |
| `severity` | `VARCHAR` | no |
| `category` | `VARCHAR` | no |
| `path` | `VARCHAR` | no |

Approved metrics:

- `code_quality_finding_count`: Selected code_quality_findings rows at the declared entity grain.
- `code_quality_open_finding_count`: Selected code_quality_findings rows at the declared entity grain. Restricted to state=open.
- `code_quality_dismissed_finding_count`: Selected code_quality_findings rows at the declared entity grain. Restricted to state=dismissed.
- `code_quality_error_finding_count`: Selected code_quality_findings rows at the declared entity grain. Restricted to severity=error.
- `code_quality_warning_finding_count`: Selected code_quality_findings rows at the declared entity grain. Restricted to severity=warning.
- `code_quality_note_finding_count`: Selected code_quality_findings rows at the declared entity grain. Restricted to severity=note.
- `code_quality_none_finding_count`: Selected code_quality_findings rows at the declared entity grain. Restricted to severity=none.

### `dependabot_dismissal_requests`

Canonical GHEC Dependabot dismissal requests unified across organization, repository and exact alert scopes. Request ID, request number and alert number are distinct. Nested response reviewers remain distinct from the requester. selected_alert_number is populated only from the exact alert endpoint selector; source data.alert_number stays VARCHAR. Collection counts cover the explicit lookback window.

Grain: `repository_id`, `dismissal_request_id`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `dependabot_dismissal_requests__alerts` | `dependabot_alert_number` | Exact selected alert dismissal request. |
| `dependabot_dismissal_requests__organizations` | `organization` | All advertised pages of requests within the selected lookback window (repository default month; organization default day), with optional requester/reviewer/status filters. This is not complete historical request coverage. |
| `dependabot_dismissal_requests__repositories` | `owner`, `repository`, `organization`, `repositories` | All advertised pages of requests within the selected lookback window (repository default month; organization default day), with optional requester/reviewer/status filters. This is not complete historical request coverage. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `dismissal_request_id` | `BIGINT` | no |
| `dismissal_request_number` | `BIGINT` | yes |
| `repository_id` | `BIGINT` | no |
| `repository` | `VARCHAR` | no |
| `organization_id` | `BIGINT` | yes |
| `organization_name` | `VARCHAR` | yes |
| `requester_id` | `BIGINT` | yes |
| `requester_login` | `VARCHAR` | yes |
| `request_type` | `VARCHAR` | yes |
| `resource_identifier` | `VARCHAR` | yes |
| `status` | `VARCHAR` | yes |
| `requester_comment` | `VARCHAR` | yes |
| `expires_at` | `TIMESTAMP WITH TIME ZONE` | yes |
| `created_at` | `TIMESTAMP WITH TIME ZONE` | yes |
| `url` | `VARCHAR` | yes |
| `html_url` | `VARCHAR` | yes |
| `data` | `STRUCT("reason" VARCHAR, "alert_number" VARCHAR, "alert_title" VARCHAR)[]` | yes |
| `responses` | `STRUCT("id" BIGINT, "reviewer" STRUCT("actor_id" BIGINT, "actor_name" VARCHAR), "message" VARCHAR, "status" VARCHAR, "created_at" TIMESTAMP WITH TIME ZONE)[]` | yes |
| `repository_name` | `VARCHAR` | yes |
| `selected_alert_number` | `BIGINT` | yes |

Approved metrics:

- `dependabot_dismissal_request_count`: Requests in the selected lookback window (repository default month; organization default day), not all historical requests.
- `dependabot_pending_dismissal_request_count`: Selected dependabot_dismissal_requests rows at the declared entity grain. Restricted to status=pending. Collection lookback defaults to month for repositories and day for organizations, not complete history.
- `dependabot_approved_dismissal_request_count`: Selected dependabot_dismissal_requests rows at the declared entity grain. Restricted to status=approved. Collection lookback defaults to month for repositories and day for organizations, not complete history.
- `dependabot_denied_dismissal_request_count`: Selected dependabot_dismissal_requests rows at the declared entity grain. Restricted to status=denied. Collection lookback defaults to month for repositories and day for organizations, not complete history.
- `dependabot_expired_dismissal_request_count`: Selected dependabot_dismissal_requests rows at the declared entity grain. Restricted to status=expired. Collection lookback defaults to month for repositories and day for organizations, not complete history.

### `agent_tasks`

Canonical agent tasks identified by globally unique task ID. Repository and authenticated routes hydrate full details, including typed artifact alternatives and session observations. The listing defaults to non-archived tasks; archived tasks require explicit selection. Global responses supply optional numeric repository and actor IDs, without account logins or repository full names; unknown names stay NULL and no unsupported ID-to-name endpoint is invented. Creator, repository owner and nested session user are separate roles. Session billing units remain typed detail and are not combined into a usage metric.

Grain: `task_id`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `agent_tasks__lookup` | `agent_task_id` | One globally identified task. Supplying repository uses the repository-scoped API; omitting it uses the authenticated global task lookup. Listing filters are deliberately not accepted by lookup. |
| `agent_tasks__authenticated` | `authenticated_user` | Tasks visible to the authenticated user, defaulting to non-archived tasks; agent_task_archived=true selects archived tasks. Full detail is hydrated for every discovered task. Numeric repository IDs may be known while repository names remain unknown. |
| `agent_tasks__repositories` | `owner`, `repository`, `organization`, `repositories` | All selected repositories or repository cohorts, preserving every Link page. Default non-archived and explicitly selected archived tasks are separate API populations, with optional state, update-time and creator filters. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `repository` | `VARCHAR` | yes |
| `task_id` | `VARCHAR` | no |
| `repository_id` | `BIGINT` | yes |
| `repository_owner_id` | `BIGINT` | yes |
| `creator_id` | `BIGINT` | yes |
| `creator_type` | `VARCHAR` | yes |
| `user_collaborators` | `STRUCT("id" BIGINT)[]` | yes |
| `url` | `VARCHAR` | yes |
| `html_url` | `VARCHAR` | yes |
| `name` | `VARCHAR` | yes |
| `state` | `VARCHAR` | no |
| `session_count` | `BIGINT` | yes |
| `artifacts` | `STRUCT("provider" VARCHAR, "type" VARCHAR, "data" STRUCT("matched_types" VARCHAR[], "variant_1" STRUCT("global_id" VARCHAR, "id" BIGINT), "variant_2" STRUCT("base_ref" VARCHAR, "head_ref" VARCHAR)))[]` | yes |
| `archived_at` | `TIMESTAMP WITH TIME ZONE` | yes |
| `created_at` | `TIMESTAMP WITH TIME ZONE` | no |
| `updated_at` | `TIMESTAMP WITH TIME ZONE` | yes |
| `custom_agent_id` | `VARCHAR` | yes |
| `sessions` | `STRUCT("base_ref" VARCHAR, "completed_at" TIMESTAMP WITH TIME ZONE, "created_at" TIMESTAMP WITH TIME ZONE, "error" STRUCT("message" VARCHAR), "head_ref" VARCHAR, "id" VARCHAR, "model" VARCHAR, "name" VARCHAR, "owner" STRUCT("id" BIGINT), "prompt" VARCHAR, "repository" STRUCT("id" BIGINT), "state" VARCHAR, "task_id" VARCHAR, "updated_at" TIMESTAMP WITH TIME ZONE, "usage" STRUCT("amount" DOUBLE, "type" VARCHAR), "user" STRUCT("id" BIGINT))[]` | yes |
| `task_created_day` | `DATE` | no |

Approved metrics:

- `agent_task_count`: Enumerated task identities in the explicitly selected population.
- `completed_agent_task_count`: Tasks whose current API state is completed.
- `failed_agent_task_count`: Tasks whose current API state is failed.
- `in_progress_agent_task_count`: Tasks whose current API state is in_progress.
- `queued_agent_task_count`: Tasks whose current API state is queued.
- `waiting_for_user_agent_task_count`: Tasks whose current API state is waiting_for_user.
- `timed_out_agent_task_count`: Tasks whose current API state is timed_out.
- `cancelled_agent_task_count`: Tasks whose current API state is cancelled.
- `idle_agent_task_count`: Tasks whose current API state is idle.
- `reported_agent_session_count`: Sum of API-reported session counters, which may differ from nested session observations.
- `observed_agent_session_count`: Number of observed nested sessions; missing session arrays remain unknown, while empty arrays count zero.
- `agent_task_artifact_count`: Typed artifact associations returned with selected tasks, not distinct PRs or branches.
- `archived_agent_task_count`: Tasks with a reported archive timestamp; no inferred archive time.

### `gists`

Canonical current gists keyed by opaque gist ID. Typed file maps retain content, encoding and truncation. Owner is distinct from comment authors and revision committers. Pinned detail creation/update fields are unformatted strings and remain raw text; no unsupported timestamp conversion. Deprecated embedded forks/history are replaced by paginated child routes.

Grain: `gist_id`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `gists__lookup` | `gist_id` | One exact current gist, including secret gists visible to the caller. Missing/inaccessible hydration fails. |
| `gists__user` | `user` | Every public gist owned by the selected user, following advertised pages; each discovered ID is hydrated to canonical current detail. |
| `gists__forks` | `parent_gist_id` | All current fork gists of the selected parent across advertised pages; each discovered ID is hydrated. |
| `gists__public` | `gist_population`; `gist_population` in ["public"] | Public gists ordered by last update. Reaching the documented 3000-result ceiling fails rather than reporting the public universe as complete. |
| `gists__starred` | `gist_population`; `gist_population` in ["starred"] | Gists starred by the authenticated caller, across advertised pages, hydrated to canonical current detail. |
| `gists__visible` | Default | Authenticated caller-owned gists; anonymously GitHub returns public gists. Reaching 3000 rows is rejected conservatively because anonymous discovery has the public-feed ceiling. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `gist_id` | `VARCHAR` | no |
| `node_id` | `VARCHAR` | yes |
| `url` | `VARCHAR` | yes |
| `forks_url` | `VARCHAR` | yes |
| `commits_url` | `VARCHAR` | yes |
| `git_pull_url` | `VARCHAR` | yes |
| `git_push_url` | `VARCHAR` | yes |
| `html_url` | `VARCHAR` | yes |
| `files` | `MAP(VARCHAR, STRUCT("content" VARCHAR, "encoding" VARCHAR, "filename" VARCHAR, "language" VARCHAR, "raw_url" VARCHAR, "size" BIGINT, "truncated" BOOLEAN, "type" VARCHAR))` | yes |
| `public` | `BOOLEAN` | yes |
| `created_at_raw` | `VARCHAR` | yes |
| `updated_at_raw` | `VARCHAR` | yes |
| `description` | `VARCHAR` | yes |
| `comments` | `BIGINT` | yes |
| `comments_enabled` | `BOOLEAN` | yes |
| `comments_url` | `VARCHAR` | yes |
| `truncated` | `BOOLEAN` | yes |
| `owner_id` | `BIGINT` | yes |
| `owner_login` | `VARCHAR` | yes |
| `owner_type` | `VARCHAR` | yes |
| `owner` | `STRUCT("id" BIGINT, "login" VARCHAR, "node_id" VARCHAR, "type" VARCHAR, "html_url" VARCHAR)` | yes |
| `parent_gist_id` | `VARCHAR` | yes |
| `fork_of` | `STRUCT("id" VARCHAR, "node_id" VARCHAR, "url" VARCHAR, "owner" STRUCT("id" BIGINT, "login" VARCHAR, "node_id" VARCHAR, "type" VARCHAR, "html_url" VARCHAR), "created_at" TIMESTAMP WITH TIME ZONE, "updated_at" TIMESTAMP WITH TIME ZONE)` | yes |

Approved metrics:

- `gist_count`: Canonical current gists, regardless of lookup/discovery route. Secret visibility follows the caller. Counts exclude historical revisions.
- `public_gist_count`: Selected current gists explicitly marked public.
- `truncated_gist_count`: Selected gist snapshots flagged truncated by GitHub; content is never advertised as fully downloaded.

### `gist_comments`

Canonical gist-qualified comments with nullable author identity retained as NULL. Comment author roles do not stand in for gist ownership.

Grain: `gist_id`, `gist_comment_id`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `gist_comments__comment_lookup` | `gist_comment_id` | One exact comment in a current visible gist, with parent and comment identity validation. |
| `gist_comments__lookup` | `gist_id` | Within One exact current gist, including secret gists visible to the caller. Missing/inaccessible hydration fails. Child retrieval follows every advertised page and aborts on errors. |
| `gist_comments__user` | `user` | Within Every public gist owned by the selected user, following advertised pages; each discovered ID is hydrated to canonical current detail. Child retrieval follows every advertised page and aborts on errors. |
| `gist_comments__forks` | `parent_gist_id` | Within All current fork gists of the selected parent across advertised pages; each discovered ID is hydrated. Child retrieval follows every advertised page and aborts on errors. |
| `gist_comments__public` | `gist_population`; `gist_population` in ["public"] | Within Public gists ordered by last update. Reaching the documented 3000-result ceiling fails rather than reporting the public universe as complete. Child retrieval follows every advertised page and aborts on errors. |
| `gist_comments__starred` | `gist_population`; `gist_population` in ["starred"] | Within Gists starred by the authenticated caller, across advertised pages, hydrated to canonical current detail. Child retrieval follows every advertised page and aborts on errors. |
| `gist_comments__visible` | Default | Within Authenticated caller-owned gists; anonymously GitHub returns public gists. Reaching 3000 rows is rejected conservatively because anonymous discovery has the public-feed ceiling. Child retrieval follows every advertised page and aborts on errors. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `gist_id` | `VARCHAR` | no |
| `gist_comment_id` | `BIGINT` | no |
| `node_id` | `VARCHAR` | no |
| `url` | `VARCHAR` | no |
| `body` | `VARCHAR` | no |
| `author_id` | `BIGINT` | yes |
| `author_login` | `VARCHAR` | yes |
| `author` | `STRUCT("id" BIGINT, "login" VARCHAR, "node_id" VARCHAR, "type" VARCHAR, "html_url" VARCHAR)` | yes |
| `created_at` | `TIMESTAMP WITH TIME ZONE` | no |
| `updated_at` | `TIMESTAMP WITH TIME ZONE` | no |
| `author_association` | `VARCHAR` | no |

Approved metrics:

- `gist_comment_count`: Current comments belonging to selected gists; a deleted author remains a comment.

### `gist_revisions`

Gist commit identity, committer, changes and exact revision files in one canonical entity. Revisions retain immutable gist/SHA grain and typed file maps; current gist ownership is only traversal context. Optional exact SHA narrows after complete commit discovery.

Grain: `gist_id`, `revision_sha`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `gist_revisions__lookup` | `gist_id` | Within One exact current gist, including secret gists visible to the caller. Missing/inaccessible hydration fails. Child retrieval follows every advertised page and aborts on errors. |
| `gist_revisions__user` | `user` | Within Every public gist owned by the selected user, following advertised pages; each discovered ID is hydrated to canonical current detail. Child retrieval follows every advertised page and aborts on errors. |
| `gist_revisions__forks` | `parent_gist_id` | Within All current fork gists of the selected parent across advertised pages; each discovered ID is hydrated. Child retrieval follows every advertised page and aborts on errors. |
| `gist_revisions__public` | `gist_population`; `gist_population` in ["public"] | Within Public gists ordered by last update. Reaching the documented 3000-result ceiling fails rather than reporting the public universe as complete. Child retrieval follows every advertised page and aborts on errors. |
| `gist_revisions__starred` | `gist_population`; `gist_population` in ["starred"] | Within Gists starred by the authenticated caller, across advertised pages, hydrated to canonical current detail. Child retrieval follows every advertised page and aborts on errors. |
| `gist_revisions__visible` | Default | Within Authenticated caller-owned gists; anonymously GitHub returns public gists. Reaching 3000 rows is rejected conservatively because anonymous discovery has the public-feed ceiling. Child retrieval follows every advertised page and aborts on errors. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `gist_id` | `VARCHAR` | no |
| `revision_sha` | `VARCHAR` | no |
| `commit_url` | `VARCHAR` | no |
| `committed_at` | `TIMESTAMP WITH TIME ZONE` | no |
| `committer_id` | `BIGINT` | yes |
| `committer_login` | `VARCHAR` | yes |
| `committer` | `STRUCT("id" BIGINT, "login" VARCHAR, "node_id" VARCHAR, "type" VARCHAR, "html_url" VARCHAR)` | yes |
| `change_status` | `STRUCT("additions" BIGINT, "deletions" BIGINT, "total" BIGINT)` | no |
| `additions` | `BIGINT` | yes |
| `deletions` | `BIGINT` | yes |
| `total_changes` | `BIGINT` | yes |
| `files` | `MAP(VARCHAR, STRUCT("content" VARCHAR, "encoding" VARCHAR, "filename" VARCHAR, "language" VARCHAR, "raw_url" VARCHAR, "size" BIGINT, "truncated" BOOLEAN, "type" VARCHAR))` | yes |
| `truncated` | `BOOLEAN` | yes |
| `description` | `VARCHAR` | yes |

Approved metrics:

- `gist_revision_count`: Gist-qualified immutable revision identities discovered through the complete commit listing and hydrated by exact SHA; an absent optional SHA filter returns zero.
- `gist_revision_additions`: Reported line changes for selected gist revision records; missing upstream counters are not invented. Empty selected populations yield zero; an observed population with no reported values yields NULL. Mixed populations sum only reported values.
- `gist_revision_deletions`: Reported line changes for selected gist revision records; missing upstream counters are not invented. Empty selected populations yield zero; an observed population with no reported values yields NULL. Mixed populations sum only reported values.

### `gist_files`

Current gist-qualified file dictionary entries, with exact filename key, typed nullable value, encoding and truncation. Raw URLs are descriptive and never followed automatically. A missing files object fails, while an empty object yields zero entries.

Grain: `gist_id`, `filename`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `gist_files__lookup` | `gist_id` | Within One exact current gist, including secret gists visible to the caller. Missing/inaccessible hydration fails. Child retrieval follows every advertised page and aborts on errors. |
| `gist_files__user` | `user` | Within Every public gist owned by the selected user, following advertised pages; each discovered ID is hydrated to canonical current detail. Child retrieval follows every advertised page and aborts on errors. |
| `gist_files__forks` | `parent_gist_id` | Within All current fork gists of the selected parent across advertised pages; each discovered ID is hydrated. Child retrieval follows every advertised page and aborts on errors. |
| `gist_files__public` | `gist_population`; `gist_population` in ["public"] | Within Public gists ordered by last update. Reaching the documented 3000-result ceiling fails rather than reporting the public universe as complete. Child retrieval follows every advertised page and aborts on errors. |
| `gist_files__starred` | `gist_population`; `gist_population` in ["starred"] | Within Gists starred by the authenticated caller, across advertised pages, hydrated to canonical current detail. Child retrieval follows every advertised page and aborts on errors. |
| `gist_files__visible` | Default | Within Authenticated caller-owned gists; anonymously GitHub returns public gists. Reaching 3000 rows is rejected conservatively because anonymous discovery has the public-feed ceiling. Child retrieval follows every advertised page and aborts on errors. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `gist_id` | `VARCHAR` | no |
| `filename` | `VARCHAR` | no |
| `file` | `STRUCT("content" VARCHAR, "encoding" VARCHAR, "filename" VARCHAR, "language" VARCHAR, "raw_url" VARCHAR, "size" BIGINT, "truncated" BOOLEAN, "type" VARCHAR)` | yes |
| `declared_filename` | `VARCHAR` | yes |
| `media_type` | `VARCHAR` | yes |
| `language` | `VARCHAR` | yes |
| `raw_url` | `VARCHAR` | yes |
| `byte_size` | `BIGINT` | yes |
| `truncated` | `BOOLEAN` | yes |
| `content` | `VARCHAR` | yes |
| `encoding` | `VARCHAR` | yes |

Approved metrics:

- `gist_file_entry_count`: Current gist file dictionary entries. A nullable file value remains an entry; this count does not assert complete file content.
- `gist_file_bytes`: Reported byte sizes for returned current file entries; NULL sizes remain unknown and are not inferred from truncated content. Empty selected populations yield zero; an observed population with no reported values yields NULL. Mixed populations sum only reported values.

### `gist_star_observations`

Authenticated caller-qualified observations of gist star status. 204 means starred; 404 is the endpoint negative status and does not establish whether a target exists or is visible. Repeated invocations are current snapshots, not history.

Grain: `caller_id`, `gist_id`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `gist_star_observations__lookup` | `gist_id` | One current authenticated-caller star predicate for the exact requested target. No existence lookup precedes the predicate; 404 retains its documented negative status without asserting target existence. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `gist_id` | `VARCHAR` | no |
| `caller_id` | `BIGINT` | no |
| `status_code` | `BIGINT` | no |
| `caller_login` | `VARCHAR` | no |

Approved metrics:

- `gist_star_observation_count`: Current authenticated caller/gist star-status observations; not durable star-event history.
- `starred_gist_observation_count`: Observations for which GitHub returned the documented starred status. A 404 does not prove target existence or visibility.

### `codespaces`

Canonical Codespace instances across organization, organization-member, repository and authenticated-user scopes. Codespace owner is distinct from repository owner and billable owner. Machine capacity describes the configured machine and is not running utilization or billing consumption. Nullable machines and the API-declared Unknown state remain observable; undeclared state values fail pinned-schema validation. Repository relationship uses returned repository identity, without parsing incidental URLs.

Grain: `codespace_id`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `codespaces__lookup` | `codespace_name` | One Codespace visible through the authenticated-user lookup. |
| `codespaces__organization_members` | `user` | One organization member's visible Codespaces. |
| `codespaces__organizations` | `organization` | All Codespaces visible to the caller in the selected organization; not limited to the caller's own Codespaces. |
| `codespaces__authenticated` | `authenticated_user` | Authenticated caller's Codespaces, optionally filtered by numeric repository ID. |
| `codespaces__repositories` | `owner`, `repository`, `organization`, `repositories` | Authenticated caller's Codespaces for selected repositories, not every organization member's Codespaces. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `codespace_id` | `BIGINT` | no |
| `codespace_name` | `VARCHAR` | no |
| `repository_id` | `BIGINT` | no |
| `repository` | `VARCHAR` | no |
| `owner_id` | `BIGINT` | no |
| `owner_login` | `VARCHAR` | no |
| `billable_owner_id` | `BIGINT` | no |
| `billable_owner_login` | `VARCHAR` | no |
| `display_name` | `VARCHAR` | yes |
| `environment_id` | `VARCHAR` | yes |
| `owner` | `STRUCT("avatar_url" VARCHAR, "email" VARCHAR, "events_url" VARCHAR, "followers_url" VARCHAR, "following_url" VARCHAR, "gists_url" VARCHAR, "gravatar_id" VARCHAR, "html_url" VARCHAR, "id" BIGINT, "login" VARCHAR, "name" VARCHAR, "node_id" VARCHAR, "organizations_url" VARCHAR, "received_events_url" VARCHAR, "repos_url" VARCHAR, "site_admin" BOOLEAN, "starred_at" VARCHAR, "starred_url" VARCHAR, "subscriptions_url" VARCHAR, "type" VARCHAR, "url" VARCHAR, "user_view_type" VARCHAR)` | no |
| `billable_owner` | `STRUCT("avatar_url" VARCHAR, "email" VARCHAR, "events_url" VARCHAR, "followers_url" VARCHAR, "following_url" VARCHAR, "gists_url" VARCHAR, "gravatar_id" VARCHAR, "html_url" VARCHAR, "id" BIGINT, "login" VARCHAR, "name" VARCHAR, "node_id" VARCHAR, "organizations_url" VARCHAR, "received_events_url" VARCHAR, "repos_url" VARCHAR, "site_admin" BOOLEAN, "starred_at" VARCHAR, "starred_url" VARCHAR, "subscriptions_url" VARCHAR, "type" VARCHAR, "url" VARCHAR, "user_view_type" VARCHAR)` | no |
| `machine` | `STRUCT("cpus" BIGINT, "display_name" VARCHAR, "memory_in_bytes" BIGINT, "name" VARCHAR, "operating_system" VARCHAR, "prebuild_availability" VARCHAR, "storage_in_bytes" BIGINT)` | yes |
| `devcontainer_path` | `VARCHAR` | yes |
| `prebuild` | `BOOLEAN` | yes |
| `created_at` | `TIMESTAMP WITH TIME ZONE` | no |
| `updated_at` | `TIMESTAMP WITH TIME ZONE` | no |
| `last_used_at` | `TIMESTAMP WITH TIME ZONE` | no |
| `state` | `VARCHAR` | no |
| `url` | `VARCHAR` | no |
| `git_status` | `STRUCT("ahead" BIGINT, "behind" BIGINT, "has_uncommitted_changes" BOOLEAN, "has_unpushed_changes" BOOLEAN, "ref" VARCHAR)` | no |
| `location` | `VARCHAR` | no |
| `idle_timeout_minutes` | `BIGINT` | yes |
| `web_url` | `VARCHAR` | no |
| `machines_url` | `VARCHAR` | no |
| `start_url` | `VARCHAR` | no |
| `stop_url` | `VARCHAR` | no |
| `publish_url` | `VARCHAR` | yes |
| `pulls_url` | `VARCHAR` | yes |
| `recent_folders` | `VARCHAR[]` | no |
| `runtime_constraints` | `STRUCT("allowed_port_privacy_settings" VARCHAR[])` | yes |
| `pending_operation` | `BOOLEAN` | yes |
| `pending_operation_disabled_reason` | `VARCHAR` | yes |
| `idle_timeout_notice` | `VARCHAR` | yes |
| `retention_period_minutes` | `BIGINT` | yes |
| `retention_expires_at` | `TIMESTAMP WITH TIME ZONE` | yes |
| `last_known_stop_notice` | `VARCHAR` | yes |
| `machine_cpus` | `BIGINT` | yes |
| `machine_memory_bytes` | `BIGINT` | yes |
| `machine_storage_bytes` | `BIGINT` | yes |
| `codespace_created_day` | `DATE` | no |

Approved metrics:

- `codespace_count`: Enumerated Codespace instances.
- `available_codespace_count`: Codespaces reporting Available.
- `shutdown_codespace_count`: Codespaces reporting Shutdown.
- `configured_codespace_cpu_count`: Sum of configured machine cores, not utilization.
- `configured_codespace_memory_bytes`: Configured machine memory capacity.
- `configured_codespace_storage_bytes`: Configured machine storage capacity.
- `prebuilt_codespace_count`: Instances explicitly created from prebuilds.

### `codespace_machine_options`

Machine eligibility observations qualified by repository or Codespace context and machine name. Query inputs preserve location, ref and client-IP provenance; capacity is an offered configuration, not an allocated resource. Repository and Codespace availability may differ and must not be deduplicated by machine name alone.

Grain: `availability_scope`, `availability_key`, `machine_name`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `codespace_machine_options__codespaces` | `codespace_name` | Machine alternatives for one existing Codespace, including context-specific prebuild availability. |
| `codespace_machine_options__repositories` | `owner`, `repository`, `organization`, `repositories` | Selected repositories or repository cohort, using the authenticated caller for operational eligibility. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `repository_id` | `BIGINT` | no |
| `repository` | `VARCHAR` | no |
| `codespace_name` | `VARCHAR` | yes |
| `availability_scope` | `VARCHAR` | no |
| `availability_key` | `VARCHAR` | no |
| `codespace_ref` | `VARCHAR` | yes |
| `codespace_location` | `VARCHAR` | yes |
| `codespace_client_ip` | `VARCHAR` | yes |
| `machine_name` | `VARCHAR` | no |
| `display_name` | `VARCHAR` | no |
| `operating_system` | `VARCHAR` | no |
| `storage_in_bytes` | `BIGINT` | no |
| `memory_in_bytes` | `BIGINT` | no |
| `cpus` | `BIGINT` | no |
| `prebuild_availability` | `VARCHAR` | yes |
| `codespace_id` | `BIGINT` | yes |

Approved metrics:

- `codespace_machine_option_count`: Eligible machine configurations in the selected contexts.
- `ready_prebuild_machine_option_count`: Machine options reporting a ready prebuild.
- `offered_codespace_cpu_count`: Sum of offered cores across options, not allocated machine cores.

### `repository_devcontainers`

Repository devcontainer configurations visible to the authenticated caller. Paths qualify configuration identity within a repository; optional display labels are not keys.

Grain: `repository_id`, `devcontainer_path`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `repository_devcontainers__repositories` | `owner`, `repository`, `organization`, `repositories` | Selected repositories or repository cohort, using the authenticated caller for operational eligibility. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `repository_id` | `BIGINT` | no |
| `repository` | `VARCHAR` | no |
| `devcontainer_path` | `VARCHAR` | no |
| `name` | `VARCHAR` | yes |
| `display_name` | `VARCHAR` | yes |

Approved metrics:

- `repository_devcontainer_count`: Enumerated repository devcontainer paths.

### `codespace_creation_defaults`

Caller-specific preflight observations of defaults for creating a Codespace. This GET reads defaults without creating an instance. Absent defaults and unknown devcontainer paths remain NULL.

Grain: `repository_id`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `codespace_creation_defaults__repositories` | `owner`, `repository`, `organization`, `repositories` | Selected repositories or repository cohort, using the authenticated caller for operational eligibility. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `repository_id` | `BIGINT` | no |
| `repository` | `VARCHAR` | no |
| `codespace_ref` | `VARCHAR` | yes |
| `codespace_client_ip` | `VARCHAR` | yes |
| `billable_owner` | `STRUCT("avatar_url" VARCHAR, "email" VARCHAR, "events_url" VARCHAR, "followers_url" VARCHAR, "following_url" VARCHAR, "gists_url" VARCHAR, "gravatar_id" VARCHAR, "html_url" VARCHAR, "id" BIGINT, "login" VARCHAR, "name" VARCHAR, "node_id" VARCHAR, "organizations_url" VARCHAR, "received_events_url" VARCHAR, "repos_url" VARCHAR, "site_admin" BOOLEAN, "starred_at" VARCHAR, "starred_url" VARCHAR, "subscriptions_url" VARCHAR, "type" VARCHAR, "url" VARCHAR, "user_view_type" VARCHAR)` | yes |
| `default_location` | `VARCHAR` | yes |
| `default_devcontainer_path` | `VARCHAR` | yes |

Approved metrics:

- `codespace_creation_default_observation_count`: Returned repository preflight observations, including empty defaults.

### `codespace_devcontainer_permissions`

Operational permission-acceptance observations for a devcontainer at an exact repository reference. accepted describes the authenticated caller's existing acceptance and this read does not grant permissions.

Grain: `repository_id`, `codespace_ref`, `devcontainer_path`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `codespace_devcontainer_permissions__repositories` | `owner`, `repository`, `organization`, `repositories` | Selected repositories or repository cohort, using the authenticated caller for operational eligibility. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `repository_id` | `BIGINT` | no |
| `repository` | `VARCHAR` | no |
| `codespace_ref` | `VARCHAR` | no |
| `devcontainer_path` | `VARCHAR` | no |
| `accepted` | `BOOLEAN` | no |

Approved metrics:

- `codespace_devcontainer_permission_check_count`: Returned devcontainer permission observations.
- `accepted_devcontainer_permission_count`: Checks whose permissions the caller has accepted.

### `codespace_export_observations`

Export-status observations qualified by Codespace identity and requested export selector. The API makes reported export ID optional and documents latest as a selector; no durable export identity or export listing is invented. Empty response objects remain an observation with unknown status.

Grain: `codespace_id`, `codespace_export_id`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `codespace_export_observations__codespaces` | `codespace_name` | One requested Codespace export observation; latest observes the mutable latest-export alias, not all historical exports. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `codespace_id` | `BIGINT` | no |
| `repository_id` | `BIGINT` | no |
| `repository` | `VARCHAR` | no |
| `codespace_name` | `VARCHAR` | no |
| `codespace_export_id` | `VARCHAR` | no |
| `reported_export_id` | `VARCHAR` | yes |
| `state` | `VARCHAR` | yes |
| `completed_at` | `TIMESTAMP WITH TIME ZONE` | yes |
| `branch` | `VARCHAR` | yes |
| `sha` | `VARCHAR` | yes |
| `export_url` | `VARCHAR` | yes |
| `html_url` | `VARCHAR` | yes |
| `export_completed_day` | `DATE` | yes |

Approved metrics:

- `codespace_export_observation_count`: Requested export observations, including unknown status.
- `succeeded_codespace_export_count`: Export observations reporting succeeded.
- `failed_codespace_export_count`: Export observations reporting failed.

### `user_follow_relationships`

Canonical directed follow edges with stable ordered follower and followed identities. Incoming and outgoing listings unify at the same pair grain. Follows are not organization/team memberships; count distinct actors only by their explicit role.

Grain: `follower_id`, `followed_id`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `user_follow_relationships__followers` | `followed_user` | All advertised pages of directed follow relationships; each follower/followed pair counts once. The selected account is the followed role for followers, or follower role for following. |
| `user_follow_relationships__authenticated_followers` | `authenticated_user`, `follow_direction`; `follow_direction` in ["followers"] | All advertised pages of directed follow relationships; each follower/followed pair counts once. The selected account is the followed role for followers, or follower role for following. |
| `user_follow_relationships__following` | `follower_user` | All advertised pages of directed follow relationships; each follower/followed pair counts once. The selected account is the followed role for followers, or follower role for following. |
| `user_follow_relationships__authenticated_following` | `authenticated_user`, `follow_direction`; `follow_direction` in ["following"] | All advertised pages of directed follow relationships; each follower/followed pair counts once. The selected account is the followed role for followers, or follower role for following. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `follower_id` | `BIGINT` | no |
| `follower_login` | `VARCHAR` | no |
| `followed_id` | `BIGINT` | no |
| `followed_login` | `VARCHAR` | no |

Approved metrics:

- `user_follow_relationship_count`: Selected user_follow_relationships rows at the declared entity grain.
- `distinct_follower_count`: Distinct follower_id identities in the selected directed follow population; non-additive across groups.
- `distinct_followed_user_count`: Distinct followed_id identities in the selected directed follow population; non-additive across groups.

### `user_follow_checks`

Directed follow capability observations including negative results; 404 is never emitted as an actual following relationship.

Grain: `follower_id`, `followed_id`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `user_follow_checks__authenticated` | `authenticated_user` | One directed follow-status observation. 204 confirms a follow; 404 is a negative observation. Other HTTP failures propagate. |
| `user_follow_checks__accounts` | `follower_user`, `followed_user` | One directed follow-status observation. 204 confirms a follow; 404 is a negative observation. Other HTTP failures propagate. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `follower_id` | `BIGINT` | no |
| `follower_login` | `VARCHAR` | no |
| `followed_id` | `BIGINT` | no |
| `followed_login` | `VARCHAR` | no |
| `status_code` | `BIGINT` | no |

Approved metrics:

- `user_follow_check_count`: Selected user_follow_checks rows at the declared entity grain.
- `confirmed_user_follow_count`: Selected user_follow_checks observations satisfying the explicitly stated measure predicate.
- `absent_user_follow_count`: Selected user_follow_checks observations satisfying the explicitly stated measure predicate.

### `user_emails`

Email address identities belong to the authenticated account; public and complete credential-visible email endpoints are retrieval populations of the same entity.

Grain: `user_id`, `email`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `user_emails__all` | `user_email_population`; `user_email_population` in ["all"] | All advertised pages of the authenticated account's selected email population; primary and verified are independent properties. |
| `user_emails__public` | `user_email_population`; `user_email_population` in ["public"] | All advertised pages of the authenticated account's selected email population; primary and verified are independent properties. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `user_id` | `BIGINT` | no |
| `user_login` | `VARCHAR` | no |
| `email` | `VARCHAR` | no |
| `is_primary` | `BOOLEAN` | no |
| `is_verified` | `BOOLEAN` | no |
| `visibility` | `VARCHAR` | yes |

Approved metrics:

- `user_email_count`: Selected user_emails rows at the declared entity grain.
- `primary_user_email_count`: Selected user_emails observations satisfying the explicitly stated measure predicate.
- `verified_user_email_count`: Selected user_emails observations satisfying the explicitly stated measure predicate.

### `user_social_accounts`

External social account links, identified by stable GitHub account ID plus provider and URL. The API supplies no independent immutable social-link ID.

Grain: `user_id`, `provider`, `url`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `user_social_accounts__authenticated` | `authenticated_user` | All advertised pages of social account links for the selected identity. Providers are not unique keys; one provider can have multiple URLs. |
| `user_social_accounts__users` | `user` | All advertised pages of social account links for the selected identity. Providers are not unique keys; one provider can have multiple URLs. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `user_id` | `BIGINT` | no |
| `user_login` | `VARCHAR` | no |
| `provider` | `VARCHAR` | no |
| `url` | `VARCHAR` | no |

Approved metrics:

- `user_social_account_count`: Selected user_social_accounts rows at the declared entity grain.

### `user_context_observations`

Typed user hovercard context observations. Subject IDs stay opaque strings; none plus an empty subject ID identifies the explicit context-free scope. Messages are descriptions, not membership or permission assertions.

Grain: `user_id`, `subject_type`, `subject_id`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `user_context_observations__subjects` | `user_context_subject_type`, `user_context_subject_id` | One typed hovercard observation for the selected account and optional explicit context subject. An empty contexts list remains a valid observation. |
| `user_context_observations__users` | `user` | One typed hovercard observation for the selected account and optional explicit context subject. An empty contexts list remains a valid observation. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `user_id` | `BIGINT` | no |
| `user_login` | `VARCHAR` | no |
| `subject_type` | `VARCHAR` | no |
| `subject_id` | `VARCHAR` | no |
| `contexts` | `STRUCT("message" VARCHAR, "octicon" VARCHAR)[]` | no |

Approved metrics:

- `user_context_observation_count`: Selected user_context_observations rows at the declared entity grain.

### `copilot_report_metadata`

Available organization Copilot report metadata observations, qualified by organization, report population and the returned day/window. One-day endpoints can return204 when no report is available. download_links may contain multiple signed links; links are not users, usage events or completions. Downloaded payload schemas are not supplied by the pinned API, so this entity does not claim usage-row coverage and never follows arbitrary signed URLs automatically. Latest windows are response-derived and can overlap across snapshots.

Grain: `organization_id`, `report_kind`, `report_start_day`, `report_end_day`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `copilot_report_metadata__organization_day` | `copilot_report_kind`; `copilot_report_kind` in ["organization_day"] | Available organization_day report metadata only. Signed download URLs are returned as evidence; underlying usage rows and metrics are outside the pinned endpoint response contract. |
| `copilot_report_metadata__organization_latest` | `copilot_report_kind`; `copilot_report_kind` in ["organization_latest"] | Available organization_latest report metadata only. Signed download URLs are returned as evidence; underlying usage rows and metrics are outside the pinned endpoint response contract. |
| `copilot_report_metadata__repositories_day` | `copilot_report_kind`; `copilot_report_kind` in ["repositories_day"] | Available repositories_day report metadata only. Signed download URLs are returned as evidence; underlying usage rows and metrics are outside the pinned endpoint response contract. |
| `copilot_report_metadata__user_teams_day` | `copilot_report_kind`; `copilot_report_kind` in ["user_teams_day"] | Available user_teams_day report metadata only. Signed download URLs are returned as evidence; underlying usage rows and metrics are outside the pinned endpoint response contract. |
| `copilot_report_metadata__users_day` | `copilot_report_kind`; `copilot_report_kind` in ["users_day"] | Available users_day report metadata only. Signed download URLs are returned as evidence; underlying usage rows and metrics are outside the pinned endpoint response contract. |
| `copilot_report_metadata__users_latest` | `copilot_report_kind`; `copilot_report_kind` in ["users_latest"] | Available users_latest report metadata only. Signed download URLs are returned as evidence; underlying usage rows and metrics are outside the pinned endpoint response contract. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `organization_id` | `BIGINT` | no |
| `organization_login` | `VARCHAR` | no |
| `report_kind` | `VARCHAR` | no |
| `requested_day` | `DATE` | yes |
| `report_start_day` | `DATE` | no |
| `report_end_day` | `DATE` | no |
| `download_links` | `VARCHAR[]` | no |

Approved metrics:

- `available_copilot_report_count`: Available typed report metadata records;204 contributes zero.
- `copilot_report_download_link_count`: Signed download links advertised by available reports, not downloaded files or usage rows.

### `copilot_spaces`

Canonical Copilot Spaces across organization and user ownership, keyed by global Space ID. Owner kind/login/number preserve the supported retrieval direction; creator is a separate user role. Typed owner anyOf branches retain every matching alternative. resources_attributes retains every schema-declared inline resource metadata field; standalone resource metadata has a broader unbounded contract.

Grain: `space_id`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `copilot_spaces__lookup` | `copilot_space_number` | Selected owner and space population; preserve every advertised cursor/Link page and empty spaces. |
| `copilot_spaces__owners` | `organization`, `user` | Selected owner and space population; preserve every advertised cursor/Link page and empty spaces. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `space_owner_kind` | `VARCHAR` | no |
| `space_id` | `BIGINT` | no |
| `space_number` | `BIGINT` | no |
| `space_owner_id` | `BIGINT` | no |
| `space_owner_login` | `VARCHAR` | no |
| `owner` | `STRUCT("matched_types" VARCHAR[], "variant_1" STRUCT("avatar_url" VARCHAR, "email" VARCHAR, "events_url" VARCHAR, "followers_url" VARCHAR, "following_url" VARCHAR, "gists_url" VARCHAR, "gravatar_id" VARCHAR, "html_url" VARCHAR, "id" BIGINT, "login" VARCHAR, "name" VARCHAR, "node_id" VARCHAR, "organizations_url" VARCHAR, "received_events_url" VARCHAR, "repos_url" VARCHAR, "site_admin" BOOLEAN, "starred_at" VARCHAR, "starred_url" VARCHAR, "subscriptions_url" VARCHAR, "type" VARCHAR, "url" VARCHAR, "user_view_type" VARCHAR), "variant_2" STRUCT("avatar_url" VARCHAR, "description" VARCHAR, "events_url" VARCHAR, "hooks_url" VARCHAR, "id" BIGINT, "issues_url" VARCHAR, "login" VARCHAR, "members_url" VARCHAR, "node_id" VARCHAR, "public_members_url" VARCHAR, "repos_url" VARCHAR, "url" VARCHAR))` | no |
| `creator_id` | `BIGINT` | no |
| `creator_login` | `VARCHAR` | no |
| `creator` | `STRUCT("avatar_url" VARCHAR, "email" VARCHAR, "events_url" VARCHAR, "followers_url" VARCHAR, "following_url" VARCHAR, "gists_url" VARCHAR, "gravatar_id" VARCHAR, "html_url" VARCHAR, "id" BIGINT, "login" VARCHAR, "name" VARCHAR, "node_id" VARCHAR, "organizations_url" VARCHAR, "received_events_url" VARCHAR, "repos_url" VARCHAR, "site_admin" BOOLEAN, "starred_at" VARCHAR, "starred_url" VARCHAR, "subscriptions_url" VARCHAR, "type" VARCHAR, "url" VARCHAR, "user_view_type" VARCHAR)` | no |
| `name` | `VARCHAR` | no |
| `description` | `VARCHAR` | yes |
| `general_instructions` | `VARCHAR` | yes |
| `base_role` | `VARCHAR` | no |
| `created_at` | `TIMESTAMP WITH TIME ZONE` | no |
| `updated_at` | `TIMESTAMP WITH TIME ZONE` | no |
| `html_url` | `VARCHAR` | no |
| `api_url` | `VARCHAR` | no |
| `resources_attributes` | `STRUCT("copilot_chat_attachment_id" BIGINT, "created_at" TIMESTAMP WITH TIME ZONE, "id" BIGINT, "metadata" STRUCT("copilot_chat_attachment_id" BIGINT, "file_path" VARCHAR, "height" BIGINT, "media_type" VARCHAR, "name" VARCHAR, "number" BIGINT, "repository_id" BIGINT, "text" VARCHAR, "url" VARCHAR, "width" BIGINT), "resource_type" VARCHAR, "updated_at" TIMESTAMP WITH TIME ZONE)[]` | yes |

Approved metrics:

- `copilot_space_count`: Enumerated Copilot Space identities.
- `copilot_inline_resource_count`: Inline resource attribute observations, independently reported from standalone resource listing.

### `copilot_space_resources`

Resource identity and status envelopes attached to canonical Copilot Spaces. The standalone metadata object permits arbitrary keys and values without a pinned typed schema, so full dynamic metadata remains an explicit coverage gap; it is neither stringified nor guessed. The parent Space retains its schema-declared typed inline resources_attributes metadata. Resource types are classifications, not invented PR/repository identity relationships.

Grain: `space_id`, `resource_id`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `copilot_space_resources__lookup` | `copilot_space_resource_id` | Selected owner and space population; preserve every advertised cursor/Link page and empty spaces. |
| `copilot_space_resources__spaces` | `copilot_space_number` | Selected owner and space population; preserve every advertised cursor/Link page and empty spaces. |
| `copilot_space_resources__owners` | `organization`, `user` | Selected owner and space population; preserve every advertised cursor/Link page and empty spaces. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `space_id` | `BIGINT` | no |
| `space_owner_kind` | `VARCHAR` | no |
| `space_owner_login` | `VARCHAR` | no |
| `copilot_space_number` | `BIGINT` | no |
| `resource_id` | `BIGINT` | no |
| `resource_type` | `VARCHAR` | no |
| `copilot_chat_attachment_id` | `BIGINT` | yes |
| `created_at` | `TIMESTAMP WITH TIME ZONE` | no |
| `updated_at` | `TIMESTAMP WITH TIME ZONE` | no |

Approved metrics:

- `copilot_space_resource_count`: Enumerated Space/resource identities.
- `copilot_repository_resource_count`: Resources declared as repository references.
- `copilot_text_resource_count`: Resources declared as free text.

### `copilot_space_collaborators`

Copilot Space collaborator memberships qualified by actor type and actor ID. Typed user/team branches preserve business membership roles; team membership is not expanded into individual users. The pinned Team parent property supplies no value type and remains an explicit dynamic-value coverage gap.

Grain: `space_id`, `actor_type`, `collaborator_id`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `copilot_space_collaborators__spaces` | `copilot_space_number` | Selected owner and space population; preserve every advertised cursor/Link page and empty spaces. |
| `copilot_space_collaborators__owners` | `organization`, `user` | Selected owner and space population; preserve every advertised cursor/Link page and empty spaces. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `space_id` | `BIGINT` | no |
| `space_owner_kind` | `VARCHAR` | no |
| `space_owner_login` | `VARCHAR` | no |
| `copilot_space_number` | `BIGINT` | no |
| `collaborator_id` | `BIGINT` | no |
| `actor_type` | `VARCHAR` | no |
| `role` | `VARCHAR` | no |
| `collaborator` | `STRUCT("matched_types" VARCHAR[], "variant_1" STRUCT("avatar_url" VARCHAR, "email" VARCHAR, "events_url" VARCHAR, "followers_url" VARCHAR, "following_url" VARCHAR, "gists_url" VARCHAR, "gravatar_id" VARCHAR, "html_url" VARCHAR, "id" BIGINT, "login" VARCHAR, "name" VARCHAR, "node_id" VARCHAR, "organizations_url" VARCHAR, "received_events_url" VARCHAR, "repos_url" VARCHAR, "site_admin" BOOLEAN, "starred_at" VARCHAR, "starred_url" VARCHAR, "subscriptions_url" VARCHAR, "type" VARCHAR, "url" VARCHAR, "user_view_type" VARCHAR, "actor_type" VARCHAR, "role" VARCHAR), "variant_2" STRUCT("actor_type" VARCHAR, "role" VARCHAR, "id" BIGINT, "node_id" VARCHAR, "name" VARCHAR, "slug" VARCHAR, "type" VARCHAR, "description" VARCHAR, "privacy" VARCHAR, "notification_setting" VARCHAR, "url" VARCHAR, "html_url" VARCHAR, "members_url" VARCHAR, "repositories_url" VARCHAR, "organization_id" BIGINT))` | no |

Approved metrics:

- `copilot_space_collaborator_count`: Space/actor memberships; user and team IDs are separate domains.
- `copilot_user_collaborator_count`: Collaborator memberships declared User.
- `copilot_team_collaborator_count`: Collaborator memberships declared Team.

### `repository_stars`

Canonical current repository stars keyed by stable repository and stargazer account IDs. Repository and user routes express alternate retrieval directions of this one business relation.

Grain: `repository_id`, `stargazer_id`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `repository_stars__repositories` | `owner`, `repository`, `organization`, `repositories` | All current stars for each selected repository. Missing actor identity fails the source qualification; no anonymous row is silently dropped. |
| `repository_stars__user` | `user` | Current stars for the named user, restricted by GitHub profile/repository visibility. |
| `repository_stars__authenticated` | Default | Current stars for the authenticated caller, across advertised pages. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `repository_id` | `BIGINT` | no |
| `repository` | `VARCHAR` | no |
| `stargazer_id` | `BIGINT` | no |
| `stargazer_login` | `VARCHAR` | no |
| `starred_at` | `TIMESTAMP WITH TIME ZONE` | no |

Approved metrics:

- `repository_star_count`: Current repository/account relationships, with the same grain from repository and account retrieval directions. Not historical follow/unfollow events.

### `repository_watchers`

Canonical current repository watchers keyed by stable repository and watcher account IDs. Repository and user routes express alternate retrieval directions of this one business relation.

Grain: `repository_id`, `watcher_id`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `repository_watchers__repositories` | `owner`, `repository`, `organization`, `repositories` | All current watchers for each selected repository. Missing actor identity fails the source qualification; no anonymous row is silently dropped. |
| `repository_watchers__user` | `user` | Current watchers for the named user, restricted by GitHub profile/repository visibility. |
| `repository_watchers__authenticated` | Default | Current watchers for the authenticated caller, across advertised pages. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `repository_id` | `BIGINT` | no |
| `repository` | `VARCHAR` | no |
| `watcher_id` | `BIGINT` | no |
| `watcher_login` | `VARCHAR` | no |

Approved metrics:

- `repository_watcher_count`: Current repository/account relationships, with the same grain from repository and account retrieval directions. Not historical follow/unfollow events.

### `repository_star_counts`

Current repository star-count snapshots. Previously removed stars are excluded; repeated invocations are observations, not additive history.

Grain: `repository_id`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `repository_star_counts__repositories` | `owner`, `repository`, `organization`, `repositories` | Current repository star-count snapshots. Previously removed stars are excluded; repeated invocations are observations, not additive history. Follow all advertised pages; reaching the history API 100-page/3000-week boundary fails. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `repository_id` | `BIGINT` | no |
| `repository` | `VARCHAR` | no |
| `current_count` | `BIGINT` | no |

Approved metrics:

- `repository_star_count_observation_count`: Selected repository snapshots.
- `repository_current_stars`: Sum over distinct selected repositories in the current snapshot.

### `repository_star_history`

Repository-qualified calendar-week star creation buckets. Days start Sunday; API day/week boundaries need not align with UTC, so the supplied Unix week key is preserved without inventing UTC dates.

Grain: `repository_id`, `week_unix`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `repository_star_history__repositories` | `owner`, `repository`, `organization`, `repositories` | Repository-qualified calendar-week star creation buckets. Days start Sunday; API day/week boundaries need not align with UTC, so the supplied Unix week key is preserved without inventing UTC dates. Follow all advertised pages; reaching the history API 100-page/3000-week boundary fails. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `repository_id` | `BIGINT` | no |
| `repository` | `VARCHAR` | no |
| `week_unix` | `BIGINT` | no |
| `total` | `BIGINT` | no |
| `days` | `BIGINT[]` | no |

Approved metrics:

- `repository_star_week_count`: Selected repository/week buckets, including zero-count weeks.
- `repository_weekly_stars_created`: Reported stars created in the selected distinct repository/week buckets.

### `repository_subscriptions`

Authenticated caller-qualified repository subscription snapshots, distinct from public watcher identity relations. Typed state and timestamps retain the API response; missing lookups fail closed.

Grain: `caller_id`, `repository_id`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `repository_subscriptions__repositories` | `owner`, `repository`, `organization`, `repositories` | Caller subscription state for every selected repository. Missing/inaccessible subscription responses fail; a 404 is not silently interpreted as a universal negative. |
| `repository_subscriptions__authenticated` | Default | Every repository in the authenticated caller watched listing, hydrated to typed subscription state. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `repository_id` | `BIGINT` | no |
| `repository` | `VARCHAR` | no |
| `caller_id` | `BIGINT` | no |
| `caller_login` | `VARCHAR` | no |
| `subscribed` | `BOOLEAN` | no |
| `ignored` | `BOOLEAN` | no |
| `reason` | `VARCHAR` | yes |
| `created_at` | `TIMESTAMP WITH TIME ZONE` | no |
| `url` | `VARCHAR` | no |
| `repository_url` | `VARCHAR` | no |

Approved metrics:

- `repository_subscription_observation_count`: Caller/repository subscription snapshots returned successfully; not an inference about inaccessible repositories.
- `ignored_repository_subscription_count`: Selected repository subscription observations explicitly marked ignored.

### `repository_star_observations`

Current authenticated-caller repository star-status observations. No repository hydration precedes the predicate, preserving negative responses even when a target is inaccessible.

Grain: `caller_id`, `repository`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `repository_star_observations__lookup` | `repository` | One current authenticated-caller star predicate for the exact requested target. No existence lookup precedes the predicate; 404 retains its documented negative status without asserting target existence. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `repository` | `VARCHAR` | no |
| `caller_id` | `BIGINT` | no |
| `status_code` | `BIGINT` | no |
| `caller_login` | `VARCHAR` | no |

Approved metrics:

- `repository_star_observation_count`: Current caller/requested repository star-status observations. The requested owner/name is an observation locator, not a stable renamed repository identity.
- `starred_repository_observation_count`: The documented affirmative star status; 404 does not prove target existence or visibility.

### `notifications`

Canonical caller-qualified notifications, unifying account, repository and direct-thread retrieval. Subject URLs remain native descriptive text; raw timestamps remain VARCHAR because the pinned schema has no date-time format.

Grain: `caller_id`, `notification_thread_id`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `notifications__lookup` | `notification_thread_id` | One caller-visible notification thread by exact canonical decimal ID. |
| `notifications__repositories` | `owner`, `repository`, `organization`, `repositories` | All read and unread caller-visible notifications for the selected repository population, with optional API time and participation filters. |
| `notifications__authenticated` | Default | All read and unread caller-visible notifications across advertised pages, subject to API retention and optional filters. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `caller_id` | `BIGINT` | no |
| `caller_login` | `VARCHAR` | no |
| `notification_thread_id` | `VARCHAR` | no |
| `repository_id` | `BIGINT` | no |
| `repository` | `VARCHAR` | no |
| `subject` | `STRUCT("latest_comment_url" VARCHAR, "title" VARCHAR, "type" VARCHAR, "url" VARCHAR)` | no |
| `reason` | `VARCHAR` | no |
| `unread` | `BOOLEAN` | no |
| `updated_at_raw` | `VARCHAR` | no |
| `last_read_at_raw` | `VARCHAR` | yes |
| `url` | `VARCHAR` | no |
| `subscription_url` | `VARCHAR` | no |

Approved metrics:

- `notification_count`: Current caller-qualified notification threads, including read and unread entries.
- `unread_notification_count`: Selected caller notification threads explicitly marked unread.

### `notification_subscriptions`

Current caller-qualified notification subscription observations with automatic notification parent traversal. Nullable created_at remains NULL for responses without a subscription creation timestamp.

Grain: `caller_id`, `notification_thread_id`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `notification_subscriptions__lookup` | `notification_thread_id` | One caller-visible notification thread by exact canonical decimal ID. Hydrate the caller subscription for each discovered notification; missing/inaccessible responses fail. |
| `notification_subscriptions__repositories` | `owner`, `repository`, `organization`, `repositories` | All read and unread caller-visible notifications for the selected repository population, with optional API time and participation filters. Hydrate the caller subscription for each discovered notification; missing/inaccessible responses fail. |
| `notification_subscriptions__authenticated` | Default | All read and unread caller-visible notifications across advertised pages, subject to API retention and optional filters. Hydrate the caller subscription for each discovered notification; missing/inaccessible responses fail. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `caller_id` | `BIGINT` | no |
| `caller_login` | `VARCHAR` | no |
| `notification_thread_id` | `VARCHAR` | no |
| `subscribed` | `BOOLEAN` | no |
| `ignored` | `BOOLEAN` | no |
| `reason` | `VARCHAR` | yes |
| `created_at` | `TIMESTAMP WITH TIME ZONE` | yes |
| `url` | `VARCHAR` | no |
| `thread_url` | `VARCHAR` | yes |
| `repository_url` | `VARCHAR` | yes |

Approved metrics:

- `notification_subscription_observation_count`: Caller/thread subscription snapshots hydrated from the selected canonical notification population.
- `subscribed_notification_count`: Selected thread subscription snapshots explicitly marked subscribed.

### `activity_events`

Canonical GitHub activity event envelopes keyed by event ID, with separate event actor, repository and organization roles. Payload remains an explicit coverage gap: pinned payload variants overlap and include an unconstrained PublicEvent object, so no fabricated JSON schema or untyped payload is exposed. Only the API-retained recent timeline is modeled: current GitHub.com documentation limits it to the past 30 days and at most 300 events, with 30s-6h latency. Reaching 300 fails rather than advertising a complete recent population. Source: https://docs.github.com/en/rest/activity/events .

Grain: `event_id`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `activity_events__organization_authenticated` | `activity_view`; `activity_view` in ["organization_authenticated"] | organization authenticated event timeline. Only the API-retained recent timeline is modeled: current GitHub.com documentation limits it to the past 30 days and at most 300 events, with 30s-6h latency. Reaching 300 fails rather than advertising a complete recent population. Source: https://docs.github.com/en/rest/activity/events . |
| `activity_events__network` | `activity_view`; `activity_view` in ["network"] | network event timeline. Only the API-retained recent timeline is modeled: current GitHub.com documentation limits it to the past 30 days and at most 300 events, with 30s-6h latency. Reaching 300 fails rather than advertising a complete recent population. Source: https://docs.github.com/en/rest/activity/events . |
| `activity_events__performed_public` | `activity_view`; `activity_view` in ["performed_public"] | performed public event timeline. Only the API-retained recent timeline is modeled: current GitHub.com documentation limits it to the past 30 days and at most 300 events, with 30s-6h latency. Reaching 300 fails rather than advertising a complete recent population. Source: https://docs.github.com/en/rest/activity/events . |
| `activity_events__received` | `activity_view`; `activity_view` in ["received"] | received event timeline. Only the API-retained recent timeline is modeled: current GitHub.com documentation limits it to the past 30 days and at most 300 events, with 30s-6h latency. Reaching 300 fails rather than advertising a complete recent population. Source: https://docs.github.com/en/rest/activity/events . |
| `activity_events__received_public` | `activity_view`; `activity_view` in ["received_public"] | received public event timeline. Only the API-retained recent timeline is modeled: current GitHub.com documentation limits it to the past 30 days and at most 300 events, with 30s-6h latency. Reaching 300 fails rather than advertising a complete recent population. Source: https://docs.github.com/en/rest/activity/events . |
| `activity_events__performed` | `activity_view`; `activity_view` in ["performed"] | performed event timeline. Only the API-retained recent timeline is modeled: current GitHub.com documentation limits it to the past 30 days and at most 300 events, with 30s-6h latency. Reaching 300 fails rather than advertising a complete recent population. Source: https://docs.github.com/en/rest/activity/events . |
| `activity_events__user` | `user` | Named-user performed events; private visibility only applies to the same authenticated account. Only the API-retained recent timeline is modeled: current GitHub.com documentation limits it to the past 30 days and at most 300 events, with 30s-6h latency. Reaching 300 fails rather than advertising a complete recent population. Source: https://docs.github.com/en/rest/activity/events . |
| `activity_events__repository` | `repository` | repository event timeline. Only the API-retained recent timeline is modeled: current GitHub.com documentation limits it to the past 30 days and at most 300 events, with 30s-6h latency. Reaching 300 fails rather than advertising a complete recent population. Source: https://docs.github.com/en/rest/activity/events . |
| `activity_events__organization` | `organization` | organization event timeline. Only the API-retained recent timeline is modeled: current GitHub.com documentation limits it to the past 30 days and at most 300 events, with 30s-6h latency. Reaching 300 fails rather than advertising a complete recent population. Source: https://docs.github.com/en/rest/activity/events . |
| `activity_events__public` | Default | public event timeline. Only the API-retained recent timeline is modeled: current GitHub.com documentation limits it to the past 30 days and at most 300 events, with 30s-6h latency. Reaching 300 fails rather than advertising a complete recent population. Source: https://docs.github.com/en/rest/activity/events . |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `event_id` | `VARCHAR` | no |
| `event_type` | `VARCHAR` | yes |
| `actor_id` | `BIGINT` | no |
| `actor_login` | `VARCHAR` | no |
| `actor` | `STRUCT("avatar_url" VARCHAR, "display_login" VARCHAR, "gravatar_id" VARCHAR, "id" BIGINT, "login" VARCHAR, "url" VARCHAR)` | no |
| `repository_id` | `BIGINT` | no |
| `repository` | `VARCHAR` | no |
| `repository_url` | `VARCHAR` | no |
| `organization_id` | `BIGINT` | yes |
| `organization_login` | `VARCHAR` | yes |
| `organization_actor` | `STRUCT("avatar_url" VARCHAR, "display_login" VARCHAR, "gravatar_id" VARCHAR, "id" BIGINT, "login" VARCHAR, "url" VARCHAR)` | yes |
| `public` | `BOOLEAN` | no |
| `created_at` | `TIMESTAMP WITH TIME ZONE` | yes |

Approved metrics:

- `activity_event_count`: Distinct event envelopes within the explicitly retained API timeline; not complete issue, commit or release history.

### `activity_feed_observations`

Typed current-caller feed URLs and URI templates, preserving optional authenticated links and nested link structures. These are descriptive values and are never followed as arbitrary HTTP targets; repeated invocations are snapshots.

Grain: `api_host`.

| Column | SQL type | Nullable |
| --- | --- | --- |
| `api_host` | `VARCHAR` | no |
| `timeline_url` | `VARCHAR` | no |
| `user_url` | `VARCHAR` | no |
| `current_user_public_url` | `VARCHAR` | yes |
| `current_user_url` | `VARCHAR` | yes |
| `current_user_actor_url` | `VARCHAR` | yes |
| `current_user_organization_url` | `VARCHAR` | yes |
| `current_user_organization_urls` | `VARCHAR[]` | yes |
| `security_advisories_url` | `VARCHAR` | yes |
| `repository_discussions_url` | `VARCHAR` | yes |
| `repository_discussions_category_url` | `VARCHAR` | yes |
| `links` | `STRUCT("current_user" STRUCT("href" VARCHAR, "type" VARCHAR), "current_user_actor" STRUCT("href" VARCHAR, "type" VARCHAR), "current_user_organization" STRUCT("href" VARCHAR, "type" VARCHAR), "current_user_organizations" STRUCT("href" VARCHAR, "type" VARCHAR)[], "current_user_public" STRUCT("href" VARCHAR, "type" VARCHAR), "repository_discussions" STRUCT("href" VARCHAR, "type" VARCHAR), "repository_discussions_category" STRUCT("href" VARCHAR, "type" VARCHAR), "security_advisories" STRUCT("href" VARCHAR, "type" VARCHAR), "timeline" STRUCT("href" VARCHAR, "type" VARCHAR), "user" STRUCT("href" VARCHAR, "type" VARCHAR))` | no |

Approved metrics:

- `activity_feed_observation_count`: One API-host/current-caller feed discovery response in this invocation; not durable feed membership history.

### `organization_membership_checks`

Organization/account membership visibility observations, not actual membership rows. Public and credential-visible checks preserve their distinct scopes; a negative public result does not prove absence of private membership.

Grain: `organization_id`, `user_id`, `check_kind`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `organization_membership_checks__visible` | `organization_membership_check`; `organization_membership_check` in ["visible"] | One visibility-scoped membership check. 204 confirms membership in this visibility scope; 404 means not confirmed and can hide a private membership. Permission errors fail. |
| `organization_membership_checks__public` | `organization_membership_check`; `organization_membership_check` in ["public"] | One visibility-scoped membership check. 204 confirms membership in this visibility scope; 404 means not confirmed and can hide a private membership. Permission errors fail. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `organization_id` | `BIGINT` | no |
| `organization_login` | `VARCHAR` | no |
| `user_id` | `BIGINT` | no |
| `member_login` | `VARCHAR` | no |
| `check_kind` | `VARCHAR` | no |
| `status_code` | `BIGINT` | no |

Approved metrics:

- `organization_membership_check_count`: Selected membership visibility observations including unconfirmed results.
- `confirmed_organization_membership_check_count`: Membership confirmed under the explicitly selected endpoint visibility; no claim about hidden private membership.
- `unconfirmed_organization_membership_check_count`: Membership not confirmed under the explicitly selected endpoint visibility; no claim about hidden private membership.

### `search_code_hits`

Query-qualified code search hit observations. Grain combines the exact query with canonical returned identity; ordering and search-mode selectors define the invocation population. Result position is response order across pages, not durable identity. Total count and incomplete_results are exposed per returned hit and are not additive facts. A partial response, changed count, or 1000-result API cap prevents successful completion. Optional text-match fields remain typed when returned; this route does not request highlighted-media enrichment. Search covers only indexed files smaller than 384 KB on default branches and requires authentication; it is not a repository contents inventory.

Grain: `search_query`, `repository_id`, `file_path`, `blob_sha`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `search_code_hits__query` | `search_query` | One exact GitHub query population under the supplied API sort/search-mode/repository selectors. Every advertised page must report complete results and a stable total_count matching all emitted hits. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `search_query` | `VARCHAR` | no |
| `result_position` | `BIGINT` | no |
| `reported_total_count` | `BIGINT` | no |
| `incomplete_results` | `BOOLEAN` | no |
| `repository_id` | `BIGINT` | no |
| `repository` | `VARCHAR` | no |
| `repository_metadata` | `STRUCT("id" BIGINT, "node_id" VARCHAR, "name" VARCHAR, "full_name" VARCHAR, "private" BOOLEAN, "html_url" VARCHAR, "description" VARCHAR, "owner" STRUCT("id" BIGINT, "login" VARCHAR, "type" VARCHAR))` | no |
| `file_name` | `VARCHAR` | no |
| `file_path` | `VARCHAR` | no |
| `blob_sha` | `VARCHAR` | no |
| `url` | `VARCHAR` | no |
| `git_url` | `VARCHAR` | no |
| `html_url` | `VARCHAR` | no |
| `score` | `DOUBLE` | no |
| `file_size` | `BIGINT` | yes |
| `language` | `VARCHAR` | yes |
| `last_modified_at` | `TIMESTAMP WITH TIME ZONE` | yes |
| `line_numbers` | `VARCHAR[]` | yes |
| `text_matches` | `STRUCT("fragment" VARCHAR, "matches" STRUCT("indices" BIGINT[], "text" VARCHAR)[], "object_type" VARCHAR, "object_url" VARCHAR, "property" VARCHAR)[]` | yes |

Approved metrics:

- `search_code_hit_count`: Query-qualified code hits in one complete API response population, not a count of all GitHub code.
- `search_code_hit_max_score`: Maximum upstream relevance score in this selected query population; scores are not additive and are not comparable across different query kinds or invocations.

### `search_commit_hits`

Query-qualified commits search hit observations. Grain combines the exact query with canonical returned identity; ordering and search-mode selectors define the invocation population. Result position is response order across pages, not durable identity. Total count and incomplete_results are exposed per returned hit and are not additive facts. A partial response, changed count, or 1000-result API cap prevents successful completion. Optional text-match fields remain typed when returned; this route does not request highlighted-media enrichment. The API searches commits on default branches; commit signatures are distinct from nullable GitHub author-account identity.

Grain: `search_query`, `repository_id`, `commit_sha`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `search_commit_hits__query` | `search_query` | One exact GitHub query population under the supplied API sort/search-mode/repository selectors. Every advertised page must report complete results and a stable total_count matching all emitted hits. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `search_query` | `VARCHAR` | no |
| `result_position` | `BIGINT` | no |
| `reported_total_count` | `BIGINT` | no |
| `incomplete_results` | `BOOLEAN` | no |
| `repository_id` | `BIGINT` | no |
| `repository` | `VARCHAR` | no |
| `repository_metadata` | `STRUCT("id" BIGINT, "node_id" VARCHAR, "name" VARCHAR, "full_name" VARCHAR, "private" BOOLEAN, "html_url" VARCHAR, "description" VARCHAR, "owner" STRUCT("id" BIGINT, "login" VARCHAR, "type" VARCHAR))` | no |
| `commit_sha` | `VARCHAR` | no |
| `commit_node_id` | `VARCHAR` | no |
| `url` | `VARCHAR` | no |
| `html_url` | `VARCHAR` | no |
| `comments_url` | `VARCHAR` | no |
| `commit` | `STRUCT("author" STRUCT("date" TIMESTAMP WITH TIME ZONE, "email" VARCHAR, "name" VARCHAR), "comment_count" BIGINT, "committer" STRUCT("date" TIMESTAMP WITH TIME ZONE, "email" VARCHAR, "name" VARCHAR), "message" VARCHAR, "tree" STRUCT("sha" VARCHAR, "url" VARCHAR), "url" VARCHAR, "verification" STRUCT("payload" VARCHAR, "reason" VARCHAR, "signature" VARCHAR, "verified" BOOLEAN, "verified_at" VARCHAR))` | no |
| `parents` | `STRUCT("html_url" VARCHAR, "sha" VARCHAR, "url" VARCHAR)[]` | no |
| `score` | `DOUBLE` | no |
| `author_account` | `STRUCT("id" BIGINT, "node_id" VARCHAR, "login" VARCHAR, "type" VARCHAR, "html_url" VARCHAR)` | yes |
| `committer_signature` | `STRUCT("date" TIMESTAMP WITH TIME ZONE, "email" VARCHAR, "name" VARCHAR)` | yes |
| `text_matches` | `STRUCT("fragment" VARCHAR, "matches" STRUCT("indices" BIGINT[], "text" VARCHAR)[], "object_type" VARCHAR, "object_url" VARCHAR, "property" VARCHAR)[]` | yes |

Approved metrics:

- `search_commit_hit_count`: Query-qualified commits hits in one complete API response population, not a count of all GitHub commits.
- `search_commit_hit_max_score`: Maximum upstream relevance score in this selected query population; scores are not additive and are not comparable across different query kinds or invocations.

### `search_issue_hits`

Query-qualified issues search hit observations. Grain combines the exact query with canonical returned identity; ordering and search-mode selectors define the invocation population. Result position is response order across pages, not durable identity. Total count and incomplete_results are exposed per returned hit and are not additive facts. A partial response, changed count, or 1000-result API cap prevents successful completion. Optional text-match fields remain typed when returned; this route does not request highlighted-media enrichment. Typed node hydration distinguishes Issue and PullRequest and obtains current repository identity without parsing or following URLs. Requested mode, performed mode and lexical fallback reasons are distinct. Recursive app/comment details remain available through canonical detail entities rather than guessed search projections.

Grain: `search_query`, `node_id`, `performed_search_type`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `search_issue_hits__query` | `search_query` | One exact GitHub query population under the supplied API sort/search-mode/repository selectors. Every advertised page must report complete results and a stable total_count matching all emitted hits. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `search_query` | `VARCHAR` | no |
| `result_position` | `BIGINT` | no |
| `reported_total_count` | `BIGINT` | no |
| `incomplete_results` | `BOOLEAN` | no |
| `issue_search_type` | `VARCHAR` | yes |
| `issue_advanced_search` | `VARCHAR` | yes |
| `performed_search_type` | `VARCHAR` | no |
| `lexical_fallback_reason` | `VARCHAR[]` | yes |
| `url` | `VARCHAR` | no |
| `repository_url` | `VARCHAR` | no |
| `labels_url` | `VARCHAR` | no |
| `comments_url` | `VARCHAR` | no |
| `events_url` | `VARCHAR` | no |
| `html_url` | `VARCHAR` | no |
| `issue_database_id` | `BIGINT` | no |
| `node_id` | `VARCHAR` | no |
| `indexed_number` | `BIGINT` | no |
| `title` | `VARCHAR` | no |
| `locked` | `BOOLEAN` | no |
| `active_lock_reason` | `VARCHAR` | yes |
| `assignees` | `STRUCT("id" BIGINT, "node_id" VARCHAR, "login" VARCHAR, "type" VARCHAR, "html_url" VARCHAR)[]` | yes |
| `user` | `STRUCT("id" BIGINT, "node_id" VARCHAR, "login" VARCHAR, "type" VARCHAR, "html_url" VARCHAR)` | yes |
| `labels` | `STRUCT("archived_at" TIMESTAMP WITH TIME ZONE, "archived_by" STRUCT("avatar_url" VARCHAR, "email" VARCHAR, "events_url" VARCHAR, "followers_url" VARCHAR, "following_url" VARCHAR, "gists_url" VARCHAR, "gravatar_id" VARCHAR, "html_url" VARCHAR, "id" BIGINT, "login" VARCHAR, "name" VARCHAR, "node_id" VARCHAR, "organizations_url" VARCHAR, "received_events_url" VARCHAR, "repos_url" VARCHAR, "site_admin" BOOLEAN, "starred_at" VARCHAR, "starred_url" VARCHAR, "subscriptions_url" VARCHAR, "type" VARCHAR, "url" VARCHAR, "user_view_type" VARCHAR), "color" VARCHAR, "default" BOOLEAN, "description" VARCHAR, "id" BIGINT, "name" VARCHAR, "node_id" VARCHAR, "url" VARCHAR)[]` | no |
| `sub_issues_summary` | `STRUCT("completed" BIGINT, "percent_completed" BIGINT, "total" BIGINT)` | yes |
| `issue_dependencies_summary` | `STRUCT("blocked_by" BIGINT, "blocking" BIGINT, "total_blocked_by" BIGINT, "total_blocking" BIGINT)` | yes |
| `issue_field_values` | `STRUCT("data_type" VARCHAR, "issue_field_id" BIGINT, "issue_field_name" VARCHAR, "multi_select_options" STRUCT("color" VARCHAR, "id" BIGINT, "name" VARCHAR)[], "node_id" VARCHAR, "single_select_option" STRUCT("color" VARCHAR, "id" BIGINT, "name" VARCHAR), "value" STRUCT("matched_types" VARCHAR[], "variant_1" VARCHAR, "variant_2" DOUBLE, "variant_3" BIGINT))[]` | yes |
| `state` | `VARCHAR` | no |
| `state_reason` | `VARCHAR` | yes |
| `assignee` | `STRUCT("id" BIGINT, "node_id" VARCHAR, "login" VARCHAR, "type" VARCHAR, "html_url" VARCHAR)` | yes |
| `milestone` | `STRUCT("closed_at" TIMESTAMP WITH TIME ZONE, "closed_issues" BIGINT, "created_at" TIMESTAMP WITH TIME ZONE, "creator" STRUCT("avatar_url" VARCHAR, "email" VARCHAR, "events_url" VARCHAR, "followers_url" VARCHAR, "following_url" VARCHAR, "gists_url" VARCHAR, "gravatar_id" VARCHAR, "html_url" VARCHAR, "id" BIGINT, "login" VARCHAR, "name" VARCHAR, "node_id" VARCHAR, "organizations_url" VARCHAR, "received_events_url" VARCHAR, "repos_url" VARCHAR, "site_admin" BOOLEAN, "starred_at" VARCHAR, "starred_url" VARCHAR, "subscriptions_url" VARCHAR, "type" VARCHAR, "url" VARCHAR, "user_view_type" VARCHAR), "description" VARCHAR, "due_on" TIMESTAMP WITH TIME ZONE, "html_url" VARCHAR, "id" BIGINT, "labels_url" VARCHAR, "node_id" VARCHAR, "number" BIGINT, "open_issues" BIGINT, "state" VARCHAR, "title" VARCHAR, "updated_at" TIMESTAMP WITH TIME ZONE, "url" VARCHAR)` | yes |
| `comments` | `BIGINT` | no |
| `created_at` | `TIMESTAMP WITH TIME ZONE` | no |
| `updated_at` | `TIMESTAMP WITH TIME ZONE` | no |
| `closed_at` | `TIMESTAMP WITH TIME ZONE` | yes |
| `text_matches` | `STRUCT("fragment" VARCHAR, "matches" STRUCT("indices" BIGINT[], "text" VARCHAR)[], "object_type" VARCHAR, "object_url" VARCHAR, "property" VARCHAR)[]` | yes |
| `pull_request` | `STRUCT("diff_url" VARCHAR, "html_url" VARCHAR, "merged_at" TIMESTAMP WITH TIME ZONE, "patch_url" VARCHAR, "url" VARCHAR)` | yes |
| `body` | `VARCHAR` | yes |
| `score` | `DOUBLE` | no |
| `author_association` | `VARCHAR` | no |
| `draft` | `BOOLEAN` | yes |
| `body_html` | `VARCHAR` | yes |
| `body_text` | `VARCHAR` | yes |
| `timeline_url` | `VARCHAR` | yes |
| `issue_type` | `STRUCT("color" VARCHAR, "created_at" TIMESTAMP WITH TIME ZONE, "description" VARCHAR, "id" BIGINT, "is_enabled" BOOLEAN, "name" VARCHAR, "node_id" VARCHAR, "updated_at" TIMESTAMP WITH TIME ZONE)` | yes |
| `reactions` | `STRUCT("+1" BIGINT, "-1" BIGINT, "confused" BIGINT, "eyes" BIGINT, "heart" BIGINT, "hooray" BIGINT, "laugh" BIGINT, "rocket" BIGINT, "total_count" BIGINT, "url" VARCHAR)` | yes |
| `subject_kind` | `VARCHAR` | no |
| `repository_id` | `BIGINT` | yes |
| `repository` | `VARCHAR` | no |
| `number` | `BIGINT` | no |
| `repository_node_id` | `VARCHAR` | no |

Approved metrics:

- `search_issue_hit_count`: Query-qualified issues hits in one complete API response population, not a count of all GitHub issues.
- `search_issue_hit_max_score`: Maximum upstream relevance score in this selected query population; scores are not additive and are not comparable across different query kinds or invocations.

### `search_label_hits`

Query-qualified labels search hit observations. Grain combines the exact query with canonical returned identity; ordering and search-mode selectors define the invocation population. Result position is response order across pages, not durable identity. Total count and incomplete_results are exposed per returned hit and are not additive facts. A partial response, changed count, or 1000-result API cap prevents successful completion. Optional text-match fields remain typed when returned; this route does not request highlighted-media enrichment.

Grain: `search_query`, `repository_id`, `label_id`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `search_label_hits__query` | `search_query` | One exact GitHub query population under the supplied API sort/search-mode/repository selectors. Every advertised page must report complete results and a stable total_count matching all emitted hits. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `search_query` | `VARCHAR` | no |
| `result_position` | `BIGINT` | no |
| `reported_total_count` | `BIGINT` | no |
| `incomplete_results` | `BOOLEAN` | no |
| `repository_id` | `BIGINT` | no |
| `label_id` | `BIGINT` | no |
| `label_node_id` | `VARCHAR` | no |
| `url` | `VARCHAR` | no |
| `name` | `VARCHAR` | no |
| `color` | `VARCHAR` | no |
| `is_default` | `BOOLEAN` | no |
| `description` | `VARCHAR` | yes |
| `archived_at` | `TIMESTAMP WITH TIME ZONE` | yes |
| `archived_by` | `STRUCT("id" BIGINT, "node_id" VARCHAR, "login" VARCHAR, "type" VARCHAR, "html_url" VARCHAR)` | yes |
| `score` | `DOUBLE` | no |
| `text_matches` | `STRUCT("fragment" VARCHAR, "matches" STRUCT("indices" BIGINT[], "text" VARCHAR)[], "object_type" VARCHAR, "object_url" VARCHAR, "property" VARCHAR)[]` | yes |
| `repository` | `VARCHAR` | no |

Approved metrics:

- `search_label_hit_count`: Query-qualified labels hits in one complete API response population, not a count of all GitHub labels.
- `search_label_hit_max_score`: Maximum upstream relevance score in this selected query population; scores are not additive and are not comparable across different query kinds or invocations.

### `search_repository_hits`

Query-qualified repositories search hit observations. Grain combines the exact query with canonical returned identity; ordering and search-mode selectors define the invocation population. Result position is response order across pages, not durable identity. Total count and incomplete_results are exposed per returned hit and are not additive facts. A partial response, changed count, or 1000-result API cap prevents successful completion. Optional text-match fields remain typed when returned; this route does not request highlighted-media enrichment.

Grain: `search_query`, `repository_id`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `search_repository_hits__query` | `search_query` | One exact GitHub query population under the supplied API sort/search-mode/repository selectors. Every advertised page must report complete results and a stable total_count matching all emitted hits. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `search_query` | `VARCHAR` | no |
| `result_position` | `BIGINT` | no |
| `reported_total_count` | `BIGINT` | no |
| `incomplete_results` | `BOOLEAN` | no |
| `repository_id` | `BIGINT` | no |
| `node_id` | `VARCHAR` | no |
| `name` | `VARCHAR` | no |
| `repository` | `VARCHAR` | no |
| `owner` | `STRUCT("id" BIGINT, "node_id" VARCHAR, "login" VARCHAR, "type" VARCHAR, "html_url" VARCHAR)` | yes |
| `private` | `BOOLEAN` | no |
| `html_url` | `VARCHAR` | no |
| `description` | `VARCHAR` | yes |
| `fork` | `BOOLEAN` | no |
| `url` | `VARCHAR` | no |
| `created_at` | `TIMESTAMP WITH TIME ZONE` | no |
| `updated_at` | `TIMESTAMP WITH TIME ZONE` | no |
| `pushed_at` | `TIMESTAMP WITH TIME ZONE` | no |
| `homepage` | `VARCHAR` | yes |
| `size` | `BIGINT` | no |
| `stargazers_count` | `BIGINT` | no |
| `watchers_count` | `BIGINT` | no |
| `language` | `VARCHAR` | yes |
| `forks_count` | `BIGINT` | no |
| `open_issues_count` | `BIGINT` | no |
| `master_branch` | `VARCHAR` | yes |
| `default_branch` | `VARCHAR` | no |
| `score` | `DOUBLE` | no |
| `forks_url` | `VARCHAR` | no |
| `keys_url` | `VARCHAR` | no |
| `collaborators_url` | `VARCHAR` | no |
| `teams_url` | `VARCHAR` | no |
| `hooks_url` | `VARCHAR` | no |
| `issue_events_url` | `VARCHAR` | no |
| `events_url` | `VARCHAR` | no |
| `assignees_url` | `VARCHAR` | no |
| `branches_url` | `VARCHAR` | no |
| `tags_url` | `VARCHAR` | no |
| `blobs_url` | `VARCHAR` | no |
| `git_tags_url` | `VARCHAR` | no |
| `git_refs_url` | `VARCHAR` | no |
| `trees_url` | `VARCHAR` | no |
| `statuses_url` | `VARCHAR` | no |
| `languages_url` | `VARCHAR` | no |
| `stargazers_url` | `VARCHAR` | no |
| `contributors_url` | `VARCHAR` | no |
| `subscribers_url` | `VARCHAR` | no |
| `subscription_url` | `VARCHAR` | no |
| `commits_url` | `VARCHAR` | no |
| `git_commits_url` | `VARCHAR` | no |
| `comments_url` | `VARCHAR` | no |
| `issue_comment_url` | `VARCHAR` | no |
| `contents_url` | `VARCHAR` | no |
| `compare_url` | `VARCHAR` | no |
| `merges_url` | `VARCHAR` | no |
| `archive_url` | `VARCHAR` | no |
| `downloads_url` | `VARCHAR` | no |
| `issues_url` | `VARCHAR` | no |
| `pulls_url` | `VARCHAR` | no |
| `milestones_url` | `VARCHAR` | no |
| `notifications_url` | `VARCHAR` | no |
| `labels_url` | `VARCHAR` | no |
| `releases_url` | `VARCHAR` | no |
| `deployments_url` | `VARCHAR` | no |
| `git_url` | `VARCHAR` | no |
| `ssh_url` | `VARCHAR` | no |
| `clone_url` | `VARCHAR` | no |
| `svn_url` | `VARCHAR` | no |
| `forks` | `BIGINT` | no |
| `open_issues` | `BIGINT` | no |
| `watchers` | `BIGINT` | no |
| `topics` | `VARCHAR[]` | yes |
| `mirror_url` | `VARCHAR` | yes |
| `has_issues` | `BOOLEAN` | no |
| `has_projects` | `BOOLEAN` | no |
| `has_pages` | `BOOLEAN` | no |
| `has_wiki` | `BOOLEAN` | no |
| `has_downloads` | `BOOLEAN` | no |
| `has_discussions` | `BOOLEAN` | yes |
| `has_pull_requests` | `BOOLEAN` | yes |
| `pull_request_creation_policy` | `VARCHAR` | yes |
| `archived` | `BOOLEAN` | no |
| `disabled` | `BOOLEAN` | no |
| `visibility` | `VARCHAR` | yes |
| `license` | `STRUCT("html_url" VARCHAR, "key" VARCHAR, "name" VARCHAR, "node_id" VARCHAR, "spdx_id" VARCHAR, "url" VARCHAR)` | yes |
| `permissions` | `STRUCT("admin" BOOLEAN, "maintain" BOOLEAN, "pull" BOOLEAN, "push" BOOLEAN, "triage" BOOLEAN)` | yes |
| `text_matches` | `STRUCT("fragment" VARCHAR, "matches" STRUCT("indices" BIGINT[], "text" VARCHAR)[], "object_type" VARCHAR, "object_url" VARCHAR, "property" VARCHAR)[]` | yes |
| `allow_merge_commit` | `BOOLEAN` | yes |
| `allow_squash_merge` | `BOOLEAN` | yes |
| `allow_rebase_merge` | `BOOLEAN` | yes |
| `allow_auto_merge` | `BOOLEAN` | yes |
| `delete_branch_on_merge` | `BOOLEAN` | yes |
| `allow_forking` | `BOOLEAN` | yes |
| `is_template` | `BOOLEAN` | yes |
| `web_commit_signoff_required` | `BOOLEAN` | yes |

Approved metrics:

- `search_repository_hit_count`: Query-qualified repositories hits in one complete API response population, not a count of all GitHub repositories.
- `search_repository_hit_max_score`: Maximum upstream relevance score in this selected query population; scores are not additive and are not comparable across different query kinds or invocations.

### `search_topic_hits`

Query-qualified topics search hit observations. Grain combines the exact query with canonical returned identity; ordering and search-mode selectors define the invocation population. Result position is response order across pages, not durable identity. Total count and incomplete_results are exposed per returned hit and are not additive facts. A partial response, changed count, or 1000-result API cap prevents successful completion. Optional text-match fields remain typed when returned; this route does not request highlighted-media enrichment. released and created_by are descriptive strings, not inferred dates or verified account identities.

Grain: `search_query`, `topic_name`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `search_topic_hits__query` | `search_query` | One exact GitHub query population under the supplied API sort/search-mode/repository selectors. Every advertised page must report complete results and a stable total_count matching all emitted hits. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `search_query` | `VARCHAR` | no |
| `result_position` | `BIGINT` | no |
| `reported_total_count` | `BIGINT` | no |
| `incomplete_results` | `BOOLEAN` | no |
| `topic_name` | `VARCHAR` | no |
| `display_name` | `VARCHAR` | yes |
| `short_description` | `VARCHAR` | yes |
| `description` | `VARCHAR` | yes |
| `created_by` | `VARCHAR` | yes |
| `released` | `VARCHAR` | yes |
| `created_at` | `TIMESTAMP WITH TIME ZONE` | no |
| `updated_at` | `TIMESTAMP WITH TIME ZONE` | no |
| `featured` | `BOOLEAN` | no |
| `curated` | `BOOLEAN` | no |
| `score` | `DOUBLE` | no |
| `repository_count` | `BIGINT` | yes |
| `logo_url` | `VARCHAR` | yes |
| `text_matches` | `STRUCT("fragment" VARCHAR, "matches" STRUCT("indices" BIGINT[], "text" VARCHAR)[], "object_type" VARCHAR, "object_url" VARCHAR, "property" VARCHAR)[]` | yes |
| `related` | `STRUCT("topic_relation" STRUCT("id" BIGINT, "name" VARCHAR, "relation_type" VARCHAR, "topic_id" BIGINT))[]` | yes |
| `aliases` | `STRUCT("topic_relation" STRUCT("id" BIGINT, "name" VARCHAR, "relation_type" VARCHAR, "topic_id" BIGINT))[]` | yes |

Approved metrics:

- `search_topic_hit_count`: Query-qualified topics hits in one complete API response population, not a count of all GitHub topics.
- `search_topic_hit_max_score`: Maximum upstream relevance score in this selected query population; scores are not additive and are not comparable across different query kinds or invocations.

### `search_account_hits`

Query-qualified users search hit observations. Grain combines the exact query with canonical returned identity; ordering and search-mode selectors define the invocation population. Result position is response order across pages, not durable identity. Total count and incomplete_results are exposed per returned hit and are not additive facts. A partial response, changed count, or 1000-result API cap prevents successful completion. Optional text-match fields remain typed when returned; this route does not request highlighted-media enrichment. This endpoint is explicitly anonymous and only returns public accounts, including account types outside the canonical personal-user entity.

Grain: `search_query`, `account_id`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `search_account_hits__query` | `search_query` | One exact GitHub query population under the supplied API sort/search-mode/repository selectors. Every advertised page must report complete results and a stable total_count matching all emitted hits. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `search_query` | `VARCHAR` | no |
| `result_position` | `BIGINT` | no |
| `reported_total_count` | `BIGINT` | no |
| `incomplete_results` | `BOOLEAN` | no |
| `account_login` | `VARCHAR` | no |
| `account_id` | `BIGINT` | no |
| `node_id` | `VARCHAR` | no |
| `avatar_url` | `VARCHAR` | no |
| `gravatar_id` | `VARCHAR` | yes |
| `url` | `VARCHAR` | no |
| `html_url` | `VARCHAR` | no |
| `followers_url` | `VARCHAR` | no |
| `subscriptions_url` | `VARCHAR` | no |
| `organizations_url` | `VARCHAR` | no |
| `repos_url` | `VARCHAR` | no |
| `received_events_url` | `VARCHAR` | no |
| `account_type` | `VARCHAR` | no |
| `score` | `DOUBLE` | no |
| `following_url` | `VARCHAR` | no |
| `gists_url` | `VARCHAR` | no |
| `starred_url` | `VARCHAR` | no |
| `events_url` | `VARCHAR` | no |
| `public_repos` | `BIGINT` | yes |
| `public_gists` | `BIGINT` | yes |
| `followers` | `BIGINT` | yes |
| `following` | `BIGINT` | yes |
| `created_at` | `TIMESTAMP WITH TIME ZONE` | yes |
| `updated_at` | `TIMESTAMP WITH TIME ZONE` | yes |
| `name` | `VARCHAR` | yes |
| `bio` | `VARCHAR` | yes |
| `email` | `VARCHAR` | yes |
| `location` | `VARCHAR` | yes |
| `site_admin` | `BOOLEAN` | no |
| `hireable` | `BOOLEAN` | yes |
| `text_matches` | `STRUCT("fragment" VARCHAR, "matches" STRUCT("indices" BIGINT[], "text" VARCHAR)[], "object_type" VARCHAR, "object_url" VARCHAR, "property" VARCHAR)[]` | yes |
| `blog` | `VARCHAR` | yes |
| `company` | `VARCHAR` | yes |
| `suspended_at` | `TIMESTAMP WITH TIME ZONE` | yes |
| `user_view_type` | `VARCHAR` | yes |

Approved metrics:

- `search_account_hit_count`: Query-qualified users hits in one complete API response population, not a count of all GitHub users.
- `search_account_hit_max_score`: Maximum upstream relevance score in this selected query population; scores are not additive and are not comparable across different query kinds or invocations.

### `repository_fork_memberships`

Explicit parent/fork associations discovered through GitHub fork listings. Repository IDs remain canonical; the parent and fork are distinct repository roles, not two identities for one row.

Grain: `parent_repository_id`, `repository_id`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `repository_fork_memberships__repositories` | `owner`, `repository`, `organization`, `repositories` | Parent/fork memberships returned by the selected repository fork inventories. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `parent_repository_id` | `BIGINT` | no |
| `parent_repository` | `VARCHAR` | no |
| `repository_id` | `BIGINT` | no |
| `repository` | `VARCHAR` | no |

Approved metrics:

- `repository_fork_membership_count`: Visible parent/fork associations.

### `repository_codeowners_errors`

CODEOWNERS syntax-error occurrences in the selected ref or default branch. No durable error ID is supplied; error_ordinal preserves duplicate occurrences within this retrieval and does not claim identity across snapshots. File path/line/column locate evidence and need not be unique.

Grain: `repository_id`, `error_ordinal`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `repository_codeowners_errors__repositories` | `owner`, `repository`, `organization`, `repositories` | Complete selected repository or repository-cohort observations; API errors are not empty results. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `repository_id` | `BIGINT` | no |
| `repository` | `VARCHAR` | no |
| `codeowners_ref` | `VARCHAR` | yes |
| `error_ordinal` | `BIGINT` | no |
| `line` | `BIGINT` | no |
| `column` | `BIGINT` | no |
| `source` | `VARCHAR` | yes |
| `kind` | `VARCHAR` | no |
| `suggestion` | `VARCHAR` | yes |
| `message` | `VARCHAR` | no |
| `path` | `VARCHAR` | no |

Approved metrics:

- `codeowners_error_count`: Returned CODEOWNERS error occurrences.

### `repository_property_values`

Typed custom property assignments on a repository, separate from administrative property definitions. Scalar strings, string lists and NULL values remain distinct.

Grain: `repository_id`, `property_name`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `repository_property_values__organizations` | `organization` | All advertised pages of organization property-bearing repository discovery, optionally search-filtered; each repository hydrates canonical current per-property values. Nested properties in the discovery response are not claimed as directly mapped. |
| `repository_property_values__repositories` | `owner`, `repository`, `organization`, `repositories` | Complete selected repository or repository-cohort observations; API errors are not empty results. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `repository_id` | `BIGINT` | no |
| `repository` | `VARCHAR` | no |
| `property_name` | `VARCHAR` | no |
| `value` | `STRUCT("matched_types" VARCHAR[], "variant_1" VARCHAR, "variant_2" VARCHAR[])` | yes |

Approved metrics:

- `repository_property_value_count`: Property assignments, including explicitly null values.

### `repository_community_profiles`

Community health observations for supported non-fork repositories. Health percentage measures recommended community files, not project activity or security posture. Unsupported fork reads fail with GitHub's response instead of becoming zero health.

Grain: `repository_id`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `repository_community_profiles__repositories` | `owner`, `repository`, `organization`, `repositories` | Complete selected repository or repository-cohort observations; API errors are not empty results. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `repository_id` | `BIGINT` | no |
| `repository` | `VARCHAR` | no |
| `health_percentage` | `BIGINT` | no |
| `description` | `VARCHAR` | yes |
| `documentation` | `VARCHAR` | yes |
| `files` | `STRUCT("code_of_conduct" STRUCT("html_url" VARCHAR, "key" VARCHAR, "name" VARCHAR, "url" VARCHAR), "code_of_conduct_file" STRUCT("html_url" VARCHAR, "url" VARCHAR), "contributing" STRUCT("html_url" VARCHAR, "url" VARCHAR), "issue_template" STRUCT("html_url" VARCHAR, "url" VARCHAR), "license" STRUCT("html_url" VARCHAR, "key" VARCHAR, "name" VARCHAR, "node_id" VARCHAR, "spdx_id" VARCHAR, "url" VARCHAR), "pull_request_template" STRUCT("html_url" VARCHAR, "url" VARCHAR), "readme" STRUCT("html_url" VARCHAR, "url" VARCHAR))` | no |
| `updated_at` | `TIMESTAMP WITH TIME ZONE` | yes |
| `content_reports_enabled` | `BOOLEAN` | yes |

Approved metrics:

- `repository_community_profile_count`: Returned community profile observations.
- `average_repository_community_health`: Mean returned repository community health percentage.

### `repository_hash_observations`

Current Git object hash-algorithm observations for canonical repositories. This dedicated optional read does not force additional requests on ordinary repository discovery.

Grain: `repository_id`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `repository_hash_observations__repositories` | `owner`, `repository`, `organization`, `repositories` | Complete selected repository or repository-cohort observations; API errors are not empty results. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `repository_id` | `BIGINT` | no |
| `repository` | `VARCHAR` | no |
| `hash_algorithm` | `VARCHAR` | no |

Approved metrics:

- `repository_hash_observation_count`: Repositories with an observed object hash algorithm.
- `sha256_repository_count`: Repositories reporting sha256 object hashing.

### `repository_contributor_observations`

Cached contributor-count observations, not commit rows. GitHub groups by user after matching author email addresses, but only the first500 author email addresses link to accounts; later addresses can appear anonymously when requested. Default listing excludes anonymous rows; contributor_anonymous=true or1 explicitly includes them. Optional IDs/emails are never promoted to guaranteed identity. The retrieval-local ordinal preserves anonymous rows and duplicate-looking occurrences. Empty repositories may return204 and emit no observation.

Grain: `repository_id`, `contributor_ordinal`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `repository_contributor_observations__repositories` | `owner`, `repository`, `organization`, `repositories` | Complete selected repository or repository-cohort observations; API errors are not empty results. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `repository_id` | `BIGINT` | no |
| `repository` | `VARCHAR` | no |
| `contributor_anonymous` | `VARCHAR` | yes |
| `contributor_ordinal` | `BIGINT` | no |
| `contributor_login` | `VARCHAR` | yes |
| `contributor_id` | `BIGINT` | yes |
| `node_id` | `VARCHAR` | yes |
| `avatar_url` | `VARCHAR` | yes |
| `gravatar_id` | `VARCHAR` | yes |
| `url` | `VARCHAR` | yes |
| `html_url` | `VARCHAR` | yes |
| `followers_url` | `VARCHAR` | yes |
| `following_url` | `VARCHAR` | yes |
| `gists_url` | `VARCHAR` | yes |
| `starred_url` | `VARCHAR` | yes |
| `subscriptions_url` | `VARCHAR` | yes |
| `organizations_url` | `VARCHAR` | yes |
| `repos_url` | `VARCHAR` | yes |
| `events_url` | `VARCHAR` | yes |
| `received_events_url` | `VARCHAR` | yes |
| `contributor_type` | `VARCHAR` | no |
| `site_admin` | `BOOLEAN` | yes |
| `contributions` | `BIGINT` | no |
| `email` | `VARCHAR` | yes |
| `name` | `VARCHAR` | yes |
| `user_view_type` | `VARCHAR` | yes |

Approved metrics:

- `repository_contributor_observation_count`: Returned contributor observations in the selected anonymous population.
- `reported_contributor_commit_count`: Sum of cached API contribution counters; not independently enumerated commit count.

### `repository_collaborator_permissions`

Effective repository permission observations for an explicitly requested user. Legacy permission maps maintain to write and triage to read; role_name preserves the actual assigned or custom role. Effective access can combine direct, team and organization grants. A nullable returned user is retained, with requested login as lookup provenance.

Grain: `repository_id`, `requested_user`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `repository_collaborator_permissions__repositories` | `owner`, `repository`, `organization`, `repositories` | Complete selected repository or repository-cohort observations; API errors are not empty results. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `repository_id` | `BIGINT` | no |
| `repository` | `VARCHAR` | no |
| `requested_user` | `VARCHAR` | no |
| `permission` | `VARCHAR` | no |
| `role_name` | `VARCHAR` | no |
| `user` | `STRUCT("avatar_url" VARCHAR, "email" VARCHAR, "events_url" VARCHAR, "followers_url" VARCHAR, "following_url" VARCHAR, "gists_url" VARCHAR, "gravatar_id" VARCHAR, "html_url" VARCHAR, "id" BIGINT, "login" VARCHAR, "name" VARCHAR, "node_id" VARCHAR, "organizations_url" VARCHAR, "permissions" STRUCT("admin" BOOLEAN, "maintain" BOOLEAN, "pull" BOOLEAN, "push" BOOLEAN, "triage" BOOLEAN), "received_events_url" VARCHAR, "repos_url" VARCHAR, "role_name" VARCHAR, "site_admin" BOOLEAN, "starred_url" VARCHAR, "subscriptions_url" VARCHAR, "type" VARCHAR, "url" VARCHAR, "user_view_type" VARCHAR)` | yes |
| `user_id` | `BIGINT` | yes |
| `user_login` | `VARCHAR` | yes |

Approved metrics:

- `repository_permission_observation_count`: Returned effective permission observations, including none.

### `repository_collaborator_checks`

Caller-authorized repository collaborator membership checks. Status204 confirms membership;404 means the API did not confirm membership and can also reflect inaccessible resources. This observation does not grant access or infer the source of a grant.

Grain: `repository_id`, `requested_user`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `repository_collaborator_checks__repositories` | `owner`, `repository`, `organization`, `repositories` | Complete selected repository or repository-cohort observations; API errors are not empty results. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `repository_id` | `BIGINT` | no |
| `repository` | `VARCHAR` | no |
| `requested_user` | `VARCHAR` | no |
| `status_code` | `BIGINT` | no |

Approved metrics:

- `repository_collaborator_check_count`: Returned membership-check observations.
- `confirmed_repository_collaborator_count`: Checks with affirmative204 membership evidence.
- `unconfirmed_repository_collaborator_count`: Checks returning404; not a claim of proven absence under every credential.

### `repository_invitations`

Canonical pending repository invitations shared by repository-visible and authenticated-invitee routes. Invitee and inviter are separate optional actors. Expired is an API observation; absence is unknown rather than false. Historical accepted/deleted invitations are outside these listing populations.

Grain: `invitation_id`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `repository_invitations__authenticated` | `authenticated_user` | Currently open repository invitations for the authenticated user. |
| `repository_invitations__repositories` | `owner`, `repository`, `organization`, `repositories` | Currently open invitations for repositories where the caller has the API-required administrative visibility; this read describes pending business membership. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `invitation_id` | `BIGINT` | no |
| `repository_id` | `BIGINT` | no |
| `repository` | `VARCHAR` | no |
| `invitee_id` | `BIGINT` | yes |
| `invitee_login` | `VARCHAR` | yes |
| `inviter_id` | `BIGINT` | yes |
| `inviter_login` | `VARCHAR` | yes |
| `invitee` | `STRUCT("avatar_url" VARCHAR, "email" VARCHAR, "events_url" VARCHAR, "followers_url" VARCHAR, "following_url" VARCHAR, "gists_url" VARCHAR, "gravatar_id" VARCHAR, "html_url" VARCHAR, "id" BIGINT, "login" VARCHAR, "name" VARCHAR, "node_id" VARCHAR, "organizations_url" VARCHAR, "received_events_url" VARCHAR, "repos_url" VARCHAR, "site_admin" BOOLEAN, "starred_at" VARCHAR, "starred_url" VARCHAR, "subscriptions_url" VARCHAR, "type" VARCHAR, "url" VARCHAR, "user_view_type" VARCHAR)` | yes |
| `inviter` | `STRUCT("avatar_url" VARCHAR, "email" VARCHAR, "events_url" VARCHAR, "followers_url" VARCHAR, "following_url" VARCHAR, "gists_url" VARCHAR, "gravatar_id" VARCHAR, "html_url" VARCHAR, "id" BIGINT, "login" VARCHAR, "name" VARCHAR, "node_id" VARCHAR, "organizations_url" VARCHAR, "received_events_url" VARCHAR, "repos_url" VARCHAR, "site_admin" BOOLEAN, "starred_at" VARCHAR, "starred_url" VARCHAR, "subscriptions_url" VARCHAR, "type" VARCHAR, "url" VARCHAR, "user_view_type" VARCHAR)` | yes |
| `permissions` | `VARCHAR` | no |
| `created_at` | `TIMESTAMP WITH TIME ZONE` | no |
| `expired` | `BOOLEAN` | yes |
| `url` | `VARCHAR` | no |
| `html_url` | `VARCHAR` | no |
| `node_id` | `VARCHAR` | no |
| `invitation_created_day` | `DATE` | no |

Approved metrics:

- `repository_invitation_count`: Visible currently open invitations.
- `expired_repository_invitation_count`: Returned invitations explicitly marked expired.

### `attestation_envelopes`

Attestation envelope occurrences qualified by retrieval scope type and stable scope ID, subject digest and occurrence ordinal. Ordinals are positions within the selected invocation and predicate filter, not durable attestation identities or cross-route equivalence. Attestation envelope occurrences for a subject digest, preserving reported media type, bundle URL and initiator. The pinned verificationMaterial and dsseEnvelope values are arbitrary objects without typed fields, so their dynamic content remains explicitly uncovered. Bundle URLs are evidence and are not fetched. Listing metadata is not cryptographic signature, timestamp or signer verification. No durable attestation ID is supplied; ordinal identity applies only within this retrieval. Organization/user listings expose optional reported repository IDs but no repository locators. Nullable repository evidence is retained; users/list-attestations bodyless204 is empty, while its ambiguous201 empty-object alternative is not a completed attestation population and fails.

Grain: `retrieval_scope_type`, `retrieval_scope_id`, `attestation_subject_digest`, `attestation_ordinal`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `attestation_envelopes__organizations` | `organization` | All advertised attestation pages associated with repositories owned by the selected organization and visible to the caller. Repository fields remain optional evidence; ordinal positions are qualified by this retrieval scope, never equated to per-repository ordinal positions. |
| `attestation_envelopes__users` | `user` | All advertised attestation pages associated with repositories owned by the selected user and visible to the caller. Repository fields remain optional evidence; ordinal positions are qualified by this retrieval scope, never equated to per-repository ordinal positions. |
| `attestation_envelopes__repositories` | `owner`, `repository`, `organization`, `repositories` | Complete selected repository or repository-cohort observations; API errors are not empty results. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `retrieval_scope_type` | `VARCHAR` | no |
| `retrieval_scope_id` | `BIGINT` | no |
| `repository_id` | `BIGINT` | yes |
| `repository` | `VARCHAR` | yes |
| `attestation_subject_digest` | `VARCHAR` | no |
| `attestation_predicate_type` | `VARCHAR` | yes |
| `attestation_ordinal` | `BIGINT` | no |
| `reported_repository_id` | `BIGINT` | yes |
| `bundle_media_type` | `VARCHAR` | yes |
| `bundle_url` | `VARCHAR` | yes |
| `initiator` | `VARCHAR` | yes |
| `retrieval_organization_id` | `BIGINT` | yes |
| `retrieval_organization_login` | `VARCHAR` | yes |
| `retrieval_user_id` | `BIGINT` | yes |
| `retrieval_user_login` | `VARCHAR` | yes |

Approved metrics:

- `attestation_envelope_count`: Returned attestation envelope occurrences, not verified attestations.

### `repository_topics`

Canonical repository/topic membership pairs across every topics endpoint page. The repository_topics dataset and existing topic metrics are preserved; parent repositories with no topics remain visible through repository facts.

Grain: `repository_id`, `topic`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `repository_topics__repositories` | `owner`, `repository`, `organization`, `repositories` | Complete selected repository or repository-cohort observations; API errors are not empty results. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `repository_id` | `BIGINT` | no |
| `repository_name` | `VARCHAR` | no |
| `topic` | `VARCHAR` | no |

Approved metrics:

- `repository_topic_membership_count`: Current repository/topic membership pairs in the complete selected endpoint population.
- `repositories_with_topic_count`: Distinct repositories represented by the selected topic memberships; excludes empty parents and is non-additive across overlapping topics.

### `organization_invitations`

Canonical current organization invitations selected by team or explicit pending/failed organization population; accepted and canceled invitation history is not enumerated. Pending organization invitations selected through one team. Identity is organization/invitation, so retrieving the same invitation via another team does not create a distinct business entity. Invitee login and email may be NULL; invitation role is an organization invitation role, not a team membership role.

Grain: `organization_id`, `invitation_id`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `organization_invitations__failed` | `organization_invitation_population`; `organization_invitation_population` in ["failed"] | All advertised pages of current failed organization invitations; not historical accepted or canceled invitations. |
| `organization_invitations__pending` | `organization_invitation_population`; `organization_invitation_population` in ["pending"] | All advertised pages of current pending organization invitations; not historical accepted or canceled invitations. |
| `organization_invitations__teams` | `team_numeric_id`, `organization` | All advertised pages of pending invitations associated with the exact selected team; not all organization invitations. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `organization_id` | `BIGINT` | no |
| `organization_login` | `VARCHAR` | no |
| `invitation_id` | `BIGINT` | no |
| `login` | `VARCHAR` | yes |
| `email` | `VARCHAR` | yes |
| `role` | `VARCHAR` | no |
| `created_at` | `VARCHAR` | no |
| `failed_at` | `VARCHAR` | yes |
| `failed_reason` | `VARCHAR` | yes |
| `team_count` | `BIGINT` | no |
| `node_id` | `VARCHAR` | no |
| `invitation_teams_url` | `VARCHAR` | no |
| `invitation_source` | `VARCHAR` | yes |
| `inviter` | `STRUCT("name" VARCHAR, "email" VARCHAR, "login" VARCHAR, "id" BIGINT, "node_id" VARCHAR, "avatar_url" VARCHAR, "gravatar_id" VARCHAR, "url" VARCHAR, "html_url" VARCHAR, "followers_url" VARCHAR, "following_url" VARCHAR, "gists_url" VARCHAR, "starred_url" VARCHAR, "subscriptions_url" VARCHAR, "organizations_url" VARCHAR, "repos_url" VARCHAR, "events_url" VARCHAR, "received_events_url" VARCHAR, "type" VARCHAR, "site_admin" BOOLEAN, "starred_at" VARCHAR, "user_view_type" VARCHAR)` | no |
| `invitation_state` | `VARCHAR` | no |

Approved metrics:

- `organization_invitation_count`: Selected organization_invitations rows at their declared qualified grain.
- `pending_organization_invitation_count`: Current selected pending organization invitations.
- `failed_organization_invitation_count`: Current selected failed organization invitations.

### `team_repository_access`

Visible effective team/repository access relationships. Inherited access can be included by GitHub. Optional permission flags or role_name remain unknown when omitted; selected exact access objects fail on unconfirmed or inaccessible repositories.

Grain: `team_id`, `repository_id`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `team_repository_access__lookup` | `team_repository_permission` | One repository with team access established by the pinned repository media response; exact404 fails. |
| `team_repository_access__repositories` | `repository` | All advertised pages of visible teams with access to one repository; each team hydrates its canonical identity. |
| `team_repository_access__teams` | `team_numeric_id`, `organization` | All advertised pages of repositories accessible to the selected team, including inherited access when returned. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `team_id` | `BIGINT` | no |
| `team_slug` | `VARCHAR` | no |
| `organization_id` | `BIGINT` | no |
| `organization_login` | `VARCHAR` | no |
| `repository_id` | `BIGINT` | no |
| `repository` | `VARCHAR` | no |
| `permissions` | `STRUCT("admin" BOOLEAN, "pull" BOOLEAN, "triage" BOOLEAN, "push" BOOLEAN, "maintain" BOOLEAN)` | yes |
| `role_name` | `VARCHAR` | yes |

Approved metrics:

- `team_repository_access_count`: Selected team_repository_access rows at their declared qualified grain.

### `team_membership_checks`

Explicit status observations at the requested team/member or team/repository grain; exact scope is retained and authorization failures other than the declared404 fail.

Grain: `team_id`, `user_id`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `team_membership_checks__lookup` | `team_membership_check` | One legacy active-membership status observation, preserving204/404; not an active or pending membership object. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `team_id` | `BIGINT` | no |
| `team_slug` | `VARCHAR` | no |
| `organization_id` | `BIGINT` | no |
| `organization_login` | `VARCHAR` | no |
| `user_id` | `BIGINT` | no |
| `team_member_login` | `VARCHAR` | no |
| `status_code` | `BIGINT` | no |

Approved metrics:

- `team_membership_check_count`: Selected team_membership_checks rows at their declared qualified grain.
- `confirmed_team_membership_check_count`: Selected status observations; unconfirmed visibility does not establish absence of private access.
- `unconfirmed_team_membership_check_count`: Selected status observations; unconfirmed visibility does not establish absence of private access.

### `team_repository_permission_checks`

Explicit status observations at the requested team/member or team/repository grain; exact scope is retained and authorization failures other than the declared404 fail.

Grain: `team_id`, `repository`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `team_repository_permission_checks__lookup` | `team_repository_check` | One team/repository visibility check.404 may reflect caller access and does not prove absence of a team permission relationship. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `team_id` | `BIGINT` | no |
| `team_slug` | `VARCHAR` | no |
| `organization_id` | `BIGINT` | no |
| `organization_login` | `VARCHAR` | no |
| `repository` | `VARCHAR` | no |
| `status_code` | `BIGINT` | no |

Approved metrics:

- `team_repository_permission_check_count`: Selected team_repository_permission_checks rows at their declared qualified grain.
- `confirmed_team_repository_permission_check_count`: Selected status observations; unconfirmed visibility does not establish absence of private access.
- `unconfirmed_team_repository_permission_check_count`: Selected status observations; unconfirmed visibility does not establish absence of private access.

### `pages_sites`

Canonical current GitHub Pages configuration, one site per stable repository identity. Typed source configuration and HTTPS certificate metadata remain native structures. Public visibility describes the site, not repository visibility.

Grain: `repository_id`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `pages_sites__repositories` | `owner`, `repository`, `organization`, `repositories` | Each selected repository is hydrated before its Pages read. Missing, unconfigured or inaccessible Pages responses fail; 404 is not silently treated as a zero build/site population. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `repository_id` | `BIGINT` | no |
| `repository` | `VARCHAR` | no |
| `url` | `VARCHAR` | no |
| `status` | `VARCHAR` | yes |
| `cname` | `VARCHAR` | yes |
| `protected_domain_state` | `VARCHAR` | yes |
| `pending_domain_unverified_at` | `TIMESTAMP WITH TIME ZONE` | yes |
| `custom_404` | `BOOLEAN` | no |
| `html_url` | `VARCHAR` | yes |
| `build_type` | `VARCHAR` | yes |
| `source_configuration` | `STRUCT("branch" VARCHAR, "path" VARCHAR)` | yes |
| `public` | `BOOLEAN` | no |
| `https_certificate` | `STRUCT("description" VARCHAR, "domains" VARCHAR[], "expires_at" DATE, "state" VARCHAR)` | yes |
| `https_enforced` | `BOOLEAN` | yes |

Approved metrics:

- `pages_site_count`: Configured Pages site snapshots retrieved successfully for the selected repositories; not a count of every repository hosting status.

### `pages_builds`

Canonical GitHub Pages builds, unifying paginated history, latest and exact numeric selector routes. Stable grain is repository ID plus the API build URL; URLs are descriptive identities and never followed as arbitrary request targets. A supplied numeric build selector is not invented as a response field. Nullable pusher identity remains distinct from repository owner and commit author.

Grain: `repository_id`, `build_url`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `pages_builds__lookup` | `pages_build_id` | Each selected repository is hydrated before its Pages read. Missing, unconfigured or inaccessible Pages responses fail; 404 is not silently treated as a zero build/site population. |
| `pages_builds__latest` | `pages_build_population`; `pages_build_population` in ["latest"] | Each selected repository is hydrated before its Pages read. Missing, unconfigured or inaccessible Pages responses fail; 404 is not silently treated as a zero build/site population. |
| `pages_builds__repositories` | `owner`, `repository`, `organization`, `repositories` | Each selected repository is hydrated before its Pages read. Missing, unconfigured or inaccessible Pages responses fail; 404 is not silently treated as a zero build/site population. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `repository_id` | `BIGINT` | no |
| `repository` | `VARCHAR` | no |
| `build_url` | `VARCHAR` | no |
| `status` | `VARCHAR` | no |
| `error` | `STRUCT("message" VARCHAR)` | no |
| `pusher_id` | `BIGINT` | yes |
| `pusher_login` | `VARCHAR` | yes |
| `pusher_type` | `VARCHAR` | yes |
| `pusher` | `STRUCT("id" BIGINT, "login" VARCHAR, "type" VARCHAR, "node_id" VARCHAR, "html_url" VARCHAR)` | yes |
| `commit_sha` | `VARCHAR` | no |
| `reported_duration` | `BIGINT` | no |
| `created_at` | `TIMESTAMP WITH TIME ZONE` | no |
| `updated_at` | `TIMESTAMP WITH TIME ZONE` | no |

Approved metrics:

- `pages_build_count`: Distinct repository/build-URL records from the selected all/latest/exact-ID population; API retention bounds are preserved.
- `successful_pages_build_count`: Selected build records explicitly marked built.
- `failed_pages_build_count`: Selected build records explicitly marked errored.
- `pages_build_reported_duration`: Sum of upstream reported duration values for distinct selected builds. The pinned schema does not specify a duration unit; no seconds/milliseconds conversion is inferred.

### `repository_clone_traffic`

Current rolling 14-day clone traffic window per repository and requested day/week aggregation. Window unique counts are not additive across repositories or overlapping retrievals; they are never calculated by summing bucket uniques. Bucket timestamps start at UTC midnight; weeks start Monday. This is one current observation per retrieval, not an append-only historical window identity.

Grain: `repository_id`, `traffic_granularity`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `repository_clone_traffic__granularity` | `traffic_granularity` | Current rolling 14-day clone traffic window per repository and requested day/week aggregation. Window unique counts are not additive across repositories or overlapping retrievals; they are never calculated by summing bucket uniques. Bucket timestamps start at UTC midnight; weeks start Monday. This is one current observation per retrieval, not an append-only historical window identity. |
| `repository_clone_traffic__repositories` | `owner`, `repository`, `organization`, `repositories` | Current rolling 14-day clone traffic window per repository and requested day/week aggregation. Window unique counts are not additive across repositories or overlapping retrievals; they are never calculated by summing bucket uniques. Bucket timestamps start at UTC midnight; weeks start Monday. This is one current observation per retrieval, not an append-only historical window identity. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `repository_id` | `BIGINT` | no |
| `repository` | `VARCHAR` | no |
| `traffic_granularity` | `VARCHAR` | no |
| `total_count` | `BIGINT` | no |
| `unique_count` | `BIGINT` | no |
| `buckets` | `STRUCT("count" BIGINT, "timestamp" TIMESTAMP WITH TIME ZONE, "uniques" BIGINT)[]` | no |

Approved metrics:

- `repository_clone_traffic_observation_count`: Successfully retrieved repository traffic-window observations.
- `repository_clone_count`: Reported clone events summed across disjoint selected repositories within the current response window.
- `repository_clone_unique_max`: Maximum repository-window unique clone count; not global distinct people and not a sum of bucket uniques.

### `repository_clone_traffic_buckets`

Timestamped clone traffic buckets within the current 14-day API window. Grain includes requested day/week aggregation so overlapping representations are not conflated. Timestamp is UTC midnight, with weeks starting Monday. Unique counts are non-additive across buckets and repositories.

Grain: `repository_id`, `traffic_granularity`, `bucket_start`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `repository_clone_traffic_buckets__granularity` | `traffic_granularity` | Timestamped clone traffic buckets within the current 14-day API window. Grain includes requested day/week aggregation so overlapping representations are not conflated. Timestamp is UTC midnight, with weeks starting Monday. Unique counts are non-additive across buckets and repositories. |
| `repository_clone_traffic_buckets__repositories` | `owner`, `repository`, `organization`, `repositories` | Timestamped clone traffic buckets within the current 14-day API window. Grain includes requested day/week aggregation so overlapping representations are not conflated. Timestamp is UTC midnight, with weeks starting Monday. Unique counts are non-additive across buckets and repositories. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `repository_id` | `BIGINT` | no |
| `repository` | `VARCHAR` | no |
| `traffic_granularity` | `VARCHAR` | no |
| `bucket_start` | `TIMESTAMP WITH TIME ZONE` | no |
| `event_count` | `BIGINT` | no |
| `unique_count` | `BIGINT` | no |

Approved metrics:

- `repository_clone_traffic_buckets_count`: Returned traffic buckets, not repositories or unique people.
- `repository_clone_bucket_event_count`: Reported events summed over selected non-overlapping buckets of one requested aggregation.
- `repository_clone_bucket_unique_max`: Maximum single bucket unique count; not distinct people across buckets.

### `repository_view_traffic`

Current rolling 14-day view traffic window per repository and requested day/week aggregation. Window unique counts are not additive across repositories or overlapping retrievals; they are never calculated by summing bucket uniques. Bucket timestamps start at UTC midnight; weeks start Monday. This is one current observation per retrieval, not an append-only historical window identity.

Grain: `repository_id`, `traffic_granularity`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `repository_view_traffic__granularity` | `traffic_granularity` | Current rolling 14-day view traffic window per repository and requested day/week aggregation. Window unique counts are not additive across repositories or overlapping retrievals; they are never calculated by summing bucket uniques. Bucket timestamps start at UTC midnight; weeks start Monday. This is one current observation per retrieval, not an append-only historical window identity. |
| `repository_view_traffic__repositories` | `owner`, `repository`, `organization`, `repositories` | Current rolling 14-day view traffic window per repository and requested day/week aggregation. Window unique counts are not additive across repositories or overlapping retrievals; they are never calculated by summing bucket uniques. Bucket timestamps start at UTC midnight; weeks start Monday. This is one current observation per retrieval, not an append-only historical window identity. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `repository_id` | `BIGINT` | no |
| `repository` | `VARCHAR` | no |
| `traffic_granularity` | `VARCHAR` | no |
| `total_count` | `BIGINT` | no |
| `unique_count` | `BIGINT` | no |
| `buckets` | `STRUCT("count" BIGINT, "timestamp" TIMESTAMP WITH TIME ZONE, "uniques" BIGINT)[]` | no |

Approved metrics:

- `repository_view_traffic_observation_count`: Successfully retrieved repository traffic-window observations.
- `repository_view_count`: Reported view events summed across disjoint selected repositories within the current response window.
- `repository_view_unique_max`: Maximum repository-window unique view count; not global distinct people and not a sum of bucket uniques.

### `repository_view_traffic_buckets`

Timestamped view traffic buckets within the current 14-day API window. Grain includes requested day/week aggregation so overlapping representations are not conflated. Timestamp is UTC midnight, with weeks starting Monday. Unique counts are non-additive across buckets and repositories.

Grain: `repository_id`, `traffic_granularity`, `bucket_start`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `repository_view_traffic_buckets__granularity` | `traffic_granularity` | Timestamped view traffic buckets within the current 14-day API window. Grain includes requested day/week aggregation so overlapping representations are not conflated. Timestamp is UTC midnight, with weeks starting Monday. Unique counts are non-additive across buckets and repositories. |
| `repository_view_traffic_buckets__repositories` | `owner`, `repository`, `organization`, `repositories` | Timestamped view traffic buckets within the current 14-day API window. Grain includes requested day/week aggregation so overlapping representations are not conflated. Timestamp is UTC midnight, with weeks starting Monday. Unique counts are non-additive across buckets and repositories. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `repository_id` | `BIGINT` | no |
| `repository` | `VARCHAR` | no |
| `traffic_granularity` | `VARCHAR` | no |
| `bucket_start` | `TIMESTAMP WITH TIME ZONE` | no |
| `event_count` | `BIGINT` | no |
| `unique_count` | `BIGINT` | no |

Approved metrics:

- `repository_view_traffic_buckets_count`: Returned traffic buckets, not repositories or unique people.
- `repository_view_bucket_event_count`: Reported events summed over selected non-overlapping buckets of one requested aggregation.
- `repository_view_bucket_unique_max`: Maximum single bucket unique count; not distinct people across buckets.

### `repository_top_paths`

At most the top 10 paths over the current rolling 14 days. This deliberately ranked response is not a complete population of all paths. Response position records current API order, not durable rank. Unique counts cannot be added across paths or repositories.

Grain: `repository_id`, `path`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `repository_top_paths__repositories` | `owner`, `repository`, `organization`, `repositories` | At most the top 10 paths over the current rolling 14 days. This deliberately ranked response is not a complete population of all paths. Response position records current API order, not durable rank. Unique counts cannot be added across paths or repositories. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `repository_id` | `BIGINT` | no |
| `repository` | `VARCHAR` | no |
| `path` | `VARCHAR` | no |
| `title` | `VARCHAR` | no |
| `event_count` | `BIGINT` | no |
| `unique_count` | `BIGINT` | no |
| `response_position` | `BIGINT` | no |

Approved metrics:

- `repository_top_paths_count`: Returned top-10 paths observations, not all paths.
- `repository_top_paths_event_count`: Events attributed to the returned top-10 paths only, not all repository traffic.
- `repository_top_paths_unique_max`: Maximum unique count for one returned path; not a distinct visitor total.

### `repository_top_referrers`

At most the top 10 referrers over the current rolling 14 days. This deliberately ranked response is not a complete population of all referrers. Response position records current API order, not durable rank. Unique counts cannot be added across referrers or repositories.

Grain: `repository_id`, `referrer`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `repository_top_referrers__repositories` | `owner`, `repository`, `organization`, `repositories` | At most the top 10 referrers over the current rolling 14 days. This deliberately ranked response is not a complete population of all referrers. Response position records current API order, not durable rank. Unique counts cannot be added across referrers or repositories. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `repository_id` | `BIGINT` | no |
| `repository` | `VARCHAR` | no |
| `referrer` | `VARCHAR` | no |
| `event_count` | `BIGINT` | no |
| `unique_count` | `BIGINT` | no |
| `response_position` | `BIGINT` | no |

Approved metrics:

- `repository_top_referrers_count`: Returned top-10 referrers observations, not all referrers.
- `repository_top_referrers_event_count`: Events attributed to the returned top-10 referrers only, not all repository traffic.
- `repository_top_referrers_unique_max`: Maximum unique count for one returned referrer; not a distinct visitor total.

### `repository_code_frequency`

Weekly upstream additions/deletions tuples. The signed deletion value is preserved as reported. Available only for repositories with fewer than 10,000 commits; 422 fails. A 202 pending computation fails rather than becoming an empty population; explicit bodyless 204 is empty. Week values remain Unix seconds without an invented calendar conversion.

Grain: `repository_id`, `week_epoch`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `repository_code_frequency__repositories` | `owner`, `repository`, `organization`, `repositories` | Weekly upstream additions/deletions tuples. The signed deletion value is preserved as reported. Available only for repositories with fewer than 10,000 commits; 422 fails. A 202 pending computation fails rather than becoming an empty population; explicit bodyless 204 is empty. Week values remain Unix seconds without an invented calendar conversion. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `repository_id` | `BIGINT` | no |
| `repository` | `VARCHAR` | no |
| `week_epoch` | `BIGINT` | no |
| `additions` | `BIGINT` | no |
| `deletions` | `BIGINT` | no |

Approved metrics:

- `repository_code_frequency_week_count`: Returned repository code frequency observations; not an independent count of Git commits or users.
- `repository_code_frequency_additions`: Reported additions in distinct selected weekly tuples.
- `repository_code_frequency_signed_deletions`: Signed upstream deletion values, with no sign inversion.

### `repository_commit_activity`

Last-year weekly commit activity from GitHub statistics. Each typed daily_commits array retains upstream Sunday-first order. Week is the upstream Unix timestamp. A 202 pending computation fails rather than claiming zero commits; explicit bodyless 204 is empty.

Grain: `repository_id`, `week_epoch`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `repository_commit_activity__repositories` | `owner`, `repository`, `organization`, `repositories` | Last-year weekly commit activity from GitHub statistics. Each typed daily_commits array retains upstream Sunday-first order. Week is the upstream Unix timestamp. A 202 pending computation fails rather than claiming zero commits; explicit bodyless 204 is empty. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `repository_id` | `BIGINT` | no |
| `repository` | `VARCHAR` | no |
| `week_epoch` | `BIGINT` | no |
| `commit_count` | `BIGINT` | no |
| `daily_commits` | `BIGINT[]` | no |

Approved metrics:

- `repository_commit_activity_week_count`: Returned repository commit activity observations; not an independent count of Git commits or users.
- `repository_commit_activity_commit_count`: Upstream commit totals for distinct returned weeks.

### `repository_contributor_statistics`

Contributor statistics snapshot, including nullable/unlinked authors. Grain is repository plus one-based position in this retrieval because the pinned contract permits author=NULL; position is not a durable contributor identity across refreshes. Typed weeks retain w (Unix week), a (additions), d (deletions), c (commits). Repositories with at least 10,000 commits report zero additions/deletions by API policy, which must not be interpreted as observed zero changes. A 202 pending computation fails; explicit bodyless 204 is empty.

Grain: `repository_id`, `response_position`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `repository_contributor_statistics__repositories` | `owner`, `repository`, `organization`, `repositories` | Contributor statistics snapshot, including nullable/unlinked authors. Grain is repository plus one-based position in this retrieval because the pinned contract permits author=NULL; position is not a durable contributor identity across refreshes. Typed weeks retain w (Unix week), a (additions), d (deletions), c (commits). Repositories with at least 10,000 commits report zero additions/deletions by API policy, which must not be interpreted as observed zero changes. A 202 pending computation fails; explicit bodyless 204 is empty. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `repository_id` | `BIGINT` | no |
| `repository` | `VARCHAR` | no |
| `response_position` | `BIGINT` | no |
| `author_id` | `BIGINT` | yes |
| `author_login` | `VARCHAR` | yes |
| `author_type` | `VARCHAR` | yes |
| `author` | `STRUCT("avatar_url" VARCHAR, "email" VARCHAR, "events_url" VARCHAR, "followers_url" VARCHAR, "following_url" VARCHAR, "gists_url" VARCHAR, "gravatar_id" VARCHAR, "html_url" VARCHAR, "id" BIGINT, "login" VARCHAR, "name" VARCHAR, "node_id" VARCHAR, "organizations_url" VARCHAR, "received_events_url" VARCHAR, "repos_url" VARCHAR, "site_admin" BOOLEAN, "starred_at" VARCHAR, "starred_url" VARCHAR, "subscriptions_url" VARCHAR, "type" VARCHAR, "url" VARCHAR, "user_view_type" VARCHAR)` | yes |
| `total_commits` | `BIGINT` | no |
| `weeks` | `STRUCT("a" BIGINT, "c" BIGINT, "d" BIGINT, "w" BIGINT)[]` | no |

Approved metrics:

- `repository_contributor_statistics_observation_count`: Returned repository contributor statistics observations; not an independent count of Git commits or users.
- `repository_contributor_statistics_commit_count`: Reported contributor commit totals within the selected repository snapshots; not distinct global commits.

### `repository_participation_statistics`

Current last-52-week participation snapshot. Typed arrays run oldest to most recent week. The latest week spans seven days ago at UTC midnight to today at UTC midnight; no timestamp is invented without a response observation anchor. all_commits includes owner_commits, so the two series must not be added. This is an observation, not a count of participating people.

Grain: `repository_id`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `repository_participation_statistics__repositories` | `owner`, `repository`, `organization`, `repositories` | Current last-52-week participation snapshot. Typed arrays run oldest to most recent week. The latest week spans seven days ago at UTC midnight to today at UTC midnight; no timestamp is invented without a response observation anchor. all_commits includes owner_commits, so the two series must not be added. This is an observation, not a count of participating people. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `repository_id` | `BIGINT` | no |
| `repository` | `VARCHAR` | no |
| `all_commits` | `BIGINT[]` | no |
| `owner_commits` | `BIGINT[]` | no |

Approved metrics:

- `repository_participation_observation_count`: Returned repository participation statistics observations; not an independent count of Git commits or users.

### `repository_commit_punch_card`

Commit frequency grouped by day number (0 Sunday through 6 Saturday) and hour (0 through 23). Times use each individual commit time zone, not one global UTC calendar. Exact three-integer tuples are required. Explicit bodyless 204 is empty.

Grain: `repository_id`, `day_of_week`, `hour_of_day`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `repository_commit_punch_card__repositories` | `owner`, `repository`, `organization`, `repositories` | Commit frequency grouped by day number (0 Sunday through 6 Saturday) and hour (0 through 23). Times use each individual commit time zone, not one global UTC calendar. Exact three-integer tuples are required. Explicit bodyless 204 is empty. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `repository_id` | `BIGINT` | no |
| `repository` | `VARCHAR` | no |
| `day_of_week` | `BIGINT` | no |
| `hour_of_day` | `BIGINT` | no |
| `commit_count` | `BIGINT` | no |

Approved metrics:

- `repository_commit_punch_card_bucket_count`: Returned repository commit punch card observations; not an independent count of Git commits or users.
- `repository_commit_punch_card_commit_count`: Reported commits summed over disjoint day/hour buckets in the selected repositories.

### `commit_statuses`

Canonical commit status events keyed by repository and status ID. History lists every event for a ref; latest retrieves only the current event for each context across every combined-status page. Latest retrieval resolves the ref through a retained aggregate parent, preserving empty commits. Timestamp strings from history remain created_at_raw/updated_at_raw VARCHAR; latest typed date-time values populate created_at/updated_at only. Fields absent from a selected API schema remain NULL, including creator in latest and required in history. No timestamp parsing or fabricated creators are applied.

Grain: `repository_id`, `status_id`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `commit_statuses__latest` | `commit_status_population` | Canonical commit status events keyed by repository and status ID. History lists every event for a ref; latest retrieves only the current event for each context across every combined-status page. Latest retrieval resolves the ref through a retained aggregate parent, preserving empty commits. Timestamp strings from history remain created_at_raw/updated_at_raw VARCHAR; latest typed date-time values populate created_at/updated_at only. Fields absent from a selected API schema remain NULL, including creator in latest and required in history. No timestamp parsing or fabricated creators are applied. |
| `commit_statuses__repositories` | `owner`, `repository`, `organization`, `repositories` | Canonical commit status events keyed by repository and status ID. History lists every event for a ref; latest retrieves only the current event for each context across every combined-status page. Latest retrieval resolves the ref through a retained aggregate parent, preserving empty commits. Timestamp strings from history remain created_at_raw/updated_at_raw VARCHAR; latest typed date-time values populate created_at/updated_at only. Fields absent from a selected API schema remain NULL, including creator in latest and required in history. No timestamp parsing or fabricated creators are applied. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `repository_id` | `BIGINT` | no |
| `repository` | `VARCHAR` | no |
| `commit_sha` | `VARCHAR` | yes |
| `status_id` | `BIGINT` | no |
| `node_id` | `VARCHAR` | no |
| `state` | `VARCHAR` | no |
| `description` | `VARCHAR` | yes |
| `target_url` | `VARCHAR` | yes |
| `context` | `VARCHAR` | no |
| `created_at` | `TIMESTAMP WITH TIME ZONE` | yes |
| `updated_at` | `TIMESTAMP WITH TIME ZONE` | yes |
| `avatar_url` | `VARCHAR` | yes |
| `url` | `VARCHAR` | no |
| `required` | `BOOLEAN` | yes |
| `created_at_raw` | `VARCHAR` | yes |
| `updated_at_raw` | `VARCHAR` | yes |
| `creator` | `STRUCT("avatar_url" VARCHAR, "email" VARCHAR, "events_url" VARCHAR, "followers_url" VARCHAR, "following_url" VARCHAR, "gists_url" VARCHAR, "gravatar_id" VARCHAR, "html_url" VARCHAR, "id" BIGINT, "login" VARCHAR, "name" VARCHAR, "node_id" VARCHAR, "organizations_url" VARCHAR, "received_events_url" VARCHAR, "repos_url" VARCHAR, "site_admin" BOOLEAN, "starred_at" VARCHAR, "starred_url" VARCHAR, "subscriptions_url" VARCHAR, "type" VARCHAR, "url" VARCHAR, "user_view_type" VARCHAR)` | yes |
| `creator_id` | `BIGINT` | yes |
| `creator_login` | `VARCHAR` | yes |

Approved metrics:

- `commit_statuses_count`: Commit statuses count. Counts the declared entity grain.
- `commit_statuses_success_count`: Commit statuses success count. Counts the declared entity grain.
- `commit_statuses_failure_count`: Commit statuses failure count. Counts the declared entity grain.
- `commit_statuses_error_count`: Commit statuses error count. Counts the declared entity grain.
- `commit_statuses_pending_count`: Commit statuses pending count. Counts the declared entity grain.

### `commit_status_summaries`

Combined latest-context state observations. References resolve at request time. Historical status timestamps remain VARCHAR because the pinned status schema does not declare date-time format; combined context timestamps have their own typed schema.

Grain: `repository_id`, `commit_sha`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `commit_status_summaries__repositories` | `owner`, `repository`, `organization`, `repositories` | Combined latest-context state observations. References resolve at request time. Historical status timestamps remain VARCHAR because the pinned status schema does not declare date-time format; combined context timestamps have their own typed schema. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `repository_id` | `BIGINT` | no |
| `repository` | `VARCHAR` | no |
| `commit_sha` | `VARCHAR` | no |
| `state` | `VARCHAR` | no |
| `total_count` | `BIGINT` | no |
| `reported_repository_id` | `BIGINT` | no |
| `reported_repository` | `VARCHAR` | no |
| `repository_details` | `STRUCT("id" BIGINT, "node_id" VARCHAR, "name" VARCHAR, "full_name" VARCHAR, "owner" STRUCT("avatar_url" VARCHAR, "email" VARCHAR, "events_url" VARCHAR, "followers_url" VARCHAR, "following_url" VARCHAR, "gists_url" VARCHAR, "gravatar_id" VARCHAR, "html_url" VARCHAR, "id" BIGINT, "login" VARCHAR, "name" VARCHAR, "node_id" VARCHAR, "organizations_url" VARCHAR, "received_events_url" VARCHAR, "repos_url" VARCHAR, "site_admin" BOOLEAN, "starred_at" VARCHAR, "starred_url" VARCHAR, "subscriptions_url" VARCHAR, "type" VARCHAR, "url" VARCHAR, "user_view_type" VARCHAR), "private" BOOLEAN, "html_url" VARCHAR, "description" VARCHAR, "fork" BOOLEAN, "url" VARCHAR, "archive_url" VARCHAR, "assignees_url" VARCHAR, "blobs_url" VARCHAR, "branches_url" VARCHAR, "collaborators_url" VARCHAR, "comments_url" VARCHAR, "commits_url" VARCHAR, "compare_url" VARCHAR, "contents_url" VARCHAR, "contributors_url" VARCHAR, "deployments_url" VARCHAR, "downloads_url" VARCHAR, "events_url" VARCHAR, "forks_url" VARCHAR, "git_commits_url" VARCHAR, "git_refs_url" VARCHAR, "git_tags_url" VARCHAR, "git_url" VARCHAR, "issue_comment_url" VARCHAR, "issue_events_url" VARCHAR, "issues_url" VARCHAR, "keys_url" VARCHAR, "labels_url" VARCHAR, "languages_url" VARCHAR, "merges_url" VARCHAR, "milestones_url" VARCHAR, "notifications_url" VARCHAR, "pulls_url" VARCHAR, "releases_url" VARCHAR, "ssh_url" VARCHAR, "stargazers_url" VARCHAR, "statuses_url" VARCHAR, "subscribers_url" VARCHAR, "subscription_url" VARCHAR, "tags_url" VARCHAR, "teams_url" VARCHAR, "trees_url" VARCHAR, "clone_url" VARCHAR, "mirror_url" VARCHAR, "hooks_url" VARCHAR, "svn_url" VARCHAR, "homepage" VARCHAR, "language" VARCHAR, "forks_count" BIGINT, "stargazers_count" BIGINT, "watchers_count" BIGINT, "size" BIGINT, "default_branch" VARCHAR, "open_issues_count" BIGINT, "is_template" BOOLEAN, "topics" VARCHAR[], "has_issues" BOOLEAN, "has_projects" BOOLEAN, "has_wiki" BOOLEAN, "has_pages" BOOLEAN, "has_downloads" BOOLEAN, "has_discussions" BOOLEAN, "has_pull_requests" BOOLEAN, "pull_request_creation_policy" VARCHAR, "archived" BOOLEAN, "disabled" BOOLEAN, "visibility" VARCHAR, "pushed_at" TIMESTAMP WITH TIME ZONE, "created_at" TIMESTAMP WITH TIME ZONE, "updated_at" TIMESTAMP WITH TIME ZONE, "permissions" STRUCT("admin" BOOLEAN, "maintain" BOOLEAN, "pull" BOOLEAN, "push" BOOLEAN, "triage" BOOLEAN), "role_name" VARCHAR, "temp_clone_token" VARCHAR, "delete_branch_on_merge" BOOLEAN, "subscribers_count" BIGINT, "network_count" BIGINT, "code_of_conduct" STRUCT("body" VARCHAR, "html_url" VARCHAR, "key" VARCHAR, "name" VARCHAR, "url" VARCHAR), "license" STRUCT("key" VARCHAR, "name" VARCHAR, "node_id" VARCHAR, "spdx_id" VARCHAR, "url" VARCHAR), "forks" BIGINT, "open_issues" BIGINT, "watchers" BIGINT, "allow_forking" BOOLEAN, "web_commit_signoff_required" BOOLEAN, "security_and_analysis" STRUCT("advanced_security" STRUCT("status" VARCHAR), "code_security" STRUCT("status" VARCHAR), "dependabot_security_updates" STRUCT("status" VARCHAR), "secret_scanning" STRUCT("status" VARCHAR), "secret_scanning_ai_detection" STRUCT("status" VARCHAR), "secret_scanning_delegated_alert_dismissal" STRUCT("status" VARCHAR), "secret_scanning_delegated_bypass" STRUCT("status" VARCHAR), "secret_scanning_delegated_bypass_options" STRUCT("reviewers" STRUCT("mode" VARCHAR, "reviewer_id" BIGINT, "reviewer_type" VARCHAR)[]), "secret_scanning_non_provider_patterns" STRUCT("status" VARCHAR), "secret_scanning_push_protection" STRUCT("status" VARCHAR)))` | no |
| `commit_url` | `VARCHAR` | no |
| `url` | `VARCHAR` | no |

Approved metrics:

- `commit_status_summaries_count`: Commit status summaries count. Counts the declared entity grain.
- `commit_status_summaries_success_count`: Commit status summaries success count. Counts the declared entity grain.
- `commit_status_summaries_failure_count`: Commit status summaries failure count. Counts the declared entity grain.
- `commit_status_summaries_error_count`: Commit status summaries error count. Counts the declared entity grain.
- `commit_status_summaries_pending_count`: Commit status summaries pending count. Counts the declared entity grain.
- `commit_status_reported_context_count`: Sum of API-reported latest context counts, including zero-context commit summaries; not historical event counts.

### `rule_suites`

Observed rule evaluation suites across organization and repository collections or direct IDs. Complete list pages hydrate full rule details; no ruleset configuration is retrieved. Pinned optional IDs must be non-null to establish the canonical grain. Unknown actors and absent evaluation results remain NULL. Repository full name is unavailable on organization responses; repository_id remains independent association evidence.

Grain: `rule_suite_id`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `rule_suites__lookup` | `rule_suite_id` | Observed rule evaluation suites across organization and repository collections or direct IDs. Complete list pages hydrate full rule details; no ruleset configuration is retrieved. Pinned optional IDs must be non-null to establish the canonical grain. Unknown actors and absent evaluation results remain NULL. Repository full name is unavailable on organization responses; repository_id remains independent association evidence. |
| `rule_suites__organizations` | `organization` | Observed rule evaluation suites across organization and repository collections or direct IDs. Complete list pages hydrate full rule details; no ruleset configuration is retrieved. Pinned optional IDs must be non-null to establish the canonical grain. Unknown actors and absent evaluation results remain NULL. Repository full name is unavailable on organization responses; repository_id remains independent association evidence. |
| `rule_suites__repositories` | `owner`, `repository`, `organization`, `repositories` | Observed rule evaluation suites across organization and repository collections or direct IDs. Complete list pages hydrate full rule details; no ruleset configuration is retrieved. Pinned optional IDs must be non-null to establish the canonical grain. Unknown actors and absent evaluation results remain NULL. Repository full name is unavailable on organization responses; repository_id remains independent association evidence. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `rule_suite_id` | `BIGINT` | no |
| `actor_id` | `BIGINT` | yes |
| `actor_name` | `VARCHAR` | yes |
| `before_sha` | `VARCHAR` | yes |
| `after_sha` | `VARCHAR` | yes |
| `ref` | `VARCHAR` | yes |
| `repository_id` | `BIGINT` | yes |
| `pushed_at` | `TIMESTAMP WITH TIME ZONE` | yes |
| `result` | `VARCHAR` | yes |
| `evaluation_result` | `VARCHAR` | yes |
| `rule_evaluations` | `STRUCT("details" VARCHAR, "enforcement" VARCHAR, "result" VARCHAR, "rule_source" STRUCT("id" BIGINT, "name" VARCHAR, "type" VARCHAR), "rule_type" VARCHAR)[]` | yes |
| `reported_repository_name` | `VARCHAR` | yes |
| `repository` | `VARCHAR` | yes |
| `organization` | `VARCHAR` | yes |

Approved metrics:

- `rule_suite_count`: Rule suite count. Counts the declared entity grain.
- `rule_suite_pass_count`: Rule suite pass count. Counts the declared entity grain.
- `rule_suite_fail_count`: Rule suite fail count. Counts the declared entity grain.
- `rule_suite_bypass_count`: Rule suite bypass count. Counts the declared entity grain.
- `rule_evaluation_count`: Count of observed typed rule evaluations; a missing list provides no observed evaluations.

### `push_bypass_requests`

Push-rule bypass requests identified globally by request ID, with repository-local request numbers for lookup. Requester and delegated-reviewer roles remain separate; all typed violation summaries and responses are retained. The pinned GET operations are available in the ghec product contract. Optional IDs are explicitly required at emission; absent nested metadata remains unknown. Organization retrieval retains requests with missing repository evidence; reported repository identity remains nullable.

Grain: `bypass_request_id`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `push_bypass_requests__lookup` | `bypass_request_number` | Push-rule bypass requests identified globally by request ID, with repository-local request numbers for lookup. Requester and delegated-reviewer roles remain separate; all typed violation summaries and responses are retained. The pinned GET operations are available in the ghec product contract. Optional IDs are explicitly required at emission; absent nested metadata remains unknown. Organization retrieval retains requests with missing repository evidence; reported repository identity remains nullable. |
| `push_bypass_requests__organizations` | `organization` | All advertised pages of credential-visible organization push-rule bypass requests in the selected rolling time window (API default day), optional repository/requester/reviewer/status filters; not complete historical requests. |
| `push_bypass_requests__repositories` | `owner`, `repository`, `organization`, `repositories` | Push-rule bypass requests identified globally by request ID, with repository-local request numbers for lookup. Requester and delegated-reviewer roles remain separate; all typed violation summaries and responses are retained. The pinned GET operations are available in the ghec product contract. Optional IDs are explicitly required at emission; absent nested metadata remains unknown. Organization retrieval retains requests with missing repository evidence; reported repository identity remains nullable. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `bypass_request_id` | `BIGINT` | no |
| `request_number` | `BIGINT` | yes |
| `repository_details` | `STRUCT("full_name" VARCHAR, "id" BIGINT, "name" VARCHAR)` | yes |
| `organization_details` | `STRUCT("id" BIGINT, "name" VARCHAR)` | yes |
| `requester_id` | `BIGINT` | yes |
| `requester_login` | `VARCHAR` | yes |
| `requester` | `STRUCT("actor_id" BIGINT, "actor_name" VARCHAR)` | yes |
| `request_type` | `VARCHAR` | yes |
| `data` | `STRUCT("rule_type" VARCHAR, "ruleset_id" BIGINT, "ruleset_name" VARCHAR, "total_violations" BIGINT)[]` | yes |
| `resource_identifier` | `VARCHAR` | yes |
| `status` | `VARCHAR` | yes |
| `requester_comment` | `VARCHAR` | yes |
| `expires_at` | `TIMESTAMP WITH TIME ZONE` | yes |
| `created_at` | `TIMESTAMP WITH TIME ZONE` | yes |
| `responses` | `STRUCT("created_at" TIMESTAMP WITH TIME ZONE, "id" BIGINT, "reviewer" STRUCT("actor_id" BIGINT, "actor_name" VARCHAR), "status" VARCHAR)[]` | yes |
| `url` | `VARCHAR` | yes |
| `html_url` | `VARCHAR` | yes |
| `repository_id` | `BIGINT` | yes |
| `repository` | `VARCHAR` | yes |

Approved metrics:

- `push_bypass_request_count`: Push bypass request count. Counts the declared entity grain.
- `push_bypass_pending_count`: Push bypass pending count. Counts the declared entity grain.
- `push_bypass_denied_count`: Push bypass denied count. Counts the declared entity grain.
- `push_bypass_approved_count`: Push bypass approved count. Counts the declared entity grain.
- `push_bypass_cancelled_count`: Push bypass cancelled count. Counts the declared entity grain.
- `push_bypass_completed_count`: Push bypass completed count. Counts the declared entity grain.
- `push_bypass_expired_count`: Push bypass expired count. Counts the declared entity grain.
- `push_bypass_deleted_count`: Push bypass deleted count. Counts the declared entity grain.
- `push_bypass_open_count`: Push bypass open count. Counts the declared entity grain.
- `push_bypass_response_count`: Count of observed reviewer responses; requester and reviewer roles remain distinct.

### `repository_property_definitions`

Custom repository-property definitions visible in one organization, including their declared source_type, required/default semantics and ordered allowed values. Enterprise source labels describe inherited definitions; enterprise administration endpoints are outside this model.

Grain: `organization_id`, `property_name`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `repository_property_definitions__lookup` | `custom_property_name` | One exact custom-property definition; missing404 fails. |
| `repository_property_definitions__organizations` | `organization` | All custom-property definitions reported for the selected organization. Allowed values are the ordered definition domain, bounded to200 by the pinned API. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `organization_id` | `BIGINT` | no |
| `organization_login` | `VARCHAR` | no |
| `property_name` | `VARCHAR` | no |
| `url` | `VARCHAR` | yes |
| `source_type` | `VARCHAR` | yes |
| `value_type` | `VARCHAR` | no |
| `required` | `BOOLEAN` | yes |
| `default_value` | `STRUCT("matched_types" VARCHAR[], "variant_1" VARCHAR, "variant_2" VARCHAR[])` | yes |
| `description` | `VARCHAR` | yes |
| `allowed_values` | `VARCHAR[]` | yes |
| `values_editable_by` | `VARCHAR` | yes |
| `require_explicit_values` | `BOOLEAN` | yes |

Approved metrics:

- `repository_property_definition_count`: Selected repository_property_definitions rows at the declared identity grain.

### `issue_types`

Organization-defined issue types with full feasible typed pinned fields. Retrieval is metadata availability, not assigned issue occurrences.

Grain: `organization_id`, `issue_type_id`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `issue_types__repositories` | `repository` | Issue types available to one repository, preserving the owning organization/type identity; personal-owner lookup fails rather than inventing organization identity. |
| `issue_types__organizations` | `organization` | All reported issue types defined in the organization; malformed NULL identity rows fail. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `organization_id` | `BIGINT` | no |
| `organization_login` | `VARCHAR` | no |
| `issue_type_id` | `BIGINT` | no |
| `node_id` | `VARCHAR` | yes |
| `name` | `VARCHAR` | yes |
| `description` | `VARCHAR` | yes |
| `color` | `VARCHAR` | yes |
| `created_at` | `TIMESTAMP WITH TIME ZONE` | yes |
| `updated_at` | `TIMESTAMP WITH TIME ZONE` | yes |
| `is_enabled` | `BOOLEAN` | yes |

Approved metrics:

- `issue_type_count`: Selected issue_types rows at the declared identity grain.

### `issue_fields`

Organization-defined issue fields with full feasible typed pinned fields. Retrieval is metadata availability, not assigned issue occurrences.

Grain: `organization_id`, `issue_field_id`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `issue_fields__organizations` | `organization` | All reported issue fields defined in the organization; malformed NULL identity rows fail. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `organization_id` | `BIGINT` | no |
| `organization_login` | `VARCHAR` | no |
| `issue_field_id` | `BIGINT` | no |
| `node_id` | `VARCHAR` | yes |
| `name` | `VARCHAR` | yes |
| `description` | `VARCHAR` | yes |
| `data_type` | `VARCHAR` | yes |
| `visibility` | `VARCHAR` | yes |
| `options` | `STRUCT("id" BIGINT, "name" VARCHAR, "description" VARCHAR, "color" VARCHAR, "priority" BIGINT, "created_at" TIMESTAMP WITH TIME ZONE, "updated_at" TIMESTAMP WITH TIME ZONE)[]` | yes |
| `created_at` | `TIMESTAMP WITH TIME ZONE` | yes |
| `updated_at` | `TIMESTAMP WITH TIME ZONE` | yes |

Approved metrics:

- `issue_field_count`: Selected issue_fields rows at the declared identity grain.

### `organization_outside_collaborators`

Credential-visible organization/account outside-collaborator relationships. These accounts are not organization membership records; account types and optional profile fields are preserved.

Grain: `organization_id`, `user_id`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `organization_outside_collaborators__organizations` | `organization` | All advertised pages of outside collaborators in the selected optional two-factor population. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `organization_id` | `BIGINT` | no |
| `organization_login` | `VARCHAR` | no |
| `user_id` | `BIGINT` | no |
| `user_login` | `VARCHAR` | no |
| `account_type` | `VARCHAR` | no |
| `account` | `STRUCT("name" VARCHAR, "email" VARCHAR, "login" VARCHAR, "id" BIGINT, "node_id" VARCHAR, "avatar_url" VARCHAR, "gravatar_id" VARCHAR, "url" VARCHAR, "html_url" VARCHAR, "followers_url" VARCHAR, "following_url" VARCHAR, "gists_url" VARCHAR, "starred_url" VARCHAR, "subscriptions_url" VARCHAR, "organizations_url" VARCHAR, "repos_url" VARCHAR, "events_url" VARCHAR, "received_events_url" VARCHAR, "type" VARCHAR, "site_admin" BOOLEAN, "starred_at" VARCHAR, "user_view_type" VARCHAR)` | no |

Approved metrics:

- `organization_outside_collaborator_count`: Selected organization_outside_collaborators rows at the declared identity grain.

### `organization_invitation_teams`

Organization-invitation/team associations, distinct from either invitation or team identity. One invitation for two teams contributes two associations. Both retrieval directions share the same qualified pair.

Grain: `organization_id`, `invitation_id`, `team_id`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `organization_invitation_teams__invitations` | `organization_invitation_id` | All advertised team associations for one visible organization invitation. |
| `organization_invitation_teams__teams` | `team_numeric_id`, `organization` | All pending invitations associated with one selected team. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `organization_id` | `BIGINT` | no |
| `organization_login` | `VARCHAR` | no |
| `invitation_id` | `BIGINT` | no |
| `team_id` | `BIGINT` | no |
| `team_slug` | `VARCHAR` | no |

Approved metrics:

- `organization_invitation_team_count`: Selected organization_invitation_teams rows at the declared identity grain.

### `repository_changes`

Detailed repository change records (pushes, force pushes, branch changes and merges), separate from the retained general Events API. Follow every advertised Link cursor in the selected filters; opaque initial before/after cursors intentionally select a subpopulation. Actor is the performer, not the commit author or repository owner. before_sha/after_sha are reported boundaries; zero or unavailable commit objects are not invented as retrieved commits.

Grain: `repository_id`, `change_id`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `repository_changes__repositories` | `owner`, `repository`, `organization`, `repositories` | Detailed repository change records (pushes, force pushes, branch changes and merges), separate from the retained general Events API. Follow every advertised Link cursor in the selected filters; opaque initial before/after cursors intentionally select a subpopulation. Actor is the performer, not the commit author or repository owner. before_sha/after_sha are reported boundaries; zero or unavailable commit objects are not invented as retrieved commits. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `repository_id` | `BIGINT` | no |
| `repository` | `VARCHAR` | no |
| `change_id` | `BIGINT` | no |
| `node_id` | `VARCHAR` | no |
| `before_sha` | `VARCHAR` | no |
| `after_sha` | `VARCHAR` | no |
| `ref_name` | `VARCHAR` | no |
| `occurred_at` | `TIMESTAMP WITH TIME ZONE` | no |
| `activity_type` | `VARCHAR` | no |
| `actor_id` | `BIGINT` | yes |
| `actor_login` | `VARCHAR` | yes |
| `actor_type` | `VARCHAR` | yes |
| `actor` | `STRUCT("avatar_url" VARCHAR, "email" VARCHAR, "events_url" VARCHAR, "followers_url" VARCHAR, "following_url" VARCHAR, "gists_url" VARCHAR, "gravatar_id" VARCHAR, "html_url" VARCHAR, "id" BIGINT, "login" VARCHAR, "name" VARCHAR, "node_id" VARCHAR, "organizations_url" VARCHAR, "received_events_url" VARCHAR, "repos_url" VARCHAR, "site_admin" BOOLEAN, "starred_at" VARCHAR, "starred_url" VARCHAR, "subscriptions_url" VARCHAR, "type" VARCHAR, "url" VARCHAR, "user_view_type" VARCHAR)` | yes |

Approved metrics:

- `repository_change_count`: Distinct repository-qualified change records in the selected filtered history.
- `repository_push_count`: Selected ordinary push records.
- `repository_force_push_count`: Selected force-push records.
- `repository_branch_deletion_count`: Selected branch-deletion records.

### `repository_contents`

Canonical repository content objects, unifying explicit path/root and preferred README retrieval. Grain is stable repository ID plus returned path and content/tree SHA; requested refs are selectors, not extra identities. Encoded content stays VARCHAR with its declared encoding, never falsely decoded as complete bytes. Object-media files of 1–100 MB may report encoding=none and empty content; over 100 MB is unsupported. Directory entries are immediate children only, fail at the 1,000-entry ceiling, and remain NULL/unknown when absent. Submodules may be reported as file and symlinks may return their file target, so reported_type is not a definitive Git object classification. Expiring download URLs are descriptive and never automatically followed. Use Git trees for recursive listings. The object-media pinned schema omits symlink target/submodule URL; those fields are NULL on the path route, even if undocumented extra response keys exist.

Grain: `repository_id`, `content_path`, `content_sha`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `repository_contents__directory_readme` | `readme_directory` | Canonical repository content objects, unifying explicit path/root and preferred README retrieval. Grain is stable repository ID plus returned path and content/tree SHA; requested refs are selectors, not extra identities. Encoded content stays VARCHAR with its declared encoding, never falsely decoded as complete bytes. Object-media files of 1–100 MB may report encoding=none and empty content; over 100 MB is unsupported. Directory entries are immediate children only, fail at the 1,000-entry ceiling, and remain NULL/unknown when absent. Submodules may be reported as file and symlinks may return their file target, so reported_type is not a definitive Git object classification. Expiring download URLs are descriptive and never automatically followed. Use Git trees for recursive listings. The object-media pinned schema omits symlink target/submodule URL; those fields are NULL on the path route, even if undocumented extra response keys exist. |
| `repository_contents__path` | `content_path` | Canonical repository content objects, unifying explicit path/root and preferred README retrieval. Grain is stable repository ID plus returned path and content/tree SHA; requested refs are selectors, not extra identities. Encoded content stays VARCHAR with its declared encoding, never falsely decoded as complete bytes. Object-media files of 1–100 MB may report encoding=none and empty content; over 100 MB is unsupported. Directory entries are immediate children only, fail at the 1,000-entry ceiling, and remain NULL/unknown when absent. Submodules may be reported as file and symlinks may return their file target, so reported_type is not a definitive Git object classification. Expiring download URLs are descriptive and never automatically followed. Use Git trees for recursive listings. The object-media pinned schema omits symlink target/submodule URL; those fields are NULL on the path route, even if undocumented extra response keys exist. |
| `repository_contents__repositories` | `owner`, `repository`, `organization`, `repositories` | Canonical repository content objects, unifying explicit path/root and preferred README retrieval. Grain is stable repository ID plus returned path and content/tree SHA; requested refs are selectors, not extra identities. Encoded content stays VARCHAR with its declared encoding, never falsely decoded as complete bytes. Object-media files of 1–100 MB may report encoding=none and empty content; over 100 MB is unsupported. Directory entries are immediate children only, fail at the 1,000-entry ceiling, and remain NULL/unknown when absent. Submodules may be reported as file and symlinks may return their file target, so reported_type is not a definitive Git object classification. Expiring download URLs are descriptive and never automatically followed. Use Git trees for recursive listings. The object-media pinned schema omits symlink target/submodule URL; those fields are NULL on the path route, even if undocumented extra response keys exist. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `repository_id` | `BIGINT` | no |
| `repository` | `VARCHAR` | no |
| `content_ref` | `VARCHAR` | yes |
| `reported_type` | `VARCHAR` | no |
| `content_encoding` | `VARCHAR` | yes |
| `size` | `BIGINT` | no |
| `name` | `VARCHAR` | no |
| `content_path` | `VARCHAR` | no |
| `encoded_content` | `VARCHAR` | yes |
| `content_sha` | `VARCHAR` | no |
| `url` | `VARCHAR` | no |
| `git_url` | `VARCHAR` | yes |
| `html_url` | `VARCHAR` | yes |
| `download_url` | `VARCHAR` | yes |
| `links` | `STRUCT("git" VARCHAR, "html" VARCHAR, "self" VARCHAR)` | no |
| `symlink_target` | `VARCHAR` | yes |
| `submodule_git_url` | `VARCHAR` | yes |
| `entries` | `STRUCT("_links" STRUCT("git" VARCHAR, "html" VARCHAR, "self" VARCHAR), "download_url" VARCHAR, "git_url" VARCHAR, "html_url" VARCHAR, "name" VARCHAR, "path" VARCHAR, "sha" VARCHAR, "size" BIGINT, "type" VARCHAR, "url" VARCHAR)[]` | yes |

Approved metrics:

- `repository_content_object_count`: Successfully retrieved content objects at repository/path/SHA grain, not recursive file counts.
- `repository_content_reported_size_bytes`: Reported size of the distinct selected content objects. Directory size does not represent recursively contained bytes; this is not downloaded payload size.

### `artifact_deployment_records`

Artifact metadata deployment record occurrences for an organization and requested digest. Optional upstream IDs remain observations; ordinal identity exists only within this retrieval. All advertised Link pages are consumed. The optional total_count is not independently asserted; count measures returned occurrences. Raw timestamps remain strings because the pinned schema gives no date-time format. Attestation IDs are reported evidence, not joined to positional attestation envelope occurrences.

Grain: `organization_id`, `artifact_subject_digest`, `record_ordinal`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `artifact_deployment_records__organizations` | `organization` | Returned record occurrences in all advertised pages for the selected organization and digest; missing optional record IDs do not erase rows. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `organization_id` | `BIGINT` | no |
| `organization_login` | `VARCHAR` | no |
| `artifact_subject_digest` | `VARCHAR` | no |
| `record_ordinal` | `BIGINT` | no |
| `record_id` | `BIGINT` | yes |
| `reported_digest` | `VARCHAR` | yes |
| `logical_environment` | `VARCHAR` | yes |
| `physical_environment` | `VARCHAR` | yes |
| `cluster` | `VARCHAR` | yes |
| `deployment_name` | `VARCHAR` | yes |
| `tags` | `MAP(VARCHAR, VARCHAR)` | yes |
| `runtime_risks` | `VARCHAR[]` | yes |
| `created_at_raw` | `VARCHAR` | yes |
| `updated_at_raw` | `VARCHAR` | yes |
| `attestation_id` | `BIGINT` | yes |

Approved metrics:

- `artifact_deployment_record_count`: Returned artifact_deployment_records rows at the declared retrieval-qualified occurrence grain.

### `artifact_storage_records`

Artifact metadata storage record occurrences for an organization and requested digest. Optional upstream IDs remain observations; ordinal identity exists only within this retrieval. All advertised Link pages are consumed. The optional total_count is not independently asserted; count measures returned occurrences. Raw timestamps remain strings because the pinned schema gives no date-time format. The repository field identifies a registry repository, not a GitHub repository relationship.

Grain: `organization_id`, `artifact_subject_digest`, `record_ordinal`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `artifact_storage_records__organizations` | `organization` | Returned record occurrences in all advertised pages for the selected organization and digest; missing optional record IDs do not erase rows. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `organization_id` | `BIGINT` | no |
| `organization_login` | `VARCHAR` | no |
| `artifact_subject_digest` | `VARCHAR` | no |
| `record_ordinal` | `BIGINT` | no |
| `record_id` | `BIGINT` | yes |
| `name` | `VARCHAR` | yes |
| `reported_digest` | `VARCHAR` | yes |
| `artifact_url` | `VARCHAR` | yes |
| `registry_url` | `VARCHAR` | yes |
| `registry_repository` | `VARCHAR` | yes |
| `status` | `VARCHAR` | yes |
| `created_at_raw` | `VARCHAR` | yes |
| `updated_at_raw` | `VARCHAR` | yes |

Approved metrics:

- `artifact_storage_record_count`: Returned artifact_storage_records rows at the declared retrieval-qualified occurrence grain.
- `active_artifact_storage_record_count`: Returned storage record occurrences explicitly marked active.

### `artifact_metadata_jobs`

Status observations of previously created artifact metadata cluster jobs, qualified by organization, cluster and job ID. Missing started_at and successful-mutation counts remain unknown. The pinned errors field is an array of arbitrary objects with no typed fields and is explicitly uncovered.

Grain: `organization_id`, `cluster`, `job_id`.

| Retrieval route | Selection | Population |
| --- | --- | --- |
| `artifact_metadata_jobs__lookup` | `artifact_metadata_job_id` | One exact previously created cluster job; missing404 and identity mismatch fail. |

| Column | SQL type | Nullable |
| --- | --- | --- |
| `organization_id` | `BIGINT` | no |
| `organization_login` | `VARCHAR` | no |
| `cluster` | `VARCHAR` | no |
| `job_id` | `BIGINT` | no |
| `status` | `VARCHAR` | no |
| `started_at` | `TIMESTAMP WITH TIME ZONE` | yes |
| `mutated_record_count` | `BIGINT` | yes |

Approved metrics:

- `artifact_metadata_job_count`: Returned artifact_metadata_jobs rows at the declared retrieval-qualified occurrence grain.
- `pending_artifact_metadata_job_count`: Selected artifact metadata jobs whose observed lifecycle status is pending.
- `processing_artifact_metadata_job_count`: Selected artifact metadata jobs whose observed lifecycle status is processing.
- `completed_artifact_metadata_job_count`: Selected artifact metadata jobs whose observed lifecycle status is completed.
- `failed_artifact_metadata_job_count`: Selected artifact metadata jobs whose observed lifecycle status is failed.
- `artifact_metadata_mutated_record_count`: Records successfully mutated by selected jobs as reported in total_count; absent counts on pending/failed observations remain unknown. This read does not start a mutation.

## Reproduce

```sh
python scripts/generate_semantic_catalog.py
python scripts/generate_semantic_catalog.py --check
python scripts/generate_semantic_catalog.py --verify-source-cache /path/to/full-source-cache
```

The source lock and retained licenses record immutable upstream inputs. Runtime never downloads schemas. The existing broad GitHub model/default worker remain available. This connected graph is deliberately bounded. Reads are live across sources, without a transactionally consistent GitHub snapshot. HTTP errors, malformed responses and duplicate identities fail the query. All advertised pages are followed without a generated row or page cap; operation deadlines still apply. Crossfield adds no row cap; SQL LIMIT controls presentation.
