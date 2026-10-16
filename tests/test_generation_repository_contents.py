"""Contents and README routes preserve one path/SHA identity and typed response limits."""

import json
from copy import deepcopy

import httpx
import pytest

from tests.helpers import install
from tests.test_generated_runtime import run
from tests.test_generation_artifacts import ROOT
from tests.test_generation_artifacts import pilot as pilot
from vgi_github.generated_runtime import GeneratedContractError
from vgi_github.github_api import GitHubError


@pytest.fixture
def contents(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "tests/crossfield"))
    import repository_contents_fixture

    return repository_contents_fixture


def rows_for(contract, **arguments):
    entity = next(value for value in contract["functions"] if value["name"] == "repository_contents")
    output = run(entity, {key: [value] for key, value in arguments.items()}, contract=contract)
    return [row for batch in output.batches for row in batch.to_pylist()]


def test_contents_unifies_three_endpoints_without_fabricating_media_fields():
    domain = json.loads((ROOT / "generation/domains/repository_contents.json").read_text())
    assert {s["transport"]["operation_id"] for s in domain["entities"]} == {
        "repos/get-content",
        "repos/get-readme",
        "repos/get-readme-in-directory",
    }
    assert len(domain["functions"]) == 1
    assert domain["functions"][0]["grain"] == ["repository_id", "content_path", "content_sha"]
    assert set(domain["functions"][0]["nullable_route_fields"]) == {
        "entries",
        "symlink_target",
        "submodule_git_url",
    }
    assert len(domain["relationships"]) == 2


def test_readme_and_path_routes_produce_same_canonical_file(pilot, contents, monkeypatch):
    _, contract, _ = pilot
    requests = install(monkeypatch, contents.respond)
    readme = rows_for(contract, repository="contents-fixture/alpha")
    explicit = rows_for(contract, repository="contents-fixture/alpha", content_path="README.md")
    assert readme == explicit
    assert [
        (r["content_path"], r["content_sha"], r["encoded_content"], r["content_encoding"]) for r in readme
    ] == [
        ("README.md", "a" * 40, "aGVsbG8K", "base64"),
    ]
    assert readme[0]["entries"] is None
    assert all(r.url.host == "api.github.com" for r in requests)
    assert any(r.url.path.endswith("/readme") and r.headers["accept"] == "application/json" for r in requests)
    assert any(
        r.url.path.endswith("/contents/README.md")
        and r.headers["accept"] == "application/vnd.github.object+json"
        for r in requests
    )


def test_directory_readme_nested_path_and_ref_are_actual_retrieval_routes(pilot, contents, monkeypatch):
    _, contract, _ = pilot
    requests = install(monkeypatch, contents.respond)
    directory = rows_for(contract, repository="contents-fixture/alpha", readme_directory="docs")
    path = rows_for(contract, repository="contents-fixture/alpha", content_path="docs/README.md")
    assert directory == path
    assert directory[0]["content_path"] == "docs/README.md"
    assert any(b"docs%2FREADME.md" in request.url.raw_path for request in requests)
    old = rows_for(contract, repository="contents-fixture/alpha", content_ref="old")
    assert old[0]["content_sha"] == "f" * 40
    assert old[0]["content_ref"] == "old"
    assert old[0]["encoded_content"] == "b2xk"
    explicit_old = rows_for(
        contract, repository="contents-fixture/alpha", content_path="README.md", content_ref="old"
    )
    directory_old = rows_for(
        contract, repository="contents-fixture/alpha", readme_directory="docs", content_ref="old"
    )
    assert explicit_old == old
    assert (directory_old[0]["content_path"], directory_old[0]["content_sha"]) == (
        "docs/README.md",
        "7" * 40,
    )
    assert directory_old[0]["content_ref"] == "old"
    assert {request.url.path for request in requests if request.url.params.get("ref") == "old"} == {
        "/repos/contents-fixture/alpha/readme",
        "/repos/contents-fixture/alpha/contents/README.md",
        "/repos/contents-fixture/alpha/readme/docs",
    }


def test_root_empty_path_is_real_identity_and_entries_are_typed(pilot, contents, monkeypatch):
    _, contract, _ = pilot
    install(monkeypatch, contents.respond)
    roots = rows_for(contract, organization="contents-fixture", content_path="")
    assert [
        (r["repository_id"], r["content_path"], r["reported_type"], len(r["entries"])) for r in roots
    ] == [
        (6701, "", "dir", 2),
        (6702, "", "dir", 1),
    ]
    assert roots[0]["entries"][0]["path"] == "README.md"
    assert roots[0]["entries"][0]["_links"]["self"].endswith("/contents/README.md")
    assert roots[0]["encoded_content"] is None


def test_large_file_empty_content_and_resolved_symlink_are_not_invented_bytes(pilot, contents, monkeypatch):
    _, contract, _ = pilot
    install(monkeypatch, contents.respond)
    large = rows_for(contract, repository="contents-fixture/alpha", content_path="big.bin")
    assert (large[0]["size"], large[0]["encoded_content"], large[0]["content_encoding"]) == (
        2000000,
        "",
        "none",
    )
    link = rows_for(contract, repository="contents-fixture/alpha", content_path="link.md")
    assert link[0]["reported_type"] == "file"
    assert link[0]["symlink_target"] is None


def test_contents_empty_cohort_and_owner_scope(pilot, contents, monkeypatch):
    _, contract, _ = pilot
    requests = install(monkeypatch, contents.respond)
    assert rows_for(contract, repositories=[], content_path="") == []
    assert requests == []
    rows = rows_for(contract, owner="contents-fixture")
    assert [(r["repository_id"], r["content_path"], r["size"]) for r in rows] == [
        (6701, "README.md", 6),
        (6702, "README.rst", 4),
    ]


@pytest.mark.parametrize(
    "failure", ["missing", "capped", "null_entries", "invalid_entry", "wrong_media_shape"]
)
def test_contents_unknown_or_incomplete_data_fails(pilot, contents, monkeypatch, failure):
    _, contract, _ = pilot

    def handler(request):
        if "/contents/" in request.url.path:
            if failure == "missing":
                return httpx.Response(404, json={"message": "Not Found"})
            payload = deepcopy(contents.ROOTS["alpha"])
            if failure == "capped":
                payload["entries"] = [payload["entries"][0]] * 1000
            if failure == "null_entries":
                payload["entries"] = None
            if failure == "invalid_entry":
                payload["entries"][0]["size"] = True
            if failure == "wrong_media_shape":
                payload = payload["entries"]
            return httpx.Response(200, json=payload)
        return contents.respond(request)

    install(monkeypatch, handler)
    with pytest.raises((GeneratedContractError, GitHubError)):
        rows_for(contract, repository="contents-fixture/alpha", content_path="")


def test_absent_optional_directory_entries_remain_unknown(pilot, contents, monkeypatch):
    _, contract, _ = pilot

    def handler(request):
        if "/contents/" in request.url.path:
            payload = deepcopy(contents.ROOTS["alpha"])
            del payload["entries"]
            return httpx.Response(200, json=payload)
        return contents.respond(request)

    install(monkeypatch, handler)
    assert rows_for(contract, repository="contents-fixture/alpha", content_path="")[0]["entries"] is None
