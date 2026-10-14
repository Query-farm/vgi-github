"""Small independent examples for the opt-in, schema-driven entity runtime."""

from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace

import httpx
import pyarrow as pa
import pytest
from vgi.protocol import _resolve_state_type, _TrackingOutputCollector
from vgi.table_function import TableFunctionGenerator
from vgi_rpc.rpc import OutputCollector

from tests.helpers import install
from tests.test_functions import _Out, _Params
from vgi_github import auth
from vgi_github import github_api as api
from vgi_github.generated_runtime import (
    GeneratedContractError,
    GeneratedScanState,
    load_functions,
    make_function,
)
from vgi_github.generation.schema import compile_graphql_entity

REPORTING = auth.encode_attach("off", "", reporting=True, operation_timeout_seconds=120)


def column(name, kind="VARCHAR", *, nullable=False, required=True, **source):
    return {
        "name": name,
        "description": f"Documented {name}",
        "type": kind,
        "nullable": nullable,
        "required": required,
        "schema": {"kind": "scalar", "type": kind, "nullable": nullable},
        **(source or {"path": [name]}),
    }


def reviews_contract():
    columns = [
        column("repository", source_argument="repository"),
        column("pull_request_number", "BIGINT", source_argument="pull_request_number"),
        column("id", "BIGINT"),
        column("state"),
        column("submitted_at", "TIMESTAMP WITH TIME ZONE", nullable=True),
        {
            "name": "reviewer",
            "description": "Review author",
            "type": 'STRUCT("id" BIGINT, "login" VARCHAR, "display_name" VARCHAR)',
            "nullable": True,
            "required": True,
            "path": ["user"],
            "schema": {
                "kind": "struct",
                "nullable": True,
                "fields": [column("id", "BIGINT"), column("login"), column("display_name", required=False)],
            },
        },
        {
            "name": "aliases",
            "description": "Nullable list elements",
            "type": "VARCHAR[]",
            "nullable": False,
            "required": False,
            "path": ["aliases"],
            "schema": {
                "kind": "list",
                "nullable": False,
                "item": {"kind": "scalar", "type": "VARCHAR", "nullable": True},
            },
        },
    ]
    columns[3]["schema"]["enum"] = ["APPROVED", "COMMENTED", "PENDING"]
    return {
        "name": "reviews",
        "description": "Complete review entities",
        "arguments": [
            {"name": "repository", "type": "VARCHAR", "nullable": False, "position": 0},
            {"name": "pull_request_number", "type": "BIGINT", "nullable": False, "position": 1},
        ],
        "columns": columns,
        "grain": ["repository", "pull_request_number", "id"],
        "transport": {
            "kind": "rest",
            "method": "GET",
            "path": "/repos/{owner}/{repo}/pulls/{pull_number}/reviews",
            "path_bindings": {
                "owner": {"argument": "repository", "transform": "repository_owner"},
                "repo": {"argument": "repository", "transform": "repository_name"},
                "pull_number": {"argument": "pull_request_number"},
            },
            "query_bindings": {"per_page": {"literal": 100}},
            "result_path": [],
            "pagination": {"kind": "link"},
        },
        "semantics": {},
    }


def labels_contract():
    return {
        "name": "labels",
        "description": "Complete label entities",
        "arguments": [{"name": "repository", "type": "VARCHAR", "nullable": False, "position": 0}],
        "columns": [
            column("repository", source_argument="repository"),
            column("id"),
            column("name"),
            column("description", nullable=True),
        ],
        "grain": ["repository", "id"],
        "semantics": {},
        "transport": {
            "kind": "graphql",
            "operation_name": "Labels",
            "document": "query Labels($owner:String!,$name:String!,$first:Int!,$cursor:String) {"
            "repository(owner:$owner,name:$name) { labels(first:$first,after:$cursor) {"
            "nodes {id name description} pageInfo {hasNextPage endCursor}}}}",
            "variables": {
                "owner": {"argument": "repository", "transform": "repository_owner"},
                "name": {"argument": "repository", "transform": "repository_name"},
                "first": {"literal": 100},
                "cursor": {"cursor": True},
            },
            "result_path": ["repository", "labels", "nodes"],
            "pagination": {
                "kind": "cursor",
                "cursor_variable": "cursor",
                "page_info_path": ["repository", "labels", "pageInfo"],
            },
        },
    }


def review(identity=1, **changes):
    return {
        "id": identity,
        "state": "APPROVED",
        "submitted_at": "2026-10-01T12:00:00Z",
        "user": {"id": 23, "login": "alice"},
        **changes,
    }


def labels_response(identity="L1", *, cursor=None):
    return {
        "data": {
            "repository": {
                "labels": {
                    "nodes": [{"id": identity, "name": "bug", "description": None}],
                    "pageInfo": {"hasNextPage": cursor is not None, "endCursor": cursor},
                }
            }
        }
    }


def run(entity, inputs, *, out=None, output=None, contract=None, tick=None):
    function = make_function(entity, contract)
    out = out if out is not None else _Out()
    assert all(len(values) == 1 for values in inputs.values()), "producer takes scalar arguments"
    params = _Params(
        SimpleNamespace(**{name: values[0] for name, values in inputs.items()}),
        output if output is not None else function.FIXED_SCHEMA,
        attach_opaque_data=REPORTING,
    )
    state = function.initial_state(params)
    assert _resolve_state_type(function) is GeneratedScanState
    for index in range(1000):
        raw = OutputCollector(params.output_schema, producer_mode=True)
        # The same wrappers used by TableProducerState.produce, not a permissive
        # mock: exactly one data batch per tick, correct cache metadata and finish.
        function.process(params, state, _TrackingOutputCollector(raw))
        if not raw.finished:
            raw.validate()
        if raw.batches:
            data = raw.data_batch
            out.batches.append(data.batch)
            metadata = data.custom_metadata
            out.parents.append(None)
            out.cache.append(SimpleNamespace(no_store=metadata.get(b"vgi.cache.no_store") == b"1"))
        if tick is not None:
            tick(index, state, raw)
        if raw.finished:
            out.finished = True
            break
        # Exercise the real state codec between every tick, as HTTP rehydration does.
        state = GeneratedScanState.deserialize_from_bytes(state.serialize_to_bytes())
    else:
        pytest.fail("producer did not finish within the test's tick bound")
    return out


def test_bind_is_local_and_preserves_nested_nullability_and_comments(monkeypatch):
    install(monkeypatch, lambda request: pytest.fail("metadata must not fetch data"))
    function = make_function(reviews_contract())
    schema = function.on_bind(SimpleNamespace()).output_schema
    assert not schema.field("id").nullable
    assert schema.field("aliases").nullable  # Optional presence differs from explicit NULL.
    assert schema.field("reviewer").type.field("login").nullable is False
    assert schema.field("reviewer").type.field("display_name").nullable is True
    assert schema.field("submitted_at").type == pa.timestamp("us", tz="UTC")
    assert schema.field("id").metadata[b"comment"] == b"Documented id"
    assert not function.get_metadata().input_from_args
    assert issubclass(function, TableFunctionGenerator)


def test_rest_emits_each_page_before_next_request_with_nested_values_and_parents(monkeypatch):
    out = _Out()

    def handle(request):
        assert request.method == "GET" and request.url.path == "/repos/o/r/pulls/7/reviews"
        if "page" not in request.url.params:
            assert request.url.params["per_page"] == "100"
            return httpx.Response(
                200,
                json=[review(1, aliases=["first", None])],
                headers={"Link": f'<{api.base_url()}{request.url.path}?page=2>; rel="next"'},
            )
        assert len(out.batches) == 1  # No unconditional whole-result buffering.
        return httpx.Response(200, json=[review(2, state="PENDING", submitted_at=None, user=None)])

    seen = install(monkeypatch, handle)
    run(reviews_contract(), {"repository": ["o/r"], "pull_request_number": [7]}, out=out)
    first, second = [batch.to_pylist()[0] for batch in out.batches]
    assert first["repository"] == "o/r" and first["pull_request_number"] == 7
    assert first["reviewer"] == {"id": 23, "login": "alice", "display_name": None}
    assert first["aliases"] == ["first", None] and first["submitted_at"].tzinfo is not None
    assert second["reviewer"] is None and second["submitted_at"] is None
    assert out.parents == [None, None] and len(seen) == 2
    assert all(cache.no_store for cache in out.cache)


def test_independent_scalar_scans_preserve_resource_identity(monkeypatch):
    seen = install(monkeypatch, lambda request: httpx.Response(200, json=[review()]))
    out = _Out()
    for repository, number in [("o/r", 7), ("o/r", 7), ("o/other", 8)]:
        run(reviews_contract(), {"repository": [repository], "pull_request_number": [number]}, out=out)
    assert out.parents == [None, None, None] and len(seen) == 3
    assert [batch.to_pylist()[0]["repository"] for batch in out.batches] == ["o/r", "o/r", "o/other"]


def test_graphql_follows_generated_cursor_mapping(monkeypatch):
    import json

    out = _Out()

    def handle(request):
        body = json.loads(request.content)
        assert body["operationName"] == "Labels" and body["variables"]["first"] == 100
        assert body["variables"]["owner"] == "o" and body["variables"]["name"] == "r"
        if body["variables"]["cursor"] is None:
            return httpx.Response(200, json=labels_response(cursor="opaque+=="))
        assert body["variables"]["cursor"] == "opaque+==" and len(out.batches) == 1
        return httpx.Response(200, json=labels_response("L2"))

    seen = install(monkeypatch, handle)
    run(labels_contract(), {"repository": ["o/r"]}, out=out)
    assert [batch.to_pylist()[0]["id"] for batch in out.batches] == ["L1", "L2"]
    assert len(seen) == 2 and out.parents == [None, None]


def test_graphql_input_object_preserves_caller_values_and_cursor_without_interpolation(monkeypatch):
    import json

    sdl = """
        type Query { issues(first: Int, after: String, filterBy: IssueFilter!): Connection! }
        input IssueFilter { createdBy: String!, options: Options! }
        input Options { enabled: Boolean!, note: String }
        type Connection { nodes: [Issue!]!, pageInfo: PageInfo! }
        type Issue { id: ID!, title: String! }
        type PageInfo { hasNextPage: Boolean!, endCursor: String }
    """
    entity = compile_graphql_entity(
        sdl,
        {
            "name": "issues",
            "arguments": [
                {"name": "user", "type": "VARCHAR", "nullable": False},
                {"name": "note", "type": "VARCHAR", "nullable": True},
            ],
            "columns": [{"name": "id", "path": ["id"]}, {"name": "title", "path": ["title"]}],
            "grain": ["id"],
            "transport": {
                "kind": "graphql",
                "field_path": ["issues"],
                "result_path": ["nodes"],
                "pagination": {"kind": "cursor", "page_info_path": ["pageInfo"]},
                "field_arguments": {
                    "issues": {
                        "first": {"literal": 100},
                        "after": {"cursor": True},
                        "filterBy": {
                            "object": {
                                "createdBy": {"argument": "user"},
                                "options": {
                                    "object": {
                                        "enabled": {"literal": True},
                                        "note": {"argument": "note"},
                                    }
                                },
                            }
                        },
                    }
                },
            },
        },
    )
    original = deepcopy(entity)
    caller = 'quoted" login\n{ mutation: forbidden }'
    inputs = {"user": [caller], "note": [None]}
    out = _Out()

    def handle(request):
        body = json.loads(request.content)
        assert body["query"] == original["transport"]["document"]
        assert caller not in body["query"]
        assert body["variables"]["issues_filterBy"] == {
            "createdBy": caller,
            "options": {"enabled": True, "note": None},
        }
        assert body["variables"]["issues_first"] == 100
        cursor = body["variables"]["cursor"]
        if cursor is not None:
            assert cursor == 'opaque"\n+==' and len(out.batches) == 1
        return httpx.Response(
            200,
            json={
                "data": {
                    "issues": {
                        "nodes": [{"id": "I1" if cursor is None else "I2", "title": "A contribution"}],
                        "pageInfo": {
                            "hasNextPage": cursor is None,
                            "endCursor": 'opaque"\n+==' if cursor is None else None,
                        },
                    }
                }
            },
        )

    seen = install(monkeypatch, handle)
    run(entity, inputs, out=out)
    assert [batch.to_pylist()[0]["id"] for batch in out.batches] == ["I1", "I2"]
    assert len(seen) == 2 and out.parents == [None, None]
    assert entity == original and inputs == {"user": [caller], "note": [None]}


@pytest.mark.parametrize(
    "changes,error",
    [
        ({"id": None}, "NULL"),
        ({"id": True}, "BIGINT"),
        ({"id": 2**63}, "BIGINT"),
        ({"id": "1"}, "BIGINT"),
        ({"state": "UNKNOWN"}, "enum"),
        ({"submitted_at": "2026-10-01T12:00:00"}, "TIMESTAMP"),
        ({"user": {"id": 23}}, "missing required"),
        ({"user": {"id": 23, "login": None}}, "NULL"),
        ({"aliases": None}, "NULL"),
        ({"aliases": [False]}, "VARCHAR"),
    ],
)
def test_malformed_values_are_rejected_even_when_projected_away(monkeypatch, changes, error):
    install(monkeypatch, lambda request: httpx.Response(200, json=[review(**changes)]))
    with pytest.raises(GeneratedContractError, match=error):
        run(
            reviews_contract(),
            {"repository": ["o/r"], "pull_request_number": [7]},
            output=pa.schema([pa.field("repository", pa.string())]),
        )


def test_required_nullable_timestamp_must_be_present(monkeypatch):
    payload = review()
    del payload["submitted_at"]
    install(monkeypatch, lambda request: httpx.Response(200, json=[payload]))
    with pytest.raises(GeneratedContractError, match="submitted_at: missing required"):
        run(reviews_contract(), {"repository": ["o/r"], "pull_request_number": [7]})


def test_optional_nonnullable_timestamp_allows_absence_but_rejects_explicit_null(monkeypatch):
    entity = reviews_contract()
    submitted = next(column for column in entity["columns"] if column["name"] == "submitted_at")
    submitted.update(required=False, nullable=False)
    submitted["schema"]["nullable"] = False
    payload = review(state="PENDING")
    del payload["submitted_at"]
    install(monkeypatch, lambda request: httpx.Response(200, json=[payload]))
    result = run(entity, {"repository": ["o/r"], "pull_request_number": [7]})
    assert result.batches[0].to_pylist()[0]["submitted_at"] is None
    install(monkeypatch, lambda request: httpx.Response(200, json=[{**payload, "submitted_at": None}]))
    with pytest.raises(GeneratedContractError, match="submitted_at: NULL"):
        run(entity, {"repository": ["o/r"], "pull_request_number": [7]})


@pytest.mark.parametrize(
    "inputs",
    [
        {"repository": [None], "pull_request_number": [7]},
        {"repository": ["../r"], "pull_request_number": [7]},
        {"repository": ["o/r"], "pull_request_number": [None]},
    ],
)
def test_invalid_arguments_fail_before_transport(monkeypatch, inputs):
    seen = install(monkeypatch, lambda request: pytest.fail("invalid input must not reach HTTP"))
    with pytest.raises((GeneratedContractError, api.GitHubInputError)):
        run(reviews_contract(), inputs)
    assert not seen


def test_duplicate_across_pages_raises_after_previous_page_was_emitted(monkeypatch):
    responses = iter(
        [
            httpx.Response(200, json=[review()], headers={"Link": f'<{api.base_url()}/next>; rel="next"'}),
            httpx.Response(200, json=[review()]),
        ]
    )
    install(monkeypatch, lambda request: next(responses))
    out = _Out()
    with pytest.raises(GeneratedContractError, match="duplicate row identity"):
        run(reviews_contract(), {"repository": ["o/r"], "pull_request_number": [7]}, out=out)
    assert len(out.batches) == 1


@pytest.mark.parametrize(
    "payload,error",
    [
        ({"data": {"repository": None}}, "connection/pageInfo"),
        ({"data": {"repository": {"labels": {"nodes": [], "pageInfo": {}}}}}, "pageInfo"),
        ({"data": {"repository": {"labels": {"nodes": [], "pageInfo": {"hasNextPage": True}}}}}, "cursor"),
        ({"data": {}, "errors": [{"message": "Partial access error"}]}, "Partial access error"),
    ],
)
def test_graphql_missing_malformed_and_partial_responses_raise(monkeypatch, payload, error):
    install(monkeypatch, lambda request: httpx.Response(200, json=payload))
    with pytest.raises((GeneratedContractError, api.GitHubError), match=error):
        run(labels_contract(), {"repository": ["o/r"]})


@pytest.mark.parametrize("kind", ["rest", "graphql"])
def test_generated_pagination_finishes_past_legacy_page_cap(monkeypatch, kind):
    # Curated legacy endpoints still use this cap; generated streams do not.
    monkeypatch.setattr(api, "MAX_PAGES", 1)
    out = _Out()

    def handle(request):
        page = len(out.batches) + 1
        assert page <= 3
        if kind == "graphql":
            return httpx.Response(
                200, json=labels_response(f"L{page}", cursor=f"cursor{page}" if page < 3 else None)
            )
        headers = {"Link": f'<{api.base_url()}/next?page={page + 1}>; rel="next"'} if page < 3 else {}
        return httpx.Response(200, json=[review(page)], headers=headers)

    seen = install(monkeypatch, handle)
    entity = reviews_contract() if kind == "rest" else labels_contract()
    inputs = {"repository": ["o/r"], **({"pull_request_number": [7]} if kind == "rest" else {})}
    run(entity, inputs, out=out)
    assert len(seen) == 3 and out.finished
    assert [batch.to_pylist()[0]["id"] for batch in out.batches] == (
        [1, 2, 3] if kind == "rest" else ["L1", "L2", "L3"]
    )


@pytest.mark.parametrize("kind", ["rest", "graphql"])
def test_repeated_pagination_still_fails_without_page_cap(monkeypatch, kind):
    out = _Out()

    def handle(request):
        identity = len(out.batches) + 1
        if kind == "graphql":
            return httpx.Response(200, json=labels_response(f"L{identity}", cursor="same"))
        return httpx.Response(
            200, json=[review(identity)], headers={"Link": f'<{api.base_url()}/same>; rel="next"'}
        )

    seen = install(monkeypatch, handle)
    entity = reviews_contract() if kind == "rest" else labels_contract()
    inputs = {"repository": ["o/r"], **({"pull_request_number": [7]} if kind == "rest" else {})}
    with pytest.raises(GeneratedContractError, match="repeated pagination"):
        run(entity, inputs, out=out)
    assert len(seen) == 2 and not out.finished


def test_late_provider_error_does_not_turn_emitted_prefix_into_complete_result(monkeypatch):
    responses = iter(
        [
            httpx.Response(200, json=[review(1)], headers={"Link": f'<{api.base_url()}/next>; rel="next"'}),
            httpx.Response(422, json={"message": "Provider cannot complete this selection"}),
        ]
    )
    seen = install(monkeypatch, lambda request: next(responses))
    out = _Out()
    with pytest.raises(api.GitHubError, match="Provider cannot complete"):
        run(reviews_contract(), {"repository": ["o/r"], "pull_request_number": [7]}, out=out)
    assert len(seen) == 2 and not out.finished
    assert [batch.to_pylist()[0]["id"] for batch in out.batches] == [1]


def test_runtime_is_not_dispatched_by_entity_name(monkeypatch):
    entity = deepcopy(reviews_contract())
    entity["name"] = "renamed_review_entities"
    install(monkeypatch, lambda request: httpx.Response(200, json=[review()]))
    out = run(entity, {"repository": ["o/r"], "pull_request_number": [7]})
    assert out.batches[0].to_pylist()[0]["id"] == 1


def test_flattened_nullable_parent_preserves_null_and_rejects_malformed_object(monkeypatch):
    entity = reviews_contract()
    entity["columns"].append(column("author_login", nullable=True, path=["user", "login"]))
    install(monkeypatch, lambda request: httpx.Response(200, json=[review(user=None)]))
    out = run(entity, {"repository": ["o/r"], "pull_request_number": [7]})
    assert out.batches[0].to_pylist()[0]["author_login"] is None
    install(monkeypatch, lambda request: httpx.Response(200, json=[review(user="malformed")]))
    with pytest.raises(GeneratedContractError, match="expected an object"):
        run(entity, {"repository": ["o/r"], "pull_request_number": [7]})


@pytest.mark.parametrize("author", ["alice", "ALICE", "Alice"])
def test_row_assertion_compares_github_logins_case_insensitively(monkeypatch, author):
    entity = reviews_contract()
    entity["arguments"].append({"name": "user", "type": "VARCHAR", "nullable": False, "position": 2})
    entity["columns"].append(column("author_login", nullable=True, path=["user", "login"]))
    entity["policy"] = {
        "row_assertions": [{"column": "author_login", "argument": "user", "comparison": "github_login"}]
    }
    install(monkeypatch, lambda request: httpx.Response(200, json=[review(user={"id": 23, "login": author})]))
    out = run(entity, {"repository": ["o/r"], "pull_request_number": [7], "user": ["alice"]})
    assert out.batches[0].to_pylist()[0]["author_login"] == author


@pytest.mark.parametrize("user", [{"id": 24, "login": "another-user"}, None])
def test_row_assertion_fails_before_emitting_foreign_or_null_author_even_if_projected_away(monkeypatch, user):
    entity = reviews_contract()
    entity["arguments"].append({"name": "user", "type": "VARCHAR", "nullable": False, "position": 2})
    entity["columns"].append(column("author_login", nullable=True, path=["user", "login"]))
    entity["policy"] = {
        "row_assertions": [{"column": "author_login", "argument": "user", "comparison": "github_login"}]
    }
    responses = iter(
        [
            httpx.Response(
                200, json=[review()], headers={"Link": f'<{api.base_url()}/reviews?page=2>; rel="next"'}
            ),
            httpx.Response(200, json=[review(2, user=user)]),
        ]
    )
    install(monkeypatch, lambda request: next(responses))
    out = _Out()
    with pytest.raises(GeneratedContractError, match="row assertion failed: author_login must match user"):
        run(
            entity,
            {"repository": ["o/r"], "pull_request_number": [7], "user": ["alice"]},
            output=pa.schema([]),
            out=out,
        )
    assert len(out.batches) == 1 and out.batches[0].num_rows == 1


def test_null_graphql_entity_is_not_silently_skipped(monkeypatch):
    payload = labels_response()
    payload["data"]["repository"]["labels"]["nodes"] = [None]
    install(monkeypatch, lambda request: httpx.Response(200, json=payload))
    with pytest.raises(GeneratedContractError, match="expected an entity object"):
        run(labels_contract(), {"repository": ["o/r"]})


def test_numeric_schema_retains_finite_numbers_and_rejects_nonfinite_values(monkeypatch):
    entity = reviews_contract()
    entity["columns"].append(column("score", "DOUBLE"))
    install(monkeypatch, lambda request: httpx.Response(200, json=[review(score=1.25)]))
    out = run(entity, {"repository": ["o/r"], "pull_request_number": [7]})
    assert out.batches[0].to_pylist()[0]["score"] == 1.25
    install(
        monkeypatch,
        lambda request: httpx.Response(
            200, content=b'[{"id":1,"state":"PENDING","submitted_at":null,"user":null,"score":NaN}]'
        ),
    )
    with pytest.raises((GeneratedContractError, api.GitHubError)):
        run(entity, {"repository": ["o/r"], "pull_request_number": [7]})


def test_opt_in_worker_preserves_default_catalog_and_attach_policy(monkeypatch):
    install(monkeypatch, lambda request: pytest.fail("metadata must not call the network"))
    from vgi_github.generated_worker import GENERATED_CATALOG, GeneratedGitHubCatalog
    from vgi_github.worker import _GITHUB_CATALOG

    assert [schema.path for schema in _GITHUB_CATALOG.schemas] == [["main"], ["rest"], ["api"]]
    assert [schema.path for schema in GENERATED_CATALOG.schemas][-1] == ["generated"]
    assert sorted(function.Meta.name for function in load_functions()) == sorted(
        [
            "repositories",
            "pull_requests",
            "pull_request_reviews",
            "repository_labels",
            "organizations",
            "users",
            "organization_memberships",
            "teams",
            "team_memberships",
            "authored_pull_requests",
            "authored_issues",
            "authored_discussions",
            "authored_issue_comments",
            "authored_discussion_comments",
            "authored_commit_comments",
        ]
    )
    attached = GeneratedGitHubCatalog().catalog_attach(
        name="github",
        options={"reporting": True, "auth": "off"},
        data_version_spec=None,
        implementation_version=None,
    )
    assert attached.tags["vgi_github_reporting"] == "true"
    assert attached.tags["vgi_github_api_origin"] == api.base_url()
    assert auth.reporting_of(attached.attach_opaque_data)


def connected_contract():
    """A small independent relationship graph, not the generated artifact."""

    def rest_entity(name, columns, path, bindings, *, singleton=False, arguments=()):
        return {
            "name": name,
            "description": name,
            "arguments": [
                {"name": arg, "type": kind, "nullable": False, "position": i}
                for i, (arg, kind) in enumerate(arguments)
            ],
            "columns": columns,
            "grain": [columns[0]["name"]],
            "semantics": {},
            "transport": {
                "kind": "rest",
                "method": "GET",
                "path": path,
                "path_bindings": bindings,
                "query_bindings": {},
                "result_path": [],
                "result_shape": "object" if singleton else "array",
                "pagination": {"kind": "none" if singleton else "link"},
            },
        }

    repository_columns = [
        column("repository_id", "BIGINT", path=["id"]),
        column("repository", path=["full_name"]),
    ]
    repo_paths = {
        "owner": {"argument": "repository", "transform": "repository_owner"},
        "repo": {"argument": "repository", "transform": "repository_name"},
    }
    account = rest_entity(
        "account",
        [column("account_type", path=["type"])],
        "/users/{owner}",
        {"owner": {"argument": "owner"}},
        singleton=True,
        arguments=[("owner", "VARCHAR")],
    )
    repository = rest_entity(
        "repository",
        repository_columns,
        "/repos/{owner}/{repo}",
        repo_paths,
        singleton=True,
        arguments=[("repository", "VARCHAR")],
    )
    org_repositories = rest_entity(
        "organization_repositories",
        repository_columns,
        "/orgs/{owner}/repos",
        {"owner": {"argument": "owner"}},
        arguments=[("owner", "VARCHAR")],
    )
    user_repositories = deepcopy(org_repositories)
    user_repositories["name"] = "user_repositories"
    user_repositories["transport"]["path"] = "/users/{owner}/repos"
    pulls = rest_entity(
        "pulls",
        [
            column("pull_id", "BIGINT", path=["id"]),
            column("number", "BIGINT"),
            column("author", path=["user", "login"]),
            column("created_at", "TIMESTAMP WITH TIME ZONE"),
        ],
        "/repos/{owner}/{repo}/pulls",
        repo_paths,
        arguments=[("repository", "VARCHAR")],
    )
    pulls["transport"]["query_bindings"] = {"state": {"literal": "all"}}
    single_pull = deepcopy(pulls)
    single_pull["name"] = "single_pull"
    single_pull["transport"].update(
        path="/repos/{owner}/{repo}/pulls/{number}", result_shape="object", pagination={"kind": "none"}
    )
    single_pull["transport"]["path_bindings"]["number"] = {"argument": "pull_request_number"}
    single_pull["arguments"].append(
        {"name": "pull_request_number", "type": "BIGINT", "nullable": False, "position": 1}
    )
    scope = {
        "repositories": {
            "exclusive_parameters": ["owner", "repository", "organization"],
            "select": {
                "parameter": "repository",
                "if_present": {
                    "entity": "repository",
                    "arguments": {"repository": {"parameter": "repository"}},
                },
                "if_absent": {
                    "parameter": "organization",
                    "if_present": {
                        "entity": "organization_repositories",
                        "arguments": {"owner": {"parameter": "organization"}},
                    },
                    "if_absent": {
                        "resolve": {"entity": "account", "arguments": {"owner": {"parameter": "owner"}}},
                        "field": "account_type",
                        "cases": {
                            kind: {"entity": entity, "arguments": {"owner": {"parameter": "owner"}}}
                            for kind, entity in [
                                ("Organization", "organization_repositories"),
                                ("User", "user_repositories"),
                            ]
                        },
                    },
                },
            },
        },
        "pull_requests": {
            "requires_parameters": {"pull_request_number": ["repository"]},
            "select": {
                "parameter": "pull_request_number",
                "if_present": {
                    "entity": "single_pull",
                    "arguments": {
                        "repository": {"stage": "repositories", "column": "repository"},
                        "pull_request_number": {"parameter": "pull_request_number"},
                    },
                },
                "if_absent": {
                    "entity": "pulls",
                    "arguments": {
                        "repository": {"stage": "repositories", "column": "repository"},
                    },
                },
            },
        },
    }
    review_entity = reviews_contract()
    outputs = []
    for name, stage, source, kind in [
        ("repository", "repositories", "repository", "VARCHAR"),
        ("repository_id", "repositories", "repository_id", "BIGINT"),
        ("pull_number", "pull_requests", "number", "BIGINT"),
        ("pull_id", "pull_requests", "pull_id", "BIGINT"),
        ("pull_author", "pull_requests", "author", "VARCHAR"),
        ("pull_created_at", "pull_requests", "created_at", "TIMESTAMP WITH TIME ZONE"),
        ("review_id", "reviews", "id", "BIGINT"),
        ("review_state", "reviews", "state", "VARCHAR"),
    ]:
        outputs.append(column(name, kind, source_stage=stage, source_column=source))
    function = {
        "name": "scoped_reviews",
        "description": "Connected reviews",
        "arguments": [
            {
                "name": name,
                "type": kind,
                "nullable": True,
                "default": None,
                "position": i,
                **({"minimum": 1} if kind == "BIGINT" else {"min_length": 1}),
            }
            for i, (name, kind) in enumerate(
                [
                    ("owner", "VARCHAR"),
                    ("repository", "VARCHAR"),
                    ("organization", "VARCHAR"),
                    ("pull_request_number", "BIGINT"),
                ]
            )
        ],
        "columns": outputs,
        "grain": ["repository", "pull_number", "review_id"],
        "traversal": {
            "stages": [
                {"name": "repositories", "scope": "repositories"},
                {"name": "pull_requests", "scope": "pull_requests"},
                {
                    "name": "reviews",
                    "entity": "reviews",
                    "arguments": {
                        "repository": {"stage": "repositories", "column": "repository"},
                        "pull_request_number": {"stage": "pull_requests", "column": "number"},
                    },
                },
            ],
            "output_stage": "reviews",
        },
    }
    return {
        "entities": [
            account,
            repository,
            org_repositories,
            user_repositories,
            pulls,
            single_pull,
            review_entity,
        ],
        "scopes": scope,
        "functions": [function],
    }


def test_connected_scope_streams_depth_first_and_preserves_ancestor_identity(monkeypatch):
    contract = connected_contract()
    out = _Out()
    paths = []

    def handle(request):
        path = request.url.path
        paths.append(path)
        if path == "/users/o":
            return httpx.Response(200, json={"type": "Organization"})
        if path == "/orgs/o/repos":
            return httpx.Response(200, json=[{"id": 10, "full_name": "o/r"}, {"id": 11, "full_name": "o/s"}])
        if path.endswith("/pulls"):
            assert request.url.params["state"] == "all"
            if path.startswith("/repos/o/s"):
                assert sum(batch.num_rows for batch in out.batches) == 2
                return httpx.Response(200, json=[])
            return httpx.Response(
                200,
                json=[
                    {"id": 70, "number": 7, "user": {"login": "alice"}, "created_at": "2026-10-01T12:00:00Z"}
                ],
            )
        assert path == "/repos/o/r/pulls/7/reviews"
        if "page" not in request.url.params:
            return httpx.Response(
                200, json=[review(1)], headers={"Link": f'<{api.base_url()}{path}?page=2>; rel="next"'}
            )
        assert sum(batch.num_rows for batch in out.batches) == 1
        return httpx.Response(200, json=[review(2)])

    install(monkeypatch, handle)
    run(contract["functions"][0], {"owner": ["o"]}, contract=contract, out=out)
    rows = [row for batch in out.batches for row in batch.to_pylist()]
    assert [row["review_id"] for row in rows] == [1, 2]
    assert all(
        row["repository_id"] == 10 and row["pull_id"] == 70 and row["pull_author"] == "alice" for row in rows
    )
    assert all(row["pull_created_at"].isoformat() == "2026-10-01T12:00:00+00:00" for row in rows)
    assert paths == [
        "/users/o",
        "/orgs/o/repos",
        "/repos/o/r/pulls",
        "/repos/o/r/pulls/7/reviews",
        "/repos/o/r/pulls/7/reviews",
        "/repos/o/s/pulls",
    ]
    assert out.finished and len(out.batches) == len(paths)  # One HTTP request per producer tick.


def test_user_scope_uses_public_user_listing_and_handles_empty_population(monkeypatch):
    contract = connected_contract()

    def handle(request):
        if request.url.path == "/users/alice":
            return httpx.Response(200, json={"type": "User"})
        assert request.url.path == "/users/alice/repos"
        return httpx.Response(200, json=[])

    seen = install(monkeypatch, handle)
    out = run(contract["functions"][0], {"owner": ["alice"]}, contract=contract)
    assert len(seen) == 2 and out.finished and all(batch.num_rows == 0 for batch in out.batches)


def test_explicit_organization_scope_skips_account_resolution(monkeypatch):
    contract = connected_contract()

    def handle(request):
        assert request.url.path == "/orgs/example/repos"
        return httpx.Response(200, json=[])

    seen = install(monkeypatch, handle)
    out = run(contract["functions"][0], {"organization": ["example"]}, contract=contract)
    assert len(seen) == 1 and out.finished and [batch.num_rows for batch in out.batches] == [0]


def test_singleton_scope_requires_its_nullable_public_parameter_before_http(monkeypatch):
    contract = connected_contract()
    scope = contract["scopes"]["repositories"]
    scope["exclusive_parameters"] = ["organization"]
    scope["select"] = scope["select"]["if_absent"]["if_present"]
    seen = install(monkeypatch, lambda request: httpx.Response(200, json=[]))
    with pytest.raises(GeneratedContractError, match="exactly one of organization"):
        run(contract["functions"][0], {}, contract=contract)
    assert seen == []
    out = run(contract["functions"][0], {"organization": ["example"]}, contract=contract)
    assert len(seen) == 1 and out.finished


@pytest.mark.parametrize("resolve_again,requests", [(None, 2), (True, 3)])
def test_resolver_cases_support_nested_parameter_choices_and_resolvers(monkeypatch, resolve_again, requests):
    contract = connected_contract()
    function = contract["functions"][0]
    function["arguments"].append(
        {"name": "resolve_again", "type": "BOOLEAN", "nullable": True, "default": None, "position": 4}
    )
    resolver = contract["scopes"]["repositories"]["select"]["if_absent"]["if_absent"]
    leaf = deepcopy(resolver["cases"]["User"])
    resolver["cases"]["User"] = {
        "parameter": "resolve_again",
        "if_present": {
            "resolve": deepcopy(resolver["resolve"]),
            "field": "account_type",
            "cases": {"User": leaf},
        },
        "if_absent": leaf,
    }

    def handle(request):
        if request.url.path == "/users/alice":
            return httpx.Response(200, json={"type": "User"})
        assert request.url.path == "/users/alice/repos"
        return httpx.Response(200, json=[])

    seen = install(monkeypatch, handle)
    out = run(function, {"owner": ["alice"], "resolve_again": [resolve_again]}, contract=contract)
    assert len(seen) == requests and len(out.batches) == requests and out.finished
    assert all(batch.num_rows == 0 for batch in out.batches)


def test_repository_scope_single_pr_avoids_listing_other_prs(monkeypatch):
    contract = connected_contract()

    def handle(request):
        if request.url.path == "/repos/o/r":
            return httpx.Response(200, json={"id": 10, "full_name": "o/r"})
        if request.url.path == "/repos/o/r/pulls/7":
            return httpx.Response(
                200,
                json={
                    "id": 70,
                    "number": 7,
                    "user": {"login": "alice"},
                    "created_at": "2026-10-01T12:00:00Z",
                },
            )
        assert request.url.path == "/repos/o/r/pulls/7/reviews"
        return httpx.Response(200, json=[review()])

    seen = install(monkeypatch, handle)
    out = run(
        contract["functions"][0], {"repository": ["o/r"], "pull_request_number": [7]}, contract=contract
    )
    assert len(seen) == 3 and sum(batch.num_rows for batch in out.batches) == 1


@pytest.mark.parametrize(
    "inputs,error",
    [
        ({}, "exactly one"),
        ({"owner": ["o"], "repository": ["o/r"]}, "exactly one"),
        ({"owner": ["o"], "organization": ["o"]}, "exactly one"),
        ({"repository": ["o/r"], "organization": ["o"]}, "exactly one"),
        ({"owner": [""]}, "empty resource"),
        ({"repository": ["o/r"], "pull_request_number": [0]}, "at least"),
        ({"owner": ["o"], "pull_request_number": [7]}, "requires repository"),
        ({"organization": ["o"], "pull_request_number": [7]}, "requires repository"),
    ],
)
def test_scope_constraints_fail_before_any_http(monkeypatch, inputs, error):
    contract = connected_contract()
    install(monkeypatch, lambda request: pytest.fail("invalid scope must not call HTTP"))
    with pytest.raises(GeneratedContractError, match=error):
        run(contract["functions"][0], inputs, contract=contract)


def test_unknown_account_type_fails_without_guessing_a_listing_route(monkeypatch):
    contract = connected_contract()
    seen = install(monkeypatch, lambda request: httpx.Response(200, json={"type": "Robot"}))
    with pytest.raises(GeneratedContractError, match="Unsupported scope account type"):
        run(contract["functions"][0], {"owner": ["o"]}, contract=contract)
    assert len(seen) == 1


def test_empty_leaf_page_still_obeys_real_producer_collector(monkeypatch):
    responses = iter(
        [
            httpx.Response(200, json=[], headers={"Link": f'<{api.base_url()}/next>; rel="next"'}),
            httpx.Response(200, json=[review()]),
        ]
    )
    install(monkeypatch, lambda request: next(responses))
    out = run(reviews_contract(), {"repository": ["o/r"], "pull_request_number": [7]})
    assert [batch.num_rows for batch in out.batches] == [0, 1] and out.finished


def test_zero_column_projection_preserves_row_count_and_checks_full_payload(monkeypatch):
    install(monkeypatch, lambda request: httpx.Response(200, json=[review(1), review(2)]))
    out = run(reviews_contract(), {"repository": ["o/r"], "pull_request_number": [7]}, output=pa.schema([]))
    assert out.batches[0].num_columns == 0 and out.batches[0].num_rows == 2


def test_deadline_survives_producer_ticks_and_state_serialization(monkeypatch):
    clock = [10.0]
    monkeypatch.setattr(api.time, "monotonic", lambda: clock[0])
    seen = install(
        monkeypatch,
        lambda request: httpx.Response(
            200, json=[review()], headers={"Link": f'<{api.base_url()}/next>; rel="next"'}
        ),
    )

    def tick(index, state, raw):
        assert state.deadline == 130.0
        clock[0] = 131.0

    with pytest.raises(api.GitHubDeadlineError):
        run(reviews_contract(), {"repository": ["o/r"], "pull_request_number": [7]}, tick=tick)
    assert len(seen) == 1


def test_source_and_output_identities_do_not_limit_streamed_cardinality(monkeypatch):
    # Former source and output limits were MAX_PAGES * PER_PAGE. Keep both small
    # so even the first real page exceeds them, then consume the complete stream.
    monkeypatch.setattr(api, "MAX_PAGES", 1)
    monkeypatch.setattr(api, "PER_PAGE", 1)
    responses = iter(
        [
            httpx.Response(
                200, json=[review(1), review(2)], headers={"Link": f'<{api.base_url()}/next>; rel="next"'}
            ),
            httpx.Response(200, json=[review(3)]),
        ]
    )
    seen = install(monkeypatch, lambda request: next(responses))
    out = _Out()
    run(reviews_contract(), {"repository": ["o/r"], "pull_request_number": [7]}, out=out)
    assert [row["id"] for batch in out.batches for row in batch.to_pylist()] == [1, 2, 3]
    assert len(seen) == 2 and out.finished


def test_producer_cursor_retains_keys_but_no_leaf_result_payload(monkeypatch):
    seen = install(monkeypatch, lambda request: httpx.Response(200, json=[review()]))
    import json

    def tick(index, state, raw):
        cursor = json.loads(state.cursor_json)
        if not raw.finished:
            assert cursor["frames"][0]["rows"] == []
            assert "alice" not in state.cursor_json
            assert cursor["seen"] == ['["o/r",7,1]']

    out = run(reviews_contract(), {"repository": ["o/r"], "pull_request_number": [7]}, tick=tick)
    assert out.finished and len(seen) == 1
