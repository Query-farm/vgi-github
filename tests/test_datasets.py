"""Typed dataset contracts: pagination, provenance, filters and read-only transport."""

from __future__ import annotations

import json
from types import SimpleNamespace

import httpx
import pyarrow as pa
import pytest

from tests.helpers import install
from tests.test_functions import _input, _Out, _Params, _run
from vgi_github import auth
from vgi_github import datasets as ds
from vgi_github import github_api as api
from vgi_github.graphql_reads import validate_query


def discussion(number=1):
    return {
        "id": f"D_{number}",
        "number": number,
        "title": f"Question {number}",
        "body": "Question body",
        "author": None,
        "category": {"id": "CAT_1", "name": "Q&A"},
        "isAnswered": False,
        "answer": None,
        "comments": {"totalCount": 3},
        "upvoteCount": 7,
        "locked": False,
        "createdAt": "2026-10-01T09:00:00Z",
        "updatedAt": "2026-10-02T10:00:00Z",
        "answerChosenAt": None,
        "url": f"https://github.com/o/r/discussions/{number}",
        "repository": {"nameWithOwner": "o/r"},
    }


def comment(identity="C_1", parent=None):
    return {
        "id": identity,
        "body": "A response",
        "author": {"login": "alice"},
        "isAnswer": True,
        "replyTo": {"id": parent} if parent else None,
        "replies": {"totalCount": 2},
        "upvoteCount": 4,
        "createdAt": "2026-10-02T11:00:00Z",
        "updatedAt": "2026-10-02T12:00:00Z",
        "url": "https://github.com/o/r/discussions/1#discussioncomment-1",
        "discussion": {"number": 1, "repository": {"nameWithOwner": "o/r"}},
    }


def connection(nodes, cursor=None):
    return {"nodes": nodes, "pageInfo": {"hasNextPage": cursor is not None, "endCursor": cursor}}


def test_discussions_paginate_filter_and_preserve_lateral_rows(monkeypatch):
    def handle(request):
        assert request.method == "POST" and request.url.path == "/graphql"
        body = json.loads(request.content)
        validate_query(body["query"])
        v = body["variables"]
        assert v["owner"] == "o" and v["name"] == "r"
        assert v["answered"] is False and v["category"] == "CAT_1"
        assert v["order"] == {"field": "CREATED_AT", "direction": "ASC"}
        page = connection([discussion(2)]) if v["after"] else connection([discussion()], "cursor+==")
        return httpx.Response(200, json={"data": {"repository": {"discussions": page}}})

    seen = install(monkeypatch, handle)
    out = _run(
        ds.DiscussionsFunction,
        ds.DiscussionsArgs(
            repo="", max_rows=0, answered=False, category_id="CAT_1", sort="created", direction="asc"
        ),
        _input(repo=["o/r", None, "o/r"]),
    )
    rows = out.batches[0].to_pylist()
    assert len(seen) == 2 and out.parents == [[0, 0, 2, 2]]
    assert [r["number"] for r in rows] == [1, 2, 1, 2]
    assert rows[0]["category_name"] == "Q&A" and rows[0]["upvote_count"] == 7
    assert rows[0]["user_login"] is None and rows[0]["answer_comment_id"] is None
    assert rows[0]["is_answered"] is False and rows[0]["created_at"].tzinfo is not None
    assert out.cache == [None]


def test_discussion_cap_shrinks_requests_and_stops_without_next_fetch(monkeypatch):
    def handle(request):
        v = json.loads(request.content)["variables"]
        assert v["first"] == (3 if v["after"] is None else 1)
        page = (
            connection([discussion(1), discussion(2)], "two")
            if not v["after"]
            else connection([discussion(3)], "three")
        )
        return httpx.Response(200, json={"data": {"repository": {"discussions": page}}})

    seen = install(monkeypatch, handle)
    out = _run(ds.DiscussionsFunction, ds.DiscussionsArgs(repo="", max_rows=3), _input(repo=["o/r"]))
    assert out.batches[0].num_rows == 3 and len(seen) == 2


@pytest.mark.parametrize(
    "func,args,inputs,path,node",
    [
        (
            ds.DiscussionCommentsFunction,
            ds.DiscussionCommentsArgs(repo="", number=0),
            {"repo": ["o/r"], "number": [1]},
            ("repository", "discussion", "comments"),
            comment(),
        ),
        (
            ds.DiscussionRepliesFunction,
            ds.DiscussionRepliesArgs(node_id=""),
            {"node_id": ["C_1"]},
            ("node", "replies"),
            comment("R_1", "C_1"),
        ),
    ],
)
def test_comments_and_replies_are_typed_separate_connections(monkeypatch, func, args, inputs, path, node):
    page = connection([node])
    for key in reversed(path):
        page = {key: page}
    seen = install(monkeypatch, lambda r: httpx.Response(200, json={"data": page}))
    out = _run(func, args, _input(**inputs))
    row = out.batches[0].to_pylist()[0]
    assert row["node_id"] == node["id"] and row["repo"] == "o/r"
    assert row["discussion_number"] == 1 and row["user_login"] == "alice"
    assert row["reply_to_id"] == ("C_1" if func is ds.DiscussionRepliesFunction else None)
    assert row["replies"] == 2 and row["is_answer"] is True
    assert len(seen) == 1
    validate_query(json.loads(seen[0].content)["query"])


@pytest.mark.parametrize(
    "page,error",
    [
        ({"nodes": None, "pageInfo": {"hasNextPage": False}}, "Malformed"),
        ({"nodes": [None], "pageInfo": {"hasNextPage": False}}, "Malformed"),
        ({"nodes": [], "pageInfo": {}}, "Malformed"),
        ({"nodes": [], "pageInfo": {"hasNextPage": True, "endCursor": None}}, "cursor"),
        ({"nodes": [], "pageInfo": {"hasNextPage": True, "endCursor": "repeat"}}, "repeated"),
        (None, "Missing connection"),
    ],
)
def test_graphql_refuses_malformed_and_repeated_pages(monkeypatch, page, error):
    install(monkeypatch, lambda r: httpx.Response(200, json={"data": {"repository": {"discussions": page}}}))
    with pytest.raises(api.GitHubError, match=error):
        _run(ds.DiscussionsFunction, ds.DiscussionsArgs(repo="", max_rows=0), _input(repo=["o/r"]))


def test_empty_graphql_page_with_next_cursor_is_followed(monkeypatch):
    responses = [connection([], "next"), connection([discussion()])]
    seen = install(
        monkeypatch,
        lambda r: httpx.Response(200, json={"data": {"repository": {"discussions": responses.pop(0)}}}),
    )
    out = _run(ds.DiscussionsFunction, ds.DiscussionsArgs(repo="", max_rows=0), _input(repo=["o/r"]))
    assert out.batches[0].num_rows == 1 and len(seen) == 2


def test_graphql_page_bound_errors_instead_of_truncating(monkeypatch):
    monkeypatch.setattr(api, "MAX_PAGES", 2)
    pages = [connection([discussion(1)], "a"), connection([discussion(2)], "b")]
    install(
        monkeypatch,
        lambda r: httpx.Response(200, json={"data": {"repository": {"discussions": pages.pop(0)}}}),
    )
    with pytest.raises(api.GitHubPageLimitError):
        _run(ds.DiscussionsFunction, ds.DiscussionsArgs(repo="", max_rows=0), _input(repo=["o/r"]))


def test_missing_resource_and_partial_errors_are_distinct(monkeypatch):
    install(monkeypatch, lambda r: httpx.Response(200, json={"data": {"repository": None}}))
    out = _run(ds.DiscussionsFunction, ds.DiscussionsArgs(repo=""), _input(repo=["o/r"]))
    assert out.batches[0].num_rows == 0
    install(
        monkeypatch,
        lambda r: httpx.Response(
            200,
            json={
                "data": {"repository": {"discussions": connection([discussion()])}},
                "errors": [{"message": "Permission denied"}],
            },
        ),
    )
    with pytest.raises(api.GitHubError, match="Permission denied"):
        _run(ds.DiscussionsFunction, ds.DiscussionsArgs(repo=""), _input(repo=["o/r"]))


def test_disappearing_resource_mid_walk_fails(monkeypatch):
    pages = [{"discussions": connection([discussion()], "next")}, None]
    install(monkeypatch, lambda r: httpx.Response(200, json={"data": {"repository": pages.pop(0)}}))
    with pytest.raises(api.GitHubError, match="disappeared"):
        _run(ds.DiscussionsFunction, ds.DiscussionsArgs(repo="", max_rows=0), _input(repo=["o/r"]))


PROJECT_FUNCTIONS = [
    (ds.ProjectsFunction, ds.ProjectsArgs, {"owner": ["space name"]}, ""),
    (ds.ProjectItemsFunction, ds.ProjectItemsArgs, {"owner": ["space name"], "number": [7]}, "/7/items"),
    (ds.ProjectFieldsFunction, ds.ProjectFieldsArgs, {"owner": ["space name"], "number": [7]}, "/7/fields"),
]


@pytest.mark.parametrize("owner_type,prefix", [("organization", "orgs"), ("user", "users")])
@pytest.mark.parametrize("func,args_type,inputs,suffix", PROJECT_FUNCTIONS)
def test_project_routes_are_rest_gets(monkeypatch, owner_type, prefix, func, args_type, inputs, suffix):
    def handle(request):
        assert request.method == "GET"
        assert request.url.raw_path.split(b"?")[0].decode() == f"/{prefix}/space%20name/projectsV2{suffix}"
        assert request.url.params["per_page"] == "1"
        return httpx.Response(200, json=[{"id": 12, "number": 7}])

    seen = install(monkeypatch, handle)
    args = args_type(**{k: v[0] for k, v in inputs.items()}, owner_type=owner_type, max_rows=1)
    out = _run(func, args, _input(**inputs))
    row = out.batches[0].to_pylist()[0]
    assert row["owner"] == "space name" and row["owner_type"] == owner_type
    assert row["id"] == 12 and len(seen) == 1


def test_project_items_pagination_filters_and_null_content(monkeypatch):
    def handle(request):
        if "after" not in request.url.params:
            assert request.url.params["q"] == "is:open" and request.url.params["fields"] == "12,34"
            return httpx.Response(
                200,
                json=[
                    {
                        "id": 100,
                        "content_type": "Issue",
                        "created_at": "2026-10-01T00:00:00Z",
                        "content": {"id": 200, "number": 3, "title": "Fix", "user": {"login": "alice"}},
                        "fields": [{"id": 12, "value": 42.5}],
                    }
                ],
                headers={
                    "Link": "<https://api.github.com/orgs/o/projectsV2/7/items?"
                    'after=a%2Bb&fields=12,34>; rel="next"'
                },
            )
        assert request.url.params["after"] == "a+b" and request.url.params["fields"] == "12,34"
        return httpx.Response(200, json=[{"id": 101, "content_type": "DraftIssue", "content": None}])

    seen = install(monkeypatch, handle)
    out = _run(
        ds.ProjectItemsFunction,
        ds.ProjectItemsArgs(owner="", number=0, max_rows=0, query="is:open", fields="12,34"),
        _input(owner=["o", "o", None], number=[7, 7, 7]),
    )
    rows = out.batches[0].to_pylist()
    assert len(seen) == 2 and out.parents == [[0, 0, 1, 1]]
    assert rows[0]["id"] == 100 and rows[0]["content_id"] == 200 and rows[0]["content_number"] == 3
    assert rows[0]["title"] == "Fix" and rows[0]["user_login"] == "alice"
    assert json.loads(rows[0]["fields_json"]) == [{"id": 12, "value": 42.5}]
    assert rows[1]["title"] is None and rows[1]["content_number"] is None


def test_projects_and_fields_preserve_metadata(monkeypatch):
    seen = install(
        monkeypatch,
        lambda r: httpx.Response(
            200,
            json=[
                {
                    "id": 1,
                    "number": 7,
                    "owner": {"login": "o"},
                    "creator": {"login": "alice"},
                    "title": "Roadmap",
                    "public": False,
                    "state": "open",
                    "is_template": True,
                    "created_at": "2026-10-01T00:00:00Z",
                }
            ],
        ),
    )
    rows = (
        _run(ds.ProjectsFunction, ds.ProjectsArgs(owner="", query="is:open"), _input(owner=["o"]))
        .batches[0]
        .to_pylist()
    )
    assert seen[0].url.params["q"] == "is:open"
    assert rows[0]["owner"] == "o" and rows[0]["creator_login"] == "alice" and rows[0]["is_public"] is False
    install(
        monkeypatch,
        lambda r: httpx.Response(
            200,
            json=[
                {
                    "id": 12,
                    "name": "Status",
                    "data_type": "single_select",
                    "options": [{"id": "opt", "name": {"raw": "Done"}}],
                    "configuration": None,
                }
            ],
        ),
    )
    row = (
        _run(
            ds.ProjectFieldsFunction,
            ds.ProjectFieldsArgs(owner="", number=0),
            _input(owner=["o"], number=[7]),
        )
        .batches[0]
        .to_pylist()[0]
    )
    assert row["name"] == "Status" and row["project_number"] == 7
    assert json.loads(row["options_json"])[0]["id"] == "opt" and row["configuration_json"] is None


@pytest.mark.parametrize("status", [401, 403, 404])
def test_project_permissions_do_not_look_like_empty_boards(monkeypatch, status):
    install(monkeypatch, lambda r: httpx.Response(status, json={"message": "Access unavailable"}))
    with pytest.raises(api.GitHubError, match="Access unavailable"):
        _run(ds.ProjectsFunction, ds.ProjectsArgs(owner=""), _input(owner=["o"]))


@pytest.mark.parametrize(
    "func,args,inputs",
    [
        (ds.DiscussionsFunction, ds.DiscussionsArgs(repo=""), {"repo": ["../bad"]}),
        (
            ds.DiscussionCommentsFunction,
            ds.DiscussionCommentsArgs(repo="", number=0),
            {"repo": ["o/r"], "number": [0]},
        ),
        (ds.DiscussionRepliesFunction, ds.DiscussionRepliesArgs(node_id=""), {"node_id": [""]}),
        (ds.ProjectsFunction, ds.ProjectsArgs(owner=""), {"owner": [".."]}),
        (ds.ProjectsFunction, ds.ProjectsArgs(owner="", owner_type="team"), {"owner": ["o"]}),
        (ds.ProjectItemsFunction, ds.ProjectItemsArgs(owner="", number=0), {"owner": ["o"], "number": [-1]}),
    ],
)
def test_invalid_keys_fail_before_network(monkeypatch, func, args, inputs):
    seen = install(monkeypatch, lambda r: pytest.fail("Unexpected network request"))
    with pytest.raises(api.GitHubInputError):
        _run(func, args, _input(**inputs))
    assert not seen


def test_projected_output_and_opt_in_graphql_cache(monkeypatch):
    install(
        monkeypatch,
        lambda r: httpx.Response(
            200, json={"data": {"repository": {"discussions": connection([discussion()])}}}
        ),
    )
    out = _Out()
    ds.DiscussionsFunction.process(
        _Params(
            args=ds.DiscussionsArgs(repo="", cache_ttl=60),
            output_schema=pa.schema([ds.DISCUSSION_SCHEMA.field("number")]),
        ),
        None,
        _input(repo=["o/r"]),
        out,
    )
    assert out.batches[0].to_pylist() == [{"number": 1}]
    assert out.cache[0].ttl == 60 and out.cache[0].per_value


@pytest.mark.parametrize("func", ds.DATASET_FUNCTIONS)
def test_reporting_mode_rejects_unapproved_datasets(func):
    with pytest.raises(api.GitHubReportingError, match="not approved"):
        func.on_bind(SimpleNamespace(attach_opaque_data=auth.encode_attach("off", "", reporting=True)))


def test_dataset_catalog_contracts():
    for func in ds.DATASET_FUNCTIONS:
        assert func.get_metadata().input_from_args and not func.has_finalize_override()
