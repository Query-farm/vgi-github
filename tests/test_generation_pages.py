"""Pages site/build identities and alternate retrieval populations are explicit."""

import json
from datetime import date

import httpx
import pytest

from tests.helpers import install
from tests.test_generated_runtime import run
from tests.test_generation_artifacts import ROOT
from tests.test_generation_artifacts import pilot as pilot
from vgi_github.generated_runtime import GeneratedContractError
from vgi_github.github_api import GitHubError


@pytest.fixture
def pages(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "tests/crossfield"))
    import pages_fixture

    return pages_fixture


def rows_for(contract, name, **arguments):
    entity = next(value for value in contract["functions"] if value["name"] == name)
    output = run(entity, {key: [value] for key, value in arguments.items()}, contract=contract)
    return [row for batch in output.batches for row in batch.to_pylist()]


def test_pages_selects_four_read_operations_without_health_side_effect():
    domain = json.loads((ROOT / "generation/domains/pages.json").read_text())
    assert {source["transport"]["operation_id"] for source in domain["entities"]} == {
        "repos/get-pages",
        "repos/list-pages-builds",
        "repos/get-latest-pages-build",
        "repos/get-pages-build",
    }
    assert {entity["name"] for entity in domain["functions"]} == {"pages_sites", "pages_builds"}
    assert next(entity for entity in domain["functions"] if entity["name"] == "pages_builds")["grain"] == [
        "repository_id",
        "build_url",
    ]
    assert len(domain["relationships"]) == 5


def test_pages_sites_keep_typed_certificate_and_separate_site_visibility(pilot, pages, monkeypatch):
    _, contract, _ = pilot
    install(monkeypatch, pages.respond)
    rows = rows_for(contract, "pages_sites", organization="pages-fixture")
    assert [(row["repository_id"], row["status"], row["build_type"], row["public"]) for row in rows] == [
        (6401, "built", "legacy", True),
        (6402, "building", "workflow", False),
    ]
    assert rows[0]["https_certificate"]["expires_at"] == date(2027, 1, 1)
    assert rows[0]["https_certificate"]["domains"] == ["pages.example.invalid"]
    assert rows[1]["cname"] is None
    assert rows_for(contract, "pages_sites", owner="pages-fixture") == rows


def test_build_list_latest_and_exact_id_share_response_url_identity(pilot, pages, monkeypatch):
    _, contract, _ = pilot
    requests = install(monkeypatch, pages.respond)
    all_rows = rows_for(contract, "pages_builds", organization="pages-fixture")
    assert [row["build_url"].rsplit("/", 1)[-1] for row in all_rows] == ["103", "102", "101", "201"]
    assert sum(row["reported_duration"] for row in all_rows) == 90
    assert all_rows[0]["pusher_id"] is None
    assert rows_for(
        contract, "pages_builds", organization="pages-fixture", pages_build_population="latest"
    ) == [all_rows[0], all_rows[3]]
    assert rows_for(contract, "pages_builds", repository="pages-fixture/alpha", pages_build_id=102) == [
        all_rows[1]
    ]
    assert rows_for(contract, "pages_builds", owner="pages-fixture", pages_build_population="all") == all_rows
    assert any(
        request.url.path.endswith("/builds") and request.url.params.get("page") == "3" for request in requests
    )
    assert any(request.url.path.endswith("/builds/latest") for request in requests)
    assert all(request.url.host == "api.github.com" for request in requests)


def test_pages_repository_cohort_preserves_scope_and_empty_result(pilot, pages, monkeypatch):
    _, contract, _ = pilot
    requests = install(monkeypatch, pages.respond)
    assert rows_for(contract, "pages_builds", repositories=[]) == []
    assert requests == []
    rows = rows_for(
        contract,
        "pages_builds",
        repositories=[{"repository": "pages-fixture/alpha"}, {"repository": "pages-fixture/beta"}],
        pages_build_population="latest",
    )
    assert [row["repository_id"] for row in rows] == [6401, 6402]


@pytest.mark.parametrize("failure", ["later_page", "missing_site", "missing_build", "null_pusher_id"])
def test_pages_missing_or_invalid_data_never_claims_complete_success(pilot, pages, monkeypatch, failure):
    _, contract, _ = pilot

    def handler(request):
        if (
            failure == "later_page"
            and request.url.path.endswith("/builds")
            and request.url.params.get("page") == "2"
        ):
            return httpx.Response(403, json={"message": "Forbidden"})
        if failure == "missing_site" and request.url.path.endswith("/pages"):
            return httpx.Response(404, json={"message": "Not Found"})
        if failure == "null_pusher_id" and request.url.path.endswith("/builds/102"):
            row = dict(pages.BUILDS["alpha"][1])
            row["pusher"] = dict(row["pusher"], id="6450")
            return httpx.Response(200, json=row)
        return pages.respond(request)

    install(monkeypatch, handler)
    with pytest.raises((GeneratedContractError, GitHubError)):
        rows_for(
            contract,
            "pages_sites" if failure == "missing_site" else "pages_builds",
            repository="pages-fixture/alpha",
            **(
                {"pages_build_id": 999}
                if failure == "missing_build"
                else {"pages_build_id": 102}
                if failure == "null_pusher_id"
                else {}
            ),
        )
