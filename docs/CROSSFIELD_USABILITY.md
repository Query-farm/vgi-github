# Complete GitHub semantic access through Crossfield

**Wider implementation plan.** The broad model's public name is `github`.
An opt-in [connected generated model](../models/generated-pilot/README.md)
implements a ten-entity graph: repositories, PRs, reviews, labels, organizations,
users, organization memberships, teams, team memberships and authored PRs.
Organization/user/owner/repository scopes support model-owned traversal,
fifteen freely selected measures and callable detail tables.
Both packages expose the public model name `github`; separate attachments such
as `engineering` and `legacy` provide scope while their internal identities
remain distinct. The generated package does not replace the broad model yet.
Examples below describe the full target, including capabilities beyond that graph.
This document owns the wider user workflow and implementation sequence;
[integration notes](CROSSFIELD_SPEC.md) record runtime evidence and limits.

**Goal: the whole worker read surface is usable through typed SQL entities,
modeled relationships and approved measures, without requiring REST or GraphQL
knowledge.** Implementation phases determine order; completion requires every
phase and every inventory item. Reviews are an early integration case, not the
boundary of the project.

Researchers must be able to discover fields, select single resources or cohorts,
inspect populations, combine related data and export typed rows. API request
details belong in the worker and model.

## What completeness means

The REST denominator is the checked-in manifest: **780 GET operations across 48
categories**, with separate `api.github.com` and Enterprise Cloud availability.
The target includes all 21 typed functions and the general GraphQL interface.
Pin the corresponding public GraphQL schema and inventory its query-accessible
domain fields, types, connections and arguments; accepting a GraphQL string is
not coverage of that schema. Upstream changes extend this ledger on revision.

| Surface | Required semantic access |
| --- | --- |
| Entity collections and individual resources | Named SQL tables/functions, typed fields, keys, supported scopes and automatic pagination. Multiple endpoints may share one entity definition. |
| Relationships and child collections | Model-owned traversal, qualified identities and approved joins; users do not enumerate every parent or construct child requests. |
| Analytical facts | Approved counts, state measures, durations, rates and distributions wherever the source supports a defined population. Every published measure has an explicit recipe and numerical tests. |
| Configuration, permissions, membership and reference data | Typed singleton/detail relations and meaningful state/count measures. These families are required even when they are not traditional reporting facts. |
| Logs, text, archives and binary downloads | Named resource access with typed metadata and native text/BLOB payloads. Unstructured content remains content; users need no REST operation ID or media-type selection. |
| GraphQL-only fields and connections | The same entity/dimension vocabulary, generated typed projections and complete connection traversal. Interfaces/unions retain their concrete type and approved fields. |

Keep a machine-readable ledger alongside `source_inventory.json`: source operation
or GraphQL field, product/version, public SQL entry, supported arguments/fields,
scope and traversal, grain, metric definitions, permissions and test references.
An item is complete only when its declared public contract is implemented and
tested. Raw JSON passthrough, a deferred label or a schema-generation success alone
does not close it. Product-specific or inaccessible data has a typed contract and
explicit capability/error behavior; it is not silently omitted from the ledger.

Completion is finite against these pinned contracts. It does not promise every
future GitHub field or every conceivable business calculation. New measures can
use the complete typed foundation without introducing another API wrapper.

## What the current query actually does

In the existing broad model,
`SELECT repository_count FROM engineering.semantic.github(owner => 'Query-farm')`
counts rows from the worker's owned-repository listing. It uses complete pagination
within declared bounds. It does not fetch PRs, reviews or CI for those repositories;
those metrics still require their own `repository` input. The connected generated
model instead follows its declared repository/PR/review graph for owner-scoped
queries, and keeps author and reviewer dimensions separate.

The broad worker's `ReposFunction` currently calls
`/users/{owner}/repos`, which GitHub documents as a public-repository listing.
The model's word “visible” and some worker descriptions are broader than the
endpoint guarantees. Organization and authenticated-user listings have separate
contracts. Private organization coverage cannot be inferred from having a token,
and capped search is not a substitute for complete inventory.
[GitHub repository API contracts](https://docs.github.com/en/rest/repos/repos#list-repositories-for-a-user).

For `owner`, the generated profile resolves account type before choosing the
organization or user repository route. Organization inventory follows credential
visibility; a personal owner's inventory contains **public owned repositories**.
The explicit `organization` scope also connects profiles, members and teams.
The separate `user` scope provides a personal profile and authored PRs across
visible repositories, including those the user does not own. Membership and
authorship remain separate; team attribution is not inferred. Private user-owned
inventory and multiple-repository cohort inputs remain wider-plan work.

The previous milestone exposed all pinned APIs at response grain. Its 780 REST
operation IDs establish access coverage; they do not establish 780 usable semantic
entities, approved measures or live-tested endpoints. The 21 typed functions are
the foundation for the researcher interface.

## The intended SQL experience

Keep `engineering.semantic.github(...)` for approved measures. Extend the existing
`detail` schema with callable entity tables; keep `reports` for reusable analyses.
Names describe GitHub concepts, regardless of the underlying transport.

```sql
-- Proposed: the same measures across the owner's repositories.
SELECT repository_name, merged_prs, median_merge_hours
FROM engineering.semantic.github(owner => 'Query-farm')
WHERE pulls_merged_day >= DATE '2026-09-01'
  AND pulls_merged_day < DATE '2026-10-01'
GROUP BY repository_name;

-- Proposed: review records, with no endpoint or JSON knowledge required.
SELECT repository_name, pull_request_number,
       reviewer_login, review_state, submitted_at
FROM engineering.detail.pull_request_reviews(
    repository => 'Query-farm/crossfield'
)
WHERE submitted_at >= TIMESTAMP '2026-09-01 00:00:00'
  AND submitted_at < TIMESTAMP '2026-10-01 00:00:00';

-- Proposed: select a particular PR through a business identifier.
SELECT reviewer_login, review_state, submitted_at
FROM engineering.detail.pull_request_reviews(
    repository => 'Query-farm/crossfield', pull_request_number => 1
);

-- Proposed: approved review measures over an organization.
SELECT repository_name, submitted_review_count, reviewed_pr_count
FROM engineering.semantic.github(owner => 'Query-farm')
WHERE review_submitted_day >= DATE '2026-09-01'
  AND review_submitted_day < DATE '2026-10-01'
GROUP BY repository_name;

-- Proposed: project discovery and traversal are part of the model.
SELECT project_title, project_item_count, archived_project_items
FROM engineering.semantic.github(owner => 'Query-farm')
GROUP BY project_title;
```

`repository_name` is a proposed shared dimension backed by repository identity.
It is not a spelling change to unrelated source columns. Existing explicit
dataset names remain useful where dimensions describe different concepts.

The first detail call enumerates the selected repository's PRs, then their reviews.
The third call selects one PR. An owner-scoped equivalent discovers repositories
first. Users can still supply stable project numbers; project titles are readable
dimensions and filters, not silently unique keys. A title used as a lookup must
match exactly one project or return an actionable ambiguity error.

## Scope and population rules

| Selection | Intended population |
| --- | --- |
| `repository => 'owner/name'` | One explicitly selected repository. |
| `owner => 'login'` | Owned repositories or projects available under the selected credential scope, according to the requested entity/metric. It does not add repositories merely collaborated on. |
| `pull_request_number => n` | One PR within an explicitly selected repository. Omitting it enumerates PRs. |
| `project_number => n` | One project within an owner. Omitting it for project-item queries enumerates projects. |
| `visibility => 'public'` | Proposed optional repository scope for public-data studies. Default repository scope is accessible repositories, with credential limitations disclosed. |

Offer one coherent scope per call, including single or multiple repositories and
owners, explicit research cohorts, and resource-specific scopes such as enterprise,
installation, user, project or workflow run. Add typed collection/cohort inputs
where needed instead of requiring repeated manual calls. Overlapping selections
must resolve to one declared entity population, with duplicate handling exposed.
Conflicting or irrelevant inputs reject. Resolve account kind once in the worker
at execution; routine callers need not know `organization` versus `user`. Infer
no repository from a project title. Project metrics use an owner/project scope;
repository visibility options do not silently filter project populations.

Correct owner enumeration chooses reviewed organization, authenticated-user or
installation routes as appropriate for the token. Other-user public enumeration
must remain explicit in metadata. An unsupported credential/scope combination
fails with guidance rather than claiming complete private coverage. “Accessible”
does not prove the existence or absence of resources hidden from the credential.
Archived repositories and forks remain included unless the model or caller
explicitly filters approved dimensions; definitions disclose that population.

Counts refer to entities at declared keys, not response pages. Repository totals
must not multiply when reviews or CI facts are added. PR numbers are qualified
by repository identity; project membership is qualified by project identity.
Keep repositories/projects with no children in grouped counts as zero, and
undefined durations as NULL. Filtered cohorts and denominators remain visible.

## Implementation sequence

| Step | Change and deliverable | Acceptance |
| --- | --- | --- |
| 1. Inventory and correct scope | Build the full REST/GraphQL coverage ledger. Correct owner resolution, public/private repository selection and source descriptions. | Every pinned operation/read field has an assigned SQL contract and status. Organization/user/token cases have independently expected inventories. |
| 2. Generate the typed foundation | Use pinned OpenAPI response schemas and GraphQL types to generate adapters, typed arguments/results, documentation and structural tests. Apply reviewed overrides for entity names, keys, pagination, polymorphism and dynamic fields. | No operation is dropped because it is outside the initial reporting families. Schema drift is explicit; generated fields are not automatically approved measures. |
| 3. Complete generic query composition | Add alternative scopes, typed cohort inputs, callable detail entries, parent/child traversal and shared dimensions. Use reviews, Projects and an organization-wide PR/CI query as integration cases. | Single-resource and cohort queries agree. Empty parents survive, facts do not multiply, and callers need no endpoint IDs, JSON maps or cursor management. |
| 4. Complete every entity family | Implement all ledger contracts across development, delivery, collaboration, identity, administration, security, billing, usage and reference/content APIs. Reuse adapters for equivalent REST/GraphQL access. | All 48 REST categories and pinned GraphQL domain fields have typed SQL access and product/permission behavior. Raw-only or deferred entries remain gaps. |
| 5. Complete the measures and research workflows | Define applicable metrics for every family, including review latency, workflow attempts/duration, deployments, code changes, security state, usage and billing. Deliver discovery, repair, explain and export workflows. | Each declared measure has approved population/grain/units and independent answers. Required intermediate aggregation and relationship capabilities are implemented. |
| 6. Close the ledger | Reconcile generated contracts, public catalog entries, examples and tests; finish every uncovered entry. | No unexplained, raw-only or deferred item is counted as complete. Every mapping and measure has passing evidence; unavailable live credentials are recorded separately from deterministic passes. |

All six steps are required for completion. Each can deliver usable improvements
while subsequent steps continue; an early reviews example does not close the goal.

The family inventory includes repositories/Git data/issues/pulls/reactions,
Actions/checks/deployments/releases/packages, Discussions/Projects,
users/orgs/teams/enterprise/SCIM/apps, code/dependency/secret security,
billing/Copilot/agents/hosted compute/Codespaces, and classroom/gists/migrations/
reference/search APIs. The checked-in manifest is authoritative, so this readable
grouping cannot hide a missed category. Search retains its documented discovery
population and cannot substitute for complete inventory.

GitHub publishes both an [OpenAPI description](https://docs.github.com/en/rest/about-the-rest-api/about-the-openapi-description-for-the-rest-api)
and a [public GraphQL schema](https://docs.github.com/en/graphql/overview/public-schema).
Use those machine-readable contracts for breadth, preserving their licenses and
notices, and reviewed semantic definitions for meaning. Preserve nested
STRUCT/LIST values and intentional text/BLOB content. Dynamic project fields
need typed value relations and reviewed named projections, not guessed types
or a JSON-only escape hatch.

### Crossfield changes versus worker changes

The worker owns API routes, generated or fixed approved GraphQL documents,
response decoding, typed columns and cursor/Link traversal. GitHub review listing is per PR; pagination
and any nested GraphQL connections must be completed by these adapters.
[Review API](https://docs.github.com/en/rest/pulls/reviews#list-reviews-for-a-pull-request),
[GraphQL pagination](https://docs.github.com/en/graphql/guides/using-pagination-in-the-graphql-api).

The model owns scope alternatives, approved source bindings, invocation edges,
keys, shared dimensions, metric recipes and population rules. Native DuckDB
executes the resulting joins and table functions. Reuse Crossfield's existing
source pruning and row-map stages. Do not add a Crossfield call scheduler,
unconditional result buffering or an API-specific SQL parser.

Today `semantic_query` is one input template; it cannot choose repository versus
owner traversal from alternative argument sets. It also excludes `detail_dataset`.
The generic composition step therefore requires extension work: validated scope
alternatives, callable detail descriptors, original-intent checks and metadata for
those calls. Extend native argument handling for required structured/cohort inputs;
support new reviewed relationship or intermediate-aggregation patterns when a
ledger contract requires them. Existing implementation limits are work to resolve,
not reasons to silently remove families from the target.
Named saved reports can reuse the resulting definitions; they should not be the
only way to choose fields. Keep stable entity/metric IDs independent of the
chosen scope. Prepared/view identity must retain the selected template and inputs.
No core patch is planned; require a concrete missing generic hook before adding one.

Only push filters ahead of remote calls when they preserve the requested
population. A September review can belong to an August PR; review submission
filters must not become PR creation filters. Query LIMIT is a presentation
operation and must not masquerade as a complete source listing. A broad scope
that exceeds existing execution bounds fails with a suggestion for a smaller
scope; exact request counts cannot be known by metadata-only EXPLAIN.

### Measures that need more than a typed endpoint

Submitted-review counts exclude pending reviews with no submission timestamp;
state-dependent counts describe the returned current state. “Approved review”
does not mean a PR satisfies branch protection. GitHub documents pending reviews
as unsubmitted records without `submitted_at`.
[Review state contract](https://docs.github.com/en/rest/pulls/reviews).

First-review latency needs one approved first-review observation per PR before
aggregation across PRs. Define reviewer exclusions, bots, draft time, cohort date,
unreviewed PRs and elapsed-hour units before exposing a median. Prove the necessary
intermediate PR grain through the provider compiler; if unsupported, add a small
generic approved aggregation stage. Do not average repository medians or hide a
business recipe in transport decoding. This can follow review counts during
implementation but remains required before the review-analysis scope is complete.

Deployment frequency similarly needs explicit environment and success rules;
workflow duration needs attempt/completion evidence. Keep these proposed measures
distinct from existing, validated metrics until their independent tests pass.

## Discovery and a researcher's session

1. Inspect `crossfield_members()`, `crossfield_queries()` and parameter discovery
   for entity descriptions, row grain, approved metrics, scopes and required
   inputs. Extend the existing global functions to describe callable detail and
   scope alternatives; do not create metadata tables in each attachment.
2. Use `DESCRIBE` and `EXPLAIN (SEMANTIC)` on the intended query without fetching
   GitHub data. Show the owner/repository traversal, fields, cohort, completeness
   limits and approved definitions. `EXPLAIN (SQL)` still shows generated SQL.
3. Select typed entity rows or approved metrics. Return semantic repair guidance
   for unsupported combinations, including the appropriate entity entry and
   scope. Do not suggest REST JSON or a GraphQL document as the normal repair.
4. Export detail through existing COPY/CTAS support and retain model revision,
   scope and observation time with the analysis. Live GitHub has no transactionally
   consistent historical snapshot; output is not historical state reconstruction.

Keep raw response helpers as a documented advanced interface. The main guide
should lead with research questions, typed rows and measures. Custom project
fields can expose a typed long-form entity (`project`, `item`, `field`, typed
value) before model authors approve named field projections; never infer a
cross-project dimension solely because two fields share the name “Status.”

## Validation and completion

Use the actual worker with independently authored HTTP fixtures and standard
native DuckDB SQLLogicTests on EC2, in both optimizer modes. Extend the existing
suites; no new custom runner, Python DuckDB build or capacity qualification.

Every operation/GraphQL mapping needs request, response/type and field-preservation
coverage. Each entity needs grain, scope, relationship, pagination and error cases;
each measure needs independent numerical expectations. Shared generated tests
can cover common contracts, while reviewed fixtures verify real semantic meaning.
Generation is not its own correctness oracle. Require catalog/discovery and
prepared/CTE/export coverage for each execution shape. Separately record which
product and credential profiles have live evidence; unrun tests are never passes.

Concrete acceptance examples include:

- An owner has three repositories, including one accessible private repository
  and one with no PRs. They contain PR counts 2/1/0. Owner inventory count is 3;
  grouped PR counts retain 2/1/0. A separate public scope excludes the private row.
- Reviews per PR are 2/0/1, all submitted. The owner total is three review records
  and two reviewed PRs, independent of unrelated workflow rows. A pending review
  adds one detail row but changes neither submitted count nor reviewed-PR count.
- PR number 1 in two repositories remains two PRs; IDs, NULL payloads, parent
  mismatches and duplicated review identities have explicit acceptance/rejection.
- A review submitted inside the time range for a PR created before it survives.
  Date filtering and empty cohorts reconcile detail with approved counts.
- Every page is consumed; exhausted bounds, inaccessible children and partial
  GraphQL errors fail, and a subsequent healthy query succeeds. Credentials do
  not leak into metadata or explain output.
- Scope selection, prepared values, attachment replacement, CTEs and native
  consumers retain approval. Discovery/explanation performs no GitHub data fetch;
  unrelated source families are not executed.

Required first-review fixtures use PR latencies 2 and 10 hours with one unreviewed
PR: the approved median is 6 hours over two observations. Repeated reviews must
not weight the PR twice. A passing entity-access test is not acceptance of this
latency recipe.

Equivalent fixtures cover each remaining family's measures and relationships,
including overlapping cohorts, project membership, workflow retries, deployment
state changes, security states and period/unit boundaries. The implementation
is complete only when the coverage ledger closes, not when the first example
or the current regression suite passes.
