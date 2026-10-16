"""Spaces preserve owner-qualified navigation, typed metadata and actor identity."""

from copy import deepcopy

import pytest

from tests.helpers import install
from tests.test_generated_runtime import run
from tests.test_generation_artifacts import ROOT
from tests.test_generation_artifacts import pilot as pilot
from vgi_github.generated_runtime import GeneratedContractError

OWNER = "copilot-space-fixture"
USER = "copilot-space-alice"


@pytest.fixture
def spaces(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "tests/crossfield"))
    import copilot_spaces_fixture

    return copilot_spaces_fixture


def rows_for(contract, name, **arguments):
    entity = next(row for row in contract["functions"] if row["name"] == name)
    result = run(entity, {key: [value] for key, value in arguments.items()}, contract=contract)
    return [row for batch in result.batches for row in batch.to_pylist()]


def test_owner_routes_preserve_global_space_identity_and_cursor_pages(pilot, spaces, monkeypatch):
    _, contract, _ = pilot
    requests = install(monkeypatch, spaces.respond)
    org = rows_for(contract, "copilot_spaces", organization=OWNER)
    personal = rows_for(contract, "copilot_spaces", user=USER)
    assert [(r["space_id"], r["space_number"], r["space_owner_kind"]) for r in org + personal] == [
        (61001, 1, "organization"),
        (61002, 2, "organization"),
        (61003, 1, "user"),
    ]
    assert rows_for(contract, "copilot_spaces", organization=OWNER, copilot_space_number=1) == org[:1]
    assert rows_for(contract, "copilot_spaces", user=USER, copilot_space_number=1) == personal
    assert any(r.url.params.get("after") == "2" for r in requests)
    assert org[0]["creator_id"] == 68101 and org[0]["space_owner_id"] == 61000
    assert org[0]["owner"]["variant_1"]["id"] == 61000
    assert org[0]["owner"]["variant_2"]["id"] == 61000
    assert personal[0]["owner"]["variant_2"] is None


def test_inline_resource_metadata_keeps_all_declared_typed_properties(pilot, spaces, monkeypatch):
    _, contract, _ = pilot
    install(monkeypatch, spaces.respond)
    row = rows_for(contract, "copilot_spaces", organization=OWNER, copilot_space_number=1)[0]
    repo, text = row["resources_attributes"]
    assert repo["metadata"]["repository_id"] == 64001 and repo["metadata"]["name"] == "alpha"
    assert text["metadata"]["text"] == "Independent fixture text"
    assert repo["metadata"]["height"] is None and repo["metadata"]["width"] is None
    # Standalone arbitrary metadata and Team.parent remain explicit typed-coverage gaps.
    assert "extra_shape" not in repo["metadata"]


def test_resource_lookup_parent_and_owner_routes_keep_one_grain(pilot, spaces, monkeypatch):
    _, contract, _ = pilot
    requests = install(monkeypatch, spaces.respond)
    rows = rows_for(contract, "copilot_space_resources", organization=OWNER)
    assert [(r["space_id"], r["resource_id"], r["resource_type"]) for r in rows] == [
        (61001, 63001, "repository"),
        (61001, 63002, "free_text"),
    ]
    assert rows_for(contract, "copilot_space_resources", organization=OWNER, copilot_space_number=1) == rows
    assert (
        rows_for(
            contract,
            "copilot_space_resources",
            organization=OWNER,
            copilot_space_number=1,
            copilot_space_resource_id=63001,
        )
        == rows[:1]
    )
    assert rows_for(contract, "copilot_space_resources", organization=OWNER, copilot_space_number=2) == []
    personal = rows_for(contract, "copilot_space_resources", user=USER)
    assert [(r["space_id"], r["resource_id"]) for r in personal] == [(61003, 63003)]
    assert (
        rows_for(
            contract,
            "copilot_space_resources",
            user=USER,
            copilot_space_number=1,
            copilot_space_resource_id=63003,
        )
        == personal
    )
    assert any(r.url.path.endswith("/resources") and r.url.params.get("after") == "2" for r in requests)


def test_collaborators_qualify_user_and_team_ids_and_keep_typed_roles(pilot, spaces, monkeypatch):
    _, contract, _ = pilot
    install(monkeypatch, spaces.respond)
    rows = rows_for(contract, "copilot_space_collaborators", organization=OWNER)
    assert [(r["space_id"], r["actor_type"], r["collaborator_id"], r["role"]) for r in rows] == [
        (61001, "User", 68101, "writer"),
        (61001, "Team", 68101, "reader"),
    ]
    assert rows[0]["collaborator"]["variant_1"]["login"] == USER
    assert rows[1]["collaborator"]["variant_2"]["slug"] == "reviewers"
    assert rows[1]["collaborator"]["variant_2"]["organization_id"] == 61000
    assert (
        rows_for(contract, "copilot_space_collaborators", organization=OWNER, copilot_space_number=1) == rows
    )
    personal = rows_for(contract, "copilot_space_collaborators", user=USER)
    assert [(r["space_id"], r["actor_type"], r["collaborator_id"], r["role"]) for r in personal] == [
        (61003, "User", 68102, "admin")
    ]


def test_lookup_resource_identity_is_asserted(pilot, spaces, monkeypatch):
    _, contract, _ = pilot
    rows = deepcopy(spaces.RESOURCES[(OWNER, 1)])

    def wrong_resource(request):
        result = spaces.respond(request)
        if request.url.path.endswith("/resources/63001"):
            import httpx

            return httpx.Response(200, json=rows[1], request=request)
        return result

    install(monkeypatch, wrong_resource)
    with pytest.raises(GeneratedContractError, match="resource_id"):
        rows_for(
            contract,
            "copilot_space_resources",
            organization=OWNER,
            copilot_space_number=1,
            copilot_space_resource_id=63001,
        )


@pytest.mark.parametrize(
    "name,arguments",
    [
        ("copilot_spaces", {}),
        ("copilot_spaces", {"organization": OWNER, "user": USER}),
        ("copilot_spaces", {"copilot_space_number": 1}),
        ("copilot_space_resources", {"organization": OWNER, "copilot_space_resource_id": 63001}),
        ("copilot_space_collaborators", {"user": USER, "copilot_space_number": 0}),
    ],
)
def test_ambiguous_or_incomplete_owner_scope_rejected_before_http(
    pilot, spaces, monkeypatch, name, arguments
):
    _, contract, _ = pilot
    requests = install(monkeypatch, spaces.respond)
    with pytest.raises(GeneratedContractError):
        rows_for(contract, name, **arguments)
    assert requests == []
