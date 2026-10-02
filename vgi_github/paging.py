"""Link-header paging as VGI scan state.

Walking every page inside one call is the obvious implementation of a search
scan and the wrong one: DuckDB would see no rows until the last page arrived, a
``LIMIT 10`` would still pay for ten pages of the 30-a-minute search budget, and
a scan blocked inside its first batch cannot be cancelled.

A ``TableFunctionGenerator`` carries state between ``process()`` ticks, so the
``next`` link lives in that state and each tick fetches exactly one page and
emits exactly one batch. DuckDB sees rows immediately, a ``LIMIT`` stops the
walk early, and cancellation lands between ticks.

The trade-off: a stateful scan cannot be the inner side of a correlated
``LATERAL``. That is why only the *search* endpoints are scans here — they are
the natural drivers of a query, not lookups into it. Everything keyed by a
repository or a user is blended instead (see :mod:`vgi_github.functions`) and
bounds its walk with ``max_rows``.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from vgi.cache_control import CacheControl
from vgi.table_function import ProcessParams
from vgi_rpc import ArrowSerializableDataclass
from vgi_rpc.rpc import OutputCollector

from vgi_github import auth
from vgi_github import github_api as api
from vgi_github.github_api import PER_PAGE, SEARCH_RESULT_CAP, STALE_IF_ERROR, CacheHint
from vgi_github.schemas import batch_from_rows


@dataclass(kw_only=True)
class PagedScanState(ArrowSerializableDataclass):
    """Where a Link-paged scan has got to.

    ``next_url`` is GitHub's ``rel="next"`` link; empty means "not started",
    which the link alone cannot tell apart from "finished" — hence ``done``.
    ``fetched`` counts rows seen, because search stops serving at 1,000 and
    answers the page beyond with a 422 rather than an empty page.
    """

    next_url: str = ""
    done: bool = False
    fetched: int = 0


def emit_search_page(
    params: ProcessParams[Any],
    state: PagedScanState,
    out: OutputCollector,
    *,
    path: str,
    query: dict[str, Any],
    flatten: Callable[[dict[str, Any]], dict[str, Any]],
) -> None:
    """Fetch one page of search results into one batch, and record where to resume.

    The query is sent on the first page only; every later page follows the
    ``next`` link GitHub minted for it, which already encodes the query. That
    also means a pushed filter refreshed between ticks cannot change the query
    mid-walk — the link is the query.
    """
    if state.done:
        out.finish()
        return
    hint = CacheHint()
    rows, next_url = api.page(
        state.next_url or path,
        None if state.next_url else {**query, "per_page": PER_PAGE},
        key="items",
        hint=hint,
        credentials=auth.for_call(params.secrets, params.attach_opaque_data),
    )
    state.fetched += len(rows)
    state.next_url = next_url or ""
    state.done = next_url is None or state.fetched >= SEARCH_RESULT_CAP
    cache_control = CacheControl(ttl=hint.max_age, stale_if_error=STALE_IF_ERROR) if hint.cacheable else None
    out.emit(
        batch_from_rows([flatten(row) for row in rows], params.output_schema), cache_control=cache_control
    )
