# Crossfield integration notes

The [model guide](../models/README.md) owns user SQL and business definitions.
[build_model.py](../models/build_model.py) assembles the reviewed model and named
reports; [source_inventory.json](../models/source_inventory.json) records all
15 native signatures and 241 source columns. Generated JSON is checked in.
This replaces the earlier PR-only proposal.

## Runtime contract

- Use matching patched DuckDB `6b6099a3e9787f1b32c59fab61fcdd1d3bc835cd`,
  Crossfield and native VGI. Crossfield's `patches/duckdb/series` is authoritative;
  its fifth patch fixes correlated table in-out calls with named scalar options.
- Attach the worker with `reporting true, operation_timeout_seconds 120`.
  Crossfield checks immutable reporting, deadline and API-origin tags. The model
  pins complete keyed listings (`max_rows => 0`) and no result-cache reuse.
- Use a POSIX subprocess. Native VGI observes interruption, enforces finite
  reads and tears down failed workers; the worker bounds requests/retries and
  validation. HTTP transport is not qualified by these tests.
- The model-owned `semantic_query` contract maps named `repository`, `owner` and
  `issue_number` inputs to approved providers. The callable semantic catalog entry
  retains the caller's metric selection, dimensions and filters. Only inputs and
  sources needed by that selection are retained; unused supplied inputs reject.
  `crossfield_parameters()` exposes types and source/metric dependencies. Named
  reports remain useful for fixed presentations and detail. Search remains capped
  discovery; neither search nor rate-limit data has approved aggregate metrics.
- UTC is mandatory. DATE parameters define half-open cohorts. Empty or reversed
  intervals yield empty cohorts under ordinary SQL semantics. NULL/invalid typed
  arguments reject. Required source identities and metric inputs validate before
  output projection. Live errors may follow already streamed rows.

Metric populations, units, non-additivity and source identity remain model-owned.
All provider calls execute through native DuckDB. There is no Python DuckDB
runner, Crossfield result buffer or bespoke call scheduler.

## Matching native VGI build

The isolated adapter is reproducible from the upstream VGI checkout plus the
two checked-in patches; retain VGI's license and notices. The first patch supplies
the earlier isolated DuckDB 2 profile. The second adds its scalar adapter and
current engine/signature compatibility. This is a qualified invocation profile,
not a port of every VGI feature. Build on EC2:

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
  -DGIT_COMMIT_HASH=6b6099a3e9787f1b32c59fab61fcdd1d3bc835cd \
  -DDUCKDB_EXPLICIT_VERSION=v2.0.0-dev0 -DArrow_DIR=/path/to/arrow/share/arrow
cmake --build /path/to/build-vgi --target vgi_loadable_extension -j 20
```

`patched-duckdb` must have Crossfield's complete five-patch series applied.
Supply the installed Arrow CMake package for the target platform. The tested EC2
installation is `vgi/build/release/vcpkg_installed/arm64-linux/share/arrow`.
The output is `build-vgi/extension/vgi/vgi.duckdb_extension`. Native SQL fixtures
in the adapter's `test/duckdb2/` separately exercise all 15 worker signatures.

## Standard SQLLogicTest execution

Install the worker's locked dependencies on the build host. Set these paths for
the matching build and checkout (absolute paths are required):

```sh
export GITHUB_PROJECT=/path/to/vgi-github
export DUCKDB_BUILD=/path/to/crossfield/build
export VGI_EXTENSION=/path/to/build-vgi-scalar/extension/vgi/vgi.duckdb_extension
export CROSSFIELD_GITHUB_PACKAGE="$GITHUB_PROJECT/models/github-reporting.package.json"
export CROSSFIELD_GITHUB_WORKER="$GITHUB_PROJECT/.venv/bin/python $GITHUB_PROJECT/tests/crossfield/worker_fixture.py"
export SLURM_CPUS_ON_NODE=4
mkdir -p /tmp/github-slt-on
cd /tmp/github-slt-on
export CROSSFIELD_GITHUB_API_LOG="$PWD/requests.jsonl"
printf '%s\n' "$GITHUB_PROJECT/tests/crossfield/reporting.test" > tests.list
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
access errors, late failures and recovery.

Provider unit tests run separately on EC2:

```sh
uv run pytest -q --ignore=tests/test_end_to_end.py --ignore=tests/test_live.py
```

Crossfield's normal CTest suite supplies the broader semantic and lifecycle
regression. Its optional schema checker validates the package without executing
SQL. These deterministic tests do not claim a live github.com integration run,
HTTP qualification, a historical snapshot or an all-platform release.

## Validation

The previous EC2 Linux ARM64 baseline, October 11, 2026, used the matching engine
and native extensions. The new callable semantic entry adds cases to the native
suite; its validation results will replace the baseline once the rebuilt
extension passes them:

| Check | Result |
| --- | --- |
| Full native GitHub SQLLogicTest, optimizer on | 294 assertions; all 32 reports and 15 functions; 27.944 seconds |
| Same suite, optimizer off | 294 assertions; 29.273 seconds |
| Provider tests above | 277 passed; 9 live cases deselected |
| Package schema and document closure | Passed |
| Full Crossfield CTest regression | 204/204 passed; 170 SQLLogicTest runs, 33 native/CLI cases and one core suite; 47.72 seconds |
| Crossfield authoring/schema regression | 41/41 passed |
| Focused native producer reports | Both optimizer modes; distinct prepared arguments, no execution during metadata binding, type/NULL/domain rejection |
| Generic DuckDB table-function regression | 9 cases / 105 assertions, including 26 correlated keyword assertions |
| DuckDB lifecycle regression | 18 cases / 5,223 assertions |

Evidence is collected under
`crossfield/logs/github-semantic-model/`; per-mode HTTP traces come from the
mock transport. The PR oracle is **4 merged, mean 9 hours, median 7, p90 17**.
The combined PR/CI oracle is **6 all-history merges, 3 runs, 0.5 success rate**;
independent facts cannot multiply each other. Missing/failed/malformed sources
reject and a subsequent healthy report succeeds.
