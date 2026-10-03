"""Optional GitHub token authentication.

Authentication is optional, but on GitHub it matters far more than it does on
most public APIs: anonymous traffic gets **60 requests an hour per IP**, against
5,000 an hour for a token. A correlated ``LATERAL`` issues at least one request
per input row, so without a token a join across a modest organisation exhausts
the anonymous budget in a single query. A token is also the only way to read a
private repository.

Credentials arrive as a DuckDB secret rather than an ATTACH option, because an
ATTACH option string is visible in ``duckdb_databases()`` and in anything that
logs the statement::

    CREATE SECRET github (TYPE github, token 'ghp_...');

    -- in the DuckDB CLI, straight from the environment:
    CREATE SECRET github (TYPE github, token getenv('GITHUB_TOKEN'));

    -- a GitHub Enterprise Server token, chosen by scope:
    CREATE SECRET ghe (TYPE github, token '...', SCOPE 'https://ghe.example.com');

``token`` is marked redacted, so ``duckdb_secrets()`` shows it masked. Any
token GitHub accepts as a bearer token works: a classic or fine-grained
personal access token, an OAuth token (what ``gh auth token`` prints), or a
GitHub App installation token. Read-only scopes are sufficient — this worker
never writes.

Authenticating stays read-only: it adds an ``Authorization`` header to a
``GET`` and nothing else. The chokepoint in :mod:`vgi_github.github_api` is
still the only place an HTTP call is made.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass, field
from typing import Any

import pyarrow as pa
from vgi.catalog.secret_type import SecretTypeSpec

#: The DuckDB secret type this worker registers at ATTACH.
SECRET_TYPE = "github"

#: The one secret key: a bearer token.
TOKEN = "token"

SECRET_SPEC = SecretTypeSpec(
    name=SECRET_TYPE,
    description=(
        "GitHub API token for authenticated access. Optional, but anonymous access is limited "
        "to 60 requests an hour and cannot see private repositories. Provide token (a personal "
        "access token, OAuth token such as `gh auth token` prints, or an App installation token)."
    ),
    schema=pa.schema([pa.field(TOKEN, pa.string(), metadata={"redact": "true"})]),
)


class GitHubAuthError(RuntimeError):
    """A credential was supplied but cannot be used, or one was required and absent."""


@dataclass(slots=True, frozen=True)
class Credentials:
    """A GitHub token, ready to authorize requests."""

    token: str = field(repr=False)

    def headers(self) -> dict[str, str]:
        """The header that authorizes one request."""
        return {"Authorization": f"Bearer {self.token}"}

    @property
    def fingerprint(self) -> str:
        """A stable, non-reversible identity for this token.

        Used to partition the conditional-request cache, so an ETag and body
        fetched with one token are never replayed to a caller holding another —
        or holding none. Two tokens can see different things (a private
        repository, say), so sharing an entry across them would leak.
        """
        return hashlib.sha256(self.token.encode()).hexdigest()[:16]


def load(token: str) -> Credentials:
    """Validate a token's shape and wrap it as :class:`Credentials`.

    Only the shape is checked. GitHub has issued tokens in several formats over
    the years (40 hex characters, ``ghp_``, ``gho_``, ``github_pat_``, ...), and
    a GitHub Enterprise Server may issue others, so the prefix is deliberately
    not policed. Whitespace is, because a pasted token with a trailing newline
    is the most common way to get a confusing 401.

    Raises:
        GitHubAuthError: The token is empty or contains whitespace.
    """
    token = (token or "").strip()
    if not token:
        raise GitHubAuthError(f"a {SECRET_TYPE!r} secret needs a non-empty {TOKEN!r}")
    if any(ch.isspace() for ch in token):
        raise GitHubAuthError(f"the {TOKEN!r} in the {SECRET_TYPE!r} secret contains whitespace")
    return Credentials(token=token)


def _select(secrets: dict[str, dict[str, Any]], scope: str | None) -> dict[str, Any] | None:
    """The ``github`` secret that applies to ``scope``, from resolved DuckDB secrets.

    Resolved secrets are keyed by each secret's *name* — whatever followed
    ``CREATE SECRET`` — not by its type, so looking one up by the type string
    only works when someone happened to name it ``github``. Selection goes by
    the ``type`` field instead, and by ``SCOPE`` when several are present: a
    secret scoped to ``https://ghe.example.com`` serves an Enterprise server
    while an unscoped one serves github.com, the longest matching prefix
    winning and an unscoped secret acting as the fallback.
    """
    selector = getattr(secrets, "for_scope_of_type", None)
    if selector is not None:
        found = selector(scope or "", SECRET_TYPE)
        if found:
            return dict(found)
    # A plain dict (tests, or an older framework) keyed by name or type.
    by_name = secrets.get(SECRET_TYPE)
    if by_name:
        return by_name
    typed = [v for v in secrets.values() if isinstance(v, dict) and _text(v.get("type")) == SECRET_TYPE]
    return typed[0] if typed else None


def _text(raw: Any) -> str:
    """A resolved secret field as text; they arrive as Arrow scalars, tests pass plain values."""
    value = raw.as_py() if hasattr(raw, "as_py") else raw
    return "" if value is None else str(value)


def from_secrets(secrets: dict[str, dict[str, Any]] | None, scope: str | None = None) -> Credentials | None:
    """Build credentials from resolved DuckDB secrets, or None for anonymous access.

    A missing secret is the normal case, not an error: public data is readable
    anonymously. A secret that is *present* but unusable does raise — someone
    asked for authentication and would otherwise silently get anonymous access
    on a budget eighty times smaller.

    Args:
        secrets: Resolved secrets, as the framework hands them to a function.
        scope: The API base URL being called, used to pick between several
            ``github`` secrets by their ``SCOPE``.
    """
    values = _select(secrets, scope) if secrets else None
    if not values:
        return None
    return load(_text(values.get(TOKEN)))


#: Environment variable the *operator* can set to give the worker a token of its
#: own, used only when no ``github`` secret resolves. Deliberately not the
#: ambient ``GITHUB_TOKEN``/``GH_TOKEN``: on an HTTP-served worker every caller
#: would inherit that token's identity and private-repository access, so it
#: must be something nobody sets by accident. CI and ``vgi-lint`` use it, since
#: neither can issue ``CREATE SECRET`` before running a query.
ENV_TOKEN = "VGI_GITHUB_TOKEN"


def from_environment() -> Credentials | None:
    """The operator's fallback token from :data:`ENV_TOKEN`, if set."""
    token = os.environ.get(ENV_TOKEN, "").strip()
    return load(token) if token else None


# ---------------------------------------------------------------------------
# Token sources: where ATTACH may tell the worker to find your identity
# ---------------------------------------------------------------------------

#: ``token_source`` values. The ATTACH option names *where* to get a token,
#: never the token itself: an ATTACH string is visible in ``duckdb_databases()``
#: and lands in logs and shell history, which is why a token is a secret.
SOURCE_NONE = ""
SOURCE_GH = "gh"
SOURCE_ENV = "env"
SOURCES = (SOURCE_NONE, SOURCE_GH, SOURCE_ENV)

#: The standard variables ``token_source 'env'`` reads, in GitHub CLI order.
SOURCE_ENV_VARS = ("GH_TOKEN", "GITHUB_TOKEN")

#: How long a token read from ``gh auth token`` is reused. Spawning ``gh`` costs
#: tens of milliseconds, and a LATERAL can make thousands of calls; a login
#: change is picked up within this window.
GH_TOKEN_TTL_SECONDS = 300

_gh_cache: dict[str, tuple[float, str]] = {}
_gh_lock = threading.Lock()

#: Whether this process may read a token from its own environment on a
#: client's request. True when DuckDB launched the worker for one user over
#: stdio. A worker serving HTTP or a socket answers many clients, and running
#: ``gh`` there would hand the *operator's* identity to whoever asked for it,
#: so the entry points turn this off before serving.
_local_sources_allowed = True


def disallow_local_sources() -> None:
    """Refuse ``token_source`` for the life of this process (shared servers)."""
    global _local_sources_allowed
    _local_sources_allowed = False


def local_sources_allowed() -> bool:
    return _local_sources_allowed


def _gh_hostname(api_base: str) -> str:
    """The host ``gh`` knows a login by: github.com for the public API, else the server."""
    from urllib.parse import urlsplit

    host = urlsplit(api_base).hostname or "github.com"
    return "github.com" if host == "api.github.com" else host


def from_gh_cli(api_base: str) -> Credentials:
    """The token the GitHub CLI is logged in with, for the host being called.

    Raises:
        GitHubAuthError: ``gh`` is missing, not logged in to that host, or
            fails. ``token_source 'gh'`` was asked for explicitly, so falling
            back to anonymous access would be the silent failure ``auth`` exists
            to prevent.
    """
    hostname = _gh_hostname(api_base)
    with _gh_lock:
        cached = _gh_cache.get(hostname)
        if cached and time.monotonic() - cached[0] < GH_TOKEN_TTL_SECONDS:
            return load(cached[1])
    executable = shutil.which("gh")
    if executable is None:
        raise GitHubAuthError(
            "ATTACH asked for token_source 'gh' but the GitHub CLI (gh) is not on this machine's PATH; "
            "install it and run `gh auth login`, or use a github secret instead"
        )
    try:
        result = subprocess.run(
            [executable, "auth", "token", "--hostname", hostname],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise GitHubAuthError(f"`gh auth token` failed: {exc}") from exc
    token = result.stdout.strip()
    if result.returncode != 0 or not token:
        detail = (result.stderr or "no token printed").strip().splitlines()[0][:200]
        raise GitHubAuthError(
            f"ATTACH asked for token_source 'gh' but the GitHub CLI has no login for {hostname} "
            f"({detail}); run `gh auth login --hostname {hostname}`"
        )
    credentials = load(token)
    with _gh_lock:
        _gh_cache[hostname] = (time.monotonic(), credentials.token)
    return credentials


def from_env_vars() -> Credentials:
    """A token from ``GH_TOKEN`` or ``GITHUB_TOKEN``, as ``token_source 'env'`` asks.

    Raises:
        GitHubAuthError: Neither is set — asked for explicitly, so no fallback.
    """
    for name in SOURCE_ENV_VARS:
        token = os.environ.get(name, "").strip()
        if token:
            return load(token)
    raise GitHubAuthError(
        f"ATTACH asked for token_source 'env' but neither {' nor '.join(SOURCE_ENV_VARS)} is set "
        "in the environment DuckDB was started from"
    )


def from_source(source: str, api_base: str) -> Credentials | None:
    """Credentials from the ATTACH ``token_source``, or None when none was named."""
    if source == SOURCE_NONE:
        return None
    if not _local_sources_allowed:
        raise GitHubAuthError(
            f"token_source {source!r} is not available on a shared (HTTP or socket) worker; "
            "send your own token with CREATE SECRET (TYPE github, token '...') instead"
        )
    if source == SOURCE_GH:
        return from_gh_cli(api_base)
    if source == SOURCE_ENV:
        return from_env_vars()
    raise GitHubAuthError(f"unknown token_source {source!r}")


# ---------------------------------------------------------------------------
# Attach-time policy
# ---------------------------------------------------------------------------

#: What ATTACH asked to happen when no credential resolves. The mode travels as
#: the catalog's attach bytes, which the framework hands back to every function.
AUTO = "auto"
REQUIRED = "required"
OFF = "off"
MODES = (AUTO, REQUIRED, OFF)


def encode_attach(mode: str, token_source: str) -> bytes:
    """The ATTACH choices as the catalog's attach bytes."""
    return json.dumps({"auth": mode, "token_source": token_source}, sort_keys=True).encode()


def _attach_options(attach_opaque_data: bytes | None) -> dict[str, str]:
    """Decode attach bytes: JSON now, a bare mode string from before token_source.

    Anything unreadable degrades to the defaults: both options are validated at
    ATTACH, so a surprise here means an older client, and the default behaviour
    beats failing every query.
    """
    if not attach_opaque_data:
        return {}
    text = attach_opaque_data.decode(errors="replace").strip()
    if text.startswith("{"):
        try:
            decoded = json.loads(text)
        except ValueError:
            return {}
        return {k: str(v) for k, v in decoded.items()} if isinstance(decoded, dict) else {}
    return {"auth": text}


def mode_of(attach_opaque_data: bytes | None) -> str:
    """The auth mode ATTACH selected, defaulting to :data:`AUTO`."""
    mode = _attach_options(attach_opaque_data).get("auth", AUTO).strip().lower()
    return mode if mode in MODES else AUTO


def token_source_of(attach_opaque_data: bytes | None) -> str:
    """The token source ATTACH selected, defaulting to none."""
    source = _attach_options(attach_opaque_data).get("token_source", SOURCE_NONE).strip().lower()
    return source if source in SOURCES else SOURCE_NONE


def for_call(
    secrets: dict[str, dict[str, Any]] | None, attach_opaque_data: bytes | None = None
) -> Credentials | None:
    """The credentials to authorize this call with, honouring the ATTACH options.

    In order: a resolved ``github`` secret; the ATTACH ``token_source``; the
    operator's :data:`ENV_TOKEN`; anonymous access. ``auth => 'off'`` skips all
    of them and never authenticates.

    Raises:
        GitHubAuthError: ``auth => 'required'`` was requested and no usable
            credential resolved — otherwise the query silently runs
            anonymously and returns *nothing* for a private repository, because
            GitHub answers an unauthorized read of one with 404, not 403. Also
            raised when an explicitly requested ``token_source`` cannot deliver.
    """
    mode = mode_of(attach_opaque_data)
    if mode == OFF:
        return None
    # Imported here: github_api imports Credentials from this module.
    from vgi_github.github_api import base_url

    api_base = base_url()
    credentials = (
        from_secrets(secrets, api_base)
        or from_source(token_source_of(attach_opaque_data), api_base)
        or from_environment()
    )
    if credentials is None and mode == REQUIRED:
        raise GitHubAuthError(
            f"ATTACH requested auth => 'required' but no {SECRET_TYPE!r} secret resolved; "
            f"CREATE SECRET (TYPE {SECRET_TYPE}, {TOKEN} '...') first, attach with "
            "token_source 'gh' to use your GitHub CLI login, "
            "or attach with auth => 'auto' to allow anonymous access"
        )
    return credentials
