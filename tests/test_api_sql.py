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

        def do_GET(self):
            seen.append(("GET", self.path))
            if "/projectsV2" in self.path:
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
