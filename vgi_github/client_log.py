"""Route the HTTP layer's activity reports to the DuckDB client.

:func:`vgi_github.github_api.reporting_to` collects rate-limit waits, retries
and budget per call; this turns them into vgi client log batches, which the
DuckDB extension records in ``duckdb_logs`` (type ``VGI``) at the level given.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from vgi_rpc.log import Level


def emitter(out: Any) -> Callable[[str, str], None]:
    """An ``(level, message)`` callback that sends client log batches through ``out``."""

    def emit(level: str, message: str) -> None:
        out.client_log(Level[level], message)

    return emit
