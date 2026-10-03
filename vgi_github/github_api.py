"""Read-only HTTP access to the GitHub REST API.

Every function here issues ``GET`` requests only — the single chokepoint
:func:`_get` is the sole place an HTTP call is made, which is what the read-only
CI guard (``tests/test_readonly_guard.py``) asserts against.

Three GitHub behaviours shape this module more than any endpoint does:

* **Rate limits are tight and explicit.** 60 requests an hour anonymously, 5,000
  with a token, and a separate 30-a-minute budget for search. Unlike many APIs,
  GitHub *tells* you when you may retry (``Retry-After``, ``X-RateLimit-Reset``),
  so a short wait is honoured and a long one is reported instead of slept.
* **Pagination is by ``Link`` header**, and the ``next`` URL GitHub hands back
  is not necessarily the path that was asked for — a repository's issues page
  ``next`` points at ``/repositories/{id}/issues``. Following it is therefore
  checked against the API origin rather than the original path.
* **Conditional requests are free.** A ``304 Not Modified`` does not count
  against the primary rate limit, and every response carries an ``ETag``, so a
  small in-process cache turns a repeated ``LATERAL`` into near-free
  revalidations.
"""

from __future__ import annotations

import atexit
import contextlib
import contextvars
import json
import os
import re
import threading
import time
from collections import OrderedDict
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote, urlsplit

import httpx

from vgi_github import __version__
from vgi_github.auth import Credentials

#: Production base URL. ``GITHUB_API_URL`` overrides it — the same variable
#: GitHub Actions sets, and the way to point at a GitHub Enterprise Server
#: (``https://ghe.example.com/api/v3``).
DEFAULT_BASE_URL = "https://api.github.com"

#: The REST API version this worker's schemas were written against. Sent on
#: every request so a future default-version change cannot reshape a payload
#: underneath a running worker.
API_VERSION = "2022-11-28"

#: GitHub rejects requests without a User-Agent outright.
USER_AGENT = f"vgi-github/{__version__} (+https://github.com/Query-farm/vgi-github)"

#: The default media type. ``star+json`` is requested only by ``stargazers``.
ACCEPT_JSON = "application/vnd.github+json"
ACCEPT_STAR = "application/vnd.github.star+json"

#: Largest page size any list endpoint accepts; larger values are clamped.
PER_PAGE = 100

#: Search returns at most the first 1,000 results of any query; asking for page
#: 11 at 100 a page is HTTP 422, not an empty page.
SEARCH_RESULT_CAP = 1_000

#: Hard stop on following ``next`` links, so a runaway walk cannot hang a query
#: forever. 100 pages is 10,000 rows. Hitting it is an error, not a quiet
#: truncation — see :class:`GitHubPageLimitError`.
MAX_PAGES = 100

#: Connect and read timeouts for every request this module makes.
TIMEOUT = httpx.Timeout(30.0, connect=10.0)

#: Grace window (seconds) for serving a stale cached result when a refetch
#: fails. Shared by every function that advertises cacheability.
STALE_IF_ERROR = 300

#: The longest wait this client will sleep through for a rate limit. GitHub may
#: ask for up to an hour, and even the search budget's one-minute window is too
#: long to block for: the wait happens inside a ``process()`` call, which cannot
#: be cancelled, so the client is wedged for as long as this sleeps. A brief
#: secondary-limit pause is worth absorbing; anything longer fails with the
#: reset time, which the caller can act on.
MAX_RATE_LIMIT_WAIT = 15

#: Statuses whose meaning for a keyed lookup is "there is nothing here":
#: 404 (absent — or private and unauthorized; GitHub does not distinguish),
#: 410 (gone, e.g. issues disabled), 451 (removed for legal reasons) and 409
#: (an empty repository, which has no commits to list).
MISSING_STATUSES = frozenset({404, 409, 410, 451})

#: ``max-age=N``, anchored to a directive boundary so it cannot match the tail
#: of some other token (``s-maxage`` is a shared-cache directive, not ours).
_MAX_AGE = re.compile(r"(?:^|[\s,])max-age=(\d+)")

#: Directives that forbid reuse outright, whatever ``max-age`` also says.
#: ``private`` means "not for a shared cache", which the DuckDB result cache is
#: — and GitHub marks every authenticated response private, because what a
#: token can see is specific to that token.
_NO_REUSE = re.compile(r"(?:^|[\s,])(?:no-store|no-cache|private)(?:\s*[,=]|\s*$)")

#: ``<url>; rel="next"`` within a Link header.
_LINK_NEXT = re.compile(r'<([^>]+)>\s*;\s*rel="?next"?')

#: Transient server-side statuses, retried with exponential backoff.
_RETRYABLE_STATUSES = frozenset({500, 502, 503, 504})

#: Exponential backoff: ~0.5s, 1s, 2s, 4s.
_RETRY_ATTEMPTS = 5
_RETRY_BASE_SECONDS = 0.5

#: Conditional-request cache bounds. Entries hold raw response bodies, so the
#: count is capped and oversized bodies are not kept at all.
_ETAG_CACHE_ENTRIES = 512
_ETAG_CACHE_MAX_BODY = 2 * 1024 * 1024


@dataclass(slots=True)
class CacheHint:
    """The origin's own freshness opinion, collected across a call's responses.

    GitHub sends ``public, max-age=60`` on anonymous responses and
    ``private, max-age=60`` on authenticated ones. Only the first is reusable by
    a shared result cache; the second is specific to the token that fetched it.

    ``max_age`` is the **minimum** seen across every response folded into it,
    so the shortest-lived page bounds the result. It stays ``None`` when the
    origin declared nothing reusable.
    """

    max_age: int | None = None
    #: True once any response arrived without a usable freshness directive.
    saw_uncacheable: bool = field(default=False)

    def observe(self, headers: httpx.Headers | dict[str, str]) -> None:
        """Fold one response's Cache-Control into the running hint."""
        directives = headers.get("cache-control", "") or ""
        match = _MAX_AGE.search(directives)
        if match is None or _NO_REUSE.search(directives):
            self.saw_uncacheable = True
            return
        seconds = int(match.group(1))
        if seconds == 0:
            self.saw_uncacheable = True
            return
        self.max_age = seconds if self.max_age is None else min(self.max_age, seconds)

    @property
    def cacheable(self) -> bool:
        """Whether every response in this call carried a usable freshness directive."""
        return self.max_age is not None and not self.saw_uncacheable


def base_url() -> str:
    """The API base URL, overridable with ``GITHUB_API_URL``."""
    return os.environ.get("GITHUB_API_URL", DEFAULT_BASE_URL).rstrip("/")


def open_client() -> httpx.Client:
    """Open a client carrying this module's timeouts and fixed headers.

    Callers that issue a burst of per-row fetches (a correlated LATERAL) should
    open one of these and pass it in, so the whole batch shares a connection
    pool. It is the only httpx object the rest of the package constructs.

    Redirects are followed because GitHub answers a request for a renamed or
    transferred repository with a 301 to its new home. httpx drops the
    ``Authorization`` header on a cross-origin redirect, so a redirect cannot
    carry the token off GitHub.
    """
    return httpx.Client(
        timeout=TIMEOUT,
        follow_redirects=True,
        headers={"User-Agent": USER_AGENT, "X-GitHub-Api-Version": API_VERSION},
    )


_shared: httpx.Client | None = None
_shared_lock = threading.Lock()


def shared_client() -> httpx.Client:
    """A process-wide client, for calls that have no batch to share one with.

    A paged scan fetches one page per ``process()`` tick, so there is no
    enclosing scope to hold a client open across the walk; without this every
    page would pay a fresh TLS handshake.
    """
    global _shared
    if _shared is None or _shared.is_closed:
        with _shared_lock:
            if _shared is None or _shared.is_closed:
                _shared = open_client()
    return _shared


def reset_shared_client() -> None:
    """Close and forget the process pool and the conditional-request cache.

    Operationally it forces a reconnect; in tests it makes both hermetic, since
    each is process-wide state that would otherwise leak from one test into the
    next.
    """
    global _shared
    with _shared_lock:
        if _shared is not None and not _shared.is_closed:
            _shared.close()
        _shared = None
    _ETAGS.clear()


atexit.register(reset_shared_client)


# --------------------------------------------------------------------------
# Input validation
# --------------------------------------------------------------------------

#: What GitHub allows in an owner or repository name. Owners are narrower
#: (alphanumerics and hyphens) but repository names also allow ``.`` and ``_``,
#: and one pattern for both keeps the check honest without second-guessing
#: GitHub's own validation, which still runs.
_NAME = re.compile(r"^[A-Za-z0-9._-]+$")


class GitHubInputError(ValueError):
    """A caller-supplied key cannot name a GitHub object."""


def segment(value: str) -> str:
    """Percent-encode one path segment, so a value cannot escape its position.

    Owner, repository and user names reach this module straight from user SQL.
    Interpolated raw, ``../../user`` would resolve outside the object it was
    meant to name, and with a token configured the request would be authorized.
    ``/`` and ``?`` are encoded so a segment stays a segment, and the
    dot-segments ``.`` and ``..`` — which URL normalisation would collapse
    whatever their encoding — are refused outright.
    """
    if value in ("", ".", ".."):
        raise GitHubInputError(f"{value!r} is not a valid GitHub name")
    return quote(value, safe="")


def split_repo(full_name: str) -> tuple[str, str]:
    """Split ``'owner/name'`` into its two path segments, validated.

    Raises:
        GitHubInputError: The value is not exactly ``owner/name`` with both
            halves made of characters GitHub permits.
    """
    owner, sep, name = str(full_name).strip().partition("/")
    dots = (".", "..")
    if not sep or not _NAME.fullmatch(owner) or not _NAME.fullmatch(name) or owner in dots or name in dots:
        raise GitHubInputError(f"repository must be written 'owner/name', got {full_name!r}")
    return owner, name


def repo_path(full_name: str) -> str:
    """``/repos/{owner}/{name}`` for a validated ``owner/name``."""
    owner, name = split_repo(full_name)
    return f"/repos/{segment(owner)}/{segment(name)}"


# --------------------------------------------------------------------------
# Errors
# --------------------------------------------------------------------------


class GitHubError(RuntimeError):
    """A non-2xx response from the GitHub API, carrying the status and message."""

    def __init__(self, status: int, path: str, body: str) -> None:
        super().__init__(f"GitHub API {status} for {path}: {_message_of(body)[:400]}")
        self.status = status
        self.path = path


class GitHubRateLimitError(GitHubError):
    """A rate limit that would take longer than :data:`MAX_RATE_LIMIT_WAIT` to clear."""

    def __init__(self, status: int, path: str, body: str, *, reset_at: datetime | None, authenticated: bool):
        super().__init__(status, path, body)
        self.reset_at = reset_at
        when = f" until {reset_at.isoformat()}" if reset_at else ""
        advice = (
            "wait for the reset or reduce the number of requests (lower max_rows, fewer LATERAL rows)"
            if authenticated
            else "anonymous access is limited to 60 requests an hour — CREATE SECRET (TYPE github, "
            "token '...') for 5,000"
        )
        self.args = (f"GitHub API rate limit exceeded for {path}{when}; {advice}",)


class GitHubPageLimitError(RuntimeError):
    """A walk followed :data:`MAX_PAGES` links without reaching the end.

    Raised rather than returning the truncated prefix: a silently short result
    reads as real data, and nothing downstream can tell the difference.
    """

    def __init__(self, path: str, rows: int) -> None:
        super().__init__(
            f"GitHub API {path}: still paging after {MAX_PAGES} pages ({rows} rows); "
            "narrow the query or pass a non-zero max_rows"
        )
        self.path = path
        self.rows = rows


def _message_of(body: str) -> str:
    """GitHub's own ``message`` from an error body, or the raw body."""
    try:
        decoded = json.loads(body)
    except ValueError:
        return body
    if isinstance(decoded, dict) and decoded.get("message"):
        return str(decoded["message"])
    return body


# --------------------------------------------------------------------------
# Conditional requests
# --------------------------------------------------------------------------


@dataclass(slots=True, frozen=True)
class _Cached:
    etag: str
    body: bytes
    link: str | None
    cache_control: str


class _ETagCache:
    """A bounded LRU of ``(request, token) -> (ETag, body)``.

    GitHub does not count a ``304 Not Modified`` against the primary rate limit
    when the request is authorized, so revalidating instead of refetching makes
    a repeated lookup nearly free — and a correlated LATERAL repeats lookups
    constantly. Bodies are stored as bytes and re-decoded on every hit, so a
    caller mutating its rows cannot corrupt what the next caller gets.
    """

    def __init__(self, capacity: int) -> None:
        self._capacity = capacity
        self._entries: OrderedDict[tuple[str, ...], _Cached] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: tuple[str, ...]) -> _Cached | None:
        with self._lock:
            entry = self._entries.get(key)
            if entry is not None:
                self._entries.move_to_end(key)
            return entry

    def store(self, key: tuple[str, ...], entry: _Cached) -> None:
        if len(entry.body) > _ETAG_CACHE_MAX_BODY:
            return
        with self._lock:
            self._entries[key] = entry
            self._entries.move_to_end(key)
            while len(self._entries) > self._capacity:
                self._entries.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()

    def __len__(self) -> int:
        return len(self._entries)


_ETAGS = _ETagCache(_ETAG_CACHE_ENTRIES)


# --------------------------------------------------------------------------
# Telling the caller what happened
# --------------------------------------------------------------------------

#: Budget below which a call warns: this fraction of the limit, or this many
#: requests, whichever is larger.
_LOW_BUDGET_FRACTION = 0.10
_LOW_BUDGET_FLOOR = 10

#: ``(level, message)`` — level is a vgi_rpc ``Level`` name such as ``"WARN"``.
Emit = Callable[[str, str], None]


@dataclass(slots=True)
class ActivityLog:
    """What one function call did on the wire, reported back to the DuckDB client.

    Rate-limit waits and retries happen inside a call, so without this a
    throttled query just looks slow. Warnings go out as they happen; a one-line
    summary goes out when the call finishes.
    """

    emit: Emit
    requests: int = 0
    revalidated: int = 0
    retries: int = 0
    #: resource -> (remaining, limit, reset epoch), from the latest response.
    budget: dict[str, tuple[int, int, int]] = field(default_factory=dict)
    warned_low: set[str] = field(default_factory=set)

    def warn(self, message: str) -> None:
        self.emit("WARN", message)

    def observe(self, response: httpx.Response) -> None:
        headers = response.headers
        try:
            remaining = int(headers["x-ratelimit-remaining"])
            limit = int(headers["x-ratelimit-limit"])
            reset = int(headers.get("x-ratelimit-reset", "0"))
        except (KeyError, ValueError):
            return
        resource = headers.get("x-ratelimit-resource", "core")
        self.budget[resource] = (remaining, limit, reset)
        threshold = max(_LOW_BUDGET_FLOOR, int(limit * _LOW_BUDGET_FRACTION))
        if remaining < threshold and resource not in self.warned_low:
            self.warned_low.add(resource)
            self.warn(
                f"GitHub {resource} budget is low: {remaining} of {limit} requests left, "
                f"resets at {_clock(reset)}"
            )

    def summary(self) -> str:
        parts = [f"{self.requests} GitHub request{'s' if self.requests != 1 else ''}"]
        if self.revalidated:
            parts.append(f"{self.revalidated} unchanged (free)")
        if self.retries:
            parts.append(f"{self.retries} retried")
        for resource, (remaining, limit, reset) in sorted(self.budget.items()):
            parts.append(f"{resource} budget {remaining}/{limit}, resets {_clock(reset)}")
        return "; ".join(parts)


def _clock(epoch: int) -> str:
    return datetime.fromtimestamp(epoch, tz=UTC).strftime("%H:%M:%S UTC") if epoch else "unknown"


_activity: contextvars.ContextVar[ActivityLog | None] = contextvars.ContextVar(
    "github_activity", default=None
)


@contextlib.contextmanager
def reporting_to(emit: Emit) -> Iterator[ActivityLog]:
    """Report this call's rate-limit waits, retries and budget through ``emit``.

    A context variable carries it down to :func:`_get`, so none of the fetch
    helpers between a function and the chokepoint need a parameter for it. The
    summary is emitted on the way out, even if the call failed.
    """
    log = ActivityLog(emit)
    token = _activity.set(log)
    try:
        yield log
    finally:
        _activity.reset(token)
        if log.requests:
            emit("INFO", log.summary())


# --------------------------------------------------------------------------
# The chokepoint
# --------------------------------------------------------------------------


def _check_url(url: str) -> str:
    """Refuse any absolute URL outside the configured API base.

    ``next`` links come from response headers, so they are data, not code. A
    link pointing anywhere else — another host, a downgrade to ``http``, or a
    path outside an Enterprise server's ``/api/v3`` prefix — would carry the
    token with it, and is refused rather than followed.
    """
    base = urlsplit(base_url())
    target = urlsplit(url)
    prefix = base.path.rstrip("/") + "/"
    if (target.scheme, target.netloc) != (base.scheme, base.netloc) or not target.path.startswith(prefix):
        raise GitHubError(0, url, f"refusing to follow a link outside {base_url()}")
    return url


def _retry_after(response: httpx.Response, attempt: int) -> float | None:
    """How long to wait before retrying ``response``, or None to stop now.

    GitHub has two rate limits and says which one you hit. A secondary limit
    sends ``Retry-After``; an exhausted primary limit sends
    ``X-RateLimit-Remaining: 0`` and the epoch second it resets. Either is
    honoured if it is short, and reported if it is not — sleeping for most of
    an hour inside a query is not a retry, it is a hang.
    """
    status = response.status_code
    if status in _RETRYABLE_STATUSES:
        return _RETRY_BASE_SECONDS * (2**attempt)
    if status not in (403, 429):
        return None
    if (retry_after := response.headers.get("retry-after")) is not None:
        try:
            wait = float(retry_after)
        except ValueError:
            return None
        return wait if wait <= MAX_RATE_LIMIT_WAIT else None
    if response.headers.get("x-ratelimit-remaining") == "0":
        reset = _reset_at(response)
        if reset is None:
            return None
        wait = max(reset.timestamp() - time.time(), 0) + 1
        return wait if wait <= MAX_RATE_LIMIT_WAIT else None
    # A bare 429 with no guidance is still a rate limit; a bare 403 is a
    # permission failure, and retrying it changes nothing.
    return _RETRY_BASE_SECONDS * (2**attempt) if status == 429 else None


def _reset_at(response: httpx.Response) -> datetime | None:
    raw = response.headers.get("x-ratelimit-reset")
    try:
        return datetime.fromtimestamp(int(raw), tz=UTC) if raw else None
    except (ValueError, OverflowError, OSError):
        return None


def _is_rate_limited(response: httpx.Response) -> bool:
    if response.status_code == 429:
        return True
    if response.status_code != 403:
        return False
    if response.headers.get("x-ratelimit-remaining") == "0" or "retry-after" in response.headers:
        return True
    return "rate limit" in response.text.lower()


def next_link(headers: httpx.Headers | dict[str, str]) -> str | None:
    """The ``rel="next"`` URL from a Link header, or None on the last page."""
    match = _LINK_NEXT.search(headers.get("link", "") or "")
    return match.group(1) if match else None


@dataclass(slots=True)
class Response:
    """A decoded response: the JSON payload, the next-page link, and the status."""

    payload: Any
    next_url: str | None
    status: int


def _get(
    path_or_url: str,
    params: dict[str, Any] | Sequence[tuple[str, Any]] | None = None,
    *,
    client: httpx.Client | None = None,
    hint: CacheHint | None = None,
    credentials: Credentials | None = None,
    accept: str = ACCEPT_JSON,
) -> Response:
    """GET a path below the API base (or a validated absolute link) and decode it.

    The one and only outbound-HTTP chokepoint. It issues ``GET`` and nothing
    else; adding a write verb here is the thing the read-only guard forbids.

    Retries transient failures (5xx, transport errors) with exponential backoff
    and honours short rate-limit waits; see :func:`_retry_after`. Revalidates
    against the conditional-request cache when it holds an ETag for this exact
    request and token.

    Args:
        path_or_url: A path with a leading slash, or an absolute ``next`` link.
        params: Query parameters; ``None`` values are dropped. Ignored by
            GitHub's ``next`` links, which already carry their own.
        client: Optional caller-owned client, so a lateral join can reuse one
            connection pool across a batch of per-row fetches.
        hint: Optional :class:`CacheHint` to fold this response's
            ``Cache-Control`` into.
        credentials: Optional token. ``None`` goes out anonymously.
        accept: The media type to request.

    Raises:
        GitHubRateLimitError: A rate limit too long to wait out.
        GitHubError: Any other non-2xx after retries, or a 2xx body that was
            not JSON.
        httpx.TransportError: Every attempt failed to reach the API.
    """
    url = f"{base_url()}{path_or_url}" if path_or_url.startswith("/") else _check_url(path_or_url)
    pairs = list(params.items()) if isinstance(params, dict) else list(params or ())
    clean: Any = [(k, str(v).lower() if isinstance(v, bool) else v) for k, v in pairs if v is not None]
    # Passing ``params`` to httpx *replaces* a URL's query string rather than
    # merging into it, so a ``next`` link followed with an empty list silently
    # loses its cursor and every filter on it — page 2 of ``state=closed``
    # quietly became page 1 of the default, open issues. A link carries its own
    # query; send params only with a bare path, and never an empty list.
    if not path_or_url.startswith("/") or not clean:
        clean = None
    target = httpx.URL(url, params=clean) if clean else httpx.URL(url)
    key = (str(target), accept, credentials.fingerprint if credentials else "")
    cached = _ETAGS.get(key)

    headers = {"Accept": accept}
    if credentials is not None:
        headers.update(credentials.headers())
    if cached is not None:
        headers["If-None-Match"] = cached.etag

    http = client or shared_client()
    activity = _activity.get()
    for attempt in range(_RETRY_ATTEMPTS):
        last_attempt = attempt == _RETRY_ATTEMPTS - 1
        if activity is not None:
            activity.requests += 1
        try:
            response = http.get(target, headers=headers)
        except httpx.TransportError as exc:
            if last_attempt:
                raise
            wait = _RETRY_BASE_SECONDS * (2**attempt)
            if activity is not None:
                activity.retries += 1
                activity.warn(
                    f"GitHub request to {path_or_url} failed ({type(exc).__name__}); "
                    f"retrying in {wait:g}s (attempt {attempt + 2} of {_RETRY_ATTEMPTS})"
                )
            time.sleep(wait)
            continue
        if activity is not None:
            activity.observe(response)
        wait = _retry_after(response, attempt) if response.status_code >= 400 else None
        if wait is None or last_attempt:
            break
        if activity is not None:
            activity.retries += 1
            why = "rate limited" if _is_rate_limited(response) else f"answered {response.status_code}"
            activity.warn(
                f"GitHub {why} on {path_or_url}; waiting {wait:g}s before retrying "
                f"(attempt {attempt + 2} of {_RETRY_ATTEMPTS})"
            )
        time.sleep(wait)

    if response.status_code == 304 and cached is not None:
        if activity is not None:
            activity.revalidated += 1
        if hint is not None:
            hint.observe(response.headers)
        return Response(_decode(cached.body, url, 200), cached.link, 200)
    if response.status_code >= 400:
        if _is_rate_limited(response):
            raise GitHubRateLimitError(
                response.status_code,
                path_or_url,
                response.text,
                reset_at=_reset_at(response),
                authenticated=credentials is not None,
            )
        raise GitHubError(response.status_code, path_or_url, response.text)
    # Only fold a served response into the freshness hint; an error carries the
    # CDN's policy, not the resource's.
    if hint is not None:
        hint.observe(response.headers)
    link = next_link(response.headers)
    if response.status_code == 204 or not response.content:
        return Response(None, link, response.status_code)
    payload = _decode(response.content, url, response.status_code, response.headers.get("content-type"))
    if etag := response.headers.get("etag"):
        _ETAGS.store(key, _Cached(etag, response.content, link, response.headers.get("cache-control", "")))
    return Response(payload, link, response.status_code)


def _decode(body: bytes, url: str, status: int, content_type: str | None = None) -> Any:
    """Decode a JSON body, or raise a GitHubError that names what arrived instead."""
    try:
        return json.loads(body)
    except ValueError as exc:
        raise GitHubError(
            status, url, f"expected JSON, got {content_type or 'no content-type'}: {body[:200]!r}"
        ) from exc


# --------------------------------------------------------------------------
# Paging
# --------------------------------------------------------------------------


def rows_of(payload: Any, key: str | None) -> list[dict[str, Any]]:
    """The list of row objects in one page, tolerating a malformed page.

    Most list endpoints return a bare JSON array; search and Actions wrap it in
    an object (``items``, ``workflow_runs``). Anything that is not a dict in the
    list is dropped: a malformed entry should cost that entry, not the scan.
    """
    if key is not None:
        payload = payload.get(key) if isinstance(payload, dict) else None
    if not isinstance(payload, list):
        return []
    return [row for row in payload if isinstance(row, dict)]


def page(
    path_or_url: str,
    params: dict[str, Any] | None = None,
    *,
    key: str | None = None,
    client: httpx.Client | None = None,
    hint: CacheHint | None = None,
    credentials: Credentials | None = None,
    accept: str = ACCEPT_JSON,
) -> tuple[list[dict[str, Any]], str | None]:
    """Fetch exactly one page, returning its rows and the link to the next.

    The primitive behind both paging styles: :func:`collect` loops on it for a
    bounded call, and a scan holds the link in its state and calls this once
    per tick. A ``None`` link means this was the last page. ``params`` apply to
    the first page only — a ``next`` link carries its own.
    """
    response = _get(
        path_or_url,
        params if path_or_url.startswith("/") else None,
        client=client,
        hint=hint,
        credentials=credentials,
        accept=accept,
    )
    rows = rows_of(response.payload, key)
    # An empty page ends the walk even when a link comes back with it.
    return rows, (response.next_url if rows else None)


def collect(
    path: str,
    params: dict[str, Any] | None = None,
    *,
    key: str | None = None,
    limit: int | None = None,
    keep: Callable[[dict[str, Any]], bool] | None = None,
    missing_ok: bool = True,
    client: httpx.Client | None = None,
    hint: CacheHint | None = None,
    credentials: Credentials | None = None,
    accept: str = ACCEPT_JSON,
) -> list[dict[str, Any]]:
    """Follow ``next`` links and accumulate rows, up to ``limit``.

    The page size is shrunk to the limit when the caller wants less than a full
    page — asking for 100 to keep 5 is wasted bandwidth and, on search, wasted
    rate-limit budget.

    Args:
        path: Path below the API base.
        params: Query parameters for the first page.
        key: Key holding the rows, for endpoints that wrap their list.
        limit: Stop once this many rows have been *kept*. ``None`` walks to the
            end, bounded by :data:`MAX_PAGES`.
        keep: Optional row predicate applied before counting toward ``limit``
            (e.g. dropping pull requests from the issues listing).
        missing_ok: Treat a :data:`MISSING_STATUSES` answer on the **first**
            page as "no rows". A missing page mid-walk is still an error: the
            object existed a moment ago, and a short result would look whole.
    """
    rows: list[dict[str, Any]] = []
    per_page = PER_PAGE if limit is None or keep is not None else max(1, min(PER_PAGE, limit))
    target: str = path
    first = {**(params or {}), "per_page": per_page}
    for index in range(MAX_PAGES):
        try:
            batch, target_next = page(
                target,
                first if index == 0 else None,
                key=key,
                client=client,
                hint=hint,
                credentials=credentials,
                accept=accept,
            )
        except GitHubError as exc:
            if index == 0 and missing_ok and exc.status in MISSING_STATUSES:
                return []
            raise
        rows.extend(row for row in batch if keep is None or keep(row))
        if limit is not None and len(rows) >= limit:
            return rows[:limit]
        if target_next is None:
            return rows
        target = target_next
    raise GitHubPageLimitError(path, len(rows))


def lookup(
    path: str,
    params: dict[str, Any] | None = None,
    *,
    client: httpx.Client | None = None,
    hint: CacheHint | None = None,
    credentials: Credentials | None = None,
) -> dict[str, Any] | None:
    """One object by path, or None when GitHub says it is not there."""
    try:
        payload = _get(path, params, client=client, hint=hint, credentials=credentials).payload
    except GitHubError as exc:
        if exc.status in MISSING_STATUSES:
            return None
        raise
    return payload if isinstance(payload, dict) else None
