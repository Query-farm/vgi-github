"""Replay two complete public GitHub pages, preserving bodies and bounding requests."""

from __future__ import annotations

import hashlib
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit


class ReplaySource:
    """Hash-checked local HTTP replay with no external forwarding or fallback."""

    def __init__(self, directory: Path) -> None:
        manifest = json.loads((directory / "manifest.json").read_text())
        bodies = {}
        links = {}
        for entry in manifest["entries"]:
            body = (directory / entry["filename"]).read_bytes()
            if hashlib.sha256(body).hexdigest() != entry["sha256"]:
                raise ValueError(f"Recorded response checksum mismatch: {entry['filename']}")
            bodies[entry["page"]] = body
            links[entry["page"]] = entry["link"]
        self.requests: list[str] = []
        requests = self.requests

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format: str, *args: object) -> None:
                pass

            def do_GET(self) -> None:
                parsed = urlsplit(self.path)
                query = parse_qs(parsed.query)
                requests.append(self.path)
                page = query.pop("page", ["1"])
                if (
                    parsed.path not in {"/repos/duckdb/duckdb/pulls", "/repositories/138754790/pulls"}
                    or query
                    != {"state": ["all"], "sort": ["created"], "direction": ["desc"], "per_page": ["100"]}
                    or page not in [["1"], ["2"]]
                ):
                    self.send_error(400, "Request outside recorded two-page coverage")
                    return
                number = int(page[0])
                body = bodies[number]
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                if links[number]:
                    self.send_header(
                        "Link",
                        links[number].replace(
                            "https://api.github.com", f"http://127.0.0.1:{self.server.server_port}"
                        ),
                    )
                self.end_headers()
                self.wfile.write(body)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.server.server_port}"

    def close(self) -> None:
        """Stop only this replay server."""
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
