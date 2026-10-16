"""HTTP content stays typed bytes/status, without fabricated upstream JSON fields."""

import json
from copy import deepcopy

import httpx
import pytest
from graphql import build_schema, parse, validate

from tests.helpers import install
from tests.test_generated_runtime import run
from tests.test_generation_artifacts import ROOT
from tests.test_generation_artifacts import pilot as pilot
from vgi_github.auth import Credentials
from vgi_github.generated_runtime import GeneratedContractError, _page
from vgi_github.generation.schema import SchemaError, compile_graphql_entity, compile_rest_entity


def download_contract(*, text=False, pending=False):
    responses = {"302": {"description": "Download", "headers": {"Location": {"schema": {"type": "string"}}}}}
    if pending:
        responses["202"] = {"description": "Processing; no content"}
    spec = {
        "paths": {
            "/downloads/{id}": {
                "get": {
                    "operationId": "downloads/get",
                    "responses": responses,
                    "parameters": [
                        {"name": "id", "in": "path", "required": True, "schema": {"type": "integer"}}
                    ],
                }
            }
        }
    }
    fields = ["status_code", "content_type", "byte_length", "pending", "body"]
    if text:
        fields.append("body_text")
    content = {"accept": "application/vnd.github+json", "response_statuses": list(responses)}
    if pending:
        content["pending_statuses"] = ["202"]
    if text:
        content["text_encoding"] = "utf-8"
    entity = {
        "name": "downloads",
        "arguments": [{"name": "id", "type": "BIGINT"}],
        "columns": [{"name": "id", "source_argument": "id"}]
        + [{"name": name, "source_response": name} for name in fields],
        "grain": ["id"],
        "transport": {
            "kind": "rest",
            "operation_id": "downloads/get",
            "path_bindings": {"id": {"argument": "id"}},
            "content": content,
        },
    }
    return spec, entity


def rows(entity, **arguments):
    result = run(entity, {name: [value] for name, value in arguments.items()})
    return [row for batch in result.batches for row in batch.to_pylist()]


def test_binary_download_follows_redirect_without_forwarding_token(monkeypatch):
    spec, entity = download_contract()
    compiled = compile_rest_entity(spec, entity)

    def handler(request):
        assert "per_page" not in request.url.params
        if request.url.host == "api.github.com":
            assert request.headers["authorization"] == "Bearer fixture-secret"
            return httpx.Response(302, headers={"Location": "https://download.example.invalid/file"})
        assert "authorization" not in request.headers
        return httpx.Response(200, content=b"\x00\xff\x80", headers={"Content-Type": "application/zip"})

    requests = install(monkeypatch, handler)
    page = _page(compiled, {"id": 7}, Credentials(token="fixture-secret"), {})
    assert page == [
        {
            "status_code": 200,
            "content_type": "application/zip",
            "byte_length": 3,
            "pending": False,
            "body": b"\x00\xff\x80",
        }
    ]
    assert len(requests) == 2
    assert compiled["columns"][-1]["type"] == "BLOB"
    assert compiled["source"]["representation"] == "http_content"
    assert "properties" not in compiled["source"]["response_schema"]["root"]


@pytest.mark.parametrize(
    "status,body,expected", [(202, b"", None), (200, b"", b""), (200, b"\x00\xff", b"\x00\xff")]
)
def test_pending_empty_and_binary_values_are_distinct(monkeypatch, status, body, expected):
    spec, entity = download_contract(pending=True)
    compiled = compile_rest_entity(spec, entity)
    install(monkeypatch, lambda request: httpx.Response(status, content=body))
    row = rows(compiled, id=8)[0]
    assert row["body"] == expected
    assert row["byte_length"] == len(body)
    assert row["pending"] is (status == 202)


def test_utf8_preserves_newlines_and_rejects_bad_encoding(monkeypatch):
    spec, entity = download_contract(text=True)
    compiled = compile_rest_entity(spec, entity)
    install(monkeypatch, lambda request: httpx.Response(200, content="λ\nDone\n".encode()))
    row = rows(compiled, id=8)[0]
    assert row["body_text"] == "λ\nDone\n"
    assert row["byte_length"] == 8
    install(monkeypatch, lambda request: httpx.Response(200, content=b"\xff"))
    with pytest.raises(GeneratedContractError, match="not valid UTF-8"):
        rows(compiled, id=8)


@pytest.mark.parametrize(
    "status,body,headers,error",
    [
        (202, b"surprise", {}, "pending response"),
        (206, b"partial", {}, "unexpected content response status"),
        (200, b"part", {"Link": '<https://api.github.com/downloads/8?page=2>; rel="next"'}, "pagination"),
        (403, b"denied", {}, "403"),
    ],
)
def test_content_failures_never_become_empty_success(monkeypatch, status, body, headers, error):
    spec, entity = download_contract(pending=True)
    compiled = compile_rest_entity(spec, entity)
    install(monkeypatch, lambda request: httpx.Response(status, content=body, headers=headers))
    with pytest.raises(Exception, match=error):
        rows(compiled, id=8)


def test_content_requires_pinned_media_status_and_declared_redirect():
    spec, entity = download_contract()
    bad = deepcopy(entity)
    bad["transport"]["content"]["accept"] = "application/invented"
    with pytest.raises(SchemaError, match="pinned response"):
        compile_rest_entity(spec, bad)
    bad = deepcopy(entity)
    bad["transport"]["content"]["response_statuses"] = ["299"]
    with pytest.raises(SchemaError, match="missing response status"):
        compile_rest_entity(spec, bad)
    del spec["paths"]["/downloads/{id}"]["get"]["responses"]["302"]["headers"]
    with pytest.raises(SchemaError, match="Location"):
        compile_rest_entity(spec, entity)


ALIAS_SDL = """
    type Query { record: Record! }
    type Record { id: ID!, content: Content! }
    union Content = Issue | PullRequest
    enum IssueState { OPEN CLOSED }
    enum PullRequestState { OPEN MERGED }
    type Issue { id: ID!, state: IssueState! }
    type PullRequest { id: ID!, state: PullRequestState! }
"""


def aliased_entity():
    return compile_graphql_entity(
        ALIAS_SDL,
        {
            "name": "aliased_records",
            "arguments": [],
            "grain": ["id"],
            "columns": [
                {"name": "id", "path": ["id"]},
                {"name": "content_id", "path": ["content", "id"]},
                {
                    "name": "content",
                    "path": ["content"],
                    "selection": {
                        "__typename": True,
                        "... on Issue": {"id": True, "state": True},
                        "... on PullRequest": {"id": True, "state": True},
                    },
                },
            ],
            "transport": {
                "kind": "graphql",
                "field_path": ["record"],
                "field_arguments": {},
                "result_path": [],
                "pagination": {"kind": "none"},
            },
        },
    )


def test_conflicting_graphql_enum_fields_use_real_aliases_and_restore_public_names(monkeypatch):
    compiled = aliased_entity()
    assert validate(build_schema(ALIAS_SDL), parse(compiled["transport"]["document"])) == []

    def response(request):
        query = json.loads(request.content)["query"]
        assert "_vgi_Issue_state: state" in query
        assert "_vgi_PullRequest_state: state" in query
        return httpx.Response(
            200,
            json={
                "data": {
                    "record": {
                        "id": "R1",
                        "content": {
                            "__typename": "Issue",
                            "_vgi_Issue_id": "I1",
                            "_vgi_Issue_state": "CLOSED",
                        },
                    }
                }
            },
        )

    install(monkeypatch, response)
    assert rows(compiled) == [
        {
            "id": "R1",
            "content_id": "I1",
            "content": {"__typename": "Issue", "Issue": {"id": "I1", "state": "CLOSED"}, "PullRequest": None},
        }
    ]


def test_disagreeing_alias_and_canonical_values_are_rejected(monkeypatch):
    compiled = aliased_entity()
    install(
        monkeypatch,
        lambda request: httpx.Response(
            200,
            json={
                "data": {
                    "record": {
                        "id": "R1",
                        "content": {
                            "__typename": "Issue",
                            "_vgi_Issue_id": "I1",
                            "_vgi_Issue_state": "CLOSED",
                            "state": "OPEN",
                        },
                    }
                }
            },
        ),
    )
    with pytest.raises(GeneratedContractError, match="conflicting GraphQL response aliases"):
        rows(compiled)


@pytest.fixture
def content(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "tests/crossfield"))
    import content_fixture

    return content_fixture


def scan(contract, name, **arguments):
    entity = next(value for value in contract["functions"] if value["name"] == name)
    output = run(entity, {key: [value] for key, value in arguments.items()}, contract=contract)
    return [row for batch in output.batches for row in batch.to_pylist()]


def test_parent_pagination_reaches_all_job_logs(pilot, content, monkeypatch):
    _, contract, _ = pilot
    install(monkeypatch, content.respond_all)
    result = scan(contract, "workflow_job_logs", repository="example/alpha", run_id=1001)
    assert [row["job_id"] for row in result] == [2001, 2002, 2003]
    assert [row["body_text"] for row in result] == ["job 2001\n", "job 2002\n", "job 2003\n"]


def test_expired_artifact_fails_after_earlier_valid_download(pilot, content, monkeypatch):
    _, contract, _ = pilot
    requests = install(monkeypatch, content.respond_all)
    with pytest.raises(Exception, match="410"):
        scan(contract, "workflow_artifact_archives", repository="example/alpha", run_id=1001)
    assert any("/artifacts/3001/zip" in str(request.url) for request in requests)
    assert any("/artifacts/3002/zip" in str(request.url) for request in requests)


def test_type_restricted_leaf_does_not_leak_from_whole_union_selection(monkeypatch):
    sdl = """
        type Query { record: Record! }
        type Record { id: ID!, actor: Actor! }
        union Actor = User | Organization
        type User { email: String! }
        type Organization { email: String! }
    """
    compiled = compile_graphql_entity(
        sdl,
        {
            "name": "restricted_email",
            "arguments": [],
            "grain": ["id"],
            "columns": [
                {"name": "id", "path": ["id"]},
                {"name": "user_email", "path": ["actor", "email"], "on_types": ["User"]},
                {
                    "name": "actor",
                    "path": ["actor"],
                    "selection": {
                        "__typename": True,
                        "... on User": {"email": True},
                        "... on Organization": {"email": True},
                    },
                },
            ],
            "transport": {
                "kind": "graphql",
                "field_path": ["record"],
                "field_arguments": {},
                "result_path": [],
                "pagination": {"kind": "none"},
            },
        },
    )
    install(
        monkeypatch,
        lambda request: httpx.Response(
            200,
            json={
                "data": {
                    "record": {
                        "id": "R1",
                        "actor": {
                            "__typename": "Organization",
                            "_vgi_Organization_email": "org@example.invalid",
                        },
                    }
                }
            },
        ),
    )
    row = rows(compiled)[0]
    assert row["user_email"] is None
    assert row["actor"]["Organization"]["email"] == "org@example.invalid"
    install(
        monkeypatch,
        lambda request: httpx.Response(
            200, json={"data": {"record": {"id": "R1", "actor": {"_vgi_User_email": "user@example.invalid"}}}}
        ),
    )
    with pytest.raises(GeneratedContractError, match="parent type"):
        rows(compiled)


def test_bodyless_merge_predicate_preserves_declared_404(monkeypatch):
    spec, entity = download_contract()
    spec["paths"]["/downloads/{id}"]["get"]["responses"] = {
        "204": {"description": "Merged"},
        "404": {"description": "Not merged"},
    }
    entity["transport"]["content"]["response_statuses"] = ["204", "404"]
    compiled = compile_rest_entity(spec, entity)
    install(monkeypatch, lambda request: httpx.Response(404))
    row = rows(compiled, id=8)[0]
    assert row["status_code"] == 404
    assert row["body"] == b"" and row["pending"] is False
    install(monkeypatch, lambda request: httpx.Response(204))
    assert rows(compiled, id=8)[0]["status_code"] == 204


@pytest.mark.parametrize(
    "expected,actual,fails", [(0, [], False), (2, [1, 2], False), (3, [1, 2], True), (1, [1, 2], True)]
)
def test_hydrated_parent_count_detects_collection_truncation(monkeypatch, expected, actual, fails):
    spec = {
        "paths": {
            "/records": {
                "get": {
                    "operationId": "records/list",
                    "responses": {
                        "200": {
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "array",
                                        "items": {
                                            "type": "object",
                                            "properties": {"id": {"type": "integer"}},
                                            "required": ["id"],
                                        },
                                    }
                                }
                            }
                        }
                    },
                }
            }
        }
    }
    entity = {
        "name": "records",
        "arguments": [{"name": "expected_count", "type": "BIGINT"}],
        "columns": [{"name": "id", "path": ["id"]}],
        "grain": ["id"],
        "transport": {
            "kind": "rest",
            "operation_id": "records/list",
            "pagination": {"kind": "link", "expected_count_argument": "expected_count"},
        },
    }
    compiled = compile_rest_entity(spec, entity)
    install(monkeypatch, lambda request: httpx.Response(200, json=[{"id": value} for value in actual]))
    if fails:
        with pytest.raises(GeneratedContractError, match="pagination expected count"):
            rows(compiled, expected_count=expected)
    else:
        assert rows(compiled, expected_count=expected) == [{"id": value} for value in actual]
