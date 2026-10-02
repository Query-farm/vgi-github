"""The HTTP chokepoint: retries, rate limits, paging, conditional requests."""

from __future__ import annotations

import time

import httpx
import pytest

from tests.helpers import install
from vgi_github import auth
from vgi_github import github_api as api

BASE = "https://api.github.com"


def _json(payload, status: int = 200, **headers: str) -> httpx.Response:
    return httpx.Response(status, json=payload, headers=headers)


class TestRequestShape:
    def test_fixed_headers_and_bearer_token(self, monkeypatch) -> None:
        seen = install(monkeypatch, lambda r: _json({}))
        api._get("/rate_limit", credentials=auth.load("ghp_abc"))
        request = seen[0]
        assert request.headers["Authorization"] == "Bearer ghp_abc"
        assert request.headers["Accept"] == api.ACCEPT_JSON
        assert request.headers["X-GitHub-Api-Version"] == api.API_VERSION
        assert request.headers["User-Agent"].startswith("vgi-github/")

    def test_anonymous_sends_no_authorization(self, monkeypatch) -> None:
        seen = install(monkeypatch, lambda r: _json({}))
        api._get("/rate_limit")
        assert "Authorization" not in seen[0].headers

    def test_none_params_dropped_and_bools_lowercased(self, monkeypatch) -> None:
        seen = install(monkeypatch, lambda r: _json([]))
        api._get("/x", {"a": None, "b": True, "c": "v"})
        assert dict(seen[0].url.params) == {"b": "true", "c": "v"}

    def test_base_url_override(self, monkeypatch) -> None:
        monkeypatch.setenv("GITHUB_API_URL", "https://ghe.example.com/api/v3/")
        seen = install(monkeypatch, lambda r: _json({}))
        api._get("/rate_limit")
        assert str(seen[0].url) == "https://ghe.example.com/api/v3/rate_limit"


class TestRetries:
    def test_transient_5xx_is_retried(self, monkeypatch) -> None:
        responses = iter([httpx.Response(502), httpx.Response(503), _json({"ok": 1})])
        seen = install(monkeypatch, lambda r: next(responses))
        assert api._get("/x").payload == {"ok": 1}
        assert len(seen) == 3

    def test_a_dropped_connection_is_retried(self, monkeypatch) -> None:
        calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            if calls["n"] == 1:
                raise httpx.ConnectError("boom", request=request)
            return _json({"ok": 1})

        install(monkeypatch, handler)
        assert api._get("/x").payload == {"ok": 1}

    def test_a_plain_403_is_not_retried(self, monkeypatch) -> None:
        seen = install(monkeypatch, lambda r: _json({"message": "Resource not accessible"}, 403))
        with pytest.raises(api.GitHubError) as info:
            api._get("/x")
        assert info.value.status == 403
        assert not isinstance(info.value, api.GitHubRateLimitError)
        assert len(seen) == 1

    def test_error_message_surfaces_githubs_message(self, monkeypatch) -> None:
        install(monkeypatch, lambda r: _json({"message": "Validation Failed"}, 422))
        with pytest.raises(api.GitHubError, match="Validation Failed"):
            api._get("/x")


class TestRateLimits:
    def test_short_retry_after_is_honoured(self, monkeypatch) -> None:
        waits: list[float] = []
        responses = iter([_json({"message": "secondary rate limit"}, 403, **{"retry-after": "3"}), _json({})])
        install(monkeypatch, lambda r: next(responses))
        monkeypatch.setattr(api.time, "sleep", waits.append)
        api._get("/x")
        assert waits == [3.0]

    @pytest.mark.parametrize("seconds", ["60", "900"])
    def test_long_retry_after_fails_fast(self, monkeypatch, seconds: str) -> None:
        """Even the search budget's one-minute window is too long to block a query for."""
        seen = install(
            monkeypatch, lambda r: _json({"message": "slow down"}, 429, **{"retry-after": seconds})
        )
        with pytest.raises(api.GitHubRateLimitError):
            api._get("/x")
        assert len(seen) == 1, "an hour-long wait must not be slept through"

    def test_exhausted_primary_limit_reports_reset_and_advice(self, monkeypatch) -> None:
        reset = int(time.time()) + 3000
        install(
            monkeypatch,
            lambda r: _json(
                {"message": "API rate limit exceeded"},
                403,
                **{"x-ratelimit-remaining": "0", "x-ratelimit-reset": str(reset)},
            ),
        )
        with pytest.raises(api.GitHubRateLimitError) as info:
            api._get("/x")
        assert info.value.reset_at is not None and int(info.value.reset_at.timestamp()) == reset
        assert "CREATE SECRET" in str(info.value), "anonymous callers should be told how to authenticate"

    def test_authenticated_advice_does_not_suggest_a_token(self, monkeypatch) -> None:
        install(monkeypatch, lambda r: _json({}, 429, **{"x-ratelimit-remaining": "0"}))
        with pytest.raises(api.GitHubRateLimitError) as info:
            api._get("/x", credentials=auth.load("t"))
        assert "CREATE SECRET" not in str(info.value)

    def test_primary_limit_resetting_soon_is_waited_out(self, monkeypatch) -> None:
        waits: list[float] = []
        reset = int(time.time()) + 5  # within MAX_RATE_LIMIT_WAIT
        responses = iter(
            [_json({}, 403, **{"x-ratelimit-remaining": "0", "x-ratelimit-reset": str(reset)}), _json({})]
        )
        install(monkeypatch, lambda r: next(responses))
        monkeypatch.setattr(api.time, "sleep", waits.append)
        api._get("/x")
        assert len(waits) == 1 and 0 < waits[0] <= 7


class TestLinks:
    def test_next_link_is_parsed(self) -> None:
        header = (
            '<https://api.github.com/repositories/1/issues?page=2>; rel="next", '
            '<https://api.github.com/repositories/1/issues?page=9>; rel="last"'
        )
        assert api.next_link({"link": header}) == "https://api.github.com/repositories/1/issues?page=2"
        assert api.next_link({}) is None

    def test_a_next_link_to_another_path_on_the_api_is_followed(self, monkeypatch) -> None:
        """GitHub's own next links point at /repositories/{id}, not the requested path."""
        pages = {
            "/repos/o/r/issues": _json([{"n": 1}], link=f'<{BASE}/repositories/7/issues?page=2>; rel="next"'),
            "/repositories/7/issues": _json([{"n": 2}]),
        }
        install(monkeypatch, lambda r: pages[r.url.path])
        assert [row["n"] for row in api.collect("/repos/o/r/issues")] == [1, 2]

    def test_a_next_links_query_survives_being_followed(self, monkeypatch) -> None:
        """Regression: httpx replaces a URL's query when given params, even an empty list.

        Following GitHub's next link that way dropped its cursor and its
        `state=closed`, so page two of closed issues came back as open ones.
        """
        link = f"{BASE}/repositories/7/issues?state=closed&after=CURSOR&page=2"
        pages = iter([_json([{"n": 1}], link=f'<{link}>; rel="next"'), _json([{"n": 2}])])
        seen = install(monkeypatch, lambda r: next(pages))
        api.collect("/repos/o/r/issues", {"state": "closed"})
        assert dict(seen[1].url.params) == {"state": "closed", "after": "CURSOR", "page": "2"}

    def test_distinct_pages_have_distinct_cache_entries(self, monkeypatch) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            page = request.url.params.get("page", "1")
            return _json([{"page": page}], etag=f'"{page}"')

        install(monkeypatch, handler)
        assert api._get(f"{BASE}/x?page=2").payload == [{"page": "2"}]
        assert api._get(f"{BASE}/x?page=3").payload == [{"page": "3"}]
        assert len(api._ETAGS) == 2

    @pytest.mark.parametrize(
        "link",
        [
            "https://evil.example.com/steal?page=2",
            "http://api.github.com/repos/o/r/issues?page=2",
            "https://api.github.com.evil.com/x",
        ],
    )
    def test_a_next_link_off_the_api_is_refused(self, monkeypatch, link: str) -> None:
        """The link is response data; following it elsewhere would carry the token."""
        seen = install(monkeypatch, lambda r: _json([{"n": 1}], link=f'<{link}>; rel="next"'))
        with pytest.raises(api.GitHubError, match="refusing"):
            api.collect("/repos/o/r/issues", credentials=auth.load("secret"))
        assert len(seen) == 1

    def test_enterprise_prefix_must_be_kept(self, monkeypatch) -> None:
        monkeypatch.setenv("GITHUB_API_URL", "https://ghe.example.com/api/v3")
        with pytest.raises(api.GitHubError):
            api._check_url("https://ghe.example.com/admin/users")
        assert api._check_url("https://ghe.example.com/api/v3/x?page=2")


class TestCollect:
    def test_limit_shrinks_the_page_and_stops_early(self, monkeypatch) -> None:
        seen = install(
            monkeypatch, lambda r: _json([{"n": i} for i in range(5)], link=f'<{BASE}/x?p=2>; rel="next"')
        )
        rows = api.collect("/x", limit=5)
        assert len(rows) == 5 and len(seen) == 1
        assert seen[0].url.params["per_page"] == "5"

    def test_keep_filters_before_counting(self, monkeypatch) -> None:
        pages = iter(
            [
                _json([{"pr": True}, {"pr": False}], link=f'<{BASE}/x?page=2>; rel="next"'),
                _json([{"pr": False}, {"pr": False}]),
            ]
        )
        install(monkeypatch, lambda r: next(pages))
        rows = api.collect("/x", limit=2, keep=lambda row: not row["pr"])
        assert rows == [{"pr": False}, {"pr": False}]

    def test_missing_on_first_page_is_no_rows(self, monkeypatch) -> None:
        install(monkeypatch, lambda r: _json({"message": "Not Found"}, 404))
        assert api.collect("/repos/o/gone/issues") == []

    def test_missing_mid_walk_is_an_error(self, monkeypatch) -> None:
        pages = iter([_json([{"n": 1}], link=f'<{BASE}/x?page=2>; rel="next"'), _json({}, 404)])
        install(monkeypatch, lambda r: next(pages))
        with pytest.raises(api.GitHubError):
            api.collect("/x")

    def test_empty_repository_409_is_no_rows(self, monkeypatch) -> None:
        install(monkeypatch, lambda r: _json({"message": "Git Repository is empty."}, 409))
        assert api.collect("/repos/o/empty/commits") == []

    def test_running_out_of_pages_raises(self, monkeypatch) -> None:
        install(monkeypatch, lambda r: _json([{"n": 1}], link=f'<{BASE}/x?page=n>; rel="next"'))
        with pytest.raises(api.GitHubPageLimitError):
            api.collect("/x")

    def test_wrapped_rows_and_junk_entries(self, monkeypatch) -> None:
        install(monkeypatch, lambda r: _json({"total_count": 3, "items": [{"a": 1}, "junk", None]}))
        assert api.collect("/search/x", key="items") == [{"a": 1}]

    def test_no_content_is_no_rows(self, monkeypatch) -> None:
        install(monkeypatch, lambda r: httpx.Response(204))
        assert api.collect("/repos/o/r/contributors") == []

    def test_non_json_200_names_what_arrived(self, monkeypatch) -> None:
        install(
            monkeypatch, lambda r: httpx.Response(200, text="<html>", headers={"content-type": "text/html"})
        )
        with pytest.raises(api.GitHubError, match="text/html"):
            api._get("/x")


class TestConditionalRequests:
    def test_etag_is_revalidated_and_304_served_from_cache(self, monkeypatch) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.headers.get("If-None-Match") == '"v1"':
                return httpx.Response(304, headers={"etag": '"v1"'})
            return _json({"stars": 5}, etag='"v1"')

        seen = install(monkeypatch, handler)
        assert api._get("/repos/o/r").payload == {"stars": 5}
        assert api._get("/repos/o/r").payload == {"stars": 5}
        assert seen[1].headers["If-None-Match"] == '"v1"'

    def test_cache_is_partitioned_by_token(self, monkeypatch) -> None:
        """A body fetched with one token must never be replayed to another."""
        seen = install(monkeypatch, lambda r: _json({"x": 1}, etag='"e"'))
        api._get("/repos/o/private", credentials=auth.load("token-a"))
        api._get("/repos/o/private", credentials=auth.load("token-b"))
        api._get("/repos/o/private")
        assert all("If-None-Match" not in r.headers for r in seen)

    def test_cached_bodies_are_not_aliased(self, monkeypatch) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.headers.get("If-None-Match"):
                return httpx.Response(304)
            return _json({"x": 1}, etag='"e"')

        install(monkeypatch, handler)
        first = api._get("/r").payload
        first["x"] = "mutated"
        assert api._get("/r").payload == {"x": 1}

    def test_lru_is_bounded(self) -> None:
        cache = api._ETagCache(2)
        for key in ("a", "b", "c"):
            cache.store((key,), api._Cached("e", b"{}", None, ""))
        assert len(cache) == 2 and cache.get(("a",)) is None


class TestCacheHint:
    def test_public_max_age_is_cacheable(self) -> None:
        hint = api.CacheHint()
        hint.observe({"cache-control": "public, max-age=60, s-maxage=60"})
        assert hint.cacheable and hint.max_age == 60

    def test_private_is_not(self) -> None:
        """Every authenticated GitHub response is private: specific to the token."""
        hint = api.CacheHint()
        hint.observe({"cache-control": "private, max-age=60, s-maxage=60"})
        assert not hint.cacheable

    def test_s_maxage_alone_is_not_max_age(self) -> None:
        hint = api.CacheHint()
        hint.observe({"cache-control": "public, s-maxage=60"})
        assert not hint.cacheable


class TestInputValidation:
    @pytest.mark.parametrize("name", ["duckdb/duckdb", "a-b/c.d_e", "Query-farm/vgi-kalshi"])
    def test_valid_repositories(self, name: str) -> None:
        owner, repo = api.split_repo(name)
        assert f"{owner}/{repo}" == name

    @pytest.mark.parametrize(
        "name", ["duckdb", "a/b/c", "/b", "a/", "a/..", "../x", "a/b?x=1", "a b/c", "a/%2e%2e", ""]
    )
    def test_invalid_repositories(self, name: str) -> None:
        with pytest.raises(api.GitHubInputError):
            api.split_repo(name)

    @pytest.mark.parametrize("value", ["", ".", ".."])
    def test_dot_segments_refused(self, value: str) -> None:
        with pytest.raises(api.GitHubInputError):
            api.segment(value)

    def test_separators_are_encoded(self) -> None:
        assert api.segment("../user") == "..%2Fuser"
        assert api.segment("a?b") == "a%3Fb"
