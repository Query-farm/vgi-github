"""The worker served over HTTP, with several clients sharing one server.

stdio gives every DuckDB connection a worker of its own; HTTP does not. One
server process — one connection pool, one ETag cache — answers every client,
so the property that matters here is isolation: a client's token must
authorize only that client's queries, and nothing one client fetched may be
replayed to another.

The server is started *without* VGI_GITHUB_TOKEN, deliberately: any
authentication observed has to have come from the client's own secret, sent
over the wire.

Marked `live`: it talks to GitHub. The authenticated half needs
VGI_GITHUB_TOKEN in the *test* environment to create a client secret from.
"""

from __future__ import annotations

import os
import re
import subprocess
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from tests.helpers import haybarn_connection

pytestmark = pytest.mark.live

ROOT = Path(__file__).resolve().parent.parent

#: The worker prints this once it is listening; `--port 0` picks a free port.
_PORT_LINE = re.compile(r"^PORT:(\d+)$")


@pytest.fixture(scope="module")
def server() -> Iterator[str]:
    env = {
        k: v
        for k, v in os.environ.items()
        if k not in ("VGI_GITHUB_TOKEN", "GITHUB_TOKEN", "GH_TOKEN", "VGI_GITHUB_ALLOW_TOKEN_SOURCE")
    }
    proc = subprocess.Popen(
        ["uv", "run", "serve.py", "--port", "0"],
        cwd=ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    port = None
    assert proc.stdout is not None
    for line in proc.stdout:
        if match := _PORT_LINE.match(line.strip()):
            port = match.group(1)
            break
    if port is None:
        proc.kill()
        pytest.fail("the HTTP worker exited without reporting a port")
    # Keep draining output so the server never blocks on a full pipe.
    threading.Thread(target=proc.stdout.read, daemon=True).start()
    yield f"http://127.0.0.1:{port}"
    proc.terminate()
    proc.wait(timeout=10)


def _attach(
    url: str, *, auth: str | None = None, token: str | None = None, token_source: str | None = None
) -> Any:
    con = haybarn_connection()
    option = f", auth '{auth}'" if auth else ""
    option += f", token_source '{token_source}'" if token_source else ""
    con.execute(f"ATTACH 'github' (TYPE vgi, LOCATION '{url}'{option})")
    if token:
        con.execute(f"CREATE SECRET client_token (TYPE github, token '{token}')")
    return con


def _core(con: Any) -> tuple[int, bool]:
    return con.execute(
        "SELECT request_limit, authenticated FROM github.rate_limit WHERE resource = 'core'"
    ).fetchone()


@pytest.fixture(scope="module")
def token() -> str:
    value = os.environ.get("VGI_GITHUB_TOKEN")
    if not value:
        pytest.skip("needs VGI_GITHUB_TOKEN to create a client secret from")
    return value


class TestOverHttp:
    def test_anonymous_client(self, server: str) -> None:
        con = _attach(server)
        assert _core(con) == (60, False)
        assert con.execute("SELECT full_name FROM github.repo('duckdb/duckdb')").fetchall() == [
            ("duckdb/duckdb",)
        ]

    def test_client_secret_reaches_the_server(self, server: str, token: str) -> None:
        limit, authenticated = _core(_attach(server, token=token))
        assert authenticated and limit > 60

    def test_lateral_over_http(self, server: str, token: str) -> None:
        con = _attach(server, token=token)
        (mismatches, rows) = con.execute(
            "SELECT count(*) FILTER (WHERE t.n <> i.repo), count(*) FROM "
            "(VALUES ('duckdb/duckdb'), ('duckdb/duckdb-wasm')) t(n), "
            "LATERAL github.issues(t.n, max_rows => 5) i"
        ).fetchone()
        assert mismatches == 0 and rows == 10

    def test_search_streams_over_http(self, server: str, token: str) -> None:
        con = _attach(server, token=token)
        rows = con.execute("SELECT * FROM github.search_repositories('duckdb') LIMIT 5").fetchall()
        assert len(rows) == 5

    def test_token_source_is_refused_over_http(self, server: str) -> None:
        """By default a shared server never runs gh, or reads its environment, for a client."""
        with pytest.raises(Exception, match="not enabled on this worker"):
            _attach(server, token_source="gh")

    def test_required_mode_over_http(self, server: str) -> None:
        con = _attach(server, auth="required")
        with pytest.raises(Exception, match="required"):
            con.execute("SELECT * FROM github.repo('duckdb/duckdb')").fetchall()


class TestClientIsolation:
    """One server, two clients: a token must never authorize the other client."""

    def test_a_token_does_not_leak_to_an_anonymous_client(self, server: str, token: str) -> None:
        authed, anon = _attach(server, token=token), _attach(server)
        # Warm every server-side cache with the token client first.
        for _ in range(2):
            assert _core(authed)[1] is True
            authed.execute("SELECT * FROM github.repo('duckdb/duckdb')").fetchall()
        for _ in range(2):
            assert _core(anon) == (60, False)

    def test_interleaved_clients_keep_their_own_identity(self, server: str, token: str) -> None:
        authed, anon = _attach(server, token=token), _attach(server)
        seen: dict[str, set[bool]] = {"authed": set(), "anon": set()}

        def hammer(name: str, con: Any) -> None:
            for _ in range(5):
                seen[name].add(_core(con)[1])

        threads = [
            threading.Thread(target=hammer, args=pair) for pair in (("authed", authed), ("anon", anon))
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        assert seen == {"authed": {True}, "anon": {False}}

    def test_a_private_repository_stays_private(self, server: str, token: str) -> None:
        """Set VGI_GITHUB_PRIVATE_REPO to a repository the token can read and others cannot."""
        private = os.environ.get("VGI_GITHUB_PRIVATE_REPO")
        if not private:
            pytest.skip("set VGI_GITHUB_PRIVATE_REPO to run the private-repository check")
        authed, anon = _attach(server, token=token), _attach(server)
        sql = f"SELECT count(*) FROM github.repo('{private}')"
        assert authed.execute(sql).fetchone() == (1,)
        assert anon.execute(sql).fetchone() == (0,)
