"""Mock-transport plumbing shared by the offline tests."""

from __future__ import annotations

from collections.abc import Callable

import httpx

from vgi_github import github_api


def install(monkeypatch, handler: Callable[[httpx.Request], httpx.Response]) -> list[httpx.Request]:
    """Route every request through ``handler`` and record them; disable sleeping."""
    seen: list[httpx.Request] = []

    def recording(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    client = httpx.Client(
        transport=httpx.MockTransport(recording),
        headers={"User-Agent": github_api.USER_AGENT, "X-GitHub-Api-Version": github_api.API_VERSION},
        follow_redirects=True,
    )
    monkeypatch.setattr(github_api, "shared_client", lambda: client)
    monkeypatch.setattr(github_api.time, "sleep", lambda _s: None)
    return seen


def haybarn_connection():
    """A Haybarn connection with the vgi extension installed and loaded.

    Haybarn does not have vgi until asked: on a fresh machine ``ATTACH ...
    (TYPE vgi, ...)`` fails with "Extension ... not found". Installing it here
    makes the live tiers self-provisioning on a clean CI runner, where they
    used to skip every test under a green check.
    """
    import pytest

    haybarn = pytest.importorskip("haybarn")
    connection = haybarn.connect()
    connection.execute("INSTALL vgi FROM community; LOAD vgi;")
    return connection
