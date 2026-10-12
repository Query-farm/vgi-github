"""Exercise every generated read route and the lossless response/pagination contract."""

from __future__ import annotations

import json
import re

import httpx
import pyarrow as pa
import pytest

from tests.helpers import install
from tests.test_functions import _Out, _Params
from vgi_github import auth, rest
from vgi_github import github_api as api
from vgi_github.auth import Credentials

FUNCTIONS = {f.OPERATION["operation_id"]: f for f in rest.REST_FUNCTIONS}


def run(operation, values=None, *, attach=None, **options):
    function = FUNCTIONS[operation]
    paths = values or {}
    args = function.FunctionArguments(**paths, **options)
    params = _Params(args=args, output_schema=function.FIXED_SCHEMA, attach_opaque_data=attach)
    out = _Out()
    if paths:
        batch = pa.record_batch({name: [value] for name, value in paths.items()})
        function.process(params, None, batch, out)
    else:
        function.process(params, None, out)
    return out.batches[0].to_pylist()


def test_manifest_contains_all_source_reads_and_only_get():
    assert {source["product"]: source["get_operations"] for source in rest.MANIFEST["sources"]} == {
        "api.github.com": 644,
        "ghec": 770,
    }
    assert len(FUNCTIONS) == len(rest.OPERATIONS)
    assert len(FUNCTIONS) >= max(source["get_operations"] for source in rest.MANIFEST["sources"])
    assert {op["method"] for op in rest.OPERATIONS.values()} == {"GET"}
    for source in rest.MANIFEST["sources"]:
        assert (
            sum(source["product"] in op["products"] for op in rest.OPERATIONS.values())
            == source["get_operations"]
        )


@pytest.mark.parametrize("identity", sorted(FUNCTIONS))
def test_every_generated_operation_is_callable_read_only(monkeypatch, identity):
    function = FUNCTIONS[identity]
    op = function.OPERATION
    parameters = {p["name"]: p for p in op["parameters"]}
    values = {
        name: 1 if parameters[path].get("schema", {}).get("type") == "integer" else "sample"
        for name, path in zip(function.INPUT_NAMES, function.PATH_NAMES, strict=True)
    }
    query = {
        p["name"]: 1 if p.get("schema", {}).get("type") == "integer" else "sample"
        for p in op["parameters"]
        if p["in"] == "query" and p.get("required")
    }
    seen = install(monkeypatch, lambda request: httpx.Response(200, json={"nested": {"unknown": [1, None]}}))
    rows = run(identity, values, query=json.dumps(query))
    assert len(seen) == len(rows) == 1
    assert seen[0].method == "GET"
    expected = op["path"]
    for name, path in zip(function.INPUT_NAMES, function.PATH_NAMES, strict=True):
        expected = expected.replace("{" + path + "}", str(values[name]))
    assert seen[0].url.path == expected
    assert json.loads(rows[0]["data"]) == {"nested": {"unknown": [1, None]}}
    assert seen[0].headers["X-GitHub-Api-Version"] == rest.API_VERSION
    metadata = function.get_metadata()
    assert metadata.input_from_args == bool(values)
    assert not metadata.filter_pushdown
    if values:
        assert not function.has_finalize_override()


def test_general_dispatch_and_lateral_provenance(monkeypatch):
    seen = install(monkeypatch, lambda request: httpx.Response(200, json=[{"id": 42}]))
    function = rest.RestFunction
    args = function.FunctionArguments(operation_id="", path_parameters="")
    paths = json.dumps({"owner": "o", "repo": "r", "pull_number": 7})
    batch = pa.record_batch(
        {
            "operation_id": ["pulls/list-reviews", None, "pulls/list-reviews"],
            "path_parameters": [paths, paths, paths],
        }
    )
    out = _Out()
    function.process(_Params(args=args, output_schema=function.FIXED_SCHEMA), None, batch, out)
    assert len(seen) == 1
    assert seen[0].url.path == "/repos/o/r/pulls/7/reviews"
    assert out.parents == [[0, 2]]


@pytest.mark.parametrize(
    "identity", ["pulls/merge", "issues/create", "DELETE /repos/o/r", "https://evil.test"]
)
def test_dispatch_cannot_select_write_or_arbitrary_url(monkeypatch, identity):
    seen = install(monkeypatch, lambda request: pytest.fail("must not send a request"))
    function = rest.RestFunction
    args = function.FunctionArguments(operation_id="", path_parameters="")
    with pytest.raises(api.GitHubInputError, match="Unknown read"):
        function.process(
            _Params(args=args, output_schema=function.FIXED_SCHEMA),
            None,
            pa.record_batch({"operation_id": [identity], "path_parameters": ["{}"]}),
            _Out(),
        )
    assert not seen


def test_query_filters_arrays_and_required_arguments(monkeypatch):
    seen = install(monkeypatch, lambda request: httpx.Response(200, json=[]))
    run("repos/list-for-authenticated-user", query='{"visibility":"private","per_page":100}')
    assert dict(seen[0].url.params) == {"visibility": "private", "per_page": "100"}
    array_operation = next(
        op
        for op in rest.OPERATIONS.values()
        if any(p["in"] == "query" and p.get("schema", {}).get("type") == "array" for p in op["parameters"])
    )
    array = next(p for p in array_operation["parameters"] if p.get("schema", {}).get("type") == "array")
    paths = dict.fromkeys(re.findall(r"\{([^}]+)\}", array_operation["path"]), "x")
    _, pairs = rest.request_arguments(array_operation, paths, {array["name"]: ["one", "two"]})
    assert pairs == [(array["name"], "one"), (array["name"], "two")]
    with pytest.raises(api.GitHubInputError, match="Required query"):
        run("search/code")
    with pytest.raises(api.GitHubInputError, match="Unknown query"):
        run("repos/list-for-authenticated-user", query='{"method":"POST"}')


@pytest.mark.parametrize("path", [".", "..", "a/../b", "a\\..\\b"])
def test_path_traversal_rejected_before_network(monkeypatch, path):
    install(monkeypatch, lambda request: pytest.fail("must not send"))
    with pytest.raises(api.GitHubInputError, match="dot segments"):
        run("repos/get-content", {"owner": "o", "repo": "r", "path": path})


def test_path_escaping_preserves_slashes_spaces_and_query_characters(monkeypatch):
    seen = install(monkeypatch, lambda request: httpx.Response(200, json={}))
    run("repos/get-content", {"owner": "o", "repo": "r", "path": "src/a b?x#z.py"})
    assert seen[0].url.raw_path == b"/repos/o/r/contents/src%2Fa%20b%3Fx%23z.py"


def test_page_walk_preserves_cursor_filters_and_full_payload(monkeypatch):
    link = "https://api.github.com/repositories/42/pulls?state=closed&after=opaque"

    def handler(request):
        if request.url.path.startswith("/repos/"):
            return httpx.Response(200, json=[{"id": 1}], headers={"link": f'<{link}>; rel="next"'})
        assert str(request.url) == link
        return httpx.Response(200, json=[{"id": 2, "new_field": "retained"}])

    seen = install(monkeypatch, handler)
    rows = run("pulls/list", {"owner": "o", "repo": "r"}, query='{"state":"closed"}', max_pages=0)
    assert len(rows) == len(seen) == 2
    assert rows[0]["next_url"] == link and rows[1]["next_url"] is None
    assert json.loads(rows[1]["data"])[0]["new_field"] == "retained"
    seen.clear()
    assert run("pulls/list", {"owner": "o", "repo": "r"})[0]["next_url"] == link
    assert len(seen) == 1


def test_empty_pages_are_followed_and_repeated_links_fail(monkeypatch):
    url = "https://api.github.com/user/repos?page=2"
    seen = install(
        monkeypatch, lambda request: httpx.Response(200, json=[], headers={"link": f'<{url}>; rel="next"'})
    )
    with pytest.raises(api.GitHubError, match="Repeated pagination"):
        run("repos/list-for-authenticated-user", max_pages=0)
    assert len(seen) == 2


def test_pagination_cannot_leave_api_origin(monkeypatch):
    seen = install(
        monkeypatch,
        lambda request: httpx.Response(
            200, json=[], headers={"link": '<https://evil.test/steal>; rel="next"'}
        ),
    )
    with pytest.raises(api.GitHubError, match="outside"):
        run("repos/list-for-authenticated-user", max_pages=0)
    assert len(seen) == 1


def test_pagination_cap_raises_for_complete_walk(monkeypatch):
    monkeypatch.setattr(api, "MAX_PAGES", 2)
    counter = iter(range(2, 10))
    install(
        monkeypatch,
        lambda request: httpx.Response(
            200,
            json=[],
            headers={"link": f'<https://api.github.com/user/repos?page={next(counter)}>; rel="next"'},
        ),
    )
    with pytest.raises(api.GitHubPageLimitError):
        run("repos/list-for-authenticated-user", max_pages=0)


@pytest.mark.parametrize(
    "payload", [{"total_count": 1001, "items": []}, {"incomplete_results": True, "items": []}]
)
def test_complete_search_does_not_claim_truncated_results(monkeypatch, payload):
    install(monkeypatch, lambda request: httpx.Response(200, json=payload))
    with pytest.raises(api.GitHubReportingError):
        run("search/code", query='{"q":"topic"}', max_pages=0)


def test_status_checks_missing_errors_and_binary_bodies(monkeypatch):
    seen = install(monkeypatch, lambda request: httpx.Response(404, json={"message": "Not Found"}))
    values = {"org": "o", "username": "u"}
    with pytest.raises(api.GitHubError):
        run("orgs/check-membership-for-user", values)
    assert run("orgs/check-membership-for-user", values, allow_not_found=True)[0]["status_code"] == 404
    install(monkeypatch, lambda request: httpx.Response(204))
    assert run("orgs/check-membership-for-user", values)[0]["body"] == b""
    install(
        monkeypatch,
        lambda request: httpx.Response(
            200, content=b"PK\x00\xff", headers={"content-type": "application/zip"}
        ),
    )
    row = run(
        "actions/download-artifact", {"owner": "o", "repo": "r", "artifact_id": 1, "archive_format": "zip"}
    )[0]
    assert row["body"] == b"PK\x00\xff" and row["data"] is None
    assert all(request.method == "GET" for request in seen)


def test_binary_etag_revalidation_and_api_version_partition(monkeypatch):
    def handler(request):
        if "if-none-match" in request.headers:
            return httpx.Response(304)
        return httpx.Response(
            200, content=b"diff --git a/a b/a", headers={"etag": '"one"', "content-type": "text/plain"}
        )

    seen = install(monkeypatch, handler)
    values = {"owner": "o", "repo": "r", "pull_number": 1}
    first = run("pulls/get", values, accept="application/vnd.github.diff")
    assert run("pulls/get", values, accept="application/vnd.github.diff") == first
    run("pulls/get", values, accept="application/vnd.github.diff", api_version="2022-11-28")
    assert "if-none-match" not in seen[2].headers


def test_raw_and_native_json_share_etag_without_losing_payload(monkeypatch):
    def handler(request):
        return (
            httpx.Response(304)
            if "if-none-match" in request.headers
            else httpx.Response(200, json={"id": 1}, headers={"etag": '"one"'})
        )

    install(monkeypatch, handler)
    api._get("/repos/o/r", raw=True)
    assert api.lookup("/repos/o/r") == {"id": 1}


@pytest.mark.parametrize("media", ["application/vnd.github.raw+json", "application/json"])
def test_raw_files_with_github_json_media_types_remain_bytes(monkeypatch, media):
    install(
        monkeypatch,
        lambda request: httpx.Response(200, content=b"# a README\n", headers={"content-type": media}),
    )
    row = run(
        "repos/get-content",
        {"owner": "o", "repo": "r", "path": "README.md"},
        accept="application/vnd.github.raw+json",
    )[0]
    assert row["body"] == b"# a README\n" and row["data"] is None


def test_download_without_content_type_is_not_assumed_json(monkeypatch):
    install(monkeypatch, lambda request: httpx.Response(200, content=b"PK\x00\xff"))
    row = run(
        "actions/download-artifact", {"owner": "o", "repo": "r", "artifact_id": 1, "archive_format": "zip"}
    )[0]
    assert row["body"] == b"PK\x00\xff" and row["data"] is None


def test_ndjson_exports_are_preserved_as_bytes(monkeypatch):
    body = b'{"first":1}\n{"second":2}\n'
    install(
        monkeypatch,
        lambda request: httpx.Response(200, content=body, headers={"content-type": "application/x-ndjson"}),
    )
    row = run("repos/get", {"owner": "o", "repo": "r"})[0]
    assert row["body"] == body and row["data"] is None


def test_malformed_json_response_is_not_silently_reinterpreted(monkeypatch):
    install(
        monkeypatch,
        lambda request: httpx.Response(200, content=b"{broken", headers={"content-type": "application/json"}),
    )
    with pytest.raises(api.GitHubError, match="malformed JSON"):
        run("repos/get", {"owner": "o", "repo": "r"})


def test_rest_reporting_refuses_implicit_page_truncation(monkeypatch):
    install(monkeypatch, lambda request: pytest.fail("must not send"))
    with pytest.raises(api.GitHubReportingError, match="max_pages"):
        run("repos/list-for-authenticated-user", attach=auth.encode_attach("auto", "", 0, reporting=True))


def test_binary_redirect_does_not_forward_credentials(monkeypatch):
    def handler(request):
        if request.url.host == "api.github.com":
            assert request.headers["authorization"] == "Bearer secret"
            return httpx.Response(302, headers={"location": "https://downloads.example.test/file.zip"})
        assert "authorization" not in request.headers
        return httpx.Response(200, content=b"archive", headers={"content-type": "application/zip"})

    install(monkeypatch, handler)
    response = api._get("/repos/o/r/zipball/main", raw=True, credentials=Credentials("secret"))
    assert response.body == b"archive"
