"""Result cache policy shared by keyed lookups and streaming searches."""

from vgi.cache_control import CacheControl

from vgi_github import auth
from vgi_github.github_api import STALE_IF_ERROR, CacheHint


def result_cache_control(
    hint: CacheHint,
    cache_ttl: int | None,
    attach_opaque_data: bytes | None,
    *,
    per_value: bool = False,
) -> CacheControl | None:
    """Prefer the call's TTL, then ATTACH; zero delegates to GitHub's policy.

    Only explicit positive TTLs enable per-value memoization for keyed calls.
    Search scans cache whole results and must not request per-value caching.
    """
    if auth.reporting_of(attach_opaque_data):
        return CacheControl(no_store=True)
    ttl = auth.cache_ttl_of(attach_opaque_data) if cache_ttl is None else cache_ttl
    if ttl > 0:
        return CacheControl(ttl=ttl, stale_if_error=STALE_IF_ERROR, per_value=per_value)
    if hint.cacheable:
        return CacheControl(ttl=hint.max_age, stale_if_error=STALE_IF_ERROR)
    return None
