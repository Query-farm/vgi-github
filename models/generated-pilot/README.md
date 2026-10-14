# Connected generated GitHub model

Connected GitHub semantic model with organization, owner, repository and personal-user scopes. User activity includes authored PRs, issues, discussions and issue/PR, discussion and commit comments. Approved counts, active-day/repository measures, UTC calendar dimensions and evidence support explicit period comparisons.

Start with an organization, a user or a repository. Organizations connect to visible members, teams and repository activity; users connect to authored pull requests, issues, discussions and comments across visible repositories. Ownership, membership, authorship and reviewing are separate roles. Each metric retains its own entity grain, and every public source also supports callable detail.

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
SELECT user_login, user_count, authored_pr_count, authored_merged_pr_count,
       authored_median_merge_hours
FROM engineering.semantic.github(user => 'octocat') GROUP BY user_login;

SELECT authored_repository_name, authored_pr_count, authored_merged_pr_count
FROM engineering.semantic.github(user => 'octocat')
GROUP BY authored_repository_name ORDER BY authored_repository_name;

SELECT authored_pr_merged_day, authored_merged_pr_count, authored_median_merge_hours
FROM engineering.semantic.github(user => 'octocat')
WHERE authored_pr_merged_day >= DATE '2026-09-01'
  AND authored_pr_merged_day < DATE '2026-10-01'
GROUP BY authored_pr_merged_day ORDER BY authored_pr_merged_day;

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

For repository inventory, PRs, reviews and labels, choose exactly one of `organization`, `owner` and `repository`. `organization` explicitly selects an organization's visible repositories. The existing `owner` route resolves account type; a user owner lists PUBLIC owned repositories, not that person's contributions or private user inventory. Optional `pull_request_number` requires `repository`. Invalid, empty or conflicting scope arguments fail before HTTP.

The parameter catalog publishes example values as JSON and declares named, constant arguments. Examples are suggestions, never defaults: omitting `pull_request_number` still selects all PRs even though its example is `1`. The constraints include nonempty resource names, PR numbers of at least 1, mutually exclusive scope choices and the repository requirement for a PR number. Crossfield validates the rules for the selected datasets before provider execution; a user-only query does not require a repository. Detail entries publish the same rules for their own sources. NULL defaults count as absent when choosing a scope.

Organization profiles, organization memberships, teams and team memberships require `organization`. User profiles and all `authored_*` entities accept `user` or `users`. Only sources needed by the selected measures, dimensions and filters are fetched. Requesting a profile does not enumerate repositories; zero-activity users and empty organizations remain visible when `user_count` or `organization_count` establishes the inventory population.

For explicit cohorts use `users => [{'login': 'octocat'}, {'login': 'hubot'}]` or `repositories => [{'repository': 'Query-farm/crossfield'}, {'repository': 'Query-farm/vgi'}]`. Cohorts are mutually exclusive with their singular scope alternatives. NULL means absent; an empty list selects an empty population. Names must be nonempty and unique ignoring case, and resolved duplicate identities raise an error. `pull_request_number` continues to require one `repository`. Discovery publishes the exact LIST/STRUCT types and examples.

Each selected function streams its own traversal. Separate functions may fetch the same ancestors; cross-function HTTP sharing awaits a paginated row-map interface in VGI. Native stages reuse their own parent relation without mixing independent fact grains.

User PRs come from GitHub's cursor-paginated user connection across visible repositories. Each row must identify the selected canonical user as its author; missing or different authors fail rather than silently changing the population. This is authored-PR activity, not an all-contributions score, an events timeline or a capped search result. Authored issues, discussions and issue/discussion/commit comments use their own cursor-paginated user connections with the same author check. Issue comments include comments on pull requests; commit comments describe comments, not authored commits. Private or inaccessible content is outside the visible population. Deleted discussion subjects may lack repository context; the unknown-repository count makes those records visible.

Active-day and distinct-repository metrics are non-additive counts: request the desired grouping directly instead of summing daily or category subtotals. DATE dimensions use UTC days; weekly periods start on ISO Monday and monthly periods on the first day. Ordered case-insensitive title-prefix rules label explicit conventions such as `docs:` or `fix:`; unmatched titles stay `unclassified`. Detail rows retain titles, bodies, timestamps and URLs for checking the evidence. Repository primary language is current repository context, not the language of an individual contribution.

Membership means GitHub membership visible to the caller, not employment. Public-only credentials cannot establish a complete private roster. Team membership includes members inherited from child teams; nullable role/inheritance fields preserve what the pinned API actually supplies. `team_membership_count` counts team/account pairs. Someone in two teams contributes two memberships, but does not become two organization members. PR/review measures cannot be grouped through a team's membership: that attribution rule has not been approved. Organization members are not silently equated with all contributors.

API meaning: [user activity](https://docs.github.com/en/graphql/reference/users#user), [organization membership](https://docs.github.com/en/rest/orgs/members#list-organization-members), [effective team membership](https://docs.github.com/en/rest/teams/members#list-team-members).

Include `repository_count` to establish repository inventory as the grouping axis, including empty repositories. PR-only reports describe the PR population. Label counts describe definitions, not assignments. Review counts describe records, not distinct reviewers, latest decisions or merge eligibility.
Count metrics return zero for an established group with no matching records. Median merge time remains NULL for an empty merged cohort.

`pull_request_created_day`, `pull_request_merged_day`, `review_submitted_day`, `authored_pr_created_day` and `authored_pr_merged_day` are approved DATE dimensions computed by DuckDB from the corresponding timestamp. They use Gregorian UTC calendar days, with a required `TimeZone='UTC'` session. Unmerged PRs have a NULL merge day; a missing review submission timestamp stays NULL. A merge-day filter selects PRs merged in the interval; a creation-day filter selects PRs created in it. Review-day filtering selects review activity and does not define a PR merge cohort. The model preserves these different populations and roles.

Schema facts define types; declarative scopes select sources, traversals map parent fields to child inputs, and semantic relationships define approved many-to-one joins. Business recipes define populations and elapsed-hour calculations. Saved reports are optional; this package needs none.

## Research a user's activity

After attaching `engineering` as above, choose a user and ask for approved measures
and dimensions directly. This monthly PR query is included verbatim in
the native SQLLogicTests, with independently authored expected answers:

```sql
-- Replace the fixture login 'researcher' and dates for a real account.
SELECT authored_pr_created_month, authored_pr_count,
       authored_pr_active_days, authored_pr_repository_count,
       authored_median_merge_hours
FROM engineering.semantic.github(user => 'researcher')
WHERE authored_pr_created_day >= DATE '2026-08-01'
  AND authored_pr_created_day < DATE '2026-10-01'
GROUP BY authored_pr_created_month
ORDER BY authored_pr_created_month;
```

Swap the month dimension for `authored_pr_created_week`, `authored_repository_name`,
`authored_pr_title_category` or `authored_pr_repository_language` to investigate timing,
repository mix or explicit title conventions. The issue, discussion and comment
families have their own count, active-day, repository and UTC date fields listed below.
Only the selected populations are fetched. Prefix the SELECT with `EXPLAIN (SEMANTIC)`
to inspect the approved grain, population and expanded SQL without fetching records.

To compare a cohort, pass typed resource rows instead of writing one query per user:

```sql
PREPARE github_user_cohort AS
SELECT user_login, user_count, authored_pr_count, authored_issue_count
FROM engineering.semantic.github(users => $1)
GROUP BY user_login
ORDER BY user_login;
EXECUTE github_user_cohort([{'login': 'octocat'}, {'login': 'hubot'}]);
```

The profile count keeps users with no observed activity in the result. An empty
cohort returns no grouped rows. Use `repositories => [{'repository': 'owner/name'}]`
for an explicit repository population. `user`/`users` and the repository scope
alternatives are mutually exclusive; discovery exposes both forms and examples.

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

This profile covers visible authored PRs, issues, discussions and the three comment
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
SELECT activity_user_id, activity_user, authored_pr_created_month, activity_repository_id, authored_repository_name,
       authored_pr_count, monthly_authored_pr_total,
       monthly_repository_pr_share
FROM engineering.semantic.github(user=>'researcher')
GROUP BY activity_user_id, activity_user, authored_pr_created_month,
         activity_repository_id, authored_repository_name;
```

Monthly ranks compare only the selected visible user cohort. Equal counts share rank; users with no observed PRs have no activity row. This is activity volume, not an impact score.

```sql
SELECT activity_user_id, activity_user, authored_pr_created_month, authored_pr_count, monthly_user_pr_rank
FROM engineering.semantic.github(users=>[{'login':'alice'},{'login':'bob'},{'login':'researcher'},{'login':'carol'}])
GROUP BY activity_user_id, activity_user, authored_pr_created_month;
```

UTC days and fixed US Eastern reporting days are explicit alternatives. The _eastern_day dimension uses America/New_York daylight-saving rules, never a GitHub profile location. Keep the required session TimeZone='UTC'; a changed session raises TIMEZONE_MISMATCH.

```sql
SELECT authored_pr_created_day, authored_pr_created_eastern_day, authored_pr_count
FROM engineering.semantic.github(user=>'researcher')
GROUP BY authored_pr_created_day, authored_pr_created_eastern_day;
```

## Entity contracts

### `repositories`

Canonical visible repository inventory. Organization scopes follow credential visibility; user scopes list PUBLIC owned repositories only.

Grain: `repository_id`.

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

Approved metrics:

- `repository_count`: Visible repository entities, including repositories with no PRs or labels.

### `pull_requests`

All selected open and closed pull requests, preserving PR grain and author role.

Grain: `repository_id`, `pull_request_number`.

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
| `merge_hours` | `DOUBLE` | yes |
| `pull_request_created_day` | `DATE` | no |
| `pull_request_merged_day` | `DATE` | yes |

Approved metrics:

- `pull_request_count`: All selected open and closed PR records; each PR counts once regardless of reviews.
- `merged_prs`: PRs with a merge timestamp, including bots and draft waiting time.
- `median_merge_hours`: Exact continuous median elapsed UTC hours from PR creation to merge. NULL for an empty merged cohort; independent of review multiplicity.

### `pull_request_reviews`

Review records including pending and dismissed records; reviewer and PR-author roles remain distinct. Not latest reviewer decisions or merge eligibility.

Grain: `repository_id`, `pull_request_number`, `review_id`.

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

Current repository label definitions, including unused labels; not issue/PR memberships.

Grain: `repository_id`, `label_id`.

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

Canonical organization profiles for an explicit organization scope; not an inventory of every organization on GitHub.

Grain: `organization_id`.

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

Current organization membership visible to the attached credentials, including concealed members only when authorized. Membership does not imply employment; outside repository contributors are not members.

Grain: `organization_id`, `user_id`.

| Column | SQL type | Nullable |
| --- | --- | --- |
| `organization_id` | `BIGINT` | no |
| `user_id` | `BIGINT` | no |
| `member_login` | `VARCHAR` | no |
| `member_type` | `VARCHAR` | no |

Approved metrics:

- `organization_member_count`: Current visible organization-member relationships, one per organization and account. Credential visibility defines the population; not employees or distinct members across organizations.

### `teams`

Teams in the selected organization visible to the attached credentials; includes teams with no returned members.

Grain: `team_id`.

| Column | SQL type | Nullable |
| --- | --- | --- |
| `organization_id` | `BIGINT` | no |
| `team_id` | `BIGINT` | no |
| `team_slug` | `VARCHAR` | no |
| `team_name` | `VARCHAR` | no |
| `description` | `VARCHAR` | yes |
| `privacy` | `VARCHAR` | yes |
| `team_type` | `VARCHAR` | no |

Approved metrics:

- `team_count`: Current visible team identities in the selected organization, including empty teams.

### `team_memberships`

Effective membership returned for each visible team. One person in two teams contributes two memberships. Child-team membership may be included by GitHub; optional role and inherited fields remain NULL when absent.

Grain: `team_id`, `user_id`.

| Column | SQL type | Nullable |
| --- | --- | --- |
| `organization_id` | `BIGINT` | no |
| `team_id` | `BIGINT` | no |
| `user_id` | `BIGINT` | no |
| `team_member_login` | `VARCHAR` | no |
| `member_role` | `VARCHAR` | yes |
| `membership_inherited` | `BOOLEAN` | yes |

Approved metrics:

- `team_membership_count`: Current visible effective team-account pairs, including inherited membership when returned. Additive over teams as memberships, not distinct people or attributable PR activity.

### `users`

One canonical personal GitHub user profile. User scope does not mean owned repositories; organization logins reject.

Grain: `user_id`.

| Column | SQL type | Nullable |
| --- | --- | --- |
| `user_id` | `BIGINT` | no |
| `user_login` | `VARCHAR` | no |
| `account_type` | `VARCHAR` | no |
| `name` | `VARCHAR` | yes |
| `created_at` | `TIMESTAMP WITH TIME ZONE` | no |

Approved metrics:

- `user_count`: Selected personal user accounts, including users with no visible authored PRs.

### `authored_pull_requests`

PRs authored by the selected personal user across visible repositories, including repositories the user does not own. Each row's author must match the canonical user or the query fails. This is independent of owned-repository inventory.

Grain: `pull_request_node_id`.

| Column | SQL type | Nullable |
| --- | --- | --- |
| `user_id` | `BIGINT` | no |
| `user_login` | `VARCHAR` | no |
| `pull_request_node_id` | `VARCHAR` | no |
| `pull_request_number` | `BIGINT` | no |
| `state` | `VARCHAR` | no |
| `title` | `VARCHAR` | no |
| `created_at` | `TIMESTAMP WITH TIME ZONE` | no |
| `merged_at` | `TIMESTAMP WITH TIME ZONE` | yes |
| `repository_node_id` | `VARCHAR` | no |
| `repository_name` | `VARCHAR` | no |
| `author_login` | `VARCHAR` | yes |
| `url` | `VARCHAR` | no |
| `body` | `VARCHAR` | no |
| `updated_at` | `TIMESTAMP WITH TIME ZONE` | no |
| `repository_language` | `VARCHAR` | yes |
| `merge_hours` | `DOUBLE` | yes |
| `authored_pr_created_day` | `DATE` | no |
| `authored_pr_merged_day` | `DATE` | yes |
| `authored_pr_created_week` | `DATE` | no |
| `authored_pr_created_month` | `DATE` | no |
| `authored_pr_title_category` | `VARCHAR` | no |

Approved metrics:

- `authored_pr_count`: All visible open and closed PRs authored by the selected user, regardless of who owns each repository.
- `authored_merged_pr_count`: Visible PRs authored by the selected user with a non-NULL merge timestamp.
- `authored_median_merge_hours`: Exact continuous median elapsed UTC hours from creation to merge for visible authored PRs; NULL for an empty merged cohort.
- `authored_pr_active_days`: Distinct UTC creation dates represented by selected visible records. Non-additive across repositories and other overlapping groups; inactive dates contribute zero.
- `authored_pr_repository_count`: Distinct known repository identities represented by selected visible records. Non-additive across dates/categories; unknown repository context is excluded.

### `authored_issues`

Issues authored by the selected user across visible repositories. Creation activity; current status is not status at a historical period end.

Grain: `issue_node_id`.

| Column | SQL type | Nullable |
| --- | --- | --- |
| `user_id` | `BIGINT` | no |
| `user_login` | `VARCHAR` | no |
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
| `authored_issue_created_day` | `DATE` | no |
| `authored_issue_created_week` | `DATE` | no |
| `authored_issue_created_month` | `DATE` | no |
| `authored_issue_title_category` | `VARCHAR` | no |

Approved metrics:

- `authored_issue_count`: Issues authored by the selected user across visible repositories. Creation activity; current status is not status at a historical period end. Each visible source identity counts once; event time is its creation timestamp.
- `authored_issue_active_days`: Distinct UTC creation dates represented by selected visible records. Non-additive across repositories and other overlapping groups; inactive dates contribute zero.
- `authored_issue_repository_count`: Distinct known repository identities represented by selected visible records. Non-additive across dates/categories; unknown repository context is excluded.

### `authored_discussions`

Repository discussions started by the selected user across visible repositories.

Grain: `discussion_node_id`.

| Column | SQL type | Nullable |
| --- | --- | --- |
| `user_id` | `BIGINT` | no |
| `user_login` | `VARCHAR` | no |
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
| `authored_discussion_created_day` | `DATE` | no |
| `authored_discussion_created_week` | `DATE` | no |
| `authored_discussion_created_month` | `DATE` | no |
| `authored_discussion_title_category` | `VARCHAR` | no |

Approved metrics:

- `authored_discussion_count`: Repository discussions started by the selected user across visible repositories. Each visible source identity counts once; event time is its creation timestamp.
- `authored_discussion_active_days`: Distinct UTC creation dates represented by selected visible records. Non-additive across repositories and other overlapping groups; inactive dates contribute zero.
- `authored_discussion_repository_count`: Distinct known repository identities represented by selected visible records. Non-additive across dates/categories; unknown repository context is excluded.

### `authored_issue_comments`

Issue and PR timeline comments authored by the selected user; these are comment records, not review submissions or distinct issues.

Grain: `comment_node_id`.

| Column | SQL type | Nullable |
| --- | --- | --- |
| `user_id` | `BIGINT` | no |
| `user_login` | `VARCHAR` | no |
| `comment_node_id` | `VARCHAR` | no |
| `created_at` | `TIMESTAMP WITH TIME ZONE` | no |
| `updated_at` | `TIMESTAMP WITH TIME ZONE` | no |
| `url` | `VARCHAR` | no |
| `body` | `VARCHAR` | no |
| `repository_node_id` | `VARCHAR` | no |
| `repository_name` | `VARCHAR` | no |
| `repository_language` | `VARCHAR` | yes |
| `author_login` | `VARCHAR` | yes |
| `authored_issue_comment_created_day` | `DATE` | no |
| `authored_issue_comment_created_week` | `DATE` | no |
| `authored_issue_comment_created_month` | `DATE` | no |

Approved metrics:

- `authored_issue_comment_count`: Issue and PR timeline comments authored by the selected user; these are comment records, not review submissions or distinct issues. Each visible source identity counts once; event time is its creation timestamp.
- `authored_issue_comment_active_days`: Distinct UTC creation dates represented by selected visible records. Non-additive across repositories and other overlapping groups; inactive dates contribute zero.
- `authored_issue_comment_repository_count`: Distinct known repository identities represented by selected visible records. Non-additive across dates/categories; unknown repository context is excluded.

### `authored_discussion_comments`

Discussion comments and replies authored by the selected user. Missing discussion/repository context remains NULL and does not discard an attributable comment.

Grain: `comment_node_id`.

| Column | SQL type | Nullable |
| --- | --- | --- |
| `user_id` | `BIGINT` | no |
| `user_login` | `VARCHAR` | no |
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
| `authored_discussion_comment_created_day` | `DATE` | no |
| `authored_discussion_comment_created_week` | `DATE` | no |
| `authored_discussion_comment_created_month` | `DATE` | no |

Approved metrics:

- `authored_discussion_comment_count`: Discussion comments and replies authored by the selected user. Missing discussion/repository context remains NULL and does not discard an attributable comment. Each visible source identity counts once; event time is its creation timestamp.
- `authored_discussion_comment_active_days`: Distinct UTC creation dates represented by selected visible records. Non-additive across repositories and other overlapping groups; inactive dates contribute zero.
- `authored_discussion_comment_repository_count`: Distinct known repository identities represented by selected visible records. Non-additive across dates/categories; unknown repository context is excluded.
- `authored_discussion_comment_unknown_repository_count`: Visible discussion comments with unavailable discussion/repository context. Included in comment count, excluded from distinct known repositories.

### `authored_commit_comments`

Commit comments authored by the selected user, not commits or code-change counts.

Grain: `comment_node_id`.

| Column | SQL type | Nullable |
| --- | --- | --- |
| `user_id` | `BIGINT` | no |
| `user_login` | `VARCHAR` | no |
| `comment_node_id` | `VARCHAR` | no |
| `created_at` | `TIMESTAMP WITH TIME ZONE` | no |
| `updated_at` | `TIMESTAMP WITH TIME ZONE` | no |
| `url` | `VARCHAR` | no |
| `body` | `VARCHAR` | no |
| `repository_node_id` | `VARCHAR` | no |
| `repository_name` | `VARCHAR` | no |
| `repository_language` | `VARCHAR` | yes |
| `author_login` | `VARCHAR` | yes |
| `authored_commit_comment_created_day` | `DATE` | no |
| `authored_commit_comment_created_week` | `DATE` | no |
| `authored_commit_comment_created_month` | `DATE` | no |

Approved metrics:

- `authored_commit_comment_count`: Commit comments authored by the selected user, not commits or code-change counts. Each visible source identity counts once; event time is its creation timestamp.
- `authored_commit_comment_active_days`: Distinct UTC creation dates represented by selected visible records. Non-additive across repositories and other overlapping groups; inactive dates contribute zero.
- `authored_commit_comment_repository_count`: Distinct known repository identities represented by selected visible records. Non-additive across dates/categories; unknown repository context is excluded.

## Reproduce

```sh
python scripts/generate_semantic_catalog.py
python scripts/generate_semantic_catalog.py --check
python scripts/generate_semantic_catalog.py --verify-source-cache /path/to/full-source-cache
```

The source lock and retained licenses record immutable upstream inputs. Runtime never downloads schemas. The existing broad GitHub model/default worker remain available. This connected graph is deliberately bounded. Reads are live across sources, without a transactionally consistent GitHub snapshot. HTTP errors, malformed responses and duplicate identities fail the query. All advertised pages are followed without a generated row or page cap; operation deadlines still apply. Crossfield adds no row cap; SQL LIMIT controls presentation.
