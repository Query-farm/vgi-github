"""The ``rate_limit`` table: how much API budget is left, and whose it is.

The one unkeyed, argument-free object in the catalog, so it is a real table
rather than a function. It is also the quickest way to confirm a token was
picked up: an authenticated ``core`` limit is 5,000 an hour, an anonymous one
60. GitHub does not count calls to ``/rate_limit`` against any budget.
"""

from __future__ import annotations

from typing import ClassVar

import pyarrow as pa
from vgi.arguments import SecretLookupEntry
from vgi.invocation import BindResponse
from vgi.metadata import FunctionExample
from vgi.table_function import BindParams, ProcessParams, TableFunctionGenerator, init_single_worker
from vgi_rpc.rpc import OutputCollector

from vgi_github import auth
from vgi_github import github_api as api
from vgi_github.meta import docs, examples
from vgi_github.schemas import RATE_LIMIT_SCHEMA, batch_from_rows, flatten_rate_limit


@init_single_worker
class RateLimitFunction(TableFunctionGenerator[None, None]):
    """Current rate-limit budgets — the scan behind the ``rate_limit`` table."""

    FIXED_SCHEMA: ClassVar[pa.Schema] = RATE_LIMIT_SCHEMA

    class Meta:
        name = "all_rate_limit"
        description = "GitHub API rate-limit budgets (the scan backing the `rate_limit` table)"
        categories = ["reference"]
        required_secrets = [SecretLookupEntry(secret_type=auth.SECRET_TYPE)]
        projection_pushdown = True
        tags = docs(
            category="reference",
            result_schema=RATE_LIMIT_SCHEMA,
            llm=(
                "How many GitHub API requests remain in each budget and when it resets. Prefer the "
                "`rate_limit` table, which scans this. Check it before a large LATERAL, or to "
                "confirm a token is in use (core limit 5,000 with one, 60 without). Free: GitHub "
                "does not charge for reading it."
            ),
            md=(
                "One row per budget GitHub tracks.\n\n"
                "### Prefer the table\n\n"
                "The `rate_limit` catalog table is backed by this function and returns the same "
                "rows; query the table.\n\n"
                "### The budgets that matter\n\n"
                "`core` (hourly) covers every function here except `search_repositories()` and "
                "`search_issues()`, which draw on `search` — a per-MINUTE window of 30 with a "
                "token, 10 without. `reset_at` is a UTC instant. The column is `request_limit` "
                "rather than GitHub's `limit` because LIMIT is an SQL keyword. Other resources "
                "(graphql, ...) are for APIs this worker does not call and can be ignored."
            ),
            example_queries=examples(
                (
                    "Remaining core and search budget",
                    "SELECT resource, remaining, request_limit, reset_at FROM github.main.all_rate_limit() "
                    "WHERE resource IN ('core', 'search')",
                ),
            ),
        )
        examples = [
            FunctionExample(
                sql=(
                    "SELECT resource, remaining, request_limit, reset_at FROM github.main.all_rate_limit() "
                    "WHERE resource IN ('core', 'search')"
                ),
                description="Remaining core and search budget",
            ),
        ]

    @classmethod
    def on_bind(cls, params: BindParams[None]) -> BindResponse:
        return BindResponse(output_schema=cls.FIXED_SCHEMA)

    @classmethod
    def process(cls, params: ProcessParams[None], state: None, out: OutputCollector) -> None:
        """Fetch the budgets. Never cached: the point is to see them move."""
        credentials = auth.for_call(params.secrets, params.attach_opaque_data)
        payload = api.lookup("/rate_limit", credentials=credentials)
        rows = flatten_rate_limit(payload, authenticated=credentials is not None)
        out.emit(batch_from_rows(rows, params.output_schema))
        out.finish()


REFERENCE_FUNCTIONS: list[type] = [RateLimitFunction]
