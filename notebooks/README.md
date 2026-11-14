# GitHub notebooks

[01 · A recent-PR cap changes the population behind merge time](01_recent_caps_change_merge_time_populations.ipynb) separates merged, closed-without-merge and open pull requests in a bounded public sample. The experiment expands a local recent subset from 100 to 200 while retaining the same source.

## Run

Install [uv](https://docs.astral.sh/uv/) and Git. Python 3.13–3.14 is required; uv can install it. Internet access is needed for initial dependencies and worker downloads. No worker checkout or GitHub credentials are needed.

```sh
cd notebooks
uv sync --locked
uv run --locked python execute.py --timeout 300
```

Haybarn 2.0.0rc11 runs the SQL notebook. Its literal ATTACH launches `uvx --from git+https://github.com/Query-farm/vgi-github@v0.3.0 ... vgi-github`. Tag v0.3.0 resolves to `d80835497330d08ccd6c3261d85061227ff85968`. The command pins vgi-python 0.51.0, vgi-rpc 0.53.1, httpx 0.28.1, pyarrow 25.0.1 and graphql-core 3.2.6. This is a tested Git package launch, not a claim that the package is on PyPI. uv caches the Git checkout/environment. To upgrade, review the upstream tag and rerun defaults, experiment and live validation deliberately.

Optional editor kernel:

```sh
uv run --locked python -m ipykernel install --user --name vgi-github-notebooks --display-name "Python (vgi-github notebooks)"
```

Use this directory as working directory, then Restart Kernel → Run All. The runner registers a temporary kernel and replaces the saved notebook only after successful execution.

## Separate experiment and live mode

```sh
uv run --locked python execute.py --parameters '{"RECENT_N":200}' --output-dir artifacts/recent-200
uv run --locked python execute.py --parameters '{"DATA_MODE":"live"}' --output-dir artifacts/live
```

Overrides require a separate destination; companions, branding and docs accompany the copy. Restore `RECENT_N=100`, `DATA_MODE="replay"` for defaults. Artifacts, validation copies and environments are ignored.

## Recorded public responses

`fixtures/manifest.json` records exact request URLs, UTC request start/completion timestamps, HTTP status, original Link headers, body sizes and SHA-256 hashes. The two `pulls-page-*.json` files are complete unmodified GitHub responses captured anonymously on 2026-11-14, for the 200 newest `duckdb/duckdb` PRs by creation time (`state=all`, `sort=created`, `direction=desc`, 100/page). They include public descriptions and author metadata, though the analysis projects only identifiers, state and timestamps. GitHub data belongs to GitHub and its users and is subject to [GitHub's terms](https://docs.github.com/site-policy/github-terms/github-terms-of-service); see the repository NOTICE. The recording is real public data, not synthetic.

`replay_source.py` verifies every hash, serves the exact bodies on an ephemeral loopback port, and replaces only `https://api.github.com` in recorded Link headers with its local origin. It accepts only the documented repository-name/ID paths, exact filter/page-size parameters and pages 1–2. A third page fails. The unchanged worker follows pagination and flattens fields. There is no remote fallback. API pages were requested separately and may reflect intervening changes; the recording is not an atomic snapshot.

Live mode explicitly targets `https://api.github.com`, still with `auth 'off'`, and retrieves at most 200 PRs. A new kernel avoids previous in-process caches. HTTP errors and rate limits fail the run. The observation clock is retrieval completion; replay uses recorded acquisition completion. GitHub's returned timestamps are UTC, and open ages can differ slightly between page acquisition and that clock. Do not use this as an exact event-time snapshot.

## Analytical limits

The API cap selects arrivals by creation time, not every PR merged in a date interval. The local `RECENT_N` cap holds the full source constant; it models selection sensitivity without extra API calls. UTC creation boundaries are observed inclusive minimum/maximum timestamps, not guaranteed complete calendar windows. Equal creation times use descending PR number as a deterministic local tie break.

Merged means non-NULL `merged_at`; closed without merging is a separate terminal event. Open ages remain unfinished and are never filled with zero. Empirical distributions use an explicit denominator for each outcome; the median among observed merges does not estimate a lifetime merge distribution. No repository-wide completeness, causal process change or individual performance inference follows from this sample. See [GitHub's pull-list documentation](https://docs.github.com/en/rest/pulls/pulls#list-pull-requests) for filters, order and page size.

## SQL credential isolation

The notebook creates Haybarn with a fresh temporary `secret_directory` and
`allow_persistent_secrets=False` before attaching workers. It fully drains and
checks an empty secret inventory. This example needs no saved SQL credential;
its explicit public-data or local-fixture configuration remains in effect.
Cleanup removes the temporary directory after closing the connection.
Existing user SQL secrets are neither read, modified nor deleted.
