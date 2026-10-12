"""GraphQL query validation and SQL access; mutations never reach the transport."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Annotated

import pyarrow as pa
from graphql import GraphQLError, parse
from graphql.language import FragmentDefinitionNode, OperationDefinitionNode, OperationType
from vgi.arguments import Arg, SecretLookupEntry
from vgi.cache_control import CacheControl
from vgi.invocation import BindResponse
from vgi.table_in_out_function import RowTransformFunction

from vgi_github import auth
from vgi_github import github_api as api
from vgi_github.client_log import emitter
from vgi_github.meta import docs, examples, field
from vgi_github.rest import json_object
from vgi_github.schemas import batch_from_rows


def validate_query(query: str, operation_name: str | None = None) -> None:
    """Parse the entire document. Only queries and fragment definitions are legal."""
    try:
        document = parse(query, max_tokens=100_000)
    except (GraphQLError, TypeError, RecursionError) as exc:
        raise api.GitHubInputError(f"Invalid GraphQL query: {exc}") from exc
    operations = []
    for definition in document.definitions:
        if isinstance(definition, OperationDefinitionNode):
            if definition.operation is not OperationType.QUERY:
                raise api.GitHubInputError(
                    "Read-only GraphQL accepts queries only; mutations and subscriptions are forbidden"
                )
            operations.append(definition.name.value if definition.name else None)
        elif not isinstance(definition, FragmentDefinitionNode):
            raise api.GitHubInputError("GraphQL schema definitions are not executable queries")
    if not operations or len(operations) != len(set(operations)):
        raise api.GitHubInputError("GraphQL requires uniquely named query operations")
    if operation_name:
        if operation_name not in operations:
            raise api.GitHubInputError(f"GraphQL query operation {operation_name!r} was not found")
    elif len(operations) != 1:
        raise api.GitHubInputError("Specify operation_name for a document with multiple queries")


GRAPHQL_SCHEMA = pa.schema(
    [
        field(
            "data",
            pa.string(),
            "Complete GraphQL response JSON, including data and extensions. Errors fail the call.",
        ),
    ]
)


@dataclass(frozen=True, kw_only=True)
class GraphQLArgs:
    query: Annotated[str, Arg(0, doc="GraphQL query document; mutations and subscriptions are rejected")]
    variables: Annotated[str, Arg(1, doc="JSON variables object; use '{}' when no variables are needed")]
    operation_name: Annotated[
        str, Arg("operation_name", default="", doc="Query name for a multi-query document")
    ] = ""


class GraphQLFunction(RowTransformFunction[GraphQLArgs]):
    """Read any GraphQL query field, including Discussions and Projects."""

    FIXED_SCHEMA = GRAPHQL_SCHEMA

    class Meta:
        name = "graphql"
        description = "Execute read-only GitHub GraphQL queries with JSON variables"
        categories = ["graphql"]
        projection_pushdown = True
        required_secrets = [SecretLookupEntry(secret_type=auth.SECRET_TYPE)]
        tags = docs(
            category="graphql",
            result_schema=GRAPHQL_SCHEMA,
            llm="Read Discussions, Projects and all other GitHub GraphQL query fields. "
            "Pass a query and JSON variables. "
            "Use pageInfo/endCursor and cursor variables to paginate each connection explicitly. "
            "Requires appropriate GitHub credentials. Mutations are rejected before network access.",
            md="Queries use GitHub's POST transport after AST validation. Every operation in a document must "
            "be a query. GraphQL errors fail the call, including partial-data responses. "
            "Results are uncached. "
            "Pagination is explicit because a query may contain multiple independent connections. "
            "Raw GraphQL responses are not validated Crossfield reporting sources.",
            example_queries=examples(
                (
                    "Read the authenticated account",
                    "SELECT data FROM github.api.graphql('{ viewer { login } }', '{}')",
                )
            ),
        )

    @classmethod
    def on_bind(cls, params):
        return BindResponse(output_schema=cls.FIXED_SCHEMA)

    @classmethod
    def process(cls, params, state, batch, out):
        rows, parents, fetched = [], [], {}
        with api.reporting_operation(params.attach_opaque_data), api.reporting_to(emitter(out)):
            credentials = auth.for_call(params.secrets, params.attach_opaque_data)
            for index, (query, variables) in enumerate(
                zip(batch.column("query").to_pylist(), batch.column("variables").to_pylist(), strict=True)
            ):
                api.remaining_time()
                if query is None or variables is None:
                    if api.reporting_enabled():
                        raise api.GitHubReportingError("GraphQL reporting source keys must not be NULL")
                    continue
                key = query, variables
                if key not in fetched:
                    fetched[key] = {
                        "data": json.dumps(
                            api.graphql_query(
                                query,
                                json_object(variables, "variables"),
                                operation_name=params.args.operation_name or None,
                                credentials=credentials,
                            )
                        )
                    }
                rows.append(fetched[key])
                parents.append(index)
            out.emit(
                batch_from_rows(rows, params.output_schema),
                parent_rows=parents,
                cache_control=CacheControl(no_store=True),
            )
