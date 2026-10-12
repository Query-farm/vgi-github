"""The GraphQL POST exception must never execute a mutation."""

import json

import httpx
import pyarrow as pa
import pytest

from tests.helpers import install
from tests.test_functions import _Out, _Params
from vgi_github import github_api as api
from vgi_github.graphql_reads import GraphQLArgs, GraphQLFunction, validate_query


@pytest.mark.parametrize(
    "query",
    [
        'mutation { deleteIssue(input: {issueId: "x"}) { clientMutationId } }',
        "# query { viewer { login } }\nmutation M { x }",
        "query Safe { viewer { login } } mutation Unsafe { x }",
        "subscription { x }",
        "fragment Only on Query { viewer { login } }",
        "type Query { x: String }",
        '{ "query": "{viewer{login}}" }',
    ],
)
def test_nonqueries_never_reach_network(monkeypatch, query):
    seen = install(monkeypatch, lambda request: pytest.fail("must not send"))
    with pytest.raises(api.GitHubInputError):
        api.graphql_query(query, {}, operation_name="Safe")
    assert seen == []


def test_query_named_mutation_and_fragments_are_valid():
    validate_query("query mutation { viewer { ...U } } fragment U on User { login }")
    validate_query('{ search(query: "mutation", type: ISSUE, first: 1) { issueCount } }')


def test_multiple_queries_require_a_selected_existing_name():
    query = "query A { viewer { login } } query B { viewer { name } }"
    with pytest.raises(api.GitHubInputError, match="operation_name"):
        validate_query(query)
    with pytest.raises(api.GitHubInputError, match="not found"):
        validate_query(query, "C")
    validate_query(query, "B")


def test_sql_query_variables_and_lateral_provenance(monkeypatch):
    def handler(request):
        assert request.method == "POST" and request.url.path == "/graphql"
        body = json.loads(request.content)
        assert body["variables"] == {"after": "cursor"}
        assert body["operationName"] == "Read"
        return httpx.Response(200, json={"data": {"viewer": {"login": "octocat"}}})

    seen = install(monkeypatch, handler)
    args = GraphQLArgs(query="", variables="", operation_name="Read")
    query = (
        "query Read($after: String) { viewer { repositories(first:1, after:$after) "
        "{ pageInfo { endCursor } } } }"
    )
    batch = pa.record_batch({"query": [query, None, query], "variables": ['{"after":"cursor"}'] * 3})
    out = _Out()
    GraphQLFunction.process(_Params(args=args, output_schema=GraphQLFunction.FIXED_SCHEMA), None, batch, out)
    assert len(seen) == 1 and out.parents == [[0, 2]]
    assert out.cache[0].no_store


@pytest.mark.parametrize(
    "body",
    [{"errors": [{"message": "denied"}]}, {"data": {"viewer": None}, "errors": [{"message": "partial"}]}, []],
)
def test_graphql_errors_fail_instead_of_returning_partial_success(monkeypatch, body):
    install(monkeypatch, lambda request: httpx.Response(200, json=body))
    with pytest.raises(api.GitHubError, match="GraphQL failed"):
        api.graphql_query("{ viewer { login } }", {})


def test_enterprise_endpoint_and_redirect_rejection(monkeypatch):
    monkeypatch.setenv("GITHUB_API_URL", "https://ghe.example.test/api/v3")
    seen = install(
        monkeypatch, lambda request: httpx.Response(307, headers={"location": "https://evil.test"})
    )
    with pytest.raises(api.GitHubError):
        api.graphql_query("{ viewer { login } }", {})
    assert len(seen) == 1 and str(seen[0].url) == "https://ghe.example.test/api/graphql"


def test_query_retries_transient_failure(monkeypatch):
    responses = iter([httpx.Response(502), httpx.Response(200, json={"data": {}})])
    seen = install(monkeypatch, lambda request: next(responses))
    assert api.graphql_query("{ viewer { login } }", {}) == {"data": {}}
    assert len(seen) == 2
