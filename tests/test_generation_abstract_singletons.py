"""Node hydration preserves concrete type while sharing one typed singleton source."""

import httpx
import pytest

from tests.helpers import install
from tests.test_generated_runtime import run
from vgi_github.generated_runtime import GeneratedContractError
from vgi_github.generation.schema import compile_graphql_entity


def subject_source(abstract):
    root = (
        "interface Node { id: ID! }"
        if abstract == "interface"
        else "union Node = Issue | PullRequest | Account"
    )
    implements = " implements Node" if abstract == "interface" else ""
    sdl = (
        root
        + " type Query { node: Node }"
        + " ".join(
            f"type {name}{implements} {{ id: ID! "
            + ("number: Int!" if name != "Account" else "login: String!")
            + " }"
            for name in ["Issue", "PullRequest", "Account"]
        )
    )
    return compile_graphql_entity(
        sdl,
        {
            "name": "subjects",
            "arguments": [],
            "grain": ["id"],
            "columns": [
                {"name": "id", "path": ["id"], "on_types": ["Issue", "PullRequest"]},
                {"name": "kind", "path": ["__typename"]},
                {"name": "number", "path": ["number"], "on_types": ["Issue", "PullRequest"]},
            ],
            "transport": {
                "kind": "graphql",
                "field_path": ["node"],
                "field_arguments": {},
                "result_path": [],
                "pagination": {"kind": "none"},
            },
            "policy": {"require_one_row": True, "required_non_null_fields": ["id", "number"]},
        },
    )


@pytest.mark.parametrize("abstract", ["interface", "union"])
@pytest.mark.parametrize("kind", ["Issue", "PullRequest"])
def test_abstract_singletons_emit_declared_concrete_identity(monkeypatch, abstract, kind):
    source = subject_source(abstract)
    aliases = source["transport"].get("response_aliases", {})
    record = {"__typename": kind, "id": "N1", "number": 17}
    record.update({wire: record[name] for wire, name in aliases.items()})
    install(monkeypatch, lambda request: httpx.Response(200, json={"data": {"node": record}}))
    result = run(source, {})
    assert [row for batch in result.batches for row in batch.to_pylist()] == [
        {"id": "N1", "kind": kind, "number": 17}
    ]


@pytest.mark.parametrize("abstract", ["interface", "union"])
@pytest.mark.parametrize(
    "record",
    [
        None,
        {},
        {"id": "N1", "number": 17},
        {"__typename": "Future", "id": "N1", "number": 17},
        {"__typename": "Account", "id": "N1", "login": "alice"},
    ],
)
def test_unknown_or_inapplicable_hydration_never_becomes_a_valid_subject(monkeypatch, abstract, record):
    source = subject_source(abstract)
    install(monkeypatch, lambda request: httpx.Response(200, json={"data": {"node": record}}))
    with pytest.raises(GeneratedContractError):
        run(source, {})


def connection_source(policy="error", *, nullable=True):
    suffix = "" if nullable else "!"
    sdl = (
        f"type Query {{ parent: Parent{suffix} }} "
        f"type Parent {{ children(after: String): Connection{suffix} }} "
        "type Connection { nodes: [Child!]! pageInfo: PageInfo! } "
        "type Child { id: ID! } "
        "type PageInfo { hasNextPage: Boolean! endCursor: String }"
    )
    return compile_graphql_entity(
        sdl,
        {
            "name": "children",
            "arguments": [],
            "grain": ["id"],
            "columns": [{"name": "id", "path": ["id"]}],
            "transport": {
                "kind": "graphql",
                "field_path": ["parent", "children"],
                "field_arguments": {"children": {"after": {"cursor": True}}},
                "result_path": ["nodes"],
                "pagination": {"kind": "cursor", "page_info_path": ["pageInfo"]},
                **({"nullable_path_policy": policy} if policy is not None else {}),
            },
        },
    )


@pytest.mark.parametrize("data", [{"parent": None}, {"parent": {"children": None}}])
def test_required_graphql_connection_distinguishes_unavailable_from_empty(monkeypatch, data):
    install(monkeypatch, lambda request: httpx.Response(200, json={"data": data}))
    with pytest.raises(GeneratedContractError, match="required GraphQL traversal returned NULL"):
        run(connection_source(), {})
    # Ordinary optional discovery retains its existing empty-population behavior.
    assert sum(batch.num_rows for batch in run(connection_source(None), {}).batches) == 0


def test_required_graphql_connection_keeps_empty_pages_and_following_cursor(monkeypatch):
    calls = []

    def respond(request):
        import json

        variables = json.loads(request.content)["variables"]
        calls.append(variables["cursor"])
        page = {"nodes": [], "pageInfo": {"hasNextPage": True, "endCursor": "next"}}
        if variables["cursor"] == "next":
            page = {"nodes": [{"id": "C2"}], "pageInfo": {"hasNextPage": False, "endCursor": None}}
        return httpx.Response(200, json={"data": {"parent": {"children": page}}})

    install(monkeypatch, respond)
    out = run(connection_source(), {})
    assert [row for batch in out.batches for row in batch.to_pylist()] == [{"id": "C2"}]
    assert calls == [None, "next"]


@pytest.mark.parametrize("policy,nullable", [("empty", True), (True, True), ("error", False)])
def test_nullable_traversal_policy_is_explicit_and_schema_checked(policy, nullable):
    with pytest.raises(ValueError, match="nullable_path_policy requires error"):
        connection_source(policy, nullable=nullable)
