"""Real SQL and subprocess transport, with every GitHub response served locally."""

from __future__ import annotations

import json
import shlex
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from vgi_github.rest import OPERATIONS

LOG_FIXTURES = Path(__file__).parent / "fixtures" / "actions_logs"
#: Enough lines to need several streamed batches, so resume() runs in a real worker.
BIG_LOG_LINES = 20_000
LOG_ROUTES = {
    "jobs/7/logs": "/blob/job.log",
    "jobs/9/logs": "/blob/big.log",
    "runs/5/logs": "/blob/run.zip",
    "runs/5/attempts/1/logs": "/blob/run.zip",
}
LOG_BLOBS = {
    "/blob/job.log": (LOG_FIXTURES / "job.log").read_bytes(),
    "/blob/run.zip": (LOG_FIXTURES / "run_logs.zip").read_bytes(),
    "/blob/big.log": "".join(
        f"2026-07-21T12:{i // 6000 % 60:02d}:{i // 100 % 60:02d}.{i % 100:02d}00000Z line {i}\n"
        for i in range(BIG_LOG_LINES)
    ).encode(),
}


@pytest.fixture
def sql_api(monkeypatch):
    haybarn = pytest.importorskip("haybarn")
    connection = haybarn.connect()
    try:
        connection.execute("LOAD vgi")
    except Exception as exc:
        connection.close()
        pytest.skip(f"Local VGI extension is not installed: {exc}")
    seen = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def respond(self, data, media="application/json"):
            self.send_response(200)
            self.send_header("Content-Type", media)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def redirect(self, target):
            # A different origin (localhost vs 127.0.0.1), as GitHub's signed blob URLs are.
            self.send_response(302)
            self.send_header("Location", f"http://localhost:{self.server.server_port}{target}")
            self.send_header("Content-Length", "0")
            self.end_headers()

        def not_found(self):
            body = b'{"message":"Not Found"}'
            self.send_response(404)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            seen.append(("GET", self.path))
            actions = "/api/v3/repos/o/r/actions/"
            if self.path.startswith(actions) and self.path.endswith("/logs"):
                target = LOG_ROUTES.get(self.path[len(actions) :])
                self.redirect(target) if target else self.not_found()
            elif self.path.startswith("/blob/"):
                self.respond(LOG_BLOBS[self.path], "application/octet-stream")
            elif "/projectsV2" in self.path:
                if "/items" in self.path:
                    data = [{"id": 11, "content_type": "Issue", "content": {"title": "Task", "number": 3}}]
                elif "/fields" in self.path:
                    data = [{"id": 12, "name": "Status", "data_type": "single_select"}]
                else:
                    data = [{"id": 1, "number": 7, "title": "Roadmap", "owner": {"login": "o"}}]
                self.respond(json.dumps(data).encode())
            elif "application/vnd.github.diff" in self.headers.get("Accept", ""):
                self.respond(b"diff --git a/a b/a\n", "text/plain")
            else:
                self.respond(json.dumps({"path": self.path, "nested": {"retained": True}}).encode())

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            seen.append(("POST", self.path))
            # Two one-row pages exercise automatic cursor pagination in a real
            # worker subprocess, including chained correlated LATERAL joins.
            v = body["variables"]
            page = {"pageInfo": {"hasNextPage": False, "endCursor": None}}
            if "query Discussions(" in body["query"]:
                number = 2 if v["after"] else 1
                page["nodes"] = [
                    {
                        "number": number,
                        "title": f"Question {number}",
                        "isAnswered": False,
                        "repository": {"nameWithOwner": f"{v['owner']}/{v['name']}"},
                    }
                ]
                if not v["after"]:
                    page["pageInfo"] = {"hasNextPage": True, "endCursor": "page2"}
                data = {"repository": {"discussions": page}}
            elif "query DiscussionComments(" in body["query"]:
                page["nodes"] = [
                    {
                        "id": f"C_{v['number']}",
                        "body": "Comment",
                        "author": {"login": "alice"},
                        "discussion": {"number": v["number"], "repository": {"nameWithOwner": "o/r"}},
                    }
                ]
                data = {"repository": {"discussion": {"comments": page}}}
            elif "query DiscussionReplies(" in body["query"]:
                page["nodes"] = [{"id": f"R_{v['id']}", "body": "Reply", "replyTo": {"id": v["id"]}}]
                data = {"node": {"replies": page}}
            else:
                data = {"echo": v}
            self.respond(json.dumps({"data": data}).encode())

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setenv("GITHUB_API_URL", f"http://127.0.0.1:{server.server_port}/api/v3")
    monkeypatch.delenv("VGI_GITHUB_TOKEN", raising=False)
    script = Path(__file__).resolve().parents[1] / "github_worker.py"
    # VGI pools subprocesses by command. Include this server's address in that
    # key so another test cannot reuse a worker pointing at a stopped server.
    command = shlex.join(
        ["env", f"GITHUB_API_URL=http://127.0.0.1:{server.server_port}/api/v3", sys.executable, str(script)]
    ).replace("'", "''")
    try:
        connection.execute(f"ATTACH 'github' (TYPE vgi, LOCATION '{command}', auth 'off')")
        yield connection, seen
    finally:
        connection.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_generated_catalog_and_queries_through_sql(sql_api):
    con, seen = sql_api
    assert con.execute("SELECT count(*) FROM github.api.endpoints").fetchone() == (len(OPERATIONS),)
    assert not seen
    result = con.execute(
        "SELECT t.n, p.data::JSON ->> 'path' FROM (VALUES (1), (2)) t(n), "
        "LATERAL github.rest.pulls_get('o', 'r', t.n) p ORDER BY t.n"
    ).fetchall()
    assert result == [(1, "/api/v3/repos/o/r/pulls/1"), (2, "/api/v3/repos/o/r/pulls/2")]
    assert con.execute(
        "SELECT data::JSON ->> 'path' FROM github.rest.repos_list_for_authenticated_user("
        'query => \'{"visibility":"private"}\')'
    ).fetchone() == ("/api/v3/user/repos?visibility=private",)
    assert con.execute(
        "SELECT body FROM github.rest.pulls_get('o', 'r', 1, accept => 'application/vnd.github.diff')"
    ).fetchone() == (b"diff --git a/a b/a\n",)
    assert con.execute(
        "SELECT data::JSON ->> 'path' FROM github.api.rest('pulls/list-reviews', "
        '\'{"owner":"o","repo":"r","pull_number":7}\')'
    ).fetchone() == ("/api/v3/repos/o/r/pulls/7/reviews",)
    assert all(method == "GET" for method, _ in seen)


def test_graphql_query_and_mutation_guard_through_sql(sql_api):
    con, seen = sql_api
    assert con.execute(
        "SELECT data::JSON -> 'data' -> 'echo' ->> 'value' "
        "FROM github.api.graphql('query Read($value:String) { viewer { login } }', '{\"value\":\"ok\"}')"
    ).fetchone() == ("ok",)
    assert seen == [("POST", "/api/graphql")]
    with pytest.raises(Exception, match="queries only"):
        con.execute(
            "SELECT * FROM github.api.graphql('mutation { deleteIssue { clientMutationId } }', '{}')"
        ).fetchall()
    assert len(seen) == 1


def test_typed_discussions_paginate_and_chain_under_lateral(sql_api):
    con, seen = sql_api
    rows = con.execute(
        "SELECT d.number, d.title, d.is_answered, c.node_id, r.reply_to_id, r.body "
        "FROM github.discussions('o/r', answered => false, max_rows => 0) d, "
        "LATERAL github.discussion_comments(d.repo, d.number, max_rows => 1) c, "
        "LATERAL github.discussion_replies(c.node_id, max_rows => 1) r ORDER BY d.number"
    ).fetchall()
    assert rows == [
        (1, "Question 1", False, "C_1", "C_1", "Reply"),
        (2, "Question 2", False, "C_2", "C_2", "Reply"),
    ]
    assert len(seen) == 6 and all(item == ("POST", "/api/graphql") for item in seen)


def test_typed_projects_and_field_discovery_through_sql(sql_api):
    con, seen = sql_api
    assert con.execute(
        "SELECT p.title, i.content_type, i.title, i.project_number FROM github.projects('o') p, "
        "LATERAL github.project_items(p.owner, p.number, fields => '12', query => 'is:open') i"
    ).fetchall() == [("Roadmap", "Issue", "Task", 7)]
    assert con.execute(
        "SELECT id, name, data_type FROM github.project_fields('o', 7, owner_type => 'user')"
    ).fetchall() == [(12, "Status", "single_select")]
    assert any("/users/o/projectsV2/7/fields" in path for _, path in seen)
    assert any("fields=12" in path for _, path in seen)
    assert all(method == "GET" for method, _ in seen)


def test_job_logs_decode_through_sql(sql_api):
    con, seen = sql_api
    assert con.execute(
        "SELECT line_number, command_properties['file'], command_properties['line'], command_message "
        "FROM github.main.job_logs('o/r', 7) WHERE command = 'error' ORDER BY line_number"
    ).fetchall() == [
        (10, "src/app.py", "42", "Expected int, got str\nsecond line"),
        (12, None, None, "Process completed with exit code 1."),
    ]
    assert con.execute(
        "SELECT typeof(timestamp), text, group_path FROM github.main.job_logs('o/r', 7) WHERE line_number = 6"
    ).fetchone() == ("TIMESTAMP WITH TIME ZONE", "make test", ["Run make test"])
    assert con.execute(
        "SELECT count(*), count(timestamp) FROM github.main.job_logs('o/r', 7)"
    ).fetchone() == (14, 13)
    # A missing log and a NULL key are empty, not errors, under LATERAL.
    assert con.execute(
        "SELECT t.id, count(l.line_number) FROM (VALUES (7), (404), (NULL)) t(id) "
        "LEFT JOIN LATERAL github.main.job_logs('o/r', t.id) l ON true GROUP BY t.id ORDER BY t.id"
    ).fetchall() == [(7, 14), (404, 0), (None, 0)]
    assert any(path == "/blob/job.log" for _, path in seen)


def test_run_logs_decode_archive_through_sql(sql_api):
    con, _ = sql_api
    assert con.execute(
        "SELECT job_name, step_number, step_name, count(*) FROM github.main.run_logs('o/r', 5) "
        "GROUP BY ALL ORDER BY job_name, step_number"
    ).fetchall() == [("build", 1, "Set up job", 4), ("build", 2, "Run tests", 5), ("lint", None, None, 5)]
    assert con.execute(
        "SELECT l.attempt, l.job_name, l.command, l.command_properties['file'], l.command_message "
        "FROM (VALUES (5)) r(id), LATERAL github.main.run_logs('o/r', r.id, attempt => 1) l "
        "WHERE l.command IN ('error', 'warning') ORDER BY l.job_name"
    ).fetchall() == [
        (1, "build", "error", None, "Process completed with exit code 1."),
        (1, "lint", "warning", "src/app.py", "Unused import os"),
    ]


def test_large_logs_stream_in_resumed_batches(sql_api):
    con, _ = sql_api
    assert con.execute(
        "SELECT count(*), count(DISTINCT line_number), max(line_number), "
        "bool_and(text = 'line ' || (line_number - 1)) FROM github.main.job_logs('o/r', 9)"
    ).fetchone() == (BIG_LOG_LINES, BIG_LOG_LINES, BIG_LOG_LINES, True)
    assert con.execute("SELECT count(*) FROM (FROM github.main.job_logs('o/r', 9) LIMIT 5)").fetchone() == (
        5,
    )


def test_log_scalars_through_sql(sql_api):
    con, _ = sql_api
    line = "2026-07-21T12:00:00.1234567Z \x1b[31m::error file=a.py,line=3::boom\x1b[0m"
    assert con.execute(
        "SELECT github.main.log_ts($1) = TIMESTAMPTZ '2026-07-21 12:00:00.123456+00', "
        "github.main.log_text($1, true), github.main.log_text($1, false) = $2, "
        "github.main.workflow_command($1).command, github.main.workflow_command($1).properties['line'], "
        "github.main.workflow_command('plain') IS NULL",
        [line, line.split(" ", 1)[1]],
    ).fetchone() == (True, "::error file=a.py,line=3::boom", True, "error", "3", True)


def test_workflow_runs_created_cursor_from_a_subquery(sql_api):
    con, seen = sql_api
    con.execute("CREATE TEMP TABLE runs AS SELECT TIMESTAMPTZ '2026-07-01 12:30:00+00' AS created_at")
    con.execute(
        "SET VARIABLE since = "
        "(SELECT strftime(max(created_at) AT TIME ZONE 'UTC', '>=%Y-%m-%dT%H:%M:%SZ') FROM runs)"
    )
    con.execute(
        "SELECT * FROM (VALUES ('o/r')) t(repo), LATERAL github.main.workflow_runs(t.repo, max_rows => 0, "
        "created => getvariable('since'))"
    ).fetchall()
    assert any("created=%3E%3D2026-07-01T12%3A30%3A00Z" in path for _, path in seen), seen
