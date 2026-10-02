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
import os
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
# Attach-time policy
# ---------------------------------------------------------------------------

#: What ATTACH asked to happen when no credential resolves. The mode travels as
#: the catalog's attach bytes, which the framework hands back to every function.
AUTO = "auto"
REQUIRED = "required"
OFF = "off"
MODES = (AUTO, REQUIRED, OFF)


def mode_of(attach_opaque_data: bytes | None) -> str:
    """The auth mode ATTACH selected, defaulting to :data:`AUTO`.

    Anything unrecognised reads as ``auto``: the mode is validated at ATTACH,
    so a surprise here means an older client, and degrading to the default
    behaviour beats failing every query.
    """
    if not attach_opaque_data:
        return AUTO
    mode = attach_opaque_data.decode(errors="replace").strip().lower()
    return mode if mode in MODES else AUTO


def for_call(
    secrets: dict[str, dict[str, Any]] | None, attach_opaque_data: bytes | None = None
) -> Credentials | None:
    """The credentials to authorize this call with, honouring the ATTACH auth mode.

    A resolved ``github`` secret wins; failing that, the operator's
    :data:`ENV_TOKEN`; failing that, anonymous access. ``auth => 'off'`` skips
    both and never authenticates.

    Raises:
        GitHubAuthError: ``auth => 'required'`` was requested and no usable
            credential resolved. Failing here is the point of that mode —
            otherwise the query silently runs anonymously, cannot see private
            repositories, and returns *nothing* for them rather than an error,
            because GitHub answers an unauthorized read of a private repository
            with 404, not 403.
    """
    mode = mode_of(attach_opaque_data)
    if mode == OFF:
        return None
    # Imported here: github_api imports Credentials from this module.
    from vgi_github.github_api import base_url

    credentials = from_secrets(secrets, base_url()) or from_environment()
    if credentials is None and mode == REQUIRED:
        raise GitHubAuthError(
            f"ATTACH requested auth => 'required' but no {SECRET_TYPE!r} secret resolved; "
            f"CREATE SECRET (TYPE {SECRET_TYPE}, {TOKEN} '...') first, "
            "or attach with auth => 'auto' to allow anonymous access"
        )
    return credentials
