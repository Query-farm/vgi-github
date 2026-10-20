# Crossfield integration notes

The [model guide](../models/README.md) owns user SQL and business definitions.
[build_model.py](../models/build_model.py) assembles the reviewed model and named
reports; [source_inventory.json](../models/source_inventory.json) records all
24 native source signatures and 344 source columns. This covers all 21 typed
`main` functions, all 780 pinned REST operations through `api.rest`, GraphQL and
endpoint discovery. Generated JSON is checked in; `--check` rejects changed
worker registrations, endpoint domains or stale generated artifacts.

## Runtime contract

- Use matching patched DuckDB `94abd4ed366569345faf5dc1e254ae6ca7311a76`,
  Crossfield and native VGI. Crossfield's `patches/duckdb/series` is authoritative;
  its fifth patch fixes correlated table in-out calls with named scalar options.
- Attach the worker with `reporting true, operation_timeout_seconds 120`.
  Crossfield checks immutable reporting, deadline and API-origin tags. The model
  pins complete keyed listings (`max_rows => 0`) and no result-cache reuse.
- Use a POSIX subprocess. Native VGI observes interruption, enforces finite
  reads and tears down failed workers; the worker bounds requests/retries and
  validation. HTTP transport is not qualified by these tests.
- The model-owned `semantic_query` contract maps seven named repository, account,
  discussion/comment and project inputs to approved providers. The callable semantic catalog entry
  retains the caller's metric selection, dimensions and filters. Only inputs and
  sources needed by that selection are retained; unused supplied inputs reject.
  `crossfield_parameters()` exposes types and source/metric dependencies. Named
  reports remain useful for fixed presentations and detail. Search remains capped
  discovery; neither search nor rate-limit data has approved aggregate metrics.
- Discussions and Projects validate complete rows before projection, including
  answer/state/timestamp evidence and parent identity. Nullable project content
  retains its item identity. Raw REST/GraphQL reports preserve response payloads
  and binary bodies without approving entity metrics. REST fixes all-Link-page
  traversal and API version; GraphQL preserves explicit connection cursors.
- GraphQL response grain uses exact, nonnullable source arguments. The extension
  validates one response per retained driver/request identity; different payloads
  for that same identity reject. This uses the existing native execution path
  and requires no new DuckDB core patch.
- UTC is mandatory. DATE parameters define half-open cohorts. Empty or reversed
  intervals yield empty cohorts under ordinary SQL semantics. NULL/invalid typed
  arguments reject. Required source identities and metric inputs validate before
  output projection. Live errors may follow already streamed rows.

Metric populations, units, non-additivity and source identity remain model-owned.
All provider calls execute through native DuckDB. There is no Python DuckDB
runner, Crossfield result buffer or bespoke call scheduler.

The isolated native VGI profile does not expose macros. DuckDB's global
`duckdb_functions()` inventory scans those catalogs and currently rejects even
when filtered to another catalog. Use `crossfield_*()` discovery with this
profile; Crossfield's native fixture separately checks its DuckDB catalog entries.

## Matching native VGI build

The isolated adapter is reproducible from the upstream VGI checkout plus the
two checked-in patches; retain VGI's license and notices. The first patch supplies
the earlier isolated DuckDB 2 profile. The second adds its scalar adapter and
current engine/signature compatibility. This is a qualified invocation profile,
not a port of every VGI feature. The profile removes direct and conditional
`duckdb_static` references from both archive link properties, so the loadable
extension resolves engine symbols from the matching host. Build on EC2:

```sh
git clone https://github.com/Query-farm/vgi.git /path/to/vgi-profile
git -C /path/to/vgi-profile checkout --detach de68c1786d517ad65bce535bc00d3c2e54d18c1e
git -C /path/to/vgi-profile apply /path/to/vgi-github/tests/crossfield/native-vgi-profile-base.patch
git -C /path/to/vgi-profile apply /path/to/vgi-github/tests/crossfield/native-vgi-profile.patch
printf '%s\n' 'duckdb_extension_load(vgi SOURCE_DIR /path/to/vgi-profile)' > /path/to/vgi-config.cmake
cmake -S /path/to/patched-duckdb -B /path/to/build-vgi \
  -DDUCKDB_EXTENSION_CONFIGS=/path/to/vgi-config.cmake \
  -DCMAKE_BUILD_TYPE=Release -DBUILD_UNITTESTS=OFF -DEXTENSION_STATIC_BUILD=OFF \
  -DVGI_ENABLE_IROH=OFF -DVGI_DUCKDB2_INVOCATION_PROFILE=ON \
  -DGIT_COMMIT_HASH=94abd4ed366569345faf5dc1e254ae6ca7311a76 \
  -DDUCKDB_EXPLICIT_VERSION=v2.0.0-dev0 -DArrow_DIR=/path/to/arrow/share/arrow
cmake --build /path/to/build-vgi --target vgi_loadable_extension -j 20
```

`patched-duckdb` must have Crossfield's complete seven-patch series applied.
Supply the installed Arrow CMake package for the target platform. The tested EC2
installation is `vgi/build/release/vcpkg_installed/arm64-linux/share/arrow`.
The output is `build-vgi/extension/vgi/vgi.duckdb_extension`. Native SQL fixtures
in the adapter's `test/duckdb2/` exercise its invocation/type contracts; the
Crossfield suites below validate the expanded worker package.

## Standard SQLLogicTest execution

Install the worker's locked dependencies on the build host. Set these paths for
the matching build and checkout (absolute paths are required):

```sh
export GITHUB_PROJECT=/path/to/vgi-github
export DUCKDB_BUILD=/path/to/crossfield/build
export VGI_EXTENSION=/path/to/build-vgi-scalar/extension/vgi/vgi.duckdb_extension
export CROSSFIELD_GITHUB_PACKAGE="$GITHUB_PROJECT/models/github-reporting.package.json"
export CROSSFIELD_GITHUB_WORKER="$GITHUB_PROJECT/.venv/bin/python $GITHUB_PROJECT/tests/crossfield/surface_fixture.py"
export SLURM_CPUS_ON_NODE=4
mkdir -p /tmp/github-slt-on
cd /tmp/github-slt-on
export CROSSFIELD_GITHUB_API_LOG="$PWD/requests.jsonl"
printf '%s\n' "$GITHUB_PROJECT/tests/crossfield/reporting.test" \
  "$GITHUB_PROJECT/tests/crossfield/surface.test" \
  "$GITHUB_PROJECT/tests/crossfield/raw_api.test" > tests.list
"$DUCKDB_BUILD/test/unittest" -f tests.list \
  --env-passthrough CROSSFIELD_GITHUB_PACKAGE \
  --env-passthrough CROSSFIELD_GITHUB_WORKER \
  --env-passthrough CROSSFIELD_GITHUB_API_LOG \
  --on-init "LOAD '$VGI_EXTENSION'; LOAD '$DUCKDB_BUILD/extension/crossfield/crossfield.duckdb_extension'"
```

Repeat in a separate directory with `; PRAGMA disable_optimizer` appended to
`--on-init`. The suite uses DuckDB's normal SQLLogicTest comparison and error
matching. External test paths use `-f`; a bare path can select no registered tests.

The fixture runs the real worker against `httpx.MockTransport`; it cannot make
network requests. [Fixture inputs](../tests/crossfield/FIXTURES.md) independently
define the numbers. API request logging proves attach/discovery/preparation and
explanation do not fetch source rows. Every named report executes. Tests also
cover free metric composition and repository totals, callable-input discovery,
CTEs, prepared arguments, dependency pruning, arrays, UTC boundaries, empty
cohorts, independent-fact combination, strict restrictions, malformed data,
access errors, late failures and recovery. Expanded cases cover discussion
answers, project membership, inaccessible content, custom-field JSON, REST
response pages and exact binary bytes, GraphQL request identity and partial errors.

For the connected generated profile, use the same native runner with these
inputs instead of the broad package and test files:

```sh
export CROSSFIELD_GITHUB_PACKAGE="$GITHUB_PROJECT/models/generated-pilot/github-generated.package.json"
export CROSSFIELD_GITHUB_WORKER="$GITHUB_PROJECT/.venv/bin/python $GITHUB_PROJECT/tests/crossfield/research_fixture.py"
printf '%s\n' "$GITHUB_PROJECT/tests/crossfield/connected.test" \
  "$GITHUB_PROJECT/tests/crossfield/people.test" \
  "$GITHUB_PROJECT/tests/crossfield/research.test" \
  "$GITHUB_PROJECT/tests/crossfield/research_examples.test" > tests.list
```

Run from a separate output directory for each optimizer mode. This package
contains fifteen connected entities and thirty-three measures, with no saved reports.
It tests organization/user/owner/repository selection, automatic parent
traversal, independent metric grains and callable detail. Organization profiles
connect memberships, teams and repository activity; personal users connect
authored PRs, issues, discussions and comments across repositories. Membership, authorship and reviewing remain
distinct roles. Overlapping team membership does not authorize contribution
attribution. Its producer worker streams through VGI's existing producer
protocol. No new native VGI continuation implementation or Crossfield result
buffer is involved. The full DuckDB 2 VGI port and live GitHub credentials remain
outside the deterministic profile's evidence.

Provider reporting-contract unit tests run separately on EC2:

```sh
uv run pytest -q -m 'not live' --ignore=tests/test_api_sql.py
uv run python models/build_model.py --check
```

Crossfield's normal CTest suite supplies the broader semantic and lifecycle
regression. Its optional schema checker validates the package without executing
SQL. These deterministic tests do not claim a live github.com integration run,
HTTP qualification, a historical snapshot or an all-platform release.

## Validation

The DuckDB baseline refresh to `94abd4ed366569345faf5dc1e254ae6ca7311a76`
passes **1,524 native SQLLogicTest assertions across nine suites per optimizer
mode** on EC2 Linux ARM64, October 20 UTC, with rebuilt Crossfield and native
VGI. Generated-artifact and pinned-source verification also pass for all nine
artifacts. Evidence is in Crossfield's `logs/dev/20261020T023415Z-2589-github-sql.log`,
`20261020T023824Z-3296-github-sql.log` and `20261020T023401Z-2539-github-check.log`.
These selected workloads use deterministic HTTP with the actual worker; they do
not qualify every generated operation, live github.com or HTTP/Iroh transport.
The dated checkpoints below retain their original artifacts and scope.

The manual [native model validation workflow](../.github/workflows/crossfield-models.yml)
runs the versioned Crossfield authoring validator against both checked-in model
profiles and retains source diagnostics as annotations, a summary and JSON.
It needs an explicitly published validator version and a reviewed action commit;
no release is assumed to exist and it does not rebuild DuckDB. Enable it on model
pull requests after pinning the first qualified release. Authoring validation
does not establish provider binding or numerical answers; the native VGI and
SQLLogicTest checks below remain the integration evidence.

The connected generated profile passed on EC2 Linux ARM64, October 13, 2026:
**963 native SQLLogicTest assertions per optimizer mode** across five suites, and
**237 generator/schema/actual-SDK producer checks**. This includes 299 assertions
for the exact published examples and 24 for native Crossfield definitions.
Revision 7 retains 15 public entities and 33 production metrics; the native-expression
proof adds test-only definitions. Generation, pinned-source checks and Ruff pass.
The maintained Crossfield `./dev` command ran the workflow; evidence is in
`crossfield/logs/dev/20261013T202546Z-12425-github-sql.log`,
`20261013T202849Z-13511-github-sql.log` and `20261013T202835Z-13454-github-test.log`.

The [research walkthrough](../models/generated-pilot/README.md#research-a-users-activity)
uses SQL maintained in [generation/examples/research](../generation/examples/research/).
The normal generator includes those statements in the guide, runnable `research.sql`
and `research_examples.test`. Edit the source SQL, then regenerate; `--check` rejects
stale copies. Numerical answers stay independently authored in
`research_examples.test.in`; generation neither executes SQL nor records answers.
DuckDB's ordinary SQLLogicTest runner checks the published examples. Earlier native
CLI output, including `EXPLAIN (SEMANTIC)`, remains in
`logs/github-contributions/research-session.log`.
Source-inclusion tests verify that edits reach the guide and native tests while
expected answers remain independently maintained.
The independent oracle compares 9 August records with 14 September records across
six authored activity populations, a calendar-day-normalized change of 60.74%.
PRs increase 2 to 3 while active PR days remain 2; repository shares, evidence URLs,
UTC boundary crossings, empty populations and later-page failures are checked.
Existing organization, team, PR and reviewer assertions remain passing.
The monthly example also supports PREPARE with user and/or date parameters.
Crossfield validates the target's timezone before optimizing the prepared plan;
the EXECUTE wrapper no longer incorrectly requires its own model. The research
SQLLogicTest passes **318 assertions per optimizer mode**, including strict and
semantic execution, changed date ranges and empty users. Evidence:
`crossfield/logs/dev/20261013T204305Z-18318-github-sql.log` and
`crossfield/logs/dev/20261013T204338Z-18165-github-sql.log`.

Crossfield's **218 CTest cases pass** across the full regression and corrected
bound-validation fixture rerun (`crossfield/logs/dev/20261013T204417Z-18726-test.log`
and `20261013T204626Z-19291-test.log`). The unchanged authoring-check checkpoint
passes **41/41 checks** (`crossfield/logs/user-activity/distinct-zero-schema-authoring.log`).
The extension now permits zero for a missing group only for existing additive
policies or a proven direct non-additive COUNT(DISTINCT scalar field) recipe.
Distinct rollups, aliases and ratios do not gain zero-fill approval. No additional
core or native VGI patch was needed; the engine retains six generic patches.
The deterministic native profile uses the actual producer worker and mock HTTP;
it does not qualify live credentials, HTTP/Iroh, or the full VGI port.

The broad model's earlier checkpoint follows; it has not been replaced by the
connected generated profile:

EC2 Linux ARM64, October 12, 2026, using the matching engine and native extensions.
Worker sources use revision `56d28ba8` plus the reporting/model
changes for this milestone. Coverage is all 21 typed `main` functions, 51 metrics
and 49 reports, plus all 780 pinned REST GET operations, raw GraphQL and local
endpoint discovery through 24 model sources. Raw payloads have response grain;
this is not 780 independently defined business metric populations.

| Check | Result |
| --- | --- |
| `reporting.test`, optimizer on / off | 385 assertions each; 152.309 / 150.962 seconds |
| `surface.test`, optimizer on / off | 111 assertions each; 75.736 / 71.325 seconds |
| `raw_api.test`, optimizer on / off | 41 assertions each; 28.975 / 29.036 seconds |
| Total native GitHub SQLLogicTest coverage | 537 assertions per optimizer mode; all 49 reports execute |
| Offline worker unit tests | 1,243 passed; 51 live cases deselected; Python-engine API SQL test excluded; 12.46 seconds |
| Model coverage/schema and generated-artifact tests | 31 passed; 2.00 seconds; generator `--check` and Ruff pass |
| Full Crossfield CTest regression | 206/206 passed; 49.28 seconds |
| Crossfield authoring/schema regression | 41/41 passed |

Those broad-model native runs validate the public model name `github`, including
`engineering.semantic.github(...)` and the exact model name in compiled metadata.
Stable model, package and report IDs are unchanged. SQL logs and mock HTTP traces
(`run.log` and `api.jsonl`) are collected under
`crossfield/logs/github-model-rename/on/` and `off/`; both complete three-suite runs
pass without changing numerical expectations. Earlier worker, schema and engine
regression evidence remains under `crossfield/logs/github-surface/`.
All 780 operation IDs and 24 source schemas have inventory/contract coverage;
runtime tests exercise representative raw operations, not 780 live endpoints.

The PR oracle is **4 merged, mean 9 hours, median 7, p90 17**.
The combined PR/CI oracle is **6 all-history merges, 3 runs, 0.5 success rate**;
independent facts cannot multiply each other. Discussions give **3 total, 2
answered, mean/median answer time 6 hours**. Project items give **4 total, 2 issues,
1 PR, 1 draft**, including an inaccessible item's identity. Missing/failed/malformed
sources reject and a subsequent healthy report succeeds.
