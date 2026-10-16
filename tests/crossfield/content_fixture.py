"""Independent content bytes and statuses; download internals are never inferred."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

import actions_fixture
import code_scanning_fixture
import connected_fixture as baseline
import httpx
import releases_fixture

from vgi_github.generated_worker import main

BINARY = b"PK\x03\x04\x00\xff"
SARIF = b'{"version":"2.1.0","runs":[]}'


def respond(request):
    path = request.url.path
    accept = request.headers.get("accept", "")
    headers = {"Cache-Control": "no-store", "X-RateLimit-Remaining": "5000"}

    def response(body=b"", status=200, media="application/octet-stream", **extra):
        if os.environ.get("CROSSFIELD_GITHUB_API_LOG"):
            with Path(os.environ["CROSSFIELD_GITHUB_API_LOG"]).open("a") as log:
                log.write(json.dumps({"path": path, "accept": accept}) + "\n")
        return httpx.Response(
            status, content=body, headers={**headers, "Content-Type": media, **extra}, request=request
        )

    def redirect():
        return response(status=302, Location="https://content-fixture.invalid" + path)

    if request.url.host == "content-fixture.invalid":
        assert "authorization" not in request.headers
        if match := re.search(r"/jobs/(\d+)(?:/steps/(\d+))?/logs$", path):
            job, step = match.groups()
            text = f"job {job}\n" if step is None else f"job {job} step {step}\n"
            return response(text.encode(), media="text/plain; charset=utf-8")
        if "/releases/assets/" in path:
            return response(b"" if path.endswith("/112") else b"\x00\xffrelease")
        return response(BINARY, media="application/zip")
    if request.method != "GET":
        return None
    if path.startswith("/repos/example/alpha/actions/"):
        if re.search(r"/(?:runs/\d+(?:/attempts/\d+)?|jobs/\d+(?:/steps/\d+)?)/logs$", path):
            return redirect()
        if re.search(r"/artifacts/\d+/zip$", path):
            return response(b"Artifact expired", 410) if "/3002/" in path else redirect()
    if (
        path.startswith("/repos/release-fixture/")
        and "/releases/assets/" in path
        and accept == "application/octet-stream"
    ):
        return redirect()
    if path.startswith("/repos/scan-fixture/"):
        if "/code-scanning/analyses/" in path and accept == "application/sarif+json":
            return response(SARIF, media="application/sarif+json")
        if "/code-scanning/codeql/databases/" in path and accept == "application/zip":
            return redirect()
    if path.startswith("/repos/example/alpha/"):
        if "/dependency-graph/sbom/fetch-report/" in path:
            return response(status=202, media="") if path.endswith("/pending-report") else redirect()
        if "/zipball/" in path or "/tarball/" in path:
            return redirect()
    return None


def respond_all(request):
    for handler in (
        respond,
        actions_fixture.respond,
        releases_fixture.respond,
        code_scanning_fixture.respond,
    ):
        value = handler(request)
        if value is not None:
            return value
    return baseline.respond(request)


baseline.api.open_client = lambda: httpx.Client(
    transport=httpx.MockTransport(respond_all), follow_redirects=True
)
if __name__ == "__main__":
    main()
