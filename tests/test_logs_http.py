"""Streamed Actions logs over the HTTP transport, against a local fake GitHub.

Over HTTP each reply of a multi-batch scan is its own request, and the resume
state travels in the stream's state token rather than staying in a process.
A log long enough to need several replies proves the externalized state is
sufficient: positions only, with the body re-read from the spool (or downloaded
again) on each resume.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).parent / "fixtures" / "actions_logs"
_PORT_LINE = re.compile(r"^PORT:(\d+)$")
LINES = 30_000
BIG_LOG = "".join(
    f"2026-07-21T12:00:{i // 1000 % 60:02d}.{i % 1000:03d}0000Z line {i}\n" for i in range(LINES)
)
BLOBS = {"/blob/big.log": BIG_LOG.encode(), "/blob/run.zip": (FIXTURES / "run_logs.zip").read_bytes()}
ROUTES = {
    "/api/v3/repos/o/r/actions/jobs/9/logs": "/blob/big.log",
    "/api/v3/repos/o/r/actions/runs/5/logs": "/blob/run.zip",
}


@pytest.fixture(scope="module")
def fake_github() -> Iterator[str]:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            if self.path in ROUTES:
                self.send_response(302)
                self.send_header("Location", f"http://localhost:{self.server.server_port}{ROUTES[self.path]}")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            body = BLOBS.get(self.path)
            self.send_response(200 if body is not None else 404)
            body = body if body is not None else b"{}"
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}/api/v3"
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)


@pytest.fixture(scope="module")
def http_worker(fake_github: str) -> Iterator[str]:
    env = {
        k: v
        for k, v in os.environ.items()
        if k not in ("VGI_GITHUB_TOKEN", "GITHUB_TOKEN", "GH_TOKEN", "VGI_GITHUB_ALLOW_TOKEN_SOURCE")
    }
    env["GITHUB_API_URL"] = fake_github
    proc = subprocess.Popen(
        [sys.executable, "serve.py", "--port", "0"],
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
    threading.Thread(target=proc.stdout.read, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        proc.terminate()
        proc.wait(timeout=10)


@pytest.fixture
def con(http_worker: str):
    haybarn = pytest.importorskip("haybarn")
    connection = haybarn.connect()
    try:
        connection.execute("LOAD vgi")
    except Exception as exc:
        connection.close()
        pytest.skip(f"Local VGI extension is not installed: {exc}")
    connection.execute(f"ATTACH 'github' (TYPE vgi, LOCATION '{http_worker}', auth 'off')")
    yield connection
    connection.close()


def test_long_job_log_resumes_across_http_replies(con) -> None:
    assert con.execute(
        "SELECT count(*), count(DISTINCT line_number), max(line_number), "
        "bool_and(text = 'line ' || (line_number - 1)), count(timestamp) "
        "FROM github.main.job_logs('o/r', 9)"
    ).fetchone() == (LINES, LINES, LINES, True, LINES)


def test_run_archive_over_http(con) -> None:
    assert con.execute(
        "SELECT job_name, step_number, count(*) FROM github.main.run_logs('o/r', 5) "
        "GROUP BY ALL ORDER BY job_name, step_number"
    ).fetchall() == [("build", 1, 4), ("build", 2, 5), ("lint", None, 5)]
