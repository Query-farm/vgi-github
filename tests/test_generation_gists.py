"""Gist population selectors preserve canonical identities and typed child snapshots."""

import json
from copy import deepcopy
from datetime import UTC, datetime

import httpx
import pytest

from tests.helpers import install
from tests.test_generated_runtime import run
from tests.test_generation_artifacts import ROOT
from tests.test_generation_artifacts import pilot as pilot
from vgi_github.generated_runtime import GeneratedContractError
from vgi_github.github_api import GitHubError


@pytest.fixture
def gists(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "tests/crossfield"))
    import gists_fixture

    return gists_fixture


def rows_for(contract, name, **arguments):
    entity = next(value for value in contract["functions"] if value["name"] == name)
    output = run(entity, {key: [value] for key, value in arguments.items()}, contract=contract)
    return [row for batch in output.batches for row in batch.to_pylist()]


def test_gists_select_every_read_operation_and_keep_one_current_entity():
    domain = json.loads((ROOT / "generation/domains/gists.json").read_text())
    assert {row["transport"]["operation_id"] for row in domain["entities"]} == {
        "gists/list",
        "gists/list-public",
        "gists/list-starred",
        "gists/list-for-user",
        "gists/get",
        "gists/list-forks",
        "gists/list-comments",
        "gists/get-comment",
        "gists/list-commits",
        "gists/get-revision",
        "gists/check-is-starred",
        "users/get-authenticated",
    }
    assert {row["name"] for row in domain["functions"]} == {
        "gists",
        "gist_comments",
        "gist_revisions",
        "gist_files",
        "gist_star_observations",
    }
    assert len(domain["relationships"]) == 9


@pytest.mark.parametrize(
    "arguments,expected,endpoint",
    [
        ({}, ["gist-a", "gist-b"], "/gists"),
        ({"gist_population": "visible"}, ["gist-a", "gist-b"], "/gists"),
        ({"gist_population": "public"}, ["gist-a", "gist-c"], "/gists/public"),
        ({"gist_population": "starred"}, ["gist-b"], "/gists/starred"),
        ({"user": "gist-fixture-owner"}, ["gist-a", "gist-c"], "/users/gist-fixture-owner/gists"),
        ({"parent_gist_id": "gist-a"}, ["gist-c"], "/gists/gist-a/forks"),
        ({"gist_id": "gist-b"}, ["gist-b"], "/gists/gist-b"),
    ],
)
def test_gist_population_routes_hydrate_canonical_details(
    pilot, gists, monkeypatch, arguments, expected, endpoint
):
    _, contract, _ = pilot
    requests = install(monkeypatch, gists.respond)
    rows = rows_for(contract, "gists", **arguments)
    assert [row["gist_id"] for row in rows] == expected
    assert requests[0].url.path == endpoint
    assert rows[0]["node_id"] == "G-" + expected[0]
    for identity in expected:
        assert any(request.url.path == "/gists/" + identity for request in requests)
    if len(expected) > 1:
        assert any(request.url.params.get("page") == "2" for request in requests)


def test_population_typos_and_inapplicable_selectors_fail_before_http(pilot, gists, monkeypatch):
    _, contract, _ = pilot
    requests = install(monkeypatch, gists.respond)
    with pytest.raises(GeneratedContractError, match="enum|allowed"):
        rows_for(contract, "gists", gist_population="publci")
    with pytest.raises(GeneratedContractError, match="do not apply"):
        rows_for(contract, "gists", gist_id="gist-a", gist_population="public")
    assert requests == []


def test_gist_since_remains_typed_and_empty_listing_stays_empty(pilot, gists, monkeypatch):
    _, contract, _ = pilot
    requests = install(monkeypatch, gists.respond)
    assert rows_for(contract, "gists", gist_since=datetime(2027, 1, 1, tzinfo=UTC)) == []
    assert len(requests) == 1
    assert requests[0].url.params["since"].startswith("2027-01-01")


def test_gist_maps_keep_null_entries_truncation_and_raw_schema_dates(pilot, gists, monkeypatch):
    _, contract, _ = pilot
    install(monkeypatch, gists.respond)
    rows = rows_for(contract, "gists")
    files = dict(rows[0]["files"])
    assert files["gone.txt"] is None
    assert files["main.py"]["size"] == 5
    assert rows[0]["created_at_raw"] == "creation timestamp is unformatted in the pinned detail schema"
    assert rows[1]["truncated"] is True
    entries = rows_for(contract, "gist_files")
    assert [(row["gist_id"], row["filename"], row["byte_size"]) for row in entries] == [
        ("gist-a", "gone.txt", None),
        ("gist-a", "main.py", 5),
        ("gist-b", "README", 4),
    ]
    assert entries[0]["file"] is None
    assert entries[2]["content"] == "ab"
    assert entries[2]["truncated"] is True
    assert rows_for(contract, "gist_files", parent_gist_id="gist-a") == []


def test_comments_are_parent_qualified_and_retain_missing_authors(pilot, gists, monkeypatch):
    _, contract, _ = pilot
    install(monkeypatch, gists.respond)
    rows = rows_for(contract, "gist_comments")
    assert [(row["gist_id"], row["gist_comment_id"], row["author_id"]) for row in rows] == [
        ("gist-a", 1, 5100),
        ("gist-a", 2, None),
        ("gist-b", 1, 5100),
    ]
    assert rows_for(contract, "gist_comments", gist_id="gist-a", gist_comment_id=2) == [rows[1]]
    assert len(rows_for(contract, "gist_comments", user="gist-fixture-owner")) == 2


def test_observed_files_and_revisions_preserve_unreported_measurements(pilot, gists, monkeypatch):
    _, contract, _ = pilot
    install(monkeypatch, gists.respond)
    files = rows_for(contract, "gist_files", gist_id="gist-unknown")
    assert [(row["filename"], row["byte_size"]) for row in files] == [
        ("missing-size.txt", None),
        ("unavailable.txt", None),
    ]
    assert files[0]["content"] == "Available content does not supply the omitted byte-size measurement."
    assert files[1]["file"] is None
    revisions = rows_for(contract, "gist_revisions", gist_id="gist-unknown")
    assert [(row["revision_sha"], row["additions"], row["deletions"]) for row in revisions] == [
        ("e" * 40, None, None)
    ]
    assert rows_for(contract, "gist_files", gist_id="gist-c") == []
    assert rows_for(contract, "gist_revisions", gist_id="gist-c") == []


def test_revisions_keep_exact_sha_files_and_commit_metrics(pilot, gists, monkeypatch):
    _, contract, _ = pilot
    requests = install(monkeypatch, gists.respond)
    rows = rows_for(contract, "gist_revisions")
    assert [(row["gist_id"], row["revision_sha"], row["additions"], row["deletions"]) for row in rows] == [
        ("gist-a", "a" * 40, 10, 2),
        ("gist-a", "b" * 40, 3, 1),
        ("gist-b", "c" * 40, 4, 0),
    ]
    assert rows[1]["committer_id"] is None
    assert dict(rows[1]["files"])["main.py"]["size"] == 2
    requests.clear()
    selected = rows_for(contract, "gist_revisions", gist_id="gist-a", gist_revision="b" * 40)
    assert selected == [rows[1]]
    assert not any(request.url.path.endswith("/" + "a" * 40) for request in requests)
    assert any(request.url.params.get("page") == "2" for request in requests)
    assert rows_for(contract, "gist_revisions", gist_id="gist-a", gist_revision="d" * 40) == []


def test_star_status_does_not_require_existence_and_keeps_caller_identity(pilot, gists, monkeypatch):
    _, contract, _ = pilot
    requests = install(monkeypatch, gists.respond)
    assert rows_for(contract, "gist_star_observations", gist_id="gist-b") == [
        {"gist_id": "gist-b", "caller_id": 903, "status_code": 204, "caller_login": "package-fixture-current"}
    ]
    assert rows_for(contract, "gist_star_observations", gist_id="gist-missing")[0]["status_code"] == 404
    assert not any(request.url.path == "/gists/gist-missing" for request in requests)


@pytest.mark.parametrize("failure", ["later_page", "lookup", "identity", "missing_files", "wrong_size"])
def test_partial_or_invalid_gist_populations_fail(pilot, gists, monkeypatch, failure):
    _, contract, _ = pilot

    def handler(request):
        if failure == "later_page" and request.url.path == "/gists" and request.url.params.get("page") == "2":
            return httpx.Response(403, json={"message": "Forbidden"})
        if request.url.path == "/gists/gist-b":
            if failure == "lookup":
                return httpx.Response(404, json={"message": "Not Found"})
            row = deepcopy(gists.GISTS["gist-b"])
            if failure == "identity":
                row["id"] = "other"
            elif failure == "missing_files":
                row.pop("files")
            elif failure == "wrong_size":
                row["files"]["README"]["size"] = "4"
            return httpx.Response(200, json=row)
        return gists.respond(request)

    install(monkeypatch, handler)
    with pytest.raises((GeneratedContractError, GitHubError)):
        rows_for(contract, "gist_files" if failure == "missing_files" else "gists")


def test_public_feed_ceiling_is_not_reported_as_complete(pilot, gists, monkeypatch):
    _, original, _ = pilot
    contract = deepcopy(original)
    source = next(row for row in contract["entities"] if row["name"] == "gist_public_list_source")
    assert source["transport"]["pagination"]["reject_at_rows"] == 3000
    source["transport"]["pagination"]["reject_at_rows"] = 2
    install(monkeypatch, gists.respond)
    with pytest.raises(GeneratedContractError, match="completeness boundary"):
        rows_for(contract, "gists", gist_population="public")
