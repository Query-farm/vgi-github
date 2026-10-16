"""Canonical release/asset populations across independent API retrieval routes."""

from copy import deepcopy

import httpx
import pytest

from tests.helpers import install
from tests.test_functions import _Out
from tests.test_generated_runtime import run
from tests.test_generation_artifacts import ROOT
from tests.test_generation_artifacts import pilot as pilot
from vgi_github.generated_runtime import GeneratedContractError
from vgi_github.github_api import GitHubError


@pytest.fixture
def releases_api(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "tests/crossfield"))
    import releases_fixture

    return releases_fixture


def rows_for(contract, name, **arguments):
    entity = next(value for value in contract["functions"] if value["name"] == name)
    output = run(entity, {key: [value] for key, value in arguments.items()}, contract=contract)
    return [row for batch in output.batches for row in batch.to_pylist()]


@pytest.mark.parametrize(
    "selection", [{"release_id": 11}, {"release_tag": "v1"}, {"release_selection": "latest"}]
)
def test_release_id_tag_latest_preserve_canonical_identity(pilot, releases_api, monkeypatch, selection):
    _, contract, _ = pilot
    requests = install(monkeypatch, releases_api.respond)
    repository_rows = rows_for(contract, "releases", repository="release-fixture/alpha")
    assert [row["release_id"] for row in repository_rows] == [13, 12, 11]
    direct = rows_for(contract, "releases", repository="release-fixture/alpha", **selection)
    assert direct == [repository_rows[2]]
    assert all(request.method == "GET" for request in requests)


def test_repository_cohort_preserves_release_identity_and_publication_state(pilot, releases_api, monkeypatch):
    _, contract, _ = pilot
    requests = install(monkeypatch, releases_api.respond)
    rows = rows_for(contract, "releases", organization="release-fixture")
    assert [(row["repository_id"], row["release_id"]) for row in rows] == [
        (101, 13),
        (101, 12),
        (101, 11),
        (102, 21),
    ]
    assert [(row["draft"], row["prerelease"], row["published_at"] is None) for row in rows] == [
        (True, False, True),
        (False, True, False),
        (False, False, False),
        (False, False, False),
    ]
    assert sum(request.url.path == "/orgs/release-fixture/repos" for request in requests) == 3
    assert sum(request.url.path == "/repos/release-fixture/alpha/releases" for request in requests) == 3
    assert rows_for(contract, "releases", repositories=[]) == []
    assert rows_for(contract, "releases", repository="release-fixture/empty") == []


@pytest.mark.parametrize(
    "selection", [{"release_id": 11}, {"release_tag": "v1"}, {"release_selection": "latest"}]
)
def test_asset_routes_follow_all_asset_pages_not_embedded_assets(pilot, releases_api, monkeypatch, selection):
    _, contract, _ = pilot
    requests = install(monkeypatch, releases_api.respond)
    rows = rows_for(contract, "release_assets", repository="release-fixture/alpha", **selection)
    assert [(row["release_id"], row["release_asset_id"]) for row in rows] == [(11, 111), (11, 112)]
    assert [(row["uploader_id"], row["uploader_login"]) for row in rows] == [(202, "bob"), (None, None)]
    assert (
        sum(request.url.path == "/repos/release-fixture/alpha/releases/11/assets" for request in requests)
        == 2
    )


def test_asset_lookup_keeps_unknown_parent_without_inventing_relationship(pilot, releases_api, monkeypatch):
    _, contract, _ = pilot
    requests = install(monkeypatch, releases_api.respond)
    listed = rows_for(contract, "release_assets", repository="release-fixture/alpha", release_id=11)[0]
    requests.clear()
    direct = rows_for(contract, "release_assets", repository="release-fixture/alpha", release_asset_id=111)
    assert direct == [{**listed, "release_id": None}]
    assert [request.url.path for request in requests] == [
        "/repos/release-fixture/alpha",
        "/repos/release-fixture/alpha/releases/assets/111",
    ]


def test_asset_repository_population_preserves_grain_state_and_counters(pilot, releases_api, monkeypatch):
    _, contract, _ = pilot
    install(monkeypatch, releases_api.respond)
    rows = rows_for(contract, "release_assets", owner="release-fixture")
    assert [(row["repository_id"], row["release_asset_id"]) for row in rows] == [
        (101, 121),
        (101, 111),
        (101, 112),
        (102, 211),
    ]
    assert [(row["state"], row["size_bytes"], row["download_count"]) for row in rows] == [
        ("open", 0, 0),
        ("uploaded", 100, 3),
        ("uploaded", 200, 5),
        ("uploaded", 400, 7),
    ]
    assert rows_for(contract, "release_assets", repository="release-fixture/alpha", release_id=13) == []


@pytest.mark.parametrize(
    "entity,arguments",
    [
        ("releases", {}),
        ("releases", {"release_id": 11}),
        ("releases", {"repository": "release-fixture/alpha", "release_id": 0}),
        ("releases", {"repository": "release-fixture/alpha", "release_id": 11, "release_tag": "v1"}),
        ("releases", {"repository": "release-fixture/alpha", "release_selection": "first"}),
        ("release_assets", {"release_asset_id": 111}),
        (
            "release_assets",
            {"repository": "release-fixture/alpha", "release_asset_id": 111, "release_id": 11},
        ),
        ("release_assets", {"repository": "release-fixture/alpha", "release_selection": "first"}),
    ],
)
def test_invalid_release_selections_fail_before_http(pilot, monkeypatch, entity, arguments):
    _, contract, _ = pilot
    requests = install(monkeypatch, lambda request: pytest.fail("Invalid input made an API request"))
    with pytest.raises(GeneratedContractError):
        rows_for(contract, entity, **arguments)
    assert requests == []


def test_asset_duplicate_identity_is_rejected_across_pages(pilot, releases_api, monkeypatch):
    _, contract, _ = pilot

    def respond(request):
        response = releases_api.respond(request)
        if request.url.path.endswith("/11/assets") and request.url.params.get("page") == "2":
            value = deepcopy(response.json())
            value[0]["id"] = 111
            return httpx.Response(200, json=value, headers=response.headers, request=request)
        return response

    install(monkeypatch, respond)
    with pytest.raises(GeneratedContractError, match="duplicate row identity"):
        rows_for(contract, "release_assets", repository="release-fixture/alpha", release_id=11)


def test_later_asset_page_failure_cannot_become_a_complete_population(pilot, releases_api, monkeypatch):
    _, contract, _ = pilot

    def respond(request):
        if request.url.path.endswith("/11/assets") and request.url.params.get("page") == "2":
            return httpx.Response(403, json={"message": "Asset page unavailable"}, request=request)
        return releases_api.respond(request)

    install(monkeypatch, respond)
    with pytest.raises(GitHubError, match="Asset page unavailable"):
        rows_for(contract, "release_assets", repository="release-fixture/alpha", release_id=11)


def test_release_relationship_roles_and_unknown_parent_are_explicit(pilot):
    _, contract, _ = pilot
    relationships = {value["name"]: value for value in contract["relationships"]}
    assert relationships["releases_to_publishers"]["from_columns"] == ["publisher_id"]
    assert relationships["release_assets_to_uploaders"]["from_columns"] == ["uploader_id"]
    parent = relationships["release_assets_to_releases"]
    assert parent["optional"] is True
    assert parent["analytical"] is False
    assert {value["direction"] for value in parent["retrievals"]} == {"forward", "reverse"}
    forward = next(value for value in parent["retrievals"] if value["direction"] == "forward")
    assert forward["when_not_null"] == ["release_id"]


def test_typed_release_snapshots_preserve_missing_versus_zero(pilot, releases_api, monkeypatch):
    _, contract, _ = pilot
    requests = install(monkeypatch, releases_api.respond)
    rows = rows_for(contract, "releases", repository="release-fixture/alpha")
    assert [(row["release_id"], row["mentions_count"], row["reaction_total_count"]) for row in rows] == [
        (13, None, None),
        (12, None, None),
        (11, 2, 3),
    ]
    assert rows[0]["reaction_summary"] is None
    assert rows[0]["body_html"] is None
    assert rows[2]["reaction_summary"]["+1"] == 2
    assert rows[2]["reaction_summary"]["heart"] == 1
    assert rows[2]["publisher"]["id"] == 201
    assert rows[2]["publisher"]["gravatar_id"] is None
    assert rows[2]["body_html"] == "<p>Independent release notes</p>"
    assert rows[2]["body_text"] == "Independent release notes"
    assert rows[2]["assets_url"].endswith("/11/assets")
    assert rows[2]["upload_url"].endswith("/11/assets{?name,label}")
    assert [request.url.path for request in requests] == [
        "/repos/release-fixture/alpha",
        "/repos/release-fixture/alpha/releases",
        "/repos/release-fixture/alpha/releases",
        "/repos/release-fixture/alpha/releases",
    ]
    zero = rows_for(contract, "releases", repository="release-fixture/beta")[0]
    assert zero["mentions_count"] == 0
    assert zero["reaction_total_count"] == 0
    assert zero["reaction_summary"]["total_count"] == 0


def test_typed_asset_uploader_retains_nullable_role(pilot, releases_api, monkeypatch):
    _, contract, _ = pilot
    install(monkeypatch, releases_api.respond)
    rows = rows_for(contract, "release_assets", repository="release-fixture/alpha", release_id=11)
    assert rows[0]["uploader"]["id"] == 202
    assert rows[0]["uploader"]["login"] == "bob"
    assert rows[0]["uploader"]["site_admin"] is False
    assert rows[1]["uploader"] is None


def test_repository_existing_response_exposes_node_identity_and_unknown_language(
    pilot, releases_api, monkeypatch
):
    _, contract, _ = pilot
    requests = install(monkeypatch, releases_api.respond)
    rows = rows_for(contract, "repositories", repository="release-fixture/alpha")
    assert [(row["repository_node_id"], row["repository_language"]) for row in rows] == [("R101", None)]
    assert [request.url.path for request in requests] == ["/repos/release-fixture/alpha"]


@pytest.mark.parametrize("nested", ["author", "reactions"])
def test_selected_required_snapshot_fields_are_not_silently_nullable(
    pilot, releases_api, monkeypatch, nested
):
    _, contract, _ = pilot

    def respond(request):
        response = releases_api.respond(request)
        if request.url.path.endswith("/releases/11"):
            value = deepcopy(response.json())
            del value[nested]["avatar_url" if nested == "author" else "heart"]
            return httpx.Response(200, json=value, headers=response.headers, request=request)
        return response

    install(monkeypatch, respond)
    with pytest.raises(GeneratedContractError, match="missing required"):
        rows_for(contract, "releases", repository="release-fixture/alpha", release_id=11)


@pytest.mark.parametrize(
    "entity,arguments,path,field,foreign_value",
    [
        ("releases", {"release_id": 11}, "/releases/11", "id", 12),
        ("releases", {"release_tag": "v1"}, "/releases/tags/v1", "tag_name", "V1"),
        ("release_assets", {"release_asset_id": 111}, "/releases/assets/111", "id", 112),
    ],
)
def test_lookup_rejects_mismatched_identity_before_emitting_rows(
    pilot, releases_api, monkeypatch, entity, arguments, path, field, foreign_value
):
    _, contract, _ = pilot

    def respond(request):
        response = releases_api.respond(request)
        if request.url.path.endswith(path):
            value = deepcopy(response.json())
            value[field] = foreign_value
            return httpx.Response(200, json=value, headers=response.headers, request=request)
        return response

    install(monkeypatch, respond)
    function = next(value for value in contract["functions"] if value["name"] == entity)
    inputs = {"repository": ["release-fixture/alpha"], **{key: [value] for key, value in arguments.items()}}
    output = _Out()
    with pytest.raises(GeneratedContractError, match="row assertion failed"):
        run(function, inputs, out=output, contract=contract)
    assert sum(batch.num_rows for batch in output.batches) == 0
