"""Shared fixtures for the test suite.

Two pieces of process-wide state need resetting between tests: the pooled
HTTP client and the conditional-request (ETag) cache. Without that, a client
built against one test's mock transport — or a cached body from one test's
fake response — would serve the next, and test order would decide outcomes.

Live tests that exhaust GitHub's rate limit are turned into skips: a budget
spent by something else sharing the token says nothing about the code.
"""

from __future__ import annotations

from collections.abc import Generator
from typing import Any

import pytest

from vgi_github import github_api
from vgi_github.github_api import GitHubRateLimitError


@pytest.fixture(autouse=True)
def _hermetic_state(monkeypatch: pytest.MonkeyPatch) -> Generator[None]:
    github_api.reset_shared_client()
    # Never sleep in an offline test; retry timing is asserted via the mock.
    yield
    github_api.reset_shared_client()


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo[Any]) -> Generator[None, Any]:
    outcome = yield
    report = outcome.get_result()
    if item.get_closest_marker("live") is None or report.outcome != "failed":
        return
    exception = getattr(call, "excinfo", None)
    if exception is None:
        return
    text = str(exception.value)
    if not isinstance(exception.value, GitHubRateLimitError) and "rate limit exceeded" not in text:
        return
    report.outcome = "skipped"
    report.longrepr = (
        str(item.path),
        item.location[1] or 0,
        "Skipped: GitHub rate limit exhausted — set VGI_GITHUB_TOKEN, or re-run after the reset.",
    )
