"""A fake GitHub REST + GraphQL API for the SQL suite (test/sql/mock_api.test).

    python test/mock_api/server.py [port]   # default 0: any free port

Prints ``PORT:<n>`` once listening. ci/run-integration.sh starts it and points
the worker at it with ``GITHUB_API_URL=http://127.0.0.1:<n>/api/v3``. The
responses mirror the in-process fixture in tests/test_api_sql.py: REST GETs
echo their path, a diff ``Accept`` returns a diff, and GraphQL serves two
one-row pages of discussions plus one comment and one reply each.
"""

from __future__ import annotations

import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class Handler(BaseHTTPRequestHandler):
    """REST and GraphQL responses for the SQL suite."""

    def log_message(self, *args: object) -> None:
        pass

    def respond(self, data: bytes, media: str = "application/json") -> None:
        self.send_response(200)
        self.send_header("Content-Type", media)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        if "application/vnd.github.diff" in self.headers.get("Accept", ""):
            self.respond(b"diff --git a/a b/a\n", "text/plain")
        else:
            self.respond(json.dumps({"path": self.path, "nested": {"retained": True}}).encode())

    def do_POST(self) -> None:
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        v = body["variables"]
        page: dict[str, object] = {"pageInfo": {"hasNextPage": False, "endCursor": None}}
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
            data: dict[str, object] = {"repository": {"discussions": page}}
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


if __name__ == "__main__":
    server = ThreadingHTTPServer(("127.0.0.1", int(sys.argv[1]) if len(sys.argv) > 1 else 0), Handler)
    print(f"PORT:{server.server_address[1]}", flush=True)
    server.serve_forever()
