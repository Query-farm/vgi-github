"""Organization identity, active/pending memberships and visibility checks."""

import json

import httpx
import pytest

from tests.helpers import install
from tests.test_generated_runtime import run
from tests.test_generation_artifacts import ROOT
from tests.test_generation_artifacts import pilot as pilot
from vgi_github.generated_runtime import GeneratedContractError


@pytest.fixture
def memberships(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "tests/crossfield"))
    import organization_identity_fixture

    return organization_identity_fixture


def rows_for(contract, name, **arguments):
    entity = next(f for f in contract["functions"] if f["name"] == name)
    output = run(entity, {k: [v] for k, v in arguments.items()}, contract=contract)
    return [row for batch in output.batches for row in batch.to_pylist()]


@pytest.mark.parametrize(
    "name,arguments,key,expected",
    [
        ("organizations", {"organization_directory": True}, "organization_id", [3101, 3102, 3103]),
        (
            "organizations",
            {"organization_directory": True, "organization_since_id": 3101},
            "organization_id",
            [3102, 3103],
        ),
        ("organizations", {"authenticated_user": True}, "organization_id", [3101]),
        (
            "organization_memberships",
            {"organization": "membership-fixture-alpha"},
            "user_id",
            [903, 3001, 3002],
        ),
        (
            "organization_memberships",
            {"organization": "membership-fixture-alpha", "organization_public_members": True},
            "user_id",
            [3001],
        ),
        ("organization_memberships", {"user": "membership-alice"}, "organization_id", [3101]),
        ("organization_memberships", {"user": "membership-bob"}, "organization_id", []),
        (
            "organization_memberships",
            {"organization": "membership-fixture-alpha", "membership_user": "membership-alice"},
            "membership_state",
            ["active"],
        ),
        (
            "organization_memberships",
            {"organization": "membership-fixture-alpha", "membership_user": "membership-carol"},
            "membership_state",
            ["pending"],
        ),
        ("organization_memberships", {"authenticated_user": True}, "membership_state", ["active", "pending"]),
        (
            "organization_memberships",
            {"authenticated_user": True, "organization_membership_state": "pending"},
            "organization_id",
            [3102],
        ),
        (
            "organization_memberships",
            {"authenticated_user": True, "organization": "membership-fixture-beta"},
            "membership_state",
            ["pending"],
        ),
        (
            "organization_memberships",
            {
                "authenticated_user": True,
                "organization": "membership-fixture-beta",
                "organization_membership_state": "active",
            },
            "membership_state",
            [],
        ),
        ("organization_memberships", {"organization": "membership-fixture-empty"}, "user_id", []),
        (
            "organization_membership_checks",
            {
                "organization": "membership-fixture-alpha",
                "membership_user": "membership-alice",
                "organization_membership_check": "visible",
            },
            "status_code",
            [204],
        ),
        (
            "organization_membership_checks",
            {
                "organization": "membership-fixture-alpha",
                "membership_user": "membership-alice",
                "organization_membership_check": "public",
            },
            "status_code",
            [204],
        ),
        (
            "organization_membership_checks",
            {
                "organization": "membership-fixture-alpha",
                "membership_user": "membership-bob",
                "organization_membership_check": "visible",
            },
            "status_code",
            [204],
        ),
        (
            "organization_membership_checks",
            {
                "organization": "membership-fixture-alpha",
                "membership_user": "membership-bob",
                "organization_membership_check": "public",
            },
            "status_code",
            [404],
        ),
    ],
)
def test_organization_routes_preserve_distinct_membership_populations(
    pilot, memberships, monkeypatch, name, arguments, key, expected
):
    _, contract, _ = pilot
    install(monkeypatch, memberships.respond_all)
    assert [r[key] for r in rows_for(contract, name, **arguments)] == expected


def test_auth_membership_canonical_identity_and_optional_observed_user(pilot, memberships, monkeypatch):
    _, contract, _ = pilot
    install(monkeypatch, memberships.respond_all)
    all_auth = rows_for(contract, "organization_memberships", authenticated_user=True)
    exact = rows_for(
        contract, "organization_memberships", authenticated_user=True, organization="membership-fixture-beta"
    )
    assert exact == all_auth[1:]
    assert exact[0]["user_id"] == 903 and exact[0]["observed_member_id"] == 903
    bob = rows_for(
        contract,
        "organization_memberships",
        organization="membership-fixture-alpha",
        membership_user="membership-bob",
    )[0]
    assert bob["user_id"] == 3002 and bob["member_login"] == "membership-bob"
    assert bob["observed_member_id"] is None and bob["observed_member_login"] is None
    assert bob["membership_role"] == "admin" and bob["direct_membership"] is False
    assert bob["enterprise_team_slugs"] == ["ent:security", "ent:reviewers"]
    assert bob["can_create_repository"] is True


def test_summary_endpoints_establish_active_state_without_inventing_object_metadata(
    pilot, memberships, monkeypatch
):
    _, contract, _ = pilot
    install(monkeypatch, memberships.respond_all)
    rows = rows_for(contract, "organization_memberships", organization="membership-fixture-alpha")
    assert all(r["membership_state"] == "active" for r in rows)
    assert all(r["membership_role"] is None and r["direct_membership"] is None for r in rows)
    assert all(r["enterprise_team_slugs"] is None for r in rows)
    reverse = rows_for(contract, "organization_memberships", user="membership-alice")
    assert [(r["organization_id"], r["user_id"]) for r in reverse] == [(3101, 3001)]
    assert reverse[0]["membership_state"] == "active" and reverse[0]["membership_role"] is None


def test_directory_hydration_preserves_stable_identity_and_since_pagination(pilot, memberships, monkeypatch):
    _, contract, _ = pilot
    requests = install(monkeypatch, memberships.respond_all)
    rows = rows_for(contract, "organizations", organization_directory=True)
    assert len(rows) == 3
    assert [r.url.params.get("since") for r in requests if r.url.path == "/organizations"] == [
        None,
        "3101",
        "3102",
    ]
    assert rows_for(contract, "organizations", organization="membership-fixture-alpha") == rows[:1]


def test_visible_membership_redirect_to_public_check_retains_unconfirmed_visibility(
    pilot, memberships, monkeypatch
):
    _, contract, _ = pilot
    requests = install(monkeypatch, memberships.respond_all)
    rows = rows_for(
        contract,
        "organization_membership_checks",
        organization="membership-fixture-alpha",
        membership_user="membership-carol",
        organization_membership_check="visible",
    )
    assert rows[0]["status_code"] == 404 and rows[0]["check_kind"] == "visible"
    assert any(r.url.path.endswith("/members/membership-carol") for r in requests)
    assert any(r.url.path.endswith("/public_members/membership-carol") for r in requests)


def test_redirect_can_confirm_public_membership(pilot, memberships, monkeypatch):
    _, contract, _ = pilot

    def respond(request):
        if request.url.path.endswith("/members/membership-alice"):
            return httpx.Response(
                302,
                headers={
                    "Location": "https://api.github.com/orgs/membership-fixture-alpha/public_members/membership-alice"
                },
                request=request,
            )
        return memberships.respond_all(request)

    install(monkeypatch, respond)
    rows = rows_for(
        contract,
        "organization_membership_checks",
        organization="membership-fixture-alpha",
        membership_user="membership-alice",
        organization_membership_check="visible",
    )
    assert rows[0]["status_code"] == 204


@pytest.mark.parametrize("code", [200, 403])
def test_unexpected_check_response_is_not_a_valid_membership_observation(
    pilot, memberships, monkeypatch, code
):
    _, contract, _ = pilot

    def respond(request):
        if request.url.path.endswith("/members/membership-alice"):
            return httpx.Response(code, text="Unexpected response", request=request)
        return memberships.respond_all(request)

    install(monkeypatch, respond)
    with pytest.raises(Exception, match="200|403|unexpected|Unexpected"):
        rows_for(
            contract,
            "organization_membership_checks",
            organization="membership-fixture-alpha",
            membership_user="membership-alice",
            organization_membership_check="visible",
        )


@pytest.mark.parametrize("kind", ["organization", "member"])
def test_membership_identity_mismatch_fails(pilot, memberships, monkeypatch, kind):
    _, contract, _ = pilot

    def respond(request):
        result = memberships.respond_all(request)
        if request.url.path.endswith("/memberships/membership-alice"):
            body = result.json()
            body["organization" if kind == "organization" else "user"]["id"] = 9999
            return httpx.Response(200, json=body, headers=result.headers, request=request)
        return result

    install(monkeypatch, respond)
    with pytest.raises(GeneratedContractError, match="row assertion"):
        rows_for(
            contract,
            "organization_memberships",
            organization="membership-fixture-alpha",
            membership_user="membership-alice",
        )


def test_capped_enterprise_team_metadata_is_preserved_without_claiming_exhaustiveness(
    pilot, memberships, monkeypatch
):
    _, contract, _ = pilot

    def respond(request):
        result = memberships.respond_all(request)
        if request.url.path.endswith("/memberships/membership-alice"):
            body = result.json()
            body["enterprise_teams_providing_indirect_membership"] = [f"ent:team-{i}" for i in range(100)]
            return httpx.Response(200, json=body, headers=result.headers, request=request)
        return result

    install(monkeypatch, respond)
    rows = rows_for(
        contract,
        "organization_memberships",
        organization="membership-fixture-alpha",
        membership_user="membership-alice",
    )
    assert len(rows[0]["enterprise_team_slugs"]) == 100
    assert rows[0]["enterprise_team_slugs"][-1] == "ent:team-99"
    entity = next(f for f in contract["functions"] if f["name"] == "organization_memberships")
    assert "capped at 100" in entity["description"]


def test_exact_missing_affiliation_fails_instead_of_empty_membership(pilot, memberships, monkeypatch):
    _, contract, _ = pilot
    install(monkeypatch, memberships.respond_all)
    with pytest.raises(Exception, match="404"):
        rows_for(
            contract,
            "organization_memberships",
            authenticated_user=True,
            organization="membership-fixture-empty",
        )


def test_auth_membership_later_page_failure_does_not_report_complete_population(
    pilot, memberships, monkeypatch
):
    _, contract, _ = pilot

    def respond(request):
        if request.url.path == "/user/memberships/orgs" and request.url.params.get("page") == "2":
            return httpx.Response(403, json={"message": "Membership page denied"}, request=request)
        return memberships.respond_all(request)

    install(monkeypatch, respond)
    with pytest.raises(Exception, match="403|denied"):
        rows_for(contract, "organization_memberships", authenticated_user=True)


@pytest.mark.parametrize(
    "name,args",
    [
        ("organizations", {"organization_directory": True, "organization": "membership-fixture-alpha"}),
        (
            "organization_memberships",
            {
                "organization": "membership-fixture-alpha",
                "organization_public_members": True,
                "membership_user": "membership-alice",
            },
        ),
        (
            "organization_memberships",
            {
                "organization": "membership-fixture-alpha",
                "membership_user": "membership-alice",
                "authenticated_user": True,
            },
        ),
        (
            "organization_memberships",
            {"authenticated_user": True, "organization_membership_state": "disabled"},
        ),
        (
            "organization_membership_checks",
            {
                "organization": "membership-fixture-alpha",
                "membership_user": "membership-alice",
                "organization_membership_check": "all",
            },
        ),
    ],
)
def test_conflicting_populations_reject_before_http(pilot, memberships, monkeypatch, name, args):
    _, contract, _ = pilot
    requests = install(monkeypatch, memberships.respond_all)
    with pytest.raises(GeneratedContractError, match="argument|population|enum|value|route"):
        rows_for(contract, name, **args)
    assert requests == []


def test_new_org_operations_extend_canonical_entities_without_duplicate_memberships():
    domain = json.loads((ROOT / "generation/domains/organization_identity.json").read_text())
    assert [f["name"] for f in domain["functions"]] == ["organization_membership_checks"]
    assert {s["transport"]["operation_id"] for s in domain["entities"]} == {
        "orgs/list",
        "orgs/list-for-authenticated-user",
        "orgs/get",
        "orgs/list-members",
        "orgs/list-public-members",
        "orgs/list-for-user",
        "users/get-by-username",
        "orgs/get-membership-for-user",
        "orgs/get-membership-for-authenticated-user",
        "orgs/list-memberships-for-authenticated-user",
        "orgs/check-membership-for-user",
        "orgs/check-public-membership-for-user",
    }
