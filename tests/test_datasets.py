"""Typed dataset contracts: pagination, provenance, filters and read-only transport."""

from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import replace
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


def test_dataset_catalog_contracts():
    for func in ds.DATASET_FUNCTIONS:
        assert func.get_metadata().input_from_args and not func.has_finalize_override()


REPORTING = auth.encode_attach("off", "", reporting=True, operation_timeout_seconds=120)


def project(number=7):
    return {
        "id": 100 + number,
        "number": number,
        "node_id": f"P_{number}",
        "owner": {"login": "o"},
        "title": "Roadmap",
        "state": "open",
        "public": False,
        "is_template": False,
        "created_at": "2026-10-01T09:00:00Z",
        "updated_at": "2026-10-02T10:00:00Z",
        "closed_at": None,
    }


def project_item(identity=1):
    return {
        "id": identity,
        "node_id": f"PI_{identity}",
        "content_type": "Issue",
        "content": {"id": 999, "number": 13, "state": "open", "title": "Implement reporting"},
        "created_at": "2026-10-01T09:00:00Z",
        "updated_at": "2026-10-02T10:00:00Z",
        "archived_at": None,
        "fields": [],
    }


def project_field(identity=1):
    return {
        "id": identity,
        "node_id": f"PF_{identity}",
        "name": "Effort",
        "data_type": "number",
        "created_at": "2026-10-01T09:00:00Z",
        "updated_at": "2026-10-02T10:00:00Z",
        "options": [],
        "configuration": None,
    }


# These responses and independent expected identities cover every typed dataset.
# Repeated project content is deliberate: the item, not its content, is the grain.
REPORTING_CASES = [
    pytest.param(
        ds.DiscussionsFunction,
        ds.DiscussionsArgs(repo="", max_rows=0),
        {"repo": ["o/r"]},
        ("repository", "discussions"),
        [discussion(1), discussion(2)],
        "node_id",
        ["D_1", "D_2"],
        id="discussions",
    ),
    pytest.param(
        ds.DiscussionCommentsFunction,
        ds.DiscussionCommentsArgs(repo="", number=0, max_rows=0),
        {"repo": ["o/r"], "number": [1]},
        ("repository", "discussion", "comments"),
        [comment("C_1"), comment("C_2")],
        "node_id",
        ["C_1", "C_2"],
        id="comments",
    ),
    pytest.param(
        ds.DiscussionRepliesFunction,
        ds.DiscussionRepliesArgs(node_id="", max_rows=0),
        {"node_id": ["C_1"]},
        ("node", "replies"),
        [comment("R_1", "C_1"), comment("R_2", "C_1")],
        "node_id",
        ["R_1", "R_2"],
        id="replies",
    ),
    pytest.param(
        ds.ProjectsFunction,
        ds.ProjectsArgs(owner="", max_rows=0),
        {"owner": ["o"]},
        "/orgs/o/projectsV2",
        [project(7), project(8)],
        "id",
        [107, 108],
        id="projects",
    ),
    pytest.param(
        ds.ProjectItemsFunction,
        ds.ProjectItemsArgs(owner="", number=0, max_rows=0),
        {"owner": ["o"], "number": [7]},
        "/orgs/o/projectsV2/7/items",
        [project_item(1), project_item(2)],
        "id",
        [1, 2],
        id="items",
    ),
    pytest.param(
        ds.ProjectFieldsFunction,
        ds.ProjectFieldsArgs(owner="", number=0, max_rows=0),
        {"owner": ["o"], "number": [7]},
        "/orgs/o/projectsV2/7/fields",
        [project_field(1), project_field(2)],
        "id",
        [1, 2],
        id="fields",
    ),
]
CASE_COLUMNS = "func,args,inputs,path,rows,key,expected"


def reporting_response(path, rows, cursor=None):
    if isinstance(path, tuple):
        data = connection(rows, cursor)
        for segment in reversed(path):
            data = {segment: data}
        return httpx.Response(200, json={"data": data})
    headers = {"Link": f'<{api.base_url()}{path}?after={cursor}>; rel="next"'} if cursor else {}
    return httpx.Response(200, json=rows, headers=headers)


def run_reporting(func, args, inputs, *, output=None, out=None):
    out = out if out is not None else _Out()
    schema = func.on_bind(SimpleNamespace(attach_opaque_data=REPORTING)).output_schema
    func.process(
        _Params(
            args=args, output_schema=output if output is not None else schema, attach_opaque_data=REPORTING
        ),
        None,
        _input(**inputs),
        out,
    )
    return out


@pytest.mark.parametrize(CASE_COLUMNS, REPORTING_CASES)
def test_reporting_walks_all_pages_validates_grain_and_disables_cache(
    monkeypatch, func, args, inputs, path, rows, key, expected
):
    responses = iter(
        [
            reporting_response(path, rows[:1], "next"),
            reporting_response(path, [], "last"),
            reporting_response(path, rows[1:]),
        ]
    )
    seen = install(monkeypatch, lambda request: next(responses))
    # Two identical LATERAL keys retain both parents but fetch only once per batch.
    out = run_reporting(
        func, replace(args, cache_ttl=60), {name: values * 2 for name, values in inputs.items()}
    )
    result = out.batches[0].to_pylist()
    assert [row[key] for row in result] == expected * 2
    assert out.parents == [[0, 0, 1, 1]] and len(seen) == 3
    assert out.cache[0].no_store and out.cache[0].stale_if_error is None
    assert all(row["created_at"].tzinfo is not None for row in result)


@pytest.mark.parametrize(CASE_COLUMNS, REPORTING_CASES)
def test_reporting_accepts_verified_empty_listing(monkeypatch, func, args, inputs, path, rows, key, expected):
    seen = install(monkeypatch, lambda request: reporting_response(path, []))
    out = run_reporting(func, args, inputs)
    assert out.batches[0].num_rows == 0 and len(seen) == 1


@pytest.mark.parametrize(CASE_COLUMNS, REPORTING_CASES)
def test_reporting_rejects_caps_and_null_keys_before_network(
    monkeypatch, func, args, inputs, path, rows, key, expected
):
    seen = install(monkeypatch, lambda request: pytest.fail("must reject before HTTP"))
    with pytest.raises(api.GitHubReportingError, match="max_rows"):
        run_reporting(func, replace(args, max_rows=100), inputs)
    for column in inputs:
        with pytest.raises(api.GitHubReportingError, match="NULL"):
            run_reporting(func, args, {**inputs, column: [None]})
    assert not seen


@pytest.mark.parametrize(CASE_COLUMNS, REPORTING_CASES)
def test_reporting_rejects_duplicate_identity_across_pages_before_emitting(
    monkeypatch, func, args, inputs, path, rows, key, expected
):
    responses = iter([reporting_response(path, rows[:1], "next"), reporting_response(path, rows[:1])])
    install(monkeypatch, lambda request: next(responses))
    out = _Out()
    # Projecting away identity cannot hide malformed source rows.
    output = pa.schema([func.FIXED_SCHEMA.field("created_at")])
    with pytest.raises(api.GitHubReportingError, match="duplicate"):
        run_reporting(func, args, inputs, output=output, out=out)
    assert out.batches == []


@pytest.mark.parametrize(CASE_COLUMNS, REPORTING_CASES)
def test_reporting_requires_valid_identity_and_dates_even_when_projected_away(
    monkeypatch, func, args, inputs, path, rows, key, expected
):
    created = "createdAt" if isinstance(path, tuple) else "created_at"
    updated = "updatedAt" if isinstance(path, tuple) else "updated_at"
    raw_key = "id"  # GraphQL's id maps to node_id; REST id is numeric.
    for change in (
        {raw_key: None},
        {raw_key: True},
        {created: None},
        {updated: None},
        {created: "2026-10-01T09:00:00"},
        {updated: "2026-09-30T00:00:00Z"},
    ):
        install(monkeypatch, lambda request, change=change: reporting_response(path, [{**rows[0], **change}]))
        with pytest.raises(api.GitHubReportingError):
            run_reporting(func, args, inputs, output=pa.schema([func.FIXED_SCHEMA.field(0)]))


@pytest.mark.parametrize(
    "func,required,optional",
    [
        (
            ds.DiscussionsFunction,
            "repo number node_id is_answered comments upvote_count locked created_at updated_at",
            "user_login answer_comment_id answer_chosen_at",
        ),
        (
            ds.DiscussionCommentsFunction,
            "repo discussion_number node_id is_answer replies upvote_count created_at updated_at",
            "user_login reply_to_id",
        ),
        (
            ds.DiscussionRepliesFunction,
            "repo discussion_number node_id reply_to_id is_answer replies upvote_count created_at updated_at",
            "user_login",
        ),
        (
            ds.ProjectsFunction,
            "owner owner_type number id node_id state is_public is_template created_at updated_at",
            "closed_at creator_login",
        ),
        (
            ds.ProjectItemsFunction,
            "owner owner_type project_number id node_id content_type created_at updated_at",
            "content_id content_number title state archived_at",
        ),
        (
            ds.ProjectFieldsFunction,
            "owner owner_type project_number id node_id name data_type created_at updated_at",
            "options_json configuration_json",
        ),
    ],
)
def test_reporting_bind_publishes_validated_contract_without_fetch(monkeypatch, func, required, optional):
    seen = install(monkeypatch, lambda request: pytest.fail("binding must not fetch"))
    schema = func.on_bind(SimpleNamespace(attach_opaque_data=REPORTING)).output_schema
    assert all(not schema.field(name).nullable for name in required.split())
    assert all(schema.field(name).nullable for name in optional.split())
    exploratory = func.on_bind(SimpleNamespace(attach_opaque_data=None)).output_schema
    assert all(exploratory.field(name).nullable for name in required.split())
    assert seen == []


@pytest.mark.parametrize(
    "change,error",
    [
        ({"isAnswered": None}, "boolean"),
        ({"locked": 1}, "boolean"),
        ({"comments": {"totalCount": -1}}, "nonnegative"),
        ({"comments": {}}, "nonnegative"),
        ({"upvoteCount": True}, "nonnegative"),
        ({"isAnswered": True}, "answer ID/time"),
        ({"answer": {"id": "C_1"}}, "answer ID/time"),
        ({"answerChosenAt": "2026-10-02T00:00:00Z"}, "answer ID/time"),
        ({"answer": {}}, "answer id"),
        ({"answer": []}, "object or NULL"),
        ({"isAnswered": True, "answer": {"id": "C_1"}, "answerChosenAt": "2026-09-30T00:00:00Z"}, "duration"),
        ({"repository": {"nameWithOwner": "elsewhere/repo"}}, "mismatched repo"),
    ],
)
def test_reporting_discussion_rejects_invalid_answer_counter_or_population(monkeypatch, change, error):
    install(
        monkeypatch,
        lambda request: reporting_response(("repository", "discussions"), [{**discussion(), **change}]),
    )
    with pytest.raises(api.GitHubReportingError, match=error):
        run_reporting(ds.DiscussionsFunction, ds.DiscussionsArgs(repo="", max_rows=0), {"repo": ["o/r"]})


def test_reporting_answered_discussion_retains_nullable_author_and_answer_duration(monkeypatch):
    row = {
        **discussion(),
        "isAnswered": True,
        "answer": {"id": "C_1"},
        "answerChosenAt": "2026-10-01T11:00:00Z",
    }
    install(monkeypatch, lambda request: reporting_response(("repository", "discussions"), [row]))
    result = (
        run_reporting(ds.DiscussionsFunction, ds.DiscussionsArgs(repo="", max_rows=0), {"repo": ["o/r"]})
        .batches[0]
        .to_pylist()[0]
    )
    assert result["is_answered"] and result["user_login"] is None
    assert (result["answer_chosen_at"] - result["created_at"]).total_seconds() == 7200


@pytest.mark.parametrize(
    "path,data",
    [
        (("repository", "discussions"), {"repository": None}),
        (("repository", "discussion", "comments"), {"repository": {"discussion": None}}),
        (("node", "replies"), {"node": None}),
    ],
)
def test_reporting_missing_graphql_resource_is_not_an_empty_population(monkeypatch, path, data):
    install(monkeypatch, lambda request: httpx.Response(200, json={"data": data}))
    with api.reporting_operation(REPORTING), pytest.raises(api.GitHubReportingError, match="accessible"):
        ds._connection_rows(ds.DISCUSSIONS_QUERY, {}, path, 0, None)


@pytest.mark.parametrize("is_reply", [False, True])
@pytest.mark.parametrize(
    "change,error",
    [
        ({"isAnswer": None}, "boolean"),
        ({"replies": {"totalCount": -1}}, "nonnegative"),
        ({"upvoteCount": 2**63}, "nonnegative"),
        ({"discussion": {"number": 0, "repository": {"nameWithOwner": "o/r"}}}, "discussion_number"),
        ({"replyTo": {"id": "wrong-parent"}}, "reply_to_id"),
    ],
)
def test_reporting_comments_require_valid_counters_and_parent(monkeypatch, is_reply, change, error):
    path = ("node", "replies") if is_reply else ("repository", "discussion", "comments")
    row = {**comment("R_1" if is_reply else "C_1", "C_1" if is_reply else None), **change}
    install(monkeypatch, lambda request: reporting_response(path, [row]))
    func = ds.DiscussionRepliesFunction if is_reply else ds.DiscussionCommentsFunction
    args = (
        ds.DiscussionRepliesArgs(node_id="", max_rows=0)
        if is_reply
        else ds.DiscussionCommentsArgs(repo="", number=0, max_rows=0)
    )
    inputs = {"node_id": ["C_1"]} if is_reply else {"repo": ["o/r"], "number": [1]}
    with pytest.raises(api.GitHubReportingError, match=error):
        run_reporting(func, args, inputs)


@pytest.mark.parametrize(
    "change,error",
    [
        ({"state": None}, "invalid state"),
        ({"public": 1}, "boolean"),
        ({"is_template": None}, "boolean"),
        ({"state": "closed"}, "closed_at"),
        ({"closed_at": "2026-10-02T00:00:00Z"}, "open project"),
        ({"state": "closed", "closed_at": "2026-09-30T00:00:00Z"}, "duration"),
        ({"owner": {"login": "other"}}, "mismatched owner"),
    ],
)
def test_reporting_projects_require_valid_state_and_dates(monkeypatch, change, error):
    install(monkeypatch, lambda request: reporting_response("/orgs/o/projectsV2", [{**project(), **change}]))
    with pytest.raises(api.GitHubReportingError, match=error):
        run_reporting(ds.ProjectsFunction, ds.ProjectsArgs(owner="", max_rows=0), {"owner": ["o"]})


def test_reporting_project_items_allow_declared_inaccessible_content_and_drafts(monkeypatch):
    rows = [
        {**project_item(1), "content": None},
        {
            **project_item(2),
            "content_type": "DraftIssue",
            "content": {"id": 200, "title": "Draft"},
            "archived_at": "2026-10-02T00:00:00Z",
        },
    ]
    install(monkeypatch, lambda request: reporting_response("/orgs/o/projectsV2/7/items", rows))
    result = (
        run_reporting(
            ds.ProjectItemsFunction,
            ds.ProjectItemsArgs(owner="", number=0, max_rows=0),
            {"owner": ["o"], "number": [7]},
        )
        .batches[0]
        .to_pylist()
    )
    assert [row["id"] for row in result] == [1, 2]
    assert result[0]["content_id"] is None and result[0]["title"] is None
    assert result[1]["content_id"] == 200 and result[1]["content_number"] is None
    assert result[1]["state"] is None and result[1]["archived_at"] is not None


@pytest.mark.parametrize(
    "change,error",
    [
        ({"content_type": None}, "content_type"),
        ({"content_type": "Unknown"}, "content_type"),
        ({"content": []}, "object or NULL"),
        ({"content": {}}, "content id"),
        ({"content": {"id": True}}, "content id"),
        ({"content": {"id": 11, "number": None}}, "content number"),
        ({"content": {"id": 11, "number": 12, "state": "unknown"}}, "content state"),
        ({"archived_at": "2026-09-30T00:00:00Z"}, "duration"),
    ],
)
def test_reporting_project_items_do_not_repair_bad_content(monkeypatch, change, error):
    install(
        monkeypatch,
        lambda request: reporting_response("/orgs/o/projectsV2/7/items", [{**project_item(), **change}]),
    )
    with pytest.raises(api.GitHubReportingError, match=error):
        run_reporting(
            ds.ProjectItemsFunction,
            ds.ProjectItemsArgs(owner="", number=0, max_rows=0),
            {"owner": ["o"], "number": [7]},
        )


@pytest.mark.parametrize("column", ["name", "data_type"])
@pytest.mark.parametrize("value", [None, "", "  ", 1])
def test_reporting_project_fields_require_real_names_and_types(monkeypatch, column, value):
    install(
        monkeypatch,
        lambda request: reporting_response(
            "/orgs/o/projectsV2/7/fields", [{**project_field(), column: value}]
        ),
    )
    with pytest.raises(api.GitHubReportingError, match=column):
        run_reporting(
            ds.ProjectFieldsFunction,
            ds.ProjectFieldsArgs(owner="", number=0, max_rows=0),
            {"owner": ["o"], "number": [7]},
        )


@pytest.mark.parametrize(
    "case_index,column",
    [
        (0, "answer"),
        (0, "answerChosenAt"),
        (1, "replyTo"),
        (2, "replyTo"),
        (3, "closed_at"),
        (4, "content"),
        (4, "archived_at"),
    ],
)
def test_reporting_requires_explicit_optional_state_evidence(monkeypatch, case_index, column):
    func, args, inputs, path, rows, _, _ = REPORTING_CASES[case_index].values
    row = deepcopy(rows[0])
    del row[column]
    install(monkeypatch, lambda request: reporting_response(path, [row]))
    with pytest.raises(api.GitHubReportingError, match=f"missing {column}"):
        run_reporting(func, args, inputs)


@pytest.mark.parametrize(CASE_COLUMNS, REPORTING_CASES)
def test_reporting_pagination_failure_never_emits_a_partial_population(
    monkeypatch, func, args, inputs, path, rows, key, expected
):
    failure = (
        httpx.Response(200, json={"data": {"node": None}, "errors": [{"message": "Denied midway"}]})
        if isinstance(path, tuple)
        else httpx.Response(403, json={"message": "Denied midway"})
    )
    responses = iter([reporting_response(path, rows[:1], "next"), failure])
    seen = install(monkeypatch, lambda request: next(responses))
    out = _Out()
    with pytest.raises(api.GitHubError, match="Denied midway"):
        run_reporting(func, args, inputs, out=out)
    assert len(seen) == 2 and out.batches == []


@pytest.mark.parametrize("case_index", [0, 3])
def test_reporting_page_limit_raises_instead_of_returning_truncated_rows(monkeypatch, case_index):
    func, args, inputs, path, rows, _, _ = REPORTING_CASES[case_index].values
    monkeypatch.setattr(api, "MAX_PAGES", 2)
    responses = iter(
        [
            reporting_response(path, rows[:1], "next"),
            reporting_response(path, rows[1:], "last"),
        ]
    )
    seen = install(monkeypatch, lambda request: next(responses))
    out = _Out()
    with pytest.raises(api.GitHubPageLimitError):
        run_reporting(func, args, inputs, out=out)
    assert len(seen) == 2 and out.batches == []


@pytest.mark.parametrize("case_index", [0, 3])
def test_reporting_graphql_and_rest_share_deadline_across_pages(monkeypatch, case_index):
    func, args, inputs, path, rows, _, _ = REPORTING_CASES[case_index].values
    clock = [0.0]
    monkeypatch.setattr(api.time, "monotonic", lambda: clock[0])

    def handler(request):
        expected_timeout = 120.0 if clock[0] == 0 else 59.0
        assert request.extensions["timeout"]["read"] <= expected_timeout
        clock[0] += 61
        return reporting_response(path, rows[:1], "next")

    seen = install(monkeypatch, handler)
    out = _Out()
    with pytest.raises(api.GitHubDeadlineError):
        run_reporting(func, args, inputs, out=out)
    assert len(seen) == 2 and out.batches == []
    assert not api.reporting_enabled()
